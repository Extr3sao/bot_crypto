# EXP-ARP-008 — SPEC (pre-registered BEFORE any result)

## Identity

- experiment_id: `EXP-ARP-008`
- strategy_id: `H-DAILY-TSMOM-001` (**NEW hypothesis** — no `STRAT-CAND` lineage)
- arm: `PROJECT_DERIVED_VARIANT`
- mechanism family: continuation (time-series momentum / trend)
- grounding: the runtime `trend` family is EMA-slope continuation **at 5m**; this
  tests the same idea at a **daily** horizon, which the feasibility frontier says is
  cost-compatible (1d ratio 8.2; 7d ratio 22.3)

## Rules (frozen)

1. Bars: 1-day bars derived PIT-safely from the frozen 5m corpus (complete UTC
   buckets).
2. **Signal** on the daily close: *long if `close_t > close_{t - lookback_days}`*;
   otherwise flat (no short — a short capability is out of scope and would add
   turnover).
3. Re-evaluate every day at the daily close; enter/exit at the **next** day's open.
4. No stop (the exit is the signal flip). Max hold `max_hold_days=20`.
5. One position at a time per symbol; fixed notional 500 USD; no compounding.

## Parameters (frozen, a priori)

`lookback_days=30`, `max_hold_days=20`.

## Assets / timeframe / splits

- assets: BTCUSDT, ETHUSDT, SOLUSDT
- timeframe: `1d`
- DEV W1–W4 · VALIDATION W5–W6 · OOS_LOCK W7 (unopened)

## Cost model

`COST_MODEL_V3` = 23.559016994374947 bps RT (live `CostEngine`); stress 0.5/1.0/2.0.

## PIT contract

`data_time <= decision_time`; the 30-day lookback consumes warmup — the first
evaluable day is `t >= 30`; daily bars complete; entry at the next open.

## Kill criteria (frozen)

- `REJECT_NO_EDGE` if DEV gross `<= 0`.
- `REJECT_COSTS` if DEV gross `<= 23.559` bps.
- `REJECT_INSUFFICIENT_SAMPLE` if DEV trades `< 20`.
- `REJECT_FRAGILE` if one trade `> 50 %` of positive DEV net.
- `REJECT_PIT` on any look-ahead.

## Testability caveat (pre-declared)

30-day warmup on ≈122 DEV days leaves ≈92; long holds can make trades sparse →
**`DATA_SHORT_FOR_HORIZON`** for the 20-day-hold case. A shorter sub-horizon
(`max_hold_days`) would be a *different* pre-registered experiment, not a tweak.

## Status

`PREREGISTERED_NOT_IMPLEMENTED`.
