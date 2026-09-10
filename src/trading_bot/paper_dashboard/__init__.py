"""Read-only paper-trading observability layer (PHASE UI-01, CP-UI-001).

This package is an OBSERVABILITY layer over the canonical paper trading
runtime (PaperOrchestrator / PaperCycleEngine / PaperBroker). It never
creates, modifies or cancels trades, never imports the live execution
gateway, and never touches exchange credentials.
"""

from __future__ import annotations

from .events import EVENT_TYPES, DashboardEvent, DashboardEventBus
from .projection import DashboardSnapshot, DashboardStore
from .server import PaperDashboardServer
from .taps import ObservedBroker, ObservedEngine, ObservedRouter

__all__ = [
    "EVENT_TYPES",
    "DashboardEvent",
    "DashboardEventBus",
    "DashboardSnapshot",
    "DashboardStore",
    "ObservedBroker",
    "ObservedEngine",
    "ObservedRouter",
    "PaperDashboardServer",
]
