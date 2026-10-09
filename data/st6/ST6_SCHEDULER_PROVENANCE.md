# ST-6 — provenance of the scheduled tick

Generated 2026-10-09T16:37:46Z by `scripts/st6_slot_ledger.py`, read-only with respect to the campaign.

## 01 — External evidence: `SCHEDULER_EVIDENCE_UNAVAILABLE`

Microsoft-Windows-TaskScheduler/Operational is disabled on this host and no event file exists for it, so the channel has never recorded a single run of this task; the enabled Microsoft-Windows-TaskScheduler/Maintenance channel holds only its own maintenance events, which name no task; and the Security channel, which would carry a process-creation record if that audit subcategory were enabled and if this session could read it, is not readable here

| what the external record can support | what it cannot |
| --- | --- |
| the task's registration: it exists, it is enabled, its action is the declared interpreter and script, and it repeats every fifteen minutes | an absence of execution inside any slot of this period: no external source covers those hours, so a slot with no internal event is UNKNOWN, not proven unattended |
| the most recent run, as the scheduler itself records it, sampled as often as the witness runs | a distinction between a time-trigger launch and an engine launch asked for by hand: both are started by the Task Scheduler service and neither leaves an event here |
| a live launch, from the process table: a tick whose parent is the Task Scheduler service was launched by the schema, not by a person | a per-run exit status: only the most recent result is readable, and only while it is the most recent |

Witness samples: 152 (2026-10-09T14:43:34.545Z → 2026-10-09T16:31:50.326Z); scheduler instants observed: 9; ticks seen in flight with the Task Scheduler service as their parent: 0.

Rotation of the external record: `EXTERNAL_RECORD_ROTATION_LOSS_RECORDED`.

- `Microsoft-Windows-TaskScheduler/Maintenance`: RECORDS_ROTATED_OUT, 439 record(s) no longer present before the oldest one still held, oldest retained event 2025-11-02T02:30:31Z
- `Microsoft-Windows-TaskScheduler/Operational`: NEVER_RECORDED

## 02 — Where each run event's origin comes from

| origin | runs | what it means |
| --- | --- | --- |
| `CORROBORATED_ENGINE_LAUNCH` | 20 | a witness sample names the scheduler's own last-run instant at this event's start, so the Task Scheduler engine launched the task then; the operational channel is disabled, so the trigger type stays unknown |
| `SELF_DECLARED_UNVERIFIED` | 140 | the event declares itself the schedule and nothing outside the run log corroborates it: a declaration, not proof |
| `MANUAL` | 35 | the event declares itself a manual invocation |
| `INDUCED_BY_THE_VERIFIER` | 50 | this repository's own verifier asked the scheduler to run the task; a real launch, and not the schedule's own tick |
| `UNATTRIBUTED` | 129 | the event declares nothing and no witness sample reaches it |

a run event's origin is decided outside the tick: by the scheduler's own record, by the verifier's own record of what it induced, or by the event's own declaration, which is the weakest of the three and is labelled as such

## 03 — The slot grid

| state | slots |
| --- | --- |
| COLLECTED | 7 |
| PENDING | 77 |

| external coverage | slots |
| --- | --- |
| EXTERNAL_COVERAGE_COMPLETE | 0 |
| EXTERNAL_COVERAGE_NOT_YET_STARTED | 77 |
| EXTERNAL_COVERAGE_PARTIAL | 2 |
| SCHEDULER_EVIDENCE_UNAVAILABLE | 5 |

| attendance class | slots |
| --- | --- |
| none (the 7 collected slot(s) are not losses and have no class here) | 0 |

The vocabulary classifies *losses*: a slot that produced its own window and its raw evidence
is described by its state (`COLLECTED`), not by a loss class, and no class is claimed for a
slot that has not ended.

## 04 — What this document does not claim

- that any past slot of this period was provably unattended: no per-run external record covers those hours on this host
- that a run the scheduler's record corroborated was time-triggered: the trigger type is not observable here
- that the schedule will tick in the future: a declared cadence is not a promise

Remediation (needs an administrator, not applied): `wevtutil sl Microsoft-Windows-TaskScheduler/Operational /e:true`

Research only: no orders, no credentials, no capital.
