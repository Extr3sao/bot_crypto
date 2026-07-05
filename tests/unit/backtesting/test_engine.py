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
import math
from collections.abc import Iterator
from itertools import pairwise

import pytest

from trading_bot.backtesting.engine import BacktestEngine
from trading_bot.backtesting.types import (
    OHLCV,
    BacktestContext,
    EquityPoint,
    Fill,
    OHLCVSourceProtocol,
    Order,
    Trade,
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


# ===========================================================================
# F2 advanced metrics tests (TSK-104 F2)
# ===========================================================================


def test_engine_metrics_zero_trades_all_zeros() -> None:
    """Empty trades -> all 7 F2 advanced metrics = 0.0 (zero state)."""
    src = FakeOHLCVSource(_make_flat_candles("BTC/USDT", 3))
    engine = BacktestEngine(
        src, _AlwaysBuyThenSellAfterN(sell_after_bars=2), initial_capital=10_000.0
    )
    start = _to_dt(1_700_000_000_000)
    end = _to_dt(1_700_000_000_000 + 3 * 60_000)
    metrics = engine._compute_metrics(
        trades=[],
        final_equity=10_000.0,
        equity_curve=[
            EquityPoint(timestamp=1_700_000_000_000, equity=10_000.0, drawdown_pct=0.0),
        ],
        start=start,
        end=end,
        timeframe="1m",
    )
    for key in (
        "max_drawdown",
        "cagr",
        "calmar_ratio",
        "sharpe_ratio",
        "sortino_ratio",
        "avg_trade_pnl",
        "expectancy",
    ):
        assert metrics[key] == 0.0, f"{key} should be 0.0 for zero trades, got {metrics[key]}"


def test_engine_metrics_cagr_doubles_in_one_year() -> None:
    """Mock: 1-year span + final=2x initial -> CAGR = 1.0 (100 percent)."""
    src = FakeOHLCVSource([])
    engine = BacktestEngine(
        src, _AlwaysBuyThenSellAfterN(sell_after_bars=2), initial_capital=10_000.0
    )
    # Use 2025-01-01 -> 2026-01-01 (non-leap-year span => 365 days exactly);
    # 2024 -> 2025 would give 366 days (leap year) and break abs=1e-6 assertion.
    start = datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC)
    end = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    metrics = engine._compute_metrics(
        trades=[],
        final_equity=20_000.0,
        equity_curve=[
            EquityPoint(timestamp=1_700_000_000_000, equity=10_000.0, drawdown_pct=0.0),
            EquityPoint(timestamp=1_701_577_600_000, equity=20_000.0, drawdown_pct=0.0),
        ],
        start=start,
        end=end,
        timeframe="1d",
    )
    assert metrics["cagr"] == pytest.approx(1.0, abs=1e-6)


def test_engine_metrics_perfect_strategy_profit_factor_inf() -> None:
    """All winning trades (no losses) -> profit_factor=inf, sortino=0.0."""
    src = FakeOHLCVSource([])
    engine = BacktestEngine(
        src, _AlwaysBuyThenSellAfterN(sell_after_bars=2), initial_capital=10_000.0
    )
    start = datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC)
    end = datetime.datetime(2024, 1, 2, tzinfo=datetime.UTC)
    winning_trades = [
        Trade(
            entry_fill=Fill(
                order_id=f"o{i}",
                symbol="BTC/USDT",
                side="buy",
                qty_filled=1.0,
                fill_price=100.0,
                commission=0.1,
                slippage=0.05,
                timestamp=1_700_000_000_000 + i * 60_000,
            ),
            exit_fill=Fill(
                order_id=f"s{i}",
                symbol="BTC/USDT",
                side="sell",
                qty_filled=1.0,
                fill_price=110.0,
                commission=0.11,
                slippage=0.06,
                timestamp=1_700_000_300_000 + i * 60_000,
            ),
            pnl=9.78,
            pnl_pct=0.0978,
            bars_held=3,
        )
        for i in range(3)
    ]
    metrics = engine._compute_metrics(
        trades=winning_trades,
        final_equity=10_030.0,
        equity_curve=[
            EquityPoint(timestamp=1_700_000_000_000, equity=10_000.0, drawdown_pct=0.0),
        ],
        start=start,
        end=end,
        timeframe="1d",
    )
    assert metrics["profit_factor"] == float("inf")
    assert metrics["sortino_ratio"] == 0.0  # downside rets empty
    assert metrics["calmar_ratio"] == float("inf")  # no drawdown + positive CAGR


