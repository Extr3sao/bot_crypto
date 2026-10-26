# PAPER-CONTINUOUS-STRATEGY-LAB-V1 — FINAL REPORT

Four planes ran, in parallel, as separate operating-system processes under one
portable supervisor: the PAPER runtime, the forward microstructure collector, the
retention worker and the strategy research lab. Nothing here can reach LIVE: the
only broker in the loop is the PAPER broker, the only market data is read-only
public data, and no child holds an execution credential.

Verified HEAD: `6a9e4ba5f8544847c49a53dcef8a344f78357252`.

## What this phase found and fixed

### 1. A stop that killed instead of asking (found, fixed, regression-tested)

The supervisor stopped children with `terminate()`. On Windows that is
`TerminateProcess`: the child never runs its cleanup. Every lab stop therefore
ended with **no collector manifest, 36 of 108 raw segments left with partial
tails, a hard-killed paper loop (`exit 1`)** — and a report that called it
`"duration reached"` when a STOP file had stopped it.

* Fixed by making the stop a *file each child polls* (`STOP` for PAPER,
  `state/<run-id>.stop` for the collector, `STOP.retention` /
  `STOP.strategy_lab` for the maintenance workers), with
  `--stop-grace-seconds` before any escalation to `terminate()`/`kill()`.
* A stale stop file cannot stop a fresh start: each child's file is cleared
  before it is spawned.
* The capture now publishes **why** it ended (`stop_reason` in the manifest and
  in its resume state) instead of leaving it to be inferred from what is missing.
* Evidence: legs 1 and 2 of `paper-lab-stoprestart-02` — all four children
  `STOPPED exit 0`, manifests with **0 partial tails** (31 and 18 segments, all
  sealed), `stop_reason: "stop file"`.
* Regression tests: 4 in `tests/unit/autonomous/test_supervisor.py` (ask before
  kill, escalate a deaf child, clear a stale stop file, apply the grace in
  `supervise_forever`) and 4 in `tests/unit/forward/test_forward_collector_replay.py`.

### 2. A restart that re-owned its root (found, fixed, regression-tested)

Leg 2 of that same pair reused the run id without `--resume`. A segment's path is
a pure function of the window it covers, so the writer refused its own earlier
file and the capture died of its own past: **198 unrecoverable gaps across every
stream, while all four children exited 0 and the lab reported a clean restart**.

* Fixed in the launcher: `--resume` is passed exactly when the run id already
  owns a state file, and the decision is recorded as `collector_resume` in
  `LAB_PLAN.json`.
* Regression test: `test_a_restart_tells_the_collector_it_owns_the_root`.

### 3. Open (P2): a capture that cannot write still exits 0

The same run recorded the storage failure honestly in its manifest
(`INCOMPLETE_DATA`, 198 `UNRECOVERABLE` gaps, per-stream status) but the process
returned 0, so the supervisor could not see it. The trigger is removed by fix 2;
the fix belongs in the write-failure taxonomy, which is frozen by the
certification capture, and is deferred with this note rather than hidden.

## The runs behind the claims

| run | commit | duration | stop | segments | partial tails | children |
| --- | --- | --- | --- | --- | --- | --- |
| `headcert-3d3be37` (writer certification) | `3d3be37` | 1000.9 s | `duration reached` | 211 | **0** | n/a (bare collector) |
| `paper-lab-integrated-04` (integrated lab) | `6a9e4ba` | 1303.0 s | `STOP file` | 143 | **0** | 4 × `STOPPED exit 0`, 0 restarts |
| `paper-lab-stoprestart-02` legs 1+2 | `3d3be37` | 181.5 s + 115.9 s | `STOP file` | 31 + 18 | **0** | 4 × `STOPPED exit 0` |
| `paper-lab-integrated-03` (longest, pre-fix) | earlier | 4839.99 s | STOP file | 108 | 36 (the defect) | 4 × `STOPPED exit 1` |

Retention inside a live lab is proven on `paper-lab-integrated-03`: six
compaction passes, 220 raw segments deleted, 365.7 MB reclaimed, 8 lineage
records — every one of them re-hashed by the independent verifier
(`RETENTION_LINEAGE_AND_ORDER` PASS on that root, 8 aggregates verified). On
`integrated-04` the check passes vacuously (0 aggregates verified: nothing was
due, deletion disabled), which is stated rather than dressed up.

