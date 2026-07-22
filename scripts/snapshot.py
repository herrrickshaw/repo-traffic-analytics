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

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
OWNER = "herrrickshaw"


def gh_api(path):
    result = subprocess.run(
        ["gh", "api", path], capture_output=True, text=True, timeout=30
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
        return json.loads(f.read_text())
    return {"clones": {}, "views": {}, "releases": {}}


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
    from datetime import date

    data["releases"][str(date.today())] = today_total
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
        data = snapshot_releases(name, data)

        save_repo_data(name, data)
        print(f"  {name}: ok")

    # Rebuild a flat summary CSV for quick scanning
    import csv

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


if __name__ == "__main__":
    sys.exit(main())
