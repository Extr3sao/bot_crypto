# ST-6 — versioning and independent end-of-period replay

Generated 2026-10-08T22:13Z from the baseline `9660afab9003001d3a8130b9679c066071548421` (branch
`main`, verified with `git rev-parse HEAD`), now at
`14514d66dbcdd4236a9d18dcbc79c1d90d9a14a1` after two commits of this work. No new campaign, no change
to the declared period, no change to COST_MODEL_V3, no order, no credential, no touch of
CAP-004B/CAP-004D.

## 01 — Baseline

`HEAD` is the communicated `9660afa` — `feat(research): open the ST-6 forward cost regime period (14
declared days)`. `origin/main` is `5e6f9632e8d9c15dabd60ea92ac68f350ca28c9d` and the local branch is
205 commits ahead of it, so this work is a local commit only: nothing is pushed.

| what | state at the baseline |
| --- | --- |
| scheduler task | `TradingAgentic-ST6-Forward`, installed and enabled, repetition `PT15M`, action `python.exe … st6_forward_regime.py --due --scheduled` in the repository directory |
| entrypoint of `--due` | `scripts/st6_forward_regime.py --due --scheduled` (unattended) / `--due` (manual) |
| code pending a commit | the autonomous tick layer, the health checker, the scheduler verifier and the scheduler tests were complete on disk and uncommitted |
| period | `2026-10-08T16:21:20Z` → `2026-10-22T16:21:20Z`; 14 days, 6 slots/day, plan 84 windows |
| windows collected | 2 — `20261008T162202Z` (`2026-10-08#4`) and `20261008T200323Z` (`2026-10-08#5`), both complete, 0 orders, 0 credentials |
| static artefacts | `ST6_SCHEDULER_REPORT.{json,md}`, `ST6_SCHEDULER_VERIFICATION.json`, `ST6_TASK_DEFINITION.xml` present and uncommitted |
| dynamic artefacts | `ST6_RUNS.jsonl`, `ST6_HEALTH.jsonl`, `ST6_HEALTH_STATUS.json` rewritten by every tick; `ST6_WINDOWS.jsonl`, `ST6_OBSERVATIONS.jsonl`, `ST6_REGIME_COVERAGE.json`, `ST6_MODEL_DRIFT.json`, `ST6_FORWARD_REGIME_REPORT.*` rewritten on each collection |
| raw evidence | 2 gzipped snapshots, both re-hashed and reproducing the hash recorded in the window index |
| ECO-1 | OPEN — the declared coverage rule is far from met (2 of 84 planned windows) |
| other threads' paths | listed below, deliberately not staged |

Paths under modification by other threads of the repository, **not staged, not touched**:

```text
FINAL_REPORT.md
RUN_REPORT.json
RUN_REPORT.md
docs/source_registry.md
evidence/real_decisions/evaluations.jsonl
evidence/real_decisions/outcomes.jsonl
scripts/cap004c_verify.py
PAPER_DATA_24H_REPORT.json
PAPER_DATA_24H_REPORT.md
data/rfc035e/…
scripts/rfc035*
scripts/source_candidate_experiment.py
src/trading_bot/research/experimental/…
docs/research/experiment_specs/…
docs/research/runtime_reconciliation/…
docs/research/work_packages/…
tests/unit/research/test_experimental_candidates_pit.py
tests/unit/research/test_rfc035*.py
```

## 02 — What was versioned, and how it was separated

Three kinds of artefact were separated **before** anything was staged:

| class | members | treatment |
| --- | --- | --- |
| `IMMUTABLE_EVIDENCE` | `data/st6/raw/*.json.gz` | re-hashed, committed; never rewritten |
| `VERSIONED_IMPLEMENTATION` | the six programs, the scheduler test suite, `ST6_TASK_DEFINITION.xml` | committed |
| `LIVE_RUNTIME_STATE` | `ST6_RUNS.jsonl`, `ST6_HEALTH.jsonl`, `ST6_HEALTH_STATUS.json`, `ST6_WINDOWS.jsonl`, `ST6_OBSERVATIONS.jsonl`, `ST6_MISSED_WINDOWS.jsonl`, `ST6_PERIOD_CLOSURE.json`, `ST6_REGIME_COVERAGE.json`, `ST6_MODEL_DRIFT.json`, `ST6_FORWARD_REGIME_REPORT.{json,md}`, `ST6_SCHEDULER_REPORT.{json,md}`, `ST6_SCHEDULER_VERIFICATION.json`, `ST6_INDEPENDENT_VERIFICATION.{json,md}`, `ST6_PERIOD.json` | **snapshotted and hashed, not committed** |
| `TRANSIENT_COORDINATION` | `data/st6/scheduler_lock/CAMPAIGN_LOCK.json` | hashed for completeness, never copied, never committed |

