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

---

## REFRESH — H3-GOVERNANCE-RECONCILIATION-AND-H5-SELECTION-01 (2026-09-10)

Evidence consumed: FAILED_RESEARCH_MEMORY #1–#11 (incl. H1 transition defense and
H3 BTC/ETH relative-value), H1_RESULT.json, H3_RESULT.json, COST_SENSITIVITY_AUDIT.json,
R2 attribution ledger (coarse labels only), legacy retro cells. No new backtest was run
for this refresh (performance-blind).

### Updated canonical regime coverage table (addendum)

| Regime (canonical coarse) | Discovery evidence (new) | Status (updated) |
| --- | --- | --- |
| LOW_VOLATILITY (any trend/structure) | unchanged from base report | **ACTIVITY_WITHOUT_EDGE** |
| HIGH_VOLATILITY \| MIXED \| RANGING | unchanged | **UNDER_COVERED** (runtime) + **ACTIVITY_WITHOUT_EDGE** (retro) |
| LOW_VOLATILITY \| MIXED \| TRENDING | unchanged | **UNDER_COVERED** + **ACTIVITY_WITHOUT_EDGE** |
| CORRECTION / regime-transition (any vol) | H1 (N=10,193): transition STATE alone carries zero gross edge (−0.003 R); 6.5 qualifying transitions/day are cost-dominated | **ACTIVITY_WITHOUT_EDGE** (was INSUFFICIENT_OBSERVATION — now discovered-and-refuted at 1h with frozen spec) |
| Cross-asset displacement (BTC↔ETH majors) | H3 (N=243): |z|≥2.5 trailing-z dislocations CONTINUE, not revert (gross PF 0.492); genuinely orthogonal (daily PnL corr 0.009/−0.035) but edge-less; "beta-neutral" label withdrawn (DEF-H3-NEUTRALITY-001) | **ACTIVITY_WITHOUT_EDGE** (new row — cross-asset family now discovered-and-refuted in this normalization) |
| Order-flow imbalance regimes (taker-flow extremes, high/low participation) | **no discovery ever run**; data authority PROVEN in frozen committed dataset (12-field klines incl. numberOfTrades + takerBuyBaseVolume, 58,633 rows BTC/ETH, 52,458 SOL, 2020-01→2026-09) | **INSUFFICIENT_OBSERVATION — largest evidence-backed remaining GAP (selected for H5)** |
| Session / time-of-day | unchanged; cost-blocked (memory #9) | **ACTIVITY_WITHOUT_EDGE / cost-blocked** |

### Honest reading (refresh)

- Two previously-open structural gaps are now **closed by refutation** (transition state,
  trailing-z relative value). The remaining largest gap with (a) no discovery ever run,
  (b) proven data authority in already-frozen committed files, and (c) an economic
  mechanism distinct from #1–#11, is **order-flow imbalance** (buyer/seller taker
  participation extremes and trade-count/flow-participation regimes).
- Failed-memory exclusions consumed (E1): legacy directional families (#1–#4),
  volatility_structure (#6), cross_sectional (#7), carry_funding (#8), session (#9),
  H1 transition-state defense (#10), H3 BTC/ETH trailing-z relative value (#11).
  The H5 candidate conditions on ORDER FLOW (who traded), a variable none of #1–#11 used.
- NO_SIGNAL: still not assigned anywhere — R2 continues to produce signals; funnel loss
  remains downstream of signal generation.
