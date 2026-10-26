# WP-EDGE-04 — EDGE04_SCHEDULER_DESIGN.md

**What this is.** The FASE 1/2 design of the automatic forward observation: what fires, when, what
happens when it fires twice, when it is killed, when the machine was asleep, when the volume is
low, and what an operator has to do (nothing, in the steady state).

Research only. Public market data, no credentials, no orders, no capital, no promotion.

---

## 1. One entry point

```
.venv\Scripts\python.exe scripts/edge04_observer.py --scheduled --due
```

That line is the entire automation. `scripts/edge04_observer.py` parses arguments, builds a
`ForwardObserver` over `data/forward/edge04`, calls `tick()`, prints the record and exits with the
outcome's code. The pipeline, the rulesets and the reports are WP-EDGE-03's; this file adds no
analysis of its own.

| Invocation | Meaning |
| --- | --- |
| `--scheduled --due` | what the operating system runs: observe this slot only if it is unobserved |
| *(no flags)* | a manual tick, for a window of validation or a deliberate replay |
| `--status` / `--task-status` | read the observer's own state / the OS task's state, change nothing |
| `--install` / `--uninstall` / `--run-task` | register the task, remove it, or ask the scheduler to fire it now |
| `--snapshot DIR` | copy the live evidence into a dated directory, digests and all |
| `--report-only DIR --compare` | re-render the reports from the preserved observation, with no network, and check byte identity |

Timestamps are UTC everywhere (`YYYY-MM-DDTHH:MM:SSZ`, slots `YYYY-MM-DDTHH:MMZ`). No local time
appears in any artefact, so a reader cannot mistake a host's timezone for the market's.

## 2. The trigger

Registered through the repository's existing supervisor (`scripts/cap004_supervisor.py` §9) as
`TradingAgentic-EDGE04-Forward`:

| Setting | Value | Why |
| --- | --- | --- |
| Trigger | `TimeTrigger` + `Repetition` `PT15M` for `P3650D` | one firing per 15-minute bar plus the margin the venue needs to publish it |
| `StartWhenAvailable` | `true` | a trigger missed while the machine was asleep fires as soon as it is back; that is the recovery path for lost intervals |
| `MultipleInstancesPolicy` | `IgnoreNew` | the OS itself refuses to start an overlapping instance |
| `ExecutionTimeLimit` | `PT1H` | a wedged tick cannot sit on the lease for a day |
| `AllowHardTerminate` | `true` | the limit above is enforceable |
| `RestartOnFailure` | `PT5M`, 3 attempts | a crashed process is retried by the OS, not by a resident daemon |
| `WakeToRun` | `false` | waking a sleeping machine to fetch a bar is not worth the wake |
| `RunLevel` / `LogonType` | `LeastPrivilege` / `InteractiveToken` | no elevation; see §9 for the availability consequence |
| Action | `python.exe scripts/edge04_observer.py --scheduled --due` in the repo root | one command, no shell, no wrapper |

The scheduler's own last-result field is the outcome's exit code, so `schtasks /query /v` alone
tells an operator whether the last tick ingested, refused or found nothing:

| Outcome | Exit | Scheduler result |
| --- | --- | --- |
| `OBSERVED`, `NO_NEW_DATA`, `ALREADY_OBSERVED` | 0 | done |
| `RUNTIME_EXCEPTION` | 1 | failed |
| `ALREADY_RUNNING` | 2 | another tick holds the lease |
| `MISSING_BARS`, `STALE_DATA` | 4 | the tick ran, the store is still short |
| `DISK_BUDGET_EXCEEDED` | 5 | refused before any request |
| `VERIFICATION_FAILED` | 6 | the frozen pin refused |
| `PROVIDER_UNAVAILABLE` | 7 | every series failed to fetch |

## 3. Slot discipline — closed bars, at most once

* A **slot** is the 15-minute UTC bucket a tick's market instant belongs to.
* The tick observes **its own slot**: `--due` checks the slot ledger first and, if the slot is
  already consumed, exits `ALREADY_OBSERVED` after **zero** market requests. Measured: the
  11:24:27Z and 11:40:56Z scheduled triggers each spent 0 of the 6 in-flight requests, and the
  verifier fails any row that claims an observation without spending a request.
* Only **closed** bars are ingested. `expected_closed_bars()` computes the newest bar that can have
  closed at the tick's instant; anything later is still open and is not fetched, requested or
  counted as a gap.
* `1h` bars are appended only when a 1-hour bar has actually closed since the store's high-water
  mark; `15m` bars likewise. There is no "one bar per tick" assumption anywhere.

## 4. The lease

`IgnoreNew` covers the OS's view of the task; it cannot see a manual tick, a tick started under a
different task name, or a `--run-task` firing that overlaps a running instance. The second line is
a **renewable file lease** over `data/forward/edge04/lock/` — the repository's existing idiom,
`campaign_lock.CampaignLock`, used as it is rather than re-implemented for this lane. This is the
document it actually writes (quoted from the live file left behind by a killed tick):

