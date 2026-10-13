# WP-EDGE-04 — RUN_REPORT.md

**What this is.** The record of a run that really happened: what was executed, on which commit, on
which host, with what data, what it decided, what it refused, what broke and what was fixed. The
machine-readable twin is `RUN_REPORT.json`; the tick-by-tick table is
`evidence/FASE7_TIMELINE.md`; the interpretation is
`EDGE04_AUTONOMOUS_EXECUTION_REPORT.md`.

Research only. Public market data, no credentials, no orders, no capital, no promotion. Nothing in
this work package can authorise PAPER or LIVE trading.

---

## 1. The run

| | |
| --- | --- |
| Window | `2026-10-13T11:24:03Z` → `2026-10-13T15:07:57Z` |
| Unattended scheduled span | `11:23:27Z` → `14:55:55Z` (2 h 5 m) |
| Host / runtime | `DESKTOP-4CHO695`, `.venv\Scripts\python.exe` 3.11.15 |
| Task | `TradingAgentic-EDGE04-Forward`, installed and enabled, every 15 min |
| Ticks | 22 — 17 scheduled, 5 manual |
| Outcomes | `OBSERVED` 14 · `ALREADY_OBSERVED` 3 · `NO_NEW_DATA` 3 · `ALREADY_RUNNING` 2 |
| Slot seals | 16, 16 distinct, none duplicated |
| Market requests spent | 68 |
| Newly closed bars stored | 51 (expected 51, missing 0) |
| Health at the close | `DEGRADED`, one reason: the measured growth rate is volatile |
| Independent verdict | `VERIFY_PASS` 15/15, `SELF_TEST_PASS` 20/20 |

## 2. The commits

| Commit | Subject | Files |
| --- | --- | --- |
| `5b1e771` | Say a pid cannot be probed instead of crashing the lease. | `campaign_lock.py`, `test_campaign_runtime.py` |
| `4b845c9` | Make the forward lane tick itself, once per slot. | the tick engine, the single entry point, the verifier, the closure, the lane's tests, `.gitignore` |

Base commit `1d5eda9e72b0ad07fa1807f2df33a5f5bb761668`. The shared-module fix is its own commit
because every campaign that takes this lease had the same trap. The lane's own artefacts (this
directory) are a third, separate commit — see §7. No other workstream's file was staged, and the
operational state under `data/forward/` is ignored by git and therefore not in any of them.

**Push: `BLOCKED_GITHUB_AUTH`** — re-probed after this work package's commits rather than assumed:

```
$ GIT_TERMINAL_PROMPT=0 GIT_ASKPASS=/bin/true timeout 60 git push --dry-run origin HEAD
(60 s, no output, killed)  exit 124
```

`origin` is `https://github.com/Extr3sao/bot_crypto.git`; the credential helper never returns because
the prompt it is waiting for is disabled. The probe was a **dry run** and no credential was supplied,
so nothing left this machine. The commits stay local rather than being re-attributed to somebody
else. This is the same blocker the previous work packages recorded; it is a diagnosis, not a pass.

## 3. What the ticks did with the data

* **Only closed bars.** `expected_closed_bars()` computes the newest bar that can have closed at the
  tick's own market instant. The 15-minute-only ticks spend 4 requests and store 3 bars; the ticks
  that straddle the hour spend 7 and store 6. That ratio is the point-in-time rule, visible.
* **Nothing re-fetched.** A tick whose slot is already sealed never runs the pipeline (`--due` ⇒
  `ALREADY_OBSERVED`, 0 requests, 0 evidence written).
* **Per series, for the day:** `15m:BTC` 14 · `15m:ETH` 14 · `15m:SOL` 14 · `1h:BTC` 3 · `1h:ETH` 3 ·
  `1h:SOL` 3 = 51, which is the day's own total and the sum of every run row's `new_bars`. The store
  holds 18 084 bars and the day's recomputed digests match the ones the day file recorded.
* **Latency** is measured close → store per bar the tick pulled, and the forward rule reads it: a
  bar counts only if it arrived within 30 min (`15m`) or 2 h (`1h`) of closing.

