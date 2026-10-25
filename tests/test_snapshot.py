"""Tests for scripts/snapshot.py — the daily GitHub traffic snapshotter.

GitHub retains only 14 days of clones/views and exposes NO per-IP or per-origin
breakdown, so this script accumulates history by upserting each API pull by date.
"clones" are mostly automated/self-generated, so the real signal is deduplicated
view uniques — the reason the summaries split those columns apart.

These tests cover the DATA-SHAPING logic (date-keyed upsert/dedup, GitHub's own
14-day dedup reconciliation, command->repo attribution, CSV window sums), the
network-touching helpers with `gh` mocked, and an end-to-end main() run against a
temp output dir (mocked API, no transcripts) that verifies the emitted rows,
columns, and same-day idempotency.
"""

import csv
import json
import subprocess
from datetime import timedelta

import pytest

from scripts import snapshot as sn

# --------------------------- upsert_series() : date-keyed dedup ---------------------------


def test_upsert_series_keys_by_date_truncating_timestamp():
    existing = {}
    pts = [{"timestamp": "2026-07-20T00:00:00Z", "count": 10, "uniques": 5}]
    out = sn.upsert_series(existing, pts)
    assert out == {"2026-07-20": {"count": 10, "uniques": 5}}  # ISO time dropped


def test_upsert_series_is_idempotent_by_date():
    existing = {"2026-07-20": {"count": 10, "uniques": 5}}
    # same date pulled again (API always returns trailing 14 days) -> replace, not add
    pts = [{"timestamp": "2026-07-20T00:00:00Z", "count": 12, "uniques": 6}]
    out = sn.upsert_series(existing, pts)
    assert len(out) == 1  # not doubled
    assert out["2026-07-20"] == {"count": 12, "uniques": 6}  # newest wins


# --------------------------- record_period_totals() : 14-day dedup reconciliation ---------


def test_record_period_totals_stores_deduplicated_uniques():
    data = {"period_totals": {}}
    clones = {"count": 64, "uniques": 38}
    views = {"count": 8, "uniques": 2}
    sn.record_period_totals(data, clones, views)
    entry = data["period_totals"][str(sn.today())]
    assert entry["clones"] == {"count": 64, "uniques": 38}
    assert entry["views"] == {"count": 8, "uniques": 2}


def test_record_period_totals_skips_payloads_without_uniques():
    data = {"period_totals": {}}
    sn.record_period_totals(data, None, {"count": 5})  # no 'uniques' key
    assert data["period_totals"] == {}  # nothing honest to store


# --------------------------- _repos_in_command() : attribution ---------------------------


def test_repos_in_command_matches_known_repo_with_git_suffix():
    known = {"repo-a", "repo-b"}
    hits = sn._repos_in_command("git clone https://github.com/x/repo-a.git", known)
    assert hits == {"repo-a"}


def test_repos_in_command_ignores_substring_phantom_hits():
    known = {"ab"}  # short name must not match inside a longer repo name
    assert sn._repos_in_command("git clone https://x/repo-abc", known) == set()


def test_repos_in_command_home_cd_falls_back_to_home_repo():
    known = {sn.HOME_REPO}
    hits = sn._repos_in_command("cd ~ && git fetch", known)
    assert hits == {
        sn.HOME_REPO
    }  # bare home working-tree update attributed to HOME_REPO


# --------------------------- self_label() / _window_sum() : CSV shaping -------------------


def test_self_label_reports_clone_fetch_combo():
    days = {"2026-07-20": {"repos": {"r": {"clone": 1, "fetch": 1}}}}
    assert sn.self_label(days, "r", "2026-07-20") == "clone+fetch"
    assert sn.self_label(days, "r", "2026-07-19") == ""  # no activity that day
    assert sn.self_label({}, "r", "2026-07-20") == ""


def test_window_sum_respects_since_cutoff():
    series = {
        "2026-07-20": {"count": 5},
        "2026-07-10": {"count": 3},  # before cutoff, excluded
    }
    assert sn._window_sum(series, "count", "2026-07-15") == 5
    assert sn._window_sum(series, "count", "") == 8  # empty cutoff -> all


# --------------------------- _scan_transcript() : local activity parse -------------------


