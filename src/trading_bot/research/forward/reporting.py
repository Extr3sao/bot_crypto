"""Forward dataset reporting: quality, books, resources, daily (§42-§49).

Every number here comes from the capture itself — the manifest for structure and
the persisted rows for latency, health tallies and readiness. Nothing is
estimated, and nothing is rounded up into a claim: readiness verdicts are
``READY_FOR_RESEARCH`` / ``COLLECTING`` / ``NOT_READY``, never a profitability
statement.
"""

from __future__ import annotations

import gzip
import shutil
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from trading_bot.research.forward.aggregation import DatasetAggregation, aggregate_dataset
from trading_bot.research.forward.contract import BACKFILL_ORIGIN, EventType
from trading_bot.research.forward.orderbook import BookHealth
from trading_bot.research.forward.replay import (
    ForwardReplay,
    ReplayVerification,
    aggregation_digest,
    replay_microstructure_dataset,
)
from trading_bot.research.forward.resources import percentile, percentile_from_histogram
from trading_bot.research.forward.storage import (
    CONTINUITY_CONTINUOUS,
    StorageError,
    load_json,
    load_manifest,
    save_json,
)

__all__ = [
    "REPORT_VERSION",
    "build_aggregation",
    "build_book_report",
    "build_contract_document",
    "build_daily_report",
    "build_health_accounting",
    "build_quality_report",
    "build_readiness",
    "build_resource_report",
    "load_run",
    "save_aggregation",
    "write_machine_readable_reports",
]

REPORT_VERSION: Final[str] = "FORWARD-REPORT-V1"

#: §14: below this many days of headroom the volume cannot carry 24/7 collection.
STORAGE_ACCEPTABLE_DAYS: Final[float] = 7.0
#: Between a week and a day of headroom the capture can run, but not unattended.
STORAGE_TIGHT_DAYS: Final[float] = 1.0

#: Sample needed before M-03 (order-book imbalance) can be researched at all.
M03_REQUIRED_MINUTES: Final[int] = 24 * 60
#: M-07 needs a DEV / VAL / OOS split, i.e. days rather than hours of OI.
M07_REQUIRED_DAYS: Final[int] = 6


#: How each event type maps onto the venue's own fields, and which contract
#: fields it populates. Declared here so the machine-readable contract cannot
#: drift away from what the collector actually writes.
EVENT_PROVENANCE: Final[dict[str, dict[str, Any]]] = {
    "agg_trade": {
        "venue_endpoint": "spot wss /ws/<symbol>@aggTrade ; USDⓈ-M wss /ws/<symbol>@aggTrade",
        "venue_fields": {
            "a": "exchange_event_id + sequence.first/last",
            "p": "price (verbatim decimal string)",
            "q": "quantity (verbatim decimal string)",
            "T": "exchange_event_time (trade time)",
            "E": "detail.event_time_ms (event time)",
            "m": "aggressor_side ('sell' when the buyer is the maker)",
            "f": "detail.first_trade_id",
            "l": "trade_count = l - f + 1",
        },
        "loss_detection": "aggregate trade id is strictly +1 per symbol",
    },
    "depth_diff": {
        "venue_endpoint": "wss /ws/<symbol>@depth@100ms",
        "venue_fields": {
            "U": "sequence.first",
            "u": "sequence.last",
            "pu": "sequence.prev (USDⓈ-M only)",
            "b": "bids (verbatim [price, qty] strings)",
            "a": "asks (verbatim [price, qty] strings)",
            "E": "exchange_event_time",
        },
        "loss_detection": "update-id chain: spot U == previous u + 1 ; USDⓈ-M pu == previous u",
    },
    "book_ticker": {
        "venue_endpoint": "wss /ws/<symbol>@bookTicker",
        "venue_fields": {
            "u": "exchange_event_id + sequence.last",
            "b": "bid",
            "B": "bid_qty",
            "a": "ask",
            "A": "ask_qty",
            "E/T": "exchange_event_time (USDⓈ-M only; spot publishes none)",
        },
        "loss_detection": "update id is monotonic but not contiguous; liveness only",
    },
    "depth_snapshot": {
        "venue_endpoint": "REST GET /api/v3/depth ; GET /fapi/v1/depth",
        "venue_fields": {
            "lastUpdateId": "exchange_event_id + sequence.last",
            "bids": "bids",
            "asks": "asks",
        },
        "loss_detection": "not applicable; this is the alignment anchor",
    },
    "open_interest": {
        "venue_endpoint": "REST GET /fapi/v1/openInterest",
        "venue_fields": {"openInterest": "open_interest", "time": "open_interest_time"},
        "loss_detection": "periodic poll; the venue DOES supply an independent timestamp",
    },
    "mark_price": {
        "venue_endpoint": "REST GET /fapi/v1/premiumIndex",
        "venue_fields": {
            "markPrice": "mark_price",
            "indexPrice": "index_price",
            "time": "exchange_event_time",
        },
        "loss_detection": "periodic poll; basis is derived from these raw inputs plus spot bookTicker",
    },
    "funding": {
        "venue_endpoint": "REST GET /fapi/v1/premiumIndex",
        "venue_fields": {
            "lastFundingRate": "funding_rate",
            "nextFundingTime": "next_funding_time",
        },
        "loss_detection": "periodic by nature of the venue; interval recorded in the manifest",
    },
    "book_checkpoint": {
        "venue_endpoint": "derived from the reconstructed book",
        "venue_fields": {},
        "loss_detection": (
            "emitted every checkpoint interval with its health; only HEALTHY checkpoints "
            "may feed a feature"
        ),
    },
    "heartbeat": {
        "venue_endpoint": "collector telemetry",
        "venue_fields": {},
        "loss_detection": "not applicable",
    },
    "gap": {
        "venue_endpoint": "collector telemetry",
        "venue_fields": {},
        "loss_detection": "this IS the loss record",
    },
    "violation": {
        "venue_endpoint": "collector telemetry",
        "venue_fields": {},
        "loss_detection": "each violation is a discarded or quarantined datum",
    },
    "lifecycle": {
        "venue_endpoint": "collector telemetry",
        "venue_fields": {},
        "loss_detection": "connect/disconnect/restart/state evidence",
    },
}


