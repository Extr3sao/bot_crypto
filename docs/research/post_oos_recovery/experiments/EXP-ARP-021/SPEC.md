# EXP-ARP-021 — SPEC (pre-registered BEFORE any result)

## Identity

- experiment_id: `EXP-ARP-021`
- strategy_id: `H-XSEC-RISKADJ-RELSTR-001` (**NEW mechanism**)
- arm: `PROJECT_DERIVED_VARIANT`
- mechanism family: **cross-sectional momentum / relative strength / factor ranking**
- grounding: the cross-sectional infrastructure already exists
  (`research/diversified/xsec.py`). This tests a *risk-adjusted* ranking with a
  skip window, distinct from the raw-trailing-return construction of EXP-ARP-016.

## Why this is NOT an EXP-ARP-008 or EXP-ARP-016 variant

- vs EXP-ARP-008: that ranks nothing and trades one asset on a time-series rule;
  this ranks the whole universe against itself and holds a portfolio.
- vs EXP-ARP-016: ARP-016 ranked raw trailing return. This ranks
  `formation_return / realized_vol` and **skips the most recent 7 days**
  (the classic 12-1 momentum construction, adapted to a 90-day crypto
  formation). The mechanism differs in the ranking statistic and the skip.

## Rules (frozen)

1. `score_i = (close_{t-skip} / close_{t-skip-formation} - 1) / realized_vol_i`
   with `formation = 90` days, `skip = 7` days, `realized_vol_i` = population
   stdev of 30 daily log returns ending at `t-skip`.
2. Eligible universe: PIT-safe `DynamicAssetUniverse` snapshot; require
   `members >= min_members`.
3. Long equal-weight the top decile (min 5, max 20 names).
4. Rebalance every 7 days at the UTC close; act at the next open; only names
   whose membership changed are traded (turnover control).
5. A held name force-exits after `max_hold_days`, **at the next open** (never at
   the signal bar's close — the EXP-ARP-008 defect is explicitly excluded).
6. Long-only; fixed total notional 500 USD; no compounding.

## Parameters (frozen, a priori)

`lookback_days=90`, `skip_days=7`, `top_fraction=0.1`, `min_members=5`,
`rebalance_days=7`, `max_hold_days=30`.

## Assets / timeframe / splits

- assets: `DYNAMIC_ASSET_UNIVERSE(ARP-006-UNIVERSE-v1)`
- timeframe: `1d`
- DEV 2019-01-01 .. 2024-01-01 · VALIDATION 2024-01-01 .. 2025-07-01 ·
  OOS_LOCK 2026-03-01 .. 2027-03-01 (**forward PAPER only; locked**).

## Cost model

`COST_MODEL_V3` via the live `CostEngine`; stress 0.5/1.0/1.25/1.5/2.0.

## PIT contract

`data_time <= decision_time <= fill_time`. The skip window and volatility
window read only closed bars; ranking at the decision close; trades at the next
open. `SURVIVORSHIP_DATA_LIMITATION` binds every cross-sectional claim.

## Kill criteria (frozen)

`REJECT_NO_EDGE`, `REJECT_COSTS`, `REJECT_INSUFFICIENT_SAMPLE`,
`REJECT_FRAGILE`, `REJECT_PIT` on DEV; `REJECT_VALIDATION` if VALIDATION net
`<= 0`.

## Status

`PREREGISTERED_NOT_IMPLEMENTED`. OOS **LOCKED**.
