# WP-STRAT-04 — Regime Performance Matrix

- RFC: RFC-STRAT-013
- SCOPE: context-keyed performance (strategy × asset × timeframe × regime), rolling windows.
- CURRENT STATE: `StrategyPerformance` keyed by (strategy, asset, regime, timeframe) but no windows.
- TARGET STATE: `ContextualPerformanceStore` (short/medium/long) + `regime_matrix`.
- IMPLEMENTATION: `src/trading_bot/strategy_lifecycle/performance.py`.
- TESTS: `test_performance.py`.
- RISKS: unit drift (bps vs usdt) → net_bps derived from notional.
- ACCEPTANCE: last-N windows, context isolation, peak-to-trough drawdown.
- EVIDENCE: test_performance.py.
- ROLLBACK: delete.
- STATUS: IMPLEMENTED.
