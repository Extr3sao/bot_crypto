# WP-EDGE-04 — EDGE04_AUTONOMOUS_EXECUTION_REPORT.md

**What this is.** The FASE 7 record: the window in which the autonomous forward observer ran
against the real runtime, and the seven things it was required to demonstrate. Every row below is a
tick that really ran on this host, taken from `data/forward/edge04/runs.jsonl`, `slots.jsonl` and
`alerts.jsonl` — not from a rehearsal, not from a scripted source, and not from anybody's memory.
The tick-by-tick table is generated into `evidence/FASE7_TIMELINE.md`; this document says what it
means.

Window: **2026-10-13 11:23:27Z → 15:08:17Z** (~3 h 45 m of the lane's life, of which 2 h 5 m were
unattended scheduled ticking). Data: public Binance klines only. Orders: none, ever.

Research only. Public market data, no credentials, no orders, no capital, no promotion.

---

## 0. What was running

| | |
| --- | --- |
| Task | `TradingAgentic-EDGE04-Forward` (Windows Task Scheduler) |
| Command | `.venv\Scripts\python.exe scripts\edge04_observer.py --scheduled --due` |
| Working directory | the repository root |
| Cadence | every 15 min; observed firings at `:10:55Z`, `:25:55Z`, `:40:55Z`, `:55:55Z` |
| Installed / enabled | `true` / `true` (read back from `schtasks`, not from the installer's return value) |
| Ticks recorded | **22** — 17 `SCHEDULED`, 5 `MANUAL` |
| Outcome histogram | `OBSERVED` 14, `ALREADY_OBSERVED` 3, `NO_NEW_DATA` 3, `ALREADY_RUNNING` 2 |
| Slot seals | **16**, 16 distinct, none duplicated |
| Bars appended by the lane | **51** (68 market requests) |
| Health at the close of the window | `DEGRADED` — one reason: the measured growth rate is volatile |
| Lane bytes / budget | 2 998 142 / 268 435 456 (1.1 %) |

`DEGRADED` is the honest reading, not an incident: the lane is hours old, its measured growth is
dominated by the one-off 2.45 MB publication and by the day's file, so the coefficient of variation
is 0.556 and **no forecast is published** (`days_to_budget: null`). A number would have had to be
invented, and the lane is built so that it is not.

## 1. Does the scheduler really fire? — **EXERCISED**

17 scheduled ticks, none of them started by a person or by an agent session, at the task's own
cadence. Consecutive scheduled firings observed:

| at (UTC) | slot | outcome | new bars | requests | exit |
| --- | --- | --- | --- | --- | --- |
| 12:10:55 | 12:00Z | `OBSERVED` | 6 | 7 | 0 |
| 12:25:55 | 12:15Z | `OBSERVED` | 3 | 4 | 0 |
| 12:40:55 | 12:30Z | `OBSERVED` | 3 | 4 | 0 |
| 14:40:55 | 14:30Z | `OBSERVED` | 3 | 4 | 0 |
| 14:55:55 | 14:45Z | `OBSERVED` | 3 | 4 | 0 |

The exit code is the outcome, and the scheduler's own last-result field carries it, so the task's
state alone tells an operator whether the lane ingested, refused or found nothing.

## 2. A newly closed bar, ingested — **EXERCISED**

The 12:10:55Z tick stored **6** newly closed bars — the `1h` close at 12:00Z and the `15m` close at
12:00Z, for BTC, ETH and SOL — and the 14:55:55Z tick stored **3**. Only closed bars are ever
requested: `expected_closed_bars()` computes the newest bar that can have closed at the tick's own
market instant, and the `15m`-only ticks show it (4 requests, 3 bars) against the `1h`-boundary
ticks (7 requests, 6 bars).

## 3. A trigger with nothing new — **EXERCISED**

| at (UTC) | mode | outcome | new / expected / missing | requests | exit |
| --- | --- | --- | --- | --- | --- |
| 11:24:27 / 11:25:55 / 11:40:56 | scheduled (`--due`) | `ALREADY_OBSERVED` | 0 / — / — | **0** | 0 |
| 14:45:00 | manual | `NO_NEW_DATA` | 0 / 0 / 0 | 1 | 0 |
| 15:07:24 | manual (recovery) | `NO_NEW_DATA` | 0 / 0 / 0 | 1 | 0 |

`NO_NEW_DATA` is a recorded result: the whole pipeline ran (frozen pin, ingest, shadow, parity) and
there was nothing to append. `ALREADY_OBSERVED` is the cheaper path — zero market requests, zero
evidence written — and it is what makes a 15-minute cadence affordable.

## 4. Recovery after a controlled interruption — **EXERCISED**

This is the one demonstration that was done by *breaking* something on purpose, so it is reported in
full.

| when (UTC) | what |
| --- | --- |
| 15:02:07 | a manual tick started (pid 49528) |
| 15:02:21 | `kill -9` — 14 s in, mid-tick |
| 15:02:21 | lease left behind: `pid 1308`, `renewed_at 1791903728`, `stale_after_seconds 300`. No run row was written; the process left no log line at all |
| 15:03:54 | the next tick **refused**: `ALREADY_RUNNING`, exit 2, `market_requests: 0`, duration 0.002 s |
| 15:07:24 | the tick after the bound **reclaimed**: `STALE_LEASE_RECLAIMED`, `previous_holder.pid = 1308`, then ran to completion — `NO_NEW_DATA`, the lease released |

The store was fingerprinted before the kill and reconstructed after it: the killed tick had appended
**exactly 6 bars** (one per series: the `1h` and `15m` closes at 15:00Z for BTC/ETH/SOL) before it
died, and the recovery tick found them at the store's high-water mark and appended **nothing** —
`expected_new_bars: 0`, `missing_bars: 0`. A killed process therefore costs *attribution* (those 6
bars have no run row claiming them) and costs neither data nor a duplicate. The reconstruction, not
an assumption: trimming the last bar from each series reproduces the pre-kill digest byte for byte.

**The first attempt of this rehearsal did not behave like that, and the difference is the point.**
It crashed: `os.kill(pid, 0)` on this platform answers a stale pid with `WinError 87`, raised as
`SystemError`, which the probe did not catch, so the trigger died with a traceback and exit 1 — no
refusal, no reclaim, no explanation. Fixed in `campaign_lock._pid_probe()` (returns `None`, so the
lease's age rule decides) with a regression test; see `EDGE04_RUNTIME_AUDIT.md` §10b.6. A rehearsal
that had only been *designed* would have shipped that.

## 5. No duplicates — **EXERCISED**

* 16 slot seals, 16 distinct slot keys, 0 duplicate rows (`duplicate_slots: []`), 0 corrupt lines in
  `runs.jsonl`, `slots.jsonl` and `alerts.jsonl`.
* A repeat tick inside a drained slot writes its own run row and **no second seal**:
  `slot_sealed: false`, `slot_seal_held_by` naming the tick the ledger already holds.
* The one duplicate seal this lane ever produced was written by the very first manual probe, before
  the seal rule existed. It is gone and the removal is auditable: `--repair-slot-ledger` dropped it
  and wrote `slot_ledger_repair.json` —

  ```
  rows_before 15 -> rows_after 14
  dropped: [{"slot_key": "2026-10-13T14:30Z", "run_id": "FWD-EDGE04-20261013T143000Z",
             "outcome": "NO_NEW_DATA", "at_utc": "2026-10-13T14:45:00Z"}]
  sha256_before 3aa174f9dd5faefa902e024ed770a3f36a29f3b2b4b4e0305913b99e58a5c12e
  sha256_after  e2c3390d0fb567ccb9d7fd03cb654dd58d5870f962ff8c5cbc5495acda7e0dc3
  ```

  The *first* row of that slot — the scheduled tick's `OBSERVED` seal — was kept, and the run log was
  not rewritten: both ticks really ran and both keep their rows.
* The same episode exposed a second duplicate path and it is closed: the day file had let the later
  tick overwrite the interval's numbers. `daily/2026-10-13.json` disagreed with the ledger, the
  independent verifier refused it, and the **next scheduled tick** corrected it (slot
  `14:30Z`: `NO_NEW_DATA`/0 → `OBSERVED`/3, `at_utc 14:41:45Z` — the seal's own). The day's slot
  table is now derived from the seal on every tick.

## 6. A report is published — **EXERCISED, with one named exception**

`publication/LATEST.json` names **13** artefacts with their digests; the verifier recomputes all 13
from disk and they answer (`PUBLICATION_SWAPPED_ATOMICALLY`). The heavy set is rendered once per
24 h, not per tick, and published by pointer over a staging tree, so a torn write cannot leave a
half-written report.

Offline reproduction, re-run today from the preserved observation with no network:

```
cumulative   CUMULATIVE.md        byte_identical: false
daily        DAILY_2026-10-13.md  byte_identical: true
daily_rollup DAILY_REPORTS.json   byte_identical: true
summary      CUMULATIVE.json      byte_identical: true
```

Three of the four are byte-identical. `CUMULATIVE.md` is **not**, and the difference is exactly one
line:

```
< Ledger rows on file: **228** (6 from the observation pass, 222 from the restart pass ...)
> Ledger rows on file: **12**  (6 from the observation pass, 6 from the restart pass ...)
```

`write_observability()` counts the rows of the ingest ledger *on disk* at the path the payload
names, so that line is a live reading, not a function of the preserved payload: it was 12 when the
report was published and it is 228 now. The reproduction property is real but it **expires**, and it
is stated here rather than claimed away. Fixing it belongs in the reporting module (the payload
would have to carry the count the publisher saw); it is recorded as an open item, not silently
tolerated.

## 7. Independent verification — **EXERCISED**

`scripts/edge04_verify.py`, which shares no code with the tick engine and reads only the artefacts:

```
verdict    VERIFY_PASS  (15/15)
self-test  SELF_TEST_PASS  (20/20 sabotages detected, 0 skipped)
```

`INDEPENDENT_VERIFICATION.json` carries the per-check detail and the sabotage matrix. Both the
verdict and the self-test are required: a pass with an undetected sabotage would mean a check that
cannot fail, and this run found exactly that — the "grow a bounded log past its cap" sabotage was
being caught incidentally by a byte-count comparison while the cap arm itself pointed at file names
the bundle never loads. Both were repaired (see `EDGE04_RUNTIME_AUDIT.md` §10b.10).

## 8. NOT_EXERCISED, and why

| Item | Status | Why |
| --- | --- | --- |
| Long unattended window (hours→days) | **NOT_EXERCISED** | 2 h 5 m of unattended scheduled firing was observed. Nothing here proves 60 days of it. |
| Logoff / reboot across a tick | **NOT_EXERCISED** | the task runs under `InteractiveToken`; making it survive logoff needs stored credentials, which this work package is not authorised to hold |
| Linux registration | **NOT_EXERCISED** | no Linux host; the runner is portable and the cron/systemd lines are in `EDGE04_SCHEDULER_DESIGN.md` §9 |
| A real provider outage | **NOT_EXERCISED** | the venue answered all day. `PROVIDER_UNAVAILABLE`, `STALE_DATA`, `MISSING_BARS`, `DISK_BUDGET_EXCEEDED`, `VERIFICATION_FAILED` and `RUNTIME_EXCEPTION` are exercised in the test suite and in the verifier's sabotage matrix, not live |
| A re-registration with stored credentials | **NOT_EXERCISED** | requires the owner's account credentials; deliberately out of scope |
| 60 forward days | **NOT_EXERCISED (0 of 60)** | see §9 |

## 9. Where the forward coverage actually stands

`coverage.json`, unchanged in its rule: a day counts only if every primary asset holds ≥ 90 % of the
bars the calendar expects and those bars reached the store while still fresh.

| | |
| --- | --- |
| Observation epoch | `2026-03-01T00:00:00Z` (the day after the frozen corpora end) |
| Prospective forward days | **0 of 60** (remaining 60) |
| Days with any stored data | 227 |
| Densely covered but backfilled | 226 |
| Store digest (6 series) | recorded per series in `coverage.json#store_digests` |
| Longest silence between slot-consuming ticks | 1 525.751 s (no gap event: the warning bound is 2 100 s) |
| Hours of unavailability | 0 |
| Bars appended by this lane | 51 |

Zero, and that is the correct number: the frozen corpora cover history up to the freeze, and only
bars that arrive while they are fresh count forward. A day on which the scheduler ran is not
automatically a forward day — that is the whole reason the coverage rule is separated from the run
log. **Reaching 60 days is a requirement of a later decision, not that decision**, and no artefact of
this lane can promote anything.

## 10. What would have made this report a false success

* A tick that failed and was written as a success — impossible by construction: the outcome
  vocabulary is separate from the exit code, and the exit code is derived from the outcome.
* A day counted because the scheduler fired — refuted by §9 (0 days, 227 with data).
* A duplicate bar or slot seal — refuted by §5, with the repair receipt naming the one that existed.
* A check that cannot fail — refuted by §7's self-test, and by finding one that could not.
* A rehearsal reported as a live run — the scripted venue exists for the tests and its store root is
  never `data/forward/edge03`.
* An inflated reading — refuted by the byte check (§0), after the reading's own ordering bug was
  found and fixed.
