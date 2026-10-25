# EXP-ARP-016 — SPEC (pre-registered BEFORE any result)

## Identity

- experiment_id: `EXP-ARP-016`
- strategy_id: `H-XSEC-MOM-LONG-002` (**NEW** hypothesis — no `STRAT-CAND` lineage)
- arm: `NEW_HYPOTHESIS`
- mechanism family: cross-sectional momentum (long the strongest trailing return)
- prior art: `EXP-ARP-013` `H-XSEC-MOM-LONG-001` → `REJECT_FRAGILE` (single SOL-2021
  trade, top1 share 0.5049) on a **3-asset** universe. This is a **different
  experiment**: the universe materially changes (PIT dynamic, 100+ eligible assets).

## Hypothesis

A broader PIT-safe universe reduces single-name concentration and gives the
cross-sectional ranking enough dispersion to test the mechanism properly.

## Rules (frozen)

1. Universe: the ARP-006 PIT `DynamicAssetUniverse`
   (`min_history_days=60`, `liquidity_lookback_days=30`,
   `min_median_quote_volume=1e6 USD`, `max_gap_ratio=0.05`, `max_stale_days=2`).
2. Ranking feature: trailing return over `90` daily bars.
3. Rebalance every `5` days; hold up to `30` days; long the rank-1 leader.
4. `min_members=5` — fewer than 5 synchronized eligible assets ⇒ no position.
5. Fill at the **next** daily open after a closed decision bar (`data_time <=
   decision_time <= fill_time`).

## Parameters (frozen, a priori — round values, never tuned)

`ranking_window=90`, `ascending=false`, `rebalance_days=5`, `max_hold_days=30`,
`min_members=5`, `entry_delay_days=0`.

## Universe / timeframe / splits

- timeframe: `1d` (native Binance klines, complete days only)
- DEV: 2019-01-01…2023-12-31 · VALIDATION: 2024-01-01…2025-06-30
- OOS_LOCK: 2025-07-01…2026-02-28 — **must not be opened** unless DEV + COST +
  VALIDATION + ROBUSTNESS + PIT + CONCENTRATION all pass, with independent
  verification first.

## Cost model

`COST_MODEL_V3` / `BINANCE_SPOT_STANDARD_TAKER` = `23.559016994374947` bps RT,
obtained live from `CostEngine` (never hardcoded). Stress 0.5 / 1.0 / 1.25 / 1.5 / 2.0.

## Kill criteria (frozen)

- `REJECT_NO_EDGE` if DEV gross expectancy `<= 0`.
- `REJECT_COSTS` if DEV gross expectancy `<= 23.559` bps.
- `REJECT_INSUFFICIENT_SAMPLE` if DEV trades `< 20`.
- `REJECT_FRAGILE` if one trade contributes `> 50 %` of positive DEV net.
- `REJECT_VALIDATION` if VALIDATION net expectancy `<= 0`, sample `< 20`, or
  `top_asset_share > 0.50`.
- `REJECT_PIT` on any look-ahead.

## Status

`PREREGISTERED`. Frozen before any result; identical to `EXP-ARP-013` in ranking
mechanism only, and forbidden from re-running `EXP-ARP-013`'s configuration.