def build_contract_document() -> dict[str, Any]:
    """The machine-readable forward data contract, generated from the code.

    Generated rather than hand-written so the documented schema cannot drift away
    from the schema the collector actually writes.
    """
    from trading_bot.research.forward.contract import (
        COLLECTOR_VERSION,
        CONTRACT_VERSION,
        LOSSLESS_EVENT_TYPES,
        PERIODIC_EVENT_TYPES,
        PROVIDER,
        SCHEMA_VERSION,
        TRANSPORT_BY_EVENT_TYPE,
        EventType,
        Market,
        RawEvent,
        SequenceRange,
    )

    sample = RawEvent(
        event_type=EventType.HEARTBEAT,
        symbol="BTCUSDT",
        market=Market.SPOT,
        stream="heartbeat",
        transport=TRANSPORT_BY_EVENT_TYPE[EventType.HEARTBEAT],
        run_id="contract-sample",
        exchange_event_time=None,
        receive_time=0,
        process_time=0,
    )
    return {
        "contract_version": CONTRACT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "collector_version": COLLECTOR_VERSION,
        "provider": PROVIDER,
        "markets": [market.value for market in Market],
        "field_order": list(sample.to_dict()),
        "sequence_fields": list(SequenceRange().as_dict()),
        "clocks": {
            "exchange_event_time": "venue clock, milliseconds, may be absent by design",
            "receive_time": "when the frame finished being read off the socket",
            "process_time": "when the record was assembled for persistence",
            "network_delay_ms": "receive_time - exchange_event_time (derived)",
            "processing_delay_ms": "process_time - receive_time (derived)",
            "note": "derived values are recorded alongside the three clocks, never instead of them",
        },
        "temporal_invariants": [
            "process_time >= receive_time (enforced, raises ClockViolation)",
            "exchange_event_time <= receive_time + collector tolerance, default 500 ms",
            "a violation of the second invariant quarantines the event into the violation stream",
        ],
        "number_representation": (
            "every price, quantity, depth level, funding rate and open interest is stored as "
            "the exact decimal STRING the venue sent; nothing is coerced to float on the way "
            "to disk, and a zero quantity stays exactly zero (it means: delete this level)"
        ),
        "event_types": {
            event_type.value: {
                "transport": TRANSPORT_BY_EVENT_TYPE[event_type].value,
                "lossless": event_type in LOSSLESS_EVENT_TYPES,
                "periodic": event_type in PERIODIC_EVENT_TYPES,
                **EVENT_PROVENANCE.get(
                    event_type.value,
                    {"venue_endpoint": "n/a", "venue_fields": {}, "loss_detection": "n/a"},
                ),
            }
            for event_type in EventType
        },
        "book_health_states": ["HEALTHY", "RECOVERING", "STALE", "INVALID"],
        "diff_verdicts": [
            "APPLIED",
            "BUFFERED",
            "DUPLICATE",
            "OUT_OF_ORDER",
            "GAP",
            "MALFORMED",
        ],
        "sequence_policies": {
            "spot_update_id": (
                "after a snapshot with lastUpdateId L, drop u <= L, the bridging update must "
                "satisfy U <= L + 1 <= u, then every update must satisfy U == previous u + 1"
            ),
            "futures_prev_id": (
                "after a snapshot with lastUpdateId L, drop u < L, the bridging update must "
                "satisfy U <= L + 1 <= u, then every update must satisfy pu == previous u"
            ),
        },
        "gap_record_fields": [
            "market",
            "symbol",
            "event_type",
            "start_ms",
            "end_ms",
            "duration_ms",
            "reason",
            "recovered",
            "data_lost",
            "estimated_lost_events",
            "detail",
        ],
        "fingerprint_fields": [
            "path",
            "row_count",
            "first_event_time",
            "last_event_time",
            "first_receive_time",
            "last_receive_time",
            "sha256",
            "bytes",
            "schema_version",
            "sealed",
            "partial_tail",
        ],
        "storage_layout": (
            "<root>/segments/<source>/<market>/<symbol>/<event_type>/<UTC date>/"
            "<rotation bucket HHMMSS>.jsonl.gz"
        ),
    }


def load_run(root: Path | str, run_id: str | None = None) -> tuple[str, dict[str, Any]]:
    """Resolve a run and return ``(run_id, manifest)``."""
    base = Path(root)
    manifest_dir = base / "manifest"
    if not manifest_dir.is_dir():
        raise StorageError(f"{base}: no manifest/ directory — nothing has been captured yet")
    resolved = run_id
    if resolved is None:
        candidates = sorted(manifest_dir.glob("*.json"))
        if not candidates:
            raise StorageError(f"{base}: manifest/ is empty")
        resolved = candidates[-1].stem
    return resolved, load_manifest(manifest_dir / f"{resolved}.json")


def build_aggregation(
    root: Path | str, run_id: str | None = None
) -> tuple[str, DatasetAggregation]:
    """Rebuild the full raw -> 1m -> 5m/15m/30m aggregation from persisted rows.

    The aggregation is given a callable source, not a list: an hour of forward
    capture is millions of rows, so holding them here would make the report
    unrunnable on exactly the capture it exists to describe. Each accumulator
    re-reads the run instead, trading I/O for memory (§34).
    """
    base = Path(root)
    resolved, _manifest = load_run(base, run_id)
    replay = ForwardReplay(base, resolved)
    loss_windows, window = replay.capture_bounds_from_manifest()
    # ``counts`` is left to the aggregator: the manifest counts only the streams it
    # models, while the digest must cover every persisted row type (heartbeats,
    # lifecycle, gaps), so the aggregator tallies by streaming one more pass.
    aggregation = aggregate_dataset(
        replay.iter_events,
        run_id=resolved,
        loss_windows=loss_windows,
        window=window,
    )
    return resolved, aggregation


def save_aggregation(root: Path | str, run_id: str, aggregation: DatasetAggregation) -> Path:
    """Persist the aggregation digest so replay can prove feature equality (§32)."""
    payload = aggregation.as_dict()
    summary = {
        "run_id": run_id,
        "digest": aggregation_digest(aggregation),
        "event_counts": payload["event_counts"],
        "intervals_minutes": payload["intervals_minutes"],
        "trade_bucket_count": sum(len(v) for v in payload["trades"].values()),
        "derived_bucket_count": sum(len(v) for v in payload["derived"].values()),
        "book_bucket_count": sum(len(v) for v in payload["book"].values()),
        "open_interest_bucket_count": sum(len(v) for v in payload["open_interest"].values()),
        "complete_1m_buckets": {
            key: sum(1 for b in buckets if b["complete"])
            for key, buckets in sorted(payload["trades"].items())
        },
    }
    path = Path(root) / "aggregation" / f"{run_id}.json"
    save_json(path, summary)
    return path


@dataclass(slots=True)
class _StreamScan:
    events: int = 0
    with_event_time: int = 0
    #: Delay distribution as value -> count. One entry per event would grow with
    #: the capture and make the report unrunnable on the run it describes, and
    #: every event type here has few distinct millisecond delays, so the exact
    #: distribution costs almost nothing (§34).
    delay_counts: dict[int, int] = field(default_factory=dict)
    process_before_receive: int = 0
    event_after_receive: int = 0
    duplicate_ids: int = 0
    out_of_order_ids: int = 0
    backfilled_events: int = 0
    first_receive: int | None = None
    last_receive: int | None = None


#: The lifecycle kinds the health accounting reads. Kept to the transport
#: transitions: they are the only rows that record how long a socket was *down*
#: rather than how much a stream lost.
_HEALTH_LIFECYCLE_KINDS: Final[frozenset[str]] = frozenset(
    {"WS_CONNECTED", "WS_DISCONNECTED", "DISK_LIMIT_REACHED", "STORAGE_FAILURE"}
)


@dataclass(slots=True)
class _RowScan:
    """Everything the quality report needs, from one streaming pass (§34)."""

    scans: dict[str, _StreamScan] = field(default_factory=lambda: defaultdict(_StreamScan))
    checkpoints: dict[str, list[dict[str, Any]]] = field(default_factory=lambda: defaultdict(list))
    #: Transport transitions only: one per connect/disconnect, so bounded.
    lifecycle: list[dict[str, Any]] = field(default_factory=list)


def _stream_rows(replay: ForwardReplay) -> tuple[Iterator[dict[str, Any]], list[int]]:
    """Stream a run's rows, exposing the running partial-tail count in a box."""
    box = [0]

    def _rows() -> Iterator[dict[str, Any]]:
        for row, partial in replay.iter_rows():
            box[0] = partial
            yield row

    return _rows(), box


