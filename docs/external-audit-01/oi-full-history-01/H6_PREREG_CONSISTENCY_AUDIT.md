# H6 PREREG CONSISTENCY AUDIT — P0-C

Checkpoint: `OI-FULL-HISTORY-FREEZE-01 + H6-HYPOTHESIS-SELECTION-AND-PREREG-ONLY` · 2026-09-11
Machine-readable: `H6_PREREG_CONSISTENCY_AUDIT.json` · **Result: `PASS` — `UNRESOLVED_FIELDS = []` (30/30 dimensions resolved, commit allowed)**

## Contested dimensions resolved to single canonical semantics

| Dimension | Frozen canonical value |
| --- | --- |
| continuation vs reversal | **continuation only** — expansion qualifies; OI contraction ⇒ `NO_TRADE` (a contraction-reversal variant would need its own prereg) |
| holding horizon | **1h primary** (`decision_timeframe.primary_holding_horizon_hours = 1`); secondary horizons not computed |
| exit | **time exit** — next 1h bar close; **no ATR stop, no signal-flip exit** |
| cooldown | **NONE** (fixed 1h non-overlapping per-asset outcomes) |
| cost | **`BASE_TOTAL_ROUND_TRIP_COST_BPS = 10`** — one canonical TOTAL RT number; not 5+2 decomposition (which would be 14); sensitivity 0/10/20/40 bps as diagnostics; gross metrics mandatory |
| funding | **`EXCLUDED_WITH_LIMITATION`** + `funding_materiality_gate_before_promotion = true` (no authoritative funding series for all three assets) |
| orthogonality | **`MAX_ABS_DAILY_CORRELATION_TO_MOMENTUM_PROXY = 0.50`** (0.70 removed); H5 comparator = `NOT_EVALUABLE_FROM_PERSISTED_EVIDENCE` |
| experiment identity | **`experiment_id = 1` (integer)**, `hypothesis_id = "H6-OI-POSITION-STOCK-01"` |
| z-score scale | **median / 1.4826·MAD** (rolling std removed); trailing 720 completed hourly changes; min 336 observations; MAD=0 ⇒ `NO_SIGNAL` |
| price filter | **no separate price threshold** — direction from completed-hour close vs open (UP/DOWN/NO_SIGNAL) |
| eligibility model | **`DECISION_ELIGIBILITY_AT_T` causal** (P0-B/H) — archive day validity is evidence only; gaps after T cannot change state at T |
| H5 integrity | result/spec/manifest hashes re-verified unchanged in the manifest (`H5_state_untouched`) |

## Cross-artifact consistency

- `H6_MANIFEST.spec.sha256` == sha256 of the frozen `H6_SPEC.json` bytes (`f514fecf…`)
- manifest assets/window/gates mirror the spec exactly (orthogonality 0.50 in both)
- whitelist OI fields == `spec.oi_field_whitelist`
- manifest carries `entry_timing/exit_timing/stop/cooldown/cost_model/funding_accounting` mirrors (P0-D/E/F states)
- no prereg-commit self-reference inside the manifest (P0-J)

## Note on process

An initial audit run surfaced 2 unresolved cross-artifact fields (manifest still carried 0.70 / stale spec hash). Both were reconciled to the corrected spec **before** any prereg commit (pre-commit reconciliation is the only window in which such edits are permitted). The final audit runs clean: `CONTRADICTIONS_FOUND = 0`, `commit_allowed = true`.
