# WP-051-02I — EDGE-04 storage stability

**Phase:** EXP-004A, phase 3 · **Work package:** WP-051-02I · **RFC:** `CODEX — EDGE04 STORAGE STABILITY` ·
**Date:** 2026-10-23 · **Base commit:** `611cd717` · **Branch:** `wp/exp004a-051-02h`

> The risk was not hypothetical and it was not in the future. Over the eleven days this volume
> has on record it went under the 2 GiB floor **25 times**, reached **0.00 GiB** at least five
> times, and the lane's own guard **refused 162 ticks** — 40.55 hours of slots whose bars were
> never fetched. On `2026-10-23`, the first day of the pre-registered window, it sat at
> **0.00 GiB from 03:40Z to 04:55Z** and refused 22 consecutive ticks between `00:10Z` and
> `05:25Z`. That day is the 72 rows the campaign has already lost.
>
> This package measured all of it, fixed what it could within its authority, and **declares the
> 90-day capacity insufficient**: the window needs **16.68 GiB** of stable free space and the
> host has **4.42 GiB**. The campaign's own footprint for the whole window is **104 MB** — it
> cannot solve this by being frugal, and a report that suggests otherwise would be a false
> success.

---

## 1. The headline

| Question | Answer | Basis |
| --- | --- | --- |
| Is the risk real? | **Yes, and ongoing** | 25 stretches under 2 GiB, 162 refused ticks, lowest 0.00 GiB |
| What does 90 days need? | **16.68 GiB** of stable free space | own 104.5 MB + floor 2 GiB + worst observed drawdown 14.58 GiB |
| What is available? | **4.42 GiB**, and it has been as low as 0.00 | measured at 10:54:43Z |
| Can the campaign free it itself? | **No** | its whole footprint is 20.37 MiB; the sweep reclaimed 13.57 MiB |
| Is the window still the pre-registered one? | **Yes** | 2026-10-24 is day 2 of 2026-10-23 → 2027-01-21; nothing was restarted |
| Can the window still be certified *complete*? | **No** | ceiling 0.988889 after losing 23/10; the 0.9 floor still holds |
| Verdict | **`BLOCKED`** on capacity | per the RFC: no sufficiency, declared, quantified |

## 2. §1 — Capacity audit, on the host itself

Volume: **237.53 GiB**, **98.14 % used**, **4.42 GiB free** at `10:54:43Z`
([FILESYSTEM_SURVEY.json](FILESYSTEM_SURVEY.json), [STORAGE_CAPACITY_REPORT.json](STORAGE_CAPACITY_REPORT.json)).

The consumers that matter, each one named with its owner, because who may delete a byte is the
whole question:

| Tree | Size | Owner | Class |
| --- | --- | --- | --- |
| `data/forward/edge04` (lane state) | **13.67 MiB** | this campaign | protected evidence |
| `data/forward/edge03` (source store) | 6.40 MiB | this campaign | protected evidence |
| `data/exp004a` (phase-3 shards) | 0.30 MiB | this campaign | write-once evidence |
| `.git` | 150.6 MiB | the repository | protected history |
| `%TEMP%` | **6.23–7.0 GiB** (moves by the hour) | every process on the host | shared, volatile |
| `Downloads` (incl. all worktrees) | **18.53 GiB** | the user and other packages | foreign |
| `AppData\Local` | **55.76 GiB** | the OS, browsers, tooling | foreign |
| `Windows` / `Program Files` | 33.93 / 20.39 GiB | the OS | foreign |
| `C:\ESD` | 4.58 GiB | Windows upgrade staging | foreign, admin to remove |

Inside `AppData\Local` the largest named trees are `Microsoft` 13.19 GiB, `Programs` 7.03 GiB,
`Temp` 6.23 GiB, `wsl` 6.16 GiB, `ms-playwright` 3.27 GiB, `hermes` 2.77 GiB. **None of them is
this campaign's, and none of them is removable by this package.**

**Growth, from the lane's own instrument.** The observer records free space before and after
every tick; 929 such readings exist, from `2026-10-13T11:23:38Z` to `2026-10-23T10:40:56Z`:

- median net change **−1.66 GiB/day** over 11 days (7 days spending, 4 recovering);
- largest fall from a peak inside one day: **14.58 GiB** on `2026-10-19` (22.91 → 8.32 GiB);
- lowest reading: **0.00 GiB**, repeatedly.

**Two series, never one number.** The campaign's own growth is **1.16 MB/day**, measured over
9.94 days of its own `resource_budget.json` samples — 104.5 MB for the whole window, at
**314.5 bytes/row** over 15 measured phase-3 shards × 72 rows/day × 90 days. The volume's
decline is two orders of magnitude larger and belongs to something else. Adding them into a
single figure would blame a 20 MiB dataset for a 14 GiB problem.

