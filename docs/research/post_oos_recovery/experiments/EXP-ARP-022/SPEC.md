# EXP-ARP-022 — SPEC (pre-registered BEFORE any result)

## Identity

- experiment_id: `EXP-ARP-022`
- strategy_id: `H-INTERMARKET-RISKAPP-001` (**NEW mechanism**)
- arm: `PROJECT_DERIVED_VARIANT`
- mechanism family: **intermarket signals / multi-asset rotation**
- grounding: the daily corpus carries both `BTCUSDT` and `ETHUSDT`, so the
  ETH/BTC ratio is a PIT-computable cross-market variable. This tests a ratio
  between two markets as the decision variable.

## Why this is NOT an EXP-ARP-008 variant

EXP-ARP-008 reads one asset's own price history. Here the decision variable is a
*ratio of two different markets* (ETH/BTC) and the action is a rotation between
BTC and a liquid alt basket — an intermarket signal, not a per-asset trend.

## Rules (frozen)

1. `risk_on = ETHBTC_close_t > SMA50(ETHBTC)_t`, computed on closed bars only.
2. If `risk_on`, hold an equal-weight top-20 liquid non-BTC alt basket; else
   hold `BTCUSDT`.
3. Rebalance weekly at the UTC close; act at the next open; only trade on a
   regime flip or a basket-membership change.
4. One leg at a time; fixed total notional 500 USD; no compounding; one
   round-trip cost per rotation.

## Parameters (frozen, a priori)

`lookback_days=50`, `alt_basket_size=20`, `min_members=5`, `max_hold_days=7`.

## Assets / timeframe / splits

- assets: `DYNAMIC_ASSET_UNIVERSE(ARP-006-UNIVERSE-v1)`
- timeframe: `1d`
- DEV 2019-01-01 .. 2024-01-01 · VALIDATION 2024-01-01 .. 2025-07-01 ·
  OOS_LOCK 2026-03-01 .. 2027-03-01 (**forward PAPER only; locked**).

## Cost model

`COST_MODEL_V3` via the live `CostEngine`; stress 0.5/1.0/1.25/1.5/2.0.

## PIT contract

`data_time <= decision_time <= fill_time`; the SMA and the alt basket
membership read closed bars only. `SURVIVORSHIP_DATA_LIMITATION` binds the
cross-sectional basket.

## Kill criteria (frozen)

`REJECT_NO_EDGE`, `REJECT_COSTS`, `REJECT_INSUFFICIENT_SAMPLE`,
`REJECT_FRAGILE`, `REJECT_PIT` on DEV; `REJECT_VALIDATION` if VALIDATION net
`<= 0`.

## Status

`PREREGISTERED_NOT_IMPLEMENTED`. OOS **LOCKED**.
