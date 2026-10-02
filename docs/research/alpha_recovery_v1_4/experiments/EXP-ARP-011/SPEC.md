# EXP-ARP-011 — SPEC (pre-registered BEFORE any result)

## Identity

- experiment_id: `EXP-ARP-011`
- strategy_id: `H-VOLEXP-BREAK-001` (**NEW project hypothesis**, no source lineage)
- arm: `PROJECT_DERIVED_VARIANT`
- mechanism family: **breakout / volatility expansion** (orthogonal to the ARP-005
  mean-reversion and cross-sectional families)

## Why an edge might exist

Daily volatility is autocorrelated (volatility clustering). A close above the prior
`L`-day high *when realised ATR is above its own recent median* is a regime where a
directional move is being accepted rather than faded: the breakout is confirmed by an
expansion of the day's range, not by a single noisy print. Continuation modestly
favours going with the expansion. The horizon is multi-day so the expected favourable
excursion can plausibly exceed the ~23.6 bps round-trip cost (contrast ARP-004
`EXP-ARP-007`, whose ~0.4 % capture was cost-dominated).

## Rules (frozen)

1. Bars: 1-day bars derived PIT-safely from the frozen 5m corpus (complete UTC
   buckets; no partial day).
2. `ATR(14)` on the daily series.
3. **Breakout gate:** `close[i] > max(high[i-L .. i-1])` with `L=20` (the current
   bar is excluded from its own breakout level).
4. **Volatility-expansion gate:** `ATR(14)[i] > median(ATR(14)[i-V .. i-1])` with
   `V=20`. Both gates must hold on the *same* closed bar.
5. Entry: **next** daily bar's open (long-only; a short leg is out of scope).
6. Stop: `1.5 x ATR(14)`; target: `3.0 x ATR(14)`.
7. Max hold: `10` days (exit at that bar's close); one position at a time per symbol;
   fixed 500 USD notional; no compounding; stop-first on intra-bar ambiguity.

## Parameters (frozen, a priori — round values, never tuned)

`atr_period=14`, `breakout_lookback_days=20`, `vol_gate_days=20`, `stop_atr=1.5`,
`target_atr=3.0`, `max_hold_days=10`.

## Assets / timeframe / splits

- assets: BTCUSDT, ETHUSDT, SOLUSDT · timeframe `1d`
- DEV: W1_2026-03…W4_2026-06 · VALIDATION: W5_2026-07…W6_2026-08 · OOS_LOCK:
  W7_2026-09 (unopened)

## Cost model

`COST_MODEL_V3` / `BINANCE_SPOT_STANDARD_TAKER` = live `CostEngine` round trip
(never hardcoded); stress 0.5 / 1.0 / 1.5 / 2.0.

## PIT contract

`data_time <= decision_time <= fill_time`; every derived daily bar is complete; the
breakout level never includes a future high; the ATR median never includes the
current day.

## Kill criteria (frozen)

- `REJECT_NO_EDGE` if DEV gross expectancy `<= 0`.
- `REJECT_COSTS` if DEV gross expectancy `<= 23.559` bps.
- `REJECT_INSUFFICIENT_SAMPLE` if DEV trades `< 10`.
- `REJECT_FRAGILE` if a single trade contributes `> 50 %` of positive DEV net.
- `REJECT_PIT` on any look-ahead; hidden exception ⇒ `REJECT_IMPLEMENTATION`.

## Testability caveat (honest, pre-declared)

DEV ≈122 days, warmup `max(20,20)+2≈22`, so ≈100 evaluable days; a `max_hold_days=10`
continuation can make trade count sparse. A DEV pass would be weak evidence; a DEV
fail is still informative.

## Status

`PREREGISTERED_NOT_IMPLEMENTED`.
