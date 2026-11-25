"""Tests for scripts/portfolio_review.py.

No network: gh_api is replaced with a stub, and every path (catalog, data,
reports, self-activity) points into tmp_path. snapshot.py is never run.
"""

import json
import os
import sys
from datetime import UTC, datetime, timedelta

import pytest

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"
    ),
)
import portfolio_review as pr


def _day(n):
    return (datetime.now(UTC) - timedelta(days=n)).strftime("%Y-%m-%d")


@pytest.fixture
def env(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(pr, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(pr, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(pr, "REPORT_DIR", tmp_path / "reports")
    monkeypatch.setattr(pr, "SELF_ACTIVITY_PATH", tmp_path / "self_activity.json")
    return tmp_path


def _write_data(env, name, data):
    (env / "data" / f"{name}.json").write_text(json.dumps(data))


# ── decide ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "args,expected",
    [
        ((1, None, False, False), "MISSING"),  # 404 beats everything
        ((1, 50, True, True), "ARCHIVED"),
        ((1, 0, True, False), "KEEP"),  # tier-1 automation exemption
        ((1, None, True, False), "KEEP"),
        ((3, None, True, False), "NO-DATA"),
        ((3, pr.MIN_VIEWERS, True, False), "KEEP"),  # boundary is inclusive
        ((2, pr.MIN_VIEWERS - 1, True, False), "REVIEW"),
        ((3, 0, True, False), "ARCHIVE-CANDIDATE"),
    ],
)
def test_decide_verdicts(args, expected):
    assert pr.decide(*args) == expected


# ── load_catalog ─────────────────────────────────────────────────────────


def test_load_catalog_parses_keys_and_strips_comments_and_quotes(env):
    (env / "repos.yaml").write_text(
        "# header\nrepos:\n"
        "  alpha:\n    tier: 1\n    visibility: PRIVATE  # created 2026-09-09\n"
        '    purpose: "does things"\n'
        "  beta.repo-2:\n    tier: 3\n"
    )
    cat = pr.load_catalog()
    assert cat == {
        "alpha": {"tier": "1", "visibility": "PRIVATE", "purpose": "does things"},
        "beta.repo-2": {"tier": "3"},
    }


# ── load_self_days ───────────────────────────────────────────────────────


def test_load_self_days_missing_or_corrupt_is_empty(env):
    assert pr.load_self_days() == {}
    (env / "self_activity.json").write_text("{bad")
    assert pr.load_self_days() == {}
    (env / "self_activity.json").write_text(
        json.dumps({"days": {"2026-10-01": {"repos": {"a": 1}}}})
    )
    assert pr.load_self_days() == {"2026-10-01": {"repos": {"a": 1}}}


# ── traffic_30d ──────────────────────────────────────────────────────────


def test_traffic_30d_no_file_or_bad_json(env):
    assert pr.traffic_30d("nope", {}) == (None, None, None, None)
    (env / "data" / "bad.json").write_text("{")
    assert pr.traffic_30d("bad", {}) == (None, None, None, None)


def test_traffic_30d_window_and_self_day_exclusion(env):
    _write_data(
        env,
        "r",
        {
            "clones": {
                _day(1): {"count": 5},
                _day(10): {"count": 7},
                _day(40): {"count": 100},
            },
            "views": {_day(2): {"count": 3}, _day(31): {"count": 50}},
            "period_totals": {
                _day(8): {"views": {"uniques": 2}},
                _day(1): {"views": {"uniques": 4}},
            },
        },
    )
    self_days = {_day(10): {"repos": {"r": 1}}, _day(1): {"repos": {"other": 1}}}
    external, raw, views, viewers = pr.traffic_30d("r", self_days)
    assert raw == 12  # 40-day-old clone excluded
    assert external == 5  # owner's own clone day dropped
    assert views == 3  # 31-day-old view excluded
    assert viewers == 4  # latest 14-day window wins


def test_traffic_30d_viewers_none_when_no_period_totals(env):
    _write_data(env, "r", {"clones": {}, "views": {}})
    assert pr.traffic_30d("r", {})[3] is None


def test_traffic_30d_ignores_viewer_count_from_a_long_expired_window(env):
    """`viewers` is reported as GitHub's *trailing* 14-day distinct count. If
    the newest recorded window ended months ago (snapshots stopped for this
    repo), that number says nothing about current readership and must not be
    allowed to vote KEEP."""
    _write_data(
        env,
        "r",
        {
            "clones": {},
            "views": {},
            "period_totals": {_day(90): {"views": {"uniques": 9}}},
        },
    )
    viewers = pr.traffic_30d("r", {})[3]
    assert viewers is None
    assert pr.decide(3, viewers) == "NO-DATA"


# ── main (report) ────────────────────────────────────────────────────────


def test_main_writes_ordered_report(env, monkeypatch, capsys):
    (env / "repos.yaml").write_text(
        "repos:\n"
        "  gone:\n    tier: 2\n"
        "  auto:\n    tier: 1\n    visibility: PUBLIC\n"
        "  read:\n    tier: 3\n"
        "  dusty:\n    tier: 3\n"
        "  old:\n    tier: 3\n"
    )
    _write_data(env, "read", {"period_totals": {_day(1): {"views": {"uniques": 5}}}})
    _write_data(env, "dusty", {"period_totals": {_day(1): {"views": {"uniques": 0}}}})
    pushed = (datetime.now(UTC) - timedelta(days=3)).isoformat().replace("+00:00", "Z")
    api = {
        "repos/herrrickshaw/auto": {"pushed_at": pushed},
        "repos/herrrickshaw/read": {"pushed_at": pushed},
        "repos/herrrickshaw/dusty": {"pushed_at": pushed},
        "repos/herrrickshaw/old": {"archived": True},
    }
    monkeypatch.setattr(pr, "gh_api", lambda path: api.get(path))
    pr.main()
    out = env / "reports" / f"REVIEW_{datetime.now(UTC).strftime('%Y-%m')}.md"
    text = out.read_text()
    table = [
        l
        for l in text.splitlines()
        if l.startswith("| ") and not l.startswith("| Verdict")
    ]
    assert [row.split(" | ")[0].lstrip("| ") for row in table] == [
        "MISSING",
        "ARCHIVE-CANDIDATE",
        "KEEP",
        "KEEP",
        "ARCHIVED",
    ]
    assert "| KEEP | 1 | auto | 3 |" in text
    assert "Kept by readers (1): read (5 viewers)" in text
    assert "Summary: ARCHIVE-CANDIDATE: 1, ARCHIVED: 1, KEEP: 2, MISSING: 1" in text
