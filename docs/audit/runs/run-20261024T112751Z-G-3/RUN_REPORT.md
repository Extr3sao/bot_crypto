# G-3 — RUN REPORT

- **Verdict:** `G3_VERIFIED_SCOPED` (verifier: 15/15, `verification.json`).
- **Checkout:** `C:/Users/GVLLFR0035/Downloads/ff-wt-mt0004`
- **Branch:** `audit/mt0004-negative-controls`
- **Verified commit:** `9eeb8e87` (parent `a072da90`, the G-1 close-out)
- **Baseline commit:** `a072da90`
- **Date:** 2026-10-24
- **Contract:** [G-3.md](../../G-3.md)
- **Independence:** PROCEDURALLY_SEPARATED — a different artefact, the same author.

## 1. What was measured

The mission asked a measurement question: can a LIVE path reach a broker without
crossing the Hot Stop? The answer at `a072da90` was **yes, on every live
entrypoint**. With `KILL_SWITCH` sitting in the run directory:

| Entrypoint | Sink reached | `broker_calls` | exit |
|---|---|---|---|
| `run --mode live --auto-trade --market-kind futures` | `futures.place_order` | **1** | 0 |
| `run --mode live --auto-trade --market-kind spot` | `connector.create_order` | **1** | 0 |
| `place-order --market-kind futures --trade-side OPEN` | `futures.place_order` | **1** | 0 |
| `place-order --market-kind spot --side buy` | `spot.place_spot_order` | **1** | 0 |
| `close-position` | `futures.flash_close_position` | 1 | 0 |
| `set-tpsl` | `futures.place_position_tpsl` | 1 | 0 |

`evidence/live_matrix_before.json`. `HotStopGate` was imported by exactly one
module (`autonomous/runtime.py`); `app.py` imported only the marker writer for
the G-2 CLI. G-1's persistence was real and scoped to a program that the live
paths do not run.

## 2. What changed

One boundary function, `_live_order_boundary(gate, *, opens_risk=…)`, and seven
call sites inside it:

1. `_maybe_execute_live_trade` (spot entry) — `opens_risk=True`
2. `_maybe_execute_live_futures_trade` (futures entry) — `opens_risk=True`
3. `_close_stale_futures_positions` — `opens_risk=False`
4. `_cmd_place_order` futures — classified from `--trade-side` / `--reduce-only`
5. `_cmd_place_order` spot — `buy` opens risk, `sell` does not
6. `_cmd_close_position` — `opens_risk=False`
7. `_cmd_set_tpsl` — `opens_risk=False`

Three decisions are worth arguing with, and are argued in [G-3.md §4](../../G-3.md):

- **Entry is gated, reduction is not.** A stop that refused `close-position`
  would trap the book at the moment the operator is trying to get out. The
  classification is a literal at each call site, and the AST test requires it.
- **The run directory is stable by default** (`data/live`, overridable with
  `--run-dir`). A live bot is one long-lived process, so a restart has to land in
  the same directory for G-1's marker to be inherited.
- **`KILL_SWITCH_ENV` is checked at dispatch.** A live path has no
  `DecisionEngine` rule 0, so the boot-time switch would otherwise be invisible
  here. Refusing does not write a marker: the env token keeps the semantics G-1
  fixed.

`hot_stop.py` is byte-identical to `a072da90` (V-10). G-3 reused the gate; it did
not rewrite the thing G-1 and G-2 verified.

**Retries stay inside the boundary.** `MultiExchangeConnector.create_order`
retries with tenacity *inside* the call G-3 wraps, so a retry cannot escape the
gate; the lock is held for the whole call, retries included. A retry is not a
second dispatch site and does not get a second decision.

## 3. Coverage matrix (measured)

