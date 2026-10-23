# WP-051-02H — run report

**Generated:** `2026-10-23T06:38:29.813Z` · **HEAD:** `819cb0d29f87b624fd982b5c581f4aea6e5993e0` · **Experiment certified:** `false`

## Recovery

- verdict: **OBSERVER_RUNNING**
- ticks since the reference instant: **50** (2026-10-22T18:00:00.000Z → 2026-10-23T06:25:58.000Z), outcomes `{"DISK_BUDGET_EXCEEDED": 34, "OBSERVED": 16}`
- refusals in that window: **34**, lowest free space **0.0 GiB**
- newest tick age: **696.5 s**
- first observation after the last refusal: `FWD-EDGE04-20261023T060000Z` at `2026-10-23T06:10:58Z`, **9 new bar(s)**

## The hole

- last bar before the reference instant: `2026-10-22T18:00:00.000Z` (lag 10.97 min)
- first bar after it: `2026-10-22T19:00:00.000Z` (lag 145.99 min, ['LATE', 'BEFORE_EFFECTIVE_FROM'])
- refusal episodes in the log: **23**; the worst one ran `2026-10-23T00:10:56.000Z` → `2026-10-23T05:25:57.000Z` (22 tick(s), lowest free space 0.0 GiB)
- **store silence: 345.02 min** between the last tick that added bars and the tick that resumed them
- recovery latency after the last refusal: `902.0 s`

## Coverage, against the declaration

- declared: **6480** rows over **90** days
- days already lost: **['2026-10-23']**
- rows still reachable: **6408 / 6480** = **0.988889** (required floor 0.9)
- `COVERAGE_COMPLETE` reachable: **False** — CEILING_BELOW_DECLARED

## Continuity

- verdict: **CONTINUITY_SATISFIED** over 10 requirement(s)
- blocking: `[]`

## Independent verification

- **PASS**, 17 checks, failed `[]`

## Root cause

DISK_BUDGET_EXCEEDED: the observer's own storage guard refused to make a market request while the volume was below its critical free-space floor, and it said so in every tick it refused. Nothing was broken; nothing was fetched.

Claims: `{"RC1": "CONFIRMED", "RC2": "CONFIRMED", "RC3": "CONFIRMED", "RC4": "CONFIRMED"}`
