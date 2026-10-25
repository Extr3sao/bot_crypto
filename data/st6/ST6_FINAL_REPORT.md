# ST-6 — AUDIT-002: scheduler provenance and lossless slot evidence

The last relevant audit problem of the ST-6 monitor: **where a run's origin comes from**, and **what
the campaign loses when a log truncates**. Reuses the existing implementation, opens no RFC, creates
no second scheduler, and touches no signal, strategy, cost rule or governance decision.

Written 2026-10-09 by the audit's own programmes from the artefacts they left on disk. Reported
HEAD: `7cd8d72f8d4330682af560f11b30cac211ad78b3` (the working tree carries this work; §10 lists what
was versioned).

## 01 — Baseline (what is provable, and what is already gone)

| what | state |
| --- | --- |
| campaign | `ST6_AUTONOMOUS_COLLECTION_ACTIVE`, 7 of 84 declared slots collected |
| period | 2026-10-08T16:21:20Z → **2026-10-22T16:21:20Z**, 14 declared days × 6 slots/day = 84 windows |
| installed task | `TradingAgentic-ST6-Forward`, enabled, repeats every `PT15M`, runs `.venv\Scripts\python.exe scripts\st6_forward_regime.py --due --scheduled` |
| run log | retained, bounded at 400 events; the appends are the tick's own |
| `MISSED_WINDOW` records | none yet: no declared slot has ended without a window |
| closure | absent (`{"present": false}`): the period is open, and the guard is verified structurally |
| historical data that survives | the 84-slot grid, the run log, the raw window bytes, the witness samples |
| historical data that is gone | every per-run Task Scheduler event of the period: the operational channel was never enabled on this host (see §04) |

## 02 — Independent Windows evidence

Read only, through the operating system's own tooling. **Status: `SCHEDULER_EVIDENCE_UNAVAILABLE`.**

| channel | state | event file | retention | records held | oldest record # | oldest retained event | newest retained event |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `Microsoft-Windows-TaskScheduler/Operational` | **disabled** | absent | circular | - | - | - | - |
| `Microsoft-Windows-TaskScheduler/Maintenance` | enabled | 1 052 672 B (full) | circular | 2269 | 440 | 2025-11-02T02:30:31Z | 2026-10-09T16:24:57Z |
| `Security` (would carry 4688) | not readable from this session | - | - | - | - | - | - |

The per-run events that would settle the question are declared by the provider — 100 (action
started), 102 (action completed, with its result code), 107 (trigger fired on schedule), 110 (task
launched because a person asked), 200/201 (the executable started and finished) — and **not one of
them exists on this host**, so their fields and semantics could not be verified event by event
against this installation. Correlation, when a record does exist, is by the task's full name, its own
instance and its action with start/finish timestamps: `LastTaskResult` and `LastRunTime` are the most
recent values of a task, not a history, and an event id alone — 100 against 110 — does not establish
that a run was scheduled. Nothing about the machine's audit configuration was changed.

## 03 — Lossless slot ledger

`data/st6/ST6_SLOT_LEDGER.json` — 84 entries, one per declared slot, `ST6_SLOT_LEDGER_V1`.

Each entry keeps: `slot_id`, `slot_start_utc`, `slot_end_utc`, `expected_trigger` (cadence, expected
triggers in the slot, declared action, and why the trigger *type* is not observable), `scheduler_instance_id`
(`null`: the channel that would carry one has never recorded), `scheduler_event_ids` (`[]`),
`external_evidence_status`, `external_evidence`, `internal_run_id`, `process_start_utc`, `result`,
`exit_code`, `collection_window_id`, `raw_evidence_hash`, `failure_reason`, `attendance_classification`
with its reading, `attendance_evidence`, `attendance_correction`, `evidence_refs`, `verifier_status`,
and the runs of the slot with their origin.

| state | slots |
| --- | --- |
| `COLLECTED` | 7 |
| `PENDING` | 77 |
| `LOST_NO_WINDOW` | 0 |
| `UNACCOUNTED` | 0 |

| external coverage of the slot | slots |
| --- | --- |
| `EXTERNAL_COVERAGE_COMPLETE` | 0 |
| `EXTERNAL_COVERAGE_PARTIAL` | 2 |
| `SCHEDULER_EVIDENCE_UNAVAILABLE` | 5 |
| `EXTERNAL_COVERAGE_NOT_YET_STARTED` | 77 |

Durable, bounded and idempotent: atomic write, no roll-up inside an event, carry-forward of a
stronger earlier statement, and an **archive copy written only at the close**
(`ST6_SLOT_LEDGER_ARCHIVE.json`, absent today on purpose) so that the 84 slots survive the period
with its identity attached. This ledger — not the 400-event ring — is the record the close will read.

## 04 — Retention of the external evidence

`data/st6/ST6_RETENTION_AUDIT.md`, regenerate on demand with `st6_scheduler_witness.py --export`.

- What exists is kept raw with its hash: the task's registration (the scheduler's own XML,
  `de358389…dcc6`), the channel states (`wevtutil gl` answers), and dated samples of the scheduler's
  own reporting (152 samples, 2026-10-09T14:43:34Z → 16:31:50Z).
