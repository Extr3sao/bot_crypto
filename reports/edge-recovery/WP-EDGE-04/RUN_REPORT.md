# WP-EDGE-04 — RUN_REPORT.md

**What this is.** The record of a run that really happened: what was executed, on which commit, on
which host, with what data, what it decided, what it refused, what broke and what was fixed. The
machine-readable twin is `RUN_REPORT.json`; the tick-by-tick table is
`evidence/FASE7_TIMELINE.md`; the interpretation is
`EDGE04_AUTONOMOUS_EXECUTION_REPORT.md`.

This reading was taken at **`2026-10-15T15:45:51Z`** and supersedes the one of
`2026-10-13T15:20:00Z`, which described the first 22 ticks of the same lane. The lane was not
restarted to write it: the same state root, the same task, the same ruleset, three days later. The
closure that produced it ran against the code as committed (`351ecba`), not against an earlier
revision: the evidence published here is the output of the code published with it.

Research only. Public market data, no credentials, no orders, no capital, no promotion. Nothing in
this work package can authorise PAPER or LIVE trading.

---

## 1. The run

| | |
| --- | --- |
| Window | `2026-10-13T11:23:38Z` → `2026-10-15T15:42:11Z` (2 days 4 h 19 m) |
| Unattended scheduled ticks | 190 of the 196 |
| Host / runtime | `DESKTOP-4CHO695`, `.venv\Scripts\python.exe` 3.11.15 |
| Task | `TradingAgentic-EDGE04-Forward`, installed and enabled, every 15 min |
| Ticks | 196 — 190 scheduled, 6 manual |
| Outcomes | `OBSERVED` 139 · `DISK_BUDGET_EXCEEDED` 45 · `ALREADY_OBSERVED` 7 · `NO_NEW_DATA` 3 · `ALREADY_RUNNING` 2 |
| Hard failures | **0** (`RUNTIME_EXCEPTION`, `VERIFICATION_FAILED`, `PROVIDER_UNAVAILABLE`, `MISSING_BARS`, `STALE_DATA`) |
| Slot seals | 141, 141 distinct, none duplicated |
| Market requests spent | 676 |
| Newly closed bars stored | 777 across 6 series |
| Longest silence between consuming ticks | `27 918.8 s` (7 h 45 m, the machine's night) |
| Health at the close | `DEGRADED`, one reason: the measured growth rate is volatile |
| Independent verdict | `VERIFY_PASS` 15/15, `SELF_TEST_PASS` 20/20 |

This session re-drove the lane by hand as well, through the scheduler rather than around it:
`--run-task` asked Task Scheduler to fire the registered task, the scheduler reported
`CORRECTO: se ha intentado ejecutar la tarea programada`, and the task's own **`last_task_result`
became `0`** — the OS's field, not the installer's return value. Three ticks followed from that
interaction, all recorded below.

## 2. The commits

| Commit | Subject | Files |
| --- | --- | --- |
| `5b1e771` | Say a pid cannot be probed instead of crashing the lease. | `campaign_lock.py`, `test_campaign_runtime.py` |
| `4b845c9` | Make the forward lane tick itself, once per slot. | the tick engine, the single entry point, the verifier, the closure, the lane's tests, `.gitignore` |
| `75cb791` | Publish the forward observer's evidence, its verdict and its record. | this directory |
| `e07785b` | Record the post-commit re-verification and the push probe. | this directory |
| *this session* | Correct the two artefacts the verifier refused, and harden the snapshot against a mixed copy. | `edge03/autonomous.py`, `scripts/edge04_verify.py`, `tests/unit/research/test_edge04_autonomous.py`, this directory |

Base commit `1d5eda9e72b0ad07fa1807f2df33a5f5bb761668`. No other workstream's file is staged: the
modified files under `data/st6/`, `data/recovery/wp8/`, `evidence/real_decisions/` and
`docs/source_registry.md` belong to other lanes and were left exactly as they were found. The
operational state under `data/forward/` is ignored by git and is therefore in none of these commits.

**Push:** probed, not asserted, after the commits — `git push --dry-run origin HEAD` answered
`Everything up-to-date` at `2026-10-15T15:27Z`, i.e. the remote already carries this work package's
committed work. The probe is a dry run and pushes nothing; no credential was supplied to it.

## 3. What the ticks did with the data

* **Only closed bars.** `expected_closed_bars()` computes the newest bar that can have closed at the
  tick's own market instant. A  15-minute-only tick spends 4 requests and stores 3 bars; a tick that
  straddles the hour spends 7 and stores 6. 676 requests produced 777 bars and **0 missing**.
* **Nothing re-fetched.** A tick whose slot is already sealed never runs the pipeline (`--due` ⇒
  `ALREADY_OBSERVED`, 0 requests, 0 evidence written). Seven ticks took that path, several of them
  fired by the OS scheduler while this report was being written.
* **Per series, over the window** (summed from the three day files, so the figures include the bars
  the lane recovered after the disk block): `15m:BTC` 208 · `15m:ETH` 208 · `15m:SOL` 208 ·
  `1h:BTC` 51 · `1h:ETH` 51 · `1h:SOL` 51 = 777. The store holds 18 810 bars and every day file's
  digests re-derive from it (§6c).
* **Latency is measured, and it is not flattering.** Close → store, per bar the tick pulled: the
  median tick reports a fresh-bar median of **658.6 s** and the worst reports **27 658 s**. The large
  figures are the recovery after a block: the high-water mark makes the pipeline re-fetch hours of
  bars it missed, and those bars *name their own lateness* instead of being smoothed into the
  healthy ones. The forward rule reads exactly this number: a bar counts only if it arrived within
  30 min (`15m`) or 2 h (`1h`) of closing, which is why days 2026-10-13 and 2026-10-14 did not reach
  the 90 % coverage floor (§5).

## 4. What it decided, and what it refused

* Ruleset pinned on every tick: `params_hash d073a2d686b9b198…` agrees with the publication on all
  141 pipeline runs; `forward_plan.assert_frozen_params()` runs **first**, so a moved ruleset is
  `VERIFICATION_FAILED` (exit 6) before a single request.
* 16 arms re-read over the forward window on each tick. Primary arm `edge_trend_01_4h:BASE`, and its
  hypothetical window: 31 trades, gross **−9.087451 USDT**, fees **29.608409**, price costs
  **5.611636**, net **−44.307497 USDT**, max drawdown **2.776571 %**, 3 974 no-trade bars.
  *Hypothetical.* Costs and slippage are applied; nothing was realised and nothing is expected.
* 324 signals and 1 101 refusals in the window; 101 captured decisions with digest
  `e6ed38e7015e25de…`. **0 signals and 0 trades on any of these dates** — the window's own rows are
  empty, which is what an hours-old observation window looks like.
* Risk parity against the real Risk Engine: **`PARITY_PASS`, 0 defects, on every one of the 141
  runs** that reached it.

## 5. Coverage: 0 of 60 forward days, and why the two near-misses are still zero

| Day | Class | Fresh `1h` bars of the 24 expected | Coverage | Counts |
| --- | --- | ---: | ---: | :-: |
| 2026-10-11 | `DENSE_BUT_BACKFILLED` | 0 | 0.0 % | no |
| 2026-10-12 | `DENSE_BUT_BACKFILLED` | 2 | 8.3 % | no |
| 2026-10-13 | `DENSE_BUT_BACKFILLED` | 14 | 58.3 % | no |
| 2026-10-14 | `DENSE_BUT_BACKFILLED` | 19 | 79.2 % | no |
| 2026-10-15 | `INCOMPLETE` (in progress) | 13 of 15 stored | 54.2 % | no |

**0 of 60**, 60 remaining. 229 days hold data and 228 of them are dense but backfilled. The floor is
90 % of the calendar's hourly bars per primary asset *arriving fresh*, and the lane reached 79.2 %
on its best day — a near miss that is reported as a miss, because a day at 79 % is not a day at 90 %
and the rule has no rounding. `BACKFILL_IS_NOT_AN_OBSERVATION` recomputes the same split from the
day files on every verification and passes: no day counted as observed fails the prospective rule,
because no day is counted at all.

## 6. What this session found by re-running the closure, and what was fixed

The re-run was not a formality. The closure renders the artefacts, copies the whole state root and
then hands that copy to `scripts/edge04_verify.py`, which shares no code with the lane. It **refused
the live lane twice**, on two different artefacts, and a third defect was found while reconciling
the first refusal. All three are described in `EDGE04_RUNTIME_AUDIT.md` §10c; this is the short list.

1. **The verifier refused two day files, and it was right.** `DAILY_EVIDENCE_CONSISTENT` reported
   `daily/2026-10-13.json: 15m:BTC digest does not answer to the store` (and the same for the other
   five series). The cause is structural: a day file is written by the ticks of *its own* day, so
   the last write of that day happens while the day is still running and can never hold the day's
   last bars. The `day_hashes` the file publishes for ever described a partial day — an artefact
   whose entire purpose is to make a claim about a day checkable, and which could not answer to the
   store it claims to describe. **Fixed**: a tick now re-derives the hashes of any *finished* day
   whose file disagrees with the store, rewrites only that file, and records that it did
   (`day_hashes_finalised_at_utc`). The very next tick corrected `2026-10-13` and `2026-10-14`,
   6 series each.
2. **The verifier refused the publication directory, and it was right too.**
   `PUBLICATION_SWAPPED_ATOMICALLY` reported *"15 published file(s) against 13 recorded digest(s); a
   published file answers to no recorded digest: DAILY_2026-10-13.md; … DAILY_2026-10-14.md"*. The
   pointer enumerated what the newest render *wrote*, while the swap leaves every earlier per-date
   report in place — the declared policy never deletes a published report. So the pointer described a
   subset of the directory while reading as if it described all of it, and a reader could not tell a
   live artefact from a leftover. **Fixed**: the pointer now enumerates the directory, keyed by each
   file's own path relative to the publication root, with its size, its digest, the role it was
   written under and whether *this* render wrote it. The check became name-for-name instead of
   digest-set membership, which is strictly stronger: 15 files named, 15 answered.
3. **The snapshot could be a mixture of two instants** — found while reconciling the first refusal,
   which mentioned a published file whose bytes in the evidence directory were those of the previous
   snapshot (136 444) and not those of the live tree (136 989). The copy is written into a directory
   that already holds one, and nothing dropped a file the live tree no longer had, so the directory
   could hold the union of two readings while claiming to be one. **Hardened**: exactly the files the
   *previous* `SNAPSHOT.json` recorded are dropped when the live tree no longer has them, and the
   snapshot names what it dropped. The copy is now whole in both directions — asserted by test, and
   measured: all 29 live files are byte-identical in `evidence/`.
4. **A guard that had never fired has now fired 45 times.** 45 ticks refused with
   `DISK_BUDGET_EXCEEDED` (exit 5, **0 market requests**, no slot consumed) between
   `2026-10-13T20:25:56Z` and `2026-10-14T13:40:56Z`, with the volume at 1.81 GiB free — below the
   declared 2 GiB critical floor. That is the guard working, not a defect, and it is why 2026-10-13
   and 2026-10-14 sit at 58 % and 79 % instead of higher: for ~17 hours the lane could not legally
   fetch. The volume now has 10.58 GiB free (95.55 % used) and the status is `HEALTHY`.

Between them these are the first *live* firings of `DISK_CRITICAL`, `DISK_WARNING`,
`DISK_RECOVERED`, `PUBLICATION_PAUSED`, `HEALTH_BLOCKED`, `OBSERVATION_GAP` and
`OBSERVATION_STALLED`; the alert log holds 21 rows, one per transition rather than one per tick.

## 7. The published evidence

* **Snapshot**: `evidence/` is the whole live state root at `15:45:51Z`, 29 files, each with its
  sha256 and byte count in `evidence/SNAPSHOT.json`, and every byte of it identical to the live tree
  (§6c). The closure records whether a tick wrote while the copy was taken; this time it did not
  (`snapshot raced: no`), and the copy had nothing to prune (`superseded_copies_dropped: []`), which
  is the §6c hardening running on the real destination and finding nothing to remove.
* **Publication**: `LATEST.json` enumerates **15 published files** — the 13 the newest heavy render
  wrote and the 2 per-date reports earlier renders left in place — and the verifier recomputes all
  15. The heavy set is rendered on the declared 24 h cadence and swapped in by pointer over a staging
  tree; this session forced one render (`--force`) because the pointer's own vocabulary had changed,
  and the tick record says so.
* **Offline reproduction**: `--report-only … --compare` reproduces `daily`, `daily_rollup` and
  `summary` byte for byte, and **not** `cumulative`, whose "Ledger rows on file" line is a live
  reading. Three of four, stated as three of four.
* **Independent verification**: `INDEPENDENT_VERIFICATION.json` — `VERIFY_PASS` 15/15,
  `SELF_TEST_PASS` 20/20 sabotages detected, 0 skipped, over the copy above. The verdict was
  **`VERIFY_FAIL` 13/15** on the first run of this session; the two failures and their causes are §6.
* **Re-derived against the committed snapshot** (`VERIFIER_RERUN.json`, 27 minutes later, offline,
  `--self-test`): same 15 checks, same 20 sabotages, exit 0. The published verdict is re-derived
  rather than merely described.
* **One arm of that verification has an expiry, and it is named.** The day-hash comparison is exact
  for ever for a day the store has finished, and exact only at the snapshot instant for the day the
  store is still filling: a running day file is refreshed by every tick, so a frozen copy of it can
  only answer to the store as it was when the copy was taken. The re-run above is inside that window;
  a reader re-running it after the store gains bars for 2026-10-15 should expect that one arm to
  report the day as an artefact of its own instant, and should re-take the snapshot with
  `scripts/edge04_closure.py` rather than re-verify a stale copy. Stating this as a limit, not as a
  pass, is the same treatment the `cumulative` reproduction gets two bullets above.
* **Closure artefacts**: `EDGE04_FORWARD_COVERAGE.json`, `EDGE04_RESOURCE_BUDGET.json`,
  `EDGE04_HEALTH_REPORT.json`, `evidence/FASE7_TIMELINE.md`, all regenerated from the live state by
  `scripts/edge04_closure.py`, which decides nothing and rewrites nothing.

## 8. Resources

| | |
| --- | --- |
| Lane / budget | 5 462 253 / 268 435 456 bytes (2.03 %) |
| Store | 5 824 046 bytes |
| Heavy publication | 2 544 674 bytes, once per 24 h |
| Free on the volume | 9.6136 GiB of 237.5264 GiB (95.95 % used) |
| Disk status | `HEALTHY` (warning floor 5 GiB, critical floor 2 GiB) |
| Measured growth | **no forecast**: rate volatile (cv 4.30, mean 2.05 MB/day) |
| Tick wall time | median 34.4 s, max 94.8 s, sum 5 874.9 s over 196 ticks |
| Bounded logs | runs 2 880 · slots 2 880 · ledger 4 032 · daily 366 · alerts 500 rows |
| Never pruned | the store, `daily/<date>.json`, every published report |

The volume has been both sides of its own floors during this window, which is the useful part: the
critical refusal was exercised for real (45 times), the warning path paused the heavy publication,
and 30.7 hours of host downtime and 17.2 hours of disk refusal are what separate 74 actual triggers
from the 96 the last 24 hours expected.

## 9. Where it stands, and what is missing

| Item | State |
| --- | --- |
| Scheduler installed, enabled, firing unattended | **yes** — 190 scheduled ticks, `last_task_result 0` read back from the scheduler |
| Closed-bar ingest, no duplicates, point-in-time | **yes** — 676 requests, 777 bars, 0 missing, 141 distinct seals |
| Crash → refusal → reclaim, no duplicate bar | **yes** (controlled kill at `15:02:21Z`, reclaimed at `15:07:24Z`) |
| Real disk exhaustion handled without a request | **yes** — 45 refusals, 0 market requests, 0 slots consumed |
| Independent verification | `VERIFY_PASS` 15/15, `SELF_TEST_PASS` 20/20 — after it first returned `VERIFY_FAIL` 13/15 |
| Forward observation days | **0 of 60** (229 days hold data; 228 are dense but backfilled) |
| A host that stays logged in | **required and not guaranteed** — the task runs under `InteractiveToken`; 30.7 h of silence in this window is that bound, measured |
| Long unattended window | **NOT_EXERCISED** — 2 days 4 h 19 m is not 60 days |
| Linux registration | **NOT_EXERCISED** — no POSIX host here |
| Provider outage, `STALE_DATA`, `MISSING_BARS`, moved ruleset | **NOT_EXERCISED** live — covered by the suite and the 20-sabotage matrix only |

Not claimed: `PASS`, `CERTIFIED`, `PRODUCTION_READY`, `READY_FOR_PAPER`. The lane observes; it does
not admit. Zero of sixty forward days is the honest reading of the coverage rule, and a day on which
the scheduler ran is not one of them.

## 10. The regression that covers the changes themselves

| | |
| --- | --- |
| `tests/unit/research` + `tests/unit/autonomous`, full | **2 584 passed, 1 failed** (13 m 27 s) |
| The lane's own regressions | 49 passed (`test_edge04_autonomous.py`, 45 before this session) |
| The scheduler layer | 284 passed (`tests/unit/autonomous`) |
| The frozen pipeline and the determinism suite | 48 passed (`test_edge03_forward.py`, `test_recovery_determinism.py`) |
| Lint | `ruff check` clean on all three changed files |

**The one failure is inherited and is not this work package's.**
`test_cost_barrier_adversarial.py::test_the_certification_record_digests_content_not_a_checkout`
fails because a certification record in another lane's package digests `8a101e88…` for
`data/recovery/ACTIVE_ECONOMIC_AUDIT.json`, which hashes `d1d49f09…` at HEAD and on disk. Neither
commit of this session touches that file — its last change is `7522255` (`[WP-EDGE-01]`) — and the
same failure was already recorded by `WP-EDGE-09F` before this session began. It is reported here as
a failure with an owner, not smoothed into a pass and not silenced by editing the assertion.

The two defects this session fixed were found by the verifier, not by the suite; the suite is what
says the fixes did not break anything else, and it is reported with its failure attached.
