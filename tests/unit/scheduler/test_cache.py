"""Tests unitarios para ``src/trading_bot/scheduler/cache.py``.

Pinea el contrato pure-function de ``evaluate_cache_hit`` (RF-4) con
boundary cases exhaustivos via parametrizacion.

Cobertura esperada per DoD F2 (TSK-104.2.1): 14 tests verde (3 core
+ 11 parametrizados cubriendo 4 paths + boundary strict-< +
multi-TF + invalid params + purity sentinel).
"""

from __future__ import annotations

import dataclasses
from typing import get_args

import pytest

from trading_bot.scheduler.cache import evaluate_cache_hit
from trading_bot.scheduler.types import CacheHitDecision, CacheState

# ---------------------------------------------------------------------------
# Helpers de construccion.
# ---------------------------------------------------------------------------


def _evaluate(
    *,
    last_candle_ts: int | None,
    current_ts: int,
    primary_timeframe_ms: int = 5 * 60 * 1000,  # 5min default
    freshness_window_ms: int = 5 * 60 * 1000,  # 5min default (decay 0)
) -> CacheHitDecision:
    """Helper: invoca evaluate_cache_hit con defaults realistas."""
    return evaluate_cache_hit(
        last_candle_ts=last_candle_ts,
        current_ts=current_ts,
        primary_timeframe_ms=primary_timeframe_ms,
        freshness_window_ms=freshness_window_ms,
    )


# ---------------------------------------------------------------------------
# Path 1: EMPTY (no prior candle).
# ---------------------------------------------------------------------------


def test_evaluate_cache_hit_empties_when_no_last_candle() -> None:
    """last_candle_ts=None -> state=EMPTY + should_pull=True."""
    decision = _evaluate(
        last_candle_ts=None,
        current_ts=1_672_531_260_000,
    )
    assert decision.state is CacheState.EMPTY
    assert decision.last_candle_ts is None
    assert decision.should_pull is True
    assert "no prior candle" in decision.reason


# ---------------------------------------------------------------------------
# Path 2: FRESH (periodo actual + dentro de ventana de freshness).
# ---------------------------------------------------------------------------


def test_evaluate_cache_hit_fresh_when_vela_in_current_period_under_window() -> None:
    """5m TF, vela 4min old -> FRESH (periodo actual + freshness)."""
    current_ts = 1_672_531_260_000
    last_candle_ts = current_ts - 4 * 60 * 1000  # 4 min ago
    decision = _evaluate(
        last_candle_ts=last_candle_ts,
        current_ts=current_ts,
    )
    assert decision.state is CacheState.FRESH
    assert decision.should_pull is False


@pytest.mark.parametrize(
    "age_ms,expected_state,expected_pull",
    [
        # Boundary strict-<: age == 0 is fresh
        (0, CacheState.FRESH, False),
        # Below TF: age < TF => period current
        (60 * 1000, CacheState.FRESH, False),  # 1 min
        (4 * 60 * 1000, CacheState.FRESH, False),  # 4 min (under window)
        # boundary strict-< for freshness: age == freshness - 1ms
        (5 * 60 * 1000 - 1, CacheState.FRESH, False),
    ],
)
def test_evaluate_cache_hit_is_fresh_at_minute_resolution(
    age_ms: int, expected_state: CacheState, expected_pull: bool
) -> None:
    """Pinea boundary strict-< para freshness window."""
    current_ts = 1_672_531_260_000
    decision = _evaluate(
        last_candle_ts=current_ts - age_ms,
        current_ts=current_ts,
    )
    assert decision.state is expected_state
    assert decision.should_pull is expected_pull


# ---------------------------------------------------------------------------
# Path 3: STALE (periodo previo OR dentro del periodo actual pero fuera).
# ---------------------------------------------------------------------------


def test_evaluate_cache_hit_stale_when_previous_period() -> None:
    """5m TF, vela 10min old -> STALE (vela de periodo previo)."""
    current_ts = 1_672_531_260_000
    last_candle_ts = current_ts - 10 * 60 * 1000  # 10 min ago (2 periods prev)
    decision = _evaluate(
        last_candle_ts=last_candle_ts,
        current_ts=current_ts,
    )
    assert decision.state is CacheState.STALE
    assert decision.should_pull is True