def test_scan_transcript_attributes_clone_and_flags_unattributed(tmp_path):
    known = {"repo-a"}
    lines = [
        {
            "timestamp": "2026-07-20T10:00:00Z",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "input": {"command": "git clone https://x/repo-a"},
                    }
                ]
            },
        },
        {
            "timestamp": "2026-07-20T11:00:00Z",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "input": {"command": "git clone https://x/unknown-repo"},
                    }
                ]
            },
        },
    ]
    f = tmp_path / "session.jsonl"
    f.write_text("\n".join(json.dumps(x) for x in lines) + "\n")

    days = sn._scan_transcript(f, known)
    day = days["2026-07-20"]
    assert day["repos"]["repo-a"] == {"clone": 1, "fetch": 0}
    assert day["unattributed"] == 1  # the clone of an untracked repo


# --------------------------- gh_api() / list_tracked_repos() : network mocked ------------


class _Completed:
    def __init__(self, returncode=0, stdout=""):
        self.returncode = returncode
        self.stdout = stdout


def test_gh_api_returns_parsed_json(monkeypatch):
    monkeypatch.setattr(
        sn.subprocess, "run", lambda *a, **k: _Completed(0, json.dumps({"count": 3}))
    )
    assert sn.gh_api("repos/x/y/traffic/clones") == {"count": 3}


def test_gh_api_returns_none_on_error(monkeypatch):
    monkeypatch.setattr(
        sn.subprocess, "run", lambda *a, **k: _Completed(1, "")
    )  # gh exited nonzero
    assert sn.gh_api("repos/x/y/traffic/clones") is None


def test_list_tracked_repos_filters_archive_twins(monkeypatch):
    payload = [
        {"name": "repo-b", "visibility": "public"},
        {"name": "repo-a", "visibility": "private"},
        {"name": "old-archive-2026-07-17", "visibility": "private"},  # excluded
    ]
    monkeypatch.setattr(
        sn.subprocess, "run", lambda *a, **k: _Completed(0, json.dumps(payload))
    )
    assert sn.list_tracked_repos() == ["repo-a", "repo-b"]  # sorted, archive dropped


# --------------------------- main() : end-to-end, mocked net + temp output dir -----------


