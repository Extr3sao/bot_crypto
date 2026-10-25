# Agent Topology Gap Analysis (WP-OBS-STRAT-01 §3/§45)

The topology audit answered **NO**: no `StrategyPod` is governed by an independent
agent (see [`STRATEGY_AGENT_TOPOLOGY.md`](STRATEGY_AGENT_TOPOLOGY.md)). Per §45
this document records the gap and the recommended action. **No strategy was
auto-converted into an agent.**

## Current architecture

```
DynamicStrategyEcosystem (deterministic: registry, performance, health,
                          lifecycle, portfolio, champion)
  └── strategies (24 canonical, deterministic family runtimes)
        └── NO per-strategy agent

Decision layer (shared, per decision packet)
  └── 5 reviewer agents: data-integrity, cost-economics, evidence-provenance,
      regime-alignment, risk-adversary
        scope: DECISION_LAYER_SHARED · tools: none · forbidden: execute/risk/portfolio
```

Everything that decides *what to trade* is deterministic and reproducible. The
only agents are structured reviewers of a decision packet.

## Potential benefit of adding per-strategy agents

* **Narrative / diagnosis** — an agent could explain, in natural language, why a
  specific strategy is degraded (regime mismatch, cost kill, sample size).
* **Research hypothesis generation** — an agent could propose the next experiment
  for a strategy that keeps failing.
* **Independent critique per strategy** — an adversarial reviewer dedicated to one
  strategy's evidence.

All three are **analysis/explanation** functions; none requires, or is permitted
to have, trading authority.

## Cost

| Dimension | Impact of 1 agent per strategy (×24) |
| --- | --- |
| Tokens | 24× the review surface per cycle; recurring, unbounded |
| Latency | unless asynchronous, a per-strategy review adds to every decision |
| Complexity | 24 independent states, memories and lifecycles to operate and observe |
| Redundancy | the 5 shared reviewers already cover the decision packet |
| Risk | more surfaces that could be mistaken for authority; more to audit |

## Independence and redundancy

The 5 shared reviewers are intentionally **shared**: they critique the *packet*,
which is the unit the runtime actually decides on. A per-strategy agent would
duplicate `regime-alignment`/`risk-adversary` for each strategy while adding 24
state stores, no new authority, and a large token bill — **no orthogonal
function**.

## Recommended action

**Do not add per-strategy agents now.** They would be cosmetic, not functional:

1. Keep the deterministic runtimes as the source of truth (`REAL_RUNTIME` first).
2. Keep the 5 shared reviewers as the only agents.
3. If diagnosis/explanation value is later demonstrated and bounded, add a
   **single optional** `StrategyAgent` capability that `OBSERVE`s / `ANALYZE`s /
   `CRITIQUE`s / `EXPLAIN`s / `GENERATE_RESEARCH_HYPOTHESIS` and is guaranteed
   the same `FORBIDDEN_AGENT_ACTIONS` — introduced by its own work package with
   evidence of benefit and a bounded token budget, not by this observability phase.
4. The dashboard already distinguishes `DEDICATED_AGENT` / `SHARED_AGENT` /
   `NO_AGENT`, so any future change will be visible immediately.
