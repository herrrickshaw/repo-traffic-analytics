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

**The largest single source of clone traffic is this account's own CI.** Every
GitHub Actions run checks the repo out, and `actions/checkout` is a real clone
from GitHub's side, so it lands in `traffic/clones` indistinguishable from an
outsider's. `snapshot.py` now fetches each repo's Actions run counts per day
(archived in `ci_runs` in the per-repo JSON) and subtracts them from that day's
clones in `clones_7d_ext`.

The effect is not marginal. `blogger_writeups_code` booked 278 clones in a
fortnight from **2 unique cloners**, with **zero views ever** — a private repo
nobody outside the account can even reach. Its clone series matches its Actions
run count almost day for day (87/87, 15/15, 50/50, 41/41), driven by a
`push`-triggered link audit on `posts/**`. It now correctly reports **0**
external clones and **0** external cloners. Across the account, 201 of last
week's 486 clones were Actions checkouts, on 21 repos.

Subtraction is per-day and clamped at zero, so a repo whose CI ran still reports
the external clones it received that day. It remains a floor: a matrix run
checks out once per job while only the run is counted.

**A large share of the rest is the account owner's own work — also detected and
excluded automatically.** On every run `snapshot.py` gathers own activity from
two independent sources and records the dates in `self_activity.json`, where
`via` says which source saw each repo-day. Those repo-days are flagged in
`summary.csv` and dropped from `clones_7d_ext` in `views_summary.csv` — dropped
rather than subtracted, because the reflog records one entry per ref a fetch
moved, not one per clone event, so those counts cannot be subtracted without
wild over-correction.

1. **Session transcripts** (`~/.claude/projects/**/*.jsonl`) — scanned for
   `git clone` / `gh repo clone` / `git fetch` / `git pull`, resolving which
   tracked repos each command touched.
2. **Git reflogs of local working copies** — every local clone of a tracked repo
   is located by reading git remotes under `$HOME`, and its reflog gives the
   dates of every clone/fetch/pull *whoever ran it*. This is the half the
   transcript scan structurally cannot see: terminal work and cron jobs. The
   09:05 archive cron shows up here and nowhere else, as do the knowledge-graph
   tooling's own clones of 24 repos under `~/.graphify/gh-clones/`.

**A zero in `self_days_7d` is no longer ambiguous.** It used to conflate "no
local copy exists, so own traffic is impossible" with "a copy exists but nothing
was detected". The `local_copies` column now separates them: at 0 the zero is
authoritative, above 0 it means none was found this week. 18 of 71 repos have no
local copy at all.

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

**Counts have a hard limit — `clones_7d_ext` is a floor, not a clean number.**
The daily unique-cloner counts on those days (278, 539) far exceed what one
machine can account for, so own activity and external traffic overlap rather
than one explaining the other. Dropping a whole repo-day for self-activity
therefore also discards whatever external traffic occurred on it. GitHub exposes
no per-source data, so the split cannot be resolved further — only bounded from
both sides: `clones_7d_ext` under-counts, `clones_7d_sum` over-counts, and the
truth is somewhere between.

**Unique cloners survive the cleaning that counts cannot.** GitHub deduplicates
cloners across the trailing 14 days, and over that window CI presents as one
identity and the owner's machine as another. `ext_cloners_14d` subtracts one for
each, on evidence that each was actually active, leaving the distinct third
parties — 651 raw unique cloners last week, **627** external. That is the figure
to quote when asking how many outside parties took a copy; the count columns
answer only how much traffic they generated.

Three more limits worth knowing: the transcript scan sees only sessions still
present under `~/.claude/projects`, so pruned transcripts leave older days
unflagged (the reflog source is unaffected by pruning); commands that name no
recognisable repo (a bare `git fetch` in an unrelated directory) are counted in
`unattributed` and excluded from nothing; and a reflog entry is only written
when a ref actually moves, so a fetch that brings nothing new leaves no trace.
Bare mirror clones have reflogs disabled by default and would go unseen — none
exist today, but the 2026-07-17 `--mirror` backup was exactly that shape.

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

That signature is quantified in
[`reports/CLONE_SPIKES_2026-08-10.md`](reports/CLONE_SPIKES_2026-08-10.md): 25
of the 29 repos with a peak day above 30 clones peak within two days of first
publication, and the unique count distinguishes a crawler swarm (many uniques,
one day) from your own cron (exactly one unique, sustained).

### Daily uniques do not sum

GitHub reports uniques *per day*, so adding them across days double-counts
anyone who returns. Each traffic endpoint also returns a top-level `uniques`
that **is** deduplicated across the full trailing 14-day window — that is the
only honest distinct-person figure available, and it is stored in each repo's
`period_totals`. Prefer `view_uniques_14d` over any `_sum` column; the `_sum`
columns are upper bounds.

## Files

- `data/<repo>.json` — per-repo time series (clones/views/releases keyed by
  date), plus `ci_runs` — GitHub Actions runs per day, the checkout traffic
  subtracted from that day's clones — and `period_totals`, GitHub's
  deduplicated trailing-14-day clone/view totals, keyed by the snapshot date
  the window ends on
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
  interest is sustained or a one-day blip; `ext_cloners_14d` /
  `clone_uniques_14d` give distinct third-party cloners before and after
  discounting CI and the owner, and `clones_7d_ext` / `clones_7d_sum` /
  `ci_runs_7d` / `ci_runs_14d` / `self_days_7d` carry clone volume with and
  without that traffic, purely for machine-vs-human contrast; `local_copies`
  counts local working copies of the repo, which is what makes a
  `self_days_7d` of 0 authoritative (0 copies) rather than merely undetected
- `graphify-out/` — local code knowledge graph (`graph.json`, `graph.html`,
  `GRAPH_REPORT.md`) used for navigation, not part of the traffic data.
  Gitignored because it is derived output that churns on every edit; rebuild
  it with `~/.venvs/graphifyy/bin/graphify update .` (re-extracts code, no LLM
  needed). Doc and image changes need `/graphify --update` in the assistant
