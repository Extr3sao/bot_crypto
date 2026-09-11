# TRADE FLOW DATA ADMISSION REPORT — ALPHA-DATA-ADMISSION-01

**Decision: `ADMIT_WITH_LIMITATIONS`** · Family: high-resolution aggregate trades (DATA-FAMILY-A) · Source: `SOURCE_BINANCE_VISION_USDM_AGGTRADES_DAILY` (official data.binance.vision)

## Scorecard

| Dimension | Score | Evidence |
| --- | --- | --- |
| DATA_AUTHORITY | 5/5 | official archive; official `.CHECKSUM` sha256 sidecars verified 21/21; tooling-MIT vs data-terms separation enforced |
| HISTORICAL_DEPTH | 5/5 | BTC/ETH from 2019-12-31, SOL from 2020-09-14 → 2026-09-10; **0 missing files** first→last |
| PIT_SAFETY | 5/5 | event-time (transact_time, UTC ms); immutable archives; `data_time <= decision cutoff` enforced + future-mutation tests PASS |
| QUALITY | 5/5 | **16,269,514 rows, 0 errors**, 0 duplicate `agg_trade_id`s, monotonic after canonical sort, price/quantity > 0 |
| INFORMATION_DISTINCTNESS | YES | event-level taker direction, per-trade size, burst structure, intra-bar sequence — absent from hourly OHLCV/takerBuyBaseVolume/funding/regime state (Track J, data-level only) |
| COST | 2/5 | full 3-symbol backfill ~101 GB compressed / ~455 GB uncompressed |
| STORAGE | 2/5 | sample (7 days, 3 symbols): 186 MB compressed / ~840 MB CSV |
| PORTABILITY | 5/5 | plain zip+CSV + sha256 sidecars |

## Sample evidence (engineering validation only — NOT alpha evidence)

| Item | Value |
| --- | --- |
| Files | 21 (3 symbols × 7 days, 2026-09-01..07) |
| Rows | 16,269,514 (BTC 7,517,538 · ETH 6,932,098 · SOL 1,819,878) |
| Official checksum | PASS 21/21 |
| Quality errors | 0 |
| PIT | 16,269,514/16,269,514 within cutoff |
| Manifest | `data/processed/trade_flow/DATASET_MANIFEST.json` (run-B, `normalizer_commit=ec2483f`) |

## Direction semantics (schema authority)

`is_buyer_maker = true` → buyer is **maker** → aggressive/taker side is **SELL**; `false` → taker side is **BUY**. Frozen in `data_contracts.py`, enforced by tests. No inferred direction.

## Limitations

1. **FULL_BACKFILL = COST_REVIEW_REQUIRED** (~101 GB compressed, ~6,700 files). Does not affect admission; the sample already proves schema, quality, PIT and fingerprints.
2. Sample is engineering validation only; no profitability/alpha inspection was performed anywhere in this checkpoint (ALPHA_LEAKAGE = 0).

Machine-readable: `TRADE_FLOW_DATA_ADMISSION_REPORT.json`.
