# WP-051-02H — recovery, gap, and continuity of the forward observer

**Phase:** EXP-004A, phase 3 · **Work package:** WP-051-02H · **Branch:** `wp/exp004a-051-02h` ·
**Base commit:** `819cb0d2` · **Session date:** 2026-10-23 · **Experiment certified:** `false`

> The observer was never down. Its **task** fired every fifteen minutes throughout, and every
> fourth tick or so it refused to fetch, because the volume it writes to was under its own
> critical free-space floor. The store went silent for **345 minutes**, one day of the phase is
> gone for all three assets, and the phase can no longer reach `COVERAGE_COMPLETE`. It can still
> reach the declared 0.9 floor. The cause is the host's free space, not the lane's code, and the
> lane is still one bad afternoon away from losing another day.

---

## 1. The real state, first

Measured at `2026-10-23T06:57Z` from the **live** lane, not from a worktree copy.

| Reading | Value | Source |
| --- | --- | --- |
| Observer task | `TradingAgentic-EDGE04-Forward`, installed, last result `0` | OS scheduler |
| Cadence | `PT15M` for `P3650D`, `StartWhenAvailable`, restart 3×`PT5M`, `MultipleInstances=IgnoreNew` | OS scheduler |
| Last tick | `FWD-EDGE04-20261023T065500Z` at `06:55:57Z`, **refused** | `runs.jsonl` |
| The refusal that started the open episode | `FWD-EDGE04-20261023T064000Z` at `06:40:57Z` on `1.6262 GiB` free | `runs.jsonl` |
| Last consuming tick | `FWD-EDGE04-20261023T061500Z` finished `06:26:51Z`, 3 new bars | `runs.jsonl` |
| Tick age at audit | `767.1 s` (limit `2700 s`) | `health.json`, `runs.jsonl` |
| Ticks in the audited window | **52** — 16 `OBSERVED`, 36 `DISK_BUDGET_EXCEEDED` | `runs.jsonl` |
| Health | `DEGRADED` (below the 5 GiB warning floor; growth volatile) | `health.json` |
| Watchdog | installed, 15-minute cadence; raised a real `BLOCKED` alarm (`exit 8`, `LastTaskResult=8`) at `06:47:02Z` | OS scheduler, `WATCHDOG.json` |
| Free space | `1.43 GiB` of `237.5 GiB` — **99 % full**, and falling | `WATCHDOG.json`, `df` |
| Orders | `order_sent: false`, `promotion: NONE` in every record read | tick log, daily shard |

The recovery is real and the risk is still live: **the lane was refused again at `06:40:57Z`
and once more at `06:55:57Z`**, on `1.6262 GiB` and then `1.42 GiB` free, and at `06:47:02Z` the new
watchdog raised `ATTENTION_REQUIRED.txt` for the first time — a `BLOCKED` verdict with free space
falling from `2.30 GiB` to `1.43 GiB` inside twenty minutes. The episode audited below is the closed
one that cost the day; the open one is a second hole forming while this paragraph is written, and
the tick at `07:10:57Z` will say which way it went.

Two independent programs agree on that table (`exp004a_wp051_02h_audit.py`,
`exp004a_wp051_02h_verify.py`), and a third that predates this package
(`scripts/edge04_verify.py`) agrees with both on the daily lane: **15/15 `VERIFY_PASS`**.

## 2. What actually stopped, and why

`ROOT_CAUSE.json`, four claims, all `CONFIRMED`:

- **RC1 — the instant 02G named was a copy.** `data/forward/` is git-ignored; the 02G worktree's
  `18:00Z` was the end of a *copy*, not of the live store. The live store held bars to
  `2026-10-23T05:00Z` at audit time.
- **RC2 — the live store has a real hole, and the disk guard caused it.** 34 refusals between
  `2026-10-22T18:10:56Z` and `2026-10-23T05:55:56Z`; the lowest reading was **0.0 GiB** free; each
  refusal is the observer's own guard: *"0.4797 GiB free is below the 2147483648 byte critical
  floor: the tick refused before making a market request"*.
- **RC3 — the observer resumed by itself.** No process was restarted, no lock was cleared, no
  parameter was touched. The first consuming tick after the worst episode is
  `FWD-EDGE04-20261023T053000Z` at `05:40:57Z` with 87 bars, 900 s after the last refusal.
- **RC4 — the mechanism is intact.** `runs.jsonl` parses (912 lines, 0 corrupt), slots are sealed
  once, and `ALREADY_RUNNING` appears twice in the log's history: the lease has actually refused a
  second instance in production.

Not the cause, each excluded with evidence rather than assurance: a crash or missing entry point (the
task returned `0` and the log continues), a provider failure (no `PROVIDER_*` outcome in the window),
a stopped scheduler (`next_run_time` advanced every interval), a duplicate instance (no slot sealed
twice), a corrupted log (0 corrupt lines), and a code defect shipped by 02G (02G wrote no bar).

