"""WebSocket-first forward microstructure collector (§5, §11-§29).

DISCOVERY PLANE / RESEARCH_ONLY. This process:

* speaks only to PUBLIC read-only endpoints — no API key, no secret, no account,
  no order API, no capital (§4);
* never imports, constructs or mutates anything on the trading decision path
  (§3, §40, §39): it shares no mutable state with the PAPER runtime and its
  entire output is append-only files on disk;
* captures the authoritative streams over **WebSocket**, because REST polling
  cannot prove the absence of loss. The previous REST collector measured exactly
  that failure: a missed aggTrade burst and a stale funding period.

Why the design looks like this
------------------------------
Loss detection is only possible when the venue hands us an ordered identifier.
Binance gives us ``a`` (aggregate trade id, strictly +1), ``U``/``u`` (depth
update id range) and ``pu`` (USDⓈ-M previous id). So:

* every aggTrade is checked against ``previous_id + 1``; any jump is a
  *measured* gap with an estimated number of lost prints, not a guess;
* every depth diff goes through :class:`~.orderbook.BookSyncer`, which refuses
  to advance a book past a broken sequence chain and demands a resnapshot;
* the book is periodically checkpointed with its health, so later research can
  only ever use `HEALTHY` snapshots (§14).

What this collector refuses to do
---------------------------------
* It never substitutes REST polling for a high-frequency WS stream (§5). If a
  venue stream is silent, the stream is reported as ``NO_DATA`` in the
  manifest and the affected readiness claim is downgraded — never papered over.
* It never claims ``CONTINUOUS_DATA`` when an unrecoverable gap exists (§27).
* It never repairs, interpolates or back-fills a hole in the sequence.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import shutil
import signal
import time
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import aiohttp

from trading_bot.research.forward.contract import (
    BACKFILL_ORIGIN,
    COLLECTOR_VERSION,
    CONTRACT_VERSION,
    LIVE_ORIGIN,
    PROVIDER,
    SCHEMA_VERSION,
    TRANSPORT_BY_EVENT_TYPE,
    ClockViolation,
    EventType,
    Market,
    RawEvent,
    SequenceRange,
    Transport,
)
from trading_bot.research.forward.orderbook import (
    BookHealth,
    BookStateError,
    BookSyncer,
    DepthUpdate,
    DiffDisposition,
    SequencePolicy,
    SnapshotOutcome,
    parse_depth_levels,
)
from trading_bot.research.forward.outcome import (
    FAILURE_STORAGE,
    CaptureOutcome,
    classify_capture,
)
from trading_bot.research.forward.resources import ResourceSampler, directory_bytes
from trading_bot.research.forward.storage import (
    CONTINUITY_CONTINUOUS,
    CONTINUITY_INCOMPLETE,
    DEFAULT_ROOT,
    GAP_STATUSES,
    LATENCY_STEP,
    GapRecord,
    RunManifest,
    SegmentWriter,
    StreamManifest,
    StreamStats,
    format_utc,
    load_resume_state,
    merge_latency_histograms,
    save_resume_state,
    stream_key_from_path,
)

__all__ = [
    "COLLECTOR_STATES",
    "PERP_REST",
    "PERP_WS",
    "SPOT_REST",
    "SPOT_WS",
    "CollectorConfig",
    "ForwardCollector",
    "provider_stream_status",
    "subscriptions_for",
]

SPOT_REST: Final[str] = "https://api.binance.com"
PERP_REST: Final[str] = "https://fapi.binance.com"
SPOT_WS: Final[str] = "wss://stream.binance.com:9443"
PERP_WS: Final[str] = "wss://fstream.binance.com"

COLLECTOR_STATES: Final[tuple[str, ...]] = ("HEALTHY", "DEGRADED", "FAILED")

#: Sentinel symbol for genuinely global streams. Upper-case because the
#: contract requires symbols to be upper-case — no special-casing downstream.
GLOBAL_SYMBOL: Final[str] = "GLOBAL"
NONE_SENTINEL: Final[str] = GLOBAL_SYMBOL

#: §29 draws the line between *recoverable* and *irrecoverable*, not between
#: "healthy right now" and "not healthy right now". A book that has been healthy
#: and is being reconciled is a DEGRADED condition; a book that has never
#: converged, or a reconciliation path that keeps failing, is FAILED.
BOOK_UNAVAILABLE_DEGRADED_S: Final[float] = 60.0
#: A book that has never reached HEALTHY after this long is not recovering.
BOOK_NEVER_HEALTHY_FAILED_S: Final[float] = 300.0
#: A market socket that stays down this long is no longer "reconnecting".
MARKET_DOWN_FAILED_S: Final[float] = 60.0
#: Failed REST reconciliations before the book path is declared broken.
BOOK_IRRECOVERABLE_FAILURES: Final[int] = 5

#: Rolling per-stream window of already-persisted aggregate trade ids. A row can
#: therefore never be written twice, even when a reconnect races a backfill.
RECENT_ID_WINDOW: Final[int] = 4096
#: Public aggregate-trade index paging used to close a post-reconnect hole (§5).
BACKFILL_PAGE_LIMIT: Final[int] = 1000
BACKFILL_MAX_PAGES: Final[int] = 5


@dataclass(slots=True)
class CollectorConfig:
    """Everything that changes collector behaviour. Explicit, no hidden defaults."""

    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
    markets: tuple[Market, ...] = (Market.SPOT, Market.PERP)
    root: Path = field(default_factory=lambda: Path(DEFAULT_ROOT))
    rotation_seconds: int = 3600
    duration_seconds: float | None = None
    heartbeat_seconds: float = 60.0
    checkpoint_seconds: float = 30.0
    flush_every: int = 1
    oi_interval_seconds: float = 60.0
    premium_interval_seconds: float = 60.0
    depth_limit: int = 1000
    depth_n: int = 10
    keep_raw: bool = True
    max_event_skew_ms: int = 500
    read_timeout_seconds: float = 30.0
    stale_after_ms: int = 5_000
    reconnect_backoff_seconds: tuple[float, ...] = (1.0, 2.0, 5.0, 10.0, 20.0, 30.0)
    resnapshot_retry_seconds: float = 2.0
    run_id: str | None = None
    resume: bool = False
    connect_timeout_seconds: float = 10.0
    ws_heartbeat_seconds: float = 20.0
    #: Which WebSocket streams to capture. Selection is an explicit operational
    #: decision (§6, §43); it is recorded in the manifest so nobody later has to
    #: guess why a stream is missing. ``agg_trade`` and ``depth`` are the ones
    #: that carry the sequence evidence.
    streams: tuple[str, ...] = ("agg_trade", "depth", "book_ticker")
    #: Stop gracefully before filling the volume (§43). ``None`` disables it.
    max_total_bytes: int | None = None
    #: §20 — stop *before* the volume is full. Where ``max_total_bytes`` bounds
    #: the dataset this capture owns, this bounds the whole filesystem: the last
    #: barrier for a host shared with everything else. ``None`` disables it.
    min_free_bytes: int | None = None
    #: The file whose appearance asks this capture to stop *gracefully*: seal the
    #: open segment, write the manifest, exit 0. It exists because a supervisor's
    #: ``terminate()`` on Windows is a hard kill that skips all of that (§51).
    stop_file: Path | None = None
    #: Cadence of the maintenance loop (rotation + resume-state save).
    maintenance_seconds: float = 5.0

    def resolved_run_id(self) -> str:
        if self.run_id:
            return self.run_id
        return f"forward-{int(time.time())}-{uuid.uuid4().hex[:8]}"


STREAM_SPECS: Final[tuple[tuple[str, str, EventType], ...]] = (
    ("agg_trade", "aggTrade", EventType.AGG_TRADE),
    ("depth", "depth@100ms", EventType.DEPTH_DIFF),
    ("book_ticker", "bookTicker", EventType.BOOK_TICKER),
)


def subscriptions_for(
    symbols: tuple[str, ...], streams: tuple[str, ...] = ("agg_trade", "depth", "book_ticker")
) -> dict[str, tuple[str, EventType]]:
    """Combined-stream plan. Identical for spot and USDⓈ-M for these streams.

    ``aggTrade`` is subscribed on the perpetual venue too: if the venue serves
    it we capture it losslessly, and if it does not, the manifest records
    ``NO_DATA`` instead of us pretending a REST poll replaced it (§5, §55).
    """
    unknown = sorted(set(streams) - {spec[0] for spec in STREAM_SPECS})
    if unknown:
        raise ValueError(f"unknown stream(s) {unknown}")
    plan: dict[str, tuple[str, EventType]] = {}
    selected = [spec for spec in STREAM_SPECS if spec[0] in set(streams)]
    for symbol in symbols:
        low = symbol.lower()
        for _name, suffix, event_type in selected:
            plan[f"{low}@{suffix}"] = (symbol, event_type)
    return plan


def provider_stream_status(stats: dict[str, StreamStats]) -> dict[str, Any]:
    """Per-stream availability verdict, computed from what actually arrived.

    ``OBSERVED``      the venue delivered this stream during the capture.
    ``NO_DATA``       the venue accepted the subscription and sent nothing.
    ``NOT_SUBSCRIBED`` the venue is not expected to serve it (e.g. spot has no
                      open interest).
    """
    verdicts: dict[str, Any] = {}
    for key, entry in sorted(stats.items()):
        if entry.events > 0:
            verdict = "OBSERVED"
        elif entry.transport == Transport.WS.value:
            verdict = "NO_DATA"
        elif key.startswith(f"{Market.SPOT.value}|"):
            verdict = "NOT_SUBSCRIBED"
        else:
            verdict = "NO_DATA"
        verdicts[f"{entry.market}/{entry.symbol}/{entry.event_type}"] = {
            "verdict": verdict,
            "transport": entry.transport,
            "lossless": entry.lossless,
            "events": entry.events,
        }
    return verdicts


def _now_ms() -> int:
    return int(time.time() * 1000)


def _disk_free_bytes(path: Path) -> int:
    """Free bytes on the volume holding ``path``; ``0`` if the host won't say.

    The disk guard must never be the thing that crashes a capture: an unreadable
    free-space figure is reported as zero-but-unknown rather than raised, and the
    dataset-size guard still applies when this cannot be measured.
    """
    try:
        return shutil.disk_usage(path if Path(path).exists() else Path.cwd()).free
    except OSError:  # pragma: no cover - platform dependent
        return 0


class _IdWindow:
    """Bounded "ids already written" set, so no row can be persisted twice (§11).

    Aggregate trade ids are monotonic, so a sliding window over the most recent
    ids answers the duplicate question exactly for any realistic reconnect. The
    bound keeps memory flat over a 24/7 capture.
    """

    __slots__ = ("_ids", "_limit", "_order")

    def __init__(self, limit: int) -> None:
        self._ids: set[int] = set()
        self._order: deque[int] = deque()
        self._limit = limit

    def __contains__(self, value: int) -> bool:
        return value in self._ids

    def add(self, value: int) -> None:
        if value in self._ids:
            return
        self._ids.add(value)
        self._order.append(value)
        while len(self._order) > self._limit:
            self._ids.discard(self._order.popleft())


class ForwardCollector:
    """One process, one event loop, one append-only dataset."""

    def __init__(self, config: CollectorConfig) -> None:
        self.config = config
        self.root = Path(config.root)
        self.run_id = config.resolved_run_id()
        self.writer = SegmentWriter(
            self.root,
            rotation_seconds=config.rotation_seconds,
            run_id=self.run_id,
            # Only a run that is deliberately resuming may append to segments
            # that already contain rows.
            allow_existing_segments=config.resume,
            flush_every=config.flush_every,
        )
        self.stats: dict[str, StreamStats] = {}
        self.books: dict[str, BookSyncer] = {}
        self.gaps: list[GapRecord] = []
        self.reconnects = 0
        self.connect_failures = 0
        self.resnapshots = 0
        self.resnapshots_failed = 0
        self.resnapshots_deferred = 0
        self.clock_violations = 0
        self.max_clock_skew_ms = 0
        self.degradation_events: list[dict[str, Any]] = []
        self.network_bytes = 0
        self.heartbeats: list[dict[str, Any]] = []
        self.last_agg_trade_id: dict[str, int] = {}
        self._recent_ids: dict[str, _IdWindow] = {}
        self.backfilled_events = 0
        self.backfill_failures = 0
        self.backfill_gaps_closed = 0
        self.backfill_partial = 0
        self.backfill_deferred = 0
        self.stopped_on_disk_budget = False
        self._backfill_tasks: dict[str, asyncio.Task[None]] = {}
        self._resume_backfills: list[tuple[GapRecord, Market, str, int]] = []
        self._gap_seq = 0
        self.last_message_time: dict[str, int] = {}
        self.connection_ids: dict[str, int] = {}
        self.connection_started: dict[str, int] = {}
        self.connected: dict[str, bool] = {}
        self._tasks: list[asyncio.Task[None]] = []
        self._resnap_tasks: dict[str, asyncio.Task[None]] = {}
        self._stopping = False
        self._stop_reason: str | None = None
        self._fatal: str | None = None
        #: §2 — what kind of terminal failure, so the exit code can say which.
        self._fatal_kind: str | None = None
        self.write_failures = 0
        self.stopped_on_min_free = False
        self._started_wall = time.time()
        self._started_ms = _now_ms()
        self.resources = ResourceSampler()
        self._current_state = "HEALTHY"
        self._git_commit = "UNKNOWN"
        self._book_unavailable_since: dict[str, float] = {}
        self._book_ever_healthy: set[str] = set()
        self._market_down_since: dict[str, float] = {}
        self._resume_payload: dict[str, Any] | None = None
        self._session: aiohttp.ClientSession | None = None
        self.signals_installed: list[str] = []
        self._prime_streams()

    # ------------------------------------------------------------------- setup
    def _add_stat(self, market: Market, symbol: str, event_type: EventType, lossless: bool) -> None:
        transport = TRANSPORT_BY_EVENT_TYPE[event_type]
        self.stats[f"{market.value}|{symbol}|{event_type.value}"] = StreamStats(
            market=market.value,
            symbol=symbol,
            event_type=event_type.value,
            transport=transport.value,
            lossless=lossless,
        )

    def _active_event_types(self) -> tuple[EventType, ...]:
        selected = set(self.config.streams)
        return tuple(spec[2] for spec in STREAM_SPECS if spec[0] in selected)

    def _prime_streams(self) -> None:
        active = self._active_event_types()
        for market in self.config.markets:
            for symbol in self.config.symbols:
                for event_type in active:
                    self._add_stat(market, symbol, event_type, True)
                if EventType.DEPTH_DIFF in active:
                    self._add_stat(market, symbol, EventType.BOOK_CHECKPOINT, False)
                    self._add_stat(market, symbol, EventType.DEPTH_SNAPSHOT, False)
                self.books[f"{market.value}|{symbol}"] = BookSyncer(
                    symbol=symbol,
                    market=market.value,
                    policy=(
                        SequencePolicy.SPOT_UPDATE_ID
                        if market is Market.SPOT
                        else SequencePolicy.FUTURES_PREV_ID
                    ),
                    depth_n=self.config.depth_n,
                    stale_after_ms=self.config.stale_after_ms,
                )
            if market is Market.PERP:
                for symbol in self.config.symbols:
                    self._add_stat(market, symbol, EventType.OPEN_INTEREST, False)
                    self._add_stat(market, symbol, EventType.FUNDING, False)
                    self._add_stat(market, symbol, EventType.MARK_PRICE, False)
        for event_type in (
            EventType.HEARTBEAT,
            EventType.GAP,
            EventType.VIOLATION,
            EventType.LIFECYCLE,
        ):
            self._add_stat(self.config.markets[0], NONE_SENTINEL, event_type, False)

    def _stat(self, event: RawEvent) -> StreamStats:
        symbol = event.symbol if event.event_type not in _GLOBAL_EVENT_TYPES else NONE_SENTINEL
        market = (
            event.market.value
            if event.event_type not in _GLOBAL_EVENT_TYPES
            else self.config.markets[0].value
        )
        key = f"{market}|{symbol}|{event.event_type.value}"
        entry = self.stats.get(key)
        if entry is None:
            entry = StreamStats(
                market=market,
                symbol=symbol,
                event_type=event.event_type.value,
                transport=event.transport.value,
                lossless=event.event_type in _LOSSLESS,
            )
            self.stats[key] = entry
        return entry

    # ----------------------------------------------------------------- writing
    def _write(self, event: RawEvent) -> None:
        """Persist one event, and treat a refusal to persist it as terminal.

        §2/§3 — a writer that cannot write is the one failure the collector may
        not swallow: everything after it is unaccounted for. The first failure is
        recorded, the run is asked to stop and finalise, and the manifest and the
        process exit code both carry FAILED. Swallowing it here is exactly how a
        capture with a dead writer used to exit 0.
        """
        try:
            self.writer.write(event)
        except Exception as exc:
            self.write_failures += 1
            self._record_fatal(
                FAILURE_STORAGE,
                f"{type(exc).__name__}: {exc}",
                stop_reason="storage failure",
            )
            return
        self._stat(event).observe(event)

    def _record_fatal(self, kind: str, reason: str, *, stop_reason: str) -> None:
        """Record the first terminal failure and ask the run to finalise (§2).

        Only the first one is kept: the later ones are consequences, and a
        manifest whose failure reason is the tenth symptom of the first cause is
        a manifest nobody can diagnose from.
        """
        if self._fatal is not None:
            return
        self._fatal = f"{reason}" if not kind else f"{kind}: {reason}"
        self._fatal_kind = kind
        with contextlib.suppress(Exception):
            self._global_write(
                self._global_event(
                    EventType.VIOLATION,
                    detail={"kind": kind, "reason": reason, "terminal": True},
                )
            )
        self.stop(stop_reason)

    def _global_write(self, event: RawEvent) -> None:
        """Write a diagnostics-only event, never letting it mask the real fault."""
        self.writer.write(event)

    def _emit(self, event: RawEvent) -> None:
        """Validate the temporal guarantee, then persist (§10)."""
        try:
            event.assert_temporal_guarantee(self.config.max_event_skew_ms)
        except ClockViolation as exc:
            self._on_clock_violation(event, str(exc))
            return
        self._write(event)

    def _on_clock_violation(self, event: RawEvent, reason: str) -> None:
        self.clock_violations += 1
        skew = 0
        if event.exchange_event_time is not None:
            skew = event.exchange_event_time - event.receive_time
        self.max_clock_skew_ms = max(self.max_clock_skew_ms, skew)
        self._stat(event).clock_violations += 1
        self._write(
            self._global_event(
                EventType.VIOLATION,
                detail={
                    "kind": "TEMPORAL_GUARANTEE",
                    "reason": reason,
                    "market": event.market.value,
                    "symbol": event.symbol,
                    "event_type": event.event_type.value,
                    "clock_skew_ms": skew,
                },
            )
        )

    def _global_event(
        self,
        event_type: EventType,
        detail: dict[str, Any] | None = None,
        *,
        market: Market | None = None,
    ) -> RawEvent:
        now = _now_ms()
        return RawEvent(
            event_type=event_type,
            symbol=NONE_SENTINEL,
            market=market or self.config.markets[0],
            stream=event_type.value,
            transport=Transport.WS,
            run_id=self.run_id,
            exchange_event_time=None,
            receive_time=now,
            process_time=now,
            detail=detail,
        )

    # ------------------------------------------------------------------- gaps
    def _record_gap(
        self,
        market: str,
        symbol: str,
        event_type: str,
        start_ms: int,
        end_ms: int,
        reason: str,
        *,
        recovered: bool,
        data_lost: bool = True,
        estimated_lost_events: int | None = None,
        recovered_events: int = 0,
        detail: str | None = None,
    ) -> GapRecord:
        self._gap_seq += 1
        record = GapRecord(
            market=market,
            symbol=symbol,
            event_type=event_type,
            start_ms=int(start_ms),
            end_ms=int(end_ms),
            reason=reason,
            recovered=recovered,
            data_lost=data_lost,
            estimated_lost_events=estimated_lost_events,
            recovered_events=recovered_events,
            gap_id=f"{self.run_id}:gap:{self._gap_seq:06d}",
            detail=detail,
        )
        self.gaps.append(record)
        self._write(
            self._global_event(
                EventType.GAP,
                detail={
                    "market": record.market,
                    "symbol": record.symbol,
                    "event_type": record.event_type,
                    "start_ms": record.start_ms,
                    "end_ms": record.end_ms,
                    "duration_ms": record.duration_ms,
                    "reason": record.reason,                    "gap_id": record.gap_id,
                    "phase": "GAP_DETECTED",
                    "status": record.status,
                    "recovered": record.recovered,
                    "data_lost": record.data_lost,
                    "recovered_events": record.recovered_events,
                    "estimated_lost_events": record.estimated_lost_events,
                    "remaining_missing": record.remaining_missing,
                    "note": record.detail,
                },
            )
        )
        return record

    # ------------------------------------------------------------------ ingest
    def _raw(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        return payload if self.config.keep_raw else None

    def _handle_agg_trade(
        self,
        market: Market,
        symbol: str,
        payload: dict[str, Any],
        receive_time: int,
        cid: int,
        *,
        origin: str = LIVE_ORIGIN,
    ) -> None:
        agg_id = payload.get("a")
        trade_time = payload.get("T", payload.get("E"))
        if not isinstance(agg_id, int) or not isinstance(trade_time, int):
            self._malformed(market, symbol, EventType.AGG_TRADE, "aggTrade missing 'a' or 'T'")
            return
        is_buyer_maker = payload.get("m")
        if not isinstance(is_buyer_maker, bool):
            self._malformed(market, symbol, EventType.AGG_TRADE, "aggTrade missing 'm'")
            return
        price_raw, qty_raw = payload.get("p"), payload.get("q")
        if not isinstance(price_raw, str) or not isinstance(qty_raw, str):
            self._malformed(market, symbol, EventType.AGG_TRADE, "aggTrade missing 'p' or 'q'")
            return
        first_trade = payload.get("f")
        last_trade = payload.get("l")
        trade_count: int | None = None
        if isinstance(first_trade, int) and isinstance(last_trade, int):
            trade_count = last_trade - first_trade + 1
            if trade_count <= 0:
                self._malformed(
                    market,
                    symbol,
                    EventType.AGG_TRADE,
                    f"aggTrade f={first_trade} > l={last_trade}",
                )
                return
        key = f"{market.value}|{symbol}"
        stats = self.stats[f"{key}|{EventType.AGG_TRADE.value}"]
        window = self._recent_ids.setdefault(key, _IdWindow(RECENT_ID_WINDOW))
        if agg_id in window:
            # Already on disk. Persisting it again would be a duplicate row, and
            # the whole point of the id is that it identifies one trade.
            stats.duplicates += 1
            return
        previous = self.last_agg_trade_id.get(key)
        if previous is not None:
            if agg_id == previous:
                stats.duplicates += 1
            elif agg_id < previous:
                stats.out_of_order += 1
            elif agg_id > previous + 1:
                missing = agg_id - previous - 1
                stats.sequence_gaps += 1
                jump_gap = self._record_gap(
                    market.value,
                    symbol,
                    EventType.AGG_TRADE.value,
                    int(trade_time),
                    int(trade_time),
                    "AGG_TRADE_ID_JUMP",
                    recovered=False,
                    estimated_lost_events=int(missing),
                    detail=(
                        f"aggregate trade id jumped {previous} -> {agg_id} "
                        f"({missing} id(s) never observed)"
                    ),
                )
                # The ids in between are individually addressable in the public
                # index, so the hole is closed in the background rather than
                # left as a permanent hole in a stream we call loss-detectable.
                # A hole seen *inside* a backfill page is not scheduled: we are
                # already walking that very index, and re-entering it would not
                # terminate. It stays recorded, and its size stays visible.
                if origin is LIVE_ORIGIN:
                    self._schedule_gap_recovery(
                        jump_gap,
                        market,
                        symbol,
                        from_id=previous + 1,
                        stop_before_id=agg_id,
                    )
                else:
                    self.backfill_deferred += 1
        window.add(agg_id)
        self.last_agg_trade_id[key] = max(agg_id, previous or agg_id)
        event = RawEvent(
            event_type=EventType.AGG_TRADE,
            symbol=symbol,
            market=market,
            stream=f"{symbol.lower()}@aggTrade",
            # The row belongs to the sequenced WS stream either way: its id is
            # what makes it loss-detectable. A recovered row is not REST polling
            # wearing a WS label — that is what ``detail.origin`` is for, and the
            # contract forbids calling a lossless stream anything but WS.
            transport=Transport.WS,
            run_id=self.run_id,
            connection_id=cid or None,
            exchange_event_id=str(agg_id),
            exchange_event_time=int(trade_time),
            receive_time=receive_time,
            process_time=_now_ms(),
            sequence=SequenceRange(first=agg_id, last=agg_id),
            price=price_raw,
            quantity=qty_raw,
            aggressor_side="sell" if is_buyer_maker else "buy",
            trade_count=trade_count,
            detail={
                "event_time_ms": payload.get("E"),
                "first_trade_id": first_trade,
                # Provenance: a backfilled row is the venue's own record of a
                # trade we missed, not something reconstructed (§19).
                "origin": origin,
            },
            raw=self._raw(payload),
        )
        self._emit(event)

    def _handle_book_ticker(
        self, market: Market, symbol: str, payload: dict[str, Any], receive_time: int, cid: int
    ) -> None:
        bid, ask = payload.get("b"), payload.get("a")
        if not isinstance(bid, str) or not isinstance(ask, str):
            self._malformed(market, symbol, EventType.BOOK_TICKER, "bookTicker missing 'b' or 'a'")
            return
        bid_qty, ask_qty = payload.get("B"), payload.get("A")
        if not isinstance(bid_qty, str) or not isinstance(ask_qty, str):
            self._malformed(market, symbol, EventType.BOOK_TICKER, "bookTicker missing 'B' or 'A'")
            return
        # Spot bookTicker publishes NO event time; futures publishes E and T.
        # Documented rather than invented (§16 pattern).
        event_time = payload.get("E", payload.get("T"))
        event = RawEvent(
            event_type=EventType.BOOK_TICKER,
            symbol=symbol,
            market=market,
            stream=f"{symbol.lower()}@bookTicker",
            transport=Transport.WS,
            run_id=self.run_id,
            connection_id=cid,
            exchange_event_id=None if payload.get("u") is None else str(payload.get("u")),
            exchange_event_time=int(event_time) if isinstance(event_time, int) else None,
            receive_time=receive_time,
            process_time=_now_ms(),
            sequence=SequenceRange(last=payload["u"])
            if isinstance(payload.get("u"), int)
            else None,
            bid=bid,
            ask=ask,
            bid_qty=bid_qty,
            ask_qty=ask_qty,
            detail={"event_time_available": isinstance(event_time, int)},
            raw=self._raw(payload),
        )
        self._emit(event)

    def _handle_depth(
        self, market: Market, symbol: str, payload: dict[str, Any], receive_time: int, cid: int
    ) -> None:
        key = f"{market.value}|{symbol}"
        syncer = self.books[key]
        stats = self.stats[f"{key}|{EventType.DEPTH_DIFF.value}"]
        try:
            update = DepthUpdate.from_ws_payload(payload, receive_time)
        except BookStateError as exc:
            stats.malformed += 1
            syncer.counters.malformed += 1
            syncer.invalidate()
            self._malformed(market, symbol, EventType.DEPTH_DIFF, str(exc))
            self._schedule_resnapshot(market, symbol, delay=self.config.resnapshot_retry_seconds)
            return
        disposition = syncer.on_diff(update)
        if disposition is DiffDisposition.GAP:
            stats.sequence_gaps += 1
            self._record_gap(
                market.value,
                symbol,
                EventType.DEPTH_DIFF.value,
                update.received_time,
                update.received_time,
                "DEPTH_SEQUENCE_BREAK",
                recovered=False,
                estimated_lost_events=max(
                    0, update.first_id - (syncer.book.last_update_id or update.first_id)
                ),
                detail=(
                    f"depth chain broke at U={update.first_id} u={update.last_id} "
                    f"pu={update.prev_id} (policy={syncer.policy.value}); book invalidated"
                ),
            )
            self._schedule_resnapshot(market, symbol, delay=self.config.resnapshot_retry_seconds)
        elif disposition is DiffDisposition.DUPLICATE:
            stats.duplicates += 1
        elif disposition is DiffDisposition.OUT_OF_ORDER:
            stats.out_of_order += 1
        event = RawEvent(
            event_type=EventType.DEPTH_DIFF,
            symbol=symbol,
            market=market,
            stream=f"{symbol.lower()}@depth@100ms",
            transport=Transport.WS,
            run_id=self.run_id,
            connection_id=cid,
            exchange_event_id=f"{update.first_id}-{update.last_id}",
            exchange_event_time=update.exchange_event_time,
            receive_time=receive_time,
            process_time=_now_ms(),
            sequence=SequenceRange(first=update.first_id, last=update.last_id, prev=update.prev_id),
            bids=[[str(p), str(q)] for p, q in update.bids],
            asks=[[str(p), str(q)] for p, q in update.asks],
            detail={"disposition": disposition.value, "book_health": syncer.health(receive_time)},
            raw=self._raw(payload),
        )
        self._emit(event)

    def _malformed(self, market: Market, symbol: str, event_type: EventType, reason: str) -> None:
        self._write(
            self._global_event(
                EventType.VIOLATION,
                detail={
                    "kind": "MALFORMED_PAYLOAD",
                    "market": market.value,
                    "symbol": symbol,
                    "event_type": event_type.value,
                    "reason": reason,
                },
            )
        )

    def handle_message(
        self,
        market: Market,
        plan: dict[str, tuple[str, EventType]],
        payload: dict[str, Any],
        receive_time: int,
        cid: int,
        stream: str | None,
    ) -> None:
        """Route one WS frame. Unknown streams are ignored, never guessed at."""
        if stream is None:
            return
        resolved = plan.get(stream)
        if resolved is None:
            return
        symbol, event_type = resolved
        if event_type is EventType.AGG_TRADE:
            self._handle_agg_trade(market, symbol, payload, receive_time, cid)
        elif event_type is EventType.BOOK_TICKER:
            self._handle_book_ticker(market, symbol, payload, receive_time, cid)
        elif event_type is EventType.DEPTH_DIFF:
            self._handle_depth(market, symbol, payload, receive_time, cid)

    # ------------------------------------------------------------------- REST
    def _rest_base(self, market: Market) -> str:
        return SPOT_REST if market is Market.SPOT else PERP_REST

    async def _rest_get(
        self, session: aiohttp.ClientSession, market: Market, path: str, params: dict[str, Any]
    ) -> Any:
        url = f"{self._rest_base(market)}{path}"
        timeout = aiohttp.ClientTimeout(total=self.config.connect_timeout_seconds)
        async with session.get(url, params=params, timeout=timeout) as response:
            body = await response.read()
            self.network_bytes += len(body)
            if response.status != 200:
                raise RuntimeError(f"HTTP {response.status} from {url}")
            return json.loads(body)

    async def _backfill_agg_trades(
        self,
        market: Market,
        symbol: str,
        from_id: int,
        *,
        stop_before_id: int | None = None,
    ) -> tuple[int, bool, str]:
        """Walk the public aggregate-trade index forward from ``from_id``.

        §5 allows REST for "backfill when possible", and the trade index is a
        public, sequenced, authoritative source: ids ``from_id ..`` are exactly
        the trades a socket outage swallowed, so restoring them is recovery
        rather than fabrication. ``stop_before_id`` closes a hole whose upper
        bound is already known (an id jump between two live trades), so the walk
        stops at the boundary instead of running to the present.

        Returns ``(events, caught_up, note)``; ``caught_up`` is False whenever
        any part of the hole stayed unread, and the caller then records the gap
        as unrecovered (or partially recovered) data loss (§2, §27).
        """
        session = self._session
        if session is None:  # pragma: no cover - defensive
            return 0, False, "backfill impossible: no HTTP session"
        path = "/api/v3/aggTrades" if market is Market.SPOT else "/fapi/v1/aggTrades"
        cursor = from_id
        recovered = 0
        for page in range(BACKFILL_MAX_PAGES):
            try:
                rows = await self._rest_get(
                    session,
                    market,
                    path,
                    {"symbol": symbol, "fromId": cursor, "limit": BACKFILL_PAGE_LIMIT},
                )
            except Exception as exc:
                self.backfill_failures += 1
                self._write(
                    self._global_event(
                        EventType.VIOLATION,
                        detail={
                            "kind": "AGG_TRADE_BACKFILL_FAILED",
                            "market": market.value,
                            "symbol": symbol,
                            "from_id": cursor,
                            "reason": f"{type(exc).__name__}: {exc}",
                        },
                    )
                )
                return recovered, False, (
                    f"trade index unreachable after {recovered} recovered event(s): "
                    f"{type(exc).__name__}: {exc}"
                )
            if not isinstance(rows, list) or not rows:
                self.backfilled_events += recovered
                return (
                    recovered,
                    True,
                    f"{recovered} aggregate trade(s) restored from the public index",
                )
            usable = [row for row in rows if isinstance(row, dict)]
            if stop_before_id is not None:
                # Everything at or above the boundary is already on disk from
                # the live stream: it is not part of this hole at all.
                usable = [
                    row
                    for row in usable
                    if isinstance(row.get("a"), int) and int(row["a"]) < stop_before_id
                ]
            receive_time = _now_ms()
            for row in usable:
                self._handle_agg_trade(
                    market,
                    symbol,
                    row,
                    receive_time,
                    0,
                    origin=BACKFILL_ORIGIN,
                )
            recovered += len(usable)
            newest = rows[-1].get("a") if isinstance(rows[-1], dict) else None
            reached_boundary = (
                stop_before_id is not None
                and isinstance(newest, int)
                and newest >= stop_before_id - 1
            )
            if isinstance(newest, int) and newest >= cursor:
                cursor = newest + 1
            if reached_boundary or len(rows) < BACKFILL_PAGE_LIMIT:
                self.backfilled_events += recovered
                return (
                    recovered,
                    True,
                    f"{recovered} aggregate trade(s) restored from the public index",
                )
            if page == BACKFILL_MAX_PAGES - 1:
                break
        self.backfilled_events += recovered
        return (
            recovered,
            False,
            f"trade index still behind after {BACKFILL_MAX_PAGES} page(s); "
            f"{recovered} event(s) recovered, the remainder is a real loss",
        )

    def _schedule_gap_recovery(
        self,
        gap: GapRecord,
        market: Market,
        symbol: str,
        *,
        from_id: int,
        stop_before_id: int | None,
    ) -> None:
        """Recover a measured trade hole in the background (§2, §26).

        The live stream keeps flowing while the index is walked; duplicate
        suppression makes the overlap harmless. Offline ingest has no loop to
        schedule on, so the attempt is counted as deferred rather than silently
        skipped.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self.backfill_deferred += 1
            return
        key = gap.gap_id or f"{market.value}|{symbol}|{from_id}"
        existing = self._backfill_tasks.get(key)
        if existing is not None and not existing.done():
            return

        async def _runner() -> None:
            recovered, caught_up, note = await self._backfill_agg_trades(
                market, symbol, from_id, stop_before_id=stop_before_id
            )
            self._resolve_gap(gap.gap_id, recovered, caught_up, note)

        self._backfill_tasks[key] = loop.create_task(_runner())

    def _resolve_gap(
        self, gap_id: str, recovered_events: int, caught_up: bool, note: str
    ) -> None:
        """Rewrite one gap's outcome and append the lifecycle event (§2)."""
        index = next((i for i, g in enumerate(self.gaps) if g.gap_id == gap_id), None)
        if index is None:
            return
        resolved = self.gaps[index].resolve(
            recovered=caught_up,
            recovered_events=recovered_events,
            detail=note,
        )
        self.gaps[index] = resolved
        if caught_up:
            self.backfill_gaps_closed += 1
        elif recovered_events:
            self.backfill_partial += 1
        self._write(
            self._global_event(
                EventType.GAP,
                detail={
                    "gap_id": resolved.gap_id,
                    "phase": "RECOVERY_RESOLVED",
                    "status": resolved.status,
                    "recovered": resolved.recovered,
                    "data_lost": resolved.data_lost,
                    "recovered_events": resolved.recovered_events,
                    "estimated_lost_events": resolved.estimated_lost_events,
                    "remaining_missing": resolved.remaining_missing,
                    "note": note,
                },
            )
        )

    async def _recover_agg_trade_gap(
        self, market: Market, symbol: str, last_seen_ms: int, disconnect_ms: int, failure: str | None
    ) -> None:
        """§25, §26 — record a trade hole, and close it when the index allows."""
        window_ms = max(0, disconnect_ms - last_seen_ms)
        key = f"{market.value}|{symbol}"
        last_id = self.last_agg_trade_id.get(key)
        if last_id is None or window_ms == 0:
            self._record_gap(
                market.value,
                symbol,
                EventType.AGG_TRADE.value,
                last_seen_ms,
                disconnect_ms,
                "WS_DISCONNECT",
                recovered=False,
                data_lost=window_ms > 0,
                detail=(
                    f"{failure or 'disconnected'}; "
                    + (
                        "no aggregate trade id was ever observed on this stream, so no "
                        "window can be walked forward"
                        if last_id is None
                        else "the venue closed the socket immediately after the handshake, "
                        "so no event window was lost"
                    )
                ),
            )
            return
        # Detected first, then resolved: the gap is on disk before the walk
        # starts, so a crash mid-recovery cannot lose the record of the hole.
        gap = self._record_gap(
            market.value,
            symbol,
            EventType.AGG_TRADE.value,
            last_seen_ms,
            disconnect_ms,
            "WS_DISCONNECT",
            recovered=False,
            data_lost=True,
            detail=f"{failure or 'disconnected'}; recovery from the public index attempted",
        )
        recovered_events, caught_up, note = await self._backfill_agg_trades(
            market, symbol, last_id + 1
        )
        self._resolve_gap(gap.gap_id, recovered_events, caught_up, note)

    def _schedule_resnapshot(self, market: Market, symbol: str, *, delay: float = 0.0) -> None:
        key = f"{market.value}|{symbol}"
        existing = self._resnap_tasks.get(key)
        if existing is not None and not existing.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # Offline ingest (tests, replay tooling) has no loop to schedule on.
            # The gap is already persisted, so nothing is hidden; the counter
            # makes the deferred work visible.
            self.resnapshots_deferred += 1
            return

        async def _runner() -> None:
            if delay:
                await asyncio.sleep(delay)
            await self._resnapshot(market, symbol)

        self._resnap_tasks[key] = loop.create_task(_runner())

    async def _resnapshot(self, market: Market, symbol: str) -> None:
        """REST snapshot -> reconcile with the buffered diffs (§12, §13, §26)."""
        session = self._session
        if session is None:  # pragma: no cover - defensive
            return
        path = "/api/v3/depth" if market is Market.SPOT else "/fapi/v1/depth"
        try:
            payload = await self._rest_get(
                session, market, path, {"symbol": symbol, "limit": self.config.depth_limit}
            )
        except Exception as exc:
            self.resnapshots_failed += 1
            self._write(
                self._global_event(
                    EventType.VIOLATION,
                    detail={
                        "kind": "RESNAPSHOT_FAILED",
                        "market": market.value,
                        "symbol": symbol,
                        "reason": f"{type(exc).__name__}: {exc}",
                    },
                )
            )
            return
        receive_time = _now_ms()
        self.install_snapshot(
            market,
            symbol,
            last_update_id=payload.get("lastUpdateId"),
            bids_raw=payload.get("bids", []),
            asks_raw=payload.get("asks", []),
            receive_time=receive_time,
            stream=path.rsplit("/", 1)[-1],
            exchange_event_time=payload.get("T"),
            reason="sequence_alignment",
        )

    def install_snapshot(
        self,
        market: Market,
        symbol: str,
        *,
        last_update_id: object,
        bids_raw: object,
        asks_raw: object,
        receive_time: int,
        stream: str,
        exchange_event_time: object = None,
        reason: str = "sequence_alignment",
    ) -> SnapshotOutcome | None:
        """Persist a snapshot and reconcile it with the buffered diffs.

        Separated from the REST fetch so the reconciliation step is reachable
        without a network and so the *only* way a book becomes live is through
        this one audited path (§12, §13).
        """
        key = f"{market.value}|{symbol}"
        syncer = self.books[key]
        if not isinstance(last_update_id, int):
            self.resnapshots_failed += 1
            self._malformed(
                market, symbol, EventType.DEPTH_SNAPSHOT, "snapshot without lastUpdateId"
            )
            return None
        try:
            bids = parse_depth_levels(bids_raw, "bids")
            asks = parse_depth_levels(asks_raw, "asks")
        except BookStateError as exc:
            self.resnapshots_failed += 1
            self._malformed(market, symbol, EventType.DEPTH_SNAPSHOT, str(exc))
            return None
        self.resnapshots += 1
        self._emit(
            RawEvent(
                event_type=EventType.DEPTH_SNAPSHOT,
                symbol=symbol,
                market=market,
                stream=stream,
                transport=Transport.REST_BACKFILL,
                run_id=self.run_id,
                exchange_event_id=str(last_update_id),
                exchange_event_time=(
                    exchange_event_time if isinstance(exchange_event_time, int) else None
                ),
                receive_time=receive_time,
                process_time=_now_ms(),
                sequence=SequenceRange(last=last_update_id),
                bids=[[str(p), str(q)] for p, q in bids],
                asks=[[str(p), str(q)] for p, q in asks],
                detail={"levels": len(bids) + len(asks), "reason": reason},
            )
        )
        try:
            outcome = syncer.on_snapshot(last_update_id, bids, asks, receive_time)
        except BookStateError as exc:
            self.resnapshots_failed += 1
            self._malformed(market, symbol, EventType.DEPTH_SNAPSHOT, str(exc))
            syncer.invalidate()
            return None
        if outcome is SnapshotOutcome.GAP:
            self._record_gap(
                market.value,
                symbol,
                EventType.DEPTH_DIFF.value,
                receive_time,
                receive_time,
                "SNAPSHOT_CANNOT_BRIDGE_BUFFER",
                recovered=False,
                estimated_lost_events=None,
                detail="buffered diffs start past the snapshot; taking another snapshot",
            )
            self._schedule_resnapshot(market, symbol, delay=self.config.resnapshot_retry_seconds)
        elif outcome is SnapshotOutcome.LIVE:
            # The book is valid again; the intervening diffs are still lost, so
            # the earlier DEPTH_SEQUENCE_BREAK gap is annotated, not erased.
            self._write(
                self._global_event(
                    EventType.LIFECYCLE,
                    detail={
                        "kind": "BOOK_RECONCILED",
                        "market": market.value,
                        "symbol": symbol,
                        "last_update_id": last_update_id,
                    },
                )
            )
        return outcome

    # --------------------------------------------------------------- aux loops
    async def _aux_loop(self, market: Market, session: aiohttp.ClientSession) -> None:
        """Periodic derivatives context. Polling is the *only* source for these
        (no WS on this venue for OI; funding/premium are periodic by nature), so
        the interval is recorded as a design parameter, not as loss (§16, §17)."""
        interval = self.config.oi_interval_seconds
        while not self._stopping:
            for symbol in self.config.symbols:
                if self._stopping:
                    return
                await self._poll_open_interest(session, market, symbol)
                await self._poll_premium(session, market, symbol)
            await asyncio.sleep(interval)

    async def _poll_open_interest(
        self, session: aiohttp.ClientSession, market: Market, symbol: str
    ) -> None:
        try:
            payload = await self._rest_get(
                session, market, "/fapi/v1/openInterest", {"symbol": symbol}
            )
        except Exception as exc:
            self._aux_failure(market, symbol, EventType.OPEN_INTEREST, exc)
            return
        receive_time = _now_ms()
        exchange_time = payload.get("time")
        self._emit(
            RawEvent(
                event_type=EventType.OPEN_INTEREST,
                symbol=symbol,
                market=market,
                stream="openInterest",
                transport=Transport.REST_POLL,
                run_id=self.run_id,
                exchange_event_id=None,
                # The venue DOES provide an independent timestamp here, so the
                # temporal guarantee is checkable for open interest too.
                exchange_event_time=int(exchange_time) if isinstance(exchange_time, int) else None,
                receive_time=receive_time,
                process_time=_now_ms(),
                open_interest=str(payload.get("openInterest")),
                open_interest_time=int(exchange_time) if isinstance(exchange_time, int) else None,
                detail={
                    "poll_interval_seconds": self.config.oi_interval_seconds,
                    "independent_event_time": isinstance(exchange_time, int),
                },
                raw=self._raw(payload),
            )
        )

    async def _poll_premium(
        self, session: aiohttp.ClientSession, market: Market, symbol: str
    ) -> None:
        try:
            payload = await self._rest_get(
                session, market, "/fapi/v1/premiumIndex", {"symbol": symbol}
            )
        except Exception as exc:
            self._aux_failure(market, symbol, EventType.MARK_PRICE, exc)
            return
        receive_time = _now_ms()
        exchange_time = payload.get("time")
        event_time = int(exchange_time) if isinstance(exchange_time, int) else None
        self._emit(
            RawEvent(
                event_type=EventType.MARK_PRICE,
                symbol=symbol,
                market=market,
                stream="premiumIndex",
                transport=Transport.REST_POLL,
                run_id=self.run_id,
                exchange_event_time=event_time,
                receive_time=receive_time,
                process_time=_now_ms(),
                mark_price=str(payload.get("markPrice")),
                index_price=str(payload.get("indexPrice")),
                detail={
                    "estimated_settle_price": payload.get("estimatedSettlePrice"),
                    "interest_rate": payload.get("interestRate"),
                    "poll_interval_seconds": self.config.premium_interval_seconds,
                },
                raw=self._raw(payload),
            )
        )
        funding_rate = payload.get("lastFundingRate")
        next_funding = payload.get("nextFundingTime")
        self._emit(
            RawEvent(
                event_type=EventType.FUNDING,
                symbol=symbol,
                market=market,
                stream="premiumIndex.funding",
                transport=Transport.REST_POLL,
                run_id=self.run_id,
                exchange_event_time=event_time,
                receive_time=receive_time,
                process_time=_now_ms(),
                funding_rate=(
                    str(funding_rate) if isinstance(funding_rate, (str, int, float)) else None
                ),
                next_funding_time=int(next_funding) if isinstance(next_funding, int) else None,
                mark_price=str(payload.get("markPrice")),
                index_price=str(payload.get("indexPrice")),
                detail={
                    "source_field": "lastFundingRate",
                    "poll_interval_seconds": self.config.premium_interval_seconds,
                },
            )
        )

    def _aux_failure(
        self, market: Market, symbol: str, event_type: EventType, exc: BaseException
    ) -> None:
        self._write(
            self._global_event(
                EventType.VIOLATION,
                detail={
                    "kind": "AUX_POLL_FAILURE",
                    "market": market.value,
                    "symbol": symbol,
                    "event_type": event_type.value,
                    "reason": f"{type(exc).__name__}: {exc}",
                },
            )
        )

    # ------------------------------------------------------------------ WS loop
    async def _ws_loop(self, market: Market, session: aiohttp.ClientSession) -> None:
        plan = subscriptions_for(self.config.symbols, self.config.streams)
        base = SPOT_WS if market is Market.SPOT else PERP_WS
        streams = "/".join(sorted(plan))
        url = f"{base}/stream?streams={streams}"
        backoff = self.config.reconnect_backoff_seconds
        attempt = 0
        while not self._stopping:
            self.connection_ids[market.value] = self.connection_ids.get(market.value, 0) + 1
            cid = self.connection_ids[market.value]
            connect_ms = _now_ms()
            failure: str | None = None
            try:
                async with session.ws_connect(
                    url,
                    heartbeat=self.config.ws_heartbeat_seconds,
                    max_msg_size=0,
                ) as ws:
                    self.connected[market.value] = True
                    self.connection_started[market.value] = connect_ms
                    self.last_message_time[market.value] = connect_ms
                    attempt = 0
                    self._write(
                        self._global_event(
                            EventType.LIFECYCLE,
                            detail={
                                "kind": "WS_CONNECTED",
                                "market": market.value,
                                "url": url,
                                "connection_id": cid,
                                "streams": sorted(plan),
                            },
                        )
                    )
                    for symbol in self.config.symbols:
                        if EventType.DEPTH_DIFF in self._active_event_types():
                            self._schedule_resnapshot(market, symbol)
                    while not self._stopping:
                        try:
                            frame = await asyncio.wait_for(
                                ws.receive(), timeout=self.config.read_timeout_seconds
                            )
                        except TimeoutError:
                            failure = (
                                f"no frame for {self.config.read_timeout_seconds}s on "
                                f"{market.value} websocket"
                            )
                            break
                        if frame.type is aiohttp.WSMsgType.TEXT:
                            self.last_message_time[market.value] = _now_ms()
                            self.network_bytes += len(frame.data)
                            self._dispatch_frame(market, plan, frame.data, cid)
                        elif frame.type in (
                            aiohttp.WSMsgType.CLOSED,
                            aiohttp.WSMsgType.CLOSING,
                            aiohttp.WSMsgType.ERROR,
                        ):
                            failure = f"websocket {frame.type.name}"
                            break
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                failure = f"{type(exc).__name__}: {exc}"
            if self._stopping:
                return
            was_established = self.connected.get(market.value, False)
            self.connected[market.value] = False
            last_seen = self.last_message_time.get(market.value, connect_ms)
            disconnect_ms = _now_ms()
            window_ms = max(0, disconnect_ms - last_seen)
            if not was_established:
                # The handshake itself failed: no stream ever ran, so there is no
                # window to call a gap. It is recorded as a violation instead, and
                # the late first_receive_time of each stream is the visible cost.
                self.connect_failures += 1
                self._write(
                    self._global_event(
                        EventType.VIOLATION,
                        detail={
                            "kind": "WS_CONNECT_FAILED",
                            "market": market.value,
                            "attempt": attempt,
                            "reason": failure,
                        },
                    )
                )
            else:
                self.reconnects += 1
                for symbol in self.config.symbols:
                    for event_type in self._active_event_types():
                        if event_type is EventType.AGG_TRADE:
                            # The one stream whose hole the public index can close.
                            await self._recover_agg_trade_gap(
                                market, symbol, last_seen, disconnect_ms, failure
                            )
                            continue
                        self._record_gap(
                            market.value,
                            symbol,
                            event_type.value,
                            last_seen,
                            disconnect_ms,
                            "WS_DISCONNECT",
                            # A zero-length window cannot have lost anything, and
                            # saying otherwise would overstate our losses.
                            recovered=False,
                            data_lost=window_ms > 0,
                            estimated_lost_events=None,
                            detail=(
                                f"{failure or 'disconnected'}; reconnect attempts continue, "
                                + (
                                    "the diffs in this window are gone, but the book is "
                                    "re-snapshotted and its state is authoritative again "
                                    "from the recovery instant onward"
                                    if window_ms > 0
                                    else "the venue closed the socket immediately after the "
                                    "handshake, so no event window was lost"
                                )
                            ),
                        )
            self._write(
                self._global_event(
                    EventType.LIFECYCLE,
                    detail={
                        "kind": "WS_DISCONNECTED",
                        "market": market.value,
                        "reason": failure,
                        "connection_id": cid,
                        "was_established": was_established,
                        "disconnect_duration_ms": window_ms,
                    },
                )
            )
            delay = backoff[min(attempt, len(backoff) - 1)]
            attempt += 1
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.sleep(delay)

    def _dispatch_frame(
        self, market: Market, plan: dict[str, tuple[str, EventType]], data: str, cid: int
    ) -> None:
        try:
            message = json.loads(data)
        except json.JSONDecodeError:
            self._write(
                self._global_event(
                    EventType.VIOLATION,
                    detail={
                        "kind": "UNDECODABLE_FRAME",
                        "market": market.value,
                        "bytes": len(data),
                    },
                )
            )
            return
        if not isinstance(message, dict):
            return
        stream = message.get("stream")
        body = message.get("data")
        if body is None:
            body = message
        if not isinstance(body, dict):
            return
        self.handle_message(
            market, plan, body, _now_ms(), cid, stream if isinstance(stream, str) else None
        )

    # ------------------------------------------------------------ housekeeping
    async def _checkpoint_loop(self) -> None:
        while not self._stopping:
            await asyncio.sleep(self.config.checkpoint_seconds)
            if self._stopping:
                return
            self.checkpoint_books()

    def checkpoint_books(self) -> None:
        now = _now_ms()
        for key, syncer in self.books.items():
            market, symbol = key.split("|", 1)
            health = syncer.health(now)
            if health is BookHealth.HEALTHY or not syncer.book.is_empty():
                checkpoint = syncer.book.checkpoint(health)
                self._write(
                    RawEvent(
                        event_type=EventType.BOOK_CHECKPOINT,
                        symbol=symbol,
                        market=Market(market),
                        stream="book_checkpoint",
                        transport=Transport.WS,
                        run_id=self.run_id,
                        exchange_event_time=checkpoint.exchange_event_time,
                        receive_time=now,
                        process_time=_now_ms(),
                        sequence=SequenceRange(last=checkpoint.last_update_id),
                        bid=checkpoint.best_bid,
                        ask=checkpoint.best_ask,
                        bid_qty=checkpoint.best_bid_qty,
                        ask_qty=checkpoint.best_ask_qty,
                        detail={
                            "health": health.value,
                            "depth_n": checkpoint.depth_n,
                            "bid_levels": checkpoint.bid_levels,
                            "ask_levels": checkpoint.ask_levels,
                            "mid": checkpoint.mid,
                            "spread_bps": checkpoint.spread_bps,
                            "depth_imbalance": checkpoint.depth_imbalance,
                            "microprice": checkpoint.microprice,
                            # Notional depth (sum of price * qty over the top N levels),
                            # kept next to the top-of-book quantities in bid_qty/ask_qty
                            # so a later consumer never has to re-derive either (§15).
                            "bid_depth_notional": checkpoint.bid_depth_n,
                            "ask_depth_notional": checkpoint.ask_depth_n,
                            "feature_usable": health is BookHealth.HEALTHY,
                            "counters": syncer.counters.as_dict(),
                        },
                    )
                )

    async def _heartbeat_loop(self) -> None:
        while not self._stopping:
            await asyncio.sleep(self.config.heartbeat_seconds)
            if self._stopping:
                return
            self.emit_heartbeat()

    def emit_heartbeat(self) -> dict[str, Any]:
        now = _now_ms()
        elapsed = max(1e-9, (now - self._started_ms) / 1000.0)
        disk_bytes = directory_bytes(self.root)
        sample = self.resources.sample(disk_bytes, self.network_bytes)
        counters = _aggregate_counters(self.stats)
        age_by_market = {
            market: (now - self.last_message_time[market]) / 1000.0
            for market in sorted(self.connected)
        }
        state = self._evaluate_state(now)
        self._note_state_change(state)
        # §2 — the writer's own latency telemetry, aggregated from the bounded
        # per-stream histograms. No samples are materialised, so a heartbeat
        # every minute stays flat in memory for the life of the capture.
        merged_latency = merge_latency_histograms(entry.latency for entry in self.stats.values())
        heartbeat = {
            "timestamp": now,
            "timestamp_iso": format_utc(now),
            "state": state,
            "connections": {m: bool(v) for m, v in sorted(self.connected.items())},
            "events_per_second": round(self.writer.total_rows / elapsed, 4),
            "last_event_age_seconds": {m: round(v, 3) for m, v in sorted(age_by_market.items())},
            "trade_count": counters["agg_trade"],
            "book_updates": counters["depth_diff"],
            "book_checkpoints": counters["book_checkpoint"],
            "oi_samples": counters["open_interest"],
            "funding_updates": counters["funding"],
            "mark_price_samples": counters["mark_price"],
            "gaps": len(self.gaps),
            "reconnects": self.reconnects,
            "resnapshots": self.resnapshots,
            "clock_violations": self.clock_violations,
            "network_delay_ms": {
                "p50": merged_latency.quantile(0.50),
                "p95": merged_latency.quantile(0.95),
                "p99": merged_latency.quantile(0.99),
                "samples": merged_latency.samples,
                "resolution_ratio": LATENCY_STEP,
            },
            "disk_bytes": disk_bytes,
            "disk_free_bytes": _disk_free_bytes(self.root),
            "memory_mb": sample.memory_mb,
            "cpu_seconds": round(sample.cpu_seconds, 3),
            "network_bytes": self.network_bytes,
            # §2 — the live view of the exit contract, so an operator watching
            # the heartbeat sees a failed writer before the process is gone.
            "write_failures": self.write_failures,
            "fatal_failure": self._fatal,
        }
        self.heartbeats.append(heartbeat)
        self._write(
            self._global_event(EventType.HEARTBEAT, detail=dict(heartbeat, timestamp_iso=None))
        )
        return heartbeat

    def _evaluate_state(self, now_ms: int) -> str:
        """§29. HEALTHY | DEGRADED | FAILED, derived, never asserted.

        FAILED is reserved for conditions the collector cannot work around: a
        broken temporal invariant, a reconciliation path that keeps failing, no
        lossless stream at all, a market that never reconnects, or a book that
        never converges. Everything else that is currently wrong is DEGRADED,
        because the dataset keeps its own record of it either way.
        """
        if self._fatal is not None:
            return "FAILED"
        if self.clock_violations > 0:
            return "FAILED"
        if self.resnapshots_failed >= BOOK_IRRECOVERABLE_FAILURES:
            return "FAILED"
        lossless_seen = sum(entry.events for entry in self.stats.values() if entry.lossless)
        if lossless_seen == 0 and (now_ms - self._started_ms) > 10_000:
            return "FAILED"

        now_s = time.time()
        degraded = False
        for market, connected in self.connected.items():
            if connected:
                self._market_down_since.pop(market, None)
                continue
            down_since = self._market_down_since.setdefault(market, now_s)
            if now_s - down_since > MARKET_DOWN_FAILED_S:
                return "FAILED"
            degraded = True
        for key, syncer in self.books.items():
            if syncer.health(now_ms) is BookHealth.HEALTHY:
                self._book_unavailable_since.pop(key, None)
                self._book_ever_healthy.add(key)
                continue
            unavailable_since = self._book_unavailable_since.setdefault(key, now_s)
            if (
                key not in self._book_ever_healthy
                and now_s - unavailable_since > BOOK_NEVER_HEALTHY_FAILED_S
            ):
                return "FAILED"
            degraded = True
        if self.gaps or self.resnapshots_failed:
            degraded = True
        return "DEGRADED" if degraded else "HEALTHY"

    def _note_state_change(self, state: str) -> None:
        if state == self._current_state:
            return
        self.degradation_events.append(
            {
                "at_ms": _now_ms(),
                "from": self._current_state,
                "to": state,
            }
        )
        self._write(
            self._global_event(
                EventType.LIFECYCLE,
                detail={"kind": "STATE_CHANGE", "from": self._current_state, "to": state},
            )
        )
        self._current_state = state

    # -------------------------------------------------------------- resume
    def _load_resume(self) -> None:
        if not self.config.resume:
            return
        state = load_resume_state(self.root, self.run_id)
        if state is None:
            return
        self._resume_payload = state
        previous_ids = state.get("last_agg_trade_id")
        if isinstance(previous_ids, dict):
            for key, value in previous_ids.items():
                if isinstance(value, int):
                    self.last_agg_trade_id[key] = value
        gap_seq = state.get("gap_seq")
        if isinstance(gap_seq, int):
            self._gap_seq = max(self._gap_seq, gap_seq)
        last_receive = state.get("last_receive_time")
        if isinstance(last_receive, int):
            resume_ms = _now_ms()
            for market in self.config.markets:
                for symbol in self.config.symbols:
                    for event_type in (
                        EventType.AGG_TRADE,
                        EventType.DEPTH_DIFF,
                        EventType.BOOK_TICKER,
                    ):
                        gap = self._record_gap(
                            market.value,
                            symbol,
                            event_type.value,
                            last_receive,
                            resume_ms,
                            "COLLECTOR_RESTART",
                            recovered=False,
                            estimated_lost_events=None,
                            detail=(
                                "collector was stopped and resumed; the downtime window is "
                                "recorded rather than hidden, and the trade index is walked "
                                "forward to close the part of it that can be closed"
                                if event_type is EventType.AGG_TRADE
                                else "collector was stopped and resumed; the downtime window "
                                "is unrecoverable and is recorded rather than hidden"
                            ),
                        )
                        if event_type is EventType.AGG_TRADE:
                            previous = self.last_agg_trade_id.get(f"{market.value}|{symbol}")
                            if previous is not None:
                                # Scheduled once the HTTP session exists, so the very
                                # first thing a resumed capture does is repair its
                                # own downtime hole.
                                self._resume_backfills.append((gap, market, symbol, previous + 1))
        self._write(
            self._global_event(
                EventType.LIFECYCLE,
                detail={
                    "kind": "RESUMED",
                    "run_id": self.run_id,
                    "previous_last_receive_time": last_receive,
                },
            )
        )

    def _save_state(self) -> Path:
        payload: dict[str, Any] = {
            "run_id": self.run_id,
            "collector_version": COLLECTOR_VERSION,
            "contract_version": CONTRACT_VERSION,
            "schema_version": SCHEMA_VERSION,
            "saved_at_ms": _now_ms(),
            "last_receive_time": max(
                (e.last_receive_time or 0 for e in self.stats.values()), default=0
            ),
            "last_agg_trade_id": dict(self.last_agg_trade_id),
            "gap_seq": self._gap_seq,
            "stop_reason": self._stop_reason,
            "events": self.writer.total_rows,
            "reconnects": self.reconnects,
            "resnapshots": self.resnapshots,
            "gaps": len(self.gaps),
        }
        return save_resume_state(self.root, self.run_id, payload)

    # ------------------------------------------------------------------- run
    async def run(self) -> RunManifest:
        self._git_commit = _git_commit()
        self.signals_installed = install_signal_handlers(asyncio.get_running_loop(), self.stop)
        self.resources.start()
        self._load_resume()
        self._write(
            self._global_event(
                EventType.LIFECYCLE,
                detail={
                    "kind": "RUN_START",
                    "run_id": self.run_id,
                    "symbols": list(self.config.symbols),
                    "markets": [m.value for m in self.config.markets],
                    "rotation_seconds": self.config.rotation_seconds,
                    "git_commit": self._git_commit,
                    "signals_installed": self.signals_installed,
                    "streams": list(self.config.streams),
                    "keep_raw": self.config.keep_raw,
                },
            )
        )
        # No *total* timeout on the session: a WebSocket capture is long-lived by
        # design. Only the handshake is bounded, and REST calls pass their own.
        session_timeout = aiohttp.ClientTimeout(
            total=None,
            connect=self.config.connect_timeout_seconds,
            sock_connect=self.config.connect_timeout_seconds,
        )
        async with aiohttp.ClientSession(timeout=session_timeout) as session:
            self._session = session
            for pending_gap, market, symbol, from_id in self._resume_backfills:
                self._schedule_gap_recovery(
                    pending_gap, market, symbol, from_id=from_id, stop_before_id=None
                )
            self._resume_backfills.clear()
            for market in self.config.markets:
                self._tasks.append(asyncio.create_task(self._ws_loop(market, session)))
            if Market.PERP in self.config.markets:
                self._tasks.append(asyncio.create_task(self._aux_loop(Market.PERP, session)))
            self._tasks.append(asyncio.create_task(self._checkpoint_loop()))
            self._tasks.append(asyncio.create_task(self._heartbeat_loop()))
            self._tasks.append(asyncio.create_task(self._maintenance_loop()))
            try:
                await self._wait_until_stopped()
            except asyncio.CancelledError:
                pass
            finally:
                self.stop()
                for task in self._tasks:
                    task.cancel()
                for task in list(self._resnap_tasks.values()):
                    task.cancel()
                await asyncio.gather(
                    *self._tasks, *self._resnap_tasks.values(), return_exceptions=True
                )
        return self.finalise()

    def stop(self, reason: str = "signal") -> None:
        """Ask the run loop to stop after it has sealed what it has written.

        The reason is kept because a capture that was stopped by the disk guard
        and a capture that was stopped by an operator are different findings, and
        the manifest is where that is read from.
        """
        if self._stop_reason is None:
            self._stop_reason = reason
        self._stopping = True

    @property
    def stop_reason(self) -> str | None:
        """Why the run ended, as published in the manifest (``None`` while live)."""
        return self._stop_reason

    def _stop_file_present(self) -> bool:
        path = self.config.stop_file
        return path is not None and Path(path).exists()

    async def _wait_until_stopped(self) -> None:
        """Wait for the duration, the operator's signal, or the stop file.

        The stop file is the portable half: a supervisor on Windows cannot send
        SIGTERM, so a file it can write is the only way to ask for a stop that
        still seals the segments and writes the manifest (§51).
        """
        loop = asyncio.get_running_loop()
        deadline = (
            None
            if self.config.duration_seconds is None
            else loop.time() + self.config.duration_seconds
        )
        while not self._stopping:
            if deadline is not None and loop.time() >= deadline:
                self._stop_reason = self._stop_reason or "duration reached"
                return
            if self._stop_file_present():
                self.stop("stop file")
                return
            await asyncio.sleep(1.0)

    async def _maintenance_loop(self) -> None:
        """Rotate segments and checkpoint resume state on a fixed cadence."""
        while not self._stopping:
            await asyncio.sleep(self.config.maintenance_seconds)
            if self._stopping:
                return
            try:
                self.writer.rotate(_now_ms())
            except Exception as exc:
                self._record_fatal(
                    FAILURE_STORAGE,
                    f"{type(exc).__name__}: {exc}",
                    stop_reason="storage failure",
                )
                return
            if self.config.min_free_bytes is not None:
                free = _disk_free_bytes(self.root)
                if free < self.config.min_free_bytes:
                    with contextlib.suppress(Exception):
                        self._global_write(
                            self._global_event(
                                EventType.LIFECYCLE,
                                detail={
                                    "kind": "MIN_FREE_BYTES_REACHED",
                                    "free_bytes": free,
                                    "floor_bytes": self.config.min_free_bytes,
                                    "note": (
                                        "stopping gracefully before the volume is "
                                        "full; the manifest and fingerprints are "
                                        "still written"
                                    ),
                                },
                            )
                        )
                    self.stopped_on_min_free = True
                    self.stop("disk guard")
                    return
            if self.config.max_total_bytes is not None:
                used = directory_bytes(self.root)
                if used >= self.config.max_total_bytes:
                    self._write(
                        self._global_event(
                            EventType.LIFECYCLE,
                            detail={
                                "kind": "DISK_LIMIT_REACHED",
                                "bytes": used,
                                "limit": self.config.max_total_bytes,
                                "note": (
                                    "stopping gracefully so the capture never fills the "
                                    "volume; the manifest and fingerprints are still written"
                                ),
                            },
                        )
                    )
                    self.stopped_on_disk_budget = True
                    self.stop("disk budget")
                    return
            self._save_state()

    def finalise(self) -> RunManifest:
        self.checkpoint_books()
        self.writer.close()
        fingerprints = self.writer.fingerprints()
        ended = _now_ms()
        bytes_written = sum(f.bytes for f in fingerprints)
        uncompressed_bytes = self.writer.total_bytes
        elapsed_hours = max(1e-9, (ended - self._started_ms) / 3600_000.0)
        # Best-effort final disk measurement on top of the last heartbeat sample.
        self.resources.sample(directory_bytes(self.root), self.network_bytes)
        summary = self.resources.summary(directory_bytes(self.root), self.network_bytes)
        gap_seconds_by_stream: dict[tuple[str, str, str], tuple[int, float]] = {}
        for gap in self.gaps:
            gap_key = (gap.market, gap.symbol, gap.event_type)
            count, seconds = gap_seconds_by_stream.get(gap_key, (0, 0.0))
            increment = gap.duration_ms / 1000.0 if gap.data_lost else 0.0
            gap_seconds_by_stream[gap_key] = (count + 1, seconds + increment)
        resnapshots_by_stream: dict[str, int] = {}
        for key, syncer in self.books.items():
            resnapshots_by_stream[key] = syncer.counters.resnapshots
        bytes_by_stream: dict[tuple[str, str, str], int] = {}
        for fingerprint in fingerprints:
            try:
                market, symbol, event_type = stream_key_from_path(fingerprint.path)
            except Exception:
                continue
            bytes_by_stream[(market, symbol, event_type)] = (
                bytes_by_stream.get((market, symbol, event_type), 0) + fingerprint.bytes
            )

        streams: list[StreamManifest] = []
        for entry in sorted(self.stats.values(), key=lambda e: (e.market, e.symbol, e.event_type)):
            if entry.events == 0 and not entry.lossless:
                continue
            lookup = (entry.market, entry.symbol, entry.event_type)
            gap_count, gap_seconds = gap_seconds_by_stream.get(lookup, (0, 0.0))
            unrecovered = sum(
                gap.duration_ms / 1000.0
                for gap in self.gaps
                if (gap.market, gap.symbol, gap.event_type) == lookup and gap.data_lost
            )
            streams.append(
                StreamManifest(
                    market=entry.market,
                    symbol=entry.symbol,
                    event_type=entry.event_type,
                    transport=entry.transport,
                    lossless=entry.lossless,
                    events=entry.events,
                    bytes=bytes_by_stream.get(lookup, 0),
                    first_receive_time=entry.first_receive_time,
                    last_receive_time=entry.last_receive_time,
                    gaps=gap_count,
                    gap_seconds=round(gap_seconds, 3),
                    unrecovered_gap_seconds=round(unrecovered, 3),
                    duplicates=entry.duplicates,
                    out_of_order=entry.out_of_order,
                    sequence_gaps=entry.sequence_gaps,
                    malformed=entry.malformed,
                    reconnects=(
                        self.reconnects
                        if entry.lossless and entry.transport == Transport.WS.value
                        else 0
                    ),
                    resnapshots=(
                        resnapshots_by_stream.get(f"{entry.market}|{entry.symbol}", 0)
                        if entry.event_type == EventType.DEPTH_DIFF.value
                        else 0
                    ),
                    network_delay_ms=entry.latency.as_dict(),
                )
            )

        book_health = {
            key: {
                "health": syncer.health(ended).value,
                "counters": syncer.counters.as_dict(),
                "last_update_id": syncer.book.last_update_id,
                "bid_levels": syncer.book.bid_levels(),
                "ask_levels": syncer.book.ask_levels(),
            }
            for key, syncer in sorted(self.books.items())
        }
        # §2 — the verdict, derived from what the run recorded, before it is
        # written down. The manifest and the process exit code are the same
        # answer through two channels, so neither can disagree with the other.
        outcome: CaptureOutcome = classify_capture(
            stop_reason=self._stop_reason,
            fatal_kind=self._fatal_kind,
            fatal_reason=self._fatal,
            clock_violations=self.clock_violations,
            book_failed_streams=tuple(
                key for key, state in book_health.items() if state["health"] == "FAILED"
            ),
        )

        # §27 — continuity is a claim about missing data, not about how tidy the
        # run was. A hole that the public index let us walk forward is closed, so
        # only genuinely unrecovered loss makes the dataset incomplete.
        data_lost_gaps = [g for g in self.gaps if g.data_lost]
        recovery_events = [g for g in self.gaps if g.recovered]
        # §2/§57 — a FAILED run cannot claim continuity either. ``reporting``
        # turns this flag into ``permits_continuity_claim`` and
        # ``continuity_continuous``, so a capture whose writer died must not be
        # able to licence a continuity claim downstream just because the rows it
        # never wrote also never produced a gap record.
        continuity = (
            CONTINUITY_INCOMPLETE
            if outcome.failed
            or data_lost_gaps
            or self.clock_violations
            or self.resnapshots_failed
            else CONTINUITY_CONTINUOUS
        )
        manifest = RunManifest(
            run_id=self.run_id,
            collector_version=COLLECTOR_VERSION,
            contract_version=CONTRACT_VERSION,
            schema_version=SCHEMA_VERSION,
            provider=PROVIDER,
            market=",".join(m.value for m in self.config.markets),
            commit=self._git_commit,
            symbols=list(self.config.symbols),
            markets=[m.value for m in self.config.markets],
            started_at=format_utc(self._started_ms) or "",
            ended_at=format_utc(ended),
            duration_seconds=round((ended - self._started_ms) / 1000.0, 3),
            rotation_seconds=self.config.rotation_seconds,
            continuity=continuity,
            depth_n=self.config.depth_n,
            stale_after_ms=self.config.stale_after_ms,
            streams=streams,
            provider_stream_status=provider_stream_status(self.stats),
            gaps=self.gaps,
            reconnects=self.reconnects,
            resnapshots=self.resnapshots,
            bytes_written=bytes_written,
            uncompressed_bytes_written=uncompressed_bytes,
            disk_bytes_per_hour=round(bytes_written / elapsed_hours, 2),
            max_total_bytes=self.config.max_total_bytes,
            stopped_on_disk_budget=self.stopped_on_disk_budget,
            stopped_on_min_free=self.stopped_on_min_free,
            stop_reason=self._stop_reason,
            status=outcome.status.value,
            failure_kind=outcome.kind,
            failure_reason=outcome.reason,
            fingerprints=fingerprints,
            resources=summary.as_dict(),
            book_health=book_health,
            integrity={
                "write_failures": self.write_failures,
                "duplicates": sum(e.duplicates for e in self.stats.values()),
                "out_of_order": sum(e.out_of_order for e in self.stats.values()),
                "sequence_gaps": sum(e.sequence_gaps for e in self.stats.values()),
                "malformed": sum(e.malformed for e in self.stats.values()),
                "clock_violations": self.clock_violations,
                "max_clock_skew_ms": self.max_clock_skew_ms,
                "data_recovering_gaps": len(recovery_events),
                "backfilled_events": self.backfilled_events,
                "backfill_gaps_closed": self.backfill_gaps_closed,
                "backfill_partial": self.backfill_partial,
                "backfill_failures": self.backfill_failures,
                "backfill_deferred": self.backfill_deferred,
                "gaps_by_status": {
                    status: sum(1 for g in self.gaps if g.status == status)
                    for status in GAP_STATUSES
                },
                "remaining_missing_events": sum(
                    g.remaining_missing or 0 for g in self.gaps
                ),
                "data_lost_gaps": len(data_lost_gaps),
                "data_lost_gap_seconds": round(
                    sum(g.duration_ms for g in data_lost_gaps) / 1000.0, 3
                ),
                "recovered_gaps": sum(1 for g in self.gaps if g.recovered),
                "resnapshots_failed": self.resnapshots_failed,
                "resnapshots_deferred": self.resnapshots_deferred,
                "connect_failures": self.connect_failures,
                "failures": self._fatal,
                "streams_selected": list(self.config.streams),
                "keep_raw_payloads": self.config.keep_raw,
            },
            heartbeat_count=len(self.heartbeats),
            degradation_events=self.degradation_events,
        )
        manifest.save(self.root)
        self._save_state()
        return manifest


