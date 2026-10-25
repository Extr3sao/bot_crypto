# EXP-ARP-009 — SPEC (pre-registered BEFORE any result)

## Identity

- experiment_id: `EXP-ARP-009`
- strategy_id: `H-XSEC-RELSTR-001` (**NEW hypothesis** — no `STRAT-CAND` lineage; the
  source's FX/DXY pair-divergence idea is a *different* universe, so this carries no
  CAND-012 name)
- arm: `PROJECT_DERIVED_VARIANT`
- mechanism family: **cross-sectional / relative strength** (the only cross-instrument
  mechanism in the backlog)
- grounding: §10 "crypto cross-sectional"; feasibility frontier 1d ratio 8.2

## Rules (frozen)

1. Universe: `BTCUSDT, ETHUSDT, SOLUSDT`. Membership is **fixed as-of the corpus
   start** and is a documented survivorship limitation (see below).
2. 1-day bars derived PIT-safely from the frozen 5m corpus (complete UTC buckets).
3. Metric: trailing `lookback_days=30` simple return, computed **only** from closes
   observable at the rebalance timestamp.
4. Rebalance: daily at UTC 00:00. Long-only: hold the single asset with the highest
   trailing return; if its rank falls to 2nd or 3rd, rotate to the new leader.
5. Equal weighting (single asset at a time, 100 % of the research notional).
6. No short leg (spot-only corpus; a short leg would be a separate experiment).
7. Max hold: until rank loss; `max_hold_days=30` safety cap.

## Parameters (frozen, a priori)

`lookback_days=30`, `long_only=true`, `max_hold_days=30`.

## Assets / timeframe / splits

- assets: BTCUSDT, ETHUSDT, SOLUSDT
- timeframe: `1d`, daily rebalance
- DEV W1–W4 · VALIDATION W5–W6 · OOS_LOCK W7 (unopened)

## Cost model

`COST_MODEL_V3` = 23.559016994374947 bps RT (live `CostEngine`); stress 0.5/1.0/2.0.

## PIT / leakage contract (explicit, from §4)

- No future membership: the universe is a fixed 3-asset set, not a changing index.
- No future liquidity filter (none is applied).
- No future ranking window: the metric window must end at or before the decision bar.
- No future returns in the ranking.

## Infrastructure requirement (§20)

`INFRASTRUCTURE_PARTIAL`. `research/cross_sectional.py::CrossSectionalEngine` exists
but is **untested and has no caller**. Readiness is `PARTIAL` until a PIT unit test
for that engine and a thin PIT-safe adapter exist. Do **not** build a large
subsystem; the minimum is identified in `../../INFRASTRUCTURE_NOTES.md`.

## Kill criteria (frozen)

- `REJECT_NO_EDGE` if DEV gross `<= 0`.
- `REJECT_COSTS` if DEV gross `<= 23.559` bps.
- `REJECT_INSUFFICIENT_SAMPLE` if DEV rotations/trades `< 20`.
- `REJECT_FRAGILE` if one trade `> 50 %` of positive DEV net, **or** if the result
  depends on the single best asset.
- `REJECT_PIT` on any look-ahead.
- `REJECT_DUPLICATE` if the mechanism turns out to be time-series momentum on one
  name (it must genuinely rank across assets each day).

## Status

`PREREGISTERED_NOT_IMPLEMENTED` — blocked on the small infrastructure step above.
