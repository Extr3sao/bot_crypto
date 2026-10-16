# WP-EDGE-12D — continuity matrix

**Generated:** 2026-10-16T06:30:47Z · **Verdict:** `CONTINUITY_MATRIX_COMPLETE`

Nine properties. Each row names where it was exercised: a rehearsal step that drove the
real observer over a copy of the store, or a live reading. A property that could not be
exercised says so and says why; nothing here passes because the design intends it.

| property | evidence | where | verdict | detail |
| --- | --- | --- | --- | --- |
| `IDEMPOTENT_SLOT` | REHEARSED_ON_THE_RUNTIME | `repeat_inside_the_same_slot` | `PASS` | outcome ALREADY_OBSERVED with 0 market request(s), store unchanged True |
| `SINGLE_INSTANCE` | REHEARSED_ON_THE_RUNTIME | `trigger_while_another_tick_holds_the_lease` | `PASS` | outcome ALREADY_RUNNING while another holder's lease was live, store unchanged True |
| `STALE_LEASE_RECLAIM` | REHEARSED_ON_THE_RUNTIME | `lease_left_by_a_crashed_process` | `PASS` | lease status STALE_LEASE_RECLAIMED after an 360 s old lease |
| `RESUME_AFTER_RESTART` | REHEARSED_ON_THE_RUNTIME | `bars_that_closed_while_the_observer_was_down` | `PASS` | 12 bar(s) removed, next tick reported new_bars=12 outcome=OBSERVED |
| `RESUME_AFTER_ABSENT_SESSION` | OBSERVED_LIVE_AND_BOUNDED | `WP-EDGE-04R SESSION_INDEPENDENCE.json + the logon-trigger probe in this pass` | `BOUNDED_NOT_REMOVED` | the absence itself cannot be removed without a privilege or a credential this package does not have; the logon trigger is UNKNOWN on this host and the worst live gap was 23418.9 s |
| `INCOMPLETE_WRITE_SURVIVAL` | REHEARSED_ON_THE_RUNTIME | `a_log_line_interrupted_mid_write` | `PASS` | corrupt_log_lines=1, partial line preserved True |
| `LEDGER_RECONCILIATION` | REHEARSED_ON_THE_RUNTIME_AND_READ_LIVE | `a_duplicated_slot_seal + the live slot ledger` | `PASS` | 1 duplicate(s) dropped; the live ledger holds 200 row(s) and 200 unique key(s) |
| `TIMEOUT_HANDLING` | REHEARSED_ON_THE_RUNTIME_AND_READ_LIVE | `a_tick_against_its_own_interval + the live run log` | `PASS` | rehearsal maximum 56.398 s of wall clock against a 900 s interval; live maximum 349.035 s with 0 tick(s) over it |
| `MISSED_TRIGGER_DETECTION` | READ_LIVE | `the live run log and alerts.jsonl` | `DETECTED` | 1 silence(s) over the declared bound, worst 23418.9 s; alerts recorded: {'DISK_CRITICAL': 1, 'DISK_RECOVERED': 1, 'DISK_WARNING': 1, 'HEALTH_BLOCKED': 5, 'HEALTH_DEGRADED': 7, 'HEALTH_RECOVERED': 3, 'OBSERVATION_GAP': 1, 'OBSERVATION_STALLED': 1, 'PUBLICATION_PAUSED': 1} |

Required: 9 · missing: none · not passing: ['RESUME_AFTER_ABSENT_SESSION', 'MISSED_TRIGGER_DETECTION'].

## The rehearsal, step by step

Verdict `REHEARSAL_PASS` over 9 step(s); failures: none.

| step | property | verdict |
| --- | --- | --- |
| `copy_the_store` | `BASELINE` | `PASS` |
| `first_tick` | `BASELINE` | `PASS` |
| `repeat_inside_the_same_slot` | `IDEMPOTENT_SLOT` | `PASS` |
| `trigger_while_another_tick_holds_the_lease` | `SINGLE_INSTANCE` | `PASS` |
| `lease_left_by_a_crashed_process` | `STALE_LEASE_RECLAIM` | `PASS` |
| `bars_that_closed_while_the_observer_was_down` | `RESUME_AFTER_RESTART` | `PASS` |
| `a_log_line_interrupted_mid_write` | `INCOMPLETE_WRITE_SURVIVAL` | `PASS` |
| `a_duplicated_slot_seal` | `LEDGER_RECONCILIATION` | `PASS` |
| `a_tick_against_its_own_interval` | `TIMEOUT_HANDLING` | `PASS` |

> no row passes because the design intends it: each one names either a rehearsal step or a live reading, and the rows that could not be exercised say so

Research only: no orders, no capital, no promotion.