## Independent verification

`scripts/paper_lab_verification.py` (a second implementation, not the builder's)
on `integrated-04` + `lab-06` + `headcert`: **12/12 PASS**, including
`PHASE_TESTS` (131 passed). On the pre-fix `integrated-03` the same verifier
returns 10/11 with `SAFE_STOP_AND_RESTART` **FAIL** — it detects the very defect
this phase fixed, which is why it is trusted on the run that passes.

```text
TRADING AGENTIC PORTABLE — PAPER CONTINUOUS STRATEGY LAB FINAL SUMMARY

PHASE:                        PAPER-CONTINUOUS-STRATEGY-LAB-V1
MODE:                         PAPER ONLY (read-only market data; no live, no capital, no keys)
VERIFIED HEAD:                6a9e4ba5f8544847c49a53dcef8a344f78357252
WORKING TREE:                 clean

PLANES RUNNING (in parallel, one supervisor, separate processes):
  PAPER RUNTIME               autonomous_paper.py --continuous  (critical)
  FORWARD COLLECTOR           forward_collector.py --mode run   (critical)
  RETENTION                   forward_retention.py --loop       (maintenance)
  STRATEGY LAB                paper_lab_research.py --loop      (maintenance)

INTEGRATED RUN:               paper-lab-integrated-04
DURATION:                     1303.0 s (21.7 min) - operator STOP file
STOP REASON (recorded):       STOP file  (not assumed: read back from the evidence)
FINAL SUPERVISOR STATE:       DEGRADED (all children STOPPED after the stop, by design)
CHILDREN:                     paper/collector/retention/strategy_lab -> STOPPED exit 0
RESTARTS:                     0   SUPERVISOR EVENTS: 0   CRASH LOOPS: 0
HEARTBEAT:                    SYSTEM_HEARTBEAT.json + SYSTEM_DAILY_REPORT.{json,md}

PAPER DECISIONS:              59 decisions, 59 unique decision_id, 0 duplicates
PAPER TRADES:                 0        SHADOW TRADES: 0
NO_TRADE KIND:                NO_TRADE_STRATEGIC (every cycle)
RISK VETOES:                  0        RUNTIME FAILURES: 0
STRATEGIES EVALUATED/CYCLE:   6
ADMISSION LEDGER:             24 strategies, 0 admitted_for_paper
LIFECYCLE HISTOGRAM:          REJECTED=0 RESEARCH_REQUIRED=0 PAPER_CANDIDATE=0
                              PAPER_ACTIVE=0 PAPER_RETIRED=0 (all_checks_ok=true)
NO_TRADE IS THE RESULT:       0 trades is the correct output of 0 admitted strategies

COLLECTOR (integrated run):   441,091 rows / 143 segments / 0 partial tails / 143 sealed
                              stored 29.9 MB, uncompressed 540.5 MB, gaps 12 (data lost 0.0 s)
                              memory 161.16 MB max, CPU 194.48 s (0.15 of one core)
COLLECTOR (writer cert):      headcert-3d3be37, 1000.9 s, rotation 60 s, BTC spot+perp
                              575,447 rows / 211 segments / 0 partial tails / 211 sealed
                              stored 37.2 MB, uncompressed 695.7 MB (18.70x)
                              memory 165.02 MB max == final, CPU 192.09 s (0.192)
                              duplicates 9, sequence gaps 5, malformed 0, clock violations 0
                              data-lost gaps 8 totalling 0.003 s, stop_reason duration reached
OFFLINE REPLAY (network-free): ok=true, internet_access=false, 211/211 fingerprints match,
                              partial_tails=0, event_count_match, trade_sequence_ok
                              (0 repaired rows, 0 unresolved holes), book_match, feature_match,
                              deterministic, aggregation digest b537e393... == recorded
EVENT LATENCY (live only):    p50 250.0 ms, p95 30,869 ms, p99 40,066 ms, max 42,409 ms
                              (436,381 samples; recovered rows counted as loss, not latency)
P1 BOUNDED TELEMETRY:         PASS - 1M observations, growth < 4096 B, old field absent

RETENTION:                    compact always, delete only under pressure (deletion here: off)
IN-RUN COMPACTION PROOF:      integrated-03: 6 passes, 220 raw segments deleted, 365.7 MB freed,
                              8 lineage records, every aggregate re-hashed by the verifier
LINEAGE VERIFICATION:         PASS (8/8 aggregates re-derived), lineage/aggregation/compaction
                              persisted; nothing was deleted without a matching digest

STORAGE MEASURED:             3.212 GB/day compressed at the certified rate (BTC spot+perp)
FREE DISK:                    0.34 GB of 238 GB (100% used)
STORAGE VERDICT:              EXTERNAL_STORAGE_REQUIRED - estimated_operating_days 0.0
LONG-HORIZON RAW:             needs external storage; a 2 h raw hot window is the viable ceiling
                              (1 h/2 h/4 h probes VIABLE, >= 6 h EXTERNAL_STORAGE_REQUIRED)

M-03 READINESS:               COLLECTING / TECHNICALLY_READY_NEEDS_HISTORY (16.7 min vs 24 h)
M-07 READINESS:               COLLECTING / TECHNICALLY_READY_NEEDS_HISTORY (0.011 d vs 6 d)
M-PREREG-V1:                  intact, not_yet_run=true - no hypothesis was promoted on one run

DEFECTS FOUND:                3
DEFECTS FIXED:                2
  1 supervisor killed instead of asking -> stop file first, grace, then kill;
    manifest + 0 partial tails + children exit 0 (regression-tested)
  2 restart re-owned its root -> --resume when the run id owns a state file;
    198 unrecoverable gaps removed from the restart path (regression-tested)
DEFECTS OPEN:                 1
P0 OPEN:                      0
P2 OPEN:                      1 - a capture that cannot write still exits 0 (failure is in the
                              manifest, not in the exit code); trigger removed, fix deferred out
                              of the frozen writer surface

TESTS:                        1146 passed (0 failed)
RUFF:                         All checks passed!
MYPY:                         Success: no issues found in 342 source files
PHASE TESTS (verifier-run):   131 passed

INDEPENDENT VERIFIER:         12/12 PASS at HEAD (integrated-04 + lab-06 + headcert)
                              IMPORT_ISOLATION, P1_NETWORK_DELAYS_BOUNDED,
                              RETENTION_LINEAGE_AND_ORDER, STORAGE_CAPACITY_POLICY,
                              STRATEGY_ADMISSION_GATE, DEF_AUTO_2_3_4, NO_LIVE_PATH,
                              FAILURE_ISOLATION, SAFE_STOP_AND_RESTART, FINAL_HEAD_EXECUTED,
                              M03_M07_PREREGISTERED, PHASE_TESTS
                              pre-fix integrated-03: 10/11 - SAFE_STOP_AND_RESTART FAIL
                              (the verifier reproduces the defect it now certifies away)

SAFE STOP:                    children asked, then stopped; state flushed; manifest written
SAFE RESTART:                 same run id resumes the capture; 0 duplicated economic decisions
FAILURE ISOLATION:            a collector crash cannot stop PAPER; a crash loop is declared

FALSE_SUCCESS:                0
FINAL STATUS:                 PAPER_CONTINUOUS_VERIFIED
COLLECTOR STATUS:             COLLECTOR_STORAGE_BLOCKED
HOST_READY_FOR_LONG_TERM_24_7: FALSE
READY_FOR_CONTINUOUS_COLLECTION: FALSE
  reasons: storage_capacity = EXTERNAL_STORAGE_REQUIRED (0.34 GB free, 3.212 GB/day)
           paper_path = VERIFIED (12/12 checks, 0 trades, 0 duplicates, 0 failures)
           long_horizon_raw = EXTERNAL_STORAGE_REQUIRED

NEXT RECOMMENDED PHASE:       PAPER-CONTINUOUS-STRATEGY-LAB-V2
  + attach external storage so the raw hot window (and therefore the run length) is not
    dictated by a 0.34 GB volume, then let M-03/M-07 collect the history their gates require
  + fix the P2 exit-code finding inside the writer surface (a capture that cannot write
    must not report success)
```
