"""OHLCV Scheduler: pull periodico + cache hit + retry + mode-aware.

Fase objetivo: 1 (market data + universe), ticket ``TSK-104``
per ``tasks/sprint-002.md`` Pri 6 + ``tasks/backlog.md``.

Responsabilidades (TSK-104.3 skeleton + TSK-104.4 wiring, tickets
posteriores):
- Disparar pulls periodicos del ``OHLCVFetcher`` sobre
  ``universe.pairs``.
- Respetar ``runtime.scheduler.active_hours_start/end`` (default
  0-23) y ``runtime.risk.kill_switch_enabled``.
- Aplicar cache-hit predicate (``evaluate_cache_hit`` pure
  function en ``scheduler/cache.py``) sobre la ultima vela en
  ``OHLCVStore``.
- Aislar errores transitorios por par sin abortar el batch
  (try/except + counters via ``PullMetricsSink``).
- Mode-aware: ``paper``/``live``/``shadow_live`` instancian
  ``CCXTExchangeConnector`` con sandbox flag; ``backtest``/
  ``research`` usan ``DeterministicOHLCVSource`` synthetic.

Reglas (pinea contra ``docs/architecture.md`` §11 + §14):
- Cero dependencias cross-layer: el scheduler NO importa
  ``execution.*``, ``strategies.*``, ``risk.*``, ``portfolio.*``,
  ``indicators.*``, ``paper.*``, ``observability.*``, ``scanner.*``.
  Cobertura via test AST enforcement (TSK-104.3b.5).
- Tipos frozen + slots (RNF-6); ver ``types.py``.
- ``__init__.py`` solo docstring + re-exports; cero side-effects.

Subpaquetes (a construir en F2 / F3a / F3b / F4):
- ``types``: ``SchedulerResult``, ``PullOutcome``,
  ``CacheHitDecision``, ``CacheState``, ``SkipReason``,
  ``PullFailureReason``.
- ``protocols``: ``OHLCVSourceProtocol`` (runtime_checkable),
  ``ConnectorFactory`` (Callable type alias),
  ``PullMetricsSink`` (Protocol).
- ``exceptions``: ``SchedulerError``, ``KillSwitchActiveError``,
  ``EmptyUniverseWarning``, ``RetryExhaustedError``.
- ``cache``: ``evaluate_cache_hit`` (pure function RF-4) —
  TSK-104.2.
- ``filters``: ``check_kill_switch`` + ``check_active_hours`` +
  ``ActiveHoursWindow`` — TSK-104.2.
- ``scheduler``: ``OHLCVScheduler`` orquestador async + counters
  + retry/jitter + ``connector_reinjector`` + cross-layer
  enforcement — TSK-104.3a + TSK-104.3b.
- ``fake``: ``FakeOHLCVSource`` test scaffolding para la rama
  scheduler — TSK-104.3b.5 (NO vivir en ``market_data/fake.py``;
  bloqueante por cross-layer: el scheduler no puede importar
  scanner ni market_data/fake).

Estado del paquete:
- TSK-104.1 (F1, este commit): tipos + protocolos + exceptions
  cerrados. ~8 tests verde esperados en
  ``tests/unit/scheduler/{test_types,test_protocols}.py``.
- TSK-104.2 (F2, en cola): ``cache.py`` + ``filters.py``
  pure functions + ~14 tests verde.
- TSK-104.3a (F3a, en cola): ``OHLCVScheduler`` skeleton
  + tier DI + reentrancy guard + 7 tests verde.
- TSK-104.3b (F3b, en cola): retries + run loop + events +
  mode-flip + cross-layer AST + 13 tests verde.
- TSK-104.4 (F4, en cola): wiring con Settings + 17 BDD
  scenarios + ADR-0014 + 6 quality gates.
"""

from trading_bot.scheduler.exceptions import (
    EmptyUniverseWarning,
    KillSwitchActiveError,
    RetryExhaustedError,
    SchedulerError,
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

__all__ = [
    "CacheHitDecision",
    "CacheState",
    "ConnectorFactory",
    "EmptyUniverseWarning",
    "KillSwitchActiveError",
    "OHLCVSourceProtocol",
    "PullFailureReason",
    "PullMetricsSink",
    "PullOutcome",
    "RetryExhaustedError",
    "SchedulerError",
    "SchedulerResult",
    "SkipReason",
]
