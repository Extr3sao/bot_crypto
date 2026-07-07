"""``evaluate_cache_hit`` pure function (RF-4).

Pine contract (03-specify.md §4): skip si ``last_candle_ts >=
current_ts - primary_timeframe AND current_ts - last_candle_ts <
freshness_window_ms``.

Casos cubiertos:
- EMPTY (last_candle_ts is None) -> should_pull=True, state=EMPTY.
- FRESH (periodo actual + fresh) -> should_pull=False, state=FRESH.
- STALE (periodo previo OR dentro del periodo actual pero fuera de
  ventana de freshness) -> should_pull=True, state=STALE.

Boundary pineado (Q10 thinker verdict): current_ts -
last_candle_ts == freshness_window_ms -> STALE (strict ``<``, NO
``<=``). El miss intencional en el limite evita under-pull en el
edge case donde la vela esta en el boundary exacto.

La corrupcion (NaN, high<low) NO se detecta aqui; CL-8 reserva esa
validacion a ``OHLCVFetcher.fetch_and_cache`` downstream. Aqui
solo decidimos pull vs skip; la calidad de datos se evalua tras
el pull (RK-1 Pine contract).
"""

from __future__ import annotations

from trading_bot.scheduler.types import CacheHitDecision, CacheState


def evaluate_cache_hit(
    *,
    last_candle_ts: int | None,
    current_ts: int,
    primary_timeframe_ms: int,
    freshness_window_ms: int,
) -> CacheHitDecision:
    """Decide si el par necesita pull o cache hit (RF-4).

    Args:
        last_candle_ts: timestamp (ms since epoch) de la ultima vela en
            ``OHLCVStore`` para este par; ``None`` si no hay vela.
        current_ts: timestamp (ms since epoch) del momento de la
            decision (inyectado via ``clock_fn`` para determinismo).
        primary_timeframe_ms: duracion del timeframe primario en ms
            (e.g. 5*60*1000 para "5m"). Usado para distinguir
            "vela del periodo actual" vs "vela del periodo previo".
        freshness_window_ms: ventana maxima en ms dentro de la cual
            una vela reciente cuenta como fresh (e.g. 5*60*1000 para
            "5m" con decay tolerance 0).

    Returns:
        ``CacheHitDecision`` frozen dataclass con la decision +
        metadata para logs.

    Raises:
        ValueError: si ``primary_timeframe_ms <= 0`` o
            ``freshness_window_ms <= 0`` (pinea contract per CL-1
            scheduler params; parametro invalido es bug, no se
            recupera).
    """
    if primary_timeframe_ms <= 0:
        raise ValueError(
            f"primary_timeframe_ms must be > 0 (got {primary_timeframe_ms}). "
            f"Invalid scheduler config would produce a non-deterministic "
            f"fresh/stale boundary. Fix config/runtime.yaml."
        )
    if freshness_window_ms <= 0:
        raise ValueError(
            f"freshness_window_ms must be > 0 (got {freshness_window_ms}). "
            f"Invalid scheduler config would cause every fetch to look stale. "
            f"Fix config/runtime.yaml."
        )

    # Path 1: EMPTY (no prior candle in OHLCVStore).
    if last_candle_ts is None:
        return CacheHitDecision(
            state=CacheState.EMPTY,
            last_candle_ts=None,
            current_ts=current_ts,
            primary_timeframe_ms=primary_timeframe_ms,
            freshness_window_ms=freshness_window_ms,
            should_pull=True,
            reason="no prior candle in OHLCVStore",
        )

    age_ms = current_ts - last_candle_ts

    # Path 2: FRESH — vela del periodo actual Y dentro de la ventana
    # de freshness (strict <, NO <=).
    is_current_period = last_candle_ts >= (current_ts - primary_timeframe_ms)
    is_fresh = age_ms < freshness_window_ms
    if is_current_period and is_fresh:
        return CacheHitDecision(
            state=CacheState.FRESH,
            last_candle_ts=last_candle_ts,
            current_ts=current_ts,
            primary_timeframe_ms=primary_timeframe_ms,
            freshness_window_ms=freshness_window_ms,
            should_pull=False,
            reason=f"last candle {age_ms}ms old within {freshness_window_ms}ms window",
        )

    # Path 3: STALE — periodo previo OR dentro del periodo actual pero
    # fuera de la ventana de freshness (boundary exacto cuenta como
    # stale, pine contract strict-<).
    return CacheHitDecision(
        state=CacheState.STALE,
        last_candle_ts=last_candle_ts,
        current_ts=current_ts,
        primary_timeframe_ms=primary_timeframe_ms,
        freshness_window_ms=freshness_window_ms,
        should_pull=True,
        reason=(
            f"last candle {age_ms}ms old (current_period={is_current_period}, fresh={is_fresh})"
        ),
    )


__all__ = ["evaluate_cache_hit"]
