# H6 SELECTION RATIONALE — H6-OI-POSITION-STOCK-01

Checkpoint: `OI-FULL-HISTORY-FREEZE-01 + H6-HYPOTHESIS-SELECTION-AND-PREREG-ONLY` · 2026-09-11 · **prereg-only: `H6_EXECUTIONS = 0`**

## Decision

**Selected: exactly one hypothesis — `H6-OI-POSITION-STOCK-01`** (OI-CONFIRMED-CONTINUATION: position-stock conditioning on 1h decision buckets; BTCUSDT/ETHUSDT/SOLUSDT; common window 2021-12-01 → 2026-09-10).

## Why this mechanism

1. **New information axis, not a retry.** Open interest (position stock) appears in none of the 12 terminal failed families — every failure conditioned on price/volume flows, funding basis, or their derived states. OI conditioning is a genuinely different market variable.
2. **Ex-ante mechanism evidence at official tier.** CME's official education material (E-1) treats OI change as the canonical confirmation/contradiction signal for price moves; corroborated by E-2 and leveraged-perp feedback dynamics in the peer-reviewed literature (E-3). No profitability claim is made — the gates decide later.
3. **Cost structure is design-compatible.** Hourly cadence with OI conditioning targets far fewer decisions than H1's ≈6.5/day transitions (the #10 cost lesson); the prereg hard-codes cooldown + minimum-edge statement + the 0.12%/trade cost hurdle.
4. **Collision risk managed.** M-A (event-level trade flow) collides with H5 (#12) and carries a severe storage/cost profile → **DEFERRED** with reasons recorded, not silently dropped.

## How thresholds were frozen (no sweep)

- `oi_change_zscore` uses a strictly trailing 30-day (720-hour) PIT window with `min_observations=480`.
- The single expansion/contraction threshold pair (±1.0 z) is mechanism-backed (OI must move with/against the hour's move beyond one rolling std) and frozen **before** any performance observation. No alternatives were evaluated on returns — none exist to evaluate, since `PERFORMANCE_OBSERVED=false`.

## Falsifiability

PASS requires all of: N minimums, net expectancy > 0, `P(Sharpe>0) ≥ 0.90`, permutation `p ≤ 0.05`, Sharpe CI excluding zero, halves/thirds/walk-forward consistency, and `|r| ≤ 0.70` vs the momentum proxy (computed with a correct, self-tested Pearson). Any unmet gate ⇒ terminal `DISCOVERY_FAIL` recorded in the failed-memory register; post-hoc subcells are `POST_HOC_LEAD_ONLY`.

## Governance chain

Dataset freeze (`OI_FULL_HISTORY_DATASET_SHA256 = 16779b7d…`) → collision review (PASS) → mechanism evidence (PASS) → selection (this document) → prereg commit → independent verifier. No economic execution in this checkpoint; execution may only be considered by `H6-INDEPENDENT-IMPLEMENTATION-AND-DISCOVERY-01` after verifier PASS.
