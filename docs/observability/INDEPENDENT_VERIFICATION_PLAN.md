# Independent Verification Plan (WP-OBS-STRAT-01 §48)

`BUILDER != VERIFIER`. The builder does **not** declare `CERTIFIED`/`READY`/
`PRODUCTION_READY`. This is the plan an independent verifier executes to move the
phase from `DASHBOARD_IMPLEMENTED_PENDING_VERIFICATION` to
`INDEPENDENTLY_VERIFIED` / `VERIFIED_WITH_DEFECTS` / `VERIFICATION_FAILED`.

Each check states a **falsifiable** test and the evidence to capture. The verifier
must reproduce from a clean checkout of the phase's `END_SHA`.

## 1. Data authenticity

* Point the observatory at `reports/autonomous-paper/<run_id>` and confirm
  `GET /api/system` `run_id`, `state`, `cycles` equal `PAPER_RUN.json`, and
  `config_hash` equals `sha256(config/strategy_admission.json)`.
* Corrupt one line of `traces.jsonl`; confirm the view still loads and the
  malformed line is skipped (no crash, no silent value).
* Confirm no view returns a value that is absent from its source
  (spot-check `signals`, `proposals`, routing matrix against the files).

## 2. Strategy-agent topology

* Independently grep the tree for `StrategyAgent`, `agent_id` bindings, and any
  strategy↔agent map; confirm none exists.
* Confirm `GET /api/topology` returns
  `are_strategies_governed_by_independent_agents = "NO"`, `dedicated_agent_count =
  0`, `no_agent_count = 24`, and that the 5 shared agents are
  `DECISION_LAYER_SHARED`.
* Confirm the STRATEGIES view never labels a strategy as having an agent.

## 3. Read-only guarantee

* Issue `POST`/`PUT`/`PATCH`/`DELETE` to every `/api/*` path; expect **405** for
  all.
* Inspect `resolve_api` and the module imports; confirm the server imports only
  `trading_bot.observability` and never a mutating runtime surface.
* Confirm no endpoint, query parameter or header can start/stop/promote/execute.

## 4. Runtime isolation

* Snapshot `sha256` of every file under `reports/` before and after a full request
  cycle (including SSE); expect identical.
* With the dashboard stopped, confirm a PAPER run proceeds normally (or that the
  run artifacts continue to be written).
* Open an SSE connection and abandon it; confirm the server thread is released and
  the connection is bounded (120 events).

## 5. Event accuracy

* For an arbitrary `decision_id`, compare `GET /api/traces/{id}` to the raw trace
  line: `trace_hash`, `prev_hash`, `mode`, `no_trade_kind`, `regime` must match
  exactly. Verify the hash chain of `traces.jsonl` independently.

## 6. Funnel accuracy

* Independently recompute `SIGNALS`, `PROPOSAL`, `ROUTER_SELECTED` and
  `rejected_by_router` for one strategy from `traces.jsonl` and compare to
  `GET /api/strategies/{id}/funnel`.
* Confirm later stages are `NOT_AVAILABLE` (not `0`) and that the API documents
  them as decision-level.

## 7. Risk accuracy

* Recompute the `risk.verdict` histogram from `traces.jsonl`; compare to
  `GET /api/risk`.
* Confirm the view states the engine is deterministic and independent of agents.

## 8. Decision-trace accuracy

* Confirm the timeline stages and their details match the trace's own blocks
  (MarketContext, AssetContext, Strategies, Proposal, AgentReviews, Decision,
  Risk, Execution).

## 9. Freshness

* Set the heartbeat older/newer than 900 s and confirm `FRESH`/`STALE`; with no
  heartbeat confirm `UNKNOWN`.
* Confirm no view presents stale data as current.

## 10. No demo contamination

* Confirm the projection has no demo/fixture fallback in the runtime path (grep
  for hardcoded sample data; the tests use synthetic trees under `tmp_path`, which
  never execute at runtime).
* Confirm missing data yields `NOT_AVAILABLE`/`UNKNOWN`/`INSUFFICIENT_SAMPLE`, not
  an invented number.

## 11. Quality gates

* `pytest` (baseline + `tests/unit/observability/`), `ruff check .`,
  `mypy . --exclude "reports"` — all green, no pre-existing failures hidden.

## Required verdict format

```
INDEPENDENT_VERIFICATION_STATUS: INDEPENDENTLY_VERIFIED | VERIFIED_WITH_DEFECTS | VERIFICATION_FAILED
CAMPAIGN_VERDICT: SHADOW_EVIDENCE_ACCUMULATING | ...
DEFECTS_FOUND: ...
FALSE_SUCCESS: 0
```