def test_engine_metrics_sharpe_known_returns() -> None:
    """Inject trades with known pnl_pct returns, verify Sharpe = mean/std * sqrt(ppy).

    rets = [0.02, 0.04, 0.06, 0.08] -> mean=0.05, stdev~0.02449, sqrt(365)~19.10,
    expected sharpe ~ 39.00.
    """
    src = FakeOHLCVSource([])
    engine = BacktestEngine(
        src, _AlwaysBuyThenSellAfterN(sell_after_bars=2), initial_capital=10_000.0
    )
    start = datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC)
    end = datetime.datetime(2024, 1, 2, tzinfo=datetime.UTC)
    rets = [0.02, 0.04, 0.06, 0.08]
    asymmetric_trades = [
        Trade(
            entry_fill=Fill(
                order_id=f"o{i}",
                symbol="BTC/USDT",
                side="buy",
                qty_filled=1.0,
                fill_price=100.0,
                commission=0.1,
                slippage=0.05,
                timestamp=1_700_000_000_000 + i * 60_000,
            ),
            exit_fill=Fill(
                order_id=f"s{i}",
                symbol="BTC/USDT",
                side="sell",
                qty_filled=1.0,
                fill_price=100.0 * (1 + r),
                commission=0.11,
                slippage=0.06,
                timestamp=1_700_000_300_000 + i * 60_000,
            ),
            pnl=r * 100.0,
            pnl_pct=r,
            bars_held=3,
        )
        for i, r in enumerate(rets)
    ]
    metrics = engine._compute_metrics(
        trades=asymmetric_trades,
        final_equity=10_200.0,
        equity_curve=[
            EquityPoint(timestamp=1_700_000_000_000, equity=10_000.0, drawdown_pct=0.0),
        ],
        start=start,
        end=end,
        timeframe="1d",
    )
    import statistics

    expected_sharpe = (statistics.mean(rets) / statistics.stdev(rets)) * math.sqrt(365)
    assert metrics["sharpe_ratio"] == pytest.approx(expected_sharpe, rel=1e-3)


def test_engine_initial_capital_zero_raises() -> None:
    """F2 gate: initial_capital <= 0 raises ValueError (F1 had no such gate)."""
    src = FakeOHLCVSource(_make_flat_candles("BTC/USDT", 3))
    with pytest.raises(ValueError, match="initial_capital must be > 0"):
        BacktestEngine(src, _AlwaysBuyThenSellAfterN(sell_after_bars=2), initial_capital=0.0)


# ===========================================================================
# F2 advanced metrics tests — extended coverage (TSK-104 F2 follow-up)
# ===========================================================================


def test_engine_metrics_sharpe_single_trade_gated_to_zero() -> None:
    """Sharpe with n=1 trade: gated to 0.0 (cannot compute sample stdev)."""
    src = FakeOHLCVSource([])
    engine = BacktestEngine(
        src, _AlwaysBuyThenSellAfterN(sell_after_bars=2), initial_capital=10_000.0
    )
    start = datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC)
    end = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    metrics = engine._compute_metrics(
        trades=[
            Trade(
                entry_fill=Fill(
                    order_id="o1",
                    symbol="BTC/USDT",
                    side="buy",
                    qty_filled=1.0,
                    fill_price=100.0,
                    commission=0.1,
                    slippage=0.05,
                    timestamp=1_700_000_000_000,
                ),
                exit_fill=Fill(
                    order_id="s1",
                    symbol="BTC/USDT",
                    side="sell",
                    qty_filled=1.0,
                    fill_price=120.0,
                    commission=0.12,
                    slippage=0.06,
                    timestamp=1_700_000_300_000,
                ),
                pnl=19.67,
                pnl_pct=0.1967,
                bars_held=3,
            )
        ],
        final_equity=10_019.67,
        equity_curve=[
            EquityPoint(timestamp=1_700_000_000_000, equity=10_000.0, drawdown_pct=0.0),
            EquityPoint(timestamp=1_700_000_300_000, equity=10_019.67, drawdown_pct=0.0),
        ],
        start=start,
        end=end,
        timeframe="1d",
    )
    assert metrics["sharpe_ratio"] == 0.0  # gated: n=1 cannot compute stdev


