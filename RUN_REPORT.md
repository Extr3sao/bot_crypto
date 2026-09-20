# RUN_REPORT — ARC02 Prereg V2 Repair

## Summary

Repaired ARC-02 checkout import authority and portability without any economic
change. The work is BUILDER evidence only and is returned as
PENDING_INDEPENDENT_PREREG_VERIFICATION_V2.

## Worktree

- Worktree: `.research/arc02-prereg-v2-repair-01`
- Branch: `repair/arc02-prereg-v2-repair-01`
- Base commit: `3ebf5f54bba84300663a9de7f6b05c5b583bc9c6`
- Expected commit: `3ebf5f54bba84300663a9de7f6b05c5b583bc9c6`

## Defect

`PYTHON_IMPORT_AUTHORITY = FAIL` was reproduced: under ambient PYTHONPATH and/or
editable install metadata, `import trading_bot` resolved to the main checkout
`src`, not the ARC-02 worktree `src`.

## Root cause

Environment authority leakage: shared editable `.pth` and PYTHONPATH exposed the
main checkout as the authoritative first-party package source, and the authority
contract itself was previously loadable only under ideal `sys.modules` state.

## Repair

- Added an explicit checkout import authority contract
  (`src/trading_bot/research/import_authority.py`) that is loadable even in
  contaminated environments.
- Added a pytest authority guard (`conftest.py`).
- Added a script bootstrap (`scripts/arc02_import_bootstrap.py`).
- Added adversarial and fail-closed evidence for wrong root, empty root and
  editable `.pth` contamination.

## Evidence

- `ARC02_IMPORT_CONTAMINATION_REPRODUCTION.json`
- `ARC02_IMPORT_AUTHORITY_ROOT_CAUSE.md`
- `ARC02_IMPORT_AUTHORITY.json`
- `ARC02_TEST_TARGET_AUTHORITY.json`
- `ARC02_ROOT_FAIL_CLOSED.json`
- `ARC02_PORTABILITY_V2.json`
- `ARC02_V1_V2_SEMANTIC_DIFF.json`
- `ARC02_PREREG_V2_REPAIR_REPORT.json`
- `ARC02_PREREG_V2_REPAIR_REPORT.md`
- `RUN_REPORT.json`
- `RUN_REPORT.md`

## Acceptance

- DEFECT_REPRODUCED: true
- ROOT_CAUSE_IDENTIFIED: true
- PYTHON_IMPORT_AUTHORITY: PASS
- TEST_TARGET == AUDITED_TARGET: PASS
- EDITABLE_PTH_CONTAMINATION_TEST: PASS
- WRONG_ROOT_FAIL_CLOSED: PASS
- EMPTY_ROOT_FAIL_CLOSED: PASS
- PORTABILITY: PASS
- ECONOMIC_DIFF_COUNT: 0
- ARC02_BACKTESTS: 0
- ARC02_EXECUTIONS: 0
- ARC02_PERFORMANCE_OBSERVED: false
- FALSE_SUCCESS: 0

### Research discovery governance (Track B)

Track B contracts are implemented conservatively over the existing research
namespace:

- `StrategyFailureDiagnostics`
- `HypothesisGenerator`
- `ResearchBudget`
- `ExternalStrategyIntake`
- `MarketIntelligenceProvider`

Existing discovery tests in
`tests/unit/research/test_discovery_view.py` and
`tests/unit/research/test_discovery_execution.py` pass in this worktree
(20 passed). No new online economics were executed.

Acceptance highlights:

- FAILURE_DIAGNOSTICS_DETERMINISTIC: PASS
- FAILED_HYPOTHESIS_IMMUTABLE: PASS
- HYPOTHESIS_NEW_ID_ENFORCED: PASS
- RESEARCH_BUDGET_PERSISTENT: PASS
- SAME_HYPOTHESIS_RERUN_DENIED: PASS
- MULTIPLE_TESTING_EXPOSURE_TRACKED: PASS
- EXTERNAL_CANDIDATE_UNTRUSTED: PASS
- EXTERNAL_TO_RUNTIME_SHORTCUT: BLOCKED
- MARKET_INTELLIGENCE_FUTURE_AVAILABILITY_GUARD: PASS
- MARKET_INTELLIGENCE_EXECUTION_AUTHORITY: NONE
- NO_ECONOMICS_EXECUTED: true

### Status

FINAL_STATUS: PENDING_INDEPENDENT_PREREG_VERIFICATION_V2

NEXT: ARC02_INDEPENDENT_PREREG_VERIFICATION_V2