| ID | Entrypoint | Sink | Class | Gate | Evidence |
|---|---|---|---|---|---|
| E1 | `run --auto-trade` futures | `BitunixFuturesClient.place_order` | `RUNTIME_REACHABLE` | yes (`opens_risk=True`) | V-3, V-4, M3 |
| E2 | `run --auto-trade` spot | `MultiExchangeConnector.create_order` | `RUNTIME_REACHABLE` | yes (`True`) | V-4 (`run_calls=0`), M2 |
| E3 | `_close_stale_futures_positions` | `flash_close_position` | `RUNTIME_REACHABLE` | yes (`False`, exempt) | AST V-2 |
| E4 | `place-order` futures OPEN | `place_order` | `RUNTIME_REACHABLE` | yes (`True`) | V-4 (`cli_calls=0`), M4 |
| E5 | `place-order` futures CLOSE | `place_order` | `RUNTIME_REACHABLE` | yes (`False`, exempt) | focals `test_reduction_...` |
| E6 | `place-order` spot buy | `place_spot_order` | `RUNTIME_REACHABLE` | yes (`True`) | V-6 |
| E7 | `place-order` spot sell | `place_spot_order` | `RUNTIME_REACHABLE` | yes (`False`, exempt) | focals |
| E8 | `close-position` | `flash_close_position` | `RUNTIME_REACHABLE` | yes (`False`, exempt) | V-8 |
| E9 | `set-tpsl` | `place_position_tpsl` | `RUNTIME_REACHABLE` | yes (`False`, exempt) | focals |
| E10 | `BitunixFuturesClient.create_order` | inner REST client | `LEGACY` (no caller) | n/a | `grep` P-4 |
| E11 | `BitunixSpotClient.create_order/cancel_order` | — | `DEAD` (raises) | n/a | `bitunix.py:570` |
| E12 | `*.cancel_order` | — | `UNREACHABLE` | n/a | `grep` |
| E13 | `run --demo` → `paper_cycle` | `PaperBroker` | `EXCLUDED` (G-4) | **no** | unchanged |
| E14 | `scripts/st6_*` | string fixtures | `TEST_ONLY` | n/a | P-5 |

Seven `RUNTIME_REACHABLE` rows, seven gated call sites. E13 is the one that is
still open, and it is G-4.

## 4. Tests

| Suite | Result |
|---|---|
| `tests/unit/test_live_hot_stop_coverage.py` | **21 passed** (and **11 failed, 10 passed** on the pre-fix export — ACC-G3-11) |
| focal + `test_app_demo` + CLI + trade journal | **70 passed** |
| `tests/unit/autonomous/` (G-1/G-2) | **360 passed** |
| same four paths inside the verifier export | **426 passed** (V-11) |

The eleven reds are the eleven properties G-3 added: four blocked entrypoints,
the operator-CLI marker, the restart, the unreadable marker, the env switch, the
AST coverage (two variants) and the in-flight barrier. The ten that pass before
the fix are the positive controls, the four reduction paths, `--disarm` and the
identity check — exactly the set that must not depend on the change.

## 5. Mutation matrix

