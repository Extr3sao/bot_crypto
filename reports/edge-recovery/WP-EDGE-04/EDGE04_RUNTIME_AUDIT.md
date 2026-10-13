# WP-EDGE-04 — EDGE04_RUNTIME_AUDIT.md

**What this is.** The FASE 0 audit: which runtime already existed when this work package started,
what was reused unchanged, what had to be added, and which limits of the host are declared rather
than discovered later. It is an audit, not a proposal: every path below was read at
`1d5eda9e72b0ad07fa1807f2df33a5f5bb761668` before a line of WP-EDGE-04 was written.

Research only. Public market data, no credentials, no orders, no capital, no promotion.

---

## 1. Entrypoints

| Role | Path | What it is |
| --- | --- | --- |
| Frozen pipeline (WP-EDGE-03) | `scripts/edge03_run.py` | CLI over `trading_bot.research.edge03.run.run_forward_observation` |
| Forward observation engine | `src/trading_bot/research/edge03/run.py` | ingest → frozen rulesets → shadow decisions → parity → reports |
| **Autonomous tick engine (WP-EDGE-04)** | `src/trading_bot/research/edge03/autonomous.py` | `ForwardObserver.tick()`: lease, guard, ingest, evaluate, evidence, report |
| **Single portable entry point (WP-EDGE-04)** | `scripts/edge04_observer.py` | argument parsing, observer construction, exit code; nothing else |
| Independent verifier (runtime) | `scripts/edge04_verify.py` | reads the artefacts and *disagrees* with them where they are wrong |
| Independent verifier (evidence) | `scripts/edge03_verify.py` | the WP-EDGE-03 verifier, unchanged |

No second orchestrator and no second agent architecture was created. The tick engine composes the
modules WP-EDGE-03 already published; the entry point is a five-line argument parser around it.

## 2. Scheduler that already existed

`scripts/cap004_supervisor.py` §9 is the repository's OS-scheduler layer, and it is complete
enough to reuse rather than shadow:

| Function | Behaviour |
| --- | --- |
| `scheduler_type()` | `windows_task_scheduler` on `os.name == "nt"`; `systemd_user` on Linux when `systemctl` exists; otherwise `none` |
| `install_scheduler(interval_minutes=, task_name=, arguments=)` | writes the task XML, `schtasks /create /tn <name> /xml <file> /f`, returns `INSTALLED`/`UPDATED`/`INSTALL_FAILED`/`UNSUPPORTED_SCHEDULER` and the task's own status |
| `scheduler_status()` | `schtasks /query /tn <name> /xml ONE` → `installed`, `enabled`, `state`, `last_run_time`, `last_task_result`, `next_run_time`, `missed_runs`, `multiple_instances`, `start_when_available` |
| `enable_scheduler()`, `uninstall_scheduler()`, `run_task_now()` | the rest of the lifecycle |
| `build_task_xml()` | `TimeTrigger` + `Repetition` `/Interval PT{n}M` `/Duration P3650D`, `IgnoreNew`, `StartWhenAvailable`, `ExecutionTimeLimit PT1H`, `AllowHardTerminate`, `RestartOnFailure PT5M ×3`, `WakeToRun false`, `LeastPrivilege`, `InteractiveToken`, `<Exec>` with command, arguments and working directory |

**Decision: reuse it, under a different task name.** WP-EDGE-04 registers
`TradingAgentic-EDGE04-Forward` through the same installer; the CAP-004 campaign task is untouched
and neither task can start the other's process. A second scheduler implementation would have been
a second set of failure modes.

## 3. Ingest and evaluation scripts (reused unchanged)

* `src/trading_bot/research/edge03/ingest.py` — `ForwardStore` (line-per-bar JSONL, append-only,
  high-water mark per series), `BinancePublicKlines` (public `/api/v3/klines`, bounded retries),
  `ScriptedKlineSource` (the offline rehearsal source), `IngestLedger`.
* `src/trading_bot/research/edge03/parity.py` — the frozen-ruleset replay and the risk-parity audit
  (`PARITY_PASS` / defect list).
* `src/trading_bot/research/edge03/shadow.py` — hypothetical decisions and equity, `hypothetical:
  true`, `order_sent: false`.
* `src/trading_bot/research/edge03/reporting.py` — `write_observability()` renders the published
  artefact set from a preserved observation payload, with no network.

## 4. Frozen rulesets and pins

| Pin | Where | Value |
| --- | --- | --- |
| Parameters | `trading_bot.research.edge01.candidates.FROZEN_PARAMS` / `PARAMS_HASH` | recipe `sha256(json.dumps(FROZEN_PARAMS, sort_keys=True, separators=(',', ':')))` |
| Published digest | `reports/edge-recovery/WP-EDGE-01/oos-trend-4h/OOS_TREND.json#params_hash` | re-derived and compared on every tick (`forward_plan.assert_frozen_params()`) |
| Observation floor | `forward_plan.MIN_OBSERVATION_DAYS` | 60 days |
| Day admission | `forward_plan.OBSERVATION_COVERAGE` | 0.90 of the bars the calendar expects, per primary asset |

