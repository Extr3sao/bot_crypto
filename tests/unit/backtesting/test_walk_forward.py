"""Tests for walk-forward execution helpers (TSK-104 F3b)."""

from __future__ import annotations

import datetime

import pytest

from trading_bot.backtesting.engine import BacktestEngine
from trading_bot.backtesting.types import BacktestContext, BacktestInputs, OHLCV, Order
from trading_bot.backtesting.walk_forward import walk_forward_run
from tests.unit.backtesting.test_engine import FakeOHLCVSource, _make_flat_candles


class _BuyThenSell:
    @property
    def name(self) -> str:
        return "wf-demo"

    def __init__(self) -> None:
        self._has_bought = False
        self._bars = 0

    def on_candle(self, ctx: BacktestContext, candle: OHLCV) -> Order | None:
        if not self._has_bought:
            self._has_bought = True
            return Order(
                id="b1",
                symbol=ctx.symbol,
                side="buy",
                qty=1.0,
                type="market",
                timestamp=candle.timestamp,
            )
        if ctx.position_qty > 0.0:
            self._bars += 1
            if self._bars >= 1:
                return Order(
                    id="s1",
                    symbol=ctx.symbol,
                    side="sell",
                    qty=1.0,
                    type="market",
                    timestamp=candle.timestamp,
                )
        return None


def test_walk_forward_run_requires_at_least_one_fold() -> None:
    engine = BacktestEngine(FakeOHLCVSource([]), _BuyThenSell(), strategy_factory=_BuyThenSell)
    inputs = BacktestInputs(
        symbols="BTC/USDT",
        start=datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC),
        end=datetime.datetime(2024, 1, 31, tzinfo=datetime.UTC),
    )
    with pytest.raises(ValueError, match="al menos un fold"):
        walk_forward_run(engine, inputs)


def test_walk_forward_run_returns_one_result_per_fold_for_single_symbol() -> None:
    candles = _make_flat_candles("BTC/USDT", 20, interval_ms=86_400_000)
    engine = BacktestEngine(
        FakeOHLCVSource(candles),
        _BuyThenSell(),
        strategy_factory=_BuyThenSell,
        initial_capital=10_000.0,
    )
    inputs = BacktestInputs(
        symbols="BTC/USDT",
        start=datetime.datetime(2023, 11, 14, tzinfo=datetime.UTC),
        end=datetime.datetime(2023, 12, 10, tzinfo=datetime.UTC),
        timeframe="1d",
        walk_forward_splits=[
            (
                datetime.datetime(2023, 11, 14, tzinfo=datetime.UTC),
                datetime.datetime(2023, 11, 18, tzinfo=datetime.UTC),
                datetime.datetime(2023, 11, 19, tzinfo=datetime.UTC),
                datetime.datetime(2023, 11, 23, tzinfo=datetime.UTC),
            ),
            (
                datetime.datetime(2023, 11, 24, tzinfo=datetime.UTC),
                datetime.datetime(2023, 11, 28, tzinfo=datetime.UTC),
                datetime.datetime(2023, 11, 29, tzinfo=datetime.UTC),
                datetime.datetime(2023, 12, 3, tzinfo=datetime.UTC),
            ),
        ],
    )

    results = walk_forward_run(engine, inputs)
    assert len(results) == 2
    assert all(result.symbol == "BTC/USDT" for result in results)


def test_walk_forward_run_multisymbol_flattens_results_across_folds() -> None:
    candles = _make_flat_candles("BTC/USDT", 20, interval_ms=86_400_000) + _make_flat_candles(
        "ETH/USDT", 20, interval_ms=86_400_000
    )
    engine = BacktestEngine(
        FakeOHLCVSource(candles),
        _BuyThenSell(),
        strategy_factory=_BuyThenSell,
        initial_capital=10_000.0,
    )
    inputs = BacktestInputs(
        symbols=["BTC/USDT", "ETH/USDT"],
        start=datetime.datetime(2023, 11, 14, tzinfo=datetime.UTC),
        end=datetime.datetime(2023, 12, 10, tzinfo=datetime.UTC),
        timeframe="1d",
        walk_forward_splits=[
            (
                datetime.datetime(2023, 11, 14, tzinfo=datetime.UTC),
                datetime.datetime(2023, 11, 18, tzinfo=datetime.UTC),
                datetime.datetime(2023, 11, 19, tzinfo=datetime.UTC),
                datetime.datetime(2023, 11, 23, tzinfo=datetime.UTC),
            ),
            (
                datetime.datetime(2023, 11, 24, tzinfo=datetime.UTC),
                datetime.datetime(2023, 11, 28, tzinfo=datetime.UTC),
                datetime.datetime(2023, 11, 29, tzinfo=datetime.UTC),
                datetime.datetime(2023, 12, 3, tzinfo=datetime.UTC),
            ),
        ],
    )

    results = walk_forward_run(engine, inputs)
    assert len(results) == 4
    assert [result.symbol for result in results] == [
        "BTC/USDT",
        "ETH/USDT",
        "BTC/USDT",
        "ETH/USDT",
    ]


def test_walk_forward_run_preserves_non_leaking_fold_order() -> None:
    candles = _make_flat_candles("BTC/USDT", 30, interval_ms=86_400_000)
    engine = BacktestEngine(
        FakeOHLCVSource(candles),
        _BuyThenSell(),
        strategy_factory=_BuyThenSell,
        initial_capital=10_000.0,
    )
    fold_1_test_end = datetime.datetime(2023, 11, 23, tzinfo=datetime.UTC)
    fold_2_test_start = datetime.datetime(2023, 11, 29, tzinfo=datetime.UTC)
    inputs = BacktestInputs(
        symbols="BTC/USDT",
        start=datetime.datetime(2023, 11, 14, tzinfo=datetime.UTC),
        end=datetime.datetime(2023, 12, 10, tzinfo=datetime.UTC),
        timeframe="1d",
        walk_forward_splits=[
            (
                datetime.datetime(2023, 11, 14, tzinfo=datetime.UTC),
                datetime.datetime(2023, 11, 18, tzinfo=datetime.UTC),
                datetime.datetime(2023, 11, 19, tzinfo=datetime.UTC),
                fold_1_test_end,
            ),
            (
                datetime.datetime(2023, 11, 24, tzinfo=datetime.UTC),
                datetime.datetime(2023, 11, 28, tzinfo=datetime.UTC),
                fold_2_test_start,
                datetime.datetime(2023, 12, 3, tzinfo=datetime.UTC),
            ),
        ],
    )

    results = walk_forward_run(engine, inputs)
    assert len(results) == 2
    assert results[0].end < results[1].start
