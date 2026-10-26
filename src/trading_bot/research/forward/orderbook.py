"""Order book reconstruction with hard sequence integrity (§12-§15).

The snapshot+diff dance is implemented here literally, per venue policy:

    REST SNAPSHOT
      -> buffer WS diffs
      -> align sequence
      -> apply diffs
      -> LIVE BOOK

Two venue policies exist and they are *not* interchangeable:

``SPOT_UPDATE_ID``
    Binance Spot publishes ``U`` (first update id in the message) and ``u``
    (final update id). After a snapshot with ``lastUpdateId = L`` the book may
    only go live on an update satisfying ``U <= L + 1 <= u``; afterwards every
    update must satisfy ``U == previous u + 1``.

``FUTURES_PREV_ID``
    Binance USDⓈ-M additionally publishes ``pu`` (previous update id). The book
    may only go live on an update satisfying ``U <= L <= u``; afterwards every
    update must satisfy ``pu == previous u``. The ``pu`` chain is stronger than
    arithmetic adjacency and is therefore the primary check.

If either chain breaks, the book becomes ``INVALID`` and MUST be resnapshotted.
It is never patched, never extrapolated and never silently reused: a feature
derived from a corrupt book is worse than a missing feature (§13, §14).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Final

__all__ = [
    "MAX_BUFFERED_UPDATES",
    "ZERO",
    "BookCheckpoint",
    "BookHealth",
    "BookStateError",
    "BookSyncer",
    "DepthUpdate",
    "DiffDisposition",
    "OrderBook",
    "SequencePolicy",
    "SnapshotOutcome",
    "SyncerCounters",
    "parse_depth_levels",
]


MAX_BUFFERED_UPDATES: Final[int] = 20_000
ZERO: Final[Decimal] = Decimal(0)


class BookStateError(ValueError):
    """Raised when an order book is used past the point of believability."""


class SequencePolicy(StrEnum):
    """Venue-specific sequence semantics for depth diffs."""

    SPOT_UPDATE_ID = "spot_update_id"
    FUTURES_PREV_ID = "futures_prev_id"


class BookHealth(StrEnum):
    """§14. Only ``HEALTHY`` books may produce book features."""

    HEALTHY = "HEALTHY"
    RECOVERING = "RECOVERING"
    STALE = "STALE"
    INVALID = "INVALID"


class DiffDisposition(StrEnum):
    """What the syncer did with one diff. Every diff gets exactly one verdict."""

    APPLIED = "APPLIED"
    BUFFERED = "BUFFERED"
    DUPLICATE = "DUPLICATE"
    OUT_OF_ORDER = "OUT_OF_ORDER"
    GAP = "GAP"
    MALFORMED = "MALFORMED"


class SnapshotOutcome(StrEnum):
    """Result of installing a REST snapshot."""

    LIVE = "LIVE"
    AWAITING_DIFF = "AWAITING_DIFF"
    GAP = "GAP"


Level = tuple[Decimal, Decimal]


def _to_decimal(value: object, field_name: str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, str)):
        try:
            return Decimal(str(value))
        except InvalidOperation as exc:
            raise BookStateError(f"{field_name}: {value!r} is not a decimal") from exc
    raise BookStateError(f"{field_name}: expected str/int/Decimal, got {type(value).__name__}")


def parse_depth_levels(levels: object, side: str) -> tuple[Level, ...]:
    """Parse ``[[price, qty], ...]`` fail-closed.

    A zero quantity is meaningful (it *deletes* the level) and is preserved
    exactly. A duplicate price inside one message, a negative quantity, a
    non-positive or non-finite price are all malformed and raise.
    """
    if not isinstance(levels, (list, tuple)):
        raise BookStateError(f"{side}: expected a list of levels, got {type(levels).__name__}")
    parsed: list[Level] = []
    seen: set[Decimal] = set()
    for idx, level in enumerate(levels):
        if not isinstance(level, (list, tuple)) or len(level) < 2:
            raise BookStateError(f"{side}[{idx}]: expected [price, qty], got {level!r}")
        price = _to_decimal(level[0], f"{side}[{idx}].price")
        qty = _to_decimal(level[1], f"{side}[{idx}].qty")
        if not price.is_finite() or price <= 0:
            raise BookStateError(f"{side}[{idx}]: price {price} is not > 0")
        if not qty.is_finite() or qty < 0:
            raise BookStateError(f"{side}[{idx}]: qty {qty} is negative")
        if price in seen:
            raise BookStateError(f"{side}[{idx}]: duplicate price {price} inside one message")
        seen.add(price)
        parsed.append((price, qty))
    return tuple(parsed)


@dataclass(frozen=True, slots=True)
class DepthUpdate:
    """One depth message, normalised but not yet applied."""

    first_id: int
    last_id: int
    prev_id: int | None
    bids: tuple[Level, ...]
    asks: tuple[Level, ...]
    exchange_event_time: int | None
    received_time: int

    def __post_init__(self) -> None:
        if self.first_id < 0 or self.last_id < 0:
            raise BookStateError("depth update ids must be >= 0")
        if self.first_id > self.last_id:
            raise BookStateError(f"depth update range inverted: {self.first_id} > {self.last_id}")

    @classmethod
    def from_ws_payload(cls, payload: dict[str, object], received_time: int) -> DepthUpdate:
        """Build an update from a Binance ``depthUpdate`` JSON body."""
        if payload.get("e") != "depthUpdate":
            raise BookStateError(f"unexpected depth payload type {payload.get('e')!r}")
        first_raw = payload.get("U")
        last_raw = payload.get("u")
        if not isinstance(first_raw, int) or not isinstance(last_raw, int):
            raise BookStateError("depth payload missing integer 'U' or 'u'")
        prev_raw = payload.get("pu")
        if prev_raw is not None and not isinstance(prev_raw, int):
            raise BookStateError("depth payload field 'pu' must be an integer when present")
        event_time = payload.get("E")
        if event_time is not None and not isinstance(event_time, int):
            raise BookStateError("depth payload field 'E' must be an integer when present")
        return cls(
            first_id=first_raw,
            last_id=last_raw,
            prev_id=prev_raw,
            bids=parse_depth_levels(payload.get("b", []), "bids"),
            asks=parse_depth_levels(payload.get("a", []), "asks"),
            exchange_event_time=event_time,
            received_time=received_time,
        )


@dataclass(slots=True)
class SyncerCounters:
    """Per-stream integrity counters, surfaced verbatim in the manifest."""

    applied: int = 0
    buffered: int = 0
    duplicates: int = 0
    out_of_order: int = 0
    gaps: int = 0
    malformed: int = 0
    resnapshots: int = 0
    crossed_book_events: int = 0
    invalidations: int = 0
    snapshot_mismatches: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "applied": self.applied,
            "buffered": self.buffered,
            "duplicates": self.duplicates,
            "out_of_order": self.out_of_order,
            "gaps": self.gaps,
            "malformed": self.malformed,
            "resnapshots": self.resnapshots,
            "crossed_book_events": self.crossed_book_events,
            "invalidations": self.invalidations,
            "snapshot_mismatches": self.snapshot_mismatches,
        }


@dataclass(frozen=True, slots=True)
class BookCheckpoint:
    """A point-in-time, replay-checkable view of a book.

    Persisted so that replay can assert "same book checkpoints" (§32) without
    re-deriving anything from a different code path.
    """

    symbol: str
    market: str
    last_update_id: int
    health: BookHealth
    best_bid: str | None
    best_ask: str | None
    best_bid_qty: str | None
    best_ask_qty: str | None
    bid_levels: int
    ask_levels: int
    depth_n: int
    bid_depth_n: str | None
    ask_depth_n: str | None
    mid: str | None
    spread_bps: str | None
    depth_imbalance: str | None
    microprice: str | None
    exchange_event_time: int | None


class OrderBook:
    """A mutable L2 book. Only ever advanced by validated updates."""

    def __init__(self, symbol: str, market: str, depth_n: int = 10) -> None:
        self.symbol = symbol
        self.market = market
        self.depth_n = depth_n
        self._bids: dict[Decimal, Decimal] = {}
        self._asks: dict[Decimal, Decimal] = {}
        self.last_update_id: int | None = None
        self.last_event_time: int | None = None

    # ------------------------------------------------------------------ probing
    def __len__(self) -> int:
        return len(self._bids) + len(self._asks)

    def is_empty(self) -> bool:
        return not self._bids or not self._asks

    def bid_levels(self) -> int:
        return len(self._bids)

    def ask_levels(self) -> int:
        return len(self._asks)

    def best_bid(self) -> Decimal | None:
        if not self._bids:
            return None
        return max(self._bids)

    def best_ask(self) -> Decimal | None:
        if not self._asks:
            return None
        return min(self._asks)

    def is_crossed(self) -> bool:
        best_bid, best_ask = self.best_bid(), self.best_ask()
        if best_bid is None or best_ask is None:
            return False
        return best_bid >= best_ask

    def depth(self, n: int, side: str) -> Decimal:
        """Sum the notional (price * qty) of the top ``n`` levels of a side."""
        book = self._bids if side == "bid" else self._asks
        ordered = sorted(book.items(), key=lambda kv: kv[0], reverse=(side == "bid"))[:n]
        return sum((price * qty for price, qty in ordered), Decimal(0))

    def top(self, n: int, side: str) -> list[Level]:
        book = self._bids if side == "bid" else self._asks
        ordered = sorted(book.items(), key=lambda kv: kv[0], reverse=(side == "bid"))[:n]
        return list(ordered)

    def mid(self) -> Decimal | None:
        best_bid, best_ask = self.best_bid(), self.best_ask()
        if best_bid is None or best_ask is None:
            return None
        return (best_bid + best_ask) / 2

    def spread_bps(self) -> Decimal | None:
        best_bid, best_ask = self.best_bid(), self.best_ask()
        if best_bid is None or best_ask is None:
            return None
        mid = (best_bid + best_ask) / 2
        if mid <= 0:
            return None
        return (best_ask - best_bid) / mid * Decimal(10_000)

    def microprice(self) -> Decimal | None:
        """Size-weighted mid: heavy bid size pulls the price down, and vice versa."""
        best_bid, best_ask = self.best_bid(), self.best_ask()
        if best_bid is None or best_ask is None:
            return None
        bid_qty = self._bids[best_bid]
        ask_qty = self._asks[best_ask]
        total = bid_qty + ask_qty
        if total <= 0:
            return None
        return (best_bid * ask_qty + best_ask * bid_qty) / total

    def depth_imbalance(self, n: int) -> Decimal | None:
        bid_depth = self.depth(n, "bid")
        ask_depth = self.depth(n, "ask")
        total = bid_depth + ask_depth
        if total <= 0:
            return None
        return (bid_depth - ask_depth) / total

    # ------------------------------------------------------------------ mutation
    def reset(self) -> None:
        self._bids.clear()
        self._asks.clear()
        self.last_update_id = None
        self.last_event_time = None

    def load_snapshot(
        self, last_update_id: int, bids: tuple[Level, ...], asks: tuple[Level, ...]
    ) -> None:
        """Replace the book with a REST snapshot. Raises on a crossed/empty book."""
        if last_update_id < 0:
            raise BookStateError("snapshot last_update_id must be >= 0")
        if not bids or not asks:
            raise BookStateError("snapshot must contain at least one bid and one ask")
        self._bids = {price: qty for price, qty in bids if qty > ZERO}
        self._asks = {price: qty for price, qty in asks if qty > ZERO}
        self.last_update_id = last_update_id
        if self.is_empty():
            raise BookStateError("snapshot produced an empty side (all quantities zero)")
        if self.is_crossed():
            raise BookStateError(
                f"snapshot is crossed: best_bid={self.best_bid()} >= best_ask={self.best_ask()}"
            )

    def apply_levels(self, bids: tuple[Level, ...], asks: tuple[Level, ...]) -> None:
        """Apply diff levels; a zero quantity removes the level exactly."""
        self._apply_side(self._bids, bids)
        self._apply_side(self._asks, asks)

    def _apply_side(self, book: dict[Decimal, Decimal], levels: tuple[Level, ...]) -> None:
        for price, qty in levels:
            if qty == ZERO:
                book.pop(price, None)
            else:
                book[price] = qty

    def checkpoint(self, health: BookHealth) -> BookCheckpoint:
        best_bid, best_ask = self.best_bid(), self.best_ask()
        mid = self.mid()
        spread = self.spread_bps()
        imbalance = self.depth_imbalance(self.depth_n)
        micro = self.microprice()
        return BookCheckpoint(
            symbol=self.symbol,
            market=self.market,
            last_update_id=self.last_update_id or 0,
            health=health,
            best_bid=None if best_bid is None else str(best_bid),
            best_ask=None if best_ask is None else str(best_ask),
            best_bid_qty=(None if best_bid is None else str(self._bids.get(best_bid, ZERO))),
            best_ask_qty=(None if best_ask is None else str(self._asks.get(best_ask, ZERO))),
            bid_levels=len(self._bids),
            ask_levels=len(self._asks),
            depth_n=self.depth_n,
            bid_depth_n=str(self.depth(self.depth_n, "bid")),
            ask_depth_n=str(self.depth(self.depth_n, "ask")),
            mid=None if mid is None else str(mid),
            spread_bps=None if spread is None else str(spread),
            depth_imbalance=None if imbalance is None else str(imbalance),
            microprice=None if micro is None else str(micro),
            exchange_event_time=self.last_event_time,
        )


@dataclass(slots=True)
class BookSyncer:
    """Drives an :class:`OrderBook` through snapshot -> buffer -> live.

    The syncer is the only component allowed to declare a book usable. It counts
    every anomaly and refuses to produce ``HEALTHY`` until a fresh snapshot has
    re-established a continuous sequence chain.
    """

    symbol: str
    market: str
    policy: SequencePolicy
    depth_n: int = 10
    stale_after_ms: int = 5_000
    book: OrderBook = field(init=False)
    counters: SyncerCounters = field(default_factory=SyncerCounters)
    _buffer: list[DepthUpdate] = field(default_factory=list, init=False)
    _live: bool = field(default=False, init=False)
    _invalid: bool = field(default=False, init=False)
    _last_received_ms: int | None = field(default=None, init=False)
    _pending_after_snapshot: DepthUpdate | None = field(default=None, init=False)
    _awaiting_first: bool = field(default=False, init=False)
    used_invalid_data: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        self.book = OrderBook(self.symbol, self.market, self.depth_n)

    # -------------------------------------------------------------------- state
    @property
    def is_live(self) -> bool:
        return self._live and not self._invalid

    @property
    def awaiting_first(self) -> bool:
        """Snapshot installed, still waiting for the diff that bridges it."""
        return self._awaiting_first

    @property
    def buffered_updates(self) -> int:
        return len(self._buffer)

    def health(self, now_ms: int) -> BookHealth:
        if self._invalid:
            return BookHealth.INVALID
        if not self._live:
            return BookHealth.RECOVERING
        if self._last_received_ms is None:
            return BookHealth.RECOVERING
        if now_ms - self._last_received_ms > self.stale_after_ms:
            return BookHealth.STALE
        return BookHealth.HEALTHY

    def feature_usable(self, now_ms: int) -> bool:
        """§14: only a HEALTHY book may feed a book feature."""
        return self.health(now_ms) is BookHealth.HEALTHY

    def invalidate(self) -> None:
        self._invalid = True
        self._live = False
        self._awaiting_first = False
        self._pending_after_snapshot = None
        self.counters.invalidations += 1

    def needs_snapshot(self) -> bool:
        return self._invalid or not self._live

    # ------------------------------------------------------------------ ingress
    def on_diff(self, update: DepthUpdate) -> DiffDisposition:
        """Feed one depth diff. Returns the verdict; never raises for bad order."""
        self._last_received_ms = update.received_time
        if self.book.last_update_id is None and not self._buffer:
            # Nothing to align against yet: buffer until the snapshot lands.
            self._push_buffer(update)
            return DiffDisposition.BUFFERED
        if self._awaiting_first:
            return self._align_first(update)
        if not self.is_live:
            self._push_buffer(update)
            return DiffDisposition.BUFFERED
        return self._apply_live(update)

    def _push_buffer(self, update: DepthUpdate) -> None:
        self._buffer.append(update)
        self.counters.buffered += 1
        if len(self._buffer) > MAX_BUFFERED_UPDATES:
            # A book that never converges must not grow without bound.
            del self._buffer[: len(self._buffer) - MAX_BUFFERED_UPDATES]

    def on_snapshot(
        self,
        last_update_id: int,
        bids: tuple[Level, ...],
        asks: tuple[Level, ...],
        received_time: int,
    ) -> SnapshotOutcome:
        """Install a REST snapshot and try to bridge into the buffered stream.

        ``LIVE``      the buffer bridged the snapshot; the book is usable.
        ``AWAITING_DIFF`` the snapshot is installed, the buffer is empty and the
                          next live diff is expected to bridge it. Normal.
        ``GAP``       the buffer cannot bridge the snapshot — a real hole. The
                      caller must take another snapshot after a short delay.
        """
        self.counters.resnapshots += 1
        self._invalid = False
        self._live = False
        self._pending_after_snapshot = None
        self.book.reset()
        self.book.load_snapshot(last_update_id, bids, asks)
        self._last_received_ms = received_time

        had_buffer = bool(self._buffer)
        kept = [u for u in self._buffer if self._survives_snapshot(u, last_update_id)]
        self._buffer = kept
        if had_buffer and not kept:
            # The snapshot is strictly NEWER than every buffered update, so the
            # diff that would bridge it was consumed before we asked. Not a
            # correctness failure by itself, but it is the signature of a
            # snapshot taken late, so it is counted rather than hidden.
            self.counters.snapshot_mismatches += 1

        if not kept:
            self._awaiting_first = True
            return SnapshotOutcome.AWAITING_DIFF
        first = kept[0]
        if not self._bridges_snapshot(first, last_update_id):
            # Buffer starts past the snapshot: the updates in between are gone.
            self.counters.gaps += 1
            self.invalidate()
            return SnapshotOutcome.GAP
        self._buffer = kept[1:]
        self._apply_aligned(first)
        self._live = True
        self._awaiting_first = False
        # Anything still buffered must continue the chain.
        while self._buffer:
            nxt = self._buffer.pop(0)
            disp = self._apply_live(nxt)
            if disp is not DiffDisposition.APPLIED:
                self.invalidate()
                return SnapshotOutcome.GAP
        return SnapshotOutcome.LIVE

    def _survives_snapshot(self, update: DepthUpdate, last_update_id: int) -> bool:
        if self.policy is SequencePolicy.SPOT_UPDATE_ID:
            return update.last_id > last_update_id
        return update.last_id >= last_update_id

    def _bridges_snapshot(self, update: DepthUpdate, last_update_id: int) -> bool:
        """Can this update legitimately continue the snapshot?

        Binance documents the spot boundary as ``U <= lastUpdateId + 1 <= u`` and
        the USDⓈ-M boundary as ``U <= lastUpdateId <= u``. The two collapse into
        one necessary-and-sufficient condition once you accept that
        ``lastUpdateId`` is the id of the last update already *in* the snapshot:
        the bridging update must start at or before ``lastUpdateId + 1`` and must
        cover it. Both documented forms satisfy that, so this accepts the union
        and rejects everything else — a buffer that starts strictly after the
        snapshot is a real hole and is never bridged.

        For USDⓈ-M the ``pu`` chain then takes over on every later update, which
        is a strictly stronger check than arithmetic adjacency.
        """
        return update.first_id <= last_update_id + 1 <= update.last_id

    def _chain_ok(self, update: DepthUpdate, previous_last: int) -> bool:
        if self.policy is SequencePolicy.FUTURES_PREV_ID and update.prev_id is not None:
            return update.prev_id == previous_last
        return update.first_id == previous_last + 1

    def _align_first(self, update: DepthUpdate) -> DiffDisposition:
        last_update_id = self.book.last_update_id
        if last_update_id is None:  # pragma: no cover - defensive
            raise BookStateError("aligning without a snapshot")
        if update.last_id <= last_update_id:
            self.counters.duplicates += 1
            return DiffDisposition.DUPLICATE
        if not self._bridges_snapshot(update, last_update_id):
            self.counters.gaps += 1
            self.invalidate()
            return DiffDisposition.GAP
        self._awaiting_first = False
        self._apply_aligned(update)
        self._live = True
        return DiffDisposition.APPLIED

    def _apply_aligned(self, update: DepthUpdate) -> None:
        self.book.apply_levels(update.bids, update.asks)
        self.book.last_update_id = update.last_id
        self.book.last_event_time = update.exchange_event_time
        self.counters.applied += 1
        self._check_crossed()

    def _apply_live(self, update: DepthUpdate) -> DiffDisposition:
        previous_last = self.book.last_update_id
        if previous_last is None:  # pragma: no cover - defensive
            raise BookStateError("applying a live update without a snapshot")
        if update.last_id <= previous_last:
            self.counters.duplicates += 1
            return DiffDisposition.DUPLICATE
        if update.first_id <= previous_last:
            # Straddles the current head: strictly older than what we applied.
            self.counters.out_of_order += 1
            return DiffDisposition.OUT_OF_ORDER
        if not self._chain_ok(update, previous_last):
            self.counters.gaps += 1
            self._invalid = True
            self._live = False
            return DiffDisposition.GAP
        self._apply_aligned(update)
        return DiffDisposition.APPLIED

    def _check_crossed(self) -> None:
        best_bid, best_ask = self.book.best_bid(), self.book.best_ask()
        if best_bid is not None and best_ask is not None and best_bid >= best_ask:
            self.counters.crossed_book_events += 1
            self.invalidate()
