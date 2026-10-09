# RFC-047 — INDEPENDENT VERIFICATION

- **status**: `PASS`
- **taken at**: 2026-10-09T19:58:50Z
- **verifier**: `scripts/rfc047_verify.py` — imports nothing from the builder, the ledger or the ingestion component
- **checks**: 16 (0 failed, 0 unverified)
- **FALSE_SUCCESS**: `0`
- **false accusations**: `0`

## What was recomputed here rather than believed

| recomputation | result |
| --- | --- |
| slots | `84` |
| slots_declared_by_the_period | `84` |
| windows_states | `{"WIN_EVENT_CONFIRMED_SCHEDULED": 0, "WIN_EVENT_CONFIRMED_MANUAL": 0, "WIN_EVENT_PARTIAL": 0, "WIN_EVENT_CONFLICT": 0, "PENDING_EVENT_COMPLETION": 0, "WIN_EVENT_UNAVAILABLE": 0, "PRE_ENABLE_NOT_OBSERVABLE": 84}` |
| records_in_the_store | `0` |
| slots_with_an_external_confirmation | `0` |
| channel_enabled_per_the_host | `false` |
| monitor_tasks_on_the_host | `["TradingAgentic-ALPHA002-Capture", "TradingAgentic-CAP004-Campaign", "TradingAgentic-CAP004D-HealthWatch", "TradingAgentic-ST6-Forward"]` |

## Checks

