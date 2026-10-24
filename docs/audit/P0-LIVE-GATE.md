# P0 — Live gate enforcement on every path that opens risk

> Contract for the work that closes **DEF-G3-03**. G-3 declared
> `LiveTradingGate` out of scope on purpose; this task is that scope.
>
> Preflight measured the defect before any code changed, against
> `96e211bd` (branch `audit/mt0004-negative-controls`): for all ten gate
> checks, a configuration the gate rejects still sent exactly **one** order
> and exited 0, and the gate was constructed **zero** times.

## 1. What the defect was

`src/trading_bot/execution/live_gate.py` implements ten pre-flight checks
(GATE-001…GATE-010) with `GateReport.all_passed` blocking only `critical`
failures. `src/` had **no importer**: `grep -rn "LiveTradingGate" src/` matched
only its own module and the package `__init__`. The live CLI therefore reached
`BitunixFuturesClient.place_order`, `BitunixSpotClient.place_spot_order` and
`MultiExchangeConnector.create_order` without ever asking whether the
environment was legal for live trading.

G-3 had already installed the **hot stop** on those same seven sinks. The two
controls are independent: the stop answers "has an operator stopped this run?";
the gate answers "is this deployment allowed to trade live at all?". P0 adds the
second without touching the first.

## 2. Preflight

| Item | Measurement |
|---|---|
| HEAD | `96e211bd` |
| Branch | `audit/mt0004-negative-controls` |
| Tree | clean before the first edit |
| G-3 | `docs/audit/G-3.md`, run `run-20261024T112751Z-G-3`, verdict `G3_VERIFIED_SCOPED` |
| Gate | ten checks, `GATE-001…GATE-010`; `all_passed` = no **critical** failure |
| Entrypoints | `run --mode live --auto-trade` (spot/futures), `place-order` (spot/futures) |
| Reduction | `close-position`, `set-tpsl`, `place-order CLOSE`, spot `sell` |
| Reachability | `LiveTradingGate` importers in `src/` before this task: **0** |

Baseline evidence is `docs/audit/runs/run-20261024T163641Z-P0-LIVE-GATE/before/`:
ten JSON runs, one per rejected check, all with `broker_calls: 1`,
`gate_validations: 0`, `exit_code: 0`.

## 3. Decision

### 3.1 Two enforcement points, one rule

The gate is consulted at the **sink boundary** — inside
`_live_order_boundary`, after the hot stop's switch check and before
`HotStopGate.order_boundary`, so both authorities cover the same in-flight lock
— and again at the **entry** of `run --auto-trade` and `place-order`, so a
refusal happens before any broker client is constructed. Both call the same
`_evaluate_live_gate`; there is no second rule engine.

`_live_order_boundary` now takes `settings` as a **required** keyword. An entry
boundary without the data the gate validates would be a bypass with a friendly
signature; the structural test asserts all seven call sites declare
`opens_risk` and `settings`.

### 3.2 All ten checks must pass, not only the critical ones

`GateReport.all_passed` blocks critical failures. Under that reading
**GATE-006** (SQLite directory reachable) and **GATE-008** (security
constraints) are severity `high` and would be advisory: a rejected check that
does not stop the order. P0's rule is `failed_gates == 0`, plus
`total_gates == 10` (a report with a missing check is not a pass in either
reading).

This is deliberately **stricter than the gate's own verdict**, and the rule
lives in `_evaluate_live_gate`, not in `LiveTradingGate`, so the class keeps
its published semantics for every other caller. The unit and verifier cases for
GATE-006/GATE-008 exist to pin the difference: they are the two checks a
critical-only implementation lets through.

GATE-009 and GATE-010 cannot fail through configuration (one reports the logging
block, the other returns warnings on a pass). The tests force a failure on the
real class to prove that a rejection at those severities also blocks; no claim
is made that they can fail naturally.

### 3.3 Credentials come from the runtime, not from `os.environ`

