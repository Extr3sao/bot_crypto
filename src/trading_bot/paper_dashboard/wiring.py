"""Composition-root wiring for the local PAPER observability dashboard."""

from __future__ import annotations

from typing import Any

from trading_bot.config.runtime import TradingMode
from trading_bot.config.settings import Settings

from .events import DashboardEventBus
from .projection import DashboardStore
from .server import PaperDashboardServer
from .taps import ObservedBroker, ObservedEngine

DASHBOARD_HOST = "127.0.0.1"
DASHBOARD_PORT = 8000
DASHBOARD_PRICE_REFRESH_SECONDS = 2.0


def validate_paper_mode(settings: Settings) -> None:
    if settings.runtime.mode is not TradingMode.PAPER:
        raise RuntimeError(
            f"Paper dashboard requires runtime.mode='paper'; got {settings.runtime.mode.value!r}. Refusing to start (fail closed)."
        )


def build_taps(
    *,
    settings: Settings,
    broker: Any,
    cycle_engine: Any | None = None,
    bus: DashboardEventBus | None = None,
) -> tuple[ObservedBroker, ObservedEngine | None, DashboardEventBus, DashboardStore]:
    validate_paper_mode(settings)
    event_bus = bus or DashboardEventBus()
    store = DashboardStore()
    event_bus.add_listener(store.handle_event)
    return (
        ObservedBroker(broker, event_bus),
        ObservedEngine(cycle_engine, event_bus) if cycle_engine is not None else None,
        event_bus,
        store,
    )


def build_dashboard(
    *,
    settings: Settings,
    store: DashboardStore,
    bus: DashboardEventBus,
    orchestrator: Any | None = None,
    broker: Any | None = None,
    host: str = DASHBOARD_HOST,
    port: int = DASHBOARD_PORT,
) -> PaperDashboardServer:
    validate_paper_mode(settings)
    server = PaperDashboardServer(
        store=store, bus=bus, orchestrator=orchestrator, broker=broker, host=host, port=port
    )
    server.start()
    return server


__all__ = [
    "DASHBOARD_HOST",
    "DASHBOARD_PORT",
    "DASHBOARD_PRICE_REFRESH_SECONDS",
    "build_dashboard",
    "build_taps",
    "validate_paper_mode",
]