```json
{"lease_version": "CAMPAIGN_LEASE_V1", "campaign_id": "EDGE04_FORWARD_OBSERVER",
 "pid": 1308, "host": "DESKTOP-4CHO695", "acquired_at": 1791903728,
 "renewed_at": 1791903728, "stale_after_seconds": 300}
```

* **Acquire never blocks and never waits.** A lease inside its bound is answered with
  `ALREADY_RUNNING` (exit 2, `market_requests: 0`, measured duration 0.002 s) and the tick touches
  no evidence at all — not the store, not the ledger, not a log.
* **Staleness is decided by age, not by a pid guess.** `campaign_lock.is_stale()` applies the age
  rule first and consults `os.kill(pid, 0)` only as a hint for a lease that is still young; the
  hint can never be the deciding vote, and **a probe that cannot answer says so instead of
  raising**. That last clause is a fix, not a description: on this host `os.kill(pid, 0)` for a
  stale pid raises `WinError 87` as `SystemError`, which is not an `OSError`, and the first
  controlled-kill rehearsal crashed the tick with a traceback instead of refusing it. A crashed
  trigger is worse than a refused one — the schedule loses the observation *and* the record that
  would have explained it. `_pid_probe` now returns `None` for that case, and the age rule decides.
* **A killed tick cannot leave a wedge.** 300 s of silence is enough: a tick takes tens of seconds.
  Observed end to end at `15:02:21Z` (tick hard-killed 14 s in), `15:03:54Z` (refused: inside the
  bound) and `15:07:24Z` (reclaimed: `STALE_LEASE_RECLAIMED`, `previous_holder.pid = 1308`).
* The lease is released at the end of every path, including the exception path, and
  `lease_release` is part of the run record.

## 5. Recovery of lost intervals

Two mechanisms, deliberately independent:

1. **The scheduler**: `StartWhenAvailable=true` re-fires the trigger that was missed while the
   machine was off, and `RestartOnFailure ×3` retries a crashed process.
2. **The pipeline**: the next tick that runs ingests *every* bar that closed after the store's
   high-water mark, within the venue's own kline window. A gap in the schedule therefore becomes a
   gap in *latency*, not in *data*.

Latency is what separates a prospective observation from a backfill: a bar is counted for the
forward coverage only if it reached the store within `PROSPECTIVE_LAG_BOUND_MS` of closing (30 min
for `15m`, 2 h for `1h`). A day made of bars fetched months later is dense and does not count.
`coverage.json` keeps both readings, so the honest one is always visible.

## 6. Before any request: the resource guard

Order inside one tick, and the reason for the order:

1. **Lease** — a second trigger must not even read the disk.
2. **Frozen pin** — a moved ruleset is refused before any network call (`VERIFICATION_FAILED`).
3. **Free space** — below `CRITICAL_FREE_BYTES` (2 GiB) the tick records
   `DISK_BUDGET_EXCEEDED`, exit 5, and makes **no market request**; below `HEALTHY_FREE_BYTES`
   (5 GiB) it ingests but the heavy 2.3 MB publication waits.
4. Ingest → evaluate → shadow → parity.
5. Evidence: run row, slot row, ledger, `daily/<date>.json`.
6. Report: the heavy artefact set only when its 24 h cadence is due, written to a staging tree and
   published by pointer, so a torn write leaves no half-written report.
7. Prune only the bounded operational logs; never the store, the daily evidence files or a
   published report.

All seven are measured in `resource_budget.json` per tick (`state`/`store`/`lane` bytes, free
space, measured growth, forecast), and the lane tree is compared with its declared 256 MiB budget.

## 7. Failure vocabulary (never collapsed into success)

`NO_NEW_DATA` · `PROVIDER_UNAVAILABLE` · `STALE_DATA` · `MISSING_BARS` ·
`DISK_BUDGET_EXCEEDED` · `VERIFICATION_FAILED` · `RUNTIME_EXCEPTION`

`NO_NEW_DATA` is a *recorded result*, not a failure: the tick ran the whole pipeline and there was
nothing to append. `PROVIDER_UNAVAILABLE` means every series failed to fetch — the venue is what is
missing. `STALE_DATA` means the feed stopped. `MISSING_BARS` means bars that had closed are still
absent. None of them is ever written as success, and no failure consumes a slot: a failed tick must
not block the slot its own retry needs.

Retries are bounded and declared: `MAX_PIPELINE_ATTEMPTS = 2` with a 20 s delay for a provider that
answered nothing at all, on top of the per-request retries inside the ingest path. There is no
unbounded loop anywhere in the tick.

## 8. Alerts

`alerts.jsonl` carries one row per **transition**, in the shape the host's health watch already
reads, each with `hypothetical: true` and `order_sent: false`:

`DISK_WARNING` · `DISK_CRITICAL` · `DISK_RECOVERED` · `BUDGET_EXCEEDED` ·
`PROVIDER_UNAVAILABLE` · `STALE_DATA` · `MISSING_BARS` · `VERIFICATION_FAILED` ·
`PUBLICATION_PAUSED` · `HEALTH_BLOCKED` · `HEALTH_DEGRADED` · `HEALTH_RECOVERED` ·
`OBSERVATION_GAP` · `OBSERVATION_STALLED` · `SIGNALS_DETECTED`

