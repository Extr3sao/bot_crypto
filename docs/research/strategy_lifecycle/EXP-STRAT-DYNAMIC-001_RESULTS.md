# EXP-STRAT-DYNAMIC-001 — recorded results

- Driver: `scripts/strategy_dynamic_experiment.py`
- Artifacts: `reports/strategy-dynamic/EXP-STRAT-DYNAMIC-001.{json,md}`
- Run commit: `fe05bc3` (recorded in the artifact)
- Dataset: BTCUSDT W1..W7 (5m), `reports/strategy-baseline/data`
- Economics: fees 5 bps, slippage 1 bp, TP 0.75%, risk 0.25%, start equity 10 000
- Static family (chosen on DEV only): `volatility`

## Results

| split | arm | trades | net | expectancy | win_rate | PF | max_dd% |
|---|---|---|---|---|---|---|---|
| DEV (W1–W4) | static | 80 | -54.42 | -0.68 | 41.25 | 0.653 | 0.646 |
| DEV | dynamic | 0 | 0.00 | 0.0 | 0.0 | — | 0.0 |
| VALIDATION (W5–W6) | static | — | -20.50 | — | — | — | — |
| VALIDATION | dynamic | 0 | 0.00 | 0.0 | 0.0 | — | 0.0 |
| OOS_LOCKED (W7) | static | — | -13.53 | — | — | — | — |
| OOS_LOCKED | dynamic | 0 | 0.00 | 0.0 | 0.0 | — | 0.0 |

- Transitions: **0**. Final states: every family stayed `SHADOW`.
- Activation churn: all zeros.

## Verdict: `DO_NOT_PROMOTE`

The preregistered evidence gate (≥40 medium samples, ≥15 samples in the current
regime cell, stability, profit factor, cost-adjusted positivity) was not met for
any family/regime cell within the available trade volume, so the dynamic arm
abstained entirely. **An abstaining arm is not a winning arm**: 0 trades
demonstrates no measurable value, and the run is recorded as `DO_NOT_PROMOTE`,
not as an improvement over a losing static arm. Reporting it as "improved"
(the naive `0 > -74.92`) would be a false success.

## What this does and does not show

- DOES show: the gate is conservative and NO_TRADE is a real, first-class
  outcome; the static single-family router lost money on this dataset.
- Does NOT show: that the dynamic architecture improves returns. That claim is
  unproven at this evidence volume.
- Next authorized step (not done): re-run with a preregistered *lower* sample
  gate OR a longer history (the forward collector's 24 h+ capture) and compare
  again on DEV/VAL/OOS. Any such change must be preregistered and independently
  verified; it must not be tuned to make the dynamic arm look good.
