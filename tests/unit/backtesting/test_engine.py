"""Tests for the BacktestEngine (TSK-104 F1).

Strategy:
- Use a deterministic ``FakeOHLCVSource`` (in-memory list of OHLCVs)
  mirroring the scanner's ``FakeMarketDataSource`` pattern.
- Use a simple ``BuyAndHoldStrategy`` for most tests; parametrize
  one or two tests with a custom strategy for edge cases.
- Verify determinism: two runs with the same input produce identical
  results.
- Verify F1 limitations are documented (no shorting, no partial fills,
  fills at candle close).
"""

from __future__ import annotations

import datetime
from collections.abc import Iterator
from itertools import pairwise

import pytest

from trading_bot.backtesting.engine import BacktestEngine
from trading_bot.backtesting.types import (
    OHLCV,
    BacktestContext,
    OHLCVSourceProtocol,
    Order,
)

# ===========================================================================
# Test doubles
# ===========================================================================


class FakeOHLCVSource:
    """In-memory OHLCV source for tests.

    Implements ``OHLCVSourceProtocol``. Filters the in-memory list by
    ``symbol`` and ``[start, end]`` (epoch ms inclusive on both ends).
    """

    def __init__(self, candles: list[OHLCV]) -> None:
        self._candles = sorted(candles, key=lambda c: c.timestamp)

    def iter_candles(self, symbol: str, start: int, end: int) -> Iterator[OHLCV]:
        for c in self._candles:
            if c.symbol != symbol:
                continue
            if c.timestamp < start or c.timestamp > end:
                continue
            yield c


class _AlwaysBuyThenSellAfterN:
    """Strategy that buys first, sells after N bars."""

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


def _make_flat_candles(
    symbol: str,
    n: int,
    *,
    price: float = 100.0,
    start_ms: int = 1_700_000_000_000,
    interval_ms: int = 60_000,
) -> list[OHLCV]:
    """Build n flat candles at a constant price (no movement)."""
    return [
        OHLCV(
            symbol=symbol,
            timestamp=start_ms + i * interval_ms,
            open=price,
            high=price,
            low=price,
            close=price,
            volume=1.0,
        )
        for i in range(n)
    ]


def _make_rising_candles(
    symbol: str,
    n: int,
    *,
    start_price: float = 100.0,
    step: float = 1.0,
    start_ms: int = 1_700_000_000_000,
    interval_ms: int = 60_000,
) -> list[OHLCV]:
    """Build n rising candles (close = start_price + i * step)."""
    return [
        OHLCV(
            symbol=symbol,
            timestamp=start_ms + i * interval_ms,
            open=start_price + i * step,
            high=start_price + i * step + 0.5,
            low=start_price + i * step - 0.5,
            close=start_price + (i + 1) * step,
            volume=1.0,
        )
        for i in range(n)
    ]


def _to_dt(ms: int) -> datetime.datetime:
    return datetime.datetime.fromtimestamp(ms / 1000, tz=datetime.UTC)


# ===========================================================================
# Engine tests
# ===========================================================================


def test_engine_produces_protocol_compliant_source() -> None:
    """FakeOHLCVSource must pass isinstance(source, OHLCVSourceProtocol)."""
    src = FakeOHLCVSource(_make_flat_candles("BTC/USDT", 5))
    assert isinstance(src, OHLCVSourceProtocol)


def test_engine_empty_source_returns_empty_result() -> None:
    """0 candles -> 0 trades, 0 equity points, final_equity = initial."""
    src = FakeOHLCVSource([])
    strat = _AlwaysBuyThenSellAfterN(sell_after_bars=2)
    engine = BacktestEngine(src, strat, initial_capital=10_000.0)

    start = _to_dt(1_700_000_000_000)
    end = _to_dt(1_700_000_000_000 + 5 * 60_000)
    result = engine.run("BTC/USDT", start, end)

    assert result.trades == []
    assert result.equity_curve == []
    assert result.final_equity == 10_000.0
    assert result.metrics["total_trades"] == 0.0


