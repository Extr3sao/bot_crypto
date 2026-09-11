# DATA ARCHIVE COVERAGE MATRIX — ALPHA-DATA-ADMISSION-01

Retrieval: 2026-09-11 (UTC) · Method: **metadata listing only** (official `data.binance.vision` S3 XML listing; no archive download beyond the separately ingested 7-day samples).

## aggTrades (data/futures/um/{daily,monthly}/aggTrades/<SYMBOL>/)

| Symbol | Cadence | First available | Last available | Dated zips | CHECKSUM | Missing (first→last) | Compressed total |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BTCUSDT | daily | 2019-12-31 | 2026-09-10 | 2,446 | FULL | 0 | 44,522,317,394 B (~44.5 GB) |
| BTCUSDT | monthly | 2020-01 | 2026-08 | 80 | FULL | 0 | 44,030,199,865 B (~44.0 GB) |
| ETHUSDT | daily | 2019-12-31 | 2026-09-10 | 2,446 | FULL | 0 | 42,086,381,867 B (~42.1 GB) |
| ETHUSDT | monthly | 2020-01 | 2026-08 | 80 | FULL | 0 | 41,733,653,778 B (~41.7 GB) |
| SOLUSDT | daily | 2020-09-14 | 2026-09-10 | 2,188 | FULL | 0 | 14,308,632,127 B (~14.3 GB) |
| SOLUSDT | monthly | 2020-09 | 2026-08 | 72 | FULL | 0 | 14,248,870,192 B (~14.2 GB) |

Note: the monthly listing also contains one non-dated Spark `part-*.zip` chunk per symbol (excluded from dated-coverage math, reported in the JSON).

## Open interest (data/futures/um/daily/metrics/<SYMBOL>/)

| Symbol | First available | Last available | Dated zips | CHECKSUM | Missing (first→last) | Compressed total |
| --- | --- | --- | --- | --- | --- | --- |
| BTCUSDT | 2020-09-01 | 2026-09-10 | 2,201 | FULL | 0 | 25,467,697 B (~25.5 MB) |
| ETHUSDT | 2021-12-01 | 2026-09-10 | 1,745 | FULL | 0 | 20,577,894 B (~20.6 MB) |
| SOLUSDT | 2021-12-01 | 2026-09-10 | 1,745 | FULL | 0 | 19,570,801 B (~19.6 MB) |

Native cadence: **5 minutes** (288 rows/day, DEF-DATA-OI-001 corrected — see `OI_CADENCE_RECONCILIATION.md`).

## Full-history cost estimate (aggTrades, Track D1)

| Item | Estimate | Basis |
| --- | --- | --- |
| Compressed (BTC+ETH+SOL, daily) | ~101 GB | listing byte sums above |
| Uncompressed (×~4.5 observed sample ratio) | ~455 GB | 7-day sample: 186 MB compressed → ~840 MB CSV |
| Files | ~6,700 daily zips (+ CHECKSUMs) | listing counts |
| Download time @10 MB/s | ~3 hours | 101 GB / 10 MB/s |
| Normalization time | ~2–4 hours | 16.27M rows / 7 days ≈ 2.3M rows/day → ~480M rows total at observed ingest rate |

**FULL_BACKFILL = COST_REVIEW_REQUIRED** — materially exceeds a routine local research budget. This does NOT invalidate the family: the 7-day engineering sample already proved schema, quality, PIT and fingerprint behavior.

## Machine-readable evidence

`DATA_ARCHIVE_COVERAGE_MATRIX.json` (same directory) carries the exact per-prefix listing evidence, retrieval dates, and `non_dated_part_files` accounting.
