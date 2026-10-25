# RISK-SPEC-003 — Leverage / Margin Stress Contract

## risk_problem
Leverage multiplies PnL and can create margin/liquidation risk not visible from nominal trade direction alone.

## source_claim
SRC-BOOK-001 pp.129-130 shows symmetric magnification of gains/losses and cautions inexperienced use.

## current_policy
Supplied architecture requires deterministic leverage/sizing; actual runtime controls were not supplied.

## proposed_invariant
Every leveraged proposal must expose gross/net/notional leverage, margin requirement, liquidation buffer, worst-case gap stress and post-trade portfolio exposure before authorization. Deterministic Risk can veto/resize; LLM cannot set leverage freely.

## quantitative_validation_needed
Venue-specific margin models, liquidation behavior, gap/slippage stress and correlated portfolio shocks.

## edge_cases
Cross-margin, changing maintenance margin, funding, options nonlinear exposure, exchange auto-deleveraging, stale mark price.

## adversarial_tests
Manipulated notional, omitted derivative multiplier, stale margin table, sudden volatility/maintenance-margin increase.

## paper_experiment
Offline/paper stress only.

## governance_required
Critical Risk contract; independent verifier and human/policy gate for production limit changes.

## Adoption
ADOPT_P0 at invariant level.
