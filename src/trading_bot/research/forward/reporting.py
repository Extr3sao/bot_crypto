"""Forward dataset reporting: quality, books, resources, daily (§42-§49).

Every number here comes from the capture itself — the manifest for structure and
the persisted rows for latency, health tallies and readiness. Nothing is
estimated, and nothing is rounded up into a claim: readiness verdicts are
``READY_FOR_RESEARCH`` / ``COLLECTING`` / ``NOT_READY``, never a profitability
statement.
"""

from __future__ import annotations

import gzip
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from trading_bot.research.forward.aggregation import DatasetAggregation, aggregate_dataset
from trading_bot.research.forward.contract import BACKFILL_ORIGIN, EventType, parse_event
from trading_bot.research.forward.orderbook import BookHealth
from trading_bot.research.forward.replay import (
    ForwardReplay,
    aggregation_digest,
    replay_microstructure_dataset,
)
from trading_bot.research.forward.resources import percentile
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
    "build_quality_report",
    "build_readiness",
    "build_resource_report",
    "load_run",
    "save_aggregation",
    "write_machine_readable_reports",
]

REPORT_VERSION: Final[str] = "FORWARD-REPORT-V1"

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
    """Rebuild the full raw -> 1m -> 5m/15m/30m aggregation from persisted rows."""
    base = Path(root)
    resolved, _manifest = load_run(base, run_id)
    replay = ForwardReplay(base, resolved)
    rows, _ = replay.load_rows()
    events = [parse_event(row) for row in rows]
    loss_windows, window = replay.capture_bounds_from_manifest()
    aggregation = aggregate_dataset(
        events, run_id=resolved, loss_windows=loss_windows, window=window
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
    delays: list[int] = field(default_factory=list)
    process_before_receive: int = 0
    event_after_receive: int = 0
    duplicate_ids: int = 0
    out_of_order_ids: int = 0
    backfilled_events: int = 0
    first_receive: int | None = None
    last_receive: int | None = None


def _scan_rows(rows: list[dict[str, Any]]) -> dict[str, _StreamScan]:
    scans: dict[str, _StreamScan] = defaultdict(_StreamScan)
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
                scan.delays.append(receive - event_time)
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
    return scans


def build_book_report(rows: list[dict[str, Any]], manifest: dict[str, Any]) -> dict[str, Any]:
    """§45 — everything a consumer must know before trusting a book."""
    checkpoints: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("event_type") != EventType.BOOK_CHECKPOINT.value:
            continue
        detail = row.get("detail") or {}
        checkpoints[f"{row.get('market')}/{row.get('symbol')}"].append(detail)
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


def build_quality_report(root: Path | str, run_id: str | None = None) -> dict[str, Any]:
    """§44/§45 — per-stream event, loss, latency and book quality."""
    base = Path(root)
    resolved, manifest = load_run(base, run_id)
    rows, partial_tails = ForwardReplay(base, resolved).load_rows()
    scans = _scan_rows(rows)

    streams: dict[str, Any] = {}
    for stream in manifest.get("streams", []):
        key = f"{stream['market']}/{stream['symbol']}/{stream['event_type']}"
        scan = scans.get(key, _StreamScan())
        delays = scan.delays
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
                "p50": percentile([float(d) for d in delays], 0.50),
                "p95": percentile([float(d) for d in delays], 0.95),
                "p99": percentile([float(d) for d in delays], 0.99),
                "max": max(delays) if delays else None,
                "min": min(delays) if delays else None,
                "samples": len(delays),
            },
            "process_before_receive": scan.process_before_receive,
            "event_after_receive": scan.event_after_receive,
        }

    all_delays = [float(d) for scan in scans.values() for d in scan.delays]
    gaps = manifest.get("gaps", [])
    by_reason: dict[str, int] = defaultdict(int)
    for gap in gaps:
        by_reason[str(gap["reason"])] += 1
    integrity = manifest.get("integrity", {})
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
            "rows_on_disk": len(rows),
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
            "gaps_recovered": integrity.get("recovered_gaps", 0),
            "gaps_by_status": integrity.get("gaps_by_status", {}),
            "backfilled_events": integrity.get("backfilled_events", 0),
            "backfill_gaps_closed": integrity.get("backfill_gaps_closed", 0),
            "backfill_partial": integrity.get("backfill_partial", 0),
            "backfill_failures": integrity.get("backfill_failures", 0),
            "backfill_deferred": integrity.get("backfill_deferred", 0),
            "remaining_missing_events": integrity.get("remaining_missing_events", 0),
            "data_lost_gap_seconds": integrity.get("data_lost_gap_seconds", 0.0),
            "gaps_by_reason": dict(sorted(by_reason.items())),
            "malformed": integrity.get("malformed", 0),
            "clock_violations": integrity.get("clock_violations", 0),
            "max_clock_skew_ms": integrity.get("max_clock_skew_ms", 0),
            "reconnects": manifest.get("reconnects", 0),
            "resnapshots": manifest.get("resnapshots", 0),
            "resnapshots_failed": integrity.get("resnapshots_failed", 0),
        },
        "event_latency_ms": {
            "p50": percentile(all_delays, 0.50),
            "p95": percentile(all_delays, 0.95),
            "p99": percentile(all_delays, 0.99),
            "max": max(all_delays) if all_delays else None,
            "samples": len(all_delays),
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
        "books": build_book_report(rows, manifest),
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
    report["readiness"] = build_readiness(report, manifest)
    return report


def build_readiness(report: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    """§46/§49 — what M-03 and M-07 still need, stated as gaps not as hopes."""
    totals = report["totals"]
    books = report["books"]
    depth_gaps = sum(
        s["sequence_gaps"] for k, s in report["streams"].items() if k.endswith("/depth_diff")
    )
    healthy_books = [
        key for key, entry in books.items() if entry.get("final_health") == BookHealth.HEALTHY.value
    ]
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
    if not healthy_books:
        m03_blocking.append("no book reached HEALTHY")
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

    return {
        "M-03": {
            "name": "order book imbalance",
            "verdict": verdict(
                m03_blocking, totals["book_update_events"] > 0 and bool(healthy_books)
            ),
            "blocking": m03_blocking,
            "available": {
                "book_update_events": totals["book_update_events"],
                "book_checkpoints": totals["book_checkpoint_events"],
                "healthy_books": sorted(healthy_books),
                "sequence_gaps": depth_gaps,
                "capture_minutes": round(duration_minutes, 3),
            },
            "requires": "forward book samples, valid book sequence, enough observations",
        },
        "M-07": {
            "name": "open interest x price",
            "verdict": verdict(m07_blocking, oi_events > 0),
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
            try:
                with gzip.open(path, "rb") as handle:
                    uncompressed += len(handle.read())
            except (EOFError, OSError, gzip.BadGzipFile):
                # The open segment's final member may still be mid-write.
                continue
        else:
            uncompressed += path.stat().st_size
    return stored, uncompressed, segments


def build_resource_report(root: Path | str, run_id: str | None = None) -> dict[str, Any]:
    """§42 — the collector's measured cost, so it can be bounded against PAPER."""
    base = Path(root)
    resolved, manifest = load_run(base, run_id)
    rows, _ = ForwardReplay(base, resolved).load_rows()
    duration = float(manifest.get("duration_seconds") or 0.0)
    stored_bytes, uncompressed_bytes, segment_count = _measure_segment_sizes(base / "segments")
    hours = max(1e-9, duration / 3600.0)
    raw_gb_per_hour = uncompressed_bytes / hours / 1e9
    stored_gb_per_hour = stored_bytes / hours / 1e9
    heartbeats = [row for row in rows if row.get("event_type") == EventType.HEARTBEAT.value]
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
            "stopped_on_budget": bool(manifest.get("stopped_on_disk_budget")),
        },
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


def build_daily_report(root: Path | str, run_id: str | None = None) -> dict[str, Any]:
    """§48 — the compact daily artifact: coverage, quality, gaps, hashes, health."""
    base = Path(root)
    resolved, manifest = load_run(base, run_id)
    quality = build_quality_report(base, resolved)
    resource = build_resource_report(base, resolved)
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
    root: Path | str, out_dir: Path | str, run_id: str | None = None
) -> dict[str, Path]:
    """Write the JSON artifacts that later phases must be able to cite."""
    base = Path(root)
    resolved, manifest = load_run(base, run_id)
    target = Path(out_dir)
    quality = build_quality_report(base, resolved)
    resource = build_resource_report(base, resolved)
    daily = build_daily_report(base, resolved)
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
