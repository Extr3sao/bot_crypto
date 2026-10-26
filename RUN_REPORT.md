# RUN REPORT — PAPER LAB OPS HARDENING V1 / RECOVERY + RE-CERTIFICATION

| | |
|---|---|
| **run_id** | `recovery-paper-lab-ops-2026-09-29` |
| **baseline HEAD** | `222078baedd07401b8b590d87bc06ae3307e862e` |
| **final HEAD** | `1376fa4456e59826608a13de4fad4b2a8faacf2b` |
| **branch** | `main` |
| **commits** | `f406a45`, `81dec23`, `06100e7`, `77e9d65`, `1376fa4` |
| **mode** | PAPER + read-only public market data. No keys, no account, no orders, no capital. |
| **FALSE_SUCCESS** | **0** |

## 1. What the recovery gate established

The interrupted session **had landed all of its work before it died**: the tree was clean at
`222078b` with five new commits after the previously certified head, and no work had to be
rewritten. What had to be established was whether each item *runs*, which is what the rest of this
report records. Full classification:
[INTERRUPTED_SESSION_RECOVERY.json](reports/recovery/INTERRUPTED_SESSION_RECOVERY.json).

| Item | Status |
|---|---|
| writer-surface fix (P2) | IMPLEMENTED_AND_VERIFIED |
| exit contract module | IMPLEMENTED_AND_VERIFIED |
| collector changes | IMPLEMENTED_AND_VERIFIED |
| supervisor disk levels / failure propagation | IMPLEMENTED_AND_VERIFIED |
| supervisor stop report | IMPLEMENTED_AND_VERIFIED |
| disk telemetry wiring | IMPLEMENTED_AND_VERIFIED |
| poll labelling | IMPLEMENTED_AND_VERIFIED |
| exit-contract tests | IMPLEMENTED_AND_VERIFIED |
| data preservation (M-03 / M-07) | IMPLEMENTED_AND_VERIFIED |
| durable-write helper | IMPLEMENTED_AND_VERIFIED |
| PAPER entrypoint hardening | IMPLEMENTED_AND_VERIFIED |
| launcher restart / status / data-root / disk thresholds | IMPLEMENTED_AND_VERIFIED |
| independent verifier extension | IMPLEMENTED_UNVERIFIED → **now verified, and it had five defects** |
| read-only localhost dashboard | IMPLEMENTED_UNVERIFIED → **now verified over real HTTP** |

## 2. Quality gates

| Gate | Result |
|---|---|
| `ruff check .` | All checks passed |
| `mypy .` | Success: no issues found in 350 source files |
| `pytest` (at `222078b`) | 1194 passed, 78 warnings in 328.74 s |
| `pytest` (at `f406a45`) | 1201 passed, **1 failed** — the frozen-writer certificate guard |
| `pytest` (final tree, at `1376fa4`) | **1202 passed**, 78 warnings in 220.08 s |
| independent verifier (clean worktree, `1376fa4`) | **18/18 PASS, verdict=PASS** |

The single failure at `f406a45` is the guard that exists to notice exactly that: the honesty fixes
touched `src/trading_bot/research/forward/collector.py`, so the capture certificate no longer
matched. The resolution was a **new capture**, not a relaxed check.

## 3. Real runtime validation

### 3.1 The exit contract, proven by a real capture

A real capture whose writer cannot write (its `segments` path poisoned with a regular file, no
doubles anywhere) returned `EXIT_CODE=2` and wrote a manifest that says so:

```json
{"status": "FAILED", "failure_kind": "STORAGE_WRITE_FAILURE", "stop_reason": "storage failure",
 "exit_code": 2, "integrity": {"write_failures": 1},
 "failure_reason": "STORAGE_WRITE_FAILURE: FileExistsError [WinError 183] ... 'segments'"}
```

### 3.2 Failure injection end to end — the §4 chain

`paper-lab-failinject-01` ran the **real launcher** against a poisoned data root:

```
collector EXIT(exit_code=2, outcome=FAILED)
  → RESTART_SCHEDULED(delay 5.0)  → RESTARTED
  → EXIT(2)                       → RESTART_SCHEDULED(15.0) → RESTARTED
  → EXIT(2)                       → RESTART_SCHEDULED(60.0) → ...
collector  state=FAILED  exit=2  restarts=4
           reason="crash loop: 4 restarts inside 900s (budget 3)"
paper      state=RUNNING restarts=0 for the whole run; final STOPPED exit=0
stop_report verdict=FAILED  failed_children=[collector]
            exit_codes {paper: 0, collector: 2, retention: 0, strategy_lab: 0}
```

A failed write produced a FAILED manifest, a non-zero exit, a supervisor that treated it as a
crash with the declared backoff and restart budget, and a PAPER plane that kept deciding.

### 3.3 A clean stop writes its manifest

The defect that started this line of work was a lab stop that killed the collector before it could
finalise, leaving **no manifest** and partial tails. `paper-lab-ops-hardened-01` (23.0 min,
`stop_reason "STOP file"`):

```
status CONTROLLED_STOP  exit 0  stop_reason "stop file"
segments 115 / sealed 115 / partial_tails 0 / rows 656278 / write_failures 0
stop_report verdict CLEAN, every child exit 0
```

## 4. Re-certification

| | |
|---|---|
| run_id | `paper-lab-cert-01` |
| commit | `f406a459b89f41e7771e5edb0a33f6725f708831` |
| collector duration | 719.05 s (**≥ 10 min**) |
| lab duration | 768.5 s, `stop_reason "duration reached"` |
| children | 4, zero restarts, zero supervisor events, stop report `CLEAN` |
| manifest | `CONTROLLED_STOP`, exit 0, **89/89 segments sealed, 0 partial tails**, 546,043 rows, 0 write failures |
| replay | `ok: true`, **89/89 fingerprints**, 0 partial tails, `internet_access: false`, `event_count_match`, `book_match` (4 books, 24/24 checkpoints each), `deterministic: true`, 0 repaired trade rows, `errors: []` |
| digest | `2f4e90d4f3d31e1187b8f1695e6cdabe26e65803f3ef31659f0c68818564d24a` (identical on both passes) |