The window index is therefore **not** committed: it is campaign state that the next collection
rewrites, and the current one is not the last one this period will have. Its exact bytes at the
snapshot instant are inside the snapshot, with their sha256.

Four dated snapshots were produced by `scripts/st6_state_snapshot.py`:

* `data/st6/snapshots/ST6_LIVE_STATE_20261008T215219Z.json` — the one the independent verification
  read at the first commit;
* `data/st6/snapshots/ST6_LIVE_STATE_20261008T215222Z.json` — the picture taken after that
  verification;
* `data/st6/snapshots/ST6_LIVE_STATE_20261008T221134Z.json` — the picture taken at `14514d6`;
* `data/st6/snapshots/ST6_LIVE_STATE_20261008T222000Z.json` — the picture taken once the code had
  stopped moving, and the one `--check` re-verifies.

Each snapshot copies every live file under `data/st6/snapshots/<id>/` and records, for each one, its
sha256, size, mtime and **git blob hash**, plus a re-hash of every raw window snapshot against the
hash in the index. `python scripts/st6_state_snapshot.py --check` → **PASS (17 checks, 0 live files
moved)** when it was taken.

The check used to compare every live file with the hash recorded at snapshot time, so it reported
`FAIL` as soon as the tick rewrote its own state — which it does every fifteen minutes, by design
(five live files had already moved by 22:00Z). It now answers two separate questions: whether the
snapshot still says what it said (its manifest, its copied files, the raw evidence — a failure), and
whether the campaign has moved on since (drift — named, hashed and counted, never a failure). This
is what makes it usable for the whole period instead of only for the minute after it ran.

## 03 — The commits

`git add` was called with explicit paths only — never `git add -A`, never `git add .`, never a
directory that could carry another agent's file.

| commit | subject | paths | role |
| --- | --- | --- | --- |
| `8a7afd2` | make the ST-6 close terminal, idempotent and independently replayed | 47 | the implementation, the reports and the first two snapshots |
| `14514d6` | record who invoked the tick and tell snapshot drift from corruption | 6 | the correction below |
| the commit that carries this report | this report, the regenerated replay report, the verification and the third snapshot | 9 | reports and the newest snapshot |

The identity of the content staged (git blob SHA-1, `git hash-object` of the exact bytes, and what
`HEAD` actually holds — they agree on every row) is:

| path | git blob sha1 at `14514d6` | bytes |
| --- | --- | --- |
| `scripts/st6_forward_regime.py` | `142287f750dbb30f4c0e7cb26e12ca88785839b5` | 122969 |
| `scripts/st6_health_check.py` | `2abb44bf0228fc5b1bfc8c6c8fbf6be48adf5eba` | 20512 |
| `scripts/st6_scheduler_verify.py` | `8eceb9b2ead559fad37f4c29178bb5332f119484` | 29401 |
| `scripts/st6_state_snapshot.py` | `96e065cfb3d5869c1aa12af364232dcb264f314b` | 15435 |
| `scripts/st6_close_replay.py` | `c22204ab89dcfd7b1b8e329cead91533d808bb43` | 61363 |
| `scripts/st6_close_verify.py` | `a1e473d6f5db933ed60b61d3e6b90f15fb744c8a` | 46892 |
| `tests/unit/research/test_st6_scheduler.py` | `20a406d2797f4ef9d9c578c0a6eba913f3ad35d4` | 33335 |
| `data/st6/ST6_TASK_DEFINITION.xml` | `6c13e0e75568feaca1329a226116eed2b18d58ac` | 3308 |

Every row of that table is verified against `HEAD` (blob in the tree equals blob of the bytes on
disk), and `ST6_VERSIONING_REPORT.json` carries the same table with the sha256 of every file as well,
including the reports, the raw evidence and the three snapshots.

The commit id cannot appear inside the commit that carries this report; it is reported in the
mission's final response (`CURRENT_HEAD`).

## 04 — Scheduler lifecycle at and after the close

* **Before the close** the task wakes every fifteen minutes. The tick takes the shared lease,
  consults the local slot state *first*, and makes **no market request** when the slot already has a
  window. Verified live: 1515/1515 checks, all live tests PASS.
* **At the instant of the close** (`now >= ends_at_utc`, inclusive) the ended branch returns
  `EXIT_PERIOD_ENDED` *before* any statement that could collect a window. That dominance is
  re-derived from the tick's own syntax tree by `closure_guard_structure`, and it is replayed here.
  The consolidation is written **once**: metrics consolidated, missed windows named, verifiers
  delegated, terminal state declared.
