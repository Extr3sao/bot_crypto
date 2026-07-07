"""Tests unitarios para ``src/trading_bot/scanner/types.py``.

Estrategia: tests deterministas sin fixtures costosos; pinning
contractual del dataclass ``frozen=True`` + ``slots=True`` + Literal.
Tests rapidos (<50ms total) para CI.

Cobertura esperada per DoD F1: 8 tests verde en este archivo.
Mas tests vendran en TSK-103.2..103.4 segun ``docs/specs/TSK-103-
universe-scanner/05-tasks.md``.
"""

from __future__ import annotations

import dataclasses
from typing import get_args

import pytest

from trading_bot.scanner.exceptions import (
    ConfigurationError,
    KillSwitchActiveError,
    ScannerError,
)
from trading_bot.scanner.types import (
    FilterOutcome,
    MarketSnapshot,
    RejectionReason,
)

# ---------------------------------------------------------------------------
# Helpers de construccion.
# ---------------------------------------------------------------------------


def _make_snapshot(**overrides: object) -> MarketSnapshot:
    """Construye un ``MarketSnapshot`` valido con overrides keyword-only.

    Los defaults reflejan un par sano (BTC/USDT con volumen > minimo,
    spread < maximo, ATR en rango optimo).
    """
    defaults: dict[str, object] = {
        "symbol": "BTC/USDT",
        "last_price": 16555.5,
        "volume_24h_usdt": 50_000_000.0,
        "spread_bps": 12.0,
        "atr_pct": 1.5,
        "volatility_pct": 0.8,
        "active": True,
        "rejection_reason": None,
        "timestamp": 1672531200000,
        "rank_score": 0.85,
    }
    defaults.update(overrides)
    return MarketSnapshot(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Estructura del dataclass: campos y orden.
# ---------------------------------------------------------------------------


def test_snapshot_frozen_mutation_raises() -> None:
    """Pinea RNF-6: ``frozen=True`` levanta FrozenInstanceError al mutar."""
    snap = _make_snapshot()
    with pytest.raises(dataclasses.FrozenInstanceError):
        snap.rank_score = 0.99  # type: ignore[misc]


def test_snapshot_first_field_is_symbol() -> None:
    """Sentinel explicito: ``symbol`` debe ser el primer campo del
    dataclass (jerarquia coherente con PK SQL ``(symbol, timestamp)``
    del ``OHLCVStore`` y con ``universe.pairs[i].symbol`` de
    ``config/assets.yaml``).
    """
    assert dataclasses.fields(MarketSnapshot)[0].name == "symbol"


def test_snapshot_field_order_matches_spec() -> None:
    """Pinea el orden contractual exacto del dataclass (10 campos)."""
    expected = (
        "symbol",
        "last_price",
        "volume_24h_usdt",
        "spread_bps",
        "atr_pct",
        "volatility_pct",
        "active",
        "rejection_reason",
        "timestamp",
        "rank_score",
    )
    actual = tuple(f.name for f in dataclasses.fields(MarketSnapshot))
    assert actual == expected


def test_snapshot_uses_slots() -> None:
    """Pinea RNF-6: ``slots=True`` reduce overhead de memoria por
    iteracion (importante cuando el scanner produce 25+
    snapshots/iteration).

    Tightness: NO basta con verificar que ``__slots__`` existe (eso haria
    cualquier tupla vacia o un solo campo). Pineamos que la tupla completa
    coincide 1:1, en orden de declaracion contractual, con los 10 campos
    del dataclass. Cualquier regresion a ``slots=False``, un renombre de
    un campo sin propagar al slot, o insercion de un nuevo campo sin
    extender este test rompe el ADR-locked pine.
    """
    expected_slots: tuple[str, ...] = (
        "symbol",
        "last_price",
        "volume_24h_usdt",
        "spread_bps",
        "atr_pct",
        "volatility_pct",
        "active",
        "rejection_reason",
        "timestamp",
        "rank_score",
    )
    actual_slots: tuple[str, ...] = MarketSnapshot.__slots__
    assert actual_slots == expected_slots


# ---------------------------------------------------------------------------
# FilterOutcome.
# ---------------------------------------------------------------------------


def test_outcome_frozen_mutation_raises() -> None:
    outcome = FilterOutcome(passed=True)
    with pytest.raises(dataclasses.FrozenInstanceError):
        outcome.passed = False  # type: ignore[misc]


def test_outcome_default_reason_is_none() -> None:
    """Cuando solo se pasa ``passed=True``, ``reason`` default = None
    (compatible con passed=True)."""
    outcome = FilterOutcome(passed=True)
    assert outcome.reason is None


def test_outcome_failed_carries_reason() -> None:
    """Sentinela semantico: ``passed=False`` siempre lleva ``reason``
    (contrato no-enforced por dataclass; pineado por test)."""
    fail = FilterOutcome(passed=False, reason="atr_out_of_range")
    assert fail.passed is False
    assert fail.reason == "atr_out_of_range"


# ---------------------------------------------------------------------------
# RejectionReason literal.
# ---------------------------------------------------------------------------


def test_rejection_reason_literal_values() -> None:
    """ADR lock: el Literal ``RejectionReason`` contiene exactamente
    los 7 valores documentados en spec y BDD. Cualquier cambio futuro
    rompe este test, forzando ``update del .feature + revision del
    orchestrator + posible ADR``.
    """
    expected = {
        "not_whitelisted",
        "volume_below_threshold",
        "volume_below_threshold_for_live_min_10M",
        "spread_above_threshold",
        "atr_out_of_range",
        "insufficient_history",
        "price_below_threshold",
    }
    actual = set(get_args(RejectionReason))
    assert actual == expected


# ---------------------------------------------------------------------------
# Jerarquia de excepciones.
# ---------------------------------------------------------------------------


def test_exceptions_inherit_scanner_error() -> None:
    assert issubclass(KillSwitchActiveError, ScannerError)
    assert issubclass(ConfigurationError, ScannerError)
    assert issubclass(ScannerError, Exception)
    # Sentinel: ScannerError NO debe ser KeyboardInterrupt/SystemExit
    # para no atrapar el shutdown del interpreter accidentalmente.
    # NOTA: ScannerError SI es subclass de BaseException (vía Exception
    # que extiende BaseException); eso es normal y no es lo que pineamos
    # aqui. Lo que pineamos es que NO sea una de las dos clases criticas
    # del flujo de control de CPython.
    assert ScannerError is not KeyboardInterrupt
    assert ScannerError is not SystemExit