## 4. What it decided, and what it refused

* Ruleset pinned on every tick: `params_hash d073a2d686b9b198…` agrees with the publication;
  `forward_plan.assert_frozen_params()` runs **first**, so a moved ruleset is `VERIFICATION_FAILED`
  (exit 6) before a single request.
* 16 arms re-read over the forward window on each tick. Primary arm `edge_trend_01_4h:BASE`, and its
  hypothetical window: 31 trades, gross **-9.087451 USDT**, fees **29.608409**, price costs
  **5.611636**, net **-44.307497 USDT**, max drawdown **2.776571 %**, 3 974 no-trade bars.
  *Hypothetical.* Costs and slippage are applied; nothing was realised and nothing is expected.
* 324 signals and 951 refusals in the window; 101 captured decisions with digest
  `e6ed38e7015e25de…`. **0 signals and 0 trades on this date** — the day's own rows are empty, which is
  what an hours-old observation window looks like.
* Risk parity against the real Risk Engine: **`PARITY_PASS`, 0 defects**, 544 decisions compared —
  79 `AGREE_APPROVED`, 155 `AGREE_REFUSED_SAME_RULE`, 194 `RULE_ORDER_DIFFERS`, 72
  `RULE_NOT_MODELLED_BY_RESEARCH`, 35 `SIZING_ROUNDING_ONLY`, 9 `RESEARCH_ONLY_REFUSAL`. The
  research budget is compared with the engine's own verdicts on the same inputs; a difference is
  named, never smoothed.

## 5. The two errors, and why neither is a failure being hidden

Both are `ALREADY_RUNNING` refusals, exit 2, **0 market requests**, no slot consumed:

| at (UTC) | run | reason as written | what it was |
| --- | --- | --- | --- |
| `11:25:39Z` | `FWD-EDGE04-20261013T111500Z` | `holder pid 35104 is live and renewed` | a manual probe while the scheduled tick held the lease |
| `15:03:55Z` | `FWD-EDGE04-20261013T150000Z` | `holder pid 1308 is live and renewed` | the tick after the controlled kill, inside the lease's age bound |

The second one is the interesting one: the holder was already **dead**, and the lease could not
legally be reclaimed yet. The honest statement is the lease's arithmetic — who holds it, how long
ago they renewed it, whether the bound has passed — and not a claim of liveness this platform cannot
always prove. The wording was corrected after these two rows were written (`4b845c9`); the rows
themselves are left as they are, because a run log that gets edited when it becomes inconvenient is
not a run log.

## 6. What broke, and what was fixed

Four defects were found by running the thing, not by reading it. All four are described in
`EDGE04_RUNTIME_AUDIT.md` §10b; this is the short list.

1. **The lease probe crashed the trigger.** `os.kill(pid, 0)` for a stale pid answers `WinError 87`
   on this host, raised as `SystemError`, which is not an `OSError`; the first controlled-kill
   rehearsal died with exit 1 instead of refusing. Fixed in `campaign_lock._pid_probe()` (returns
   `None`, so the age rule decides) with a regression test, commit `5b1e771`.
2. **The byte reading excluded the tick's own row.** `budget_reading()` ran before the run row was
   appended, so the artefact reported a lane smaller than the tree holding it. The verifier refused
   it — *"9227 bytes below the tree, more than the 6433 bytes of the files written after it"* — and
   the reading is now taken after the appends.
3. **The snapshot copied a curated list.** A file the list did not know made the copy smaller than
   the tree the reading describes, and that failure looks exactly like an inflated reading. The
   snapshot is now the whole state root, dot-entries excepted, with a digest per file.
4. **The day file could overwrite an interval's numbers.** `daily/2026-10-13.json` disagreed with the
   slot ledger after a repeat trigger, the verifier refused it, and the **next scheduled tick**
   corrected it from the seal (slot `14:30Z`: `NO_NEW_DATA`/0 → `OBSERVED`/3, `at_utc 14:41:45Z`).
   The day's slot table is derived from the seal on every tick now.

