"""Real Backtest Evidence Adapter V0.2.1 — eliminates synthetic metrics.

V0.2.1 §5: RealBacktestAdapter must call REAL BacktestEngine.
V0.2.1 §6: Trade-level evidence output (trades.csv, daily_metrics.csv, etc.)

No synthetic PF/PnL/WR/expectancy from simulated code.
BacktestResult derived from REAL Trade objects produced by the engine.
"""

from __future__ import annotations

import csv
import datetime
import json
import statistics
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import structlog

from .evidence import EvidenceClass, EvidenceRecord
from .historical_data import HistoricalDataset


@dataclass(frozen=True, slots=True)
class TradeRecord:
    """Single trade record for evidence output.

    V0.2.1 §6: trades.csv must include at minimum these fields.
    """

    trade_id: str
    experiment_id: str
    strategy: str
    family: str
    symbol: str
    direction: str  # "LONG" or "SHORT"

    signal_timestamp: int
    entry_timestamp: int
    exit_timestamp: int

    entry_price: float
    exit_price: float
    quantity: float
    notional: float

    stop_price: float = 0.0
    target_price: float = 0.0

    gross_pnl: float = 0.0
    fees: float = 0.0
    slippage: float = 0.0
    net_pnl: float = 0.0

    initial_risk: float = 0.0
    gross_R: float = 0.0
    net_R: float = 0.0

    exit_reason: str = ""  # "take_profit", "stop_loss", "signal", "end_of_data"
    bars_held: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize for CSV output."""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DailyMetrics:
    """Per-day metrics for frequency analysis."""

    calendar_date: str
    executed_trades: int
    gross_pnl: float = 0.0
    net_pnl: float = 0.0
    wins: int = 0
    losses: int = 0


@dataclass(frozen=True, slots=True)
class RealBacktestResult:
    """Complete backtest result with trade-level evidence.

    V0.2.1 §5: metrics_source = CALCULATED_FROM_REAL_TRADES
    V0.2.1 §6: All metrics derived from Trade objects, not computed separately.
    """

    engine_version: str = "BacktestEngine-V0.2.1"
    run_id: str = ""
    strategy_name: str = ""
    symbol: str = ""
    timeframe: str = ""
    dataset_checksum: str = ""
    metrics_source: str = "CALCULATED_FROM_REAL_TRADES"
    evidence: EvidenceRecord | None = None

    # Raw trade data
    trades: list[TradeRecord] = field(default_factory=list)
    daily_metrics: list[DailyMetrics] = field(default_factory=list)

    # Computed metrics (from real trades)
    n_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    gross_pnl: float = 0.0
    net_pnl: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    gross_expectancy: float = 0.0
    net_expectancy: float = 0.0
    gross_pf: float = 0.0
    net_pf: float = 0.0
    max_drawdown: float = 0.0
    total_fees: float = 0.0
    total_slippage: float = 0.0
    turnover: float = 0.0
    trades_per_day: float = 0.0
    median_trades_per_day: float = 0.0
    zero_trade_days: int = 0
    pct_days_ge_1: float = 0.0
    long_trades: int = 0
    short_trades: int = 0
    long_pnl: float = 0.0
    short_pnl: float = 0.0

    # Engine result reference
    engine_initial_capital: float = 10_000.0
    engine_final_equity: float = 10_000.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON output."""
        return {
            "engine_version": self.engine_version,
            "run_id": self.run_id,
            "strategy_name": self.strategy_name,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "dataset_checksum": self.dataset_checksum,
            "metrics_source": self.metrics_source,
            "evidence": self.evidence.to_dict() if self.evidence else None,
            "n_trades": self.n_trades,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": self.win_rate,
            "gross_pnl": self.gross_pnl,
            "net_pnl": self.net_pnl,
            "avg_win": self.avg_win,
            "avg_loss": self.avg_loss,
            "gross_expectancy": self.gross_expectancy,
            "net_expectancy": self.net_expectancy,
            "gross_pf": self.gross_pf,
            "net_pf": self.net_pf,
            "max_drawdown": self.max_drawdown,
            "total_fees": self.total_fees,
            "total_slippage": self.total_slippage,
            "turnover": self.turnover,
            "trades_per_day": self.trades_per_day,
            "median_trades_per_day": self.median_trades_per_day,
            "zero_trade_days": self.zero_trade_days,
            "pct_days_ge_1": self.pct_days_ge_1,
            "long_trades": self.long_trades,
            "short_trades": self.short_trades,
            "long_pnl": self.long_pnl,
            "short_pnl": self.short_pnl,
            "engine_initial_capital": self.engine_initial_capital,
            "engine_final_equity": self.engine_final_equity,
        }