def test_engine_metrics_sortino_mixed_returns_filters_downside() -> None:
    """Sortino: only downside returns (pnl_pct < 0) contribute to denominator.

    rets = [+0.05, -0.01, +0.05, -0.02] -> mean=0.0175, downside_std~0.015, ppy=365.
    """
    src = FakeOHLCVSource([])
    engine = BacktestEngine(
        src, _AlwaysBuyThenSellAfterN(sell_after_bars=2), initial_capital=10_000.0
    )
    start = datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC)
    end = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    rets = [0.05, -0.01, 0.05, -0.02]
    trades_mixed = [
        Trade(
            entry_fill=Fill(
                order_id=f"o{i}",
                symbol="BTC/USDT",
                side="buy",
                qty_filled=1.0,
                fill_price=100.0,
                commission=0.1,
                slippage=0.05,
                timestamp=1_700_000_000_000 + i * 60_000,
            ),
            exit_fill=Fill(
                order_id=f"s{i}",
                symbol="BTC/USDT",
                side="sell",
                qty_filled=1.0,
                fill_price=100.0 * (1 + r),
                commission=0.11,
                slippage=0.06,
                timestamp=1_700_000_300_000 + i * 60_000,
            ),
            pnl=r * 100.0,
            pnl_pct=r,
            bars_held=3,
        )
        for i, r in enumerate(rets)
    ]
    metrics = engine._compute_metrics(
        trades=trades_mixed,
        final_equity=10_070.0,
        equity_curve=[
            EquityPoint(timestamp=1_700_000_000_000, equity=10_000.0, drawdown_pct=0.0),
        ],
        start=start,
        end=end,
        timeframe="1d",
    )
    # Sortino formula: mean(rets) / downside_std(rets) * sqrt(ppy)
    # downside_std uses only rets<0: [-0.01, -0.02] -> mean=-0.015, sample stdev~0.00707
    downside = [r for r in rets if r < 0]
    import statistics

    expected_sortino = (statistics.mean(rets) / statistics.stdev(downside)) * math.sqrt(365)
    assert metrics["sortino_ratio"] == pytest.approx(expected_sortino, rel=1e-3)


def test_engine_metrics_cagr_negative_loss() -> None:
    """CAGR negative: final < initial after 1 year -> CAGR = -0.5 (50% loss)."""
    src = FakeOHLCVSource([])
    engine = BacktestEngine(
        src, _AlwaysBuyThenSellAfterN(sell_after_bars=2), initial_capital=10_000.0
    )
    # Non-leap-year span 2025->2026 (365 days exactly).
    start = datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC)
    end = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    metrics = engine._compute_metrics(
        trades=[],
        final_equity=5_000.0,
        equity_curve=[
            EquityPoint(timestamp=1_700_000_000_000, equity=10_000.0, drawdown_pct=0.0),
            EquityPoint(timestamp=1_701_577_600_000, equity=5_000.0, drawdown_pct=0.5),
        ],
        start=start,
        end=end,
        timeframe="1d",
    )
    assert metrics["cagr"] == pytest.approx(-0.5, abs=1e-6)


def test_engine_metrics_max_drawdown_explicit_equity_curve() -> None:
    """max_drawdown: equity dropped 20% from peak -> max_drawdown=0.20."""
    src = FakeOHLCVSource([])
    engine = BacktestEngine(
        src, _AlwaysBuyThenSellAfterN(sell_after_bars=2), initial_capital=10_000.0
    )
    start = datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC)
    end = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    # Equity path: 10000 -> 12000 (peak) -> 9600 (20%) -> 11000 (recovery)
    eq_curve = [
        EquityPoint(timestamp=1_700_000_000_000, equity=10_000.0, drawdown_pct=0.0),
        EquityPoint(timestamp=1_700_000_300_000, equity=12_000.0, drawdown_pct=0.0),
        EquityPoint(timestamp=1_700_000_600_000, equity=9_600.0, drawdown_pct=0.20),
        EquityPoint(timestamp=1_700_000_900_000, equity=11_000.0, drawdown_pct=0.20),
    ]
    metrics = engine._compute_metrics(
        trades=[],
        final_equity=11_000.0,
        equity_curve=eq_curve,
        start=start,
        end=end,
        timeframe="1d",
    )
    assert metrics["max_drawdown"] == pytest.approx(0.20, abs=1e-6)


def test_engine_metrics_calmar_with_real_drawdown() -> None:
    """Calmar = cagr / |max_dd|. Both finite -> real ratio (NOT inf)."""
    src = FakeOHLCVSource([])
    engine = BacktestEngine(
        src, _AlwaysBuyThenSellAfterN(sell_after_bars=2), initial_capital=10_000.0
    )
    start = datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC)
    end = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    # 1y span, final=15k (cagr=0.5), max_drawdown=0.20 -> calmar=0.5/0.20=2.5
    eq_curve = [
        EquityPoint(timestamp=1_700_000_000_000, equity=10_000.0, drawdown_pct=0.0),
        EquityPoint(timestamp=1_700_864_000_000, equity=13_000.0, drawdown_pct=0.0),
        EquityPoint(timestamp=1_701_577_600_000, equity=10_400.0, drawdown_pct=0.20),
        EquityPoint(timestamp=1_701_750_000_000, equity=15_000.0, drawdown_pct=0.20),
    ]
    metrics = engine._compute_metrics(
        trades=[],
        final_equity=15_000.0,
        equity_curve=eq_curve,
        start=start,
        end=end,
        timeframe="1d",
    )
    assert metrics["cagr"] == pytest.approx(0.5, abs=1e-6)
    assert metrics["max_drawdown"] == pytest.approx(0.20, abs=1e-6)
    assert metrics["calmar_ratio"] == pytest.approx(2.5, abs=1e-3)