**Why nobody noticed for six hours:** the observer wrote `HEALTH_BLOCKED` into `alerts.jsonl` on
every refused tick — 60 alert lines exist — but that file has to be opened by a person. The new
watchdog converts that into an OS-visible exit code, which is the only reason this is measurable
without opening a file.

## 3. The hole, quantified

| Quantity | Value |
| --- | --- |
| Last consuming tick before the worst episode | `FWD-EDGE04-20261022T234500Z` at `23:55:56Z`, 3 bars |
| Worst episode | `2026-10-23T00:10:56Z` → `2026-10-23T05:25:57Z`, **22 refused ticks** |
| Lowest free space in the episode | `0.0 GiB` (`0.0218 GiB` at the last refusal) |
| Resume | `FWD-EDGE04-20261023T053000Z` at `05:40:57Z`, 87 bars |
| **Store silence** | **345.02 min** (20 701 s) — the last consuming tick to the resuming one |
| Recovery latency after the last refusal | **900 s** (exactly one cadence: the next scheduled tick) |
| Refusal episodes in the whole log | 23 |
| Bars stored in the window, all three assets | 6 per asset on `2026-10-23`, of which **3 admissible** |

The bars that did arrive during the silence were fetched 160–281 minutes after they closed, so
`LATE` (bound `7 200 000 ms`) is the correct verdict for them, and the day that holds them is
`DAY_OPEN_ALREADY_DOOMED` — already lost before it closed, because a late bar cannot be made on
time afterwards.

### Coverage, against the phase-3 declaration

| Reading | Value |
| --- | --- |
| Declared | 6 480 rows / 90 days / 3 assets × 24 bars |
| Lost days (all three assets) | `['2026-10-23']` — 72 rows |
| Rows still reachable | **6 408 / 6 480 = 0.988889** |
| Required fraction | **0.9** — the ceiling is still above it |
| `COVERAGE_COMPLETE` reachable | **`false`** — `CEILING_BELOW_DECLARED` |
| Quarantine applied | classification only: **no bar re-fetched, no timestamp synthesised, no threshold moved** |

The distinction the phase must live with: **the coverage floor can still be met; exactness cannot.**
6 408 rows is 98.9 % of the declaration, and `COVERAGE_COMPLETE` asks for `admissible == declared`
exactly — which one lost day makes arithmetically unreachable for the rest of the window.

## 4. The alternatives — presented, not applied

The declaration belongs to its owner, so this package changes nothing and recommends in order:

1. **Accept the 72-row hole and target the 0.9 floor.** Cost: none, and it is the only option that
   needs no new artefact. Consequence: the phase ends as `CEILING_BELOW_DECLARED`, and the eventual
   verdict must be phrased against the floor, never against `COVERAGE_COMPLETE`.
2. **Re-declare the window start** to the first day with no inadmissible bar. Cost: a new
   declaration file and a new effective instant, so a *new* experiment with a 90-day horizon from
   that instant; this package cannot decide it and did not write it.
3. **Restart phase 3 after the host's free space is fixed.** Cost: the 7 forward days already
   observed are discarded as evidence for the new window, plus 90 days. Only defensible if the disk
   condition is treated as a prerequisite, which `DEF-02H-01` argues it should be.

Recommended: **1**, paired with `DEF-02H-01` being closed before the next day is lost. Option 2
buys nothing that option 1 does not, and option 3 spends the only thing the phase cannot buy back.

## 5. Continuity

`CONTINUITY_REPORT.json`, ten properties, all `SATISFIED`, recomputed against the scheduler rather
than against the repository's `install.json`:

| Id | Property | Evidence |
| --- | --- | --- |
| C1 | automatic start | `PT15M` trigger for `P3650D` from `2026-10-13T13:25:53` |
| C2 | restart after failure | `restart_on_failure` count 3, interval `PT5M` |
| C3 | after a reboot | `StartWhenAvailable=true` — **see `DEF-02H-02`** |
| C4 | no two instances | `MultipleInstances=IgnoreNew` plus the tick's own lease; 2 real refusals |
| C5 | atomic, append-only persistence | 4 append-only logs, 0 corrupt lines |
| C6 | verifiable heartbeat | `health.json` every tick, age 751.7 s at audit |
| C7 | stale detection | `consecutive_non_observations=0`, silence limit 2 700 s |
| C8 | interruption log | `alerts.jsonl`, 60 lines, last alert carries its reason |
| C9 | the alarm reaches a person | watchdog task installed, `LastTaskResult` is the signal |
| C10 | no daily human step | 15-minute cadence, no interactive confirmation anywhere in the path |