def test_evaluate_cache_hit_stale_when_current_period_outside_window() -> None:
    """5m TF, vela 4min ago pero freshness 1ms (current period + fuera de window).

    Caso edge: ventana de freshness 1ms -> solo age == 0 es fresh.
    Esto pinea que current_period=True AND is_fresh=False -> STALE
    (tercer path, pine contract 03-specify §4).
    """
    current_ts = 1_672_531_260_000
    decision = _evaluate(
        last_candle_ts=current_ts - 4 * 60 * 1000,  # 4 min ago (current period)
        current_ts=current_ts,
        freshness_window_ms=1,  # window minimo valido (>= 1ms per guard)
    )
    assert decision.state is CacheState.STALE
    assert decision.should_pull is True


@pytest.mark.parametrize(
    "age_ms,expected_state,expected_pull",
    [
        # boundary strict-<: age == freshness (exact) -> STALE
        (5 * 60 * 1000, CacheState.STALE, True),
        # Vela de periodo previo (mas alla del primary timeframe)
        (10 * 60 * 1000, CacheState.STALE, True),  # 2 periods prev (TF=5min)
        (30 * 60 * 1000, CacheState.STALE, True),  # 6 periods prev
        (60 * 60 * 1000, CacheState.STALE, True),  # 12 periods prev
        # boundary strict-< para period current: age == primary tf -> STALE
        (5 * 60 * 1000, CacheState.STALE, True),  # vela exactly 1 period old
    ],
)
def test_evaluate_cache_hit_is_stale_past_boundary(
    age_ms: int, expected_state: CacheState, expected_pull: bool
) -> None:
    """Pinea boundary strict-< para freshness + previous-period detection."""
    current_ts = 1_672_531_260_000
    decision = _evaluate(
        last_candle_ts=current_ts - age_ms,
        current_ts=current_ts,
    )
    assert decision.state is expected_state
    assert decision.should_pull is expected_pull


# ---------------------------------------------------------------------------
# Boundary: age == freshness exactly (strict-< rejection).
# ---------------------------------------------------------------------------


def test_evaluate_cache_hit_boundary_age_at_exactly_freshness_is_stale() -> None:
    """Pinea contract: age == freshness -> STALE (strict <, no <=)."""
    current_ts = 1_672_531_260_000
    decision = _evaluate(
        last_candle_ts=current_ts - 5 * 60 * 1000,  # age == freshness exact
        current_ts=current_ts,
    )
    assert decision.state is CacheState.STALE
    assert decision.should_pull is True


def test_evaluate_cache_hit_boundary_age_one_ms_under_freshness_is_fresh() -> None:
    """Pinea contract: age == freshness - 1ms -> FRESH (last fresh moment)."""
    current_ts = 1_672_531_260_000
    decision = _evaluate(
        last_candle_ts=current_ts - (5 * 60 * 1000 - 1),  # age = fresh - 1ms
        current_ts=current_ts,
    )
    assert decision.state is CacheState.FRESH
    assert decision.should_pull is False


def test_evaluate_cache_hit_boundary_age_at_exactly_primary_period_is_stale() -> None:
    """Pinea contract: age == primary_tf -> STALE (vela de periodo previo)."""
    current_ts = 1_672_531_260_000
    decision = _evaluate(
        last_candle_ts=current_ts - 5 * 60 * 1000,  # age == TF exact => previous
        current_ts=current_ts,
    )
    assert decision.state is CacheState.STALE


