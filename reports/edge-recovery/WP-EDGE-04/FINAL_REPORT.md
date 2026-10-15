# WP-EDGE-04 — FINAL_REPORT.md

**Mission.** Turn WP-EDGE-03 into an automatic, persistent and recoverable forward observer that
accumulates the 60 forward days the frozen contracts require, preserving the rules, thresholds and
admission conditions exactly — and that does not authorise PAPER or LIVE trading.

**Status.** The observer exists, is installed, is firing unattended every 15 minutes, ingests newly
closed bars, refuses to duplicate work, survives a hard kill, survives a real disk exhaustion,
publishes its evidence and is verified by a verifier that shares none of its code — and that
**refused the live lane twice in this session** before its two refusals were fixed. It has
accumulated **0 of 60 forward observation days** and 774 newly stored bars over 2 days 3 h 54 m,
which is what two days of a 60-day requirement looks like.

No `PASS`, `CERTIFIED`, `PRODUCTION_READY` or `READY_FOR_PAPER` is claimed, and none should be read
into anything below.

Research only. Public market data, no credentials, no orders, no capital, no promotion.

---

## 1. Is the scheduler really installed and working?

**Yes, and it is worth being precise about what "working" means here.** The task
`TradingAgentic-EDGE04-Forward` is registered with Windows Task Scheduler, `installed: true`,
`enabled: true`, state `Ready`, and — read back from `schtasks` itself, not from the installer's
return value — running every 15 minutes with `MultipleInstances=IgnoreNew` and
`StartWhenAvailable=true`.

Proof it fires rather than proof it exists: **188 scheduled ticks** ran with no human and no agent
session involved, and one of them fired *while this report was being written*. This session also
asked the scheduler to fire the task (`--run-task`) and read the answer back from the scheduler's own
fields: `last_run_time` moved and **`last_task_result` became `0`**, the exit code of the tick. Three
ticks followed from that interaction, all in the run log.

