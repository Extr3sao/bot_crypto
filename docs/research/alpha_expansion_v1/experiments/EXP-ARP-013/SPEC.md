# EXP-ARP-013 — SPEC (pre-registered BEFORE the pipeline)

## Identity

- experiment_id: `EXP-ARP-013`
- strategy_id: `H-XSEC-MOM-LONG-001`
- arm: `NEW_PROJECT_HYPOTHESIS` (not source-faithful)
- mechanism family: **cross-sectional momentum (factor / ranking)**
- relationship: distinct from every failed 2019–2021/ARP-004 mechanism
  (`EMA crossover`, `momentum timing`, `breakout timing`, `trend timing`,
  `mean reversion timing`, `volatility timing`). This ranks *assets against each
  other* at one point in time, it does not time one asset's own series.

## Why an edge might exist

Cross-sectional momentum is one of the most robust documented crypto factors:
returns are positively autocorrelated at medium horizons, so the asset currently
leading a peer group tends to keep leading. The 3-asset crypto universe (BTC, ETH,
SOL) is small but genuinely cross-sectional, and a 30-day maximum hold with a
5-day rebalance cadence gives the factor room to clear the ~23.6 bps round-trip
cost.

## Rules (frozen)

1. Bars: 1-day bars **constructed** from native 1h bars by complete UTC epoch
   buckets (§5). No partial bucket is ever emitted.
2. Feature: `trailing_return` over `ranking_window = 90` days, day-contiguous.
3. Decision: at the close of day `D`, rank all *synchronized* eligible assets; the
   highest trailing return is the leader. Executed at day `D+1`'s open.
4. Holding: long-only, single position. Rotate when the leader changes; force-exit
   after `max_hold_days = 30` and exclude that name until the leader changes.
5. Fixed 500 USD notional; one round-trip cost per completed episode.
6. Minimum universe: `min_members = 2` (a blocked snapshot produces no trade).

## Parameters (frozen, a priori round values — never tuned)

`ranking_feature = trailing_return`, `ranking_window = 90`, `ascending = false`,
`rebalance_days = 5`, `max_hold_days = 30`, `min_members = 2`.

## Data (EXPANSION CORPUS)

- `reports/alpha-expansion-v1/data/` — native 1h shards `2019 … 2026`, constructed
  into 1d bars. Corpus digest `2ce6e6b5…`.
- DEV `2019-01-01 … 2023-12-31` (≈1806 days/symbol) · VALIDATION `2024-01-01 …
  2025-06-30` · OOS_LOCK `2025-07-01 … 2026-02-28`.
- The frozen baseline (`9d51385d…`) and extended (`d3669d28…`) corpora are untouched.

## Cost model

`COST_MODEL_V3` = live `CostEngine` round trip (never hardcoded); stress
0.5 / 1.0 / 1.25 / 1.5 / 2.0. **1.0× decides viability.**

## PIT contract

The ranking for day `D` reads only bars with `timestamp <= D`; the snapshot is
built with `decision_time = D+1` and a series trimmed to `<= D`, so
`feature_time <= decision_time <= fill_time`. No future membership, no future
return, ties broken by symbol name.

## Kill criteria (frozen)

- `REJECT_NO_EDGE` if DEV gross expectancy `<= 0`.
- `REJECT_COSTS` if DEV net expectancy `<= 0` at 1.0×.
- `INSUFFICIENT_EVIDENCE` if DEV trades `< 20`.
- `REJECT_FRAGILE` if a single trade contributes `> 50 %` of positive DEV net, or
  if the DEV edge is a single-point optimum under the robustness variants.
- `REJECT_PIT` on any look-ahead; hidden exception ⇒ `REJECT_IMPLEMENTATION`.
- `REJECT_DUPLICATE` if the strategy degenerates to a single name across DEV.

## Status

`PREREGISTERED_NOT_IMPLEMENTED`.
