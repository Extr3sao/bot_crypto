# PREREGISTRATION — EXP-003O — Independent Signal Regeneration

**Written and committed before any comparison ran.** The digest of `design/PROTOCOL.json`
travels inside every artefact this experiment produces, and `RUN_REPORT.json` states whether the
commit order actually makes this prospective (`prospective` is computed from Git, not typed by
hand).

## Question

Does the frozen signal producer of EXP-003N emit, at every evaluable instant of its own
calendar, the same decision that a separately written implementation derives from the same
bars — and if it does not, where exactly do they diverge?

This is a question about **causal correctness**, not about money. `ECONOMIC_EDGE` is
`NOT_EVALUATED` here and no cell can be promoted by passing.

## Unit of comparison

`EvaluationKey = (cell_id, symbol, decision_time)`, with

- `cell_id` = `family@timeframe` over the 24 cells 003N screened (6 lane-A families × 5m/1h/4h
  and 3 lane-B families × 1h/4h), three symbols each;
- `decision_time` = the bar close at which the decision was taken.

Every key carries one state: `SIGNAL` (with `LONG`, `SHORT` or `FLAT`), `NO_SIGNAL`,
`NOT_READY` or `NOT_EVALUABLE`. `NOT_READY` and `NOT_EVALUABLE` carry a reason code and are
**never** merged into `NO_SIGNAL`: a zero produced by a warm-up and a zero produced by a quiet
market are different facts.

## Frozen inputs

- The three 1m files of EXP-003K, by the digests `DESIGN.json` of 003N froze
  (`7fbdfefa…`, `cf04dc37…`, `33342aac…`), re-hashed at run time.
- The 003N seal (`SHA256SUMS.txt`, 29 files) verified before and after, and never written to.
- The 24 cells, their families and their parameters, copied into `design/PROTOCOL.json` with a
  `parameter_hash` per cell.
- The calendar rule per lane, the availability convention and the reason vocabulary.

## Independence

The rebuilder is `scripts/exp_003o_rebuilder.py`. It may import the standard library, `numpy`
and `scripts/exp_003o_contract.py` (cell ids, states, writers, a bar dataclass, a digest
helper). It may **not** import `trading_bot.research.families`, `trading_bot.indicators`,
`trading_bot.research.economic_recovery.pit15`, `trading_bot.vision.signal_sources`, nor read
`SIGNALS.jsonl.gz`, `SCREENING.json`, `VALIDATION.json` or any `*evaluations*` file.

That rule is not a promise. `scripts/exp_003o_verify.py` enforces it three ways: an AST scan of
the rebuilder's import graph, a static scan for the forbidden paths as string literals, and a
causal run of the rebuilder under an audit hook that raises on any `open` of a forbidden path.
`NEG-12` proves the third mechanism can fail.

## Order of work

1. `WP-00` baseline: seals, digests, cells, dependency map. **Done before this file.**
2. `WP-01` this protocol, **committed**. The commit hash is recorded in every report.
3. `WP-02` both producers run without reading each other: the independent rebuilder first, then
   the replay of the frozen producer.
4. `WP-03` parity join, PIT audit, prefix invariance, 12 negative controls, independence audit.
5. `WP-04` clean-checkout reproduction, reports, seal.

## Acceptance, decided in advance

| id | condition | if it fails |
| --- | --- | --- |
| `ACC-003O-01` | baseline inputs intact, 003N read-only | `BLOCKED` |
| `ACC-003O-02` | protocol committed before evaluation; `prospective` truthful | `INCOMPLETE` if not prospective |
| `ACC-003O-03` | all 24 cells have a traceable count and state | `INCOMPLETE` |
| `ACC-003O-04` | rebuilder isolated from the producer's signal and indicator code | `FAIL` |
| `ACC-003O-05` | exact coverage; 0 unexplained differences | `FAIL` |
| `ACC-003O-06` | `data_available_at <= decision_time` at every instant used | `FAIL` |
| `ACC-003O-07` | 12/12 negative controls effective and detected | `FAIL` / `INCOMPLETE` |
| `ACC-003O-08` | zero-sample families have an activating fixture and a quiet control | `INCOMPLETE_FUNCTIONAL_COVERAGE` |
| `ACC-003O-09` | verifier is not a builder; clean-checkout reproduction | `INCOMPLETE` |
| `ACC-003O-10` | holdout closed, 0 orders, `config/` untouched | `FAIL` |
| `ACC-003O-11` | reports and hashes complete; `FALSE_SUCCESS=0` | `INCOMPLETE` |
| `ACC-003O-12` | the verdict promotes nothing and re-prices nothing | `FAIL` |

## Two verdicts, never merged

- `TECHNICAL_SIGNAL_PARITY` — coverage, PIT, parity and controls. It can pass on a window too
  short to be economically meaningful; it says nothing about edge.
- `FULL_INDEPENDENT_CERTIFICATION` — the above **plus** functional coverage of every family
  (real sample or activating fixture) and a verifier that is not a builder. Lane B's 4h cells
  cannot have a real sample in a 46-day window, so this one is expected to be
  `INCOMPLETE_REAL_DATA_COVERAGE` unless the fixtures carry the functional weight — and the
  fixtures prove implementation behaviour, not regime coverage.

`ECONOMIC_EDGE = NOT_EVALUATED` in all cases. `STRATEGY_PROMOTION = DENIED`. `LIVE = DISABLED`.
`HOLDOUT = CLOSED`.

## What would make this file dishonest

Editing it after seeing a difference, adding a tolerance after a mismatch, dropping a cell that
fails, or reporting `PASS` because two empty lists matched. None of those is available here: the
digest is quoted by every downstream artefact, and the comparator's difference classes are a
closed list frozen in `PROTOCOL.json`.
