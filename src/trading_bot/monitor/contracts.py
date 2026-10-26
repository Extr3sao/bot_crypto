"""Normalised contract for the Trading Decision Monitor — ``TradingDecisionEventV1``.

The contract is a *projection* schema: one instance describes exactly one thing the
PAPER runtime did, with the identifiers needed to walk back to the originating
``DecisionTrace``. It is deliberately narrower than the trace (no market context,
no agent prose) so that everything a marker can show has a named source field.

Invariants (raised as :class:`MonitorContractError`):

* ``schema_version == "1.0"``;
* ``event_id`` is a real UUID (deterministic uuid5, so re-projection is stable);
* ``sequence >= 1`` and monotonic per run (assigned by the projector);
* ``observed_market_time <= decision_time`` (:class:`TemporalEvidenceError`);
* ``decision_status`` is one of :class:`DecisionStatus`;
* ``event_type`` is one of :class:`EventType`;
* ``reason_codes`` are catalogued codes, and an unknown code is preserved with the
  ``UNCATALOGUED_`` marker rather than silently dropped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

__all__ = [
    "DECISION_STATUS_LABELS",
    "EVENT_TYPE_LABELS",
    "SEVERITY_ORDER",
    "ConnectionState",
    "DecisionStatus",
    "EventType",
    "MonitorContractError",
    "ReasonCode",
    "TemporalEvidenceError",
    "TradingDecisionEventV1",
    "iso_utc",
    "reason_for",
]

SCHEMA_VERSION = "1.0"
MAX_SHORT_TEXT = 160
MAX_REASON_SUMMARY = 320


class MonitorContractError(ValueError):
    """The projection produced something the contract forbids."""


class TemporalEvidenceError(MonitorContractError):
    """Point-in-time violation: the evidence claims to know the future."""


class EventType(StrEnum):
    """Event classes. Mirrors RFC-TAP-OBS-001 §4.2 B exactly."""

    SIGNAL_DETECTED = "SIGNAL_DETECTED"
    PROPOSAL_CREATED = "PROPOSAL_CREATED"
    UNDER_REVIEW = "UNDER_REVIEW"
    DECISION_REJECTED = "DECISION_REJECTED"
    DECISION_ACCEPTED = "DECISION_ACCEPTED"
    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    ORDER_FILLED = "ORDER_FILLED"
    ORDER_REJECTED = "ORDER_REJECTED"
    POSITION_CLOSED = "POSITION_CLOSED"
    SYSTEM_DATA_STALE = "SYSTEM_DATA_STALE"
    PIPELINE_ERROR = "PIPELINE_ERROR"


class DecisionStatus(StrEnum):
    """The *decision-level* state, which is what the UI must never confuse.

    ``ACCEPTED_NOT_EXECUTED`` exists because the runtime can authorise an order
    and then fail to fill it; ``EXECUTED_PAPER`` exists because a fill is a
    different fact from an acceptance. ``SHADOW_OBSERVED`` exists because a
    ``SHADOW_TRADE`` is neither a trade nor a ``NO_TRADE`` decision.
    """

    NO_TRADE = "NO_TRADE"
    SHADOW_OBSERVED = "SHADOW_OBSERVED"
    ACCEPTED_NOT_EXECUTED = "ACCEPTED_NOT_EXECUTED"
    EXECUTED_PAPER = "EXECUTED_PAPER"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    SIGNAL_ONLY = "SIGNAL_ONLY"
    UNDECIDED = "UNDECIDED"


class ConnectionState(StrEnum):
    """What the *stream* is, never what the user hopes it is."""

    LIVE_DATA = "LIVE_DATA"
    DELAYED = "DELAYED"
    DISCONNECTED = "DISCONNECTED"
    REPLAY = "REPLAY"
    SIMULATED_FIXTURE = "SIMULATED_FIXTURE"


#: UI copy for every event class. Colour/icon/text always travel together, so
#: colour is never the only carrier of meaning (accessibility, RFC §5).
EVENT_TYPE_LABELS: dict[EventType, dict[str, str]] = {
    EventType.SIGNAL_DETECTED: {"text": "Señal detectada", "icon": "◆", "tone": "neutral"},
    EventType.PROPOSAL_CREATED: {"text": "Propuesta creada", "icon": "◇", "tone": "neutral"},
    EventType.UNDER_REVIEW: {"text": "En evaluación", "icon": "…", "tone": "warn"},
    EventType.DECISION_REJECTED: {"text": "Rechazada / NO_TRADE", "icon": "✕", "tone": "bad"},
    EventType.DECISION_ACCEPTED: {"text": "Aceptada para ejecución", "icon": "✓", "tone": "good"},
    EventType.ORDER_SUBMITTED: {"text": "Orden enviada a PAPER", "icon": "→", "tone": "info"},
    EventType.ORDER_FILLED: {"text": "Ejecutada PAPER", "icon": "●", "tone": "info-strong"},
    EventType.ORDER_REJECTED: {"text": "Orden fallida", "icon": "⊘", "tone": "bad-outline"},
    EventType.POSITION_CLOSED: {"text": "Posición cerrada", "icon": "■", "tone": "exit"},
    EventType.SYSTEM_DATA_STALE: {"text": "Datos atrasados", "icon": "⏱", "tone": "system"},
    EventType.PIPELINE_ERROR: {"text": "Error de sistema", "icon": "⚠", "tone": "system"},
}

#: The label shown for each decision status. This is the text that prevents the
#: RFC's six confusions; it is never derived from colour or icon alone.
DECISION_STATUS_LABELS: dict[DecisionStatus, str] = {
    DecisionStatus.NO_TRADE: "NO_TRADE",
    DecisionStatus.SHADOW_OBSERVED: "SHADOW (NO EJECUTADA)",
    DecisionStatus.ACCEPTED_NOT_EXECUTED: "ACEPTADA (NO EJECUTADA)",
    DecisionStatus.EXECUTED_PAPER: "EJECUTADA PAPER",
    DecisionStatus.EXECUTION_FAILED: "ACEPTADA (EJECUCIÓN FALLIDA)",
    DecisionStatus.SIGNAL_ONLY: "SEÑAL (SIN DECISIÓN)",
    DecisionStatus.UNDECIDED: "SIN DECISIÓN",
}

SEVERITY_ORDER = ("INFO", "WARN", "ERROR", "CRITICAL")


@dataclass(frozen=True, slots=True)
class ReasonCode:
    """One attributable reason, with the measured value the component recorded.

    ``short_text`` is deterministic copy from the catalog. ``measured_value`` and
    ``threshold`` are ``None`` unless the authoritative component persisted them —
    an unknown threshold is reported as unknown, never estimated.
    """

    code: str
    short_text: str
    component: str
    severity: str = "INFO"
    measured_value: float | None = None
    threshold: float | None = None
    unit: str | None = None
    evidence_ref: str | None = None
    explanation_version: str = "reason-catalog-v1"
    counter_evidence: tuple[str, ...] = ()
    dissenting_agents: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.code:
            raise MonitorContractError("reason code must be non-empty")
        if self.severity not in SEVERITY_ORDER:
            raise MonitorContractError(f"unknown severity {self.severity!r}")
        if len(self.short_text) > MAX_SHORT_TEXT:
            raise MonitorContractError(
                f"short_text exceeds {MAX_SHORT_TEXT} chars: {self.short_text!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "reason_code": self.code,
            "short_text": self.short_text,
            "component": self.component,
            "severity": self.severity,
            "measured_value": self.measured_value,
            "threshold": self.threshold,
            "unit": self.unit,
            "evidence_ref": self.evidence_ref,
            "explanation_version": self.explanation_version,
            "counter_evidence": list(self.counter_evidence),
            "dissenting_agents": list(self.dissenting_agents),
        }


#: Deterministic reason catalog. Codes match ``autonomous.decision.CLASSIFICATIONS``
#: plus the deterministic risk rules the runtime writes into ``risk.rule``.
#: Adding a code here changes UI copy only — never a decision.
_CATALOG: dict[str, tuple[str, str, str]] = {
    # classification code -> (short_text, component, severity)
    "AGENT_VETO": ("Un agente revisor emitió un veto sobre la propuesta.", "agents", "WARN"),
    "CONTEXT_ERROR": ("No se pudo construir un contexto de mercado utilizable.", "runtime", "ERROR"),
    "COST_KILLED": ("El coste estimado supera el borde bruto esperado.", "cost_engine", "INFO"),
    "NO_ALPHA": ("Ninguna familia de estrategia emitió una señal.", "strategy_router", "INFO"),
    "NO_GROSS_EDGE": ("El borde bruto esperado no es positivo.", "decision_engine", "INFO"),
    "NO_MARKET_DATA": ("No hay datos de mercado utilizables en este ciclo.", "runtime", "ERROR"),
    "NO_PROPOSAL": ("El router no generó propuesta para este activo.", "strategy_router", "INFO"),
    "NOT_ADMITTED": (
        "La estrategia no está admitida para PAPER; se observa en SHADOW.",
        "admission_ledger",
        "INFO",
    ),
    "PAPER_ADMITTED": (
        "Candidata admitida con borde neto positivo y verificación PASS.",
        "decision_engine",
        "INFO",
    ),
    "RISK_VETO": ("El motor de riesgo determinista vetó la operación.", "risk_engine", "WARN"),
    "UNKNOWN_STRATEGY": (
        "La estrategia no figura en el ledger de admisión.",
        "admission_ledger",
        "WARN",
    ),
    "VERIFIER_FAIL": (
        "El verificador independiente no dio PASS a este paquete.",
        "verifier",
        "WARN",
    ),
    # operational / projection codes
    "DUPLICATE_DECISION_ID": (
        "Dos registros comparten decision_id en el mismo run.",
        "monitor",
        "ERROR",
    ),
    "INVALID_TEMPORAL_EVIDENCE": (
        "El mercado observado es posterior a la decisión; evidencia inválida.",
        "monitor",
        "CRITICAL",
    ),
    "REASON_UNAVAILABLE": (
        "El runtime no registró un motivo atribuible para este estado.",
        "monitor",
        "WARN",
    ),
    "RUNTIME_ERROR": ("El ciclo registró un error operativo.", "runtime", "ERROR"),
    "ORDER_SUBMITTED_NOT_RECORDED": (
        "El runtime no persiste el envío de la orden, solo el fill.",
        "runtime",
        "WARN",
    ),
    "FILL_PRICE_NOT_RECORDED": (
        "El runtime no persiste el precio de fill; se muestra la referencia de entrada.",
        "runtime",
        "WARN",
    ),
    "RISK_NOT_EVALUATED": (
        "No se invocó el motor de riesgo porque no había propuesta.",
        "risk_engine",
        "INFO",
    ),
    "RISK_ADVISORY_PASS": (
        "Riesgo evaluado en modo advisory: no autoriza ni bloquea.",
        "risk_engine",
        "INFO",
    ),
    "RISK_BINDING_PASS": ("Riesgo determinista favorable y vinculante.", "risk_engine", "INFO"),
    "VERIFIER_NOT_RUN": (
        "El verificador no se ejecutó para este paquete.",
        "verifier",
        "INFO",
    ),
    "STRATEGY_EMITTED_ALPHA": (
        "La familia de estrategia emitió una señal alpha evaluable.",
        "strategy_router",
        "INFO",
    ),
    "PROPOSAL_FROM_ROUTER": (
        "El router construyó una propuesta con borde y coste estimados.",
        "runtime",
        "INFO",
    ),
    "COST_EXCEEDS_GROSS": (
        "El coste estimado supera el borde bruto de la propuesta.",
        "cost_engine",
        "INFO",
    ),
    "PAPER_FILL": (
        "El broker PAPER confirmó la ejecución de la orden.",
        "paper_broker",
        "INFO",
    ),
    "TRACE_RECORD_INVALID": (
        "Un registro de traza no supera la validación del contrato.",
        "monitor",
        "ERROR",
    ),
}


def reason_for(code: str, **kwargs: Any) -> ReasonCode:
    """Build a catalogued reason; unknown codes are kept, explicitly marked."""
    entry = _CATALOG.get(code)
    if entry is None:
        return ReasonCode(
            code=code,
            short_text=f"Motivo no catalogado: {code}.",
            component=str(kwargs.pop("component", "unknown")),
            severity=str(kwargs.pop("severity", "WARN")),
            **kwargs,
        )
    short_text, component, severity = entry
    kwargs.setdefault("component", component)
    kwargs.setdefault("severity", severity)
    return ReasonCode(code=code, short_text=short_text, **kwargs)


def iso_utc(ms: int | None) -> str | None:
    """Epoch milliseconds → ``YYYY-MM-DDTHH:MM:SS.mmmZ`` (never a local zone)."""
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000.0, tz=UTC).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


@dataclass(frozen=True, slots=True)
class TradingDecisionEventV1:
    """One normalised event, linked to the trace row that produced it."""

    event_id: str
    run_id: str
    sequence: int
    decision_id: str
    event_type: EventType
    decision_status: DecisionStatus
    symbol: str
    timeframe: str
    mode: str
    observed_market_time: str | None
    decision_time: str
    emitted_at: str
    reason_codes: tuple[ReasonCode, ...]
    reason_summary: str
    proposal_id: str | None = None
    order_id: str | None = None
    venue: str = "UNKNOWN"
    strategy_id: str | None = None
    signal_direction: str | None = None
    verification: str = "NOT_RUN"
    risk_gate: str = "NOT_APPLICABLE"
    confidence: float | None = None
    source_component: str = "unknown"
    source_commit: str | None = None
    source_sequence: int = 0
    trace_hash: str | None = None
    evidence_refs: tuple[str, ...] = ()
    price_observed: float | None = None
    price_source: str = "NOT_RECORDED"
    severity: str = "INFO"
    observed_market_time_ms: int | None = None
    decision_time_ms: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    # -- validation ---------------------------------------------------------

    def __post_init__(self) -> None:
        if not _UUID_RE.match(self.event_id):
            raise MonitorContractError(f"event_id must be a UUID: {self.event_id!r}")
        UUID(self.event_id)  # version-agnostic structural check
        if self.sequence < 1:
            raise MonitorContractError("sequence must be >= 1")
        if not self.run_id or not self.decision_id:
            raise MonitorContractError("run_id and decision_id are mandatory")
        if not isinstance(self.event_type, EventType):
            raise MonitorContractError(f"event_type must be EventType, got {self.event_type!r}")
        if not isinstance(self.decision_status, DecisionStatus):
            raise MonitorContractError(
                f"decision_status must be DecisionStatus, got {self.decision_status!r}"
            )
        if self.severity not in SEVERITY_ORDER:
            raise MonitorContractError(f"unknown severity {self.severity!r}")
        if len(self.reason_summary) > MAX_REASON_SUMMARY:
            raise MonitorContractError("reason_summary too long")
        if (
            self.observed_market_time_ms is not None
            and self.observed_market_time_ms > self.decision_time_ms
        ):
            raise TemporalEvidenceError(
                "observed_market_time "
                f"({self.observed_market_time_ms}) > decision_time ({self.decision_time_ms})"
            )
        if self.event_type is EventType.DECISION_ACCEPTED and (
            self.decision_status is not DecisionStatus.ACCEPTED_NOT_EXECUTED
        ):
            raise MonitorContractError(
                "DECISION_ACCEPTED must carry ACCEPTED_NOT_EXECUTED (a fill is ORDER_FILLED)"
            )
        if self.event_type is EventType.ORDER_FILLED and (
            self.decision_status is not DecisionStatus.EXECUTED_PAPER
        ):
            raise MonitorContractError("ORDER_FILLED must carry EXECUTED_PAPER")

    # -- serialisation ------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "event_id": self.event_id,
            "run_id": self.run_id,
            "sequence": self.sequence,
            "decision_id": self.decision_id,
            "proposal_id": self.proposal_id,
            "order_id": self.order_id,
            "symbol": self.symbol,
            "venue": self.venue,
            "timeframe": self.timeframe,
            "strategy_id": self.strategy_id,
            "mode": self.mode,
            "event_type": self.event_type.value,
            "decision_status": self.decision_status.value,
            "decision_status_label": DECISION_STATUS_LABELS[self.decision_status],
            "event_label": EVENT_TYPE_LABELS[self.event_type]["text"],
            "event_icon": EVENT_TYPE_LABELS[self.event_type]["icon"],
            "event_tone": EVENT_TYPE_LABELS[self.event_type]["tone"],
            "signal_direction": self.signal_direction,
            "reason_codes": [r.to_dict() for r in self.reason_codes],
            "reason_summary": self.reason_summary,
            "observed_market_time": self.observed_market_time,
            "observed_market_time_ms": self.observed_market_time_ms,
            "decision_time": self.decision_time,
            "decision_time_ms": self.decision_time_ms,
            "emitted_at": self.emitted_at,
            "evidence_refs": list(self.evidence_refs),
            "verification": self.verification,
            "risk_gate": self.risk_gate,
            "confidence": self.confidence,
            "source_component": self.source_component,
            "source_commit": self.source_commit,
            "source_sequence": self.source_sequence,
            "trace_hash": self.trace_hash,
            "price_observed": self.price_observed,
            "price_source": self.price_source,
            "severity": self.severity,
        }
        if self.extra:
            payload["extra"] = dict(self.extra)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> TradingDecisionEventV1:
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise MonitorContractError(
                f"unsupported schema_version {payload.get('schema_version')!r}"
            )
        reasons = tuple(
            ReasonCode(
                code=str(r["reason_code"]),
                short_text=str(r["short_text"]),
                component=str(r.get("component", "unknown")),
                severity=str(r.get("severity", "INFO")),
                measured_value=r.get("measured_value"),
                threshold=r.get("threshold"),
                unit=r.get("unit"),
                evidence_ref=r.get("evidence_ref"),
                explanation_version=str(r.get("explanation_version", "reason-catalog-v1")),
                counter_evidence=tuple(r.get("counter_evidence") or ()),
                dissenting_agents=tuple(r.get("dissenting_agents") or ()),
            )
            for r in payload.get("reason_codes", [])
        )
        return cls(
            event_id=str(payload["event_id"]),
            run_id=str(payload["run_id"]),
            sequence=int(payload["sequence"]),
            decision_id=str(payload["decision_id"]),
            event_type=EventType(str(payload["event_type"])),
            decision_status=DecisionStatus(str(payload["decision_status"])),
            symbol=str(payload.get("symbol", "")),
            timeframe=str(payload.get("timeframe", "UNKNOWN")),
            mode=str(payload.get("mode", "PAPER")),
            observed_market_time=payload.get("observed_market_time"),
            decision_time=str(payload.get("decision_time") or ""),
            emitted_at=str(payload.get("emitted_at") or ""),
            reason_codes=reasons,
            reason_summary=str(payload.get("reason_summary") or ""),
            proposal_id=payload.get("proposal_id"),
            order_id=payload.get("order_id"),
            venue=str(payload.get("venue") or "UNKNOWN"),
            strategy_id=payload.get("strategy_id"),
            signal_direction=payload.get("signal_direction"),
            verification=str(payload.get("verification") or "NOT_RUN"),
            risk_gate=str(payload.get("risk_gate") or "NOT_APPLICABLE"),
            confidence=payload.get("confidence"),
            source_component=str(payload.get("source_component") or "unknown"),
            source_commit=payload.get("source_commit"),
            source_sequence=int(payload.get("source_sequence") or 0),
            trace_hash=payload.get("trace_hash"),
            evidence_refs=tuple(payload.get("evidence_refs") or ()),
            price_observed=payload.get("price_observed"),
            price_source=str(payload.get("price_source") or "NOT_RECORDED"),
            severity=str(payload.get("severity") or "INFO"),
            observed_market_time_ms=payload.get("observed_market_time_ms"),
            decision_time_ms=int(payload.get("decision_time_ms") or 0),
            extra=dict(payload.get("extra") or {}),
        )
