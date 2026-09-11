# DATA SOURCE AUTHORITY REPORT — ALPHA-DATA-ADMISSION-01

**Rule enforced:** every external claim is anchored to an official source. **Zero third-party/blog sources used. Zero credentials used. Zero trading calls made.**

The authoritative registry for this checkpoint is `DATA_SOURCE_REGISTRY.json` (this directory). The legacy `docs/external-audit-01/source_registry.json` is **preserved untouched**: a prior-run H5 evidence artifact (`h5-orderflow-imbalance-01/evidence/H5_POST_EXECUTION_ANNOTATIONS.PRIOR_RUN_v1.json`) references it by path, so mutating it would disturb the H5 evidence chain.

**License separation:** the Binance public-data GitHub repo is MIT — that is the *tooling* license only. The *data* falls under Binance official public data terms. All reports here keep the two distinct.

## Claim → Source → Evidence → Decision

| # | Claim | Source | Evidence | Decision |
| --- | --- | --- | --- | --- |
| 1 | aggTrades daily depth: BTC/ETH from 2019-12-31, SOL from 2020-09-14; 0 missing files → 2026-09-10 | Vision archive (official) | `DATA_ARCHIVE_COVERAGE_MATRIX.json` (metadata-only listing) | Trade-flow HISTORICAL_DEPTH 5/5 |
| 2 | OI metrics depth: BTC from 2020-09-01; ETH/SOL from 2021-12-01 | Vision metrics archive (official) | same probe, per-asset independent | OI HISTORICAL_DEPTH 4/5; no per-asset symmetry assumed |
| 3 | REST `openInterestHist` ≈ 30-day ceiling for USD-M | Official REST API (empirical probe) | `startTime` 39 days old → error `-1130`; recent works | `REST_DEEP_HISTORY=INSUFFICIENT`; archive supersedes |
| 4 | OI native cadence = **5m** (288 rows/day) | Raw official files measured directly | `OI_CADENCE_RECONCILIATION.json` (uniform 300s deltas, 21/21 files) | `DEF-DATA-OI-001` corrected in contracts/readers/engine/tests |
| 5 | USD-M aggTrades = 7-column schema; `is_buyer_maker` defines taker side | Official schema docs | frozen in `data_contracts.py`, tested | D2 contract frozen; no inferred direction |
| 6 | Official `.CHECKSUM` sha256 sidecars for both families | Schema docs + direct verification | 42/42 sample files verified PASS at ingestion | checksum/schema guards enforced in `source_readers.py` |

## Sources registered (see registry for full attributes)

- `SOURCE_BINANCE_VISION_USDM_AGGTRADES_DAILY`
- `SOURCE_BINANCE_VISION_USDM_AGGTRADES_MONTHLY`
- `SOURCE_BINANCE_VISION_USDM_METRICS_DAILY`
- `SOURCE_BINANCE_USDM_AGGTRADES_REST` (registered; NOT used for historical ingestion)
- `SOURCE_BINANCE_USDM_OPEN_INTEREST_HIST_REST` (registered; classified INSUFFICIENT for deep history)
- `SOURCE_BINANCE_PUBLIC_DATA_SCHEMA_DOCS`

Reliability tier for all used sources: **SOURCE_CODE / OFFICIAL_DOC**. No blog or third-party aggregator was consulted for any factual claim.
