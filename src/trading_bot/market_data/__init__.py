"""Conectores de mercado y descarga de OHLCV.

Fase objetivo: 1.

Responsabilidades:
- ``ExchangeConnector``: abstracción sobre el exchange (CCXT v4+).
- ``OHLCVFetcher``: descarga y validación de series temporales.
- ``validate``: comprobaciones de integridad (gaps, duplicados).
- ``storage``: persistencia local en ``data/raw/`` (Parquet/CSV).

Restricciones:
- No conoce estrategias ni indicadores.
- Todas las llamadas pasan por ``Retry`` (tenacity).
- En sandbox por defecto.
"""
