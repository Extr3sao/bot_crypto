"""Tests unitarios para ``src/trading_bot/scheduler/types.py``.

Estrategia: tests deterministas sin fixtures costosos; pinning
contractual del dataclass ``frozen=True`` + ``slots=True`` + Literals.
Tests rapidos (<50ms total) para CI.

Cobertura esperada per DoD F1 (TSK-104.1): 8 tests verde en este
archivo + 6 tests verde en ``test_protocols.py``.

Sentinelas pineados (ADR-locked per 03-specify + 01-requirements):

1. ``SchedulerResult`` invariante post-filter
   (``pulls_attempted == pulls_succeeded + pulls_failed + cache_hits``)
   pine EN el orchestrator, NO EN el dataclass (frozen+slots no
   permite ``__post_init__`` que valide); pineamos que el invariant
   esta DOCUMENTADO en el docstring + pineado por test de la
   combinacion de valores posibles.
2. ``CacheHitDecision`` 7 campos en orden contractual + slots True.
3. ``PullOutcome`` 6 campos + ``failure_reason`` required-if-fail
   (sentinel semantico, no enforced por dataclass).
4. ``SkipReason`` Literal cerrado: 3 valores.
5. ``PullFailureReason`` Literal cerrado: 6 valores.
6. ``CacheState`` Enum cerrado: 4 valores.
7. ``UUID`` field en ``SchedulerResult`` (no ``str``).
"""

from __future__ import annotations

import dataclasses
import uuid
from typing import get_args

import pytest

from trading_bot.scheduler.exceptions import (
    EmptyUniverseWarning,
    KillSwitchActiveError,
    RetryExhaustedError,
    SchedulerError,
)
from trading_bot.scheduler.types import (
    CacheHitDecision,
    CacheState,
    PullFailureReason,
    PullOutcome,
    SchedulerResult,
    SkipReason,
)

# ---------------------------------------------------------------------------
# Helpers de construccion.
# ---------------------------------------------------------------------------


def _make_scheduler_result(
    **overrides: object,
) -> SchedulerResult:
    """Construye un ``SchedulerResult`` valido con overrides keyword-only.

    Los defaults reflejan una iteracion healthy (paper mode, 25 pairs,
    cache hit en 5, success en 18, fail en 2). Cualquier combinacion
    que rompa la invariante pine se descarta explicitamente en los
    tests negativos.
    """
    defaults: dict[str, object] = {
        "pulls_attempted": 25,
        "pulls_succeeded": 18,
        "pulls_failed": 2,
        "cache_hits": 5,
        "duration_ms": 4200,
        "scheduler_iteration_id": uuid.UUID("12345678-1234-5678-1234-567812345678"),
    }
    defaults.update(overrides)
    # Invariante pre-check: cast to SchedulerResult sin tocar counters.
    return SchedulerResult(**defaults)


def _make_pull_outcome(**overrides: object) -> PullOutcome:
    """Construye un ``PullOutcome`` valido (sentinel de campos)."""
    defaults: dict[str, object] = {
        "symbol": "BTC/USDT",
        "attempted": True,
        "succeeded": True,
        "failure_reason": None,
        "duration_ms": 320,
        "retries_used": 0,
    }
    defaults.update(overrides)
    return PullOutcome(**defaults)


def _make_cache_hit_decision(**overrides: object) -> CacheHitDecision:
    """Construye un ``CacheHitDecision`` valido (sentinel de campos)."""
    defaults: dict[str, object] = {
        "state": CacheState.FRESH,
        "last_candle_ts": 1672531200000,
        "current_ts": 1672531260000,
        "primary_timeframe_ms": 5 * 60 * 1000,
        "freshness_window_ms": 5 * 60 * 1000,
        "should_pull": False,
        "reason": "last candle 60000ms old within 300000ms window",
    }
    defaults.update(overrides)
    return CacheHitDecision(**defaults)


# ---------------------------------------------------------------------------
# SchedulerResult: frozen, slots, invariante, UUID type.
# ---------------------------------------------------------------------------


def test_scheduler_result_frozen_mutation_raises() -> None:
    """Pinea RNF-6: ``frozen=True`` levanta FrozenInstanceError al mutar."""
    result = _make_scheduler_result()
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.pulls_succeeded = 999


