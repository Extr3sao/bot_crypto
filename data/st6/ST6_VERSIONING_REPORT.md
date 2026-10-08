# ST-6 — versioning and independent end-of-period replay

Generated 2026-10-08T21:49Z at `9660afab9003001d3a8130b9679c066071548421` (branch `main`,
verified with `git rev-parse HEAD`). No new campaign, no change to the declared period, no change to
COST_MODEL_V3, no order, no credential, no touch of CAP-004B/CAP-004D.

## 01 — Baseline

`HEAD` is the communicated `9660afa` — `feat(research): open the ST-6 forward cost regime period (14
declared days)`. `origin/main` is `5e6f9632e8d9c15dabd60ea92ac68f350ca28c9d` and the local branch is
205 commits ahead of it, so this work is a local commit only: nothing is pushed.

| what | state at the baseline |
| --- | --- |
| scheduler task | `TradingAgentic-ST6-Forward`, installed and enabled, repetition `PT15M`, action `python.exe … st6_forward_regime.py --due --scheduled` in the repository directory |
| entrypoint of `--due` | `scripts/st6_forward_regime.py --due --scheduled` (unattended) / `--due` (manual) |
| code pending a commit | the autonomous tick layer, the health checker, the scheduler verifier and the scheduler tests were complete on disk and uncommitted |
| period | `2026-10-08T16:21:20Z` → `2026-10-22T16:21:20Z`; 14 days, 6 slots/day, plan 84 windows |
| windows collected | 2 — `20261008T162202Z` (`2026-10-08#4`) and `20261008T200323Z` (`2026-10-08#5`), both complete, 0 orders, 0 credentials |
| static artefacts | `ST6_SCHEDULER_REPORT.{json,md}`, `ST6_SCHEDULER_VERIFICATION.json`, `ST6_TASK_DEFINITION.xml` present and uncommitted |
| dynamic artefacts | `ST6_RUNS.jsonl`, `ST6_HEALTH.jsonl`, `ST6_HEALTH_STATUS.json` rewritten by every tick; `ST6_WINDOWS.jsonl`, `ST6_OBSERVATIONS.jsonl`, `ST6_REGIME_COVERAGE.json`, `ST6_MODEL_DRIFT.json`, `ST6_FORWARD_REGIME_REPORT.*` rewritten on each collection |
| raw evidence | 2 gzipped snapshots, both re-hashed and reproducing the hash recorded in the window index |
| ECO-1 | OPEN — the declared coverage rule is far from met (2 of 84 planned windows) |
| other threads' paths | listed below, deliberately not staged |

Paths under modification by other threads of the repository, **not staged, not touched**:

```text
FINAL_REPORT.md
RUN_REPORT.json
RUN_REPORT.md
docs/source_registry.md
evidence/real_decisions/evaluations.jsonl
evidence/real_decisions/outcomes.jsonl
scripts/cap004c_verify.py
PAPER_DATA_24H_REPORT.json
PAPER_DATA_24H_REPORT.md
data/rfc035e/…
scripts/rfc035*
scripts/source_candidate_experiment.py
src/trading_bot/research/experimental/…
docs/research/experiment_specs/…
docs/research/runtime_reconciliation/…
docs/research/work_packages/…
tests/unit/research/test_experimental_candidates_pit.py
tests/unit/research/test_rfc035*.py
```

## 02 — What was versioned, and how it was separated

Three kinds of artefact were separated **before** anything was staged:

| class | members | treatment |
| --- | --- | --- |
| `IMMUTABLE_EVIDENCE` | `data/st6/raw/*.json.gz` | re-hashed, committed; never rewritten |
| `VERSIONED_IMPLEMENTATION` | the six programs, the scheduler test suite, `ST6_TASK_DEFINITION.xml` | committed |
| `LIVE_RUNTIME_STATE` | `ST6_RUNS.jsonl`, `ST6_HEALTH.jsonl`, `ST6_HEALTH_STATUS.json`, `ST6_WINDOWS.jsonl`, `ST6_OBSERVATIONS.jsonl`, `ST6_MISSED_WINDOWS.jsonl`, `ST6_PERIOD_CLOSURE.json`, `ST6_REGIME_COVERAGE.json`, `ST6_MODEL_DRIFT.json`, `ST6_FORWARD_REGIME_REPORT.{json,md}`, `ST6_SCHEDULER_REPORT.{json,md}`, `ST6_SCHEDULER_VERIFICATION.json`, `ST6_INDEPENDENT_VERIFICATION.{json,md}`, `ST6_PERIOD.json` | **snapshotted and hashed, not committed** |
| `TRANSIENT_COORDINATION` | `data/st6/scheduler_lock/CAMPAIGN_LOCK.json` | hashed for completeness, never copied, never committed |

