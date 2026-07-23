# Action Items — CIO Index governance review + cioindex.com/Crunchbase historical review
Compiled 2026-07-23 from session "CIO Index tools and techniques" (2026-07-22).
Statuses re-verified against live repo/cron state on 2026-07-23.

## Progress log 2026-07-23
- ✅ #1 cron fixed (cd prefix added, grep-verified; imports resolve under /usr/bin/python3)
- ✅ #3 gitleaks full-history sweep of all 50 public repos: 44 clean, 15 findings in 6
  repos, ALL benign (data.gov.in public sample key, Deutsche Börse shared public key,
  SSR-guide placeholders sk_live_abc…/truncated JWT, chart variable names, Figma fileKey).
  Zero rotations needed. Reports: scratchpad gitleaks_sweep/ (session-temporary).
- ✅ #8 both trackers flipped off LFS (full 1MB blobs verified served by GitHub API)
- ✅ #2 CI gate adopted in 6 more Tier-1 repos (repo-data-dedup, cng-cgd, digital-twin,
  agri, india-trade, repo-traffic-analytics); python lint enabled only where ruff-clean
  (repo-traffic-analytics); others gitleaks-only with TODO to flip after cleanup.
  BazaarTalks/Py2Cplus/gss/gmd/gmrp already had CI. First runs green (5/6 + refix).
- ✅ #7 monthly portfolio review installed: scripts/portfolio_review.py (this repo) +
  cron 1st 09:30; first report reports/REVIEW_2026-07.md (all 50 KEEP — estate touched
  this month).
- ✅ #10 VERIFIED DERIVABLE: market-screener-backtests' market_data.duckdb (759MB LFS,
  already unreadable — repo over LFS budget) is build_warehouse.py output from
  cache_seed/ltm + fundamentals_history + exchange_reference — all present in local
  gss clone AND dropbox:market-data-backup/current/gss-cache_seed (82 parquets) AND
  GDrive mirror. Full code/docs history bundled to
  ~/repos/branch-archives/market-screener-backtests_full_pre-delete_2026-07-23.bundle
  (verified). Repo DELETION (frees 0.77GB LFS) awaiting user's call.
- ✅ #10+#13 DELETED BY USER 2026-07-23: market-screener-backtests (+0.77GB LFS freed)
  and tools-handling_data (empty). Catalog updated.
- ✅ #11 fuel-retail-outlets REBUILT LFS-FREE (gmd pattern): old repo renamed
  fuel-retail-outlets-lfs-legacy (deletion pending, frees 0.24GB); fresh repo pushed with
  code+docs + canonical ssri_pumps_raw_20260722.jsonl.gz (105,035 pumps — NEWER than the
  locked dumps) + crawl_ssri.py + REBUILD_NOTE.md + CI gate; history bundle
  fuel-retail-outlets_full_pre-rebuild_2026-07-23.bundle in branch-archives.
- ✅ #38 restore drill installed: repo-data-dedup/scripts/restore_drill.sh + cron 2nd
  09:15 (samples 3 backup files <50MB, byte-verifies restore, cross-checks GDrive mirror,
  gunzip-tests latest pg dump). First run: 2/2 PASS.
- ✅ #35 canonical dataset registry: repo-traffic-analytics/datasets.yaml — 10 datasets,
  canonical flags, the broken gmd US.parquet marked superseded_by with the do-not-cite
  warning. Two-file trap now machine-readable.
- ⚠️ #9 working-files uniqueness VERDICT: NOT fully redundant. 97.6% content-contained,
  but unique: 12-commit history + 26.7MB regular blobs + 98 LFS payloads (1.04GB —
  older ltm snapshots incl. the letter-biased US panel, correlation_scan.duckdb 346MB
  [outputs recomputed as CSVs 2026-07-23], dated scan xlsx). RESCUED NOW: full bundle
  working-files_full_2026-07-23.bundle (276MB, verified — covers history + all unique
  regular blobs) + 18 gc-vulnerable gmrp blobs extracted; both in branch-archives
  (clouds tonight). PENDING: LFS payload rescue — reads still blocked 05:02 despite
  freed 0.77GB (GitHub recalculates lazily); retry per
  branch-archives/working-files-rescue-inventory-2026-07-23/README.md. Deletion
  (frees 1.32GB LFS) only after LFS retry succeeds OR user accepts stale-snapshot loss.
- ✅ fuel-retail-outlets-lfs-legacy DELETED by user 2026-07-23 (+0.24GB; total LFS freed
  today: 1.01GB). Retries at 05:09/05:10 still blocked — AUTO-RETRY CRON installed
  (every 6h, repo-data-dedup/scripts/lfs_rescue_working_files.sh, self-terminating:
  on unblock it fetches all 125 payloads → branch-archives → clouds, writes done-marker;
  progress in state/wf_lfs_rescue.log). Side-finding: 27 election-analysis files match
  LFS patterns but are stored as REAL blobs (pointer-mismatch class) — already safe in
  the bundle.

