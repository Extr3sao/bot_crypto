# FINAL REPORT — EXP-003O — Independent Signal Regeneration

**PHASE:** `EXP-003O` · **VERDICT:** `PASS_PARTIAL_INCOMPLETE_REAL_DATA` · **STATUS:** `INCOMPLETE`

`TECHNICAL_SIGNAL_PARITY=PASS` · `FULL_INDEPENDENT_CERTIFICATION=INCOMPLETE_REAL_DATA_COVERAGE` · `ECONOMIC_EDGE=NOT_EVALUATED` · `STRATEGY_PROMOTION=DENIED` · `LIVE=DISABLED` · `HOLDOUT=CLOSED`

## COMMITS

- baseline + protocol: `4ea93d815ed6` (prospective=`True`)
- experiment HEAD: `fe196d795e40`

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
- cells with no evaluable instant at all: `mean_reversion_vol_liq@4h, vol_regime_breakout@4h` — the 46-day window never clears their warm-up, so their coverage rests on the frozen fixtures, which prove implementation behaviour only.
- cells evaluated but silent: `vol_regime_breakout@1h` — real NO_SIGNAL instants compared key by key; a zero here is a compared zero, not a missing sample.
- cells with zero signals in the independent stream: `vol_regime_breakout@1h, vol_regime_breakout@4h, mean_reversion_vol_liq@4h`.

## TESTS

`{"executed_at_utc": "2026-10-21T09:13:09Z", "failed": [], "mypy": {"exit_code": 0, "tail": "Success: no issues found in 11 source files"}, "pytest_reports": {"exit_code": 0, "tail": "174 passed, 14 warnings in 21.95s"}, "ruff": {"exit_code": 0, "tail": "All checks passed!"}, "state": "PASS"}`

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
- **DEF-003O-05** (high): the verifier's own bar reader disagreed with the producers' arithmetic
  - the window digest packs float64 bits; the verifier summed minute volumes with Python's sum while the producers used numpy's pairwise reduction, so 37,224 per-row digests disagreed in both streams. The audit was blaming the producers for a defect in itself.
  - treatment: reader now uses the same IEEE-754 reduction and a digest-format self-check runs before any declared digest is judged; 0 mismatches after the fix
- **DEF-003O-06** (high): negative controls asserted on the first difference class of a one-sided join
  - NEG-06 and NEG-10 mutated one side of a join with no counterpart, so the join invented MISSING/EXTRA_EVALUATION and the expected class was never the one read; NEG-07 placed its spurious key on an instant that already existed in both streams.
  - treatment: each control now mutates a single row inside a complete cell and requires exactly one class with exactly one instance; 12/12 effective
- **DEF-003O-07** (high): a cell with no evaluable instant could borrow a quiet cell's zero
  - coverage counted cells by zero signals, so the two 4h lane-B cells that are entirely NOT_READY looked identical to a cell that was evaluated 1,083 times and never fired.
  - treatment: evaluated instants are counted separately from signals; the full certification is INCOMPLETE_REAL_DATA_COVERAGE, not PASS
- **DEF-003O-08** (low): report generation crashed on a relative --out path
  - design/PROTOCOL.json was made relative to the repository before being resolved
  - treatment: every entry point resolves --out first

## INDEPENDENT VERIFICATION

- **`BUILDER != VERIFIER`**: three separate programs. Builder A replays the frozen 003N
  producer and imports its families; builder B reads the bars itself and owns its own
  indicator arithmetic and lane-B machines; the verifier recomputes every row from bytes
  with its own digest, join and controls and never calls either builder to decide.
- **What the verifier proved**: every declared window digest reproduced (275,724 keys),
  calendar coverage with zero missing or extra instants, zero PIT violations, prefix
  invariance at 300 and 1,500 bars, 12/12 controls each detecting exactly one intended
  class in a complete cell.
- **What it did not prove**: `organizational_independence=false`. One author wrote both
  builders and the verifier in one session, so a shared conceptual error would survive
  the parity. The fixtures and the hand-computed expectations are the only defence
  against that, and they cover the rule families, not the regimes.

## BLOCKERS

- no evaluable instant in this window: mean_reversion_vol_liq@4h, vol_regime_breakout@4h (their warm-up exceeds 46 days of bars)
- organizational independence not certified: builders A/B and verifier C share one author; BUILDER != VERIFIER holds as three programs, not as three people

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
| `CLEAN_CHECKOUT_REPRODUCTION.json` | `fefca46da935f381…` |
| `CELL_COVERAGE_MANIFEST.csv` | `c9e33e46811eb7eb…` |
| `RUN_REPORT.json` | `95e893977bbda885…` |

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
