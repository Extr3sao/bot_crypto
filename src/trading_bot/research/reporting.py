"""Automated Reporting (FASE 7, P23).

Generates structured reports from backtest/portfolio results:
- MASTER_STATUS.json — full portfolio status
- TRADES.csv — all trades with gross/net PnL
- BLOCKED_EVENTS.csv — all blocked signals with reasons
- DAILY_METRICS.csv — daily performance breakdown

All reports are deterministic and reproducible from the same input data.
"""

from __future__ import annotations

import csv
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

from .types import (
    PerformanceMetrics,
)

# ---------------------------------------------------------------------------
# Report Generator
# ---------------------------------------------------------------------------


class ReportGenerator:
    """Generates structured reports from backtest results.

    P23 contract:
    - MASTER_STATUS.json: full portfolio status
    - TRADES.csv: all trades
    - BLOCKED_EVENTS.csv: all blocked signals
    - DAILY_METRICS.csv: daily performance breakdown
    """

    def __init__(self, output_dir: Path | str = ".ai/reports") -> None:
        self._output_dir = Path(output_dir)
        self._log = structlog.get_logger("report_generator")

    def generate_all(
        self,
        metrics: PerformanceMetrics,
        trades: list[dict[str, Any]] | None = None,
        blocked_events: list[dict[str, Any]] | None = None,
        daily_metrics: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ReportBundle:
        """Generate all report files and return their paths.

        Args:
            metrics: Aggregate performance metrics
            trades: List of trade dicts (symbol, direction, entry_price, etc.)
            blocked_events: List of blocked event dicts
            daily_metrics: List of daily metric dicts
            metadata: Additional metadata (experiment_id, family, etc.)

        Returns:
            ReportBundle with paths to generated files.
        """
        self._output_dir.mkdir(parents=True, exist_ok=True)

        now = int(time.time() * 1000)
        ts_str = time.strftime("%Y%m%d_%H%M%S", time.gmtime(now / 1000))

        # MASTER_STATUS.json
        master_status = self._build_master_status(metrics, metadata, trades, blocked_events, daily_metrics)
        master_path = self._output_dir / f"MASTER_STATUS_{ts_str}.json"
        master_path.write_text(json.dumps(master_status, indent=2, default=str), encoding="utf-8")

        # TRADES.csv
        trades_path = self._output_dir / f"TRADES_{ts_str}.csv"
        self._write_trades_csv(trades_path, trades or [])

        # BLOCKED_EVENTS.csv
        blocked_path = self._output_dir / f"BLOCKED_EVENTS_{ts_str}.csv"
        self._write_blocked_csv(blocked_path, blocked_events or [])

        # DAILY_METRICS.csv
        daily_path = self._output_dir / f"DAILY_METRICS_{ts_str}.csv"
        self._write_daily_csv(daily_path, daily_metrics or [])

        # Summary markdown
        summary_path = self._output_dir / f"SUMMARY_{ts_str}.md"
        summary_path.write_text(
            self._build_summary_md(metrics, metadata, trades, blocked_events),
            encoding="utf-8",
        )

        self._log.info(
            "reports.generated",
            master=str(master_path),
            trades=str(trades_path),
            blocked=str(blocked_path),
            daily=str(daily_path),
        )

        return ReportBundle(
            master_status_path=master_path,
            trades_path=trades_path,
            blocked_events_path=blocked_path,
            daily_metrics_path=daily_path,
            summary_path=summary_path,
        )

    # ------------------------------------------------------------------
    # Build master status
    # ------------------------------------------------------------------

    def _build_master_status(
        self,
        metrics: PerformanceMetrics,
        metadata: dict[str, Any] | None,
        trades: list[dict[str, Any]] | None,
        blocked_events: list[dict[str, Any]] | None,
        daily_metrics: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        """Build MASTER_STATUS.json content."""
        status: dict[str, Any] = {
            "generated_at": int(time.time() * 1000),
            "schema_version": "1.0",
            "metadata": metadata or {},
            "aggregate_metrics": _metrics_to_dict(metrics),
        }

        if trades:
            status["trade_summary"] = {
                "total_trades": len(trades),
                "winning_trades": sum(1 for t in trades if t.get("net_pnl", 0) > 0),
                "losing_trades": sum(1 for t in trades if t.get("net_pnl", 0) < 0),
                "total_gross_pnl": sum(t.get("gross_pnl", 0) for t in trades),
                "total_net_pnl": sum(t.get("net_pnl", 0) for t in trades),
                "total_commission": sum(t.get("commission", 0) for t in trades),
                "total_slippage": sum(t.get("slippage", 0) for t in trades),
            }

        if blocked_events:
            status["blocked_summary"] = {
                "total_blocked": len(blocked_events),
                "by_reason": _count_by_field(blocked_events, "reason"),
            }

        if daily_metrics:
            status["daily_summary"] = {
                "trading_days": len(daily_metrics),
                "profitable_days": sum(1 for d in daily_metrics if d.get("net_pnl", 0) > 0),
                "losing_days": sum(1 for d in daily_metrics if d.get("net_pnl", 0) < 0),
                "best_day_pnl": max((d.get("net_pnl", 0) for d in daily_metrics), default=0.0),
                "worst_day_pnl": min((d.get("net_pnl", 0) for d in daily_metrics), default=0.0),
            }

        return status

    # ------------------------------------------------------------------
    # CSV writers
    # ------------------------------------------------------------------

    def _write_trades_csv(self, path: Path, trades: list[dict[str, Any]]) -> None:
        """Write TRADES.csv."""
        if not trades:
            path.write_text("symbol,direction,family,entry_price,exit_price,quantity,notional_usdt,gross_pnl,commission,slippage,net_pnl,entry_timestamp,exit_timestamp,bars_held,exit_reason\n", encoding="utf-8")
            return

        fieldnames = [
            "symbol", "direction", "family", "entry_price", "exit_price",
            "quantity", "notional_usdt", "gross_pnl", "commission", "slippage",
            "net_pnl", "entry_timestamp", "exit_timestamp", "bars_held", "exit_reason",
        ]

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for trade in trades:
                writer.writerow(trade)

    def _write_blocked_csv(self, path: Path, blocked: list[dict[str, Any]]) -> None:
        """Write BLOCKED_EVENTS.csv."""
        if not blocked:
            path.write_text("signal_family,symbol,timestamp,direction,details\n", encoding="utf-8")
            return

        fieldnames = ["signal_family", "symbol", "timestamp", "direction", "reason", "details"]
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for event in blocked:
                writer.writerow(event)

    def _write_daily_csv(self, path: Path, daily: list[dict[str, Any]]) -> None:
        """Write DAILY_METRICS.csv."""
        if not daily:
            path.write_text("date,trades,winning,losing,gross_pnl,net_pnl,commission,max_drawdown\n", encoding="utf-8")
            return

        fieldnames = [
            "date", "trades", "winning", "losing",
            "gross_pnl", "net_pnl", "commission", "max_drawdown",
        ]
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in daily:
                writer.writerow(row)

    # ------------------------------------------------------------------
    # Summary markdown
    # ------------------------------------------------------------------

    def _build_summary_md(
        self,
        metrics: PerformanceMetrics,
        metadata: dict[str, Any] | None,
        trades: list[dict[str, Any]] | None,
        blocked_events: list[dict[str, Any]] | None,
    ) -> str:
        """Build human-readable summary markdown."""
        lines: list[str] = []
        lines.append("# Portfolio Backtest Summary\n")

        if metadata:
            lines.append("## Metadata\n")
            for k, v in metadata.items():
                lines.append(f"- **{k}**: {v}")
            lines.append("")

        lines.append("## Aggregate Metrics\n")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        lines.append(f"| Total Trades | {metrics.total_trades} |")
        lines.append(f"| Winning | {metrics.winning_trades} ({metrics.win_rate:.1%}) |")
        lines.append(f"| Losing | {metrics.losing_trades} |")
        lines.append(f"| Gross PnL | {metrics.gross_pnl:,.2f} |")
        lines.append(f"| Net PnL | {metrics.net_pnl:,.2f} |")
        lines.append(f"| Commission | {metrics.total_commission:,.2f} |")
        lines.append(f"| Slippage | {metrics.total_slippage:,.2f} |")
        lines.append(f"| Gross ExpR | {metrics.gross_exp_r:.3f} |")
        lines.append(f"| Fee ExpR | {metrics.fee_exp_r:.3f} |")
        lines.append(f"| Net ExpR | {metrics.net_exp_r:.3f} |")
        lines.append(f"| Economic Margin R | {metrics.economic_margin_r:.3f} |")
        lines.append(f"| Gross PF | {metrics.gross_pf:.2f} |")
        lines.append(f"| Net PF | {metrics.net_pf:.2f} |")
        lines.append(f"| Max Drawdown | {metrics.max_drawdown:.2%} |")
        lines.append(f"| Coverage Days | {metrics.coverage_days_pct:.1%} |")
        lines.append("")

        if trades:
            lines.append(f"## Trades ({len(trades)})\n")
            lines.append("| # | Symbol | Dir | Family | Entry | Exit | Gross | Net | Reason |")
            lines.append("|---|--------|-----|--------|-------|------|-------|-----|--------|")
            for i, t in enumerate(trades[:50], 1):
                lines.append(
                    f"| {i} | {t.get('symbol', '?')} | {t.get('direction', '?')} | "
                    f"{t.get('family', '?')} | {t.get('entry_price', 0):.2f} | "
                    f"{t.get('exit_price', 0):.2f} | {t.get('gross_pnl', 0):.2f} | "
                    f"{t.get('net_pnl', 0):.2f} | {t.get('exit_reason', '?')} |"
                )
            if len(trades) > 50:
                lines.append(f"\n... ({len(trades) - 50} more trades in TRADES.csv)")
            lines.append("")

        if blocked_events:
            reasons = _count_by_field(blocked_events, "reason")
            lines.append(f"## Blocked Events ({len(blocked_events)})\n")
            lines.append("| Reason | Count |")
            lines.append("|--------|-------|")
            for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
                lines.append(f"| {reason} | {count} |")
            lines.append("")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Result bundle
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReportBundle:
    """Paths to generated report files."""

    master_status_path: Path
    trades_path: Path
    blocked_events_path: Path
    daily_metrics_path: Path
    summary_path: Path

    def to_dict(self) -> dict[str, str]:
        return {
            "master_status": str(self.master_status_path),
            "trades": str(self.trades_path),
            "blocked_events": str(self.blocked_events_path),
            "daily_metrics": str(self.daily_metrics_path),
            "summary": str(self.summary_path),
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _metrics_to_dict(m: PerformanceMetrics) -> dict[str, Any]:
    """Serialize PerformanceMetrics to dict."""
    import dataclasses
    return {f.name: getattr(m, f.name) for f in dataclasses.fields(m)}


def _count_by_field(items: list[dict[str, Any]], field: str) -> dict[str, int]:
    """Count occurrences of each value in a field."""
    counts: dict[str, int] = {}
    for item in items:
        val = str(item.get(field, "unknown"))
        counts[val] = counts.get(val, 0) + 1
    return counts


__all__ = ["ReportBundle", "ReportGenerator"]
