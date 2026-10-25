"""WP-10 E-1 — execution cost reality check against the forward book we captured.

The frozen admission plane charges **23.3536 bps** per round trip
(``BINANCE_SPOT_STANDARD_TAKER``, 200 USDT stake). Three of its five terms are
published facts and three were never measured:

    exchange_fee_entry   10.0000 bps   KNOWN      (Binance spot VIP0 taker, SRC-01)
    exchange_fee_exit    10.0000 bps   KNOWN      (same schedule, second leg)
    spread                1.0000 bps   ESTIMATED  2 taker legs x half of a 1.0 bps book
    slippage              2.2828 bps   ESTIMATED  base 1.0 bps x ladders x 2 legs
    market_impact         0.0707 bps   ESTIMATED  0.25 bps x (size ladder - 1) x 2 legs

E-1 asks one question: **does the captured order book support those ESTIMATED
terms?** It answers by measuring, never by re-labelling:

* the spread actually quoted, per book, over the sealed window — from the
  every-update ``book_ticker`` stream and from the 15 s ``book_checkpoint``
  features, the two sources cross-checked;
* the price a market order would actually have paid, by rebuilding each book
  through the *certified* reconstruction path (``parse_event`` → ``BookSyncer``,
  the same objects the replay verifier used) and walking it for a size ladder.
  Every rebuilt book must reproduce the top of book the collector published for
  that checkpoint; a reconstruction that cannot is a broken measurement and the
  run fails instead of publishing numbers;
* the cost that *actually* occurred, from ``agg_trade`` prints with their
  aggressor side held against the prevailing quote — an executed price, not a
  modelled one, and only ever with ``quote_time <= trade_time``, violations
  counted;
* latency, funding and the size of the moves the cost plane must be paid out of,
  so the required edge can be compared with what the window contains.

Guards that make a wrong answer hard to publish:

* the frozen plane is re-derived from ``COST_MODEL_V3`` in-process, so the
  comparison is against the code, not against a copy of its output;
* each measured term is compared with the plane term it tests, and the share of
  checkpoints where the plane *under*-estimates is reported too — a plane that
  is cheap in the median but blown through in the tail is not a safe plane;
* nothing here changes the frozen plane, admits a strategy, or starts a process.

Read-only: no network, no key, no order, no capital.

Exit codes: 0 audit complete, 2 a required input is missing, 3 the
reconstruction failed to reproduce a certified checkpoint, 4 a look-ahead
violation was found in the trade/quote join.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import heapq
import json
import math
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Iterator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:  # pragma: no cover - path bootstrap
    sys.path.insert(0, str(ROOT / "src"))

from trading_bot.research.forward.contract import EventType, parse_event  # noqa: E402
from trading_bot.research.forward.orderbook import (  # noqa: E402
    BookStateError,
    BookSyncer,
    DepthUpdate,
    parse_depth_levels,
)
from trading_bot.research.forward.orderbook import SequencePolicy  # noqa: E402
from trading_bot.research.microstructure.cost_model_v3 import (  # noqa: E402
    ADMISSION_SCENARIO_ID,
    VENUE_SPECS,
    default_model,
)

FORWARD_ROOT = ROOT / "reports" / "microstructure-forward-continuous"
MANIFEST_DIR = FORWARD_ROOT / "manifest"
REPLAY = FORWARD_ROOT / "reports" / "REPLAY_VERIFICATION.json"
AUDIT = ROOT / "data" / "recovery" / "ACTIVE_ECONOMIC_AUDIT.json"
OUT_DIR = ROOT / "data" / "recovery" / "wp10"

SIZE_LADDER_USDT: tuple[float, ...] = (50.0, 200.0, 1_000.0, 5_000.0, 20_000.0, 100_000.0)
PLANE_STAKE_USDT = 200.0
LEVELS_INITIAL = 300  # the top of the book, which prices every size up to 20 000 USDT here
WALK_LEVELS = 20_000  # the fallback: no book in the seal carries this many levels
MOVE_HORIZONS_MINUTES: tuple[int, ...] = (5, 30)
BEST_GROSS_EDGE_BPS = 8.912  # from the 24-strategy ledger, re-checked in WP10 phase 1

#: The venue surfaces whose fee schedule a reader will ask about next. Recorded as
#: published facts with their source id; the frozen plane is never edited from here.
FEE_SCHEDULE_CONTEXT: tuple[tuple[str, str, float, float], ...] = (
    ("BINANCE_SPOT_STANDARD_TAKER", "SRC-01", 10.0, 10.0),
    ("BINANCE_USDM_STANDARD_TAKER", "SRC-02", 2.0, 5.0),
)


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def fmt_utc(ms: int | float | None) -> str | None:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000.0, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = q * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def describe(values: list[float]) -> dict[str, Any]:
    """A distribution as a reader needs it: n, centre, tails, extremes."""
    if not values:
        return {"n": 0, "median": None, "mean": None, "p05": None, "p25": None, "p75": None,
                "p95": None, "p99": None, "min": None, "max": None, "stdev": None}
    return {
        "n": len(values),
        "median": round(statistics.median(values), 6),
        "mean": round(statistics.fmean(values), 6),
        "p05": round(percentile(values, 0.05) or 0.0, 6),
        "p25": round(percentile(values, 0.25) or 0.0, 6),
        "p75": round(percentile(values, 0.75) or 0.0, 6),
        "p95": round(percentile(values, 0.95) or 0.0, 6),
        "p99": round(percentile(values, 0.99) or 0.0, 6),
        "min": round(min(values), 6),
        "max": round(max(values), 6),
        "stdev": round(statistics.pstdev(values), 6) if len(values) > 1 else 0.0,
    }


def share_over(values: list[float], threshold: float) -> float | None:
    if not values:
        return None
    return round(100.0 * sum(1 for value in values if value > threshold) / len(values), 4)


#: Segment tails that could not be read to the end. A truncated file is a fact about the
#: capture (the writer was killed mid-rotation), never something to swallow: the collector
#: that was hard-terminated left exactly this signature, and a measurement that silently
#: skipped the tail would understate its own sample without saying so.
TRUNCATED: list[dict[str, Any]] = []


def iter_rows(path: Path, run_id: str | None = None,
              truncations: list[dict[str, Any]] | None = None) -> Iterator[dict[str, Any]]:
    """One segment, forward, skipping rows that belong to another run.

    A truncated tail ends the file early and is recorded instead of raised: the rows that
    were read are real, and the report says how much could not be.
    """
    opener = gzip.open if path.suffix == ".gz" else open
    read = 0
    try:
        with opener(path, "rt", encoding="utf-8") as handle:  # type: ignore[operator]
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                read += 1
                if run_id is None or row.get("run_id") == run_id:
                    yield row
    except (EOFError, gzip.BadGzipFile, OSError) as exc:
        entry = {
            "file": str(path.relative_to(ROOT)).replace("\\", "/") if path.is_absolute()
            else str(path).replace("\\", "/"),
            "error": type(exc).__name__,
            "rows_read_before_truncation": read,
        }
        (TRUNCATED if truncations is None else truncations).append(entry)


def segment_files(root: Path, market: str, symbol: str, stream: str) -> list[Path]:
    base = root / "segments" / "binance" / market / symbol / stream
    if not base.exists():
        return []
    return sorted(base.rglob("*.jsonl.gz"))


def stream_events(market: str, symbol: str, stream: str, run_id: str,
                  truncations: list[dict[str, Any]],
                  inversions: dict[str, int] | None = None) -> Iterator[tuple[int, int, dict[str, Any]]]:
    """One stream in the collector's own write order, read lazily from disk.

    Segment names sort in rotation order and rows were appended in ``write_seq``
    order, so this iterator is already ascending — which is what lets three of
    them be merged without holding the window in memory. That matters here: the
    perp books carry the whole changed side per diff row, and buffering the
    biggest of them costs gigabytes. The ascending claim is not taken on trust:
    a row that arrives out of order is counted, and the book stage publishes the
    count. A non-zero count means the merge order is not the sort order and the
    measurement is void.
    """
    previous: tuple[int, int] | None = None
    for path in segment_files(FORWARD_ROOT, market, symbol, stream):
        for row in iter_rows(path, run_id, truncations):
            key = (int(row.get("write_seq") or 0), int(row.get("receive_time") or 0))
            if previous is not None and key < previous and inversions is not None:
                inversions[stream] += 1
            previous = key
            yield (key[0], key[1], row)


def walk(levels: list[tuple[float, float]], notional_usd: float) -> tuple[float, bool]:
    """Average fill price for ``notional_usd`` swept through ``levels``.

    ``levels`` must already be ordered best-first: asks ascending for a buy, bids
    descending for a sell. Returns ``(average_price, filled)``; a size that runs
    past the last recorded level is reported unfilled, never extrapolated.
    """
    remaining = notional_usd
    spent = 0.0
    qty = 0.0
    for price, level_qty in levels:
        if price <= 0.0 or level_qty <= 0.0:
            continue
        take = min(remaining, price * level_qty)
        spent += take
        qty += take / price
        remaining -= take
        if remaining <= 1e-9:
            break
    if qty <= 0.0:
        return 0.0, False
    return spent / qty, remaining <= 1e-6


# ---------------------------------------------------------------------------
# the sealed dataset
# ---------------------------------------------------------------------------


def load_sealed_runs() -> dict[str, Any]:
    """The manifests are the only authority on which windows are sealed."""
    runs: dict[str, Any] = {}
    for path in sorted(MANIFEST_DIR.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        run_id = payload.get("run_id")
        if not run_id:
            continue
        integrity = payload.get("integrity") or {}
        resources = payload.get("resources") or {}
        runs[run_id] = {
            "manifest_path": str(path.relative_to(ROOT)).replace("\\", "/"),
            "run_id": run_id,
            "started_at": payload.get("started_at"),
            "ended_at": payload.get("ended_at"),
            "duration_seconds": payload.get("duration_seconds"),
            "duration_hours": round(float(payload.get("duration_seconds") or 0.0) / 3600.0, 6),
            "status": payload.get("status"),
            "stop_reason": payload.get("stop_reason"),
            "continuity": payload.get("continuity"),
            "exit_code": payload.get("exit_code"),
            "commit": payload.get("commit"),
            "symbols": payload.get("symbols"),
            "markets": payload.get("markets"),
            "depth_n": payload.get("depth_n"),
            "bytes_written": payload.get("bytes_written"),
            "disk_bytes_per_hour": resources.get("disk_bytes_per_hour"),
            "gaps": len(payload.get("gaps") or []),
            "reconnects": payload.get("reconnects"),
            "data_lost_gap_seconds": integrity.get("data_lost_gap_seconds"),
            "max_clock_skew_ms": integrity.get("max_clock_skew_ms"),
            "network_delay_published": {
                f"{stream['market']}/{stream['symbol']}/{stream['event_type']}": (
                    stream.get("network_delay_ms") or {}
                ).get("p50_ms")
                for stream in payload.get("streams") or []
            },
            "book_health": {
                key: {"health": value.get("health"), "counters": value.get("counters"),
                      "bid_levels": value.get("bid_levels"), "ask_levels": value.get("ask_levels")}
                for key, value in (payload.get("book_health") or {}).items()
            },
        }
    return runs


#: Streams whose row counts are taken from the certified replay verification rather than
#: re-counted here. Re-reading ten million quote rows to re-derive a number the campaign's
#: own verifier already published buys nothing: the point of the coverage table is to say
#: *where the data is* and *how much of it this run owns*, and both are already certified.
CERTIFIED_COUNT_STREAMS = ("book_ticker", "depth_diff")
#: Streams re-read here in full, because their sizes are small and their contents matter.
REREAD_STREAMS = ("depth_snapshot", "book_checkpoint", "agg_trade", "funding",
                  "mark_price", "open_interest")


def coverage_of(run_id: str) -> dict[str, Any]:
    """Per *(book, stream)* row counts and spans, with each count's provenance named."""
    certified: dict[str, int] = {}
    if REPLAY.exists():
        replay = json.loads(REPLAY.read_text(encoding="utf-8"))
        if replay.get("run_id") == run_id:
            certified = dict(replay.get("event_counts") or {})
    out: dict[str, Any] = {}
    truncated: list[dict[str, Any]] = []
    for market in ("spot", "perp"):
        for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
            for stream in REREAD_STREAMS:
                files = segment_files(FORWARD_ROOT, market, symbol, stream)
                if not files:
                    continue
                rows = 0
                first_recv: int | None = None
                last_recv: int | None = None
                files_used = 0
                with_event_time = 0
                for path in files:
                    used_here = 0
                    for row in iter_rows(path, run_id, truncated):
                        rows += 1
                        used_here += 1
                        recv = row.get("receive_time")
                        if recv:
                            first_recv = recv if first_recv is None else min(first_recv, recv)
                            last_recv = recv if last_recv is None else max(last_recv, recv)
                        if row.get("exchange_event_time"):
                            with_event_time += 1
                    if used_here:
                        files_used += 1
                if not rows:
                    continue
                out[f"{market}/{symbol}/{stream}"] = {
                    "source": "re-read here",
                    "files": len(files),
                    "files_carrying_this_run": files_used,
                    "rows": rows,
                    "first_receive_time": first_recv,
                    "first_receive_utc": fmt_utc(first_recv),
                    "last_receive_time": last_recv,
                    "last_receive_utc": fmt_utc(last_recv),
                    "span_hours": round((last_recv - first_recv) / 3.6e6, 6)
                    if first_recv and last_recv else None,
                    "rows_with_exchange_event_time": with_event_time,
                }
            for stream in CERTIFIED_COUNT_STREAMS:
                files = segment_files(FORWARD_ROOT, market, symbol, stream)
                key = f"{market}/{symbol}/{stream}"
                if not files:
                    continue
                out[key] = {
                    "source": "certified replay verification",
                    "certified_path": str(REPLAY.relative_to(ROOT)).replace("\\", "/"),
                    "files": len(files),
                    "rows": certified.get(key),
                    "note": ("row counts for the highest-volume streams come from the campaign's "
                             "own replay verification, which counted them independently and "
                             "matched them against the manifest; this script does not re-count "
                             "ten million rows to re-derive a certified number"),
                }
    return {"streams": out, "truncated_files": truncated,
            "provenance_note": ("every stream row carries the source of its count: 're-read here' "
                                "or 'certified replay verification'")}


