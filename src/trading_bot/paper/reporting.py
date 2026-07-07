"""Session-level reporting helpers for paper trading (TSK-105)."""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any

from trading_bot.scanner import CounterSnapshot, MarketSnapshot

from .types import (
    PaperBacktestExpectation,
    PaperExecutionSummary,
    PaperSessionAlert,
    PaperSessionMetrics,
    PaperSessionResult,
)


def build_session_metrics(
    snapshots: list[MarketSnapshot],
    counters: CounterSnapshot,
    execution_summary: PaperExecutionSummary | None = None,
) -> PaperSessionMetrics:
    active = [snap for snap in snapshots if snap.active]
    inactive = [snap for snap in snapshots if not snap.active]
    total = len(snapshots)

    avg_active_rank_score = (
        sum(snap.rank_score for snap in active) / len(active) if active else 0.0
    )
    median_spread_bps_active = (
        float(statistics.median(snap.spread_bps for snap in active)) if active else 0.0
    )
    active_ratio = (len(active) / total) if total else 0.0
    inactive_ratio = (len(inactive) / total) if total else 0.0

    return PaperSessionMetrics(
        total_snapshots=total,
        active_snapshots=len(active),
        inactive_snapshots=len(inactive),
        scanner_errors=counters.scanner_errors,
        active_ratio=active_ratio,
        inactive_ratio=inactive_ratio,
        avg_active_rank_score=float(avg_active_rank_score),
        median_spread_bps_active=median_spread_bps_active,
        fills_opened=0 if execution_summary is None else execution_summary.fills_opened,
        fills_closed=0 if execution_summary is None else execution_summary.fills_closed,
        closed_trades=0 if execution_summary is None else len(execution_summary.closed_trades),
        realized_pnl=0.0 if execution_summary is None else execution_summary.realized_pnl,
        unrealized_pnl=0.0 if execution_summary is None else execution_summary.unrealized_pnl,
        ending_cash=0.0 if execution_summary is None else execution_summary.ending_cash,
        ending_equity=0.0 if execution_summary is None else execution_summary.ending_equity,
        win_rate_closed=0.0 if execution_summary is None else execution_summary.win_rate_closed,
    )


def build_session_alerts(
    result: PaperSessionResult,
    expectation: PaperBacktestExpectation | None = None,
) -> list[PaperSessionAlert]:
    alerts: list[PaperSessionAlert] = []
    metrics = result.metrics

    if expectation is not None:
        if (
            expectation.expected_realized_pnl is not None
            and abs(expectation.expected_realized_pnl) > 1e-9
        ):
            pnl_divergence = (
                abs(metrics.realized_pnl - expectation.expected_realized_pnl)
                / abs(expectation.expected_realized_pnl)
            )
            if pnl_divergence > 0.50:
                alerts.append(
                    PaperSessionAlert(
                        code="realized_pnl_diverged",
                        message=(
                            "El PnL realizado diverge mas del 50% frente al backtest "
                            f"({metrics.realized_pnl:.4f} vs "
                            f"{expectation.expected_realized_pnl:.4f})."
                        ),
                    )
                )
        if expectation.expected_active_snapshots > 0:
            divergence = abs(
                metrics.active_snapshots - expectation.expected_active_snapshots
            ) / expectation.expected_active_snapshots
            if divergence > 0.50:
                alerts.append(
                    PaperSessionAlert(
                        code="signal_frequency_diverged",
                        message=(
                            "Active snapshots divergen mas del 50% frente al backtest "
                            f"({metrics.active_snapshots} vs {expectation.expected_active_snapshots})."
                        ),
                    )
                )
        if expectation.expected_median_spread_bps > 0 and (
            metrics.median_spread_bps_active > expectation.expected_median_spread_bps * 2.0
        ):
            alerts.append(
                PaperSessionAlert(
                    code="spread_above_expected",
                    message=(
                        "El spread mediano activo supera 2x el estimado del backtest "
                        f"({metrics.median_spread_bps_active:.2f} vs "
                        f"{expectation.expected_median_spread_bps:.2f} bps)."
                    ),
                )
            )
        if metrics.active_ratio < expectation.min_active_ratio:
            alerts.append(
                PaperSessionAlert(
                    code="active_ratio_below_threshold",
                    message=(
                        "La ratio de snapshots activos cae por debajo del minimo "
                        f"({metrics.active_ratio:.2%} < {expectation.min_active_ratio:.2%})."
                    ),
                )
            )
        if metrics.closed_trades > 0 and metrics.win_rate_closed < expectation.min_win_rate_closed:
            alerts.append(
                PaperSessionAlert(
                    code="win_rate_below_threshold",
                    message=(
                        "El win rate de trades cerrados cae por debajo del minimo "
                        f"({metrics.win_rate_closed:.2%} < "
                        f"{expectation.min_win_rate_closed:.2%})."
                    ),
                )
            )
        if metrics.scanner_errors > expectation.max_scanner_errors:
            alerts.append(
                PaperSessionAlert(
                    code="scanner_errors_above_threshold",
                    message=(
                        "La sesion acumula demasiados errores de scanner "
                        f"({metrics.scanner_errors} > {expectation.max_scanner_errors})."
                    ),
                )
            )
    return alerts