One more, about the tools rather than the lane: the self-test's *"grow a bounded log past its cap"*
sabotage was being caught only as a side effect of a byte comparison — the cap arm itself compared
file names the bundle never loads, so it could never fire. Both were repaired, and the sabotage now
crosses the declared cap. A check that cannot fail is not a check.

## 7. The published evidence

* **Snapshot**: `evidence/` is the whole live state root at `15:08:17Z`, 24 files, each with its
  sha256 and byte count in `evidence/SNAPSHOT.json`. The closure records whether a tick wrote while
  the copy was being taken; this time it did not (`snapshot raced: no`).
* **Publication**: `LATEST.json` names 13 artefacts and the verifier recomputes all 13 from disk.
  The heavy set is rendered once per 24 h, not per tick, and swapped in by pointer over a staging
  tree.
* **Offline reproduction**: `--report-only … --compare` reproduces `daily`, `daily_rollup` and
  `summary` byte for byte, and **not** `cumulative`, whose "Ledger rows on file" line is a live
  reading (228 now, 12 as published). Three of four, stated as three of four: the reproduction
  property is real but it expires, and that is a finding rather than a footnote.
* **Independent verification**: `INDEPENDENT_VERIFICATION.json` — `VERIFY_PASS` 15/15,
  `SELF_TEST_PASS` 20/20 sabotages detected, 0 skipped. Re-run afterwards against the **committed**
  snapshot (`VERIFIER_RERUN.json`, `15:16:24Z`): same 15 checks, same 20 sabotages, exit 0 — the
  published verdict is re-derived rather than merely described.
* **Closure artefacts**: `EDGE04_FORWARD_COVERAGE.json`, `EDGE04_RESOURCE_BUDGET.json`,
  `EDGE04_HEALTH_REPORT.json`, `evidence/FASE7_TIMELINE.md`, all regenerated from the live state by
  `scripts/edge04_closure.py`, which decides nothing and rewrites nothing.

## 8. Resources

| | |
| --- | --- |
| Lane / budget | 2 998 142 / 268 435 456 bytes (1.12 %) |
| Store | 5 598 300 bytes |
| One-off publication | 2 450 494 bytes |
| Free on the volume | 6.7546 GiB of 237.5264 GiB (97.16 % used) |
| Disk status | `HEALTHY` (warning floor 5 GiB, critical floor 2 GiB) |
| Measured growth | **no forecast**: rate volatile (cv 0.556), mean 1.86 MB/day |
| Tick wall time | median 31.3 s, max 49.2 s over 22 ticks |
| Bounded logs | runs 2 880 · slots 2 880 · ledger 4 032 · daily 366 · alerts 500 rows |
| Never pruned | the store, `daily/<date>.json`, every published report |

The volume is 97.16 % full and that is not this lane's doing, but it is this lane's risk: the tick's
own guard (`DISK_BUDGET_EXCEEDED`, exit 5, **no market request**) is the thing standing between a
full disk and a half-written observation. It has not fired, and it has been exercised by tests.

## 9. Where it stands, and what is missing

| Item | State |
| --- | --- |
| Scheduler installed, enabled, firing unattended | **yes** |
| Closed-bar ingest, no duplicates, point-in-time | **yes** |
| Crash → refusal → reclaim, no duplicate bar | **yes** (controlled kill at `15:02:21Z`) |
| Independent verification | `VERIFY_PASS` 15/15, `SELF_TEST_PASS` 20/20 |
| Forward observation days | **0 of 60** (227 days hold data; 226 are dense but backfilled) |
| A host that stays logged in | **required and not guaranteed** — the task runs under `InteractiveToken`, and surviving logoff needs stored credentials this work package will not hold |
| Long unattended window | **NOT_EXERCISED** — 2 h 5 m is not 60 days |
| Linux registration | **NOT_EXERCISED** — no POSIX host here |

Not claimed: `PASS`, `CERTIFIED`, `PRODUCTION_READY`, `READY_FOR_PAPER`. The lane observes; it does
not admit. Zero of sixty forward days is the honest reading of the coverage rule, and a day on which
the scheduler ran is not one of them.