# ----------------------------------------------------------------- module state
_LOSSLESS: Final[frozenset[EventType]] = frozenset(
    {EventType.AGG_TRADE, EventType.DEPTH_DIFF, EventType.BOOK_TICKER}
)
_GLOBAL_EVENT_TYPES: Final[frozenset[EventType]] = frozenset(
    {EventType.HEARTBEAT, EventType.GAP, EventType.VIOLATION, EventType.LIFECYCLE}
)


def _aggregate_counters(stats: dict[str, StreamStats]) -> dict[str, int]:
    counters: dict[str, int] = {}
    for entry in stats.values():
        counters[entry.event_type] = counters.get(entry.event_type, 0) + entry.events
    return counters


def _git_commit() -> str:
    """HEAD of the repository that produced the capture, for auditability."""
    import subprocess

    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=Path(__file__).resolve().parents[4],
            timeout=10,
        )
        return completed.stdout.strip()
    except Exception:
        return "UNKNOWN"


def install_signal_handlers(loop: asyncio.AbstractEventLoop, stop: Callable[[], None]) -> list[str]:
    """Make SIGINT/SIGTERM stop the collector *gracefully*.

    A signal must never kill the process between an append and a fingerprint: it
    sets a flag and lets the run loop seal every segment and write the manifest.
    Windows has no ``add_signal_handler``, so the portable fallback is used.
    Returns the signal names that were successfully installed.
    """
    installed: list[str] = []

    def _handler(*_args: object) -> None:
        stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop)
            installed.append(sig.name)
            continue
        except (NotImplementedError, RuntimeError, ValueError):
            pass
        try:
            signal.signal(sig, _handler)
            installed.append(sig.name)
        except (ValueError, OSError, AttributeError):  # pragma: no cover - platform dependent
            continue
    return installed
