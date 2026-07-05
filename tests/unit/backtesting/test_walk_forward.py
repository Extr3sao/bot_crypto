"""Walk-forward tests (TSK-104 F3).

Pine contract:
- `WalkForwardSplit(train_start, train_end, test_start, test_end)` enforces
  `train_start < train_end < test_start < test_end` in `__post_init__`.
- `BacktestEngine.walk_forward_run(inputs)` returns list[list[BacktestResult]]:
  outer = folds in order, inner = per-symbol results.
- Data-leakage check: if `split[i].test_end > split[i+1].test_start`, ValueError.
- OOS-only window per ADR-0012 DoD: each fold runs only the test window.
- Empty `walk_forward_splits` returns `[]`.
"""

from __future__ import annotations

import dataclasses
import datetime
from collections.abc import Iterator

import pytest

from trading_bot.backtesting.engine import BacktestEngine
from trading_bot.backtesting.types import (
    OHLCV,
    BacktestContext,
    BacktestInputs,
    BacktestResult,
    OHLCVSourceProtocol,
    Order,
    WalkForwardSplit,
)


def _split(
    train_start: datetime.datetime,
    train_end: datetime.datetime,
    test_start: datetime.datetime,
    test_end: datetime.datetime,
) -> WalkForwardSplit:
    return WalkForwardSplit(
        train_start=train_start,
        train_end=train_end,
        test_start=test_start,
        test_end=test_end,
    )


def _src() -> OHLCVSourceProtocol:
    return _StubOHLCVSource()


# ===========================================================================
# WalkForwardSplit invariant
# ===========================================================================


def test_walk_forward_split_valid_ordering() -> None:
    """Valid: train_start < train_end < test_start < test_end."""
    s = _split(
        datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC),
        datetime.datetime(2025, 6, 1, tzinfo=datetime.UTC),
        datetime.datetime(2025, 7, 1, tzinfo=datetime.UTC),
        datetime.datetime(2025, 12, 31, tzinfo=datetime.UTC),
    )
    assert s.train_start == datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC)
    assert s.test_end == datetime.datetime(2025, 12, 31, tzinfo=datetime.UTC)


def test_walk_forward_split_rejects_train_end_after_test_start() -> None:
    """Invalid: train_end >= test_start violates invariant."""
    with pytest.raises(ValueError, match="WalkForwardSplit invariant violated"):
        _split(
            datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC),
            datetime.datetime(2025, 7, 1, tzinfo=datetime.UTC),  # train_end == test_start
            datetime.datetime(2025, 7, 1, tzinfo=datetime.UTC),
            datetime.datetime(2025, 12, 31, tzinfo=datetime.UTC),
        )


def test_walk_forward_split_rejects_test_before_train_end() -> None:
    """Invalid: test_start < train_end violates invariant."""
    with pytest.raises(ValueError, match="WalkForwardSplit invariant violated"):
        _split(
            datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC),
            datetime.datetime(2025, 12, 31, tzinfo=datetime.UTC),  # train_end > test_start
            datetime.datetime(2025, 6, 1, tzinfo=datetime.UTC),
            datetime.datetime(2025, 12, 31, tzinfo=datetime.UTC),
        )


def test_walk_forward_split_frozen() -> None:
    """Frozen dataclass: mutation raises FrozenInstanceError."""
    s = _split(
        datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC),
        datetime.datetime(2025, 6, 1, tzinfo=datetime.UTC),
        datetime.datetime(2025, 7, 1, tzinfo=datetime.UTC),
        datetime.datetime(2025, 12, 31, tzinfo=datetime.UTC),
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.test_start = datetime.datetime(2025, 8, 1, tzinfo=datetime.UTC)  # type: ignore[misc]


# ===========================================================================
# walk_forward_run: OOS window + ordering
# ===========================================================================


def test_walk_forward_run_empty_splits_returns_empty_list() -> None:
    """No folds -> []."""
    inputs: BacktestInputs = {
        "symbols": "BTC/USDT",
        "timeframe": "1m",
        "walk_forward_splits": [],
    }
    engine = BacktestEngine(
        _src(), _AlwaysBuyThenSellAfterN(sell_after_bars=2), initial_capital=10_000.0
    )
    result = engine.walk_forward_run(inputs)
    assert result == []


def test_walk_forward_run_two_folds_returns_two_results() -> None:
    """Two non-overlapping folds -> list[length 2]."""
    from trading_bot.backtesting.types import OHLCV

    fold1_test_start = datetime.datetime(2025, 2, 1, tzinfo=datetime.UTC)
    fold1_test_end = datetime.datetime(2025, 3, 1, tzinfo=datetime.UTC)
    fold2_test_start = datetime.datetime(2025, 4, 1, tzinfo=datetime.UTC)
    fold2_test_end = datetime.datetime(2025, 5, 1, tzinfo=datetime.UTC)

    class _Src:
        def iter_candles(self, symbol: str, start: int, end: int) -> Iterator[OHLCV]:
            n = (end - start) // 60_000
            for i in range(n + 1):
                yield OHLCV(
                    symbol=symbol,
                    timestamp=start + i * 60_000,
                    open=100.0,
                    high=100.0,
                    low=100.0,
                    close=100.0,
                    volume=1.0,
                )

    inputs: BacktestInputs = {
        "symbols": "BTC/USDT",
        "timeframe": "1m",
        "walk_forward_splits": [
            _split(
                datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC),
                datetime.datetime(2025, 1, 31, tzinfo=datetime.UTC),
                fold1_test_start,
                fold1_test_end,
            ),
            _split(
                fold1_test_end,
                datetime.datetime(2025, 3, 15, tzinfo=datetime.UTC),
                fold2_test_start,
                fold2_test_end,
            ),
        ],
    }
    engine = BacktestEngine(
        _Src(), _AlwaysBuyThenSellAfterN(sell_after_bars=2), initial_capital=10_000.0
    )
    results = engine.walk_forward_run(inputs)

    assert len(results) == 2
    assert all(isinstance(r, list) and len(r) == 1 for r in results)
    assert all(isinstance(r[0], BacktestResult) for r in results)


