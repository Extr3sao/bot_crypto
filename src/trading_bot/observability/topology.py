"""Strategy ↔ agent topology audit (WP-OBS-STRAT-01 §2/§3/§4/§16/§44).

Answers, from the code and the registries — never from naming — the question:

    is each StrategyPod actually governed/supervised by an independent agent?

The empirical answer for this runtime is **NO**, and the reason is structural:

* a ``StrategyPod`` (``trading_bot.strategy_lifecycle.pods``) is a
  ``StrategyDescriptor`` plus a **deterministic runtime callable**. It has no
  agent, no LLM call and no message channel;
* the only agents in the system are the five **shared** decision-packet
  reviewers in ``trading_bot.autonomous.agents`` (data-integrity,
  cost-economics, evidence-provenance, regime-alignment, risk-adversary). They
  review a ``TradeProposal``/context at the *decision layer*, on behalf of the
  whole runtime, not one strategy each;
* no strategy↔agent binding exists anywhere in the registries.

This module records that honestly and refuses to invent a per-strategy agent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from trading_bot.autonomous.agents import FORBIDDEN_AGENT_ACTIONS

__all__ = [
    "DEDICATED_AGENT",
    "FORBIDDEN_AGENT_ACTIONS",
    "NO_AGENT",
    "SHARED_AGENT",
    "AgentTopologyEntry",
    "AgentTopologyReport",
    "build_agent_topology",
    "family_runtime_implementation",
]

DEDICATED_AGENT: Final[str] = "DEDICATED_AGENT"
SHARED_AGENT: Final[str] = "SHARED_AGENT"
NO_AGENT: Final[str] = "NO_AGENT"

#: family -> the deterministic runtime that implements it (module + class).
_FAMILY_RUNTIME: Final[dict[str, str]] = {
    "breakout": "trading_bot.research.families.breakout_family.BreakoutFamily",
    "ema_crossover": "trading_bot.research.families.ema_crossover_family.EmaCrossoverFamily",
    "mean_reversion": "trading_bot.research.families.mean_reversion_family.MeanReversionFamily",
    "momentum": "trading_bot.research.families.momentum_family.MomentumFamily",
    "trend": "trading_bot.research.families.trend_family.TrendFamily",
    "volatility": "trading_bot.research.families.volatility_family.VolatilityFamily",
}


def family_runtime_implementation(family: str) -> str:
    """The deterministic runtime implementation for a family, or ``UNKNOWN``."""
    return _FAMILY_RUNTIME.get(family, "UNKNOWN")


@dataclass(frozen=True, slots=True)
class AgentTopologyEntry:
    """One strategy's place in the agent topology (§4)."""

    strategy_id: str
    strategy_version: str
    family: str
    pod_id: str
    runtime_implementation: str
    agent_id: str | None
    agent_type: str  # DEDICATED_AGENT / SHARED_AGENT / NO_AGENT
    classification: str  # the governance classification used by the summary
    capabilities: tuple[str, ...]
    permissions: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    state_ownership: str
    memory_ownership: str
    runtime_reachability: str
    message_channels: tuple[str, ...]
    evidence_path: str
    shared_agent_ids: tuple[str, ...] = ()
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "family": self.family,
            "pod_id": self.pod_id,
            "runtime_implementation": self.runtime_implementation,
            "agent_id": self.agent_id,
            "agent_type": self.agent_type,
            "classification": self.classification,
            "capabilities": list(self.capabilities),
            "permissions": list(self.permissions),
            "forbidden_actions": list(self.forbidden_actions),
            "state_ownership": self.state_ownership,
            "memory_ownership": self.memory_ownership,
            "runtime_reachability": self.runtime_reachability,
            "message_channels": list(self.message_channels),
            "evidence_path": self.evidence_path,
            "shared_agent_ids": list(self.shared_agent_ids),
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class AgentTopologyReport:
    """The whole topology plus the honest governance answer (§44)."""

    are_strategies_governed_by_independent_agents: str  # YES / PARTIAL / NO
    dedicated_agent_strategies: tuple[str, ...]
    shared_agent_strategies: tuple[str, ...]
    no_agent_strategies: tuple[str, ...]
    shared_agents: tuple[dict[str, Any], ...]
    entries: tuple[AgentTopologyEntry, ...]
    pod_count: int
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "are_strategies_governed_by_independent_agents": self.are_strategies_governed_by_independent_agents,
            "dedicated_agent_strategies": list(self.dedicated_agent_strategies),
            "shared_agent_strategies": list(self.shared_agent_strategies),
            "no_agent_strategies": list(self.no_agent_strategies),
            "dedicated_agent_count": len(self.dedicated_agent_strategies),
            "shared_agent_count": len(self.shared_agent_strategies),
            "no_agent_count": len(self.no_agent_strategies),
            "pod_count": self.pod_count,
            "shared_agents": [dict(a) for a in self.shared_agents],
            "forbidden_actions": list(FORBIDDEN_AGENT_ACTIONS),
            "entries": [e.to_dict() for e in self.entries],
            "note": self.note,
        }


