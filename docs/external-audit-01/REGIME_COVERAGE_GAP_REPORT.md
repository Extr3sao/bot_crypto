# REGIME_COVERAGE_GAP_REPORT — POC02-R2-GOVERNANCE-RECONCILIATION-AND-ALPHA-SEARCH-01

Purpose: canonical evidence-backed map of regime coverage (TRACK F). This document is
the ONLY authorized input for the next research batch — no hypothesis may be generated
from a gap that is not documented here (ALPHA-01/ALPHA-04).

## Sources (immutable)

1. `LEGACY_RETRO_EXECUTION_RESULTS.json` + `LEGACY_FAILURE_DIAGNOSIS.json` — 30 retro
   validation cells by coarse regime (all FAILED or INSUFFICIENT_SAMPLE; zero VALIDATED).
2. R2 attribution ledger (`cycles/POC02_ATTRIBUTION.jsonl`) — per-candidate regime labels
   (coarse `LOW_VOLATILITY` label from the runtime classifier).
3. R2 telemetry bottleneck-by-regime windows (`POC02_TELEMETRY_*.json`).
4. Prior discovery batches: `volatility_structure` DISCOVERY_FAIL/REFUTED_BY_DEEPER_WINDOW,
   `cross_sectional` DISCOVERY_FAIL/REDUNDANT_WITH_MOMENTUM, `carry_funding` DISCOVERY_FAIL
   (deep study confirmed on 7,670 real rows, 2019-09-10→present).

## Canonical regime coverage table

| Regime (canonical coarse) | Observed market time (R2) | Legacy signals | Proposals | Selected | Paper opportunities | Known validation cells | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| LOW_VOLATILITY (any trend/structure) | ~14 cycle-minutes across 14 runs (3 assets × 5m windows) | momentum signals present every window | 5m: 2/run (LONG+SHORT echo); post-arbitration 1 direction/run | 30 candidate-selections | 4 paper opens (post-arm exactly-once) | 5m cells FAILED (cost-dominated) / INSUFFICIENT | **ACTIVITY_WITHOUT_EDGE** — activity exists but zero validated edge and thin observation |
| HIGH_VOLATILITY \| MIXED \| RANGING | not observed in R2 (too few windows) | none recorded | 0 | 0 | 0 | 1h cells FAILED (breakout/MR/momentum), INSUFFICIENT (trend/volatility) | **UNDER_COVERED** (runtime) + **ACTIVITY_WITHOUT_EDGE** (retro) |
| LOW_VOLATILITY \| MIXED \| RANGING | not observed in R2 | none recorded | 0 | 0 | 0 | 1h cells FAILED / INSUFFICIENT | **UNDER_COVERED** (runtime) + **ACTIVITY_WITHOUT_EDGE** (retro) |
| LOW_VOLATILITY \| MIXED \| TRENDING | not observed in R2 | none recorded | 0 | 0 | 0 | 15× 5m cells FAILED / INSUFFICIENT (largest retro cell population) | **UNDER_COVERED** (runtime) + **ACTIVITY_WITHOUT_EDGE** (retro) |
| MIXED (coarse 1h bucket) | not observed in R2 | none recorded | 0 | 0 | 0 | 1h FAILED / INSUFFICIENT | **UNDER_COVERED** (runtime) + **ACTIVITY_WITHOUT_EDGE** (retro) |
| CORRECTION / regime-transition (any vol) | not observable — runtime records coarse labels only | n/a | n/a | n/a | n/a | none — never validated | **INSUFFICIENT_OBSERVATION** — no validated cells AND no runtime regime granularity; evidence-backed GAP |

## Reading (honest)

- No canonical regime is `COVERED_WITH_EVIDENCE`. The best-described regimes are
  `ACTIVITY_WITHOUT_EDGE` (activity exists, no validated edge) — the legacy retro shows
  cost drag 0.0012/trade killing 5m cells — and `UNDER_COVERED` (runtime has barely
  observed them: 14 runs, single coarse label).
- The only regime with BOTH no validated cells AND no runtime observation granularity is
  regime-transition/correction: flagged `INSUFFICIENT_OBSERVATION` and it is the single
  largest evidence-backed structural gap (runtime cannot even see transitions today).
- `NO_SIGNAL` status: not assigned anywhere — the R2 composition DOES produce signals in
  every observed window (momentum echo); the funnel loss is downstream (risk/capacity), not signal absence.

## Constraints carried forward

- Zero VALIDATED legacy cells → no legacy-derived hypothesis may skip the full
  preregistered pipeline (F2) on the strength of legacy evidence.
- Any "gap" in HIGH_VOL/TRENDING regimes rests on retro cells that FAILED — hypotheses
  there must explain why the new mechanism is not the same failed mechanism
  (TRACK G failed-research memory is binding).