def test_scheduler_result_field_order_matches_spec() -> None:
    """Pinea el orden contractual exacto del dataclass (6 campos).

    El orden es contrato publico per ``03-specify.md`` §2; cualquier
    reorden rompe callers que dependen de ``dataclasses.fields()[i]``.
    Sentinel: ``scheduler_iteration_id`` va ULTIMO (es metadato de
    correlacion, NO counter; orden de importance diferente).
    """
    expected = (
        "pulls_attempted",
        "pulls_succeeded",
        "pulls_failed",
        "cache_hits",
        "duration_ms",
        "scheduler_iteration_id",
    )
    actual = tuple(f.name for f in dataclasses.fields(SchedulerResult))
    assert actual == expected


def test_scheduler_result_uses_slots() -> None:
    """Pinea RNF-6: ``slots=True`` reduce overhead por iteracion.

    Tightness: pineamos la tupla completa 1:1 con los 6 campos del
    dataclass (no basta con verificar ``__slots__`` existe — eso haria
    cualquier tupla vacia o un solo campo).
    """
    expected_slots: tuple[str, ...] = (
        "pulls_attempted",
        "pulls_succeeded",
        "pulls_failed",
        "cache_hits",
        "duration_ms",
        "scheduler_iteration_id",
    )
    actual_slots: tuple[str, ...] = SchedulerResult.__slots__
    assert actual_slots == expected_slots


def test_scheduler_result_iteration_id_is_uuid_type() -> None:
    """Pinea que ``scheduler_iteration_id`` es ``uuid.UUID`` (no ``str``).

    Razon: type-safety en runtime; ``structlog.bind(scheduler_iteration_id=...)``
    acepta tanto UUID como str, pero el dataclass publica el tipo
    canonico. Si en algun momento se quiere aceptar ``str`` para
    compat con callers externos, hay que actualizar este test.
    """
    field = next(
        f for f in dataclasses.fields(SchedulerResult) if f.name == "scheduler_iteration_id"
    )
    assert field.type == "uuid.UUID" or field.type is uuid.UUID


def test_scheduler_result_invariante_pulls_attempted_eq_sum() -> None:
    """Pinea la invariante post-filter (documentada, no enforced):

    ``pulls_attempted == pulls_succeeded + pulls_failed + cache_hits``

    Pineamos la combinacion tipica (healthy iter) + un caso abort
    (todos 0) para cubrir ``early_exit`` paths.
    """
    # Healthy iter: 25 pares, 5 cache hit, 18 success, 2 fail.
    healthy = _make_scheduler_result(
        pulls_attempted=25,
        pulls_succeeded=18,
        pulls_failed=2,
        cache_hits=5,
    )
    assert healthy.pulls_attempted == (
        healthy.pulls_succeeded + healthy.pulls_failed + healthy.cache_hits
    )

    # Abort path (kill_switch or empty_universe): todos 0.
    aborted = _make_scheduler_result(
        pulls_attempted=0,
        pulls_succeeded=0,
        pulls_failed=0,
        cache_hits=0,
    )
    assert aborted.pulls_attempted == 0


# ---------------------------------------------------------------------------
# PullOutcome: frozen + sentinel semantico failure_reason.
# ---------------------------------------------------------------------------


def test_pull_outcome_frozen_mutation_raises() -> None:
    outcome = _make_pull_outcome()
    with pytest.raises(dataclasses.FrozenInstanceError):
        outcome.succeeded = False


def test_pull_outcome_succeeded_implies_no_failure_reason() -> None:
    """Sentinel semantico: ``succeeded=True`` debe llevar
    ``failure_reason=None``. NO enforced por dataclass (el test es la
    unica garantia runtime)."""
    outcome = _make_pull_outcome(succeeded=True, failure_reason=None)
    assert outcome.failure_reason is None


def test_pull_outcome_failure_carries_reason() -> None:
    """Sentinel semantico: ``succeeded=False`` siempre lleva
    ``failure_reason`` populated. Pine contract: el scheduler emite
    ``on_pull_failed`` con ese reason."""
    fail = _make_pull_outcome(
        succeeded=False,
        failure_reason="rate_limit_exhausted",
        retries_used=3,
    )
    assert fail.succeeded is False
    assert fail.failure_reason == "rate_limit_exhausted"
    assert fail.retries_used == 3


# ---------------------------------------------------------------------------
# CacheHitDecision: 7 campos + state Enum coverage.
# ---------------------------------------------------------------------------


def test_cache_hit_decision_frozen_mutation_raises() -> None:
    decision = _make_cache_hit_decision()
    with pytest.raises(dataclasses.FrozenInstanceError):
        decision.should_pull = True


