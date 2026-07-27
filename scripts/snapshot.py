#!/usr/bin/env python3
"""
Daily traffic snapshot for all public repos under herrrickshaw.

GitHub only retains 14 days of traffic/clones and traffic/views data, and
exposes no per-IP or per-origin breakdown (this is a hard platform limit, not
a filtering choice made here). This script runs daily to accumulate history
beyond that 14-day window into per-repo JSON files, upserting by date so
re-running never creates duplicate entries even though each API call returns
the last 14 days every time.
"""

import csv
import json
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
OWNER = "herrrickshaw"

# Local Claude Code session transcripts, used to detect the account owner's own
# clone activity. Never read for content — only for dates and repo names.
TRANSCRIPT_ROOT = Path.home() / ".claude" / "projects"
SELF_ACTIVITY_PATH = REPO_ROOT / "self_activity.json"
# Scan cache is kept OUT of git: its keys are local session paths and UUIDs.
# Only the derived dates/repos/counts are versioned. Rebuild with --rescan.
SELF_CACHE_PATH = REPO_ROOT / ".self_activity_cache.json"
HOME_REPO = "global-market-research-platform"  # $HOME itself is a working tree

CLONE_CMD = re.compile(r"\b(?:git\s+clone|gh\s+repo\s+clone)\b")
FETCH_CMD = re.compile(r"\bgit\s+(?:fetch|pull)\b")
HOME_CD = re.compile(r"cd\s+(?:\"?\$HOME\"?|~|/Users/[^/\s]+)(?=\s|$|&|;)")


def today():
    """UTC, to match the traffic API — its day buckets are UTC midnights.

    Stamping with local dates would key snapshots a day off whenever the run
    straddles the UTC boundary.
    """
    return datetime.now(UTC).date()


