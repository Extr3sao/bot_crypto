# FINAL REPORT — POC02-R2-GOVERNANCE-RECONCILIATION-AND-ALPHA-SEARCH-01

| Field | Value |
| --- | --- |
| **CHECKPOINT** | POC02-R2-GOVERNANCE-RECONCILIATION-AND-ALPHA-SEARCH-01 |
| **R2_MANIFEST** | `docs/external-audit-01/POC02_R2_MANIFEST.md` · commit **`f669899`** · sha256 **`7408f1ce…791b6b8`** (working tree verified byte-identical to committed blob) |
| **COVERAGE_THRESHOLD** | **≥ 0.80 observed/expected minutes per completed UTC day** (preregistered in the R2 manifest; never lowered, never raised) |
| **DAY1_EXPECTED_MINUTES** | **1440** — A2 semantics: POC02 manifest preregisters `expected cycles/day = runtime cadence × 1440 min` → **option D (full 1440-minute counted day)**; this is what the runtime has recorded since cycle 0. No burn-in, partial-day, or launch-day exception exists in any R2 manifest — none invented. |
| **DAY1_OBSERVED_MINUTES** | 4 |
| **DAY1_COVERAGE** | **0.0028** |
| **DAY1_COUNTED** | **false** |
| **DAY1_VALID** | **false** (corrected via formal amendment; originally — defectively — VALID) |
| **DEF_R2_003** | **CONFIRMED** (`COVERAGE_VALIDITY_CONTRACT_BYPASS`): `VALIDITY_MIN_RATIO = 0.80` was declared at commit `2bda355` but `_evaluate_validity` never enforced it (metadata only). The "coverage is evidence, not a new threshold" line contradicts the manifest's own numeric row; it is an undocumented post-hoc reinterpretation, not a preregistered exception. DEF-POC01-OBS-006 (trade-coupling) was orthogonal and confers no coverage exception. **Repaired**: ratio now enforced (`COVERAGE_BELOW_MINIMUM`), formal `amend_day()` added; day 2026-09-09 amended `VALID → INVALID` with the original finalization preserved verbatim in the append-only amendments chain (finalization_count stays 1; no evidence deleted). |
| **COMPLETED_VALID_DAYS** | **0** |
| **DAYS_GE_3** | **0** |
| **FREQUENCY_DAY1** | **NOT_EVALUABLE_INVALID_DAY** (an invalid day is not frequency-failed — it is not frequency-evaluable; prior "FREQUENCY_DAY_FAIL" wording corrected) |
| **R2_CLASSIFICATION** | **DIAGNOSTIC_CAMPAIGN + DEGRADED_OBSERVATIONAL_CAMPAIGN + INVALID_FOR_PERFORMANCE_CERTIFICATION** (labels retained; NOT a clean observational campaign) |
| **CERTIFY_RUNTIME_REACHABILITY** | **true (post-repair)** — 4 natural executions after `007b691` |
| **CERTIFY_DIRECTION_ARBITRATION** | **true (composition)** — no structural deadlock recurrence across all windows; adversarial suite frozen |
| **CERTIFY_EXACTLY_ONCE_WHOLE_CAMPAIGN** | **false** — pre-enforcement duplicate exists (09-10 BTC-LONG ×2) |
| **CERTIFY_EXACTLY_ONCE_POST_ARM** | **true** — `R2_INTENT_LEDGER` armed 2026-09-10T06:58Z; post-arm max orders/intent = 1 |
| **CERTIFY_FREQUENCY** | **false** — zero valid counted days |
| **CERTIFY_PROFITABILITY** | **false** — 4 opens, 0 closes, zero valid days |
| **SHADOW_CAPTURES** | **10** |
| **SHADOW_RESOLVED** | **0** — earliest matures 2026-09-11T21:15Z (48h immutable horizon; mature-only resolution) |
| **MAX_POSITIONS_SHADOW** | **INSUFFICIENT_SAMPLE** (0 resolved; MAX_POSITIONS unchanged) |
| **FUTURE_PAPER_ELIGIBLE** | **NONE** (preserved; no new PAPER campaign launched — no Admission authority exists) |
| **REGIME_GAPS** | No regime is COVERED_WITH_EVIDENCE; transition/correction = biggest `INSUFFICIENT_OBSERVATION` gap (runtime lacks transition granularity); HIGH_VOL/TRENDING = `UNDER_COVERED` runtime + `ACTIVITY_WITHOUT_EDGE` retro. Canonical map: `REGIME_COVERAGE_GAP_REPORT.md` |
| **NEXT_RESEARCH_HYPOTHESES** | **H1 regime-transition defense → CANDIDATE** (rank 1, 24/30; targets the transition gap; cost-realism directly attacks the 0.0012/trade kill). H2 vol term-structure gate (20), H4 session effects (21, blocked by failed-memory cost mechanism), H3 relative-value pairs (18) held as IDEAs. Full ranking + F2 pipeline: `NEXT_RESEARCH_HYPOTHESES.md` |
| **CONFIRMATION_CONSUMED** | **false** (CONF-EDGE-002-001, window 2026-09-08 → 2026-09-22, untouched; no early inspection) |
| **CONFIRMATION_EXECUTIONS** | **0** |
| **RISK_CHANGED** | **0** (RiskManager untouched; MAX_POSITIONS unchanged; only the validity evaluator + telemetry were repaired) |
| **LIVE_CALLS** | **0** (REAL_BROKER=0, PRIVATE=0, SHADOW_PAPERBROKER=0) |
| **FALSE_SUCCESS** | **0** |
| **HERMETIC_REGRESSION** | **1190 passed / 0 failed** (ruff clean) |
| **STATUS** | **PASS** — contradiction reconciled by repair + formal amendment; classification honest; alpha-search artifacts produced |
| **NEXT** | CONTINUE_DIAGNOSTIC_R2 + MATURE_SHADOW (first resolutions 09-11+) + EXECUTE_PREREGISTERED_ALPHA_RESEARCH (H1 spec) + CONFIRMATION_WAIT |

## Key governance outcomes

1. **The contradiction was real and is now repaired.** Day 1 was finalized VALID under a
   bypassed contract. The numeric ≥ 0.80 rule is now enforced in the finalizer, the
   defective finalization was corrected through a formal append-only amendment (original
   preserved), and today's open day is displayed with the contract banner.
2. **No retrospective threshold choice.** The 1440-minute denominator was already the
   runtime's recorded semantics; the enforcing threshold is exactly the preregistered
   0.80 — not raised to make the past look worse, not lowered to make it look better.
3. **Frequency language corrected**: FREQUENCY_DAY1 = NOT_EVALUABLE_INVALID_DAY (the
   prior checkpoint's "FREQUENCY_DAY_FAIL" implied evaluation of a day that cannot be
   evaluated).
4. **Primary work shifted to alpha discovery** with three canonical artifacts:
   regime-gap map, failed-research memory (9 lessons), and one ranked hypothesis (H1)
   admitted to CANDIDATE — bounded, evidence-backed, no random proliferation.
