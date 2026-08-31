"""HTF Point-in-Time — P3: estado de higher-timeframe sin lookahead.

Un régimen HTF (15m/1h/4h) solo puede usar velas HTF cuya apertura
cumpla::

    htf_open_timestamp + htf_timeframe_seconds <= signal_timestamp

``get_completed_htf_state_at`` devuelve el estado de la última vela
HTF **cerrada** en ``signal_timestamp``, o ``None`` si no hay ninguna
vela HTF cerrada todavía (FAIL CLOSED: mejor no etiquetar que
etiquetar con datos del futuro).

Prohibido etiquetar trades históricos con el régimen existente al
ejecutar el auditor: siempre point-in-time.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from trading_bot.market_data.candle_filter import timeframe_seconds_or_raise
from trading_bot.market_data.types import OHLCV


@dataclass(frozen=True, slots=True)
class HTFState:
    """Estado HTF conocido en un instante dado (point-in-time)."""

    symbol: str
    timeframe: str
    bar_open_ts: int  # epoch s o ms según convención de las velas de entrada
    close_ts: int  # bar_open_ts + tf (momento en que la vela quedó cerrada)
    open: float
    high: float
    low: float
    close: float
    volume: float


def get_completed_htf_state_at(
    candles: Sequence[OHLCV],
    htf_timeframe: str,
    signal_timestamp: float,
) -> HTFState | None:
    """Devuelve el último estado HTF cerrado en ``signal_timestamp``.

    Args:
        candles: Velas del HTF (ordenadas por timestamp; timestamp = apertura).
        htf_timeframe: Timeframe HTF (e.g. "15m", "1h", "4h").
        signal_timestamp: Instante de la señal (mismas unidades que
            candle.timestamp).

    Returns:
        El HTFState de la última vela con
        ``bar_open_ts + tf <= signal_timestamp``, o None si no hay
        ninguna vela cerrada aún (FAIL CLOSED).

    Raises:
        UnknownTimeframeError: si el timeframe no es conocido.
    """
    tf_seconds = timeframe_seconds_or_raise(htf_timeframe)

    best: OHLCV | None = None
    for c in candles:
        close_ts = c.timestamp + tf_seconds
        if close_ts <= signal_timestamp and (best is None or c.timestamp > best.timestamp):
            best = c

    if best is None:
        return None

    return HTFState(
        symbol=best.symbol,
        timeframe=htf_timeframe,
        bar_open_ts=best.timestamp,
        close_ts=best.timestamp + tf_seconds,
        open=best.open,
        high=best.high,
        low=best.low,
        close=best.close,
        volume=best.volume,
    )


__all__ = ["HTFState", "get_completed_htf_state_at"]
