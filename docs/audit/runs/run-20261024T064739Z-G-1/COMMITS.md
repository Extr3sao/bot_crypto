# COMMITS — G-1

Branch `audit/mt0004-negative-controls`, cut from G-2's record commit. Nothing
pushed, nothing merged.

| Order | Commit | What it contains | Verified? |
|---|---|---|---|
| 1 | `453d17ac` | `docs/audit/G-1.md` — the contract, frozen before code | n/a (specification) |
| 2 | `0bcc100c` | implementation + tests + mutation harness + probe | **yes** — this is the commit `verify_g1.py` reads |
| 3 | the commit that introduced this file | run reports, mutant matrix, cross-process trace, verifier, `verification.json` | no — documentation over the verified commit |
| 4 | the commit that updates the backlog and the authority map | record | no |
| 5 | the commit that adds `COMMANDS.md` and refreshes the artefact hashes | exact invocations, for an auditor who wants the command lines rather than the prose | no |

A file cannot contain the hash of the commit that adds it. For the last three:

```bash
git log -1 --format=%H -- docs/audit/runs/run-20261024T064739Z-G-1/RUN_REPORT.md
git log -1 --format=%H -- docs/audit/AUDIT_BACKLOG.yaml
git log -1 --format=%H -- docs/audit/runs/run-20261024T064739Z-G-1/COMMANDS.md
```

## What each commit does, and why in that order

1. **Contract first.** `G-1.md` fixes the authority (the marker), the restore
   point (gate construction), the fail-closed rule and the scope limit *before*
   any implementation exists, so the tests can be judged against a claim that
   did not move afterwards.
2. **Implementation.** `hot_stop.py` gains `restore`, the marker-presence test,
   `write_control_file` and `persist` on `engage`; `app.py` reuses the writer.
   `runtime.py` and `decision.py` are untouched on purpose: restoring in the
   gate's constructor covers every construction path without a second wiring
   site.
3. **Evidence.** The reports and the artefacts they reference. This commit does
   not change behaviour; it records the numbers and the trace.
4. **Record.** Backlog entry `G-1`, the corrected G-1 row in
   `runtime_authority_map.md`, and `next_ready` recomputed (G-3 recommended,
   G-1 and G-2 closed for the autonomous path).

## Diff shape of the verified commit

```
 src/trading_bot/autonomous/hot_stop.py          | +203 -25
 src/trading_bot/app.py                          |   +9  -6
 tests/unit/autonomous/test_kill_switch_persistence.py | new (19 tests)
 tests/unit/autonomous/test_hot_engage.py        |  +31
 tests/unit/autonomous/test_decision_kill_switch.py | docstring only
 scripts/audit/g1_mutants.py                     | new (8 mutants)
 scripts/audit/g1_restart_probe.py               | new (cross-process probe)
```

`verify_g1.py` V-1 re-checks that every changed path is inside the contract's
`allowed_paths` and outside its `protected_paths`; V-2 proves that the only
change in `test_decision_kill_switch.py` is its docstring (the assertion lines
are byte-identical to the baseline).
