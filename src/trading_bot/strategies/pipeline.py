"""Trading Pipeline — wires strategy, risk, and execution together.

Fase 6: the core loop that connects:
  OHLCV candles + indicators → Strategy → Signal → Risk → Position → Execution

This is the single entry point for the trading loop. It does NOT
contain strategy logic, risk logic, or execution logic — it orchestrates.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import structlog

from trading_bot.indicators.types import IndicatorResult
from trading_bot.market_data.types import OHLCV
from trading_bot.risk.manager import RiskManager
from trading_bot.strategies.protocols import Strategy
from trading_bot.strategies.types import Signal, StrategyConfig


@dataclass(frozen=True, slots=True)
class PipelineResult:
    """Result of one pipeline tick."""

    symbol: str
    timestamp: int
    signal: Signal | None
    risk_check_approved: bool
    risk_check_reason: str | None
    risk_blocked_by: str | None = None
    position_size: Any = None
    execution_result: Any = None


@dataclass
class TradingPipeline:
    """Stateful trading pipeline.

    One instance per symbol. Orchestrates strategy → risk → execution
    without containing business logic in either layer.
    """

    symbol: str
    strategy: Strategy
    strategy_config: StrategyConfig
    risk_manager: RiskManager
    indicator_fn: Callable[[Sequence[OHLCV]], dict[str, IndicatorResult]]
    executor: Callable[[Signal, Any], Any] | None = None
    _log: Any = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self._log is None:
            self._log = structlog.get_logger("trading_pipeline")

    def tick(
        self,
        candles: Sequence[OHLCV],
    ) -> PipelineResult:
        """Process one tick: evaluate strategy, check risk, execute if approved.

        This is the hot path. It should be fast and side-effect-free
        except for the executor callback.
        """
        if not candles:
            return PipelineResult(
                symbol=self.symbol,
                timestamp=0,
                signal=None,
                risk_check_approved=False,
                risk_check_reason="no candles",
            )

        # 1. Compute indicators
        indicators = self.indicator_fn(candles)

        # 2. Evaluate strategy
        signal = self.strategy.evaluate(candles, indicators, self.strategy_config)

        if signal is None:
            return PipelineResult(
                symbol=self.symbol,
                timestamp=candles[-1].timestamp,
                signal=None,
                risk_check_approved=False,
                risk_check_reason="no signal",
            )

        # 3. Risk check
        risk_check = self.risk_manager.check_signal(signal)

        if not risk_check.approved:
            self._log.info(
                "pipeline.signal_blocked",
                symbol=signal.symbol,
                side=signal.side,
                reason=risk_check.reason,
                blocked_by=risk_check.blocked_by,
            )
            return PipelineResult(
                symbol=self.symbol,
                timestamp=candles[-1].timestamp,
                signal=signal,
                risk_check_approved=False,
                risk_check_reason=risk_check.reason,
                risk_blocked_by=risk_check.blocked_by,
            )

        # 4. Execute (if executor is configured)
        execution_result = None
        if self.executor is not None and risk_check.position_size is not None:
            try:
                execution_result = self.executor(signal, risk_check.position_size)
                self._log.info(
                    "pipeline.executed",
                    symbol=signal.symbol,
                    side=signal.side,
                    notional=risk_check.position_size.notional_usdt,
                )
            except Exception as exc:
                self._log.error(
                    "pipeline.execution_failed",
                    symbol=signal.symbol,
                    error=str(exc),
                )
                return PipelineResult(
                    symbol=self.symbol,
                    timestamp=candles[-1].timestamp,
                    signal=signal,
                    risk_check_approved=True,
                    risk_check_reason=f"execution failed: {exc}",
                    position_size=risk_check.position_size,
                )

        return PipelineResult(
            symbol=self.symbol,
            timestamp=candles[-1].timestamp,
            signal=signal,
            risk_check_approved=True,
            risk_check_reason=None,
            position_size=risk_check.position_size,
            execution_result=execution_result,
        )


__all__ = ["PipelineResult", "TradingPipeline"]