The window index is therefore **not** committed: it is campaign state that the next collection
rewrites, and the current one is not the last one this period will have. Its exact bytes at the
snapshot instant are inside the snapshot, with their sha256.

Two dated snapshots were produced by `scripts/st6_state_snapshot.py`:

* `data/st6/snapshots/ST6_LIVE_STATE_20261008T215219Z.json` — the one the independent verification
  read;
* `data/st6/snapshots/ST6_LIVE_STATE_20261008T215222Z.json` — the final picture, taken after the
  verification, and the one `--check` re-verifies.

Each snapshot copies every live file under `data/st6/snapshots/<id>/` and records, for each one, its
sha256, size, mtime and **git blob hash**, plus a re-hash of every raw window snapshot against the
hash in the index. `python scripts/st6_state_snapshot.py --check` → **PASS (19 checks)**.

## 03 — The commit

`git add` was called with explicit paths only — never `git add -A`, never `git add .`, never a
directory that could carry another agent's file. The identity of the content staged (git blob SHA-1,
`git hash-object` of the exact bytes) is:

| path | git blob sha1 | bytes |
| --- | --- | --- |
| `scripts/st6_forward_regime.py` | `3c3c7092c942ef3613be17f6ead89652431f8ae3` | 121866 |
| `scripts/st6_health_check.py` | `36ce06959843401ccb42da291d2086218484e4c2` | 18246 |
| `scripts/st6_scheduler_verify.py` | `8eceb9b2ead559fad37f4c29178bb5332f119484` | 29401 |
| `scripts/st6_state_snapshot.py` | `821987eaa8f7db8143c05d2191776f7ce26a1bb6` | 11797 |
| `scripts/st6_close_replay.py` | `29b2a3cbb4c7ead03356976535fb94c1059d5149` | 61284 |
| `scripts/st6_close_verify.py` | `26b52211bbeee9bbcb68d17fefbb70ca6f15c970` | 46742 |
| `tests/unit/research/test_st6_scheduler.py` | `c54a23284067074c30e6165b6778cb646435e972` | 26255 |
| `data/st6/ST6_TASK_DEFINITION.xml` | `6c13e0e75568feaca1329a226116eed2b18d58ac` | 3308 |
| `data/st6/raw/20261008T200323Z.json.gz` | `2d42847d6090feaab898a726bdc5d04fd50cc362` | 17904 |
| `data/st6/ST6_PERIOD_BOUNDARY_AUDIT.md` | `d8c4f72cf89dffc615a0d73aee6f1d215c651bcc` | 8693 |
| `data/st6/ST6_CLOSE_REPLAY_REPORT.md` | `aaf662e39e3e1bf9e9f05b624ef07be573c446de` | 4130 |
| `data/st6/ST6_CLOSE_REPLAY_REPORT.json` | `ca63240911a283dbd18769e753714e6ff2c3a809` | 59645 |
| `data/st6/ST6_CLOSE_INDEPENDENT_VERIFICATION.json` | `71bc6e237810a0a965299a9ff15f749f41bc3aea` | 11161 |

Plus the two snapshot manifests and their 30 copied live files (15 per snapshot,
`data/st6/snapshots/**`, `git add` by explicit path), for **47 paths** in total. Every one of them
is listed with its blob hash and sha256 in `ST6_VERSIONING_REPORT.json`.

The commit id cannot appear inside the commit that carries this report; it is reported in the
mission's final response (`CURRENT_HEAD`).

## 04 — Scheduler lifecycle at and after the close

* **Before the close** the task wakes every fifteen minutes. The tick takes the shared lease,
  consults the local slot state *first*, and makes **no market request** when the slot already has a
  window. Verified live: 1515/1515 checks, all live tests PASS.
* **At the instant of the close** (`now >= ends_at_utc`, inclusive) the ended branch returns
  `EXIT_PERIOD_ENDED` *before* any statement that could collect a window. That dominance is
  re-derived from the tick's own syntax tree by `closure_guard_structure`, and it is replayed here.
  The consolidation is written **once**: metrics consolidated, missed windows named, verifiers
  delegated, terminal state declared.
* **The terminal transition** is new in this commit: the period disables **its own** task
  (`schtasks /change /tn <own task> /disable`), without elevation, without touching any other
  program's task, and records the outcome inside the consolidation. A failure is recorded rather
  than raised, with a note telling the operator to disable the task by hand; the tick still refuses
  to sample.