The caveat is not the task, it is the host: `InteractiveToken` plus a machine that sleeps. The last
24 h contained **75 of the 96 expected triggers**, and the longest silence between two ticks that
consumed a slot was **7 h 45 m** (the machine's night). That is the availability bound, measured
rather than asserted.

The trigger itself is a table of ticks in `evidence/FASE7_TIMELINE.md`, generated from the run log.

## 2. What process and configuration keeps it alive?

* **The OS task**, not a daemon and not an agent session:
  `C:\...\.venv\Scripts\python.exe scripts/edge04_observer.py --scheduled --due`, working directory
  the repository root, registered through the repository's *existing* supervisor
  (`scripts/cap004_supervisor.py`). No second orchestrator, no resident process, no Codex or ChatGPT
  session required.
* **One portable entry point**: `scripts/edge04_observer.py --scheduled --due`. Everything else
  (`--status`, `--task-status`, `--install`, `--uninstall`, `--run-task`, `--snapshot`,
  `--report-only`, `--repair-slot-ledger`) is operator surface over the same object.
* **The configuration**: 15-minute cadence, `IgnoreNew`, `StartWhenAvailable`, one-hour execution
  limit, `LeastPrivilege` + `InteractiveToken`. Timestamps are UTC everywhere; no local time appears
  in any artefact.
* **The recovery layer inside the tick**: a renewable file lease over `data/forward/edge04/lock/`
  (300 s bound), a frozen-ruleset pin checked before any request, a disk guard checked before any
  request, two bounded pipeline attempts with a 20 s delay, and idempotent slot sealing.

On a POSIX host the runner is portable and the registration is one cron line or one systemd timer
(`EDGE04_SCHEDULER_DESIGN.md` §9). **Not exercised here: no Linux host.**

## 3. How many bars and valid forward days have accumulated?

| | |
| --- | --- |
| Newly closed bars stored by this lane | **774** (`15m` BTC/ETH/SOL 130 each · `1h` BTC/ETH/SOL 128 each) |
| Market requests spent | 672 |
| Missing bars | 0 |
| Store total | 18 807 bars across 6 series |
| **Valid forward observation days** | **0 of 60** (60 remaining) |
| Days with any stored data | 229 |
| Densely covered but backfilled | 228 |
| Observation epoch | `2026-03-01T00:00:00Z` |

Zero is the correct number and it is not a defect. The frozen corpora are history; a day counts
forward only if every primary asset holds ≥ 90 % of the calendar's expected bars **and** those bars
reached the store while still fresh (within 30 min for `15m`, 2 h for `1h`). The best day so far is
**79.2 %** (2026-10-14) and the day before it 58.3 %; both are reported as misses, because 79 % is not
90 % and the rule has no rounding. A day on which the scheduler ran is not thereby a forward day —
that separation is the entire reason the coverage rule is kept apart from the run log.

Why the two days fell short is known rather than mysterious: the volume sat below its own 2 GiB
critical floor for ~17 hours (§4c) and the host was asleep for the rest of it.

## 4. Does it recover after restarts?

**Yes — demonstrated by breaking it, not by arguing about it.** A tick was hard-killed 14 s in
(`15:02:21Z`):

| when (UTC) | what happened |
| --- | --- |
| `15:02:21Z` | killed mid-tick; the lease was left behind (`pid 1308`, bound 300 s); no run row was written |
| `15:03:54Z` | the next tick **refused**: `ALREADY_RUNNING`, exit 2, **0 market requests**, 0.002 s |
| `15:07:24Z` | the tick after the bound **reclaimed**: `STALE_LEASE_RECLAIMED`, `previous_holder.pid = 1308`, ran to completion, released the lease |

The store was fingerprinted before the kill and reconstructed after it: the dead tick had appended
exactly **6 bars**; the recovery tick found them at the store's high-water mark and appended
**nothing** (`expected 0`, `missing 0`). So a crash costs *attribution* — those 6 bars have no run
row claiming them — and costs neither data nor a duplicate.

The first attempt at this rehearsal **crashed** instead of refusing, because this platform answers
`os.kill(pid, 0)` for a stale pid with `WinError 87` raised as `SystemError`, which the probe did not
catch. Fixed (`5b1e771`) with a regression test. A crashed trigger is worse than a refused one: the
schedule loses the observation *and* the record that would have explained it.

### 4b. Does it survive a real disk exhaustion?

**Yes, and it now has, 45 times.** Between `2026-10-13T20:25:56Z` and `2026-10-14T13:40:56Z` the
volume was at 1.81 GiB free — below the declared 2 GiB critical floor. Every trigger in that window
returned `DISK_BUDGET_EXCEEDED`, exit 5, **0 market requests, no slot consumed, no half-written
evidence**, and one `DISK_CRITICAL` alert (raised once for the episode, not once per tick). The
recovery is the ordinary path: the next healthy tick finds the store's high-water mark and re-fetches
what it missed, which is exactly why the bars it recovers carry a large measured latency (§4d). The
volume now has 10.58 GiB free and is `HEALTHY`.

### 4c. Is the loss of observation visible, or silently absorbed?

Visible. `continuity()` measures the silence between the ticks that *consumed a slot* — a trigger that
found its slot already sealed is not a gap in the observation. Over this window there were 141 such
ticks, 6 silences over the 2 100 s warning bound, and **66 683.8 s (18.5 h) of declared
unavailability**, each episode named with its own start and end. Two of those episodes are the host's
sleep, one is the disk refusal, and the report says which is which rather than reporting a single
"99 % uptime" that hides both.

### 4d. Latency: is a late bar smoothed into a fresh one?

No. Every tick records the close → store delay of the bars it pulled, and the forward rule reads that
number. The median tick reports a fresh-bar median of 658.6 s and the worst reports 27 658 s: those
large figures are the bars recovered after a block, arriving hours late, and being labelled as such.
That is why 2026-10-13 has 96 stored 15-minute bars and only 58 % prospective coverage — the bars are
there, they just did not arrive while the day was live.

## 5. How much disk does it consume per day?

| | |
| --- | --- |
| Lane tree now | 5 445 169 bytes of a declared 268 435 456 (2.03 %) |
| Store | 5 823 115 bytes |
| One-off heavy publication | 2 544 674 bytes, rendered **once per 24 h**, not per tick |
| Marginal cost of one tick | a few kilobytes of bounded logs plus the store's new bars |
| Measured growth | **volatile → no forecast published** (mean 1.99 MB/day, cv 4.42) |
| Volume free | 10.5794 GiB of 237.5264 GiB (95.55 % used) |
| Guards | warning below 5 GiB free (ingest continues, publication waits); critical below 2 GiB (`DISK_BUDGET_EXCEEDED`, exit 5, **no market request at all**) |

The coefficient of variation is now 4.42, worse than the 0.556 of the first reading, because the
sample mixes 15-minute ticks with an 18-hour hole and a forced multi-megabyte render. No forecast is
published, and that is the point: a number invented from a rate this unstable would be a fiction with
a units field. What can be said without inventing anything: the heavy set costs 2.54 MB per day, the
logs are bounded (2 880 / 2 880 / 4 032 / 366 / 500 rows), nothing frozen or published is ever pruned,
and over 60 days that is on the order of 150 MB of publication plus tens of MB of logs and store —
inside the lane budget, on a volume whose *free space*, not the lane budget, was the binding
constraint twice in three days.

## 6. How many signals, and with what hypothetical result?

| | |
| --- | --- |
| Arms re-read on every tick | 16 (intraday, trend-1d, trend-4h × base / 2× fees / adverse) |
| Primary arm | `edge_trend_01_4h:BASE` |
| Signals in the forward window | **324** |
| Refusals in the window | **1 101** |
| Captured decisions | 101 (digest `e6ed38e7015e25de…`) |
| Signals / trades on these dates | 0 / 0 |
| Hypothetical primary window | 31 trades · gross **−9.087451 USDT** · fees **29.608409** · price costs **5.611636** · net **−44.307497 USDT** · max drawdown **2.776571 %** · 3 974 no-trade bars |
| Cost stress | the `2X_FEES` and `ADVERSE` variants exist for exactly this reason: the base arm's gross is **−9.09** and its costs are **35.22**, so the window's sign is decided by costs |
| Risk parity vs the real Risk Engine | **`PARITY_PASS`, 0 defects** over 544 decisions, on all 141 pipeline runs |

**These are hypothetical.** They are the frozen ruleset's numbers over the forward window with fees
and slippage applied, marked `hypothetical: true` and `order_sent: false` in every artefact. Nothing
was realised and nothing is expected: a negative net here is a fact about the window, not a verdict
about the strategy, and it is deliberately not smoothed into something that reads better.

## 7. What failures does it detect?

The outcome vocabulary is separate from the exit code, and the exit code is derived from the outcome,
so a failure cannot be written as a success:

`NO_NEW_DATA` · `PROVIDER_UNAVAILABLE` · `STALE_DATA` · `MISSING_BARS` ·
`DISK_BUDGET_EXCEEDED` · `VERIFICATION_FAILED` · `RUNTIME_EXCEPTION` · `ALREADY_OBSERVED` ·
`ALREADY_RUNNING`

`NO_NEW_DATA` is a recorded result, not a failure. None of them consumes a slot, so a failed tick
cannot block the retry that would fix it. Alerts fire once per transition, never per tick:
`DISK_WARNING`/`DISK_CRITICAL`/`DISK_RECOVERED`, `BUDGET_EXCEEDED`, `PROVIDER_UNAVAILABLE`,
`STALE_DATA`, `MISSING_BARS`, `VERIFICATION_FAILED`, `PUBLICATION_PAUSED`, `HEALTH_BLOCKED`/
`HEALTH_DEGRADED`/`HEALTH_RECOVERED`, `OBSERVATION_GAP`, `OBSERVATION_STALLED`, `SIGNALS_DETECTED`.

Seen live in this lane's life: 21 alert rows over 9 kinds — 1 `DISK_CRITICAL`, 1 `DISK_WARNING`,
1 `DISK_RECOVERED`, 1 `PUBLICATION_PAUSED`, 5 `HEALTH_BLOCKED`, 7 `HEALTH_DEGRADED`,
3 `HEALTH_RECOVERED`, 1 `OBSERVATION_GAP`, 1 `OBSERVATION_STALLED` — and, the useful part, **six
real defects found by measuring**. Three were fixed in the first session (a day file disagreeing with
the slot ledger, a byte reading taken before the tick's own row existed, a snapshot that silently
copied less than the tree it described); a sabotage that was being detected by accident while the
check it named could not fail; and **two more were refused by the independent verifier in this
session** and fixed:

* **`DAILY_EVIDENCE_CONSISTENT` refused two day files.** A day file is written by the ticks of its own
  day, so its last write of that day cannot contain the day's last bars: the published `day_hashes`
  described a partial day for ever, and an artefact whose whole purpose is to make a claim about a day
  checkable could not answer to the store it claims to describe. A tick now re-derives and corrects
  the hashes of a *finished* day, and records that it did; the next tick corrected `2026-10-13` and
  `2026-10-14`, 6 series each.
* **`PUBLICATION_SWAPPED_ATOMICALLY` refused the publication directory.** The pointer named what the
  newest render *wrote*, while the swap leaves every earlier per-date report in place (nothing
  published is deleted). So it described a subset of the directory while reading as complete. The
  pointer now enumerates the directory by each file's own path, with its digest, its role and whether
  this render wrote it — and the check became name-for-name, which is strictly stronger: 15 files
  named, 15 answered.

The third finding of the session was structural rather than a refusal: the snapshot's copy was written
into a directory that already held one, and nothing dropped a file the live tree no longer had, so the
directory *could* be the union of two readings while claiming to be one. It now drops exactly the
files the previous snapshot recorded and the live tree has lost, and says which. All are in
`EDGE04_RUNTIME_AUDIT.md` §10b–§10c.

Not yet seen live (exercised only in the suite and the sabotage matrix): a real provider outage,
`STALE_DATA`, `MISSING_BARS`, a moved ruleset.

## 8. What is still missing for the 60 days?

Only one thing is *missing*, and four things are *unproven*:

1. **Time — 60 admissible days, and nothing else can substitute for it.** 0 of 60. The lane must
   stay installed and running on a host that is up, and each day must be at least 90 % covered per
   primary asset with bars that arrived fresh.
2. **A host that stays logged in** — the task runs under `InteractiveToken`, so it runs while the
   user session is active. This is no longer a hypothesis: this window contains 30.7 h of silence and
   the last 24 h contained 75 of 96 expected triggers. `StartWhenAvailable=true` fires the missed
   trigger once the machine is back and the pipeline's high-water mark makes up the missed *data*, so
   the cost is latency and coverage rather than data. Making it survive logoff needs stored account
   credentials, which this work package is not authorised to hold. **This is the largest single
   obstacle to the 60-day requirement, and at the current rate of coverage the floor of 60 days is not
   reachable on this host.**
3. **Unproven: a long unattended run.** 2 days 3 h 54 m of unattended scheduled firing was observed,
   with real interruptions. That is evidence the mechanism works, not evidence of 60 days of it.
4. **Unproven: some live failure paths.** The guards and the failure vocabulary are exercised in tests
   and in a 20-sabotage self-test; the disk paths have now fired for real, the outage paths have not.
5. **Unproven: Linux.** Portable by construction and unexercised in fact.

## 9. What would prevent a future PAPER admission?

Reaching 60 days is **not** sufficient, and this lane cannot promote anything. Even with 60 covered
days, admission should be refused if any of the following holds:

* **The frozen ruleset moved.** Any change to `FROZEN_PARAMS` / `params_hash`, or a re-derivation
  that "explains" the forward data after the fact, invalidates the observation. A tick detects this
  (`VERIFICATION_FAILED`, exit 6); a human should treat it as disqualifying, not as a warning.
* **The days are not prospective.** Backfilled days do not count, however dense: 228 such days
  already exist in this store, and if the coverage rule were ever read off the store's density rather
  than its freshness the answer would be wrong by 228 days.
* **The observation was not continuous.** 18.5 h of declared unavailability in three days, an
  unclosed gap in the slot ledger, or a window in which the observer was silently not running all
  reduce what was really observed. Silence is measured between the ticks that consumed a slot and
  each episode is named; a report that gives only a percentage would be hiding this.
* **Costs change the sign and nobody notices.** The primary arm's gross is −9.09 and its costs are
  35.22 over this window: an admission that reads the gross, or that reads the base variant only
  while ignoring `2X_FEES` and `ADVERSE`, would be reading the wrong number. Parity with the Risk
  Engine must hold (`PARITY_PASS`, 0 defects) — a parity defect is an admission blocker, not a
  footnote.
* **The evidence cannot be re-checked.** If the verifier cannot reproduce its verdict on the
  committed snapshot, or a report cannot be re-rendered offline, the numbers are testimony rather
  than evidence. Today: 15/15 checks, 20/20 sabotages, and three of four articles reproducing byte
  for byte — the fourth is named, not waved through.
* **The lane's own claims drift from what it measured.** Every defect found in this work package was
  a claim that had become false, and two of them were only found because a verifier that shares no
  code with the lane was pointed at the live artefacts. A green health reading from the lane's own
  module is not a substitute for that.

Conversely, none of the following would justify admission: reaching 60 days, a green health reading,
a long stretch without a crash, or a positive hypothetical net. **This work package authorises
PAPER or LIVE trading under no circumstances whatsoever.**

---

## Re-checking this file

```bash
# the lane's own state, changing nothing
python scripts/edge04_observer.py --status

# the OS task, read back from the scheduler
python scripts/edge04_observer.py --task-status

# regenerate every artefact in this directory from the live state and re-verify
python scripts/edge04_closure.py --reports reports/edge-recovery/WP-EDGE-04

# or verify the committed snapshot alone, offline, including the sabotage matrix
python scripts/edge04_verify.py --state-root reports/edge-recovery/WP-EDGE-04/evidence \
    --repo . --install reports/edge-recovery/WP-EDGE-04/evidence/install.json --self-test
```

`scripts/edge04_closure.py` decides nothing and rewrites nothing: it reads, it writes under
`--reports`, and it runs the verifier. The verifier imports nothing from `trading_bot` and drives none
of the observer's code; it restates every rule from its own declarations, so a claim in any artefact
above can be re-derived from the files rather than believed.

The run this report describes is at `2026-10-15T15:17:41Z`, and the machine-readable twin
(`RUN_REPORT.json`) carries the same numbers field by field.
