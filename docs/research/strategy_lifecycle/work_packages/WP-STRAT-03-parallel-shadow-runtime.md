# WP-STRAT-03 — Parallel Shadow Runtime

- RFC: RFC-STRAT-013 / RFC-STRAT-014
- SCOPE: evaluate many pods over one shared context; isolate shadow results.
- CURRENT STATE: single strategy selected per cycle.
- TARGET STATE: `ParallelShadowRuntime.evaluate_all` (deterministic order) +
  `guard_not_executable` barrier.
- IMPLEMENTATION: `src/trading_bot/strategy_lifecycle/pods.py`.
- TESTS: `test_pods.py`, `test_adversarial.py::test_shadow_result_cannot_reach_execution`.
- RISKS: shadow leakage into execution → structural guard.
- ACCEPTANCE: every result tagged SHADOW; guard raises on leak.
- EVIDENCE: pods + adversarial tests.
- ROLLBACK: delete.
- STATUS: IMPLEMENTED (simulation-level; not wired to the live PAPER loop).
