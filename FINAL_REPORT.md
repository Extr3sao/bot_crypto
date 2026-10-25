# FINAL REPORT — PAPER LAB OPS HARDENING V1 (RECOVERED AND RE-CERTIFIED)

```text
PHASE:                          PAPER-LAB-OPS-HARDENING-V1 / RECOVERY + RE-CERTIFICATION
BASELINE_HEAD:                  222078baedd07401b8b590d87bc06ae3307e862e
FINAL_HEAD:                     1376fa4456e59826608a13de4fad4b2a8faacf2b
COMMITS:                        f406a45, 81dec23, 06100e7, 77e9d65, 1376fa4
RECOVERED_FROM:                 a local session that ended mid-turn after 51 tool calls
FALSE_SUCCESS:                  0
```

## RECOVERED_FROM_INTERRUPTED_SESSION

The interrupted session **had already landed its work**. The tree was clean at `222078b` with five
new commits after the previously certified head (`33d01b6`):

| SHA | Subject | Δ |
|---|---|---|
| `7b14297` | fix(autonomous): make a failed or full disk visible instead of fatal | 18 files, +4352/−70 |
| `ac1ad33` | verify(autonomous): re-certify the writer and re-arm the guard that checks it | 3 files, +524 |
| `01ea265` | docs(autonomous): write down the ops contract the lab now enforces | 5 files, +410 |
| `5cf8b73` | test(autonomous): build the launcher fixture from the launcher's own parser | 3 files, +42/−32 |
| `222078b` | chore(autonomous): drop the lint suppressions the hardened code no longer needs | 2 files |

Nothing was rewritten. Each item was then re-established from the runtime rather than from the
description, per [INTERRUPTED_SESSION_RECOVERY.json](reports/recovery/INTERRUPTED_SESSION_RECOVERY.json).

## IMPLEMENTED

Recovered and verified as working: the exit contract, the collector's terminal-failure
propagation, the supervisor's failure detection and truthful stop report, disk levels with a
measured rate, the durable-write helper, PAPER's survival of a storage failure, the
M-03/M-07 preservation gate, and the launcher's `start` / `stop` / `restart` / `status` /
`--data-root` surfaces.

Fixed during this phase (five commits):

1. **A `FAILED` capture claimed `CONTINUOUS_DATA`.** `reporting.py` reads that flag as
   `permits_continuity_claim` and `continuity_continuous`, so a capture whose writer died could
   licence a continuity claim downstream. A failed run is now `INCOMPLETE_DATA`; a clean capture
   still reports `CONTINUOUS_DATA`.
2. **`COLLECTOR_READY` read `yes` while the collector was in a crash loop.** Readiness was keyed
   off a state file that a first-write failure never creates. It now also reads the manifest verdict
   and the child's process state.
3. **The operator's own status command crashed.** A child's log is written in the console code page
   while its JSON artifacts are UTF-8; decoding it with `errors="replace"` injected U+FFFD into the
   payload and a cp1252 console cannot encode it. Logs are now decoded with the encodings the child
   could actually have used, and the console degrades a character instead of dying.
4. **Machine-readable output depended on the console code page.** `--json` and the collector's
   output now escape non-ASCII, so redirected output is parseable.
5. **Five independent-verifier checks could never pass** (see DEFECTS) — including one that called
   an API that does not exist, so the claim it encoded had never been checked at all.

Also fixed: an absent measurement rendered as `?` instead of `None`, and an unmeasured survival time
as `unknown` instead of `~None h at the observed rate`.

## TESTS

| Gate | Result |
|---|---|
| `ruff check .` | All checks passed |
| `mypy .` | Success: no issues found in 350 source files |
| `pytest` at `222078b` | 1194 passed |
| `pytest` at `f406a45` | 1201 passed, 1 failed — the frozen-writer certificate guard |
| `pytest` final tree | **1202 passed**, 78 warnings in 220.08 s |
| new targeted tests | 42 passed (`test_lab_ops_hardening` + `test_forward_exit_contract`) |
| independent verifier | **18/18 PASS** |

`TEST_TARGET == RUNTIME_TARGET` holds: `CAPTURE_CRITICAL_PATHS` and the verifier's `RUNTIME_PATHS`
name the same modules the launcher actually spawns, and the guard proves the certified commit
matches the tree that ran.

## RUNTIME_VALIDATION

Three real runs on this host, no mocks in the runtime path:

| Run | Duration | Result |
|---|---|---|
| `paper-lab-ops-hardened-01` | 23.0 min | STOP-file stop, `CONTROLLED_STOP`, 115/115 sealed, **0 partial tails**, stop report `CLEAN` |
| `paper-lab-failinject-01` | 4.9 min | self-stop by duration, collector crash-looped and `FAILED`, **PAPER stayed RUNNING and exited 0** |
| `paper-lab-cert-01` | 12.8 min | `CLEAN`, 89/89 sealed, 0 partial tails, replay `ok: true` with 89/89 fingerprints, deterministic |

The re-certification capture happened on all four data planes (spot and perp, BTC and ETH) against
public read-only Binance endpoints, with **zero credentials** and **zero sequence gaps**, and its
manifest records `commit f406a459b89f41e7771e5edb0a33f6725f708831`.

## FAILURE_INJECTION

