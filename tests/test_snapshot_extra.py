"""Additional offline tests for scripts/snapshot.py: gh wrappers, CI-run counting, releases, transcript
scan caching, reflog edges, committed-record helpers. No network; every path in tmp_path."""
import json
import subprocess
import types
from datetime import UTC, datetime

import pytest

from scripts import snapshot as sn


def proc(returncode=0, stdout=""):
    return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")


@pytest.fixture
def paths(monkeypatch, tmp_path):
    monkeypatch.setattr(sn, "DATA_DIR", tmp_path / "data")
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(sn, "SELF_ACTIVITY_PATH", tmp_path / "self_activity.json")
    monkeypatch.setattr(sn, "SELF_CACHE_PATH", tmp_path / ".cache.json")
    monkeypatch.setattr(sn, "TRANSCRIPT_ROOT", tmp_path / "transcripts")
    return tmp_path


# ---- gh wrappers ----------------------------------------------------------------------------------

def test_gh_api_invokes_gh_with_timeout_and_survives_garbage(monkeypatch):
    seen = {}
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: seen.update(cmd=cmd, kw=kw) or proc(0, "not json"))
    assert sn.gh_api("repos/x/y") is None
    assert seen["cmd"] == ["gh", "api", "repos/x/y"] and seen["kw"]["timeout"] == 30 and seen["kw"]["check"] is False
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: proc(0, '{"a": 1}'))
    assert sn.gh_api("p") == {"a": 1}
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: proc(1, '{"a": 1}'))
    assert sn.gh_api("p") is None                                  # non-zero exit wins over valid stdout


def test_gh_api_lines_paginates_and_drops_blank_lines(monkeypatch):
    seen = {}
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: seen.update(cmd=cmd, kw=kw) or proc(0, "a\n\nb\n"))
    assert sn.gh_api_lines("runs", ".x") == ["a", "b"]
    assert seen["cmd"] == ["gh", "api", "--paginate", "runs", "--jq", ".x"] and seen["kw"]["timeout"] == 120
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: proc(2, "a\n"))
    assert sn.gh_api_lines("runs", ".x") == []


def test_fetch_ci_runs_counts_per_day_and_skips_second_call_without_workflows(monkeypatch):
    calls = []
    monkeypatch.setattr(sn, "gh_api", lambda p: calls.append(p) or {"total_count": 0})
    monkeypatch.setattr(sn, "gh_api_lines", lambda p, j: pytest.fail("no workflows -> no run listing"))
    assert sn.fetch_ci_runs("r", "2026-07-01") == {}
    monkeypatch.setattr(sn, "gh_api", lambda p: None)
    assert sn.fetch_ci_runs("r", "2026-07-01") == {}

    monkeypatch.setattr(sn, "gh_api", lambda p: {"total_count": 3})
    seen = {}
    monkeypatch.setattr(sn, "gh_api_lines", lambda p, j: seen.update(p=p, j=j) or [
        "2026-07-01T01:00:00Z", "2026-07-01T23:59:59Z", "2026-07-02T00:00:00Z"])
    assert sn.fetch_ci_runs("repo", "2026-06-30") == {"2026-07-01": 2, "2026-07-02": 1}
    assert seen["p"] == "repos/herrrickshaw/repo/actions/runs?per_page=100&created=%3E%3D2026-06-30"
    assert seen["j"] == ".workflow_runs[].created_at"


def test_snapshot_releases_sums_assets_under_todays_utc_date(monkeypatch):
    monkeypatch.setattr(sn, "gh_api", lambda p: [
        {"assets": [{"download_count": 3}, {}, {"download_count": 4}]}, {"assets": []}, {}])
    data = sn.snapshot_releases("r", {"releases": {}})
    assert data["releases"] == {str(datetime.now(UTC).date()): 7}
    assert sn.today() == datetime.now(UTC).date()


@pytest.mark.parametrize("payload", [None, []])
def test_snapshot_releases_leaves_data_alone_without_releases(monkeypatch, payload):
    monkeypatch.setattr(sn, "gh_api", lambda p: payload)
    assert sn.snapshot_releases("r", {"releases": {"x": 1}}) == {"releases": {"x": 1}}


# ---- repo data files ------------------------------------------------------------------------------