# ---------------------------------------------------------------------------
# Multi-timeframe coverage (parametrized over TFs).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tf_label,tf_ms,freshness_ms",
    [
        ("1m", 60 * 1000, 60 * 1000),
        ("5m", 5 * 60 * 1000, 5 * 60 * 1000),
        ("15m", 15 * 60 * 1000, 15 * 60 * 1000),
        ("1h", 60 * 60 * 1000, 60 * 60 * 1000),
        ("4h", 4 * 60 * 60 * 1000, 4 * 60 * 60 * 1000),
    ],
)
def test_evaluate_cache_hit_supports_different_timeframes(
    tf_label: str, tf_ms: int, freshness_ms: int
) -> None:
    """Pinea que evaluate_cache_hit funciona para 5 TFs comunes.

    Caso: vela TF/2 ago (FRESCA) -> should_pull=False; vela 2*TF ago
    (STALE, periodo previo) -> should_pull=True.
    """
    current_ts = 1_672_531_260_000
    fresh_decision = _evaluate(
        last_candle_ts=current_ts - tf_ms // 2,  # TF/2 ago = current period
        current_ts=current_ts,
        primary_timeframe_ms=tf_ms,
        freshness_window_ms=freshness_ms,
    )
    stale_decision = _evaluate(
        last_candle_ts=current_ts - 2 * tf_ms,  # 2 TFs ago = previous period
        current_ts=current_ts,
        primary_timeframe_ms=tf_ms,
        freshness_window_ms=freshness_ms,
    )
    assert fresh_decision.state is CacheState.FRESH, f"TF={tf_label} fresh case"
    assert fresh_decision.should_pull is False, f"TF={tf_label} fresh case"
    assert stale_decision.state is CacheState.STALE, f"TF={tf_label} stale case"
    assert stale_decision.should_pull is True, f"TF={tf_label} stale case"


# ---------------------------------------------------------------------------
# Param validation (defensive).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_tf,bad_fresh,why",
    [
        (0, 60 * 1000, "primary_timeframe_ms=0 is invalid"),
        (-1, 60 * 1000, "negative primary_timeframe_ms"),
        (60 * 1000, 0, "freshness_window_ms=0 invalid"),
        (60 * 1000, -100, "negative freshness_window_ms"),
    ],
)
def test_evaluate_cache_hit_invalid_params_raise_value_error(
    bad_tf: int, bad_fresh: int, why: str
) -> None:
    """Parametros invalidos -> ValueError (fail-fast)."""
    with pytest.raises(ValueError, match=r"must be > 0"):
        _evaluate(
            last_candle_ts=1_672_531_260_000,
            current_ts=1_672_531_261_000,
            primary_timeframe_ms=bad_tf,
            freshness_window_ms=bad_fresh,
        )


# ---------------------------------------------------------------------------
# Pure-function sentinel: no side-effects verificables.
# ---------------------------------------------------------------------------


def test_evaluate_cache_hit_is_pure_function() -> None:
    """Repetidas invocaciones con los mismos args retornan el mismo objeto
    semantico (CacheHitDecision frozen + slots + dataclass equality).

    Sentinel anti-regresion: si alguien introduce side-effects (e.g. un
    cache LRU interno, una seed global, un wrapper async), este test
    cae o se vuelve flaky.
    """
    current_ts = 1_672_531_260_000
    args = dict(
        last_candle_ts=current_ts - 60 * 1000,
        current_ts=current_ts,
        primary_timeframe_ms=5 * 60 * 1000,
        freshness_window_ms=5 * 60 * 1000,
    )
    decision_1 = evaluate_cache_hit(**args)
    decision_2 = evaluate_cache_hit(**args)
    assert decision_1 == decision_2
    # Frozen + slots: no mutation possible.
    with pytest.raises(dataclasses.FrozenInstanceError):
        decision_1.should_pull = True


# ---------------------------------------------------------------------------
# Contract guard: CacheHitDecision siempre retorna state from enum
# ---------------------------------------------------------------------------


def test_evaluate_cache_hit_decision_state_is_in_enum() -> None:
    """Pinea decision.state in CacheState enum (no string leaks)."""
    decision = _evaluate(
        last_candle_ts=1_672_531_260_000 - 60 * 1000,
        current_ts=1_672_531_260_000,
    )
    assert decision.state in set(get_args(CacheState)) or decision.state in set(CacheState)