def gh_api(path):
    result = subprocess.run(
        ["gh", "api", path], capture_output=True, text=True, timeout=30, check=False
    )
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def list_public_repos():
    result = subprocess.run(
        ["gh", "repo", "list", OWNER, "--limit", "200", "--json", "name,visibility"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    data = json.loads(result.stdout)
    return sorted(
        r["name"]
        for r in data
        if r["visibility"] == "PUBLIC" and not r["name"].endswith("-archive-2026-07-17")
    )


def load_repo_data(name):
    f = DATA_DIR / f"{name}.json"
    if f.exists():
        data = json.loads(f.read_text())
        # period_totals was added later; older files predate it
        data.setdefault("period_totals", {})
        return data
    return {"clones": {}, "views": {}, "releases": {}, "period_totals": {}}


def save_repo_data(name, data):
    f = DATA_DIR / f"{name}.json"
    f.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def upsert_series(existing, incoming_points, key_field="timestamp"):
    for point in incoming_points:
        date = point[key_field][:10]
        existing[date] = {"count": point["count"], "uniques": point["uniques"]}
    return existing


def snapshot_releases(name, data):
    releases = gh_api(f"repos/{OWNER}/{name}/releases")
    if not releases:
        return data
    today_total = sum(
        asset.get("download_count", 0)
        for rel in releases
        for asset in rel.get("assets", [])
    )
    data["releases"][str(today())] = today_total
    return data


def record_period_totals(data, clones, views):
    """Store GitHub's own 14-day deduplicated totals.

    The daily series counts uniques per day, so summing it across days
    double-counts anyone who returns on a later day. The top-level `uniques`
    on each traffic endpoint is deduplicated across the whole trailing 14-day
    window, which is the only honest "how many distinct people" figure GitHub
    gives us. Keyed by snapshot date = the day that window ends.
    """
    entry = {}
    for label, payload in (("clones", clones), ("views", views)):
        if payload and "uniques" in payload:
            entry[label] = {
                "count": payload.get("count", 0),
                "uniques": payload.get("uniques", 0),
            }
    if entry:
        data["period_totals"][str(today())] = entry
    return data


def _repos_in_command(cmd, known):
    """Which tracked repos a shell command touches.

    Matched against the real repo list rather than a loose pattern, so short
    names can't produce phantom hits. Falls back to the $HOME repo for a bare
    `cd ~ && git fetch`, which is how the home working tree gets updated.
    """
    hits = {r for r in known if re.search(rf"(?:^|[/\s'\"]){re.escape(r)}(?:\.git)?(?:$|[/\s'\";&)])", cmd)}
    if not hits and HOME_CD.search(cmd) and HOME_REPO in known:
        hits.add(HOME_REPO)
    return hits


def _scan_transcript(path, known):
    """Extract {date: {repo: {clone,fetch}}} plus unattributed counts."""
    days = {}
    try:
        with path.open(errors="replace") as fh:
            for line in fh:
                if "clone" not in line and "fetch" not in line and "pull" not in line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = rec.get("timestamp")
                content = (rec.get("message") or {}).get("content")
                if not ts or not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "tool_use":
                        continue
                    cmd = (block.get("input") or {}).get("command")
                    if not isinstance(cmd, str):
                        continue
                    is_clone = bool(CLONE_CMD.search(cmd))
                    is_fetch = bool(FETCH_CMD.search(cmd))
                    if not (is_clone or is_fetch):
                        continue
                    day = days.setdefault(ts[:10], {"repos": {}, "unattributed": 0})
                    touched = _repos_in_command(cmd, known)
                    if not touched:
                        day["unattributed"] += 1
                    for r in touched:
                        e = day["repos"].setdefault(r, {"clone": 0, "fetch": 0})
                        e["clone"] += int(is_clone)
                        e["fetch"] += int(is_fetch and not is_clone)
    except OSError:
        return {}
    return days


def scan_self_activity(known, rescan=False):
    """Build {date: {repo: {...}}} of the owner's own clone/fetch commands.

    Cached per transcript file and keyed by mtime, so a weekly run only parses
    sessions that changed. Sessions are append-only while live, hence replacing
    a file's whole contribution on reparse rather than accumulating counts.
    """
    cache = {"by_file": {}, "scanned_through": 0.0}
    if SELF_CACHE_PATH.exists() and not rescan:
        try:
            cache = json.loads(SELF_CACHE_PATH.read_text())
        except json.JSONDecodeError:
            pass

    by_file = cache.get("by_file", {})
    through = 0.0 if rescan else float(cache.get("scanned_through", 0.0))
    high_water = through
    parsed = 0

    if TRANSCRIPT_ROOT.exists():
        for f in TRANSCRIPT_ROOT.rglob("*.jsonl"):
            try:
                mtime = f.stat().st_mtime
            except OSError:
                continue
            high_water = max(high_water, mtime)
            key = str(f.relative_to(TRANSCRIPT_ROOT))
            if mtime <= through and key not in by_file:
                continue  # unchanged and previously had no events
            if key in by_file and mtime <= by_file[key].get("mtime", 0):
                continue
            found = _scan_transcript(f, known)
            parsed += 1
            if found:
                by_file[key] = {"mtime": mtime, "days": found}
            else:
                by_file.pop(key, None)

    merged = {}
    for entry in by_file.values():
        for day, payload in entry["days"].items():
            tgt = merged.setdefault(day, {"repos": {}, "unattributed": 0})
            tgt["unattributed"] += payload.get("unattributed", 0)
            for r, counts in payload.get("repos", {}).items():
                e = tgt["repos"].setdefault(r, {"clone": 0, "fetch": 0})
                e["clone"] += counts.get("clone", 0)
                e["fetch"] += counts.get("fetch", 0)

    SELF_CACHE_PATH.write_text(
        json.dumps({"by_file": by_file, "scanned_through": high_water}) + "\n"
    )
    SELF_ACTIVITY_PATH.write_text(
        json.dumps(
            {
                "_comment": (
                    "Dates on which the account owner ran git clone / gh repo clone "
                    "/ git fetch, derived from local session transcripts. Clone "
                    "traffic on these dates is self-generated and is excluded from "
                    "the ex_self columns. Only dates, repo names and counts are "
                    "stored -- never command text, file paths or session ids."
                ),
                "days": dict(sorted(merged.items())),
            },
            indent=1,
            sort_keys=False,
        )
        + "\n"
    )
    print(f"Self-activity: {len(merged)} dates flagged ({parsed} transcripts parsed)")
    return merged


def main():
    DATA_DIR.mkdir(exist_ok=True)
    repos = list_public_repos()
    print(f"Snapshotting {len(repos)} public repos...")

    for name in repos:
        clones = gh_api(f"repos/{OWNER}/{name}/traffic/clones")
        views = gh_api(f"repos/{OWNER}/{name}/traffic/views")
        data = load_repo_data(name)

        if clones and "clones" in clones:
            data["clones"] = upsert_series(data["clones"], clones["clones"])
        if views and "views" in views:
            data["views"] = upsert_series(data["views"], views["views"])
        data = record_period_totals(data, clones, views)
        data = snapshot_releases(name, data)

        save_repo_data(name, data)
        print(f"  {name}: ok")

    self_days = scan_self_activity(set(repos), rescan="--rescan" in sys.argv)

    # Rebuild a flat summary CSV for quick scanning
    summary_path = REPO_ROOT / "summary.csv"
    with open(summary_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "repo",
                "date",
                "clones",
                "clone_uniques",
                "views",
                "view_uniques",
                "release_downloads_cumulative",
                "self_activity",
            ]
        )
        for name in repos:
            data = load_repo_data(name)
            all_dates = sorted(
                set(data["clones"]) | set(data["views"]) | set(data["releases"])
            )
            for d in all_dates:
                c = data["clones"].get(d, {})
                v = data["views"].get(d, {})
                r = data["releases"].get(d, "")
                w.writerow(
                    [
                        name,
                        d,
                        c.get("count", ""),
                        c.get("uniques", ""),
                        v.get("count", ""),
                        v.get("uniques", ""),
                        r,
                        self_label(self_days, name, d),
                    ]
                )
    print(f"Wrote {summary_path}")
    write_views_summary(repos, self_days)


def self_label(self_days, repo, day):
    """'clone', 'fetch', 'clone+fetch', or '' for a given repo-day."""
    counts = self_days.get(day, {}).get("repos", {}).get(repo)
    if not counts:
        return ""
    parts = [k for k in ("clone", "fetch") if counts.get(k)]
    return "+".join(parts)


def is_self_day(self_days, repo, day):
    return bool(self_days.get(day, {}).get("repos", {}).get(repo))


def _window_sum(series, field, since):
    return sum(v.get(field, 0) or 0 for d, v in series.items() if d >= since)


def write_views_summary(repos, self_days):
    """Human-interest rollup, kept apart from the machine-traffic columns.

    Clones are overwhelmingly automated (mirrors, indexers, CI checkouts) or
    self-generated, so they drown out the one signal that tracks actual people
    reading a repo. This file isolates that signal. Read `view_uniques_14d`
    first: it is GitHub's own deduplicated count. The `_sum` columns add up
    per-day uniques and are therefore upper bounds, not distinct-person counts.

    `clones_7d_ex_self` drops days on which the owner ran a clone/fetch against
    that repo. The raw `clones_7d_sum` stays alongside it — the exclusion is
    shown, never applied silently — and `self_days_7d` says how many days were
    dropped. Views are left untouched: browser page loads aren't produced by
    git commands, so there is nothing to exclude.
    """
    now = today()
    since_7 = str(now - timedelta(days=7))
    rows = []

    for name in repos:
        data = load_repo_data(name)
        views, clones = data["views"], data["clones"]
        periods = data.get("period_totals", {})
        latest = periods.get(max(periods), {}) if periods else {}

        recent_clone_days = [d for d in clones if d >= since_7]
        dropped = [d for d in recent_clone_days if is_self_day(self_days, name, d)]
        clean = sum(
            clones[d].get("count", 0) or 0
            for d in recent_clone_days
            if d not in set(dropped)
        )

        viewed_days = sorted(d for d, v in views.items() if (v.get("count") or 0) > 0)
        rows.append(
            {
                "repo": name,
                "view_uniques_14d": latest.get("views", {}).get("uniques", ""),
                "views_14d": latest.get("views", {}).get("count", ""),
                "view_uniques_7d_sum": _window_sum(views, "uniques", since_7),
                "views_7d_sum": _window_sum(views, "count", since_7),
                "view_uniques_tracked_sum": _window_sum(views, "uniques", ""),
                "views_tracked_sum": _window_sum(views, "count", ""),
                "days_with_views": len(viewed_days),
                "last_viewed": viewed_days[-1] if viewed_days else "",
                "clones_7d_ex_self": clean,
                "clones_7d_sum": _window_sum(clones, "count", since_7),
                "self_days_7d": len(dropped),
            }
        )

    # Most-read first; the deduplicated figure is the one that ranks.
    rows.sort(
        key=lambda r: (
            r["view_uniques_14d"] if isinstance(r["view_uniques_14d"], int) else -1,
            r["view_uniques_7d_sum"],
            r["views_tracked_sum"],
        ),
        reverse=True,
    )

    path = REPO_ROOT / "views_summary.csv"
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {path}")


if __name__ == "__main__":
    sys.exit(main())
