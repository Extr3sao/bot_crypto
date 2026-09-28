"""Reproducible aggregation: raw -> 1m -> 5m/15m/30m (§33-§35).

Two rules make this safe to research on later:

**Complete buckets only.** A bucket is ``complete`` when the whole of its closed
interval lies inside the capture window *and* no data-loss gap overlaps it. A
partial bucket is emitted (so the hole is visible) but flagged, and it may never
be rolled up into a higher timeframe.

**No lookahead.** A bucket's ``available_at_ms`` is its **close**, never its
open. A feature built on the 10:00-10:05 bucket is only knowable from 10:05:00
onwards, so any later ``feature_available_time <= decision_time`` argument is
checkable against a number we persisted rather than reconstructed.

Roll-up is pure set arithmetic: a 5m bucket exists only if all five of its 1m
children are complete, and its ``available_at_ms`` is its own close.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any, Final

from trading_bot.research.forward.contract import EventType, RawEvent
from trading_bot.research.forward.orderbook import BookHealth

__all__ = [
    "AGGREGATION_VERSION",
    "BOOK_INTERVALS_MINUTES",
    "HIGHER_TIMEFRAMES_MINUTES",
    "BucketAggregate",
    "DatasetAggregation",
    "OrderBookBucketAggregate",
    "aggregate_book_checkpoints",
    "aggregate_dataset",
    "aggregate_events",
    "bucket_open_ms",
    "roll_up",
]

AGGREGATION_VERSION: Final[str] = "FORWARD-AGGREGATION-V1"
BASE_TIMEFRAME_MINUTES: Final[int] = 1
HIGHER_TIMEFRAMES_MINUTES: Final[tuple[int, ...]] = (5, 15, 30)
BOOK_INTERVALS_MINUTES: Final[tuple[int, ...]] = (1, 5, 15, 30)
MINUTE_MS: Final[int] = 60_000


@dataclass(frozen=True, slots=True)
class BucketAggregate:
    """One OHLC-free bucket of trade flow. Volume is in base units."""

    market: str
    symbol: str
    interval_minutes: int
    open_time_ms: int
    close_time_ms: int
    available_at_ms: int
    complete: bool
    empty: bool
    trade_count: int
    buy_volume: str
    sell_volume: str
    buy_notional: str
    sell_notional: str
    vwap: str | None
    taker_imbalance: str | None
    open_interest_last: str | None
    open_interest_mean: str | None
    open_interest_samples: int
    funding_rate_last: str | None
    mark_price_last: str | None
    index_price_last: str | None
    basis_bps_last: str | None
    source_event_count: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class OrderBookBucketAggregate:
    """One bucket of *derived* book statistics. Raw levels are already on disk."""

    market: str
    symbol: str
    interval_minutes: int
    open_time_ms: int
    close_time_ms: int
    available_at_ms: int
    complete: bool
    checkpoints: int
    healthy_checkpoints: int
    usable_ratio: str
    spread_bps_mean: str | None
    spread_bps_min: str | None
    spread_bps_max: str | None
    depth_imbalance_mean: str | None
    mid_last: str | None
    best_bid_last: str | None
    best_ask_last: str | None
    microprice_last: str | None
    bid_depth_n_last: str | None
    ask_depth_n_last: str | None
    depth_n: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class DatasetAggregation:
    """Everything derivable from a capture, plus a digest to prove determinism."""

    version: str = AGGREGATION_VERSION
    run_id: str = ""
    intervals_minutes: tuple[int, ...] = (BASE_TIMEFRAME_MINUTES,)
    trades: dict[str, list[BucketAggregate]] = field(default_factory=dict)
    book: dict[str, list[OrderBookBucketAggregate]] = field(default_factory=dict)
    open_interest: dict[str, list[BucketAggregate]] = field(default_factory=dict)
    derived: dict[str, list[BucketAggregate]] = field(default_factory=dict)
    event_counts: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "run_id": self.run_id,
            "intervals_minutes": list(self.intervals_minutes),
            "trades": {k: [b.as_dict() for b in v] for k, v in sorted(self.trades.items())},
            "book": {k: [b.as_dict() for b in v] for k, v in sorted(self.book.items())},
            "open_interest": {
                k: [b.as_dict() for b in v] for k, v in sorted(self.open_interest.items())
            },
            "derived": {k: [b.as_dict() for b in v] for k, v in sorted(self.derived.items())},
            "event_counts": dict(sorted(self.event_counts.items())),
        }


def bucket_open_ms(ts_ms: int, interval_minutes: int) -> int:
    width = interval_minutes * MINUTE_MS
    return (ts_ms // width) * width


def _key(market: str, symbol: str) -> str:
    return f"{market}/{symbol}"


def aggregate_events(
    events: list[RawEvent],
    interval_minutes: int = BASE_TIMEFRAME_MINUTES,
    *,
    loss_windows: dict[str, list[tuple[int, int]]] | None = None,
    window: dict[str, tuple[int, int]] | None = None,
) -> dict[str, list[BucketAggregate]]:
    """Aggregate aggTrades (and join periodic state) into closed buckets.

    ``loss_windows`` maps ``market/symbol`` to ``[(start_ms, end_ms)]`` intervals
    that lost data; a bucket overlapping one of them is emitted but never marked
    complete. ``window`` maps ``market/symbol`` to the capture window; buckets
    extending past either edge are partial by construction.
    """
    width = interval_minutes * MINUTE_MS
    loss_windows = loss_windows or {}
    window = window or {}

    trades: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
    state: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
    for event in events:
        key = _key(event.market.value, event.symbol)
        if event.event_type is EventType.AGG_TRADE:
            if event.exchange_event_time is None or event.price is None or event.quantity is None:
                continue
            opened = bucket_open_ms(event.exchange_event_time, interval_minutes)
            cell = trades[key].setdefault(
                opened,
                {
                    "buy_volume": Decimal(0),
                    "sell_volume": Decimal(0),
                    "buy_notional": Decimal(0),
                    "sell_notional": Decimal(0),
                    "trade_count": 0,
                    "sources": 0,
                    "last_ts": event.exchange_event_time,
                },
            )
            price = Decimal(event.price)
            qty = Decimal(event.quantity)
            notional = price * qty
            if event.aggressor_side == "buy":
                cell["buy_volume"] += qty
                cell["buy_notional"] += notional
            else:
                cell["sell_volume"] += qty
                cell["sell_notional"] += notional
            cell["trade_count"] += 1
            cell["sources"] += 1
            cell["last_ts"] = max(int(cell["last_ts"]), event.exchange_event_time)
        elif event.event_type in (
            EventType.OPEN_INTEREST,
            EventType.FUNDING,
            EventType.MARK_PRICE,
        ):
            stamp = event.exchange_event_time or event.receive_time
            opened = bucket_open_ms(stamp, interval_minutes)
            cell = state[key].setdefault(
                opened,
                {
                    "oi_last": None,
                    "oi_values": [],
                    "funding_last": None,
                    "mark_last": None,
                    "index_last": None,
                    "basis_values": [],
                    "sources": 0,
                    "last_ts": stamp,
                },
            )
            if event.event_type is EventType.OPEN_INTEREST and event.open_interest is not None:
                cell["oi_last"] = event.open_interest
                cell["oi_values"].append(Decimal(event.open_interest))
            if event.event_type is EventType.FUNDING and event.funding_rate is not None:
                cell["funding_last"] = event.funding_rate
            if event.event_type is EventType.MARK_PRICE:
                if event.mark_price is not None:
                    cell["mark_last"] = event.mark_price
                if event.index_price is not None:
                    cell["index_last"] = event.index_price
                if event.mark_price is not None and event.index_price is not None:
                    index = Decimal(event.index_price)
                    if index > 0:
                        # Basis is derived, and always stored next to the raw
                        # spot/perp inputs it came from (§18).
                        cell["basis_values"].append(
                            (Decimal(event.mark_price) - index) / index * Decimal(10_000)
                        )
            cell["sources"] += 1
            cell["last_ts"] = max(int(cell["last_ts"]), int(stamp))

    results: dict[str, list[BucketAggregate]] = {}
    for key in sorted(set(trades) | set(state)):
        cells = sorted(set(trades.get(key, {})) | set(state.get(key, {})))
        bounds = window.get(key)
        losses = loss_windows.get(key, [])
        buckets: list[BucketAggregate] = []
        for opened in cells:
            trade_cell = trades.get(key, {}).get(opened)
            state_cell = state.get(key, {}).get(opened)
            closed = opened + width
            complete = True
            if bounds is None or opened < bounds[0] or closed > bounds[1]:
                complete = False
            for loss_start, loss_end in losses:
                if loss_start < closed and loss_end > opened:
                    complete = False
                    break
            if trade_cell is None:
                complete = False
            buy_volume = Decimal(0) if trade_cell is None else trade_cell["buy_volume"]
            sell_volume = Decimal(0) if trade_cell is None else trade_cell["sell_volume"]
            buy_notional = Decimal(0) if trade_cell is None else trade_cell["buy_notional"]
            sell_notional = Decimal(0) if trade_cell is None else trade_cell["sell_notional"]
            total_volume = buy_volume + sell_volume
            total_notional = buy_notional + sell_notional
            oi_values = [] if state_cell is None else state_cell["oi_values"]
            basis_values = [] if state_cell is None else state_cell["basis_values"]
            buckets.append(
                BucketAggregate(
                    market=key.split("/", 1)[0],
                    symbol=key.split("/", 1)[1],
                    interval_minutes=interval_minutes,
                    open_time_ms=opened,
                    close_time_ms=closed,
                    available_at_ms=closed,
                    complete=complete,
                    empty=trade_cell is None,
                    trade_count=0 if trade_cell is None else int(trade_cell["trade_count"]),
                    buy_volume=str(buy_volume),
                    sell_volume=str(sell_volume),
                    buy_notional=str(buy_notional),
                    sell_notional=str(sell_notional),
                    vwap=None if total_volume <= 0 else str(total_notional / total_volume),
                    taker_imbalance=(
                        None
                        if total_volume <= 0
                        else str((buy_volume - sell_volume) / total_volume)
                    ),
                    open_interest_last=None if state_cell is None else state_cell["oi_last"],
                    open_interest_mean=(
                        None
                        if not oi_values
                        else str(sum(oi_values, Decimal(0)) / Decimal(len(oi_values)))
                    ),
                    open_interest_samples=len(oi_values),
                    funding_rate_last=None if state_cell is None else state_cell["funding_last"],
                    mark_price_last=None if state_cell is None else state_cell["mark_last"],
                    index_price_last=None if state_cell is None else state_cell["index_last"],
                    basis_bps_last=(
                        None
                        if not basis_values
                        else str(sum(basis_values, Decimal(0)) / Decimal(len(basis_values)))
                    ),
                    source_event_count=(
                        (0 if trade_cell is None else int(trade_cell["sources"]))
                        + (0 if state_cell is None else int(state_cell["sources"]))
                    ),
                )
            )
        results[key] = buckets
    return results


def aggregate_book_checkpoints(
    events: list[RawEvent],
    interval_minutes: int = BASE_TIMEFRAME_MINUTES,
    *,
    loss_windows: dict[str, list[tuple[int, int]]] | None = None,
    window: dict[str, tuple[int, int]] | None = None,
) -> dict[str, list[OrderBookBucketAggregate]]:
    """Bucket book checkpoints, tracking how many were actually *usable*.

    A bucket whose checkpoints were all ``INVALID`` still exists — hiding it
    would hide the failure — but its ``usable_ratio`` is zero and any research
    consumer must refuse it (§14).
    """
    width = interval_minutes * MINUTE_MS
    loss_windows = loss_windows or {}
    window = window or {}
    grouped: dict[str, dict[int, list[RawEvent]]] = defaultdict(lambda: defaultdict(list))
    for event in events:
        if event.event_type is not EventType.BOOK_CHECKPOINT:
            continue
        opened = bucket_open_ms(event.receive_time, interval_minutes)
        grouped[_key(event.market.value, event.symbol)][opened].append(event)

    results: dict[str, list[OrderBookBucketAggregate]] = {}
    for key, cells in sorted(grouped.items()):
        bounds = window.get(key)
        losses = loss_windows.get(key, [])
        buckets: list[OrderBookBucketAggregate] = []
        for opened in sorted(cells):
            entries = cells[opened]
            closed = opened + width
            complete = True
            if bounds is None or opened < bounds[0] or closed > bounds[1]:
                complete = False
            for loss_start, loss_end in losses:
                if loss_start < closed and loss_end > opened:
                    complete = False
                    break
            spreads = [
                Decimal(str(e.detail["spread_bps"]))
                for e in entries
                if e.detail and e.detail.get("spread_bps") is not None
            ]
            imbalances = [
                Decimal(str(e.detail["depth_imbalance"]))
                for e in entries
                if e.detail and e.detail.get("depth_imbalance") is not None
            ]
            healthy = [
                e
                for e in entries
                if e.detail and e.detail.get("health") == BookHealth.HEALTHY.value
            ]
            last = entries[-1]
            detail = last.detail or {}
            buckets.append(
                OrderBookBucketAggregate(
                    market=key.split("/", 1)[0],
                    symbol=key.split("/", 1)[1],
                    interval_minutes=interval_minutes,
                    open_time_ms=opened,
                    close_time_ms=closed,
                    available_at_ms=closed,
                    complete=complete,
                    checkpoints=len(entries),
                    healthy_checkpoints=len(healthy),
                    usable_ratio=str(Decimal(len(healthy)) / Decimal(len(entries))),
                    spread_bps_mean=(
                        None
                        if not spreads
                        else str(sum(spreads, Decimal(0)) / Decimal(len(spreads)))
                    ),
                    spread_bps_min=None if not spreads else str(min(spreads)),
                    spread_bps_max=None if not spreads else str(max(spreads)),
                    depth_imbalance_mean=(
                        None
                        if not imbalances
                        else str(sum(imbalances, Decimal(0)) / Decimal(len(imbalances)))
                    ),
                    mid_last=last.detail.get("mid") if last.detail else None,
                    best_bid_last=last.bid,
                    best_ask_last=last.ask,
                    microprice_last=detail.get("microprice"),
                    bid_depth_n_last=last.bid_qty,
                    ask_depth_n_last=last.ask_qty,
                    depth_n=int(detail.get("depth_n") or 0),
                )
            )
        results[key] = buckets
    return results


def roll_up(buckets: list[BucketAggregate], higher_minutes: int) -> list[BucketAggregate]:
    """Roll 1m buckets into a higher timeframe, complete children only (§34)."""
    if not buckets:
        return []
    base = buckets[0].interval_minutes
    if higher_minutes % base != 0:
        raise ValueError(f"{higher_minutes}m is not a multiple of the base {base}m")
    width = higher_minutes * MINUTE_MS
    by_parent: dict[int, list[BucketAggregate]] = defaultdict(list)
    for bucket in buckets:
        by_parent[(bucket.open_time_ms // width) * width].append(bucket)

    rolled: list[BucketAggregate] = []
    for opened in sorted(by_parent):
        children = sorted(by_parent[opened], key=lambda b: b.open_time_ms)
        expected = higher_minutes // base
        aligned = all(
            (opened + i * base * MINUTE_MS) == child.open_time_ms
            for i, child in enumerate(children)
        )
        if len(children) != expected or not aligned or not all(c.complete for c in children):
            continue
        closed = opened + width
        buy_volume = sum((Decimal(c.buy_volume) for c in children), Decimal(0))
        sell_volume = sum((Decimal(c.sell_volume) for c in children), Decimal(0))
        buy_notional = sum((Decimal(c.buy_notional) for c in children), Decimal(0))
        sell_notional = sum((Decimal(c.sell_notional) for c in children), Decimal(0))
        total_volume = buy_volume + sell_volume
        total_notional = buy_notional + sell_notional
        oi_samples = sum(c.open_interest_samples for c in children)
        oi_mean = None
        if oi_samples:
            weighted = sum(
                (
                    Decimal(c.open_interest_mean) * c.open_interest_samples
                    for c in children
                    if c.open_interest_mean is not None
                ),
                Decimal(0),
            )
            oi_mean = str(weighted / Decimal(oi_samples))
        basis_values = [c.basis_bps_last for c in children if c.basis_bps_last is not None]
        rolled.append(
            BucketAggregate(
                market=children[0].market,
                symbol=children[0].symbol,
                interval_minutes=higher_minutes,
                open_time_ms=opened,
                close_time_ms=closed,
                available_at_ms=closed,
                complete=True,
                empty=False,
                trade_count=sum(c.trade_count for c in children),
                buy_volume=str(buy_volume),
                sell_volume=str(sell_volume),
                buy_notional=str(buy_notional),
                sell_notional=str(sell_notional),
                vwap=None if total_volume <= 0 else str(total_notional / total_volume),
                taker_imbalance=(
                    None if total_volume <= 0 else str((buy_volume - sell_volume) / total_volume)
                ),
                open_interest_last=children[-1].open_interest_last,
                open_interest_mean=oi_mean,
                open_interest_samples=oi_samples,
                funding_rate_last=children[-1].funding_rate_last,
                mark_price_last=children[-1].mark_price_last,
                index_price_last=children[-1].index_price_last,
                basis_bps_last=(
                    None
                    if not basis_values
                    else str(
                        sum((Decimal(b) for b in basis_values), Decimal(0))
                        / Decimal(len(basis_values))
                    )
                ),
                source_event_count=sum(c.source_event_count for c in children),
            )
        )
    return rolled


def aggregate_dataset(
    events: list[RawEvent],
    *,
    run_id: str = "",
    intervals: tuple[int, ...] = (BASE_TIMEFRAME_MINUTES, *HIGHER_TIMEFRAMES_MINUTES),
    loss_windows: dict[str, list[tuple[int, int]]] | None = None,
    window: dict[str, tuple[int, int]] | None = None,
) -> DatasetAggregation:
    """Full raw -> 1m -> 5m/15m/30m pipeline over an in-memory event list."""
    base = aggregate_events(
        events, BASE_TIMEFRAME_MINUTES, loss_windows=loss_windows, window=window
    )
    books = aggregate_book_checkpoints(
        events, BASE_TIMEFRAME_MINUTES, loss_windows=loss_windows, window=window
    )
    counts: dict[str, int] = defaultdict(int)
    for event in events:
        counts[event.event_type.value] += 1
    result = DatasetAggregation(
        run_id=run_id,
        intervals_minutes=tuple(intervals),
        trades={},
        book=books,
        open_interest={},
        derived={},
        event_counts=dict(counts),
    )
    for minutes in intervals:
        for key, buckets in base.items():
            target = result.trades if minutes == BASE_TIMEFRAME_MINUTES else result.derived
            name = key if minutes == BASE_TIMEFRAME_MINUTES else f"{key}@{minutes}m"
            target[name] = (
                buckets if minutes == BASE_TIMEFRAME_MINUTES else roll_up(buckets, minutes)
            )
    for key, buckets in base.items():
        oi = [b for b in buckets if b.open_interest_samples > 0]
        if oi:
            result.open_interest[key] = oi
    return result
