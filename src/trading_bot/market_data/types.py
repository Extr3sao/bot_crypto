"""Tipos de dominio para market data y conector (Pydantic-friendly).

Dataclasses frozen e inmutables (defensiva contra mutación accidental en
retries). Acopladas a `ExchangeConnector` y `CCXTExchangeConnector` en
`exchange_connector.py`. NO importan `ccxt` directamente — los tipos
quedan en una capa de dominio aislada para que las estrategias y
indicadores puedan consumir OHLCV/Balance/OrderResult sin acoplamiento
al exchange (regla arquitectónica §11 en `docs/architecture.md`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# Lado CCXT normalizado. ccxt devuelve lowercase en `side`.
Side = Literal["buy", "sell"]
# Tipo de orden; ampliamos a medida que se necesiten variantes (stop,
# stop_limit, etc.) — ver ADR-0012 cuando se introduzcan.
OrderType = Literal["limit", "market"]
# Estados post-creación que ccxt estandariza. La lista exhaustiva de CCXT
# incluye 6 valores importantes:
#   "open"            — en libro, sin fills.
#   "partially_filled" — en libro con ejecución parcial (CCXT canonical).
#   "closed"          — fill total (sinónimo ccxt-canonical: "filled").
#   "canceled"        — cancelada (US/UK spelling: "cancelled" también).
#   "rejected"        — rechazada por el exchange.
#   "expired"         — expirada por time-in-force.
# CRÍTICO histórico: omitir "partially_filled" provocaba que una orden
# EXITOSA con partial fill se elevara como UnmappedOrderStatusError tras
# el POST; el caller reintentaba y duplicaba la posición. Ver
# `context/retrieval-log.md` entrada 2026-07-04 02:00.
OrderStatus = Literal[
    "open", "partially_filled", "closed", "canceled", "rejected", "expired"
]


@dataclass(frozen=True, slots=True)
class OHLCV:
    """Vela OHLCV cruda, tipada para pasar a `indicators`.

    `symbol` se pinea al bar (NO se omite) para que indicadores /
    strategies / execution puedan procesar lotes heterogéneos sin
    perder el binding exchange. La PK compuesta del store
    (``(symbol, timestamp)`` en ``ohlcv_store.py``) refleja este orden,
    asi el round-trip connector -> fetcher -> store preserva el
    symbol sin perdida de informacion.

    CRÍTICO historico (round-2 P1): omitir `symbol` provocaba que el
    store asumiera PK implicita (solo timestamp) mientras el SQL DDL
    Pineaba `(symbol, timestamp)`; el dataclass y la tabla estaban
    desincronizados y los tests fallaban con `unexpected keyword
    argument 'symbol'`. Ver `context/retrieval-log.md` entrada
    2026-07-04 04:30 y `bdd/features/market_scanner.feature`.
    """

    symbol: str          # par "BASE/QUOTE" (e.g. "BTC/USDT")
    timestamp: int       # ms since epoch (formato ccxt estandar)
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True, slots=True)
class Balance:
    """Balance por asset: free, used, total = free+used."""

    asset: str
    free: float
    used: float
    total: float


@dataclass(frozen=True, slots=True)
class OrderResult:
    """Resultado de `create_order` con `client_order_id` propagado."""

    id: str
    client_order_id: str
    symbol: str
    status: OrderStatus
    side: Side
    type: OrderType
    price: float
    amount: float
    filled: float


__all__ = [
    "Balance",
    "OHLCV",
    "OrderResult",
    "OrderStatus",
    "OrderType",
    "Side",
]
