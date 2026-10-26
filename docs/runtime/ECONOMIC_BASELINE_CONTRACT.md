# ECONOMIC BASELINE CONTRACT — RFC-010

Frozen before execution. Not modified after observing results (§36). If a change
proves necessary, a new `baseline_v2` is created and v1 preserved.

## Identity

| field | value |
| --- | --- |
| baseline_id | `RFC010-BASELINE-DEV` |
| code_sha | `6a9d47fa58fdecc56acae7af2ac60e732f63d591` (HEAD at freeze) |
| runtime_entrypoint | `scripts/autonomous_paper.py` (authoritative) |
| baseline_entrypoint | `scripts/rfc010_baseline_replay.py` (replay adapter, §12) |
| authority | `AutonomousPaperRuntime` — no reimplemented economics |

## Strategy set / versions

| field | value |
| --- | --- |
| registry | `config/strategy_admission.json` (AdmissionLedger) |
| families | ema_crossover, momentum, breakout, trend, mean_reversion, volatility |
| strategies | 24 declared (6 families × {5m,15m,30m,1h}) |
| timeframe evaluated | 5m |
| strategy_version convention | `<family>@<timeframe>` |
| admission policy | **unchanged** — `admitted_for_paper=false` strategies cannot order |

## Universe / data

| field | value |
| --- | --- |
| assets | BTC, ETH, SOL |
| timeframe | 5m |
| dataset | `reports/strategy-baseline/data/<SYM>_<W>_2026-0N.json` |
| dataset fingerprint | `reports/rfc010/DATASET_FINGERPRINTS.json` (corpus sha256 recorded) |
| start / end | 2026-03-01 → 2026-06-30 (DEV window W1–W4) |
| split | **DEV only**; VALIDATION (W5–W6) and OOS (W7) **not opened** (§10) |

## Execution economics

| field | value |
| --- | --- |
| initial_capital | 10,000 USDT |
| size_usd | 1,000 USDT requested per proposal |
| fees | COST_MODEL_V3 `BINANCE_SPOT_STANDARD_TAKER` (10 bps maker / 10 bps taker) |
| slippage | per COST_MODEL_V3 component |
| spread | **ESTIMATED** = 1.0 bps (`_MAJORS_SPREAD_BPS` default); dataset has no historical spread series |
| funding | NOT_APPLICABLE (spot) |
| borrow | NOT_APPLICABLE (no short instrument; long/flat only) |
| cost class | cost evaluated **per cycle** for the concrete size/horizon; never carried over |

## Risk / sizing

| field | value |
| --- | --- |
| risk config | `config/realdata/risk.yaml` (unchanged) |
| sizing | `RiskManager._compute_position_size` (single authority) |
| max asset exposure | per config (`max_asset_exposure_pct`), enforced |
| max total exposure | per config, enforced |
| daily drawdown / weekly loss / cooldown | per config, enforced |
| kill switch | disabled for the scan settings (paper research mode) |

## Runtime semantics

| field | value |
| --- | --- |
| routing mode | **LEGACY** (runtime default) |
| horizon_minutes | 5.0 (one 5m bar) |
| lookback_bars | 120 |
| warmup | first 100 sealed bars (scanner `min_history=100`); the first ~120 instants are warmup |
| cadence | one decision every 60th sealed 5m bar (uniform; compute-feasibility, not an economic parameter) |
| random seed | none — the runtime is deterministic; no RNG in the path |
| regime model | `asset-agent-regime-v1` (PIT, inside `build_context`) |
| reconciliation | `PaperBroker.reconcile_session` + `StartupReconcilerV4` |

## Prohibitions honoured

No tuning, no parameter search, no asset/period cherry-picking, no threshold
relaxation, no new strategies/agents/pods, no OOS, no LIVE. The baseline measures
the current certified runtime as-is.
