# WP-STRAT-02 — StrategyPod

- RFC: RFC-STRAT-013
- SCOPE: the pod contract (runtime + metadata + evaluation + evidence).
- CURRENT STATE: families are called directly by the runtime; no pod boundary.
- TARGET STATE: `StrategyPod` (deterministic runtime callable) + `PodSignal` +
  `PodResult`; pods never size/leverage/execute.
- IMPLEMENTATION: `src/trading_bot/strategy_lifecycle/pods.py`.
- TESTS: `tests/unit/strategy_lifecycle/test_pods.py`.
- RISKS: a pod could try to set sizing/leverage → `FORBIDDEN_ADVISORY_KEYS`.
- ACCEPTANCE: runtime errors are non-emissions; wrong return type refused.
- EVIDENCE: test_pods.py.
- ROLLBACK: delete pods.py.
- STATUS: IMPLEMENTED.
