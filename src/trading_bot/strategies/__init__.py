"""Catálogo de estrategias (Fase 4)."""

from .ema_crossover import EmaCrossoverStrategy
from .pipeline import PipelineResult, TradingPipeline
from .protocols import Strategy
from .types import Side, Signal, StrategyConfig, StrategyState

__all__ = [
    "EmaCrossoverStrategy",
    "PipelineResult",
    "Side",
    "Signal",
    "Strategy",
    "StrategyConfig",
    "StrategyState",
    "TradingPipeline",
]