| check | status | detail |
| --- | --- |
| `channel_state_matches_the_host` | PASS | {'audit_says_enabled': False, 'host_says_enabled': False, 'read_at_utc': '2026-10-09T19:58:49Z'} |
| `declared_grid_recomputed` | PASS | {'slots_declared_by_the_period': 84, 'slots_in_the_ledger': 84, 'bounds_agree': True, 'slots_per_day': 6} |
| `provenance_recomputed` | PASS | {'slots': 84, 'mismatches': [], 'count': 0} |
| `store_cannot_outlive_the_channel` | PASS | {'records_of_the_monitored_task': 0, 'coverage_from_utc': None, 'reading': 'a record of this task in the store implies an instant from which the channel could have produced it'} |
| `xml_fields_and_task_identity` | PASS | {'records': 0, 'incomplete': [], 'records_not_of_the_monitored_task': [], 'task': 'TradingAgentic-ST6-Forward', 'task_known_to_the_scheduler': 'TradingAgentic-ST6-Forward'} |
| `instance_identity` | PASS | {'problems': []} |
| `hashes_reproduce` | PASS | {'event_hash_problems': [], 'raw_evidence_problems': []} |
| `store_invariants` | PASS | {'records': 0, 'duplicate_keys': [], 'attempts_claiming_a_read_the_channel_could_not_serve': [], 'reads_of_a_channel_that_never_recorded': [], 'rotations_not_recorded': [], 'watermark_behind_the_store': False, 'declared_records_total': 0, 'watermark': {'Microsoft-Windows-TaskScheduler/Maintenance': 2713}, 'channel_state_as_reported': 'CHANNEL_DISABLED', 'channel_state_the_other_fields_imply': 'CHA |
| `ledger_contract` | PASS | {'ledger_version': 'ST6_SLOT_LEDGER_V1', 'slots': 84, 'missing_version_1_fields': {}, 'states_outside_the_vocabulary': [], 'torn_lines_in_the_store': 0, 'reading': 'the store is replaced atomically, so a torn line in it means a write that did not go through the temporary file, and a record may have been lost'} |
| `every_ended_slot_is_accounted_for` | PASS | {'slots_that_ended_unaccounted': [], 'slots_with_a_run_but_no_outcome': [], 'reading': 'a slot that has ended either produced its window, or carries the classification of the loss that explains it; there is no third state that may pass silently'} |
| `temporal_integrity` | PASS | {'slots_ahead_of_now_with_an_outcome': [], 'records_dated_in_the_future': [], 'confirmations_without_a_correlated_run': []} |
| `no_live_orders_or_credentials` | PASS | {'credential_values_found': [], 'standing_invariants': ['ST6_AUTONOMOUS_COLLECTION_ACTIVE', 'ECO-1 = OPEN', 'NEXT_CAMPAIGN = NOT_AUTHORIZED', 'LIVE_TRADING = DISABLED', 'TRADES_AUTHORIZED = 0', 'PROFITABILITY_VERIFIED = FALSE'], 'scanned': 13} |
| `no_additional_scheduled_task` | PASS | {'tasks_on_the_host': ['TradingAgentic-ALPHA002-Capture', 'TradingAgentic-CAP004-Campaign', 'TradingAgentic-CAP004D-HealthWatch', 'TradingAgentic-ST6-Forward'], 'the_task_of_the_campaign': 'TradingAgentic-ST6-Forward', 'occurrences_of_it': 1, 'tasks_this_rfc_would_have_created': [], 'probe': {'status': 'OK', 'exit_code': 0}, 'reading': "the campaign's own task is present exactly once and no task c |
| `report_claims_hold` | PASS | {'contradictions': []} |
| `deliverables_and_identifier` | PASS | {'missing': [], 'registry_entry': {'state': 'OCCUPIED', 'declaration_strength': 'TRACKED_DOCUMENT', 'declared_in_tracked_docs': ['docs/rfc/RFC-047_ST6_SCHEDULER_PROVENANCE.md'], 'artefacts_versioned': True, 'artefact_count': 2, 'occupant': 'RFC-047 ST-6 SCHEDULER PROVENANCE & INDEPENDENT EXECUTION EVIDENCE', 'status': 'RFC047_BLOCKED_HOST_PERMISSIONS', 'approved_at': None, 'approval_record': None, |
| `runtime_chain_is_honest` | PASS | {'links': 6, 'external_trigger_available': False, 'external_trigger_confirmed': False, 'confirmed_slots_recomputed_here': 0, 'status': 'RFC047_RUNTIME_CORRELATION_PARTIAL_INTERNAL_AND_SERVICE_ONLY'} |

## Negative controls — the eighteen cases of the test plan

Baseline of the unmutated artefacts: `PASS`.

| case | expected | observed | as required |
| --- | --- | --- | --- |
| an internal run claiming the schedule with no Windows event | REJECT | REJECTED | yes |
| a Windows event belonging to another task | REJECT | REJECTED | yes |
| two instances with neighbouring timestamps | REJECT | REJECTED | yes |
| a manual execution presented as scheduled | REJECT | REJECTED | yes |
| a start event with no completion | REJECT | REJECTED | yes |
| a completion event that arrives late | REJECT | REJECTED | yes |
| a duplicated EventRecordID | REJECT | REJECTED | yes |
| a rotation that happened before the read | REJECT | REJECTED | yes |
| the channel disabled during a run | REJECT | REJECTED | yes |
| a read refused for lack of permission | REJECT | REJECTED | yes |
| manipulated event XML | REJECT | REJECTED | yes |
| a corrupt ledger | REJECT | REJECTED | yes |
| a fabricated timestamp | REJECT | REJECTED | yes |
| market evidence that is absent | REJECT | REJECTED | yes |
| a process executed without collecting | REJECT | REJECTED | yes |
| a valid collection without external provenance | ACCEPT | ACCEPTED | yes |
| a restart during persistence | REJECT | REJECTED | yes |
| a future slot counted as lost | REJECT | REJECTED | yes |

- manipulations rejected: **17**
- manipulations accepted by mistake: **0**
- honest states refused by mistake: **0**

> A verifier that shared code with the builder would only be repeating an opinion. This one
> re-derives the channel's state from the host, the slot grid from the period, every
> classification from the raw evidence, and every hash from the bytes.