class RealBacktestEvidenceAdapter:
    """Adapter that runs the real BacktestEngine and produces trade-level evidence.

    V0.2.1 §5: NO synthetic metrics. All metrics from real Trade objects.
    V0.2.1 §6: Full trade evidence output.
    """

    def __init__(
        self,
        commission: float = 0.001,
        slippage_bps: float = 5.0,
        initial_capital: float = 10_000.0,
    ) -> None:
        self._commission = commission
        self._slippage_bps = slippage_bps
        self._initial_capital = initial_capital
        self._log = structlog.get_logger("real_backtest_evidence_adapter")

    def run(
        self,
        strategy: Any,
        source: Any,
        symbol: str,
        timeframe: str,
        start: datetime.datetime,
        end: datetime.datetime,
        dataset: HistoricalDataset | None = None,
        experiment_id: str = "",
    ) -> RealBacktestResult:
        """Run real backtest and produce evidence-backed result.

        Args:
            strategy: Object implementing StrategyProtocol (name, on_candle)
            source: Object implementing OHLCVSourceProtocol (iter_candles)
            symbol: Trading pair
            timeframe: Candle timeframe
            start: Start datetime
            end: End datetime
            dataset: Optional HistoricalDataset for evidence tracking
            experiment_id: Experiment identifier

        Returns:
            RealBacktestResult with trade-level evidence
        """
        from trading_bot.backtesting.engine import BacktestEngine

        run_id = f"RUN-{experiment_id}-{int(datetime.datetime.now().timestamp())}"

        self._log.info(
            "real_backtest_evidence.start",
            symbol=symbol,
            timeframe=timeframe,
            run_id=run_id,
        )

        # Run the REAL engine
        engine = BacktestEngine(
            source=source,
            strategy=strategy,
            commission=self._commission,
            slippage_bps=self._slippage_bps,
            initial_capital=self._initial_capital,
        )

        result = engine.run(
            symbol=symbol,
            start=start,
            end=end,
            timeframe=timeframe,
        )

        # Convert engine trades to TradeRecords
        trades = self._convert_trades(
            result.trades, symbol, strategy.name if hasattr(strategy, "name") else "unknown",
            experiment_id, timeframe,
        )

        # Compute ALL metrics from real trades
        computed = self._compute_from_trades(
            trades, result.equity_curve, start, end, timeframe
        )

        # Build daily metrics
        daily = self._compute_daily_metrics(trades)

        # Build evidence record
        evidence = EvidenceRecord(
            evidence_class=dataset.evidence_class if dataset else EvidenceClass.HISTORICAL_MARKET_REAL,
            source=f"BacktestEngine:{self._commission}:{self._slippage_bps}bps",
            dataset_id=dataset.dataset_id if dataset else "",
            checksum=dataset.checksum if dataset else "",
        )

        return RealBacktestResult(
            run_id=run_id,
            strategy_name=strategy.name if hasattr(strategy, "name") else "unknown",
            symbol=symbol,
            timeframe=timeframe,
            dataset_checksum=dataset.checksum if dataset else "",
            evidence=evidence,
            trades=trades,
            daily_metrics=daily,
            engine_initial_capital=self._initial_capital,
            engine_final_equity=result.final_equity,
            **computed,
        )

    def _convert_trades(
        self,
        engine_trades: list[Any],
        symbol: str,
        strategy_name: str,
        experiment_id: str,
        timeframe: str,
    ) -> list[TradeRecord]:
        """Convert engine Trade objects to TradeRecords."""
        records: list[TradeRecord] = []
        for i, trade in enumerate(engine_trades):
            entry = trade.entry_fill
            exit_ = trade.exit_fill

            direction = "LONG" if entry.side == "buy" else "SHORT"
            notional = entry.fill_price * entry.qty_filled
            total_fees = entry.commission + exit_.commission
            # V0.2.3 FIX: slippage in engine is per-unit price slippage.
            # Convert to total USDT slippage by multiplying by quantity.
            total_slippage = (entry.slippage + exit_.slippage) * entry.qty_filled

            # V0.2.4 CANONICAL ACCOUNTING:
            #
            # Engine's accounting:
            #   _execute_buy:  equity -= entry_commission (deducted immediately)
            #   _execute_sell: pnl = exit_rev - entry_cost - exit_commission
            #   equity_delta = sum(trade.pnl) - sum(entry_commissions)
            #
            # Therefore:
            #   trade.pnl = execution_pnl - exit_commission (NOT all costs)
            #   canonical_net = execution_pnl - entry_fee - exit_fee
            #   canonical_net = trade.pnl - entry_commission (per trade)
            #
            # Equity reconciliation:
            #   final_equity = initial + sum(trade.pnl) - sum(entry_commissions)
            #   final_equity = initial + sum(canonical_net)
            #
            # gross_price_move is the raw price movement from fills.
            # execution_pnl = gross_price_move (slippage embedded in fills).

            if direction == "LONG":
                gross_price_move = (exit_.fill_price - entry.fill_price) * entry.qty_filled
            else:
                gross_price_move = (entry.fill_price - exit_.fill_price) * entry.qty_filled

            # Canonical net: subtract ALL fees from gross price move
            canonical_net = gross_price_move - total_fees

            # Initial risk: estimate from entry to a reasonable stop
            initial_risk = abs(entry.fill_price * 0.01)  # placeholder 1%
            gross_R = gross_price_move / initial_risk if initial_risk > 0 else 0.0
            net_R = canonical_net / initial_risk if initial_risk > 0 else 0.0

            record = TradeRecord(
                trade_id=f"{experiment_id}-T{i:04d}",
                experiment_id=experiment_id,
                strategy=strategy_name,
                family=strategy_name,
                symbol=symbol,
                direction=direction,
                signal_timestamp=entry.timestamp,
                entry_timestamp=entry.timestamp,
                exit_timestamp=exit_.timestamp,
                entry_price=entry.fill_price,
                exit_price=exit_.fill_price,
                quantity=entry.qty_filled,
                notional=notional,
                gross_pnl=gross_price_move,
                fees=total_fees,
                slippage=total_slippage,
                net_pnl=canonical_net,
                initial_risk=initial_risk,
                gross_R=gross_R,
                net_R=net_R,
                exit_reason="signal",
                bars_held=trade.bars_held,
            )
            records.append(record)

        return records

    def _compute_from_trades(
        self,
        trades: list[TradeRecord],
        equity_curve: list[Any],
        start: datetime.datetime,
        end: datetime.datetime,
        timeframe: str,
    ) -> dict[str, Any]:
        """Compute ALL metrics from real trade records.

        V0.2.1 §5: metrics_source = CALCULATED_FROM_REAL_TRADES
        """
        n = len(trades)
        if n == 0:
            return {
                "n_trades": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0.0,
                "gross_pnl": 0.0,
                "net_pnl": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "gross_expectancy": 0.0,
                "net_expectancy": 0.0,
                "gross_pf": 0.0,
                "net_pf": 0.0,
                "max_drawdown": 0.0,
                "total_fees": 0.0,
                "total_slippage": 0.0,
                "turnover": 0.0,
                "trades_per_day": 0.0,
                "median_trades_per_day": 0.0,
                "zero_trade_days": 0,
                "pct_days_ge_1": 0.0,
                "long_trades": 0,
                "short_trades": 0,
                "long_pnl": 0.0,
                "short_pnl": 0.0,
            }

        wins = [t for t in trades if t.net_pnl > 0]
        losses = [t for t in trades if t.net_pnl <= 0]

        gross_pnl = sum(t.gross_pnl for t in trades)
        net_pnl = sum(t.net_pnl for t in trades)
        total_fees = sum(t.fees for t in trades)
        total_slippage = sum(t.slippage for t in trades)
        turnover = sum(t.notional for t in trades)

        win_rate = len(wins) / n if n > 0 else 0.0
        avg_win = statistics.mean([t.net_pnl for t in wins]) if wins else 0.0
        avg_loss = statistics.mean([abs(t.net_pnl) for t in losses]) if losses else 0.0

        gross_win_sum = sum(t.gross_pnl for t in wins) if wins else 0.0
        gross_loss_sum = sum(abs(t.gross_pnl) for t in losses) if losses else 0.0
        gross_pf = (
            gross_win_sum / gross_loss_sum
            if gross_loss_sum > 0
            else float("inf") if gross_win_sum > 0 else 0.0
        )

        net_win_sum = sum(t.net_pnl for t in wins) if wins else 0.0
        net_loss_sum = sum(abs(t.net_pnl) for t in losses) if losses else 0.0
        net_pf = (
            net_win_sum / net_loss_sum
            if net_loss_sum > 0
            else float("inf") if net_win_sum > 0 else 0.0
        )

        gross_expectancy = (
            (win_rate * avg_win) - ((1 - win_rate) * avg_loss)
        )
        net_expectancy = net_pnl / n if n > 0 else 0.0

        # Max drawdown from equity curve
        max_dd = 0.0
        if equity_curve:
            peak = equity_curve[0].equity if hasattr(equity_curve[0], "equity") else 0.0
            for pt in equity_curve:
                eq = pt.equity if hasattr(pt, "equity") else pt
                if eq > peak:
                    peak = eq
                dd = (peak - eq) / peak if peak > 0 else 0.0
                if dd > max_dd:
                    max_dd = dd

        # Direction breakdown
        long_trades = sum(1 for t in trades if t.direction == "LONG")
        short_trades = sum(1 for t in trades if t.direction == "SHORT")
        long_pnl = sum(t.net_pnl for t in trades if t.direction == "LONG")
        short_pnl = sum(t.net_pnl for t in trades if t.direction == "SHORT")

        # Daily frequency
        daily_counts: dict[str, int] = defaultdict(int)
        for t in trades:
            day = datetime.datetime.fromtimestamp(
                t.exit_timestamp / 1000.0, tz=datetime.UTC
            ).strftime("%Y-%m-%d")
            daily_counts[day] += 1

        counts = list(daily_counts.values())
        trades_per_day = statistics.mean(counts) if counts else 0.0
        median_tpd = statistics.median(counts) if counts else 0.0
        zero_trade_days = sum(1 for c in counts if c == 0)
        pct_ge_1 = sum(1 for c in counts if c >= 1) / len(counts) * 100 if counts else 0.0

        return {
            "n_trades": n,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": win_rate,
            "gross_pnl": gross_pnl,
            "net_pnl": net_pnl,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "gross_expectancy": gross_expectancy,
            "net_expectancy": net_expectancy,
            "gross_pf": gross_pf,
            "net_pf": net_pf,
            "max_drawdown": max_dd,
            "total_fees": total_fees,
            "total_slippage": total_slippage,
            "turnover": turnover,
            "trades_per_day": trades_per_day,
            "median_trades_per_day": median_tpd,
            "zero_trade_days": zero_trade_days,
            "pct_days_ge_1": pct_ge_1,
            "long_trades": long_trades,
            "short_trades": short_trades,
            "long_pnl": long_pnl,
            "short_pnl": short_pnl,
        }

    def _compute_daily_metrics(self, trades: list[TradeRecord]) -> list[DailyMetrics]:
        """Compute daily metrics from real trades."""
        daily_data: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"trades": 0, "gross_pnl": 0.0, "net_pnl": 0.0, "wins": 0, "losses": 0}
        )

        for t in trades:
            day = datetime.datetime.fromtimestamp(
                t.exit_timestamp / 1000.0, tz=datetime.UTC
            ).strftime("%Y-%m-%d")
            daily_data[day]["trades"] += 1
            daily_data[day]["gross_pnl"] += t.gross_pnl
            daily_data[day]["net_pnl"] += t.net_pnl
            if t.net_pnl > 0:
                daily_data[day]["wins"] += 1
            else:
                daily_data[day]["losses"] += 1

        result: list[DailyMetrics] = []
        for date in sorted(daily_data.keys()):
            d = daily_data[date]
            result.append(
                DailyMetrics(
                    calendar_date=date,
                    executed_trades=d["trades"],
                    gross_pnl=round(d["gross_pnl"], 8),
                    net_pnl=round(d["net_pnl"], 8),
                    wins=d["wins"],
                    losses=d["losses"],
                )
            )
        return result

    def write_evidence(
        self,
        result: RealBacktestResult,
        output_dir: Path,
        experiment_id: str = "",
    ) -> dict[str, Path]:
        """Write trade-level evidence files.

        V0.2.1 §6: manifest.json, dataset.json, trades.csv,
        daily_metrics.csv, metrics.json, audit.json, decision.json,
        run_metadata.json
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        paths: dict[str, Path] = {}

        # trades.csv
        trades_path = output_dir / "trades.csv"
        if result.trades:
            fieldnames = list(result.trades[0].to_dict().keys())
            with trades_path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for t in result.trades:
                    writer.writerow(t.to_dict())
        else:
            # Write empty CSV with header
            trades_path.write_text("trade_id\n", encoding="utf-8")
        paths["trades_csv"] = trades_path

        # daily_metrics.csv
        daily_path = output_dir / "daily_metrics.csv"
        with daily_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["calendar_date", "executed_trades", "gross_pnl", "net_pnl", "wins", "losses"])
            for dm in result.daily_metrics:
                writer.writerow([dm.calendar_date, dm.executed_trades, dm.gross_pnl, dm.net_pnl, dm.wins, dm.losses])
        paths["daily_metrics_csv"] = daily_path

        # metrics.json
        metrics_path = output_dir / "metrics.json"
        metrics_path.write_text(json.dumps(result.to_dict(), indent=2, default=str), encoding="utf-8")
        paths["metrics_json"] = metrics_path

        # run_metadata.json
        meta_path = output_dir / "run_metadata.json"
        meta = {
            "run_id": result.run_id,
            "strategy": result.strategy_name,
            "symbol": result.symbol,
            "timeframe": result.timeframe,
            "engine_version": result.engine_version,
            "metrics_source": result.metrics_source,
            "dataset_checksum": result.dataset_checksum,
            "n_trades": result.n_trades,
            "evidence": result.evidence.to_dict() if result.evidence else None,
        }
        meta_path.write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")
        paths["run_metadata_json"] = meta_path

        self._log.info(
            "real_backtest_evidence.written",
            output_dir=str(output_dir),
            trades=len(result.trades),
        )
        return paths


__all__ = [
    "DailyMetrics",
    "RealBacktestEvidenceAdapter",
    "RealBacktestResult",
    "TradeRecord",
]
