from __future__ import annotations

import json
import time

from trading_bot.paper.broker import PaperBroker
from trading_bot.paper_dashboard.events import DashboardEventBus
from trading_bot.paper_dashboard.projection import DashboardStore
from trading_bot.paper_dashboard.taps import ObservedBroker


def connected() -> tuple[DashboardEventBus, DashboardStore]:
    bus, store = DashboardEventBus(), DashboardStore()
    bus.add_listener(store.handle_event)
    return bus, store


def test_snapshot_defaults_are_safe() -> None:
    assert DashboardStore().snapshot().runtime_status == "STOPPED"


def test_position_open_and_close_projection() -> None:
    bus, store = connected()
    bus.publish(
        "position_opened",
        {
            "symbol": "BTC/USDT",
            "side": "buy",
            "entry_price": 100,
            "quantity": 1,
            "stop_loss_pct": 1,
            "take_profit_pct": 2,
            "strategy": "demo",
        },
    )
    assert store.snapshot().open_positions[0]["take_profit_price"] == 102
    bus.publish(
        "position_closed",
        {
            "symbol": "BTC/USDT",
            "side": "buy",
            "entry_price": 100,
            "exit_price": 101,
            "quantity": 1,
            "pnl": 1,
            "closed_at": time.time(),
            "exit_reason": "signal",
        },
    )
    snap = store.snapshot()
    assert snap.positions_open == 0 and snap.positions_closed == 1 and snap.wins == 1


def test_sl_tp_and_unrealized_pnl() -> None:
    bus, store = connected()
    bus.publish(
        "position_opened",
        {
            "symbol": "ETH/USDT",
            "side": "sell",
            "entry_price": 50,
            "quantity": 2,
            "stop_loss_pct": 1,
            "take_profit_pct": 2,
        },
    )
    store.update_prices({"ETH/USDT": 49})
    assert store.snapshot().unrealized_pnl == 2
    bus.publish(
        "sl_triggered",
        {
            "symbol": "ETH/USDT",
            "side": "sell",
            "entry_price": 50,
            "exit_price": 51,
            "pnl": -2,
            "closed_at": time.time(),
            "exit_reason": "stop_loss",
        },
    )
    assert store.snapshot().losses == 1


def test_cycle_router_risk_and_json_projection() -> None:
    bus, store = connected()
    bus.publish("context_built", {"symbol": "BTC/USDT", "regime": "TRENDING_UP"})
    bus.publish(
        "strategy_selected", {"symbol": "BTC/USDT", "strategy": "momentum", "direction": "LONG"}
    )
    bus.publish(
        "signal_rejected",
        {"symbol": "ETH/USDT", "stage": "router", "reason": "NO_TRADE:no_strategy"},
    )
    bus.publish("risk_accepted", {"count": 1})
    bus.publish("risk_rejected", {"symbol": "SOL/USDT", "reason": "max_exposure"})
    for _ in range(2):
        bus.publish(
            "cycle_completed",
            {
                "contexts_built": 1,
                "signals_generated": 1,
                "risk_accepted": 1,
                "risk_rejected": 0,
                "orders_created": 0,
                "router_no_trade": 1,
            },
        )
    snap = store.snapshot()
    assert snap.cycles == 2 and snap.contexts_built == 3
    assert snap.assets[0]["symbol"] == "BTC/USDT"
    assert "secret" not in json.dumps(snap.to_dict()).lower()


def test_sync_reads_canonical_broker_without_mutation() -> None:
    broker = PaperBroker(equity=1000)
    store = DashboardStore()
    store.sync_runtime(broker=broker, running=True)
    assert store.snapshot().equity == 1000 and store.snapshot().runtime_status == "RUNNING"


def test_observed_broker_feeds_projection() -> None:
    from trading_bot.strategies.types import Signal

    broker = PaperBroker(equity=10_000, slippage_bps=0, commission_bps=0)
    bus, store = connected()
    observed = ObservedBroker(broker, bus)
    signal = Signal(
        symbol="BTC/USDT",
        side="buy",
        strategy_name="demo",
        timeframe="5m",
        confidence=0.8,
        price=100,
        stop_loss_pct=1,
        take_profit_pct=2,
        metadata={"notional_usdt": 1000},
    )
    assert observed.execute_signal(signal) is not None
    assert store.snapshot().positions_open == 1
    assert len(observed.check_positions({"BTC/USDT": 103})) == 1
    assert store.snapshot().positions_closed == 1