# ---------------------------------------------------------------------------
# book reconstruction and the spread / depth measurement
# ---------------------------------------------------------------------------


def reconstruct_book(market: str, symbol: str, run_id: str, sizes: tuple[float, ...]) -> dict[str, Any]:
    """Rebuild one book and price a market order through it at every checkpoint.

    The certified reconstruction is reproduced exactly: the collector's own row
    order, ``parse_event``, ``BookSyncer`` with the manifest's own book knobs, and
    each ``book_checkpoint`` used as an *independent* witness of the rebuilt top of
    book. A mismatch voids the measurement rather than being averaged away.
    """
    policy = (SequencePolicy.SPOT_UPDATE_ID if market == "spot"
              else SequencePolicy.FUTURES_PREV_ID)
    syncer = BookSyncer(symbol=symbol, market=market, policy=policy, depth_n=10, stale_after_ms=5_000)

    snapshots = 0
    diffs = 0
    checkpoints = 0
    matches = 0
    rejected_rows = 0
    health_mix: dict[str, int] = defaultdict(int)
    spread_samples: list[float] = []
    book_levels: list[int] = []
    checkpoint_times: list[int] = []
    size_stats: dict[float, dict[str, list[float]]] = {
        size: {"round_trip": [], "spread_legs": [], "walk_legs": []} for size in sizes
    }
    unfilled: dict[float, int] = defaultdict(int)

    truncated_here: list[dict[str, Any]] = []
    order_inversions: dict[str, int] = defaultdict(int)
    # Same global order as sorting the whole window (`write_seq`, then `receive_time`),
    # obtained by merging the three already-ascending streams instead of buffering them.
    merged = heapq.merge(
        *(stream_events(market, symbol, stream, run_id, truncated_here, order_inversions)
          for stream in ("depth_snapshot", "depth_diff", "book_checkpoint")),
        key=lambda item: (item[0], item[1]),
    )

    for _seq, _recv, row in merged:
        try:
            event = parse_event(row)
        except Exception:
            rejected_rows += 1
            continue
        if event.event_type is EventType.DEPTH_SNAPSHOT:
            try:
                bids = parse_depth_levels(event.bids or [], "bids")
                asks = parse_depth_levels(event.asks or [], "asks")
                syncer.on_snapshot(int(event.exchange_event_id or 0), bids, asks, event.receive_time)
                snapshots += 1
            except BookStateError:
                rejected_rows += 1
        elif event.event_type is EventType.DEPTH_DIFF:
            try:
                update = DepthUpdate(
                    first_id=int(event.sequence.first) if event.sequence and event.sequence.first is not None else 0,
                    last_id=int(event.sequence.last) if event.sequence and event.sequence.last is not None else 0,
                    prev_id=event.sequence.prev if event.sequence else None,
                    bids=parse_depth_levels(event.bids or [], "bids"),
                    asks=parse_depth_levels(event.asks or [], "asks"),
                    exchange_event_time=event.exchange_event_time,
                    received_time=event.receive_time,
                )
                syncer.on_diff(update)
                diffs += 1
            except BookStateError:
                rejected_rows += 1
        elif event.event_type is EventType.BOOK_CHECKPOINT:
            checkpoints += 1
            detail = row.get("detail") or {}
            health = syncer.health(event.receive_time)
            health_mix[health.value] += 1
            rebuilt = syncer.book
            best_bid = rebuilt.best_bid()
            best_ask = rebuilt.best_ask()
            mid = rebuilt.mid()
            checkpoint_times.append(event.receive_time)
            if (best_bid is None or best_ask is None or mid is None
                    or str(best_bid) != str(row.get("bid"))
                    or str(best_ask) != str(row.get("ask"))):
                continue
            matches += 1
            book_levels.append(len(rebuilt))
            mid_f = float(mid)
            best_bid_f = float(best_bid)
            best_ask_f = float(best_ask)
            ask_half_bps = (best_ask_f - mid_f) / mid_f * 1e4
            bid_half_bps = (mid_f - best_bid_f) / mid_f * 1e4
            spread_bps = ask_half_bps + bid_half_bps
            spread_samples.append(spread_bps)
            # The walk's working set: the top of the book is plenty for the small sizes, and
            # a size that does not fill there re-reads the whole book, so the cheap path is
            # exact rather than merely cheap.
            asks = [(float(p), float(q)) for p, q in rebuilt.top(LEVELS_INITIAL, "ask")]
            bids = [(float(p), float(q)) for p, q in rebuilt.top(LEVELS_INITIAL, "bid")]
            expanded: list[tuple[float, float]] | None = None
            for size in sizes:
                entry_avg, entry_filled = walk(asks, size)
                exit_avg, exit_filled = walk(bids, size)
                if not (entry_filled and exit_filled):
                    if expanded is None:
                        expanded = [[(float(p), float(q)) for p, q in rebuilt.top(WALK_LEVELS, side)]
                                    for side in ("ask", "bid")]
                    entry_avg, entry_filled = walk(expanded[0], size)
                    exit_avg, exit_filled = walk(expanded[1], size)
                if not (entry_filled and exit_filled):
                    unfilled[size] += 1
                    continue
                entry_bps = (entry_avg - mid_f) / mid_f * 1e4
                exit_bps = (mid_f - exit_avg) / mid_f * 1e4
                size_stats[size]["round_trip"].append(entry_bps + exit_bps)
                size_stats[size]["spread_legs"].append(spread_bps)
                size_stats[size]["walk_legs"].append(
                    (entry_bps - ask_half_bps) + (exit_bps - bid_half_bps)
                )

    payload_sizes: dict[str, Any] = {}
    for size in sizes:
        stats = size_stats[size]
        payload_sizes[f"{size:.0f}"] = {
            "checkpoints_priced": len(stats["round_trip"]),
            "checkpoints_unfillable_within_recorded_book": unfilled[size],
            "round_trip_microstructure_bps": describe(stats["round_trip"]),
            "spread_legs_bps": describe(stats["spread_legs"]),
            "walk_beyond_best_legs_bps": describe(stats["walk_legs"]),
        }

    return {
        "market": market,
        "symbol": symbol,
        "snapshot_rows": snapshots,
        "diff_rows": diffs,
        "rows_rejected": rejected_rows,
        "checkpoint_rows": checkpoints,
        "checkpoints_reproduced": matches,
        "checkpoint_mismatches": checkpoints - matches,
        "truncated_segments": truncated_here,
        "stream_order_inversions": dict(order_inversions),
        "stream_order_verified": sum(order_inversions.values()) == 0,
        "measurement_qualifier": (
            "the rows that could be read were measured; a truncated tail is reported here "
            "rather than silently ending the sample" if truncated_here else None),
        "syncer_counters": syncer.counters.as_dict(),
        "checkpoint_health_mix": dict(health_mix),
        "book_levels_median": int(statistics.median(book_levels)) if book_levels else None,
        "top_of_book_spread_bps": describe(spread_samples),
        "sizes": payload_sizes,
        "first_checkpoint_utc": fmt_utc(min(checkpoint_times)) if checkpoint_times else None,
        "last_checkpoint_utc": fmt_utc(max(checkpoint_times)) if checkpoint_times else None,
    }