def test_walk_forward_run_data_leakage_raises_value_error() -> None:
    """split[i].test_end > split[i+1].test_start -> ValueError (fail-loud)."""
    # fold1: train Jan, test Feb 1 - Mar 1.
    # fold2: train Jan 15 - Feb 10, test Feb 15 - Feb 28. fold2.test_start (Feb 15)
    # is BEFORE fold1.test_end (Mar 1) -> engine leakage check fires.
    fold1_test_end = datetime.datetime(2025, 3, 1, tzinfo=datetime.UTC)
    fold2_test_start = datetime.datetime(2025, 2, 15, tzinfo=datetime.UTC)  # Overlap with fold1

    inputs: BacktestInputs = {
        "symbols": "BTC/USDT",
        "timeframe": "1m",
        "walk_forward_splits": [
            _split(
                datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC),
                datetime.datetime(2025, 1, 31, tzinfo=datetime.UTC),
                datetime.datetime(2025, 2, 1, tzinfo=datetime.UTC),
                fold1_test_end,
            ),
            _split(
                datetime.datetime(2025, 1, 15, tzinfo=datetime.UTC),
                datetime.datetime(2025, 2, 10, tzinfo=datetime.UTC),
                fold2_test_start,
                datetime.datetime(2025, 2, 28, tzinfo=datetime.UTC),
            ),
        ],
    }
    engine = BacktestEngine(
        _src(), _AlwaysBuyThenSellAfterN(sell_after_bars=2), initial_capital=10_000.0
    )
    with pytest.raises(ValueError, match="Walk-forward data leakage detected"):
        engine.walk_forward_run(inputs)


def test_walk_forward_run_multi_symbol_returns_per_symbol_per_fold() -> None:
    """Multi-symbol inputs return nested list[list[BacktestResult]] shape."""
    from trading_bot.backtesting.types import OHLCV

    fold1_test_start = datetime.datetime(2025, 2, 1, tzinfo=datetime.UTC)
    fold1_test_end = datetime.datetime(2025, 2, 28, tzinfo=datetime.UTC)
    fold2_test_start = datetime.datetime(2025, 3, 15, tzinfo=datetime.UTC)
    fold2_test_end = datetime.datetime(2025, 4, 14, tzinfo=datetime.UTC)

    class _MultiSrc:
        def iter_candles(self, symbol: str, start: int, end: int) -> Iterator[OHLCV]:
            n = (end - start) // 60_000
            for i in range(n + 1):
                yield OHLCV(
                    symbol=symbol,
                    timestamp=start + i * 60_000,
                    open=100.0,
                    high=100.0,
                    low=100.0,
                    close=100.0,
                    volume=1.0,
                )

    inputs: BacktestInputs = {
        "symbols": ["BTC/USDT", "ETH/USDT"],
        "timeframe": "1m",
        "walk_forward_splits": [
            _split(
                datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC),
                datetime.datetime(2025, 1, 31, tzinfo=datetime.UTC),
                fold1_test_start,
                fold1_test_end,
            ),
            _split(
                fold1_test_end,
                datetime.datetime(2025, 3, 14, tzinfo=datetime.UTC),
                fold2_test_start,
                fold2_test_end,
            ),
        ],
    }
    engine = BacktestEngine(
        _MultiSrc(), _AlwaysBuyThenSellAfterN(sell_after_bars=2), initial_capital=10_000.0
    )
    results = engine.walk_forward_run(inputs)

    assert len(results) == 2
    # Each fold should have 2 results (per symbol).
    assert all(len(r) == 2 for r in results)
    assert all(r[0].symbol == "BTC/USDT" and r[1].symbol == "ETH/USDT" for r in results)


# ===========================================================================
# Helpers (kept here to avoid coupling to test_engine.py)
# ===========================================================================


class _StubOHLCVSource:
    """Typed stub of OHLCVSourceProtocol for tests that never iterate candles."""

    def iter_candles(self, symbol: str, start: int, end: int) -> Iterator[OHLCV]:
        return iter([])


class _AlwaysBuyThenSellAfterN:
    def __init__(self, sell_after_bars: int, qty: float = 1.0) -> None:
        self._name = f"buy_then_sell_{sell_after_bars}"
        self._sell_after = sell_after_bars
        self._qty = qty
        self._bars_in_position = 0
        self._has_bought = False

    @property
    def name(self) -> str:
        return self._name

    def on_candle(self, ctx: BacktestContext, candle: OHLCV) -> Order | None:
        if not self._has_bought:
            self._has_bought = True
            return Order(
                id="b1",
                symbol=ctx.symbol,
                side="buy",
                qty=self._qty,
                type="market",
                timestamp=candle.timestamp,
            )
        if ctx.position_qty > 0:
            self._bars_in_position += 1
            if self._bars_in_position >= self._sell_after:
                return Order(
                    id="s1",
                    symbol=ctx.symbol,
                    side="sell",
                    qty=self._qty,
                    type="market",
                    timestamp=candle.timestamp,
                )
        return None
