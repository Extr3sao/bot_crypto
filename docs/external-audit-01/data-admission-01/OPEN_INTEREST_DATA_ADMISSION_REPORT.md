# OPEN INTEREST DATA ADMISSION REPORT — ALPHA-DATA-ADMISSION-01

**Decision: `ADMIT`** · Family: open interest / position-stock metrics (DATA-FAMILY-B) · Source: `SOURCE_BINANCE_VISION_USDM_METRICS_DAILY` (official data.binance.vision)

## Scorecard

| Dimension | Score | Evidence |
| --- | --- | --- |
| DATA_AUTHORITY | 5/5 | official archive; `.CHECKSUM` sha256 sidecars verified 21/21 |
| HISTORICAL_DEPTH | 4/5 | BTC from **2020-09-01**, ETH/SOL from **2021-12-01** (probed independently per asset) → 2026-09-10; 0 missing files |
| PIT_SAFETY | 5/5 | observation-time semantics; no interpolation/forward-fill; REST deep history verified insufficient (error `-1130` on 39-day-old window) → archive is the deep source |
| QUALITY | 5/5 | **6,048 rows = 21 × 288**; exact 5m UTC grid (uniform 300s deltas); 0 duplicates; 0 missing intervals; DEF-DATA-OI-001 corrected |
| INFORMATION_DISTINCTNESS | YES | outstanding **position-stock** information — categorically distinct from transaction-flow (Track J, data-level only) |
| COST | 5/5 | full ~6-year, 3-symbol history ≈ **66 MB compressed** |
| STORAGE | 5/5 | ~12 KB/day/symbol |
| PORTABILITY | 5/5 | plain zip+CSV + sha256 sidecars |

## Unit semantics (UNIT_AUTHORITY = OFFICIAL_DOCUMENTED)

| Field | Source column | Unit |
| --- | --- | --- |
| `open_interest_contracts` | `sum_open_interest` | base-asset units (BTC for BTCUSDT) — per official binance-public-data README |
| `open_interest_value` | `sum_open_interest_value` | USDT notional |

The two are never conflated; REST `sumOpenInterest`/`sumOpenInterestValue` map to the same semantics.

## REST vs archive (empirically verified)

`REST_HISTORY_LIMIT ≈ 30 days`: a request with `startTime` 39 days old was **rejected (error -1130)** while a recent window works — so the ~30-day ceiling applies to USD-M `openInterestHist`. The official archive (2020-09 → present) is the only deep PIT-safe path. **No scraped or third-party substitutes were used.**

## Sample evidence

| Item | Value |
| --- | --- |
| Files | 21 (3 symbols × 7 days, 2026-09-01..07) |
| Rows | 6,048 (288/day/symbol, native **5m** cadence) |
| Official checksum | PASS 21/21 |
| Quality errors | 0 |
| PIT | 6,048/6,048 within cutoff |
| Manifest | `data/processed/open_interest/DATASET_MANIFEST.json` (run-B, `normalizer_commit=ec2483f`) |

## Limitations

1. ETH/SOL depth starts 2021-12-01 (independently probed — not inferred from BTC).
2. Aggregate 5m snapshots only (no per-account/per-price-level data).
3. Raw provider files are not row-sorted; the deterministic normalizer performs the canonical sort.

Machine-readable: `OPEN_INTEREST_DATA_ADMISSION_REPORT.json`.