- **Rotation loss is recorded, not glossed**: `EXTERNAL_RECORD_ROTATION_LOSS_RECORDED`. The
  maintenance channel is circular and full; its oldest surviving record is number 440, so **439
  records have already been evicted** and are not recoverable from this host. The operational channel
  is not "empty": it never recorded. A channel that cannot be read is kept apart from one that never
  recorded, and from a readable empty log.
- The one remediation — `wevtutil sl Microsoft-Windows-TaskScheduler/Operational /e:true` — needs an
  administrator, changes a machine-wide audit setting and cannot recover runs that have already
  happened. **Not applied, and not authorised here.** No log was cleared, resized, pruned or
  re-enabled by this work.

## 05 — Attendance classification

The historical vocabulary is kept exactly, and nothing is rewritten: a slot that produced its own
window is **not a loss**, so no loss class is asserted for it (`attendance_classification_reading`:
"not a loss: the slot produced its own window …"). For a slot that is lost, the declared classes
hold: `ATTENDED_NOT_COLLECTED`, `ATTENDED_REQUEST_FAILED`, `UNATTENDED_NO_RUN_EVENT` (only with
independent coverage of every instant of the slot), `ATTENDANCE_UNKNOWN`,
`ATTENDANCE_UNKNOWN_RUN_LOG_TRUNCATED`, `ATTENDANCE_EVIDENCE_CONFLICT`. No new token was needed and
no policy version was bumped; a correction, where one is ever needed, keeps the previous value, the
reason and both policy versions beside it.

## 06 — Independent verifier (three sources)

`data/st6/ST6_INDEPENDENT_RECONCILIATION.{json,md}` — **PASS**, 0 disagreements over 84 slots.

| source | what it is |
| --- | --- |
| A — external | the Task Scheduler's own reporting, sampled by a process that is neither the tick nor the verifier |
| B — internal | the run log, the missed log and the slot ledger |
| C — raw | the raw window bytes, re-hashed by the verifier itself |

Per slot it re-derives the state, the attendance, the run events of the slot (including the runs its
own tests caused, labelled `INDUCED_BY_THE_VERIFIER`), the window's raw hash and its reproduction.
It refuses to let a `MANUAL` invocation count as the schedule, refuses to let a program declare its
own origin without corroboration, and where the external record is insufficient it says `UNKNOWN`
rather than `PASS` — no slot of this period is called *provably* unattended.

## 07 — Negative tests

All run against isolated state; none of them takes the campaign's lease or its lock (see §09).

| # | case | evidence |
| --- | --- | --- |
| 1 | false internal event with no scheduler backing | reconciliation B/C re-derivation; ledger origin `SELF_DECLARED_UNVERIFIED`; fixture "an absence claim while the external record names a run inside the slot" |
| 2 | scheduler started, programme never ran | `ATTENDED_NOT_COLLECTED` derivation |
| 3 | scheduler ran with a failed exit code | `ATTENDED_REQUEST_FAILED` derivation |
| 4 | collection without evidence of a scheduled run | origin rules (`SELF_DECLARED_UNVERIFIED` is a declaration, not proof) |
| 5 | manual event mistaken for scheduled | fixture "a manual run never counts as attendance" |
| 6 | truncated internal logs | `ATTENDANCE_UNKNOWN_RUN_LOG_TRUNCATED`; "the ledger keeps what a bounded log has already forgotten" |
| 7 | Windows Event Log inaccessible | fixture "an absent external record is `UNKNOWN`, never an absence"; new: an unreadable channel is `EXTERNAL_RECORD_NOT_READABLE`, never "never recorded" |
| 8 | rotation of the external record | new: 439 evicted records recorded as loss; an empty readable log is told apart from both a rotated one and an unreadable one |
| 9 | duplicated slot | "a duplicated window index row"; "no slot was ever measured twice"; ledger refuses a duplicated slot |
| 10 | contradictory timestamps | `ATTENDANCE_EVIDENCE_CONFLICT`; "a missed window whose own counters contradict the run log" |
| 11 | corrupt ledger | "a corrupt or duplicated ledger is refused rather than read as empty"; "a ledger that omits a declared slot" |
| 12 | invalid hash | "a tampered window hash"; "a raw hash that does not reproduce is a mismatch, not a pass" |
| 13 | host restart | "a machine restart inside a slot stops the record carrying an absence"; replay scenario 10 reproduces the close from a fresh process |
| 14 | concurrent execution | the refusal is proven in a **private** lock root (unit test and live test), the replay's scenario 7 proves the second writer refuses and samples nothing |

Counts: 44 unit tests PASS; 33 negative fixtures inside the close verifier PASS; 5 live tests PASS;
`FALSE_SUCCESS = 0` everywhere.

## 08 — Live corroboration

Read-only observation of the real schedule, plus the verifier's own exercise of it — with the fresh
evidence that this is now harmless:

- Windows scheduler event → **not available**: the operational channel has never recorded. The
  scheduler's own reporting (its last-run instant) is sampled instead, and a live launch is
  corroborated from the process table when a tick's parent is the Task Scheduler service.
- Python run → recorded in the run log with its invocation, origin, result and exit code (140
  self-declared, 46 induced by the verifier, 35 manual, 20 corroborated by the scheduler's own
  record, 129 unattributed from the first hours of the period, before the event carried an
  invocation field — those are kept readable, not rewritten).
- Result → 7 windows collected, each raw snapshot re-hashing to its recorded digest.
- Market evidence, ledger, verification → the ledger holds all 84 slots and the reconciliation
  re-derives each of them.
- No sample was forced outside its slot, no measurement was duplicated, and no future run is
  declared verified: the last eligible slot, `2026-10-22#3`, is still `PENDING`.

## 09 — End-of-period safety, and the one interference this audit found

`2026-10-22T16:21:20Z` is preserved as the declared end: the close guard is re-derived from the tick's
own syntax tree (the `EXIT_PERIOD_ENDED` branch precedes any statement that collects a window), the
close replay proves the terminal behaviour against an isolated copy of the state, and slots that are
still ahead are not `MISSED_WINDOW`.

**Defect found and fixed during this audit.** The verifier's own live concurrency test took the
*campaign's* lease. Any real scheduled tick arriving in those seconds was therefore refused: three
refusals at 16:17:09Z, 16:18:58Z and 16:20:17Z name a holder that was a verification process, not the
campaign. No measurement was lost (the slot already had its window) and the run log keeps them
honestly. From this revision the test takes its own lease in a private lock root and passes the same
root to the process under test — the production lock is neither taken nor contended for — and the
refusal it induces declares itself a manual invocation, never the schedule's own tick. Nothing was
reclassified retrospectively.

## 10 — Deliverables and versioning

| artefact | kind |
| --- | --- |
| `data/st6/ST6_SCHEDULER_PROVENANCE.md` / `.json` | regenerable report, live |
| `data/st6/ST6_SLOT_LEDGER.json` | durable ledger, live, archived at the close |
| `data/st6/ST6_RETENTION_AUDIT.md` | regenerable report, live |
| `data/st6/ST6_INDEPENDENT_RECONCILIATION.md` / `.json` | verification, dated |
| `data/st6/ST6_CLOSE_INDEPENDENT_VERIFICATION.json` | verification, dated |
| `data/st6/ST6_FINAL_REPORT.md` / `.json` | this report, authored |
| `scripts/st6_scheduler_witness.py`, `scripts/st6_scheduler_evidence.py`, `scripts/st6_slot_ledger.py`, `scripts/st6_scheduler_verify.py`, `scripts/st6_close_replay.py`, `scripts/st6_close_verify.py`, `scripts/st6_state_snapshot.py`, `scripts/st6_health_check.py`, `scripts/st6_forward_regime.py`, `tests/unit/research/test_st6_scheduler.py` | implementation, versioned |

Versioned: only this work's own files. Untouched and uncommitted: the other agents' modifications
(`FINAL_REPORT.md`, `RUN_REPORT.*`, `docs/source_registry.md`, `evidence/real_decisions/*`,
`scripts/cap004c_verify.py`, the RFC-035E material). Live runtime state (run log, window index,
observations, health, drift, coverage) is deliberately **not** frozen into the commit: it keeps
moving by design and is recorded by the snapshot, not by git. The new raw windows
(`data/st6/raw/2026*.json.gz`) are immutable evidence and are committed with the snapshot that
hashes them.

## 11 — Acceptance

| criterion | result |
| --- | --- |
| external corroboration proven, or `UNKNOWN` explicit | `UNKNOWN` recorded everywhere it is true: `SCHEDULER_EVIDENCE_UNAVAILABLE`, no absence claim anywhere |
| complete and durable ledger | PASS — 84 entries, no unaccounted slot, archive reserved for the close |
| reproducible loss classifications | PASS — vocabulary unchanged, re-derived by two independent programmes |
| negative tests | PASS — 33 fixtures + 44 unit tests + 5 live tests, `FALSE_SUCCESS = 0` |
| close replay | PASS — 10/10 scenarios, real state unmoved, 0 market requests, 0 declared deviations |
| real scheduler unaltered | PASS — read only; the one interference found (§09) is fixed |
| independent verification | PASS — 20/20 close checks, 4970+/5096 scheduler checks, 0 mismatches |
| no prior evidence lost | PASS — nothing cleared, pruned or rewritten; append-only logs kept readable |
| `FALSE_SUCCESS` | **0** |

Standing state, unchanged: `ST6_AUTONOMOUS_COLLECTION_ACTIVE`, `ECO-1 = OPEN`,
`NEXT_CAMPAIGN = NOT_AUTHORIZED`, `LIVE_TRADING = DISABLED`, `TRADES_AUTHORIZED = 0`,
`PROFITABILITY_VERIFIED = FALSE`. Next gate: the close of `2026-10-22T16:21:20Z`, verified against
the complete ledger.

Research only: no orders, no credentials, no capital.