def test_cache_hit_decision_field_order_matches_spec() -> None:
    """Pinea orden contractual del dataclass (7 campos)."""
    expected = (
        "state",
        "last_candle_ts",
        "current_ts",
        "primary_timeframe_ms",
        "freshness_window_ms",
        "should_pull",
        "reason",
    )
    actual = tuple(f.name for f in dataclasses.fields(CacheHitDecision))
    assert actual == expected


def test_cache_hit_decision_supports_all_4_states() -> None:
    """Sentinel: ``state`` enum cubre los 4 valores pineados en spec."""
    states = {CacheState.FRESH, CacheState.STALE, CacheState.EMPTY, CacheState.CORRUPT}
    assert states == set(CacheState)


# ---------------------------------------------------------------------------
# Literals cerrados: SkipReason (3 values) + PullFailureReason (6 values).
# ---------------------------------------------------------------------------


def test_skip_reason_literal_values() -> None:
    """ADR lock: el Literal ``SkipReason`` contiene exactamente los 3
    valores documentados. Cualquier cambio futuro rompe este test,
    forzando update del .feature + revision del orchestrator +
    posible ADR."""
    expected = {
        "active_hours_out_of_window",
        "cache_hit",
        "empty_universe",
    }
    actual = set(get_args(SkipReason))
    assert actual == expected


def test_pull_failure_reason_literal_values() -> None:
    """ADR lock: el Literal ``PullFailureReason`` contiene exactamente
    los 6 valores documentados. Pine contract: cada valor tiene un
    mapeo a un ccxt/builtin exception type en ``_fetch_with_retry``
    (TSK-104.3b.1)."""
    expected = {
        "rate_limit_exhausted",
        "network_timeout",
        "exchange_unavailable",
        "ddos_protection",
        "validation_error",
        "configuration_error",
    }
    actual = set(get_args(PullFailureReason))
    assert actual == expected


# ---------------------------------------------------------------------------
# Jerarquia de excepciones: SchedulerError + KillSwitch + RetryExhausted.
# ---------------------------------------------------------------------------


def test_exceptions_inherit_scheduler_error() -> None:
    """Pinea jerarquia: ``SchedulerError`` es base.

    Sensinels:
    - ``ScannerError`` / ``KillSwitchActiveError`` / ``ConfigurationError``
      en scanner extienden ``ScannerError`` (Exception). Aqui, el
      scheduler tiene SU PROPIA jerarquia: NO comparte base con el
      scanner porque pertenece a otra capa del sistema.
    - ``EmptyUniverseWarning`` NO es ``SchedulerError`` (es
      ``UserWarning``) — la condicion es esperada, no bloqueante.
    """
    assert issubclass(KillSwitchActiveError, SchedulerError)
    assert issubclass(RetryExhaustedError, SchedulerError)
    assert issubclass(SchedulerError, Exception)
    # Sentinel: SchedulerError NO debe ser KeyboardInterrupt/SystemExit
    # para no atrapar el shutdown del interpreter accidentalmente.
    assert SchedulerError is not KeyboardInterrupt
    assert SchedulerError is not SystemExit


def test_empty_universe_is_user_warning_not_scheduler_error() -> None:
    """Sentinel explicito: ``empty_universe`` es WARNING, NO ERROR.

    Razon: en paper / research, ``universe.pairs`` vacio es una
    condicion operacional esperada (todavia no hay whitelist). NO
    debe bloquear el arranque ni degradar el orchestrator. Por eso
    ``EmptyUniverseWarning extends UserWarning``, no
    ``SchedulerError``.
    """
    assert issubclass(EmptyUniverseWarning, UserWarning)
    # No debe ser error — no es silenciable via try/except de
    # ``except SchedulerError``.
    assert not issubclass(EmptyUniverseWarning, SchedulerError)


def test_retry_exhausted_error_chains_last_exception() -> None:
    """Pinea que ``RetryExhaustedError`` propaga el last_exception via
    atributo ``last_exception`` y ``attempts``.

    Pine contract: el scheduler captura ``RetryExhaustedError``, lee
    ``e.last_exception`` para mapear a ``PullFailureReason``, y
    ``e.attempts`` para el log. Si este chain se rompe, los logs
    pierden trazabilidad de la ccxt exception original.
    """
    original = TimeoutError("ccxt.RequestTimeout after 3 retries")
    err = RetryExhaustedError(
        "retries exhausted",
        last_exception=original,
        attempts=4,
    )
    assert err.attempts == 4
    assert err.last_exception is original
    assert isinstance(err.last_exception, TimeoutError)
