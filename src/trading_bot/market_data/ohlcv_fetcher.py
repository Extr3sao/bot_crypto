"""OHLCV fetcher: pull desde ``ExchangeConnector`` + persistencia via ``OHLCVStore``.

Orquesta tres responsabilidades:

1. **Pull**: delega ``ExchangeConnector.fetch_ohlcv(...)`` con retries
   ya cableados en el connector (TSK-101).
2. **Validate**: descarta filas con NaN o ``high < low`` (sanity check
   defensivo; ccxt deberia filtrar upstream pero una vela corrupta no
   debe envenenar una carga backtest).
3. **Cache**: upsert idempotente en ``OHLCVStore`` (last-write-wins
   pineado via ``test_re_fetch_with_corrected_value_overwrites_last_write_wins``).

Devuelve SIEMPRE las velas leidas desde el store (no las que acabamos
de insertar) para que el caller lea la version canonica en disco.
Esto elimina discrepancias si una correccion tardia actualizo las
mismas velas tras el upsert.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable

import structlog

from trading_bot.market_data.exchange_connector import ExchangeConnector
from trading_bot.market_data.types import OHLCV
from trading_bot.storage.ohlcv_store import OHLCVStore


class OHLCVFetcher:
    """Pull + validate + cache para una ventana OHLCV concreta."""

    def __init__(
        self,
        connector: ExchangeConnector,
        store: OHLCVStore,
        clock_fn: Callable[[], float] = time.time,
    ) -> None:
        self._connector = connector
        self._store = store
        self._clock_fn = clock_fn

    def fetch_and_cache(
        self,
        symbol: str,
        timeframe: str,
        limit: int,
    ) -> list[OHLCV]:
        log = structlog.get_logger(self.__class__.__module__).bind(
            op="fetch_and_cache",
            symbol=symbol,
            timeframe=timeframe,
            limit=limit,
        )
        rows = self._connector.fetch_ohlcv(symbol, timeframe, limit=limit)
        cleaned, n_dropped = _validate(rows)
        log.info(
            "ohlcv_pulled",
            n_pulled=len(rows),
            n_valid=len(cleaned),
            n_dropped=n_dropped,
        )
        n_persisted = self._store.upsert_ohlcv(cleaned)
        log.info(
            "ohlcv_cached",
            n_persisted=n_persisted,
            ts_pulled_at=int(self._clock_fn()),
        )
        return self._store.get_ohlcv(symbol, limit=limit)


def _validate(rows: list[OHLCV]) -> tuple[list[OHLCV], int]:
    """Drop velas con NaN o ``high < low`` (sanity defensivo).

    No intentamos arreglar valores; los descartamos para no envenenar
    el store. El caller loguea el conteo via el evento
    ``ohlcv_pulled``.
    """
    cleaned: list[OHLCV] = []
    n_dropped = 0
    for r in rows:
        if any(math.isnan(v) for v in (r.open, r.high, r.low, r.close, r.volume)):
            n_dropped += 1
            continue
        if r.high < r.low:
            n_dropped += 1
            continue
        cleaned.append(r)
    return cleaned, n_dropped


__all__ = ["OHLCVFetcher"]