All thirteen cases in §6 exercised, twelve in tests and four at real-runtime level (the overlap is
deliberate): writer exception, collector that cannot finalise, supervisor child failure, disk
`WARNING`, disk `CRITICAL`, unwritable data directory, interrupted durable write, stale PID, restart
after abnormal termination, missing manifest, corrupt manifest, report write failure, graceful user
stop — plus a stale-heartbeat dashboard check. Every one asserts the process state, the exit status
and the health verdict, and none produces a false success.

## PAPER_VALIDATION

PAPER ran the real strategy router over real market data and produced `NO_TRADE` decisions only —
which is the correct result, because the admission ledger still admits **0 of 24** strategies
(17 `NO_GROSS_EDGE`, 7 `COST_KILLED`, 0 candidates, 0 active). It recorded **0 paper trades**,
**0 shadow trades**, **0 runtime failures** and **0 risk vetoes**, and it survived a co-located
collector crash loop without a single lost cycle.

## FALSE_SUCCESS

```text
FALSE_SUCCESS = 0
```

Every `0` in this report came from the runtime, not from a default. Two would-be false successes
were found and closed (F1, F6), and one *would-be* pass was rejected: the frozen-writer guard's
failure is reported as a failure and resolved by re-certification.

## DEFECTS

| ID | Sev | Status | Summary |
|---|---|---|---|
| F1 | P1-adj | FIXED | `FAILED` capture published `continuity=CONTINUOUS_DATA` |
| F2 | P3 | FIXED | `~None h at the observed rate`, `state_age=Nones` |
| F3 | P3 | documented | `remaining_missing_events` mixes depth update-id units into an events total |
| F4 | P2 | pre-existing | perp `aggTrade` never delivers; honestly reported `NO_DATA` |
| F5 | P3 | environment | two concurrent pytest runs delete each other's temp dir |
| F6 | P2 | FIXED | `COLLECTOR_READY: yes` next to a crash loop |
| F7 | P2 | FIXED | `paper_lab_status.py --json` died on a cp1252 console |
| F8 | P1 gov | resolved | the frozen-writer guard fired; fixed by a new capture |
| F9 | P3 perf | documented | the read-side report makes 4–5 full passes over the same segments |
| F10 | P3 | FIXED | five verifier checks that could never pass |

**P0 = 0. P1 = 0.** F3, F4 and F9 are recorded with evidence and a recommended direction rather than
being changed inside a hardening phase: F3 and F9 touch semantics or cost on the read side, and F4
is a venue-side stream that the collector already reports honestly.

## BLOCKERS

1. **Storage, long horizon.** The certified capture is small, but unattended 24/7 capture at the
   measured rates still needs a second volume. `--data-root` exists, is verified end-to-end, and the
   capacity policy names `EXTERNAL_STORAGE_REQUIRED` beyond the hot window rather than hiding it.
2. **M-03/M-07 need 24 h of clean capture.** The certified 12-minute run records the gap as time,
   not as untrustworthy data: zero sequence gaps, four books ending `HEALTHY`.
3. **Perp trade flow is absent** (F4), which constrains flow-based features to spot until the venue
   behaviour is understood.

## EVIDENCE

[INTERRUPTED_SESSION_RECOVERY.json](reports/recovery/INTERRUPTED_SESSION_RECOVERY.json) ·
[RUN_REPORT.json](RUN_REPORT.json) · [RUN_REPORT.md](RUN_REPORT.md) ·
[PAPER_LAB_INDEPENDENT_VERIFICATION.json](docs/PAPER_LAB_INDEPENDENT_VERIFICATION.json) ·
[certification manifest](reports/microstructure-forward-cert01/manifest/paper-lab-cert-01.json) ·
[certification replay](reports/cert01_replay.log) ·
[lab run report](reports/paper-lab/paper-lab-cert-01/LAB_RUN_REPORT.json) ·
[failure-injection lab run](reports/paper-lab/paper-lab-failinject-01/LAB_RUN_REPORT.json) ·
[writer failure manifest](reports/failure-injection/writer-dead/manifest/failinject-writer.json) ·
[readiness report](docs/FORWARD_DATA_QUALITY_REPORT.json) ·
[operations manual](docs/PAPER_CONTINUOUS_OPERATIONS.md)

## ARCHITECTURE_STATUS

Unchanged and intact. `Market Data → Market Intelligence → Asset Intelligence → Strategy Router →
Trade Proposal → Multi-Agent Review → Decision Engine → Deterministic Risk → Execution →
Reconciliation → Post-Trade → Experience / Research`. Risk, sizing, limits, execution and
accounting remain deterministic; no LLM or agent gained authority over any of them. This phase added
no trading architecture: it closed defects and made existing behaviour visible. `NO_LIVE_PATH`
passes, so no LIVE path was introduced or exposed.

## RFC_STATUS

No RFC was needed or opened. The work was defect closure against an existing contract.

## NEXT_PHASE

**ACCUMULATE → DISCOVER.** The infrastructure is now honest and reachable: one command starts the
lab, one opens a read-only console, one reports status, stop and restart are proven. The highest-value
next work package is therefore not more infrastructure but *data and edge*:

1. Continue unattended capture toward the 24 h M-03/M-07 floor, on a second volume via `--data-root`.
2. Share one replay pass across the four read-side artifacts (F9), because reporting currently costs
   more CPU than the capture it reports on and that cost grows with the 24 h sample.
3. Investigate the perp `aggTrade` silence (F4) so trade-flow features are not spot-only.
4. Only then let the admission pipeline look for a first `PAPER_CANDIDATE`; the ledger admits 0 of 24
   and that number must not move without evidence.
