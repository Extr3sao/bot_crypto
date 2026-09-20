# ARC-02 Prereg V2 Repair Report

Scope: repair ARC-02 prereg infrastructure, import authority and portability,
with zero economic change.

## Status

- FINAL_STATUS: PENDING_INDEPENDENT_PREREG_VERIFICATION_V2
- NEXT: ARC02_INDEPENDENT_PREREG_VERIFICATION_V2
- ECONOMIC_DIFF_COUNT: 0
- ARC02_BACKTESTS: 0
- ARC02_EXECUTIONS: 0
- ARC02_PERFORMANCE_OBSERVED: false
- FALSE_SUCCESS: 0

## Artifact set

- `ARC02_IMPORT_CONTAMINATION_REPRODUCTION.json`
- `ARC02_IMPORT_AUTHORITY_ROOT_CAUSE.md`
- `src/trading_bot/research/import_authority.py`
- `conftest.py`
- `scripts/arc02_import_bootstrap.py`
- `ARC02_TEST_TARGET_AUTHORITY.json`
- `ARC02_ROOT_FAIL_CLOSED.json`
- `ARC02_PORTABILITY_V2.json`
- `ARC02_IMPORT_AUTHORITY.json`
- `ARC02_PREREG_V2_REPAIR_REPORT.json`
- `ARC02_PREREG_V2_REPAIR_REPORT.md`
- `ARC02_V1_V2_SEMANTIC_DIFF.json`
- `ARC02_PREREG_V2_POINTER.json`
- `ARC02_RESUME_STATE.json`
- `RUN_REPORT.json`
- `RUN_REPORT.md`

## Verifier defect

PYTHON_IMPORT_AUTHORITY was FAIL because ambient PYTHONPATH or editable install
metadata (main checkout `.pth`) caused `import trading_bot` to resolve to the
main repo `src` instead of the ARC-02 worktree `src`.

This work reproduces that defect and then proves the repaired contract
restores checkout-authoritative import under pollution, wrong root and empty
root.

## Repair outcome

- Defect reproduced: true
- ROOT_CAUSE_IDENTIFIED: true
- PYTHON_IMPORT_AUTHORITY: PASS
- TEST_TARGET == AUDITED_TARGET: PASS
- WRONG_ROOT_FAIL_CLOSED: PASS
- EMPTY_ROOT_FAIL_CLOSED: PASS
- EDITABLE_PTH_CONTAMINATION_TEST: PASS
- PORTABILITY: PASS
- CLEAN_WORKTREE_BUILDER_CROSSCHECK: PASS
- ECONOMIC_DIFF_COUNT: 0

## Risk/coverage note

This report is BUILDER evidence, not independent verification. The next
verification must use a fresh verifier context/worktree.
