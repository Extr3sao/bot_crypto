"""Trading Decision Monitor (TDM) — a read-only projection over PAPER decisions.

The TDM never decides, never sizes, never orders and never writes to the trading
runtime. It reads the artifacts the autonomous PAPER runtime already persists
(``traces.jsonl``, ``RUN_REPORT.json``, ``heartbeat.json``) and turns them into a
normalised, ordered event stream plus a query API and a browser view.

Design rules enforced here:

* **Read-only.** Nothing in this package imports a broker, a risk engine or the
  decision engine to *act*; ``autonomous.trace`` is imported only to read and
  replay the persisted ledger.
* **No invention.** A state the runtime did not persist is ``NOT_RECORDED``; it
  is never inferred from a neighbouring state (e.g. an acceptance is never
  rendered as a fill).
* **Point-in-time.** ``observed_market_time <= decision_time`` is validated on
  every event; a violation becomes ``INVALID_TEMPORAL_EVIDENCE`` and can never
  produce an acceptance marker.
"""

from .contracts import (
    DECISION_STATUS_LABELS,
    EVENT_TYPE_LABELS,
    ConnectionState,
    DecisionStatus,
    EventType,
    MonitorContractError,
    ReasonCode,
    TemporalEvidenceError,
    TradingDecisionEventV1,
    reason_for,
)

__all__ = [
    "DECISION_STATUS_LABELS",
    "EVENT_TYPE_LABELS",
    "ConnectionState",
    "DecisionStatus",
    "EventType",
    "MonitorContractError",
    "ReasonCode",
    "TemporalEvidenceError",
    "TradingDecisionEventV1",
    "reason_for",
]