* **The terminal transition** is new in this commit: the period disables **its own** task
  (`schtasks /change /tn <own task> /disable`), without elevation, without touching any other
  program's task, and records the outcome inside the consolidation. A failure is recorded rather
  than raised, with a note telling the operator to disable the task by hand; the tick still refuses
  to sample.
* **After the close** every later tick is an **idempotent no-op**: no sample, no artefact rewrite,
  no run event. The replay proves it — the consolidation stays byte-identical across repeated
  executions and across a simulated host restart, and a fresh process reproduces it exactly. So the
  task can neither keep making requests nor keep creating logs even if it is never disabled; its own
  `Duration` (`P30D`) also expires it.

## 05 — Verification evidence

| verification | result |
| --- | --- |
| scheduler verifier — live execution through the scheduler, lease, `--due` idempotency, refusal path, closure guard, run log, missed accounting, order-path scan | **PASS 1710/1710**, 0 mismatches, FALSE_SUCCESS 0 |
| isolated close replay — 10 scenarios, injected UTC clock, isolated sandbox, market and scheduler forbidden | **PASS 10/10**, 0 FAIL, real state unmoved, 0 real requests, 0 real scheduler calls |
| independent close verification — a different program from the builder *and* from the harness | **PASS 19/19**, 0 mismatches, FALSE_SUCCESS 0, verdict `ST6_CLOSE_VERIFIED` |
| negative fixtures — duplication, tampered hash, missing evidence, order path, foreign closure, supported-over-incomplete-coverage, hidden drift, plan past its end, moved implementation hash, misclassified artefact, hidden failed check, unexplained real change | **PASS 17/17** corruptions detected |
| determinism — the harness re-run from the same seed state | close sha256 `8610cf46337fb400…` reproduced exactly, byte for byte; every scenario verdict equal. Inside the sandbox the tick records the code identity as a constant (`REPLAY_SANDBOX_NOT_A_COMMIT`), so this proof does not depend on the commit hash — the real head is recorded at the top level of the report |
| unit suites | **46 passed**, 0 failed (`test_st6_scheduler.py` 24, `test_st6_forward_regime.py` 22); three of them added with this work |
| live-state snapshot | `--check` PASS (17 checks, 0 live files moved) right after `ST6_LIVE_STATE_20261008T222000Z` was taken; every raw hash reproduces |
| a stale snapshot is refused | when the three programs were edited after `ST6_LIVE_STATE_20261008T221134Z` had been taken, the independent verifier **failed** with `the implementation file scripts/st6_state_snapshot.py changed after the snapshot` (18/19, FALSE_SUCCESS 1). The snapshot was retaken in the right order and the same verification then passed 19/19. The check is not decorative. |
| live health after the correction | `WARNING`; run events 140 by provenance `{MANUAL: 3, SCHEDULED: 8, UNRECORDED: 129}`; failure streak 1 computed over non-manual events only (threshold 3); heartbeat basis `LAST_NON_MANUAL_RUN`; 2 windows, 0 unaccounted slots, 0 missed |

The replayed close produced `INSUFFICIENT_REGIME_COVERAGE` (2 of 84 planned windows, 82 missed) with
the terminal state `PERIOD_CLOSED_NO_FURTHER_COLLECTION`, the drift preserved beside the outcome
(1 breach, none lost against the live monitor), 0 orders and 0 credentials.

## 06 — Declared deviations and open defects

1. **`BOUNDARY-SLOT-DUE-RULE`** — the due rule is not bounded by the 84-window plan: a tick inside
   the partial slot the period closes in (2026-10-22, 16:00–16:21:20Z) would attempt an 85th,
   out-of-plan window. Measured in the replay; minimal correction proposed; **not applied**, because
   changing the collection rule mid-period would alter the campaign.
2. **`EXTENSION-FLAG-INERT`** — the declared `--authorize-extension` policy is inert in both
   directions: it cannot extend the period, and during the open period it suppresses collection.
   Measured, declared, not patched.
3. **`CORRUPT-RAW-BYTES-RAISE`** — a tampered **hash** is classified `DATA_QUALITY_FAILED` (proved),
   but raw bytes that are not gzip at all raise before the classification is written (proved: the
   replay records `BadGzipFile`). Loud, not silent — no blessed consolidation is written — but the
   declared token is not emitted. Declared, not patched.
4. **`DUPLICATE-INDEX-ROW`** — the tick consolidates what the index says; duplicate detection belongs
   to the verifier, which is proven to fail on a duplicated row.