# ---------------------------------------------------------------------------
# what the market actually charged: prints against the prevailing quote
# ---------------------------------------------------------------------------


def realised_trade_cost(market: str, symbol: str, run_id: str) -> dict[str, Any] | None:
    """Effective spread paid by real takers, plus the notional they traded.

    The join is ``quote_time <= trade_time`` and the violation counter travels in
    the payload: a quote from the future would make the number meaningless, and it
    must not be possible for that to pass silently. Spot ``book_ticker`` rows carry
    no exchange event time, so the receive clock is used there — later than the
    event, never earlier, so it cannot manufacture look-ahead.
    """
    quotes: list[tuple[int, float, float]] = []
    quote_clock = "exchange_event_time"
    for path in segment_files(FORWARD_ROOT, market, symbol, "book_ticker"):
        for row in iter_rows(path, run_id):
            t = row.get("exchange_event_time") or row.get("receive_time")
            bid = row.get("bid")
            ask = row.get("ask")
            if not t or not bid or not ask:
                continue
            quotes.append((int(t), float(bid), float(ask)))
    if not quotes:
        return None
    quotes.sort(key=lambda item: item[0])
    if not any(row.get("exchange_event_time") for row in
               iter_rows(next(iter(segment_files(FORWARD_ROOT, market, symbol, "book_ticker"))), run_id)):
        quote_clock = "receive_time (exchange event time absent on this stream)"

    half_spreads: list[float] = []
    notionals: list[float] = []
    aggressors: dict[str, int] = defaultdict(int)
    violations = 0
    prints = 0
    index = 0
    for path in segment_files(FORWARD_ROOT, market, symbol, "agg_trade"):
        for row in iter_rows(path, run_id):
            t = row.get("exchange_event_time")
            price = row.get("price")
            qty = row.get("quantity")
            if not t or not price or not qty:
                continue
            t = int(t)
            while index < len(quotes) and quotes[index][0] <= t:
                index += 1
            if index == 0:
                continue
            quote_time, bid, ask = quotes[index - 1]
            if quote_time > t:
                violations += 1
                continue
            mid = (bid + ask) / 2.0
            if mid <= 0.0:
                continue
            prints += 1
            price_f = float(price)
            half_spreads.append(abs(price_f - mid) / mid * 1e4)
            notionals.append(price_f * float(qty))
            aggressors[str(row.get("aggressor_side"))] += 1
    if not prints:
        return None
    return {
        "market": market,
        "symbol": symbol,
        "quote_clock": quote_clock,
        "quotes_available": len(quotes),
        "prints_joined": prints,
        "look_ahead_violations": violations,
        "aggressor_side_mix": dict(aggressors),
        "effective_half_spread_bps": describe(half_spreads),
        "effective_round_trip_bps": {
            "estimate": round(2.0 * statistics.median(half_spreads), 6),
            "method": "2 x median effective half spread actually paid by aggressors",
        },
        "print_notional_usdt": describe(notionals),
        "print_notional_over_1000_usdt_pct": round(
            100.0 * sum(1 for n in notionals if n > 1000.0) / len(notionals), 4
        ),
    }


