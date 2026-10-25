# RUN_REPORT — G-1 persistence of the kill switch

- **Run id:** `run-20261024T064739Z-G-1`
- **Contract:** [`docs/audit/G-1.md`](../../G-1.md)
- **Baseline:** `5238c05e2f11527606ec2afc89966dc1500a281d` (record commit of G-2)
- **Verified commit:** `9df2aa8f69e4ed76cd24dfab69a9b361d5e1fd32`
- **Branch:** `audit/mt0004-negative-controls` (not pushed, not merged)
- **Checkout tested:** `C:\Users\GVLLFR0035\Downloads\ff-wt-mt0004`
- **Verification input:** `git archive` export of `9df2aa8f`, not the working tree
- **Date:** 2026-10-24
- **Mode:** offline only. No live order, no PAPER run against a real feed, no
  deployment.

## 1. What was asked

Close G-1 — a stop must not be lost by restarting the process — without
redesigning the runtime, adding infrastructure, or touching G-3/G-4.

## 2. G1-00 — preflight, read-only

| # | Measurement | Result |
|---|---|---|
| P-1 | `git rev-parse --show-toplevel`, `--abbrev-ref HEAD`, `HEAD`, `status --porcelain` | `…/ff-wt-mt0004`, `audit/mt0004-negative-controls`, `5238c05e`, clean |
| P-2 | ancestry of `60455b46`, `ef7955dc`, `00671e62`, `f3b55a98`, `2e406560` | all ancestors of `HEAD` |
| P-3 | does `main` contain `60455b46`? | **No** (`git merge-base --is-ancestor` → 1) |
| P-4 | broker dispatch sites in the autonomous runtime | **one**, `runtime.py:1483` |
| P-5 | gate construction site | `runtime.py:353-356` (`HotStopGate(process_kill_switch(), run_dir)`) |
| P-6 | does the gate read the marker at construction? | **No** — `__post_init__` only sets paths and the lock |
| P-7 | run directory | `<repo>/<--run-root>/<--run-id>`; `--run-id` defaults to a UTC timestamp (`scripts/autonomous_paper.py:329-330`) |
| P-8 | the supervised path | `start_paper_lab.py` passes `--run-id run_id` to the paper child (`:346-361`), so a supervised restart **reuses** the directory |
| P-9 | dispatch before the runtime exists? | none: startup reconciliation restores state and never calls `execute_signal` (`reconciliation_v4.py`) |
| P-10 | existing marker write | `tmp` + `Path.replace`, **no fsync** (`app.py:1424-1428`) |

Baseline before any edit: `tests/unit/autonomous/test_decision_kill_switch.py`
→ 28 passed; `tests/unit/autonomous` → 339 passed;
`pytest test_hot_engage.py test_decision_kill_switch.py` → **1 failed, 54
passed** (defect G1-D-1, see §8).

## 3. Authority: where the stop is read, and where the order leaves

```
process start
  └─ scripts/autonomous_paper.py
       ├─ StartupReconcilerV4.reconcile()      # restores the book — no dispatch
       └─ AutonomousPaperRuntime.__init__      # runtime.py:353
            └─ HotStopGate.__post_init__       # hot_stop.py
                 └─ restore()                  # ★ marker adopted HERE
  └─ run_cycle → _evaluate_asset → _execute_paper
       └─ with order_boundary():               # runtime.py:1477
            └─ broker.execute_signal(...)      # runtime.py:1483 — the only dispatch
```

The first possible broker call is inside `run_cycle`, which cannot run before
the constructor returns. Restoring in `__post_init__` therefore covers every
construction path — the runtime, a script, a future entrypoint — without a
second wiring site that someone can forget. `runtime.py` was **not** modified.

## 4. What changed

