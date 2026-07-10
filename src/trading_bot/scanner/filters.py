"""Filtros default del scanner (TSK-103.2/F2).

Tres filtros, cada uno encapsula una sola decision (SRP):

- ``VolumeFilter``: volumen 24h en USDT; modo live endurece a 10M USDT.
- ``SpreadFilter``: maximo spread permitido en basis points.
- ``AtrFilter``: ATR en % dentro de ``[min_pct, max_pct]``;
  ``insufficient_history`` si OHLCV < ``min_history``.

Implementan el ``Filter`` Protocol estructural de
``scanner/protocols.py`` (atributo de clase ``name`` + metodo async
``apply(symbol, source) -> FilterOutcome``). NO conocen al
orquestador ni a otros filtros (SRP; composicion la gestiona el
``FilterRegistry``).

Cross-layer: solo importan de ``trading_bot.market_data.types`` (OHLCV)
y de modulos internos del paquete ``trading_bot.scanner``. Pineado
por el test AST ``tests/unit/scanner/test_cross_layer.py`` (TSK-103.4.9).

ADR-locks pineados por tests:

- VolumeFilter comportamiento por modo (D1-A del thinker):
  el filtro resuelve el threshold segun ``mode`` pasado en
  constructor y emite exactamente uno de:
    * ``"volume_below_threshold"``                -> paper/research/backtest.
    * ``"volume_below_threshold_for_live_min_10M"`` -> live, si
      ``live_min_usdt`` configurado.
  Pineado por ``test_volume_*``.
- Helper ``_compute_atr_pct`` interno (Decision X): el scanner NO
  importa ``indicators.*`` por cross-layer enforcement; ATR se calcula
  in-place sobre los OHLCV ya fetcheados (math ligero).
"""

from __future__ import annotations

from typing import Final

from trading_bot.market_data.types import OHLCV
from trading_bot.scanner.protocols import MarketDataSourceProtocol
from trading_bot.scanner.types import FilterOutcome, RejectionReason

# ----------------------------------------------------------------------------
# Constantes publicas (parte del API publico del modulo).
# ----------------------------------------------------------------------------

VALID_MODES: Final[frozenset[str]] = frozenset({"research", "backtest", "paper", "live"})
"""Modos de runtime aceptados por ``VolumeFilter``. Pineado en test."""


# ----------------------------------------------------------------------------
# Helpers privados
# ----------------------------------------------------------------------------


def _arith_mean(values: list[float]) -> float:
    """Media aritmetica; 0.0 si la lista esta vacia."""
    return sum(values) / len(values) if values else 0.0


def _compute_atr_pct(candles: list[OHLCV]) -> float:
    """Average True Range expresado como % del ultimo close.

    True Range vela ``i``:
        ``max(high_i - low_i, |high_i - close_{i-1}|, |low_i - close_{i-1}|)``

    ATR = media de los True Ranges del batch.
    ``ATR% = (ATR / last_close) * 100``.

    Edge cases (pineados en test):
    - ``len(candles) < 2`` -> 0.0 (no se puede calcular ATR).
    - ``last_close is None`` -> 0.0 (defensivo; actualmente
      ``OHLCV.close`` es ``float`` no-Optional, pero el check cubre
      una futura migracion a ``Optional[float]`` sin romper el helper).
    - ``last_close <= 0``  -> 0.0 (defensivo contra input invalido,
      no deberia pasar dado el dataclass OHLCV pero barato cubrirlo).
    """
    # TODO(R5-LATENT): Este helper calcula ATR como ``mean(TR_1..TR_N)``
    # sobre TODAS las velas recibidas, NO como ATR-Wilder de ventana
    # fija (e.g. ATR-14). Si se requiere ATR-14 estricto, los pasos son:
    # (a) aceptar ``window: int`` opcional como parametro del helper,
    # (b) decidir si las N velas vienen ya recortadas de
    # ``MarketDataSourceProtocol.fetch_recent`` o se hace in-place usando
    # las ``min_history`` velas, (c) emitir ADR firmada en
    # ``tasks/decisions.md`` para cambiar la firma publica antes de
    # modificar los tests pineadores
    # (``tests/unit/scanner/test_filters.py::test_compute_atr_pct_*``).
    # El ratio contractual hoy es ``daily_range=1 sobre last_close=100
    # => ATR% == 2.0``; ese invariant debe preservarse o documentarse
    # explicitamente en la ADR de inversion. Reread este comentario
    # antes de cualquier modificacion a la firma del helper.
    if len(candles) < 2:
        return 0.0
    last_close = candles[-1].close
    if last_close is None or last_close <= 0:
        return 0.0
    true_ranges: list[float] = []
    for i in range(1, len(candles)):
        cur = candles[i]
        prev = candles[i - 1]
        true_ranges.append(
            max(
                cur.high - cur.low,
                abs(cur.high - prev.close),
                abs(cur.low - prev.close),
            )
        )
    atr = _arith_mean(true_ranges)
    return atr / last_close * 100.0


# ----------------------------------------------------------------------------
# VolumeFilter
# ----------------------------------------------------------------------------


