# WP-051-02I — run report

**Phase:** EXP-004A, phase 3 · **Work package:** WP-051-02I (EDGE-04 storage stability) ·
**Date:** 2026-10-23 · **Base commit:** `611cd717` · **Branch:** `wp/exp004a-051-02h`

> Every command below was executed on this host. Exit codes are the ones the shell returned,
> and the three that are not `0` are the point of the report rather than a defect in it.

---

## 1. Commands actually executed

| # | Command | Exit | What it produced |
| - | ------- | ---- | ---------------- |
| 1 | `python scripts/exp004a_wp051_02i_storage.py --audit` | `0` | [STORAGE_CAPACITY_REPORT.json](STORAGE_CAPACITY_REPORT.json), [GROWTH_DIAGNOSIS.md](GROWTH_DIAGNOSIS.md) |
| 2 | `python scripts/exp004a_wp051_02i_storage.py --survey` | `0` | [FILESYSTEM_SURVEY.json](FILESYSTEM_SURVEY.json) |
| 3 | `python scripts/exp004a_wp051_02i_storage.py --sweep` | `0` | dry run: 13.57 MiB eligible, nothing deleted |
| 4 | `python scripts/exp004a_wp051_02i_storage.py --sweep --apply` | `0` | first applied run: 321 files, 13.57 MiB removed |
| 5 | `python scripts/exp004a_wp051_02i_storage.py --sweep --apply` | `0` | recorded run: 4 directories, 216 353 bytes ([SWEEP_EVIDENCE.json](SWEEP_EVIDENCE.json)) |
| 6 | `python scripts/exp004a_wp051_02i_verify.py` | `0` | **16/16 PASS** ([INDEPENDENT_VERIFICATION.json](INDEPENDENT_VERIFICATION.json)) |
| 7 | `python scripts/edge04_watchdog.py --state-root <main>/data/forward/edge04` | `1` | `DEGRADED`, forecast `AT_RISK` — non-zero is the alarm, not a failure |
| 8 | `python scripts/edge04_watchdog.py ... --json --no-persist` | `1` | the verifier's control run; store byte-identical afterwards |
| 9 | `python -m pytest tests/unit/research/test_exp004a_wp051_02i.py -q` | `0` | 19 passed |
| 10 | `python -m pytest` (02h + 02i + capture + admission + prereg ×2) `-q` | `0` | **161 passed, 1 skipped** |
| 11 | `python -m pytest tests/unit/research -q` | `2` | **did not pass**: collection error in `test_exp004a_wp051_02g.py` (imports `trading_bot.research.prospective.incremental`, absent in this worktree) and a 600 s cap on the second attempt — see §7 |
| 12 | `eventcreate /t ERROR /id 901 /l APPLICATION /d "EDGE04 storage guard probe"` | `1` | `Acceso denegado`: the event log is not available to an unprivileged writer |
| 13 | `schtasks /query /tn TradingAgentic-EDGE04-{Forward,Watchdog} /v` | `0` | both tasks registered; watchdog `LastTaskResult=1` at `10:47:01Z` |

## 2. What was measured

- **Volume:** `237.53 GiB`, **98.14 % used**, **4.42 GiB free** at `10:54:43Z`.
- **History:** **929** free-space readings, taken by the observer itself, from
  `2026-10-13T11:23:38Z` to `2026-10-23T10:40:56Z`.
- **The floor was not held:** 25 stretches under 2 GiB, **162 ticks refused for space**
  (40.55 h of slots), lowest reading **0.00 GiB**.
- **Today:** the volume sat at **0.00 GiB** from `03:40Z` to `04:55Z`; the lane refused 25
  ticks, the longest episode `00:10:56Z → 05:25:57Z` (5.5 h).
- **Trend:** median **−1.66 GiB/day** over 11 days; 7 days spent space, 4 recovered it.
- **Worst drawdown:** **14.58 GiB** inside `2026-10-19` (22.91 → 8.32 GiB free).
- **The campaign's own footprint:** **20.37 MiB** (lane 13.67 + source store 6.40 + shards 0.30),
  growing **1.16 MB/day**; 90 days of it is **104.5 MB**, and its shard format is **314.5 bytes/row**
  over 15 measured shards.