def test_engine_buy_then_sell_produces_one_trade() -> None:
    """Buy on first candle, sell after 2 bars: exactly 1 trade."""
    src = FakeOHLCVSource(_make_flat_candles("BTC/USDT", 5))
    strat = _AlwaysBuyThenSellAfterN(sell_after_bars=2)
    engine = BacktestEngine(src, strat, initial_capital=10_000.0)

    start = _to_dt(1_700_000_000_000)
    end = _to_dt(1_700_000_000_000 + 5 * 60_000)
    result = engine.run("BTC/USDT", start, end)

    assert len(result.trades) == 1
    # Flat price: pnl = 0 - commissions - 2 * slippage
    trade = result.trades[0]
    assert trade.pnl < 0  # lost money to fees
    assert trade.bars_held >= 2


def test_engine_commissions_reduce_pnl() -> None:
    """Higher commission -> more negative pnl on a flat-price trade.

    IMPORTANT: each engine must get a FRESH strategy instance because
    ``_AlwaysBuyThenSellAfterN`` is stateful (``_has_bought``,
    ``_bars_in_position``). Sharing a strategy across engines leaks
    state between runs and produces non-deterministic results.
    """
    src = FakeOHLCVSource(_make_flat_candles("BTC/USDT", 5))

    low_comm = BacktestEngine(
        src,
        _AlwaysBuyThenSellAfterN(sell_after_bars=2),
        commission=0.0001,
        initial_capital=10_000.0,
    )
    high_comm = BacktestEngine(
        src,
        _AlwaysBuyThenSellAfterN(sell_after_bars=2),
        commission=0.01,
        initial_capital=10_000.0,
    )

    start = _to_dt(1_700_000_000_000)
    end = _to_dt(1_700_000_000_000 + 5 * 60_000)
    res_low = low_comm.run("BTC/USDT", start, end)
    res_high = high_comm.run("BTC/USDT", start, end)

    assert len(res_low.trades) == 1
    assert len(res_high.trades) == 1
    assert res_low.trades[0].pnl > res_high.trades[0].pnl  # higher comm = more loss


def test_engine_slippage_reduces_pnl() -> None:
    """Higher slippage -> more negative pnl on a flat-price trade.

    Each engine gets a fresh strategy (see stateful-strategy note in
    ``test_engine_commissions_reduce_pnl``).
    """
    src = FakeOHLCVSource(_make_flat_candles("BTC/USDT", 5))

    low_slip = BacktestEngine(
        src,
        _AlwaysBuyThenSellAfterN(sell_after_bars=2),
        slippage_bps=0.0,
        initial_capital=10_000.0,
    )
    high_slip = BacktestEngine(
        src,
        _AlwaysBuyThenSellAfterN(sell_after_bars=2),
        slippage_bps=50.0,
        initial_capital=10_000.0,
    )

    start = _to_dt(1_700_000_000_000)
    end = _to_dt(1_700_000_000_000 + 5 * 60_000)
    res_low = low_slip.run("BTC/USDT", start, end)
    res_high = high_slip.run("BTC/USDT", start, end)

    assert len(res_low.trades) == 1
    assert len(res_high.trades) == 1
    assert res_low.trades[0].pnl > res_high.trades[0].pnl


def test_engine_determinism_two_runs_identical() -> None:
    """Same input -> same output (no random, no set iteration).

    Each engine gets a fresh strategy to avoid state leaks.
    """
    src = FakeOHLCVSource(_make_rising_candles("BTC/USDT", 10, step=0.5))

    start = _to_dt(1_700_000_000_000)
    end = _to_dt(1_700_000_000_000 + 10 * 60_000)

    e1 = BacktestEngine(
        src,
        _AlwaysBuyThenSellAfterN(sell_after_bars=3),
        initial_capital=10_000.0,
    )
    e2 = BacktestEngine(
        src,
        _AlwaysBuyThenSellAfterN(sell_after_bars=3),
        initial_capital=10_000.0,
    )
    r1 = e1.run("BTC/USDT", start, end)
    r2 = e2.run("BTC/USDT", start, end)

    assert len(r1.trades) == 1
    assert len(r2.trades) == 1
    assert r1.metrics == r2.metrics
    assert r1.final_equity == r2.final_equity
    assert len(r1.equity_curve) == len(r2.equity_curve)


