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
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
OWNER = "herrrickshaw"


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
                    ]
                )
    print(f"Wrote {summary_path}")
    write_views_summary(repos)


def _window_sum(series, field, since):
    return sum(v.get(field, 0) or 0 for d, v in series.items() if d >= since)


def write_views_summary(repos):
    """Human-interest rollup, kept apart from the machine-traffic columns.

    Clones are overwhelmingly automated (mirrors, indexers, CI checkouts), so
    they drown out the one signal that tracks actual people reading a repo.
    This file isolates that signal. Read `view_uniques_14d` first: it is
    GitHub's own deduplicated count. The `_sum` columns add up per-day uniques
    and are therefore upper bounds, not distinct-person counts.
    """
    now = today()
    since_7 = str(now - timedelta(days=7))
    rows = []

    for name in repos:
        data = load_repo_data(name)
        views, clones = data["views"], data["clones"]
        periods = data.get("period_totals", {})
        latest = periods.get(max(periods), {}) if periods else {}

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
                "clones_7d_sum": _window_sum(clones, "count", since_7),
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
