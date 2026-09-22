"""Desk state machine enums — RFC §5 C1."""

from __future__ import annotations

from enum import StrEnum, unique


@unique
class DeskState(StrEnum):
    """Desk lifecycle states (RFC §5 C1)."""

    IDEA = "idea"
    EVIDENCE_PENDING = "evidence_pending"
    EVIDENCE_READY = "evidence_ready"
    RISK_PENDING = "risk_pending"
    RISK_REJECTED = "risk_rejected"
    RISK_PASSED = "risk_passed"
    APPROVAL_PENDING = "approval_pending"
    APPROVED = "approved"
    EXECUTION_PENDING = "execution_pending"
    SENT = "sent"
    RECONCILING = "reconciling"
    RESTING = "resting"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CLOSING = "closing"
    CLOSED = "closed"
    VOID = "void"
    INCIDENT = "incident"
    UNAVAILABLE = "unavailable"


@unique
class DeskTransition(StrEnum):
    """Valid desk state transitions (RFC §5 C1).

    Only these transitions are legal. All others must raise an error.
    """

    IDEA_TO_EVIDENCE_PENDING = "idea→evidence_pending"
    EVIDENCE_PENDING_TO_EVIDENCE_READY = "evidence_pending→evidence_ready"
    EVIDENCE_PENDING_TO_VOID = "evidence_pending→void"
    EVIDENCE_READY_TO_RISK_PENDING = "evidence_ready→risk_pending"
    EVIDENCE_READY_TO_VOID = "evidence_ready→void"
    RISK_PENDING_TO_RISK_PASSED = "risk_pending→risk_passed"
    RISK_PENDING_TO_RISK_REJECTED = "risk_pending→risk_rejected"
    RISK_PASSED_TO_APPROVAL_PENDING = "risk_passed→approval_pending"
    RISK_PASSED_TO_VOID = "risk_passed→void"
    RISK_REJECTED_TO_VOID = "risk_rejected→void"
    APPROVAL_PENDING_TO_APPROVED = "approval_pending→approved"
    APPROVAL_PENDING_TO_VOID = "approval_pending→void"
    APPROVED_TO_EXECUTION_PENDING = "approved→execution_pending"
    APPROVED_TO_VOID = "approved→void"
    EXECUTION_PENDING_TO_SENT = "execution_pending→sent"
    EXECUTION_PENDING_TO_VOID = "execution_pending→void"
    SENT_TO_RECONCILING = "sent→reconciling"
    SENT_TO_INCIDENT = "sent→incident"
    RECONCILING_TO_RESTING = "reconciling→resting"
    RECONCILING_TO_PARTIALLY_FILLED = "reconciling→partially_filled"
    RECONCILING_TO_INCIDENT = "reconciling→incident"
    RESTING_TO_PARTIALLY_FILLED = "resting→partially_filled"
    RESTING_TO_CLOSING = "resting→closing"
    RESTING_TO_INCIDENT = "resting→incident"
    PARTIALLY_FILLED_TO_RESTING = "partially_filled→resting"
    PARTIALLY_FILLED_TO_CLOSING = "partially_filled→closing"
    PARTIALLY_FILLED_TO_INCIDENT = "partially_filled→incident"
    FILLED_TO_CLOSING = "filled→closing"
    FILLED_TO_RESTING = "filled→resting"
    FILLED_TO_INCIDENT = "filled→incident"
    CLOSING_TO_CLOSED = "closing→closed"
    CLOSING_TO_INCIDENT = "closing→incident"
    CLOSED_TO_VOID = "closed→void"
    INCIDENT_TO_VOID = "incident→void"
    INCIDENT_TO_RISK_PENDING = "incident→risk_pending"
    UNAVAILABLE_TO_RISK_PENDING = "unavailable→risk_pending"
    UNAVAILABLE_TO_VOID = "unavailable→void"
