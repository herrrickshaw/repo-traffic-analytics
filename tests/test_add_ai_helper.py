"""scripts/add_ai_helper.py: repo selection, file generation and the push path, with `sh` (git/gh) faked.
Nothing is cloned or pushed; every path is under tmp_path."""

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import add_ai_helper as ah


def repo(name, lang="Python", vis="PUBLIC", archived=False, fork=False, desc="A repo"):
    return {
        "name": name,
        "visibility": vis,
        "isArchived": archived,
        "isFork": fork,
        "primaryLanguage": {"name": lang} if lang else None,
        "description": desc,
        "defaultBranchRef": {"name": "main"},
    }


class FakeGit:
    """Fake for ah.sh. `gh repo clone` creates the directory (optionally with a README)."""

    def __init__(
        self, repos, readmes=None, status="M HOW_TO_USE_WITH_AI.md", fail_push=False
    ):
        self.repos, self.readmes, self.status, self.fail_push = (
            repos,
            readmes or {},
            status,
            fail_push,
        )
        self.calls = []

    def __call__(self, *a, **k):
        self.calls.append(a)
        if a[:3] == ("gh", "repo", "list"):
            return json.dumps(self.repos)
        if a[:3] == ("gh", "repo", "clone"):
            name = a[3].split("/")[1]
            d = pathlib.Path(a[4])
            d.mkdir(parents=True)
            if name in self.readmes:
                (d / "README.md").write_text(self.readmes[name])
            return ""
        if a[0] == "git" and "status" in a:
            return self.status
        if a[0] == "git" and "push" in a and self.fail_push:
            err = ah.subprocess.CalledProcessError(1, a)
            err.stderr = "remote rejected"
            raise err
        return ""

    def verbs(self):
        return [
            " ".join(c[:3]) if c[0] == "gh" else " ".join(c[3:5]) for c in self.calls
        ]


@pytest.fixture
def run(monkeypatch, tmp_path):
    def _run(fake, *argv):
        monkeypatch.setattr(ah, "sh", fake)
        work = tmp_path / "work"
        monkeypatch.setattr(
            sys, "argv", ["add_ai_helper", "--workdir", str(work), *argv]
        )
        ah.main()
        return work

    return _run


def test_default_selection_skips_forks_archived_private_nolang_skiplist_and_home(
    run, capsys
):
    fake = FakeGit(
        [
            repo("keep"),
            repo("fork", fork=True),
            repo("old", archived=True),
            repo("priv", vis="PRIVATE"),
            repo("nolang", lang=None),
            repo("mlflow"),
            repo(".github"),
            repo("global-market-research-platform"),
            repo("working-files"),
        ]
    )
    work = run(fake)
    assert sorted(p.name for p in work.iterdir()) == ["keep"]
    out = capsys.readouterr().out
    assert (
        "keep PUBLIC Python True" in out
        and "1 repos; workdir=" in out
        and "pushed=False" in out
    )
    assert not any(
        c[0] == "git" and "push" in c for c in fake.calls
    )  # dry run never pushes


def test_flags_widen_the_selection(run):
    repos = [
        repo("keep"),
        repo("old", archived=True),
        repo("priv", vis="PRIVATE"),
        repo("nolang", lang=None),
        repo("fork", fork=True),
    ]
    assert sorted(
        p.name for p in run(FakeGit(repos), "--include-archived").iterdir()
    ) == ["keep", "old"]


def test_include_private(run):
    repos = [
        repo("keep"),
        repo("priv", vis="PRIVATE"),
        repo("nolang", lang=None),
        repo("old", archived=True),
        repo("mlflow"),
    ]
    assert sorted(
        p.name for p in run(FakeGit(repos), "--include-private").iterdir()
    ) == ["keep", "priv"]


def test_all_flag_takes_everything_except_home_repos(monkeypatch, tmp_path):
    repos = [
        repo("keep"),
        repo("priv", vis="PRIVATE"),
        repo("nolang", lang=None),
        repo("old", archived=True),
        repo("mlflow"),
        repo("working-files"),
    ]
    monkeypatch.setattr(ah, "sh", FakeGit(repos))
    work = tmp_path / "w"
    monkeypatch.setattr(sys, "argv", ["x", "--workdir", str(work), "--all"])
    ah.main()
    assert sorted(p.name for p in work.iterdir()) == [
        "keep",
        "mlflow",
        "nolang",
        "old",
        "priv",
    ]


def test_only_bypasses_filters_but_still_skips_home_repos(run):
    repos = [repo("fork", fork=True), repo("keep"), repo("working-files")]
    assert sorted(
        p.name for p in run(FakeGit(repos), "--only", "fork", "working-files").iterdir()
    ) == ["fork"]


def test_generated_how_to_uses_repo_description_and_language_hint(run):
    work = run(
        FakeGit(
            [
                repo("py", desc="Does science"),
                repo("rr", lang="R", desc=""),
                repo("oth", lang="Rust"),
            ]
        ),
        "--all",
    )
    py = (work / "py" / "HOW_TO_USE_WITH_AI.md").read_text()
    assert py.startswith(
        "# How to use py with an AI assistant\n\nDoes science\n\nYou don't need"
    )
    assert (
        "git clone https://github.com/herrrickshaw/py.git" in py
        and "Python 3.10+" in py
    )
    rr = (work / "rr" / "HOW_TO_USE_WITH_AI.md").read_text()
    assert (
        rr.startswith("# How to use rr with an AI assistant\n\nYou don't need")
        and "Rscript <script>.R" in rr
    )
    assert (
        "the tools named in the README"
        in (work / "oth" / "HOW_TO_USE_WITH_AI.md").read_text()
    )