def test_load_repo_data_defaults_and_backfills_new_keys(paths):
    assert sn.load_repo_data("new") == {"clones": {}, "views": {}, "releases": {}, "period_totals": {}, "ci_runs": {}}
    (paths / "data" / "old.json").write_text(json.dumps({"clones": {"2026-01-01": {"count": 1}}, "views": {}, "releases": {}}))
    data = sn.load_repo_data("old")
    assert data["period_totals"] == {} and data["ci_runs"] == {} and data["clones"]["2026-01-01"]["count"] == 1


def test_save_repo_data_is_sorted_indented_and_newline_terminated(paths):
    sn.save_repo_data("r", {"b": 1, "a": {"y": 2, "x": 1}})
    text = (paths / "data" / "r.json").read_text()
    assert text.endswith("}\n") and text.index('"a"') < text.index('"b"') and text.index('"x"') < text.index('"y"')
    assert text.startswith('{\n  "a"')
    assert sn.load_repo_data("r")["b"] == 1


# ---- transcript scanning ---------------------------------------------------------------------------

def tool_line(cmd, ts="2026-08-01T10:00:00Z"):
    return json.dumps({"timestamp": ts, "message": {"content": [{"type": "tool_use", "input": {"command": cmd}}]}})


def test_scan_transcript_classifies_clone_fetch_pull_and_ignores_the_rest(tmp_path):
    f = tmp_path / "t.jsonl"
    f.write_text("\n".join([
        tool_line("git clone https://github.com/herrrickshaw/alpha.git"),
        tool_line("gh repo clone herrrickshaw/alpha"),
        tool_line("cd /x/alpha && git pull --ff-only"),
        tool_line("git fetch origin && echo beta"),
        tool_line("git fetch origin"),                                  # no repo named -> unattributed
        tool_line("ls alpha"),                                          # not a clone/fetch at all
        tool_line("echo about to clone alpha, then fetch notes"),       # mentions the words, but is no git command
        json.dumps({"timestamp": "2026-08-01T10:00:00Z", "message": {"content": "git clone alpha"}}),   # text, not a list
        json.dumps({"message": {"content": [{"type": "tool_use", "input": {"command": "git clone alpha"}}]}}),  # no timestamp
        json.dumps({"timestamp": "2026-08-01T10:00:00Z", "message": {"content": [{"type": "tool_use", "input": {"command": 5, "description": "clone"}}]}}),
        json.dumps({"timestamp": "2026-08-01T10:00:00Z", "message": {"content": ["clone", {"type": "text", "text": "clone"}]}}),
        "clone but not json",
        "",
    ]))
    days = sn._scan_transcript(f, {"alpha", "beta"})
    assert set(days) == {"2026-08-01"}
    d = days["2026-08-01"]
    assert d["repos"]["alpha"] == {"clone": 2, "fetch": 1}                 # two clones, one pull counted as fetch
    assert d["repos"]["beta"] == {"clone": 0, "fetch": 1}
    assert d["unattributed"] == 1


def test_scan_transcript_clone_with_fetch_counts_as_clone_only(tmp_path):
    f = tmp_path / "t.jsonl"
    f.write_text(tool_line("git clone https://github.com/herrrickshaw/alpha.git && git fetch --all") + "\n")
    assert sn._scan_transcript(f, {"alpha"})["2026-08-01"]["repos"]["alpha"] == {"clone": 1, "fetch": 0}


def test_scan_transcript_unreadable_path_is_empty(tmp_path):
    assert sn._scan_transcript(tmp_path / "missing.jsonl", {"a"}) == {}


def test_scan_self_activity_parses_new_files_and_caches_by_mtime(paths, monkeypatch, capsys):
    root = paths / "transcripts" / "proj"
    root.mkdir(parents=True)
    a = root / "a.jsonl"
    a.write_text(tool_line("git clone https://github.com/herrrickshaw/alpha.git") + "\n")
    b = root / "b.jsonl"
    b.write_text(tool_line("echo nothing") + "\n")
    merged = sn.scan_self_activity({"alpha"})
    assert merged == {"2026-08-01": {"repos": {"alpha": {"clone": 1, "fetch": 0}}, "unattributed": 0}}
    assert "2 transcripts parsed" in capsys.readouterr().out
    cache = json.loads(sn.SELF_CACHE_PATH.read_text())
    assert list(cache["by_file"]) == ["proj/a.jsonl"] and cache["scanned_through"] > 0

    calls = []
    real = sn._scan_transcript
    monkeypatch.setattr(sn, "_scan_transcript", lambda p, k: calls.append(p.name) or real(p, k))
    assert sn.scan_self_activity({"alpha"}) == merged
    assert calls == []                                                       # nothing changed -> nothing re-parsed
    assert "0 transcripts parsed" in capsys.readouterr().out


