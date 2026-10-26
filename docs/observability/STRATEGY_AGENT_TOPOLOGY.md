# Strategy ↔ Agent Topology (WP-OBS-STRAT-01 §2/§4/§44)

Phase: **WP-OBS-STRAT-01 — Strategy Ecosystem & Agent Observability Dashboard**
Type: **OBSERVABILITY** (no trading-behaviour change)
Authority order: `REAL_RUNTIME > EXECUTION_EVIDENCE > TESTS > SOURCE_CODE > ARCH/RFC > EXTERNAL_SOURCE > ASSUMPTION`

This document answers, **from code and registries rather than from naming**, the
mandatory question:

> Is each `StrategyPod` actually governed/supervised by an independent agent?

## §44 — Mandatory answer

```
ARE_STRATEGIES_GOVERNED_BY_INDEPENDENT_AGENTS: NO
```

```
DEDICATED_AGENT_STRATEGIES:
(empty — no strategy has a dedicated agent)

SHARED_AGENT_STRATEGIES:
(empty as a *per-strategy binding* — but the whole decision layer is reviewed by the
 5 SHARED reviewers below; they are not bound to any strategy)

NO_AGENT_STRATEGIES:
breakout@5m, breakout@15m, breakout@30m, breakout@1h,
ema_crossover@5m, ema_crossover@15m, ema_crossover@30m, ema_crossover@1h,
mean_reversion@5m, mean_reversion@15m, mean_reversion@30m, mean_reversion@1h,
momentum@5m, momentum@15m, momentum@30m, momentum@1h,
trend@5m, trend@15m, trend@30m, trend@1h,
volatility@5m, volatility@15m, volatility@30m, volatility@1h
(24 / 24 — the full canonical registry)
```

Counts: `DEDICATED_AGENT_COUNT = 0`, `SHARED_AGENT_STRATEGIES = 0`,
`NO_AGENT_COUNT = 24`.

The question is machine-answered by
[`src/trading_bot/observability/topology.py`](../../src/trading_bot/observability/topology.py)
(`build_agent_topology`) and surfaced by `GET /api/topology`.

## Why the answer is NO (evidence)

The audit covered the exact symbols the work package named:

| Audited surface | File | Empirical result |
| --- | --- | --- |
| `StrategyPod` | `src/trading_bot/strategy_lifecycle/pods.py` | A `StrategyDescriptor` **plus a deterministic runtime callable**. No agent, no LLM call, no message channel. A pod may not set sizing/leverage/risk keys (`ShadowLeakError`). |
| `StrategyRuntime` | `src/trading_bot/research/families/*_family.py` | Pure deterministic signal code (`MomentumFamily`, `BreakoutFamily`, …). No agent surface. |
| `StrategyAgent` | — | **Does not exist anywhere in the tree.** No class, module, or registry entry. |
| `AgentCapabilityRegistry` / `AgentRegistry` | `src/trading_bot/autonomous/agents.py` | 5 agents, all `scope = DECISION_LAYER_SHARED`. `tools` empty. |
| `MasterOrchestrator` | — | Only `strategy_lifecycle.ecosystem.DynamicStrategyEcosystem` (registry/performance/health/lifecycle/portfolio/champion). No agent orchestration. |
| `AgentRouter` | — | Does not exist. Routing is `strategy_lifecycle.runtime_bridge.LifecycleRoutingAdapter` (deterministic). |
| `agent_id` / `strategy_id` / `strategy_version` binding | whole tree | **No strategy↔agent binding exists.** Neither `StrategyPod` nor `TradeProposal` carries an `agent_id`; no registry maps a strategy to an agent. |
| `messages` / `tools` / `permissions` / `memory` | `autonomous/agents.py` | Agents emit `AgentMessage` (structured `ReviewType`) with empty `tools`; no independent per-strategy state or memory. |
| Runtime reachability of pods | repo-wide grep | `StrategyPod(...)` is instantiated **only in tests** (`tests/unit/strategy_lifecycle/*`). No runtime script/driver constructs pods. In the running shadow runtime `pod_id = NOT_CONSTRUCTED`, `runtime_reachability = LEDGER_ONLY`. |

### The five SHARED agents (not per-strategy)

