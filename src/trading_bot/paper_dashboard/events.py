"""Dashboard event bus — publish/subscribe for decision-stream events.

Pure stdlib. The trading loop publishes; dashboard clients subscribe via
SSE. Publishing NEVER raises to the caller: a broken subscriber or a full
buffer is contained inside the bus so the trading runtime never waits for
browser clients (dashboard-unavailable isolation requirement).
"""

from __future__ import annotations

import contextlib
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

# Event types emitted by the paper runtime taps. The taxonomy mirrors the
# canonical cycle stages (context → router → strategy → risk → broker).
EVENT_TYPES = (
    "cycle_completed",
    "context_built",
    "strategy_selected",
    "signal_generated",
    "signal_rejected",
    "risk_accepted",
    "risk_rejected",
    "position_opened",
    "position_closed",
    "sl_triggered",
    "tp_triggered",
    "runtime_error",
)

_QUEUE_MAXLEN = 1000
_SUBSCRIBER_BUFFER = 200


@dataclass(frozen=True, slots=True)
class DashboardEvent:
    """One immutable observability event (never carries credentials)."""

    type: str
    timestamp: float
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "timestamp": self.timestamp, "payload": self.payload}


def _default_now() -> float:
    return time.time()


class DashboardEventBus:
    """In-process pub/sub with bounded per-subscriber queues.

    Contract (dashboard isolation):
    - ``publish`` swallows every subscriber exception (broken client,
      full buffer): the trading loop must never block or crash because
      of the dashboard.
    - A bounded ring buffer retains recent events so late HTTP readers
      of ``/api/events`` still see the decision stream.
    """

    def __init__(
        self,
        *,
        history_size: int = 500,
        now_fn: Any = _default_now,
    ) -> None:
        self._history: deque[DashboardEvent] = deque(maxlen=history_size)
        self._subscribers: list[deque[DashboardEvent]] = []
        # Persistent listeners (e.g. DashboardStore) see EVERY event; the
        # bounded per-subscriber queues are only for live SSE fan-out.
        self._listeners: list[Any] = []
        self._now_fn = now_fn

    def add_listener(self, listener: Any) -> None:
        """Register a callable(event) that receives every published event."""
        self._listeners.append(listener)

    # -- publisher side (called from the trading loop) ----------------------

    def publish(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        """Publish one event. Never raises. Never blocks the trading loop."""
        if event_type not in EVENT_TYPES:
            # Unknown types are still recorded (observability must not hide
            # runtime surprises) but tagged so the UI can render them.
            event_type = f"unknown:{event_type}"
        event = DashboardEvent(
            type=event_type,
            timestamp=self._now_fn(),
            payload=dict(payload or {}),
        )
        try:
            self._history.append(event)
            for listener in list(self._listeners):
                try:
                    listener(event)
                except Exception:
                    continue
            for queue in list(self._subscribers):
                try:
                    queue.append(event)
                except Exception:  # full queue or broken subscriber
                    try:
                        queue.clear()
                        queue.append(event)
                    except Exception:
                        continue
        except Exception:
            # Absolute containment: observability failures must never
            # propagate into the trading runtime.
            return

    # -- subscriber side (called from dashboard clients) --------------------

    def subscribe(self) -> deque[DashboardEvent]:
        """Register a new subscriber queue (bounded; drops oldest on overflow)."""
        queue: deque[DashboardEvent] = deque(maxlen=_SUBSCRIBER_BUFFER)
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: deque[DashboardEvent]) -> None:
        with contextlib.suppress(ValueError):
            self._subscribers.remove(queue)

    def recent(self, limit: int = 100, event_type: str | None = None) -> list[DashboardEvent]:
        """Snapshot of recent events for the REST read path."""
        events = list(self._history)
        if event_type:
            events = [e for e in events if e.type == event_type]
        return events[-limit:]


__all__ = ["EVENT_TYPES", "DashboardEvent", "DashboardEventBus"]
