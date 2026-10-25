# RFC-047 — ST-6 SCHEDULER PROVENANCE & INDEPENDENT EXECUTION EVIDENCE

| field | value |
| --- | --- |
| RFC | **RFC-047** |
| STATUS | **`RFC047_BLOCKED_HOST_PERMISSIONS`** — the mechanism is implemented and verified; the one host change that would let it corroborate runs was not approved |
| BASELINE | `a709c88` |
| PERIOD | `2026-10-08T16:21:20Z` → `2026-10-22T16:21:20Z` (14 days, 6 slots of 4 h per day, 84 declared slots) |
| MODE | read-only. No order, no credential, no strategy, no backtest, no second task, no campaign |
| SUPERSEDES | nothing |
| PARENT AUTHORITY | RFC-041 `BUSINESS-FREEZE-2026-001`, RFC-046 offline discovery — both unchanged |
| TRADES_AUTHORIZED | 0 |
| LIVE_TRADING | DISABLED |
| PROFITABILITY_VERIFIED | FALSE |
| NEXT_GATE | the real close of the ST-6 period on 2026-10-22, and before it the single command that would let the remaining slots be corroborated |

> This document records a decision that was **taken and then blocked by the host**, not a plan. The
> program that reads the Windows event evidence, the reconciliation that joins it with the ledger,
> the independent verifier and its eighteen negative controls all exist and run; the one
> configuration change the request contemplates was requested with its exact command and was not
> approved, so it was not applied and the refusal is recorded rather than worked around.

## 00 — The difference this RFC exists to close

Two statements are not the same statement:

```text
PROCESS_CLAIMS_SCHEDULED_EXECUTION
WINDOWS_CONFIRMS_SCHEDULED_EXECUTION
```

ST-6 writes its own run log, so "the schedule started me" is a claim a program makes about itself. The
record that would settle it lives in a channel of the host — and on this host that channel,
`Microsoft-Windows-TaskScheduler/Operational`, is **disabled and has never recorded**. Everything
below is about keeping that difference visible instead of averaging it away.

## 01 — Authority and planes of evidence

```text
REAL_RUNTIME > EXECUTION_EVIDENCE > TESTS > SOURCE_CODE > ARCH/RFC > EXTERNAL_SOURCE > ASSUMPTION
```

Three planes are now read separately, and none may speak for another:

| plane | artefact | what it can establish |
| --- | --- | --- |
| Windows evidence | `data/st6/rfc047/WINDOWS_EVENTS.jsonl`, `RFC047_WINDOWS_EVENT_EVIDENCE.json` | that the host's own record named a launch of the task |
| ST-6 execution evidence | `ST6_RUNS.jsonl`, `ST6_SLOT_LEDGER.json` | what the monitor did, when, and with what result |
| market evidence | `ST6_WINDOWS.jsonl`, `data/st6/raw/*.json.gz` | that a window was collected, and its bytes re-hash |

## 02 — Host audit (WP-047-01)

Read-only, taken before anything else and kept verbatim in
`data/st6/rfc047/RFC047_HOST_AUDIT_PREFLIGHT_RAW.json` and normalised in `data/st6/RFC047_HOST_AUDIT.json`.

| channel | enabled | retention | max size | records held | oldest present |
| --- | --- | --- | --- | --- | --- |
| `Microsoft-Windows-TaskScheduler/Operational` | **false** | circular (`retention: false`) | 10 485 760 B | **none — never recorded** | — |
| `Microsoft-Windows-TaskScheduler/Maintenance` | true | circular, no auto-backup | 1 052 672 B | 2 274 (file at its maximum) | 440 → **439 records already evicted** |

The effective session (`DIRECTORI\GVLLFR0035`) **may read** both channels — the access list grants
*Interactive Users* the read bits — and **may not change** them: the write attempt returns exit code
`5`, *Acceso denegado*. That asymmetry is the whole finding: the evidence is readable, the setting
that would create it is not writable.

## 03 — The gate (WP-047-02)

The request names exactly one configuration change and requires it to be treated as an authorisation
gate:

```text
wevtutil sl Microsoft-Windows-TaskScheduler/Operational /e:true
```

- **State before**: `enabled: false`. **State after**: unchanged.
- **Requested**: yes, with that exact command, from an unelevated session.
- **Outcome**: `HOST_AUDIT_CHANGE_APPROVAL_REQUIRED` — the request for an elevated token was not
  approved in this session, and the unelevated attempt was refused with exit code `5`.
- **Not done, deliberately**: no ACL, no GPO, no other channel, no size or retention policy, no
  Security log, no second task, no attempt to obtain administrator credentials.
