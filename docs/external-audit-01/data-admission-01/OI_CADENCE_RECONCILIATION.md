# OI CADENCE RECONCILIATION — DEF-DATA-OI-001

Checkpoint: ALPHA-DATA-ADMISSION-01 · Date: 2026-09-11

| Field | Value |
| --- | --- |
| Defect | `DEF-DATA-OI-001` |
| Classification | `SEMANTIC_DATA_CONTRACT_DEFECT` |
| PREVIOUS_DECLARATION | `15m` (15-minute, 900s, 96 rows/day — WRONG) |
| CORRECT_DECLARATION | `5m` (300s, 288 rows/day) |
| FIXED | `true` |

## Ground truth (measured, not assumed)

Direct full-file measurement of all 21 raw provider files
`data/raw/binance_um/metrics/{BTCUSDT,ETHUSDT,SOLUSDT}/*-metrics-2026-09-01..07`:

- **288 rows per complete UTC day** → 21 files × 288 = **6,048 rows total** ✓
- Timestamp deltas **uniformly 300s** → 12 records/hour → **one record every 5 minutes**
- 288 unique timestamps per file; zero duplicates
- Provider row order is **not sorted** (observed: `00:00 → 00:15 → 00:25 → 00:30 …`); the timestamp *set* is a perfect 5m UTC grid. The normalizer sorts deterministically.

> Note: an early head-rows probe showed `00:00 → 00:15` and suggested 15m. That probe
> sampled the first rows only and was misleading. The full-file delta histogram is the
> authoritative evidence; the 15m declaration is retracted.

## Corrected contract (frozen)

| Constant | Value |
| --- | --- |
| `OPEN_INTEREST_NATIVE_PERIOD` | `5m` |
| `OPEN_INTEREST_EXPECTED_INTERVAL_SECONDS` | `300` |
| `OPEN_INTEREST_EXPECTED_ROWS_PER_DAY` | `288` |

Corrected in: `data_contracts.py`, `source_readers.py`, `data_quality.py`,
`tests/unit/research/test_data_admission.py`.

## Post-fix verification

- Data-admission tests: **22 passed / 0 failed** (incl. new 5m-grid gap test and row-order guarantee test)
- Ingestion re-run: **21 files → 6,048 OI rows, 0 quality errors, 0 duplicates, 0 missing 5m intervals**
- PIT invariant intact (`data_time <= decision cutoff`, no future interpolation / forward-fill)

## Scope discipline

Only Data-Admission OI metrics cadence declarations were corrected. Unrelated 15m
strategy/timeframe references elsewhere in the repository were deliberately untouched.

## Authority

Official Binance USD-M metrics archive files (data.binance.vision) measured directly;
checksums verified against official `.CHECKSUM` sidecars. No third-party source.
