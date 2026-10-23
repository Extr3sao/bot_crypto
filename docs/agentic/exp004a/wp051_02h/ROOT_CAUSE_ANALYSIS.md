# WP-051-02H — root cause analysis

**Question:** why did the forward store stop at 2026-10-22T18:00Z?

**Answer, in one sentence:** It did not. The store 02G measured is a copy of data/forward made inside that package's worktree for a rehearsal, and a copy stops when the copying stops. The live store kept growing; the real interruption was elsewhere and shorter.

## What was actually true, and how it was measured

| Claim | Verdict | Evidence |
|---|---|---|
| `RC1` the instant 02G named was a copy, not the live store | **CONFIRMED** | `{"claimed_last_bar_utc": "2026-10-22T18:00:00Z", "live_last_bar_is_newer": true, "live_last_bar_utc": "2026-10-23T05:00:00.000Z", "worktree_copy": "data/forward/ is git-ignored; the 02G worktree holds a copy"}` |
| `RC2` the live store has a real hole, and its cause was the disk guard | **CONFIRMED** | `{"blocked_ticks_in_window": 34, "first_blocked_utc": "2026-10-22T18:10:56.000Z", "last_blocked_utc": "2026-10-23T05:55:56.000Z", "min_free_gib": 0.0, "reason": "0.4797 GiB free is below the 2147483648 byte critical floor: the tick refused before making a market request"}` |
| `RC3` the observer resumed by itself, without any intervention | **CONFIRMED** | `{"audited_at_utc": "2026-10-23T06:38:27.532Z", "block_episode": {"blocked_ticks": 1, "first_blocked_start_utc": "2026-10-23T05:55:56.000Z", "last_block_free_gib": 0.4797, "last_block_health": "BLOCKED", "last_block_reason": "0.4797 GiB free is below the 2147483648 byte critical floor: the tick refused before making a market request", "last_blocked_start_utc": "2026-10-23T05:55:56.000Z"}, "episo…` |
| `RC4` the hole cost the declaration a whole day, and no repair is possible | **CONFIRMED** | `{"complete_days_by_asset": {"BTC": [], "ETH": [], "SOL": []}, "coverage_complete_reachable": false, "declared_days": 90, "declared_rows": 6480, "fraction_still_reachable": 0.988889, "lost_days_any_asset": ["2026-10-23"], "lost_days_by_asset": {"BTC": ["2026-10-23"], "ETH": ["2026-10-23"], "SOL": ["2026-10-23"]}, "reading": "COVERAGE_COMPLETE requires admissible_rows == declared_rows exactly. On…` |

## The interruption that was real

DISK_BUDGET_EXCEEDED: the observer's own storage guard refused to make a market request while the volume was below its critical free-space floor, and it said so in every tick it refused. Nothing was broken; nothing was fetched.

- refusals in the audited window: **34**
- first refusal: `2026-10-22T18:10:56.000Z`
- lowest free space seen: **0.0 GiB** (the observer's critical floor is 2 GiB)
- the refusal's own words: _0.4797 GiB free is below the 2147483648 byte critical floor: the tick refused before making a market request_
- the worst episode put the store quiet for **345.02 min** between the last tick that added bars and the tick that resumed them (`{'new_bars': 3, 'run_id': 'FWD-EDGE04-20261022T234500Z', 'started_at_utc': '2026-10-22T23:55:56.000Z'}` → `{'new_bars': 87, 'run_id': 'FWD-EDGE04-20261023T053000Z', 'started_at_utc': '2026-10-23T05:40:57.000Z'}`)
- the observer resumed by itself at `2026-10-23T06:10:58Z` with **9** bar(s), 902.0 s after the last refusal: nothing was done to it

## Why six hours passed before anyone could see it

the refusal reached alerts.jsonl and health.json, both of which are files that must be opened. The scheduler's last-result field carried exit 5 for hours and no one read that either. There was no push, and there is still none: C9.

## What it was not

- the scheduler was never disabled or unregistered
- no duplicate observer contended for the lease
- the provider did not fail: refused ticks made zero market requests
- the store was not corrupt: no corrupt line appears in the tick log
