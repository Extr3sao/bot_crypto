# RUN REPORT — H5-RESULT-INTEGRITY-RECONCILIATION-02

Date: 2026-09-11 · Actor: buffy-agent (Freebuff) · Branch: `feat/ma-2-specialist-opportunity-swarm` (HEAD `cb3de4f`)

| Phase | Outcome |
| --- | --- |
| P0 prereg blob recovery | **PASS** — commit `c426b35` + blob `a1eee0d2` exist; `AUTHORITATIVE_BLOB_SHA256 = 29ececb7…db0a86` |
| P1 contaminated preservation | **PASS** — `H5_MANIFEST_POST_EXECUTION_CONTAMINATED.json` (sha256 `ed087e6c…`, byte-identical to on-disk state at run start); generation-3 wrong-restore state additionally preserved (`evidence/H5_MANIFEST_GEN3_WRONG_RESTORE_DFD89A28.json`, sha256 `dfd89a28…`) |
| P2 prereg vs contaminated | **PASS** — byte/text diff registered; `INTERNAL_FINGERPRINT_VALID = true`; `DEF-H5-GOV-002 = REJECTED` |
| P3 prereg restoration | **PASS** — `H5_MANIFEST.json` restored byte-identical from `c426b35`; `git diff c426b35 -- H5_MANIFEST.json` => EMPTY; `H5_PREREG_RESTORED = true` |
| P4 post-execution externalization | **PASS** — execution record / annotations / implementation status rebuilt as dedicated artifacts (ledger-anchored); prereg manifest contains zero post-execution state |
| P5 execution ledger reconciliation | **PASS** — canonical 1 / 2 / 1 / 1; recovery links governance-established; spec+protocol hashes identical across attempts; failure evidence verbatim from durable ledger (`failure_message_authority = COMPLETE_DURABLE_LEDGER`) |
| P6 DEF-H5-ORTHO-001 | **PASS (RECONCILED)** — invalid 61.9 proven to be exactly `102 × r`; `CORRECTED_PEARSON_R = 0.6070166220125719`; H5 not rerun |
| P7 final result | **PASS** — `H5_RESULT = DISCOVERY_FAIL` preserved; `H5_RESULT.json` untouched (ledger-anchored sha256 `2427310d…`); no retune, no rerun |
| P8 failed research memory | **PASS** — entry #12 appended to `FAILED_RESEARCH_MEMORY.md` with post-hoc cells marked POST_HOC_LEAD_ONLY |
| P9 information-set governance | **PASS** — `CURRENT_INFORMATION_SET = EXHAUSTED_FOR_NOW` registered (ADR-0033); no H6, no parameter search over H5 |
| P10 alpha data expansion | **PASS** — 8 families evaluated across all 11 required attributes (`ALPHA_DATA_EXPANSION_PLAN.md`) |
| P11 family selection | **PASS** — max 2 adopted: trade flow (aggTrades) + open interest (data.binance.vision); funding-differentials EXPERIMENT; book-depth standby; rest REJECT/DEFER; no H6 created |
| P12 shadow | **WAIT** — 11 captures, earliest maturity 2026-09-11T21:15Z > current UTC (11:10Z); no early resolution; `SHADOW_POLICY_CONCLUSION = INSUFFICIENT_SAMPLE` |
| P13 confirmation lock | **WAIT** — `CONF-EDGE-002-001` consumed=false, executions=0; nothing before 2026-09-22T00:00Z |
| P14 regression / governance | **PASS_WITH_PREEXISTING_FAILURES** — focused governance tests 20/20; full hermetic 1235 passed / 2 failed (both pre-existing, unrelated; details below) |
| P15 final artifacts | **PASS** — this report + RUN_REPORT.json + FINAL_REPORT.md (+ restoration/orthogonality/plan artifacts) |

## Regression details

- Command: `PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests -q` → **1235 passed / 2 failed (3m21s)**
- `tests/unit/config/test_settings.py::test_load_settings_happy_path` — pre-existing local
  environment/config drift (`exchange.id=bybit` in local settings vs `binance` expected);
  fails identically in isolation; no code or config touched by this run.
- `tests/unit/test_dependency_closure_guard.py::test_all_imported_internal_modules_are_tracked`
  — passes in isolation; fails only under full-suite import ordering; pre-existing.

## Guard counters

| Counter | Value |
| --- | --- |
| LIVE_CALLS | 0 |
| RISK_CHANGED | 0 |
| PAPER_PROMOTIONS | 0 |
| FALSE_SUCCESS | 0 |
| H5_RERUNS | 0 |
| Shadow resolutions before maturity | 0 |

## Governance asks deferred to the user

None. No production/live trading, no real capital/risk/leverage, no credentials, no
material external cost, no irreversible/destructive action was requested or performed.

**STATUS: PASS**
