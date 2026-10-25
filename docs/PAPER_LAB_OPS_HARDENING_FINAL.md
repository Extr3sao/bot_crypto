# PAPER LAB OPS HARDENING — final report

Phase: `PAPER-LAB-OPS-HARDENING-V1`. Mode: PAPER only, read-only public market
data, no live path, no keys, no capital.

Two things were found by running the lab for real rather than by reading it, and
both were ways for the lab to fail *quietly* — which is worse than failing.

## The two findings

### P1 — PAPER died, and the supervisor died with it, because a volume filled

At ~21:46 the research volume this host shares with everything else hit 100 %:

```
reports/paper-lab/paper-lab-continuous-01/logs/paper.log
  File ".../autonomous/paper_loop.py", line 449, in write_daily_report
    json_path.write_text(
OSError: [Errno 28] No space left on device

reports/paper-lab/paper-lab-continuous-01.log
  File ".../start_paper_lab.py", line 355, in main
    final = supervisor.supervise_forever(
OSError: [Errno 28] No space left on device
```

PAPER was writing its own daily report and the supervisor was writing its own
heartbeat. Both raised. The captured run (`paper-lab-continuous-01`, 3307.9 s,
1,077,110 events) kept going for a while with its supervisor dead and its PAPER
child dead, and the only way to find out was to read a log file.

Fixed by making evidence writes survivable, because PAPER is a decision process
and its reports are evidence, not its purpose:

* `durable_write()` in [paper_loop.py](../src/trading_bot/autonomous/paper_loop.py)
  records an `OSError` in `ArtifactWriteFailures` and returns `None`; the loop
  continues, and the heartbeat gains `storage_failures` / `storage_errors`
  so the condition is visible without reading a log;
* the supervisor's heartbeat write is the same: it counts
  `heartbeat_write_failures` and reports it instead of dying;
* `supervise_forever` no longer lets a poll or an event callback raise out of the
  loop, and the launcher writes its run report and snapshot even when the
  supervisor itself fails (`supervisor_error` in `LAB_RUN_REPORT.json`).

The three places it applied: heartbeat writes (per cycle and on cycle failure),
the daily report (mid-run and at shutdown), and the run report/descriptor.

### P2 — a capture that could not write still exited 0

The capture recorded a dead writer in `integrity.failures` and then exited `0`, so
the supervisor saw a completed run where the data was not written. See
[COLLECTOR_EXIT_CONTRACT_EVIDENCE.json](../reports/paper-lab-ops-hardening/COLLECTOR_EXIT_CONTRACT_EVIDENCE.json)
for the live probes at this HEAD: a capture whose root cannot be created, and a
capture whose manifest directory cannot be created after running to its full
duration, now print a structured `FAILED` payload and exit **2**.

## The exit contract

Implemented once in [outcome.py](../src/trading_bot/research/forward/outcome.py),
carried by the manifest and by the process exit code, and read back through the
same classifier for manifests written before it existed
(`storage.manifest_outcome`).

| status | exit | when |
| --- | --- | --- |
| `COMPLETE` | 0 | the configured duration was reached |
| `CONTROLLED_STOP` | 0 | a stop file, a signal, the dataset-size guard, or the host-free-space guard ended it |
| `FAILED` | 2 | `STORAGE_WRITE_FAILURE`, `MANIFEST_FAILURE`, `TIMESTAMP_INVARIANT`, `BOOK_UNRECOVERABLE`, `COLLECTOR_CORRUPTION` |

`COMPLETE` and `CONTROLLED_STOP` are both exit 0 — everything written is complete
and accounted for — and stay *separate values*, because "it ran its two hours" and
"somebody stopped it" are different findings. An unrecognised stop reason is
reported as a controlled stop of unknown origin, never promoted to `COMPLETE`.

The supervisor reads the code, not the manifest: non-zero is a crash, which means
restart, backoff, and eventually `FAILED` instead of a silent success
(`check_supervisor_failure_propagation`, and the unit tests it mirrors). A stop is
also a finding: a child that exits non-zero while being stopped, or that has to be
killed because it did not finalise, is reported in `stop_report`
(`verdict: FAILED`), not laundered into a clean shutdown.

## Storage: the volume is a shared resource, and now everyone says so

* **Levels** (`NORMAL`, `WARNING`, `CRITICAL`, `STOP`) with thresholds set on the
  command line (`--disk-warning-gb`, `--disk-critical-gb`, `--disk-stop-gb`),
  recorded in the lab plan, and published in the heartbeat together with the
  *observed* rate and the hours it leaves — because "3 % free" means nothing
  without knowing how fast it is filling.
* **Storage guard (§22):** at `STOP`, the supervisor asks the capture to stop
  gracefully (it writes its manifest and exits 0) and **deliberately does not
  touch PAPER**, whose authoritative market data has nothing to do with the
  research volume. It also does not restart the capture into a full volume.
* **`--min-free-bytes`:** a host-free-space floor inside the collector itself, the
  last barrier, ending the run as a controlled stop with
  `stopped_on_min_free: true`.
* **`--data-root`:** capture, retention, lineage, preservation records, resume
  state and the stop file all follow one root, so the whole lab can be pointed at
  another volume.
* **Preservation before deletion** (§12/§13): M-03 and M-07 are re-derived from
  the raw rows and from the compact artifact and compared, at the resolution the
  preregistration records. A mismatch — or nothing to compare — refuses the
  deletion by name. See [PAPER_LAB_STORAGE_POLICY.md](PAPER_LAB_STORAGE_POLICY.md).

## The operator surface

```bash
python scripts/start_paper_lab.py                 # start (one command, four children)
python scripts/start_paper_lab.py --status        # what is happening right now
python scripts/start_paper_lab.py --stop reports/paper-lab/<id>
python scripts/start_paper_lab.py --restart --run-id <id>
python scripts/paper_lab_status.py                # the same status, standalone
python scripts/paper_lab_dashboard.py             # http://127.0.0.1:8787
```

The dashboard is read-only with no mutating endpoint, binds to loopback only, and
refuses any other host at startup. `STOP` is the only stop, `--restart` is
`stop → wait for the children to settle → start with the same run id and
`--resume``, and every path writes the same three artifacts:
`LAB_RUN_REPORT.{json,md}` and `LAB_RUN_SNAPSHOT.json`. See
[PAPER_DASHBOARD.md](PAPER_DASHBOARD.md).

## Verification

* `ruff check .` clean, `mypy .` clean, `pytest` green (see the summary block for
  the counts at the final HEAD).
* The independent verifier
  ([paper_lab_verification.py](../scripts/paper_lab_verification.py)) runs from a
  clean worktree with the worktree's own `src` first, and now also checks: the
  exit contract against a live process, supervisor failure propagation with PAPER
  surviving, the M-03/M-07 preservation gate on a fixture it writes itself, disk
  levels and their rate, the read-only loopback operator surface (including a real
  `POST` being refused with `405`), and the storage tiers plus the movable data
  root.

## What is still true without qualification

* `PAPER_CANDIDATES = 0`. The admission ledger admits 0 of 24 strategies (7
  `COST_KILLED`, 17 `NO_GROSS_EDGE`), so PAPER producing many `NO_TRADE` decisions
  and 0 trades is the correct behaviour, not a symptom.
* Long-horizon **raw** retention on this host is `EXTERNAL_STORAGE_REQUIRED` by
  arithmetic; long-horizon aggregates fit. `--data-root` is the supported answer.
* The volume is shared and was at 100 % twice during this phase. Retention + the
  guards kept the lab alive both times; nothing certified was deleted.
