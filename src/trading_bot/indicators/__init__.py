"""Motor enchufable de indicadores técnicos.

Fase objetivo: 2.

Indicadores v1:
- EMA (rápida/lenta/media).
- RSI.
- MACD.
- ATR.
- Bollinger Bands.
- VWAP.
- Volumen relativo.
- Spread.
- Volatilidad reciente.
- Order book imbalance (feature flag; TSK-203: shipped as
  ``OrderBookImbalance`` concrete impl behind
  ``runtime.features.enable_order_book_imbalance``).

Contrato:
- Una función ``compute(ohlcv, params) -> DataFrame`` o scalar.
- Cache por (indicator, params, last_candle_ts).
- Property tests con ``hypothesis``.

TSK-203 ships ``OrderBookImbalance`` as a self-contained concrete
indicator (see ``order_book_imbalance.py``). Integration with the
TSK-200 ``Indicator`` Protocol / ``IndicatorRegistry`` is decoupled;
when TSK-200 lands, an ``IndicatorRegistry.register("order_book_imbalance",
...)`` line will plug this concrete class into the catalog dispatch.
"""

from __future__ import annotations

from trading_bot.indicators.order_book_imbalance import (
    IndicatorDisabledError,
    InsufficientHistoryError,
    InvalidOrderBookSnapshotError,
    OrderBookImbalance,
    OrderBookImbalanceError,
    OrderBookSummary,
)

__all__ = [
    "IndicatorDisabledError",
    "InsufficientHistoryError",
    "InvalidOrderBookSnapshotError",
    "OrderBookImbalance",
    "OrderBookImbalanceError",
    "OrderBookSummary",
]  # F401 is for unused imports; here the names are re-exported via __all__