* `HEALTH_RECOVERED` is written **only** after a non-healthy episode; a healthy tick after a healthy
  tick is not news, and a degraded reading is never dressed up as recovery.
* `OBSERVATION_GAP` (35 min of silence) and `OBSERVATION_STALLED` (3 h) are the "prolonged
  interruption" events. They are raised once per episode: a replay of a slot behind the newest
  observation is a rerun, not silence, and does not raise them.

## 9. Portability

| Platform | Registration | Status |
| --- | --- | --- |
| Windows | Task Scheduler via the supervisor; **observed firing unattended** | exercised (see `EDGE04_AUTONOMOUS_EXECUTION_REPORT.md`) |
| Linux | the supervisor's `scheduler_type()` reports `systemd_user`; `install_scheduler()` returns `UNSUPPORTED_SCHEDULER` | **NOT_EXERCISED** — no Linux host in this environment |

The *runner* is portable and the audit checked why: stdlib only, no `win32` import, no shell,
UTC stamps, lease decided by age rather than by `os.kill` semantics, `Path` everywhere, and file
publication by pointer instead of by rename-over-open-handle. On a POSIX host the identical command
is registered by the operator, and these are the two lines that do it:

```cron
# crontab -e — the same command the Windows task runs
*/15 * * * * cd /path/to/repo && .venv/bin/python scripts/edge04_observer.py --scheduled --due >> data/forward/edge04/cron.log 2>&1
```

```ini
# ~/.config/systemd/user/edge04-forward.timer + .service
[Timer]
OnCalendar=*:0/15
Persistent=true          # the POSIX spelling of StartWhenAvailable
[Service]
WorkingDirectory=/path/to/repo
ExecStart=/path/to/.venv/bin/python scripts/edge04_observer.py --scheduled --due
```

`Persistent=true` and cron's behaviour after downtime play the same role as `StartWhenAvailable`;
either way the recovery of the *data* is the pipeline's job (§5), not the scheduler's.

**No interactive agent session is required** — no Codex, no ChatGPT, no terminal. The only session
the schedule depends on is the machine's own user session, because that is how the task was
registered (see §2 and the limitation below).

**Declared limitation.** `InteractiveToken` means the task runs while the user session is active and
does not run while the user is logged out, and this work package is not authorised to store account
credentials to change that. The workaround for a long unattended window is a host that stays logged
in (the machine is the orchestrator), or a re-registration with stored credentials performed by the
owner. This is the largest single caveat on the 60-day requirement and it is stated as such in
`FINAL_REPORT.md`.

## 10. Idempotence and re-entry

* Rerunning a slot: with `--due`, `ALREADY_OBSERVED`, zero requests, zero evidence written.
* **A slot is sealed once.** Without `--due` a manual tick really does re-run the pipeline — that
  is the point of a manual trigger — and what it may not do is write a *second* seal. The seal
  belongs to the tick that drained the slot: `_finish` reads the ledger and appends a slot row only
  when the slot has none, so a repeat trigger records its own run row (`slot_sealed: false`,
  `slot_seal_held_by: {...}`) and leaves the seal alone. Two rows for one slot would make the
  ledger claim the same interval was observed twice, which is a duplicate by construction and the
  first thing the verifier refuses.
* **The day file is derived from the seal, not from whoever wrote last.** Every slot the ledger
  seals on a given day is written into `daily/<date>.json` from the seal and from the run row the
  seal names; a repeat trigger is kept as `last_repeat` + a `repeats` count, never as a rewrite of
  the interval's numbers. Two consequences that were both observed live: a day file written by an
  older rule is *corrected* by the next tick instead of staying wrong, and a day entry the ledger
  can no longer explain (its seal front-truncated after `SLOTS_KEPT` rows) is left exactly as it
  is rather than dropped.
* **A duplicate seal that already reached the log can be repaired, audibly.**
  `scripts/edge04_observer.py --repair-slot-ledger` keeps the first row of each slot, drops later
  rows, and writes `slot_ledger_repair.json` with both digests and every dropped row. It exists
  because the first manual probe of this lane wrote such a row before the seal rule did.
* A crash mid-write: files are written atomically (temp + replace), a torn line is *counted*
  (`corrupt_log_lines`) rather than silently skipped, and the next tick proceeds.
* A restarted process: the slot ledger and the store's high-water marks are on disk, so the
  restart cannot duplicate a bar — verified by a test that kills the lane and re-runs it, and by
  the hard-killed rehearsal of §4, whose 6 appends the next tick found already stored and did not
  repeat.
* A replay of an old slot: allowed manually, recorded, not counted as new coverage, and not
  announced as silence.

## 11. What this design does not do

It does not place orders, hold credentials, rank strategies, change a threshold, or promote
anything. `hypothetical: true` and `order_sent: false` are on every artefact this lane writes, and
there is no code path from the tick to an execution venue. Reaching 60 admissible days is a
*requirement of a later decision*, never that decision, and no artefact of this lane can authorise
PAPER or LIVE trading.
