# PAPER lab dashboard — read-only, loopback only

```bash
python scripts/paper_lab_dashboard.py          # http://127.0.0.1:8787
python scripts/paper_lab_status.py             # the same payload, in a terminal
python scripts/paper_lab_status.py --json      # the same payload, for a monitor
```

One page that answers "is it running, what has it done, and is the disk going to
run out". No build step, no framework, no database: the Python standard library,
one HTML page, and a JSON endpoint the page re-fetches every 15 s.

## Why it cannot start, stop or change anything

There is **no mutating endpoint**. The server implements `GET` only; every other
method is answered `405` with the body `this dashboard is read-only`. That is a
deliberate design decision, not an unfinished feature:

* a dashboard that can stop the lab is a second way for the lab to die, and
  §57 lists "dashboard crash stops PAPER" and "dashboard can modify Risk" as
  false-success conditions;
* the lab has exactly one operator path (the launcher), so there is one place to
  reason about when a stop happens and what it flushes;
* the controls an operator needs are *named on the page as commands to copy*, in
  the `CONTROLS` card: start, status, stop, restart.

## Why it binds to loopback only

`resolve_host()` refuses anything that is not `127.0.0.1`, `::1` or `localhost`,
so the page cannot be reached from the network by accident:

```
$ python scripts/paper_lab_dashboard.py --host 0.0.0.0
refusing to bind '0.0.0.0': the dashboard serves live process state and is
loopback-only (use 127.0.0.1 or ::1)
```

## Endpoints

| path | method | what it returns |
| --- | --- | --- |
| `/` | GET | the page |
| `/api/status` | GET | the whole status payload (`schema_version: paper-lab-status-v1`) |
| `/healthz` | GET | `{"ok": true, "state": ..., "read_only": true}` |
| anything else | GET | `404` |
| any path | POST/PUT/PATCH/DELETE | `405`, `this dashboard is read-only` |

## Panels

| panel | what it holds |
| --- | --- |
| SYSTEM | derived supervisor state, running, uptime, heartbeat age and whether it is **stale**, restarts, mode, `live_control`, run id |
| DISK | free GB, level (`NORMAL/WARNING/CRITICAL/STOP`), the thresholds in force, observed GB/day, estimated hours left, the action that level implies |
| PAPER | cycle, uptime, assets, timeframe, strategies evaluated, decisions, no-trade (and kinds), paper trades, shadow trades, risk vetoes, runtime failures, **storage failures survived**, paper candidates |
| COLLECTOR | root, events, gaps, reconnects, resnapshots, segments on disk, raw GB, state age, stop reason, fatal failure, manifest status |
| RETENTION | deletion enabled, compacted windows, deleted segments, bytes freed |
| STRATEGIES | total, status histogram, lifecycle, admitted for paper, paper candidates, not paper executable, checks ok |
| READINESS | M-03 / M-07 verdict and preregistration state, preregistration version, `not_yet_run` |
| ERRORS | every open finding, including a stale heartbeat |
| CHILD PROCESSES | state, pid, **liveness probed from the OS**, uptime, restarts, exit code, last log error, stop file |
| STOP REPORT / RUN REPORT / PLAN / CONTROLS | what the last stop did, the run summary, the plan in force, and the operator commands |

Readiness is read from the quality report, never inferred from "the collector is
running": a running collector is not evidence of coverage, quality or history.

## Honesty rules

* a heartbeat older than 180 s is rendered **stale**, never as healthy — the last
  thing a crashed lab does is stop updating;
* a `FAILED` child, a non-zero exit at stop time, and a storage guard that had to
  intervene are all listed under ERRORS;
* `live_control` is `false` because every plane under it is PAPER or read-only
  market data; there is no LIVE path, so there is nothing to control;
* the five readiness verdicts are reported **separately** — `PAPER_READY`,
  `COLLECTOR_READY`, `STORAGE_READY`, `STRATEGY_LAB_READY` (plus
  `RESEARCH_READY`) — because "PAPER is fine while research storage is blocked" is
  a supported state (§22) and one green light would hide the difference.

## Status command

```bash
python scripts/paper_lab_status.py                       # operator summary
python scripts/paper_lab_status.py --json                # the full payload
python scripts/paper_lab_status.py --snapshot            # write CURRENT_RUN_SNAPSHOT.json
python scripts/paper_lab_status.py --out <path>          # write the payload somewhere
python scripts/paper_lab_status.py --exit-code-if-not-running   # for a monitor
python scripts/paper_lab_status.py --run-id <id>          # a specific run instead of the newest
```

It reads the artifacts the lab already writes (`LAB_PLAN.json`,
`SYSTEM_HEARTBEAT.json`, `LAB_RUN_REPORT.json`, `paper_state.json`, the PAPER
heartbeat, the collector's resume state, `STRATEGY_LAB_REPORT.json`, the quality
report) and takes no lock, so it is safe to run against a live lab.
