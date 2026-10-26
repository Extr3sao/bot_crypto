# EXP-ARP-012 — SPEC (pre-registered BEFORE any result)

## Identity

- experiment_id: `EXP-ARP-012`
- strategy_id: `STRAT-CAND-016-VARIANT-B`
- arm: `PROJECT_DERIVED_VARIANT` (NOT source-faithful — the §3 source reconstruction
  is `BLOCKED_NEEDS_SPEC`)
- mechanism family: **mean reversion after abnormal displacement** (liquidity void)
- relationship: this executes the **ARP-003 `EXP-ARP-006` rules unchanged** on the
  **ARP-005 extended corpus**. The rules are byte-identical to
  `../../alpha_recovery_v1_2/experiments/EXP-ARP-006/SPEC.md`; only the *dataset*
  changed (six provider months prepended), which is why it carries a NEW experiment
  id rather than being a silent re-reading of `EXP-ARP-006`.

## Why an edge might exist

A `>= 3`-day strictly one-sided run whose total displacement is `>= 2 x ATR(14)` is a
displacement away from recent value rather than a gradual trend. When price returns
into the void's origin band, the fast move is more likely to be retraced than
continued (temporary liquidity vacuum). The 5-day hold gives the retracement room to
exceed the ~23.6 bps round-trip cost.

## Rules (frozen; `EXP-ARP-006` verbatim)

1. Bars: 1-day bars derived PIT-safely by complete UTC epoch buckets.
2. `ATR(14)` on the daily series.
3. **Void** = `>= 3` consecutive daily closes strictly monotone one direction whose
   total displacement `>= 2.0 x ATR(14)` measured at the void's last day.
4. **Void origin band** = `[min(open_first, close_last), max(open_first, close_last)]`.
5. **Entry**: the first bar within `10` days of the void end whose high (down-void) or
   low (up-void) re-enters the origin band → enter at the *next* bar's open, in the
   direction **opposite** the void.
6. Stop: `1.5 x ATR(14)`; target `3.0 x ATR(14)`; max hold `5` days.
7. One position at a time per symbol; fixed 500 USD notional; no compounding.

## Parameters (frozen, a priori)

`void_min_days=3`, `void_min_atr=2.0`, `retest_lookback_days=10`, `stop_atr=1.5`,
`target_atr=3.0`, `max_hold_days=5`.

## Data (ARP-005 EXTENDED CORPUS)

- The six new provider windows `WX1_2025-09 … WX6_2026-02` are prepended to the
  frozen DEV windows `W1…W4`, giving **DEV = 303 days/symbol** — inside the ARP-004
  adequacy band (≈230–330) that `EXP-ARP-006` failed to reach on the baseline corpus.
- VALIDATION = `W5…W6` (62 d) · OOS_LOCK = `W7` (24 d) — unchanged and unopened.
- The extended files live in `reports/alpha-recovery-v1-4/data/`; the baseline corpus
  digest `9d51385d…` is untouched. Extended fingerprint is recorded in the manifest.
- No interpolation/synthesis: incomplete UTC days are dropped by the derivation.

## Cost model

`COST_MODEL_V3` = live `CostEngine` round trip (never hardcoded); stress 0.5 / 1.0 /
1.5 / 2.0.

## PIT contract

`data_time <= decision_time <= fill_time`; entry at the next open after a signal on a
closed bar; every derived daily bar is complete; no future high/low; the void's ATR is
read at its last (closed) day.

## Kill criteria (frozen)

- `REJECT_NO_EDGE` if DEV gross expectancy `<= 0`.
- `REJECT_COSTS` if DEV gross expectancy `<= 23.559` bps.
- `REJECT_INSUFFICIENT_SAMPLE` if DEV trade count `< 10`.
- `REJECT_FRAGILE` if a single trade contributes `> 50 %` of positive DEV net.
- `REJECT_PIT` on any look-ahead; hidden exception ⇒ `REJECT_IMPLEMENTATION`.

## Status

`PREREGISTERED_NOT_IMPLEMENTED`.