def test_scan_self_activity_reparses_changed_file_and_replaces_its_contribution(paths):
    root = paths / "transcripts"
    root.mkdir()
    f = root / "a.jsonl"
    f.write_text(tool_line("git clone alpha") + "\n")
    assert sn.scan_self_activity({"alpha"})["2026-08-01"]["repos"]["alpha"]["clone"] == 1
    f.write_text(tool_line("git clone alpha") + "\n" + tool_line("git clone alpha") + "\n")
    import os
    st = f.stat()
    os.utime(f, (st.st_atime, st.st_mtime + 10))
    assert sn.scan_self_activity({"alpha"})["2026-08-01"]["repos"]["alpha"]["clone"] == 2      # replaced, not 3
    f.write_text("nothing here\n")
    os.utime(f, (st.st_atime, st.st_mtime + 20))
    assert sn.scan_self_activity({"alpha"}) == {}
    assert json.loads(sn.SELF_CACHE_PATH.read_text())["by_file"] == {}


def test_scan_self_activity_rescan_ignores_cache_and_survives_corrupt_cache(paths):
    root = paths / "transcripts"
    root.mkdir()
    (root / "a.jsonl").write_text(tool_line("git clone alpha") + "\n")
    sn.scan_self_activity({"alpha"})
    sn.SELF_CACHE_PATH.write_text("{corrupt")
    assert sn.scan_self_activity({"alpha"})["2026-08-01"]["repos"]["alpha"]["clone"] == 1
    assert sn.scan_self_activity({"alpha"}, rescan=True)["2026-08-01"]["repos"]["alpha"]["clone"] == 1


def test_scan_self_activity_without_transcript_dir(paths, capsys):
    assert sn.scan_self_activity({"alpha"}) == {}
    assert json.loads(sn.SELF_CACHE_PATH.read_text()) == {"by_file": {}, "scanned_through": 0.0}
    assert "0 dates flagged (0 transcripts parsed)" in capsys.readouterr().out


def test_scan_self_activity_merges_same_day_across_files(paths):
    root = paths / "transcripts"
    root.mkdir()
    (root / "a.jsonl").write_text(tool_line("git clone alpha") + "\n" + tool_line("git fetch origin") + "\n")
    (root / "b.jsonl").write_text(tool_line("git pull alpha") + "\n")
    merged = sn.scan_self_activity({"alpha"})
    assert merged["2026-08-01"] == {"repos": {"alpha": {"clone": 1, "fetch": 1}}, "unattributed": 1}


# ---- local clones / reflog -------------------------------------------------------------------------

def test_remote_repo_reads_urls_and_requires_tracked_names(tmp_path):
    cfg = tmp_path / "config"
    cfg.write_text('[core]\n\turl_note = ignored\n[remote "origin"]\n\turl = git@github.com:herrrickshaw/alpha.git\n'
                   '[remote "up"]\n\turl = https://github.com/other/zed.git\n')
    assert sn._remote_repo(cfg, {"alpha"}) == "alpha"
    assert sn._remote_repo(cfg, {"zed"}) is None                              # wrong owner
    assert sn._remote_repo(cfg, set()) is None
    assert sn._remote_repo(tmp_path / "missing", {"alpha"}) is None
    cfg.write_text('[remote "origin"]\n\turl = https://github.com/herrrickshaw/beta\n')
    assert sn._remote_repo(cfg, {"beta"}) == "beta"                           # no .git suffix


def test_reflog_utc_day_bounds():
    assert sn.reflog_utc_day("main@{1104537600}") == "2005-01-01"             # the floor itself is valid
    assert sn.reflog_utc_day("main@{1104537599}") is None
    assert sn.reflog_utc_day("HEAD@{0}") is None and sn.reflog_utc_day("HEAD") is None
    assert sn.reflog_utc_day("x@{1787184411}") == "2026-08-20"


def test_scan_reflog_activity_counts_and_skips_failures(monkeypatch):
    out = {"/a": proc(0, "main@{1787184411}|clone: from https://x\nmain@{1787184412}|pull --ff-only: fast\n"
                          "main@{1787184413}|fetch origin: x\nmain@{1787184414}|commit: clone the repo\n"
                          "HEAD@{0}|fetch origin: ordinal selector\n"),
           "/b": proc(128, "main@{1787184411}|clone: x\n")}
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: out[cmd[2]])
    days = sn.scan_reflog_activity({"alpha": ["/a", "/b"]})
    assert days == {"2026-08-20": {"repos": {"alpha": {"clone": 1, "fetch": 2}}, "unattributed": 0}}
    assert sn.scan_reflog_activity({}) == {}