The watchdog is a separate program (`scripts/edge04_watchdog.py`) that reads the lane's files,
never repairs them, and exits `0`/`1`/`8`/`9`/`2` for `OK`/`DEGRADED`/`BLOCKED`/`STALE`/
`UNREADABLE`. `DEGRADED` raises no marker on purpose: a marker that fires on a warning is a marker
people learn to ignore. `BLOCKED` and `STALE` write `ATTENTION_REQUIRED.txt` and lower it again on
the next healthy run.

## 6. The first daily capture after recovery

`data/forward/edge04/daily/2026-10-23.json`, written `06:26Z` by the observer's own publication
step, judged by `scripts/edge04_verify.py` (**not** by this package's builder):

| Check | Result |
| --- | --- |
| Shard created | yes — `2026-10-23.json`, and there is a verifiable reason it exists (99 bars due, 99 seen) |
| `new_bars` / `expected_new_bars` / `missing_bars` | 99 / 99 / **0** |
| `parity_verdict` | `PARITY_PASS` |
| `errors` | `[]` |
| Timestamps | `first_tick 05:41:33Z`, `last_tick 06:26:50Z`, `market_instant 06:26:00Z` |
| Digests | 6 series (`15m`/`1h` × BTC/ETH/SOL) recomputed from the store |
| Coverage | `prospectively_observed` 7 days, `remaining_days` 53, `densely_covered_but_backfilled` 229 |
| `order_sent` / `promotion` | `false` / `NONE` |
| `hypothetical` | `true` — the economics block only; the lane sends nothing |
| Independent verdict | **`VERIFY_PASS` 15/15**, including `DAILY_EVIDENCE_CONSISTENT` (11 day files, 66 digests) and `PUBLICATION_SWAPPED_ATOMICALLY` (21 files) |

This is one real day's shard, not a rehearsal and not a projection. It says nothing about tomorrow,
and is not presented as if it did.

## 7. Tests, and what each one proves

| Suite | Result | Proves |
| --- | --- | --- |
| `tests/unit/research/test_exp004a_wp051_02h.py` (new, 27 tests) | **27 passed** (3.75 s) | watchdog statuses and marker lifecycle, disk floors, corrupt-line accounting, the audit's lag/quarantine/ceiling arithmetic, the seal's refusal to overwrite, the verifier's ability to *fail* a claim that hides a lost day, and the anchoring rule below |
| `tests/unit/research/test_exp004a_wp051_02g.py` (unchanged, 49 tests) | **49 passed** (36.55 s) | 02G's frozen behaviour is intact under this package's changes |
| `scripts/exp004a_wp051_02h_verify.py` (independent) | **17 checks, 0 failed, `PASS`** | the reports survive a second implementation reading the same bytes |
| `scripts/edge04_verify.py` (pre-existing, independent) | **15/15 `VERIFY_PASS`** | the live lane's artefacts, including today's daily shard |
| Real ticks | 16 `OBSERVED` inside the audited window, 2 real `ALREADY_RUNNING` refusals | the mechanism, not a simulation |
| Real alarm | `BLOCKED` at `06:47:02Z`, `exit 8`, marker written and worded with its reason | `C7`/`C9` hold in production, not only in a unit test |

Named scenarios from the mission, and where each stands: normal start (real, `06:25:58Z`); concurrent
second start (real refusals in history + `MultipleInstances=IgnoreNew` + lease + unit test); unexpected
termination (no termination occurred — the failure was refusal, not death; the watchdog's `STALE`
path is unit-tested and its 2 700 s limit was never crossed); supervised recovery (real, `900 s`);
restart with persisted state (real: the state root survived nine days of ticks and 912 log lines);
no duplicates (recomputed: 0 slots sealed twice); provider failure (**not observed** in the window —
reported as untested rather than passed); stale data (unit-tested, not observed in production);
coverage gaps (real); quarantine (real, classification only); immutable shard preservation (declaration
blob and 02b–02g tree compared with `HEAD`, 0 drifted).

A unit test is never counted here as a production proof: the rows above separate the two.

## 8. Defects and limitations

- **`DEF-02H-01` — the volume is the experiment's real risk, and it is not fixed.** Free space
  oscillated between `0.02` and `8.2 GiB` inside six hours against a `2 GiB` critical floor. The
  lane itself owns `14 228 034` bytes of its `268 435 456` byte budget, so the pressure is the
  host's, not the lane's. **Nothing in this package frees disk space** — that is an owner decision
  on a shared volume, and deleting another lane's evidence is not this package's to do. Until it is
  addressed, expect more refused ticks and more lost days; the coverage floor survives one or two
  such days, not thirty.
- **`DEF-02H-02` — C3 is conditional on an interactive logon.** The task principal is
  `InteractiveToken`: after a reboot the task resumes only when that user signs in. Changing it to
  "run whether the user is logged on" needs administrator rights and was **not** performed. This is
  the largest residual continuity risk over a 90-day window.
- **`DEF-02H-03` — the alarm is a file and an exit code, not a message to a person.** The watchdog
  makes failure visible to the OS scheduler; it does not notify anyone. Closing it means choosing a
  channel (out of scope here), and until then a human must look at the scheduler.
- **`DEF-02H-04` — `COVERAGE_COMPLETE` is unreachable for phase 3.** A consequence of the lost day,
  not a defect to repair: see §4 for the owner's options.
- **`DEF-02H-06` (found here, fixed here) — a claim that moved with the clock.** When a second
  refusal opened at `06:40:57Z`, the builder anchored its finding, its recovery tick and its
  latency to that *unresolved* episode, so `RC3` flipped to `REFUTED` and the independent verifier
  failed `RECOVERY_CLAIM` — on a hole that was already closed and correctly measured. Both programs
  now anchor to the last refusal the observer got past, and the running episode is reported beside
  it as `episode_in_progress`/`open_episode` instead of being averaged into the finding. Two tests
  pin this (`an_open_episode_does_not_erase_the_closed_one_it_followed`,
  `the_verifier_keeps_the_recovery_claim_when_a_newer_refusal_is_open`). It is the same class of
  error as `DEF-02G-08`: a claim whose truth decays after it is sealed.
- **`DEF-02H-05` — provider failure remains untested in production.** No `PROVIDER_*` outcome exists
  in the window; the code path is unit-tested only.
- Observed and **not touched** (outside this package's scope): `TradingAgentic-ST6-Forward` is
  `Disabled` with last result `3`, and `TradingAgentic-EDGE05-Watchdog` last returned `10`. Both are
  reported, neither is repaired here.

## 9. Verdicts

| Verdict | Value | Basis |
| --- | --- | --- |
| `RECOVERY_PASS` | **`true`**, for the audited hole | observer running (task fired on cadence, tick age `767 s`), a real forward capture (`06:10:58Z`, 9/9 bars, persisted, `store_sha256` recorded), no duplicates, the hole quantified (345.02 min), coverage classified per the existing contract. A **new** refusal episode opened at `06:40:57Z` and is reported open, not recovered |
| `CONTINUITY_PASS` | **`true`, with `DEF-02H-02` recorded** | supervision operative, restart and resume exercised for real, data preserved and append-only, health and alarm readable by the OS, independent verifier agrees |
| `EXPERIMENT_CERTIFIED` | **`false`** | 0 of 90 days complete; `CEILING_BELOW_DECLARED`; this package certifies nothing |

`FALSE_SUCCESS = 0`: no test is reported as a production proof, no simulation stands in for a tick,
and the one number that would have made the phase look whole — `6480` — appears nowhere as a result.

## 10. Commands actually executed

| Command | Exit |
| --- | --- |
| `python scripts/exp004a_wp051_02h_audit.py --all --state-root <main>/data/forward/edge04 --store-root <main>/data/forward/edge03` | `0` |
| `python scripts/exp004a_wp051_02h_verify.py --state-root … --store-root … --out …/INDEPENDENT_VERIFICATION.json` | `0` (17/17) |
| `python scripts/edge04_verify.py --state-root … --json-out …/DAILY_CAPTURE_VERIFICATION.json` | `0` (15/15) |
| `python -m pytest tests/unit/research/test_exp004a_wp051_02h.py` | `0` (27 passed) |
| `python -m pytest …test_exp004a_wp051_02h.py …test_exp004a_wp051_02g.py` | `0` (76 passed) |
| `powershell Get-ScheduledTask … Get-ScheduledTaskInfo` for `TradingAgentic-EDGE04-*` | `0` |
| `python scripts/exp004a_wp051_02h_audit.py --seal` | written after commit — see `EVIDENCE_MANIFEST.json` |

## 11. What happens next

1. **Before the next hour passes:** the owner decides on the volume in `DEF-02H-01`. Every hour at
   99 % capacity is another chance to lose a day that cannot be recovered. `%TEMP%` alone held
   **8.3 GB** of reclaimable scratch at audit time; `data/raw` holds 189 MB and `data/forward`
   82 MB, and none of it is this package's to delete.
2. **Daily, without a human step:** `TradingAgentic-EDGE04-Forward` keeps ticking; tomorrow's shard
   is written by the same publication step that wrote today's, and `edge04_verify.py` judges it.
3. **At the end of the window:** the coverage verdict is phrased against the 0.9 floor and against
   `CEILING_BELOW_DECLARED`. `COVERAGE_COMPLETE` is off the table for phase 3 unless §4 option 2 is
   taken, and that is a declaration decision, not an engineering one.
