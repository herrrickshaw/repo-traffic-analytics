# Clone spikes are first-publication events, not interest

**2026-08-10.** Written after `masaladeutsch` showed 136 clones in a week with
zero self-days and the obvious question — "is that real?" — turned out to have a
general answer.

## The finding

Large clone counts in this dataset are almost always **a single day's burst on
the day a repo first became visible to the public**, not sustained traffic.

Of the 29 repos with a peak day above 30 clones, **25 peak within two days of
their `created_at`**, and 17 peak on the creation date exactly.

| repo | peak clones | uniques | peak day | created | Δ |
|---|---|---|---|---|---|
| india-govt-yellow-pages | 497 | 38 | 2026-07-31 | 2026-07-29 | +2d |
| india-trade-sector-policy-recommendations | 332 | 96 | 2026-07-19 | 2026-07-18 | +1d |
| Bazartalks_Py2Cplus | 220 | 70 | 2026-07-12 | 2026-07-12 | 0 |
| global-ticker-universe | 216 | 17 | 2026-07-06 | 2026-07-04 | +2d |
| mospi-dataset-analysis-public | 184 | 77 | 2026-07-18 | 2026-07-18 | 0 |
| digital-twin-for-ipa | 173 | 59 | 2026-07-20 | 2026-07-20 | 0 |
| masaladeutsch | 136 | 62 | 2026-08-08 | 2026-08-08 | 0 |
| FCI-warehouse-MSPvsMSV | 110 | 50 | 2026-07-23 | 2026-07-23 | 0 |
| ev-battery-management-sim | 88 | 6 | 2026-07-03 | 2026-07-03 | 0 |
| cell-guardian | 82 | 6 | 2026-07-03 | 2026-07-03 | 0 |
| india-omc-fuel-fleet-model | 79 | 47 | 2026-07-24 | 2026-07-24 | 0 |
| india-ec-subsector-analysis | 69 | 39 | 2026-07-22 | 2026-07-22 | 0 |
| jai_kisan_jai_javan | 63 | 37 | 2026-07-31 | 2026-07-31 | 0 |
| repo-data-dedup | 62 | 42 | 2026-07-22 | 2026-07-22 | 0 |
| vehicle_fuel_mileage | 55 | 23 | 2026-07-28 | 2026-07-24 | +4d |
| stock-screener-platform | 53 | 13 | 2026-07-13 | 2026-07-13 | 0 |
| india-trade-tracker | 46 | 32 | 2026-07-21 | 2026-07-21 | 0 |
| CBSE_paper_patterns | 36 | 20 | 2026-08-07 | 2026-08-06 | +1d |
| agri-commodity-tracker | 35 | 22 | 2026-07-21 | 2026-07-21 | 0 |
| india-trade-data-analysis | 33 | 16 | 2026-07-18 | 2026-07-18 | 0 |
| jal_jeevan_lottery | 31 | 23 | 2026-07-31 | 2026-07-31 | 0 |
| kalki_flooding | 30 | 20 | 2026-07-23 | 2026-07-23 | 0 |

The trigger is **first public exposure**, which is usually but not always
`created_at`. The four repos that don't line up confirm rather than break the
rule:

| repo | peak day | `created_at` | why it differs |
|---|---|---|---|
| global-market-research-platform | 2026-07-17 | 2026-08-04 | deleted + recreated 2026-08-04 (LFS retirement); the spike is the 07-17 mass public flip, already documented in the README |
| global-stock-screener | 2026-07-09 | 2026-08-04 | same recreation — `created_at` post-dates its real history |
| global-market-data | 2026-07-23 | 2026-08-04 | same recreation |
| global-market-scanners | 2026-07-03 | 2026-06-13 | created private, spiked ~20d later — presumably its individual flip to public |

Two repos in the >30 set (`market-screener-backtests`, `ocaml-stock-screener`)
now 404 on the API — renamed or deleted — while their traffic data remains in
`data/`. Harmless, but their rows can't be re-verified.

## Why this is automation and not readers

- **Uniques are too high for one machine.** `masaladeutsch` logged 62 distinct
  cloner identities in a day. The owner's laptop plus CI runners account for a
  handful of IDs, not 62. The same holds for 96 uniques on
  `india-trade-sector-policy-recommendations`, 77 on `mospi-dataset-analysis-public`.
- **No views accompany them.** These spikes produce zero or near-zero page
  views. Anything that isn't a browser hitting github.com — mirrors, code-search
  indexers, training-data scrapers reading the public-events firehose — registers
  as clone traffic only.
- **They decay to nothing.** For `masaladeutsch` every other day in the 14-day
  window is `{count: 0, uniques: 0}`. One day at 136, thirteen days at zero.

GitHub Actions checkouts add to the count where workflows exist —
`masaladeutsch` ran 25 `pages-build-deployment` jobs on 2026-08-08 — but that's
a slice of the total and contributes very few uniques.

## Uniques tell you which kind of automation

The unique count separates the two machine populations, and it's the most
useful single number on a spike day:

- **Many uniques, one day, no views** → external crawler swarm.
  `masaladeutsch`: 136 clones / **62 uniques**.
- **One unique, sustained** → your own scheduled job.
  `blogger_writeups_code`: 87 clones / **1 unique**, driven by the 09:05
  `cron_inject_wrapper.sh` cron against `~/masaladeutsch-archive`.

Neither is readership. Only `view_uniques_14d` is.

## Consequence for `self_days`

`masaladeutsch` correctly shows `self_days_7d = 0`: there is **no local working
copy of that repo on this machine** — every git remote under `~` was checked and
none points at it. It's an API/Pages-only repo, so no `git clone`/`git fetch`
ever runs against it locally and there is genuinely nothing for the exclusion to
drop. `clones_7d_ex_self = clones_7d_sum = 136` is right, and all 136 are
external automation.

This is worth stating because a zero in `self_days_7d` has two very different
meanings:

1. **Nothing to exclude** — the repo isn't cloned locally at all (`masaladeutsch`).
2. **Nothing detected** — the repo is cloned locally, but the activity happened
   outside a Claude session and so was invisible.

The detector only reads `~/.claude/projects/**/*.jsonl`. Terminal work and cron
jobs never appear in it. On 2026-08-08 it logged 5 clone/fetch commands it could
not attribute to any repo. So `self_days_7d = 0` means "no evidence found", not
"proven zero" — check whether a local clone exists before reading it as case 1.

## How to read a spike in future weekly reports

1. Is the spike day within ~2 days of the repo's first publication? → expected
   crawler burst, ignore.
2. Are uniques ≫ 1 with no matching views? → automation, not readers.
3. Is the unique count exactly 1? → look for a local cron, not an audience.
4. Only `view_uniques_14d` moving is worth reporting as interest.

## Reproducing

```bash
cd ~/repo-traffic-analytics && python3 - <<'PY'
import json, glob, os, subprocess
for p in sorted(glob.glob('data/*.json')):
    n = os.path.basename(p)[:-5]
    c = json.load(open(p)).get('clones', {})
    if not c:
        continue
    day, best = max(c.items(), key=lambda kv: kv[1]['count'])
    if best['count'] < 30:
        continue
    r = subprocess.run(['gh', 'api', f'repos/herrrickshaw/{n}',
                        '--jq', '.created_at[0:10]'],
                       capture_output=True, text=True)
    print(n, best['count'], best['uniques'], day,
          r.stdout.strip() if r.returncode == 0 else '404')
PY
```
