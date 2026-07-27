# repo-traffic-analytics

Daily traffic snapshots for every repo under `herrrickshaw` — private included —
run via `scripts/snapshot.py` on a scheduled task.

> ⚠️ This repo is **private and must stay private**: `summary.csv`,
> `views_summary.csv` and `data/` now carry the names and traffic of private
> repos. Publishing it would disclose them.

## What this tracks

- **Clones**: `GET /repos/{owner}/{repo}/traffic/clones` — daily clone count + unique cloners
- **Views**: `GET /repos/{owner}/{repo}/traffic/views` — daily page-view count + unique visitors
- **Release downloads**: cumulative asset `download_count` for repos with GitHub Releases

## What this does NOT and CANNOT track

GitHub does not expose visitor IP addresses, geographic origin, or any way to
distinguish specific machines/sources to repo owners, on any plan tier. The
"uniques" figures are anonymized by GitHub itself before repo owners ever see
them. There is no way to filter these numbers by IP or exclude specific known
clients (e.g. CI runners, backup scripts) after the fact — this dataset is the
full ceiling of what GitHub's API provides.

GitHub also only retains 14 days of clones/views history — this repo exists to
accumulate a longer history via daily snapshots (upserted by date, so re-runs
never duplicate).

Private repos are included. The traffic API serves them to the owner, and
leaving them out meant the portfolio review had no readership data for them and
could only score them as unread — a bar they were structurally unable to clear.

## Known noise in the data

**A large share of clone traffic is the account owner's own work — this is now
detected and excluded automatically.** On every run `snapshot.py` scans local
session transcripts (`~/.claude/projects/**/*.jsonl`) for `git clone` /
`gh repo clone` / `git fetch`, resolves which tracked repos each command touched,
and records the dates in `self_activity.json`. Those repo-days are flagged in
`summary.csv` and dropped from `clones_7d_ex_self` in `views_summary.csv`.

Nothing is removed or hidden: raw counts stay in both files, the raw
`clones_7d_sum` sits next to the cleaned column, and `self_days_7d` says how
many days were dropped. Views are never adjusted — browser page loads aren't
produced by git commands.

Effect on the current week: `digital-twin-for-ipa` 517 → **249**,
`india-trade-sector-policy-recommendations` 379 → **83**,
`stock-portfolio-evaluator` 20 → **2**. `FCI-warehouse-MSPvsMSV` stays at 229
(no matching commands), which is what a genuinely external repo looks like.

Days with 5+ own commands average **433 clones/day**; the three days with none
average **108**. Every large spike lines up with a working session:

| Date | Own commands | Repos touched | GitHub logged | What was happening |
|---|---|---|---|---|
| 2026-07-17 | 34 clones + 32 fetches | 29 | 1,658 clones / 278 uniques | Mass public flip + pre-publish `git clone --mirror` backup of all 35 repos |
| 2026-07-22 | 13 clones + 19 fetches | 13 | 964 / 539 | LFS dedup + `blob:limit` inventory sweep |
| 2026-07-13 | 10 clones + 65 fetches | 6 | 262 / 125 | Cross-repo contamination cleanup |
| 2026-07-12 | 6 clones + 7 fetches | 7 | 335 / 129 | Repo hygiene pass |
| 2026-07-09 | 2 clones + 95 fetches | 4 | 218 / 99 | Screener/backtest work |

**Attribution has a hard limit — `ex_self` is a floor, not a clean number.** The
daily unique-cloner counts on those days (278, 539) far exceed what one machine
can account for, so own activity and external traffic overlap rather than one
explaining the other. Excluding a whole repo-day therefore also discards
whatever external traffic occurred on it. GitHub exposes no per-source data, so
the split cannot be resolved further — only bounded from both sides:
`clones_7d_ex_self` under-counts, `clones_7d_sum` over-counts, and the truth is
somewhere between.

Two more limits worth knowing: the scan sees only sessions still present under
`~/.claude/projects`, so pruned transcripts leave older days unflagged; and
commands that name no recognisable repo (a bare `git fetch` in an unrelated
directory) are counted in `unattributed` and excluded from nothing.

**Genuinely external, for contrast:** `FCI-warehouse-MSPvsMSV` (229 clones/week)
and `india-omc-fuel-fleet-model` (104) have zero matching own commands and no
Actions workflows.

## Reading the numbers: clones are machines, views are people

Clones and views measure two different populations, and mixing them is
misleading. "Views" counts only github.com page loads in a browser. Everything
else — `git clone`, CI checkouts, `gh api`, raw.githubusercontent.com, tarball
downloads — registers as clone traffic and produces **zero** views.

In practice clone counts here are dominated by automation: mirrors, code-search
indexers, and training-data scrapers that consume GitHub's public-events
firehose and sweep newly-public repos, plus GitHub Actions checkouts on repos
that have workflows. The signature is a burst of clones from many distinct
sources when a repo goes public, decaying to near zero over a few days, with no
corresponding views. Clone counts are therefore **not** readership.

`views_summary.csv` isolates the human-interest signal so it isn't buried.

### Daily uniques do not sum

GitHub reports uniques *per day*, so adding them across days double-counts
anyone who returns. Each traffic endpoint also returns a top-level `uniques`
that **is** deduplicated across the full trailing 14-day window — that is the
only honest distinct-person figure available, and it is stored in each repo's
`period_totals`. Prefer `view_uniques_14d` over any `_sum` column; the `_sum`
columns are upper bounds.

## Files

- `data/<repo>.json` — per-repo time series (clones/views/releases keyed by
  date), plus `period_totals` — GitHub's deduplicated trailing-14-day
  clone/view totals, keyed by the snapshot date the window ends on
- `summary.csv` — flattened per-repo-per-day view, rebuilt on every run.
  `self_activity` marks repo-days on which the owner ran `clone`, `fetch`, or
  both
- `self_activity.json` — dates the owner ran clone/fetch commands, per repo,
  derived from local transcripts. Only dates, repo names and counts — never
  command text, file paths or session ids. The scan cache
  (`.self_activity_cache.json`) is gitignored because its keys *are* local
  paths; rebuild it with `python3 scripts/snapshot.py --rescan`
- `views_summary.csv` — one row per repo, human-interest signal only, sorted
  most-read first. `view_uniques_14d` / `views_14d` are GitHub's deduplicated
  14-day figures; `*_7d_sum` and `*_tracked_sum` are sums of daily values and
  so are upper bounds. `days_with_views` and `last_viewed` show whether
  interest is sustained or a one-day blip; `clones_7d_ex_self` /
  `clones_7d_sum` / `self_days_7d` carry clone volume with and without the
  owner's own activity, purely for machine-vs-human contrast
