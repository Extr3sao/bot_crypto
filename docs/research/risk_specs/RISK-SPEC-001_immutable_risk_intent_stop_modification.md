# RISK-SPEC-001 — Immutable Risk Intent / Stop Modification Audit

## risk_problem
Open-trade stop/invalidation can drift from the authorized plan if modified without a deterministic rule.

## source_claim
SRC-BOOK-001 pp.30-33 and exam pp.139-141 emphasizes respecting stop discipline; pp.151-154 records modifications and warns against rule-breaking.

## current_policy
Supplied architecture notes require deterministic Risk, but actual RiskManager/policy code was not supplied. `RUNTIME_UNVERIFIED`.

## proposed_invariant
At authorization persist `initial_stop`, `invalidation`, `risk_budget`, `strategy_version`. Any stop modification requires `rule_id`, timestamp, market_state, old_stop, new_stop and deterministic Risk validation. Unknown/manual narrative reason alone cannot mutate risk intent.

## quantitative_validation_needed
Validate stop execution/gap/slippage behavior and whether current runtime already enforces equal/stronger invariants.

## edge_cases
Gap through stop; partial fills; trailing stop; break-even rule; exchange rejection; corporate actions; stale market data; multi-leg trades.

## adversarial_tests
Move stop farther from market without approved rule; delete stop; submit stale timestamp; duplicate modification; agent tries to override deterministic rejection.

## paper_experiment
Shadow/paper trace only after implementation; compare intended vs actual stop transitions and false-rejection rate.

## governance_required
Risk remains deterministic; production changes require normal risk governance and independent verification.

## Adoption
ADOPT_P0 — invariant/spec only; no threshold copied from source.