class VolumeFilter:
    """Filtra por volumen 24h en USDT; el modo live endurece el umbral.

    Decision D1-A del thinker (ADR-lock): el filtro recibe ``mode`` en
    constructor para resolver threshold + motivo de rechazo en su
    propio modulo, sin empujar logica de modo al orquestador.

    Reason mapping (ADR-lock catalog cerrado):
    - ``paper`` / ``research`` / ``backtest``: ``"volume_below_threshold"``.
    - ``live`` con ``live_min_usdt`` configurado: ``"volume_below_threshold_for_live_min_10M"``
      si el volumen esta por debajo del live threshold.

    Pine contract:
    - ``min_usdt >= 0``.
    - ``live_min_usdt >= min_usdt`` (live nunca mas permisivo que paper).
    - ``mode in VALID_MODES``.
    """

    name: str = "volume"

    def __init__(
        self,
        min_usdt: float,
        mode: str,
        live_min_usdt: float | None = None,
    ) -> None:
        if min_usdt < 0:
            raise ValueError(f"min_usdt debe ser >= 0; got {min_usdt}")
        if live_min_usdt is not None:
            if live_min_usdt < 0:
                raise ValueError(f"live_min_usdt debe ser >= 0; got {live_min_usdt}")
            if live_min_usdt < min_usdt:
                raise ValueError(
                    f"live_min_usdt ({live_min_usdt}) debe ser >= "
                    f"min_usdt ({min_usdt}); live no puede ser mas permisivo."
                )
        if mode not in VALID_MODES:
            raise ValueError(f"mode invalido {mode!r}; esperado uno de {sorted(VALID_MODES)}")
        self.min_usdt = min_usdt
        self.mode = mode
        self.live_min_usdt = live_min_usdt

    async def apply(self, symbol: str, source: MarketDataSourceProtocol) -> FilterOutcome:
        volume_usdt = await source.fetch_24h_volume_usdt(symbol)
        if self.mode == "live" and self.live_min_usdt is not None:
            threshold = self.live_min_usdt
            reason: RejectionReason = "volume_below_threshold_for_live_min_10M"
        else:
            threshold = self.min_usdt
            reason = "volume_below_threshold"
        if volume_usdt < threshold:
            return FilterOutcome(passed=False, reason=reason)
        return FilterOutcome(passed=True, reason=None)


# ----------------------------------------------------------------------------
# SpreadFilter
# ----------------------------------------------------------------------------


class SpreadFilter:
    """Filtra por spread top-of-book en basis points.

    Acepta el spread exactamente igual al ``max_bps`` (no es un fail,
    solo ``>``). Moda unica, sin dependencia de ``runtime.mode``.

    Reason mapping (ADR-lock):
    - ``"spread_above_threshold"`` siempre que ``spread > max_bps``.
    """

    name: str = "spread"

    def __init__(self, max_bps: float) -> None:
        if max_bps < 0:
            raise ValueError(f"max_bps debe ser >= 0; got {max_bps}")
        self.max_bps = max_bps

    async def apply(self, symbol: str, source: MarketDataSourceProtocol) -> FilterOutcome:
        spread = await source.fetch_spread_bps(symbol)
        if spread > self.max_bps:
            return FilterOutcome(passed=False, reason="spread_above_threshold")
        return FilterOutcome(passed=True, reason=None)


# ----------------------------------------------------------------------------
# AtrFilter
# ----------------------------------------------------------------------------


class AtrFilter:
    """Filtra por ATR en % dentro de ``[min_pct, max_pct]``.

    Si la fuente retorna menos de ``min_history`` velas -> ``"insufficient_history"``.
    Si ATR_pct calculado cae fuera del rango -> ``"atr_out_of_range"``.

    Pine contract:
    - ``0 <= min_pct <= max_pct``.
    - ``min_history >= 1``.
    """

    name: str = "atr"

    def __init__(
        self,
        min_pct: float,
        max_pct: float,
        min_history: int = 100,
    ) -> None:
        if min_pct < 0 or max_pct < 0:
            raise ValueError(f"ATR percent bounds deben ser >= 0; got min={min_pct} max={max_pct}")
        if max_pct < min_pct:
            raise ValueError(f"max_pct ({max_pct}) debe ser >= min_pct ({min_pct})")
        if min_history < 1:
            raise ValueError(f"min_history debe ser >= 1; got {min_history}")
        self.min_pct = min_pct
        self.max_pct = max_pct
        self.min_history = min_history

    async def apply(self, symbol: str, source: MarketDataSourceProtocol) -> FilterOutcome:
        candles = await source.fetch_recent(symbol, self.min_history)
        if len(candles) < self.min_history:
            return FilterOutcome(passed=False, reason="insufficient_history")
        atr_pct = _compute_atr_pct(candles)
        if atr_pct < self.min_pct or atr_pct > self.max_pct:
            return FilterOutcome(passed=False, reason="atr_out_of_range")
        return FilterOutcome(passed=True, reason=None)


__all__ = [
    "VALID_MODES",
    "AtrFilter",
    "SpreadFilter",
    "VolumeFilter",
    "_compute_atr_pct",  # publico por convencion para tests.
]
