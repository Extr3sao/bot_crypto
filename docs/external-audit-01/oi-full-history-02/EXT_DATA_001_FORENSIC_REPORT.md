# EXT-DATA-001 FORENSIC REPORT — BTCUSDT 2024-06-05 normalized leakage

**Date:** 2026-09-12 (rebuild V2)  
**Checkpoint:** OI-DATASET-REFREEZE-02 + PIT-CAUSALITY-REPAIR-01  
**Defect:** EXT-DATA-001 — dataset fingerprint mismatch (`16779b7d...` declared vs `5e2a10f7...` verifier recomputation)

## 1. Raw authority

- Raw zip: `data/raw/binance_um/metrics/BTCUSDT/BTCUSDT-metrics-2024-06-05.zip`
  - `RAW_SHA256 = 0ef289911a8aa9bd0ee68ab04473dca51c815bfca438629d580aa2fcb0e06058`
  - `sidecar .CHECKSUM PASS` — byte-identical to official Binance vision archive.
  - `raw_row_count = 288` (no provider duplicate era; this day is outside the 2020-09..2021-05 exact-duplicate era)
  - `distinct_timestamps = 288`
  - `exact_duplicate_collapsed = 0`
  - `conflicting_duplicate = 0`
  - `invalid_values = 0`, `missing = 0`, `off_grid = 0`, `future_rows = 0`
  - `first_timestamp_ms = 1717545600000` (`2024-06-05T00:00:00Z`)
  - `last_timestamp_ms  = 1717631700000` (`2024-06-05T23:55:00Z`)
  - `grid_gaps = 0`
- Provider header verified: `create_time,symbol,sum_open_interest,sum_open_interest_value,count_toptrader_long_short_ratio,...` — `create_time` is `YYYY-MM-DD HH:MM:SS` UTC string.

## 2. Independent reconstructions (A and B)

Two independent clean normalizations were produced into separate isolated dirs (`tmp_A`, `tmp_B`) using `process_file_v2()` from `scripts/normalize_oi_full_history_v2.py` (schema `2.0.1`, normalizer `2.1.0`):

- `NORMALIZED_A_SHA = bcd3d84950632e7cc70434b75b135bf1eaf56c4ebe72fd13fbea2bbb510a1fb7`
- `NORMALIZED_B_SHA = bcd3d84950632e7cc70434b75b135bf1eaf56c4ebe72fd13fbea2bbb510a1fb7`
- Requirement `NORMALIZED_A_SHA == NORMALIZED_B_SHA` **PASS** — byte-identical.

First line (canonical, deterministically sorted):
```
{"source_file":"data/raw/binance_um/metrics/BTCUSDT/BTCUSDT-metrics-2024-06-05.zip","source_sha256":"0ef289911a8aa9bd0ee68ab04473dca51c815bfca438629d580aa2fcb0e06058","sum_open_interest":81040.448,"sum_open_interest_value":5721504253.0688,"timestamp_ms":1717545600000,"unit_semantics":"BASE_ASSET_UNITS"}
```

- `V1 normalized path on contaminated FS`: `data/processed/oi_full_history/BTCUSDT/BTCUSDT-oi-5m-2024-06-05.jsonl`
  - `V1_contaminated_SHA = 2e74565fd7f3768d465075b77ca2422da7364291edec6b94f1c8cd9ec9da7dfb`
  - First line:
  ```
  {"source_file":"C:/Users/GVLLFR0035/AppData/Local/Temp/pytest-of-GVLLFR0035/pytest-2077/test_valid_day_classification0/BTCUSDT/BTCUSDT-metrics-2024-06-05.zip","source_sha256":"1fc63fa74517b6fac1799c124446013d5842d7bf88a1d98cac957d1414b0c051","sum_open_interest":100.0,"sum_open_interest_value":5000.0,"timestamp_ms":1717545600000,"unit_semantics":"BASE_ASSET_UNITS"}
  ```
- `V1 ledger entry` for same day correctly declared `normalized_sha256 = bcd3d8...` and `dataset_fingerprint = 2c823c02...` (i.e., ledger matches the clean reconstruction, NOT the contaminated file).
- `V1 manifest` global fingerprint `16779b7d...` was computed from the *ledger* values (`bcd3d8...`), not from the actual contaminated file bytes (`2e74...`).

## 3. Ledger vs bytes divergence

| Artifact | `normalized_sha256` | `dataset_fingerprint` |
|---|---|---|
| `V1 ledger` (committed evidence) | `bcd3d849...` (clean) | `2c823c02...` (clean) |
| `V1 actual bytes` (on disk) | `2e74565f...` (synthetic) | `0eb8aaff...` (synthetic) |
| `V2 clean A/B` | `bcd3d849...` | `2c823c02...` |
| `Verifier independent` | `bcd3d849...` expected clean; verifier measured synthetic bytes `2e74...` for that single file, then overall fingerprint `5e2a10...` | verifier overall `5e2a10...` differs from `16779b...` because the single file disagreement propagates into the canonical global hash |

Thus `NORMALIZED_BYTES_DIFFER_FROM_RAW_RECONSTRUCTION` and the two `LEDGER_MISMATCH` errors in `external-verification/dataset_independent_results.json` are explained by a single contaminated file whose bytes are synthetic test artifacts, while the ledger entry was correct.

