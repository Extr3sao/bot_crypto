# Trace architecture

`DecisionTraceEvent` is an append-only sidecar record. `TraceStore` is JSONL, idempotent by deterministic event identity, and has no imports from Risk, PaperBroker, strategy, or Shadow resolution. Instrumentation remains opt-in; no active runtime file was changed. A native run must emit trace events through adapters before it can claim trace completeness.
