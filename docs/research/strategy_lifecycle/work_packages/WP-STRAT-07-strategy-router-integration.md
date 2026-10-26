# WP-STRAT-07 — StrategyRouter Integration

- RFC: RFC-STRAT-013
- SCOPE: lifecycle-aware eligibility selection.
- CURRENT STATE: `StrategyRouter.route` returns a single best strategy.
- TARGET STATE: `select_eligible_strategies(...) -> RouterSelection` with per-strategy
  verdicts (SELECTED/REJECTED/NOT_APPLICABLE/PAUSED/DEGRADED/THROTTLED/
  INSUFFICIENT_EVIDENCE/REGIME_MISMATCH/RISK_CONFLICT/PORTFOLIO_CONFLICT).
- IMPLEMENTATION: additive method on `src/trading_bot/research/strategy_router.py`.
- TESTS: `test_router_integration.py`, `test_adversarial.py`.
- RISKS: `route()` behaviour change → none (additive).
- ACCEPTANCE: multiple eligible at once; every refusal names a reason.
- EVIDENCE: test_router_integration.py.
- ROLLBACK: remove the method.
- STATUS: IMPLEMENTED (reachable; not yet called by the hot runtime loop — see
  INDEPENDENT_VERIFICATION_PLAN).