| File | Change |
|---|---|
| `src/trading_bot/autonomous/hot_stop.py` | `restore()` + `_marker_presence()` (`os.lstat`, only `FileNotFoundError` = absent) + `_read_marker()` (returns the read fault instead of swallowing it) + `_ensure_marker()`; `engage()` persists; `EngageAck` gains `persisted`/`restored`; `write_control_file()` (temp + `fsync` + `os.replace` + best-effort directory `fsync`) |
| `src/trading_bot/app.py` | `kill-switch --engage` uses `write_control_file`; same stdout, same exit codes |
| `tests/unit/autonomous/test_kill_switch_persistence.py` | **new**, 20 tests |
| `tests/unit/autonomous/test_hot_engage.py` | G1-D-1 isolation fix + one test pinning the default gate wiring |
| `tests/unit/autonomous/test_decision_kill_switch.py` | docstring of the former gap test only; **assertion lines byte-identical** (verifier V-2) |
| `scripts/audit/g1_mutants.py` | new, 8 mutants |
| `scripts/audit/g1_restart_probe.py` | new, the cross-process runtime probe |
| `docs/audit/G-1.md` | contract |
| `docs/audit/AUDIT_BACKLOG.yaml`, `docs/audit/runtime_authority_map.md` | record |

## 5. Tests actually executed

All of these ran inside the export of `9df2aa8f` (except the audit guard, which
needs `.git`; it ran in the checkout V-0 proved clean and V-11 proved identical
for the sources).

| Suite | Result |
|---|---|
| `tests/unit/autonomous/test_kill_switch_persistence.py` | **20 passed** |
| `test_hot_engage.py` then `test_decision_kill_switch.py` | **41 passed** |
| `test_decision_kill_switch.py` then `test_hot_engage.py` | **41 passed** |
| `tests/unit/test_app_cli_contract.py` | **15 passed** |
| `tests/unit/autonomous` (regression) | **360 passed** |
| `tests/unit/test_audit_contracts_tracked.py` | **8 passed** |
| **total** | **485 test results, every run exit 0** |

The focal file is counted twice — once alone, once inside the regression run —
because the verifier records each invocation's own exit code. 485 is results,
not distinct tests.

Exact invocations and the observed output: [`COMMANDS.md`](COMMANDS.md).

Tooling:

- `ruff check` on every changed Python file → **clean**.
- `mypy src/trading_bot/autonomous/hot_stop.py src/trading_bot/app.py` → **Success**.
- `ruff format --check` on the changed files → clean, except
  `tests/unit/autonomous/test_decision_kill_switch.py`, whose drift at line 165
  **already exists at HEAD** (`git show HEAD:… | ruff format --check -` → 1).
  It was left untouched: it is outside this change.
- `ruff check .` → **180 pre-existing findings**, none in a file this run
  touched (`scripts/rfc049*`, `research/edge0*`, `reports/ai-bots/**`, …). The
  number is higher than G-2's 34 because that run reported a narrower
  invocation; this report states the command it ran.

## 6. Mutation matrix — 8/8 killed

`scripts/audit/g1_mutants.py --rev 9df2aa8f` → baseline green, every mutant
killed. Full matrix in [`mutants.json`](mutants.json).

| Mutant | Property removed | Killed by |
|---|---|---|
| M1 | no boot restore | `test_a_marker_left_by_a_previous_process_engages_at_construction` |
| M2 | unreadable path fails open at boot | `test_an_unreadable_control_path_fails_closed` |
| M3 | every `lstat` error treated as absence | `test_an_unreadable_control_path_fails_closed` |
| M4 | `engage` never writes the marker | `test_engage_persists_the_marker_for_the_next_process` |
| M5 | failed replace rewrites in place | `test_a_failed_replace_leaves_the_previous_marker_intact` |
| M6 | empty marker = permission to trade | `test_an_empty_marker_is_still_a_stop` |
| M7 | restore blocks the boundary but not rule 0 | `test_a_marker_left_by_a_previous_process_engages_at_construction` |
| M8 | restored stop logged as an ordinary engage | `test_restore_is_recorded_as_a_restored_event` |

No mutant survived. Unlike G-2's M1, none had to be re-specified: the anchors
target the property (presence, persistence, arming), not a redundant line.

## 7. Cross-process trace

[`cross_process_trace.json`](cross_process_trace.json), produced by
[`cross_process_trace.py`](cross_process_trace.py):