def build_session_report_payload(
    result: PaperSessionResult,
    expectation: PaperBacktestExpectation | None = None,
) -> dict[str, Any]:
    alerts = build_session_alerts(result, expectation)
    return {
        "session_id": result.session_id,
        "started_at": result.started_at.isoformat(),
        "ended_at": result.ended_at.isoformat(),
        "duration_ms": result.duration_ms,
        "metrics": {
            "total_snapshots": result.metrics.total_snapshots,
            "active_snapshots": result.metrics.active_snapshots,
            "inactive_snapshots": result.metrics.inactive_snapshots,
            "scanner_errors": result.metrics.scanner_errors,
            "active_ratio": result.metrics.active_ratio,
            "inactive_ratio": result.metrics.inactive_ratio,
            "avg_active_rank_score": result.metrics.avg_active_rank_score,
            "median_spread_bps_active": result.metrics.median_spread_bps_active,
            "fills_opened": result.metrics.fills_opened,
            "fills_closed": result.metrics.fills_closed,
            "closed_trades": result.metrics.closed_trades,
            "realized_pnl": result.metrics.realized_pnl,
            "unrealized_pnl": result.metrics.unrealized_pnl,
            "ending_cash": result.metrics.ending_cash,
            "ending_equity": result.metrics.ending_equity,
            "win_rate_closed": result.metrics.win_rate_closed,
        },
        "expectation": None
        if expectation is None
        else {
            "expected_active_snapshots": expectation.expected_active_snapshots,
            "expected_median_spread_bps": expectation.expected_median_spread_bps,
            "expected_realized_pnl": expectation.expected_realized_pnl,
            "min_active_ratio": expectation.min_active_ratio,
            "min_win_rate_closed": expectation.min_win_rate_closed,
            "max_scanner_errors": expectation.max_scanner_errors,
        },
        "alerts": [{"code": alert.code, "message": alert.message} for alert in alerts],
        "execution_summary": None
        if result.execution_summary is None
        else {
            "fills": [
                {
                    "fill_id": fill.fill_id,
                    "symbol": fill.symbol,
                    "side": fill.side,
                    "qty": fill.qty,
                    "fill_price": fill.fill_price,
                    "reference_price": fill.reference_price,
                    "commission": fill.commission,
                    "slippage_bps": fill.slippage_bps,
                    "notional_usdt": fill.notional_usdt,
                    "timestamp": fill.timestamp,
                    "reason": fill.reason,
                }
                for fill in result.execution_summary.fills
            ],
            "open_positions": [
                {
                    "symbol": position.symbol,
                    "qty": position.qty,
                    "entry_price": position.entry_price,
                    "entry_commission": position.entry_commission,
                    "opened_at_ms": position.opened_at_ms,
                    "last_price": position.last_price,
                    "marked_at_ms": position.marked_at_ms,
                    "notional_usdt": position.notional_usdt,
                    "unrealized_pnl": position.unrealized_pnl,
                    "sessions_held": position.sessions_held,
                }
                for position in result.execution_summary.open_positions
            ],
            "closed_trades": [
                {
                    "trade_id": trade.trade_id,
                    "symbol": trade.symbol,
                    "qty": trade.qty,
                    "entry_price": trade.entry_price,
                    "exit_price": trade.exit_price,
                    "opened_at_ms": trade.opened_at_ms,
                    "closed_at_ms": trade.closed_at_ms,
                    "realized_pnl": trade.realized_pnl,
                    "realized_pnl_pct": trade.realized_pnl_pct,
                    "total_commission": trade.total_commission,
                    "sessions_held": trade.sessions_held,
                    "entry_fill_id": trade.entry_fill_id,
                    "exit_fill_id": trade.exit_fill_id,
                }
                for trade in result.execution_summary.closed_trades
            ],
        },
    }