def test_engine_metrics_expectancy_mixed_wins_losses() -> None:
    """Expectancy = mean(trade.pnl_pct). 3 trades: +0.10, -0.04, +0.06 -> mean=0.04.

    Also verifies avg_trade_pnl = mean(trade.pnl): 10 + (-4) + 6 = 4.0.
    """
    src = FakeOHLCVSource([])
    engine = BacktestEngine(
        src, _AlwaysBuyThenSellAfterN(sell_after_bars=2), initial_capital=10_000.0
    )
    start = datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC)
    end = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    pnls_pct = [0.10, -0.04, 0.06]
    trades = [
        Trade(
            entry_fill=Fill(
                order_id=f"o{i}",
                symbol="BTC/USDT",
                side="buy",
                qty_filled=1.0,
                fill_price=100.0,
                commission=0.1,
                slippage=0.05,
                timestamp=1_700_000_000_000 + i * 60_000,
            ),
            exit_fill=Fill(
                order_id=f"s{i}",
                symbol="BTC/USDT",
                side="sell",
                qty_filled=1.0,
                fill_price=100.0 * (1 + r),
                commission=0.11,
                slippage=0.06,
                timestamp=1_700_000_300_000 + i * 60_000,
            ),
            pnl=r * 100.0,
            pnl_pct=r,
            bars_held=3,
        )
        for i, r in enumerate(pnls_pct)
    ]
    metrics = engine._compute_metrics(
        trades=trades,
        final_equity=10_120.0,
        equity_curve=[
            EquityPoint(timestamp=1_700_000_000_000, equity=10_000.0, drawdown_pct=0.0),
        ],
        start=start,
        end=end,
        timeframe="1d",
    )
    assert metrics["expectancy"] == pytest.approx(4.0, abs=1e-6)
    assert metrics["avg_trade_pnl"] == pytest.approx(4.0, abs=1e-6)
    assert metrics["total_trades"] == 3.0
    assert metrics["win_rate"] == pytest.approx(2.0 / 3.0, abs=1e-6)  # 2 wins / 3 trades


def test_engine_metrics_single_trade_all_gated_metrics() -> None:
    """Single trade edge case: verify schema completeness + sharpe/sortino=0.0 gating.

    Coverage goal: ensure all 11 Metrics keys are populated, even with n=1 trade.
    """
    src = FakeOHLCVSource([])
    engine = BacktestEngine(
        src, _AlwaysBuyThenSellAfterN(sell_after_bars=2), initial_capital=10_000.0
    )
    start = datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC)
    end = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    metrics = engine._compute_metrics(
        trades=[
            Trade(
                entry_fill=Fill(
                    order_id="o1",
                    symbol="BTC/USDT",
                    side="buy",
                    qty_filled=1.0,
                    fill_price=100.0,
                    commission=0.1,
                    slippage=0.05,
                    timestamp=1_700_000_000_000,
                ),
                exit_fill=Fill(
                    order_id="s1",
                    symbol="BTC/USDT",
                    side="sell",
                    qty_filled=1.0,
                    fill_price=110.0,
                    commission=0.11,
                    slippage=0.06,
                    timestamp=1_700_000_300_000,
                ),
                pnl=9.68,
                pnl_pct=0.0968,
                bars_held=3,
            )
        ],
        final_equity=10_009.68,
        equity_curve=[
            EquityPoint(timestamp=1_700_000_000_000, equity=10_000.0, drawdown_pct=0.0),
            EquityPoint(timestamp=1_700_000_300_000, equity=10_009.68, drawdown_pct=0.0),
        ],
        start=start,
        end=end,
        timeframe="1d",
    )
    # All 11 keys present + sharpe/sortino gated (n=1)
    assert set(metrics.keys()) == {
        "total_trades",
        "win_rate",
        "profit_factor",
        "final_equity",
        "max_drawdown",
        "cagr",
        "calmar_ratio",
        "sharpe_ratio",
        "sortino_ratio",
        "avg_trade_pnl",
        "expectancy",
    }
    assert metrics["total_trades"] == 1.0
    assert metrics["win_rate"] == 1.0  # 1 win out of 1 trade
    assert metrics["profit_factor"] == float("inf")  # no losses
    assert metrics["sharpe_ratio"] == 0.0  # n=1 gated
    assert metrics["sortino_ratio"] == 0.0  # n=1 gated (no downside)
    assert metrics["avg_trade_pnl"] == pytest.approx(9.68, abs=1e-6)
    assert metrics["expectancy"] == pytest.approx(9.68, abs=1e-6)
