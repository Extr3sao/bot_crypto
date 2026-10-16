# WP-EDGE-12A — dependency and runtime gate

**Generated:** 2026-10-16T06:20:03Z · **Verdict:** `DEPENDENCY_GATE_PASS`

A work package that answers "are the dependencies met?" from the repository's own
documents is answering from intent. Every row below is an answer from the host or the
interpreter this lane runs under, and every question that could not be answered is
recorded as unanswered rather than as zero.

## 1. Identity

|  |  |
| --- | --- |
| branch | `agent/edge-recovery/WP-EDGE-00-baseline` |
| HEAD | `151c9e0c7c5584772d6d5244ff21c54587cb9fea` |
| HEAD subject | Record the published ref read back from the remote, not from the push. [WP-EDGE-04R] |
| committed at | 2026-10-15T22:52:57+02:00 |
| upstream | `origin/agent/edge-recovery/WP-EDGE-00-baseline` |
| divergence | 0 ahead / 0 behind |
| remote ref | `refs/heads/agent/edge-recovery/WP-EDGE-00-baseline` = `151c9e0c7c5584772d6d5244ff21c54587cb9fea` |
| HEAD is the remote ref | True |
| modified paths (other workstreams) | 28 |
| untracked paths (other workstreams) | 131 |

> the modified and untracked paths are other workstreams' live artefacts; this package neither stages nor discards them and measures only its own files

## 2. The dependency the request names

`RFC-EDGE-011` — searched over 6 scope(s), 8722 file(s): **NOT_PRESENT_IN_TREE**.

> the request names RFC-EDGE-011 as a dependency; nothing in this tree carries that identifier, so what this package can certify is what it can measure: the runtime it is pointed at. Treating an absent dependency as satisfied is exactly the failure mode RFC-EDGE-012 exists to prevent.

What this package certifies instead, by digest:

| file | lines | sha256 |
| --- | --- | --- |
| `scripts/edge04_observer.py` | 494 | `fbfa8a1a504aadf5…` |
| `src/trading_bot/research/edge03/autonomous.py` | 2187 | `6f512539e6635e1f…` |
| `src/trading_bot/research/edge03/forward_plan.py` | 307 | `e9472a8a8a88db8d…` |

## 3. Reachability, measured in a fresh interpreter

Interpreter: `C:\Users\GVLLFR0035\Downloads\bot freebuff\.venv\Scripts\python.exe` (Python 3.11.15). 6/6 entry point(s) answered `--help` with status 0.