- **Rollback, should it ever be applied**: `wevtutil sl Microsoft-Windows-TaskScheduler/Operational
  /e:false`, which restores that one flag and nothing else; it deletes no evidence and does not touch
  the Security channel. The owner and the current state of the setting must be checked before anyone
  runs it.

Because the channel records from the moment it is enabled, **no coverage is inferred for any instant
before it**, and no slot of this period may be promoted to a confirmation later.

## 04 — What the identifiers mean (WP-047-03a)

The request names `100`, `102`, `107`, `110`, `200` and `201` as **candidates** and requires their
real meaning to be verified against the Windows installed before they become classification rules.

- The Maintenance channel holds only identifiers **800** and **808** (2 199 and 75 records): no
  candidate identifier exists in it, and no query filtered on the task returns a single record.
- The Operational channel holds nothing at all.
- Therefore `semantics_verified_on_this_host = false`, and **the identifiers were never turned into
  rules**. A record is classified by its channel, its task path, its instants and its instance
  identifiers; an identifier on its own never establishes that a run was scheduled.
- A meaning becomes usable only through `data/st6/rfc047/EVENT_SEMANTICS.json`, and only when it
  quotes a real record — channel and `EventRecordID` — that is actually in the store. A hand-written
  file cannot promote an absence into an observation.

## 05 — Incremental capture (WP-047-03)

`scripts/st6_windows_events.py` reads the channels read-only and persists what it reads:

- **incremental by `EventRecordID`**, advancing from a stored watermark rather than re-reading a
  window of time;
- **deduplicated** on `(channel, EventRecordID)`, so a re-read adds nothing and the store never grows
  by being read twice;
- **atomic**: the store is rewritten through a temporary file in the same directory, so a reader never
  sees half a record;
- **bounded**: at most `MAX_RECORDS_PER_READ` records per channel per run, only records of the
  monitored task, and the original fragment kept only up to 8 KiB so its hash stays re-checkable;
- **the watermark moves only after the write**, and never past a fragment that could not be parsed;
- **rotation and identifier resets are recorded**, not smoothed: a gap between the watermark and the
  oldest record still present is written down with the count of records lost;
- **refusals are recorded**: a refused query, a timeout, an unreadable fragment and a disabled channel
  each leave their own trace beside the immutable store;
- **the tick cannot be blocked by any of this**: the scheduled tick runs this program as a subprocess
  and records its exit status, so a failed read costs provenance and never a sample.

Live state (`WINDOWS_EVENT_LIVE_STATE.json`) is kept apart from immutable evidence
(`WINDOWS_EVENTS.jsonl`), so a mutable watermark can never be mistaken for a record.

## 06 — Ledger integration (WP-047-04)

`ST6_SLOT_LEDGER_V1` is **not rewritten**. Each of the 84 entries keeps its own fields and gains one
versioned block, `RFC047_WINDOWS_EVIDENCE_V1`, under the closed vocabulary:

```text
WIN_EVENT_CONFIRMED_SCHEDULED   WIN_EVENT_CONFIRMED_MANUAL   WIN_EVENT_PARTIAL
WIN_EVENT_UNAVAILABLE           WIN_EVENT_CONFLICT           PRE_ENABLE_NOT_OBSERVABLE
PENDING_EVENT_COMPLETION
```

Rules the block obeys:

- a confirmation needs **both** an established meaning **and** a record of this host naming the task
  at the instant of an internal run — neither the run's own declaration nor an identifier suffices;
- a **manual** launch is reported as manual and is never counted as attendance of the schedule;
- a claim of the schedule against a **covered** external record that names nothing is a
  `WIN_EVENT_CONFLICT`, not a gap;
- a slot that ended inside the completion grace is `PENDING_EVENT_COMPLETION`, because the engine
  writes the completion of an action after the process it describes has exited;
- a slot from before the channel could record is `PRE_ENABLE_NOT_OBSERVABLE` and is **never** promoted
  retroactively;
- a rebuild never weakens a recorded statement: a stronger earlier block is carried forward and says
  when it was read.

## 07 — Runtime correlation (WP-047-06, WP-047-07)

`data/st6/RFC047_RUNTIME_VERIFICATION.json` reports the chain link by link, from real artefacts:

| link | held | by what |
| --- | --- | --- |
| Windows scheduled trigger | **no** | the channel that would name it is disabled; the request to enable it was refused |
| process execution | yes | the run log, with the run's start, end and exit code |
| corroboration of the launch | yes | the witness process sampled the Task Scheduler's own register and it named the same instant (20 runs of this period rest on it) |
| ST-6 run id | yes | the run identity recorded in the ledger entry of its slot |
| slot outcome | yes | the slot's window, or the classification of the loss that explains it |
| evidence reference | yes | the raw bytes of the window and their re-hashed digest |

