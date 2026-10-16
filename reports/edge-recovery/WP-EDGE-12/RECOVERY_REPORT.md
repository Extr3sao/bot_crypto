# WP-EDGE-12D — recovery report

**Generated:** 2026-10-16T06:20:16Z

What survives a process dying, a session disappearing and a write being interrupted —
measured, over an isolated copy of the store, and read against the live lane's own logs.

## 1. The live lane, as it is

|  |  |
| --- | --- |
| ticks in the log | 254 |
| first tick | 2026-10-13T11:23:38Z |
| last tick | 2026-10-16T06:12:22Z |
| corrupt log lines | 0 |
| slot ledger rows / unique keys | 199 / 199 |
| the ledger is a set | True |
| median tick | 36.255 s |
| maximum tick | 349.035 s |
| ticks over the interval | 0 |
| silences over the declared bound | 1 |
| worst silence | 23418.9 s |
| alerts recorded | {'DISK_CRITICAL': 1, 'DISK_RECOVERED': 1, 'DISK_WARNING': 1, 'HEALTH_BLOCKED': 5, 'HEALTH_DEGRADED': 7, 'HEALTH_RECOVERED': 3, 'OBSERVATION_GAP': 1, 'OBSERVATION_STALLED': 1, 'PUBLICATION_PAUSED': 1} |
| derived re-reads | 158 row(s), 7 failure(s) |

### 1.1 The silences, one by one

| from | to | seconds | missed intervals |
| --- | --- | --- | --- |
| 2026-10-14T22:25:56Z | 2026-10-15T04:56:15Z | 23418.9 | 25 |

## 2. What the rehearsal proved

### `repeat_inside_the_same_slot` — `PASS`

Expected: ALREADY_OBSERVED with zero market requests and an unchanged store

```json
{
 "market_requests": 0,
 "outcome": "ALREADY_OBSERVED",
 "slot_seals": 1,
 "store_unchanged": true,
 "wall_seconds": 0.028
}
```

### `trigger_while_another_tick_holds_the_lease` — `PASS`

Expected: ALREADY_RUNNING, no market request, the store untouched

```json
{
 "holder": {
  "acquired_at": 1792104300,
  "campaign_id": "EDGE04_FORWARD_OBSERVER",
  "host": "rehearsal",
  "lease_version": "CAMPAIGN_LEASE_V1",
  "pid": 32236,
  "renewed_at": 1792104300,
  "stale_after_seconds": 300
 },
 "lease": {
  "acquired": false,
  "holder": {
   "acquired_at": 1792104300,
   "campaign_id": "EDGE04_FORWARD_OBSERVER",
   "host": "rehearsal",
   "lease_version": "CAMPAIGN_LEASE_V1",
   "pid": 32236,
   "renewed_at": 1792104300,
   "stale_after_seconds": 300
  },
  "lease_age_seconds": 30,
  "status": "ALREADY_RUNNING"
 },
 "market_requests": 0,
 "outcome": "ALREADY_RUNNING",
 "store_unchanged": true,
 "wall_seconds": 0.031
}
```

### `lease_left_by_a_crashed_process` — `PASS`

Expected: the lease is reclaimed by age and the tick proceeds

```json
{
 "lease": {
  "acquired": true,
  "holder": {
   "acquired_at": 1792105230,
   "campaign_id": "EDGE04_FORWARD_OBSERVER",
   "host": "DESKTOP-4CHO695",
   "lease_version": "CAMPAIGN_LEASE_V1",
   "pid": 32236,
   "renewed_at": 1792105230,
   "stale_after_seconds": 300
  },
  "previous_holder": {
   "acquired_at": 1792104300,
   "campaign_id": "EDGE04_FORWARD_OBSERVER",
   "host": "rehearsal",
   "lease_version": "CAMPAIGN_LEASE_V1",
   "pid": 999999,
   "renewed_at": 1792103940,
   "stale_after_seconds": 300
  },
  "status": "STALE_LEASE_RECLAIMED"
 },
 "lease_age_seconds": 360,
 "lease_status": "STALE_LEASE_RECLAIMED",
 "outcome": "NO_NEW_DATA",
 "previous_holder_pid": 999999,
 "wall_seconds": 42.629
}
```

