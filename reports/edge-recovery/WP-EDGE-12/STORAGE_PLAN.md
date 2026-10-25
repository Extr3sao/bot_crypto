# WP-EDGE-12C — storage and resource continuity

**Generated:** EDGE12_CAPACITY_FORECAST_V1 · **Horizon:** 60 days · **Verdict:** `NO_USABLE_VOLUME_FOR_A_MOVE`

Sixty days of observation has to fit somewhere, and there are two unlike questions hiding
inside that: whether the *lane* fits, and whether the *volume* has room. They have
different answers and only the first one is this lane's to decide.

## 1. The lane's footprint and its two growth laws

The state root's logs are bounded, so they have a ceiling that can be summed instead of
extrapolated. The store is append-only and never pruned, so it has a rate instead.

| tree | bytes now |
| --- | --- |
| store | 5893043 |
| state | 7457176 |
| lane (as measured for this reading) | 13350219 |

### 1.1 Ceiling of the bounded logs

| log | rows now | bytes/row | rows kept | projected bytes |
| --- | --- | --- | --- | --- |
| `runs.jsonl` | 255 | 4305.02 | 2880 | 12398467 |
| `slots.jsonl` | 200 | 249.06 | 2880 | 717292 |
| `ledger/INGEST_LEDGER.jsonl` | 2436 | 816.89 | 4032 | 3293687 |
| `derived_refresh.jsonl` | 159 | 873.38 | 2880 | 2515326 |
| `alerts.jsonl` | 21 | 313.1 | 500 | 156547 |

| daily evidence | files now | mean bytes | files kept | projected bytes |
| --- | --- | --- | --- | --- |
| never truncated | 4 | 146448.25 | 366 | 53600059 |

**Ceiling: 72837412 bytes** against a declared lane budget of 268435456 bytes — within budget: **True**.

> a ceiling holds whatever the lane does; a fitted line holds only while the trend does, which is why the bounded logs are summed at their retention instead of extrapolated

### 1.2 Rate of the store

| series | rows | bytes | bytes/bar | bars/day | bytes/day |
| --- | --- | --- | --- | --- | --- |
| `1h:BTC` | 5502 | 1727630 | 314.0 | 24 | 7536.01 |
| `1h:ETH` | 5502 | 1709602 | 310.72 | 24 | 7457.37 |
| `1h:SOL` | 5502 | 1670356 | 303.59 | 24 | 7286.18 |
| `15m:BTC` | 842 | 264784 | 314.47 | 96 | 30189.15 |
| `15m:ETH` | 842 | 262030 | 311.2 | 96 | 29875.15 |
| `15m:SOL` | 842 | 258641 | 307.17 | 96 | 29488.76 |

**360 bars/day, 111832.62 bytes/day.**

> the store is append-only and never pruned, so its growth is bars-per-day times bytes-per-bar: both are measured here from the files on disk

## 2. The forecast

|  |  |
| --- | --- |
| store at the horizon | 12603000 bytes |
| state at the horizon (ceiling) | 72837412 bytes |
| lane at the horizon | 85440412 bytes |
| added over the horizon | 6709957 bytes (0.006249 GiB) |
| fits | True |

> the store is projected forward at the measured bytes per bar and bars per day; the state root is not projected at all, it is summed at its retention ceiling, because a bounded log has a ceiling and an unbounded store has a rate

> the volume's own time-to-critical is not published: the lane measured its free space, but the volume is shared with everything else on this machine and a number derived from this lane's slope would be an attribution the evidence does not support

## 3. The volume, which is the actual constraint

Guard status `HEALTHY` at `7.5323 GiB` free on `C:\Users\GVLLFR0035\Downloads\bot freebuff\data\forward\edge04`; critical floor 2.0 GiB.

| volume | fs | capacity GiB | free GiB | used % | usable for this store |
| --- | --- | --- | --- | --- | --- |
| C:  | NTFS | 237.5264 | 7.5328 | 96.83 | False |
| (none)  | NTFS | 0.832 | 0.0532 | 93.6 | False |
| (none)  | FAT32 | 0.0938 | 0.0065 | 93.1 | False |
| G: Google Drive | FAT32 | 237.5264 | 7.1561 | 96.99 | False |

Relocation verdict: **`NO_VOLUME_WITH_CAPACITY`**. Qualifying volumes: none.

### 3.1 The volume's own trajectory, as the lane saw it

|  |  |
| --- | --- |
| samples | 255 |
| span | 2.7933 days |
| first | 7.7587 GiB |
| last | 7.5282 GiB |
| minimum | 0.8302 GiB |
| delta | -0.2305 GiB |
| per day | -0.0825 GiB/day |
| status counts | {'CRITICAL': 45, 'HEALTHY': 184, 'WARNING': 26} |

> this is the volume's free space, not the lane's footprint: the volume holds whatever else lives on this machine, and a slope measured here is not a rate this lane caused

## 4. What the refusals cost

|  |  |
| --- | --- |
| ticks refused by the guard | 45 |
| slots those refusals touched | 43 |
| first refusal | 2026-10-13T20:25:56Z |
| last refusal | 2026-10-14T13:40:56Z |
| market requests made at a refusal | [0] |

> the guard refused before any market request, so a refusal costs a slot and returns no false observation; the market-request figures listed here are the measurement of that

## 5. The plan

1. **Do nothing to this lane.** Its ceiling is inside its declared budget and its store
   adds 0.006249 GiB over the horizon; moving it would
   change the free space the guard reads by less than the noise in that reading.
2. **Decide about the volume, as an operator.** The occupancy is 97 %. This lane is not
   what fills it and this package will not delete another workstream's data to make the
   number look better: that would be measuring a different thing and calling it capacity.
3. **Keep the guard where it is.** It refuses *before* any market request, so a full
   volume costs slots and never produces a false observation. Loosening it to buy slots
   would buy them with the one property that makes the refusals acceptable.
4. **Re-run `scripts/edge12_storage.py` after any change to what lives on this volume.**
   The lane's own readings are the free-space history on this host; nothing else records it.

Research only: no orders, no capital, no promotion.
