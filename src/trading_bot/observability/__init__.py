"""Observabilidad (Fase 8) + Strategy Ecosystem observability (WP-OBS-STRAT-01).

Read-only projection layer. Nothing here can start, stop, promote, size or
execute: it reads the runtime's authoritative artifacts and turns them into
JSON-serialisable read models for the dashboard.
"""

from .ecosystem import (
    INSUFFICIENT_DATA,
    INSUFFICIENT_SAMPLE,
    NOT_AVAILABLE,
    UNKNOWN,
    RunArtifacts,
    StrategyEcosystemObservatory,
    read_json,
    read_jsonl,
)
from .journal import TradeJournal
from .metrics import MetricPoint, MetricsCollector
from .topology import (
    DEDICATED_AGENT,
    NO_AGENT,
    SHARED_AGENT,
    AgentTopologyReport,
    build_agent_topology,
)

__all__ = [
    "DEDICATED_AGENT",
    "INSUFFICIENT_DATA",
    "INSUFFICIENT_SAMPLE",
    "NOT_AVAILABLE",
    "NO_AGENT",
    "SHARED_AGENT",
    "UNKNOWN",
    "AgentTopologyReport",
    "MetricPoint",
    "MetricsCollector",
    "RunArtifacts",
    "StrategyEcosystemObservatory",
    "TradeJournal",
    "build_agent_topology",
    "read_json",
    "read_jsonl",
]
