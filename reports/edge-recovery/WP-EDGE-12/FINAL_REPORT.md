# WP-EDGE-12 — final report

**Closure state:** `FORWARD_CONTINUITY_BLOCKED`

> the mechanism that would remove the session dependence needs an administrator, and 26 instant(s) of the measured window produced no process

## 1. The one number this work package exists to change

WP-EDGE-04R measured why the forward lane loses triggers. RFC-EDGE-012 asks for the
continuity to be *demonstrated* rather than argued. What was demonstrated here, and what
was not, are different in kind and are kept apart below.

```
268 trigger instants in the measured window
   242 answered by a tick
   26 never answered by any process
        causes: {'HOST_DOWN': 1, 'NO_SESSION': 24, 'SILENT_UNATTRIBUTABLE': 1, 'SLEEP': 0}

200 slot-consuming tick(s) ran the pipeline
1 of 60 admissible forward days
```

The third line is the only one an admission criterion may read, and it is zero. Nothing in
this package moves it: only time and a host that is signed in do, which is why the closure
state is `FORWARD_CONTINUITY_BLOCKED` and not a readiness claim.

## 2. What was proved on the runtime

| property | where it was exercised | verdict |
| --- | --- | --- |
| `IDEMPOTENT_SLOT` | REHEARSED_ON_THE_RUNTIME | `PASS` |
| `SINGLE_INSTANCE` | REHEARSED_ON_THE_RUNTIME | `PASS` |
| `STALE_LEASE_RECLAIM` | REHEARSED_ON_THE_RUNTIME | `PASS` |
| `RESUME_AFTER_RESTART` | REHEARSED_ON_THE_RUNTIME | `PASS` |
| `RESUME_AFTER_ABSENT_SESSION` | OBSERVED_LIVE_AND_BOUNDED | `BOUNDED_NOT_REMOVED` |
| `INCOMPLETE_WRITE_SURVIVAL` | REHEARSED_ON_THE_RUNTIME | `PASS` |
| `LEDGER_RECONCILIATION` | REHEARSED_ON_THE_RUNTIME_AND_READ_LIVE | `PASS` |
| `TIMEOUT_HANDLING` | REHEARSED_ON_THE_RUNTIME_AND_READ_LIVE | `PASS` |
| `MISSED_TRIGGER_DETECTION` | READ_LIVE | `DETECTED` |

The rehearsal drove the **real observer** — the real ingest, the real store layout, the real
network — over an isolated copy of the store, which is what makes the isolated root a
property of the layout rather than a promise: a rehearsal that wrote into the live store
would be producing the evidence it is measuring.

## 3. What was not proved, and why

* **A real sign-in absence under the proposed trigger set.** Provoking one would end the
  session this work runs in. The property is `BOUNDED_NOT_REMOVED`, bounded by the logon
  trigger and by the measured recovery latency, not removed.
* **An S4U task actually running with no session.** The registration of *this definition*
  with `LogonType=S4U` was attempted and the host answered `Acceso denegado`; an
  administrator is the actor that can answer differently.
* **A Windows service or a runner on another host.** No authorised infrastructure was found,
  and creating a service needs a privilege this process does not hold (measured from its own
  token).
* **Linux.** The reading is portable by construction and has not been run there.
* **Attribution of an off-cadence launch.** The run log records the arguments a launch was
  invoked with, and an on-demand `schtasks /run` uses the same arguments as the scheduler.
  The operational log that separates them is disabled, which needs an administrator.

## 4. The mechanisms, priced

Selected: **`LOGON_TRIGGER`**. Available without new privileges: ['LOGON_TRIGGER', 'WITNESS_ACTION'].

| mechanism | verdict |
| --- | --- |
| `AUTHORISED_SERVICE_ACCOUNT` | `NO_ACCOUNT_DESIGNATED` |
| `INDEPENDENT_HOST_RUNNER` | `NO_AUTHORISED_INFRASTRUCTURE_FOUND` |
| `S4U_BARE` | `NEEDS_ELEVATION` |
| `S4U_PROPOSAL` | `NEEDS_ELEVATION` |
| `SYSTEM_PRINCIPAL` | `NEEDS_ELEVATION` |
| `WINDOWS_SERVICE` | `NOT_ATTEMPTED_NEEDS_ELEVATION` |

