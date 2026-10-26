"""Paper execution lifecycle (EXP-003P): contracts, store, engine, venue, reconciliation.

The package instruments the paper runtime that already exists. It does not implement a
second execution path: the real ``PaperBroker`` emits through
:class:`~trading_bot.paper.lifecycle.recorder.PaperBrokerRecorder`, and the offline venue
exists only to make partial fills, timeouts and duplicates reachable in controls.
"""

from __future__ import annotations

from .contracts import (
    ALLOWED_TRANSITIONS,
    ANOMALIES,
    PROVENANCES,
    CausalityViolation,
    ExecutionEnvelope,
    FillFact,
    IllegalTransition,
    LifecycleViolation,
    LiveModeForbidden,
    OrderIntent,
    ProvenanceViolation,
    ReconciliationResult,
    RiskGateViolation,
    digest_of,
    parse_utc,
    utc_ms,
)
from .engine import LifecycleEngine, RunContext
from .reconcile import reconcile
from .recorder import PaperBrokerRecorder
from .store import DurableEventStore, FillLedger, project_orders
from .venue import SimulatedPaperVenue, VenueMessage, VenueScript

__all__ = [
    "ALLOWED_TRANSITIONS",
    "ANOMALIES",
    "PROVENANCES",
    "CausalityViolation",
    "DurableEventStore",
    "ExecutionEnvelope",
    "FillFact",
    "FillLedger",
    "IllegalTransition",
    "LifecycleEngine",
    "LifecycleViolation",
    "LiveModeForbidden",
    "OrderIntent",
    "PaperBrokerRecorder",
    "ProvenanceViolation",
    "ReconciliationResult",
    "RiskGateViolation",
    "RunContext",
    "SimulatedPaperVenue",
    "VenueMessage",
    "VenueScript",
    "digest_of",
    "parse_utc",
    "project_orders",
    "reconcile",
    "utc_ms",
]
