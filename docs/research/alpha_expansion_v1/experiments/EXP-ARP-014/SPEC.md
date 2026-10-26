# EXP-ARP-014 — SPEC (pre-registered BEFORE the pipeline)

## Identity

- experiment_id: `EXP-ARP-014`
- strategy_id: `H-XSEC-REV-001`
- arm: `NEW_PROJECT_HYPOTHESIS`
- mechanism family: **cross-sectional short-horizon reversal (contrarian ranking)**
- relationship: orthogonal to `EXP-ARP-013` (momentum) — this buys the *worst*
  recent cross-sectional performer, not the best. It is a *relative* reversal,
  distinct from the failed single-asset "mean reversion timing" (which times one
  asset's own displacement).

## Why an edge might exist

At short horizons, cross-sectional crypto returns are negatively autocorrelated:
the weakest member of a peer group over the last week tends to mean-revert toward
the group as liquidity providers force selling pressure to unwind. A 5–7 day hold
with a 3-day rebalance cadence is structurally different from a slow factor and
gives the bounce time to clear the round-trip cost.

## Rules (frozen)

1. Bars: 1-day bars constructed from native 1h bars by complete UTC epoch buckets.
2. Feature: `trailing_return` over `ranking_window = 7` day-contiguous days.
3. Decision: rank synchronized assets at day `D` close **ascending** (smallest =
   best); the worst 7-day performer is the leader. Executed at day `D+1`'s open.
4. Holding: long-only, single position. Rotate when the leader changes; force-exit
   after `max_hold_days = 7` and exclude that name until the leader changes.
5. Fixed 500 USD notional; one round-trip cost per completed episode.
6. Minimum universe: `min_members = 2`.

## Parameters (frozen, a priori round values — never tuned)

`ranking_feature = trailing_return`, `ranking_window = 7`, `ascending = true`,
`rebalance_days = 3`, `max_hold_days = 7`, `min_members = 2`.

## Data (EXPANSION CORPUS)

Same corpus and splits as `EXP-ARP-013` (digest `2ce6e6b5…`; DEV 2019-2023,
VALIDATION 2024-2025H1, OOS_LOCK 2025H2-2026Q1, sealed).

## Cost model

`COST_MODEL_V3` live round trip; stress 0.5 / 1.0 / 1.25 / 1.5 / 2.0. 1.0× decides.

## PIT contract

Identical to `EXP-ARP-013`: `feature_time <= decision_time <= fill_time`; ties
broken by symbol name.

## Kill criteria (frozen)

- `REJECT_NO_EDGE` if DEV gross expectancy `<= 0`.
- `REJECT_COSTS` if DEV net expectancy `<= 0` at 1.0× (the 7-day hold is short, so
  this is the binding risk).
- `INSUFFICIENT_EVIDENCE` if DEV trades `< 20`.
- `REJECT_FRAGILE` if a single trade contributes `> 50 %` of positive DEV net, or
  if the DEV edge is a single-point optimum.
- `REJECT_PIT` on any look-ahead; hidden exception ⇒ `REJECT_IMPLEMENTATION`.
- `REJECT_DUPLICATE` if the strategy degenerates to a single name across DEV.

## Status

`PREREGISTERED_NOT_IMPLEMENTED`.