def _scan_rows(rows: Iterable[dict[str, Any]]) -> _RowScan:
    """One streaming pass over the rows, keeping only bounded aggregates.

    Nothing here grows with the number of rows: a capture of days must be
    analysable in constant memory, so counters and the checkpoint list are the
    only things retained.
    """
    result = _RowScan()
    scans = result.scans
    seen_ids: dict[str, int] = {}
    for row in rows:
        key = f"{row.get('market')}/{row.get('symbol')}/{row.get('event_type')}"
        scan = scans[key]
        scan.events += 1
        receive = int(row.get("receive_time") or 0)
        process = int(row.get("process_time") or 0)
        if process < receive:
            scan.process_before_receive += 1
        scan.first_receive = (
            receive if scan.first_receive is None else min(scan.first_receive, receive)
        )
        scan.last_receive = (
            receive if scan.last_receive is None else max(scan.last_receive, receive)
        )
        # A recovered row is one of the venue's own records, restored later on
        # purpose. Its delivery delay is the width of the outage it repaired, so
        # folding it into the latency distribution would describe our downtime
        # as network latency.
        detail = row.get("detail")
        backfilled = isinstance(detail, dict) and detail.get("origin") == BACKFILL_ORIGIN
        if backfilled:
            scan.backfilled_events += 1
        event_time = row.get("exchange_event_time")
        if isinstance(event_time, int):
            scan.with_event_time += 1
            if not backfilled:
                delay = receive - event_time
                scan.delay_counts[delay] = scan.delay_counts.get(delay, 0) + 1
            if event_time > receive:
                scan.event_after_receive += 1
        if row.get("event_type") == EventType.AGG_TRADE.value:
            raw_id = row.get("exchange_event_id")
            if raw_id is not None:
                identifier = int(raw_id)
                id_key = f"{row.get('market')}/{row.get('symbol')}"
                previous = seen_ids.get(id_key)
                if previous is not None:
                    if identifier == previous:
                        scan.duplicate_ids += 1
                    elif identifier < previous:
                        scan.out_of_order_ids += 1
                seen_ids[id_key] = max(identifier, previous if previous is not None else identifier)
        elif row.get("event_type") == EventType.BOOK_CHECKPOINT.value:
            detail = row.get("detail")
            if isinstance(detail, dict):
                result.checkpoints[f"{row.get('market')}/{row.get('symbol')}"].append(detail)
        elif row.get("event_type") == EventType.LIFECYCLE.value:
            detail = row.get("detail")
            kind = detail.get("kind") if isinstance(detail, dict) else None
            if kind in _HEALTH_LIFECYCLE_KINDS:
                result.lifecycle.append(
                    {
                        "kind": kind,
                        "market": (detail or {}).get("market", row.get("market")),
                        "receive_time": receive,
                        "reason": (detail or {}).get("reason"),
                    }
                )
    return result


def build_book_report(
    checkpoints: dict[str, list[dict[str, Any]]], manifest: dict[str, Any]
) -> dict[str, Any]:
    """§45 — everything a consumer must know before trusting a book.

    Takes the checkpoints already collected by the single scan pass: there is one
    checkpoint per interval per book, so the list stays bounded on a capture of
    any length (§34).
    """
    book: dict[str, Any] = {}
    for key, entries in sorted(checkpoints.items()):
        tally: dict[str, int] = defaultdict(int)
        for detail in entries:
            tally[str(detail.get("health"))] += 1
        healthy = tally.get(BookHealth.HEALTHY.value, 0)
        book[key] = {
            "checkpoints": len(entries),
            "health_tally": dict(sorted(tally.items())),
            "healthy": healthy,
            "usable_ratio": round(healthy / len(entries), 6) if entries else 0.0,
            "stale": tally.get(BookHealth.STALE.value, 0),
            "invalid": tally.get(BookHealth.INVALID.value, 0),
            "recovering": tally.get(BookHealth.RECOVERING.value, 0),
        }
    for key, entry in sorted(manifest.get("book_health", {}).items()):
        market, symbol = key.split("|", 1)
        slot = book.setdefault(
            f"{market}/{symbol}",
            {
                "checkpoints": 0,
                "health_tally": {},
                "healthy": 0,
                "usable_ratio": 0.0,
                "stale": 0,
                "invalid": 0,
                "recovering": 0,
            },
        )
        slot["final_health"] = entry["health"]
        slot["counters"] = entry["counters"]
        slot["crossed_book_events"] = entry["counters"]["crossed_book_events"]
        slot["sequence_gaps"] = entry["counters"]["gaps"]
        slot["resnapshots"] = entry["counters"]["resnapshots"]
        slot["invalidations"] = entry["counters"]["invalidations"]
        slot["snapshot_mismatches"] = entry["counters"]["snapshot_mismatches"]
        slot["final_bid_levels"] = entry["bid_levels"]
        slot["final_ask_levels"] = entry["ask_levels"]
        slot["final_last_update_id"] = entry["last_update_id"]
    return book


