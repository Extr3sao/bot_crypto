# H6 SELECTION RATIONALE V2 — H6-OI-CONFIRMED-CONTINUATION-02

Checkpoint: `OI-DATASET-REFREEZE-02 + PRICE-AUTHORITY-REPAIR-01 + PIT-CAUSALITY-REPAIR-01 + H6-PREREG-REPAIR-01` · 2026-09-12 · **prereg-only: `H6_EXECUTIONS=0`, `H6_BACKTESTS=0`, `PERFORMANCE_OBSERVED=false`**

## Decision

**Selected: exactly one hypothesis — `H6-OI-CONFIRMED-CONTINUATION-02`** (OI_CONFIRMED_CONTINUATION: position-stock conditioning on 1h decision buckets; BTCUSDT/ETHUSDT/SOLUSDT; common window 2021-12-01 → 2026-09-10; mechanism is **expansion-only** — contraction yields NO_TRADE).

## Why this mechanism

1. **New information axis, not a retry.** Open interest (position stock) appears in none of the 12 terminal failed families — every failure conditioned on price/volume flows, funding basis, or their derived states. OI conditioning is a genuinely different market variable. The failed-memory collision review V2 (`H6_FAILED_MEMORY_COLLISION_REVIEW_V2.md`) documents this per candidate and reaches `VERDICT=PASS`.
2. **Ex-ante mechanism evidence at official tier.** CME's official education material (E-1) treats OI change as the canonical confirmation/contradiction signal for price moves; corroborated by E-2 and leveraged-perp feedback dynamics in the peer-reviewed literature (E-3, corrected citation: International Journal of Financial Studies (IJFS) 14(7):178). No profitability claim is made — the gates decide later. Evidence document V2: `H6_MECHANISM_EVIDENCE_V2.md`.
3. **Cost structure is design-compatible.** Hourly cadence with OI conditioning targets far fewer decisions than H1's ≈6.5/day transitions (the #10 cost lesson). The prereg freezes **`BASE_TOTAL_ROUND_TRIP_COST_BPS=10` (single canonical TOTAL RT number; sensitivities 0/10/20/40 are diagnostic, not selection; gross reporting mandatory)** — this is the SOLE cost canonical value (no 0.12%/trade hurdle elsewhere).
4. **Collision risk managed.** M-A (event-level trade flow) collides with H5 (#12) and carries a severe storage/cost profile → **DEFERRED** with reasons recorded, not silently dropped.

## How thresholds were frozen (no sweep)

- `oi_change_zscore` uses a strictly trailing 30-day (720-hour) PIT window with **`min_observations=336`**, **center = median**, **scale = 1.4826 × MAD** (rolling std is NOT used), **no forward look**, **MAD==0 ⇒ NO_SIGNAL**.
- The single **expansion-only** threshold `z_oi >= +1.0` requires **`delta_oi > 0 AND robust_z_oi >= 1.0`** (raw-sign rule; contraction never qualifies even if z ≥ 1 due to a negative median/MAD). This is the sole threshold; contraction variant would be a separate preregistration.
- No alternative parameterizations were evaluated on returns — none exist to evaluate, since `PERFORMANCE_OBSERVED=false`.

## Falsifiability

PASS requires ALL of: N minimums (per-asset 30, pooled 100; INSUFFICIENT_SAMPLE is a FAIL-class outcome), net expectancy > 0 at **10 bps TOTAL RT**, `P(Sharpe>0) ≥ 0.90`, permutation `p ≤ 0.05`, Sharpe CI excluding zero, halves + thirds + walk-forward consistent, and **`|r| ≤ 0.50` vs the ROC(24h) momentum proxy** (correct Pearson, self-tested), plus **funding `EXCLUDED_WITH_LIMITATION` with `funding_materiality_gate_before_promotion=true`**. Any unmet gate ⇒ terminal `DISCOVERY_FAIL` recorded in the failed-memory register; post-hoc subcells are `POST_HOC_LEAD_ONLY`.

## Eligibility model (PIT)

- `DECISION_ELIGIBILITY_AT_T` is **strictly causal**: completed 1h price bar exists, `CURRENT_HOUR_OI_COMPLETENESS = exactly 12 distinct 5m OI snapshots` in the completed decision hour, previous-hour reference complete, rolling history ≥ 336 valid hourly OI changes, last observation not stale (≤ 600 s). **Archive-day validity (`OI_ARCHIVE_DAY_VALIDITY_LEDGER_V2.jsonl`) is forensic EVIDENCE only; it does NOT gate trading decisions.** A gap strictly AFTER T must not alter eligibility or feature/signal state at T (adversarially tested in `PIT_CAUSALITY_V2_REPORT.json`).
- **Decision spacing: NO COOLDOWN** — one decision per completed asset-hour (fixed 1h non-overlapping per-asset outcome: entry at next hour open, exit at that hour's close). There is no separate cooldown or minimum-hours-between-decisions gate.

## Governance chain

Dataset V2 freeze (`OI_FULL_HISTORY_DATASET_SHA256_V2 = 16779b7d...`, evidence in `docs/external-audit-01/oi-full-history-02/OI_FULL_HISTORY_DATASET_MANIFEST_V2.json`) + price authority V2 (`PRICE_AUTHORITY_SHA256_V2 = e1c2462a...`, evidence in `PRICE_1H_AUTHORITY_V2_MANIFEST.json`, 47 missing hours repaired with official klines; overlap at 2026-09-09T00:00Z byte/economic equality PASS) + collision review (PASS) + mechanism evidence (PASS, corrected E-3 citation) + V2 prereg commit (`H6_SPEC_V2.json`/`H6_MANIFEST_V2.json`, consistency audit `H6_PREREG_CONSISTENCY_AUDIT_V2.json` with `CONTRADICTIONS_FOUND=0`) → independent verifier package V2. **No economic execution in this checkpoint**; execution may only be considered after `H6_EXTERNAL_VERIFICATION_V2=PASS`.

## Canonical semantics (single source of truth)

This rationale agrees literally with `H6_SPEC_V2.json`, `H6_MANIFEST_V2.json`, `H6_FAILED_MEMORY_COLLISION_REVIEW_V2.md`, `H6_MECHANISM_EVIDENCE_V2.md`, and `H6_FEATURE_AUTHORITY_WHITELIST_V2.json`. Contradictions are `0`; the following are frozen:

- `MECHANISM = OI_CONFIRMED_CONTINUATION` (expansion-only; `delta_oi > 0 AND z >= 1` qualifies; contraction ⇒ NO_TRADE)
- `COOLDOWN = NONE`; `DECISION_SPACING = ONE_DECISION_PER_COMPLETED_ASSET_HOUR`
- `COST = 10 bps TOTAL RT` (sensitivities 0/10/20/40)
- `ROLLING_HISTORY = 720h trailing, median/1.4826·MAD, min 336, MAD==0 ⇒ NO_SIGNAL`
- `THRESHOLD = z >= 1.0` with raw-sign `delta_oi > 0`
- `ORTHOGONALITY = |r| ≤ 0.50` vs ROC(24h) proxy
- `ARCHIVE_DAY_VALIDITY = FORENSIC_ONLY`
- `STOP = NONE`; `PRIMARY_HOLDING = next-hour open → same next-hour close (exactly 1h)`