- **Projection:** required stable free space **16.68 GiB**, available **4.42 GiB** →
  **`INSUFFICIENT`**, with the floor **≈4 h** away at the worst rate this volume has already shown.

## 3. What was done about it

1. **Reclaimed what this package owns.** 321 byte-compiled files in 13.57 MiB, in a first
   applied run; the recorded run then removed 4 directories / 216 353 bytes, and an
   identical third run removed nothing (idempotent). Every candidate was inside this
   worktree, on a whitelist, and untracked by Git — `sweep` refuses a `__pycache__` that Git
   tracks, and a test proves it.
2. **Hardened the alarm** (`scripts/edge04_watchdog.py`, V1 → V2): velocity and forecast from
   the observer's own readings, a `RECOVERED` state, a size-bounded transition log, best-effort
   writes so a full volume cannot turn the watchdog into a traceback, and an escalation record
   that states what each channel answered.
3. **Declared the capacity insufficient rather than papering over it** — see §5.

## 4. Live evidence after the change

- The scheduled watchdog ran the new code on its own: `WATCHDOG.json` at `10:47:02Z` carries
  `EDGE04_WATCHDOG_V2`, `status: DEGRADED`, `forecast: AT_RISK, 2.79 h`. The task's
  `LastTaskResult` is `1`.
- The observer kept capturing: `10:30`, `10:45` slots `OBSERVED` with 3 bars each, at `10:40:56Z`
  and `10:55:56Z`.
- `runs.jsonl` and `health.json` are byte-identical after a watchdog run: the watchdog reports,
  it does not touch the store.

## 5. What the numbers say about the window

The frozen contract fixes `2026-10-23T00:00:00Z → 2027-01-21T00:00:00Z` (90 days, 6480 rows,
floor 0.9 = 5832 rows). `2026-10-24` is **inside** it — day 2 of the pre-registered window — so
nothing was restarted, shifted or extended.

`2026-10-23` lost 72 rows. `COVERAGE_COMPLETE` (exactly 6480, zero defects) is therefore
**unreachable**, at a ceiling of **6480/6480 → 0.988889**. The declared floor still holds, and
**8 more whole days** could be lost before it stops holding (9 × 72 = 648 rows = the 10 %
allowance).

That is the budget the storage risk is spending from: **one day already lost, eight left**, and
the volume that took the first one is still at 98 % used.

## 6. Alarm channels, as measured

| Channel | Works | Evidence |
| ------- | ----- | -------- |
| Task Scheduler `LastTaskResult` | **yes** | `1` at `10:47:01Z`, stored by the scheduler, not on the volume |
| `ATTENTION_REQUIRED.txt` | yes | raised for `BLOCKED`/`STALE`/`UNREADABLE`, removed by the next healthy run |
| Windows event log | **no** | `eventcreate` → `Acceso denegado` without elevation |
| Webhook | **no** | `EDGE04_ALERT_WEBHOOK` is not set; no credential was created |
| A person reading any of it | **no** | nothing on this host polls the task result — see `DEF-02I-02` |

## 7. Not run, and why

- `tests/unit/research` as a directory: one file fails to import
  (`test_exp004a_wp051_02g.py`, `trading_bot.research.prospective.incremental` is not in this
  worktree — it lives in the 02G worktree) and the directory as a whole exceeded a 600 s cap.
  The six suites that cover this package were run individually and passed. The 02G collection
  error is **pre-existing** and unrelated to this change; it is not reported as a pass anywhere.
- A real volume exhaustion. Filling C: to test the guard is exactly the failure mode this
  package exists to prevent, so the pressure tests drive `shutil.disk_usage` instead — the same
  code path, at 1.9 / 2.0 / 4.9 / 5.0 GiB, with none of the damage.
- A restart-without-logon test of the scheduled tasks: `LogonType=Interactive` is unchanged, and
  testing it needs administrator rights this session does not have.
