"""Immutable append-only blackboard for MA-1 communication."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from trading_bot.multi_agent.contracts import AgentEvidence, TraceContext

BLACKBOARD_TOPICS: Final[frozenset[str]] = frozenset(
    {
        "market_state",
        "asset_context",
        "strategy_candidates",
        "proposals",
        "evidence",
        "criticisms",
        "risk_flags",
        "decision_state",
    }
)


@dataclass(frozen=True, slots=True)
class BlackboardArtifact:
    """One immutable, traceable value published to a bounded topic."""

    artifact_id: str
    topic: str
    producer: str
    timestamp: datetime
    version: int
    trace: TraceContext
    value: object
    evidence_refs: tuple[str, ...] = ()


class Blackboard:
    """Deterministic append-only store with topic-scoped reads."""

    def __init__(self, *, run_id: str, trace_id: str) -> None:
        self._run_id = run_id
        self._trace_id = trace_id
        self._history: list[BlackboardArtifact] = []
        self._by_id: dict[str, BlackboardArtifact] = {}
        self._versions: dict[str, int] = {}

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def trace_id(self) -> str:
        return self._trace_id

    @property
    def history(self) -> tuple[BlackboardArtifact, ...]:
        """Return an immutable snapshot of all accepted artifacts."""
        return tuple(deepcopy(item) for item in self._history)

    def publish(
        self,
        *,
        artifact_id: str,
        topic: str,
        producer: str,
        timestamp: datetime,
        trace: TraceContext,
        value: object,
        evidence: tuple[AgentEvidence, ...] = (),
        evidence_refs: tuple[str, ...] = (),
    ) -> BlackboardArtifact:
        """Append an artifact, rejecting mutable/trace-inconsistent state."""
        if topic not in BLACKBOARD_TOPICS:
            raise ValueError(f"unsupported blackboard topic: {topic}")
        if not artifact_id or not producer:
            raise ValueError("artifact_id and producer are required")
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("artifact timestamp must be timezone-aware")
        if trace.run_id != self._run_id or trace.trace_id != self._trace_id:
            raise ValueError("artifact trace does not match blackboard trace")
        supplied_refs = tuple(evidence_refs) + tuple(item.evidence_id for item in evidence)
        if artifact_id in self._by_id:
            existing = self._by_id[artifact_id]
            if (
                existing.value != value
                or existing.topic != topic
                or existing.producer != producer
                or existing.evidence_refs != supplied_refs
            ):
                raise ValueError(
                    f"artifact ID already exists with different content: {artifact_id}"
                )
            return deepcopy(existing)

        if len(set(supplied_refs)) != len(supplied_refs):
            raise ValueError("duplicate evidence references are not allowed")
        evidence_by_id = {item.evidence_id: item for item in evidence}
        for ref in supplied_refs:
            linked = evidence_by_id.get(ref)
            if linked is None:
                raise ValueError(f"evidence reference is not bound in this publication: {ref}")
            if linked.run_id != self._run_id:
                raise ValueError("evidence run does not match blackboard run")
            if linked.trace is not None and linked.trace.trace_id != self._trace_id:
                raise ValueError("evidence trace does not match blackboard trace")
            if not linked.is_valid_at(timestamp):
                raise ValueError(f"evidence is not available at artifact timestamp: {ref}")

        version = self._versions.get(topic, 0) + 1
        artifact = BlackboardArtifact(
            artifact_id=artifact_id,
            topic=topic,
            producer=producer,
            timestamp=timestamp,
            version=version,
            trace=trace,
            value=deepcopy(value),
            evidence_refs=supplied_refs,
        )
        self._versions[topic] = version
        self._history.append(artifact)
        self._by_id[artifact_id] = artifact
        return deepcopy(artifact)

    def read(self, topic: str) -> tuple[BlackboardArtifact, ...]:
        """Return append-only history for exactly one topic."""
        if topic not in BLACKBOARD_TOPICS:
            raise ValueError(f"unsupported blackboard topic: {topic}")
        return tuple(deepcopy(artifact) for artifact in self._history if artifact.topic == topic)

    def get(self, artifact_id: str) -> BlackboardArtifact:
        """Resolve one immutable artifact by ID."""
        return deepcopy(self._by_id[artifact_id])


__all__ = ["BLACKBOARD_TOPICS", "Blackboard", "BlackboardArtifact"]
