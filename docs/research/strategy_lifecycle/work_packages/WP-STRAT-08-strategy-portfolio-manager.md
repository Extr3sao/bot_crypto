# WP-STRAT-08 — StrategyPortfolioManager

- RFC: RFC-STRAT-014
- SCOPE: correlated/overlapping proposal arbitration.
- CURRENT STATE: none (paper portfolio modules are ORPHAN).
- TARGET STATE: `StrategyPortfolioManager.arbitrate` over correlation, per-asset
  and total exposure, same-direction concentration; emits `PortfolioDecision`.
- IMPLEMENTATION: `src/trading_bot/strategy_lifecycle/portfolio.py`.
- TESTS: `test_portfolio.py`, `test_adversarial.py`.
- RISKS: must only REDUCE exposure, never widen → budget clamps mirror risk policy.
- ACCEPTANCE: three correlated BTC buys capped; merged exposure reported.
- EVIDENCE: test_portfolio.py.
- ROLLBACK: delete.
- STATUS: IMPLEMENTED.
