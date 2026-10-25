# RFC-OBS-015 — Strategy Ecosystem & Agent Observability Dashboard

Status: **Implemented (pending independent verification)**
Phase: WP-OBS-STRAT-01 · Type: OBSERVABILITY (no trading-behaviour change)

## CONTEXT

`Trading Agentic Portable` runs a PAPER runtime that already emits hash-chained
DecisionTrace, routing comparisons, performance cells, heartbeats and campaign
reports. The strategy lifecycle plane (`LEGACY` / `SHADOW` / `LIFECYCLE`) and a
set of shared decision-layer reviewer agents exist, but there is no single surface
that answers "what is happening and why" across strategies, agents, lifecycle,
routing, portfolio, risk and executions.

## PROBLEM

Answering operational questions today means reading JSONL by hand: which
strategies are working, which agent supervises each, why a strategy produces zero
trades, what LEGACY vs LIFECYCLE chose, what was rejected and why, where the
evidence is. There is no consolidated, evidence-linked, read-only view, and no
machine answer to whether strategies are governed by independent agents.

## GOALS

* One read-only console covering strategies, pods, agents, lifecycle, health,
  regime, signals, proposals, rejections, portfolio, risk, PAPER executions,
  performance, LEGACY-vs-LIFECYCLE, agent activity, campaigns, errors,
  DecisionTrace and evidence.
* A machine answer to the strategy↔agent governance question, from code not names.
* Show a truthful absence (`NOT_AVAILABLE`/`UNKNOWN`/`INSUFFICIENT_SAMPLE`) instead
  of fabricating `0`, and link important data to its evidence/run.

## NON-GOALS

* Any change to trading behaviour, thresholds, risk, sizing, leverage, portfolio
  limits, promotion or execution.
* Any mutating endpoint, any operator action from the UI, any auto-promotion.
* Introducing a heavyweight web stack when the repo already serves consoles with
  the standard library.
* Creating a per-strategy LLM agent just to make the topology look complete.

## DATA SOURCES

`config/strategy_admission.json`; `reports/autonomous-paper/<run_id>/{traces,
outcomes,routing_comparisons}.jsonl`, `performance.json`, `heartbeat.json`,
`PAPER_RUN.json`; `reports/paper-*/\{ANALYSIS.json,CAMPAIGN_CONFIG.md\}`; the agent
registry in code. Full mapping in `DASHBOARD_DATA_SOURCES.md`.

## READ MODEL

A projection layer (`trading_bot.observability`) turns those artifacts into
JSON-serialisable read models. It is derived, rebuildable and non-authoritative;
the dashboard never writes. A SQLite read model is deferred (volume does not
justify it) and can sit behind the same view methods later.

## API

GET-only, listed in `STRATEGY_ECOSYSTEM_DASHBOARD.md §8`. Routing is a pure
function (`resolve_api`) so it is testable without a socket.

## REALTIME

SSE (`/api/events/stream`), one-directional, bounded to 120 events per connection
so a slow client cannot pin a thread. WebSocket is not used.

## UI

A single self-contained page with the sections CONTROL ROOM, STRATEGIES, AGENTS,
LIFECYCLE, ROUTING, PORTFOLIO, RISK, EXECUTIONS, CAMPAIGNS, TRACES, SYSTEM; a
persistent top bar (environment, routing, campaign, market data, risk, runtime,
commit, freshness, READ_ONLY, `live_control=false`); strategy/trace drill-downs;
text labels on every state (never colour alone).

## FAILURE ISOLATION

Separate process; read-only file access; bounded SSE. Dashboard down / API down /
slow client / SSE disconnect / malformed telemetry cannot affect the runtime or
its authoritative evidence.

## SECURITY

Loopback-only bind; no credentials; no secrets displayed; every non-GET verb is
405.

## TESTS

`tests/unit/observability/` covers the read models, the topology answer, the
funnel aggregation, the routing matrix, risk/portfolio/execution/trace/campaign
projections, unknown/missing handling, the read-only guard (405 on
POST/PUT/PATCH/DELETE), the loopback guard, malformed-line isolation, SSE open/
close, and runtime-artifact immutability across a request cycle.

## ACCEPTANCE

ACC-OBS-01 … ACC-OBS-20 (see `STRATEGY_ECOSYSTEM_DASHBOARD.md`, data-sources doc,
and the verification plan). `FALSE_SUCCESS = 0` is a code invariant and is
reported as such.

## ROLLBACK

Additive and read-only: revert the commits (`feat(obs)` / `test(obs)` /
`docs(obs)`); no runtime or config file is touched, so there is nothing to
migrate. The dashboard process can be stopped at any time with no side effects.