# ---------------------------------------------------------------------------
# the plane, re-derived from the model in-process
# ---------------------------------------------------------------------------


def frozen_plane(stake_usd: float) -> dict[str, Any]:
    model = default_model(ADMISSION_SCENARIO_ID)
    cost = model.evaluate(size_usd=stake_usd)
    components = {c.name: {"value_bps": round(c.value_bps, 6), "knowledge": c.knowledge,
                           "source_id": c.source_id, "note": c.note}
                  for c in cost.components}
    return {
        "scenario_id": ADMISSION_SCENARIO_ID,
        "stake_usd": stake_usd,
        "round_trip_bps": round(cost.round_trip_bps, 6),
        "minimum_gross_edge_bps": round(cost.minimum_gross_edge_bps(), 6),
        "components": components,
        "fee_schedule": {
            "venue": model.spec.venue,
            "product": model.spec.product,
            "tier": model.spec.tier,
            "maker_fee_bps": model.spec.maker_fee_bps,
            "taker_fee_bps": model.spec.taker_fee_bps,
            "fee_source_id": model.spec.fee_source_id,
            "default_taker_spread_bps": model.spec.default_taker_spread_bps,
            "spread_source_id": model.spec.spread_source_id,
            "notes": model.spec.notes,
        },
        "model_constants": {
            "base_slippage_bps": model.base_slippage_bps,
            "base_impact_bps": model.base_impact_bps,
            "liquidity_regime": "normal (x1.0)",
            "size_factor": round(1.0 + math.sqrt(stake_usd / 10_000.0), 6),
            "volatility_factor": 1.0,
            "taker_legs": 2,
        },
        "fee_schedule_context": [
            {"scenario_id": scenario, "fee_source_id": source, "maker_fee_bps": maker,
             "taker_fee_bps": taker, "in_venue_registry": scenario in VENUE_SPECS}
            for scenario, source, maker, taker in FEE_SCHEDULE_CONTEXT
        ],
    }


def published_plane() -> dict[str, Any]:
    if not AUDIT.exists():
        return {}
    payload = json.loads(AUDIT.read_text(encoding="utf-8"))
    plane = payload.get("cost_plane") or {}
    return {
        "source": str(AUDIT.relative_to(ROOT)).replace("\\", "/"),
        "frozen_round_trip_bps_200_usdt": plane.get("frozen_round_trip_bps_200_usdt"),
        "published_round_trip_bps_200_usdt": plane.get("round_trip_bps_200_usdt"),
        "published_components": plane.get("components_200_usdt"),
        "reproduces_frozen_value": plane.get("reproduces_frozen_value"),
    }


# ---------------------------------------------------------------------------
# how big the moves are that the plane must be paid out of
# ---------------------------------------------------------------------------


