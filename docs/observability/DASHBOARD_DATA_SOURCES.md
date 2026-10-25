# Dashboard Data Sources (WP-OBS-STRAT-01 §27)

Every value the dashboard shows comes from an **authoritative runtime artifact**,
never from the UI and never recomputed in the browser. This table is the
provenance contract: for each view, which file it reads and which field it maps.

## Authoritative sources

| Source | Path (relative to repo root) | Written by |
| --- | --- | --- |
| Admission registry (canonical strategies) | `config/strategy_admission.json` | offline admission process |
| DecisionTrace (hash-chained, append-only) | `reports/autonomous-paper/<run_id>/traces.jsonl` | `autonomous/trace.py` `DecisionTraceStore` |
| Realised outcomes | `reports/autonomous-paper/<run_id>/outcomes.jsonl` | runtime |
| Contextual performance cells | `reports/autonomous-paper/<run_id>/performance.json` | runtime |
| Routing comparisons | `reports/autonomous-paper/<run_id>/routing_comparisons.jsonl` | `autonomous/runtime.py` |
| Run summary | `reports/autonomous-paper/<run_id>/PAPER_RUN.json` | runtime |
| Heartbeat | `reports/autonomous-paper/<run_id>/heartbeat.json` | runtime |
| Campaign analysis | `reports/paper-<campaign>/ANALYSIS.json`, `CAMPAIGN_CONFIG.md` | campaign analysis |
| Agent registry | `trading_bot.autonomous.agents.default_agent_registry()` | code (deterministic) |

The **current run** is the newest run directory (by heartbeat / `PAPER_RUN` /
traces mtime) unless `--run-id` or `?run_id=` overrides it.

## View → source → field map

| View / field | Source | Field |
| --- | --- | --- |
| `system.runtime.state` | `PAPER_RUN.json` | `state` |
| `system.runtime.cycles` | `PAPER_RUN.json` | `cycles` |
| `system.runtime.runtime_failures` | `PAPER_RUN.json` | `totals.runtime_failures` |
| `system.routing_mode` | `routing_comparisons.jsonl` (first row) | presence of `lifecycle` ⇒ `SHADOW`, else `LEGACY` |
| `system.market_data_health` | `heartbeat.json` | `errors`, `assets`, `timeframe`, `storage_failures` |
| `system.freshness` | `heartbeat.json` | `timestamp_ms` vs now (`STALE_HEARTBEAT_SECONDS = 900`) |
| `system.config_hash` | `config/strategy_admission.json` | sha256 of the file |
| `system.commit` | `git rev-parse HEAD` | HEAD (cached) |
| `system.totals.signals` | `traces.jsonl` | Σ `strategies_considered[].emitted_alpha` |
| `system.totals.proposals` | `traces.jsonl` | count of traces whose `proposal.strategy_id` was considered |
| `system.totals.no_trade` | `traces.jsonl` | `decisions − order_created` |
| `system.totals.no_trade_kinds` | `traces.jsonl` | histogram of `no_trade_kind` |
| `system.false_success` | code invariant | always `0` (invariant, not a measurement) |
| `strategies[].lifecycle` | `traces.jsonl` | dominant `strategies_considered[].lifecycle_verdict` |
| `strategies[].agent` | `topology` | `NO_AGENT` (no strategy↔agent binding) |
| `strategies[].trades`, `expectancy_net_bps`, `profit_factor`, `drawdown_bps` | `performance.json` | per-`strategy_id` samples |
| `strategy_detail.performance.by_regime` | `performance.json` | samples with matching `strategy_id` + `regime` |
| `strategy_funnel.stages` | `traces.jsonl` | `strategies_considered[]` counters |
| `lifecycle.transitions` | lifecycle event log | **not persisted by this run ⇒ `NOT_AVAILABLE`** |
| `agents[].messages`, `review_types` | `traces.jsonl` | `agent_messages[].agent_id` / `review_type` |
| `routing.matrix`, `agreement_rate` | `routing_comparisons.jsonl` | `legacy.selected` vs `lifecycle.selected` |
| `risk.verdicts` | `traces.jsonl` | `risk.verdict` histogram |
| `portfolio.portfolio_rejected` | `routing_comparisons.jsonl` | `portfolio_rejected` |
| `executions[]` | `traces.jsonl` | traces with `order_created = true` |
| `traces[]` | `traces.jsonl` | list rows |
| `traces/{id}.timeline` | `traces.jsonl` | the trace's own blocks |
| `campaigns[]` | `ANALYSIS.json` | `agreement_rate`, `cycles_with_comparisons`, matrix |

## Freshness (§38)

Every view carries `freshness = {status, age_seconds, data_timestamp_ms}` derived
from the heartbeat. `FRESH` ≤ 900 s, else `STALE`; no heartbeat ⇒ `UNKNOWN`. The
dashboard never shows ancient data as current.

## Deliberately `NOT_AVAILABLE` today (honest gaps)

These are absent from the current run's persisted evidence, so the dashboard
reports them as unavailable rather than inventing a value:

* per-strategy `health` — no health store is persisted by the shadow run;
* per-strategy funnel stages after `PROPOSAL` (REGIME/HEALTH/PORTFOLIO/DECISION/
  RISK/EXECUTED) — they are **decision-level**, not per-strategy attributable;
* lifecycle `transitions` — the dynamic registry state is not persisted;
* portfolio `exposures` / `concentration` — not persisted;
* `open_risk`, `open_critical_defects` — not persisted.

Closing these gaps needs the runtime to persist the corresponding stores (a future
phase); the dashboard is ready to read them without an API change.
