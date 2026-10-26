# EXP-ARP-017 — SPEC (pre-registered BEFORE any result)

## Identity

- experiment_id: `EXP-ARP-017`
- strategy_id: `H-XSEC-REV-002` (**NEW** hypothesis)
- arm: `NEW_HYPOTHESIS`
- mechanism family: cross-sectional short-horizon reversal
- prior art: `EXP-ARP-014` `H-XSEC-REV-001` → `REJECT_VALIDATION` (DEV net +11.75,
  VALIDATION net −1.91 on a 3-asset universe). ARP-005 recorded this as
  "out-of-sample"; the §0 `EVIDENCE_CORRECTION.md` corrects the terminology to
  **VALIDATION** because `OOS_OPENED = NO`.

## Validation-consumption acknowledgement (§15)

`EXP-ARP-014` already consumed the `VALIDATION` split (2024-01-01…2025-06-30) for
the reversal mechanism. This experiment therefore **acknowledges the consumed
validation split** and may **not** use a fresh out-of-sample read as a result of it:
its `VALIDATION` result is reported as *exploratory* and it is capped at
`MAX_ACHIEVABLE = VALIDATION_SURVIVOR`, never `OOS_GATE_ELIGIBLE`, on the strength of
this split alone.

## Rules (frozen)

1. Universe: the ARP-006 PIT `DynamicAssetUniverse` (same rule as `EXP-ARP-016`).
2. Ranking feature: trailing return over `7` daily bars, **ascending** (buy weakness).
3. Rebalance every `3` days; hold up to `7` days; long the rank-1 (weakest).
4. `min_members=5`.
5. Fill at the **next** daily open after a closed decision bar.

## Parameters (frozen, a priori)

`ranking_window=7`, `ascending=true`, `rebalance_days=3`, `max_hold_days=7`,
`min_members=5`, `entry_delay_days=0`.

## Cost model

`COST_MODEL_V3` = `23.559016994374947` bps RT (live `CostEngine`); stress
0.5 / 1.0 / 1.25 / 1.5 / 2.0.

## Kill criteria (frozen)

Same as `EXP-ARP-016` (`REJECT_NO_EDGE` / `REJECT_COSTS` /
`REJECT_INSUFFICIENT_SAMPLE` / `REJECT_FRAGILE` / `REJECT_VALIDATION` / `REJECT_PIT`).

## Status

`PREREGISTERED`. Frozen before any result.
