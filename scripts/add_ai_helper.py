#!/usr/bin/env python3
"""Add HOW_TO_USE_WITH_AI.md (+ a README pointer) to GitHub repos.

Default is a DRY RUN: shallow-clones each repo into a work dir and writes the
files locally, printing a summary. Nothing is pushed unless --push is given.

  python3 add_ai_helper.py                 # dry run, public non-archived code repos
  python3 add_ai_helper.py --only karz     # one repo
  python3 add_ai_helper.py --push          # commit + push to default branch
"""

import os

os.environ["GIT_LFS_SKIP_SMUDGE"] = "1"
import argparse
import json
import pathlib
import subprocess
import tempfile

OWNER = "herrrickshaw"
HOME_REPOS = {
    "global-market-research-platform",
    "working-files",
}  # live $HOME origin / rescue copy: a push would diverge from ~/.git
SKIP = {
    ".github",
    "k8s",
    "cloud-map",
    "lfs_archive_work",
    "market-data-artifacts",
    "ai-tools-tracker",
    "mlflow",
}
MARK = "<!-- how-to-use-with-ai -->"

RUN_HINT = {
    "Python": "Python 3.10+ (`python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`, if a requirements file exists)",
    "R": "R 4.x (`Rscript <script>.R`)",
    "C++": "a C++17 compiler and CMake/make (see the build files in the repo)",
    "Shell": "a Unix shell (macOS/Linux; on Windows use WSL)",
    "Jupyter Notebook": "Jupyter or Google Colab (open the `.ipynb` file)",
    "HTML": "just a browser for the `.html` files (some repos also ship Python scripts)",
}

TEMPLATE = """# How to use {name} with an AI assistant

{desc_line}You don't need to be a programmer to use this repository. Get the code,
hand it to an AI assistant (Claude, Gemini, ChatGPT, ...), and ask in plain
language what you want to do.

## 1. Get the code

```bash
git clone https://github.com/{owner}/{name}.git
cd {name}
```

No git? Click the green **Code** button on the repo page, choose **Download ZIP**, and unzip it.

You will usually need {run_hint}.

## 2. Give it to an AI

Pick whichever fits you:

| Option | How |
|---|---|
| **Claude Code / Gemini CLI** (best: the AI can read and run the whole repo) | Run `claude` or `gemini` inside the cloned `{name}` folder, then type your question. |
| **Claude.ai / Gemini / ChatGPT in the browser** | Upload `README.md` and the files you care about (or paste their contents), then ask. For a quick overview, paste the output of `git ls-files` too. |
| **GitHub URL** | Paste `https://github.com/{owner}/{name}` and ask the AI to read it (works only if your AI tool can browse the web; otherwise upload files). |

Tip: start with the README. If the repo is large, tell the AI which folder or file to focus on instead of pasting everything.

## 3. Sample prompts

Copy, paste, and edit the parts in `[brackets]`.

**Understand it**
- "Read this repo's README and explain in plain English what it does, who it is for, and its main folders."
- "List the main scripts or entry points, and what each one does and needs as input."

**Run it**
- "Give me exact step-by-step commands to set this up on [macOS / Windows / Linux] and run it for the first time. Tell me what output I should expect."
- "I got this error: `[paste error]`. What does it mean and how do I fix it?"

**Use it on your own data**
- "I have [describe your file or question]. Show me which script to run and how to adapt it to my data."
- "Write a short example that calls this code to [do something specific], with comments explaining each line."

**Check and trust it**
- "Where do the numbers or data in this repo come from? Point me to the file and line where each source is read."
- "What assumptions and limitations does this analysis have? What would make its results wrong?"

**Change it**
- "Add [a feature / another country / another column]. Show me the minimal change, and explain it."
- "Write a test for [function name] so I know it still works after I change it."

## 4. Good habits

- **Verify before relying on results.** AI can misread code or invent details. Ask it to cite the file and line it is using, and spot-check important numbers yourself.
- **Never paste secrets** (API keys, passwords, personal data) into an AI tool. If the code needs keys, put them in a local `.env` file that you do not upload.
- **Not financial, legal, medical, or engineering advice.** Outputs are for research and education. Check the README and licence for the repo's specific caveats.
- **Be specific.** Say your operating system, what you have already tried, and the exact error text.

Found a problem or have a question? Open an issue on the repo.
"""


