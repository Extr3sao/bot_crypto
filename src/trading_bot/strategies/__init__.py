"""Catálogo de estrategias.

Fase objetivo: 4.

Estrategias candidatas (todas en ``research`` o ``disabled`` por defecto):
- ``trend_pullback_scalping``.
- ``range_reversion_scalping``.
- ``breakout_volume_scalping``.
- ``vwap_reclaim_scalping``.
- ``momentum_microtrend_scalping``.

Cada estrategia:
- implementa ``Strategy.generate(snapshot) -> Signal | None``.
- explica el motivo si decide no emitir señal.
- registra el evento vía observability.
"""
