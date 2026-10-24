# FINAL_REPORT — G-1

**Verdict:** `G1_IMPLEMENTED_VERIFIED_SCOPED`

A stop written to a run directory is adopted **before the constructor returns**,
so a restart over that directory cannot place an order. The claim is scoped to
the run directory, and the scope is not a footnote: it is a contract clause and
a test.

## Dimensions

| Dimension | Result | Basis |
|---|---|---|
| **SPEC** | PASS | `docs/audit/G-1.md`, gate G1-01 passed against the tree (not against the handoff) |
| **IMPLEMENTATION** | PASS | `HotStopGate.restore()` in `__post_init__`; `engage` persists atomically; `write_control_file` shared by the gate and the CLI |
| **TESTS** | PASS | 19 new tests; 483 test results across six runs, all exit 0; both collection orders of the G-2 suites |
| **RUNTIME_REACHABILITY** | PASS | one dispatch site (`runtime.py:1483`) inside `order_boundary`; the gate is constructed at `runtime.py:353`; no dispatch can precede it |
| **OFFLINE_EXECUTION** | PASS | two operating-system processes: CLI writes, probe boots, broker counter stays 0; marker-free control orders once |
| **PAPER** | NOT RUN | no feed, no credentials, by design |
| **LIVE** | NOT RUN | no order, no deployment, by design |
| **INDEPENDENT_VERIFICATION** | `PROCEDURALLY_SEPARATED` | `verify_g1.py` is a separate artefact that re-derives the properties from an export; the same author wrote it |
| **FALSE_SUCCESS** | 0 | see below |

## Why `FALSE_SUCCESS = 0`

Five specific ways this task could have lied, and what closes each:

1. **A gate that was installed but never reached.** The runtime's only
   `execute_signal` is inside `order_boundary`, and the verifier re-derives that
   from the AST (V-5). The gate is constructed in `AutonomousPaperRuntime.__init__`;
   nothing dispatches before it (P-9).
2. **A restart that only re-instantiated a Python object.** The required proof is
   two OS processes (V-7): `python -m trading_bot.app kill-switch` writes, a new
   interpreter boots the real runtime over that directory. The broker counter is
   read from that child, not from the test's object graph.
3. **A blocked order that was really rule 0.** The probe injects a hostile
   decision engine that returns `TRADE_PAPER` unconditionally; the block can only
   come from the dispatch boundary. The same child reports `risk_verdict=PASS`,
   so it is not a risk veto either.
4. **A test that passes because the fixture never orders.** Every blocked
   assertion is paired with a sibling run directory without a marker that really
   reaches the broker (`broker_calls=1`, `orders_created=1`).
5. **A pass that hides a failure.** The verifier's `V-9` records the exit code of
   every suite; `V-10` requires 8/8 mutants; `V-12` hashes the artefacts. The
   tooling section of `RUN_REPORT.md` states the repo-wide `ruff` count and the
   one file whose pre-existing format drift was left alone.

## What an auditor can re-run

```bash
cd C:/Users/GVLLFR0035/Downloads/ff-wt-mt0004
uv run --frozen python docs/audit/runs/run-20261024T064739Z-G-1/verify_g1.py \
    --rev 0bcc100c --json /tmp/verification.json
```

Expected: 13/13, exit 0. The verifier exports the commit, asserts the export is
byte-identical for the two source files (line endings normalised), and runs
every suite plus the mutation matrix inside that export.

```bash
uv run --frozen python scripts/audit/g1_mutants.py --rev 0bcc100c
uv run --frozen python docs/audit/runs/run-20261024T064739Z-G-1/cross_process_trace.py
```

## Paths touched

`src/trading_bot/autonomous/hot_stop.py`, `src/trading_bot/app.py`,
`tests/unit/autonomous/test_kill_switch_persistence.py` (new),
`tests/unit/autonomous/test_hot_engage.py`,
`tests/unit/autonomous/test_decision_kill_switch.py` (docstring only),
`scripts/audit/g1_mutants.py` (new),
`scripts/audit/g1_restart_probe.py` (new), plus the contract, backlog, authority
map and this run directory. `runtime.py` and `decision.py` were **not** touched.

## The limit, stated where an auditor will see it

Persistence is per `run_dir`. `scripts/autonomous_paper.py` defaults `--run-id`
to a timestamp, so a bare restart creates a new directory and boots operational.
The supervised path passes a stable `--run-id` and is therefore covered. A
global stop was **not** implemented: it could not be cleared without a disarm
path, and `--disarm` is refused by contract. The bypass is pinned by
`test_a_new_run_dir_is_outside_the_persisted_scope_this_is_the_documented_limit`
so that improving it later is a deliberate change, not a silent regression of
the claim.

## Gaps, by name

| Gap | State after this run |
|---|---|
| **G-1** | Closed for the autonomous runtime, scoped to the run directory. |
| **G-2** | Unchanged; re-verified in both collection orders. |
| **G-3** | Open. The live path (`place-order`, `--auto-trade`) was not measured. |
| **G-4** | Open. `paper/paper_cycle.py:510` still calls `execute_signal` without the gate. |
| **D-6** | Open. A legacy test still imports `REPO_ROOT/src`; not touched. |

## Defects found in this run

`G1-D-1` — G-2's suite was order dependent (one test engaged the process-wide
authority; `test_decision_kill_switch.py` failed if run after it). Fixed by
injecting a fresh switch, plus a new test that pins the default wiring without
engaging it. `G1-D-2` — the CLI marker write lacked `fsync`; now durable.
`G1-D-3` — `decision.py`'s docstring still describes G-1 as open; forbidden
path, recorded rather than silently edited.
