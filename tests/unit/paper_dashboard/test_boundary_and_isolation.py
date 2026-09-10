from __future__ import annotations

import ast
from pathlib import Path

import pytest

from trading_bot.market_data.fake import build_demo_settings
from trading_bot.paper.broker import PaperBroker
from trading_bot.paper_dashboard.events import DashboardEventBus
from trading_bot.paper_dashboard.projection import DashboardStore
from trading_bot.paper_dashboard.taps import ObservedBroker, ObservedEngine, ObservedRouter
from trading_bot.paper_dashboard.wiring import build_taps, validate_paper_mode

PKG = Path("src/trading_bot/paper_dashboard")
FORBIDDEN = ("trading_bot.execution", "trading_bot.exchanges", "trading_bot.market_data")


def imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module] + [
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    ]


def test_dashboard_dependency_boundary() -> None:
    for path in PKG.glob("*.py"):
        assert not [
            mod
            for mod in imports(path)
            if any(mod == x or mod.startswith(x + ".") for x in FORBIDDEN)
        ]


def test_taps_do_not_add_write_methods() -> None:
    observed = ObservedBroker(PaperBroker(equity=1000), None)
    assert observed.equity == 1000
    assert not {
        name
        for name in vars(ObservedBroker)
        if any(word in name.lower() for word in ("place", "close", "modify", "cancel"))
    }


def test_mode_gate_and_build_taps() -> None:
    paper = build_demo_settings(mode="paper")
    validate_paper_mode(paper)
    observed, engine, bus, store = build_taps(settings=paper, broker=PaperBroker(equity=500))
    assert observed.equity == 500 and engine is None and bus and store
    with pytest.raises(RuntimeError):
        validate_paper_mode(build_demo_settings(mode="live"))


def test_dashboard_failures_do_not_break_broker() -> None:
    class BrokenBus(DashboardEventBus):
        def publish(self, event_type: str, payload: dict | None = None) -> None:
            raise RuntimeError("dashboard unavailable")

    from trading_bot.strategies.types import Signal

    signal = Signal(
        symbol="BTC/USDT",
        side="buy",
        strategy_name="test",
        timeframe="5m",
        confidence=0.8,
        price=100,
        stop_loss_pct=1,
        take_profit_pct=2,
        metadata={"notional_usdt": 1000},
    )
    broker = PaperBroker(equity=10_000)
    observed = ObservedBroker(broker, BrokenBus())
    assert observed.execute_signal(signal) is not None
    assert len(observed.check_positions({"BTC/USDT": 103})) == 1


def test_broken_subscriber_and_projection_are_contained() -> None:
    bus, store = DashboardEventBus(), DashboardStore()
    bus.add_listener(lambda _event: (_ for _ in ()).throw(RuntimeError("broken")))
    bus.add_listener(store.handle_event)
    bus.publish("cycle_completed", {"contexts_built": 1})
    assert store.snapshot().cycles == 1
    store.handle_event(None)


def test_engine_tap_transparency_with_deterministic_counts() -> None:
    from trading_bot.paper.paper_cycle import CycleStageCounts

    bus = DashboardEventBus()
    tap = ObservedEngine(None, bus)
    counts = CycleStageCounts(contexts_built=2, risk_accepted=1, risk_rejected=0, orders_created=1)
    tap._emit_from_counts(counts)
    assert bus.recent()[-1].type == "cycle_completed"


def test_direct_and_observed_empty_cycles_are_identical() -> None:
    """The dashboard tap preserves a deterministic canonical NO_TRADE cycle."""
    from trading_bot.paper.paper_cycle import PaperCycleEngine
    from trading_bot.research.asset_intelligence.registry import CryptoAssetAgentRegistry
    from trading_bot.research.strategy_router import StrategyRouter
    from trading_bot.risk.manager import RiskManager

    settings = build_demo_settings(mode="paper")

    def engine(broker, router):
        return PaperCycleEngine(
            asset_registry=CryptoAssetAgentRegistry(),
            router=router,
            strategy_map={},
            families={},
            risk_manager=RiskManager(risk=settings.risk, equity=broker.equity),
            broker=broker,
            indicator_fn=lambda _candles: {},
        )

    direct_counts = engine(PaperBroker(equity=1000), StrategyRouter()).run_cycle_sync({}, {})
    bus = DashboardEventBus()
    observed = ObservedEngine(
        engine(
            PaperBroker(equity=1000),
            ObservedRouter(StrategyRouter(), bus),
        ),
        bus,
    )
    observed_counts = observed.run_cycle_sync({}, {})
    assert direct_counts.to_dict() == observed_counts.to_dict()
    assert observed_counts.orders_created == 0
