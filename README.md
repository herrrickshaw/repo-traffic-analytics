# repo-traffic-analytics

Daily traffic snapshots for all public repos under `herrrickshaw`, run via
`scripts/snapshot.py` on a scheduled task.

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

## Known noise in the data

2026-07-17: all 35 originally-private repos in this account were made public,
and each was `git clone --mirror`'d once that day as part of a pre-publish
backup step (see `herrrickshaw/<name>-archive-2026-07-17` repos). Expect a
one-time clone-count bump on 2026-07-17 for every repo that isn't organic
external interest.

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
- `summary.csv` — flattened per-repo-per-day view, rebuilt on every run
- `views_summary.csv` — one row per repo, human-interest signal only, sorted
  most-read first. `view_uniques_14d` / `views_14d` are GitHub's deduplicated
  14-day figures; `*_7d_sum` and `*_tracked_sum` are sums of daily values and
  so are upper bounds. `days_with_views` and `last_viewed` show whether
  interest is sustained or a one-day blip; `clones_7d_sum` is carried along
  purely for machine-vs-human contrast
