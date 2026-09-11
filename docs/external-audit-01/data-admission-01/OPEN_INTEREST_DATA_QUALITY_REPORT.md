# OPEN INTEREST DATA QUALITY REPORT — ALPHA-DATA-ADMISSION-01

**Verdict: `PASS`** · Engine: `src/trading_bot/research/data_quality.py` · Manifest: `data/processed/open_interest/DATASET_MANIFEST.json` (run-B, `normalizer_commit=ec2483f`)

| Metric | Value |
| --- | --- |
| Files | 21 (3 symbols × 7 days, 2026-09-01..07) |
| Rows total | 6,048 (= 21 × 288) |
| Native cadence | **5m** (288 rows/complete UTC day — DEF-DATA-OI-001 corrected) |
| Rows within PIT cutoff | 6,048 (100%) |
| Files with quality errors | **0** |
| Official checksum verified | 21/21 |
| Provenance coverage | raw_source_sha256 ✓ · normalized_sha256 ✓ · dataset_fingerprint ✓ |

Checks applied: exact 5m UTC grid (0 missing intervals, uniform 300s deltas), duplicate timestamps (0), monotonicity after canonical sort (provider files are not row-sorted; the normalizer is), schema drift, nulls, non-positive values, PIT cutoff (`data_time <= day end`), no future interpolation / forward-fill.

Detail (machine-readable): `OPEN_INTEREST_DATA_QUALITY_REPORT.json`.
