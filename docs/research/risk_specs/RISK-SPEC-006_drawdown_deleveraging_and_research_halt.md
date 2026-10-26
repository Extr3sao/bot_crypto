# RISK-SPEC-006 — Drawdown Deleveraging And Research Halt

## risk_problem
External practitioner guidance identifies a real class of capital-preservation failure, but its numeric threshold is not project authority.

## source_claim
SRC-MANUAL-002 pp.108-113: The source recommends measuring drawdown, diagnosing abnormal losing runs, reducing exposure and stopping to investigate when necessary.

## current_policy
UNKNOWN from supplied materials. Architecture states Risk must be deterministic, but runtime enforcement is not proven here.

## proposed_invariant
Define deterministic drawdown state + evidence-driven escalation from normal -> warning -> reduced-risk -> research halt. Thresholds must come from portfolio policy and empirical distribution, not the book.

## quantitative_validation_needed
Requires historical drawdown distribution, strategy/portfolio decomposition, recovery math, cost/slippage and false-halt analysis

## edge_cases
Multiple strategies losing simultaneously; overnight/session boundaries; deposits/withdrawals; unrealized vs realized PnL; partial fills; stale portfolio state; restart/recovery; currency conversion; multi-asset correlation; strategy-specific expected loss clusters.

## adversarial_tests
Attempt threshold override from LLM/source; stale daily PnL; reset clock/timezone error; rapid repeated orders around gate; position remains open after halt; config exists but is not enforced on authorization path.

## paper_experiment
Only after implementation and independent verification. Shadow the gate against historical/paper decisions, measuring prevented loss, false halts and strategy opportunity cost.

## governance_required
Risk remains deterministic. Any production threshold requires normal Risk governance, historical evidence and independent verification.

## Adoption
ADOPT_P1
