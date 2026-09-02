"""Portfolio Backtest Engine (FASE 3, P3).

Multi-asset backtest with:
- Shared capital across all symbols
- Chronological execution of ALL signals
- Position sizing from risk
- Admission control (MAX_OPEN, DAILY_LOSS, etc.)
- Signal collision handling (priority-based)
- Funding cost modeling (future)

This REPLACES the single-symbol BacktestEngine for research purposes.
The existing engine remains for backward compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from trading_bot.backtesting.commissions import CommissionModel, FlatPctCommission
from trading_bot.backtesting.slippage import FlatBpsSlippage, SlippageModel
from trading_bot.indicators.types import IndicatorResult
from trading_bot.market_data.types import OHLCV

from .admission import AdmissionController
from .alpha import AlphaRegistry
from .types import AlphaSignal, BlockedEvent, Direction, PerformanceMetrics

# ---------------------------------------------------------------------------
# Portfolio State
# ---------------------------------------------------------------------------


@dataclass
class PortfolioPosition:
    """An open position in the portfolio."""

    symbol: str
    direction: Direction
    entry_price: float
    quantity: float
    notional_usdt: float
    stop_loss: float
    take_profit: float
    family: str
    entry_timestamp: int
    bars_held: int = 0


@dataclass
class PortfolioTrade:
    """A completed portfolio trade."""

    symbol: str
    direction: Direction
    family: str
    entry_price: float
    exit_price: float
    quantity: float
    notional_usdt: float
    gross_pnl: float
    commission: float
    slippage: float
    net_pnl: float
    entry_timestamp: int
    exit_timestamp: int
    bars_held: int
    exit_reason: str  # signal, stop_loss, take_profit, kill_switch


@dataclass
class PortfolioEquityPoint:
    """Equity snapshot at a point in time."""

    timestamp: int
    equity: float
    drawdown_pct: float
    open_positions: int


# ---------------------------------------------------------------------------
# Portfolio Backtest Engine
# ---------------------------------------------------------------------------


@dataclass
class PortfolioBacktestConfig:
    """Configuration for portfolio backtest."""

    initial_capital: float = 10_000.0
    commission: float | CommissionModel = 0.001
    slippage_bps: float | SlippageModel = 5.0
    risk_per_trade_pct: float = 0.25  # % of equity risked per trade
    max_positions: int = 3
    max_same_direction: int = 2
    funding_rate: float = 0.0  # per-period funding cost (0 = disabled)


class PortfolioBacktestEngine:
    """Multi-asset portfolio backtest engine.

    Iterates candles chronologically across ALL symbols.
    For each timestamp:
    1. Update mark-to-market for all open positions.
    2. Check SL/TP for all open positions.
    3. Generate signals from alpha families.
    4. Admit signals through admission controller.
    5. Execute admitted signals (with position sizing from risk).
    """

    def __init__(
        self,
        registry: AlphaRegistry,
        config: PortfolioBacktestConfig | None = None,
    ) -> None:
        self._registry = registry
        self._config = config or PortfolioBacktestConfig()

        # Resolve commission/slippage models
        self._commission: CommissionModel = (
            self._config.commission
            if isinstance(self._config.commission, CommissionModel)
            else FlatPctCommission(rate=self._config.commission)
        )
        self._slippage: SlippageModel = (
            self._config.slippage_bps
            if isinstance(self._config.slippage_bps, SlippageModel)
            else FlatBpsSlippage(bps=self._config.slippage_bps)
        )

        self._log = structlog.get_logger("portfolio_backtest")

    def run(
        self,
        candles_by_symbol: dict[str, list[OHLCV]],
        indicators_by_symbol: dict[str, list[dict[str, IndicatorResult]]] | None = None,
    ) -> PortfolioBacktestResult:
        """Run portfolio backtest across all symbols.

        Args:
            candles_by_symbol: {symbol: [candles in chronological order]}
            indicators_by_symbol: {symbol: [indicators per candle]} optional

        Returns:
            PortfolioBacktestResult with full portfolio metrics.
        """
        config = self._config
        equity = config.initial_capital
        peak_equity = equity
        positions: dict[str, PortfolioPosition] = {}
        trades: list[PortfolioTrade] = []
        equity_curve: list[PortfolioEquityPoint] = []
        blocked_events: list[BlockedEvent] = []

        # Admission controller
        from trading_bot.config.risk import Risk

        risk = Risk(
            max_risk_per_trade_pct=config.risk_per_trade_pct,
            max_daily_loss_pct=1.0,
            max_weekly_loss_pct=3.0,
            max_daily_drawdown_pct=2.0,
            max_total_drawdown_pct=5.0,
            max_open_positions=config.max_positions,
            max_trades_per_day=1000,  # effectively unlimited in backtest
            max_consecutive_losses=20,  # max allowed by Risk model
            consecutive_loss_cooldown_minutes=0,
            max_asset_exposure_pct=100.0,
            max_total_exposure_pct=100.0,
            min_order_notional_usdt=1.0,
            max_order_notional_usdt=equity,
            default_stop_loss_pct=1.0,
            default_take_profit_pct=2.0,
            kill_switch_enabled=True,
            live_trading_enabled=False,
        )
        admission = AdmissionController(risk=risk, equity=equity)

        # Build unified timeline
        all_timestamps = set()
        for candles in candles_by_symbol.values():
            for c in candles:
                all_timestamps.add(c.timestamp)
        sorted_timestamps = sorted(all_timestamps)

        # Index candles by (symbol, timestamp)
        candle_index: dict[tuple[str, int], OHLCV] = {}
        for symbol, candles in candles_by_symbol.items():
            for c in candles:
                candle_index[(symbol, c.timestamp)] = c

        # Index indicators if provided
        indicator_index: dict[tuple[str, int], dict[str, IndicatorResult]] = {}
        if indicators_by_symbol:
            for symbol, indicators in indicators_by_symbol.items():
                candles = candles_by_symbol.get(symbol, [])
                for i, ind in enumerate(indicators):
                    if i < len(candles):
                        indicator_index[(symbol, candles[i].timestamp)] = ind

        # Iterate chronologically
        for ts in sorted_timestamps:
            # 1. Check SL/TP for open positions
            symbols_to_close: list[tuple[str, str]] = []  # (symbol, reason)
            for symbol, pos in positions.items():
                candle = candle_index.get((symbol, ts))
                if candle is None:
                    continue
                pos.bars_held += 1

                # Check stop loss
                if (pos.direction == "LONG" and candle.low <= pos.stop_loss) or (pos.direction == "SHORT" and candle.high >= pos.stop_loss):
                    symbols_to_close.append((symbol, "stop_loss"))
                # Check take profit
                elif (pos.direction == "LONG" and candle.high >= pos.take_profit) or (pos.direction == "SHORT" and candle.low <= pos.take_profit):
                    symbols_to_close.append((symbol, "take_profit"))

            # Close positions that hit SL/TP
            for symbol, reason in symbols_to_close:
                pos = positions.pop(symbol)
                candle = candle_index.get((symbol, ts))
                if candle is None:
                    continue
                exit_price = candle.close
                trade = self._close_position(pos, exit_price, ts, reason)
                trades.append(trade)
                equity += trade.net_pnl
                admission.record_close(symbol, trade.net_pnl)

            # 2. Mark-to-market equity
            floating_pnl = 0.0
            for symbol, pos in positions.items():
                candle = candle_index.get((symbol, ts))
                if candle is None:
                    continue
                if pos.direction == "LONG":
                    floating_pnl += (candle.close - pos.entry_price) * pos.quantity
                else:
                    floating_pnl += (pos.entry_price - candle.close) * pos.quantity

            mtm_equity = equity + floating_pnl
            if mtm_equity > peak_equity:
                peak_equity = mtm_equity
            drawdown = (peak_equity - mtm_equity) / peak_equity if peak_equity > 0 else 0.0

            equity_curve.append(PortfolioEquityPoint(
                timestamp=ts,
                equity=mtm_equity,
                drawdown_pct=drawdown,
                open_positions=len(positions),
            ))

            # 3. Generate signals from all families
            for symbol in candles_by_symbol:
                candle = candle_index.get((symbol, ts))
                if candle is None:
                    continue

                # Get candles up to this point (lookback window)
                lookback = self._get_lookback(candles_by_symbol[symbol], ts, window=50)
                if len(lookback) < 3:
                    continue

                ind_map: dict[str, IndicatorResult] = indicator_index.get((symbol, ts), {})

                # Generate signals from all families
                signals = self._registry.generate_all(lookback, ind_map)

                # 4. Admit signals
                for signal in signals:
                    if signal.symbol in positions:
                        continue  # already have position

                    admission_result = admission.check_signal(signal)
                    if not admission_result.admitted:
                        if admission_result.blocked_event:
                            blocked_events.append(admission_result.blocked_event)
                        continue

                    # 5. Position sizing
                    notional = self._compute_position_size(
                        equity, signal, mtm_equity,
                    )
                    if notional <= 0:
                        continue

                    # Execute
                    fill_price = self._compute_fill_price(signal, candle)
                    quantity = notional / fill_price
                    commission = self._commission.calculate(notional, quantity, fill_price)

                    pos = PortfolioPosition(
                        symbol=signal.symbol,
                        direction=signal.direction,
                        entry_price=fill_price,
                        quantity=quantity,
                        notional_usdt=notional,
                        stop_loss=signal.effective_stop_price,
                        take_profit=self._compute_take_profit(signal),
                        family=signal.family,
                        entry_timestamp=ts,
                    )
                    positions[signal.symbol] = pos
                    equity -= commission
                    admission.record_open(signal.symbol, signal.direction)

        # Close any remaining positions at last price
        for symbol, pos in list(positions.items()):
            last_candle = candle_index.get((symbol, sorted_timestamps[-1]))
            if last_candle:
                trade = self._close_position(pos, last_candle.close, sorted_timestamps[-1], "end_of_data")
                trades.append(trade)
                equity += trade.net_pnl

        # Compute metrics
        metrics = self._compute_metrics(trades, equity_curve, config.initial_capital, equity)

        return PortfolioBacktestResult(
            initial_capital=config.initial_capital,
            final_equity=equity,
            trades=trades,
            equity_curve=equity_curve,
            blocked_events=blocked_events,
            metrics=metrics,
        )

    def _get_lookback(
        self, candles: list[OHLCV], current_ts: int, window: int = 50,
    ) -> list[OHLCV]:
        """Get the last N candles up to and including current timestamp."""
        result = [c for c in candles if c.timestamp <= current_ts]
        return result[-window:]

    def _compute_fill_price(self, signal: AlphaSignal, candle: OHLCV) -> float:
        """Compute fill price with slippage."""
        slippage = self._slippage.calculate(
            price=signal.entry_reference,
            qty=1.0,
            side="buy" if signal.direction == "LONG" else "sell",
            volume=candle.volume,
        )
        if signal.direction == "LONG":
            return signal.entry_reference + slippage
        return signal.entry_reference - slippage

    def _compute_take_profit(self, signal: AlphaSignal) -> float:
        """Compute take profit price."""
        if signal.direction == "LONG":
            return signal.entry_reference * 1.02  # 2% TP
        return signal.entry_reference * 0.98

    def _compute_position_size(
        self, equity: float, signal: AlphaSignal, mtm_equity: float,
    ) -> float:
        """Compute position size from risk parameters."""
        risk_amount = mtm_equity * (self._config.risk_per_trade_pct / 100.0)
        risk_per_unit = signal.risk_price
        if risk_per_unit <= 0:
            return 0.0
        quantity = risk_amount / risk_per_unit
        notional = quantity * signal.entry_reference
        # Cap at equity
        max_notional = mtm_equity * 0.95  # leave 5% buffer
        return min(notional, max_notional)

    def _close_position(
        self, pos: PortfolioPosition, exit_price: float, ts: int, reason: str,
    ) -> PortfolioTrade:
        """Close a position and compute PnL."""
        slippage = self._slippage.calculate(
            price=exit_price,
            qty=pos.quantity,
            side="sell" if pos.direction == "LONG" else "buy",
            volume=1_000_000.0,
        )
        if pos.direction == "LONG":
            actual_exit = exit_price - slippage
            gross_pnl = (actual_exit - pos.entry_price) * pos.quantity
        else:
            actual_exit = exit_price + slippage
            gross_pnl = (pos.entry_price - actual_exit) * pos.quantity

        commission = self._commission.calculate(pos.notional_usdt, pos.quantity, actual_exit)
        net_pnl = gross_pnl - commission - slippage * pos.quantity

        return PortfolioTrade(
            symbol=pos.symbol,
            direction=pos.direction,
            family=pos.family,
            entry_price=pos.entry_price,
            exit_price=actual_exit,
            quantity=pos.quantity,
            notional_usdt=pos.notional_usdt,
            gross_pnl=gross_pnl,
            commission=commission,
            slippage=slippage * pos.quantity,
            net_pnl=net_pnl,
            entry_timestamp=pos.entry_timestamp,
            exit_timestamp=ts,
            bars_held=pos.bars_held,
            exit_reason=reason,
        )

    def _compute_metrics(
        self,
        trades: list[PortfolioTrade],
        equity_curve: list[PortfolioEquityPoint],
        initial_capital: float,
        final_equity: float,
    ) -> PerformanceMetrics:
        """Compute complete performance metrics."""
        if not trades:
            return PerformanceMetrics()

        gross_pnl = sum(t.gross_pnl for t in trades)
        total_commission = sum(t.commission for t in trades)
        total_slippage = sum(t.slippage for t in trades)
        net_pnl = sum(t.net_pnl for t in trades)

        winning = [t for t in trades if t.net_pnl > 0]
        losing = [t for t in trades if t.net_pnl < 0]

        gross_win_sum = sum(t.gross_pnl for t in winning)
        gross_loss_sum = sum(t.gross_pnl for t in losing)
        net_win_sum = sum(t.net_pnl for t in winning)
        net_loss_sum = sum(t.net_pnl for t in losing)

        # Max drawdown from equity curve
        max_dd = max((ep.drawdown_pct for ep in equity_curve), default=0.0)

        # Daily coverage
        if equity_curve:
            days = len(set(ep.timestamp // 86_400_000 for ep in equity_curve))
            days_with_trades = len(set(
                t.entry_timestamp // 86_400_000 for t in trades
            ))
            coverage = days_with_trades / days if days > 0 else 0.0
        else:
            coverage = 0.0

        return PerformanceMetrics(
            total_trades=len(trades),
            winning_trades=len(winning),
            losing_trades=len(losing),
            gross_pnl=gross_pnl,
            gross_win_sum=gross_win_sum,
            gross_loss_sum=gross_loss_sum,
            total_commission=total_commission,
            total_slippage=total_slippage,
            total_funding=0.0,
            net_pnl=net_pnl,
            net_win_sum=net_win_sum,
            net_loss_sum=net_loss_sum,
            risk_per_trade=initial_capital * 0.0025,  # rough estimate
            max_drawdown=max_dd,
            coverage_days_pct=coverage,
        ).compute_derived()


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PortfolioBacktestResult:
    """Result of a portfolio backtest run."""

    initial_capital: float
    final_equity: float
    trades: list[PortfolioTrade]
    equity_curve: list[PortfolioEquityPoint]
    blocked_events: list[BlockedEvent]
    metrics: PerformanceMetrics

    @property
    def total_return_pct(self) -> float:
        if self.initial_capital <= 0:
            return 0.0
        return (self.final_equity - self.initial_capital) / self.initial_capital * 100


__all__ = [
    "PortfolioBacktestConfig",
    "PortfolioBacktestEngine",
    "PortfolioBacktestResult",
    "PortfolioEquityPoint",
    "PortfolioPosition",
    "PortfolioTrade",
]
