# WP-STRAT-09 — Champion/Challenger

- RFC: RFC-STRAT-014
- SCOPE: challenger vs champion comparison.
- CURRENT STATE: none.
- TARGET STATE: `ChampionChallenger.compare` → CHAMPION_RETAINED /
  PROMOTION_CANDIDATE / INSUFFICIENT_EVIDENCE; requires window wins + samples +
  edge + PF advantage; promotion candidate still crosses the RFC-STRAT-013 gate.
- IMPLEMENTATION: `src/trading_bot/strategy_lifecycle/champion.py`.
- TESTS: `test_champion.py`, `test_adversarial.py`.
- RISKS: single-window promotion → `required_window_wins`.
- ACCEPTANCE: one winning window never promotes; champion losing one window never demotes.
- EVIDENCE: test_champion.py.
- ROLLBACK: delete.
- STATUS: IMPLEMENTED.