def build_agent_topology(
    admission_strategies: dict[str, dict[str, Any]],
    *,
    agent_capabilities: tuple[dict[str, Any], ...],
    registered_pod_ids: tuple[str, ...] = (),
) -> AgentTopologyReport:
    """Build the topology from real registries.

    ``admission_strategies`` is ``config/strategy_admission.json``'s
    ``strategies`` map; ``agent_capabilities`` is
    ``AgentRegistry.capabilities()`` serialised. ``registered_pod_ids`` is the
    set of ``StrategyPod`` ids the runtime constructed (empty when only the
    admission ledger is loaded).
    """
    pods = set(registered_pod_ids)
    shared_ids = tuple(sorted(str(a.get("agent_id", "")) for a in agent_capabilities))
    shared_agents: list[dict[str, Any]] = []
    for agent in agent_capabilities:
        shared_agents.append(
            {
                "agent_id": str(agent.get("agent_id", "")),
                "capabilities": list(agent.get("capabilities", ())),
                "inputs": list(agent.get("inputs", ())),
                "outputs": list(agent.get("outputs", ())),
                "tools": list(agent.get("tools", ())),
                "permissions": list(agent.get("permissions", ())),
                "forbidden_actions": list(agent.get("forbidden_actions", FORBIDDEN_AGENT_ACTIONS)),
                "scope": "DECISION_LAYER_SHARED",
            }
        )

    entries: list[AgentTopologyEntry] = []
    for strategy_id in sorted(admission_strategies):
        spec = admission_strategies[strategy_id]
        family = str(spec.get("family", "UNKNOWN"))
        has_pod = strategy_id in pods
        entries.append(
            AgentTopologyEntry(
                strategy_id=strategy_id,
                strategy_version=str(spec.get("strategy_version", strategy_id)),
                family=family,
                pod_id=strategy_id if has_pod else "NOT_CONSTRUCTED",
                runtime_implementation=family_runtime_implementation(family),
                agent_id=None,
                agent_type=NO_AGENT,
                classification=NO_AGENT,
                capabilities=(),
                permissions=(),
                forbidden_actions=tuple(FORBIDDEN_AGENT_ACTIONS),
                state_ownership="DETERMINISTIC_RUNTIME",
                memory_ownership="NOT_APPLICABLE",
                runtime_reachability="REACHABLE" if has_pod else "LEDGER_ONLY",
                message_channels=(),
                evidence_path=f"admission_ledger:{strategy_id}",
                shared_agent_ids=shared_ids,
                note=(
                    "deterministic StrategyPod; supervised by the SHARED decision-layer "
                    "reviewers, not by a dedicated agent"
                ),
            )
        )

    entries_tuple = tuple(entries)
    dedicated = tuple(e.strategy_id for e in entries_tuple if e.agent_type == DEDICATED_AGENT)
    shared = tuple(e.strategy_id for e in entries_tuple if e.agent_type == SHARED_AGENT)
    none = tuple(e.strategy_id for e in entries_tuple if e.agent_type == NO_AGENT)

    answer = ("PARTIAL" if none else "YES") if dedicated else "NO"

    note = (
        "No StrategyPod is supervised by an independent agent. StrategyPods are "
        "deterministic runtimes; the five specialist agents are SHARED decision-packet "
        "reviewers with read-only / forbidden-execution capability surfaces."
    )
    return AgentTopologyReport(
        are_strategies_governed_by_independent_agents=answer,
        dedicated_agent_strategies=dedicated,
        shared_agent_strategies=shared,
        no_agent_strategies=none,
        shared_agents=tuple(shared_agents),
        entries=entries_tuple,
        pod_count=len(pods),
        note=note,
    )
