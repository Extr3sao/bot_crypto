# EXP-ARP-009 — SPEC (ARP-005 EXECUTION RESTATEMENT; frozen BEFORE any result)

## Identity

- experiment_id: `EXP-ARP-009`
- strategy_id: `H-XSEC-RELSTR-001` (**NEW project hypothesis** — no `STRAT-CAND` lineage)
- arm: `PROJECT_DERIVED_VARIANT`
- mechanism family: **cross-sectional / relative strength**
- pre-registration: the rules are **unchanged** from the ARP-003
  `../../alpha_recovery_v1_2/experiments/EXP-ARP-009/SPEC.md`. This ARP-005 file
  supersedes only the *infrastructure* precondition: the orphan
  `CrossSectionalEngine` is replaced by the minimal, tested, PIT-safe
  `src/trading_bot/research/alpha_recovery/xsec.py` ranker (ARP-005 §4). The rules,
  parameters, splits and kill criteria are byte-identical in intent.

## Rules (frozen)

1. Universe: `BTCUSDT, ETHUSDT, SOLUSDT`. Membership **fixed as-of corpus start**;
   documented survivorship limitation.
2. 1-day bars derived PIT-safely from the frozen 5m corpus (complete UTC buckets).
3. Metric: trailing `lookback_days=30` simple return, computed **only** from closes
   observable at the rebalance timestamp; the window must be day-contiguous.
4. Rebalance: daily at the UTC 00:00 bar. Long-only: hold the single asset with the
   highest trailing return; rotate to the leader when the held rank is lost.
5. Equal weighting (single asset; 100 % of the 500 USD research notional).
6. No short leg (spot-only corpus).
7. Max hold `max_hold_days=30` safety cap.
8. **Asset synchronization:** a snapshot ranks only symbols whose last closed daily
   bar is *exactly* at the rebalance timestamp; a lagging/missing symbol is excluded,
   never ranked on a stale bar.

## Parameters (frozen, a priori — round values, never tuned)

`lookback_days=30`, `long_only=true`, `max_hold_days=30`.

## Assets / timeframe / splits

- assets: BTCUSDT, ETHUSDT, SOLUSDT · timeframe `1d`, daily rebalance
- DEV: W1_2026-03…W4_2026-06 · VALIDATION: W5_2026-07…W6_2026-08 · OOS_LOCK:
  W7_2026-09 (unopened)

## Cost model

`COST_MODEL_V3` / `BINANCE_SPOT_STANDARD_TAKER` = live `CostEngine` round trip
(never hardcoded); stress 0.5 / 1.0 / 1.5 / 2.0.

## PIT / leakage contract

- No future membership; fixed 3-asset set.
- No future ranking window: the metric window ends at or before the decision bar.
- No future returns in the ranking; entry at the next daily open.
- `data_time <= decision_time <= fill_time`.

## Kill criteria (frozen)

- `REJECT_NO_EDGE` if DEV gross expectancy `<= 0`.
- `REJECT_COSTS` if DEV gross expectancy `<= 23.559` bps.
- `REJECT_INSUFFICIENT_SAMPLE` if DEV rotations/trades `< 20`.
- `REJECT_FRAGILE` if one trade `> 50 %` of positive DEV net, or dependence on the
  single best asset.
- `REJECT_PIT` on any look-ahead; hidden exception ⇒ `REJECT_IMPLEMENTATION`.
- `REJECT_DUPLICATE` if the mechanism degenerates to single-name time-series momentum.

## Status

`PREREGISTERED` — infrastructure precondition now satisfied by `xsec.py` + tests.