`CERTIFIED_CAPTURE_COMMIT` moved from `7b14297` to `f406a45` in its own commit, and the published
read-side reports now describe that run. M-03 and M-07 remain
`COLLECTING / TECHNICALLY_READY_NEEDS_HISTORY`, whose **only** remaining blocker is
*"sample is 12.0 min; 24 h of clean capture is the minimum to begin"* — not a data defect, and the
certified capture recorded **zero sequence gaps** and four books ending `HEALTHY`.

## 5. Defects found and their disposition

| ID | Severity | Status | Summary |
|---|---|---|---|
| F1 | P1-adjacent | **FIXED** | a `FAILED` capture published `continuity=CONTINUOUS_DATA`, which `reporting` turns into `permits_continuity_claim` |
| F2 | P3 | **FIXED** | the status screen rendered `~None h at the observed rate` and `state_age=Nones` |
| F3 | P3 | documented | `remaining_missing_events` mixes depth **update-id** units into an "events" total |
| F4 | P2 | pre-existing | the perp `aggTrade` stream never delivers; reported honestly as `NO_DATA` |
| F5 | P3 | environment | two concurrent pytest processes delete each other's numbered temp dir |
| F6 | P2 | **FIXED** | `COLLECTOR_READY: yes` next to a collector in a crash loop |
| F7 | P2 | **FIXED** | `paper_lab_status.py --json` died with `UnicodeEncodeError` on a cp1252 console |
| F8 | P1 governance | resolved | the frozen-writer guard fired, as designed; resolved by re-certification |
| F9 | P3 performance | documented | the read-side report makes 4–5 full passes; >12 min of CPU for a 12 min capture |
| F10 | P3 | **FIXED** | five verifier checks could never pass |

**F1** mattered because a dead capture could licence a continuity claim downstream. **F6** was the
single most valuable find: the dashboard showed a red `FAILED — STALE HEARTBEAT` banner *and* a
green `COLLECTOR_READY: yes` badge at the same time.

**F10** is worth naming plainly: the verifier's own checks had never run successfully.
`DISK_LEVELS_AND_RATE` demanded `WARNING` at 3 GB free against a 2 GB warning threshold;
`STORAGE_TIERS_AND_DATA_ROOT` called `forward_retention.parse_args([...])` on a driver whose
`parse_args()` takes no arguments; `STORAGE_CAPACITY_POLICY` and `FINAL_HEAD_EXECUTED` assumed the
capture roots live inside the verifier's own worktree; and crashed lambdas were reported as
`<lambda>`, hiding which check had failed. A verifier that reports `FAIL` for reasons of its own is
as dangerous as one that reports `PASS` for reasons of its own.

## 6. Operator surface, verified over real HTTP

```
GET /                 → 200 (read-only, auto-refresh 15s, "No LIVE control is presented…")
POST/PUT/DELETE /     → 405 {"error":"this dashboard is read-only","allowed":["GET"]}
--host 0.0.0.0        → exit 1, "refusing to bind ... loopback-only"
--host 127.0.0.1      → listening on 127.0.0.1:8787 only
```

The rendered page reported `FAILED — STALE HEARTBEAT` rather than `HEALTHY`, which is the honesty
requirement that matters most on a monitoring surface.

## 7. Final gate results

* `ruff`: clean. `mypy`: 350 files, no issues.
* `pytest` on the final tree: **1202 passed**, 78 warnings in 220.08 s — zero failures, zero errors.
* Independent verifier: **18/18 PASS**.

## 8. Evidence

| Artifact | What it shows |
|---|---|
| [reports/recovery/INTERRUPTED_SESSION_RECOVERY.json](reports/recovery/INTERRUPTED_SESSION_RECOVERY.json) | per-item classification bound to files, commits, tests and runtime |
| [reports/microstructure-forward-cert01/manifest/paper-lab-cert-01.json](reports/microstructure-forward-cert01/manifest/paper-lab-cert-01.json) | the certified capture: 89/89 sealed, 0 partial tails, commit `f406a45` |
| [reports/cert01_replay.log](reports/cert01_replay.log) | offline replay: `ok: true`, 89/89 fingerprints, deterministic |
| [reports/paper-lab/paper-lab-cert-01/LAB_RUN_REPORT.json](reports/paper-lab/paper-lab-cert-01/LAB_RUN_REPORT.json) | integrated run: `CLEAN` stop report, 4 children exit 0 |
| [reports/paper-lab/paper-lab-failinject-01/LAB_RUN_REPORT.json](reports/paper-lab/paper-lab-failinject-01/LAB_RUN_REPORT.json) | the §4 chain: crash loop, PAPER alive, stop verdict `FAILED` |
| [reports/failure-injection/writer-dead/manifest/failinject-writer.json](reports/failure-injection/writer-dead/manifest/failinject-writer.json) | `FAILED` + `exit_code: 2` from a real CLI run |
| [docs/PAPER_LAB_INDEPENDENT_VERIFICATION.json](docs/PAPER_LAB_INDEPENDENT_VERIFICATION.json) | 18/18 PASS from a clean worktree |
| [docs/FORWARD_DATA_QUALITY_REPORT.json](docs/FORWARD_DATA_QUALITY_REPORT.json) | readiness: M-03/M-07 COLLECTING, blocked only on sample length |
