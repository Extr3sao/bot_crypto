# RISK-SPEC-004 — Hedging / Basis-Risk Contract

## risk_problem
An “opposite” derivative position is not necessarily a perfect hedge due to basis, beta, sizing, funding and execution differences.

## source_claim
SRC-BOOK-001 pp.128-129 presents an opposite derivative as offsetting the cash portfolio.

## current_policy
No supplied runtime hedging module evidence.

## proposed_invariant
A hedge proposal must calculate hedge instrument mapping, hedge ratio, residual delta/beta, basis risk, contract multiplier, expiry/roll, liquidity, fees/funding and stress residual PnL. “HEDGED” is invalid if residual-risk evidence is missing.

## quantitative_validation_needed
Historical basis/correlation stability, hedge error distribution, transaction/roll costs and stress scenarios.

## edge_cases
Basis blowout, market closure mismatch, dividend/corporate action, contract expiry, partial fills, short restrictions.

## adversarial_tests
1:1 nominal hedge with mismatched beta; stale hedge ratio; missing funding; gap in one leg only.

## paper_experiment
Shadow hedge effectiveness vs unhedged baseline and beta-adjusted alternative.

## governance_required
Portfolio/Risk deterministic approval; no agent can label a position riskless.

## Adoption
ADOPT_P1 as a safety specification; reject “perfect hedge” claim as-is.