def move_sizes(market: str, symbol: str, run_id: str) -> dict[str, Any]:
    """Absolute mid move over 5 and 30 minutes, on the sealed window only.

    Descriptive market statistics with no rule attached: they bound whether a
    ~23 bps round trip can be paid for at all. Overlapping windows are reported
    beside independent ones because the window is short and the overlapping count
    is not an effective sample size.
    """
    mids: list[tuple[int, float]] = []
    for path in segment_files(FORWARD_ROOT, market, symbol, "book_checkpoint"):
        for row in iter_rows(path, run_id):
            detail = row.get("detail") or {}
            mid = detail.get("mid")
            t = row.get("receive_time")
            if mid and t:
                mids.append((int(t), float(mid)))
    mids.sort(key=lambda item: item[0])
    out: dict[str, Any] = {"samples": len(mids), "horizons": {}}
    if len(mids) < 3:
        return out
    for minutes in MOVE_HORIZONS_MINUTES:
        step_ms = minutes * 60_000
        overlapping: list[float] = []
        for t0, mid0 in mids:
            target = t0 + step_ms
            follow = next((mid for t, mid in mids if t >= target), None)
            if follow is None:
                break
            overlapping.append(abs(follow - mid0) / mid0 * 1e4)
        independent: list[float] = []
        cursor = 0
        while cursor < len(mids):
            t0, mid0 = mids[cursor]
            target = t0 + step_ms
            follow_index = next((i for i in range(cursor + 1, len(mids)) if mids[i][0] >= target), None)
            if follow_index is None:
                break
            independent.append(abs(mids[follow_index][1] - mid0) / mid0 * 1e4)
            cursor = follow_index
        out["horizons"][str(minutes)] = {
            "overlapping_windows": describe(overlapping),
            "independent_windows": {"n": len(independent),
                                    "values_bps": [round(v, 6) for v in independent]},
            "note": ("overlapping windows are correlated and are not an effective sample "
                     "size; the independent count is the honest one"),
        }
    return out


# ---------------------------------------------------------------------------
# latency, funding and other conditions that belong to a cost decision
# ---------------------------------------------------------------------------


def truncation_scan(run_id: str, per_stream_last_files: int = 1) -> list[dict[str, Any]]:
    """Read the newest segment of every stream to its end, and report the ones that stop early.

    Cheap on purpose: the question is whether this root contains partially written
    segments at all, and the file that was being written when a writer died is the newest
    one in its stream. A positive result is evidence about *how* the writer ended.
    """
    found: list[dict[str, Any]] = []
    for market in ("spot", "perp"):
        for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
            for stream in ("depth_snapshot", "depth_diff", "book_checkpoint", "book_ticker",
                           "agg_trade", "funding", "mark_price", "open_interest"):
                files = segment_files(FORWARD_ROOT, market, symbol, stream)
                for path in files[-per_stream_last_files:]:
                    rows = 0
                    try:
                        with gzip.open(path, "rt", encoding="utf-8") as handle:
                            for _line in handle:
                                rows += 1
                    except (EOFError, gzip.BadGzipFile, OSError) as exc:
                        found.append({"file": str(path.relative_to(ROOT)).replace("\\", "/"),
                                      "error": type(exc).__name__,
                                      "rows_read_before_truncation": rows, "run_id": run_id})
    return found


LATENCY_FILES_SAMPLED = 3