| Process | Action | Result |
|---|---|---|
| 1 | `python -m trading_bot.app kill-switch --run-dir A --engage` | exit 0, `{"status":"REQUESTED","enforced":false}` |
| 2 | `python scripts/audit/g1_restart_probe.py --run-dir A` | `engaged_before_first_cycle=true`, `restored=true`, `broker_calls=0`, `orders=0`, risk `PASS` |
| 2′ | same probe over a marker-free sibling | `engaged=false`, `broker_calls=1`, `orders=1` |
| — | audit event | `restored`, actor `boot_restore:<path>`, reason `operator: trace` |

The control in row 2′ is what makes row 2 evidence: without it a broken probe
would look identical to a working stop.

## 8. What the verifier re-derived

[`verify_g1.py`](verify_g1.py) → [`verification.json`](verification.json):
**13/13, `VERIFIED_SCOPED`**, `PROCEDURALLY_SEPARATED` (same author).

It does not import the test suite. It checks, from the export: scope (V-1),
unchanged assertions in the gap test (V-2), `restore()` called from
`__post_init__` (V-3, AST), no audit read in the state path (V-4, AST), the
single guarded dispatch (V-5, AST), export == commit (V-11), a fresh
interpreter adopting the marker (V-6), the CLI + runtime as two processes
(V-7), `--disarm` (V-8), all suites (V-9), the mutants (V-10), and the artefact
hashes (V-12).

### Defects found, and how each was handled

| Id | Finding | Resolution |
|---|---|---|
| G1-D-1 | G-2's suite was order dependent: `test_a_running_runtime_engages_between_cycles_without_restart` built its gate over `process_kill_switch()` and engaged the process-wide authority, so `test_decision_kill_switch.py` failed when run after it (`1 failed, 54 passed` at baseline). The full suite was green only because of collection order. | Fixed by injecting a fresh switch, plus a new test that pins the default wiring **without** engaging it. Both orders now pass (41/41 each). |
| G1-D-2 | The CLI's marker write had no `fsync`, so its own help text ("durably on disk") was not backed by a syscall. | `write_control_file` flushes, fsyncs, renames atomically, and fsyncs the directory where the platform allows it. |
| G1-D-3 | `decision.py:process_kill_switch()` says the state "is deliberately not persisted: gap G-1". The class is still stateless, but the sentence now reads as a contradiction. | **Not edited** (forbidden path). Recorded here and in G-1.md §10; the correction lives in the map and the backlog. |

## 9. What was NOT verified

- **A new run directory is not blocked.** `scripts/autonomous_paper.py` defaults
  `--run-id` to a timestamp, so a bare restart is a new scope and boots
  operational. This is a contract limit (G-1.md §4.6), pinned by
  `test_a_new_run_dir_is_outside_the_persisted_scope_this_is_the_documented_limit`.
  No global latch exists and none is claimed.
- **The supervisor was not executed end to end.** P-8 shows it passes
  `--run-id`; the cross-process probe exercises the resulting restart shape, not
  the supervisor binary.
- **Power-loss durability is not claimed.** The rename is atomic; the directory
  `fsync` is skipped on Windows because the platform has no portable directory
  handle for it.
- **G-3** (live paths that never reach `DecisionEngine`) and **G-4**
  (`paper_cycle.py` has its own broker call, `paper_cycle.py:510`) are
  untouched. `D-6` (a legacy test importing `REPO_ROOT/src`) is untouched.
- **PAPER against a real feed and LIVE** were not run. No credentials, no
  orders, no deployment.
- **The filesystem permission on `run_dir`** is the authorisation boundary for
  deleting the marker, exactly as it already is for `STOP`. This is fail-safe,
  not authentication.

## 10. Artefacts

`G-1.md` · `RUN_REPORT.md` · `RUN_REPORT.json` · `FINAL_REPORT.md` ·
`COMMITS.md` · `COMMANDS.md` · `verification.json` · `mutants.json` ·
`cross_process_trace.py` · `cross_process_trace.json` · `verify_g1.py`. SHA-256 of every artefact is in
`verification.json` → `V-12.evidence.artifacts` (the verifier hashes the files
present when it runs; `verification.json` and the verifier itself are excluded
for the obvious self-reference).
