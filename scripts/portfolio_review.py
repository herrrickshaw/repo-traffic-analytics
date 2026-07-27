#!/usr/bin/env python3
"""
Monthly repo-portfolio review generator (CIO review item: monthly 30-min review).

Produces reports/REVIEW_YYYY-MM.md with, per catalogued repo:
  - tier (from repos.yaml), visibility, size
  - last push date and days-since-push (gh api)
  - 30-day clone/view totals (from the accumulated data/*.json snapshots)
  - a suggested verdict: MISSING / KEEP / REVIEW / ARCHIVE-CANDIDATE

Verdict heuristic (metrics chosen for n=1 operator per the review:
freshness + liveness, not DORA):
  - repo 404s                    -> MISSING (catalogue entry is stale)
  - tier 1                       -> KEEP (active automation)
  - pushed <90d                  -> KEEP
  - >= 3 distinct viewers        -> KEEP (someone is actually reading it)
  - tier 2, stale + unread       -> REVIEW (is the data still canonical?)
  - tier 3, stale + unread       -> ARCHIVE-CANDIDATE

Liveness is measured in *distinct viewers*, not clones. Clone counts are
dominated by automation and by the owner's own git commands — cloning a repo to
look at it would otherwise renew its own KEEP verdict, which makes the signal
circular. Clone columns are still reported (with the owner's own days excluded,
alongside the raw figure) but they no longer decide anything.

The viewer count is GitHub's deduplicated trailing-14-day `uniques`, the only
honest distinct-person figure it exposes. Per-day uniques cannot be summed —
that double-counts anyone who returns — so a 30-day equivalent does not exist.

The human still makes the call — this file is the agenda, not the decision.
"""

import json
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from snapshot import SELF_ACTIVITY_PATH, is_self_day

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
REPORT_DIR = REPO_ROOT / "reports"
OWNER = "herrrickshaw"

# Distinct viewers (deduplicated, 14d) required to count a repo as read.
MIN_VIEWERS = 3


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


def load_catalog():
    """Parse repos.yaml without a yaml dependency (flat, known structure)."""
    text = (REPO_ROOT / "repos.yaml").read_text()
    repos = {}
    current = None
    for line in text.splitlines():
        m = re.match(r"^  ([\w.-]+):\s*$", line)
        if m:
            current = m.group(1)
            repos[current] = {}
            continue
        if current:
            kv = re.match(r"^    (\w+):\s*(.+?)(\s+#.*)?$", line)
            if kv:
                repos[current][kv.group(1)] = kv.group(2).strip().strip('"')
    return repos


def load_self_days():
    """Dates the owner ran clone/fetch commands, written by snapshot.py."""
    try:
        return json.loads(SELF_ACTIVITY_PATH.read_text()).get("days", {})
    except (OSError, json.JSONDecodeError):
        return {}


def traffic_30d(name, self_days):
    """30-day clones excluding the owner's own days, raw clones, and views.

    Views are not adjusted: they count browser page loads, which no git command
    produces. (A repo owner browsing their own repo would still register, but
    nothing in the data can distinguish that.)
    """
    path = DATA_DIR / f"{name}.json"
    if not path.exists():
        return None, None, None, None
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return None, None, None, None
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    recent = {d: v for d, v in data.get("clones", {}).items() if d >= cutoff}
    raw = sum(v.get("count", 0) for v in recent.values())
    external = sum(
        v.get("count", 0)
        for d, v in recent.items()
        if not is_self_day(self_days, name, d)
    )
    views = sum(
        v.get("count", 0) for date, v in data.get("views", {}).items() if date >= cutoff
    )
    # Distinct viewers: GitHub's own 14-day dedup, recorded by snapshot.py.
    periods = data.get("period_totals", {})
    viewers = None
    if periods:
        viewers = periods[max(periods)].get("views", {}).get("uniques")
    return external, raw, views, viewers


def decide(tier, days_stale, viewers, exists=True):
    """Suggested verdict. `exists=False` short-circuits everything.

    A catalogued repo that 404s is gone from GitHub — renamed, deleted, or
    made private. Its accumulated traffic is historical, so letting the
    liveness test see it would keep a dead entry alive forever.
    """
    if not exists:
        return "MISSING"
    if (
        tier == 1
        or (days_stale is not None and days_stale < 90)
        or (viewers or 0) >= MIN_VIEWERS
    ):
        return "KEEP"
    return "REVIEW" if tier == 2 else "ARCHIVE-CANDIDATE"


