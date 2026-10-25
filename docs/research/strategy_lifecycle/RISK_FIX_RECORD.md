# Risk fix record — DEF-RISK-EXPOSURE-001 (P0) & DEF-RISK-INERT-002 (P1)

File: `src/trading_bot/risk/manager.py`. Applied after GATE 0 confirmed the
PAPER campaign `paper-lab-continuous-03` is stopped (see `GATE0_AUDIT.md`).

## DEF-RISK-EXPOSURE-001 (P0)

`max_asset_exposure_pct` (config/risk.yaml `10`) was declared, range-validated
and cross-validated but read by nothing. `_compute_position_size` clamped only
`max_total_exposure_pct`, so three correlated positions on one asset could each
consume the full *total* budget.

**Fix:** `_compute_position_size` now clamps the notional by the asset's own
remaining budget (`equity * max_asset_exposure_pct/100 - current_asset_exposure`).
The clamp can only REDUCE the total-exposure result, never widen it. New helpers
`_asset_of`, `_position_notional`, `_position_asset`, `exposure_by_asset`.

**Reachability:** the PAPER runtime never populated `RiskManager.open_positions`
(it reconciles with the broker), so exposure was measured as 0. Added
`RiskManager.sync_open_positions(...)` and `AutonomousRuntime._sync_risk_positions()`
called at the top of `run_cycle`, so `check_signal` (called at
`runtime.py:1174` and `:1233`) now sees the live book. This also makes the
previously-inert `max_open_positions` gate real.

## DEF-RISK-INERT-002 (P1)

- `max_weekly_loss_pct`: `weekly_pnl` was accumulated but never compared. Now a
  `weekly_loss_limit` gate. `reset_daily` deliberately does NOT reset weekly P&L.
- `max_daily_drawdown_pct`: added `day_peak_equity` and a `daily_drawdown` gate
  (distinct from the all-time `max_total_drawdown_pct`).
- `consecutive_loss_cooldown_minutes`: the old gate was a permanent block. Now a
  real time-based cooldown anchored at the last loss (`_last_loss_ms`,
  injectable `_clock`); `0` preserves the legacy permanent block.

`restore_state`/`extract_state`/`snapshot` extended with `day_peak_equity`,
`last_loss_ms`, `daily_drawdown_pct`, `exposure_by_asset` (all additions are
backward-compatible keyword/defaults).

## Verification

- Behaviour probe: base notional 500 → clamped to 100 when BTC already carries
  900 of a 1000 asset budget; weekly gate blocks at -350/10000; cooldown blocks
  within 60 min and lifts after.
- `pytest tests/unit/config tests/unit/paper tests/unit/autonomous` → 317 passed.
- `pytest tests/integration` → 24 passed.
- `ruff check` clean on the file.

## Not done (out of scope, still open)

- DEF-HTF-PIT-001 (ORPHAN) — unit bug in `market_data/htf_pit.py`, no `src/` caller.
- DEF-MYPY-STRICT-001 — experimental driver typing error.
