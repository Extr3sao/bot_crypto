# FINAL REPORT — P0 LIVE GATE ENFORCEMENT

**Verdict: `P0_VERIFIED_SCOPED`.**

Scoped to the live CLI paths that can open or increase exposure. All ten gate
checks reject the order, reduction still reaches the broker, and the exported
commit re-derives every criterion independently of the test suite.

- Branch: `audit/mt0004-negative-controls`
- Before: `96e211bd`
- Implementation: `6c90b21d`; verifier correction: `efd97e76`
- Verified export: `82e8b3ac`
- Commits: `6c90b21d` (enforcement), `efd97e76` (verifier correction),
  `82e8b3ac` (evidence), `1b4e1896` (verification close); tree clean
- Verifier: `docs/audit/runs/run-20261024T163641Z-P0-LIVE-GATE/verification.json`
  — 15/15 in 235.0 s
- No exchange contacted; no live trading enabled; no push.

## What was wrong

`LiveTradingGate` implemented ten pre-flight checks and nothing in `src/`
imported it. `run --auto-trade` and `place-order` went straight to the Bitunix
clients. Measured before the change: for each of the ten checks, a
configuration the gate rejects produced **1 broker call, 0 gate validations,
exit 0**. The gate was not bypassed; it was absent.

## What changed

| Change | Why |
|---|---|
| `_evaluate_live_gate(settings)` | one verdict: ten checks must all run, `failed_gates == 0` |
| gate inside `_live_order_boundary` | the sink cannot be reached without it; same lock the hot stop uses |
| startup refusal in `_cmd_run` | `run --auto-trade` refuses before the scanner and before a client exists |
| pre-client refusal in `_cmd_place_order` | no exchange object is built for an order the gate rejects |
| `credentials=(key, secret)` on the gate | the CLI's env file is read by pydantic, not exported to `os.environ` |
| `settings` required on the boundary | an entry boundary without gate data would be a bypass with a friendly signature |

The stop still wins: a stopped process is reported as stopped, and an
already-stopped `run` keeps G-3's start-and-report behaviour.

`hot_stop.py` remains byte-identical to `a072da90`.

## Evidence

| Criterion | Result |
|---|---|
| 0 broker calls when a check rejects | 10/10 checks, 4/4 entrypoints |
| 0 calls when checks cannot complete | settings error, gate exception, 9-check report: all refused, exit 2 |
| Every entrypoint covered | `run` spot/futures, `place-order` spot/futures |
| `FALSE_SUCCESS` | 0 on every rejected entry |
| Reduction preserved | `close-position`, `set-tpsl`, futures CLOSE, spot sell: 1 call each |
| `KILL_SWITCH` priority | refusal names the stop; no gate text |
| Regressions | 473 tests pass on the export; G-3's 21 cases unchanged in meaning |
| Mutation sensitivity | 7/7 killed, including the critical-only and reduction mutants |
| Integrity | `hot_stop.py` byte-identical; 19/19 artefact hashes; clean export |

BEFORE/AFTER: `BEFORE_AFTER.md`. Coverage: `COVERAGE_MATRIX.md`. Commands:
`COMMANDS.md`. Sequence and the two verifier failures found on the way:
`TIMELINE.md`.

## Acceptance criteria

| ID | Status |
|---|---|
| ACC-P0-01 positive control | passed (V-3) |
| ACC-P0-02 each rejected check blocks | passed (V-4, V-9) |
| ACC-P0-03 all entrypoints covered | passed (V-5) |
| ACC-P0-04 boundary consults the gate | passed structurally (V-2) and behaviourally |
| ACC-P0-05 fail closed on missing/raising/short | passed (V-7, V-9) |
| ACC-P0-06 stop priority | passed (V-8) |
| ACC-P0-07 reduction preserved | passed (V-6) |
| ACC-P0-08 no false success | passed (V-4) |
| ACC-P0-09 sinks inside boundary | passed (V-2) |
| ACC-P0-10 boundary declares risk and settings | passed (V-2) |
| ACC-P0-11 `hot_stop.py` untouched | passed (V-11) |
| ACC-P0-12 regressions + mutants | passed (V-13, V-14) |
| ACC-P0-13 live still disabled in config | passed (V-12) |
| ACC-P0-14 separate verifier + hashes | passed (V-1, V-15) |
| ACC-P0-15 test target == runtime target | passed (V-3b) |

## Defects

Closed: **DEF-G3-03** (gate never called), **DEF-P0-01** (G-3 probe used an
illegal live configuration), **DEF-P0-02** (verifier built `mode` as a string,
making two checks raise).

Open, out of scope:

- **DEF-P0-03**: `LiveTradingGate._data_dir` is stored and unused; GATE-006
  resolves the SQLite path against the process working directory.
- **DEF-P0-04**: `run --auto-trade` still has no `--confirm-live`; the gate is
  the only admission control on that path.

## Limits

- Every broker is a recorder. The run proves the program reaches the call site
  and refuses before it; it does not prove exchange acceptance.
- Independence is procedural, same author. Never "independently audited".
- GATE-009/010 are forced failures; they cannot reject a real configuration.
- `run --demo` / `paper_cycle` (G-4) remains outside both controls.
- The hot stop remains scoped to `--run-dir` (G-3 §4.3).

## Recommendation for G-4

Stop adding controls to `run --demo`. Its defect is structural: `paper_cycle`
has its own broker call and never constructs `DecisionEngine`, so neither rule 0
nor the live gate applies. The next task should decide whether the path exists —
route it through the autonomous runtime or remove it — before any further gate
work. P0 does not claim coverage of that path and the backlog should not either.
