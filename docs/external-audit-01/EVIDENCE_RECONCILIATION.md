# Evidence Reconciliation — PORTFOLIO-AND-RUNTIME-INTEGRATION-01

> Mandatory Phase 0 of the checkpoint. Reconciles two inconsistencies in
> `FINAL_REPORT_HARDENING_01.md` (BASE `01f7792`). Nothing was silently
> changed: the corrections below were applied to the ADR record and the
> FINAL_REPORT with explicit before/after values.

## A. NEW_TESTS canonical count

**Reported:** `NEW_TESTS = 58` with components
`execution 19, health 13, regime 9, correlation 9, stats 12+6, projection 4`.

**Reconciliation (via `pytest --collect-only -q`, measured at BASE `01f7792`):**

| Metric | Value | Files |
| --- | --- | --- |
| TEST_FILES_ADDED | 8 | `tests/unit/execution/{test_gateway_e2e,test_conformance}.py`, `tests/unit/strategies/test_health.py`, `tests/unit/research/test_regime_v2.py`, `tests/unit/portfolio/test_correlation.py`, `tests/unit/backtesting/test_stat_validation.py`, `tests/unit/research/test_admission_stats.py`, `tests/unit/paper/test_health_projection.py` |
| TEST_FUNCTIONS_ADDED | 72 | — |
| TEST_CASES_COLLECTED | 72 | — |
| PARAMETRIZED_CASES | 0 | — |
| TOTAL_NEW_PYTEST_ITEMS | 72 | — |

Per-file: execution 19 + 4 = 23? **No** — measured split: execution 19
(gateway e2e 15 + conformance 4… measured exactly 19 in
`test_gateway_e2e.py` + `test_conformance.py` combined), health 13, regime 9,
correlation 9, stats 12 + admission 6, projection 4 → **19+13+9+9+18+4 = 72**.

**Root cause of the "58":** transcription error in the FINAL_REPORT — the
component sum (72) was never recomputed against the report field. The
component counts themselves were correct.

**Corrections applied:** `tasks/decisions.md` ADR-0025 note and
`FINAL_REPORT_HARDENING_01.md` now state `NEW_TESTS = 72 (TEST_FUNCTIONS_ADDED =
TEST_CASES_COLLECTED = 72, PARAMETRIZED_CASES = 0, 8 files)`.

## B. FULL_REGRESSION exact decomposition

**Reported:** `837 passed / 1 pre-existing baseline` (ambiguous).

**Exact decomposition (full unit suite at BASE `01f7792`, this environment):**

| Metric | Value |
| --- | --- |
| COLLECTED | 839 |
| PASSED | 838 |
| FAILED | 1 |
| SKIPPED | 0 |
| XFAILED | 0 |
| XPASSED | 0 |
| ERRORS | 0 |

**The single failure** (`tests/unit/config/test_settings.py::test_load_settings_happy_path`,
expects default `exchange.id == 'binance'` but the local environment exports
`EXCHANGE_ID=bybit` from `.env`) **was proven pre-existing at BASE:**
reproduced in a detached worktree at `01f7792` (`git worktree add /tmp/base-01f7792 01f7792`)
with the same environment → same failure; worktree removed afterwards.
Classification: **environment-driven, NOT a checkpoint defect.**

**837 → 838 drift explanation:** the earlier 837-pass run predated staging the
new execution modules required by the dependency-closure guard; after staging,
the same suite passed 838.

## FALSE_SUCCESS

`FALSE_SUCCESS = 0`: every claimed PASS above is backed by a command output in
the retrieval log; no failure was reclassified to make a gate pass.
