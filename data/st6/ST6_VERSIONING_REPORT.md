# ST-6 — versioning and independent end-of-period replay

Generated 2026-10-08T22:13Z from the baseline `9660afab9003001d3a8130b9679c066071548421` (branch
`main`, verified with `git rev-parse HEAD`) and extended at 2026-10-09T08:10Z, now at
`3868f5958250ccf846094c698719cc821f565a8c` after six commits of this work; the commit that carries
this report is reported as `CURRENT_HEAD` in the mission's final response. No new campaign, no change
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
  stopped moving, and the one `--check` re-verified at the first pass;
* `data/st6/snapshots/ST6_LIVE_STATE_20261009T074023Z.json` — the picture taken once the second
  pass's code had settled (defect 10 below);
* `data/st6/snapshots/ST6_LIVE_STATE_20261009T075959Z.json` — the picture the independent
  verification reads now; taken after every source file of the pass was frozen, and it reports that
  no live file moved while it was being taken.

A seventh picture was taken at 07:33:09Z and **discarded**: it raced the running tick, and the five
files the tick rewrites were copied before the tick rewrote them while their hashes were read after
it, so the manifest recorded digests for bytes that were nowhere on disk. The mechanism was fixed
before any evidence was committed (defect 10), and the discarded snapshot is described there rather
than shipped, because a manifest whose digests do not describe its own copies is not evidence.

The snapshot trees are stored **verbatim** (`data/st6/snapshots/.gitattributes` sets `-text`). This
host writes the live ST-6 artefacts with CRLF line endings while git's text conversion
(`core.autocrlf=true`) stores text with LF, so before this pass a manifest's per-file digests
described bytes that existed only on this machine: the copies in the first four committed snapshots
were stored normalised, and their recorded digests could not be reproduced from the commit. Every
copy of every snapshot was re-hashed against `git cat-file blob HEAD:<path>` after the change: **90
copies, 0 mismatches** (defect 11).

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
| `8a7afd2` | make the ST-6 close terminal, idempotent and independently replayed | 47 | the implementation, the first reports and the first two snapshots |
| `14514d6` | record who invoked the tick and tell snapshot drift from corruption | 6 | defects 5–7 below |
| `f0173f7` | report the ST-6 close evidence at the correcting commit | 22 | the regenerated artefacts and the third snapshot |
| `5178353` | write the ST-6 artefacts with LF so their recorded hashes travel | 24 | defect 8 below, its regenerated artefacts and the fourth snapshot |
| `3868f59` | prove why an ST-6 slot went unattended instead of asserting it | 104 | the second pass (§08): the attendance evidence, the two verifiers, the regenerated replay report and six snapshot trees |
| the commit that carries this report | this report and the boundary audit it summarises | 2 | reports |

The identity of the content staged (git blob SHA-1, `git hash-object` of the exact bytes, and what
`HEAD` actually holds — they agree on every row) is:

| path | git blob sha1 at `3868f59` | bytes |
| --- | --- | --- |
| `scripts/st6_forward_regime.py` | `0935dfb76c026e8b68410aac177b4bcc31aefb9b` | 128360 |
| `scripts/st6_health_check.py` | `6ee615c867af2e84fb8b4465ba2b7efc4a99a1fb` | 30037 |
| `scripts/st6_scheduler_verify.py` | `21db3ba38c7869507c1981a34dcb99d4e60dd509` | 32276 |
| `scripts/st6_state_snapshot.py` | `6c657d90177eab67d0569790bc35caddf7347a5a` | 17536 |
| `scripts/st6_close_replay.py` | `65a072f7b3cbbefb8f5e02234861e22d0b25ecd4` | 61686 |
| `scripts/st6_close_verify.py` | `c55d1235cfbd830255817dd2aea45bb5b9dba6b8` | 54712 |
| `tests/unit/research/test_st6_scheduler.py` | `3c0c242e3af5de20a1b307ba5fcb4df4931beaa4` | 43806 |
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
| scheduler verifier — live execution through the scheduler, lease, `--due` idempotency, refusal path, closure guard, run log, missed accounting, order-path scan | **PASS 2570/2570**, 0 mismatches, FALSE_SUCCESS 0. The total is not a fixed list: it grows with the run log (218 events at ~10 checks each) plus the live tests and the static checks |
| isolated close replay — 11 scenarios, injected UTC clock, isolated sandbox, market and scheduler forbidden | **PASS 10/10** close mechanics, 0 FAIL, real state unmoved, 0 real requests, 0 real scheduler calls |
| independent close verification — a different program from the builder *and* from the harness | **PASS 19/19**, 0 mismatches, FALSE_SUCCESS 0, verdict `ST6_CLOSE_VERIFIED` |
| negative fixtures — duplication, tampered hash, missing evidence, order path, foreign closure, supported-over-incomplete-coverage, hidden drift, plan past its end, moved implementation hash, misclassified artefact, hidden failed check, unexplained real change, and five for the attendance claim of a missed window (a lie the log contradicts, no evidence at all, counters that disagree, bounds that are not the declared slot, and the honest claim that must not be flagged) | **PASS 22/22** corruptions detected |
| missed-window evidence in the replayed close | the replayed consolidation carries **80** missed windows, every one with a cause re-derived from the run events at the injected close instant (`UNATTENDED_NO_RUN_EVENT`, because no run event lies inside those slots while the retained log reaches back before them), its counters, its last error, and a statement of how long that inference is valid |
| determinism — the harness re-run from the same seed state | close sha256 `568a20191bb8700b…` reproduced exactly, byte for byte; every scenario verdict equal. Inside the sandbox the tick records the code identity as a constant (`REPLAY_SANDBOX_NOT_A_COMMIT`), so this proof does not depend on the commit hash — the real head is recorded at the top level of the report |
| unit suites | **50 passed**, 0 failed (`test_st6_scheduler.py` 28, `test_st6_forward_regime.py` 22); seven of them added by this work. One instance of the suite failed in the live environment at 08:07Z when the `--collect --rounds 0` refusal collided with the scheduler's own tick, and the same test passed on its own four minutes later — the declared contention of §06.7, loud rather than skipped, and the event it leaves behind declares itself manual so it cannot raise the campaign's status |
| live-state snapshot | `--check` PASS (19 checks) right after `ST6_LIVE_STATE_20261009T075959Z` was taken: the snapshot's own bytes and the raw evidence reproduce, and the live files that have moved since are named as drift |
| snapshot storage | every copy of all six snapshots re-hashed against `git cat-file blob HEAD:<path>`: **90 copies, 0 mismatches** |
| a stale snapshot is refused | when the three programs were edited after `ST6_LIVE_STATE_20261008T221134Z` had been taken, the independent verifier **failed** with `the implementation file scripts/st6_state_snapshot.py changed after the snapshot` (18/19, FALSE_SUCCESS 1). The snapshot was retaken in the right order and the same verification then passed 19/19. The check is not decorative. |
| live health after the second pass | `HEALTHY` at 2026-10-09T08:02:56Z; 219 run events by provenance `{MANUAL: 12, SCHEDULED: 78, UNRECORDED: 129}`; failure streak **0** over non-manual events only (threshold 3); heartbeat basis `LAST_NON_MANUAL_RUN`, age 12 s; what the fixtures did is recorded beside it as information (`manual_invocations_with_errors: 12`, last manual error `rounds=0 …`) and no longer raises the status; 5 windows, 60 observations, 0 unaccounted slots, 0 missed, 0 unsupported attendance claims |

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

Three further defects were found by this second pass, and the two that touched the trustworthiness
of the evidence are **fixed**:

10. **`SNAPSHOT-HASHED-A-FILE-THE-TICK-REWROTE`** (fixed in `3868f59`, the second pass). The snapshot
    read each live file's hash and copied it in two separate steps. The tick rewrites five of those
    files every fifteen minutes, and the snapshot taken at 07:33:09Z landed inside a tick that was
    writing exactly then: the manifest recorded five digests for versions of those files that existed
    nowhere on disk (`ST6_RUNS.jsonl`, `ST6_HEALTH.jsonl`, `ST6_HEALTH_STATUS.json`,
    `ST6_SCHEDULER_REPORT.json`, `ST6_SCHEDULER_REPORT.md`; recorded vs actual, e.g. `efbfc4812771`
    vs `bc5427395b1c`). The manifest now copies first and hashes the **copy**, so its digests are true
    by construction, it records the hash of the live file before and after the copy, it names the
    files the tick moved while it was being taken (`live_files_that_moved_during_the_snapshot`), and
    the raced snapshot itself was **discarded rather than shipped**. Proven by a new unit test that
    re-hashes every copy of every snapshot against its manifest, and by the re-hash of all 90 copies
    against the committed blobs.