def test_discover_local_clones_respects_depth_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(sn, "LOCAL_SCAN_ROOT", tmp_path)
    monkeypatch.setattr(sn, "LOCAL_SCAN_DEPTH", 2)
    for rel in ("a", "a/b", "a/b/c"):
        d = tmp_path / rel / ".git"
        d.mkdir(parents=True)
        (d / "config").write_text(f'[remote "origin"]\n\turl = https://github.com/herrrickshaw/{rel.replace("/", "-")}\n')
    known = {"a", "a-b", "a-b-c"}
    found = sn.discover_local_clones(known)
    assert set(found) == {"a", "a-b"}                                          # depth 2 (a/b/c) is beyond the limit
    assert found["a"] == [str(tmp_path / "a")]


# ---- committed record --------------------------------------------------------------------------------

def test_load_previous_self_activity(paths):
    assert sn.load_previous_self_activity() == {}
    sn.SELF_ACTIVITY_PATH.write_text("{oops")
    assert sn.load_previous_self_activity() == {}
    sn.SELF_ACTIVITY_PATH.write_text(json.dumps({"days": {"2026-01-01": {"repos": {}, "unattributed": 0}}}))
    assert sn.load_previous_self_activity() == {"2026-01-01": {"repos": {}, "unattributed": 0}}
    sn.SELF_ACTIVITY_PATH.write_text(json.dumps({"other": 1}))
    assert sn.load_previous_self_activity() == {}


def test_write_self_activity_stores_only_dates_names_and_counts(paths):
    merged = {"2026-02-02": {"repos": {"b": {"clone": 1, "fetch": 0, "via": ["reflog"]}}, "unattributed": 2},
              "2026-01-01": {"repos": {}, "unattributed": 0}}
    sn.write_self_activity(merged, {"zeta": ["/p/z"], "alpha": ["/p/a"]})
    text = sn.SELF_ACTIVITY_PATH.read_text()
    assert text.endswith("}\n") and "/p/" not in text                         # local paths never persisted
    data = json.loads(text)
    assert data["repos_with_local_copy"] == ["alpha", "zeta"]
    assert list(data["days"]) == ["2026-01-01", "2026-02-02"]
    assert data["_comment"].startswith("Dates on which the account owner ran git clone")


def test_keep_history_does_not_mutate_inputs():
    prev = {"2026-01-01": {"repos": {"a": {"clone": 1, "fetch": 0, "via": ["x"]}}, "unattributed": 1}}
    cur = {"2026-01-01": {"repos": {"a": {"clone": 0, "fetch": 3, "via": ["y"]}}, "unattributed": 0}}
    out = sn.keep_history(prev, cur)
    assert out["2026-01-01"] == {"repos": {"a": {"clone": 1, "fetch": 3, "via": ["x", "y"]}}, "unattributed": 1}
    assert prev["2026-01-01"]["repos"]["a"] == {"clone": 1, "fetch": 0, "via": ["x"]}
    assert cur["2026-01-01"]["repos"]["a"]["via"] == ["y"]


def test_merge_activity_sums_counts_per_source():
    t = {"d": {"repos": {"a": {"clone": 1, "fetch": 0}}, "unattributed": 2}}
    r = {"d": {"repos": {"a": {"clone": 0, "fetch": 4}}, "unattributed": 1}}
    m = sn.merge_activity(t, r)
    assert m["d"] == {"repos": {"a": {"clone": 1, "fetch": 4, "via": ["transcript", "reflog"]}}, "unattributed": 3}


def test_scan_self_activity_skips_files_whose_stat_fails(paths, monkeypatch):
    root = paths / "transcripts"
    root.mkdir()
    (root / "a.jsonl").write_text(tool_line("git clone alpha") + "\n")
    real_stat = type(root).stat

    def flaky(self, *a, **k):
        if self.name == "a.jsonl":
            raise OSError("vanished")
        return real_stat(self, *a, **k)

    monkeypatch.setattr(type(root), "stat", flaky)
    assert sn.scan_self_activity({"alpha"}) == {}
