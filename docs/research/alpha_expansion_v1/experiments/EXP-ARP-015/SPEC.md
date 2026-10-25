# EXP-ARP-015 — SPEC (pre-registered BEFORE the pipeline)

## Identity

- experiment_id: `EXP-ARP-015`
- strategy_id: `H-XSEC-LOWVOL-001`
- arm: `NEW_PROJECT_HYPOTHESIS`
- mechanism family: **cross-sectional low-volatility factor**
- relationship: orthogonal to `EXP-ARP-013` (momentum) and `EXP-ARP-014` (reversal).
  The ranking feature is realized volatility, not return; the mechanism is the
  documented low-volatility anomaly (calm assets earn better risk-adjusted
  returns), distinct from the failed single-asset "volatility timing".

## Why an edge might exist

The low-volatility anomaly is one of the most replicated cross-sectional effects:
in high-volatility regimes, investors overpay for lottery-like (high-vol) names,
so the calmest peer tends to deliver better subsequent risk-adjusted returns. A
30-day hold on a 10-day rebalance cadence makes this cost-compatible.

## Rules (frozen)

1. Bars: 1-day bars constructed from native 1h bars by complete UTC epoch buckets.
2. Feature: `realized_vol` = population stdev of the last `ranking_window = 60`
   day-contiguous bar-over-bar returns.
3. Decision: rank synchronized assets at day `D` close **ascending** (lowest vol =
   best); the calmest asset is the leader. Executed at day `D+1`'s open.
4. Holding: long-only, single position. Rotate when the leader changes; force-exit
   after `max_hold_days = 30` and exclude that name until the leader changes.
5. Fixed 500 USD notional; one round-trip cost per completed episode.
6. Minimum universe: `min_members = 2`.

## Parameters (frozen, a priori round values — never tuned)

`ranking_feature = realized_vol`, `ranking_window = 60`, `ascending = true`,
`rebalance_days = 10`, `max_hold_days = 30`, `min_members = 2`.

## Data (EXPANSION CORPUS)

Same corpus and splits as `EXP-ARP-013/014` (digest `2ce6e6b5…`).

## Cost model

`COST_MODEL_V3` live round trip; stress 0.5 / 1.0 / 1.25 / 1.5 / 2.0. 1.0× decides.

## PIT contract

Identical to `EXP-ARP-013`: `feature_time <= decision_time <= fill_time`; ties
broken by symbol name.

## Kill criteria (frozen)

- `REJECT_NO_EDGE` if DEV gross expectancy `<= 0`.
- `REJECT_COSTS` if DEV net expectancy `<= 0` at 1.0×.
- `INSUFFICIENT_EVIDENCE` if DEV trades `< 15` (a 60-day window and 30-day hold
  reduce turnover).
- `REJECT_FRAGILE` if a single trade contributes `> 50 %` of positive DEV net, or
  if the DEV edge is a single-point optimum.
- `REJECT_PIT` on any look-ahead; hidden exception ⇒ `REJECT_IMPLEMENTATION`.
- `REJECT_DUPLICATE` if the strategy degenerates to a single name across DEV.

## Status

`PREREGISTERED_NOT_IMPLEMENTED`.
