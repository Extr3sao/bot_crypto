# WP-STRAT-01 — StrategyRegistry contracts

- RFC: RFC-STRAT-013
- SCOPE: typed contracts for the dynamic plane.
- CURRENT STATE: `AdmissionStatus` only; no dynamic lifecycle vocabulary.
- TARGET STATE: `LifecycleState`, closed transition graph, `EVIDENCE_REQUIRED_EDGES`,
  `StrategyDescriptor`, `PerformanceCell`, `HealthReport`, `LifecycleDecision`,
  `PromotionRecord`, `StrategyEvent`, `PortfolioDecision`, `ExecutionMode`.
- IMPLEMENTATION: `src/trading_bot/strategy_lifecycle/contracts.py`.
- TESTS: `tests/unit/strategy_lifecycle/test_contracts.py`.
- RISKS: widening vocabulary could accidentally reach LIVE → import-time assertion.
- ACCEPTANCE: PAUSED→ACTIVE and CANDIDATE→ACTIVE refused; evidence edges gated.
- EVIDENCE: test_contracts.py (9 tests).
- ROLLBACK: delete package.
- STATUS: IMPLEMENTED.
