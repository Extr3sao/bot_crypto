"""Tipos publicos del scanner.

Capa de dominio aislada (regla arquitectonica §11 + §14 en
``docs/architecture.md``). Los dataclasses son ``frozen=True`` +
``slots=True`` y NO importan ``exchange``, ``strategies``,
``execution`` ni ``risk``.

Historiador:
- Round-2 P1 (TSK-102, ``context/retrieval-log.md`` 2026-07-04 04:30)
  corrigio el dataclass ``OHLCV`` para incluir ``symbol`` despues de
  detectar que el ``OHLCVStore`` pineaba ``(symbol, timestamp)`` como
  PK compuesta. El mismo principio justifica que ``symbol`` sea el
  PRIMER campo de ``MarketSnapshot``: alineado con la jerarquia de la
  clave primaria en ``config/universe.yaml``
  (``universe.pairs[i].symbol``).

Regla de extension (ADR-0001 implicitamente via doc-style):
- Anadir un valor al ``Literal`` ``RejectionReason`` requiere:
  1. Anadir el valor en este Literal.
  2. Anadir un escenario BDD en ``bdd/features/market_scanner.feature``
     que cubra el nuevo motivo (regla del BDD: 100% cobertura RF -> BDD).
  3. Si el motivo es semantics-sensitive para money-risk o invariants
     de negocio, firmar ADR en ``tasks/decisions.md``.
- Renombrar o quitar un valor existente requiere ADR firmada + revision
  del BDD feature por impactos downstream.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# Catalogo cerrado de motivos por los que un par puede quedar inactivo
# en un ``MarketSnapshot``. Los valores documentados coinciden
# 1:1 con los escenarios Gherkin del .feature file del scanner
# (RF-3 + CLs del spec TSK-103.1):
#
#   - "not_whitelisted"                          -> Scenario "Ignorar pares no permitidos".
#   - "volume_below_threshold"                   -> Scenario "Rechazar par sin volumen suficiente".
#   - "spread_above_threshold"                  -> Scenario "Rechazar par con spread excesivo".
#   - "atr_out_of_range"                         -> Scenario "Rechazar par con ATR fuera de rango".
#   - "insufficient_history"                     -> Scenario "Motivo insufficient_history cuando OHLCV < N".
#   - "volume_below_threshold_for_live_min_10M" -> Scenario "Modo live endurece filtro volumen a 10M USDT".
#   - "price_below_threshold"                    -> Scenario "Custom filter se anade al registry".
#
# Cualquier desvío aqui DEBE propagarse al .feature, a la BDD, y si
# toca money-risk, a una ADR firmada (regla metodologica SDD/BDD).
RejectionReason = Literal[
    "not_whitelisted",
    "volume_below_threshold",
    "volume_below_threshold_for_live_min_10M",
    "spread_above_threshold",
    "atr_out_of_range",
    "insufficient_history",
    "price_below_threshold",
]


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    """Salida canonica del scanner.

    Inmutable (``frozen=True``) y ``slots=True`` para:
    - Prevenir mutacion accidental en retries del scheduler
      (TSK-104+).
    - Minimizar el overhead de memoria por iteracion (RNF-2):
      un snapshot pesa ~140 bytes con ``slots=True`` vs ~280 sin.
    - Detectar intentos de mutacion via
      ``dataclasses.FrozenInstanceError`` en tests (RNF-6).

    El campo ``symbol`` va PRIMERO por consistencia con:
    - ``universe.pairs[i].symbol`` (``config/assets.yaml``).
    - PK compuesta ``(symbol, timestamp)`` del ``OHLCVStore``
      (TSK-102).
    - Dataclass ``OHLCV`` (TSK-102 round-2 fix).
    """

    symbol: str                          # par BASE/QUOTE (e.g. "BTC/USDT").
    last_price: float                    # ultimo close de OHLCV reciente.
    volume_24h_usdt: float               # volumen rolling 24h en USDT.
    spread_bps: float                    # spread top-of-book en basis points.
    atr_pct: float | None             # None si insufficient_history.
    volatility_pct: float | None      # Idem (extensibilidad Fase 2 ATR).
    active: bool                         # True si pasa todos los filtros default.
    rejection_reason: RejectionReason | None  # None si active=True.
    timestamp: int                       # ms since epoch (OHLCV reciente).
    rank_score: float                    # ∈ [0, 1]. 0.0 si active=False.


@dataclass(frozen=True, slots=True)
class FilterOutcome:
    """Resultado de aplicar un filtro individual (TSK-103.2).

    ``FilterRegistry`` (TSK-103.2) compone N filtros sobre cada par;
    el primer fallo corto-circuita el resto (decision de performance
    documentada en ``docs/specs/TSK-103-universe-scanner/05-tasks.md``
    TSK-103.4.4). Esta dataclass es el contrato minimo de salida.

    Invariante semantica (no enforced por dataclass; pine contract):
    ``passed=False`` implica ``reason != None``. Tests pine este
    contrato en ``tests/unit/scanner/test_types.py``.
    """

    passed: bool
    reason: RejectionReason | None = None


__all__ = ["FilterOutcome", "MarketSnapshot", "RejectionReason"]