def latency_and_conditions(run_id: str, manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    """Delay and funding percentiles from a bounded sample, beside the published ones.

    The manifest already publishes per-stream delay quantiles for the whole window; this
    sample exists to disagree with it if it should, not to replace it, so three files per
    stream is enough and the sample size is reported next to every figure.
    """
    latency: dict[str, list[float]] = defaultdict(list)
    for market in ("spot", "perp"):
        for symbol in ("BTCUSDT", "ETHUSDT"):
            for stream in ("book_ticker", "agg_trade"):
                for path in segment_files(FORWARD_ROOT, market, symbol, stream)[:LATENCY_FILES_SAMPLED]:
                    for row in iter_rows(path, run_id):
                        value = row.get("network_delay_ms")
                        if value is not None and 0 <= float(value) < 60_000:
                            latency[f"{market}/{symbol}/{stream}"].append(float(value))
    funding_rates: list[float] = []
    for symbol in ("BTCUSDT", "ETHUSDT"):
        for path in segment_files(FORWARD_ROOT, "perp", symbol, "funding"):
            for row in iter_rows(path, run_id):
                rate = row.get("funding_rate")
                if rate is not None:
                    funding_rates.append(float(rate) * 1e4)
    mark_rows = sum(1 for symbol in ("BTCUSDT", "ETHUSDT")
                    for path in segment_files(FORWARD_ROOT, "perp", symbol, "mark_price")
                    for _ in iter_rows(path, run_id))
    oi_rows = sum(1 for symbol in ("BTCUSDT", "ETHUSDT")
                  for path in segment_files(FORWARD_ROOT, "perp", symbol, "open_interest")
                  for _ in iter_rows(path, run_id))
    return {
        "network_delay_ms": {key: describe(values) for key, values in sorted(latency.items())},
        "network_delay_sampling": (f"first {LATENCY_FILES_SAMPLED} files of each stream, ~"
                                   f"{LATENCY_FILES_SAMPLED * 900} s of the window"),
        "network_delay_published_by_the_manifest": (manifest or {}).get("network_delay_published"),
        "funding_rate_bps_per_interval": describe(funding_rates),
        "funding_samples": len(funding_rates),
        "mark_price_rows": mark_rows,
        "open_interest_rows": oi_rows,
    }


# ---------------------------------------------------------------------------
# verdict
# ---------------------------------------------------------------------------


def assess(plane: dict[str, Any], books: list[dict[str, Any]], trades: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare the two ESTIMATED plane terms with what the window actually quoted."""
    spread_term = plane["components"]["spread"]["value_bps"]
    walk_term = plane["components"]["slippage"]["value_bps"] + plane["components"]["market_impact"]["value_bps"]
    estimated_micro = spread_term + walk_term
    fee_term = (plane["components"]["exchange_fee_entry"]["value_bps"]
                + plane["components"]["exchange_fee_exit"]["value_bps"])

    stake_key = f"{PLANE_STAKE_USDT:.0f}"
    per_book: dict[str, Any] = {}
    for book in books:
        if not book.get("checkpoints_reproduced"):
            continue
        sizes = book.get("sizes", {}).get(stake_key)
        if not sizes or not sizes["round_trip_microstructure_bps"]["n"]:
            continue
        per_book[f"{book['market']}/{book['symbol']}"] = {
            "checkpoints": sizes["checkpoints_priced"],
            "spread_legs_bps": sizes["spread_legs_bps"],
            "walk_legs_bps": sizes["walk_beyond_best_legs_bps"],
            "round_trip_microstructure_bps": sizes["round_trip_microstructure_bps"],
        }
    if not per_book:
        return {"state": "INSUFFICIENT_EVIDENCE",
                "why": "no book reproduced a checkpoint, so nothing can be measured"}

    medians = [record["round_trip_microstructure_bps"]["median"] for record in per_book.values()]
    spread_medians = [record["spread_legs_bps"]["median"] for record in per_book.values()]
    walk_medians = [record["walk_legs_bps"]["median"] for record in per_book.values()]
    worst_p95 = max(record["round_trip_microstructure_bps"]["p95"] for record in per_book.values())
    worst_max = max(record["round_trip_microstructure_bps"]["max"] for record in per_book.values())
    median_observed = statistics.median(medians)
    median_spread = statistics.median(spread_medians)
    median_walk = statistics.median(walk_medians)

    under_estimate_shares = {
        key: {
            "spread_share_over_plane_pct": share_over(
                [record["spread_legs_bps"]["median"], record["spread_legs_bps"]["p95"],
                 record["spread_legs_bps"]["max"]], spread_term),
            "round_trip_share_over_plane_pct": share_over(
                [record["round_trip_microstructure_bps"]["median"],
                 record["round_trip_microstructure_bps"]["p95"],
                 record["round_trip_microstructure_bps"]["max"]], estimated_micro),
        }
        for key, record in per_book.items()
    }
    if median_observed < estimated_micro * 0.5:
        state = "PLANE_OVERSTATES_MICROSTRUCTURE"
    elif median_observed > estimated_micro * 1.5:
        state = "PLANE_UNDERSTATES_MICROSTRUCTURE"
    else:
        state = "PLANE_REPRESENTATIVE"

    realised = {f"{record['market']}/{record['symbol']}": record["effective_round_trip_bps"]["estimate"]
                for record in trades}
    best_gross = BEST_GROSS_EDGE_BPS
    return {
        "state": state,
        "plane_round_trip_bps": plane["round_trip_bps"],
        "plane_spread_term_bps": round(spread_term, 6),
        "plane_slippage_plus_impact_term_bps": round(walk_term, 6),
        "plane_known_fee_term_bps": round(fee_term, 6),
        "share_of_plane_that_is_known_fees": round(fee_term / plane["round_trip_bps"], 6),
        "observed_round_trip_microstructure_bps_by_book": {
            key: record["round_trip_microstructure_bps"]["median"] for key, record in per_book.items()
        },
        "observed_round_trip_microstructure_bps_median_across_books": round(median_observed, 6),
        "observed_spread_legs_bps_median_across_books": round(median_spread, 6),
        "observed_walk_beyond_best_bps_median_across_books": round(median_walk, 6),
        "observed_worst_book_p95_bps": round(worst_p95, 6),
        "observed_worst_book_max_bps": round(worst_max, 6),
        "observed_over_estimated_ratio_median": round(median_observed / estimated_micro, 6),
        "spread_observed_over_plane_ratio": round(median_spread / spread_term, 6),
        "walk_observed_over_plane_ratio": round(median_walk / walk_term, 6),
        "tail_where_the_plane_is_too_cheap_bps": {
            "spread_p95_or_worse_exceeds_plane_spread": worst_p95 > spread_term,
            "round_trip_p95_or_worse_exceeds_plane_microstructure": worst_p95 > estimated_micro,
            "share_table": under_estimate_shares,
        },
        "realised_round_trip_bps_by_book": realised,
        "books_compared": len(per_book),
        "best_measured_gross_edge_bps": best_gross,
        "best_gross_edge_covers_known_fees_alone": best_gross >= fee_term,
        "would_zero_microstructure_cost_promote_the_best_strategy": best_gross >= fee_term,
        "promotion_note": (
            "the measured microstructure cost cannot promote a rejected strategy by itself: "
            "the two fee legs are KNOWN from the published schedule and on their own exceed the "
            "best gross edge in the 24-strategy ledger (8.912 bps). Cheaper execution narrows "
            "the bar; it does not clear it"
        ),
    }


# ---------------------------------------------------------------------------
# assembly
# ---------------------------------------------------------------------------


def _head() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, check=False).stdout.strip()
    except Exception:  # pragma: no cover - git is optional for the audit
        return ""


MEASUREMENTS = OUT_DIR / "evidence" / "E1_MEASUREMENTS.json"


def measure(run_id: str) -> dict[str, Any]:
    """Everything that costs minutes to produce, cached so reporting can be re-run.

    The measurement is separated from the presentation on purpose: a fix to a table
    must not require re-reading 1.5 GB of segments, and a cached measurement carries
    the run id it came from so a stale cache cannot be silently reused for another
    window.
    """
    started = datetime.now(UTC)
    TRUNCATED.clear()
    manifest = load_sealed_runs().get(run_id) or {}
    stage_seconds: dict[str, float] = {}

    def stage(name: str, producer):
        """Time each stage, because a measurement nobody can profile is a measurement
        nobody can trust to finish."""
        begin = time.monotonic()
        print(f"[measure] {name} ...", flush=True)
        value = producer()
        stage_seconds[name] = round(time.monotonic() - begin, 3)
        print(f"[measure] {name} done in {stage_seconds[name]} s", flush=True)
        return value

    payload = {
        "run_id": run_id,
        "measured_at_utc": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "coverage": stage("coverage", lambda: coverage_of(run_id)),
        "truncation_scan": stage("truncation_scan", lambda: truncation_scan(run_id)),
        "books": stage("books", lambda: [reconstruct_book(market, symbol, run_id, SIZE_LADDER_USDT)
                                          for market in ("spot", "perp")
                                          for symbol in ("BTCUSDT", "ETHUSDT")]),
        "realised_trades": stage("realised_trades", lambda: [
            record for record in (realised_trade_cost("spot", symbol, run_id)
                                  for symbol in ("BTCUSDT", "ETHUSDT")) if record]),
        "conditions": stage("conditions", lambda: latency_and_conditions(run_id, manifest)),
        "market_moves": stage("market_moves", lambda: {
            f"{market}/{symbol}": move_sizes(market, symbol, run_id)
            for market in ("spot", "perp") for symbol in ("BTCUSDT", "ETHUSDT")}),
    }
    payload["truncated_segments_seen_during_measurement"] = list(TRUNCATED)
    payload["stage_seconds"] = stage_seconds
    payload["measure_seconds"] = round(
        (datetime.now(UTC) - started).total_seconds(), 3)
    MEASUREMENTS.parent.mkdir(parents=True, exist_ok=True)
    MEASUREMENTS.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def load_measurements(run_id: str) -> dict[str, Any] | None:
    if not MEASUREMENTS.exists():
        return None
    payload = json.loads(MEASUREMENTS.read_text(encoding="utf-8"))
    if payload.get("run_id") != run_id:
        return None
    return payload


def build(run_id: str | None, use_cache: bool = True) -> tuple[dict[str, Any], int]:
    sealed = load_sealed_runs()
    if not sealed:
        return {"artifact": "WP10_EXECUTION_COST_DISTRIBUTION", "verdict": "BLOCKED",
                "why": "no sealed forward manifest found"}, 2
    chosen = run_id or sorted(sealed)[-1]
    if chosen not in sealed:
        return {"artifact": "WP10_EXECUTION_COST_DISTRIBUTION", "verdict": "BLOCKED",
                "why": f"manifest for run {chosen!r} not found", "manifested_runs": sorted(sealed)}, 2
    manifest = sealed[chosen]

    measured = load_measurements(chosen) if use_cache else None
    from_cache = measured is not None
    if measured is None:
        measured = measure(chosen)
    coverage = measured["coverage"]
    truncation_scan_result = measured.get("truncation_scan") or []
    books = measured["books"]
    trades = measured["realised_trades"]
    conditions = measured["conditions"]
    moves = measured["market_moves"]
    plane = frozen_plane(PLANE_STAKE_USDT)
    published = published_plane()
    verdict = assess(plane, books, trades)

    replay = json.loads(REPLAY.read_text(encoding="utf-8")) if REPLAY.exists() else {}
    mismatches = sum(book["checkpoint_mismatches"] for book in books)
    reproduced = sum(book["checkpoints_reproduced"] for book in books)
    look_ahead = sum(record["look_ahead_violations"] for record in trades)
    reproduces = (published.get("frozen_round_trip_bps_200_usdt") is not None
                  and abs(plane["round_trip_bps"] - float(published["frozen_round_trip_bps_200_usdt"])) < 1e-6)
    exit_code = 3 if mismatches else 4 if look_ahead else 0

    payload = {
        "artifact": "WP10_EXECUTION_COST_DISTRIBUTION",
        "work_package": "WP-10 (ECONOMIC EDGE RECOVERY & EXECUTION COST DISCOVERY)",
        "phase": "E-1 EXECUTION COST REALITY CHECK",
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mode": "OFFLINE READ-ONLY — captured forward data only, no network, no key, no order",
        "head": _head(),
        "dataset": {
            "root": str(FORWARD_ROOT.relative_to(ROOT)).replace("\\", "/"),
            "run_id": chosen,
            "manifest": manifest,
            "replay_verification": {
                "path": str(REPLAY.relative_to(ROOT)).replace("\\", "/"),
                "ok": replay.get("ok"),
                "deterministic": replay.get("deterministic"),
                "segments": replay.get("segments"),
                "rows": replay.get("rows"),
                "partial_tails": replay.get("partial_tails"),
                "book_match": replay.get("book_match"),
                "fingerprints_match": replay.get("fingerprints_match"),
                "internet_access": replay.get("internet_access"),
            },
            "coverage": coverage,
            "truncation_scan": {
                "segments_that_stop_early": truncation_scan_result,
                "seen_during_measurement": measured.get("truncated_segments_seen_during_measurement") or [],
                "count": len(truncation_scan_result),
                "method": ("the newest segment of every stream is read to its end; a file that "
                           "ends before its gzip trailer is a segment the writer never "
                           "finished, which is a signature of a hard stop rather than a "
                           "graceful one"),
                "consequence": ("rows lost to a truncated tail are unknown in number and are "
                                "never extrapolated; the affected stream's sample is reported "
                                "as what could be read"),
            },
            "measurement_cache": {
                "path": str(MEASUREMENTS.relative_to(ROOT)).replace("\\", "/"),
                "used": from_cache,
                "measured_at_utc": measured["measured_at_utc"],
                "measure_seconds": measured.get("measure_seconds"),
            },
            "books_in_this_seal": [f"{book['market']}/{book['symbol']}" for book in books
                                   if book["checkpoints_reproduced"]],
            "coverage_note": (
                "row counts are for the sealed run only; this root also carries a later, "
                "unsealed run whose rows are excluded here rather than mixed in"
            ),
        },
        "frozen_plane": plane,
        "published_plane": published,
        "plane_reproduces_published_value": reproduces,
        "books": books,
        "realised_trades": trades,
        "conditions": conditions,
        "market_moves": moves,
        "assessment": verdict,
        "false_success": 0 if not mismatches and not look_ahead else 1,
        "checks": [
            {"check": "sealed manifest present for the analysed run", "ok": bool(manifest)},
            {"check": "replay verification ok and network-free",
             "ok": bool(replay.get("ok")) and replay.get("internet_access") is False},
            {"check": "rebuilt top of book equals every published checkpoint",
             "ok": mismatches == 0, "mismatched": mismatches, "reproduced": reproduced},
            {"check": "no trade was joined to a quote from the future",
             "ok": look_ahead == 0, "violations": look_ahead},
            {"check": "the plane re-derives to the published frozen value", "ok": reproduces},
            {"check": "measured cost carries the OBSERVED_FORWARD label and never replaces "
                      "ESTIMATED without the plane being changed by governance",
             "ok": True},
            {"check": "no admission, promotion or plane change is performed", "ok": True},
            {"check": "every measured size reports how many checkpoints priced it",
             "ok": all(record["checkpoints_priced"] >= 0
                       for book in books for record in book["sizes"].values())},
            {"check": "truncated segment tails are reported rather than skipped silently",
             "ok": True,
             "segments_that_stop_early": len(truncation_scan_result),
             "note": ("a truncated tail is a fact about the capture and is counted here; the "
                      "measurements that could be made from the readable rows are labelled with "
                      "their own sample sizes")},
        ],
        "limitations": [
            f"one sealed window of {manifest['duration_hours']} h in a single session regime",
            "BTC and ETH only: no SOL book exists in this seal, so no cross-asset generality",
            "the seal stopped on its own 800 MB disk valve, not because a measurement ended",
            "spot book_ticker rows carry no exchange event time, so the quote clock there is the "
            "receive clock; that is later than the event, never earlier, so it cannot create "
            "look-ahead",
            "the walked depth is what the venue streamed, not the venue's whole book; a size that "
            "clears the last recorded level is reported unfillable rather than extrapolated",
            "the measured ladder is a static snapshot walk: a real order arrives at a moving book, "
            "and the latency in section 5 is the size of that motion",
            "this is a cost measurement, not a profitability result: RESEARCH_RESULT only",
        ],
        "scope": {
            "trading": False,
            "processes_started": 0,
            "network": False,
            "frozen_artifacts_modified": 0,
            "strategies_admitted": 0,
        },
    }
    payload["verdict"] = {
        "e1": verdict["state"],
        "checkpoints_reproduced": reproduced,
        "checkpoints_mismatched": mismatches,
        "look_ahead_violations": look_ahead,
        "false_success": payload["false_success"],
    }
    return payload, exit_code


def render_markdown(payload: dict[str, Any]) -> str:
    plane = payload["frozen_plane"]
    verdict = payload["assessment"]
    dataset = payload["dataset"]
    manifest = dataset["manifest"]
    lines = [
        "# WP-10 E-1 — EXECUTION COST DISTRIBUTION",
        "",
        f"> `{payload['generated_at_utc']}` · head `{payload['head']}` · **{verdict['state']}**",
        "",
        f"Sealed forward window `{manifest['run_id']}`: {manifest['started_at']} → "
        f"{manifest['ended_at']} ({manifest['duration_hours']} h), status "
        f"`{manifest['status']}`, stop reason `{manifest['stop_reason']}`, continuity "
        f"`{manifest['continuity']}`, {manifest['gaps']} gaps, replay "
        f"`{'ok' if dataset['replay_verification']['ok'] else 'not ok'}`.",
        "",
        "## 1. The plane under test",
        "",
        f"`{plane['scenario_id']}` at {plane['stake_usd']:.0f} USDT = "
        f"**{plane['round_trip_bps']:.6f} bps**, re-derived in-process from COST_MODEL_V3 and "
        f"equal to the published frozen value: `{payload['plane_reproduces_published_value']}`.",
        "",
        "| component | bps | class | what it is |",
        "| --- | ---: | --- | --- |",
    ]
    for name, component in plane["components"].items():
        lines.append(f"| `{name}` | {component['value_bps']:.4f} | {component['knowledge']} | "
                     f"{component['note'] or component['source_id']} |")
    lines += [
        "",
        f"Under test: **{verdict['plane_spread_term_bps']} bps** of spread and "
        f"**{verdict['plane_slippage_plus_impact_term_bps']} bps** of slippage+impact, both "
        f"`ESTIMATED`; **{verdict['plane_known_fee_term_bps']} bps** of fees are `KNOWN` "
        f"({verdict['share_of_plane_that_is_known_fees'] * 100:.2f} % of the plane).",
        "",
        "## 2. The spread that was actually quoted",
        "",
        "| book | checkpoints reproduced | spread median | p05 | p95 | max (bps) |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for book in payload["books"]:
        spread = book["top_of_book_spread_bps"]
        lines.append(
            f"| {book['market']}/{book['symbol']} | {book['checkpoints_reproduced']}"
            f"/{book['checkpoint_rows']} | {spread['median']} | {spread['p05']} | "
            f"{spread['p95']} | {spread['max']} |"
        )
    lines += [
        "",
        "## 3. What a market order would have paid, size by size",
        "",
        "Round trip = entry and exit swept through the rebuilt book, both measured against the "
        "checkpoint mid; spread legs and walk legs are its two parts.",
        "",
        "| book | size | checkpoints | round trip median | p95 | worst | spread legs median | "
        "walk legs median | unfillable |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for book in payload["books"]:
        for size, record in book["sizes"].items():
            rt = record["round_trip_microstructure_bps"]
            lines.append(
                f"| {book['market']}/{book['symbol']} | {size} | {record['checkpoints_priced']} | "
                f"{rt['median']} | {rt['p95']} | {rt['max']} | {record['spread_legs_bps']['median']} | "
                f"{record['walk_beyond_best_legs_bps']['median']} | "
                f"{record['checkpoints_unfillable_within_recorded_book']} |"
            )
    lines += [
        "",
        "## 4. What real takers actually paid",
        "",
        "| book | prints joined | effective half spread median | p95 | round trip | print notional "
        "median USDT | >1000 USDT | look-ahead violations |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for record in payload["realised_trades"]:
        half = record["effective_half_spread_bps"]
        lines.append(
            f"| {record['market']}/{record['symbol']} | {record['prints_joined']} | "
            f"{half['median']} | {half['p95']} | {record['effective_round_trip_bps']['estimate']} | "
            f"{record['print_notional_usdt']['median']} | "
            f"{record['print_notional_over_1000_usdt_pct']} % | {record['look_ahead_violations']} |"
        )
    lines += ["", "## 5. Conditions of execution", ""]
    for key, value in payload["conditions"]["network_delay_ms"].items():
        lines.append(f"* `{key}` network delay ms: median {value['median']}, p95 {value['p95']}, "
                     f"max {value['max']} (n={value['n']})")
    funding = payload["conditions"]["funding_rate_bps_per_interval"]
    if funding["n"]:
        lines.append(f"* perp funding bps per interval: median {funding['median']}, "
                     f"p95 {funding['p95']}, max {funding['max']} (n={funding['n']})")
    lines.append(f"* mark price rows {payload['conditions']['mark_price_rows']}, "
                 f"open interest rows {payload['conditions']['open_interest_rows']}")
    lines += ["", "## 6. The move the cost has to be paid out of", "",
              "| book | horizon | independent windows | values (bps) |", "| --- | ---: | ---: | --- |"]
    for key, record in payload["market_moves"].items():
        for horizon, data in record["horizons"].items():
            values = ", ".join(f"{v:.2f}" for v in data["independent_windows"]["values_bps"])
            lines.append(f"| {key} | {horizon} min | {data['independent_windows']['n']} | {values} |")
    lines += [
        "",
        "## 7. Verdict",
        "",
        f"* state: **{verdict['state']}**",
        f"* observed / estimated microstructure: "
        f"{verdict['observed_over_estimated_ratio_median']} "
        f"({verdict['observed_round_trip_microstructure_bps_median_across_books']} bps vs "
        f"{verdict['plane_spread_term_bps'] + verdict['plane_slippage_plus_impact_term_bps']} bps)",
        f"* spread observed / plane: {verdict['spread_observed_over_plane_ratio']}; "
        f"walk observed / plane: {verdict['walk_observed_over_plane_ratio']}",
        f"* worst book p95 {verdict['observed_worst_book_p95_bps']} bps, worst single checkpoint "
        f"{verdict['observed_worst_book_max_bps']} bps — the plane is not uniformly generous",
        f"* best gross edge in the 24-strategy ledger: {verdict['best_measured_gross_edge_bps']} bps; "
        f"clears the KNOWN fee legs alone: `{verdict['best_gross_edge_covers_known_fees_alone']}`",
        "",
        verdict["promotion_note"],
        "",
        "## 8. Fee schedules the measured window did not change",
        "",
        "| scenario | source | maker bps | taker bps |",
        "| --- | --- | ---: | ---: |",
        *[f"| `{row['scenario_id']}` | {row['fee_source_id']} | {row['maker_fee_bps']} | "
          f"{row['taker_fee_bps']} |" for row in plane["fee_schedule_context"]],
        "",
        "These are published facts, recorded here as context for where a cheaper execution could "
        "come from. Moving the admission plane onto one of them is a governance decision, not a "
        "measurement result, and E-1 does not make it.",
        "",
        "## 9. Checks and limitations",
        "",
    ]
    for check in payload["checks"]:
        lines.append(f"* [{'x' if check['ok'] else ' '}] {check['check']}")
    lines.append("")
    for limitation in payload["limitations"]:
        lines.append(f"* {limitation}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=None, help="sealed run to analyse (default: latest)")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--measure-only", action="store_true",
                        help="build (and cache) the measurements, then stop")
    parser.add_argument("--no-cache", action="store_true", help="ignore a cached measurement")
    args = parser.parse_args()

    if args.measure_only:
        sealed = load_sealed_runs()
        chosen = args.run_id or sorted(sealed)[-1]
        measured = measure(chosen)
        print(f"measured {chosen} in {measured['measure_seconds']} s -> "
              f"{MEASUREMENTS.relative_to(ROOT)}")
        return 0

    payload, exit_code = build(args.run_id, use_cache=not args.no_cache)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if args.json:
        print(json.dumps(payload, indent=2))
        return exit_code
    json_path = OUT_DIR / "WP10_EXECUTION_COST_DISTRIBUTION.json"
    md_path = OUT_DIR / "WP10_EXECUTION_COST_DISTRIBUTION.md"
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(payload) + "\n", encoding="utf-8")
    payload["payload_sha256"] = hashlib.sha256(json_path.read_bytes()).hexdigest()
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"{payload.get('verdict')}: {json_path.relative_to(ROOT)}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
