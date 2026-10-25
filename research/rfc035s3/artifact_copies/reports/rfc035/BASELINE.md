# RFC-035 — BASELINE (external profitable opportunity discovery)

as_of_utc = 2026-10-07T21:05:00Z
ACTIVE_RFC = RFC-035 (EXTERNAL PROFITABLE OPPORTUNITY DISCOVERY)
MODE = PROFITABILITY_FIRST
ALPHA_004 = NOT_OPENED

## Commit / working tree

| field | value |
| --- | --- |
| branch | main |
| HEAD | 7e21f7ca6dbf8816d83f2f8ab15aeb09310b878c |
| HEAD subject | fix(research): bound CAP-004 evidence storage and keep the real settlement (CAP-004C) |
| CAP-004C commit present | YES (7e21f7c, 2026-10-07T20:46:22+02:00) |
| working tree | DIRTY (26 entries, pre-existing work of other threads) |

Dirty entries are other threads' work (docs/research/work_packages/*, src/trading_bot/research/experimental/*,
PAPER_DATA_24H_REPORT.*, evidence/real_decisions/*.jsonl growth, docs/source_registry.md, root FINAL_REPORT/RUN_REPORT).
RFC-035 touched exactly one pre-existing tracked file: `scripts/cap004c_verify.py` (plus its own new artifacts).
No entry belonging to another thread was modified, reverted or staged.

## RFC number collision (declared, not hidden)

`reports/RFC035_FINAL_REPORT.{md,json}` (2026-10-05, commit d940b532) is a **different, older RFC-035**:
"STRATEGIC PROFITABILITY PLAN V2" (diversified futures, P1 = MANAGED_FUTURES_TREND). Its own successor
lines are already closed: MF-TREND-001 = MODERN_VALIDATION_DATA_BLOCKED (RFC-037/RFC-038; min capital
25M-50M USD), FUTURES_CURVE_CARRY = not pursued. This RFC-035 is a distinct task; its artifacts are
namespaced under `reports/rfc035/` (lowercase) and `research/profitability/`. External reviewers must
not merge the two.

## RFC-035 artifact-name collision (declared)

`scripts/rfc035_verify.py` already exists in this repository: it is the tracked independent verifier of the
**older** RFC-035 ("admit external multi-asset strategy candidates", commit 17d4777), which verifies
`reports/profitability-v2/`. Overwriting it would have destroyed another RFC's ability to verify itself, so
this run's verifier was created as **`scripts/rfc035_discovery_verify.py`** and the older file was left
byte-identical to its committed state. The verification artifact of this run is
`reports/rfc035/RFC035_VERIFICATION.json`; the older one stays at `reports/profitability-v2/RFC035_VERIFICATION.json`.

## Certified incoming state (confirmed, not assumed)

| gate | command | result |
| --- | --- | --- |
| CAP-004C storage | `.venv/Scripts/python scripts/cap004c_verify.py` | **PASS** 169/169, mismatches 0, false_success 0 |
| CAP-004B campaign | `.venv/Scripts/python scripts/cap004b_verify.py` | **PASS** 36/36 |
| CAP-004 / CAP-003 | delegated by cap004c_verify | **PASS**, false_success 0 |
| unit tests | `.venv/Scripts/python -m pytest -q` | 2745 passed, exit 0 (214.6 s) |
| lint | `.venv/Scripts/python -m ruff check .` | All checks passed, exit 0 |
| types | `.venv/Scripts/python -m mypy . --exclude reports` | Success: no issues found in 687 source files, exit 0 |
| whitespace | `git diff --check` | exit 0 |

CAP004C = STORAGE_STABILIZED · CAP004B = RUNNING · CHAIN = INTACT · DRIFT = NO_DRIFT

## Campaign (CAP-004B) — running, with one observed anomaly

- campaign_id CAP004-REAL-DECISIONS-V1, campaign_status RUNNING, age 1.128 d at 2026-10-07T20:45:02Z
- population: 4 sealed · 4 matured · 4 settled · 4 evaluated · 4 verified · 0 matured_unsettled
- scheduler task `TradingAgentic-CAP004-Campaign`: state Ready, next run 2026-10-07T23:00 local
- disk: HEALTHY, 25,943,785,472 bytes free (24.16 GiB) at 20:45:02Z
- **observed anomaly**: cycles at 20:00, 20:15, 20:30 and 20:45Z ended with
 `error_type=MISSED_DECISION_SLOT`, exit_code 3 (verification SKIPPED), each still `scored: true` and
 writing its operation event. No decision was lost (0 pending, 4/4 settled). Reported as a finding so
 that a later reader does not mistake "campaign RUNNING" for "campaign sealing on cadence".

## Verifier-interpreter integrity finding (fixed during this baseline)

An earlier run of `scripts/cap004c_verify.py` on 2026-10-07T20:48:23Z (system interpreter, not the project
venv) wrote `assessment = storage_not_verified` with one mismatch: the replay group raised
`ModuleNotFoundError: No module named 'structlog'`. The evidence was fine; the interpreter was not. The
verifier now **fails closed**: if the project ledger module cannot be imported it prints
`STATUS = ENVIRONMENT_UNVERIFIED`, exits 2 and leaves the certified artifact untouched
(`scripts/cap004c_verify.py`). Re-run under the project venv: PASS 169/169. An environment artefact can no
longer be published as a storage verdict.

## Governing flags carried into RFC-035

```text
G_AGENTIC_EDGE   = NOT_TESTED   (src/trading_bot/research/agentic_baselines.py:112)
TRADES_AUTHORIZED  = 0        (src/trading_bot/research/agentic_contracts.py:49)
FALSE_SUCCESS    = 0
alpha_research_freeze = ACTIVE    (RFC-041 BUSINESS-FREEZE-2026-001, ECONOMIC_STATE.json)
next_alpha_rfc_allowed = false    (unchanged by this RFC)
BUSINESS_VALIDATED_EDGE_COUNT = 0
```

## Scope discipline

RFC-035 is executed inside the RFC-041 freeze as the **reentry-evidence mechanism** (BUSINESS_REENTRY_POLICY
trigger A: new external evidence), not as alpha research. It does not lift `alpha_research_freeze`, does not
authorize implementation, does not open ALPHA-004, and does not touch CAP-004.

Hard rules applied to everything below: no backtest of our own, no parameter search, no asset or timeframe
sweep, no strategy modification, no new agents/indicators/dashboards. The only question answered is whether
an external opportunity is defined and supported well enough to deserve an exact replication.

## Pre-existing closed lines respected (not re-opened, not renamed)

EXT-TSMOM-001 INVALIDATED_TRADABILITY · EXT-TSMOM-002 REJECTED_HISTORICAL_PLAUSIBILITY ·
EXT-TSMOM-003 REJECTED_VALIDATION · EXT-XMOM-001 REJECTED_ROBUSTNESS · MF-TREND-001 MODERN_VALIDATION_DATA_BLOCKED ·
SC-TREND-001 VALIDATED_DEFENSIVE · SC-DUALMOM-002 REJECTED_BUSINESS_EDGE · SC-CANDIDATE-003 NOT_AUTHORIZED ·
plus the internal cost-killed microstructure lines (A-01…A-06 flow imbalance / lead-lag, 23.79 bps RT cost floor).
