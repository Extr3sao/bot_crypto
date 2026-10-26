# RISK-SPEC-002 — Exposure & Concentration Threshold Validation

## risk_problem
Concentration can cause portfolio-level drawdown/ruin even if individual trade logic has edge.

## source_claim
SRC-BOOK-001 pp.125-126 proposes 1-5-15 and intraday 1-15-45 rules.

## current_policy
Unknown from supplied runtime evidence. Architecture says deterministic portfolio/risk limits must exist.

## proposed_invariant
Portfolio/market/position exposure limits must be deterministic and versioned. The source percentages are stored only as `SOURCE_THRESHOLD` experiment arms, never defaults.

## quantitative_validation_needed
Historical portfolio simulation under same assets/costs/strategy mix; stress correlated losses, gaps, volatility spikes, liquidity and drawdown constraints. Compare current policy vs candidate caps.

## edge_cases
Highly correlated “different” assets; leveraged derivatives; cross-margin; short exposure; delta-equivalent exposure; concentration via common factor.

## adversarial_tests
Many small positions that evade per-position caps but breach factor/market exposure; stale prices; leverage hidden in derivatives.

## paper_experiment
Portfolio shadow simulation with source thresholds versus current deterministic policy and statistically motivated alternatives.

## governance_required
Any real limit change requires explicit Risk governance; no auto-promotion.

## Adoption
EXPERIMENT — source numbers not adopted.
