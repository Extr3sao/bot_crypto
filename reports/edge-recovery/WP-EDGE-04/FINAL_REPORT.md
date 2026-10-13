# WP-EDGE-04 — FINAL_REPORT.md

**Mission.** Turn WP-EDGE-03 into an automatic, persistent and recoverable forward observer that
accumulates the 60 forward days the frozen contracts require, preserving the rules, thresholds and
admission conditions exactly — and that does not authorise PAPER or LIVE trading.

**Status.** The observer exists, is installed, is firing unattended every 15 minutes, ingests newly
closed bars, refuses to duplicate work, survives a hard kill, publishes its evidence and is verified
by a verifier that shares none of its code. It has accumulated **0 of 60 forward observation days**
and 51 newly stored bars so far, which is what a few hours of a 60-day requirement looks like.

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

Proof it fires rather than proof it exists: **17 scheduled ticks** ran with no human and no agent
session involved, at the task's own cadence (`:10:55Z`, `:25:55Z`, `:40:55Z`, `:55:55Z`), from
`11:23:38Z` to `14:55:55Z`. Fourteen of them stored new closed bars; three found their slot already
sealed and spent nothing. The scheduler's own last-result field carries the outcome's exit code, so
the task state alone answers "did the last tick ingest?".

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
| Newly closed bars stored by this lane | **51** (24 `15m` BTC/ETH/SOL · 3 `1h` each for BTC/ETH/SOL, per series 14/14/14 and 3/3/3) |
| Market requests spent | 68 |
| Store total | 18 084 bars across 6 series |
| **Valid forward observation days** | **0 of 60** (60 remaining) |
| Days with any stored data | 227 |
| Densely covered but backfilled | 226 |
| Observation epoch | `2026-03-01T00:00:00Z` |

Zero is the correct number and it is not a defect. The frozen corpora are history; a day counts
forward only if every primary asset holds ≥ 90 % of the calendar's expected bars **and** those bars
reached the store while still fresh (within 30 min for `15m`, 2 h for `1h`). A day on which the
scheduler ran is not thereby a forward day — that separation is the entire reason the coverage rule
is kept apart from the run log. The lane has been observing for hours; the requirement is 60 days.

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
row claiming them — and costs neither data nor a duplicate. On a restart where the lock directory is
cleared, the same high-water marks make the outcome identical.

The first attempt at this rehearsal **crashed** instead of refusing, because this platform answers
`os.kill(pid, 0)` for a stale pid with `WinError 87` raised as `SystemError`, which the probe did not
catch. Fixed (`5b1e771`) with a regression test. A crashed trigger is worse than a refused one: the
schedule loses the observation *and* the record that would have explained it.

## 5. How much disk does it consume per day?

| | |
| --- | --- |
| Lane tree now | 2 998 142 bytes of a declared 268 435 456 (~1.1 %) |
| Store | 5 598 300 bytes |
| One-off heavy publication | 2 450 494 bytes, rendered **once per 24 h**, not per tick |
| Marginal cost of one tick | a few kilobytes of bounded logs plus the store's new bars |
| Measured growth | **volatile → no forecast published** (mean 1.86 MB/day, cv 0.556) |
| Volume free | 6.7546 GiB of 237.5264 GiB (97.16 % used) |
| Guards | warning below 5 GiB free (ingest continues, publication waits); critical below 2 GiB (`DISK_BUDGET_EXCEEDED`, exit 5, **no market request at all**) |

A number for "per day" would be an invention at this age: the measured rate is dominated by the
one-off publication and the day file, and the lane publishes a forecast **only** when the rate is
stable. What can be said without inventing anything: the heavy set costs 2.45 MB per day, the logs
are bounded (2 880 / 2 880 / 4 032 / 366 / 500 rows), and nothing frozen or published is ever pruned.
Over 60 days that is on the order of 150 MB of publication plus tens of MB of logs and store — well
inside the declared 256 MiB lane budget, on a volume whose free space, not the lane budget, is the
real constraint.

## 6. How many signals, and with what hypothetical result?