The chain therefore reaches the launch but **not the trigger**, and that is stated as
`RFC047_RUNTIME_CORRELATION_PARTIAL_INTERNAL_AND_SERVICE_ONLY`. No run was started by hand to
manufacture a chain: a chain built from an induced run would prove nothing about the schedule.

## 08 — Independent verification (WP-047-05)

`scripts/rfc047_verify.py` shares no code and no vocabulary with the builder. It re-derives:

- the channel's state **from the host**, not from the audit document;
- the declared slot grid from the period, and the ledger's bounds against it;
- RFC-047's classification of every slot from the raw evidence;
- the hash of every stored fragment, and the hash of the raw market bytes of every collected slot;
- the identity of the task in every record and of the instance every correlation quotes;
- temporal integrity: no slot ahead of now may carry an outcome, no record may be dated in the
  future, no end may pass unaccounted for;
- the absence of live orders, of credential material and of any second scheduled task.

`FALSE_SUCCESS` counts two things only — a manipulation the verifier accepted, and a claim the
artefacts do not support. An honest state refused by mistake is reported separately as a false
accusation, because it is a different failure.

### 08.1 Negative controls

The eighteen adversarial cases of the test plan are implemented as mutations of the real artefacts and
run through the same verification. Seventeen must be rejected; one — *a valid collection without
external provenance* — **must be accepted**, because that is the honest state of every slot of this
period and calling it a defect would be as wrong as accepting a fabrication. A case is judged against
the baseline of the unmutated artefacts, so a baseline problem cannot masquerade as eighteen
successful controls.

## 09 — Acceptance criteria

| criterion | result |
| --- | --- |
| ACC-047-01 — history before the enable keeps an honest state | **met**: every slot of the period is `PRE_ENABLE_NOT_OBSERVABLE`, and no rebuild may promote one |
| ACC-047-02 — the channel is enabled and reachable, **or** an explicit administrative block exists | **met by the block**: `HOST_AUDIT_CHANGE_APPROVAL_REQUIRED`, with the refusal recorded |
| ACC-047-03 — incremental capture keeps relevant events without duplicating them | **implemented and verified**; on this host it captures none, because none exists |
| ACC-047-04 — the persisted information allows the decisions to be reconstructed | **met**: the block carries its reason, its missing elements, its correlations and its references |
| ACC-047-05 — a manual execution is never certified as scheduled | **met**: manual is its own state and never counts as attendance |
| ACC-047-06 — a real scheduled execution is corroborated by Windows and internal evidence | **not met**: impossible without the channel; reported as such, not asserted |
| ACC-047-07 — the monitor keeps collecting even if the audit channel fails | **met**: the reading is a subprocess of the tick and cannot block a sample |
| ACC-047-08 — the close replay stays deterministic | **met**: unchanged by this RFC |
| ACC-047-09 — no additional scheduled task is created | **met**: no task was created; the campaign's own task is the only one of its name |
| ACC-047-10 — no live orders, no live credentials, no strategy changes | **met**: the verifier scans for credential values and the invariants are asserted |
| ACC-047-11 — the close keeps every slot and does not remove DRIFT | **met**: 84/84 slots, and nothing in this RFC touches the drift record |
| ACC-047-12 — tests and independent verification are verifiable, with `FALSE_SUCCESS = 0` | **met**: see `RFC047_INDEPENDENT_VERIFICATION.*` |

## 10 — Failure policy

```text
RFC047_VERIFIED                     — every slot corroborated: not reachable while the channel is off
RFC047_PARTIAL_EXTERNAL_EVIDENCE    — some slots corroborated, not all
RFC047_BLOCKED_HOST_PERMISSIONS     — ← this RFC, decided by the host and not by this document
RFC047_FAILED                       — the mechanism itself does not hold
```

`VERIFIED` is not claimed for compiling, for a passing suite, for the channel being enabled, for an
uncorrelated event, for `LastTaskResult = 0` or for the word `SCHEDULED` appearing in a run log. The
decisive evidence is the correlation with a real scheduled execution, and it does not exist here.

## 11 — Security, rollback and retention

- No credential, token or secret is written by any program of this RFC; the verifier scans the
  artefacts for credential *values* and reports what it finds.
- The only change contemplated is reversible with `/e:false`; the document does not authorise running
  it, and any rollback must check the owner and the current state of the setting first.
