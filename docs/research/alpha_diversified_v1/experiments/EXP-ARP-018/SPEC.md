# EXP-ARP-018 — SPEC (pre-registered BEFORE any result)

## Identity

- experiment_id: `EXP-ARP-018`
- strategy_id: `H-XSEC-LOWVOL-002` (**NEW** hypothesis)
- arm: `NEW_HYPOTHESIS`
- mechanism family: cross-sectional low-volatility (buy the calmest)
- prior art: `EXP-ARP-015` `H-XSEC-LOWVOL-001` → `INSUFFICIENT_EVIDENCE` (11 < 15
  episodes) because a **3-asset** universe starves a slow factor.

## Sample justification (§16)

The broader PIT universe increases the number of *independent* rebalance episodes by
an order of magnitude; the pre-registered minimum evidence requirement is **not**
lowered (`min_trades=15`).

## Rules (frozen)

1. Universe: the ARP-006 PIT `DynamicAssetUniverse` (same rule as `EXP-ARP-016`).
2. Ranking feature: realized volatility over `60` daily bars, **ascending**.
3. Rebalance every `10` days; hold up to `30` days; long the rank-1 (calmest).
4. `min_members=5`.
5. Fill at the **next** daily open after a closed decision bar.

## Parameters (frozen, a priori)

`ranking_window=60`, `ascending=true`, `rebalance_days=10`, `max_hold_days=30`,
`min_members=5`, `entry_delay_days=0`.

## Cost model

`COST_MODEL_V3` = `23.559016994374947` bps RT (live `CostEngine`); stress
0.5 / 1.0 / 1.25 / 1.5 / 2.0.

## Kill criteria (frozen)

`REJECT_NO_EDGE` / `REJECT_COSTS` / `REJECT_INSUFFICIENT_SAMPLE` (DEV `< 15`) /
`REJECT_FRAGILE` / `REJECT_VALIDATION` / `REJECT_PIT`.

## Status

`PREREGISTERED`. Frozen before any result.
