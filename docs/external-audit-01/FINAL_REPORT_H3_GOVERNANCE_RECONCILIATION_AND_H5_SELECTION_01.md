# FINAL REPORT — H3-GOVERNANCE-RECONCILIATION-AND-H5-SELECTION-01 + R2/SHADOW CONTINUATION

Date: 2026-09-10 · Authoritative base: `8dec6c8` → this checkpoint: `c426b35` (prereg + reconciliation)
Evidence: `h3-relative-value-01/H3_EXECUTION_FORENSICS.md`, `h3-relative-value-01/execution-ledger/`,
`h5-orderflow-imbalance-01/{H5_SPEC,H5_MANIFEST,H5_SELECTION_RATIONALE}`, `DEFECT_REGISTER.md`,
`REGIME_COVERAGE_GAP_REPORT.md` (addendum).

| Field | Value |
| --- | --- |
| H3_ECONOMIC_EXPERIMENTS | **1** |
| H3_EXECUTION_ATTEMPTS | **2** (ledger `#a1`, `#a2`; attempt 2 carries `recovery_of_attempt_id = #a1`) |
| H3_COMPLETED_EXECUTIONS | **1** (`#a2`, result sha256 `78c9abac…`) |
| H3_FAILED_ATTEMPTS | **1** (`#a1`, UnboundLocalError in report-table construction AFTER economic evaluation) |
| H3_ATTEMPT1_RESULT_EXPOSURE | **RESULT_COMPUTED_NOT_OBSERVED** — metrics computed internally but no stdout emission, no marker, no result file before the crash; code-ordering reconstruction at `4ea37b3` |
| CERTIFY_EXACTLY_ONCE_H3 | **true** — 1 experiment, 2 attempts, 1 completed, 1 failed, recovery-linked; attempt semantics not hidden |
| DEF_H3_EXEC_001 | **CONFIRMED / FIXED** (LATE_EXECUTION_MARKER: the legacy pattern wrote the completion marker after simulation, before result persistence, so "ran and crashed before persisting" was indistinguishable from "never ran") |
| RESEARCH_EXECUTION_LEDGER | **PASS** — `src/trading_bot/research/execution_ledger.py`: append-only JSONL, failure-atomic acquire, recovery links; 7 adversarial tests (EXEC-04/05/06, B2/B4) |
| MARKER_BEFORE_EVALUATION | **PASS** — STARTED record persisted + fsync'd BEFORE any economic work (data evaluation, signals, simulation, metrics, classification) |
| CONCURRENCY_TEST | **PASS** — second acquirer receives ALREADY_RUNNING / ALREADY_CONSUMED; no duplicated economic authority |
| H3_RESULT | **DISCOVERY_FAIL — preserved, NOT rerun** (gross −0.3674 R, gross PF 0.492: failure is cost-, funding- and neutrality-independent) |
| H3_NEUTRALITY | **FAILED** (DEF-H3-NEUTRALITY-001 preserved; "beta-neutral" label withdrawn; allowed description: beta-weighted relative-value experiment whose preregistered neutrality condition failed) |
| PAPER_PROMOTIONS | 0 |
| SHADOW_CAPTURES / MATURE / RESOLVED / PENDING | 11 / **0** / 0 / 11 — earliest maturity 2026-09-11T21:15Z; nothing genuinely mature, zero resolutions (SH-01/SH-02) |
| MAX_POSITIONS_SHADOW | INSUFFICIENT_SAMPLE — no mature captures yet; Risk unchanged (SH-03) |
| REGIME_GAPS | Gap report addendum: order-flow imbalance regimes = **INSUFFICIENT_OBSERVATION** (largest remaining gap with proven data authority — klines fields 8/9 present in all three frozen assets); failed regime cells carried forward |
| FAILED_MEMORY_COUNT | **11** — #1–#11 explicitly consumed in the gap refresh and H5 selection (no mechanism repackaged) |
| NEXT_HYPOTHESIS | **H5** (exactly one; NO_CANDIDATE not invoked — data authority is proven) |
| H5_NAME | `H5-ORDERFLOW-IMBALANCE-CONTINUATION-01` |
| H5_RATIONALE | Taker-flow imbalance (OFI from frozen klines field 9) at elevated participation (field 8 vs trailing norm) marks directional pressure that tends to PERSIST into following bars; WITH-flow continuation at next bar open, fixed 12-bar horizon, 1.0×ATR14 stop. New family (`order_flow_microstructure`) — orthogonal to failed-memory #1–#11 and to H3's refuted reversion premise. Selection was performance-blind (no signal statistic observed). |
| H5_PREREG_COMMIT | `c426b35` (spec blob `c4cb892`; manifest blob `a1eee0d`) |
| H5_SPEC_SHA256 | `c743fba4a2a589dc1c3a15c7cd48b1b6ddf80255b8a157ea4f7ef19cc2f81023` |
| H5_EXECUTIONS | **0** |
| CONFIRMATION_CONSUMED / EXECUTIONS | false / 0 (`CONF-EDGE-002-001` untouched until 2026-09-22T00:00Z) |
| RISK_CHANGED | 0 |
| LIVE_CALLS / FALSE_SUCCESS | 0 / 0 |
| HERMETIC_REGRESSION | **1224 passed / 0 failed** (full hermetic rerun executed at `c426b35`). Note: the pre-commit run showed 1223/1, the 1 failure being `test_dependency_closure_guard` firing on the then-untracked `execution_ledger.py` — the guard working as designed; resolved by the commit itself. |
| **STATUS** | **PASS** |

**NEXT:**
- H5 preregistered → **WAIT FOR INDEPENDENT VERIFICATION** of `c426b35` (spec sha256 unchanged, ordering strict), **THEN EXECUTE H5 EXACTLY ONCE** through the ResearchExecutionLedger flow (`acquire → STARTED durable → sync/PIT checks → economic evaluation → marker → result → finish_completed`).
- CONTINUE_R2_DIAGNOSTIC (campaign unchanged, DIAGNOSTIC/DEGRADED/NON-CERTIFYING retained)
- MATURE_SHADOW (first resolutions possible from 2026-09-11T21:15Z; mature-only, PIT)
- CONFIRMATION_WAIT (`CONF-EDGE-002-001`, closes 2026-09-22)