def sh(*a, **k):
    return subprocess.run(a, check=True, capture_output=True, text=True, **k).stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--include-private", action="store_true")
    ap.add_argument("--include-archived", action="store_true")
    ap.add_argument(
        "--all",
        action="store_true",
        help="public+private+archived, incl. no-language repos",
    )
    ap.add_argument("--workdir", default=tempfile.mkdtemp(prefix="aihelper_"))
    a = ap.parse_args()

    repos = json.loads(
        sh(
            "gh",
            "repo",
            "list",
            OWNER,
            "--limit",
            "300",
            "--json",
            "name,visibility,isArchived,isFork,primaryLanguage,description,defaultBranchRef",
        )
    )
    work = pathlib.Path(a.workdir)
    work.mkdir(exist_ok=True)
    done = []
    for r in repos:
        n = r["name"]
        if a.only and n not in a.only:
            continue
        if n in HOME_REPOS:
            continue
        if a.all:
            pass
        elif not a.only:
            if n in SKIP or r["isFork"] or not r["primaryLanguage"]:
                continue
            if r["isArchived"] and not a.include_archived:
                continue
            if r["visibility"] == "PRIVATE" and not a.include_private:
                continue
        lang = r["primaryLanguage"]["name"] if r["primaryLanguage"] else ""
        desc = (r["description"] or "").strip()
        body = TEMPLATE.format(
            name=n,
            owner=OWNER,
            desc_line=(desc + "\n\n") if desc else "",
            run_hint=RUN_HINT.get(lang, "the tools named in the README"),
        )
        d = work / n
        unarch = a.push and r["isArchived"]
        if unarch:
            sh("gh", "repo", "unarchive", f"{OWNER}/{n}", "--yes")
        if not d.exists():
            sh("gh", "repo", "clone", f"{OWNER}/{n}", str(d), "--", "--depth", "1")
        (d / "HOW_TO_USE_WITH_AI.md").write_text(body)
        readme = next((p for p in d.iterdir() if p.name.lower() == "readme.md"), None)
        line = f"\n{MARK}\n> **New here?** See [How to use this repo with AI (Claude, Gemini, ChatGPT)](HOW_TO_USE_WITH_AI.md) — clone it, paste it into an AI tool, and ask in plain English.\n"
        if readme:
            t = readme.read_text(errors="replace")
            if MARK not in t:
                lines = t.split("\n", 1)
                head, rest = (lines[0], lines[1] if len(lines) > 1 else "")
                if head.startswith("#"):
                    readme.write_text(head + "\n" + line + "\n" + rest)
                else:
                    readme.write_text(line.lstrip("\n") + "\n" + t)
        else:
            (d / "README.md").write_text(f"# {n}\n{line}")
        status = sh("git", "-C", str(d), "status", "--porcelain").strip()
        if a.push and status:
            try:
                sh("git", "-C", str(d), "add", "HOW_TO_USE_WITH_AI.md", "README.md")
                sh(
                    "git",
                    "-C",
                    str(d),
                    "commit",
                    "-m",
                    "docs: add how-to-use-with-AI helper (clone, paste into Claude/Gemini, sample prompts)\n\nCo-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>",
                )
                sh("git", "-C", str(d), "push")
            except subprocess.CalledProcessError as e:
                print("FAILED", n, (e.stderr or "")[-300:])
                status = "FAILED"
            finally:
                if unarch:
                    sh("gh", "repo", "archive", f"{OWNER}/{n}", "--yes")
        elif unarch:
            sh("gh", "repo", "archive", f"{OWNER}/{n}", "--yes")
        done.append((n, r["visibility"], lang, bool(status)))
    for x in done:
        print(*x)
    print(f"{len(done)} repos; workdir={work}; pushed={a.push}")


if __name__ == "__main__":
    main()
