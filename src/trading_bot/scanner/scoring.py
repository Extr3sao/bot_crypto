"""Scoring y normalizacion para ranking de pares (TSK-103.3/F3).

Implementa la formula cerrada de RF-10 per
``docs/specs/TSK-103-universe-scanner/03-specify.md`` seccion 6. El
``rank_score`` es un escalar en ``[0, 1]`` que pondera 3 componentes:

- Spread (peso 0.5, negative correlation): menor spread -> mejor score.
- Volume (peso 0.3, positive correlation): mayor volumen -> mejor score.
- ATR en rango (peso 0.2, binary): 1.0 si ``atr_en_rango == True`` AND
  ``atr_pct`` no es ``None``; 0.0 en cualquier otro caso
  (incluso si ``atr_en_rango == True`` con ``atr_pct is None``;
  defensivo contra valores faltantes).

Coeficientes fijos por diseno (ADR lock per spec §6). Cualquier cambio
de los pesos o de la semantica del ``atr_term`` requiere ADR firmada en
``tasks/decisions.md``.

Invariante pinada por tests:

- ``0 <= compute_rank_score(...) <= 1`` para todos los inputs finitos.
- Monotonia: a igual volumen/atr, mayor ``spread_bps`` produce menor score.
- Determinismo: dos calls con inputs identicos producen score bit-identical.
- Defensivo: NaN/inf inputs -> ``ValueError`` explicito (no propagacion
  silenciosa); ``norm_max <= 0`` -> ``ValueError`` (no ``ZeroDivisionError``
  natural).

Cross-layer: cero imports cross-layer; solo stdlib ``math`` para la
guarda finiteness. Pine contract por ``tests/unit/scanner/test_cross_layer.py``
(TSK-103.4.9 cross-layer enforcement, F4).
"""

from __future__ import annotations

import math
from typing import Final

# ----------------------------------------------------------------------------
# Coeficientes ADR-locked (spec §6).
# Expuestos como Final[float] para que los tests los pineen como invariantes.
# Cualquier cambio aqui requiere ADR firmada en tasks/decisions.md.
# ----------------------------------------------------------------------------

SPREAD_WEIGHT: Final[float] = 0.5
"""Peso del componente spread (tightness premium)."""

VOLUME_WEIGHT: Final[float] = 0.3
"""Peso del componente volumen (liquidity premium)."""

ATR_WEIGHT: Final[float] = 0.2
"""Peso del componente atr_term (volatility fit)."""


# ----------------------------------------------------------------------------
# Helpers privados: defensive guards.
# ----------------------------------------------------------------------------


def _validate_finite(name: str, value: float) -> None:
    """Guard defensivo: rechaza NaN/inf (no permite silenciar NaN).

    Usado por ``compute_rank_score`` para pinear el contrato de inputs
    antes de la division que propagaria NaN y romperia la invariante
    ``0 <= score <= 1`` silenciosamente.

    Nota: NO valida no-negatividad (el nombre anterior ``_validate_finite_non_negative``
    mentia; inputs como ``volume_24h_usdt`` o ``atr_pct`` pueden ser
    negativos upstream y se clipa en la division + clip externo). Si
    una entrada concreta requiere pine contrato ``>= 0``, el guard
    adicional se aplica en el call site con un chequeo explicito.
    """
    if not math.isfinite(value):
        raise ValueError(f"{name} debe ser finito; got {value!r}")


def _validate_positive_denominator(name: str, value: float) -> None:
    """Guard adicional: ``norm_max`` debe ser > 0 (denominador)."""
    if value <= 0:
        raise ValueError(f"{name} debe ser > 0 (denominador); got {value!r}")


# ----------------------------------------------------------------------------
# API publica
# ----------------------------------------------------------------------------


def compute_rank_score(
    spread_bps: float,
    spread_norm_max: float,
    volume_24h_usdt: float,
    volume_norm_max: float,
    atr_pct: float | None,
    atr_optimo: float,
    atr_en_rango: bool,
) -> float:
    """RF-10: scoring cerrado per spec §6 (formula ADR-locked).

    Componentes (coeficientes pine contract):

        0.5 * (1 - spread_norm)   tightness premium (lower spread better).
        0.3 * vol_norm              liquidity premium (higher volume better).
        0.2 * atr_term              volatility fit (binary under RF-10 v1).

    Comportamiento:

    - ``spread_norm = clip(spread_bps / spread_norm_max, 0, 1)``.
    - ``vol_norm = clip(volume_24h_usdt / volume_norm_max, 0, 1)``.
    - ``atr_term = 1.0`` si ``atr_en_rango and atr_pct is not None``;
      ``0.0`` en cualquier otro caso (incluye ``atr_en_rango=True`` con
      ``atr_pct=None``: defensivo contra missing-data).
    - Retorna valor en ``[0, 1]`` para todos los inputs finitos.

    Param ``atr_optimo`` se conserva en la firma aunque v1 solo usa
    ``atr_en_rango`` (binary). Reservado para la extension RF-10 v2
    propuesta en ADR-0013: atr_term continua basada en proximity-to-
    optimum (``1 - |atr_pct - atr_optimo| / max_deviation``,
    clamped a [0, 1]). El renaming a ``_atr_optimo`` o el uso en la
    formula cerrada requiere ADR firmada.

    Raises:
        ValueError: si cualquier input numerico no es finito, o si
            ``spread_norm_max`` o ``volume_norm_max`` son <= 0. La
            propagacion silenciosa de NaN o ZeroDivisionError se
            pine contract con raise explicito en lugar de tolerar
            ``score is nan`` o ``score is inf``.
    """
    # Finite guards (rechaza NaN/inf silent antes del clip).
    _validate_finite("spread_bps", spread_bps)
    _validate_positive_denominator("spread_norm_max", spread_norm_max)
    _validate_finite("volume_24h_usdt", volume_24h_usdt)
    _validate_positive_denominator("volume_norm_max", volume_norm_max)
    _validate_finite("atr_optimo", atr_optimo)
    if atr_pct is not None:
        _validate_finite("atr_pct", atr_pct)

    # Componentes normalizados, cada uno ∈ [0, 1] por el clip.
    spread_norm = min(max(spread_bps / spread_norm_max, 0.0), 1.0)
    vol_norm = min(max(volume_24h_usdt / volume_norm_max, 0.0), 1.0)
    atr_term = 1.0 if atr_en_rango and atr_pct is not None else 0.0

    return SPREAD_WEIGHT * (1.0 - spread_norm) + VOLUME_WEIGHT * vol_norm + ATR_WEIGHT * atr_term


__all__ = [
    "ATR_WEIGHT",
    "SPREAD_WEIGHT",
    "VOLUME_WEIGHT",
    "compute_rank_score",
]