**Scope note:** Crunchbase was used only as a corroborating source in the cioindex.com
historical trace (founding 2006, founder Sourabh Hajela, era analysis). No repo action
items derive from Crunchbase itself — everything actionable came from the CIO-Index-framed
governance review and the analysis-exhaustiveness gap review in the same session.

## A. Broken since "done" — fix first
1. **Mon 09:15 `score_signals.py` cron has no `cd`** (crontab line 12:
   `15 9 * * 1 /usr/bin/python3 score_signals.py >> reports/score_signals.log 2>&1`).
   Runs from $HOME; script lives in `~/market-pipeline/code/python_files/`. It has never
   worked as written. Fix: prepend `cd /Users/umashankar/market-pipeline/code/python_files &&`
   and verify with `crontab -l | grep -F "cd /Users"`.

- ✅ #16 (D16) ADJUSTED-PRICE FIX COMPLETE — with a premise correction: JP/KR/CN/US
  panels were NOT raw Close (verified yf-adjusted at collection: NTT 25:1, Samsung 50:1,
  NVDA 10:1 all pre-adjusted in-panel); the raw-Close risk was INDIA-ONLY (bhavcopy,
  already fixed). Real defect = post-assembly residual breaks: price_adjuster_global.py
  detected 86 candidates (integer-ratio + calm-day + turnover gates), confirmed 8 vs the
  yfinance split calendar, wrote sparse overlays ohlcv_adj/{JP,KR,US}/corrected_symbols
  .parquet (overlay-first rule; CN/EU zero residuals). US validation 3/3 exact.
  claims.yaml corrected + new claim non-india-panels-already-adjusted; DATA_ACCESS.md
  adjustment-status table added. 🔴 NEW yfinance bug memorialised: auto_adjust serves
  UNADJUSTED prices for recent JP/KR splits (validate by continuity, never yf returns).
  Re-run the adjuster after any panel re-assembly (staleness trigger encoded).

## B. Governance review — still open
2. **Adopt the `.github` reusable CI gate per-repo** — the reusable workflow
   (ruff+black+gitleaks+integrity) and NEW_REPO_CHECKLIST exist in `herrrickshaw/.github`,
   but Tier-1 repos still need the ~4-line caller workflow added each.
3. **Full-history gitleaks sweep across all ~45 public repos** (pointer clones, ~10–15 min,
   read-only). Offered in-session, never executed. Any hit = rotate the credential.
4. **Decide `global-market-research-platform` visibility** — verified still PUBLIC today,
   and it is $HOME's origin (the "biggest standing risk" transferred here when
   `working-files` went private). User's call: flip private or accept.
5. **License pass on data-store repos** (screener.in ToS, NSE data policy, Trendlyne,
   Kaggle non-redistribution) — repos redistributing licensed market data are better
   private regardless of secrets.
6. **Tier-based visibility rule** going forward: analyses/tools public; data stores and
   home-mirror repos private.
7. **Install the monthly 30-min portfolio review** (keep/archive/merge per repo, driven by
   traffic snapshots + cron liveness via `launchctl print` runs-counter + freshness
   stamps). Proposed, no recurring mechanism installed.
8. **Flip `agri-commodity-tracker` + `india-trade-tracker` off LFS** — verified today both
   still have `data/*.duckdb filter=lfs` in .gitattributes; files still small; ~5 min each.

## C. Repo-size / LFS roadmap — remaining
9. `working-files` uniqueness check → whole-repo deletion candidate (−1.42 GB) if fully
   contained in gmrp history + bundles.
10. `market-screener-backtests` (0.77 GB, single 759MB duckdb, likely derivable from the
    gmd warehouse) — verify then delete.
11. `fuel-retail-outlets` gmd-style LFS-free rebuild (data re-collectable in ~6 min from
    SSRI API; −0.24 GB).
12. `gmrp` history surgery (1.97 GB history-only dead weight) — deferred; only pays via
    delete-recreate and it's the live $HOME origin.
13. Delete empty archived repo `tools-handling_data` (0 commits) — user's call.
14. (Optional) `gh auth refresh -s user` to read exact LFS billing via API.
15. CLOSED by policy: `market-data-artifacts` LFS-locked caches + 75 superseded objects —
    no $5 data pack (user policy); Kaggle subset re-fetchable free.

## D. Analysis-exhaustiveness gaps — still open
16. **Propagate the adjusted-price fix beyond India** — JP/KR/CN/EU/US panels still raw
    Close (the bug that manufactured a fake +12.2% illiquidity premium). Apply the split
    heuristic; keep those markets' conclusions flagged until then.
