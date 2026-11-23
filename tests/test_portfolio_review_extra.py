"""More offline tests for scripts/portfolio_review.py: gh_api, traffic windows, report ordering."""
import json
import os
import subprocess
import sys
import types
from datetime import UTC, datetime, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import portfolio_review as pr  # noqa: E402


def day(n):
    return (datetime.now(UTC) - timedelta(days=n)).strftime("%Y-%m-%d")


@pytest.fixture
def env(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(pr, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(pr, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(pr, "REPORT_DIR", tmp_path / "reports")
    monkeypatch.setattr(pr, "SELF_ACTIVITY_PATH", tmp_path / "self_activity.json")
    return tmp_path


def write(env, name, data):
    (env / "data" / f"{name}.json").write_text(json.dumps(data))


def proc(rc=0, out=""):
    return types.SimpleNamespace(returncode=rc, stdout=out, stderr="")


def test_gh_api_contract(monkeypatch):
    seen = {}
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: seen.update(cmd=cmd, kw=kw) or proc(0, '{"ok": true}'))
    assert pr.gh_api("repos/o/r") == {"ok": True}
    assert seen["cmd"] == ["gh", "api", "repos/o/r"] and seen["kw"]["timeout"] == 30
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: proc(0, "<html>"))
    assert pr.gh_api("p") is None
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: proc(1, '{"ok": true}'))
    assert pr.gh_api("p") is None


def test_min_viewers_constant():
    assert pr.MIN_VIEWERS == 3


def test_traffic_missing_or_corrupt_file(env):
    assert pr.traffic_30d("nope", {}) == (None, None, None, None)
    (env / "data" / "bad.json").write_text("{oops")
    assert pr.traffic_30d("bad", {}) == (None, None, None, None)


def test_traffic_30_day_window_boundary(env):
    write(env, "r", {"clones": {day(31): {"count": 100}, day(30): {"count": 5}, day(1): {"count": 2}},
                     "views": {day(31): {"count": 9}, day(30): {"count": 3}}})
    ext, raw, views, viewers = pr.traffic_30d("r", {})
    assert (ext, raw, views, viewers) == (7, 7, 3, None)                      # day 30 is inside, day 31 is not


def test_traffic_excludes_owner_days_from_ext_but_not_raw(env):
    write(env, "r", {"clones": {day(2): {"count": 10}, day(3): {"count": 4}}})
    self_days = {day(2): {"repos": {"r": {"clone": 1, "fetch": 0}}}, day(3): {"repos": {"other": {"clone": 1}}}}
    assert pr.traffic_30d("r", self_days)[:2] == (4, 14)


def test_viewers_use_latest_period_within_14_days(env):
    write(env, "r", {"period_totals": {day(20): {"views": {"uniques": 9}}, day(5): {"views": {"uniques": 4}},
                                        day(8): {"views": {"uniques": 6}}}})
    assert pr.traffic_30d("r", {})[3] == 4
    write(env, "r", {"period_totals": {day(14): {"views": {"uniques": 5}}}})
    assert pr.traffic_30d("r", {})[3] == 5                                    # exactly 14 days old still counts
    write(env, "r", {"period_totals": {day(15): {"views": {"uniques": 5}}}})
    assert pr.traffic_30d("r", {})[3] is None
    write(env, "r", {"period_totals": {day(1): {"clones": {"uniques": 5}}}})
    assert pr.traffic_30d("r", {})[3] is None                                 # latest period carries no views data


def test_load_self_days(env):
    assert pr.load_self_days() == {}
    (env / "self_activity.json").write_text("{oops")
    assert pr.load_self_days() == {}
    (env / "self_activity.json").write_text(json.dumps({"days": {"2026-01-01": {"repos": {}}}}))
    assert pr.load_self_days() == {"2026-01-01": {"repos": {}}}


def run_review(env, monkeypatch, catalog, api, traffic=None):
    (env / "repos.yaml").write_text(catalog)
    for name, data in (traffic or {}).items():
        write(env, name, data)
    monkeypatch.setattr(pr, "gh_api", lambda p: api.get(p.split("/", 2)[2]))
    pr.main()
    return next((env / "reports").glob("REVIEW_*.md")).read_text()


CATALOG = """repos:
  zeta:
    tier: 3
    visibility: PUBLIC
  alpha:
    tier: 1
    visibility: PRIVATE
  gone:
    tier: 2
  old:
    tier: 3
  mid:
    tier: 2
  read:
    tier: 3
  priv:
    tier: 3
"""


def test_main_report_order_summary_and_load_bearing(env, monkeypatch):
    now = datetime.now(UTC)
    recent = (now - timedelta(days=10)).isoformat()
    api = {"zeta": {"pushed_at": recent}, "alpha": {"pushed_at": recent}, "old": {"archived": True, "pushed_at": recent},
           "mid": {"pushed_at": recent}, "read": {"pushed_at": recent}, "priv": {"pushed_at": recent}}
    traffic = {
        "zeta": {"period_totals": {day(1): {"views": {"uniques": 0}}}},
        "mid": {"period_totals": {day(1): {"views": {"uniques": 1}}}},
        "read": {"clones": {day(1): {"count": 3}}, "views": {day(1): {"count": 8}},
                 "period_totals": {day(1): {"views": {"uniques": 3}}}},
    }
    text = run_review(env, monkeypatch, CATALOG, api, traffic)
    rows = [ln for ln in text.splitlines() if ln.startswith("| ") and not ln.startswith("| Verdict")]
    assert [r.split(" | ")[0][2:] for r in rows] == ["MISSING", "NO-DATA", "ARCHIVE-CANDIDATE", "REVIEW", "KEEP", "KEEP", "ARCHIVED"]
    names = [r.split(" | ")[2] for r in rows]
    assert names == ["gone", "priv", "zeta", "mid", "alpha", "read", "old"]     # within a verdict: tier, then name
    assert "Summary: ARCHIVE-CANDIDATE: 1, ARCHIVED: 1, KEEP: 2, MISSING: 1, NO-DATA: 1, REVIEW: 1" in text
    assert "> Kept by readers (1): read (3 viewers)" in text
    assert "> Kept by tier-1 automation exemption: 1." in text
    read_row = next(r for r in rows if " | read | " in r)
    assert read_row == "| KEEP | 3 | read | 10 | 3 | 3 | 3 | 8 | ? |"
    gone_row = next(r for r in rows if " | gone | " in r)
    assert gone_row == "| MISSING | 2 | gone | ? | - | - | - | - | ? |"
    assert "Checklist for the 30-minute pass:" in text


def test_main_report_without_load_bearing_repos(env, monkeypatch):
    text = run_review(env, monkeypatch, "repos:\n  alpha:\n    tier: 1\n", {"alpha": {"pushed_at": datetime.now(UTC).isoformat()}})
    assert "Every KEEP this month is a tier-1 automation exemption (1)." in text
    assert "Kept by readers" not in text
    assert text.splitlines()[0] == f"# Portfolio review — {datetime.now(UTC).strftime('%Y-%m')}"


def test_tier_defaults_to_three_when_absent(env, monkeypatch):
    text = run_review(env, monkeypatch, "repos:\n  bare:\n    visibility: PUBLIC\n", {"bare": {"pushed_at": datetime.now(UTC).isoformat()}})
    assert "| NO-DATA | 3 | bare |" in text
