# WP-EDGE-05 — RUN_REPORT.md

**What this is.** The record of a work package that really ran: what was built, on which commit, on
which host, against which evidence, what was deliberately broken and what happened, what was fixed
and what remains. The machine-readable twin is `RUN_REPORT.json`; the tick-by-tick and check-by-check
table is `evidence/FASE5_TIMELINE.md`; the Spanish executive reading is `FINAL_REPORT.md`.

Research only. Public market data, no credentials, no orders, no capital, no promotion. Nothing here
can authorise PAPER or LIVE trading.

---

## 1. The run

| | |
| --- | --- |
| Window of this work package's own evidence | `2026-10-13T18:47:10Z` → `2026-10-13T20:13:48Z` |
| Lane tick before the rehearsal | `18:41:27Z` (`FWD-EDGE04-20261013T183000Z`, 3 bars) |
| Lane tick at the recovery | `19:11:27Z` (`FWD-EDGE04-20261013T190000Z`, **9 bars**) |
| Host / runtime | `DESKTOP-4CHO695`, `.venv\Scripts\python.exe` 3.11.15 |
| Watchdog task | `TradingAgentic-EDGE05-Watchdog`, installed, enabled, every 15 min |
| Lane task | `TradingAgentic-EDGE04-Forward`, enabled again after the rehearsal |
| Watchdog readings | 9 — `WATCH_OK` ×6, `WATCH_ALARM` ×3, one per OS-scheduled run |
| Alerts | 25 rows, 16 kinds, one row per transition |
| Controlled outage | disabled `18:48:10Z` → detected `18:48:16Z` → recovered `19:12:07Z` |
| Reconciliation | 42 runs · 36 consuming · 35 seals · 456 ledger rows · 38 attempts (last at `20:13:12Z`) |
| Unattributed attempts | **2**, both `CLOSED`, **0 open defects**, chains hold on all six series |
| Unit tests | `test_edge05_watchdog.py` + `test_edge05_reconcile.py` — **46 passed** |
| Publish order | reconcile → verify → closure, back to back at `20:13Z`, so the published numbers and the published verdict describe the same instant |
| Independent verdict | `VERIFY_PASS` **13/13**, `SELF_TEST_PASS` **15/15** |

## 2. The commits

| Commit | Subject | Files |
| --- | --- | --- |
| `40ba11c` | Watch the forward lane from outside it, and say which silence is a fault. | `research/edge05/__init__.py`, `watchdog.py`, `scripts/edge05_watchdog.py`, `test_edge05_watchdog.py` |
| `17d0e44` | Reconcile the store against the ticks that claim it, and name what is unowned. | `reconcile.py`, `scripts/edge05_reconcile.py`, `test_edge05_reconcile.py` |
| `6d62c79` | Verify the watchdog with code that shares none of it, then publish the record. | `scripts/edge05_verify.py`, `scripts/edge05_closure.py` |
| *(this run)* | Plant the market lie where it is always a lie, so the self-test cannot pass by accident. | `scripts/edge05_verify.py` (§9.4) |

Base commit `e07785b2585d0b4589a9a6dbc0aba53f4ced6802`, which is the tip of WP-EDGE-04. The reports and
the `.gitignore` exception that version them are one further, separate commit — see §9. No other
workstream's file was staged, and the live state under `data/forward/` is ignored by git and therefore
in none of them.

**Push: `BLOCKED_GITHUB_AUTH`** — re-probed after this work package's commits rather than assumed:

```
$ GIT_TERMINAL_PROMPT=0 GIT_ASKPASS=/bin/true timeout 60 git push --dry-run origin HEAD
(60 s, no output, killed)  exit 124
```

`origin` is `https://github.com/Extr3sao/bot_crypto.git`; the credential helper never returns because
the prompt it waits for is disabled. The probe was a **dry run** and no credential was supplied, so
nothing left this machine. The commits stay local. This is the same blocker the previous work packages
recorded — a diagnosis, not a pass.

## 3. What the watchdog is, and what makes it independent

The requirement is a check that is *not* the thing being checked. The watchdog holds **no lease, runs
no pipeline and makes no market request**; every field of its verdict is derived from the lane's own
files and from the operating system's own reporting, and the verifier re-derives each of them:

* the lane's `runs.jsonl`, `slots.jsonl` and `ledger/INGEST_LEDGER.jsonl`;
* the forward store's own bar tails, against the closed-bar calendar;
* the process table (is the pid a recorded tick named still alive?);
* `schtasks`/`Get-ScheduledTask` — state, last result, missed runs, next trigger;
* the volume's free space, and the lane's own growth samples.

Thirteen checks, and the verdict is the **worst** of them: `scheduler_task`, `scheduler_cadence`,
`scheduler_last_result`, `lane_cadence`, `lane_lease`, `lane_process`, `store_freshness`,
`market_expectation`, `evidence_integrity`, `restart_proof`, `resource_disk`, `resource_growth`,
`watchdog_cadence`.

The distinction the whole 60-day requirement rests on is a *check of its own*:
`market_expectation` compares the bars the calendar says have closed against the store's tail. Bars
that closed while the tick was simply not due are **latency**, and the reading says so in words — as
it did, with the lane disabled, at `18:48:16Z`: *"3 bar(s) closed since the last tick and are pending
the next trigger: normal latency inside the declared schedule, not a failure"*. A quiet lane is not a
dead market, and neither is an alarm. Only a scheduler that is disabled or failing, a lease that
outlives its holder, a tick that died mid-write, a store that stops moving, unreadable evidence or a
disk below its floor earns one.

Alerts are **per transition**, not per reading: a fault is announced once, and its recovery is
announced once, carrying the id of the tick that recovered it
(`WATCHDOG_RECOVERED · recovered_by_run_id FWD-EDGE04-20261013T190000Z`).

It is registered as its **own** OS task because a watchdog sharing a scheduler with the thing it
watches cannot report that scheduler's death.

## 4. The controlled outage: detected in six seconds, recovered in twenty-four minutes

The requirement is explicit: *do not claim success unless the watchdog has really detected an
interruption.* So one was made, bounded and reversible, against the live lane:

| instant (UTC) | what happened |
| --- | --- |
| `18:48:10Z` | lane task disabled on purpose (`Disable-ScheduledTask`), receipt in `evidence/OUTAGE_REHEARSAL_START.json` |
| `18:48:16Z` | **watchdog reading `WATCH_ALARM` / `SCHEDULER_FAILURE`** — *six seconds later*, finding `scheduler_task: the task is disabled` |
| `18:48:16Z` | alerts `SCHEDULER_DISABLED` (CRITICAL) and `WATCHDOG_ALARM` (CRITICAL) |
| `18:55:53Z` | the trigger that should have fired while disabled — the scheduled run that was actually missed |
| `18:55:59Z` | `WATCH_ALARM` again, now also `scheduler_cadence: the scheduler reports 1 missed run(s)` |
| `19:02:32Z` | `WATCH_ALARM` again (the task's own unattended run, exit `11`) |
| `19:06:06Z` | lane task re-enabled |
| `19:11:27Z` | **the lane recovered by itself**, consuming slot `19:00Z` with **9 new bars** |
| `19:12:07Z` | **watchdog `WATCH_OK`**, alert `WATCHDOG_RECOVERED` naming `FWD-EDGE04-20261013T190000Z` |
| `19:17:33Z` | the watchdog's own scheduled run: `WATCH_OK` / `HEALTHY`, exit `0` |

Episode of trouble: `18:48:16Z` → `19:12:07Z` (23 m 51 s), **1 episode, 1 recovery**, closed by a tick
that exists in the lane's run log. The verifier refuses the claim unless all three hold, and it failed
*before* the recovery (`no interruption has been detected and closed on this state root`) — the check
is honest, and it cannot be satisfied by an empty history.

**No bar was lost.** The nine bars the recovering tick stored are exactly the bars that closed while
the scheduler was off: the `18:30` and `18:45` fifteen-minute bars and the `18:00` hourly bar, for the
three assets — `(2 + 1) × 3 = 9`, one request per series, all `ingested`, none re-fetched. The next
ingest pass at the same instant appended **0**, which is the lane's own restart proof. The gap was
latency, not data.

## 5. The reconciliation: every stored bar accounted for, including six of the previous crash

`scripts/edge05_reconcile.py` recomputes, from the raw files and nothing else, the chain from each
series' epoch to its newest bar, and accounts for every bar: which ingest attempt wrote it, which run
claimed it, whether an interval was written once or twice, and whether the decisions the run recorded
match the bars it says it read.

| | |
| --- | --- |
| Status | `HISTORICAL_ONLY` · verdict `RECONCILIATION_INCOMPLETE` · `20:13:12Z` |
| Series | six, epochs `1h 2026-10-13T10:00:00Z`, `15m 2026-10-13T11:00:00Z`, **chain holds on all six** |
| Bars accounted | 76 ledger rows per series · 609 stored `15m` / 5 444 stored `1h` per asset |
| Open defects | **0** of every kind (`CHAIN_BROKEN`, `CLAIMED_BUT_ABSENT`, `DECISION_DIVERGENCE`, `DOUBLE_CLAIM`, `RESTART_PROOF_BROKEN`, `SEAL_MISSING`, `SEAL_ORPHANED`, `UNATTRIBUTED_ATTEMPT`, `UNATTRIBUTED_BAR`) |
| Named, not open | 2 `UNATTRIBUTED_ATTEMPT`, both closed episodes |

The two unattributed attempts are the honest residue, and one of them is **the six bars of the
previous work package's crash**, still traceable:

| attempt | bars | found later | reading |
| --- | --- | --- | --- |
| `2026-10-13T11:25:20Z` | 0 | `FWD-EDGE04-20261013T113000Z` | an ingest that found nothing new, whose process ended before it recorded itself |
| `2026-10-13T15:02:10Z` | **6** — `1h` `14:00Z` ×3, `15m` `14:45Z` ×3 | `FWD-EDGE04-20261013T150000Z` appended **0** | the six bars are present in the store, the interval is covered **exactly once**, by the attempt that never named itself |

That is the whole point of the reconciliation: a tick that dies between writing bars and recording
itself leaves no lie behind. The reading names the attempt, counts the bars, and proves single
coverage through the next tick's own high-water mark — it does **not** invent a run row into the lane's
log.

## 6. Windows continuity: what the host permits, and the one thing that needs the owner

`evidence/EDGE05_TASK_REGISTRATION.json` holds both tasks' registrations **as the platform exported
them**, read by element path rather than by first-match text search (the repetition interval of the
failure-restart policy and the repetition interval of the trigger are both spelled `<Interval>`, and an
audit that confuses them reports a 15-minute schedule as a 5-minute one). An element the platform
omits is recorded at its schema default — including `Enabled`, so the artifact shows whether the lane
is on, not just whether it exists.

| | | |
| --- | --- | --- |
| `logon_type` | `InteractiveToken` | the lane needs a live user session |
| `trigger_repetition_interval` | `PT15M` | every 15 minutes, duration `P3650D` |
| `MultipleInstancesPolicy` | `IgnoreNew` | a slow tick is never doubled |
| `StartWhenAvailable` | `true` | a trigger missed while asleep fires on wake |
| `RestartOnFailure` | `3 × PT5M` | the platform's own retry |
| `ExecutionTimeLimit` | `PT1H` | a hung tick is killed, it does not run forever |
| `DisallowStartIfOnBatteries` | `false` | a laptop on battery still observes |
| `RunLevel` | `LeastPrivilege` (defaulted) | no elevation, no credentials stored |

Measured or declared: a **logged-on session runs it** (observed firing unattended, no agent open);
**screen locked** is *expected* to run and **NOT EXERCISED** — locking this host's screen would
interrupt the person using it; **logged off does not run**, which is the single largest caveat on the
60-day requirement and needs the owner's decision; **reboot** and **sleep/wake** are declared by the
registration and NOT EXERCISED here.

Three safe unattended modes are spelled out, each with what it needs and who must authorise it, and
the two `schtasks /change /ru … /rp …` lines are recorded for the owner to run. **Not applied**: storing
an account credential on this host is exactly what this project's rules forbid an automated agent to
do. Until a person makes that change, the accumulation depends on the session staying alive.

## 7. Resources and growth

| | |
| --- | --- |
| Lane / declared budget | 3 288 974 / 268 435 456 bytes (**1.23 %**) |
| Watchdog's own tree | 193 564 bytes |
| Store | 5 621 615 bytes · 18 159 bars (609 `15m` / 5 444 `1h` per asset) |
| Free on the volume | 5.653 GiB of 237.5 GiB (**97.62 % used**) |
| Disk status | `HEALTHY` (warning floor 5 GiB, critical floor 2 GiB) — but **falling fast, and not because of this lane** |
| Measured growth | **1 493 484 bytes/day** over an 8.0 h window — published as a measurement, not a forecast |
| Declared growth thresholds | warn 16 MiB/day, stop 64 MiB/day; the 256 MiB lane budget over 60 days is 4.37 MiB/day |
| Never pruned | the store, `daily/<date>.json`, every published report, the run log, the slot ledger and the ingest ledger |
| Pruned | the bounded operational logs, at their declared caps, and the watchdog's own readings and alerts |

Two floors and two actions, both exercised in tests rather than live: below 5 GiB free the lane keeps
ingesting and the heavy publication waits; below 2 GiB the tick records `DISK_BUDGET_EXCEEDED` and makes
**no market request at all**. The volume is 97.62 % full and that is not this lane's doing, but it is
this lane's risk, and the guard is the thing standing between a full disk and a half-written
observation. Between the two closure runs of this work package the free space fell from 6.012 GiB to
5.653 GiB — 0.36 GiB in eight minutes, against 16 KiB written by the lane in the same window — so the
warning floor is not hypothetical at this rate: another hour like that one crosses it, the lane keeps
ingesting, the heavy publication waits, and `DISK_WARNING` is raised. Nothing is deleted to make room,
which is the whole point of the two floors being declared in advance.

## 8. The published evidence

* **`VERIFICATION.json`** — the independent verifier, live, `VERIFY_PASS` **13/13**, plus
  `SELF_TEST_PASS` **15/15** sabotages detected, 0 skipped, exit 0.
* **`EDGE05_WATCHDOG_STATUS.json`** — the newest verdict, the count of readings and alerts, the alert
  vocabulary and the verdicts seen.
* **`EDGE05_RESOURCE_BUDGET.json`** — measured growth, declared floors, what each threshold does, what
  is never deleted and what is pruned.
* **`EDGE05_WINDOWS_CONTINUITY.json` / `.md`** — the registered settings, the operating system's own
  statement about the logon mode, what that permits, and the one change that would remove the
  limitation (which needs the owner's password and is therefore not applied).
* **`evidence/FASE5_TIMELINE.md`** — 42 lane ticks, 9 watchdog readings and 25 alerts on one page.
* **`evidence/STORE_SLICE.json`** — the bars after each series' epoch with the digest of the file they
  came from, small enough to version, so the reconciliation can be re-derived from the committed
  evidence instead of trusted.
* **`evidence/EDGE05_TASK_REGISTRATION.json`**, **`evidence/SNAPSHOT.json`** — the two registrations
  verbatim, and the digest and size of every artefact the closure wrote.

Everything above is regenerated from the live state by `scripts/edge05_closure.py`, which decides
nothing and rewrites nothing of the lane's.

## 9. What broke, and what was fixed

1. **A check that was right for the wrong reason.** The live verification spent most of the work
   package at `12/13`, failing `the_watchdog_really_detected_an_interruption`. That was not a bug to
   patch away: at the time, the episode was still **open** and no recovery had happened, so the claim
   the work package is judged on was genuinely undemonstrated. It passed on its own as soon as the
   re-enable and the recovering tick had actually occurred — which is the behaviour a check like this
   is supposed to have.
2. **A reconciliation with a shelf life.** After the recovering tick appended its nine bars,
   `reconciliation_chains_recomputed` failed by exactly one tick (`ledger_rows 68 vs 66`, `stored_bars
   5443 vs 5442`). The reconciliation is a *reading of the store at an instant*, and a live store moves.
   The closure sequence was corrected to reconcile and verify back to back and then publish, which is
   now the documented order; the verifier's own note records that a digest read at one instant and a
   file read later are expected to differ once the lane writes again.
3. **An audit silent about the switch that matters.** The continuity artifact read the task's
   registration by element path and listed absent elements at their schema default — except
   `Enabled`, which the platform omits when it is `true`. A reader therefore could not tell an enabled
   lane from a disabled one, which is precisely the fault this work package exists to catch. `Enabled`
   is now declared in the defaults and rendered, and trigger-scoped elements are excluded from the
   settings defaults so a trigger's own `Enabled` can never be reported as a task setting.
4. **A self-test that could pass by accident.** The market-expectation sabotage did not lie in every
   runtime state: it claimed a quiet market on the newest reading, and the check only contradicts that
   claim when the store is behind the closed-bar calendar — which, right after a tick has ingested, it
   is not. The same command therefore reported `SELF_TEST_PASS 15/15` or `SELF_TEST_FAIL 14/15`
   depending on when it ran, which is precisely the false confidence a sabotage matrix exists to
   prevent. The sabotage now moves the reading's instant three hours forward and **keeps** its claim,
   so the calendar always owes bars the store cannot hold and the lie is always a lie. The check was
   strengthened at the same time to verify the reading's own arithmetic — a summary that calls the
   market quiet while its own series report bars closed and uncollected is a contradiction no store
   state can excuse, and one a store that has since caught up would hide. Both the flip and the
   clock-drift are now covered, and the matrix is deterministic rather than lucky.

## 10. Where it stands, and what is missing

| Item | State |
| --- | --- |
| Independent watchdog, no lease, no pipeline, no market request | **yes** |
| Watches ticks omitted, delays, blocks, dead processes, absent bars | **yes** (13 checks) |
| Tells a quiet market from an operational failure | **yes**, and asserted by a check of its own |
| Alerts and recovery recorded with evidence | **yes** (22 rows, 16 kinds, per transition) |
| Interruption really detected on the live lane | **yes** — 6 s detection, 24 m episode, closed by a named tick |
| Auditable bars ↔ ticks ↔ decisions correspondence | **yes** — six series, chains hold |
| Stored bars with no recorded execution | **named, not invented** (2 attempts, both closed) |
| The six bars of the previous crash | **traceable** — present, single coverage, closed |
| Idempotence / no double decision | **yes** — second ingest pass appends 0, `RESTART_PROOF_BROKEN` 0 |
| Windows continuity audited, safe mode proposed | **yes**; the logoff case is a recorded operator blocker |
| Growth measured, thresholds defined, near-full disk tested | **yes**; thresholds exercised in tests, not live |
| 60 forward days | **0 of 60** — this work package adds reliability, not a single forward day |
| A host that stays logged in | **required and not guaranteed** — `InteractiveToken`; surviving logoff needs a credential this work package will not hold |
| Long unattended window | **NOT_EXERCISED** — a 24-minute live outage, not 60 days of scheduled firing |
| Live `DISK_BUDGET_EXCEEDED` / `STORE_STALE` / `EVIDENCE_CORRUPT` | exercised by tests and the sabotage matrix, **not live** |

Not claimed: `PASS`, `CERTIFIED`, `PRODUCTION_READY`, `READY_FOR_PAPER`. The watchdog observes; it does
not admit, and it cannot promote a strategy. Zero of sixty forward days remains the honest reading of
the coverage rule.

## 11. How to reproduce

```bash
# the watchdog's last verdict, changing nothing
python scripts/edge05_watchdog.py --status

# a fresh reading; exit code 0/10/11/12 is OK/DEGRADED/ALARM/BLOCKED
python scripts/edge05_watchdog.py --json

# how long each part of the lane has been quiet, and why
python scripts/edge05_watchdog.py --silence

# the reconciliation, against the raw files
python scripts/edge05_reconcile.py

# the independent verifier, live, with the sabotage matrix
python scripts/edge05_verify.py --self-test

# the same against the committed slice of the store
python scripts/edge05_verify.py --slice reports/edge-recovery/WP-EDGE-05/evidence/STORE_SLICE.json

# regenerate every artefact in this directory from the live state
python scripts/edge05_closure.py
```

**Order matters for one of them.** `edge05_reconcile.py` and `edge05_verify.py` are a pair: the
verifier recomputes the ledger/bar chain from the files the reconciliation recorded, so the two are run
back to back. Run the verifier alone more than fifteen minutes after the last reconciliation and it is
supposed to report `reconciliation_chains_recomputed` failing by exactly the ticks the lane has added
since — that is the check working, not the watchdog failing. The published pair in this directory is
reconciliation `20:13:12Z` → verification `20:13:18Z`, both regenerated from the live state.