def _iso_to_ms(value: Any) -> int | None:
    """Parse the manifest's ISO-8601 UTC stamps into epoch milliseconds."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp() * 1000)


def _merge_windows(windows: list[tuple[int, int]]) -> list[list[int]]:
    """Half-open union of the windows in which some stream was actually losing."""
    merged: list[list[int]] = []
    for start, end in sorted(windows):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def build_reconnect_accounting(
    lifecycle: Iterable[dict[str, Any]], ended_ms: int | None
) -> dict[str, Any]:
    """§6 — how long each socket was actually *down*, not just how much was lost.

    A gap record spans ``last_seen -> detected``: that is what a stream swallowed,
    not the downtime. The interval between a socket being detected as down and
    being established again is only visible in the persisted lifecycle rows, so
    it is derived here rather than assumed away. Without it the health accounting
    would quietly call the whole reconnect a healthy second.
    """
    by_market: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in lifecycle:
        by_market[str(entry.get("market"))].append(entry)

    intervals: list[tuple[str, int, int]] = []
    still_down: list[dict[str, Any]] = []
    for market, entries in sorted(by_market.items()):
        down_at: int | None = None
        for entry in sorted(entries, key=lambda item: int(item["receive_time"])):
            kind = entry.get("kind")
            if kind == "WS_DISCONNECTED":
                down_at = int(entry["receive_time"])
            elif kind == "WS_CONNECTED" and down_at is not None:
                intervals.append((market, down_at, int(entry["receive_time"])))
                down_at = None
        if down_at is not None:
            still_down.append({"market": market, "down_at_ms": down_at})
            if ended_ms is not None:
                intervals.append((market, down_at, ended_ms))

    durations = [end - start for _market, start, end in intervals]
    per_market: dict[str, Any] = {}
    for market in sorted({entry[0] for entry in intervals}):
        subset = [(start, end) for name, start, end in intervals if name == market]
        per_market[market] = {
            "cycles": len(subset),
            "downtime_seconds": round(sum(end - start for start, end in subset) / 1000.0, 3),
            "longest_ms": max((end - start for start, end in subset), default=0),
        }
    return {
        "method": "read-side from the persisted WS_DISCONNECTED -> WS_CONNECTED lifecycle rows",
        "cycles": len(intervals),
        "downtime_seconds_total": round(sum(durations) / 1000.0, 3),
        "downtime_ms_min": min(durations) if durations else None,
        "downtime_ms_p50": percentile([float(value) for value in durations], 0.50),
        "downtime_ms_max": max(durations) if durations else None,
        "per_market": per_market,
        "still_down_at_end": still_down,
        "intervals": [[start, end] for _market, start, end in intervals],
    }


def build_health_accounting(
    manifest: dict[str, Any],
    lifecycle: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """§6 — HEALTHY / DEGRADED / FAILED seconds, derived from the run's record.

    Two views are reported, because they answer different questions.

    ``collector_state`` is the writer's own state timeline. The writer is
    deliberately *sticky*: a recorded gap is never erased, so the state does not
    return to HEALTHY once the hour has seen one. On its own that would read as
    an hour of failure, so it is reported next to the live view, never instead
    of it.

    ``live`` is derived read-side from the gap windows. A millisecond is
    DEGRADED when it falls inside a window in which some stream actually lost
    data, and HEALTHY otherwise, so a recoverable disconnect shows up as
    DEGRADED -> reconnect -> HEALTHY. FAILED is reserved for a run that could
    not work around a condition, which is the writer's own fatal record rather
    than a busy socket.
    """
    started_ms = _iso_to_ms(manifest.get("started_at"))
    ended_ms = _iso_to_ms(manifest.get("ended_at"))
    if started_ms is None or ended_ms is None:
        duration_ms = int(float(manifest.get("duration_seconds") or 0.0) * 1000)
    else:
        duration_ms = max(0, ended_ms - started_ms)

    all_gaps = list(manifest.get("gaps", []))
    loss_gaps = [gap for gap in all_gaps if gap.get("data_lost")]
    # Any recorded window is a degradation, whether or not the hole was later
    # closed: a recoverable disconnect is still a disconnect (§6). Whether it
    # returned to HEALTHY is a question about what came *after* the window.
    windows = [(int(gap["start_ms"]), int(gap["end_ms"])) for gap in all_gaps]
    instantaneous = [gap for gap in loss_gaps if int(gap["end_ms"]) <= int(gap["start_ms"])]
    reconnect = build_reconnect_accounting(lifecycle or [], ended_ms)
    # The socket-level downtime is real degraded time even when no stream can
    # attribute lost ids to it, so both sources feed the union.
    windows.extend((int(start), int(end)) for start, end in reconnect["intervals"])
    positive = [(start, end) for start, end in windows if end > start]
    merged = _merge_windows(positive)
    degraded_ms = sum(end - start for start, end in merged)
    fatal = (manifest.get("integrity") or {}).get("failures")
    failed_ms = duration_ms if fatal else 0
    healthy_ms = max(0, duration_ms - degraded_ms - failed_ms)

    episodes: list[dict[str, Any]] = []
    for start, end in merged:
        inside = [
            gap for gap in all_gaps if int(gap["start_ms"]) <= end and int(gap["end_ms"]) >= start
        ]
        recovered = [g for g in inside if g.get("recovered")]
        partial = [g for g in inside if not g.get("recovered") and g.get("recovered_events")]
        lost = [
            g
            for g in inside
            if g.get("data_lost") and not g.get("recovered") and not g.get("recovered_events")
        ]
        # A disconnect episode is not "recovered" unless every hole inside it was
        # filled: a recoverable stream and an unrecoverable one landing in the
        # same window are still not the same event (§4).
        if lost and (recovered or partial):
            outcome = "PARTIAL_LOSS"
        elif lost:
            outcome = "PERMANENT_LOSS"
        elif recovered or partial:
            outcome = "RECOVERED"
        else:
            outcome = "NO_DATA_LOST"
        episodes.append(
            {
                "start_ms": start,
                "end_ms": end,
                "duration_ms": end - start,
                "returned_to_healthy": (end < ended_ms) if ended_ms is not None else None,
                "outcome": outcome,
                "gaps": len(inside),
                "gaps_recovered": len(recovered),
                "gaps_recovered_partial": len(partial),
                "gaps_with_permanent_loss": len(lost),
                "gaps_with_no_data_loss": len(inside) - len(recovered) - len(partial) - len(lost),
                "reasons": sorted({str(g.get("reason")) for g in inside}),
                "streams": sorted(
                    {f"{g.get('market')}/{g.get('symbol')}/{g.get('event_type')}" for g in inside}
                ),
            }
        )

    transitions = list(manifest.get("degradation_events", []))
    state_seconds: dict[str, int] = defaultdict(int)
    current = "HEALTHY"
    if started_ms is not None:
        cursor: int = started_ms
        for entry in transitions:
            at = int(entry.get("at_ms") or started_ms)
            state_seconds[current] += max(0, at - cursor)
            current = str(entry.get("to") or current)
            cursor = at
        if ended_ms is not None:
            state_seconds[current] += max(0, ended_ms - cursor)

    def _seconds(milliseconds: int) -> float:
        return round(milliseconds / 1000.0, 3)

    def _fraction(milliseconds: int) -> float:
        return round(milliseconds / duration_ms, 8) if duration_ms else 0.0

    return {
        "method": (
            "derived read-side from the manifest's gap windows; the writer's own "
            "state timeline is reported separately because it is sticky"
        ),
        "capture_seconds": _seconds(duration_ms),
        "live": {
            "healthy_seconds": _seconds(healthy_ms),
            "degraded_seconds": _seconds(degraded_ms),
            "failed_seconds": _seconds(failed_ms),
            "healthy_fraction": _fraction(healthy_ms),
            "degraded_fraction": _fraction(degraded_ms),
            "failed_fraction": _fraction(failed_ms),
            "degraded_episodes": len(merged),
            "episodes_returning_to_healthy": sum(
                1 for entry in episodes if entry["returned_to_healthy"]
            ),
            "episodes_with_permanent_loss": sum(
                1 for entry in episodes if entry["outcome"] == "PERMANENT_LOSS"
            ),
            "episodes_with_partial_loss": sum(
                1 for entry in episodes if entry["outcome"] == "PARTIAL_LOSS"
            ),
            "episodes_with_no_data_loss": sum(
                1 for entry in episodes if entry["outcome"] == "NO_DATA_LOST"
            ),
            "longest_degraded_ms": max((end - start for start, end in merged), default=0),
            "instantaneous_loss_events": len(instantaneous),
            "instantaneous_loss_note": (
                "a zero-length window still lost the ids it names: those holes carry "
                "no wall-clock duration but are counted as instantaneous loss events"
            ),
        },
        "collector_state": {
            "timeline": transitions,
            "seconds_by_state": {
                state: _seconds(milliseconds)
                for state, milliseconds in sorted(state_seconds.items())
            },
            "sticky": True,
            "sticky_note": (
                "the writer never erases a recorded gap, so DEGRADED is monotone: "
                "a recoverable disconnect moves the state to DEGRADED and leaves it "
                "there. The live view above is the one that shows the recovery."
            ),
        },
        "episodes": episodes,
        "reconnect_downtime": {
            key: value for key, value in reconnect.items() if key != "intervals"
        },
        "degraded_window_sources": (
            "union of per-stream gap windows, the reconnect downtime derived from "
            "the lifecycle rows, and the writer's fatal record"
        ),
        "failed_run": bool(fatal),
    }


#: Streams whose ids name discrete events, so an id step is an event count. The
#: book streams are deliberately absent: an update id is a sequence position, and
#: a span of skipped positions is not the number of updates that were skipped.
ID_STEP_IS_AN_EVENT_COUNT = ("agg_trade",)


def _loss_estimate_semantics(gaps: list[dict[str, Any]]) -> dict[str, Any]:
    """Read the writer's own loss estimate for what it can and cannot mean.

    ``estimated_lost_events`` is what the writer derived from the id space it was
    holding. For aggregate trades one id is one trade, so it is a count. For depth
    updates it is a span of sequence numbers, and a span is not a number of missing
    events: on a real hour it dwarfs the row count, so summing it across streams
    would produce a loss figure larger than the capture that contains it. The
    physical quantity the capture really lost is the wall-clock time in which no
    stream delivered anything, so both are reported side by side rather than the
    estimate being presented alone.
    """
    by_stream: dict[str, dict[str, Any]] = {}
    for gap in gaps:
        if not gap.get("data_lost"):
            continue
        event_type = str(gap.get("event_type") or "unknown")
        slot = by_stream.setdefault(event_type, {"gaps": 0, "id_steps": 0, "seconds": 0.0})
        slot["gaps"] += 1
        slot["id_steps"] += int(gap.get("estimated_lost_events") or 0)
        slot["seconds"] = round(slot["seconds"] + float(gap.get("duration_ms") or 0) / 1000.0, 6)
    for event_type, slot in by_stream.items():
        slot["id_steps_are_an_event_count"] = event_type in ID_STEP_IS_AN_EVENT_COUNT
    counted = sum(
        slot["id_steps"] for slot in by_stream.values() if slot["id_steps_are_an_event_count"]
    )
    spanned = sum(
        slot["id_steps"] for slot in by_stream.values() if not slot["id_steps_are_an_event_count"]
    )
    return {
        "per_stream": dict(sorted(by_stream.items())),
        "id_steps_that_are_an_event_count": counted,
        "id_steps_that_are_a_sequence_span_only": spanned,
        "lost_wall_clock_seconds": round(sum(slot["seconds"] for slot in by_stream.values()), 6),
        "note": (
            "only agg_trade ids name discrete events; for depth_diff an id step is a "
            "position in a sequence, and the affected book was invalidated and "
            "resnapshotted rather than asked to account for a count of missing updates"
        ),
    }


def build_quality_report(root: Path | str, run_id: str | None = None) -> dict[str, Any]:
    """§44/§45 — per-stream event, loss, latency and book quality."""
    base = Path(root)
    resolved, manifest = load_run(base, run_id)
    rows, partial_box = _stream_rows(ForwardReplay(base, resolved))
    scan_result = _scan_rows(rows)
    scans = scan_result.scans
    partial_tails = partial_box[0]

    streams: dict[str, Any] = {}
    for stream in manifest.get("streams", []):
        key = f"{stream['market']}/{stream['symbol']}/{stream['event_type']}"
        scan = scans.get(key, _StreamScan())
        delays = scan.delay_counts
        duration_s = max(
            1e-9,
            ((stream["last_receive_time"] or 0) - (stream["first_receive_time"] or 0)) / 1000.0,
        )
        streams[key] = {
            "transport": stream["transport"],
            "lossless": stream["lossless"],
            "events": stream["events"],
            "verified_events": scan.events,
            "bytes": stream["bytes"],
            "events_per_second": round(stream["events"] / duration_s, 4),
            "first_receive_time": stream["first_receive_time"],
            "last_receive_time": stream["last_receive_time"],
            "duplicates": scan.duplicate_ids,
            "out_of_order": scan.out_of_order_ids,
            "sequence_gaps": stream["sequence_gaps"],
            "malformed": stream["malformed"],
            "gaps": stream["gaps"],
            "gap_seconds": stream["gap_seconds"],
            "unrecovered_gap_seconds": stream["unrecovered_gap_seconds"],
            "reconnects": stream["reconnects"],
            "resnapshots": stream["resnapshots"],
            "backfilled_events": scan.backfilled_events,
            "duplicate_rows_on_disk": scan.duplicate_ids,
            "events_with_exchange_time": scan.with_event_time,
            "event_time_coverage": (
                round(scan.with_event_time / scan.events, 6) if scan.events else 0.0
            ),
            "event_latency_ms": {
                "p50": percentile_from_histogram(delays, 0.50),
                "p95": percentile_from_histogram(delays, 0.95),
                "p99": percentile_from_histogram(delays, 0.99),
                "max": max(delays) if delays else None,
                "min": min(delays) if delays else None,
                "samples": sum(delays.values()),
            },
            "process_before_receive": scan.process_before_receive,
            "event_after_receive": scan.event_after_receive,
        }

    all_delays: dict[int, int] = defaultdict(int)
    for scan in scans.values():
        for value, count in scan.delay_counts.items():
            all_delays[value] += count
    gaps = manifest.get("gaps", [])
    by_reason: dict[str, int] = defaultdict(int)
    for gap in gaps:
        by_reason[str(gap["reason"])] += 1
    integrity = manifest.get("integrity", {})
    # A gap whose window was empty is neither recovered nor lost: nothing was
    # ever in it. Counting it with the real holes would overstate the damage, so
    # the three cases are tallied separately and the arithmetic is kept visible.
    gaps_empty = sum(
        1 for gap in gaps if not gap.get("data_lost") and not gap.get("recovered_events")
    )
    gaps_with_loss = sum(1 for gap in gaps if gap.get("data_lost"))
    report = {
        "report_version": REPORT_VERSION,
        "run_id": resolved,
        "collector_version": manifest.get("collector_version"),
        "contract_version": manifest.get("contract_version"),
        "schema_version": manifest.get("schema_version"),
        "commit": manifest.get("commit"),
        "provider": manifest.get("provider"),
        "markets": manifest.get("markets"),
        "assets": manifest.get("symbols"),
        "capture": {
            "started_at": manifest.get("started_at"),
            "ended_at": manifest.get("ended_at"),
            "duration_seconds": manifest.get("duration_seconds"),
        },
        "continuity": manifest.get("continuity"),
        "continuity_continuous": manifest.get("continuity") == CONTINUITY_CONTINUOUS,
        "provider_stream_status": manifest.get("provider_stream_status", {}),
        "streams": streams,
        "totals": {
            "events": sum(s["events"] for s in streams.values()),
            # Counted during the same streaming pass, never by materialising it.
            "rows_on_disk": sum(scan.events for scan in scans.values()),
            "segments": len(manifest.get("fingerprints", [])),
            "bytes_on_disk": sum(int(f["bytes"]) for f in manifest.get("fingerprints", [])),
            "partial_tails": partial_tails,
            "agg_trade_events": sum(
                s["events"] for k, s in streams.items() if k.endswith("/agg_trade")
            ),
            "book_update_events": sum(
                s["events"] for k, s in streams.items() if k.endswith("/depth_diff")
            ),
            "book_ticker_events": sum(
                s["events"] for k, s in streams.items() if k.endswith("/book_ticker")
            ),
            "book_checkpoint_events": sum(
                s["events"] for k, s in streams.items() if k.endswith("/book_checkpoint")
            ),
            "open_interest_events": sum(
                s["events"] for k, s in streams.items() if k.endswith("/open_interest")
            ),
            "funding_events": sum(
                s["events"] for k, s in streams.items() if k.endswith("/funding")
            ),
            "mark_price_events": sum(
                s["events"] for k, s in streams.items() if k.endswith("/mark_price")
            ),
        },
        "loss": {
            "duplicates": integrity.get("duplicates", 0),
            "duplicate_rows_on_disk": sum(s["duplicate_rows_on_disk"] for s in streams.values()),
            "out_of_order": integrity.get("out_of_order", 0),
            "sequence_gaps": integrity.get("sequence_gaps", 0),
            "gaps_total": len(gaps),
            "gaps_data_lost": integrity.get("data_lost_gaps", 0),
            "gaps_with_loss": gaps_with_loss,
            "gaps_empty_window": gaps_empty,
            "gaps_accounted": gaps_with_loss + gaps_empty,
            "gaps_accounting_is_complete": (
                gaps_with_loss
                + gaps_empty
                + sum(1 for gap in gaps if not gap.get("data_lost") and gap.get("recovered_events"))
                == len(gaps)
            ),
            "gaps_recovered": integrity.get("recovered_gaps", 0),
            "gaps_by_status": integrity.get("gaps_by_status", {}),
            "backfilled_events": integrity.get("backfilled_events", 0),
            "backfill_gaps_closed": integrity.get("backfill_gaps_closed", 0),
            "backfill_partial": integrity.get("backfill_partial", 0),
            "backfill_failures": integrity.get("backfill_failures", 0),
            "backfill_deferred": integrity.get("backfill_deferred", 0),
            "remaining_missing_events": integrity.get("remaining_missing_events", 0),
            "data_lost_gap_seconds": integrity.get("data_lost_gap_seconds", 0.0),
            "estimate_semantics": _loss_estimate_semantics(gaps),
            "gaps_by_reason": dict(sorted(by_reason.items())),
            "malformed": integrity.get("malformed", 0),
            "clock_violations": integrity.get("clock_violations", 0),
            "max_clock_skew_ms": integrity.get("max_clock_skew_ms", 0),
            "reconnects": manifest.get("reconnects", 0),
            "resnapshots": manifest.get("resnapshots", 0),
            "resnapshots_failed": integrity.get("resnapshots_failed", 0),
        },
        "event_latency_ms": {
            "p50": percentile_from_histogram(all_delays, 0.50),
            "p95": percentile_from_histogram(all_delays, 0.95),
            "p99": percentile_from_histogram(all_delays, 0.99),
            "max": max(all_delays) if all_delays else None,
            "samples": sum(all_delays.values()),
            "note": (
                "live delivery only; recovered rows are counted in "
                "loss.backfilled_events instead of being described as latency"
            ),
        },
        "storage_latency_ms": {
            "p50": percentile([float(s.process_before_receive) for s in scans.values()], 0.50),
            "note": (
                "process_time - receive_time is measured per event and persisted; the "
                "aggregate is reported as the processing_delay_ms distribution"
            ),
        },
        "books": build_book_report(scan_result.checkpoints, manifest),
        "fingerprints": {
            "segments": len(manifest.get("fingerprints", [])),
            "sealed": sum(1 for f in manifest.get("fingerprints", []) if f["sealed"]),
            "rows": sum(int(f["row_count"]) for f in manifest.get("fingerprints", [])),
            "bytes": sum(int(f["bytes"]) for f in manifest.get("fingerprints", [])),
            "with_partial_tail": sum(
                1 for f in manifest.get("fingerprints", []) if f["partial_tail"]
            ),
            "schema_versions": sorted(
                {str(f["schema_version"]) for f in manifest.get("fingerprints", [])}
            ),
        },
        "cases": {
            "rest_polling_used_for_high_frequency_trades": False,
            "rest_polling_used_for": sorted(
                {
                    s["transport"]
                    for k, s in streams.items()
                    if s["transport"] != "ws" and s["events"] > 0
                }
            ),
            "permits_continuity_claim": manifest.get("continuity") == CONTINUITY_CONTINUOUS,
        },
    }
    report["health"] = build_health_accounting(manifest, scan_result.lifecycle)
    report["readiness"] = build_readiness(report, manifest)
    return report


def build_readiness(report: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    """§46/§49 — what M-03 and M-07 still need, stated as gaps not as hopes."""
    totals = report["totals"]
    books = report["books"]
    depth_gaps = sum(
        s["sequence_gaps"] for k, s in report["streams"].items() if k.endswith("/depth_diff")
    )
    # §9 — a book is usable when a checkpoint *observed* it HEALTHY, which is a
    # property of the run; ending the capture HEALTHY is a property of its last few
    # seconds. The writer's health is sticky, so a capture that stops shortly after
    # a reconnect ends STALE even though 110 of 118 checkpoints were HEALTHY. Both
    # are reported, and only the first can gate a phase that consumes samples.
    healthy_books = [
        key for key, entry in books.items() if entry.get("final_health") == BookHealth.HEALTHY.value
    ]
    healthy_books_at_checkpoint = sorted(
        key for key, entry in books.items() if int(entry.get("healthy", 0)) > 0
    )
    crossed = sum(int(entry.get("crossed_book_events", 0)) for entry in books.values())
    duration_minutes = float(report["capture"]["duration_seconds"] or 0.0) / 60.0
    oi_events = totals["open_interest_events"]
    oi_span_days = 0.0
    for key, entry in report["streams"].items():
        if (
            key.endswith("/open_interest")
            and entry["first_receive_time"]
            and entry["last_receive_time"]
        ):
            oi_span_days = max(
                oi_span_days,
                (entry["last_receive_time"] - entry["first_receive_time"]) / 86_400_000.0,
            )

    m03_blocking: list[str] = []
    if totals["book_update_events"] == 0:
        m03_blocking.append("no forward order-book updates captured")
    if depth_gaps:
        m03_blocking.append(f"{depth_gaps} order-book sequence gap(s) recorded in this run")
    if crossed:
        m03_blocking.append(f"{crossed} crossed-book event(s) recorded")
    if not healthy_books_at_checkpoint:
        m03_blocking.append("no book was observed HEALTHY at any checkpoint")
    if duration_minutes < M03_REQUIRED_MINUTES:
        m03_blocking.append(
            f"sample is {duration_minutes:.1f} min; "
            f"{M03_REQUIRED_MINUTES / 60:.0f} h of clean capture is the minimum to begin"
        )

    m07_blocking: list[str] = []
    if oi_events == 0:
        m07_blocking.append("no forward open-interest samples captured")
    if oi_span_days < M07_REQUIRED_DAYS:
        m07_blocking.append(
            f"forward open interest spans {oi_span_days:.3f} day(s); "
            f"{M07_REQUIRED_DAYS} day(s) are needed for a DEV/VAL/OOS split"
        )

    def verdict(blocking: list[str], infrastructure_ok: bool) -> str:
        if not infrastructure_ok:
            return "NOT_READY"
        return "READY_FOR_RESEARCH" if not blocking else "COLLECTING"

    def phase_vocabulary(infrastructure_ok: bool, blocking: list[str]) -> str:
        """§21/§22 vocabulary: infrastructure vs sample are different problems."""
        if not infrastructure_ok:
            return "NOT_READY"
        return "TECHNICALLY_READY_NEEDS_HISTORY" if blocking else "RESEARCH_READY"

    m03_infrastructure = totals["book_update_events"] > 0 and bool(healthy_books_at_checkpoint)
    m07_infrastructure = oi_events > 0
    return {
        "M-03": {
            "name": "order book imbalance",
            "verdict": verdict(m03_blocking, m03_infrastructure),
            "phase_readiness": phase_vocabulary(m03_infrastructure, m03_blocking),
            "blocking": m03_blocking,
            "available": {
                "book_update_events": totals["book_update_events"],
                "book_checkpoints": totals["book_checkpoint_events"],
                "books_healthy_at_a_checkpoint": healthy_books_at_checkpoint,
                "books_ending_healthy": sorted(healthy_books),
                "healthy_checkpoint_ratio": {
                    key: entry.get("usable_ratio") for key, entry in sorted(books.items())
                },
                "sequence_gaps": depth_gaps,
                "capture_minutes": round(duration_minutes, 3),
            },
            "requires": "forward book samples, valid book sequence, enough observations",
        },
        "M-07": {
            "name": "open interest x price",
            "verdict": verdict(m07_blocking, m07_infrastructure),
            "phase_readiness": phase_vocabulary(m07_infrastructure, m07_blocking),
            "blocking": m07_blocking,
            "available": {
                "open_interest_samples": oi_events,
                "open_interest_span_days": round(oi_span_days, 4),
                "historical_complement": (
                    "~31 days of 5m open interest exist historically and end before this "
                    "capture; the two are not contiguous, so this capture does not extend them"
                ),
            },
            "requires": "enough OI history for DEV, VAL and OOS",
        },
        "required_minimums": {
            "m03_capture_minutes": M03_REQUIRED_MINUTES,
            "m07_span_days": M07_REQUIRED_DAYS,
        },
        "vocabulary": {
            "verdict": "READY_FOR_RESEARCH | COLLECTING | NOT_READY",
            "phase_readiness": (
                "RESEARCH_READY | TECHNICALLY_READY_NEEDS_HISTORY | NOT_READY — the "
                "second means the pipeline captures what the hypothesis needs and only "
                "time is missing, which must never be read as the first"
            ),
        },
    }


def _measure_segment_sizes(root: Path) -> tuple[int, int, int]:
    """Measure stored vs uncompressed bytes straight off disk (§9, §43).

    The collector reports what it wrote; this measures what is actually there, so
    the GB/day estimate rests on the files rather than on a self-report.
    """
    stored = 0
    uncompressed = 0
    segments = 0
    for path in sorted(root.rglob("*.jsonl.gz")) + sorted(root.rglob("*.jsonl")):
        segments += 1
        stored += path.stat().st_size
        if path.suffix == ".gz":
            # Counted in blocks rather than with ``read()``: the measurement must
            # not itself need the whole segment resident.
            try:
                with gzip.open(path, "rb") as handle:
                    while True:
                        block = handle.read(4 * 1024 * 1024)
                        if not block:
                            break
                        uncompressed += len(block)
            except (EOFError, OSError, gzip.BadGzipFile):
                # The open segment's final member may still be mid-write.
                continue
        else:
            uncompressed += path.stat().st_size
    return stored, uncompressed, segments


def _free_disk_bytes(path: Path) -> int | None:
    """Free bytes on the volume holding ``path``, or ``None`` when untellable."""
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        return int(shutil.disk_usage(probe).free)
    except OSError:  # pragma: no cover - platform dependent
        return None


def _storage_capacity(base: Path, stored_bytes: int, stored_gb_per_hour: float) -> dict[str, Any]:
    """§14 — can this volume actually carry continuous collection?

    The free-disk figure is read at report time, i.e. *after* the capture, so the
    start-of-capture figure is reconstructed from it rather than claimed: the
    collector is the only writer of its own bytes, so subtracting them is sound,
    but it is still labelled a reconstruction. The collector itself never
    sampled free disk, because that would have meant touching frozen writer code
    for a number that can be recovered afterwards.
    """
    free_now = _free_disk_bytes(base)
    per_day_gb = stored_gb_per_hour * 24.0
    per_hour_bytes = stored_gb_per_hour * 1e9
    capacity_hours = (
        round(free_now / per_hour_bytes, 3) if free_now is not None and per_hour_bytes > 0 else None
    )
    capacity_days = round(capacity_hours / 24.0, 3) if capacity_hours is not None else None
    if capacity_days is None:
        verdict = "UNKNOWN"
    elif capacity_days >= STORAGE_ACCEPTABLE_DAYS:
        verdict = "STORAGE_CAPACITY_OK"
    elif capacity_days >= STORAGE_TIGHT_DAYS:
        verdict = "STORAGE_CAPACITY_TIGHT"
    else:
        verdict = "STORAGE_CAPACITY_BLOCKER"
    return {
        "free_disk_now_bytes": free_now,
        "free_disk_now_gb": round(free_now / 1e9, 3) if free_now is not None else None,
        "free_disk_at_capture_start_bytes": None,
        "free_disk_at_capture_start_reconstruction": (
            free_now + stored_bytes if free_now is not None else None
        ),
        "reconstruction_note": (
            "free disk was not sampled at capture time; the start figure is "
            "free-now plus the bytes this capture wrote, which is a reconstruction "
            "and is labelled as one"
        ),
        "stored_gb_per_day_at_observed_rate": round(per_day_gb, 3),
        "capacity_hours_at_observed_rate": capacity_hours,
        "capacity_days_at_observed_rate": capacity_days,
        "thresholds": {
            "acceptable_days": STORAGE_ACCEPTABLE_DAYS,
            "tight_days": STORAGE_TIGHT_DAYS,
        },
        "verdict": verdict,
        "verdict_meaning": (
            "STORAGE_CAPACITY_OK carries a week of headroom; TIGHT fits the week "
            "but needs attention; BLOCKER means under a day, so 24/7 collection "
            "must not be claimed on this volume"
        ),
    }


def build_resource_report(root: Path | str, run_id: str | None = None) -> dict[str, Any]:
    """§42 — the collector's measured cost, so it can be bounded against PAPER."""
    base = Path(root)
    resolved, manifest = load_run(base, run_id)
    # Only the heartbeats are needed, and there is one per cadence, so the run is
    # streamed and nothing else is retained.
    heartbeats = [
        row
        for row, _ in ForwardReplay(base, resolved).iter_rows()
        if row.get("event_type") == EventType.HEARTBEAT.value
    ]
    duration = float(manifest.get("duration_seconds") or 0.0)
    stored_bytes, uncompressed_bytes, segment_count = _measure_segment_sizes(base / "segments")
    hours = max(1e-9, duration / 3600.0)
    raw_gb_per_hour = uncompressed_bytes / hours / 1e9
    stored_gb_per_hour = stored_bytes / hours / 1e9
    memory_series = [
        float(hb["detail"]["memory_mb"])
        for hb in heartbeats
        if isinstance(hb.get("detail"), dict) and hb["detail"].get("memory_mb") is not None
    ]
    events_series = [
        float(hb["detail"]["events_per_second"])
        for hb in heartbeats
        if isinstance(hb.get("detail"), dict) and hb["detail"].get("events_per_second") is not None
    ]
    return {
        "report_version": REPORT_VERSION,
        "run_id": resolved,
        "duration_seconds": manifest.get("duration_seconds"),
        "footprint": {
            "measured_from": "segments on disk (decompressed vs stored)",
            "segments": segment_count,
            "stored_bytes": stored_bytes,
            "uncompressed_bytes": uncompressed_bytes,
            "compression_ratio": (
                round(uncompressed_bytes / stored_bytes, 3) if stored_bytes else None
            ),
            "raw_gb_per_hour": round(raw_gb_per_hour, 4),
            "stored_gb_per_hour": round(stored_gb_per_hour, 4),
            "raw_gb_per_day": round(raw_gb_per_hour * 24, 3),
            "stored_gb_per_day": round(stored_gb_per_hour * 24, 3),
            "retention_note": (
                "raw forward data is never deleted in this phase; a continuous capture "
                "needs either a larger volume or an explicit raw-short / aggregate-long "
                "retention policy before it can run for weeks"
            ),
        },
        "disk_guard": {
            "max_total_bytes": manifest.get("max_total_bytes"),
            "enabled": manifest.get("max_total_bytes") is not None,
            "stopped_on_disk_budget": bool(manifest.get("stopped_on_disk_budget")),
        },
        "storage_capacity": _storage_capacity(base, stored_bytes, stored_gb_per_hour),
        "resources": manifest.get("resources", {}),
        "heartbeats": len(heartbeats),
        "memory_mb_series": {
            "samples": len(memory_series),
            "max": max(memory_series) if memory_series else None,
            "p95": percentile(memory_series, 0.95),
        },
        "events_per_second_series": {
            "samples": len(events_series),
            "p50": percentile(events_series, 0.50),
            "p95": percentile(events_series, 0.95),
            "max": max(events_series) if events_series else None,
        },
        "state_history": manifest.get("degradation_events", []),
        "isolation": {
            "process_separate_from_paper_runtime": True,
            "shared_mutable_state_with_trading_runtime": False,
            "opens_orders_or_private_endpoints": False,
            "imports_trading_decision_modules": False,
            "note": (
                "the collector writes append-only JSONL under reports/microstructure-forward/ "
                "and touches no trading module; it cannot change a decision, a risk check or "
                "an execution path"
            ),
        },
    }