The CLI loads its env file through pydantic (`load_settings`), which populates
`Settings`, **not** `os.environ`. A gate reading `EXCHANGE_API_KEY` directly
would reject every correctly configured `--env-file` deployment for the wrong
reason. `LiveTradingGate` gained one optional constructor argument,
`credentials=(api_key, api_secret)`; when omitted it keeps the env behaviour
unchanged. Values are never logged or included in a message.

### 3.4 Reduction stays exempt, and the stop keeps priority

The `opens_risk=False` call sites (`close-position`, `set-tpsl`, stale-futures
flatten, futures CLOSE, spot sell) do not consult the gate. G-3's argument is
unchanged: a gate that also refused to close a position would trap the book in
exactly the configuration that is already suspect.

`_live_stop_is_closed` short-circuits the entry pre-check, so an engaged hot
stop is reported as the stop, not as a gate failure. The boundary checks the
switch before the gate for the same reason.

### 3.5 Fail closed

| Failure | Behaviour |
|---|---|
| `load_settings` raises in `place-order` | exit 2, no client, no order |
| `load_settings` raises at `run --auto-trade` startup | exit 2, no scanner iteration, no order |
| `LiveTradingGate.validate` raises | `live_gate_error:<type>`, refused |
| report has fewer than ten checks | `live_gate_incomplete:<n>/10`, refused |
| any check fails | `live_gate_blocked:<ids>`, refused |

`run --auto-trade` over a `run_dir` whose marker is already engaged keeps G-3's
behaviour: start, report the skip, exit 0. The gate is not consulted because the
stop already refused; no order is sent.

### 3.6 The G-3 probe fixture was corrected, not the G-3 claim

`scripts/audit/g3_live_probe.py` built live settings with `sandbox=True`, no
`exchange_id` and no credentials — an object a real `load_settings` rejects.
Once the gate is enforced, that fixture is refused (correctly). It now sets
`sandbox=False`, `exchange_id="bitunix"` and synthetic credentials. The G-3
positive controls still mean "without a marker the path reaches the broker";
they now reach it through a legal configuration.

## 4. Coverage matrix

`ENTRYPOINT → GATE → BROKER SINK`

| ID | Entrypoint | Gate consulted | Where | Sink | Opens risk | Result after P0 |
|---|---|---|---|---|---|---|
| P1 | `run --mode live --auto-trade --market-kind futures` | yes, at startup and at the sink boundary | `_cmd_run`, `_maybe_execute_live_futures_trade` | `BitunixFuturesClient.place_order` | yes | refused if any check fails |
| P2 | `run --mode live --auto-trade --market-kind spot` | yes, at startup and at the sink boundary | `_cmd_run`, `_maybe_execute_live_trade` | `MultiExchangeConnector.create_order` | yes | refused if any check fails |
| P3 | `place-order --market-kind futures --trade-side OPEN` | yes, before the client and at the sink boundary | `_cmd_place_order` | `BitunixFuturesClient.place_order` | yes | refused if any check fails |
| P4 | `place-order --market-kind spot --side buy` | yes, before the client and at the sink boundary | `_cmd_place_order` | `BitunixSpotClient.place_spot_order` | yes | refused if any check fails |
| P5 | `run --auto-trade` stale-futures pre-step | no | `_close_stale_futures_positions` | `flash_close_position` | no | reaches the broker (exempt) |
| P6 | `place-order --trade-side CLOSE` / `--reduce-only` | no | `_cmd_place_order` | `place_order` | no | reaches the broker (exempt) |
| P7 | `place-order --market-kind spot --side sell` | no | `_cmd_place_order` | `place_spot_order` | no | reaches the broker (exempt) |
| P8 | `close-position` | no | `_cmd_close_position` | `flash_close_position` | no | reaches the broker (exempt) |
| P9 | `set-tpsl` | no | `_cmd_set_tpsl` | `place_position_tpsl` | no | reaches the broker (exempt) |
| P10 | `run --demo` / `paper_cycle` | no | — | paper broker | no | unchanged; G-4 |
| P11 | `BitunixFuturesClient.cancel_order` | n/a | — | no entrypoint | — | unreachable (G-3) |

