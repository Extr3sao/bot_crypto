"""Paper-session runner built on top of UniverseScanner (TSK-105).

CP-PO-002: ``run_session`` now executes the canonical decision cycle per
active asset (PIT history → AssetContext → StrategyRouter → AlphaFamily →
SignalAdapter → CandidatePortfolio → RiskManager → PaperBroker) in addition
to the pre-existing position reconciliation, archive and reporting stages.
The cycle stage is optional (default off) so every existing caller and test
keeps its exact behavior.
"""

from __future__ import annotations

import datetime
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

import structlog

from trading_bot.backtesting import BacktestResult, FoldReport, build_fold_report
from trading_bot.config.runtime import TradingMode
from trading_bot.config.settings import Settings
from trading_bot.market_data.types import OHLCV
from trading_bot.risk.defensive_blocks import MarketConditions
from trading_bot.scanner import UniverseScanner

from .archive import PaperSnapshotArchive
from .broker import PaperBroker
from .expectations import build_expectation_from_fold_report
from .paper_cycle import CycleStageCounts, PaperCycleEngine, RouteOnlyEngine
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
    - ``paper.session.completed`` (info): at the end of ``run_session``, with
      duration and snapshot counts.
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
        # -- CP-PO-002 canonical cycle (optional; default off) ---------------
        cycle_engine: PaperCycleEngine | RouteOnlyEngine | None = None,
        cycle_history_reader: Any | None = None,  # HistoricalBarReader
        history_lookback_bars: int = 120,
        # -- GAP-R1 durable state (optional; default off) --------------------
        state_store: Any | None = None,
        # -- BURN-IN-V1 observability (optional; default off) -----------------
        burnin_events_path: Path | str | None = None,
    ) -> None:
        self._scanner = scanner
        self._settings = settings
        self._archive = archive
        self._broker = broker
        self._expectation = expectation
        self._report_output_dir = Path(report_output_dir) if report_output_dir is not None else None
        self._now_fn = now_fn or (lambda: datetime.datetime.now(datetime.UTC))
        self._cycle_engine = cycle_engine
        self._history_reader = cycle_history_reader
        self._history_lookback = history_lookback_bars
        self._state_store = state_store
        self._burnin_events_path = (
            Path(burnin_events_path) if burnin_events_path is not None else None
        )
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

        # -- CP-PO-002: canonical decision cycle (context→router→…→broker) --
        cycle_counts: CycleStageCounts | None = None
        if self._cycle_engine is not None:
            cycle_counts = await self._run_decision_cycle(snapshots, session_id, started_at_ms)
            log.info("paper.cycle.completed", **cycle_counts.to_dict())

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
            self._record_closed_trades_in_risk(execution_summary)

        if self._state_store is not None and self._broker is not None:
            # Durable post-session snapshot (crash window = one session).
            from trading_bot.paper.paper_runtime_state import save_session_state

            engine: Any = self._cycle_engine
            save_session_state(
                store=self._state_store,
                run_id=session_id,
                broker=self._broker,
                risk=getattr(engine, "risk_manager", None),
                idempotency=getattr(engine, "idempotency", None),
            )
            log.info("paper.state.saved")

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
            snapshots=tuple(snapshots),
            counters=counters,
            metrics=metrics,
            execution_summary=execution_summary,
            cycle_counts=cycle_counts,
        )

        # BURN-IN-V1: per-cycle structured event (best-effort, never fatal).
        self._write_burnin_event(result)

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
                cycle_counts=cycle_counts,
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

    # -- burn-in observability (BURN-IN-V1) -----------------------------------

    def _write_burnin_event(self, result: PaperSessionResult) -> None:
        """Append one JSONL event per session (minimum reusable instrumentation).

        Best-effort: observability must never break the trading loop. Schema
        (docs/PAPER_BURN_IN_V1_RUN_REPORT.md): type/ts/cycle_id/latency/
        health (HEALTHY|DEGRADED)/metrics/cycle stage counts (rejections =
        NO_TRADE + veto reasons)/portfolio rows/pnl/data_health/state bytes.
        """
        if self._burnin_events_path is None:
            return
        try:
            import json
            from datetime import UTC, datetime

            summary = result.execution_summary
            cycle_counts = result.cycle_counts
            portfolio: dict[str, Any] = {}
            if self._broker is not None:
                portfolio = {s: p.to_row() for s, p in self._broker.positions.items()}
            now_ms = int(datetime.now(UTC).timestamp() * 1000)
            degraded = bool(
                cycle_counts is not None
                and (cycle_counts.context_errors or cycle_counts.adapter_errors)
            )
            event: dict[str, Any] = {
                "type": "paper.session",
                "ts_ms": now_ms,
                "cycle_id": result.session_id,
                "started_at_ms": int(result.started_at.timestamp() * 1000),
                "ended_at_ms": int(result.ended_at.timestamp() * 1000),
                "latency_ms": result.duration_ms,
                "health": "DEGRADED" if degraded else "HEALTHY",
                "metrics": result.metrics.to_dict(),
                "cycle": cycle_counts.to_dict() if cycle_counts is not None else None,
                "no_trade_and_veto_reasons": [
                    str(r.get("reason", ""))
                    for r in (cycle_counts.rejections if cycle_counts is not None else [])
                ],
                "portfolio": portfolio,
                "pnl": {
                    "realized": float(summary.realized_pnl) if summary is not None else 0.0,
                    "ending_equity": (
                        float(summary.ending_equity) if summary is not None else None
                    ),
                },
                "data_health": {
                    "snapshots": result.metrics.total_snapshots,
                    "active": result.metrics.active_snapshots,
                    "scanner_errors": result.metrics.scanner_errors,
                },
                "state_file_bytes": (
                    self._burnin_state_size() if self._state_store is not None else None
                ),
                "mtm": self._mtm_snapshot(list(result.snapshots)),
            }
            self._burnin_events_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._burnin_events_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
        except Exception as exc:  # observability must never kill the loop
            self._log.warning("paper.burnin.event_write_failed", error=str(exc))

    def _burnin_state_size(self) -> int | None:
        try:
            import os

            assert self._state_store is not None
            return os.path.getsize(self._state_store.path)
        except Exception:
            return None

    def _mtm_snapshot(self, snapshots: list[Any]) -> dict[str, Any]:
        """Mark-to-market telemetry for this cycle (BURN-IN-V2 §10).

        Prices come ONLY from this cycle's scanner snapshots (which are
        built from closed candles at or before the decision timestamp —
        PIT-valid by construction). A position without a snapshot price is
        reported as MTM_INCOMPLETE, never guessed.
        """
        if self._broker is None:
            return {"status": "MTM_NA"}
        prices: dict[str, float] = {}
        for snap in snapshots:
            symbol = str(getattr(snap, "symbol", "") or "")
            price = getattr(snap, "last_price", None)
            if symbol and price is not None and float(price) > 0:
                prices[symbol] = float(price)
        equity = float(self._broker.equity)
        realized = equity - float(self._broker.extract_state().get("initial_equity", equity))
        missing = [s for s in self._broker.positions if s not in prices]
        unrealized = self._broker.unrealized_pnl(prices)
        mtm = equity + unrealized
        gross = sum(p.notional_usdt for p in self._broker.positions.values())
        return {
            "status": "MTM_INCOMPLETE" if missing else "MTM_OK",
            "missing_prices": missing,
            "cash_realized_equity": round(equity, 6),
            "realized_pnl": round(realized, 6),
            "unrealized_pnl": round(unrealized, 6),
            "equity_mtm": round(mtm, 6),
            "gross_exposure": round(gross, 6),
            "open_positions": len(self._broker.positions),
            "prices_used": {s: round(p, 8) for s, p in prices.items()},
        }

    # -- CP-PO-002: canonical decision cycle ---------------------------------

    async def _run_decision_cycle(
        self,
        snapshots: list[Any],
        session_id: str,
        session_started_ms: int,
    ) -> CycleStageCounts:
        """Build PIT history per active asset and run the cycle engine.

        Decision timestamp per symbol = min(session start, snapshot ts) —
        the context must be valid at the decision time; bars after it are
        trimmed (PIT safety).
        """
        engine = self._cycle_engine
        assert engine is not None

        # Reflect the latest broker equity (post previous reconcile) so
        # risk sizing/limits use the live paper equity (one authority).
        # WP-EDGE-017/P0.3: marked to the net book, including the unrealized leg
        # and the commissions accrued on open positions.
        marks = {
            str(getattr(snap, "symbol", "")): float(getattr(snap, "last_price", 0.0) or 0.0)
            for snap in snapshots
            if getattr(snap, "active", False) and float(getattr(snap, "last_price", 0.0) or 0.0) > 0
        }
        self._sync_risk_equity(marks)

        history: dict[str, list[OHLCV]] = {}
        decision_ts: dict[str, int] = {}
        conditions = self._market_conditions(snapshots)
        if self._history_reader is not None:
            for snap in snapshots:
                symbol = str(getattr(snap, "symbol", ""))
                snap_ts = int(getattr(snap, "timestamp", 0) or 0)
                if not symbol or not getattr(snap, "active", False):
                    continue
                try:
                    bars = await self._history_reader.get_ohlcv(
                        symbol,
                        as_of_timestamp_ms=snap_ts,
                        lookback_bars=self._history_lookback,
                    )
                except Exception as exc:  # provider failure ⇒ no orders (fail closed)
                    self._log.warning("paper.cycle.history_error", symbol=symbol, error=str(exc))
                    continue
                history[symbol] = list(bars)
                decision_ts[symbol] = min(snap_ts, session_started_ms) or snap_ts

        if not history:
            # No readable history: the cycle still runs per-symbol empty so
            # every asset is observable as a context error (fail closed).
            for snap in snapshots:
                symbol = str(getattr(snap, "symbol", "") or "")
                if getattr(snap, "active", False):
                    history.setdefault(symbol, [])
                    decision_ts.setdefault(
                        symbol, int(getattr(snap, "timestamp", 0) or session_started_ms)
                    )
            return engine.run_cycle_sync(history, decision_ts, conditions=conditions)

        counts = engine.run_cycle_sync(history, decision_ts, conditions=conditions)
        return counts

    def _market_conditions(self, snapshots: list[Any]) -> dict[str, MarketConditions]:
        """Measured inputs for the four declared defensive blocks.

        WP-EDGE-017/P0.4: the scanner already measures the spread and the ATR% of
        every active pair, and the snapshot timestamp gives the age of the data
        the decision is about to act on. None of it was reaching the risk path.
        A field the scanner did not measure stays ``None`` so the evaluator blocks
        instead of passing.
        """
        now_ms = int(datetime.datetime.now(datetime.UTC).timestamp() * 1000)
        at = datetime.datetime.now(datetime.UTC)
        conditions: dict[str, MarketConditions] = {}
        for snap in snapshots:
            symbol = str(getattr(snap, "symbol", "") or "")
            if not symbol or not getattr(snap, "active", False):
                continue
            snap_ts = int(getattr(snap, "timestamp", 0) or 0)
            spread = getattr(snap, "spread_bps", None)
            atr = getattr(snap, "atr_pct", None)
            conditions[symbol] = MarketConditions(
                at=at,
                spread_bps=float(spread) if spread is not None else None,
                atr_pct=float(atr) if atr is not None else None,
                latency_ms=float(now_ms - snap_ts) if snap_ts > 0 else None,
            )
        return conditions

    def _record_closed_trades_in_risk(self, execution_summary: Any) -> None:
        """Feed reconciled closed-trade PnL into the canonical RiskManager.

        Keeps daily-loss / consecutive-loss / trade-count limits live with
        the paper broker's realized results (existing risk API, reused)."""
        engine = self._cycle_engine
        if engine is None:
            return
        risk = getattr(engine, "risk_manager", None)
        if risk is None or not hasattr(risk, "record_trade_result"):
            return
        # DEF-101: feed only the reconcile delta — never the full ledger
        # (re-feeding double-counted trades_today/daily_pnl cumulatively
        # until the daily trade limit vetoed every new intent).
        new_trades = getattr(execution_summary, "new_closed_trades", []) or []
        if new_trades and engine is not None and hasattr(engine, "bump_state_version"):
            # Portfolio changed (positions closed) → legitimate re-evaluation
            # reason for the BAR_CLOSE gate (BURN-IN-V2).
            engine.bump_state_version(f"positions_closed:{len(new_trades)}")
        for trade in new_trades:
            try:
                risk.record_trade_result(float(trade.pnl))
            except (TypeError, ValueError) as exc:
                self._log.warning("paper.cycle.risk_record_failed", error=str(exc))

    def _sync_risk_equity(self, marks: dict[str, float] | None = None) -> None:
        """Sync the risk engine with the REAL paper book (net equity + positions).

        PORTFOLIO-CONTEXT-01: exposure-dependent decisions must see the
        portfolio state at decision time. Without the position map below,
        ``max_open_positions`` and the exposure clamp would operate on an
        empty book while the broker actually holds positions (zero-
        exposure assumption — forbidden after a restart).
        """
        broker = self._broker
        engine = self._cycle_engine
        if broker is None or engine is None:
            return
        risk = getattr(engine, "risk_manager", None)
        if risk is not None and hasattr(risk, "equity"):
            try:
                # The book's net equity, not just its realized cash: the mark
                # carries the open leg and the commissions already owed on it.
                equity = (
                    float(broker.mark_to_market_equity(marks)) if marks else float(broker.equity)
                )
                if hasattr(risk, "mark_equity"):
                    risk.mark_equity(equity)
                else:
                    risk.equity = equity
                    risk.peak_equity = max(risk.peak_equity, equity)
                risk.open_positions = {
                    symbol: {
                        "notional_usdt": float(p.notional_usdt),
                        "side": str(p.side),
                        "entry_price": float(p.entry_price),
                        "quantity": float(p.quantity),
                    }
                    for symbol, p in broker.positions.items()
                }
            except (TypeError, ValueError):
                self._log.warning("paper.cycle.risk_equity_sync_failed")

    # -- helpers --------------------------------------------------------------

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