17. **Re-run old conclusions on new PIT data** (XBRL to 2015 with 110,942 results; 10y
    screener.in history) — claims ledger has staleness triggers, but the re-runs themselves
    haven't happened.
18. **Make cost-adjustment a backtest-harness default** (currently only in
    `cost_vs_edge.py`).
19. **Make `data_completeness_audit.py` a gate**, not an optional script — required pass
    before any analysis is citable.
20. **Regime conditioning** — split results by vol/rate regime (VIX / India-VIX terciles).
21. **Factor spanning tests** — Fama–MacBeth with controls; double-sorts (the
    size×illiquidity lesson).
22. **One backtest harness**: gmd warehouse + PIT joins + cost model + completeness gate
    as defaults.
23. **Robustness grid as standard output** (market × subperiod × liquidity tercile × cost
    level).
24. **Adversarial replication ritual** — falsification script per headline claim.

## E. Per-domain analysis gaps — open
25. Correlation repos: rolling windows, tail dependence, hierarchical clustering for
    portfolio construction.
26. Derivatives PCP: execute Phases 1–3 of the derivatives-vs-equity framework; estimate
    historical frequency of actionable parity deviations.
27. India trade/macro repos: causal identification — event studies around policy dates
    (PLI tranches, duty changes), counterfactuals.
28. Physical-economy layers (CGD/outlets/mandi): competition/HHI by GA, mandi
    spatial-arbitrage/seasonality, mandi→CPI linkage (MoSPI connector exists),
    outlets→listed OMC/CGD stocks.
29. Incentive twin: track disbursement/utilization outcomes, not just announcements.
30. **Unexploited joins (biggest upside): XBRL filing dates × CA history × bhavcopy =
    fully-PIT earnings-drift + post-split event studies (India)**; trade data × sector
    screens; mandi × agri-listed names.

## F. Queued "next gaps" left undispositioned at session end
31. JP/KR/EU panel refresh — unblocks ~2,000–2,200 pending signal scores.
32. JP/KR June-snapshot parsing — backfill parser parsed zero for JP/KR (different
    workbook format).

## G. Infra follow-ons flagged in the same session
33. rclone Google Drive legs ride the shared client_id that retires during 2026 — create
    own client_id (~5 min); single point of fragility in the Drive backup leg.
34. Add `~/.pipeline_pause` check to collectors (`daily_pipeline.sh`, trackers).

## H. Open-literature upgrades (researched 2026-07-23)
Authoritative external versions of the same insights — confirm, improve, or replace items above.

### Data sources / canonical datasets (upgrades B, D — kills the "two-file trap" structurally)
35. **Machine-readable dataset registry** (`datasets.yaml`: path, schema, refresh cadence,
    `canonical: true/false`, `superseded_by`) + CI grep blocking reads of non-canonical
    files — the catalog-lite distillation of DataHub/OpenMetadata/Amundsen. Directly fixes
    the gmd-vs-gss `US.parquet` trap. Extends `repos.yaml`'s "canonical data file" field.
36. **DVC** (dvc.org) — content-addressed `.dvc` pointers in git, payloads on the
    Dropbox/GDrive remotes you already run; `dvc repro` DAGs re-run only stale stages.
    Free replacement for the exhausted-LFS pattern; every analysis pins its data version.
37. **Dolt** for small reference tables (instrument lists) — cell-level `diff`/`blame`;
    **lakeFS pattern** (never write to main; promote via validated merge) worth encoding
    in DuckDB scripts even without lakeFS itself.

### Redundancy / backup (upgrades the tri-store architecture)
38. **3-2-1 → 3-2-1-1-0** (Veeam/US-CERT): current setup lacks the "1" (one genuinely
    IMMUTABLE copy — a bad sync or token compromise can propagate deletions to all legs;
    Dropbox rewind ≠ immutability) and the "0" (zero errors on TESTED restores).
    Add: monthly cron restoring a random parquet + latest pg dump to scratch, diff checksums.
39. **`rclone check --download`** (byte-level) on a sampled subset = the cheap "0 errors"
    leg; **`--backup-dir`** on every sync = soft-delete quarantine against the
    parallel-session-wipe failure mode already suffered. git-annex `numcopies`/`fsck` is
    the model the weekly replication matrix should emulate.

### Pipeline / SOP frameworks (upgrades A, D)
40. **Medallion vocabulary as invariant**: bronze (raw bhavcopy, immutable) → silver
    (`cleaned_ohlcv`) → gold (views/scan inputs); gold reads ONLY from silver — formalizes
    the "load India from cleaned_ohlcv ONLY" memory note architecturally.
41. **dbt-duckdb source-freshness tests** — declarative staleness SLAs that FAIL CI instead
    of waiting for a human to read `ticker_freshness.csv`; runs on the existing warehouse,
    zero infra.
