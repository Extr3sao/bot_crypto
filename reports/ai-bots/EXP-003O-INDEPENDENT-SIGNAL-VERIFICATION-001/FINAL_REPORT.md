# FINAL REPORT — EXP-003O — Independent Signal Regeneration

**PHASE:** `EXP-003O` · **VERDICT:** `PASS_PARTIAL_INCOMPLETE_REAL_DATA` · **STATUS:** `INCOMPLETE`

`TECHNICAL_SIGNAL_PARITY=PASS` · `FULL_INDEPENDENT_CERTIFICATION=INCOMPLETE_REAL_DATA_COVERAGE` · `ECONOMIC_EDGE=NOT_EVALUATED` · `STRATEGY_PROMOTION=DENIED` · `LIVE=DISABLED` · `HOLDOUT=CLOSED`

## COMMITS

- baseline + protocol: `4ea93d815ed6` (prospective=`True`)
- experiment HEAD: `8aac8b475a15`

## IMPLEMENTED

- `scripts/exp_003o_contract.py` — the signal-free contract: 24 cells, states, writers,
  canonical bar digest. Shared by both producers; contains no rule.
- `scripts/exp_003o_baseline.py` — seals, dataset digests, config hashes, dependency map.
- `scripts/exp_003o_preregister.py` — `SIGNAL_SPECIFICATIONS.md`, `design/PROTOCOL.json`,
  `design/PREREGISTRATION.md`, digest check.
- `scripts/exp_003o_rebuilder.py` — Builder B: own reader, own EMA/RSI/ATR/MACD/Bollinger/
  volume arithmetic, own lane-B machines and driver. Imports stdlib, numpy and the contract.
- `scripts/exp_003o_original.py` — Builder A: the frozen 003N producer replayed per instant,
  with an exact anchor to the 52 769 published lane-A signals and 39 lane-B trades.
- `scripts/exp_003o_compare.py` — full outer join on the evaluation key, closed difference
  classes, per-cell reconciliation.
- `scripts/exp_003o_verify.py` — Verifier C: provenance, calendar, PIT, prefix invariance,
  independence, its own join, 12 negative controls, governance, functional coverage.
- `scripts/exp_003o_fixtures.py` — deterministic synthetic fixtures for the zero-sample
  families, active and quiet.

## RESULTS

- 275724 evaluation keys over 24 cells, 52848 signals in the original stream and 52848 in the independent one.
- **0 unexplained differences**, **0 PIT violations** over 275724 + 275724 audited rows.
- 12/12 negative controls effective and detected.
- cells without a real sample: `vol_regime_breakout@1h, vol_regime_breakout@4h, mean_reversion_vol_liq@4h` — their functional
  coverage rests on the frozen fixtures, which prove implementation behaviour only.

## TESTS

`{"note": "no TESTS.json: the suites were not executed for this report", "state": "NOT_RUN"}`

`PAPER_VALIDATION=NOT_PERFORMED` · `FALSE_SUCCESS=0`

## DEFECTS

- **DEF-003O-01** (medium): lane-A decisions depend on an undocumented fixed 80-bar window
  - re-producing a signal needs max(min_candles+1, 80) bars of history, not merely the formula: an EMA re-seeded on 80 bars differs from an EMA over the whole series. EXP-003N's published numbers therefore cannot be reproduced from the rule text alone.
  - treatment: reproduced exactly; documented in SIGNAL_SPECIFICATIONS.md
- **DEF-003O-02** (medium): lane-B parameter names say hours, the machines consume bars
  - on 4h bars, channel_hours=168 is a 672-hour channel; the 4h cells run a ~4x longer rule than their names claim
  - treatment: reproduced as frozen; the 4h cells still have no sample in this window
- **DEF-003O-03** (low): lane A has no position state, so signals overlap bar by bar
  - a signal count from lane A is not a trade count; the parity compares decisions, and 003N priced overlaps downstream
  - treatment: reproduced; documented as a property of the screening
- **DEF-003O-04** (medium): two lane-B 4h cells have zero evaluable bars in a 46-day window
  - 276 bars against a 744-bar warm-up: the cell can be announced but not evaluated
  - treatment: declared INSUFFICIENT_EVIDENCE_REAL_WINDOW; functional coverage rests on fixtures

## BLOCKERS

- see status: a required dimension is not PASS

## EVIDENCE

| artefact | sha256 (first 16) |
| --- | --- |
| `design/PROTOCOL.json` | `b28a7b4c53168fd5…` |
| `design/PREREGISTRATION.md` | `c8172493a59c82ae…` |
| `SIGNAL_SPECIFICATIONS.md` | `fbb3973569a607a5…` |
| `BASELINE_MANIFEST.json` | `9914bba8b6cf831d…` |
| `signals/original_evaluations.jsonl.gz` | `024bd453635115c1…` |
| `signals/independent_evaluations.jsonl.gz` | `e2110fa777a34074…` |
| `SIGNAL_PARITY.csv` | `2a4e7987b5888911…` |
| `SIGNAL_PARITY_SUMMARY.json` | `b6b58caa5b2165a6…` |
| `PIT_AUDIT.json` | `8672c70e873acf0c…` |
| `NEGATIVE_CONTROLS.json` | `e0eafa8a0513606f…` |
| `INDEPENDENCE_AUDIT.md` | `37818f02a1c71b00…` |
| `INDEPENDENT_VERIFICATION.md` | `19716272b7acfbd2…` |
| `CLEAN_CHECKOUT_REPRODUCTION.json` | `**missing**` |
| `CELL_COVERAGE_MANIFEST.csv` | `c9e33e46811eb7eb…` |
| `RUN_REPORT.json` | `a127b66fcf67a665…` |

## ARCHITECTURE_STATUS

The experiment is an offline, read-only layer over the frozen 003N universe. It adds no
strategy, no indicator to the runtime, no order path and no configuration change. The
runtime modules it exercises are the same ones the paper lane calls.

## RFC_STATUS

`RFC-EXP-003O` is implemented and executed in its whole scope: WP-00 to WP-04, with the
deliverables listed in section 10. Nothing in it is `PROPOSED` any more except the
continuation.

## NEXT_PHASE

`EXP-003P — Paper Execution Reality` is the natural successor: signal parity is now
measured, but a decision is not a fill. 003P must observe the paper cycle (orders,
fills, partials, slippage) without confusing a simulated fill with an executed one.

A recommendation, not a promotion: the numbers of 003N still say no mechanism covers its
own cost with sample, and nothing in 003O changes that. `EXP-003P` measures execution,
not edge; `STRATEGY_PROMOTION` stays `DENIED`.
