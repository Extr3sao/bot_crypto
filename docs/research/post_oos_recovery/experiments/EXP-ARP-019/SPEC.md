# EXP-ARP-019 — SPEC (pre-registered BEFORE any result)

## Identity

- experiment_id: `EXP-ARP-019`
- strategy_id: `H-BREADTH-REGIME-001` (**NEW mechanism** — not an EXP-ARP-008 variant)
- arm: `PROJECT_DERIVED_VARIANT`
- mechanism family: **trend breadth / market-regime allocation**
- grounding: the broad-universe daily corpus (`ARP-006-UNIVERSE-v1`) already
  computes a breadth summary over the eligible universe
  (`research/diversified/analytics.py::breadth_summary`). This tests the
  breadth aggregate itself as a *market-timing gate*, a mechanism distinct from
  EXP-ARP-008's per-asset `close_t > close_{t-lookback}` trend.

## Why this is NOT an EXP-ARP-008 variant

EXP-ARP-008 predicts each asset's direction independently and trades one asset.
Here the signal is a single cross-sectional statistic (the share of the
universe above its own moving average) and the traded object is an equal-weight
basket. No per-asset trend rule is used and no asset is selected. Under §13 this
is a materially different mechanism.

## Rules (frozen)

1. On each daily close compute `B_t = share{ asset in eligible universe :
   close_t > SMA50_t }`, using only bars closed at or before the decision time.
2. Eligible universe is the PIT-safe `DynamicAssetUniverse` snapshot (listing
   time, min history, liquidity floor, staleness, gap and synchronization rules
   unchanged). Require `members >= min_members`.
3. Long an equal-weight basket of the eligible universe when `B_t >= 0.55`;
   flat when `B_t <= 0.45`; inside the band, hold the prior state (hysteresis).
4. Enter/exit at the **next** day's open (no same-bar fill).
5. One basket position at a time; fixed total notional 500 USD; no compounding;
   single round-trip cost per basket rebalance.

## Parameters (frozen, a priori)

`lookback_days=50`, `entry_breadth=0.55`, `exit_breadth=0.45`,
`min_members=5`, `max_hold_days=30`.

## Assets / timeframe / splits

- assets: `DYNAMIC_ASSET_UNIVERSE(ARP-006-UNIVERSE-v1)`
- timeframe: `1d`
- DEV 2019-01-01 .. 2024-01-01 · VALIDATION 2024-01-01 .. 2025-07-01 ·
  OOS_LOCK 2026-03-01 .. 2027-03-01 (**forward PAPER only; not available for
  this phase — see `NEW_HOLDOUT_PLAN.md`**).

## Cost model

`COST_MODEL_V3` via the live `CostEngine` (never hardcoded); stress
0.5/1.0/1.25/1.5/2.0.

## PIT contract

`data_time <= decision_time <= fill_time`. SMA reads only closed bars; breadth
is computed at the decision close; entry/exit at the next open. The first
evaluable day is `t >= 50`.

## Kill criteria (frozen)

Same as the manifest: `REJECT_NO_EDGE`, `REJECT_COSTS`,
`REJECT_INSUFFICIENT_SAMPLE`, `REJECT_FRAGILE`, `REJECT_PIT` on DEV;
`REJECT_VALIDATION` if VALIDATION net `<= 0`.

## Status

`PREREGISTERED_NOT_IMPLEMENTED`. OOS **LOCKED**.
