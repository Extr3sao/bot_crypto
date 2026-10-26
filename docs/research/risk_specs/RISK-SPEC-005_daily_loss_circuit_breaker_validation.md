# RISK-SPEC-005 — Daily Loss Circuit Breaker Validation

## risk_problem
External practitioner guidance identifies a real class of capital-preservation failure, but its numeric threshold is not project authority.

## source_claim
SRC-MANUAL-002 p.106: The source recommends a maximum daily loss band but explicitly acknowledges that percentage generalization is difficult.

## current_policy
UNKNOWN from supplied materials. Architecture states Risk must be deterministic, but runtime enforcement is not proven here.

## proposed_invariant
A daily-loss circuit breaker is a valid deterministic risk invariant candidate; the source percentage is not valid project calibration evidence.

## quantitative_validation_needed
HYPOTHESIS_TO_VALIDATE; source 1%-3% values quarantined

## edge_cases
Multiple strategies losing simultaneously; overnight/session boundaries; deposits/withdrawals; unrealized vs realized PnL; partial fills; stale portfolio state; restart/recovery; currency conversion; multi-asset correlation; strategy-specific expected loss clusters.

## adversarial_tests
Attempt threshold override from LLM/source; stale daily PnL; reset clock/timezone error; rapid repeated orders around gate; position remains open after halt; config exists but is not enforced on authorization path.

## paper_experiment
Only after implementation and independent verification. Shadow the gate against historical/paper decisions, measuring prevented loss, false halts and strategy opportunity cost.

## governance_required
Risk remains deterministic. Any production threshold requires normal Risk governance, historical evidence and independent verification.

## Adoption
ADOPT_P0 — invariant/audit only, not source percentage