Every tick calls the pin **first**. A moved ruleset or corpus is `VERIFICATION_FAILED` (exit 6), an
outcome, never a warning. WP-EDGE-04 does not add, relax or re-derive a single threshold.

## 5. Evidence store and ledger

* Forward store (bars, authoritative): `data/forward/edge03/` — `line/…` JSONL per series.
* WP-EDGE-03 published ledger: `reports/edge-recovery/WP-EDGE-03/forward-observation/INGEST_LEDGER.jsonl`.
* WP-EDGE-04 state: `data/forward/edge04/` — `runs.jsonl`, `slots.jsonl`, `alerts.jsonl`,
  `daily/<date>.json`, `ledger/INGEST_LEDGER.jsonl`, `coverage.json`, `health.json`,
  `resource_budget.json`, `install.json`, `lock/`, `publication/`.

The audit found one real hazard: `run_forward_observation()` wrote its ingest ledger to the
WP-EDGE-03 path unconditionally, so an unattended tick would have interleaved its rows into the
ledger an earlier work package published. The fix is a named seam — `ledger_dir` / a
`default_ledger_dir()` helper in `edge03/run.py` — and WP-EDGE-04 passes its own root. Two writers,
two logs, one reader per log.

## 6. Independent verifier

* `scripts/edge03_verify.py` verifies the WP-EDGE-03 evidence set (unchanged).
* `scripts/edge04_verify.py` verifies the *runtime*: it reads the artefacts only (no import of the
  tick engine's decisions), re-derives what it can from the store on disk, and runs a self-test that
  sabotages each check to prove the check can fail. Its verdict is written to
  `INDEPENDENT_VERIFICATION.json`.

## 7. Resource policies (already declared, reused)

| Policy | Source | Value |
| --- | --- | --- |
| Warning floor | `HEALTHY_FREE_BYTES` via `disk_space.py` | 5 GiB free |
| Critical floor | `CRITICAL_FREE_BYTES` | 2 GiB free |
| Lane budget | `autonomous.LANE_BUDGET_BYTES` | 256 MiB outside the store |
| Bounded logs | `RUNS_KEPT` / `SLOTS_KEPT` / `LEDGER_KEPT` / `DAILY_KEPT` / `ALERTS_KEPT` | 2 880 / 2 880 / 4 032 / 366 / 500 rows |
| Heavy publication | `PUBLICATION_INTERVAL_SECONDS` | once per 24 h, not per tick (~2.3 MB per render) |

Measured at audit time on this host: `C:` had **7.49 GiB free of 237.5 GiB (96.85 % used)** — above
the 5 GiB warning floor and far below it is comfortable. That reading is what made the scheduler
activation decision, and it is recorded in `EDGE04_RESOURCE_BUDGET.json` with the measured growth.

## 8. Windows and Linux configuration available

| | This host | Declared |
| --- | --- | --- |
| OS | Windows, `schtasks` present and answering | — |
| Python | `.venv\Scripts\python.exe`, 3.11.15 | stdlib only, no new dependency |
| Scheduler | Task Scheduler, task `TradingAgentic-EDGE04-Forward`, `Ready`, enabled, `IgnoreNew`, `StartWhenAvailable=true` | POSIX: the supervisor returns `UNSUPPORTED_SCHEDULER`; the equivalent cron line is in `EDGE04_SCHEDULER_DESIGN.md` §9 and was **not exercised** on this host |
| Logon mode | `InteractiveToken` (runs while the user session is active) | declared limitation, §10 |
| Codex/ChatGPT | not involved | the tick needs no interactive agent session at all |

## 9. What was reused, what was added

| Reused unchanged | Added by this work package |
| --- | --- |
| supervisor scheduler + task XML | `ForwardObserver` tick engine (`autonomous.py`) |
| lease idiom and `STOP` convention (`campaign_lock.py`) | `scripts/edge04_observer.py` (one portable entry point) |
| disk/health thresholds (`disk_space.py`) | `scripts/edge04_verify.py` (runtime verifier + self-test) |
| frozen pipeline, rulesets, shadow, reporting | the `ledger_dir` seam in `edge03/run.py` |
| the store, the ledger and their formats | `tests/unit/research/test_edge04_autonomous.py` |

## 10. Findings that changed the plan

1. **Interleaved ledger (fixed).** See §5. Without the seam, WP-EDGE-03's published ingest record
   would have grown rows that no WP-EDGE-03 run wrote.
2. **Alert vocabulary was wrong (fixed).** The first live ticks exposed it: a healthy tick after a
   healthy tick was announced as `HEALTH_RECOVERED`, a `HEALTH_RECOVERED` row was written carrying
   `state: DEGRADED`, and a second *trigger inside the same slot* counted as "a tick that observed
   nothing" and pushed the health reading to `DEGRADED`. The vocabulary now has
  `HEALTH_DEGRADED`, recovery is announced only after a non-healthy episode, and
  `ALREADY_OBSERVED`/`ALREADY_RUNNING` are skipped by the "ticks since the last observation"
  counter. Two spurious pre-fix rows survive in the surviving log and are quoted verbatim in
  `RUN_REPORT.md`; one further pre-fix row, which announced a recovery while carrying
  `state: DEGRADED`, was removed from the bounded alert log while the vocabulary was being fixed —
  its text lived only there and is not quoted, and the run log was not rewritten. What the
  surviving log now shows is what can be checked: no `HEALTH_RECOVERED` row that does not follow a
  recorded non-healthy episode, and every `HEALTH_DEGRADED` row carrying the reasons that produced
  it.
3. **Interactive logon is the real availability bound.** The task carries `InteractiveToken`, so it
   runs while the user session is active, and `StartWhenAvailable=true` fires the missed trigger as
   soon as the machine is back. Registering "run whether the user is logged on or not" would require
   storing account credentials, which this work package is not authorised to do. Consequence: 60
   days of coverage requires a host that is up, not merely a task that exists — see
   `EDGE04_SCHEDULER_DESIGN.md` §9.
4. **The host volume is 96.85 % full.** Safe for this lane (measured growth is ~11 KB/day for the
   lane tree plus ~5.6 MB of store), but the critical floor is 5.5 GiB away: the tick's own guard
   (`DISK_BUDGET_EXCEEDED`, exit 5, **no market request**) is the thing standing between a full
   volume and a half-written observation.
5. **No second orchestrator needed.** The audit's most useful result: WP-EDGE-03 was already
   callable as one function, and the repository already had a scheduler, a lease idiom and a disk
   policy. WP-EDGE-04 is the missing caller.

### 10b. What running it found that reading it did not

Everything below was found *after* the audit, by ticking the real runtime and then letting the
independent verifier disagree. They are listed because they are the reason the runtime is trusted:
four of the five were invisible to inspection and one of them crashed a process.

6. **A probe that cannot answer crashed the trigger (fixed).** `campaign_lock._pid_probe()` caught
   `ProcessLookupError`, `PermissionError` and `OSError`; this host answers `os.kill(pid, 0)` for a
   stale pid with `WinError 87` raised as `SystemError`, which is **not** an `OSError`. The first
   controlled-kill rehearsal therefore died with a traceback and exit 1 instead of refusing the
   tick, leaving the lease unreclaimed *and* the failure unexplained. The probe now returns `None`
   for that case, so the lease's age rule decides — the behaviour the lane's own tests already
   asserted. Fixed in the shared `campaign_lock.py` with a regression test, because every campaign
   that uses the lease had the same trap.
7. **The byte reading was taken before the tick's own row (fixed).** `budget_reading()` was called
   from `health()`, which runs *before* the run row, the slot row and the budget sample are
   appended, so the artefact reported a lane smaller than the tree that holds it by exactly the
   bytes of the record describing the tick that took it. `INDEPENDENT_VERIFICATION.json` refused it
   ("9227 bytes below the tree, more than the 6433 bytes of the files written after it"). The
   reading is now taken after the appends, which makes the verifier's own rule — a reading can only
   be smaller than the tree at rest by the files that carry it — satisfiable by construction rather
   than by luck.
8. **The snapshot was a curated subset of the state root (fixed).** `snapshot()` copied a hard-coded
   list of file names. The lane then grew a file that list did not know
   (`slot_ledger_repair.json`, 774 bytes), so the snapshot was *smaller* than the tree the reading
   described and the same byte check failed again — in the direction that looks like an inflated
   reading, which is the worst possible misdiagnosis of a missing copy. `snapshot()` now copies the
   **whole** state root (dot-entries excepted) and records the digest of every file it copied, so
   the copy cannot silently disagree with the tree it is meant to be.
9. **The day file could disagree with the slot ledger (fixed).** See `EDGE04_SCHEDULER_DESIGN.md`
   §10: the day's slot table is now derived from the seal, so a repeat trigger cannot rewrite an
   interval's numbers and a day written by an older rule is corrected by the next tick.
10. **The self-test's own teeth were partly illusory (fixed).** The sabotage "grow a bounded log
   past its cap" was being caught by the byte check's size arm as a side effect, not by the cap
   arm, which could never fire: `BOUNDED_LOGS` named `RUNS.jsonl`/`SLOTS.jsonl`, names the bundle
   does not load, so the row counts it compared were always zero. The names are now the ones the
   bundle reads, and the sabotage crosses the **declared** cap instead of appending five rows to a
   2 880-row log. A check that cannot fail is not a check, and a sabotage that proves nothing is
   worse than no sabotage at all.
