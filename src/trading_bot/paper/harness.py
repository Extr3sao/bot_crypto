"""Paper-session runner built on top of UniverseScanner (TSK-105)."""

from __future__ import annotations

import datetime
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

import structlog

from trading_bot.backtesting import BacktestResult, FoldReport, build_fold_report
from trading_bot.config.runtime import TradingMode
from trading_bot.config.settings import Settings
from trading_bot.scanner import UniverseScanner

from .archive import PaperSnapshotArchive
from .broker import PaperBroker
from .expectations import build_expectation_from_fold_report
from .reporting import build_session_alerts, build_session_metrics, write_session_report
from .types import PaperBacktestExpectation, PaperSessionResult


class PaperSessionRunner:
    """Executes one paper-mode scanner session and optionally archives it.

    PineStructlog event taxonomy (F5 spec section 10 contract):
    - ``paper.session.started`` (info): at the beginning of ``run_session``
      after validation, with ``session_id`` and ``mode`` bound to the logger.
    - ``paper.scanner.completed`` (info): after ``scanner.run()`` finishes,
      with ``total_snapshots`` and ``scanner_errors``.
    - ``paper.broker.reconciled`` (info): after ``broker.reconcile_session()``
      (only if the broker is configured), with fills count, closed trades,
      realized PnL, ending equity, and risk events.
    - ``paper.report.alerts`` (warning): when ``build_session_alerts()``
      returns a non-empty list (only emitted if the daily report is
      enabled and produces alerts), with ``count`` and ``codes``.
    - ``paper.report.written`` (info): after ``write_session_report()``
      (only when ``paper_report=True``), with the markdown and json paths.
    - ``paper.session.completed`` (info): at the end of ``run_session``,
      with the full session summary.

    Single-emission point per logical event: the harness is the only
    emitter of these events; the broker and reporting helpers return
    data (not log events) so the harness can keep the per-event binding
    consistent.
    """

    @classmethod
    def from_backtest_result(
        cls,
        *,
        scanner: UniverseScanner,
        settings: Settings,
        backtest_result: BacktestResult,
        expected_median_spread_bps: float,
        archive: PaperSnapshotArchive | None = None,
        active_snapshots_per_trade: float = 1.0,
        min_active_ratio: float = 0.30,
        max_scanner_errors: int = 3,
        report_output_dir: Path | str | None = None,
        now_fn: Callable[[], datetime.datetime] | None = None,
    ) -> PaperSessionRunner:
        return cls.from_fold_report(
            scanner=scanner,
            settings=settings,
            fold_report=build_fold_report(backtest_result),
            expected_median_spread_bps=expected_median_spread_bps,
            archive=archive,
            active_snapshots_per_trade=active_snapshots_per_trade,
            min_active_ratio=min_active_ratio,
            max_scanner_errors=max_scanner_errors,
            report_output_dir=report_output_dir,
            now_fn=now_fn,
        )

    @classmethod
    def from_fold_report(
        cls,
        *,
        scanner: UniverseScanner,
        settings: Settings,
        fold_report: FoldReport,
        expected_median_spread_bps: float,
        archive: PaperSnapshotArchive | None = None,
        active_snapshots_per_trade: float = 1.0,
        min_active_ratio: float = 0.30,
        max_scanner_errors: int = 3,
        report_output_dir: Path | str | None = None,
        now_fn: Callable[[], datetime.datetime] | None = None,
    ) -> PaperSessionRunner:
        expectation = build_expectation_from_fold_report(
            fold_report,
            expected_median_spread_bps=expected_median_spread_bps,
            active_snapshots_per_trade=active_snapshots_per_trade,
            min_active_ratio=min_active_ratio,
            max_scanner_errors=max_scanner_errors,
        )
        return cls(
            scanner=scanner,
            settings=settings,
            archive=archive,
            expectation=expectation,
            report_output_dir=report_output_dir,
            now_fn=now_fn,
        )

    def __init__(
        self,
        *,
        scanner: UniverseScanner,
        settings: Settings,
        archive: PaperSnapshotArchive | None = None,
        broker: PaperBroker | None = None,
        expectation: PaperBacktestExpectation | None = None,
        report_output_dir: Path | str | None = None,
        now_fn: Callable[[], datetime.datetime] | None = None,
    ) -> None:
        self._scanner = scanner
        self._settings = settings
        self._archive = archive
        self._broker = broker
        self._expectation = expectation
        self._report_output_dir = Path(report_output_dir) if report_output_dir is not None else None
        self._now_fn = now_fn or (lambda: datetime.datetime.now(datetime.UTC))
        self._log = structlog.get_logger(self.__class__.__module__)

    async def run_session(self) -> PaperSessionResult:
        self._validate_runtime()
        session_id = uuid4().hex
        log = self._log.bind(
            session_id=session_id,
            mode=self._settings.runtime.mode.value,
        )
        log.info(
            "paper.session.started",
            paper_trading_enabled=self._settings.runtime.features.enable_paper_trading,
        )
        started_at = self._now_fn()
        started_at_ms = int(started_at.timestamp() * 1000)

        snapshots = await self._scanner.run()
        counters = self._scanner.counters
        log.info(
            "paper.scanner.completed",
            total_snapshots=len(snapshots),
            scanner_errors=counters.scanner_errors,
        )
        ended_at = self._now_fn()
        duration_ms = max(int((ended_at - started_at).total_seconds() * 1000), 0)
        execution_summary = None
        if self._broker is not None:
            execution_summary = self._broker.reconcile_session(
                session_id,
                snapshots,
                self._settings.risk,
            )
            log.info(
                "paper.broker.reconciled",
                fills_count=execution_summary.fills_opened + execution_summary.fills_closed,
                closed_trades=len(execution_summary.closed_trades),
                realized_pnl=execution_summary.realized_pnl,
                ending_equity=execution_summary.ending_equity,
                risk_events=execution_summary.risk_events,
            )
        metrics = build_session_metrics(snapshots, counters, execution_summary)
        report_markdown_path: Path | None = None
        report_json_path: Path | None = None

        if self._archive is not None:
            self._archive.archive_session(session_id, started_at_ms, snapshots)
            retention_days = self._settings.runtime.logging.retention
            cutoff_ms = started_at_ms - retention_days * 24 * 60 * 60 * 1000
            self._archive.purge_older_than(cutoff_ms)

        result = PaperSessionResult(
            session_id=session_id,
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=duration_ms,
            snapshots=snapshots,
            counters=counters,
            metrics=metrics,
            execution_summary=execution_summary,
        )

        if self._settings.runtime.reports.paper_report:
            report_markdown_path, report_json_path = write_session_report(
                result,
                self._resolve_report_output_dir(),
                self._expectation,
            )
            alerts = build_session_alerts(result, self._expectation)
            if alerts:
                log.warning(
                    "paper.report.alerts",
                    count=len(alerts),
                    codes=[alert.code for alert in alerts],
                )
            log.info(
                "paper.report.written",
                markdown_path=str(report_markdown_path),
                json_path=str(report_json_path),
            )
            result = PaperSessionResult(
                session_id=result.session_id,
                started_at=result.started_at,
                ended_at=result.ended_at,
                duration_ms=result.duration_ms,
                snapshots=result.snapshots,
                counters=result.counters,
                metrics=result.metrics,
                execution_summary=result.execution_summary,
                report_markdown_path=report_markdown_path,
                report_json_path=report_json_path,
            )

        log.info(
            "paper.session.completed",
            duration_ms=duration_ms,
            total_snapshots=metrics.total_snapshots,
            active_snapshots=metrics.active_snapshots,
            inactive_snapshots=metrics.inactive_snapshots,
            scanner_errors=metrics.scanner_errors,
            report_markdown_path=None
            if report_markdown_path is None
            else str(report_markdown_path),
            report_json_path=None if report_json_path is None else str(report_json_path),
        )
        return result

    def _validate_runtime(self) -> None:
        if self._settings.runtime.mode is not TradingMode.PAPER:
            raise ValueError("PaperSessionRunner requiere runtime.mode='paper'.")
        if not self._settings.runtime.features.enable_paper_trading:
            raise ValueError("PaperSessionRunner requiere enable_paper_trading=True.")

    def _resolve_report_output_dir(self) -> Path:
        if self._report_output_dir is not None:
            return self._report_output_dir
        return Path(self._settings.runtime.reports.output_dir) / "paper"


__all__ = ["PaperSessionRunner"]
