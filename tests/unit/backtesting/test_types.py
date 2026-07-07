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
from hypothesis import given
from hypothesis import strategies as st

from trading_bot.backtesting.types import (
    OHLCV,
    BacktestContext,
    BacktestInputs,
    BacktestResult,
    EquityPoint,
    Fill,
    OHLCVSourceProtocol,
    Order,
    StrategyProtocol,
    Trade,
    WalkForwardSplit,
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
        metrics={
            "total_trades": 0.0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "final_equity": 10_500.0,
            "max_drawdown": 0.0,
            "cagr": 0.0,
            "calmar_ratio": 0.0,
            "sharpe_ratio": 0.0,
            "sortino_ratio": 0.0,
            "avg_trade_pnl": 0.0,
            "expectancy": 0.0,
        },
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


def test_backtest_inputs_is_frozen() -> None:
    inputs = BacktestInputs(
        symbols="BTC/USDT",
        start=datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC),
        end=datetime.datetime(2024, 1, 2, tzinfo=datetime.UTC),
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        inputs.timeframe = "5m"  # type: ignore[misc]


def test_backtest_inputs_rejects_empty_symbol_list() -> None:
    with pytest.raises(ValueError, match="al menos un symbol"):
        BacktestInputs(
            symbols=[],
            start=datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC),
            end=datetime.datetime(2024, 1, 2, tzinfo=datetime.UTC),
        )


def test_backtest_inputs_rejects_invalid_fold_order() -> None:
    with pytest.raises(ValueError, match="train_start <= train_end <= test_start <= test_end"):
        BacktestInputs(
            symbols="BTC/USDT",
            start=datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC),
            end=datetime.datetime(2024, 2, 1, tzinfo=datetime.UTC),
            walk_forward_splits=[
                (
                    datetime.datetime(2024, 1, 10, tzinfo=datetime.UTC),
                    datetime.datetime(2024, 1, 20, tzinfo=datetime.UTC),
                    datetime.datetime(2024, 1, 15, tzinfo=datetime.UTC),
                    datetime.datetime(2024, 1, 25, tzinfo=datetime.UTC),
                )
            ],
        )


def test_backtest_inputs_rejects_overlapping_folds() -> None:
    with pytest.raises(ValueError, match="folds no solapados"):
        BacktestInputs(
            symbols="BTC/USDT",
            start=datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC),
            end=datetime.datetime(2024, 3, 1, tzinfo=datetime.UTC),
            walk_forward_splits=[
                (
                    datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC),
                    datetime.datetime(2024, 1, 10, tzinfo=datetime.UTC),
                    datetime.datetime(2024, 1, 11, tzinfo=datetime.UTC),
                    datetime.datetime(2024, 1, 20, tzinfo=datetime.UTC),
                ),
                (
                    datetime.datetime(2024, 1, 20, tzinfo=datetime.UTC),
                    datetime.datetime(2024, 1, 25, tzinfo=datetime.UTC),
                    datetime.datetime(2024, 1, 26, tzinfo=datetime.UTC),
                    datetime.datetime(2024, 2, 5, tzinfo=datetime.UTC),
                ),
            ],
        )


@given(
    st.lists(
        st.tuples(
            st.datetimes(timezones=st.just(datetime.UTC)),
            st.integers(min_value=0, max_value=5),
            st.integers(min_value=0, max_value=5),
            st.integers(min_value=0, max_value=5),
        ),
        min_size=1,
        max_size=5,
    )
)
def test_backtest_inputs_accepts_non_overlapping_walk_forward_splits(
    fold_specs: list[tuple[datetime.datetime, int, int, int]],
) -> None:
    splits: list[WalkForwardSplit] = []
    cursor: datetime.datetime | None = None
    for base, train_days, gap_days, test_days in sorted(fold_specs, key=lambda item: item[0]):
        train_start = max(base, cursor) if cursor is not None else base
        train_end = train_start + datetime.timedelta(days=train_days)
        test_start = train_end + datetime.timedelta(days=gap_days)
        test_end = test_start + datetime.timedelta(days=test_days)
        splits.append((train_start, train_end, test_start, test_end))
        cursor = test_end + datetime.timedelta(seconds=1)

    inputs = BacktestInputs(
        symbols=["BTC/USDT"],
        start=min(split[0] for split in splits),
        end=max(split[3] for split in splits),
        walk_forward_splits=splits,
    )
    assert inputs.walk_forward_splits == splits


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
