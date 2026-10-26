# EXP-ARP-020 — SPEC (pre-registered BEFORE any result)

## Identity

- experiment_id: `EXP-ARP-020`
- strategy_id: `H-VOLMAN-ALLOC-001` (**NEW mechanism** — not an EXP-ARP-008 variant)
- arm: `PROJECT_DERIVED_VARIANT`
- mechanism family: **volatility regime allocation / volatility-managed exposure**
- grounding: the regime machinery already labels volatility buckets
  (`research/diversified/analytics.py::regime_by_day`). This tests whether
  scaling a fixed basket by its own realized volatility is a distinct,
  cost-surviving mechanism.

## Why this is NOT an EXP-ARP-008 variant

There is **no directional signal**. Exposure is `min(1, target_vol /
realized_vol_t)`; the strategy never predicts return direction. EXP-ARP-008 is a
directional `close_t > close_{t-lookback}` rule on one asset at a time.

## Rules (frozen)

1. Maintain a long BTC/ETH/SOL equal-weight basket continuously.
2. `realized_vol_t` = 20-day population standard deviation of the basket's
   daily log returns, using only bars closed at or before the decision time.
3. Weight `w_t = min(1, target_vol / realized_vol_t)`, `target_vol = 0.5`
   annualized; `w_t` in `[0, 1]`.
4. Rebalance weekly at the UTC close; act at the next open.
5. Fixed base notional 500 USD; no compounding; one round-trip cost per weight
   change.

## Parameters (frozen, a priori)

`lookback_days=20`, `target_vol_annual=0.5`, `max_hold_days=7`.

## Assets / timeframe / splits

- assets: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`
- timeframe: `1d`
- DEV 2019-01-01 .. 2024-01-01 · VALIDATION 2024-01-01 .. 2025-07-01 ·
  OOS_LOCK 2026-03-01 .. 2027-03-01 (**forward PAPER only; locked**).

## Cost model

`COST_MODEL_V3` via the live `CostEngine`; stress 0.5/1.0/1.25/1.5/2.0.

## PIT contract

`data_time <= decision_time <= fill_time`; volatility reads closed bars only.

## Kill criteria (frozen)

`REJECT_NO_EDGE`, `REJECT_COSTS`, `REJECT_INSUFFICIENT_SAMPLE`,
`REJECT_FRAGILE`, `REJECT_PIT` on DEV; `REJECT_VALIDATION` if VALIDATION net
`<= 0`.

## Status

`PREREGISTERED_NOT_IMPLEMENTED`. OOS **LOCKED**.
