"""Typed configuration for crypto-scalping-agentic-bot.

Loader y modelos Pydantic v2 sobre los 6 YAML en ``config/*.yaml``.

Uso::

    from trading_bot.config import load_settings

    settings = load_settings()             # config/*.yaml + .env
    settings.runtime.mode                   # TradingMode.PAPER por defecto
    settings.risk.max_risk_per_trade_pct   # float
    settings.universe.base_currency         # 'USDT'

    # CLI alternativo::
    #   python -m trading_bot.config --validate
    #   python -m trading_bot.config --dump-json
"""

from __future__ import annotations

from trading_bot.config.exchange import (
    Exchange,
    ExchangeEndpoints,
    ExchangeRetries,
    ExchangeTimeouts,
)
from trading_bot.config.indicators import (
    IndicatorConfig,
    IndicatorParams,
    IndicatorsConfig,
    IndicatorsGlobal,
)
from trading_bot.config.risk import DefensiveBlocks, Risk
from trading_bot.config.runtime import (
    FeatureFlags,
    LoggingBlock,
    Metrics,
    Paths,
    Reports,
    Runtime,
    Scheduler,
    SchedulerActiveHours,
    Storage,
    TradingMode,
)
from trading_bot.config.settings import FLAT_ENV_ALIASES, Settings, load_settings
from trading_bot.config.strategies import (
    StrategiesConfig,
    StrategiesGlobal,
    StrategyConfig,
    StrategyEntry,
    StrategyExit,
    StrategyFilters,
    StrategyState,
)
from trading_bot.config.universe import PairSpec, Universe, UniverseFilters

__all__ = [
    "FLAT_ENV_ALIASES",
    "DefensiveBlocks",
    "Exchange",
    "ExchangeEndpoints",
    "ExchangeRetries",
    "ExchangeTimeouts",
    "FeatureFlags",
    "IndicatorConfig",
    "IndicatorParams",
    "IndicatorsConfig",
    "IndicatorsGlobal",
    "LoggingBlock",
    "Metrics",
    "PairSpec",
    "Paths",
    "Reports",
    "Risk",
    "Runtime",
    "Scheduler",
    "SchedulerActiveHours",
    "Settings",
    "Storage",
    "StrategiesConfig",
    "StrategiesGlobal",
    "StrategyConfig",
    "StrategyEntry",
    "StrategyExit",
    "StrategyFilters",
    "StrategyState",
    "TradingMode",
    "Universe",
    "UniverseFilters",
    "load_settings",
]