def render_session_markdown(
    result: PaperSessionResult,
    expectation: PaperBacktestExpectation | None = None,
) -> str:
    alerts = build_session_alerts(result, expectation)
    lines = [
        f"# Paper Session {result.session_id}",
        "",
        f"- Started: {result.started_at.isoformat()}",
        f"- Ended: {result.ended_at.isoformat()}",
        f"- Duration ms: {result.duration_ms}",
        "",
        "## Metrics",
        f"- Total snapshots: {result.metrics.total_snapshots}",
        f"- Active snapshots: {result.metrics.active_snapshots}",
        f"- Inactive snapshots: {result.metrics.inactive_snapshots}",
        f"- Scanner errors: {result.metrics.scanner_errors}",
        f"- Active ratio: {result.metrics.active_ratio:.2%}",
        f"- Median spread bps (active): {result.metrics.median_spread_bps_active:.2f}",
        f"- Avg active rank score: {result.metrics.avg_active_rank_score:.4f}",
        f"- Fills opened: {result.metrics.fills_opened}",
        f"- Fills closed: {result.metrics.fills_closed}",
        f"- Closed trades: {result.metrics.closed_trades}",
        f"- Realized PnL: {result.metrics.realized_pnl:.4f}",
        f"- Unrealized PnL: {result.metrics.unrealized_pnl:.4f}",
        f"- Ending cash: {result.metrics.ending_cash:.4f}",
        f"- Ending equity: {result.metrics.ending_equity:.4f}",
        f"- Win rate (closed trades): {result.metrics.win_rate_closed:.2%}",
        "",
        "## Backtest Comparison",
    ]
    if expectation is None:
        lines.append("- No backtest expectation supplied.")
    else:
        lines.extend(
            [
                f"- Expected active snapshots: {expectation.expected_active_snapshots}",
                (
                    "- Expected median spread bps: "
                    f"{expectation.expected_median_spread_bps:.2f}"
                ),
                (
                    "- Expected realized PnL: "
                    f"{expectation.expected_realized_pnl:.4f}"
                    if expectation.expected_realized_pnl is not None
                    else "- Expected realized PnL: n/a"
                ),
                f"- Minimum active ratio: {expectation.min_active_ratio:.2%}",
                f"- Minimum win rate (closed trades): {expectation.min_win_rate_closed:.2%}",
                f"- Maximum scanner errors: {expectation.max_scanner_errors}",
            ]
        )
    lines.extend(["", "## Alerts"])
    if not alerts:
        lines.append("- None")
    else:
        lines.extend(f"- [{alert.code}] {alert.message}" for alert in alerts)
    if result.execution_summary is not None:
        lines.extend(["", "## Open Positions"])
        if not result.execution_summary.open_positions:
            lines.append("- None")
        else:
            lines.extend(
                (
                    f"- {position.symbol}: qty={position.qty:.6f}, "
                    f"entry={position.entry_price:.4f}, last={position.last_price:.4f}, "
                    f"unrealized_pnl={position.unrealized_pnl:.4f}"
                )
                for position in result.execution_summary.open_positions
            )
    return "\n".join(lines) + "\n"


def write_session_report(
    result: PaperSessionResult,
    output_dir: Path | str,
    expectation: PaperBacktestExpectation | None = None,
) -> tuple[Path, Path]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    stem = result.started_at.strftime("%Y-%m-%d") + f"-{result.session_id}"
    markdown_path = output_path / f"{stem}.md"
    json_path = output_path / f"{stem}.json"
    markdown_path.write_text(
        render_session_markdown(result, expectation),
        encoding="utf-8",
    )
    json_path.write_text(
        json.dumps(build_session_report_payload(result, expectation), indent=2),
        encoding="utf-8",
    )
    return markdown_path, json_path


__all__ = [
    "build_session_alerts",
    "build_session_metrics",
    "build_session_report_payload",
    "render_session_markdown",
    "write_session_report",
]
