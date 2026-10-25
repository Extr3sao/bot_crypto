# GATE MATRIX — TAP-SUPERVISOR-INTEGRATION-002

Every row names the evidence file and the exit code that was actually observed. A gate is
`PASS` only when the artefact proves it; `PARTIAL` when the artefact proves part of it and the
remainder is declared; `OPEN_*` when it needs a decision this run may not make.

| Gate | What it demands | Status | Evidence | Exit |
| --- | --- | --- | --- | --- |
| **R0** scope | only justified, traceable files | **PASS** | `ROUTE_MANIFEST.json` (84 routes, each with lane blob + SHA-256 + origin commit + reason); `tools/route_manifest.py --check` | 0 |
| **R1** no main-side loss | the 7 divergent files are not main's work | **PASS** | `evidence/MAIN_ONLY_OVERLAP.txt`: 66 paths touched by main's 4 commits, **0** overlap with the 87 route paths | 0 |
| **R2** no lane merge | 301 commits not merged | **PASS** | `git rev-list --merges main..HEAD` = 0; branch has 4 commits | 0 |
| **D1** dependency declared | `matplotlib` in `pyproject.toml` | **PASS** | commit `f238b632` | 0 |
| **D2** lock consistent | `uv lock --check`; `uv sync --frozen` installs it | **PASS** | `--check` 0; `--frozen` 0; `matplotlib 3.11.2` importable; test 3/3 | 0 |
| **D3** lock cannot lie again | a test catches the omission offline | **PASS** | `tests/unit/test_dependency_lock_consistency.py` (3 passed; 3 failed against main's lock) | 0 / 1 |
| **T1** supervisor runtime | `tests/unit/ops` | **PASS** | `evidence/PYTEST_ops.log` — 76 passed | 0 |
| **T2** paper + risk | no test that passes on main fails | **PASS** (2 pre-existing reds) | `evidence/PYTEST_paper_risk_after_tests.log` 2 failed/220 passed vs `PYTEST_paper_risk_main_baseline.log` 6 failed/170 passed | 1 |
| **T3** risk contract | parity + the three deltas | **PASS** | `tests/unit/risk/test_risk_contract_014.py` — 46 passed | 0 |
| **T4** vision | migrated decision chain | **PARTIAL** | `PYTEST_vision_verbose.log` — 17 failed/311 passed/1 skipped; 15 data-bound, 1 script-bound (now skipped), 1 flaky (passes alone) | 1 |
| **T5** research | migrated economics | **PARTIAL** | `PYTEST_research_migrated.log` — 14 failed/159 passed, causes in RUN_REPORT §4 | 1 |
| **T6** entry points | the 8 scripts are runnable | **PASS** | `evidence/ENTRYPOINT_HELP.txt` — 8/8 exit 0 | 0 |
| **G1** risk contract reconciled | no unannounced risk-semantic change | **OPEN_SIGNOFF** | `RISK_CONTRACT_DELTA.md`: parity proven; three tightenings; **one loosening** (weekly veto rolls). Pre-existing `data/rfc048` red is main's, root cause measured | — |
| **G2a** supervisor verifier judges a real campaign | PASS on real artefacts, mutations detected | **PASS** | `evidence/REAL_CAMPAIGN_VERIFICATION.json` — PASS, 10/10 applicable, 2 not applicable, `false_success 0` | 0 |
| **G2b** verifier rejects bad campaigns | absent / tampered / leftover lock | **PASS** | `evidence/CONTROL_*.json` — 4/4 FAIL with the expected check | 1 each |
| **G2c** fixture behaviour preserved | the lane's verifier tests still pass | **PASS** | `tests/unit/ops/test_paper_supervisor_verifier.py` — 4 passed | 0 |
| **G2d** lock verifier judges its own producer | schema accepted, checks evaluated | **PASS** | `evidence/LOCK_CAMPAIGN_VERIFICATION.json` — no `UNSUPPORTED_CAMPAIGN_SCHEMA`, 29/32 checks true, 0 invalid/undetected mutations | 1 |
| **G2e** lock verifier on a full-contract campaign | ≥5 recoveries, both crash sites, reclaim race | **PASS** | `evidence/LOCK_CAMPAIGN_VERIFICATION_FULL.json` — 6 iterations, 17 cycles, 32/32 checks, 9/9 mutations detected, `false_success 0`; artefacts in `evidence/LOCK_CAMPAIGN_FULL2/`, stdout `evidence/LOCK_CAMPAIGN_FULL2_stdout.log` | 0 |
| **G3** B1 forced | the window reproduced and its site named | **PASS** | `tests/unit/ops/test_lock_attribution_b1.py` — 6 passed; empty lock forced, refused, not deleted | 0 |
| **P1** real PAPER campaign | STOP_COMPLETED, multi-cycle, recovery, no live order | **PASS** | `evidence/CAMPAIGN_stdout.log` exit 0; `CAMPAIGN.json` 5 cycles, RECOVERED, 0 locks, `live_orders 0` | 0 |
| **P2** independent verification | re-derived, not declared | **PASS** | `evidence/INDEPENDENT_VERIFICATION.json` — 7/7 claims, self-control requires FAIL on tampered copy, `false_success 0` | 0 |
| **B2** `verify_claims.py` | portability re-audit | **NOT_REAUDITED** | absent from `main` and from `codepaper/supervisor-001` | — |
| **B3** `uv sync --frozen` | the false success | **PASS (fixed)** | reproduced first (`--frozen` 0, no matplotlib), then locked and tested | 0 |
| **B4** `finished_without_locks` | explain `false` with empty locks | **NOT_REPRODUCED** | this run: `true`, exit 0; the flag is a poll timeout, not a verdict (RUN_REPORT §8) | 0 |
| **B5** aborted first lock campaign | name the cause, not paper over it | **EXPLAINED** | `evidence/LOCK_CAMPAIGN_FULL1_aborted_stdout.log` + `iterations/iteration-05/crash.log`: `COMMIT_CHANGED`, the pinned-identity guard refusing to resume under a moved `HEAD`; the frozen-`HEAD` rerun completed 6/6 | — |
| **S1** no self-certification | builder ≠ verifier | **PASS** | `tools/independent_verify.py` imports neither `trading_bot` nor the verifier; `imports_from_src: false`; 9/9 claims incl. `L1` (lock campaign re-walked) and self-controls `S1`/`S2` | 0 |
