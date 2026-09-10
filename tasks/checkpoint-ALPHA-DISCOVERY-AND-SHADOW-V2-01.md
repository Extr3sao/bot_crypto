# CHECKPOINT: ALPHA-DISCOVERY-AND-SHADOW-V2-01

AUTHORITATIVE_BASE: 31fd5d2 + latest POC01 evidence lineage

---
## Summary

POC01_STATUS: ACTIVE (RESUMED)

POC01_CLASSIFICATION: DEGRADED_OBSERVATIONAL_CAMPAIGN

POC01_COMPLETED_VALID_DAYS: 1

POC01_DAYS_GE_3: 0

POC01_FREQUENCY_RATE: 0 trades / valid day

POC01_COVERAGE: 09-08 coverage=0.717 (407.2 min outage); 09-09 partial 0.647 (508.1 min)

PRIMARY_FUNNEL_LOSS: NO_SIGNAL / STRATEGY_FILTERING (diagnosis pending full funnel attribution)

PRIMARY_RISK_REASON: RISK_REJECT (captures show no paper promotions)

LEGACY_VALIDATED: 0

LEGACY_FAILED: 14

LEGACY_INSUFFICIENT: 16

LEGACY_PRIMARY_FAILURE_MODES: negative expectancy, sample-size/regime-dependence, cost sensitivity (see legacy analysis)

DISCOVERY_CANDIDATES: 6

- carry_funding
- cross_sectional
- session_time
- liquidity_flow
- volatility_structure
- regime_transition_defense

DISCOVERY_PASSERS: []

DISCOVERY_FAILURES: []

REDUNDANT_CANDIDATES: []

INCREMENTAL_OPPORTUNITIES_PER_DAY: TBD (requires Discovery Batch results)

SHADOW_V2: PREPARED (ShadowCaptureHook present; integration design drafted)

SHADOW_PAPER_CONTAMINATION: 0 (design enforces isolation)

POC02_MANIFEST: DRAFT created (see manifests/POC02_MANIFEST.md)

POC02_MARKET_DATA_PROVIDER: TBD

POC02_EXECUTION_MODEL: PAPER (preregistered)

POC02_COVERAGE_CONTRACT: DRAFT included in manifest

CONFIRMATION_CONSUMED: false

CONFIRMATION_EXECUTIONS: 0

PAPER_PROMOTIONS: 0

POC01_RUNTIME_CHANGED: 0

LIVE_CALLS: 0

FALSE_SUCCESS: 0

HERMETIC_REGRESSION: see docs/external-audit-01/FINAL_REPORT_POC01_RECOVERY_AND_EVIDENCE_01.md

STATUS: REPAIR_REQUIRED (continue POC01 to end; run discovery batch; prepare POC02 manifest and preserve confirmation window)

NEXT:
- CONTINUE_POC01_TO_END
- REVIEW_DISCOVERY_PASSERS (when available)
- PREPARE_POC02
- CONFIRMATION_WAIT
