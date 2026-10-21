# RUN REPORT — EXP-003O — Independent Signal Regeneration

**status `INCOMPLETE`** · `TECHNICAL_SIGNAL_PARITY=PASS` · `FULL_INDEPENDENT_CERTIFICATION=INCOMPLETE_REAL_DATA_COVERAGE` · `ECONOMIC_EDGE=NOT_EVALUATED`

- design digest `b28a7b4c53168fd5…` · preregistration commit `4ea93d8` · prospective=`True`
- source commit `f831c66` · experiment commit `54d010c`
- 24 cells (24 evaluable) · 275724 keys · 52848 / 52848 signals
- 0 unexplained differences · 0 PIT violations · 12/12 controls

## What was measured

| dimension | value |
| --- | --- |
| keys compared | 275724 |
| rows audited (original / independent) | 275724 / 275724 |
| signals | 52848 / 52848 |
| unexplained differences | 0 |
| PIT violations | 0 |
| prefix invariance | True |
| functional coverage | True |
| clean-checkout reproduction | REPRODUCED |
| holdout opened | False |
| orders (live / paper) | 0 / 0 |
| config unchanged | True |

## Cells

| cell | evaluations | signals | mismatches | state |
| --- | ---: | ---: | ---: | --- |

See `CELL_COVERAGE_MANIFEST.csv` for the 24 cells and `SIGNAL_PARITY.csv` for the
per-symbol detail.

## Tests executed for this report

`{"executed_at_utc": "2026-10-21T09:13:09Z", "failed": [], "mypy": {"exit_code": 0, "tail": "Success: no issues found in 11 source files"}, "pytest_reports": {"exit_code": 0, "tail": "174 passed, 14 warnings in 21.95s"}, "ruff": {"exit_code": 0, "tail": "All checks passed!"}, "state": "PASS"}`

## Limits

- `ECONOMIC_EDGE` is not evaluated here: no return, cost or ranking is computed.
- The holdout was never opened; no order of any kind was produced.
- The verifier is a program, not a person; `BUILDER != VERIFIER` holds as two programs.
