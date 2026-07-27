#!/usr/bin/env python3
"""
Monthly repo-portfolio review generator (CIO review item: monthly 30-min review).

Produces reports/REVIEW_YYYY-MM.md with, per catalogued repo:
  - tier (from repos.yaml), visibility, size
  - last push date and days-since-push (gh api)
  - 30-day clone/view totals (from the accumulated data/*.json snapshots)
  - a suggested verdict: KEEP / REVIEW / ARCHIVE-CANDIDATE

Verdict heuristic (metrics chosen for n=1 operator per the review:
freshness + liveness, not DORA):
  - tier 1                       -> KEEP (active automation)
  - pushed or trafficked <90d    -> KEEP
  - tier 2, stale >90d           -> REVIEW (is the data still canonical?)
  - tier 3, stale >90d           -> ARCHIVE-CANDIDATE

The human still makes the call — this file is the agenda, not the decision.
"""

import json
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
REPORT_DIR = REPO_ROOT / "reports"
OWNER = "herrrickshaw"


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


def traffic_30d(name):
    """Sum clones/views for the last 30 days from the accumulated snapshot."""
    path = DATA_DIR / f"{name}.json"
    if not path.exists():
        return None, None
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return None, None
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    clones = sum(
        v.get("count", 0)
        for date, v in data.get("clones", {}).items()
        if date >= cutoff
    )
    views = sum(
        v.get("count", 0) for date, v in data.get("views", {}).items() if date >= cutoff
    )
    return clones, views


def main():
    catalog = load_catalog()
    now = datetime.now(timezone.utc)
    REPORT_DIR.mkdir(exist_ok=True)
    out = REPORT_DIR / f"REVIEW_{now.strftime('%Y-%m')}.md"

    rows = []
    for name, meta in sorted(catalog.items()):
        tier = int(meta.get("tier", 3))
        info = gh_api(f"repos/{OWNER}/{name}") or {}
        pushed = info.get("pushed_at")
        days_stale = None
        if pushed:
            days_stale = (
                now - datetime.fromisoformat(pushed.replace("Z", "+00:00"))
            ).days
        clones, views = traffic_30d(name)

        if (
            tier == 1
            or (days_stale is not None and days_stale < 90)
            or (clones or 0) + (views or 0) > 0
        ):
            verdict = "KEEP"
        elif tier == 2:
            verdict = "REVIEW"
        else:
            verdict = "ARCHIVE-CANDIDATE"

        rows.append(
            (
                verdict,
                tier,
                name,
                days_stale if days_stale is not None else "?",
                clones if clones is not None else "-",
                views if views is not None else "-",
                meta.get("visibility", "?"),
            )
        )

    order = {"ARCHIVE-CANDIDATE": 0, "REVIEW": 1, "KEEP": 2}
    rows.sort(key=lambda r: (order[r[0]], r[1], r[2]))

    lines = [
        f"# Portfolio review — {now.strftime('%Y-%m')}",
        "",
        (
            f"Generated {now.strftime('%Y-%m-%d %H:%M UTC')}. "
            "Verdicts are suggestions; decide keep / archive / merge per repo."
        ),
        "",
        "| Verdict | Tier | Repo | Days stale | Clones 30d | Views 30d | Visibility |",
        "|---|---|---|---|---|---|---|",
    ]
    for v, t, n, d, c, vw, vis in rows:
        lines.append(f"| {v} | {t} | {n} | {d} | {c} | {vw} | {vis} |")

    counts = {}
    for r in rows:
        counts[r[0]] = counts.get(r[0], 0) + 1
    lines += [
        "",
        "Summary: " + ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())),
        "",
        "Checklist for the 30-minute pass:",
        "- [ ] Act on each ARCHIVE-CANDIDATE (archive, or note why kept)",
        "- [ ] For each REVIEW: is its canonical data still referenced anywhere?",
        "- [ ] Cron liveness: `launchctl print` runs-counters and `crontab -l` jobs fired this month",
        "- [ ] Backup verification: last weekly replication matrix all green",
    ]
    out.write_text("\n".join(lines) + "\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
