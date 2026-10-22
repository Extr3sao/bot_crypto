"""FORWARD DATA CONTRACT (§8-§11) — stable raw event schema.

DISCOVERY PLANE ONLY. This module defines the *only* shape in which forward
microstructure observations may be persisted. It exists so that a dataset
written today stays readable and replayable months from now, and so that the
quality of that dataset is decidable mechanically rather than by narrative.

Design rules taken literally from the phase mandate:

* ``RAW EVENTS > DERIVED FEATURES`` (§19): every record keeps the verbatim
  exchange payload under ``raw`` (unless the operator explicitly drops it) and
  keeps *all* numeric quantities as the exact decimal STRINGS the exchange
  sent. Nothing is normalised into a float on the way to disk, so any feature
  can be recomputed from storage alone.
* THREE CLOCKS (§9): ``exchange_event_time``, ``receive_time`` and
  ``process_time`` are separate fields with separate names. They are never
  collapsed, and the derived ``network_delay_ms`` / ``processing_delay_ms`` are
  recorded alongside them rather than replacing them.
* TEMPORAL GUARANTEE (§10): an event whose exchange clock is ahead of our
  receive clock beyond a documented tolerance is a *violation*, not a curiosity.
  It is quarantined instead of being written into the main stream, because a
  future ``feature_available_time <= decision_time`` argument would be unsound
  on top of it.
* MARKETS ARE NEVER MIXED (§7): ``market`` is a mandatory, explicit field.
  Spot trades, perpetual depth, open interest, funding and basis all carry
  their own provenance.

Fail closed: malformed payloads raise, they are never silently coerced.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any, Final

__all__ = [
    "BACKFILL_ORIGIN",
    "COLLECTOR_VERSION",
    "CONTRACT_VERSION",
    "LIVE_ORIGIN",
    "LOSSLESS_EVENT_TYPES",
    "PERIODIC_EVENT_TYPES",
    "PERPETUAL_MARKETS",
    "PROVIDER",
    "SCHEMA_VERSION",
    "TRANSPORT_BY_EVENT_TYPE",
    "ClockViolation",
    "ContractError",
    "EventType",
    "Market",
    "RawEvent",
    "SequenceRange",
    "Transport",
    "event_stream_name",
]


CONTRACT_VERSION: Final[str] = "FORWARD-DATA-CONTRACT-V1"
SCHEMA_VERSION: Final[str] = "forward-event-v1"
COLLECTOR_VERSION: Final[str] = "FORWARD-WS-COLLECTOR-V1"

PROVIDER: Final[str] = "binance"

#: Row-level provenance. A row is one of the venue's own records either way, but
#: a recovered row was fetched from the public trade index to close a hole the
#: socket left behind, so its delivery delay is an outage width, not a latency.
LIVE_ORIGIN: Final[str] = "ws"
BACKFILL_ORIGIN: Final[str] = "agg_trade_backfill"


class ContractError(ValueError):
    """Raised when an event does not satisfy the forward data contract."""


class ClockViolation(ContractError):
    """Raised when a clock invariant (``event_time <= receive_time``) fails."""


class Market(StrEnum):
    """Market the datum belongs to. Never inferred, never mixed (§7)."""

    SPOT = "spot"
    PERP = "perp"


PERPETUAL_MARKETS: Final[frozenset[Market]] = frozenset({Market.PERP})


class Transport(StrEnum):
    """How the datum reached us. Determines whether loss is detectable."""

    WS = "ws"
    REST_POLL = "rest_poll"
    REST_BACKFILL = "rest_backfill"


class EventType(StrEnum):
    """Closed set of persisted forward event types."""

    AGG_TRADE = "agg_trade"
    BOOK_TICKER = "book_ticker"
    DEPTH_DIFF = "depth_diff"
    DEPTH_SNAPSHOT = "depth_snapshot"
    MARK_PRICE = "mark_price"
    FUNDING = "funding"
    OPEN_INTEREST = "open_interest"
    BOOK_CHECKPOINT = "book_checkpoint"
    HEARTBEAT = "heartbeat"
    GAP = "gap"
    VIOLATION = "violation"
    LIFECYCLE = "lifecycle"


#: Event types carried by a sequenced WebSocket stream. Only these can be
#: proven lossless, so only these participate in a continuity claim (§27, §55).
LOSSLESS_EVENT_TYPES: Final[frozenset[EventType]] = frozenset(
    {
        EventType.AGG_TRADE,
        EventType.DEPTH_DIFF,
        EventType.BOOK_TICKER,
    }
)

#: Event types whose nature is periodic sampling. A poll interval is a design
#: parameter, not a loss, and the interval is recorded in the manifest.
PERIODIC_EVENT_TYPES: Final[frozenset[EventType]] = frozenset(
    {
        EventType.MARK_PRICE,
        EventType.FUNDING,
        EventType.OPEN_INTEREST,
    }
)


TRANSPORT_BY_EVENT_TYPE: Final[dict[EventType, Transport]] = {
    EventType.AGG_TRADE: Transport.WS,
    EventType.BOOK_TICKER: Transport.WS,
    EventType.DEPTH_DIFF: Transport.WS,
    EventType.DEPTH_SNAPSHOT: Transport.REST_BACKFILL,
    EventType.MARK_PRICE: Transport.REST_POLL,
    EventType.FUNDING: Transport.REST_POLL,
    EventType.OPEN_INTEREST: Transport.REST_POLL,
    EventType.BOOK_CHECKPOINT: Transport.WS,
    EventType.HEARTBEAT: Transport.WS,
    EventType.GAP: Transport.WS,
    EventType.VIOLATION: Transport.WS,
    EventType.LIFECYCLE: Transport.WS,
}


@dataclass(frozen=True, slots=True)
class SequenceRange:
    """Exchange sequence identifiers for one update, when the venue supplies them.

    ``first``/``last`` are the venue's update-id bounds (Binance spot ``U``/``u``
    and USDⓈ-M ``U``/``u``). ``prev`` is the venue-published previous id
    (USDⓈ-M ``pu``). ``None`` means "the venue does not publish this", never
    "we lost it".
    """

    first: int | None = None
    last: int | None = None
    prev: int | None = None

    def __post_init__(self) -> None:
        for name, value in (("first", self.first), ("last", self.last), ("prev", self.prev)):
            if value is not None and value < 0:
                raise ContractError(f"sequence.{name} must be >= 0, got {value}")
        if self.first is not None and self.last is not None and self.first > self.last:
            raise ContractError(f"sequence range inverted: first={self.first} > last={self.last}")

    def as_dict(self) -> dict[str, int | None]:
        return {"first": self.first, "last": self.last, "prev": self.prev}

    def is_empty(self) -> bool:
        return self.first is None and self.last is None and self.prev is None


def event_stream_name(event_type: EventType, symbol: str) -> str:
    """Canonical on-disk stream name, e.g. ``agg_trade/BTCUSDT``."""
    return f"{event_type.value}/{symbol}"


def _require_str(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ContractError(f"{field}: expected a decimal string, got {type(value).__name__}")
    return value


def _positive_decimal_string(value: Any, field: str, *, allow_zero: bool = False) -> str | None:
    """Fail closed on non-numeric or out-of-range numeric strings."""
    text = _require_str(value, field)
    if text is None:
        return None
    try:
        numeric = float(text)
    except ValueError as exc:  # pragma: no cover - defensive
        raise ContractError(f"{field}: {text!r} is not numeric") from exc
    if numeric != numeric or numeric in (float("inf"), float("-inf")):
        raise ContractError(f"{field}: {text!r} is not finite")
    if numeric < 0 or (numeric == 0 and not allow_zero):
        raise ContractError(f"{field}: {text!r} violates {'>= 0' if allow_zero else '> 0'}")
    return text


@dataclass(frozen=True, slots=True)
class RawEvent:
    """One forward observation, in the contract's canonical shape.

    Numeric market quantities are stored as the exchange's own decimal strings.
    Consumers parse them with :mod:`decimal` (see
    :mod:`trading_bot.research.forward.parse`) so that no precision is lost at
    the storage boundary and a zero quantity stays *exactly* zero.
    """

    event_type: EventType
    symbol: str
    market: Market
    stream: str
    transport: Transport
    run_id: str
    exchange_event_time: int | None
    receive_time: int
    process_time: int
    #: Monotonic collector-assigned processing counter. This is the ordering
    #: authority for replay: wall-clock timestamps tie, processing order does
    #: not. Assigned by the storage layer, never by the venue.
    write_seq: int = 0
    connection_id: int | None = None
    exchange_event_id: str | None = None
    sequence: SequenceRange | None = None
    price: str | None = None
    quantity: str | None = None
    aggressor_side: str | None = None
    trade_count: int | None = None
    bid: str | None = None
    ask: str | None = None
    bid_qty: str | None = None
    ask_qty: str | None = None
    bids: list[list[str]] | None = None
    asks: list[list[str]] | None = None
    funding_rate: str | None = None
    next_funding_time: int | None = None
    mark_price: str | None = None
    index_price: str | None = None
    open_interest: str | None = None
    open_interest_time: int | None = None
    clock_skew_ms: int = 0
    detail: dict[str, Any] | None = None
    raw: dict[str, Any] | None = None
    raw_reference: str | None = None
    schema_version: str = SCHEMA_VERSION
    contract_version: str = CONTRACT_VERSION
    collector_version: str = COLLECTOR_VERSION

    def __post_init__(self) -> None:
        if not self.symbol or not self.symbol.isupper():
            raise ContractError(
                f"symbol must be a non-empty upper-case string, got {self.symbol!r}"
            )
        if self.process_time < self.receive_time:
            raise ClockViolation(
                f"process_time ({self.process_time}) < receive_time ({self.receive_time})"
            )
        if self.event_type in LOSSLESS_EVENT_TYPES and self.transport is not Transport.WS:
            raise ContractError(
                f"{self.event_type.value} must travel over WS to be loss-detectable, "
                f"got transport={self.transport.value}"
            )
        if self.event_type in PERIODIC_EVENT_TYPES and self.transport is Transport.WS:
            raise ContractError(f"{self.event_type.value} is polled on this venue, not a WS stream")
        if self.market is Market.PERP and self.event_type in (
            EventType.OPEN_INTEREST,
            EventType.FUNDING,
            EventType.MARK_PRICE,
        ):
            pass  # derivatives-only information carried as information, never as tradeable
        for name in ("price", "quantity", "bid", "ask", "mark_price", "index_price"):
            value = getattr(self, name)
            if value is not None:
                _positive_decimal_string(value, name)
        for name in ("bid_qty", "ask_qty", "open_interest"):
            value = getattr(self, name)
            if value is not None:
                _positive_decimal_string(value, name, allow_zero=True)
        if self.event_type is EventType.AGG_TRADE:
            if self.price is None or self.quantity is None:
                raise ContractError("agg_trade requires price and quantity")
            if self.aggressor_side not in ("buy", "sell"):
                raise ContractError(
                    f"agg_trade requires aggressor_side in ('buy','sell'), got {self.aggressor_side!r}"
                )
        if self.event_type is EventType.DEPTH_DIFF and (self.bids is None or self.asks is None):
            raise ContractError("depth_diff requires bids and asks level lists")

    # ------------------------------------------------------------------ clocks
    @property
    def network_delay_ms(self) -> int | None:
        """``receive_time - exchange_event_time`` when the venue dates the event."""
        if self.exchange_event_time is None:
            return None
        return self.receive_time - self.exchange_event_time

    @property
    def processing_delay_ms(self) -> int:
        """``process_time - receive_time`` — our own ingestion cost."""
        return self.process_time - self.receive_time

    def assert_temporal_guarantee(self, tolerance_ms: int) -> None:
        """Enforce ``exchange_event_time <= receive_time`` within tolerance (§10)."""
        if self.exchange_event_time is None:
            return
        skew = self.exchange_event_time - self.receive_time
        if skew > tolerance_ms:
            raise ClockViolation(
                f"{self.market.value}/{self.symbol} {self.event_type.value}: exchange_event_time "
                f"is {skew} ms ahead of receive_time (tolerance {tolerance_ms} ms)"
            )

    # ------------------------------------------------------------- serialisation
    def to_dict(self) -> dict[str, Any]:
        """Canonical field order. Stable across releases; never re-sorted."""
        return {
            "schema_version": self.schema_version,
            "contract_version": self.contract_version,
            "collector_version": self.collector_version,
            "source": PROVIDER,
            "market": self.market.value,
            "symbol": self.symbol,
            "stream": self.stream,
            "event_type": self.event_type.value,
            "transport": self.transport.value,
            "run_id": self.run_id,
            "write_seq": self.write_seq,
            "connection_id": self.connection_id,
            "exchange_event_id": self.exchange_event_id,
            "exchange_event_time": self.exchange_event_time,
            "receive_time": self.receive_time,
            "process_time": self.process_time,
            "network_delay_ms": self.network_delay_ms,
            "processing_delay_ms": self.processing_delay_ms,
            "clock_skew_ms": self.clock_skew_ms,
            "sequence": None if self.sequence is None else self.sequence.as_dict(),
            "price": self.price,
            "quantity": self.quantity,
            "aggressor_side": self.aggressor_side,
            "trade_count": self.trade_count,
            "bid": self.bid,
            "ask": self.ask,
            "bid_qty": self.bid_qty,
            "ask_qty": self.ask_qty,
            "bids": self.bids,
            "asks": self.asks,
            "funding_rate": self.funding_rate,
            "next_funding_time": self.next_funding_time,
            "mark_price": self.mark_price,
            "index_price": self.index_price,
            "open_interest": self.open_interest,
            "open_interest_time": self.open_interest_time,
            "detail": self.detail,
            "raw_reference": self.raw_reference,
            "raw": self.raw,
        }

    def to_json(self) -> str:
        """Deterministic single-line JSON: no whitespace, insertion-ordered keys."""
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))

    def with_raw_reference(self, reference: str) -> RawEvent:
        return replace(self, raw_reference=reference)


def parse_event(payload: dict[str, Any]) -> RawEvent:
    """Rehydrate an event written by :meth:`RawEvent.to_json`.

    Used by replay and by the quality report. Fails closed on unknown event
    types or shapes so a corrupted segment cannot be silently reinterpreted.
    """
    try:
        event_type = EventType(payload["event_type"])
        market = Market(payload["market"])
        transport = Transport(payload["transport"])
    except KeyError as exc:
        raise ContractError(f"missing field {exc} in persisted event") from exc
    except ValueError as exc:
        raise ContractError(f"unknown enum value in persisted event: {exc}") from exc

    sequence_raw = payload.get("sequence")
    sequence = None
    if isinstance(sequence_raw, dict):
        sequence = SequenceRange(
            first=sequence_raw.get("first"),
            last=sequence_raw.get("last"),
            prev=sequence_raw.get("prev"),
        )

    return RawEvent(
        event_type=event_type,
        symbol=str(payload["symbol"]),
        market=market,
        stream=str(payload.get("stream", "")),
        transport=transport,
        run_id=str(payload.get("run_id", "")),
        exchange_event_time=payload.get("exchange_event_time"),
        receive_time=int(payload["receive_time"]),
        process_time=int(payload["process_time"]),
        write_seq=int(payload.get("write_seq") or 0),
        connection_id=payload.get("connection_id"),
        exchange_event_id=payload.get("exchange_event_id"),
        sequence=sequence,
        price=payload.get("price"),
        quantity=payload.get("quantity"),
        aggressor_side=payload.get("aggressor_side"),
        trade_count=payload.get("trade_count"),
        bid=payload.get("bid"),
        ask=payload.get("ask"),
        bid_qty=payload.get("bid_qty"),
        ask_qty=payload.get("ask_qty"),
        bids=payload.get("bids"),
        asks=payload.get("asks"),
        funding_rate=payload.get("funding_rate"),
        next_funding_time=payload.get("next_funding_time"),
        mark_price=payload.get("mark_price"),
        index_price=payload.get("index_price"),
        open_interest=payload.get("open_interest"),
        open_interest_time=payload.get("open_interest_time"),
        clock_skew_ms=int(payload.get("clock_skew_ms") or 0),
        detail=payload.get("detail"),
        raw=payload.get("raw"),
        raw_reference=payload.get("raw_reference"),
        schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
        contract_version=str(payload.get("contract_version", CONTRACT_VERSION)),
        collector_version=str(payload.get("collector_version", COLLECTOR_VERSION)),
    )
