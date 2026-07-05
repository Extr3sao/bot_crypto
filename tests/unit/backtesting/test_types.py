"""Tests for backtest types (TSK-104 F1).

Pine contract:
- All dataclasses are frozen; mutating any field raises
  ``FrozenInstanceError``.
- ``OHLCVSourceProtocol`` and ``StrategyProtocol`` are
  ``@runtime_checkable``: minimal in-test implementations pass
  ``isinstance(x, Protocol)``.
"""

from __future__ import annotations

import dataclasses
import datetime
from collections.abc import Iterator

import pytest

from trading_bot.backtesting.types import (
    OHLCV,
    BacktestContext,
    BacktestResult,
    EquityPoint,
    Fill,
    OHLCVSourceProtocol,
    Order,
    StrategyProtocol,
    Trade,
)

# ===========================================================================
# Immutability tests (all 7 dataclasses)
# ===========================================================================


def test_ohlcv_is_frozen() -> None:
    """OHLCV must be frozen: mutation raises FrozenInstanceError."""
    candle = OHLCV(
        symbol="BTC/USDT",
        timestamp=1_700_000_000_000,
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=10.0,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        candle.close = 99.0  # type: ignore[misc]


def test_order_is_frozen() -> None:
    order = Order(
        id="o1",
        symbol="BTC/USDT",
        side="buy",
        qty=1.0,
        type="market",
        timestamp=1_700_000_000_000,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        order.qty = 2.0  # type: ignore[misc]


def test_fill_is_frozen() -> None:
    fill = Fill(
        order_id="o1",
        symbol="BTC/USDT",
        side="buy",
        qty_filled=1.0,
        fill_price=100.0,
        commission=0.1,
        slippage=0.05,
        timestamp=1_700_000_000_000,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        fill.fill_price = 99.0  # type: ignore[misc]


def test_trade_is_frozen() -> None:
    entry = Fill(
        order_id="o1",
        symbol="BTC/USDT",
        side="buy",
        qty_filled=1.0,
        fill_price=100.0,
        commission=0.1,
        slippage=0.05,
        timestamp=1_700_000_000_000,
    )
    exit_ = Fill(
        order_id="o2",
        symbol="BTC/USDT",
        side="sell",
        qty_filled=1.0,
        fill_price=110.0,
        commission=0.11,
        slippage=0.06,
        timestamp=1_700_000_300_000,
    )
    trade = Trade(
        entry_fill=entry,
        exit_fill=exit_,
        pnl=9.68,
        pnl_pct=0.0968,
        bars_held=3,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        trade.pnl = 0.0  # type: ignore[misc]


def test_equity_point_is_frozen() -> None:
    point = EquityPoint(timestamp=1_700_000_000_000, equity=10_000.0, drawdown_pct=0.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        point.equity = 9_999.0  # type: ignore[misc]


def test_backtest_result_is_frozen() -> None:
    result = BacktestResult(
        strategy_name="buy_and_hold",
        symbol="BTC/USDT",
        timeframe="1m",
        start=datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC),
        end=datetime.datetime(2024, 1, 2, tzinfo=datetime.UTC),
        initial_capital=10_000.0,
        final_equity=10_500.0,
        trades=[],
        equity_curve=[],
        metrics={"total_trades": 0.0},
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.final_equity = 0.0  # type: ignore[misc]


def test_backtest_context_is_frozen() -> None:
    ctx = BacktestContext(
        symbol="BTC/USDT",
        current_time=1_700_000_000_000,
        current_price=100.0,
        equity=10_000.0,
        position_qty=0.0,
        position_avg_price=0.0,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        ctx.equity = 9_999.0  # type: ignore[misc]


# ===========================================================================
# Protocol runtime_checkable compliance
# ===========================================================================


class _MinimalSource:
    """Minimal class implementing OHLCVSourceProtocol for isinstance check."""

    def iter_candles(self, symbol: str, start: int, end: int) -> Iterator[OHLCV]:
        return iter([])


class _MinimalStrategy:
    """Minimal class implementing StrategyProtocol for isinstance check."""

    @property
    def name(self) -> str:
        return "minimal"

    def on_candle(self, ctx: BacktestContext, candle: OHLCV) -> Order | None:
        return None


def test_ohlcv_source_protocol_isinstance() -> None:
    src = _MinimalSource()
    assert isinstance(src, OHLCVSourceProtocol)


def test_strategy_protocol_isinstance() -> None:
    strat = _MinimalStrategy()
    assert isinstance(strat, StrategyProtocol)


def test_ohlcv_source_protocol_rejects_noncompliant() -> None:
    class _NotASource:
        pass

    assert not isinstance(_NotASource(), OHLCVSourceProtocol)