* **After the close** every later tick is an **idempotent no-op**: no sample, no artefact rewrite,
  no run event. The replay proves it — the consolidation stays byte-identical across repeated
  executions and across a simulated host restart, and a fresh process reproduces it exactly. So the
  task can neither keep making requests nor keep creating logs even if it is never disabled; its own
  `Duration` (`P30D`) also expires it.

## 05 — Verification evidence

| verification | result |
| --- | --- |
| scheduler verifier — live execution through the scheduler, lease, `--due` idempotency, refusal path, closure guard, run log, missed accounting, order-path scan | **PASS 1515/1515**, FALSE_SUCCESS 0 |
| isolated close replay — 10 scenarios, injected UTC clock, isolated sandbox, market and scheduler forbidden | **PASS 10/10**, 0 FAIL, real state unmoved, 0 real requests, 0 real scheduler calls |
| independent close verification — a different program from the builder *and* from the harness | **PASS 19/19**, FALSE_SUCCESS 0 |
| negative fixtures — duplication, tampered hash, missing evidence, order path, foreign closure, supported-over-incomplete-coverage, hidden drift, plan past its end, moved implementation hash, misclassified artefact, hidden failed check, unexplained real change | **PASS 17/17** corruptions detected |
| determinism — the harness re-run from the same seed state | close sha256 `8610cf46337fb400…` reproduced exactly, byte for byte; every scenario verdict equal. Inside the sandbox the tick records the code identity as a constant (`REPLAY_SANDBOX_NOT_A_COMMIT`), so this proof does not depend on the commit hash — the real head is recorded at the top level of the report |
| unit suites | 43 passed (`test_st6_scheduler.py`, `test_st6_forward_regime.py`) |
| live-state snapshot | `--check` PASS (19 checks); every raw hash reproduces |

The replayed close produced `INSUFFICIENT_REGIME_COVERAGE` (2 of 84 planned windows, 82 missed) with
the terminal state `PERIOD_CLOSED_NO_FURTHER_COLLECTION`, the drift preserved beside the outcome
(1 breach, none lost against the live monitor), 0 orders and 0 credentials.

## 06 — Declared deviations and open defects

1. **`BOUNDARY-SLOT-DUE-RULE`** — the due rule is not bounded by the 84-window plan: a tick inside
   the partial slot the period closes in (2026-10-22, 16:00–16:21:20Z) would attempt an 85th,
   out-of-plan window. Measured in the replay; minimal correction proposed; **not applied**, because
   changing the collection rule mid-period would alter the campaign.
2. **`EXTENSION-FLAG-INERT`** — the declared `--authorize-extension` policy is inert in both
   directions: it cannot extend the period, and during the open period it suppresses collection.
   Measured, declared, not patched.
3. **`CORRUPT-RAW-BYTES-RAISE`** — a tampered **hash** is classified `DATA_QUALITY_FAILED` (proved),
   but raw bytes that are not gzip at all raise before the classification is written (proved: the
   replay records `BadGzipFile`). Loud, not silent — no blessed consolidation is written — but the
   declared token is not emitted. Declared, not patched.
4. **`DUPLICATE-INDEX-ROW`** — the tick consolidates what the index says; duplicate detection belongs
   to the verifier, which is proven to fail on a duplicated row.

Also recorded: during the test run that hardened the flakiness of the cadence test, one single-shot
tick returned status 0 with empty output and no run event (a live tick was sharing the lease at that
moment). Five immediate repeats and the manual path behaved exactly as declared, and the event never
reproduced; it is recorded here as an unexplained observation, not explained away and not claimed as
a defect of the close.

None of these alters the declared period, the collected evidence, the denominator or COST_MODEL_V3.

## 07 — Governance

```text
ST6_AUTONOMOUS_COLLECTION_ACTIVE = True
ECO_1 = OPEN
ECO_2 = UNKNOWN_NOT_RESOLVABLE_OFFLINE
NEXT_CAMPAIGN = NOT_AUTHORIZED
LIVE_TRADING = DISABLED
TRADES_AUTHORIZED = 0
PROFITABILITY_VERIFIED = False
orders_sent = 0
credentials_used = 0
period_modified = False
cost_model_v3_touched = False
cap004b_cap004d_touched = False
```

The real campaign is **not** declared finished. It closes on its own date,
`2026-10-22T16:21:20Z`, when the consolidation and the independent verification run automatically —
this work proves that the close behaves, it does not bring the close forward.

Research only: no orders, no credentials, no capital.