## 5. Acceptance criteria

| ID | Criterion |
|---|---|
| ACC-P0-01 | Positive control: with a legal configuration, P1–P4 reach the instrumented broker exactly once. |
| ACC-P0-02 | Each of the ten checks, rejected, produces zero broker calls and names its gate id. |
| ACC-P0-03 | All four entrypoints are covered; a rejecting gate makes each one exit 2 with zero calls. |
| ACC-P0-04 | The gate is consulted inside `_live_order_boundary`; removing that consultation is caught by a test. |
| ACC-P0-05 | Missing settings, a raising gate and a short report all refuse with zero calls. |
| ACC-P0-06 | `KILL_SWITCH` and `KILL_SWITCH_ENV` keep priority: the refusal names the stop, not the gate. |
| ACC-P0-07 | P5–P9 still reach the broker while the gate rejects. |
| ACC-P0-08 | No rejected entry reports success on stdout (`FALSE_SUCCESS = 0`). |
| ACC-P0-09 | AST: all seven live sinks remain inside `_live_order_boundary`. |
| ACC-P0-10 | AST: every boundary call declares `opens_risk` and `settings`; `settings` is required. |
| ACC-P0-11 | `hot_stop.py` is byte-identical to `a072da90`; G-1/G-2/G-3 semantics unchanged. |
| ACC-P0-12 | G-1/G-2/G-3, CLI, demo and autonomy suites pass; the mutation matrix kills every mutant. |
| ACC-P0-13 | No live trading is enabled by the shipped configuration; no exchange is contacted. |
| ACC-P0-14 | A verifier other than the suite re-derives ACC-P0-01…13 from an export and checks artefact hashes. |
| ACC-P0-15 | `TEST_TARGET == RUNTIME_TARGET`: the probe loads the exported `trading_bot.app` and the real gate module. |

## 6. Tests

- `tests/unit/test_live_gate_enforcement.py` — 47 cases: verdict (ten checks,
  every rejection, high-severity, short report, exception, credentials from
  settings), boundary (entry refused, reduction free, stop priority, required
  argument, AST), and the real CLI through
  `scripts/audit/p0_live_gate_probe.py`.
- `tests/unit/test_live_hot_stop_coverage.py` — G-3's 21 cases, with the
  in-flight test passing the now-required `settings`.
- `scripts/audit/p0_live_gate_mutants.py` — seven mutants, every anchor exact
  once, variant `src` wired into both pytest and the probe subprocess.
- `scripts/audit/verify_p0_live_gate.py` — separate verifier.

## 7. Limits of this verdict

- **No exchange is contacted.** Every sink is a recorder. The verifier proves
  the program reaches the call site; it cannot prove Bitunix would accept the
  payload, and P0 does not claim it.
- **Procedural independence, same author.** Verifier and probe are different
  artefacts from the suite, but not a second person.
- **Scope is the live CLI.** `run --demo`/`paper_cycle` (G-4) and D-6 are
  untouched. `--run-dir` still scopes the stop to a directory (G-3 §4.3).
- **GATE-009/010** are forced-failure cases only; they cannot reject a real
  configuration.
- **No real operator run.** `run --mode live --auto-trade` was driven with
  recording clients in a subprocess, not against a live process on a host.

## 8. Verdict vocabulary

`P0_VERIFIED_SCOPED` requires ACC-P0-01…15 **and** every risk-opening
entrypoint to be covered. `P0_PARTIAL` when a path is not demonstrated.
`P0_FAILED` for a reproducible bypass left uncorrected. Never
`PRODUCTION_READY`, never a second-person audit.
