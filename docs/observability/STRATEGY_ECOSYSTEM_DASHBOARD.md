# Strategy Ecosystem & Agent Observability Dashboard (WP-OBS-STRAT-01)

Phase: **WP-OBS-STRAT-01**. Type: **OBSERVABILITY — no trading-behaviour change.**

The dashboard is a **READ_ONLY** console that answers, from the runtime's own
authoritative artifacts, the questions in the work package's closing rule: which
strategies are working, which agent supervises each one, which are active/shadow/
degraded, why a strategy does not operate, the current regime, what LEGACY vs
LIFECYCLE would choose, which proposals were rejected and why, what Portfolio and
Risk did, what executed, what performance each strategy has, and where the
evidence is.

Verdict for this phase is not assigned here: see
[`INDEPENDENT_VERIFICATION_PLAN.md`](INDEPENDENT_VERIFICATION_PLAN.md). This
document describes what was built; it does not certify it.

## §5 — Architecture (one direction only)

```
Trading Runtime (AutonomousPaperRuntime)
      ↓  writes
Append-only Events / Stores / DecisionTrace (JSONL, heartbeat, PAPER_RUN, performance)
      ↓  reads
Observability Projection Layer   src/trading_bot/observability/
      ↓
Read-only API                    scripts/strategy_ecosystem_dashboard.py
      ↓
Dashboard                        src/trading_bot/observability/static/index.html
```

There is **no** path from the dashboard back into the trading runtime. The server
process does not import any mutating runtime surface; it imports only
`trading_bot.observability`.

## §6 — Observability projection layer

`src/trading_bot/observability/ecosystem.py` exposes
`StrategyEcosystemObservatory` with these read models:

| View | Method | Rendered by |
| --- | --- | --- |
| `SystemHealthView` | `system_view` | CONTROL ROOM, SYSTEM |
| `StrategyStatusView` | `strategies_view` | STRATEGIES |
| `StrategyDetailView` | `strategy_detail` | strategy drill-down |
| `StrategyFunnelView` | `strategy_funnel` | strategy drill-down FUNNEL |
| `StrategyLifecycleView` | `lifecycle_view` | LIFECYCLE |
| `StrategyAgentView` | `agents_view` / `agent_activity` | AGENTS |
| `RoutingComparisonView` | `routing_view` | ROUTING |
| `RiskView` | `risk_view` | RISK |
| `PortfolioView` | `portfolio_view` | PORTFOLIO |
| `ExecutionView` | `executions_view` | EXECUTIONS |
| `DecisionTraceView` | `traces_view` / `trace_detail` | TRACES |
| `CampaignView` | `campaigns_view` | CAMPAIGNS |
| `AgentTopologyReport` | `topology` | SYSTEM, STRATEGIES |

Domain models are **not** modified to fit the UI; the projection adapts the
runtime's JSON to read models.

### Honest-missing rule (ACC-OBS-19, §9)

The projection never fabricates a value. A datum that is absent is
`NOT_AVAILABLE`; a state that cannot be established is `UNKNOWN`; a sample below
`MIN_SAMPLES = 5` is `INSUFFICIENT_SAMPLE`; a run with no artifacts yields
`INSUFFICIENT_DATA`. `0` is only ever reported when the authoritative source says
`0`. There is **no silent demo fallback** in normal runtime.

## §7 — Technology choice (audited, then reused)

The repository has **no web framework** installed (`fastapi`, `uvicorn`, `flask`,
`starlette`, `sse_starlette` are all absent; `aiohttp`/`pydantic`/`jinja2` are
present but unused by the consoles). The existing consoles
(`src/trading_bot/app.py`, `scripts/paper_lab_dashboard.py`) are **stdlib
`http.server`** services that serve a single self-contained HTML page.

Because the precedent exists and a read-only observability surface needs no build
step or package install, this dashboard reuses that pattern: **stdlib
`http.server` + one HTML page**. No FastAPI/React/Vite/TypeScript was introduced —
no heavy infrastructure for a read-only console.

Real-time updates use **SSE** (`/api/events/stream`), since the flow is
one-directional server→client. WebSocket is not used (no bidirectional need).

## §8 — Read-only API (GET only)