## 4. Root cause — Proven, not guessed

**Root cause = synthetic unit-test artifact pollution via canonical output-path write during pytest.**

- `tests/unit/research/test_oi_full_history.py::test_valid_day_classification` calls `process_file(...)` (the V1 normalizer) with `raw_dir=tmp_path` but `out_dir` defaults to the canonical `data/processed/oi_full_history/`. The helper `_make_metrics_zip` generates synthetic metrics zips under `tmp_path` and for `day="2024-06-05"` the synthetic payload is `sum_open_interest=100.0, sum_open_interest_value=5000.0` plus a Windows temp path `C:/Users/GVLLFR0035/AppData/Local/Temp/pytest-of-GVLLFR0035/pytest-2077/test_valid_day_classification0/...` as `source_file` and its SHA as `source_sha256`.
- Because `out_dir` was not isolated, `process_file` wrote the synthetic normalized artifact directly to `data/processed/oi_full_history/BTCUSDT/BTCUSDT-oi-5m-2024-06-05.jsonl`, overwriting the correctly normalized clean file produced during the original freeze run (`ec2483f`). The ledger/manifest generation step (a separate batch job that consumed the correct raw file at `data/raw/.../BTCUSDT-metrics-2024-06-05.zip` independently) recorded the *clean* hash `bcd3d8...` — the test never updated the ledger, only the file.
- Historical git: the ledger and manifest were committed at `256bd5e` with clean values; the contaminated `.jsonl` file itself is `.gitignore`d (`data/processed/*`) and never tracked, so git never detected the drift. The verifier independently re-derived the clean bytes from the raw zip and found the on-disk file to be `2e74...`, causing `NORMALIZED_BYTES_DIFFER`, `LEDGER_MISMATCH` on `normalized_sha256`, and the global fingerprint `5e2a10...` vs `16779b...`.
- Controls absent: no `TEST_DATASET_WRITE_FORBIDDEN` guard existed; `process_file` signature allowed default `out_dir=OUT` even under `PYTEST_CURRENT_TEST`; no per-file normalized SHA audit existed at test time.

### Provenance chain (evidence)

1. `data/processed/oi_full_history/BTCUSDT/BTCUSDT-oi-5m-2024-06-05.jsonl` on the pre-repair FS contains `C:/Users/GVLLFR0035/AppData/Local/Temp/pytest-of-GVLLFR0035/pytest-2077/test_valid_day_classification0/...` — string only ever produced by the synthetic test helper.
2. `tests/unit/research/test_oi_full_history.py::_make_metrics_zip` generates `rows.append((t, symbol, f"100.0", f"5000.0"))` synthetic OI row pattern — matches the contaminated file's `100.0 / 5000.0` payload.
3. The verifier independently reconstructed the clean file (`bcd3d8...`, `81040.448 / 5721504253.0688`) from the raw authority; this matches the V2 rebuild `bcd3d8...`.
4. The ledger entry at `256bd5e` and on-disk ledger after contamination both still read `bcd3d8...` — proving the contamination is file-only, ledger-correct.

## 5. Repair

- Created isolated V2 output root `data/processed/oi_full_history_v2/` (never reused V1 root).
- Created `scripts/normalize_oi_full_history_v2.py::process_file_v2` with fail-closed `TEST_DATASET_WRITE_FORBIDDEN` guard: under `PYTEST_CURRENT_TEST`, any attempt to write to `data/processed/oi_full_history` or `data/processed/oi_full_history_v2` or the evidence dir raises immediately.
- Full rebuild of all 5,691 archives into V2: `quality_status = PASS_WITH_EXPLICIT_GAPS` (5596 VALID / 95 invalid), clean `OI_FULL_HISTORY_DATASET_SHA256_V2 = 16779b7d2eff0dc9e56015c444c2dbe7b67ef083e6cf1877a024a6de74098d99` (re-derived independently; matches old declared because only the single file was corrected).
- Two independent builds into separate temp dirs gave `DATASET_SHA_A == DATASET_SHA_B` and `PER_FILE_SHA_A == B` for every file (determinism PASS).
- Synthetic single-field mutation test gives `DATASET_SHA_C != DATASET_SHA_A` (sensitivity PASS).
- Ledger V2 `OI_ARCHIVE_DAY_VALIDITY_LEDGER_V2.jsonl` regenerated from V2 artifacts (forensic only; not used as trading gate).
- Original contaminated V1 file left untracked but evidence preserved here; V1 directory not reused as V2 build output; V2 commit will force-add only the evidence copies in `docs/external-audit-01/oi-full-history-02/`.

## 6. Checks after repair

- `2024-06-05` normalized bytes in V2 == `bcd3d849...` (clean) and ledger entry == `bcd3d849...` (agreement PASS).
- Global `OI_FULL_HISTORY_DATASET_SHA256_V2` recomputed from V2 ledger == manifest value (`16779b7d...`) and `A==B`.
- No test in the suite can pollute V2: guard + regression `test_v2_test_isolation_forbids_canonical_write.py` prove `TEST_DATASET_WRITE_FORBIDDEN` is raised.

## 7. Decision

`EXT-DATA-001 STATUS = REPAIRED_VERIFIED` — contamination isolated, root cause proven, V2 dataset independently rebuilt and byte-anchored; ready for preregistration V2.
