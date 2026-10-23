# FINAL_REPORT — G-2

- **Run:** `run-20261023T201915Z-G-2`
- **Verified commit:** `00671e62`
- **Contract:** [`docs/audit/G-2.md`](../../G-2.md)
- **Closing state:** **`G2_IMPLEMENTED_VERIFIED_SCOPED`**
- **`PRODUCTION_READY` / `CERTIFIED`: not claimed.** The only path measured is
  offline and adversarial; no feed, no PAPER campaign, no live order.

## Verdict by dimension

| Dimension | Verdict | Basis |
|---|---|---|
| **SPEC** | `COMPLETE` | `docs/audit/G-2.md` freezes REQ-G2-01…07, ACC-G2-01…12, exact scope and stop conditions **before** the code commit. |
| **IMPLEMENTATION** | `DONE` | 1 new module, 2 edited modules, 1 new harness, 1 new suite. `V-1`: 5/5 changed files inside `allowed_paths`, 0 protected files touched. |
| **TESTS** | `PASS` | 12 new + 15 CLI contract = 27 focal; 362 with the regression set; 7/7 mutants killed. |
| **RUNTIME_REACHABILITY** | `DEMONSTRATED` | `V-2`: the only `execute_signal` in the runtime is lexically inside `order_boundary` (1/1). `V-3`: engage and dispatch share one lock, released in `finally`. |
| **OFFLINE_EXECUTION** | `PASS` | `V-9` / `offline_trace.json`: `operational → engaged → NO_ORDER`, broker counter frozen at 1 across three cycles on one runtime object. |
| **PAPER** | `NOT_RUN` | No campaign against a real feed. Deliberately out of scope for a stop mechanism. |
| **LIVE** | `NOT_RUN` | No live order, no live path measurement. G-3 remains open. |
| **INDEPENDENT_VERIFICATION** | `VERIFIED_SCOPED` | `V-1…V-10`, 10/10, exit 0, from a fresh export of `00671e62`. Same author, separate artefact: **procedurally separated**, not organisationally independent. |
| **FALSE_SUCCESS** | **0 known** | The CLI cannot report enforcement it does not have (`enforced: false`); the gate cannot report an ACK while a dispatch is in flight (tested); the audit cannot silently drop a transition (fsync, `audited` flag). |

## Acceptance criteria, once more

| ACC | Result | Where |
|---|---|---|
| G2-01 hot engage without restart | PASS | `test_a_running_runtime_engages_between_cycles_without_restart`, V-4 |
| G2-02 risk PASS, no broker call | PASS | `test_the_boundary_blocks_even_when_the_engine_always_orders`, V-2 |
| G2-03 repeated engage, no rearm | PASS | `test_engage_is_idempotent_and_audited`, V-5 |
| G2-04 race with an in-flight dispatch | PASS | `test_engage_waits_for_the_in_flight_dispatch`, V-3 |
| G2-05 fail closed | PASS | `test_unreadable_control_path_engages`, `test_a_broken_switch_still_leaves_the_gate_closed`, V-6 |
| G2-06 malformed payload cannot preempt | PASS (inherited) | MT-0004-R1's suite, unchanged and still green |
| G2-07 disarm refused | PASS | CLI `--disarm` exit 2; delete-file test |
| G2-08 subprocess target | PASS | both the new suite and the harness assert `TEST_TARGET == RUNTIME_TARGET` |
| G2-09 mutants | PASS | 7/7, `mutants.json` |
| G2-10 focal + regression + lint + types | PASS | 27 focal, 362 regression, ruff/mypy clean on changed files |
| G2-11 offline trace | PASS | V-9 |
| G2-12 zero out-of-scope changes | PASS | V-1 |

## The one number that matters

With the gate engaged and a **hostile** decision engine still returning
`TRADE_PAPER`, `broker.calls` stays at 1 — the call made before the stop. The
order is refused at the dispatch boundary, not at the decision, which is why
this survives a future regression in `DecisionEngine`.

## Open, unchanged

| Gap | State after this run |
|---|---|
| **G-1** persistence | Open. Engaging is memory-only; a restart boots `NORMAL` unless the environment token says otherwise. |
| **G-3** live | Open and unmeasured. `execution/live_gate.py` still checks a config boolean, not the runtime state. |
| **G-4** `paper_cycle` | Open. `trading-bot run --demo` bypasses both rule 0 and the gate. Explicitly **not** claimed as protected. |
| **D-6** inherited subprocess path | Open, untouched. The new suite avoids the defect (derives `src` from the imported module). |

## What a reader should distrust

1. **Independence.** Same author. `verify_g2.py` is a second artefact, not a
   second person.
2. **Coverage.** One entrypoint. Two reachable paths (demo loop, live) remain
   outside the guarantee by construction, and the contract says so.
3. **The channel's authority model.** The filesystem permission on `run_dir` is
   the authorisation boundary — the same one `STOP` already uses. It is a
   fail-safe direction (only stop, never trade), but it is not authentication.
4. **The lock's cost.** `engage` blocks for up to `boundary_timeout_seconds`
   (default 30 s) if a broker call is slow; on timeout it engages anyway and
   records `lock_timeout`. That path is implemented and unit-tested but was not
   exercised against a real broker.

## Reproduce the verdict

```bash
python reports/multiagent-audit/tools/verify_g2.py --rev 00671e62 \
    --json docs/audit/runs/run-20261023T201915Z-G-2/verification.json
# 10/10 — VERIFIED_SCOPED (PROCEDURALLY_SEPARATED)
```