### `bars_that_closed_while_the_observer_was_down` — `PASS`

Expected: the next tick recovers every removed bar that had closed by the declared market instant, and only those

```json
{
 "clock_instant_utc": "2026-10-15T23:15:30Z",
 "dropped": {
  "dropped_per_series": {
   "15m:BTC": 2,
   "15m:ETH": 2,
   "15m:SOL": 2,
   "1h:BTC": 2,
   "1h:ETH": 2,
   "1h:SOL": 2
  },
  "dropped_total": 12
 },
 "expected_recovery_per_series": {
  "15m:BTC": 2,
  "15m:ETH": 2,
  "15m:SOL": 2,
  "1h:BTC": 2,
  "1h:ETH": 2,
  "1h:SOL": 2
 },
 "market_instant_utc": "2026-10-15T22:33:09Z",
 "new_bars_reported": 12,
 "note": "the market instant is the first tick's, re-declared: the recovery is measured as the deficit being filled, not as whatever closed while the rehearsal ran",
 "outcome": "OBSERVED",
 "rows_after_drop": {
  "15m:BTC": 809,
  "15m:ETH": 809,
  "15m:SOL": 809,
  "1h:BTC": 5492,
  "1h:ETH": 5492,
  "1h:SOL": 5492
 },
 "rows_after_recovery": {
  "15m:BTC": 811,
  "15m:ETH": 811,
  "15m:SOL": 811,
  "1h:BTC": 5494,
  "1h:ETH": 5494,
  "1h:SOL": 5494
 },
 "rows_before_drop": {
  "15m:BTC": 811,
  "15m:ETH": 811,
  "15m:SOL": 811,
  "1h:BTC": 5494,
  "1h:ETH": 5494,
  "1h:SOL": 5494
 },
 "rows_restored_per_series": {
  "15m:BTC": 2,
  "15m:ETH": 2,
  "15m:SOL": 2,
  "1h:BTC": 2,
  "1h:ETH": 2,
  "1h:SOL": 2
 },
 "wall_seconds": 45.56
}
```

### `a_log_line_interrupted_mid_write` — `PASS`

Expected: the truncated line is counted and the lane still records its own row

```json
{
 "corrupt_log_lines": 1,
 "outcome": "NO_NEW_DATA",
 "partial_line_still_present": true,
 "rows_after": 6,
 "rows_before": 5,
 "wall_seconds": 42.187
}
```

### `a_duplicated_slot_seal` — `PASS`

Expected: the duplicate is dropped and the slot ledger behaves like a set

```json
{
 "daily": {
  "2026-10-15.json": {
   "hypothetical": true,
   "new_bars": 15,
   "order_sent": false,
   "slots": 3,
   "ticks": 4
  }
 },
 "duplicates_dropped": 1,
 "rows_after_repair": 4,
 "unique_slot_keys": 4
}
```

### `a_tick_against_its_own_interval` — `PASS`

Expected: every rehearsal tick fits inside the interval with room for its successor

```json
{
 "interval_seconds": 900,
 "lease_shorter_than_the_interval": true,
 "lease_stale_after_seconds": 300,
 "maximum_seconds": 56.398,
 "note": "the wall figures come from a stopwatch around the call; the reported ones are wall_clock minus the pinned clock and are kept only as a cross-check, because a tick that takes its start from an injected clock cannot time itself",
 "reported_durations_seconds": [
  215.963,
  6.026,
  -683.927,
  -1541.287,
  -2395.676,
  -3253.46
 ],
 "wall_seconds": [
  56.398,
  0.028,
  0.031,
  42.629,
  45.56,
  42.187
 ]
}
```

## 3. What still cannot be proved here

* a **real sign-in absence** mid-pass: provoking one would end the session this work runs
  in. The property is `BOUNDED_NOT_REMOVED`, and what bounds it is the logon trigger plus
  the measured recovery latency, not this rehearsal.
* a **real reboot**: the host's reboots are in the evidence, but a rehearsal cannot schedule
  one without taking the machine down.
* the **attribution of an off-cadence launch**: the run log records the arguments a launch
  was invoked with, and an on-demand `schtasks /run` uses the same arguments as the
  scheduler. The operational log that separates them is disabled (needs an administrator).

Research only: no orders, no capital, no promotion.
