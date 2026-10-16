# WP-EDGE-12E — operational validation

**Window:** 2026-10-13T11:23:38Z → 2026-10-16T06:25:56Z (67.0384 h) · cadence 900 s, phase +653000 ms (from the registration)

Three levels, kept apart because a reader conflates them readily: a trigger that fired is
a property of the calendar, an observation that was made is a property of a process, and a
day that is admissible is a property of the store. Only the third may be compared with an
admission criterion.

## 1. Level one — triggers fired

|  |  |
| --- | --- |
| expected instants | 269 |
| answered by a tick | 243 |
| never answered | 26 |
| answered + lost = expected | True |

| cause | instants |
| --- | --- |
| `HOST_DOWN` | 1 |
| `NO_SESSION` | 24 |
| `SILENT_UNATTRIBUTABLE` | 1 |
| `SLEEP` | 0 |

> an instant with no host-side record stays SILENT_UNATTRIBUTABLE; the operational log that would name its cause is disabled on this host, which is a limit of the evidence rather than of the attribution

## 2. Level two — observations made

|  |  |
| --- | --- |
| slot-consuming ticks | 201 |
| of which OBSERVED | 198 |
| of which NO_NEW_DATA | 3 |
| fired and refused | 45 |

> this level counts processes, not instants: an on-demand run of the same task produces a real observation and does not answer a scheduled instant

| outcome | ticks |
| --- | --- |
| `ALREADY_OBSERVED` | 7 |
| `ALREADY_RUNNING` | 2 |
| `DISK_BUDGET_EXCEEDED` | 45 |
| `NO_NEW_DATA` | 3 |
| `OBSERVED` | 198 |

## 3. Level three — days admissible

|  |  |
| --- | --- |
| prospectively observed days | 1 |
| required | 60 |
| remaining | 59 |
| densely covered but backfilled | 228 |
| epoch |  |

> only this level may be compared with an admission criterion, and reaching it makes a later decision possible without making it

## 4. Bars, continuity, latency, storage

|  |  |
| --- | --- |
| new bars stored | 999 |
| missing bars reported | 0 |
| ticks reporting a stale series | 0 |
| market requests | 957 |
| silences over the declared bound | 1 |
| worst silence | 23418.872 s |
| highest severity | CRITICAL |
| median tick | 36.264 s |
| p95 tick | 71.946 s |
| maximum tick | 349.035 s |
| ticks over the interval | 0 |
| refused ticks | 45 |
| lowest free space | 0.8302 GiB |
| disk status counts | {'CRITICAL': 45, 'HEALTHY': 184, 'WARNING': 26} |
| ticks with errors | 47 |

## 5. Per day

| day | expected | ticks | observed | refused | new bars | median s | coverage |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-10-13 | 51 | 57 | 35 | 13 | 150 | 29.918 | 0.7451 |
| 2026-10-14 | 96 | 92 | 60 | 32 | 369 | 43.941 | 0.625 |
| 2026-10-15 | 96 | 80 | 77 | 0 | 381 | 36.915 | 0.8021 |
| 2026-10-16 | 26 | 26 | 26 | 0 | 99 | 38.441 | 1.0 |

## 6. Invariants

|  |  |
| --- | --- |
| ticks claiming an order | 0 |
| ticks not marked hypothetical | 0 |
| promotions recorded | ['NONE'] |

## 7. What this reading is not

It is not the admission test: 60 prospective days are not observed here, and nothing in
this file may be read as one. It is also not WP-EDGE-04R's continuity audit — that file
attributes every instant of its own frozen window from a committed snapshot, this one
reads the live lane over a window declared above. Where they disagree, the disagreement
is the finding.

Research only: no orders, no capital, no promotion.
