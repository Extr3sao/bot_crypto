# WORK PACKAGES — EXP-003P

| WP | Scope | Status | Evidence |
| --- | --- | --- | --- |
| `WP-003P-00` | read-only inventory, runtime map, baseline, paper-adapter viability | `DONE` | `BASELINE.md`, `runtime_authority_map.md`, `evidence/BASELINE.json` |
| `WP-003P-01` | instrumentation of the reachable paper runtime: contracts, store, state machine, ledger, provenance, reconciliation | `DONE` | `src/trading_bot/paper/lifecycle/*`, `EXECUTION_TRACE.jsonl`, `ORDER_EVENT_SCHEMA.*`, `STATE_MACHINE.md` |
| `WP-003P-02` | unit/contract tests and 17 adversarial controls with exact failure classes | `DONE` | `tests/unit/paper/test_execution_lifecycle.py`, `NEGATIVE_CONTROLS.json`, `evidence/TESTS.json` |
| `WP-003P-03` | offline rehearsal on frozen bars, executed twice | `DONE` | `EXECUTION_TRACE.jsonl`, `SCENARIO_TRACE.jsonl`, `ORDER_LIFECYCLE.csv`, `RECONCILIATION.json`, `METRICS.json`, `DIGESTS.json`, `runs/run-2/` |
| `WP-003P-04` | observed paper with an authorised provider | `BLOCKED_NOT_CONFIGURED` | `RECONCILIATION.json` → `paper_validation`; `evidence/BASELINE.json` → `provider_viability` |
| `WP-003P-05` | separate verifier, independence audit, clean-checkout reproduction, seal | `DONE` (`checkout` NOT_PERFORMED, see below) | `VERIFICATION.json`, `INDEPENDENCE_AUDIT.json`, `evidence/CLEAN_CHECKOUT_REPRODUCTION.json`, `SHA256SUMS.txt` |

## Commands, in order

```text
python scripts/exp_003p_baseline.py          # WP-00, read-only + one broker probe
python scripts/exp_003p_preregister.py       # freeze PROTOCOL.json before any run
python scripts/exp_003p_schema.py            # publish schema/state machine from the code
python scripts/exp_003p_rehearsal.py         # WP-03 run 1 (publishes into this directory)
python scripts/exp_003p_rehearsal.py --out .../runs/run-2   # WP-03 run 2, determinism
python scripts/exp_003p_controls.py          # WP-02, 17 controls
python scripts/exp_003p_verify.py            # WP-05, independent checks
python scripts/exp_003p_pipeline.py tests    # suites, ruff and mypy with real exit codes
python scripts/exp_003p_report.py            # RUN_REPORT / FINAL_REPORT
python scripts/exp_003p_report.py --seal     # SHA256SUMS.txt
```

## What was deliberately not built

- No second risk engine, no second broker, no second strategy layer. The instrumentation
  attaches to `PaperBroker`, the project's existing execution boundary.
- No venue integration. The offline venue is a declared test double for producing partial
  fills, rejects and timeouts; it is not a paper provider and is never labelled as one.
- No tuning, no strategy selection, no holdout access, no live path, no new credential.

## Known ordering limitation

`WP-003P-05`'s clean-checkout reproduction is `NOT_PERFORMED`: `git worktree` at `HEAD`
does not contain the 003P code because the work is uncommitted. The substitute evidence is
that two independent rehearsals in this tree produce identical digests on every compared
artifact (`DIGESTS.json` vs `runs/run-2/DIGESTS.json`). The command to run after the user
commits is recorded in `evidence/CLEAN_CHECKOUT_REPRODUCTION.json`.