`6/6 killed`, baseline green, 307.8 s, all at `9eeb8e87` (V-12b: the exported
`app.py` is byte-identical to the matrix's rev).

| Mutant | Property removed | Killed by |
|---|---|---|
| M1 | the boot-time switch is ignored | env-switch test |
| M2 | spot entry ignores the run directory | `run-spot` + AST test |
| M3 | futures entry ignores the run directory | `run-futures` |
| M4 | `place-order` stops classifying entry as risk | `place-order-futures` |
| M5 | each process invents its own run directory | restart test |
| M6 | the boundary drops the lock | in-flight barrier test |

## 6. Verifier

`scripts/audit/verify_g3.py --rev 9eeb8e87`: **15/15**, 261.3 s.

| Check | Criterion | Result |
|---|---|---|
| V-1 | identity, no dirty source | PASS (`dirty_source=0`) |
| V-2 | 7 sinks, 0 unguarded | PASS |
| V-3 | positive control: 1 call | PASS |
| V-3b | probe loaded this export and the fakes | PASS |
| V-4 | CLI marker blocks loop and CLI | PASS |
| V-5 | restart logs `restored`, 0 calls | PASS |
| V-6 | unreadable marker refuses | PASS |
| V-7 | env switch refuses, no marker | PASS |
| V-8 | `close-position` still sends | PASS |
| V-9 | `--disarm` exits 2 | PASS |
| V-10 | `hot_stop.py` byte-identical to baseline | PASS |
| V-11 | 426 tests on the exported tree | PASS |
| V-12 / V-12b | 6/6 killed, same `app.py` | PASS |
| V-13 | 7/7 artefact hashes | PASS |

The verifier re-derives the structural property from the exported source and
writes its own markers with the real `kill-switch` CLI; it does not read the test
module. It does **not** re-implement the instrumentation: the recording clients
come from `g3_live_probe.py`, written by the same author. A probe that recorded
nothing would fail V-3, but the verifier cannot prove the HTTP client would have
accepted the payload — only that the program reaches the point where it is
called.

## 7. Limits — what this does not claim

1. **Scope is the run directory, not the account.** `--run-dir` pointing
   elsewhere (or a fresh checkout) boots operational. There is no global latch;
   G-1 §4.6's limit is now reachable from the live commands too.
2. **A stop cannot preempt a call already on the wire.** A marker written by
   another process is honoured by the *next* dispatch. The ACK-waits guarantee
   applies to an in-process `engage`, as in G-2.
3. **`run --demo` → `paper_cycle.py` is still ungated** (G-4). The live gate
   does not apply to a paper sink, and this task did not touch it.
4. **No real exchange was contacted.** Every sink is a recorder. Payload
   validity, rate limits and exchange-side rejections are out of scope.
5. **No live trading, no credentials, no push.** `--auto-trade` still requires a
   config with `runtime.mode: live`; `place-order` still requires `--confirm-live`.
6. **Power-loss durability on Windows is not claimed** — inherited from G-1's
   `write_control_file` (no directory fsync on Windows).
7. **D-6 was not opened.** No claim is made about it.

## 8. Defects found

- **DEF-G3-01 (fixed here).** `tests/unit/test_app_demo.py::test_main_kill_switch_not_implemented_returns_two`
  asserted that `kill-switch` does not exist. G-2 implemented it and did not
  update the test, so the suite has been red since G-2 — outside every evidence
  set G-2 ran. The assertion now pins the current contract (exit 2, empty stdout,
  `--run-dir` named). `evidence/baseline_stale_test.txt`.
- **DEF-G3-02 (fixed here, verifier).** The first verifier run reported V-10 FAIL
  on a byte-identical `hot_stop.py`: `git show` was decoded through the Windows
  code page, turning UTF-8 arrows into two characters. Fixed by comparing bytes
  (`9eeb8e87`), and the whole first-run output is kept in TIMELINE.md.
- **DEF-G3-03 (open, out of scope).** `LiveTradingGate` (`execution/live_gate.py`)
  is never invoked by the CLI: `run --auto-trade` performs none of its ten
  checks. This is a live *admission* gap, not a stop gap, and G-3 deliberately
  did not enable it.

## 9. Artefacts

| Path | sha256 |
|---|---|
| `docs/audit/G-3.md` | `b32b19444ddd4921…` |
| `src/trading_bot/app.py` | `834eaa27cc4f6ff7…` |
| `tests/unit/test_live_hot_stop_coverage.py` | `a00c1ab174ddacf2…` |
| `tests/unit/test_app_demo.py` | `a2376e51174d6d1b…` |
| `scripts/audit/g3_live_probe.py` | `db5049641543fc5d…` |
| `scripts/audit/g3_mutants.py` | `4256c36aab98fc84…` |
| `scripts/audit/verify_g3.py` | `a3bd3ab1e03b2976…` |
| `verification.json` (output, not self-hashed) | `7cef3d37dc95c109…` |

Full hashes in `RUN_REPORT.json["artifacts"]` and `["evidence"]`. The backlog and
these reports are record, not inputs, so they are excluded from the artifact set
— otherwise the report would have to hash itself.

## 10. State of the sibling gaps

| Gap | State after this run | Basis |
|---|---|---|
| **G-1** | closed, `VERIFIED_SCOPED`, unchanged | `hot_stop.py` byte-identical (V-10); 360 autonomous tests pass |
| **G-2** | closed, `VERIFIED_SCOPED`, unchanged | same; the CLI still refuses `--disarm` (V-9) |
| **G-3** | **`G3_VERIFIED_SCOPED`** | this report |
| **G-4** | **open, no contract** | `paper_cycle.py` still reaches `PaperBroker` without `DecisionEngine`; not touched |
| **D-6** | **not opened** | no claim |

G-3 says nothing about G-4's severity, and does not inherit G-1/G-2's limits as
if it had fixed them: the cross-`run_dir` limit is now shared by three gaps, not
closed by any of them.
