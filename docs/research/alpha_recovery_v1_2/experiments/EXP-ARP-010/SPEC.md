# EXP-ARP-010 — SPEC (pre-registered BEFORE any result)

## Identity

- experiment_id: `EXP-ARP-010`
- strategy_id: `H-VOLSPIKE-MR-001` (**NEW hypothesis** — no `STRAT-CAND` lineage)
- arm: `PROJECT_DERIVED_VARIANT`
- mechanism family: mean reversion after a volatility spike
- grounding: in the admission ledger the **`volatility` family had the largest gross
  in the corpus** (`volatility@30m` +8.91 bps, `volatility@1h` +6.28) and
  `mean_reversion@30m` +5.47; all were `COST_KILLED` at 5m/30m/1h. This tests whether
  the same phenomenon survives at a **multi-hour-to-daily** horizon, where the
  feasibility frontier ratio is 3–8.

## Rules (frozen)

1. Bars: 1-day bars derived PIT-safely from the frozen 5m corpus (complete UTC
   buckets). Realized daily volatility = `sqrt(sum(r_5m^2))` over that day's 5m
   returns (PIT: the day's own 5m bars are complete at day close).
2. **Regime**: daily-volatility z-score vs the trailing `vol_lookback_days=60`
   window (population stdev, `None` until the window is full).
3. **Signal**: `vol_z >= vol_z_entry=2.0` **and** the day's return `<= -1.0 x ATR(14)`
   → enter **long** at the next day's open (fade the down spike).
4. Stop: `2.0 x ATR(14)`. Target: `1.0 x ATR(14)`. Max hold: `2` days.
5. Long-only (spot corpus); one position at a time per symbol; fixed notional 500 USD.

## Parameters (frozen, a priori)

`vol_lookback_days=60`, `vol_z_entry=2.0`, `ret_atr=1.0`, `stop_atr=2.0`,
`target_atr=1.0`, `max_hold_days=2`, `atr_period=14`.

## Assets / timeframe / splits

- assets: BTCUSDT, ETHUSDT, SOLUSDT
- timeframe: `1d`
- DEV W1–W4 · VALIDATION W5–W6 · OOS_LOCK W7 (unopened)

## Cost model

`COST_MODEL_V3` = 23.559016994374947 bps RT (live `CostEngine`); stress 0.5/1.0/2.0.

## PIT contract

`data_time <= decision_time`; the 60-day vol window uses only closed days; entry at
the next open; realized vol uses the day's own completed 5m bars (available at day
close), never a future bar.

## Kill criteria (frozen)

- `REJECT_NO_EDGE` if DEV gross `<= 0`.
- `REJECT_COSTS` if DEV gross `<= 23.559` bps.
- `REJECT_INSUFFICIENT_SAMPLE` if DEV trades `< 10` (vol spikes are rare).
- `REJECT_FRAGILE` if one trade `> 50 %` of positive DEV net.
- `REJECT_PIT` on any look-ahead.

## Testability caveat (pre-declared)

60-day warmup + a rare `vol_z >= 2` trigger means DEV may yield few trades →
`DATA_SHORT_FOR_HORIZON` is possible. The trigger threshold is **frozen**; it must
not be lowered after seeing DEV.

## Status

`PREREGISTERED_NOT_IMPLEMENTED`.