## 3. §2 — Resolving the saturation: what was possible, what was not

Ordered as the RFC asks:

1. **Safe cleanup of this package's own artefacts — done.** 321 byte-compiled files in
   **13.57 MiB** in the first applied run; 4 directories / **216 353 B** in the recorded run; an
   identical third run removed 0 B, which is the proof that the sweep is idempotent
   ([SWEEP_EVIDENCE.json](SWEEP_EVIDENCE.json)). Every candidate was inside this worktree, on a
   whitelist (`__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `.hypothesis`), and
   **untracked by Git** — a `__pycache__` that Git tracks is refused by name, and a test proves
   it.
2. **Rotation/compression of regenerable artefacts — not applicable at scale.** The lane's logs
   are 4.2 MiB after ten days; compressing them would buy kilobytes and cost the audit trail.
   The watchdog's own event log is now **bounded at 256 KiB** and rotated, which is the one place
   where unbounded growth was a real (if small) risk.
3. **Moving data to another volume — impossible on this host.** `Get-Volume` reports exactly one
   writable volume: `C:`. The only other partition is an 0.83 GiB helper with 50 MiB free and no
   drive letter. Moving the lane elsewhere would also change which volume its guard measures,
   which is a contract change nobody authorised.
4. **Expansion — required, and outside this package's authority.** See §8.

**Why 13.57 MiB is the honest ceiling of self-help:** the campaign holds 20.37 MiB in total. Even
deleting all of it would move free space by 0.5 %. The saturation is not caused by the
experiment and cannot be cured by it.

## 4. §3 — Capacity protection: what already existed, what was added

**Already there, and left in place:** `trading_bot.research.disk_space` and the observer's own
guard — `HEALTHY ≥ 5 GiB`, `WARNING < 5 GiB` (ingest continues, heavy publication waits),
`CRITICAL < 2 GiB` (the tick records `DISK_BUDGET_EXCEEDED` **before** any market request).
The **2 GiB floor was not moved**: no evidence justified a different value, and the RFC says so.

**Added to `scripts/edge04_watchdog.py` (V1 → V2), which the scheduler already runs every 15
minutes from this worktree:**

| Addition | Why it exists |
| --- | --- |
| **velocity + forecast** | "4 GiB free" is comfortable or urgent depending on the fall rate. Measured as the worst daily drawdown in the observer's own readings; `UNKNOWN` below 3 complete days, never invented |
| **`RECOVERED`** | a fifth state so that an alarm can *end*: previous `BLOCKED`/`STALE`/`UNREADABLE` and now healthy → `RECOVERED`, exit `0`, marker lowered |
| **bounded event log** | one line per transition in `WATCHDOG_EVENTS.jsonl`, rotated at 256 KiB: the alarm cannot fill the volume it reports on |
| **best-effort persistence** | every write is wrapped; a full volume yields an `ERROR` field and a non-zero exit code instead of a traceback, so the alarm survives exactly when it is needed |
| **escalation record** | each channel is attempted and its answer recorded verbatim, including refusals |

The forecast is already doing its job in production: the scheduled run at `10:47:02Z` wrote
`EDGE04_WATCHDOG_V2`, `status DEGRADED`, `forecast AT_RISK, 2.79 h` to the critical floor, and
the task's `LastTaskResult` carried `1`. At `11:02Z` the same task ran the same code with free
space back above 5 GiB and produced `OK` / `0`, with the transition written to
`WATCHDOG_EVENTS.jsonl` — the state machine has now been observed in both directions on the
real lane, not only in a test ([LIVE_ALARM_EVIDENCE.json](LIVE_ALARM_EVIDENCE.json)).

## 5. §4 — Alerts, states and recovery

**The five states are distinguishable, and each one answers a different question:**

| State | Exit | Meaning | What would fix it |
| --- | --- | --- | --- |
| `OK` | 0 | tick fresh, volume above the warning floor | nothing |
| `DEGRADED` | 1 | alive and writing; volume under 5 GiB, heavy publication waiting | free space |
| `BLOCKED` | 8 | store not growing: volume under 2 GiB, or the last tick was refused for space | free space |
| `STALE` | 9 | store not growing: no tick finished in three intervals | the scheduler |
| `RECOVERED` | 0 | the previous run was blocking and this one is not | nothing: it ends the page |
| `UNREADABLE` | 2 | no readable tick at all | a first run / a repair |

**Recovery never rewrites history.** `A_REFUSAL_IS_NOT_A_CAPTURE` (verifier, recomputed from the
log) proves every refused tick carries `new_bars = 0` and `exit_code = 5`; the lag policy in the
frozen contract forbids fetching a missed slot later, so a bar cannot be reclassified as
prospective after the fact — it is simply absent, and the daily shard names the missing open.

**Channels, as measured — and the honest gap:**

| Channel | Works | Evidence |
| --- | --- | --- |
| Task Scheduler `LastTaskResult` | **yes** | `1` at `10:47:01Z`; stored by the scheduler, not on the volume |
| `ATTENTION_REQUIRED.txt` | yes | raised for blocking states, removed by the next healthy run |
| Windows event log | **no** | `eventcreate` → `Acceso denegado` without elevation |
| Webhook | **no** | `EDGE04_ALERT_WEBHOOK` unset; no credential created |
| A human being told | **no** | nothing on this host polls the result or the marker |

That last row is `DEF-02I-02` and it is the most important defect in this report: the alarm has
been firing for eleven days and the only reason anyone knows is that a person read a file.

## 6. §5 — Validation: pressure without damaging the host

The pressure tests never fill C:. `shutil.disk_usage` is replaced with a reading the test
controls and the state machine is driven across every threshold — **1.9 / 2.0 / 4.9 / 5.0 GiB**
and back up — through the same code path a real full volume takes
([test_exp004a_wp051_02i.py](../../../../tests/unit/research/test_exp004a_wp051_02i.py), **21
tests, all passing**):

- the forecast needs three complete days, and says `UNKNOWN` with the reason when it has fewer;
- the forecast uses the **worst** day, not the average (2 / 4 / 8 GiB → 8);
- `BLOCKED` under the floor, `DEGRADED` between the floors, `RECOVERED` after a blocking state,
  with the marker raised and lowered accordingly;
- the event log rotates instead of growing;
- a volume that refuses writes produces `verdict_state: ERROR` and `marker: ERROR`, not a
  traceback;
- escalation records a **refused** channel as refused, and uses a webhook only when one is
  configured;
- the sweep refuses a Git-tracked cache by name and deletes only the untracked one (real `git`
  repository in the test);
- the verifier itself is tested to **fail**: a report that hides a refusal, and a refusal that
  claims bars, both produce `FAIL`.

**Independent verification: 16/16 `PASS`, 0 `FAIL`, 0 `UNVERIFIABLE`**
([INDEPENDENT_VERIFICATION.json](INDEPENDENT_VERIFICATION.json)) by a program that imports
neither the builder nor the watchdog and recomputes refusals, episodes, consumer sizes, shard
format, projection arithmetic, sweep scope and the watchdog's own reading from the bytes.
It also proves the watchdog leaves `runs.jsonl` and `health.json` byte-identical.

## 7. §6 — Governance: the window is intact, the ceiling is not

The frozen contract (`config/preregistrations/EXP-004A.datasets.phase3.json`) fixes
`2026-10-23T00:00:00Z → 2027-01-21T00:00:00Z`, 90 days, 6480 rows, `required_fraction 0.9`.

- **`2026-10-24T00:00:00Z` is inside the pre-registered window** — it is day 2. Nothing was
  restarted, shifted or extended to hide the 23/10 failure; the deviation is registered here
  instead.
- `COVERAGE_COMPLETE` requires exactly 6480 admissible rows and zero defects. With 72 rows lost
  on `2026-10-23` it is **unreachable**, at a ceiling of **0.988889**.
- The declared floor (0.9 = 5832 rows) still holds, and **8 more whole days** could be lost
  before it stops holding.
- **No new campaign identity is proposed**, because the original window still satisfies the
  criterion that adjudicates it. A new acquisition campaign would only be justified if the
  floor became unreachable — that is now a measurable, 8-day budget rather than a judgement.

## 8. §7 — Defects, limitations, and what this package cannot do

| Id | Defect | Status |
| --- | --- | --- |
| `DEF-02I-01` | **Capacity insufficient for the window**: 16.68 GiB required, 4.42 GiB available; the floor was crossed 25 times in 11 days | **OPEN — BLOCKED**, quantified in §1 |
| `DEF-02I-02` | **No alarm reaches a person.** Task result, marker and verdict file all fire; nothing polls them. Windows event log denied to an unprivileged writer; no webhook configured | **OPEN** — mitigated, not solved: the alarm is now also a *forecast*, which is only useful if read |
| `DEF-02I-03` | **The campaign cannot defend itself**: 20.37 MiB of footprint against a 14.58 GiB daily drawdown. Any remediation is host-level and outside this package's authority | **OPEN** by design |
| `DEF-02I-04` | The first applied sweep (321 files / 13.57 MiB) is recorded only in this session's console: the accumulating `history` field was written after that run | **RECORDED**, fix verified by the two runs that followed |
| `DEF-02I-05` | The **source** of the 14.58 GiB drawdown is **not attributed**. The largest trees are named; which process spends the bytes inside a day is not provable from this package | **OPEN**, hypothesis labelled in the projection |
| `DEF-02I-06` | Forecast needs ≥ 3 complete days of history; below that it reports `UNKNOWN` rather than a number | **BY DESIGN** |
| `DEF-02I-07` | Restart-without-logon (`LogonType=Interactive`) not tested: needs administrator rights this session does not have | **UNVERIFIED** |
| `DEF-02I-08` | `tests/unit/research` as a directory does not run: `test_exp004a_wp051_02g.py` imports `trading_bot.research.prospective.incremental`, absent in this worktree, and the directory exceeds a 600 s cap | **PRE-EXISTING**, not hidden |

**Required capacity, stated as the RFC asks** (capacity plan, *proposed and not applied* — every
item needs a decision this package cannot make):

1. **≥ 16.68 GiB of stable free space on C:** before the window can be called safe. Since the
   drawdown is daily, that means a *sustained* floor, not a one-off cleanup.
2. Reclaim candidates, in order of cost: `C:\ESD` **4.58 GiB** (Windows upgrade staging, admin);
   `Downloads` worktrees **18.53 GiB** (committed work, user's call); `%TEMP%` **6–7 GiB**
   (shared, regenerable, other processes); `ms-playwright` 3.27 GiB, `wsl` 6.16 GiB,
   `hermes` 2.77 GiB (tooling, user's call).
3. Or **a second volume** for the lane's state, which is a contract change (the guard measures
   the volume of the state root) and would need to be pre-registered, not slipped in.

## 9. Verdicts

| Verdict | Value | Basis |
| --- | --- | --- |
| `RISK_MEASURED` | **true** | 929 readings, 25 floor breaches, 162 refused ticks (40.55 h), lowest 0.00 GiB |
| `RISK_MITIGATED` | **false** | `DEF-02I-01` is open: 4.42 GiB available against 16.68 GiB required |
| Saturation resolved | **false — declared BLOCKED** | no volume to move to; own footprint 20.37 MiB |
| `CAPACITY_SUFFICIENT_FOR_WINDOW` | **false** | `INSUFFICIENT` in the projection, verifier-confirmed |
| Evidence destroyed | **0 bytes** | 13.57 MiB of untracked byte-compiled caches; nothing tracked, nothing under `data/`, `docs/` or `config/` |
| Late capture reclassified | **0** | `A_REFUSAL_IS_NOT_A_CAPTURE` recomputed; store byte-identical after the watchdog |
| `FALSE_SUCCESS` | **0** | verifier 16/16; the storage report carries no coverage or certification field |
| Regressions | **0** in the six suites: **163 passed, 1 skipped** (environment) |
| Capture alive after the change | **true** | `10:30` and `10:45` slots `OBSERVED`, 3 bars each, at `10:40:56Z` and `10:55:56Z` |
| Watchdog V2 live | **true** | scheduled run `10:47:02Z`: `EDGE04_WATCHDOG_V2`, `DEGRADED`, `AT_RISK 2.79 h` |

## 10. Verifiable artefacts

[STORAGE_CAPACITY_REPORT.json](STORAGE_CAPACITY_REPORT.json) ·
[GROWTH_DIAGNOSIS.md](GROWTH_DIAGNOSIS.md) ·
[FILESYSTEM_SURVEY.json](FILESYSTEM_SURVEY.json) ·
[SWEEP_EVIDENCE.json](SWEEP_EVIDENCE.json) ·
[LIVE_ALARM_EVIDENCE.json](LIVE_ALARM_EVIDENCE.json) ·
[INDEPENDENT_VERIFICATION.json](INDEPENDENT_VERIFICATION.json) ·
[RUN_REPORT.md](RUN_REPORT.md) · [RUN_REPORT.json](RUN_REPORT.json) ·
[EVIDENCE_MANIFEST.json](EVIDENCE_MANIFEST.json)

## 11. What happens next

The lane keeps capturing — it is alive right now, on a volume that has 4.4 GiB and spends
gigabytes a day. The watchdog will say `BLOCKED` the moment the floor is crossed again, with a
forecast hours before it happens, and nobody will be told unless a person looks.

The one action that changes the outcome is not in this repository: **16.68 GiB of sustained free
space on C:**. Until that exists, the campaign's remaining budget is **8 lost days**, and the
volume has already shown it can take a whole day in five hours.
