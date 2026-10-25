# WP-EDGE-09F — the wider research suite

*Recorded at `2026-10-15T05:53:07Z` from `.ci/edge09_research_suite.log`. Command: `python.exe -m pytest tests/unit/research -q`. Exit code: 1.*

2296 passed, 1 failed in 519.64 s — **1 inherited**, 0 caused by this package.

## Failures

| Test | Touched by this package | Diagnosis |
| --- | :-: | --- |
| `tests/unit/research/test_cost_barrier_adversarial.py::test_the_certification_record_digests_content_not_a_checkout` | False | outside every path this package commits to; the package's own commits touch no file under it |

declared, not hidden: a failure outside this package's paths is reported as inherited and left to its owner, and a failure inside them would have to be fixed here before the package could close

The package's own suite, lint, format and type checks are executed by `scripts/edge09_report.py --tests` and their exit codes are in `RUN_REPORT.json`.