def build_daily_report(
    root: Path | str,
    run_id: str | None = None,
    *,
    quality: dict[str, Any] | None = None,
    resource: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """§48 — the compact daily artifact: coverage, quality, gaps, hashes, health.

    ``quality`` and ``resource`` may be supplied by the caller so one run is not
    parsed twice; on a multi-hour capture that is the difference between minutes
    and another full scan.
    """
    base = Path(root)
    resolved, manifest = load_run(base, run_id)
    quality = quality or build_quality_report(base, resolved)
    resource = resource or build_resource_report(base, resolved)
    return {
        "report_version": REPORT_VERSION,
        "kind": "FORWARD_DATA_DAILY_REPORT",
        "run_id": resolved,
        "generated_from": "manifest + persisted segments (offline)",
        "coverage": {
            "started_at": manifest.get("started_at"),
            "ended_at": manifest.get("ended_at"),
            "duration_seconds": manifest.get("duration_seconds"),
            "continuity": manifest.get("continuity"),
            "streams_with_data": sorted(
                key for key, entry in quality["streams"].items() if entry["events"] > 0
            ),
            "streams_without_data": sorted(
                key for key, entry in quality["streams"].items() if entry["events"] == 0
            ),
        },
        "quality": {
            "events": quality["totals"]["events"],
            "duplicates": quality["loss"]["duplicates"],
            "out_of_order": quality["loss"]["out_of_order"],
            "sequence_gaps": quality["loss"]["sequence_gaps"],
            "gaps_total": quality["loss"]["gaps_total"],
            "gaps_data_lost": quality["loss"]["gaps_data_lost"],
            "event_latency_ms": quality["event_latency_ms"],
            "books": {
                key: {
                    "final_health": entry.get("final_health"),
                    "usable_ratio": entry.get("usable_ratio"),
                }
                for key, entry in quality["books"].items()
            },
        },
        "files": {
            "segments": quality["fingerprints"]["segments"],
            "rows": quality["fingerprints"]["rows"],
            "bytes": quality["fingerprints"]["bytes"],
            "hashes": {f["path"]: f["sha256"] for f in manifest.get("fingerprints", [])},
        },
        "resource_health": {
            "cpu_utilisation": resource["resources"].get("cpu_utilisation"),
            "memory_mb_max": resource["resources"].get("memory_mb_max"),
            "disk_bytes_per_hour": resource["resources"].get("disk_bytes_per_hour"),
            "state": resource["state_history"][-1]["to"]
            if resource["state_history"]
            else "HEALTHY",
        },
        "readiness": quality["readiness"],
    }


def write_machine_readable_reports(
    root: Path | str,
    out_dir: Path | str,
    run_id: str | None = None,
    *,
    quality: dict[str, Any] | None = None,
    resource: dict[str, Any] | None = None,
    daily: dict[str, Any] | None = None,
    replay: ReplayVerification | None = None,
) -> dict[str, Path]:
    """Write the JSON artifacts that later phases must be able to cite.

    Each section is a streaming pass over the capture, and this used to rebuild
    every one of them even when its caller had just built it: on an hour of data
    that was two extra full scans of the dataset to write a file. Anything handed
    in is used as given, so a caller that already holds a section pays for it once.
    """
    base = Path(root)
    resolved, manifest = load_run(base, run_id)
    target = Path(out_dir)
    if quality is None:
        quality = build_quality_report(base, resolved)
    if resource is None:
        resource = build_resource_report(base, resolved)
    if daily is None:
        daily = build_daily_report(base, resolved, quality=quality, resource=resource)
    if replay is None:
        replay = replay_microstructure_dataset(base, resolved)
    files = {
        "quality": target / "FORWARD_DATA_QUALITY_REPORT.json",
        "contract": target / "FORWARD_DATA_CONTRACT.json",
        "evidence": target / "FORWARD_DATA_EVIDENCE.json",
        "resource": target / "FORWARD_DATA_RESOURCE_REPORT.json",
        "daily": target / "FORWARD_DATA_DAILY_REPORT.json",
        "replay": target / "FORWARD_DATA_REPLAY_VALIDATION.json",
    }
    save_json(files["contract"], build_contract_document())
    save_json(
        files["quality"],
        {
            "report_version": REPORT_VERSION,
            "run_id": resolved,
            "contract_version": manifest.get("contract_version"),
            "collector_version": manifest.get("collector_version"),
            "commit": manifest.get("commit"),
            "capture": quality["capture"],
            "continuity": quality["continuity"],
            "provider_stream_status": quality["provider_stream_status"],
            "streams": quality["streams"],
            "totals": quality["totals"],
            "loss": quality["loss"],
            "event_latency_ms": quality["event_latency_ms"],
            "books": quality["books"],
            "health": quality["health"],
            "fingerprints": quality["fingerprints"],
            "readiness": quality["readiness"],
            "cases": quality["cases"],
            "artifact_digests": {
                "aggregation": load_json(base / "aggregation" / f"{resolved}.json")["digest"]
                if (base / "aggregation" / f"{resolved}.json").exists()
                else None
            },
        },
    )
    save_json(
        files["evidence"],
        {
            "run_id": resolved,
            "manifest": manifest,
            "raw_root": str(base),
        },
    )
    save_json(files["resource"], resource)
    save_json(files["daily"], daily)
    save_json(files["replay"], replay.as_dict())
    return files