The two levers already present in the live registration were priced from the lane's own
log rather than from the settings: `StartWhenAvailable` is on and the log shows
254 launches with an off-phase minority, and the
`RestartOnFailure` policy produced no measured follow-up after a refused tick. A setting
that is present and recovers nothing is worth exactly as much as a mechanism that is
absent, and saying which one it is takes a measurement.

## 5. Storage: the lane is not the constraint

Ceiling 72810853 B against a declared 268435456 B budget; the store adds 0.006249 GiB over sixty days. Relocation: `NO_VOLUME_WITH_CAPACITY` — the only other volumes are a cloud mount
that reports the host's own capacity while holding none of it, and unmounted partitions.
The guard stays where it is: it refuses *before* any market request, so a full volume costs
slots and never produces a false observation.

## 6. Defects this pass found and closed

| # | defect | how it showed up | closed by |
| --- | --- | --- | --- |
| `DEF-EDGE12-1` | the dependency scan found its own identifier in this package's source, scripts and reports, and would have reported the dependency as **present** | the first gate run printed `PRESENT` over a tree that contains no such document | the scan excludes the searcher's own roots and reports them separately (see DEF-EDGE12-9 for the root it missed the first time) |
| `DEF-EDGE12-2` | the S4U probe registered the proposal **unchanged**, so the scheduler read the principal back as `Interactive`, and the probe would have called a mechanism viable that it had never exercised | the read-back carried `Interactive` while the record claimed an S4U attempt | the probe builds a real `LogonType=S4U` variant with the lane's action swapped for an inert one, counts the lines it moved, and requires an `S4U` read-back before any verdict other than blocked |
| `DEF-EDGE12-3` | the lease rehearsal wrote `renewed_at` in **milliseconds** into a record the lock compares in **seconds**, making every lease unreclaimable and reporting two implemented properties as failures | the concurrency step returned `ALREADY_OBSERVED` instead of `ALREADY_RUNNING` | the rehearsal pins the clock to slot boundaries, writes the lock in the units the lock reads, and re-derives the recovery arithmetic exactly |
| `DEF-EDGE12-4` | the definition reader tried UTF-16 first, and a UTF-8 file decodes as UTF-16 without raising: a definition that exists read as malformed | the regression that reads a definition in both encodings | the byte-order mark decides, and only a file without one falls back |
| `DEF-EDGE12-5` | the recorded-digest search compared each value against the needle and never looked at siblings, so a certificate whose path and digest sit on adjacent keys read as unreadable | the regression that puts the two keys side by side | each object is flattened before the search |
| `DEF-EDGE12-6` | a mobile volume was counted as a relocation target, so "is there a better volume?" answered yes to the volume the store already lives on | the storage reading contradicted WP-EDGE-04R's own verdict | the current volume is excluded by letter and flagged in the record |
| `DEF-EDGE12-7` | the timeout property was judged from the duration the tick **reports**, which under an injected clock is the wall clock minus the pinned clock: the first run printed 900.797 s for a call that took seconds, then negative numbers once the pin passed the wall clock, and called a working observer a failure | the rehearsal failed on `TIMEOUT_HANDLING` with `[-857.628, -1718.829, -2580.386]` | the rehearsal times each call with a stopwatch, keeps the reported value as a cross-check, and judges the property on the wall figures and the live log |
| `DEF-EDGE12-8` | the continuity matrix read a key the rehearsal no longer writes, so the rendering of the matrix crashed with `KeyError: 'lease'` after a successful rehearsal | the run wrote its evidence and then died before writing the matrix | the row reads `lease_status` and the rehearsal's own regression covers the matrix build |
| `DEF-EDGE12-9` | the scan's exclusion named the package's source, entry points and deliverables but **not its own regressions** — and this package's test module writes the identifier out in full as a fixture, so the next gate run reported the dependency `PRESENT` on the strength of its own test file, which is DEF-EDGE12-1 one artefact later | the gate re-run over the same tree flipped from `NOT_PRESENT_IN_TREE` to `PRESENT` after the tests were added, with the single hit being `tests/unit/research/test_edge12_continuity.py` | the four roots are declared once in `SEARCHER_ROOTS`, the tests are among them, and a regression asserts that another package's test file is still a real hit |

## 7. Acceptance criteria, each with the figure that answers it