| Endpoint | Returns |
| --- | --- |
| `GET /api/system` | system health + control policy |
| `GET /api/topology` | the strategy↔agent matrix + governance answer |
| `GET /api/runs` | all runs, current run |
| `GET /api/strategies` | strategy ecosystem table |
| `GET /api/strategies/{id}` | identity + state + performance + funnel + evidence |
| `GET /api/strategies/{id}/performance` | performance windows (incl. by regime) |
| `GET /api/strategies/{id}/funnel` | the §13 funnel |
| `GET /api/strategies/{id}/lifecycle` | state block |
| `GET /api/strategies/{id}/evidence` | source / run / trace file |
| `GET /api/agents` | the 5 shared reviewers + governance |
| `GET /api/agents/{id}` | one agent |
| `GET /api/agents/{id}/activity` · `/messages` | structured messages (§17) |
| `GET /api/lifecycle` | lifecycle histogram + transitions |
| `GET /api/routing/comparisons` | LEGACY vs LIFECYCLE (§18) |
| `GET /api/portfolio` | portfolio arbitration (§21) |
| `GET /api/risk` | risk engine (§20) |
| `GET /api/executions` | PAPER executions (§22) |
| `GET /api/traces` | DecisionTrace list |
| `GET /api/traces/{decision_id}` | DecisionTrace timeline (§23) |
| `GET /api/campaigns` | campaigns (§24) |
| `GET /api/snapshot` | all views in one payload |
| `GET /api/events/stream` | SSE pulse (bounded, 120 events) |
| `GET /healthz` | liveness |

Every non-GET verb returns **405** with `{"error":"this dashboard is read-only"}`.
The routing is a **pure function** (`resolve_api`) so it is testable without a
socket.

## §9–§27 — Views

* **CONTROL ROOM** — runtime state, routing mode, campaign, market-data health,
  risk engine, strategies total, decisions, agents, guardrails (`FALSE_SUCCESS`,
  open critical defects, `read_only`, `live_control`). Missing data shows
  `UNKNOWN`/`NOT_AVAILABLE`, never `0`.
* **STRATEGIES** — one row per canonical strategy with family, timeframe,
  admission status, lifecycle, health, agent class, signals, proposals, trades and
  performance. Click a row for the detail.
* **AGENTS** — the 5 shared decision-layer reviewers, their scope, status,
  message counts, review-type histogram, forbidden actions, and the governance
  answer.
* **LIFECYCLE** — histogram over `DISCOVERED…RETIRED`, the admission-registry
  histogram, and transitions (honestly `NOT_AVAILABLE` when the run does not
  persist a lifecycle event log).
* **ROUTING** — agreement rate, the 2×2 router-selection matrix, rejections by
  reason, and the per-asset comparison table.
* **PORTFOLIO** — arbitration events, portfolio rejections, exposure/concentration
  (`NOT_AVAILABLE` when not persisted).
* **RISK** — deterministic risk engine, verdict histogram, approved/vetoed, open
  risk, config source. Makes explicit that `RISK != AGENT`.
* **EXECUTIONS** — PAPER executions with the decision link (§22).
* **CAMPAIGNS** — campaign id, mode/commit/config, agreement rate, matrix.
* **TRACES** — DecisionTrace list; click a row for the §23 timeline
  (MarketContext → AssetContext → Strategies → Proposal → AgentReviews → Decision
  → Risk → Execution).
* **SYSTEM** — the global top bar, agent governance, and the read-only controls.

Every panel shows its run/campaign context and freshness; the footer shows the
last-updated timestamp.

## §28/§29 — Current state + history, read model

The projection reads the run's authoritative JSONL directly (DecisionTrace,
routing comparisons, performance). For this runtime's data volume that is fast
enough; the observatory caches per-run reads for the process lifetime. A
rebuildable SQLite `ObservabilityReadModel` is **not** introduced here because the
retention and volume do not justify it — the projection is already derived,
rebuildable and non-authoritative. If a future phase needs sub-second history over
many runs, the read model can sit behind the same view methods without changing
the API.

## §30/§31 — Performance and security

* The dashboard runs in a **separate process** from the trading runtime; no
  synchronous dashboard work happens in any hot loop. A dashboard failure cannot
  stop PAPER trading as long as authoritative evidence keeps being written.
* The SSE stream is **bounded** (120 events, then closes) so a slow or dangling
  client cannot pin a thread forever; a broken pipe is not an error.
* The server binds **loopback only** (`resolve_host` refuses anything but
  `127.0.0.1`/`::1`/`localhost`). No secret or credential is read or shown.

## Files

| File | Role |
| --- | --- |
| `src/trading_bot/observability/ecosystem.py` | projection layer / read models |
| `src/trading_bot/observability/topology.py` | strategy↔agent audit |
| `src/trading_bot/observability/static/index.html` | dashboard page |
| `scripts/strategy_ecosystem_dashboard.py` | read-only stdlib server + `resolve_api` |
| `tests/unit/observability/` | §32–§34 tests |
