# H3 EXACTLY-ONCE SEMANTICS — GOVERNANCE CORRECTION (Track A / A1)

Checkpoint: H5-ORDERFLOW-INDEPENDENT-VERIFICATION-AND-DISCOVERY-01 · Date: 2026-09-11
**STATUS: APPLIED & VERIFIED**
Documentation/governance correction only. **H3 is NOT rerun. `H3_RESULT.json`, the ledger rows
and all prior reports remain byte-identical.**

## Correction

The prior final report (`cb3de4f`, field `CERTIFY_EXACTLY_ONCE_H3`) stated **true**. That claim
is **incorrect under the corrected semantics** and is hereby superseded:

> **CERTIFY_EXACTLY_ONCE_H3 = false**

Reason: the economic evaluation code (data load → features → signals → simulation → metrics)
executed in **both** attempts. Attempt 1 completed evaluation and crashed during report-table
construction; attempt 2 re-executed the same evaluation. One *experiment identity* does not
imply one *evaluation execution*.

## Canonical H3 execution semantics (authoritative)

| Field | Value |
| --- | --- |
| ECONOMIC_EXPERIMENT_IDS | 1 |
| EXECUTION_ATTEMPTS | 2 |
| EVALUATION_ATTEMPTS | **2** |
| COMPLETED_EXECUTIONS | 1 |
| FAILED_EXECUTION_ATTEMPTS | 1 |
| ATTEMPT1_RESULT_EXPOSURE | RESULT_COMPUTED_NOT_OBSERVED |
| DEF_H3_EXEC_001 | CONFIRMED_FIXED (LATE_EXECUTION_MARKER) |
| H3_RESULT | DISCOVERY_FAIL — unchanged; failure is gross-level (−0.3674 R, PF 0.492), independent of attempt semantics |

## A1 — Separated verdicts

| Verdict | Value |
| --- | --- |
| H3_HISTORICAL_EXACTLY_ONCE | **FAIL** (evaluation ran twice under one experiment identity) |
| FUTURE_RESEARCH_EXECUTION_PROTOCOL | **PASS** (ResearchExecutionLedger: durable STARTED before any economic work, append-only attempts, recovery links, concurrency lock; 7 adversarial tests) |
| DEF_H3_EXEC_001 | CONFIRMED_FIXED — the ledger repair remains valid |

Historical ledger rows are NOT rewritten: `#a1` remains FAILED, `#a2` remains COMPLETED with
`recovery_of_attempt_id = #a1`. The correction lives here and in the checkpoint final report.

## Future protocol rule (binding for all subsequent hypotheses, including H5)

Exactly-once certification requires **exactly one EVALUATION execution**, not merely one
experiment identity. A crashed attempt that already reached economic evaluation can never
yield a certified exactly-once execution for that experiment; recovery is still permitted
(recovery of the same identity, new attempt_id), but `CERTIFY_EXACTLY_ONCE` stays false and
the ledger records `EVALUATION_ATTEMPTS = 2`. The ledger's STARTED-before-evaluation invariant
exists precisely so this can never again be ambiguous.
