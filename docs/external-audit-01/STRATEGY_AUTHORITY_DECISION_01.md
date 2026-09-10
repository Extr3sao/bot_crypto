# STRATEGY AUTHORITY DECISION — DEF-STRAT-RUNTIME-001 (TRACK D)

Checkpoint: **POC02-R2-DAY1-EXECUTION-RECONCILIATION-01 + STRATEGY-AUTHORITY-DECISION-01**
Question resolved: *"Does this strategy have authority to participate in future PAPER?"*
— NOT *"can we technically wire it?"* (that was the previous checkpoint's reachability audit,
`strategy_runtime_authority_map.md`, which this document extends with governance decisions).

## D1 — Current campaign (POC-02-R2-direction-arbitration-01)

The frozen R2 manifest pins the strategy universe to the legacy momentum composition.
**No strategy is added, removed, or re-validated in-place.** Momentum remains the runtime
strategy of the ACTIVE campaign as observational continuity — this is explicitly
**NOT** modern validation and confers no admission authority (see D2).

## D2 — Rule (no blind activation)

For any FUTURE campaign: runtime wiring ≠ paper authority. A strategy may only enter a
future manifest with explicit admission authority from one of:
modern VALIDATED cells (preregistered retro gates), a NEW preregistered discovery batch
passing the same gates, or an explicit governance exception recorded as an ADR.
Failed validation never auto-promotes; insufficient evidence never auto-promotes.

## D3 — Authority table (evidence-cited)

| Strategy | CODE_EXISTS | RUNTIME_COMPATIBLE | PIT_SAFE | ADMISSION_STATE | MODERN_VALIDATION | PAPER_AUTHORITY | DECISION |
| --- | --- | --- | --- | --- | --- | --- | --- |
| momentum | YES (registry + runtime echo) | YES (running in R2) | YES (frozen gates) | LEGACY baseline | **FAILED cells** (5m cost-dominated: NOT_SIGNIFICANT 5, NEGATIVE_NET 4) | **LEGACY_CURRENT_CAMPAIGN_ONLY** | Future = RESEARCH/REVALIDATION_REQUIRED — current failures do NOT transfer to a future modern implementation automatically, but nothing is eligible today |
| trend | YES (`research/families/trend_family.py`) | YES (contract-compatible per B2 audit) | YES (pure OHLCV) | NOT_ADMITTED | **INSUFFICIENT cells** (n < 15 binding) | **RESEARCH_ONLY** | Stay NOT_RUNTIME_REACHABLE until validated or admitted via new batch |
| breakout | YES (`research/families/breakout_family.py`) | YES (contract-compatible) | YES (pure OHLCV) | NOT_ADMITTED | **FAILED** (6 cells NOT_SIGNIFICANT, 3 NEGATIVE_NET, PF<1 ×3) | **RESEARCH_ONLY** | Do not activate; failed-significance evidence is binding |
| mean_reversion | YES (`research/families/mean_reversion_family.py`) | YES (contract-compatible) | YES (pure OHLCV) | NOT_ADMITTED | **FAILED** (3 cells NOT_SIGNIFICANT, 2 NEGATIVE_NET) | **RESEARCH_ONLY** | Do not activate |
| volatility | YES (`research/families/volatility_family.py`) | YES (contract-compatible) | YES (pure OHLCV) | NOT_ADMITTED | **INSUFFICIENT cells** (n < 15 binding) | **RESEARCH_ONLY** | Data-availability path exists (volatility_structure batch was DISCOVERY_FAIL on sample, not on idea) — re-registration possible |

Sources: `LEGACY_FAILURE_DIAGNOSIS.json` (`cell_counts {total 30, failed 14, insufficient 16, validated 0}`;
`gate_incidence_by_strategy` as quoted above), `strategy_runtime_authority_map.md` (B2/B3/B4 contracts),
`FINAL_REPORT_ALPHA_DISCOVERY_AND_SHADOW_V2_01.md` (LEGACY_VALIDATED=0).

## Future-PAPER-eligible set

**EMPTY.** Zero strategies hold PAPER_ELIGIBLE authority today. Next legal paths:
1. New preregistered discovery batch (no Batch03 until a regime-coverage gap is
   evidence-backed — TRACK E preserved).
2. CARRY-FUNDING-DEEP-01: already executed once → DISCOVERY_FAIL (no retune; a new
   preregistration with a different, justified cost/horizon contract would be new
   research, not a re-run).
3. INSUFFICIENT strategies (trend, volatility) may qualify with deeper real data —
   data-availability investigation only, no synthetic fill.

## Runtime compatibility ≠ authority (AUTH-02)

All four non-reachable strategies passed the technical B2 audit (PIT-safe, contract-
compatible, cost assumptions recorded). **They remain NOT_RUNTIME_REACHABLE** because
authority, not wiring, is the binding constraint. Any runtime topology change requires
a NEW campaign manifest (B3) with the B4 explicit-router-reason contract
(SELECTED / REJECTED / NOT_APPLICABLE / NOT_ADMITTED / NOT_RUNTIME_REACHABLE /
INSUFFICIENT_REGIME_EVIDENCE).
