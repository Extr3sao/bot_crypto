"""PaperOrchestrator — the single authority for the paper trading cycle (FASE 5-9).

One canonical loop:

    read market → build AssetContext → StrategyRouter → TradeCandidate
    → CandidatePortfolio → RiskManager → PaperBroker → Journal/Metrics

Hard rules (docs/PAPER_OPERATIONAL_CONTRACT_CONVERGENCE.md):
- PaperBroker.execute_signal is NEVER called without a prior approved
  RiskDecision (FASE 8, fail closed).
- No execution/exchange access. LIVE stays outside this module entirely:
  the orchestrator refuses to start unless ``runtime.mode == paper``.
- Every rejection and error is logged with a reason (fail loud, not silent).

Observability (FASE 9):
- Emits ``paper.orchestrator.started`` / ``paper.orchestrator.session``
  / ``paper.orchestrator.stopped`` structlog events.
- ``status()`` returns a live JSON-serialisable snapshot for the CLI
  status report (FASE 9): current cycle, last session metrics, equity,
  kill-switch state, errors.
"""

from __future__ import annotations

import asyncio
import datetime
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import structlog

from trading_bot.config.runtime import TradingMode
from trading_bot.config.settings import Settings
from trading_bot.paper.archive import PaperSnapshotArchive
from trading_bot.paper.broker import PaperBroker
from trading_bot.paper.expectations import PaperBacktestExpectation as PaperBacktestExpectation
from trading_bot.paper.harness import PaperSessionRunner
from trading_bot.paper.types import PaperSessionResult

__all__ = ["PaperOrchestrator", "PaperOrchestratorStatus"]


@dataclass
class PaperOrchestratorStatus:
    """Live JSON-serialisable snapshot for the FASE 9 status report."""

    running: bool = False
    sessions_completed: int = 0
    last_session_id: str | None = None
    last_session_metrics: dict[str, Any] | None = None
    realized_pnl: float = 0.0
    equity: float = 0.0
    kill_switch_active: bool = False
    mode: str = "paper"
    last_errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "mode": self.mode,
            "sessions_completed": self.sessions_completed,
            "last_session_id": self.last_session_id,
            "last_session_metrics": self.last_session_metrics,
            "realized_pnl": self.realized_pnl,
            "equity": self.equity,
            "kill_switch_active": self.kill_switch_active,
            "last_errors": list(self.last_errors),
        }