| | |
| --- | --- |
| Arms re-read on every tick | 16 (intraday, trend-1d, trend-4h × base / 2× fees / adverse) |
| Primary arm | `edge_trend_01_4h:BASE` |
| Signals in the forward window | **324** |
| Refusals in the window | **951** |
| Captured decisions | 101 (digest `e6ed38e7015e25de…`) |
| Signals / trades on this date | 0 / 0 |
| Hypothetical primary window | 31 trades · gross **−9.087451 USDT** · fees **29.608409** · price costs **5.611636** · net **−44.307497 USDT** · max drawdown **2.776571 %** · 3 974 no-trade bars |
| Cost stress | the `2X_FEES` and `ADVERSE` variants exist for exactly this reason: the base arm's gross is **−9.09** and its costs are **35.22**, so the window's sign is decided by costs |
| Risk parity vs the real Risk Engine | **`PARITY_PASS`, 0 defects** over 544 decisions |

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

Seen live in this window: 2 health transitions, 2 `ALREADY_RUNNING` refusals, and — the useful part —
**three real defects found by the independent verifier and fixed**: a day file disagreeing with the
slot ledger, a byte reading taken before the tick's own row existed, and a snapshot that silently
copied less than the tree it described. Also one that the tools insisted on: a sabotage that was
being detected by accident while the check it named could not fail. All are in
`EDGE04_RUNTIME_AUDIT.md` §10b.

Not yet seen live (exercised only in the suite and the sabotage matrix): a real provider outage,
`STALE_DATA`, `MISSING_BARS`, a critical-disk refusal, a moved ruleset.

## 8. What is still missing for the 60 days?

Only one thing is *missing*, and three things are *unproven*:

1. **Time — 60 admissible days, and nothing else can substitute for it.** 0 of 60. The lane must
   stay installed and running on a host that is up, and each day must be at least 90 % covered per
   primary asset with bars that arrived fresh.
2. **A host that stays logged in** — the task runs under `InteractiveToken`, so it runs while the
   user session is active. `StartWhenAvailable=true` fires the trigger that was missed once the
   machine is back, and the pipeline's high-water mark makes the missed *data* up on the next tick,
   so the cost is latency rather than data. Making it survive logoff needs stored account credentials,
   which this work package is not authorised to hold. **This is the largest single caveat on the
   60-day requirement.**
3. **Unproven: a long unattended run.** 2 h 5 m of unattended scheduled firing was observed. That is
   evidence the mechanism works, not evidence of 60 days of it.
4. **Unproven: live failure paths.** The guards and the failure vocabulary are exercised in tests and
   in a 20-sabotage self-test, not against a real outage or a real disk exhaustion.
5. **Unproven: Linux.** Portable by construction and unexercised in fact.

## 9. What would prevent a future PAPER admission?

Reaching 60 days is **not** sufficient, and this lane cannot promote anything. Even with 60 covered
days, admission should be refused if any of the following holds:

* **The frozen ruleset moved.** Any change to `FROZEN_PARAMS` / `params_hash`, or a re-derivation
  that "explains" the forward data after the fact, invalidates the observation. A tick detects this
  (`VERIFICATION_FAILED`, exit 6); a human should treat it as disqualifying, not as a warning.
* **The days are not prospective.** Backfilled days do not count, however dense: 226 such days
  already exist in this store, and if the coverage rule were ever read off the store's density rather
  than its freshness the answer would be wrong by 226 days.
* **The observation was not continuous.** Hours of unavailability, an unclosed gap in the slot
  ledger, or a window in which the observer was silently not running all reduce what was really
  observed. Silence is measured between the ticks that consumed a slot; the current longest is
  1 525.8 s against a 2 100 s warning bound.
* **Costs change the sign and nobody notices.** The primary arm's gross is −9.09 and its costs are
  35.22 over this window: an admission that reads the gross, or that reads the base variant only
  while ignoring `2X_FEES` and `ADVERSE`, would be reading the wrong number. Parity with the Risk
  Engine must hold (`PARITY_PASS`, 0 defects) — a parity defect is an admission blocker, not a
  footnote.
* **The evidence cannot be re-checked.** If the verifier cannot reproduce its verdict on the
  committed snapshot, or a report cannot be re-rendered offline, the numbers are testimony rather
  than evidence. Today: 15/15 checks, 20/20 sabotages, and three of four articles reproducing byte
  for byte — the fourth is named, not waved through.
* **The lane's own claims drift from what it measured.** Four defects in this window were found by
  measuring, and each of them was a claim that had become false. Any admission decision has to be
  based on a freshly measured reading, not on what a previous report asserted.

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
`--reports`, and it runs the verifier.

Both were run against the committed snapshot after the commits: the verifier re-derived the same
15/15 checks and the same 20/20 sabotages (exit 0, `VERIFIER_RERUN.json`), and the push probe
diagnosed `BLOCKED_GITHUB_AUTH` — a dry run, no credential supplied, so the commits are local.
