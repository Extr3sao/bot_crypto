# WP-STRAT-05 — StrategyHealthMonitor

- RFC: RFC-STRAT-013
- SCOPE: deterministic degradation detection.
- CURRENT STATE: none.
- TARGET STATE: `StrategyHealthMonitor` emitting `HealthReport` with flags:
  expectancy decay, drawdown deterioration, profit-factor deterioration,
  hit-rate drift, signal-frequency drift, slippage, cost sensitivity, regime
  mismatch, loss clustering, inactivity, signal explosion, correlation increase.
- IMPLEMENTATION: `src/trading_bot/strategy_lifecycle/health.py`, policy `config.HealthPolicy`.
- TESTS: `test_health.py`.
- RISKS: thresholds are preregistered defaults, not optima → configurable.
- ACCEPTANCE: <min_samples ⇒ INSUFFICIENT_DATA (never HEALTHY).
- EVIDENCE: test_health.py.
- ROLLBACK: delete.
- STATUS: IMPLEMENTED.