def test_engine_equity_curve_length_matches_candles() -> None:
    """equity_curve has 1 point per processed candle (1 per minute)."""
    n = 7
    src = FakeOHLCVSource(_make_rising_candles("BTC/USDT", n))
    strat = _AlwaysBuyThenSellAfterN(sell_after_bars=3)
    engine = BacktestEngine(src, strat, initial_capital=10_000.0)

    start = _to_dt(1_700_000_000_000)
    end = _to_dt(1_700_000_000_000 + n * 60_000)
    result = engine.run("BTC/USDT", start, end)

    assert len(result.equity_curve) == n


def test_engine_mark_to_market_tracks_open_position() -> None:
    """With an open position, equity_curve reflects unrealized PnL.

    Rising prices: each candle's equity should be >= previous.
    """
    n = 5
    src = FakeOHLCVSource(_make_rising_candles("BTC/USDT", n, start_price=100.0, step=2.0))

    # Strategy that never sells -> position stays open until end.
    class _NeverSell:
        @property
        def name(self) -> str:
            return "never_sell"

        def on_candle(self, ctx: BacktestContext, candle: OHLCV) -> Order | None:
            if ctx.position_qty == 0.0:
                return Order(
                    id="b1",
                    symbol=ctx.symbol,
                    side="buy",
                    qty=1.0,
                    type="market",
                    timestamp=candle.timestamp,
                )
            return None

    engine = BacktestEngine(src, _NeverSell(), initial_capital=10_000.0)
    start = _to_dt(1_700_000_000_000)
    end = _to_dt(1_700_000_000_000 + n * 60_000)
    result = engine.run("BTC/USDT", start, end)

    # Equity is non-decreasing on rising prices.
    equities = [p.equity for p in result.equity_curve]
    for prev, curr in pairwise(equities):
        assert curr >= prev - 1e-6  # allow tiny float epsilon


def test_engine_source_raises_propagates_exception() -> None:
    """Source that raises mid-iteration: engine re-raises (fail-fast)."""

    class _RaisingSource:
        def __init__(self) -> None:
            self._n = 0

        def iter_candles(self, symbol: str, start: int, end: int) -> Iterator[OHLCV]:
            for c in _make_flat_candles(symbol, 5):
                self._n += 1
                if self._n == 3:
                    raise RuntimeError("simulated source failure")
                yield c

    engine = BacktestEngine(
        _RaisingSource(), _AlwaysBuyThenSellAfterN(sell_after_bars=2), initial_capital=10_000.0
    )
    start = _to_dt(1_700_000_000_000)
    end = _to_dt(1_700_000_000_000 + 5 * 60_000)

    with pytest.raises(RuntimeError, match="simulated source failure"):
        engine.run("BTC/USDT", start, end)


def test_engine_metrics_have_required_keys() -> None:
    """F1 metrics: total_trades, win_rate, profit_factor, final_equity."""
    src = FakeOHLCVSource(_make_rising_candles("BTC/USDT", 5))
    strat = _AlwaysBuyThenSellAfterN(sell_after_bars=2)
    engine = BacktestEngine(src, strat, initial_capital=10_000.0)

    start = _to_dt(1_700_000_000_000)
    end = _to_dt(1_700_000_000_000 + 5 * 60_000)
    result = engine.run("BTC/USDT", start, end)

    for key in ("total_trades", "win_rate", "profit_factor", "final_equity"):
        assert key in result.metrics
