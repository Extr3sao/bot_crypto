"""Tipos publicos del OHLCV Scheduler.

Capa de dominio aislada (regla arquitectonica §11 + §14 en
``docs/architecture.md``). Los dataclasses son ``frozen=True`` +
``slots=True`` y NO importan ``exchange``, ``strategies``,
``execution`` ni ``risk`` (cubierto por test AST, TSK-104.3b.5).

Regla de extension (ADR-0001 implicitamente via doc-style, mismo
criterio que ``scanner.types.RejectionReason``):

- Anadir un valor al ``Literal`` ``SkipReason`` o ``PullFailureReason``
  requiere:
  1. Anadir el valor en este Literal.
  2. Anadir un escenario BDD en
     ``bdd/features/ohlcv_scheduler.feature`` que cubra el nuevo
     motivo (regla metodologica SDD/BDD: 100% cobertura RF -> BDD).
  3. Si el motivo es semantics-sensitive para money-risk o
     invariants de negocio, firmar ADR en ``tasks/decisions.md``.
- Renombrar o quitar un valor existente requiere ADR firmada +
  revision del BDD feature por impactos downstream.

Cobertura del paquete (TSK-104.1 todo):
- 01-requirements.md §2.3 ``SchedulerResult`` contract: 6 campos +
  invariante post-filter (``pulls_attempted == pulls_succeeded +
  pulls_failed + cache_hits``) documentada.
- 03-specify.md §2 frozen+slots + §2.1 riesgos latentes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Literal

# ---------------------------------------------------------------------------
# Catalogo cerrado de motivos por los que un par es omitido del batch.
# 1:1 con escenarios Gherkin del ``bdd/features/ohlcv_scheduler.feature``:
#
#   - "active_hours_out_of_window" -> Scenario "Scheduler omite pull fuera
#     de active_hours".
#   - "cache_hit"                  -> Scenario "Cache hit evita pull si
#     vela fresca".
#   - "empty_universe"             -> Scenario "Scheduler skip si universe
#     vacio".
#
# Cualquier desvio aqui DEBE propagarse al .feature, a la BDD, y si
# toca money-risk, a una ADR firmada (regla metodologica SDD/BDD).
# ---------------------------------------------------------------------------
SkipReason = Literal[
    "active_hours_out_of_window",
    "cache_hit",
    "empty_universe",
]


# ---------------------------------------------------------------------------
# Catalogo cerrado de motivos por los que un pull fallo.
# Distingue errores transitorios (con reintento) de errores
# permanentes (configuration, validation, kill switch).
#
# Mapeo al .feature file:
#   - "rate_limit_exhausted"     -> Scenario "HTTP 429 con 3 reintentos
#     agotados reporta pull_failed".
#   - "network_timeout"          -> Scenario "OHLCVFetcherTimeoutError no
#     aborta batch".
#   - "exchange_unavailable"     -> ccxt.ExchangeNotAvailable mapeado via
#     _KNOWN_RETRYABLE_EXCEPTIONS (futuro F3b.1).
#   - "ddos_protection"          -> ccxt.DDoSProtection mapeado via
#     _KNOWN_RETRYABLE_EXCEPTIONS.
#   - "validation_error"         -> vela NaN / high<low persistente tras
#     retries (TSK-102 contract: validate() drops NaN y high<low;
#     si llegan igualmente deberia ser unrecoverable).
#   - "configuration_error"      -> e.g. connector no inicializado o
#     factory=None + new_mode requires connector (R1 opcion b defense).
# ---------------------------------------------------------------------------
PullFailureReason = Literal[
    "rate_limit_exhausted",
    "network_timeout",
    "exchange_unavailable",
    "ddos_protection",
    "validation_error",
    "configuration_error",
]


# ---------------------------------------------------------------------------
# Estado de la cache local ANTES de la decision de pull. Pineado por
# test para que el caller pueda distinguir "vela fresca" de
# "vela corrupta pero dentro de ventana" (CL-8).
# ---------------------------------------------------------------------------
class CacheState(Enum):
    """Estado de la cache local para un par (RF-4 + CL-8)."""

    FRESH = "fresh"  # RF-4 predicado True -> skip
    STALE = "stale"  # RF-4 predicado False -> pull (vela del periodo
    # previo o fuera de ventana de freshness)
    EMPTY = "empty"  # no hay vela para este simbolo en OHLCVStore
    CORRUPT = "corrupt"  # vela presente pero invalida (NaN, high<low);
    # pine contract: OHLCVFetcher.validate() filtra
    # estas en pull, NUNCA llegan a CacheHitPredicate


@dataclass(frozen=True, slots=True)
class CacheHitDecision:
    """Decision del CacheHitPredicate sobre un par (RF-4).

    Pine contract (03-specify.md §4):
    - 7 campos frozen + slots.
    - Retornado por ``evaluate_cache_hit`` (pure function en
      ``scheduler/cache.py``).
    - ``should_pull`` es derivado de ``state`` segun la tabla:
      | state    | should_pull |
      | -------- | ----------- |
      | FRESH    | False       |
      | STALE    | True        |
      | EMPTY    | True        |
      | CORRUPT  | True        |
    - ``reason`` es explicacion textual para logs (NO se usa en
      branch logic; es metadata de observabilidad).
    """

    state: CacheState
    last_candle_ts: int | None  # ms since epoch, None si EMPTY o CORRUPT
    current_ts: int  # ms since epoch
    primary_timeframe_ms: int  # e.g. 5*60*1000 para 5m
    freshness_window_ms: int  # e.g. 5*60*1000 para 5m (decay
    # tolerance pineada: 5m -> 290s en lugar
    # de 300s; ver Q10 thinker verdict)
    should_pull: bool
    reason: str  # explicacion textual para logs


@dataclass(frozen=True, slots=True)
class PullOutcome:
    """Resultado del pull de un par individual (per-pair).

    Pine contract (03-specify.md §2 + 04-plan.md §F3b.1):
    - 6 campos frozen + slots.
    - ``attempted=True`` si se intento fetch (no cache hit).
      ``attempted=False`` solo deberia ocurrir en cache hits, que NO
      pasan por ``_fetch_with_retry``; este dataclass se construye
      exclusivamente en paths de pull real.
    - ``retries_used`` 0..max_retries (3 per 03-specify §8 CL-9).
    - ``failure_reason`` None si succeeded=True; REQUIRED si succeeded=False
      (no enforced por dataclass; pineado por test_types.py).
    """

    symbol: str
    attempted: bool
    succeeded: bool
    failure_reason: PullFailureReason | None
    duration_ms: int
    retries_used: int


@dataclass(frozen=True, slots=True)
class SchedulerResult:
    """Salida canonica de ``OHLCVScheduler.run_once()``.

    Pine contract (01-requirements.md §2.3 + invariante post-filter):
    - 6 campos frozen + slots.
    - ``scheduler_iteration_id`` es ``uuid.UUID`` (no ``str``) para
      type-safety: callers que lo pasan a structlog o a log consumers
      pueden convertir implicitamente, pero el contrato en runtime es
      ``UUID``.
    - **Invariante** (sobre el subconjunto que pasa filtros
      ``active_hours`` y ``kill_switch``; pares fuera de ventana o
      con kill_switch NO aparecen en contadores):

        ``pulls_attempted == pulls_succeeded + pulls_failed + cache_hits``

      Pine contract NO enforced por dataclass (frozen+slots no
      permite ``__post_init__`` que valide); pineado por test
      ``tests/unit/scheduler/test_types.py::test_scheduler_result_invariante``.
    - Los counters pueden ser 0 en paths abort (early_exit =
      ``"kill_switch"`` o ``"empty_universe"``); en ese caso los
      3 counters son 0 y la invariante se cumple trivialmente.
    """

    pulls_attempted: int
    pulls_succeeded: int
    pulls_failed: int
    cache_hits: int
    duration_ms: int
    scheduler_iteration_id: uuid.UUID


__all__ = [
    "CacheHitDecision",
    "CacheState",
    "PullFailureReason",
    "PullOutcome",
    "SchedulerResult",
    "SkipReason",
]