Four further defects were found while producing this evidence, and each is **fixed**, because each one
made the evidence itself untrustworthy rather than describing the campaign:

5. **`FIXTURE-REFUSALS-TRIPPED-THE-LIVE-MONITOR`** (fixed in `14514d6`). The run log is append-only and
   shared with the fixtures, so the deliberate `REFUSED_INVALID_ARGUMENTS` of a verification run was
   counted by the health monitor as the campaign failing, and a manual run refreshed its 45-minute
   liveness heartbeat. Measured before the fix: `consecutive_failures` **2 of a critical threshold of
   3** at 2026-10-08T21:48Z, with 26 deliberate refusals and 24 lease collisions from fixtures in the
   live log — the next fixture would have raised a false `CRITICAL`, and a stopped schedule could
   have looked alive. Every run event now records the launch mode it declares, and the monitor derives
   its failure streak and its heartbeat from the non-manual events only, deliberately still counting
   the 129 rows written before the field existed, because dropping them could hide a real failure.
   After the fix the live status reports a streak of 1 and `heartbeat_basis = LAST_NON_MANUAL_RUN`.
6. **`SNAPSHOT-CHECK-CONFLATED-DRIFT-WITH-CORRUPTION`** (fixed in `14514d6`). `--check` failed as soon
   as the tick rewrote its own state, i.e. within fifteen minutes of being taken; five live files had
   already moved by 22:00Z. It now verifies the snapshot's own bytes and the raw evidence as
   *integrity*, and reports the campaign moving on as *drift*, named and hashed. Proven by a new
   negative test: tampering with the snapshot copy fails the check, a missing copy fails the check, a
   manifest that is not ours is refused before anything is believed, and a live file that has moved
   passes as drift.
7. **`LIVE-TESTS-RACED-THE-SCHEDULER`** (fixed in `14514d6`). Three live tests asserted on the tick's
   outcome while the 15-minute task held the shared lease, so they failed with `ALREADY_RUNNING`
   whenever the scheduler was mid-collection (observed at 22:03Z: 3 failed; the same suite passed
   24/24 at 22:08Z). They now wait for a free lease with a bounded and *loud* timeout, and a lease that
   never frees is reported as a failure rather than skipped past.
8. **`ARTEFACT-BYTES-DEPENDED-ON-THE-PLATFORM`** (fixed in the commit that carries this report). The
   three artefacts written by the new programs were created through a Windows text-mode write, so they
   carried CRLF while git stores LF: the sha256 this report first recorded described bytes that no
   other host — and no reader of the committed blob — could reproduce. The acceptance check caught it
   (`3 recorded hashes did not reproduce`), and the writers now open with `newline="\n"`, so the
   recorded digest describes the bytes that ship. A hash that only reproduces on the machine that
   wrote it is not a hash.

9. **`RUN-LOG-PROVENANCE-IS-DECLARED-MODE`** — still open, deliberately. The launch mode is what the
invocation declares on its command line, not an unforgeable origin, so a fixture that passes
`--scheduled` is recorded exactly as the task would be, and the 129 rows that predate the field carry
no provenance at all. Minimal correction: have the registered task carry a per-installation token, or
reconcile the log against Task Scheduler's own `Last Run Time`. Not applied here: it would mean
changing the installed task, which this work does not need in order to prove the close.

Also recorded: during the test run that hardened the flakiness of the cadence test, one single-shot
tick returned status 0 with empty output and no run event (a live tick was sharing the lease at that
moment). Five immediate repeats and the manual path behaved exactly as declared, and the event never
reproduced; it is recorded here as an unexplained observation, not explained away and not claimed as
a defect of the close.

None of these alters the declared period, the collected evidence, the denominator or COST_MODEL_V3.

## 07 — Governance

```text
ST6_AUTONOMOUS_COLLECTION_ACTIVE = True
ECO_1 = OPEN
ECO_2 = UNKNOWN_NOT_RESOLVABLE_OFFLINE
NEXT_CAMPAIGN = NOT_AUTHORIZED
LIVE_TRADING = DISABLED
TRADES_AUTHORIZED = 0
PROFITABILITY_VERIFIED = False
orders_sent = 0
credentials_used = 0
period_modified = False
cost_model_v3_touched = False
cap004b_cap004d_touched = False
```

The real campaign is **not** declared finished. It closes on its own date,
`2026-10-22T16:21:20Z`, when the consolidation and the independent verification run automatically —
this work proves that the close behaves, it does not bring the close forward.

Research only: no orders, no credentials, no capital.
