# PIT Causality V2 Report — PIT-CAUSALITY-REPAIR-01 + OI-DATASET-REFREEZE-02

**Verdict:** PASS

## Defect repaired: EXT-PIT-001

V1 `src/trading_bot/research/oi_dataset.py:valid_days_for` / `iter_oi_rows` gated historical eligibility on final UTC-day `VALID` classification. A later same-day missing snapshot (at `T+N`) invalidated the whole day and removed observations at `T` — a forbidden day-level future-knowledge dependency. The supplied harness was vacuous because it could not prove `DECISION_ELIGIBLE_AT_T = true` before mutation.

## V2 causal reader

`src/trading_bot/research/oi_dataset_v2.py`:

- `oi_state_at(symbol, decision_time, ...)` — only records with `record_time <= decision_time`. Never queries “Will this UTC day ultimately be VALID?”.
- `decision_eligibility_at_v2(T, symbol, data_dir)` — strictly causal checks:
  1. Current completed hour `[T-1h, T)` has exactly 12 distinct 5m snapshots.
  2. Previous hour `[T-2h, T-1h)` has exactly 12 distinct snapshots.
  3. No conflicting duplicate with `timestamp <= T`.
  4. Rolling feature history ≥ 336 valid hourly changes (causal, timestamp-scoped).
  5. Last observation not stale (`≤ 600s`).
  6. Nothing `> T` is read.
- Ledger `OI_ARCHIVE_DAY_VALIDITY_LEDGER_V2.jsonl` is **forensic-only** EVIDENCE; it MUST NOT gate trading decisions.
- `iter_oi_rows_v2` scans the filesystem for existing shards (only `VALID` days have shards on disk), sorted canonically, with no ledger validity query.

## Non-vacuous adversarial tests

`tests/unit/research/test_oi_full_history_v2_pit.py` requires `current_hour_complete == true` at baseline `T` before any mutation.

| Test | Baseline | Mutation | Expected | Result |
|------|----------|----------|----------|--------|
| **A. FUTURE_SAME_DAY_GAP_AFTER_T** | `ELIGIBLE` (or at least current-hour complete) at T | Remove observation at T+2h (same day, future) — mutate shard file | `eligibility_at_T_before == eligibility_at_T_after`, `FEATURE_STATE_AT_T` byte-identical | **PASS** |
| **B. FUTURE_MUTATION_AFTER_T** | same | Change OI values strictly > T | same state at T | **PASS** |
| **C. FUTURE_FILE_ADDITION** | same | Add next-day file (`2024-06-16`) | same state at T | **PASS** |
| **D. PAST_GAP_BEFORE_T** | same | Remove required observation < T inside completed hour | `eligible` → `false`, `current_hour_complete == false` | **PASS** |
| **E. OUT_OF_ORDER** | — | Shuffle rows inside shard | Canonical sorted state unchanged | **PASS** |
| **F. EXACT_DUPLICATE** | raw with every row doubled identically | Collapse authorized duplicates | `VALID`, `exact_duplicate_rows_collapsed == 288` | **PASS** |
| **G. CONFLICTING_DUPLICATE** | `eligible` at T | Append same-ts different-payload duplicate ≤ T | `CONFLICTING_DUPLICATE` → ineligible | **PASS** |

All 12 tests in the file pass (7 adversarial + guards + sign rule + whitelist + fingerprint).

## API contract

```python
oi_state_at(symbol="BTCUSDT", decision_time=T)  # only records with record_time <= T
decision_eligibility_at_v2(T_ms, symbol="BTCUSDT", data_dir=...)  # causal, no day-level gate
```

A gap strictly **after** T must not alter eligibility or feature/signal state at T. A gap strictly **before** T may.

## Evidence

- `src/trading_bot/research/oi_dataset_v2.py` committed — no `valid_days_for` import, no ledger validity gate in eligibility.
- `docs/external-audit-01/oi-full-history-02/OI_DATASET_V2_DETERMINISM_REPORT.json` proves byte-identical reconstructions.
- `docs/external-audit-01/oi-full-history-02/EXT_DATA_001_FORENSIC_REPORT.md` proves contamination removed; V2 BTC 2024-06-05 bytes are clean `bcd3d8...`.

## Status

`PIT_CAUSALITY_V2 = PASS` — historical eligibility is timestamp-scoped causal; the V1 day-level defect does not exist in the V2 trading path.