They review a decision packet at the *decision layer* on behalf of the whole
runtime — never one strategy each:

| agent_id | role | scope | independent state | tools |
| --- | --- | --- | --- | --- |
| `data-integrity` | data quality of the packet | `DECISION_LAYER_SHARED` | no | none |
| `cost-economics` | cost feasibility | `DECISION_LAYER_SHARED` | no | none |
| `evidence-provenance` | provenance of claims | `DECISION_LAYER_SHARED` | no | none |
| `regime-alignment` | regime fit | `DECISION_LAYER_SHARED` | no | none |
| `risk-adversary` | adversarial risk review | `DECISION_LAYER_SHARED` | no | none |

`FORBIDDEN_AGENT_ACTIONS` (identical for every agent, enforced by the runtime):
`execute_order`, `modify_risk_limits`, `modify_accounting`, `modify_risk_engine`,
`escalate_permissions`, `modify_portfolio`.

## Matrix (per strategy)

The generated matrix (`GET /api/topology` → `entries[]`) carries one row per
canonical strategy:

```
Strategy          StrategyPod          StrategyRuntime                     Agent   Agent ID   Independent State   Independent Messages   Independent Evidence   Runtime Reachable   Current Status
breakout@5m       NOT_CONSTRUCTED      ...breakout_family.BreakoutFamily   NO_AGENT  (none)    n/a                 n/a                   admission_ledger      LEDGER_ONLY        NO_AGENT
ema_crossover@5m  NOT_CONSTRUCTED      ...ema_crossover_family...          NO_AGENT  (none)    n/a                 n/a                   admission_ledger      LEDGER_ONLY        NO_AGENT
momentum@5m       NOT_CONSTRUCTED      ...momentum_family.MomentumFamily   NO_AGENT  (none)    n/a                 n/a                   admission_ledger      LEDGER_ONLY        NO_AGENT
... (24 rows, all NO_AGENT)
```

`StrategyPod` is listed as `NOT_CONSTRUCTED` because the current PAPER shadow
runtime does not instantiate pods; the class exists and is unit-tested but is not
wired into the runner. The dashboard reports this honestly rather than implying a
pod is live.

## Topology diagram (resolved with evidence)

```
DynamicStrategyEcosystem (deterministic)         AgentRegistry (5 SHARED reviewers)
        │                                                    │
        ├── strategy breakout@5m       ── Runtime: BreakoutFamily   Agent: NONE
        │     ├── Runtime   (deterministic)
        │     ├── Health    (not persisted in this run → UNKNOWN)
        │     └── Agent?    → NO  (no binding exists)
        │
        ├── strategy ema_crossover@5m  ── Runtime: EmaCrossoverFamily Agent: NONE
        │     ├── Runtime   (deterministic)
        │     ├── Health    (UNKNOWN)
        │     └── Agent?    → NO
        │
        └── strategy mean_reversion@5m ── Runtime: MeanReversionFamily Agent: NONE
              ├── Runtime   (deterministic)
              ├── Health    (UNKNOWN)
              └── Agent?    → NO

        Decision layer (per decision packet, shared across all strategies):
              TradeProposal ──▶ [data-integrity, cost-economics, evidence-provenance,
                                  regime-alignment, risk-adversary] ──▶ decision
```

No `StrategyAgent` is created; none is planned here (see
[`AGENT_TOPOLOGY_GAP_ANALYSIS.md`](AGENT_TOPOLOGY_GAP_ANALYSIS.md)). Per
WP-OBS-STRAT-01 §3/§45 the task is to *document the real architecture*, not to
force `1 strategy = 1 LLM`.

## Where the runtime is reachable

The dashboard distinguishes three agent states
(`DEDICATED_AGENT` / `SHARED_AGENT` / `NO_AGENT`) and never labels a strategy as
`AGENT` merely because it has a pod. The Strategy detail view shows, e.g.:

```
ema_crossover@5m
  Strategy Runtime:  ...ema_crossover_family.EmaCrossoverFamily   (deterministic)
  Strategy Pod:      NOT_CONSTRUCTED
  Strategy Agent:    NO_AGENT
  Agent Type:        NO_AGENT
```