11. **`SNAPSHOT-COPIES-STORED-NORMALISED`** (fixed in `3868f59`). The snapshots are evidence and
    their manifests record the sha256 of the bytes they copied, but the copies were committed through
    git's text conversion (`core.autocrlf=true` on this host): the stored bytes had LF where the live
    files have CRLF, so no other host — and no reader of the commit — could reproduce a single
    per-file digest of the first four snapshots. `data/st6/snapshots/.gitattributes` now sets `-text`
    for the whole tree and the six trees are stored verbatim. Not one byte on disk changed: what
    changed is that the committed bytes are now the bytes the manifests describe. Verified by
    re-hashing **90 copies against `git cat-file blob HEAD:<path>`, 0 mismatches** — a check that
    failed for 5 of them before the fix.
12. **`FIXTURE-CONTENTION-COSTS-A-TEST-MINUTES`** — open, declared. The live tests wait out a lease
    the scheduler holds rather than racing it, and the wait is bounded at 300 s and loud. When a
    *dead* holder's lock lingers, the wait runs until the lease's own 300 s staleness rule frees it:
    measured on this host, `test_an_impossible_cadence_refuses_with_a_non_zero_status` failed once at
    08:07Z under exactly that collision and then passed in 267 s on its own. The trade-off is
    deliberate (`LEASE_STALE_AFTER_S = 300` keeps a hard-killed tick from stalling collection beyond
    one short lease age, and the 15-minute cadence means a five-minute stall cannot cost a slot), so
    it is declared rather than papered over with a shorter, flakier wait.

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

## 08 — The second pass: proving why a slot was missed

The close mechanics were already proven; what was not proven was the *loss accounting* the close
depends on. A declared slot that ended without a window was written down as a `MISSED_WINDOW` with one
generic sentence, so two very different failures read the same: a host or a task that never fired, and
a tick that ran and still measured nothing. A period like this one ends in
`INSUFFICIENT_REGIME_COVERAGE`, and the difference between those two failures is what decides whether
the programme's own schedule can be trusted at all.

Every miss now carries the attendance evidence the run log held **at the moment the slot was
accounted**, in a closed vocabulary:

| class | what the run log proves |
| --- | --- |
| `UNATTENDED_NO_RUN_EVENT` | no scheduled run event lies in the slot while the retained log reaches back to before the slot began: the schedule itself did not fire |
| `ATTENDED_NOT_COLLECTED` | the tick visited the slot — its run events are there — and no window came of them, with the results histogram, the requests made and the last error beside it |
| `ATTENDED_REQUEST_FAILED` | as above, and at least one of those runs reached the exchange and recorded an error |
| `ATTENDANCE_UNKNOWN_RUN_LOG_TRUNCATED` | the bounded, front-truncated run log no longer reaches back to the slot, so an absent event is **not** proof of an absent tick and no cause is claimed |

A run that declares itself `MANUAL` is not the schedule and is not counted as attendance; a run that
declares nothing is kept, because dropping an unlabelled event could turn a busy slot into an
unattended one. The record also states how long its inference stays valid, because the run log keeps
only 400 events and pruning will remove the very events the inference rested on.

Three programs now audit that claim instead of trusting it, each one independent of the writer:

* the **health check** re-derives the cause from the run events and from the declared grid, and treats
  a claim it cannot support as `CRITICAL` — a miss that blames the schedule while the log shows the
  tick running is a divergence, not a note;
* the **close verifier** requires the block to be present, to name a declared class, to be bounded by
  the declared slot and to match a class it derives itself, with five new negative fixtures proving it
  fails on each corruption and stays silent on an honest claim;
* the **scheduler verifier** requires the cause to agree with the record's own counters and, while the
  retained log still covers the slot, with a second count taken from the events.

In the replayed close this runs on real records: the sandbox consolidation carries **80 missed
windows**, each with its cause, counters and evidence lifetime, at the injected close instant. The
live period has **0** missed windows and **0** unsupported claims so far, so the path is exercised by
the replay and by the unit tests rather than by a loss that has not happened yet.

Two evidence defects surfaced while producing this, and both were fixed rather than declared
(§06.10, §06.11): the snapshot that hashed a file the tick rewrote while copying it, and the snapshot
trees whose recorded digests could not be reproduced from the commit. Neither changes the declared
period, the collected evidence, the denominator or COST_MODEL_V3; both change whether a reader can
believe the hashes this report records, which is the whole point of them.
