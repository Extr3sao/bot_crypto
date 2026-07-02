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
- Order book imbalance (feature flag).

Contrato:
- Una función ``compute(ohlcv, params) -> DataFrame`` o scalar.
- Cache por (indicator, params, last_candle_ts).
- Property tests con ``hypothesis``.
"""
