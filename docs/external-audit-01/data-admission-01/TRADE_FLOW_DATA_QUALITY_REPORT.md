# TRADE FLOW DATA QUALITY REPORT — ALPHA-DATA-ADMISSION-01

**Verdict: `PASS`** · Engine: `src/trading_bot/research/data_quality.py` · Manifest: `data/processed/trade_flow/DATASET_MANIFEST.json` (run-B, `normalizer_commit=ec2483f`)

| Metric | Value |
| --- | --- |
| Files | 21 (3 symbols × 7 days, 2026-09-01..07) |
| Rows total | 16,269,514 |
| Rows within PIT cutoff | 16,269,514 (100%) |
| Files with quality errors | **0** |
| Official checksum verified | 21/21 |
| Provenance coverage | raw_source_sha256 ✓ · normalized_sha256 ✓ · dataset_fingerprint ✓ |

Checks applied by the engine (deterministic, no network): timestamp ordering (after canonical sort), duplicate `agg_trade_id` detection, schema drift, nulls, non-positive price/quantity, out-of-order provider rows, PIT cutoff (`trade_time <= day end`), future-record exclusion. Direction semantics per frozen contract (`buyer_is_maker` → taker side).

Detail (machine-readable): `TRADE_FLOW_DATA_QUALITY_REPORT.json`.
