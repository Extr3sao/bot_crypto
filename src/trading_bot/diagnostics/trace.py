"""Immutable, sidecar proposal-to-outcome tracing with no trading authority."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

TRACE_SCHEMA_VERSION = "decision-trace-v1"


class TraceStage(StrEnum):
    MARKET_WINDOW = "MARKET_WINDOW"
    RAW_SIGNAL = "RAW_SIGNAL"
    TRADE_PROPOSAL = "TRADE_PROPOSAL"
    STRATEGY_ROUTER = "STRATEGY_ROUTER"
    AGENT_REVIEW = "AGENT_REVIEW"
    CRITIC = "CRITIC"
    METARANKER = "METARANKER"
    DECISION_ENGINE = "DECISION_ENGINE"
    VERIFIER = "VERIFIER"
    RISK = "RISK"
    EXECUTION_INTENT = "EXECUTION_INTENT"
    PAPER_EXECUTION = "PAPER_EXECUTION"
    SHADOW_CAPTURE = "SHADOW_CAPTURE"
    RECONCILIATION = "RECONCILIATION"
    OUTCOME = "OUTCOME"


class TraceReason(StrEnum):
    NO_SIGNAL = "NO_SIGNAL"
    ROUTER_NOT_APPLICABLE = "ROUTER_NOT_APPLICABLE"
    STRATEGY_REJECT = "STRATEGY_REJECT"
    DIRECTION_CONFLICT = "DIRECTION_CONFLICT"
    UNRESOLVED_CONFLICT = "UNRESOLVED_CONFLICT"
    AGENT_REJECT = "AGENT_REJECT"
    CRITIC_REJECT = "CRITIC_REJECT"
    METARANKER_REJECT = "METARANKER_REJECT"
    DECISION_REJECT = "DECISION_REJECT"
    VERIFIER_REJECT = "VERIFIER_REJECT"
    MAX_POSITIONS = "MAX_POSITIONS"
    COOLDOWN = "COOLDOWN"
    PORTFOLIO_CONFLICT = "PORTFOLIO_CONFLICT"
    DATA_INVALID = "DATA_INVALID"
    STALE_DATA = "STALE_DATA"
    DUPLICATE_INTENT = "DUPLICATE_INTENT"
    EXECUTION_CONSTRAINT = "EXECUTION_CONSTRAINT"
    RISK_REJECT = "RISK_REJECT"
    OTHER = "OTHER"


def trace_id_for(run_id: str, proposal_id: str) -> str:
    if not run_id or not proposal_id:
        raise ValueError("run_id and proposal_id are required")
    body = json.dumps({"run_id": run_id, "proposal_id": proposal_id}, sort_keys=True)
    return "dtrace:" + hashlib.sha256(body.encode()).hexdigest()[:24]


@dataclass(frozen=True, slots=True)
class DecisionTraceEvent:
    trace_id: str
    run_id: str
    cycle_id: str
    proposal_id: str
    asset: str
    strategy: str
    timeframe: str
    stage: TraceStage
    event_type: str
    actor: str
    timestamp_utc: str
    decision: str | None = None
    reason_code: TraceReason | None = None
    raw_reason: str | None = None
    input_ids: tuple[str, ...] = ()
    output_ids: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    counter_evidence_refs: tuple[str, ...] = ()
    confidence: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    provenance: str = "NATIVE_TRACE_V1"
    schema_version: str = TRACE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.trace_id != trace_id_for(self.run_id, self.proposal_id):
            raise ValueError("trace_id does not match run/proposal identity")
        if self.stage is TraceStage.OUTCOME and self.provenance == "NATIVE_TRACE_V1":
            raise ValueError("outcomes require separately sourced provenance")

    def _payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["stage"] = self.stage.value
        payload["reason_code"] = self.reason_code.value if self.reason_code else None
        return payload

    @property
    def event_id(self) -> str:
        body = json.dumps(self._payload(), sort_keys=True, separators=(",", ":"))
        return "dte:" + hashlib.sha256(body.encode()).hexdigest()[:24]

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "event_id": self.event_id}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> DecisionTraceEvent:
        payload = dict(value)
        payload.pop("event_id", None)
        payload["stage"] = TraceStage(payload["stage"])
        if payload.get("reason_code"):
            payload["reason_code"] = TraceReason(payload["reason_code"])
        for key in ("input_ids", "output_ids", "evidence_refs", "counter_evidence_refs"):
            payload[key] = tuple(payload.get(key, ()))
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class ProposalOutcome:
    trace_id: str
    proposal_id: str
    asset: str
    strategy: str
    terminal_disposition: str
    executed: bool
    shadow: bool
    outcome_available: bool
    outcome_source: str = "NONE"
    rejection_stage: TraceStage | None = None
    rejection_reason: TraceReason | None = None
    gross_return: float | None = None
    net_return: float | None = None
    r_multiple: float | None = None


class TraceStore:
    """Append-only JSONL store; duplicate immutable events are idempotent."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, event: DecisionTraceEvent) -> bool:
        if event.event_id in {item.event_id for item in self.events()}:
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.to_dict(), sort_keys=True) + "\n")
        return True

    def events(self) -> tuple[DecisionTraceEvent, ...]:
        if not self.path.exists():
            return ()
        items = [
            DecisionTraceEvent.from_dict(json.loads(line))
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        return tuple(sorted(items, key=lambda item: (item.timestamp_utc, item.event_id)))

    def query(
        self,
        *,
        trace_id: str | None = None,
        run_id: str | None = None,
        proposal_id: str | None = None,
        reason: TraceReason | None = None,
    ) -> tuple[DecisionTraceEvent, ...]:
        return tuple(
            item
            for item in self.events()
            if (trace_id is None or item.trace_id == trace_id)
            and (run_id is None or item.run_id == run_id)
            and (proposal_id is None or item.proposal_id == proposal_id)
            and (reason is None or item.reason_code is reason)
        )

    def completeness(self) -> dict[str, Any]:
        grouped: dict[str, list[DecisionTraceEvent]] = {}
        for item in self.events():
            grouped.setdefault(item.proposal_id, []).append(item)
        terminal = {TraceStage.PAPER_EXECUTION, TraceStage.SHADOW_CAPTURE, TraceStage.OUTCOME}
        complete = sum(
            any(item.stage in terminal for item in entries) for entries in grouped.values()
        )
        return {
            "total_proposals": len(grouped),
            "fully_traced": complete,
            "unknown_terminal_state": len(grouped) - complete,
        }

    def replay(self, trace_id: str) -> dict[str, Any]:
        events = self.query(trace_id=trace_id)
        if not events:
            raise KeyError(trace_id)
        terminal = next(
            (
                item
                for item in reversed(events)
                if item.stage
                in {TraceStage.OUTCOME, TraceStage.PAPER_EXECUTION, TraceStage.SHADOW_CAPTURE}
            ),
            None,
        )
        return {
            "trace_id": trace_id,
            "events": [item.to_dict() for item in events],
            "terminal_disposition": terminal.event_type if terminal else "UNKNOWN_INCOMPLETE_TRACE",
            "outcome_available": bool(terminal and terminal.stage is TraceStage.OUTCOME),
        }
