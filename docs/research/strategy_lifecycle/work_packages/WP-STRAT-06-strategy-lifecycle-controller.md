# WP-STRAT-06 — StrategyLifecycleController

- RFC: RFC-STRAT-013
- SCOPE: deterministic promotion/demotion/throttle/pause/recover/retire.
- CURRENT STATE: no automatic lifecycle.
- TARGET STATE: `StrategyLifecycleController` (no side effects) producing
  `LifecycleDecision`; gates on samples, expectancy, PF, drawdown, stability,
  regime samples, cost-adjusted positivity, independent verification.
- IMPLEMENTATION: `src/trading_bot/strategy_lifecycle/lifecycle.py`, `config.LifecyclePolicy`.
- TESTS: `test_lifecycle.py`, `test_adversarial.py`.
- RISKS: over-promotion → sample/stability/regime gates; advisory proposals ignored.
- ACCEPTANCE: 5 winning trades can never activate; PAUSED never jumps to ACTIVE.
- EVIDENCE: test_lifecycle.py.
- ROLLBACK: delete.
- STATUS: IMPLEMENTED (GATED behind DEF-RISK-EXPOSURE-001 fix, now done).
