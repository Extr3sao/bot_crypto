# WP-STRAT-10 — DecisionTrace + Replay + Evidence

- RFC: RFC-STRAT-013
- SCOPE: observability, provenance, replay, evidence for the dynamic plane.
- CURRENT STATE: `DecisionTrace.replay(run_id)` exists for the runtime; the dynamic
  plane has no trace.
- TARGET STATE: registry history + append-only events + `snapshot()` provide a
  replayable record of every state change with policy version and metrics;
  observability reports written under `reports/strategy-lifecycle/`.
- IMPLEMENTATION: `registry.py` (history/events), `ecosystem.py` (snapshot).
- TESTS: `test_registry.py`.
- RISKS: evidence without provenance → every decision carries policy_version,
  metrics_snapshot and evidence tuple.
- ACCEPTANCE: every transition traceable to reason codes + metrics.
- EVIDENCE: test_registry.py, RUN_REPORT artifacts.
- ROLLBACK: delete.
- STATUS: IMPLEMENTED (dynamic-plane trace; hot runtime DecisionTrace unchanged).
