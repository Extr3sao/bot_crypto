"""Append-only execution journal with canonical order states.

EXECUTION-RELIABILITY-01 (checkpoint EXTERNAL-AUDIT-RECONCILIATION-01).

Every transition records: previous_state, new_state, intent_id,
client_order_id, venue_order_id (when available), timestamp, evidence, reason.
The journal is append-only: transitions are never rewritten or removed.

This journal is a new primitive for the execution layer. It does NOT replace
the paper trade journal (``paper/trade_journal.py``) and does not touch the
frozen POC01 runtime.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from trading_bot.execution.intent import ExecutionReliabilityError


class ExecutionState(StrEnum):
    """Canonical execution states (directive 4 of the checkpoint)."""

    CREATED = "CREATED"
    SUBMITTING = "SUBMITTING"
    ACK_UNKNOWN = "ACK_UNKNOWN"
    ACCEPTED = "ACCEPTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    ORPHANED = "ORPHANED"
    RECONCILING = "RECONCILING"


# Allowed transitions (explicit, fail-closed). CANCELLED/REJECTED/FILLED are
# terminal; ORPHANED/RECONCILING are recovery states that can exit to ACCEPTED
# (adopted) or REJECTED (closed after reconciliation).
_ALLOWED_TRANSITIONS: dict[ExecutionState, frozenset[ExecutionState]] = {
    ExecutionState.CREATED: frozenset({ExecutionState.SUBMITTING, ExecutionState.REJECTED}),
    ExecutionState.SUBMITTING: frozenset(
        {ExecutionState.ACK_UNKNOWN, ExecutionState.ACCEPTED, ExecutionState.REJECTED}
    ),
    ExecutionState.ACK_UNKNOWN: frozenset(
        {ExecutionState.ACCEPTED, ExecutionState.REJECTED, ExecutionState.RECONCILING}
    ),
    ExecutionState.ACCEPTED: frozenset(
        {
            ExecutionState.PARTIALLY_FILLED,
            ExecutionState.FILLED,
            ExecutionState.CANCEL_PENDING,
            ExecutionState.ORPHANED,
            ExecutionState.RECONCILING,
        }
    ),
    ExecutionState.PARTIALLY_FILLED: frozenset(
        {
            ExecutionState.PARTIALLY_FILLED,
            ExecutionState.FILLED,
            ExecutionState.CANCEL_PENDING,
            ExecutionState.ORPHANED,
            ExecutionState.RECONCILING,
        }
    ),
    ExecutionState.FILLED: frozenset(),
    ExecutionState.CANCEL_PENDING: frozenset(
        {
            ExecutionState.CANCELLED,
            ExecutionState.FILLED,
            ExecutionState.PARTIALLY_FILLED,
            ExecutionState.ACCEPTED,
            ExecutionState.ORPHANED,
            ExecutionState.RECONCILING,
        }
    ),
    ExecutionState.CANCELLED: frozenset(),
    ExecutionState.REJECTED: frozenset(),
    ExecutionState.ORPHANED: frozenset(
        {ExecutionState.RECONCILING, ExecutionState.CANCELLED, ExecutionState.FILLED}
    ),
    ExecutionState.RECONCILING: frozenset(
        {
            ExecutionState.ACCEPTED,
            ExecutionState.CANCELLED,
            ExecutionState.FILLED,
            ExecutionState.REJECTED,
            ExecutionState.ORPHANED,
        }
    ),
}


@dataclass(frozen=True, slots=True)
class JournalTransition:
    """One append-only transition record."""

    previous_state: str
    new_state: str
    intent_id: str
    client_order_id: str
    venue_order_id: str | None
    timestamp: float
    evidence: dict[str, Any]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "previous_state": self.previous_state,
            "new_state": self.new_state,
            "intent_id": self.intent_id,
            "client_order_id": self.client_order_id,
            "venue_order_id": self.venue_order_id,
            "timestamp": self.timestamp,
            "evidence": dict(self.evidence),
            "reason": self.reason,
        }


def _evidence_digest(evidence: dict[str, Any]) -> str:
    canonical = json.dumps(evidence, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _state(value: ExecutionState | str) -> ExecutionState:
    if isinstance(value, ExecutionState):
        return value
    try:
        return ExecutionState(value)
    except ValueError as exc:
        raise ExecutionReliabilityError(f"unknown execution state: {value!r}") from exc


@dataclass
class ExecutionJournal:
    """In-memory append-only execution journal with optional JSONL persistence.

    The in-memory journal keeps full transition history per intent. The
    optional ``path`` appends each transition as one JSON line (auditable,
    crash-tolerant ordering).
    """

    path: Path | None = None
    _transitions: dict[str, list[JournalTransition]] = field(default_factory=dict)
    _current: dict[str, ExecutionState] = field(default_factory=dict)

    # -- core API -----------------------------------------------------------
    def record(
        self,
        *,
        intent_id: str,
        client_order_id: str,
        new_state: ExecutionState | str,
        reason: str,
        evidence: dict[str, Any] | None = None,
        venue_order_id: str | None = None,
        timestamp: float | None = None,
    ) -> JournalTransition:
        """Append a transition; validates the transition against the FSM."""
        state = _state(new_state)
        previous = self.current_state(intent_id)
        if previous is not None:
            allowed = _ALLOWED_TRANSITIONS.get(previous, frozenset())
            if state not in allowed:
                raise ExecutionReliabilityError(
                    f"illegal transition {previous.value} -> {state.value} for intent {intent_id}"
                )
        transition = JournalTransition(
            previous_state=previous.value if previous else "",
            new_state=state.value,
            intent_id=intent_id,
            client_order_id=client_order_id,
            venue_order_id=venue_order_id,
            timestamp=time.time() if timestamp is None else timestamp,
            evidence=dict(evidence or {}),
            reason=reason,
        )
        self._transitions.setdefault(intent_id, []).append(transition)
        self._current[intent_id] = state
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(
                {**transition.to_dict(), "evidence_digest": _evidence_digest(transition.evidence)},
                sort_keys=True,
                default=str,
            )
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        return transition

    def current_state(self, intent_id: str) -> ExecutionState | None:
        return self._current.get(intent_id)

    def history(self, intent_id: str) -> tuple[JournalTransition, ...]:
        return tuple(self._transitions.get(intent_id, ()))

    def intents(self) -> tuple[str, ...]:
        return tuple(self._transitions.keys())

    def is_terminal(self, intent_id: str) -> bool:
        state = self.current_state(intent_id)
        return state is not None and not _ALLOWED_TRANSITIONS.get(state, frozenset())
