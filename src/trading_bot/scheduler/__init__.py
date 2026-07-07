"""OHLCV Scheduler — ``src/trading_bot/scheduler``.

Capa de orquestacion que mantiene ``OHLCVStore`` (TSK-102) fresco
ejecutando pulls periodicos via ``OHLCVFetcher``. Cross-layer
constraint (03-specify §11): solo importa
``trading_bot.market_data`` + ``trading_bot.config`` + stdlib. NO
importa ``execution``, ``strategies``, ``risk``, ``portfolio``,
``paper``, ``observability`` (cubierto por test AST
``tests/unit/scheduler/test_cross_layer.py``, pendiente F3b).
"""

from __future__ import annotations

from trading_bot.scheduler.cache import evaluate_cache_hit
from trading_bot.scheduler.exceptions import (
    EmptyUniverseWarning,
    KillSwitchActiveError,
    RetryExhaustedError,
    SchedulerError,
)
from trading_bot.scheduler.filters import (
    ActiveHoursWindow,
    PreBatchDecision,
    active_hours_window_from_settings,
    check_active_hours,
    check_kill_switch,
    parse_hhmm_to_minute,
)
from trading_bot.scheduler.protocols import (
    ConnectorFactory,
    OHLCVSourceProtocol,
    PullMetricsSink,
)
from trading_bot.scheduler.types import (
    CacheHitDecision,
    CacheState,
    PullFailureReason,
    PullOutcome,
    SchedulerResult,
    SkipReason,
)


# Public API. RUF022 alpha-sorted flat list.
# Grouping for reader comprehension (NOT enforced by ruff, alpha flat sort does):
#   F1 = types (1-6) + protocols (7-9) + exceptions (10-13)
#   F2 = cache (19) + filters (14-18, 20)
__all__ = [
    "ActiveHoursWindow",
    "CacheHitDecision",
    "CacheState",
    "ConnectorFactory",
    "EmptyUniverseWarning",
    "KillSwitchActiveError",
    "OHLCVSourceProtocol",
    "PreBatchDecision",
    "PullFailureReason",
    "PullMetricsSink",
    "PullOutcome",
    "RetryExhaustedError",
    "SchedulerError",
    "SchedulerResult",
    "SkipReason",
    "active_hours_window_from_settings",
    "check_active_hours",
    "check_kill_switch",
    "evaluate_cache_hit",
    "parse_hhmm_to_minute",
]
