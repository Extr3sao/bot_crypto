# Design

`scripts/profitability_diagnostics/run.py` reads only persisted JSON/JSONL campaign artifacts, derives a canonical funnel and normalized rejection taxonomy, snapshots every protected input digest before and after analysis, and writes reports only below `docs/profitability-diagnostics-01/` and `reports/profitability-diagnostics-01/`.

No production module is imported and no broker, risk engine, resolver, or execution ledger is called. Missing event-level traces remain `UNKNOWN`; unresolved Shadow outcomes remain `INSUFFICIENT_SAMPLE`. The tool intentionally does not replay or calculate new market outcomes.

The runtime map is evidence-based: the R2 launch script and campaign state are runtime authority; MA validation/smoke reports are test evidence. Multi-agent components are classified as reachable only where the launch composition imports or calls them.

Failure handling: malformed inputs produce an explicit diagnostic error rather than a partial economic conclusion. Reports contain source paths and digest snapshots.

Validation: fixture-driven unit tests cover reason normalization, funnel counting, deterministic serialization, and protected-state hash equality (AC-002–AC-004).