- The store is preserved until the period closes and is archived with the period's identity.
- Nothing here changes the campaign: `ST6_AUTONOMOUS_COLLECTION_ACTIVE`, `ECO-1 = OPEN`,
  `NEXT_CAMPAIGN = NOT_AUTHORIZED`, `LIVE_TRADING = DISABLED`, `TRADES_AUTHORIZED = 0`,
  `PROFITABILITY_VERIFIED = FALSE`.

## 12 — Deliverables

```text
docs/rfc/RFC-047_ST6_SCHEDULER_PROVENANCE.md          this document
docs/rfc/RFC-047_ST6_SCHEDULER_PROVENANCE.json        its machine-readable twin
data/st6/RFC047_HOST_AUDIT.json                       the host audit and the gate
data/st6/RFC047_WINDOWS_EVENT_EVIDENCE.json           the store and what it cannot hold
data/st6/RFC047_LEDGER_RECONCILIATION.json            the three planes joined, per slot
data/st6/RFC047_RUNTIME_VERIFICATION.json             the runtime chain, link by link
data/st6/RFC047_INDEPENDENT_VERIFICATION.md/.json     the independent verifier and its controls
data/st6/RFC047_FINAL_REPORT.md/.json                 the report in the requested field list
data/st6/rfc047/WINDOWS_EVENTS.jsonl                  immutable evidence
data/st6/rfc047/WINDOWS_EVENT_LIVE_STATE.json         live state: watermarks, attempts, refusals
data/st6/rfc047/RFC047_HOST_AUDIT_PREFLIGHT_RAW.json  the before-state, verbatim
```

## 12.1 — Registration of the identifier

The number was checked against the real registry before it was used:
`docs/roadmap/RFC_REGISTRY.json` named `047` as the next free number, it held no entry for it, and no
`RFC-047`/`RFC047` artefact existed anywhere in the checkout. The registry now lists **047** as
occupied and names **048** as the next free number. Because registering it changed that document's
bytes, the digest RFC-046 recorded for it in `data/rfc046/ACTIVATION.json` was refreshed by that
RFC's own generator, and RFC-046's campaign verifier still passes its 76 checks.

## 13 — Next gate

The real close of the ST-6 period at **`2026-10-22T16:21:20Z`**, verified from the complete 84-slot
ledger and its archive. Before it, one command with an elevated token would let the remaining slots of
the period be corroborated as they happen:

```text
wevtutil sl Microsoft-Windows-TaskScheduler/Operational /e:true
```

No RFC-048 and no new strategy campaign is started by this document.

## 14 — A defect found beside this RFC, and repaired in a commit of its own

Running the campaign's own scheduler verifier exposed a defect that RFC-047 did not cause. It is
recorded here because it was found while verifying this RFC, and it is repaired in a *separate*
commit, not among RFC-047's artefacts: the repair touches a program of the campaign, and mixing that
into the change set of an audit of evidence would make the audit harder to read, not easier.

`live_error_exit_status` in `scripts/st6_scheduler_verify.py` asserts that a tick with an impossible
cadence refuses, writes a `REFUSED_INVALID_ARGUMENTS` event and returns a non-zero status. It
identifies the fresh event by the length of the run log:

```text
before = len(read_jsonl(RUN_LOG))
run the tick
fresh = read_jsonl(RUN_LOG)[before:]
```

The run log is bounded and front-truncated (`RUN_EVENTS_KEPT`), and it has now **reached its bound of
400 events**. One appended event therefore removes one from the front, the length does not change, and
`fresh` is empty — so the check reports `the refusal path did not behave as declared` while the
behaviour it asserts is true. Measured directly:

```text
before 400 / after 400 / delta 0
the tick wrote 20261009T195450Z-b4047477  REFUSED_INVALID_ARGUMENTS  exit 1
the verifier reads runs[before:] -> 0 event(s)
```

`live_real_execution` compared the same way (`len(runs) > before`) and was exposed to the same failure
for the same reason — and, taking *any* new line as proof that the triggered task ran, it could also
accept a refusal from its own earlier test as evidence of a launch.

**Repaired:** fresh events are now identified by run identity (`fresh_run_events`) in both live tests,
and the launch test waits for an event that declares a scheduled invocation and is not a refusal. No
assertion was weakened; one was made stricter. The same correction was applied to the unit test that
copied the pattern. Re-run afterwards:

```text
scripts/st6_scheduler_verify.py : PASS 5449/5449 checks, 0 mismatches, FALSE_SUCCESS = 0
tests/unit/research/test_st6_scheduler.py : 44 passed
```

The repair is the only change this RFC makes outside its own files, and it is committed on its own.
