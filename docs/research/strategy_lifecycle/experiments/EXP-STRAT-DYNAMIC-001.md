# EXP-STRAT-DYNAMIC-001 (preregistration)

- Driver: `scripts/strategy_dynamic_experiment.py`
- Output: `reports/strategy-dynamic/EXP-STRAT-DYNAMIC-001.{json,md}`
- Commit at authoring: recorded in the output's `commit` field.

## Objective

Compare `CURRENT_STATIC_ROUTER` (one fixed family, always on) against
`DYNAMIC_STRATEGY_ECOSYSTEM` (lifecycle-gated multi-strategy) under identical
conditions.

## Controls (identical in both arms)

- Same dataset: `reports/strategy-baseline/data`, BTCUSDT W1..W7 (5m).
- Same families: ema_crossover, momentum, breakout, trend, mean_reversion, volatility.
- Same economics: fees 5 bps, slippage 1 bp, TP 0.75%, risk 0.25%, start equity 10 000.
- Same trade machinery: both arms consume the SAME per-family trade stream from
  `multi_family_backtest.simulate_family`; only the *selector* differs.
- Same periods and regime labels (deterministic `_regime`, no lookahead).

## Splits (preregistered, before results)

- DEV: W1..W4 (used only to pick the static family).
- VALIDATION: W5..W6 (used for the decision).
- OOS: W7 — **LOCKED**, reported but never used to choose/tune anything.

## Metrics

net PnL, expectancy, win rate, profit factor, max drawdown %, Sharpe proxy, trade
count, activation churn (activations/pauses/reactivations/reversals/time in state),
and the lifecycle transition log.

## Decision rule (preregistered)

- If DEV+VALIDATION dynamic net > static net → `PROMOTE_CANDIDATE`.
- Else → `DO_NOT_PROMOTE`.

## Non-goals / honesty

- The experiment is NOT tuned to make the dynamic arm win.
- `independent_verification_required` is set False **in the offline loop only**
  (there is no IndependentVerifier in a backtest); the runtime default stays True.
  This is recorded so the relaxation is visible.
- A result of `DO_NOT_PROMOTE` is a valid, useful outcome.
