"""Convenience builders para registries per-mode (TSK-103.4/F4).

R1-HIGH resolution: ``VolumeFilter.mode`` esta pineado en constructor
(ADR-lock D1-A). Para alternar el endurcimiento del threshold entre
``paper`` / ``live`` sin re-construir filtros en runtime, F4 mantiene
**registries paralelos** (uno por cada ``VALID_MODES`` mode), cada uno
congelado al final. Este modulo expone ``build_filter_set_per_mode``
que construye esos 4 registries a partir de un solo ``Settings``.

Single source of truth (P1 fix post code-review):

- ``build_filter_set_per_mode`` consume ``FilterBounds.from_settings``
  (en ``scanner.py``) como unica fuente de los thresholds per-mode.
  ANTES de este fix el endurecimiento live estaba duplicado en este
  archivo Y en ``FilterBounds.from_settings``; cualquier modificacion
  del spec 7.1 requeria editar ambos; ahora el construtor de cada
  filtro seccion consume un objeto ``FilterBounds`` y toda la policy
  ``min/max per-mode`` vive en ``scanner.FilterBounds``.

- ``Settings.universe.filters`` provee los bounds base; el spec 7.1
  endurecimiento live (volume 10M, spread 20 bps, ATR max 5%) se
  aplica en ``FilterBounds.from_settings``.

Reglas:

- 4 registries paralelos, uno por cada ``VALID_MODES`` mode.
- Orden de registro volume -> spread -> ATR (cheap antes de caro;
  Q4 verdict del thinker).
- Cada registry se ``freeze()`` antes de retornarse.
- Live endurece el threshold (single source via FilterBounds).
- Cross-layer: solo importa de ``trading_bot.config.settings`` (Tipos)
  + modulos internos del paquete ``trading_bot.scanner``. Pine contract
  TSK-103.4.9 via ``tests/unit/scanner/test_cross_layer.py``.
"""

from __future__ import annotations

from trading_bot.config.settings import Settings
from trading_bot.scanner.filters import AtrFilter, SpreadFilter, VolumeFilter
from trading_bot.scanner.registry import FilterRegistry
from trading_bot.scanner.scanner import FilterBounds


def build_filter_set_per_mode(settings: Settings) -> dict[str, FilterRegistry]:
    """Construye 4 ``FilterRegistry``, uno por cada ``VALID_MODES`` mode.

    Single source of truth: delega los bounds a ``FilterBounds.from_settings``
    (P1 fix). Asi cualquier cambio de spec 7.1 (e.g. ``LIVE_MAX_ATR_PERCENT``)
    ocurre solo en ``scanner.py`` y se propaga automaticamente.

    Orden de registro (Q4 verdict): volume -> spread -> atr. Asi ATR
    (caro, requiere ``fetch_recent``) solo se evalua si volume + spread
    (baratos) pasan. Short-circuit maximiza beneficio perf.

    Returns:
        ``dict[str, FilterRegistry]`` con keys ``VALID_MODES = frozenset(
        {"research", "backtest", "paper", "live"})``. Cada registry esta
        congelado (``FilterRegistry.freeze()``) al final.

    Note:
        Si el caller quiere solo un subset de modos, sigue siendo
        aceptable pasar solo esos registries a ``UniverseScanner``;
        el orquestador levanta ConfigurationError si el modo actual
        (derivado de ``settings.runtime.mode`` mapeado por
        ``_SCANNER_MODE_MAP``) no esta presente.
    """
    out: dict[str, FilterRegistry] = {}
    for mode in ("research", "backtest", "paper", "live"):
        # Single source per-mode bounds.
        bounds = FilterBounds.from_settings(settings, mode)

        reg = FilterRegistry()
        reg.register(
            "volume",
            VolumeFilter(
                min_usdt=bounds.min_24h_volume_usdt,
                mode=mode,
                live_min_usdt=bounds.live_min_24h_volume_usdt,
            ),
        )
        reg.register("spread", SpreadFilter(max_bps=bounds.max_spread_bps))
        reg.register(
            "atr",
            AtrFilter(
                min_pct=bounds.min_atr_percent,
                max_pct=bounds.max_atr_percent,
                min_history=bounds.min_history,
            ),
        )
        reg.freeze()
        out[mode] = reg

    return out


__all__ = ["build_filter_set_per_mode"]