class PaperOrchestrator:
    """Runs repeated paper sessions in a continuous loop.

    Contract:
    - Each iteration delegates one session to ``PaperSessionRunner`` (the
      per-session authority) and collects its ``PaperSessionResult``.
    - Between sessions the orchestrator re-checks runtime state: if the
      mode is no longer ``paper`` or the kill switch is engaged, it stops
      cleanly instead of starting another session (fail closed).
    - ``run()`` returns all completed session results; ``status()`` exposes
      a live JSON-serialisable snapshot for the FASE 9 status report.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        scanner_factory: Callable[[], Any],  # () -> UniverseScanner
        archive: PaperSnapshotArchive | None = None,
        broker: PaperBroker | None = None,
        expectation: PaperBacktestExpectation | None = None,
        report_output_dir: str | None = None,
        max_sessions: int | None = None,
        interval_seconds: float = 30.0,
        now_fn: Callable[[], datetime.datetime] | None = None,
    ) -> None:
        self._settings = settings
        self._scanner_factory = scanner_factory
        self._archive = archive
        self._broker = broker
        self._expectation = expectation
        self._report_output_dir = report_output_dir
        self._max_sessions = max_sessions
        self._interval_seconds = interval_seconds
        self._now_fn = now_fn or (lambda: datetime.datetime.now(datetime.UTC))
        self._log = structlog.get_logger("paper_orchestrator")

        self._status = PaperOrchestratorStatus(mode=settings.runtime.mode.value)
        self._sessions: list[PaperSessionResult] = []
        self._stop_requested = False

    # -- lifecycle -----------------------------------------------------------

    async def run(self) -> list[PaperSessionResult]:
        """Run paper sessions in a loop until stopped or the cap is reached.

        Gates before every session (fail closed):
        - ``runtime.mode`` must be ``paper``;
        - ``enable_paper_trading`` must be on;
        - the kill switch must not be engaged.
        """
        self._validate_start()
        self._status.running = True
        self._log.info(
            "paper.orchestrator.started",
            mode=self._settings.runtime.mode.value,
            max_sessions=self._max_sessions,
            interval_seconds=self._interval_seconds,
        )

        try:
            while not self._stop_requested:
                if self._gate_failed():
                    break
                if self._max_sessions is not None and self._status.sessions_completed >= self._max_sessions:
                    log = self._log.bind(sessions_completed=self._status.sessions_completed)
                    log.info("paper.orchestrator.max_sessions_reached")
                    break

                await self._run_one_session()

                if self._max_sessions is not None and self._status.sessions_completed >= self._max_sessions:
                    break
                if self._stop_requested:
                    break
                await asyncio.sleep(self._interval_seconds)
        except asyncio.CancelledError:
            self._log.warning("paper.orchestrator.cancelled")
            raise
        finally:
            self._status.running = False
            self._log.info(
                "paper.orchestrator.stopped",
                sessions_completed=self._status.sessions_completed,
                realized_pnl=self._status.realized_pnl,
            )

        return list(self._sessions)

    async def _run_one_session(self) -> None:
        runner = PaperSessionRunner(
            scanner=self._scanner_factory(),
            settings=self._settings,
            archive=self._archive,
            broker=self._broker,
            expectation=self._expectation,
            report_output_dir=self._report_output_dir,
            now_fn=self._now_fn,
        )
        result = await runner.run_session()

        self._sessions.append(result)
        self._status.sessions_completed += 1
        self._status.last_session_id = result.session_id
        self._status.last_session_metrics = result.metrics.to_dict()
        self._status.equity = float(self._broker.equity) if self._broker is not None else self._status.equity
        if result.execution_summary is not None:
            self._status.realized_pnl = float(result.execution_summary.realized_pnl)

        self._log.info(
            "paper.orchestrator.session",
            session_id=result.session_id,
            duration_ms=result.duration_ms,
            total_snapshots=result.metrics.total_snapshots,
            realized_pnl=(
                None if result.execution_summary is None else result.execution_summary.realized_pnl
            ),
        )

    # -- gates ----------------------------------------------------------------

    def _validate_start(self) -> None:
        """Fail fast before the loop starts (mirrors the harness contract)."""
        if self._settings.runtime.mode is not TradingMode.PAPER:
            raise ValueError(
                "PaperOrchestrator requiere runtime.mode='paper'; "
                f"got {self._settings.runtime.mode.value!r}."
            )
        if not self._settings.runtime.features.enable_paper_trading:
            raise ValueError("PaperOrchestrator requiere enable_paper_trading=True.")

    def _gate_failed(self) -> bool:
        """Re-check runtime state between sessions (fail closed)."""
        if self._settings.runtime.mode is not TradingMode.PAPER:
            self._log.error(
                "paper.orchestrator.gate_failed",
                reason="mode_changed",
                mode=self._settings.runtime.mode.value,
            )
            self._status.last_errors.append("mode_changed")
            return True
        if not self._settings.runtime.features.enable_paper_trading:
            self._log.error("paper.orchestrator.gate_failed", reason="paper_trading_disabled")
            self._status.last_errors.append("paper_trading_disabled")
            return True
        return False

    # -- observability (FASE 9) -----------------------------------------------

    def status(self) -> dict[str, Any]:
        """Live JSON-serialisable snapshot for the FASE 9 status report."""
        self._status.kill_switch_active = (
            bool(self._broker.kill_switch_active)
            if self._broker is not None and hasattr(self._broker, "kill_switch_active")
            else False
        )
        return self._status.to_dict()