def test_readme_pointer_inserted_after_heading_once(run):
    work = run(FakeGit([repo("a")], readmes={"a": "# Title\n\nBody text\n"}))
    text = (work / "a" / "README.md").read_text()
    assert text.startswith("# Title\n\n" + ah.MARK + "\n> **New here?**")
    assert text.endswith("Body text\n") and text.count(ah.MARK) == 1


def test_readme_without_heading_gets_pointer_first(run):
    work = run(FakeGit([repo("a")], readmes={"a": "plain first line\n"}))
    text = (work / "a" / "README.md").read_text()
    assert text.startswith(ah.MARK) and text.endswith("plain first line\n")


def test_readme_already_marked_is_left_alone(run):
    original = f"# T\n{ah.MARK}\nalready\n"
    work = run(FakeGit([repo("a")], readmes={"a": original}))
    assert (work / "a" / "README.md").read_text() == original


def test_missing_readme_is_created_with_title_and_pointer(run):
    work = run(FakeGit([repo("a"), repo("b")], readmes={}))
    assert (work / "a" / "README.md").read_text().startswith("# a\n\n" + ah.MARK)
    assert "How to use this repo with AI" in (work / "b" / "README.md").read_text()


def test_existing_workdir_checkout_is_reused_not_recloned(monkeypatch, tmp_path):
    work = tmp_path / "w"
    (work / "a").mkdir(parents=True)
    fake = FakeGit([repo("a")])
    monkeypatch.setattr(ah, "sh", fake)
    monkeypatch.setattr(sys, "argv", ["x", "--workdir", str(work)])
    ah.main()
    assert not any(c[:3] == ("gh", "repo", "clone") for c in fake.calls)
    assert (work / "a" / "HOW_TO_USE_WITH_AI.md").exists()


def test_push_commits_only_the_two_files_and_pushes(run, capsys):
    fake = FakeGit([repo("a")])
    run(fake, "--push")
    git = [c for c in fake.calls if c[0] == "git"]
    assert [c[3] for c in git] == ["status", "add", "commit", "push"]
    assert git[1][4:] == ("HOW_TO_USE_WITH_AI.md", "README.md")
    assert git[2][4] == "-m" and git[2][5].startswith(
        "docs: add how-to-use-with-AI helper"
    )
    assert git[2][5].endswith(
        "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
    )
    assert "pushed=True" in capsys.readouterr().out


def test_push_skipped_when_nothing_changed(run, capsys):
    fake = FakeGit([repo("a")], status="")
    run(fake, "--push")
    assert not any(
        c[0] == "git" and c[3] in ("add", "commit", "push") for c in fake.calls
    )
    assert "a PUBLIC Python False" in capsys.readouterr().out


def test_push_failure_is_reported_and_does_not_abort_the_loop(run, capsys):
    fake = FakeGit([repo("a"), repo("b")], fail_push=True)
    run(fake, "--push")
    out = capsys.readouterr().out
    assert out.count("FAILED") == 2 and "remote rejected" in out
    assert "a PUBLIC Python True" in out and "b PUBLIC Python True" in out


def test_archived_repo_is_unarchived_around_a_push_and_rearchived(run):
    fake = FakeGit([repo("old", archived=True)])
    run(fake, "--push", "--include-archived")
    gh = [
        " ".join(c[:4])
        for c in fake.calls
        if c[0] == "gh" and c[1] == "repo" and c[2] in ("archive", "unarchive")
    ]
    assert gh == [
        "gh repo unarchive herrrickshaw/old",
        "gh repo archive herrrickshaw/old",
    ]
    order = [c[1] if c[0] == "gh" else c[3] for c in fake.calls]
    assert order.index("repo") < order.index("push")


def test_archived_repo_with_nothing_to_push_is_rearchived(run):
    fake = FakeGit([repo("old", archived=True)], status="")
    run(fake, "--push", "--include-archived")
    names = [
        c[2]
        for c in fake.calls
        if c[:2] == ("gh", "repo") and c[2] in ("archive", "unarchive")
    ]
    assert names == ["unarchive", "archive"]
    assert not any(
        c[0] == "git" and c[3] in ("add", "commit", "push") for c in fake.calls
    )


def test_dry_run_never_touches_archive_state(run):
    fake = FakeGit([repo("old", archived=True)])
    run(fake, "--include-archived")
    assert [
        c
        for c in fake.calls
        if c[:2] == ("gh", "repo") and c[2] in ("archive", "unarchive")
    ] == []


def test_failed_push_still_rearchives(run):
    fake = FakeGit([repo("old", archived=True)], fail_push=True)
    run(fake, "--push", "--include-archived")
    names = [
        c[2]
        for c in fake.calls
        if c[:2] == ("gh", "repo") and c[2] in ("archive", "unarchive")
    ]
    assert names == ["unarchive", "archive"]  # `finally` restores the archived state


def test_sh_wrapper_runs_a_command_and_returns_stdout(monkeypatch):
    seen = {}

    class R:
        stdout = "out"

    def run(cmd, **kw):
        seen.update(cmd=cmd, kw=kw)
        return R()

    monkeypatch.undo()
    monkeypatch.setattr(ah.subprocess, "run", run)
    assert ah.sh("echo", "x") == "out"
    assert seen["cmd"] == ("echo", "x") and seen["kw"] == {
        "check": True,
        "capture_output": True,
        "text": True,
    }