42. **Dead-man's-switch pings for every cron** (healthchecks.io, self-hostable) — a job
    that never fires alerts; cron/launchd logs cannot do this (the launchd runs=0 lesson,
    and item #1's broken cron would have been caught day one).
43. **`targets` (R) / Snakemake** — analysis as content-hashed DAG; the pipeline file IS
    the SOP. `targets` is the natural upgrade for the Pegu/Sarvas R pipeline;
    Snakemake fits the Python→R handoff.

### Reproducible quant research (confirms & raises the bar on D16-24)
44. **Deflated Sharpe (Bailey & López de Prado 2014) + t>3.0 (Harvey-Liu-Zhu RFS 2016)**:
    both REQUIRE a count of ALL trials ever run — the claims ledger is a mathematical
    prerequisite, not bookkeeping. Log every strategy variant tried, report deflated
    Sharpe alongside raw. CSCV/PBO (Bailey et al. 2017) for the backtest harness.
45. **REFORMS checklist** (Science Advances 2024, 32 items, 8 modules incl. leakage &
    provenance) — consensus-backed replacement for a home-grown analysis checklist.
46. **"Good Enough Practices" (Wilson et al., PLOS Comp Bio 2017)**: raw data read-only;
    every result regenerable by a single command. The minimum standard to cite.
47. Survivorship/PIT canon (Brown-Goetzmann-Ross-Ibbotson RFS 1992) confirms the delisted-
    retention check, dated-filing collection, and the raw-vs-adjusted-price bug class.

### Repo portfolio governance (upgrades B2-B8)
48. **Consolidate CODE into 1-3 monorepos, keep DATA repos separate** (Dan Luu; Potvin &
    Levenberg CACM 2016) — the cross-repo contamination incidents (BMS/stock-mailer,
    orphan PRs) are the textbook polyrepo failure mode; stronger fix than catalog-only
    hygiene. (Reverses the in-session "skip monorepo" call — worth a fresh decision.)
49. **GitHub org RULESETS + reusable workflows** — one org-level ruleset + one shared
    `ci.yml` replaces per-repo branch-protection/gitleaks/ruff copy-paste across ~50 repos;
    this is what turns repos.yaml from description into enforcement.
50. **Weekly OpenSSF Scorecard run** (scorecard.dev, 18 checks) across all public repos —
    free, external, quantified hygiene audit; covers workflow-permission classes gitleaks
    doesn't.
51. **Cookiecutter Data Science / Turing Way template for all NEW repos** — `data/raw`
    immutable, `data/processed` derived, notebooks refactored into `src/` when reused;
    plugs into NEW_REPO_CHECKLIST.

### SOP / runbook culture (upgrades A1, B7)
52. **Gawande checklist rules**: checklists target routine steps experts skip under load;
    keep 5-9 items; every SOP ends with a MECHANICAL verification step, never a claim
    (the crontab-without-`cd` incident is the exact failure class).
53. **SRE-book practices at personal scale**: a runbook per cron job (what healthy looks
    like, how to verify it fired, how to recover); explicit staleness/error budget per
    data source so "8 days stale" trips a threshold instead of being found incidentally.

Key sources: dvc.org · lakefs.io · veeam.com/blog/321-backup-rule · rclone.org ·
databricks.com/glossary/medallion-architecture · docs.getdbt.com/best-practices ·
docs.ropensci.org/targets · snakemake.readthedocs.io · SSRN 2460551 (Deflated Sharpe) ·
RFS 29(1):5 (Harvey-Liu-Zhu) · science.org/doi/10.1126/sciadv.adk3452 (REFORMS) ·
doi 10.1371/journal.pcbi.1005510 (Wilson) · danluu.com/monorepo · dl.acm.org/doi/10.1145/2854146 ·
scorecard.dev · cookiecutter-data-science.drivendata.org · book.the-turing-way.org ·
sre.google/sre-book · atulgawande.com/book/the-checklist-manifesto

## Already done (verified or confirmed in-session)
- gita multi-repo driver; gitleaks hooks in 12 Tier-1 clones; `herrrickshaw/.github` CI +
  NEW_REPO_CHECKLIST; `repos.yaml` catalog (50 repos tiered); 21 dormant repos archived;
  home-repo branch sweep (29→17, bundles kept); `working-files` PRIVATE (verified);
  35 archive twins deleted; gmd LFS-free rebuild; ocaml-stock-screener deleted;
  ev-sim/cell-guardian rewritten <1MB; claims ledger `claims.yaml` (10 claims);
  `multiple_testing.py` (0/12 combos survive FDR q=0.10); `backfill_signals.py`
  (18,957 June signals); ETL registry + weekly replication matrix.
