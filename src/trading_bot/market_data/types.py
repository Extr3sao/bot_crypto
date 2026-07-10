"""Tipos de dominio para market data y conector (Pydantic-friendly).

Dataclasses frozen e inmutables (defensiva contra mutación accidental en
retries). Acopladas a `ExchangeConnector` y `CCXTExchangeConnector` en
`exchange_connector.py`. NO importan `ccxt` directamente — los tipos
quedan en una capa de dominio aislada para que las estrategias y
indicadores puedan consumir OHLCV/Balance/OrderResult sin acoplamiento
al exchange (regla arquitectónica §11 en `docs/architecture.md`).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Literal, Protocol, cast, runtime_checkable

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
OrderStatus = Literal["open", "partially_filled", "closed", "canceled", "rejected", "expired"]


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

    symbol: str  # par "BASE/QUOTE" (e.g. "BTC/USDT")
    timestamp: int  # ms since epoch (formato ccxt estandar)
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


# ---------------------------------------------------------------------------
# Protocol wrappers for ccxt upstream's `Any` payloads.
#
# DRACULA: ccxt methods return `Any` (we set
# ``ignore_missing_imports = true`` for ``ccxt.*`` in pyproject.toml).
# Functions in this package had to declare return types that match the
# actual runtime shape (``dict[str, Any]`` / ``list[list[float]]``) but
# mypy strict mode flagged those as ``[no-any-return]`` because the
# source value was `Any`.
#
# These Protocols are the *single* type-narrowing boundary: every ccxt
# call funnels through one of the two helpers below, the helper
# validates the shape at runtime (loud ``RuntimeError`` on mismatch),
# and the call-site function declares the narrowed Protocol as its
# return type. The override ``disable_error_code = ["no-any-return"]``
# for ``market_data.*`` in pyproject.toml is then redundant and can be
# removed (see ``chore(quality): close mypy 7 \u2192 0``).
# ---------------------------------------------------------------------------


@runtime_checkable
class CCXTPayloadProtocol(Protocol):
    """Structural type for ccxt ``dict[str, Any]``-style JSON payloads (Pine contract).

    Exposes ``__getitem__``, ``get``, ``keys``, ``values``, ``items``,
    ``__iter__`` and ``__len__`` so callers can use any Mapping-style
    accessor (``.get("orderId")``, ``result["id"]``, ``for k, v in result.items():``,
    etc.) with full mypy coverage.

    Marked ``@runtime_checkable`` so tests that need to verify a value
    ``isinstance(x, CCXTPayloadProtocol)`` succeed against the real
    ``dict[str, Any]`` runtime shape after ``narrow_ccxt_payload``.
    """

    def __getitem__(self, key: str) -> Any: ...
    def get(self, key: str, default: Any = ...) -> Any: ...
    def keys(self) -> Iterator[str]: ...
    def values(self) -> Iterator[Any]: ...
    def items(self) -> Iterator[tuple[str, Any]]: ...
    def __iter__(self) -> Iterator[str]: ...
    def __len__(self) -> int: ...


@runtime_checkable
class CCXTOHLCVProtocol(Protocol):
    """Structural type for ccxt ``list[list[float]]`` OHLCV rows.

    ccxt's canonical ``fetch_ohlcv`` row is
    ``[ts_millis, open, high, low, close, volume]`` but we don't pin
    the row length in the Protocol — some adapters emit 7-element rows
    with extra metadata; downstream code reads by index.
    """

    def __getitem__(self, index: int) -> list[float | int]: ...
    def __iter__(self) -> Iterator[list[float | int]]: ...
    def __len__(self) -> int: ...


def narrow_ccxt_payload(data: Any) -> CCXTPayloadProtocol:
    """Runtime-validate + cast ccxt ``Any`` to ``CCXTPayloadProtocol`` (Pine contract).

    Surface malformed upstream responses (non-dict, non-str keys) as a
    loud ``RuntimeError`` so callers don't see a silent ``KeyError``
    downstream. The cast is safe because a real ``dict[str, Any]``
    structurally satisfies ``CCXTPayloadProtocol`` (it has
    ``__getitem__``/``get``/``keys``/``values``/``items``/etc.).
    """
    if not isinstance(data, dict):
        raise RuntimeError(f"ccxt expected dict payload, got {type(data).__name__}: {data!r}")
    for key in data:
        if not isinstance(key, str):
            raise RuntimeError(f"ccxt dict key must be str, got {type(key).__name__}: {key!r}")
    return cast(CCXTPayloadProtocol, data)


def narrow_ccxt_ohlcv(data: Any) -> CCXTOHLCVProtocol:
    """Runtime-validate + cast ccxt ``Any`` to ``CCXTOHLCVProtocol`` (Pine contract).

    Validates outer list + inner row-list shape; we don't validate
    per-column numeric type because ccxt occasionally returns floats
    as e.g. ``numpy.float64`` and the explicit numeric-band check
    would add fragility without runtime value.
    """
    if not isinstance(data, list):
        raise RuntimeError(
            f"ccxt fetch_ohlcv expected list-of-lists, got {type(data).__name__}: {data!r}"
        )
    for idx, row in enumerate(data):
        if not isinstance(row, list):
            raise RuntimeError(
                f"ccxt OHLCV row #{idx} must be list, got {type(row).__name__}: {row!r}"
            )
    return cast(CCXTOHLCVProtocol, data)


__all__ = [
    "OHLCV",
    "Balance",
    "CCXTOHLCVProtocol",
    "CCXTPayloadProtocol",
    "OrderResult",
    "OrderStatus",
    "OrderType",
    "Side",
    "narrow_ccxt_ohlcv",
    "narrow_ccxt_payload",
]
