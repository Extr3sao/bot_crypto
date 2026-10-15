# WP-EDGE-04R — availability of the forward observer, and why triggers were lost

Every number below is re-derivable offline from `evidence/OS_CONTINUITY_EVIDENCE.json` and the lane's own tick log.

## 1. The window

| | |
| --- | --- |
| From | 2026-10-13T11:23:38Z |
| To | 2026-10-15T18:31:46Z |
| Length | 55.135 h |
| Schedule interval | 900 s |
| Measured phase | +656000 ms into the interval |

## 2. Trigger loss, attributed

| | count |
| --- | --- |
| Expected trigger instants | 221 |
| Answered by a tick | 195 |
| Of those, fired and refused | 43 |
| Never answered by any process | 26 |
| **Total lost** | **69** |

| Cause of a trigger that no process answered | instants |
| --- | --- |
| `HOST_DOWN` | 1 |
| `NO_SESSION` | 24 |
| `SILENT_UNATTRIBUTABLE` | 1 |

Recorded host states behind those buckets: 2 boots, 2 shutdowns, 3 session transitions, **0 sleep/resume pairs**.

> A local sleep hypothesis would need a sleep record. There were 0.

## 3. Availability

| | |
| --- | --- |
| Host down | 0.127 h |
| Host up, no interactive session | 6.355 h |
| Schedulable fraction of the window | 0.8824 |

| absence window | reason | seconds | first tick after | recovery latency |
| --- | --- | --- | --- | --- |
| 2026-10-14T22:29:37Z → 2026-10-15T04:50:54Z | logoff with no sign-in after it, until the next one | 22876.438 | 2026-10-15T04:56:15Z | 321.41 s |
| 2026-10-14T22:33:49Z → 2026-10-14T22:41:14Z | shutdown and boot recorded by Kernel-General | 444.478 | 2026-10-15T04:56:15Z | None s |
| 2026-10-14T22:43:07Z → 2026-10-14T22:43:21Z | shutdown and boot recorded by Kernel-General | 14.047 | 2026-10-15T04:56:15Z | None s |

## 4. Per-day reading

| day | expected | consumed | refused | no session | host down | sleep | silent | coverage of expected |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-10-13 | 51 | 37 | 13 | 0 | 0 | 0 | 1 | 0.7255 |
| 2026-10-14 | 96 | 60 | 30 | 5 | 1 | 0 | 0 | 0.625 |
| 2026-10-15 | 74 | 55 | 0 | 19 | 0 | 0 | 0 | 0.7432 |

## 5. Storage

| | |
| --- | --- |
| Tick storage readings | 207 |
| Lowest free space seen | 0.8302 GiB at 2026-10-13T11:23:38Z |
| Hours below the critical floor | 10.764 |
| Ticks refused by the guard | 45 |
| Lane tree | 11.83 MiB of a declared 256.0 MiB budget |
| Relocation verdict | `NO_VOLUME_WITH_CAPACITY` |

| volume | filesystem | capacity GiB | free GiB | used % |
| --- | --- | --- | --- | --- |
| C:  | NTFS | 237.53 | 7.83 | 96.7 |
| G: Google Drive | FAT32 | 237.53 | 7.44 | 96.87 |
| (none)  | NTFS | 0.83 | 0.05 | 93.6 |
| (none)  | FAT32 | 0.09 | 0.01 | 93.1 |

Physical disks: 1 — KXG60ZNV256G KIOXIA (SSD, 238.47 GiB)

## 6. Checks

| check | verdict | detail |
| --- | --- | --- |
| `every_answered_instant_is_a_tick` | PASS | 195 answered instants = 152 slot-consuming + 43 refused |
| `answered_and_unanswered_account_for_every_instant` | PASS | 195 answered + 26 unanswered = 221 expected |
| `every_unmatched_instant_has_a_recorded_cause` | PASS | 26 unanswered instants, 26 attributed |
| `sleep_cause_is_claimed_only_with_a_sleep_record` | PASS | 0 sleep attributions against 0 recorded sleep/resume pairs |
| `coverage_threshold_unchanged` | PASS | the lane's per-day coverage floor is still 0.9 |
| `forward_requirement_unchanged` | PASS | the admission requirement is still 60 prospective days |
| `no_tick_claims_an_order` | PASS | 207 tick records read, 0 of them record an order |
| `every_tick_marks_itself_hypothetical` | PASS | 0 tick records claim a non-hypothetical result |

**Audit verdict: `AUDIT_PASS`.**

## 7. Re-checking this reading

```bash
python scripts/edge04r_continuity.py --offline --reports reports/edge-recovery/WP-EDGE-04R --until 2026-10-15T18:31:46Z
python scripts/edge04r_verify.py --reports reports/edge-recovery/WP-EDGE-04R --repo .
```

The instant is declared because it is part of what the record says: the same frozen inputs plus this instant reproduce `evidence/EDGE04R_CONTINUITY_AUDIT.json` byte for byte, while the same command without it would end the window at whatever time the reader happened to run it. An offline run with no `--until` reads the instant back from that same file, so it reproduces the record it re-derives; a new reading declares a new one.

Host evidence collected at 2026-10-15T18:32:24.6025896Z on DESKTOP-4CHO695; errors in that collection: 0.

Research only: hypothetical marks, no orders, no capital, no promotion.
