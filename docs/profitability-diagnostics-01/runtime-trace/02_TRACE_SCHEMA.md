# Trace schema

Schema version: `decision-trace-v1`.

Identity is `trace_id = hash(run_id, proposal_id)`. Events preserve cycle, proposal, asset, strategy, timeframe, stage, actor, decision, normalized and raw reason, evidence references, confidence, provenance, and event identity. Outcomes require separate provenance and cannot be written into a native decision event.
