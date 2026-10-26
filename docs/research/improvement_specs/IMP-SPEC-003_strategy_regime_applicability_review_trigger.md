# IMP-SPEC-003 — Strategy Regime Applicability & Review Trigger

## Source
SRC-BOOK-001 printed pp.24-25, 97-125; project VNext references Regime/Strategy specialists.

## Source Claim
Trend-following tools are presented as inappropriate in lateral markets, while a separate range method is proposed for lateral conditions.

## Problem
A strategy can be valid overall but unsuitable in the current regime.

## Current Runtime
Architecture-level Strategy/Regime concepts exist in supplied notes; runtime registry/router evidence not supplied.

## Gap
Need verified mapping between validated strategy-regime performance and runtime selection/rejection.

## Proposed Pattern
Strategy applicability contract: `SELECTED / REJECTED / NOT_APPLICABLE`, driven by causal regime state plus validated StrategyPerformance by regime. Degradation creates a research-review flag/quarantine, never auto-optimization to production.

## Plane
STRATEGY_ROUTER / STRATEGY_REGISTRY / OBSERVABILITY

## Deterministic / Agentic
Selection constraints deterministic where possible; agent can propose regime hypothesis but cannot bypass validated applicability/risk gates.

## Measurable Hypothesis
Regime gating improves net OOS risk-adjusted performance or reduces strategy-specific failure rate versus ungated baseline.

## Requirements
- REQ-REG-001: PIT-safe regime label with timestamp.
- REQ-REG-002: Performance stored by strategy/version/regime.
- REQ-REG-003: Router explains selected/rejected/not-applicable.
- REQ-REG-004: Review trigger cannot auto-modify production parameters.

## Acceptance Criteria
- ACC-REG-001: stale/future regime data blocks selection.
- ACC-REG-002: unsupported regime -> NOT_APPLICABLE or NO_TRADE.
- ACC-REG-003: trigger creates research task/evidence, not live change.

## Architecture Impact
Fits existing VNext strategy/regime direction; RFC only if registry/router persistent contract does not already exist.

## Runtime Reachability
Unverified.

## Failure Modes
Regime look-ahead, overfitted labels, too-frequent regime switching, hidden fallback.

## Security / Safety
No bypass of deterministic Risk.

## Tests
UNIT / CONTRACT / INTEGRATION / PIT / ADVERSARIAL / OOS.

## Metrics
regime-gated vs ungated PnL/Sharpe/DD/expectancy; turnover; no-trade quality; misclassification impact.

## Rollback
Disable regime gating via versioned config and fall back to previously certified router behavior.

## Evidence Required
Same-data controlled A/B + OOS + independent verification.

## Adoption
ADOPT_P1