@pytest.fixture
def wired_main(monkeypatch, tmp_path):
    """Point every write target at tmp_path and mock all GitHub calls."""
    data_dir = tmp_path / "data"
    monkeypatch.setattr(sn, "DATA_DIR", data_dir)
    monkeypatch.setattr(sn, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(sn, "SELF_ACTIVITY_PATH", tmp_path / "self_activity.json")
    monkeypatch.setattr(sn, "SELF_CACHE_PATH", tmp_path / ".self_activity_cache.json")
    monkeypatch.setattr(sn, "TRANSCRIPT_ROOT", tmp_path / "no_transcripts")  # absent
    # Keep the local-clone discovery inside tmp_path: unpatched it walks $HOME,
    # which is both slow and non-hermetic.
    monkeypatch.setattr(sn, "LOCAL_SCAN_ROOT", tmp_path / "no_clones")
    monkeypatch.setattr(sn.sys, "argv", ["snapshot.py"])
    monkeypatch.setattr(sn, "list_tracked_repos", lambda: ["repo-a", "repo-b"])

    def fake_gh_api(path):
        if path.endswith("/traffic/clones"):
            return {
                "count": 10,
                "uniques": 5,
                "clones": [
                    {"timestamp": "2026-07-20T00:00:00Z", "count": 10, "uniques": 5}
                ],
            }
        if path.endswith("/traffic/views"):
            return {
                "count": 8,
                "uniques": 2,
                "views": [
                    {"timestamp": "2026-07-20T00:00:00Z", "count": 8, "uniques": 2}
                ],
            }
        if path.endswith("/releases"):
            return [{"assets": [{"download_count": 7}]}]
        if path.endswith("/actions/workflows"):
            return {"total_count": 1}
        return None

    monkeypatch.setattr(sn, "gh_api", fake_gh_api)
    # Four Actions runs on the same day the traffic API reports 10 clones.
    monkeypatch.setattr(
        sn,
        "gh_api_lines",
        lambda path, jq: ["2026-07-20T04:00:00Z"] * 4,
    )
    return tmp_path, data_dir


def test_main_writes_per_repo_json_and_summaries(wired_main):
    root, data_dir = wired_main
    sn.main()

    # per-repo data files with the upserted date-keyed series
    data = json.loads((data_dir / "repo-a.json").read_text())
    assert data["clones"]["2026-07-20"] == {"count": 10, "uniques": 5}
    assert data["views"]["2026-07-20"] == {"count": 8, "uniques": 2}
    assert data["releases"][str(sn.today())] == 7  # summed asset downloads
    assert data["period_totals"][str(sn.today())]["clones"]["uniques"] == 5

    # flat summary.csv: expected columns + one row per repo-date
    with open(root / "summary.csv") as f:
        rows = list(csv.DictReader(f))
    assert {"repo", "date", "clones", "view_uniques", "self_activity"} <= set(rows[0])
    assert {r["repo"] for r in rows} == {"repo-a", "repo-b"}

    # views_summary.csv isolates the deduplicated-readership signal
    with open(root / "views_summary.csv") as f:
        vrows = list(csv.DictReader(f))
    assert len(vrows) == 2
    assert {
        "view_uniques_14d",
        "ext_cloners_14d",
        "clone_uniques_14d",
        "clones_7d_ext",
        "ci_runs_7d",
        "self_days_7d",
        "local_copies",
    } <= set(vrows[0])
    assert vrows[0]["view_uniques_14d"] == "2"  # GitHub's own 14-day dedup count
    # No local copy exists -> self_days_7d = 0 is authoritative, not undetected
    assert vrows[0]["local_copies"] == "0"

    # Actions runs are archived per day alongside the traffic series
    assert data["ci_runs"]["2026-07-20"] == 4


def test_main_is_idempotent_across_reruns(wired_main):
    _root, data_dir = wired_main
    sn.main()
    sn.main()  # second run pulls the same trailing-14-day window again

    data = json.loads((data_dir / "repo-a.json").read_text())
    assert len(data["clones"]) == 1  # upsert by date -> not doubled
    assert data["clones"]["2026-07-20"] == {"count": 10, "uniques": 5}


def _ci_fixture(tmp_path, monkeypatch, ci_runs, clone_uniques=3):
    """One repo with 20 clones yesterday, plus whatever CI history is passed."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)  # tests may re-seed the same tmp_path
    monkeypatch.setattr(sn, "DATA_DIR", data_dir)
    monkeypatch.setattr(sn, "REPO_ROOT", tmp_path)
    yesterday = str(sn.today() - timedelta(days=1))
    (data_dir / "repo-a.json").write_text(
        json.dumps(
            {
                "clones": {yesterday: {"count": 20, "uniques": clone_uniques}},
                "views": {},
                "releases": {},
                "ci_runs": {yesterday: ci_runs},
                "period_totals": {
                    yesterday: {
                        "clones": {"count": 20, "uniques": clone_uniques},
                        "views": {"count": 0, "uniques": 0},
                    }
                },
            }
        )
    )
    return yesterday


def test_actions_runs_are_subtracted_from_the_clone_count(tmp_path, monkeypatch):
    """Every Actions run checks the repo out, and GitHub books that as a clone.

    Subtraction is per-day, so a repo whose CI ran still reports the external
    clones it received that day — unlike dropping the day wholesale.
    """
    _ci_fixture(tmp_path, monkeypatch, ci_runs=14)
    sn.write_views_summary(["repo-a"], {}, {})
    row = next(csv.DictReader((tmp_path / "views_summary.csv").open()))

    assert row["clones_7d_sum"] == "20"  # raw figure still shown
    assert row["ci_runs_7d"] == "14"
    assert row["clones_7d_ext"] == "6"  # 20 - 14


def test_ci_subtraction_never_goes_negative(tmp_path, monkeypatch):
    """Matrix runs check out once per job, so runs can exceed booked clones.

    The count is a floor, not a signed residual — it must clamp at zero rather
    than lending negative traffic to the next day in the sum.
    """
    _ci_fixture(tmp_path, monkeypatch, ci_runs=95)
    sn.write_views_summary(["repo-a"], {}, {})
    row = next(csv.DictReader((tmp_path / "views_summary.csv").open()))
    assert row["clones_7d_ext"] == "0"


def test_ext_cloners_discounts_ci_and_self_identities(tmp_path, monkeypatch):
    """GitHub dedups cloners over 14 days: CI is one identity, the owner another.

    This is the only figure that survives cleaning into a person-count, so it
    has to discount both — and only on evidence that each was actually active.
    """
    day = _ci_fixture(tmp_path, monkeypatch, ci_runs=14, clone_uniques=3)
    self_days = {day: {"repos": {"repo-a": {"clone": 1, "fetch": 0}}}}

    sn.write_views_summary(["repo-a"], self_days, {})
    row = next(csv.DictReader((tmp_path / "views_summary.csv").open()))
    assert row["clone_uniques_14d"] == "3"  # raw
    assert row["ext_cloners_14d"] == "1"  # minus CI, minus self

    # With no CI and no self-activity, every unique cloner is a third party.
    _ci_fixture(tmp_path, monkeypatch, ci_runs=0, clone_uniques=3)
    sn.write_views_summary(["repo-a"], {}, {})
    row = next(csv.DictReader((tmp_path / "views_summary.csv").open()))
    assert row["ext_cloners_14d"] == "3"


def test_private_repo_driven_entirely_by_ci_reports_no_outsiders(tmp_path, monkeypatch):
    """The blogger_writeups_code shape: heavy clone traffic, 2 unique cloners,
    never viewed. Both identities are accounted for, so the answer is zero."""
    day = _ci_fixture(tmp_path, monkeypatch, ci_runs=20, clone_uniques=2)
    sn.write_views_summary(
        ["repo-a"], {day: {"repos": {"repo-a": {"clone": 0, "fetch": 3}}}}, {}
    )
    row = next(csv.DictReader((tmp_path / "views_summary.csv").open()))
    assert row["ext_cloners_14d"] == "0"


def test_write_views_summary_handles_zero_repos(tmp_path, monkeypatch):
    """A transient `gh` outage can yield an empty repo list — the summary must
    still write a valid header-only CSV, not IndexError on rows[0]."""
    monkeypatch.setattr(sn, "REPO_ROOT", tmp_path)
    sn.write_views_summary([], {}, {})  # must not raise
    out = tmp_path / "views_summary.csv"
    assert out.exists()
    rows = list(csv.reader(out.open()))
    assert rows and rows[0][0] == "repo"  # header written
    assert len(rows) == 1  # header only, no data rows


# ------------------- local clone discovery + reflog : the second evidence source -------------------
#
# `self_days_7d = 0` used to be ambiguous: it meant either "no local copy exists,
# so no own traffic is possible" or "a copy exists but nothing was detected".
# Discovery answers the first; the reflog scan closes most of the second, since
# the transcript scan cannot see terminal or cron activity.


def _make_repo(path, remote=None, commit_message="init"):
    """A real git repo on disk — the reflog logic is git behaviour, not ours."""
    path.mkdir(parents=True, exist_ok=True)

    def run(*args):
        subprocess.run(["git", "-C", str(path), *args], capture_output=True, check=True)

    run("init", "-q", "-b", "main")
    run("config", "user.email", "t@example.com")
    run("config", "user.name", "t")
    (path / "f.txt").write_text("x")
    run("add", "f.txt")
    run("commit", "-qm", commit_message)
    if remote:
        run("remote", "add", "origin", remote)
    return path


def test_discover_local_clones_maps_remote_url_to_tracked_repo(tmp_path, monkeypatch):
    _make_repo(tmp_path / "work", remote=f"https://github.com/{sn.OWNER}/repo-a.git")
    monkeypatch.setattr(sn, "LOCAL_SCAN_ROOT", tmp_path)
    found = sn.discover_local_clones({"repo-a", "repo-b"})
    assert set(found) == {"repo-a"}
    assert found["repo-a"] == [str(tmp_path / "work")]


def test_discover_local_clones_ignores_other_owners_and_untracked(
    tmp_path, monkeypatch
):
    _make_repo(tmp_path / "other", remote="https://github.com/someone-else/repo-a.git")
    _make_repo(tmp_path / "untracked", remote=f"git@github.com:{sn.OWNER}/nope.git")
    monkeypatch.setattr(sn, "LOCAL_SCAN_ROOT", tmp_path)
    assert sn.discover_local_clones({"repo-a"}) == {}


def test_discover_local_clones_skips_pruned_directories(tmp_path, monkeypatch):
    _make_repo(
        tmp_path / "node_modules" / "dep",
        remote=f"https://github.com/{sn.OWNER}/repo-a.git",
    )
    monkeypatch.setattr(sn, "LOCAL_SCAN_ROOT", tmp_path)
    assert sn.discover_local_clones({"repo-a"}) == {}


def test_scan_reflog_ignores_commits_whose_message_mentions_cloning(tmp_path):
    """The reflog subject starts with the command; a commit *about* cloning is
    still a commit. Matching anywhere in the line would misread it as activity."""
    repo = _make_repo(tmp_path / "w", commit_message="Detect our own clone days")
    assert sn.scan_reflog_activity({"repo-a": [str(repo)]}) == {}


def test_scan_reflog_records_a_real_fetch(tmp_path):
    origin = _make_repo(tmp_path / "origin")
    clone_dir = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", "-q", str(origin), str(clone_dir)],
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(clone_dir), "fetch", "origin"],
        capture_output=True,
        check=True,
    )
    days = sn.scan_reflog_activity({"repo-a": [str(clone_dir)]})
    # `git clone` writes a "clone: from ..." reflog entry, dated today.
    # Keyed in UTC to match the traffic API's buckets, NOT in the local time
    # git stamps the reflog with — this assertion fails on a machine whose
    # offset puts it on a different calendar day, which is the whole point.
    assert days, "clone/fetch left no reflog entry"
    entry = days[str(sn.today())]["repos"]["repo-a"]
    assert entry["clone"] >= 1


def test_reflog_selector_resolves_to_a_utc_day_not_a_local_one():
    """Reflog dates must land in the same UTC buckets the traffic API uses.

    2026-08-20T00:06:51Z is still 2026-08-19 in the Americas and already
    2026-08-20 in Asia; the epoch pins it to the UTC day regardless of where
    the scan runs. Parsed from an integer rather than an ISO string because
    `--date=iso-strict` renders UTC as `Z` and everywhere else as `+05:30` —
    matching only one shape yielded zero self-days on a UTC runner, which reads
    as a clean week rather than an error.
    """
    assert sn.reflog_utc_day("main@{1787184411}") == "2026-08-20"
    # An ordinal selector means --date went unhonoured. Rejected rather than
    # dated to 1970, which would match no traffic day and look like a clean week
    assert sn.reflog_utc_day("HEAD@{0}") is None
    assert sn.reflog_utc_day("HEAD@{2}") is None
    assert sn.reflog_utc_day("HEAD@{upstream}") is None


def test_merge_activity_unions_sources_and_records_which_saw_each_day():
    transcript = {
        "2026-08-10": {"repos": {"r": {"clone": 1, "fetch": 0}}, "unattributed": 2}
    }
    reflog = {
        "2026-08-10": {"repos": {"r": {"clone": 0, "fetch": 3}}, "unattributed": 0},
        "2026-08-14": {"repos": {"r": {"clone": 0, "fetch": 1}}, "unattributed": 0},
    }
    merged = sn.merge_activity(transcript, reflog)
    assert merged["2026-08-10"]["repos"]["r"] == {
        "clone": 1,
        "fetch": 3,
        "via": ["transcript", "reflog"],
    }
    assert merged["2026-08-10"]["unattributed"] == 2
    # the cron day only the reflog can see
    assert merged["2026-08-14"]["repos"]["r"]["via"] == ["reflog"]


def test_self_label_still_reads_merged_entries():
    """`via` rides alongside the counts, so the existing label logic must not
    start reporting it as an activity kind."""
    merged = sn.merge_activity(
        {},
        {"2026-08-14": {"repos": {"r": {"clone": 1, "fetch": 2}}, "unattributed": 0}},
    )
    assert sn.self_label(merged, "r", "2026-08-14") == "clone+fetch"


def test_keep_history_retains_days_the_current_scan_no_longer_sees():
    previous = {"2026-08-01": {"repos": {"alpha": {"clone": 1, "fetch": 0, "via": ["transcript"]}}, "unattributed": 0}}
    current = {"2026-10-20": {"repos": {"beta": {"clone": 0, "fetch": 2, "via": ["reflog"]}}, "unattributed": 1}}
    out = sn.keep_history(previous, current)
    assert set(out) == {"2026-08-01", "2026-10-20"}            # the pruned-transcript day survives
    assert out["2026-08-01"]["repos"]["alpha"]["clone"] == 1
    assert out["2026-10-20"]["repos"]["beta"]["via"] == ["reflog"]


def test_keep_history_is_idempotent_and_takes_the_larger_count():
    previous = {"2026-10-20": {"repos": {"alpha": {"clone": 1, "fetch": 3, "via": ["transcript"]}}, "unattributed": 2}}
    current = {"2026-10-20": {"repos": {"alpha": {"clone": 2, "fetch": 1, "via": ["reflog"]}}, "unattributed": 1}}
    once = sn.keep_history(previous, current)
    assert once["2026-10-20"]["repos"]["alpha"] == {"clone": 2, "fetch": 3, "via": ["reflog", "transcript"]}
    assert once["2026-10-20"]["unattributed"] == 2
    assert sn.keep_history(once, current) == once              # re-running never inflates
    assert previous["2026-10-20"]["repos"]["alpha"]["clone"] == 1   # input not mutated


def test_main_keeps_self_activity_days_from_the_committed_record(wired_main):
    """A run whose scans see nothing must not erase previously recorded own-activity days."""
    old = {"2026-07-15": {"repos": {"alpha": {"clone": 1, "fetch": 0, "via": ["transcript"]}}, "unattributed": 0}}
    sn.SELF_ACTIVITY_PATH.write_text(json.dumps({"days": old}))
    sn.main()
    kept = json.loads(sn.SELF_ACTIVITY_PATH.read_text())["days"]
    assert kept["2026-07-15"]["repos"]["alpha"]["clone"] == 1
