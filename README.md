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

## Files

- `data/<repo>.json` — per-repo time series (clones/views/releases keyed by date)
- `summary.csv` — flattened view across all repos, rebuilt on every run