The RFC states eighteen criteria and this table answers them in its own order. The
evidence column is the value the verdict was computed from, not a restatement of it:
where a row rests on the independent verifier it stays
`PENDIENTE_DE_VERIFICADOR` until that verifier has run, and where the RFC allows a
blocked dependency it reads `BLOQUEADO_DECLARADO` rather than being quietly dropped.

`{"BLOQUEADO_DECLARADO": 1, "SATISFECHO": 17}`

| criterion | requirement | verdict | evidence |
| --- | --- | --- | --- |
| `ACC-01` | Dependencias auditadas contra runtime real. | `SATISFECHO` | gate DEPENDENCY_GATE_PASS; entry points 6/6 answered --help, modules 9/9 importable, RFC-EDGE-011 NOT_PRESENT_IN_TREE, scheduler Ready |
| `ACC-02` | Mecanismo de ejecución seleccionado con evidencia. | `SATISFECHO` | selected LOGON_TRIGGER; S4U probe NEEDS_ELEVATION, available without new privileges ['LOGON_TRIGGER', 'WITNESS_ACTION'] |
| `ACC-03` | Ningún cambio privilegiado sin autorización. | `SATISFECHO` | applied to the live task: False; probe tasks left behind: none; preflight PREFLIGHT_PASS |
| `ACC-04` | No se almacenan nuevas credenciales. | `SATISFECHO` | no probe stored a credential (0 offender(s)); every probe record carries stored_a_password=false, and no definition here contains a <Password> element |
| `ACC-05` | Observador ejecutable sin sesión interactiva, o bloqueo declarado. | `BLOQUEADO_DECLARADO` | the mechanism that would remove the session dependence reads NEEDS_ELEVATION on this process's own attempt, so the dependence is bounded and not removed: selected LOGON_TRIGGER; blocked {'AUTHORISED_SERVICE_ACCOUNT': 'NO_ACCOUNT_DESIGNATED', 'INDEPENDENT_HOST_RUNNER': 'NO_AUTHORISED_INFRASTRUCTURE_FOUND', 'S4U_BARE': 'NEEDS_ELEVATION', 'S4U_PROPOSAL': 'NEEDS_ELEVATION', 'SYSTEM_PRINCIPAL': 'NEEDS_ELEVATION', 'WINDOWS_SERVICE': 'NOT_ATTEMPTED_NEEDS_ELEVATION'} |
| `ACC-06` | No existen ejecuciones simultáneas que corrompan el ledger. | `SATISFECHO` | SINGLE_INSTANCE PASS on the runtime; the slot ledger holds 199 row(s) over 199 unique key(s) |
| `ACC-07` | Los disparos perdidos tienen causa o clasificación UNATTRIBUTABLE. | `SATISFECHO` | 26 unanswered instant(s), every one classified: {'HOST_DOWN': 1, 'NO_SESSION': 24, 'SILENT_UNATTRIBUTABLE': 1, 'SLEEP': 0} |
| `ACC-08` | El guardián de disco permanece activo. | `SATISFECHO` | guard HEALTHY at 7.5352 GiB against the campaign's own thresholds; storage verification STORAGE_VERIFY_PASS |
| `ACC-09` | Existe capacidad de almacenamiento justificada para la observación. | `SATISFECHO` | ceiling 72810853 B of a declared 268435456 B budget; the store adds 0.006249 GiB over sixty days at the measured rate |
| `ACC-10` | Los snapshots se reproducen offline sin acceder a datos vivos. | `SATISFECHO` | the rehearsal read C:\Users\GVLLFR0035\Downloads\bot freebuff\data\forward\edge03 and wrote C:\Users\GVLLFR0035\Downloads\bot freebuff\data\forward\edge12\rehearsal; the verifier re-derived its figures from the published snapshots with 24 check(s) |
| `ACC-11` | Los días incompletos no se promocionan. | `SATISFECHO` | level three counts 1 day(s) of 60; an incomplete day is never promoted, it is left INCOMPLETE and reported in FORWARD_COVERAGE.json |
| `ACC-12` | Los datos backfilled no cuentan como forward prospectivo. | `SATISFECHO` | 228 dense day(s) whose bars arrived late are classified DENSE_BUT_BACKFILLED and counted as zero forward days; the rule is the lane's own prospective_days |
| `ACC-13` | Se mantienen los 60 días y el 90 %. | `SATISFECHO` | required days 60, coverage floor 0.9 (the campaign's declared values, unchanged by this package) |
| `ACC-14` | Los tests y sabotajes detectan defectos reales. | `SATISFECHO` | sabotage matrix 24/24 mutation(s) detected, 0 undetected, over 24 check(s) |
| `ACC-15` | El verificador es independiente del constructor. | `SATISFECHO` | this verifier imports nothing from trading_bot.research.edge12 and re-derives every figure it checks from the published JSON and the log snapshots |
| `ACC-16` | Los informes incluyen fallos, bloqueos y evidencia. | `SATISFECHO` | 4 open failure(s) recorded, every one with an id and a status; every deliverable present: True |
| `ACC-17` | order_sent=false y promotion=NONE. | `SATISFECHO` | every record this package wrote carries order_sent=false and promotion=NONE, including the HEALTHY storage reading and the operational window |
| `ACC-18` | El resultado operativo se separa del resultado económico. | `SATISFECHO` | the operational result is published on its own (26 unanswered instant(s), 1 admissible day(s)) and the inherited economic failure is kept apart from it: ['OPEN-EDGE12-1', 'OPEN-EDGE12-2', 'OPEN-EDGE12-3', 'OPEN-EDGE12-4'] |

## 8. Regressions and checks

```json
{
  "campaign": "RFC-EDGE-012",
  "collected_nothing": false,
  "generated_at_utc": "2026-10-16T06:23:18Z",
  "hypothetical": true,
  "lint": {
    "command": "C:\\Users\\GVLLFR0035\\Downloads\\bot freebuff\\.venv\\Scripts\\python.exe -m ruff check src/trading_bot/research/edge12/ scripts/edge12_verify.py scripts/edge12_reports.py scripts/edge12_tests.py tests/unit/research/test_edge12_continuity.py tests/unit/research/test_edge12_runner.py",
    "exit_code": 0,
    "passed": true,
    "reason": null,
    "tail": "All checks passed!"
  },
  "order_sent": false,
  "promotion": "NONE",
  "pytest": {
    "command": "C:\\Users\\GVLLFR0035\\Downloads\\bot freebuff\\.venv\\Scripts\\python.exe -m pytest -q tests/unit/research/test_edge12_continuity.py tests/unit/research/test_edge12_runner.py",
    "errors": null,
    "exit_code": 0,
    "failed": null,
    "passed": 60,
    "reason": null,
    "skipped": null,
    "tail": "............................................................             [100%]\n60 passed in 1.51s"
  },
  "read_only": "no network, no live state root, no live store, no scheduler; this step runs the package's own regressions and the lint over its own paths",
  "schema_version": "EDGE12_TEST_RUNS_V1",
  "selection": {
    "declared_in": "scripts/edge12_tests.py",
    "lint_paths": [
      "src/trading_bot/research/edge12/",
      "scripts/edge12_verify.py",
      "scripts/edge12_reports.py",
      "scripts/edge12_tests.py",
      "tests/unit/research/test_edge12_continuity.py",
      "tests/unit/research/test_edge12_runner.py"
    ],
    "test_modules": [
      "tests/unit/research/test_edge12_continuity.py",
      "tests/unit/research/test_edge12_runner.py"
    ],
    "why_narrow": "these are this package's own regressions and the lint that guards them; the rest of the tree carries other work packages' findings and their owners report them"
  },
  "verdict": "TESTS_PASS",
  "work_package": "WP-EDGE-12"
}
```

## 9. Open failures, with owners

`OPEN-EDGE12-1` UNREADABLE (unowned); `OPEN-EDGE12-2` BLOCKED_NEEDS_ELEVATION (an operator with administrator rights on this host); `OPEN-EDGE12-3` BLOCKED_NEEDS_CREDENTIALS (an operator who chooses to store a credential on the machine); `OPEN-EDGE12-4` INHERITED_AND_UNREPAIRED (the cost-barrier chain; not this work package)

## 10. Next action

an administrator registers the S4U variant of the proposed definition (the command is in OPERATOR_HANDOFF.md step 5 and the rollback is written in ROLLBACK.md), and enables the Task Scheduler operational log so the next silent trigger is attributable instead of SILENT_UNATTRIBUTABLE

> this package does not authorise PAPER or LIVE trading under any circumstance: order_sent is false and promotion is NONE in every record it produced

Research only: public market data, no credentials, no orders, no capital, no promotion.