def main():
    catalog = load_catalog()
    self_days = load_self_days()
    now = datetime.now(timezone.utc)
    REPORT_DIR.mkdir(exist_ok=True)
    out = REPORT_DIR / f"REVIEW_{now.strftime('%Y-%m')}.md"

    rows = []
    load_bearing = []
    for name, meta in sorted(catalog.items()):
        tier = int(meta.get("tier", 3))
        info = gh_api(f"repos/{OWNER}/{name}")
        exists = bool(info)
        info = info or {}
        pushed = info.get("pushed_at")
        days_stale = None
        if pushed:
            days_stale = (
                now - datetime.fromisoformat(pushed.replace("Z", "+00:00"))
            ).days
        clones, raw_clones, views, viewers = traffic_30d(name, self_days)

        verdict = decide(tier, days_stale, viewers, exists)
        # Did readership decide anything, or would freshness/tier alone do it?
        if exists and verdict != decide(tier, days_stale, 0):
            load_bearing.append(f"{name} ({viewers} viewers)")

        rows.append(
            (
                verdict,
                tier,
                name,
                days_stale if days_stale is not None else "?",
                viewers if viewers is not None else "-",
                clones if clones is not None else "-",
                raw_clones if raw_clones is not None else "-",
                views if views is not None else "-",
                meta.get("visibility", "?"),
            )
        )

    order = {"MISSING": 0, "ARCHIVE-CANDIDATE": 1, "REVIEW": 2, "KEEP": 3}
    rows.sort(key=lambda r: (order[r[0]], r[1], r[2]))

    lines = [
        f"# Portfolio review — {now.strftime('%Y-%m')}",
        "",
        (
            f"Generated {now.strftime('%Y-%m-%d %H:%M UTC')}. "
            "Verdicts are suggestions; decide keep / archive / merge per repo."
        ),
        "",
        (
            f"Liveness = **{MIN_VIEWERS}+ distinct viewers**, using GitHub's "
            "deduplicated trailing-14-day count. Per-day uniques cannot be summed "
            "(that double-counts return visitors), so no 30-day equivalent exists. "
            "Clone columns are informational only and decide nothing: **ext** drops "
            "days the owner ran a clone/fetch, **raw** is unfiltered, and the true "
            "external figure sits between them."
        ),
        "",
        (
            "| Verdict | Tier | Repo | Days stale | Viewers 14d | Clones 30d ext "
            "| Clones 30d raw | Views 30d | Visibility |"
        ),
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for v, t, n, d, u, c, rawc, vw, vis in rows:
        lines.append(f"| {v} | {t} | {n} | {d} | {u} | {c} | {rawc} | {vw} | {vis} |")

    counts = {}
    for r in rows:
        counts[r[0]] = counts.get(r[0], 0) + 1
    lines += [
        "",
        "Summary: " + ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())),
    ]

    # If nothing is stale, every repo passes on freshness alone and readership
    # is inert. Say so — otherwise a wall of KEEPs reads as a real result.
    if not load_bearing:
        lines += [
            "",
            (
                f"> Note: no repo is over the 90-day staleness line (max "
                f"{max((r[3] for r in rows if isinstance(r[3], int)), default=0)}d), "
                "so all verdicts come from freshness or tier alone. Readership "
                "decided nothing this month — these KEEPs say the portfolio is "
                "recently pushed, not that anything is being read."
            ),
        ]
    else:
        lines += [
            "",
            f"> Readership was the deciding signal for {len(load_bearing)} repo(s): "
            + ", ".join(load_bearing),
        ]

    lines += [
        "",
        "Checklist for the 30-minute pass:",
        (
            "- [ ] Resolve each MISSING: repo 404s but is still catalogued in "
            "repos.yaml — renamed, deleted, or made private? Update or drop the entry"
        ),
        "- [ ] Act on each ARCHIVE-CANDIDATE (archive, or note why kept)",
        "- [ ] For each REVIEW: is its canonical data still referenced anywhere?",
        "- [ ] Cron liveness: `launchctl print` runs-counters and `crontab -l` jobs fired this month",
        "- [ ] Backup verification: last weekly replication matrix all green",
    ]
    out.write_text("\n".join(lines) + "\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