| entry point | reachable | first line |
| --- | --- | --- |
| `scripts/edge04_observer.py` | True | usage: edge04_observer.py [-h] [--state-root STATE_ROOT] |
| `scripts/edge04_observer.py --scheduled --due` | True | usage: edge04_observer.py [-h] [--state-root STATE_ROOT] |
| `scripts/edge04r_continuity.py` | True | usage: edge04r_continuity.py [-h] [--state-root STATE_ROOT] |
| `scripts/edge04r_session.py` | True | usage: edge04r_session.py [-h] [--reports REPORTS] [--no-probe] [--jso |
| `scripts/edge04r_verify.py` | True | usage: edge04r_verify.py [-h] [--reports REPORTS] [--repo REPO] [--sel |
| `scripts/cap004_supervisor.py` | True | usage: cap004_supervisor.py [-h] [--interval-seconds INTERVAL_SECONDS] |

9/9 runtime module(s) imported successfully in a separate process:

| module | importable | reason |
| --- | --- | --- |
| `trading_bot.research.edge03.autonomous` | True |  |
| `trading_bot.research.edge03.forward_plan` | True |  |
| `trading_bot.research.edge03.ingest` | True |  |
| `trading_bot.research.edge03.run` | True |  |
| `trading_bot.research.edge04r.continuity` | True |  |
| `trading_bot.research.edge04r.os_evidence` | True |  |
| `trading_bot.research.edge05.reconcile` | True |  |
| `trading_bot.research.disk_space` | True |  |
| `trading_bot.research.campaign_lock` | True |  |

## 4. Observer runtime

|  |  |
| --- | --- |
| state root | `C:\Users\GVLLFR0035\Downloads\bot freebuff\data\forward\edge04` |
| store root | `C:\Users\GVLLFR0035\Downloads\bot freebuff\data\forward\edge03` |
| ticks recorded | 254 |
| corrupt log lines | 0 run / 0 slot |
| outcomes | {'ALREADY_OBSERVED': 7, 'ALREADY_RUNNING': 2, 'DISK_BUDGET_EXCEEDED': 45, 'NO_NEW_DATA': 3, 'OBSERVED': 197} |
| first tick | 2026-10-13T11:23:38Z |
| last tick | 2026-10-16T06:12:22Z (OBSERVED) |
| sealed slots | 199 |
| current slot | 2026-10-16T06:15Z |
| daily evidence files | 4 |
| health | {'status': 'DEGRADED', 'reasons': ['the measured growth rate is volatile'], 'ticks_in_window': 99} |
| prospectively observed days | 1 |
| required days | 60 |
| epoch | 2026-03-01T00:00:00Z |

## 5. Scheduler registration, read from the host

> the scheduler's answer is the registration; install.json is what the lane asked for

|  |  |
| --- | --- |
| task name | `TradingAgentic-EDGE04-Forward` |
| present on the host | True |
| state | Ready |
| logon type | `Interactive` |
| run level | Limited |
| trigger kinds | MSFT_TaskTimeTrigger |
| start boundary | 2026-10-13T13:25:53 |
| interval | PT15M |
| start when available | True |
| wake to run | False |
| multiple instances | IgnoreNew |
| execution time limit | PT1H |
| restart policy | count=3 |
| last run | 10/16/2026 08:10:54 |
| last result | 0 |
| next run | 10/16/2026 08:25:53 |
| missed runs (the host's own counter) | 0 |
| Task Scheduler operational log enabled | False |

The host reports `NumberOfMissedRuns: 0` and `LastTaskResult: 0`. Neither is
wrong on the host's terms and neither is a statement about continuity: the counter does not
count a trigger whose task could not start, and the log that would is disabled.

## 6. Storage and the guard

|  |  |
| --- | --- |
| guard status | HEALTHY |
| free | 7.5353 GiB |
| used | 96.83% |
| critical floor | 2.0 GiB |
| warning floor | 5.0 GiB |
| relocation verdict | `NO_VOLUME_WITH_CAPACITY` |

| volume | fs | capacity GiB | free GiB | used % | can hold the store |
| --- | --- | --- | --- | --- | --- |
| C:  | NTFS | 237.5264 | 7.5355 | 96.83 | False |
| (none)  | NTFS | 0.832 | 0.0532 | 93.6 | False |
| (none)  | FAT32 | 0.0938 | 0.0065 | 93.1 | False |
| G: Google Drive | FAT32 | 237.5264 | 7.1587 | 96.99 | False |

## 7. Open failures, carried rather than closed

| id | status | what | owner |
| --- | --- | --- | --- |
| OPEN-EDGE12-1 | `UNREADABLE` | the economic certificate or its input could not be read |  |
| OPEN-EDGE12-2 | `BLOCKED_NEEDS_ELEVATION` | S4U task registration, a Windows service and the Task Scheduler operational log | an operator with administrator rights on this host |
| OPEN-EDGE12-3 | `BLOCKED_NEEDS_CREDENTIALS` | automatic logon, which is the only non-elevated way to re-create a session after a reboot | an operator who chooses to store a credential on the machine |
| OPEN-EDGE12-4 | `INHERITED_AND_UNREPAIRED` | tests/unit/research/test_cost_barrier_adversarial.py::test_the_certification_record_digests_content_not_a_checkout | the cost-barrier chain; not this work package |

## 8. Checks

| check | verdict | detail |
| --- | --- | --- |
| `the_tree_is_at_a_named_commit` | PASS | agent/edge-recovery/WP-EDGE-00-baseline @ 151c9e0c7c5584772d6d5244ff21c54587cb9fea |
| `the_entry_points_answer_the_interpreter_this_lane_runs_under` | PASS | 6/6 entry point(s) answered --help with status 0 |
| `every_module_the_lane_imports_is_importable` | PASS | 9/9 module(s) imported in a fresh interpreter |
| `the_observer_has_a_runtime_record` | PASS | 254 tick(s), last 2026-10-16T06:12:22Z (OBSERVED) |
| `the_registration_is_read_from_the_host_and_not_from_the_lane` | PASS | host reports state=Ready logon_type=Interactive missed_runs=0 |
| `the_storage_guard_is_reachable` | PASS | guard status HEALTHY, 7.5353 GiB free, NO_VOLUME_WITH_CAPACITY |
| `the_named_dependency_is_accounted_for` | PASS | RFC-EDGE-011: NOT_PRESENT_IN_TREE over 8722 file(s) in 6 scope(s) — recorded as an external dependency, not assumed satisfied |
| `no_open_failure_is_reported_as_zero` | PASS | 4 open failure(s) carried with an owner |
| `no_artefact_claims_an_order_or_a_promotion` | PASS | order_sent=False, promotion=NONE |

**`DEPENDENCY_GATE_PASS`**

Research only: hypothetical marks, no orders, no capital, no promotion.
