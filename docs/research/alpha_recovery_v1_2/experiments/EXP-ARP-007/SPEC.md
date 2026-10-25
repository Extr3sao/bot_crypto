# EXP-ARP-007 — SPEC (pre-registered BEFORE any result)

## Identity

- experiment_id: `EXP-ARP-007`
- strategy_id: `STRAT-CAND-019-VARIANT-B`
- arm: **`PROJECT_DERIVED_VARIANT`** (NOT source-faithful — §5 reconstruction is
  `BLOCKED_NEEDS_SPEC`)
- mechanism family: level reaction (fade first contact with a daily pivot)
- prior art: `EXP-ARP-005` (`STRAT-CAND-019-VARIANT-A`, 5m) → `REJECT_COSTS`.
  Different experiment (daily horizon, daily pivots).

## Rules (frozen)

1. Bars: 1-day bars derived PIT-safely from the frozen 5m corpus (complete UTC
   buckets). Pivot for day *D* uses **day D−1's** complete H/L/C only.
2. Pivot formula (floor-trader, `SOURCE_IMPLIED` "standard"):
   `PP = (H+L+C)/3`, `R1 = 2*PP - L`, `S1 = 2*PP - H`.
3. **First contact**: the first daily bar of day *D* whose **high >= R1** (fade short)
   or **low <= S1** (fade long). Tolerance = exact level touch (no buffer).
4. **Entry**: next daily bar's open, in the fade direction.
5. Stop: `1.0 x ATR(14)` beyond the pivot level.
6. Target: `PP` (the central pivot).
7. Max hold: `3` days.
8. One position at a time per symbol; fixed notional 500 USD; no compounding.

## Parameters (frozen, a priori)

`stop_atr=1.0`, `target=PP`, `max_hold_days=3`, `atr_period=14`.

## Assets / timeframe / splits

- assets: BTCUSDT, ETHUSDT, SOLUSDT
- timeframe: `1d`
- DEV W1–W4 · VALIDATION W5–W6 · OOS_LOCK W7 (unopened)

## Cost model

`COST_MODEL_V3` = 23.559016994374947 bps RT (live `CostEngine`); stress 0.5/1.0/2.0.

## PIT contract

`data_time <= decision_time`; daily bars complete; pivot uses only the prior closed
day; entry at the next open after a closed-bar signal.

## Kill criteria (frozen)

- `REJECT_NO_EDGE` if DEV gross `<= 0`.
- `REJECT_COSTS` if DEV gross `<= 23.559` bps.
- `REJECT_INSUFFICIENT_SAMPLE` if DEV trades `< 10`.
- `REJECT_FRAGILE` if one trade `> 50 %` of positive DEV net.
- `REJECT_PIT` on any look-ahead.

## Testability

Holds are 1–3 days → DEV ≈122 days supports ≈40+ independent contacts; adequate.
`EXPERIMENT_READY`.

## Status

`PREREGISTERED_NOT_IMPLEMENTED`.
