# RFC-047 — ST-6 SCHEDULER PROVENANCE & INDEPENDENT EXECUTION EVIDENCE

| field | value |
| --- | --- |
| **CURRENT_HEAD** | c667683e2e1d8c4a1a55abca9ad1f06d25d9dd4c |
| **RFC047_STATUS** | RFC047_BLOCKED_HOST_PERMISSIONS |
| **WINDOWS_CHANNEL_BEFORE** | CHANNEL_DISABLED (enabled=False, retention=false, max_size_bytes=10485760, records=None, never recorded) |
| **WINDOWS_CHANNEL_AFTER** | CHANNEL_DISABLED (enabled=False, retention=false, max_size_bytes=10485760, records=None, never recorded); unchanged, because the change that would enable it was not applied |
| **HOST_PERMISSION_STATUS** | HOST_AUDIT_CHANGE_APPROVAL_REQUIRED |
| **LIVE_SCHEDULER_STATUS** | ST6_AUTONOMOUS_COLLECTION_ACTIVE: the task remains registered and enabled with its fifteen-minute cadence, and no configuration of it was touched |
| **REAL_EXECUTION_CORROBORATED** | False |
| **EXTERNAL_EVENTS_CAPTURED** | 0 |
| **EXTERNAL_EVENTS_MISSING** | every per-run record of this period: the operational channel is disabled and has never recorded, and the maintenance channel holds only maintenance identifiers (800 and 808), none of which describes a task's execution |
| **LEDGER_RECONCILIATION** | 84 slots, version-1 fields intact True, 0 disagreement(s), 84 slot(s) outside the reach of external evidence |
| **HISTORICAL_EVIDENCE_LIMITATIONS** | no per-run Windows record exists for any instant of this period and none can be recovered: the channel records from the moment it is enabled; 440 maintenance records were evicted by the circular policy before this audit read the log; the Security channel is not readable from this session, so nothing there could be consulted either; the candidate identifiers (100, 102, 107, 110, 200, 201) could not be verified against a single real record of this host, so they were never turned into classification rules; the scheduler's own register keeps only its most recent run, so a launch can be corroborated while it is still the most recent one, and not afterwards |
| **RETENTION_STATUS** | RFC047_EVENT_STORE_BOUNDED: 0 record(s), 0 byte(s) of original evidence; incremental by EventRecordID, deduplicated on write, watermark advanced only after a durable write, rotation and identifier resets recorded, refusals recorded, and the store preserved until the period closes |
| **NEGATIVE_TESTS** | 18 adversarial case(s) run against the real artefacts: 17 rejected, 0 accepted by mistake, 0 honest state(s) refused by mistake |
| **RUNTIME_TESTS** | RFC047_RUNTIME_CORRELATION_PARTIAL_INTERNAL_AND_SERVICE_ONLY: 5 of 6 links of the runtime chain are held by real artefacts; the external trigger is not among them |
| **INDEPENDENT_VERIFICATION** | PASS |
| **FALSE_SUCCESS** | 0 |
| **COMMITS** | 2 commit(s) touch the paths of this RFC, read from the repository's own history: 7b673f5 (2026-10-09) RFC-047: read the Windows event plane instead of letting the monitor's own account stand as proof; a709c88 (2026-10-09) feat(research): record the origin of every ST-6 run and stop losing slot evidence. The report is written after them, so CURRENT_HEAD names the head it was written at; only RFC-047's own files are committed by those commits, and the pending modifications of other work are left untouched. A defect found beside this RFC is repaired in a commit of its own and is recorded in section 14 of the document. |
| **BLOCKERS** | HOST_AUDIT_CHANGE_APPROVAL_REQUIRED: enable the Microsoft-Windows-TaskScheduler/Operational channel (wevtutil sl ... /e:true): the only configuration change RFC-047 contemplates was requested and not approved, and the unelevated attempt was refused with exit code 5 (Error al guardar la configuración o al activar el registro Microsoft-Windows-TaskScheduler/Operational. Acceso denegado.); without that change no external per-run record can exist, so no slot of this period can be corroborated run by run |
| **NEXT_GATE** | the real close of the ST-6 period at 2026-10-22T16:21:20Z, and — before it — the single command that would let the remaining slots of the period be corroborated as they happen: wevtutil sl Microsoft-Windows-TaskScheduler/Operational /e:true, with an elevated token |

## Standing invariants (unchanged)

- `ST6_AUTONOMOUS_COLLECTION_ACTIVE`
- `ECO-1 = OPEN`
- `NEXT_CAMPAIGN = NOT_AUTHORIZED`
- `LIVE_TRADING = DISABLED`
- `TRADES_AUTHORIZED = 0`
- `PROFITABILITY_VERIFIED = FALSE`

## What the reconciliation found

- declared slots: **84**
- slots with an external confirmation: **0**
- slots never observable: **84**
- runs in the ledger: **420** (corroborated by the scheduler's own register: **20**)
- disagreements between the builder and its inputs: **0**

## External evidence vocabulary

| state | slots |
| --- | --- |
| `PENDING_EVENT_COMPLETION` | 0 |
| `PRE_ENABLE_NOT_OBSERVABLE` | 84 |
| `WIN_EVENT_CONFIRMED_MANUAL` | 0 |
| `WIN_EVENT_CONFIRMED_SCHEDULED` | 0 |
| `WIN_EVENT_CONFLICT` | 0 |
| `WIN_EVENT_PARTIAL` | 0 |
| `WIN_EVENT_UNAVAILABLE` | 0 |

> No slot of this period can be called corroborated while the operational channel of the
> host is disabled and has never recorded. That is stated as a limit of the evidence and
> not as a property of the schedule: the monitor keeps collecting, and its own record of
> every slot is kept in `data/st6/ST6_SLOT_LEDGER.json`.
