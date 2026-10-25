# EXP-ARP-006 — SPEC (pre-registered BEFORE any result)

## Identity

- experiment_id: `EXP-ARP-006`
- strategy_id: `STRAT-CAND-016-VARIANT-B`
- arm: **`PROJECT_DERIVED_VARIANT`** (NOT source-faithful — §3 reconstruction is
  `BLOCKED_NEEDS_SPEC`)
- mechanism family: liquidity reversal (fade a fast one-sided move)
- prior art: `EXP-ARP-002` (`STRAT-CAND-016-VARIANT-A`, 5m) → `REJECT_COSTS`. This is
  a **different experiment** (slower horizon, different parameters), not a re-reading.

## Rules (all PROJECT rules; frozen)

1. Bars: 1-day bars derived PIT-safely from the frozen 5m corpus by complete UTC
   epoch buckets (`scripts/resample_baseline_data.py` rule). No partial day.
2. Indicator: `ATR(14)` computed on the **daily** series.
3. **Void** = `>= 3` consecutive daily closes strictly monotone in one direction
   whose total displacement `>= 2.0 x ATR(14)` measured at the void's last day.
4. **Void origin band** = `[min(open_first, close_last), max(open_first, close_last)]`
   of the void.
5. **Entry**: the first daily bar within `10` days of the void end whose high (for a
   down-void) or low (for an up-void) re-enters the origin band → enter at the *next*
   bar's open, in the direction **opposite** the void.
6. Stop: `1.5 x ATR(14)` beyond the entry.
7. Target: `3.0 x ATR(14)`.
8. Max hold: `5` days (exit at close on the 5th day).
9. One position at a time per symbol; fixed notional (500 USD); no compounding.

## Parameters (frozen, a priori — round values, never tuned)

`void_min_days=3`, `void_min_atr=2.0`, `retest_lookback_days=10`, `stop_atr=1.5`,
`target_atr=3.0`, `max_hold_days=5`.

## Assets / timeframe / splits

- assets: BTCUSDT, ETHUSDT, SOLUSDT
- timeframe: `1d` (derived)
- DEV: W1_2026-03…W4_2026-06 (≈122 days) · VALIDATION: W5_2026-07…W6_2026-08 (≈62 days)
- OOS_LOCK: W7_2026-09 (≈25 days) — **must not be opened** unless DEV + COST +
  VALIDATION + ROBUSTNESS all pass

## Cost model

`COST_MODEL_V3` / `BINANCE_SPOT_STANDARD_TAKER` = **23.559016994374947 bps** RT,
obtained live from `CostEngine` (never hardcoded). Stress multiples 0.5 / 1.0 / 2.0.

## PIT contract

`data_time <= decision_time`. Entry is at the *next* bar's open after a signal on a
closed bar. Every derived daily bar is complete. No future daily high/low.

## Kill criteria (frozen)

- `REJECT_NO_EDGE` if DEV gross expectancy `<= 0`.
- `REJECT_COSTS` if DEV gross expectancy `<= 23.559` bps.
- `REJECT_INSUFFICIENT_SAMPLE` if DEV trade count `< 10`.
- `REJECT_FRAGILE` if a single trade contributes `> 50 %` of positive DEV net.
- `REJECT_PIT` on any look-ahead; hidden exception ⇒ `REJECT_IMPLEMENTATION`.

## Testability caveat (honest, pre-declared)

DEV ≈122 days minus warmup leaves ≈92 evaluable days; with `max_hold_days=5` the
number of *independent* windows is ≈18 → **`DATA_SHORT_FOR_HORIZON`**. A DEV pass
would be weak evidence; a DEV fail is still informative.

## Status

`PREREGISTERED_NOT_IMPLEMENTED`. Implementation, unit tests, PIT tests and DEV are
the next authorized step.
