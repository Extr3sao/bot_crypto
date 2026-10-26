# ST-6 — retention of the external scheduler evidence

Generated 2026-10-09T16:34:35Z by `scripts/st6_scheduler_witness.py`, read-only.

## 01 — Status: `SCHEDULER_EVIDENCE_UNAVAILABLE`

Microsoft-Windows-TaskScheduler/Operational is disabled on this host and no event file exists for it, so the channel has never recorded a single run of this task; the enabled Microsoft-Windows-TaskScheduler/Maintenance channel holds only its own maintenance events, which name no task; and the Security channel, which would carry a process-creation record if that audit subcategory were enabled and if this session could read it, is not readable here

| channel | state | event file | bytes | last written |
| --- | --- | --- | --- | --- |
| `Microsoft-Windows-TaskScheduler/Operational` | disabled | absent | - | - |
| `Microsoft-Windows-TaskScheduler/Maintenance` | enabled | present | 1052672 | 2026-10-09T16:25:58Z |

The Security channel, which would carry a per-run process-creation record, is not readable from this session: DENIED_OR_UNAVAILABLE: Intento de realizar una operaci¢n no v lida.

## 02 — What the loss is, exactly

Per-run external evidence for this period does not exist and cannot be recovered:

- the operational channel was never enabled on this host, so no run of this task has ever left an event, and a slot that already ended cannot be corroborated run by run;
- the scheduler keeps only the **most recent** run instant and result for a task, so even that single field describes one run at a time;
- the maintenance channel that is enabled carries only its own maintenance events;
- the per-run events that would settle it are declared by the provider and listed below, but not one of them exists here to be read, so their fields and semantics could not be verified against this installation;

| event id | what the provider declares it means | present on this host |
| --- | --- | --- |
| 100 | the task's action started: a run of this task began | no |
| 102 | the task's action completed, with the result code it returned | no |
| 107 | the task's trigger fired on its own schedule | no |
| 110 | the task was launched because a person asked for it | no |
| 200 | the action's executable was started | no |
| 201 | the action's executable finished, with its exit code | no |

Correlation, when a record does exist: a per-run record has to be correlated by the task's full name, its own instance and its action, with the timestamps of the start and of the action's start and finish; LastTaskResult and LastRunTime alone are the most recent values of a task, not a history, and an event id on its own — 100 against 110, a scheduled trigger against a launch asked for by hand — does not establish that the run was scheduled.

This is recorded as a limitation of the evidence, not as evidence of absence: no slot of this period may be called *provably* unattended from these sources.

## 02b — How far back the surviving record reaches

Period actually covered, per channel, read from the log itself:

| channel | retention | records held | oldest record number | oldest retained event | newest retained event |
| --- | --- | --- | --- | --- | --- |
| `Microsoft-Windows-TaskScheduler/Operational` | circular | - | - | - | - |
| `Microsoft-Windows-TaskScheduler/Maintenance` | circular | 2269 | 440 | 2025-11-02T02:30:31Z | 2026-10-09T16:24:57Z |

## 03 — What is retained instead

| retained | form | hash |
| --- | --- | --- |
| the task's registration | the scheduler's own XML, verbatim | `de3583897a529d21d2f6eaba542741b8e575f0904a912fe6506b1bd738acdcc6` |
| the channel states | the raw `wevtutil gl` answer per channel | `8c40bc8b7d6b1dcf7a39baeb2f3718883f21b4db96fcfdfa4a1e41443b8814c2` |
| the scheduler's reporting | a dated sample of last run / result / missed runs | `22713d0f3087f2b8f2660d5a3ceea849cec3cbb1c0e45306a698e17386245778` |
| the witness log | 152 sample(s), 2026-10-09T14:43:34.545Z → 2026-10-09T16:31:50.326Z | `data/st6/ST6_SCHEDULER_WITNESS.jsonl` |

Distinct scheduler last-run instants observed so far: 9; launches seen with a tick in flight: 0.

## 04 — The one remediation, and why it is not applied here

`wevtutil sl Microsoft-Windows-TaskScheduler/Operational /e:true` — needs an administrator, changes a machine-wide audit setting, and is **not authorised** in this work: it changes a machine-wide audit setting, it needs an administrator, and it cannot recover the runs that have already happened: the channel records from the moment it is enabled.

What it would give: per-run events (100 started, 102 completed, 107/110 triggered, 200/201 action started and finished) with their own record ids, so every slot could be corroborated run by run instead of from a point-in-time sample

Until an operator authorises it, the external evidence of this period stays what it is: point-in-time samples of the scheduler's own record, bounded by the witness's own coverage, with `SCHEDULER_EVIDENCE_UNAVAILABLE` recorded wherever a per-run record would be needed.

## 05 — Rotation: the loss that has already happened elsewhere

Status: `EXTERNAL_RECORD_ROTATION_LOSS_RECORDED`.

- `Microsoft-Windows-TaskScheduler/Operational`: NEVER_RECORDED, log circular
- `Microsoft-Windows-TaskScheduler/Maintenance`: RECORDS_ROTATED_OUT, 439 record(s) no longer present before the oldest one still held, oldest retained event 2025-11-02T02:30:31Z, log circular and full

where a log is circular and has filled, its oldest records are already gone: the number of the oldest record still present is the count of what this host can no longer answer for. A channel that cannot be read at all is kept apart from one that never recorded and from an empty log — only a readable, empty channel could support the reading that it holds no run. Either way the loss is a property of the evidence, recorded so that a slot the surviving record does not cover is never called provably unattended

Recorded, not applied: clearing, resizing, re-enabling or pruning any log: this reading is taken read-only and the loss it names cannot be repaired for the instants that have already passed.

Research only: no orders, no credentials, no capital.
