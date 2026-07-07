from __future__ import annotations

from pathlib import Path

from trading_bot.config.risk import DefensiveBlocks, Risk
from trading_bot.paper.broker import PaperBroker
from trading_bot.scanner.types import MarketSnapshot


def _risk() -> Risk:
    return Risk.model_construct(
        max_risk_per_trade_pct=1.0,
        max_daily_loss_pct=3.0,
        max_weekly_loss_pct=7.0,
        max_daily_drawdown_pct=5.0,
        max_total_drawdown_pct=15.0,
        max_open_positions=2,
        max_trades_per_day=100,
        max_consecutive_losses=3,
        consecutive_loss_cooldown_minutes=60,
        max_asset_exposure_pct=20.0,
        max_total_exposure_pct=80.0,
        min_order_notional_usdt=10.0,
        max_order_notional_usdt=1_000.0,
        default_stop_loss_pct=0.5,
        default_take_profit_pct=1.0,
        blocks=DefensiveBlocks.model_construct(),
        kill_switch_enabled=False,
        live_trading_enabled=False,
    )


def _snapshot(
    symbol: str,
    *,
    active: bool,
    last_price: float,
    spread_bps: float,
    rank_score: float,
    timestamp: int,
) -> MarketSnapshot:
    return MarketSnapshot(
        symbol=symbol,
        last_price=last_price,
        volume_24h_usdt=10_000_000.0,
        spread_bps=spread_bps,
        atr_pct=1.0,
        volatility_pct=1.0,
        active=active,
        rejection_reason=None if active else "spread_above_threshold",
        timestamp=timestamp,
        rank_score=rank_score,
    )


def test_broker_opens_position_for_active_snapshot(tmp_path: Path) -> None:
    with PaperBroker(f"sqlite:///{tmp_path}/paper.db") as broker:
        summary = broker.reconcile_session(
            "session-1",
            [
                _snapshot(
                    "BTC/USDT",
                    active=True,
                    last_price=100.0,
                    spread_bps=10.0,
                    rank_score=0.9,
                    timestamp=1_700_000_000_000,
                )
            ],
            _risk(),
        )
    assert summary.fills_opened == 1
    assert summary.fills_closed == 0
    assert len(summary.open_positions) == 1
    assert summary.ending_cash < 10_000.0
    assert summary.ending_equity > 0.0


def test_broker_closes_position_when_symbol_turns_inactive(tmp_path: Path) -> None:
    with PaperBroker(f"sqlite:///{tmp_path}/paper.db") as broker:
        broker.reconcile_session(
            "session-1",
            [
                _snapshot(
                    "BTC/USDT",
                    active=True,
                    last_price=100.0,
                    spread_bps=10.0,
                    rank_score=0.9,
                    timestamp=1_700_000_000_000,
                )
            ],
            _risk(),
        )
        summary = broker.reconcile_session(
            "session-2",
            [
                _snapshot(
                    "BTC/USDT",
                    active=False,
                    last_price=110.0,
                    spread_bps=10.0,
                    rank_score=0.0,
                    timestamp=1_700_000_060_000,
                )
            ],
            _risk(),
        )
    assert summary.fills_closed == 1
    assert len(summary.closed_trades) == 1
    assert not summary.open_positions
    assert summary.realized_pnl > 0.0
    assert summary.win_rate_closed == 1.0


def test_broker_respects_max_open_positions(tmp_path: Path) -> None:
    risk = _risk().model_copy(update={"max_open_positions": 1})
    with PaperBroker(f"sqlite:///{tmp_path}/paper.db") as broker:
        summary = broker.reconcile_session(
            "session-1",
            [
                _snapshot(
                    "BTC/USDT",
                    active=True,
                    last_price=100.0,
                    spread_bps=8.0,
                    rank_score=0.9,
                    timestamp=1_700_000_000_000,
                ),
                _snapshot(
                    "ETH/USDT",
                    active=True,
                    last_price=200.0,
                    spread_bps=8.0,
                    rank_score=0.5,
                    timestamp=1_700_000_000_000,
                ),
            ],
            risk,
        )
    assert summary.fills_opened == 1
    assert len(summary.open_positions) == 1
    assert summary.open_positions[0].symbol == "BTC/USDT"


def test_broker_stops_new_entries_after_daily_trade_limit(tmp_path: Path) -> None:
    risk = _risk().model_copy(update={"max_trades_per_day": 1, "max_open_positions": 1})
    with PaperBroker(f"sqlite:///{tmp_path}/paper.db") as broker:
        broker.reconcile_session(
            "session-1",
            [
                _snapshot(
                    "BTC/USDT",
                    active=True,
                    last_price=100.0,
                    spread_bps=8.0,
                    rank_score=0.9,
                    timestamp=1_700_000_000_000,
                )
            ],
            risk,
        )
        summary = broker.reconcile_session(
            "session-2",
            [
                _snapshot(
                    "BTC/USDT",
                    active=False,
                    last_price=100.0,
                    spread_bps=8.0,
                    rank_score=0.0,
                    timestamp=1_700_000_060_000,
                ),
                _snapshot(
                    "ETH/USDT",
                    active=True,
                    last_price=100.0,
                    spread_bps=8.0,
                    rank_score=0.9,
                    timestamp=1_700_000_060_000,
                ),
            ],
            risk,
        )
    assert summary.fills_opened == 0
    assert "max_trades_per_day_reached" in summary.risk_events


def test_broker_enters_cooldown_after_consecutive_losses(tmp_path: Path) -> None:
    risk = _risk().model_copy(
        update={
            "max_consecutive_losses": 1,
            "consecutive_loss_cooldown_minutes": 60,
            "max_open_positions": 1,
        }
    )
    with PaperBroker(f"sqlite:///{tmp_path}/paper.db") as broker:
        broker.reconcile_session(
            "session-1",
            [
                _snapshot(
                    "BTC/USDT",
                    active=True,
                    last_price=100.0,
                    spread_bps=8.0,
                    rank_score=0.9,
                    timestamp=1_700_000_000_000,
                )
            ],
            risk,
        )
        summary = broker.reconcile_session(
            "session-2",
            [
                _snapshot(
                    "BTC/USDT",
                    active=False,
                    last_price=90.0,
                    spread_bps=8.0,
                    rank_score=0.0,
                    timestamp=1_700_000_060_000,
                ),
                _snapshot(
                    "ETH/USDT",
                    active=True,
                    last_price=100.0,
                    spread_bps=8.0,
                    rank_score=0.9,
                    timestamp=1_700_000_060_000,
                ),
            ],
            risk,
        )
    assert summary.fills_closed == 1
    assert summary.fills_opened == 0
    assert "cooldown_active" in summary.risk_events


def test_broker_caps_position_size_by_asset_exposure(tmp_path: Path) -> None:
    risk = _risk().model_copy(
        update={
            "max_asset_exposure_pct": 5.0,
            "max_total_exposure_pct": 10.0,
        }
    )
    with PaperBroker(f"sqlite:///{tmp_path}/paper.db") as broker:
        summary = broker.reconcile_session(
            "session-1",
            [
                _snapshot(
                    "BTC/USDT",
                    active=True,
                    last_price=100.0,
                    spread_bps=10.0,
                    rank_score=0.9,
                    timestamp=1_700_000_000_000,
                )
            ],
            risk,
        )
    assert len(summary.open_positions) == 1
    assert summary.open_positions[0].notional_usdt <= 500.0
