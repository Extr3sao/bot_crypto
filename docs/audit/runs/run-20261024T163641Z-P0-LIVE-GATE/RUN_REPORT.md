# RUN REPORT — P0 LIVE GATE ENFORCEMENT

- **Task**: DEF-G3-03 — `LiveTradingGate` exists and is never invoked by
  `run --auto-trade`.
- **Branch**: `audit/mt0004-negative-controls`
- **Before**: `96e211bd` (G-3 closed, tree clean)
- **Implementation**: `6c90b21d`; verifier correction `efd97e76`
- **Verdict**: `P0_VERIFIED_SCOPED` (scoped to the live CLI; see §7)
- **Independence**: `PROCEDURALLY_SEPARATED` — different artefact, same author.
- **Live exchanges contacted**: none. Every sink is a recorder.

## 1. The defect, measured

Before any edit, `p0_live_gate_probe.py` drove the real
`trading_bot.app.main` with an instrumented broker and a live configuration in
which exactly one of the gate's ten checks rejects:

| | Result (all ten checks) |
|---|---|
| broker calls | **1** |
| gate validations | **0** |
| exit code | **0** |
| gate named in output | no |

The gate was not misconfigured or bypassed — it was never constructed. `src/`
had no importer.

Files: `before/place-order-futures-GATE-001…010.json`,
`before/SUMMARY.json`.

## 2. The fix

| File | Change |
|---|---|
| `src/trading_bot/execution/live_gate.py` | optional `credentials=(key, secret)`; rule logic unchanged |
| `src/trading_bot/app.py` | `_evaluate_live_gate`, `LiveGateVerdict`, `_live_stop_is_closed`, `_live_refusal_reason`; gate inside `_live_order_boundary`; startup refusal in `_cmd_run`; pre-client refusal in `_cmd_place_order`; settings errors exit 2 |
| `scripts/audit/g3_live_probe.py` | fixture made a legal live config (sandbox off, exchange id, keys) |
| `tests/unit/test_live_hot_stop_coverage.py` | in-flight test passes the now-required `settings` |
| `tests/unit/test_live_gate_enforcement.py` | 47 new cases |
| `scripts/audit/p0_live_gate_probe.py` | process-boundary probe with `--break`, `--gate-crash`, `--settings-error` |
| `scripts/audit/p0_live_gate_mutants.py` | seven exact-anchor mutants |
| `scripts/audit/verify_p0_live_gate.py` | separate verifier |

The enforcement rule is `failed_gates == 0` **and** `total_gates == 10`. That is
stricter than `GateReport.all_passed`, which ignores `high` failures (GATE-006
database, GATE-008 security). The rule lives in `app._evaluate_live_gate`; the
gate class keeps its published semantics.

## 3. Coverage

`ENTRYPOINT → GATE → BROKER`, full table in `COVERAGE_MATRIX.md`.

| Path | Gate | After |
|---|---|---|
| `run --auto-trade` futures | startup + boundary | 0 calls, exit 2 with a rejected check |
| `run --auto-trade` spot | startup + boundary | 0 calls, exit 2 |
| `place-order` futures OPEN | pre-client + boundary | 0 calls, exit 2 |
| `place-order` spot buy | pre-client + boundary | 0 calls, exit 2 |
| `close-position`, `set-tpsl`, futures CLOSE, spot sell | not consulted | 1 call, exit 0 |
| `run --demo` / `paper_cycle` | none | unchanged (G-4) |

Before/after table: `BEFORE_AFTER.md`. Raw evidence: `before/`, `after/`.

## 4. Test results (verified commit)

| Suite | Result |
|---|---|
| `tests/unit/test_live_gate_enforcement.py` | **47 passed** |
| `tests/unit/test_live_hot_stop_coverage.py` (G-3) | **21 passed** |
| `test_app_cli_contract` + `test_app_demo` + `tests/unit/autonomous/` | **405 passed** |
| `tests/unit/test_audit_contracts_tracked.py` | passed (contract tracked) |
| Verifier regression (P0 + G-3 + CLI + demo + autonomy) | **473 passed** |
| Mutation matrix | **7/7 killed**, baseline green (`mutations.json`) |

Static: `ruff` clean; `mypy` clean on `app.py`, `live_gate.py` and the three P0
scripts.

## 5. Independent verification

`scripts/audit/verify_p0_live_gate.py` exports the commit, re-derives the
structural property, drives all entrypoints and reductions, asks the exported
package for the verdict on legal/high/short reports, and checks artefact
hashes. It does not import the test module.

- First pass at `6c90b21d`: **13/15** — V-15 expected red (no report yet), V-9
  red for a real verifier defect (`mode` as `str`, `.value` raised). Kept in
  `verification-first-pass.json`.
- Correction commit `efd97e76`; final result in `verification.json`.

Final pass at `82e8b3ac` (archive export, clean tree): **15/15 checks —
`P0_VERIFIED_SCOPED`** in 235.0 s. V-13 ran 473 tests in 168.9 s; V-14 read the
mutation matrix (7/7 killed, same `app.py` hash); V-15 matched 19/19 artefacts.
The verifier's own output is `verification.json`.

## 6. Defects

| ID | State | Description |
|---|---|---|
| DEF-G3-03 | **closed** | gate existed and was never called; now enforced at entry and sink |
| DEF-P0-01 | **closed** | G-3 probe built an illegal live config (`sandbox=True`, no exchange id); corrected in the fixture |
| DEF-P0-02 | **closed** | verifier built `mode` as `str`, making two checks raise; corrected in `efd97e76` |
| DEF-P0-03 | **open, out of scope** | `LiveTradingGate._data_dir` is stored and never used; GATE-006 resolves the SQLite path against the process cwd |
| DEF-P0-04 | **open, out of scope** | `run --mode live --auto-trade` still has no `--confirm-live`, so the gate is the only admission control on that path |

## 7. Limits

- All brokers are recorders: payload validity and exchange rejections are not
  tested, and no real order exists.
- Procedural independence only (same author); never "independently audited".
- GATE-009/010 are forced-failure cases; they cannot reject a real config.
- Scope is the live CLI. `run --demo`/`paper_cycle` (G-4) has neither the hot
  stop nor this gate.
- A different `--run-dir` still scopes the hot stop to a directory (G-3 §4.3).
- No live process was left running; no exchange credentials were read.

## 8. Recommendation for G-4

G-4 is now the largest uncovered path: `run --demo` reaches `PaperBroker`
through `paper_cycle` without `DecisionEngine` and without either live control.
The next task should decide whether that path exists at all, not add a third
gate to it: either route it through the autonomous runtime or delete it. Until
then, neither G-3 nor P0 applies to `run --demo`, and the backlog should not
pretend it does.
