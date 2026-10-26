"""Offline deterministic replay of a captured forward dataset (§31, §32).

``replay_microstructure_dataset(...)`` rebuilds a capture from disk alone. It
never opens a socket: no REST, no WebSocket, no DNS. That is the whole point —
if replay needed the venue, the dataset would not be evidence.

What it reconstructs, and what it then proves:

===================  ==================================================
trade stream         every aggTrade in write order with sequence checks
book state           snapshot+diff through the *same* ``BookSyncer`` code
                     path the live collector used, compared against every
                     persisted ``book_checkpoint``
OI / funding / basis series   sample counts and timestamp monotonicity
derived features     the 1m/5m/15m/30m aggregation, hashed and compared
                     with the digest recorded at capture time
===================  ==================================================

It also re-derives every segment fingerprint from raw bytes and compares it
with the manifest, so a byte changed after the fact is detected.
"""

from __future__ import annotations

import contextlib
import hashlib
import heapq
import json
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from trading_bot.research.forward.aggregation import (
    DatasetAggregation,
    aggregate_dataset,
)
from trading_bot.research.forward.contract import (
    BACKFILL_ORIGIN,
    EventType,
    Market,
    RawEvent,
    parse_event,
)
from trading_bot.research.forward.orderbook import (
    BookStateError,
    BookSyncer,
    DepthUpdate,
    SequencePolicy,
    parse_depth_levels,
)
from trading_bot.research.forward.storage import (
    StorageError,
    fingerprint_segment,
    iter_segment_records,
    iter_segment_rows,
    load_json,
    load_manifest,
)

__all__ = [
    "REPLAY_VERSION",
    "ForwardReplay",
    "ReplayVerification",
    "aggregation_digest",
    "replay_microstructure_dataset",
]

REPLAY_VERSION = "FORWARD-REPLAY-V1"


def _row_order(row: dict[str, Any]) -> tuple[int, int]:
    """The collector's own ordering: processing order, then receive time."""
    return int(row.get("write_seq") or 0), int(row.get("receive_time") or 0)


#: How many open holes the trade-chain tracker will hold. A capture with more
#: unexplained holes than this is not a capture any more, and the tracker says so
#: through ``trade_hole_tracker_saturated`` instead of growing without bound.
_MAX_TRACKED_HOLES = 10_000


class _TradeChain:
    """The reconstructed aggregate-trade id chain of one market/symbol.

    Write order is *not* id order for trades, and pretending it is makes a
    legitimate recovery look like a broken chain. A row restored from the public
    index (``detail.origin == agg_trade_backfill``) is written when the index
    answers: a hole found *behind* the live stream is filled after the live row
    that revealed it, and a hole opened by a socket outage is walked *forward*
    from the last known id to the head of the index, i.e. past the newest live id
    at that moment. The live rows for those ids arrive later and are suppressed by
    the collector's id window, so the persisted set still holds each logical trade
    exactly once.

    What must hold, and what this class checks, is an id-space property:

    * the *live* chain is strictly increasing — a live row that regresses is
      corruption, never a repair;
    * an id is accounted for at most once. ``resolved_hi`` is the highest id below
      which every id is explained: it was persisted (live or repaired), or it sits
      inside a tracked hole — a region the live chain skipped, which a repair may
      legitimately fill in later;
    * a repaired row that lands on an already-explained id is a duplicate, i.e. a
      fabrication or a failed dedup, and is a violation.

    Memory is bounded by the number of *open* holes at any moment, not by the
    number of rows: a filled hole is consumed as it is filled.
    """

    __slots__ = ("holes", "live_head", "resolved_hi", "saturated")

    def __init__(self) -> None:
        #: Highest id seen on the live WS stream; only ever rises.
        self.live_head: int | None = None
        #: Highest id below which the chain is fully accounted for.
        self.resolved_hi: int | None = None
        #: Sorted, disjoint ``[lo, hi]`` regions the live chain skipped and no
        #: persisted row has explained yet.
        self.holes: list[list[int]] = []
        self.saturated = False

    # ------------------------------------------------------------------ holes
    def _add_hole(self, lo: int, hi: int) -> None:
        if hi < lo:
            return
        if len(self.holes) >= _MAX_TRACKED_HOLES:
            self.saturated = True
            return
        self.holes.append([lo, hi])
        self.holes.sort(key=lambda interval: interval[0])

    def _consume(self, trade_id: int) -> bool:
        """Explain ``trade_id`` by an open hole. True when a hole contained it."""
        for index, (lo, hi) in enumerate(self.holes):
            if lo > trade_id:
                break
            if trade_id > hi:
                continue
            if lo == hi:
                self.holes.pop(index)
            elif trade_id == lo:
                self.holes[index] = [lo + 1, hi]
            elif trade_id == hi:
                self.holes[index] = [lo, hi - 1]
            else:
                self.holes[index] = [lo, trade_id - 1]
                self.holes.insert(index + 1, [trade_id + 1, hi])
            return True
        return False

    # ------------------------------------------------------------------ ingest
    def on_live(self, trade_id: int) -> str | None:
        """Account for a live WS aggregate trade, returning a violation if any."""
        head = self.live_head
        if head is not None and trade_id <= head:
            return f"aggTrade id {trade_id} not > previous {head}"
        self.live_head = trade_id
        resolved = self.resolved_hi
        if resolved is None:
            self.resolved_hi = trade_id
            return None
        if trade_id <= resolved:
            # Presented again on the live chain after a repair already covered it:
            # the id is explained either way, and the collector suppresses the
            # duplicate row, so this is the dedup path rather than a violation.
            self._consume(trade_id)
            return None
        self._add_hole(resolved + 1, trade_id - 1)
        self.resolved_hi = trade_id
        return None

    def on_repaired(self, trade_id: int) -> str | None:
        """Account for a row restored from the public index."""
        resolved = self.resolved_hi
        if resolved is None:
            self.resolved_hi = trade_id
            return None
        if trade_id <= resolved:
            if self._consume(trade_id):
                return None
            return (
                f"repaired aggTrade id {trade_id} collides with an id the chain "
                f"already accounted for below {resolved}"
            )
        if trade_id > resolved + 1:
            # The public index itself skipped ids: those ids are left as an open
            # hole and stay visible as such instead of being silently accepted.
            self._add_hole(resolved + 1, trade_id - 1)
        self.resolved_hi = trade_id
        return None

    def as_dict(self) -> dict[str, Any]:
        return {
            "live_head": self.live_head,
            "resolved_hi": self.resolved_hi,
            "unresolved_holes": len(self.holes),
            "saturated": self.saturated,
        }


def _segment_stream(path: Path) -> tuple[Iterator[dict[str, Any]], list[int]]:
    """Lazy row iterator for one segment plus a box holding its partial flag."""
    truncated = [0]

    def _rows() -> Iterator[dict[str, Any]]:
        for row, partial in iter_segment_rows(path):
            if partial:
                truncated[0] = 1
                continue
            if row is not None:
                yield row

    return _rows(), truncated


def aggregation_digest(aggregation: DatasetAggregation) -> str:
    """Canonical digest of a full aggregation. Order-independent by construction."""
    payload = json.dumps(
        aggregation.as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class BookComparison:
    market: str
    symbol: str
    checkpoints: int = 0
    matches: int = 0
    mismatches: list[dict[str, Any]] = field(default_factory=list)
    dispositions: dict[str, int] = field(default_factory=dict)
    snapshot_outcomes: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.mismatches

    def as_dict(self) -> dict[str, Any]:
        return {
            "market": self.market,
            "symbol": self.symbol,
            "checkpoints": self.checkpoints,
            "matches": self.matches,
            "ok": self.ok,
            "mismatch_count": len(self.mismatches),
            "mismatches": self.mismatches[:20],
            "dispositions": dict(sorted(self.dispositions.items())),
            "snapshot_outcomes": dict(sorted(self.snapshot_outcomes.items())),
        }


@dataclass(slots=True)
class ReplayVerification:
    """The machine-checkable result of a replay. Nothing here is a narrative."""

    version: str = REPLAY_VERSION
    run_id: str = ""
    root: str = ""
    segments: int = 0
    rows: int = 0
    partial_tails: int = 0
    internet_access: bool = False
    event_counts: dict[str, int] = field(default_factory=dict)
    manifest_event_counts: dict[str, int] = field(default_factory=dict)
    event_count_match: bool = False
    event_count_differences: list[dict[str, Any]] = field(default_factory=list)
    trade_sequence_ok: bool = False
    trade_sequence_violations: list[str] = field(default_factory=list)
    #: Rows restored from the public trade index. Reported separately because they
    #: are legitimately out of id order in write order, and a reader must be able
    #: to tell them from a corrupted chain.
    repaired_trade_rows: int = 0
    #: ``trade_sequence_violations`` is capped for the artifact, so the number of
    #: violations is carried separately: a truncated list must never read as "few".
    trade_sequence_violation_count: int = 0
    #: Ids the live chain skipped that no persisted row explained. They are
    #: residual holes, reconciled against the manifest's gap records by the
    #: independent verifier; they are not silently presumed lost.
    trade_unresolved_holes: int = 0
    trade_hole_tracker_saturated: bool = False
    books: list[BookComparison] = field(default_factory=list)
    book_match: bool = False
    fingerprint_checks: int = 0
    fingerprint_matches: int = 0
    fingerprint_mismatches: list[dict[str, Any]] = field(default_factory=list)
    fingerprints_match: bool = False
    aggregation_digest: str = ""
    recorded_aggregation_digest: str | None = None
    feature_match: bool | None = None
    deterministic: bool = False
    second_pass_digest: str = ""
    #: Per market/symbol chain state: live head, explained frontier, open holes.
    trade_chains: dict[str, dict[str, Any]] = field(default_factory=dict)
    series: dict[str, dict[str, Any]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["books"] = [b.as_dict() for b in self.books]
        # The artifact carries its own verdict. Without it a reader has to
        # re-implement ``ok`` from seven fields to know whether the replay that
        # produced this file passed, and a consumer that guesses will guess right
        # until the day it matters.
        payload["ok"] = self.ok
        return payload

    @property
    def ok(self) -> bool:
        checks = [
            self.event_count_match,
            self.trade_sequence_ok,
            self.book_match,
            self.fingerprints_match,
            self.deterministic,
            not self.partial_tails,
            not self.errors,
        ]
        if self.feature_match is not None:
            checks.append(self.feature_match)
        return all(checks)


class ForwardReplay:
    """Reads a capture from disk and reconstructs it without any network."""

    def __init__(self, root: Path | str, run_id: str | None = None) -> None:
        self.root = Path(root)
        resolved = run_id or self._infer_run_id()
        if not resolved:
            raise StorageError(f"{self.root}: no run to replay (manifest/ is empty)")
        self.run_id: str = resolved
        self.manifest_path = self.root / "manifest" / f"{self.run_id}.json"
        self.manifest: dict[str, Any] = (
            load_manifest(self.manifest_path) if self.manifest_path.exists() else {}
        )

    def _infer_run_id(self) -> str | None:
        manifest_dir = self.root / "manifest"
        if not manifest_dir.is_dir():
            return None
        candidates = sorted(manifest_dir.glob("*.json"))
        return candidates[-1].stem if candidates else None

    # ------------------------------------------------------------------ loading
    def segment_files(self) -> list[Path]:
        """Every segment on disk, compressed or not."""
        segments = self.root / "segments"
        if not segments.is_dir():
            return []
        return sorted(set(segments.rglob("*.jsonl")) | set(segments.rglob("*.jsonl.gz")))

    def load_rows(self) -> tuple[list[dict[str, Any]], int]:
        """Every persisted row, ordered by the collector's own write counter.

        ``write_seq`` is the ordering authority because it is the *processing*
        order, which is what the live book state depended on. Sorting by
        timestamp instead would silently reinterpret ties.

        This materialises the whole run, so it is for small datasets and tests;
        analysis of a real capture must use :meth:`iter_rows`.
        """
        rows: list[dict[str, Any]] = []
        partial_tails = 0
        for path in self.segment_files():
            segment_rows, partial = iter_segment_records(path)
            if partial:
                partial_tails += 1
            rows.extend(segment_rows)
        rows.sort(key=_row_order)
        return rows, partial_tails

    def iter_rows(self) -> Iterator[tuple[dict[str, Any], int]]:
        """Stream every persisted row in write order, with bounded memory.

        A forward hour of a busy stream is one segment of ~10^6 rows, so the
        analysis path may never hold a run in memory. Each segment is already in
        write order, so the global order is a k-way merge over the open
        segments, and at any moment only one row per segment is resident.

        Yields ``(row, partial_tails)`` where the counter is the running number
        of segments that ended in a truncated tail — visible, never swallowed.
        """
        partial_tails = 0
        streams: list[Iterator[dict[str, Any]]] = []
        handles: list[Any] = []
        for path in self.segment_files():
            iterator, counter = _segment_stream(path)
            streams.append(iterator)
            handles.append(counter)
        try:
            for row in heapq.merge(*streams, key=_row_order) if streams else ():
                partial_tails = sum(handle[0] for handle in handles)
                yield row, partial_tails
        finally:
            for stream in streams:
                close = getattr(stream, "close", None)
                if callable(close):
                    with contextlib.suppress(Exception):
                        close()

    def iter_events(self) -> Iterator[RawEvent]:
        """Stream parsed events in write order, skipping rows that do not parse."""
        for row, _ in self.iter_rows():
            try:
                yield parse_event(row)
            except Exception:
                continue

    # ------------------------------------------------------------------- replay
    def _policy(self, market: str) -> SequencePolicy:
        return (
            SequencePolicy.SPOT_UPDATE_ID
            if market == Market.SPOT.value
            else SequencePolicy.FUTURES_PREV_ID
        )

    def _reconstruct(
        self, rows: Iterable[dict[str, Any]], repaired: list[int]
    ) -> tuple[
        int,
        dict[str, int],
        list[BookComparison],
        list[str],
        dict[str, dict[str, Any]],
        dict[str, Any],
    ]:
        """Walk the rows once, keeping only counters and bounded aggregates.

        Nothing here scales with the number of rows: a capture of days must be
        replayable in constant memory, so the row itself is the only thing
        resident at any moment (§34).
        """
        row_count = 0
        counts: dict[str, int] = {}
        books: dict[str, BookSyncer] = {}
        comparisons: dict[str, BookComparison] = {}
        violations: list[str] = []
        series: dict[str, dict[str, Any]] = {}
        #: The aggregate-trade chain per market/symbol, checked in id space. A
        #: repaired row is written when the public index answers, i.e. after the
        #: live stream has already moved on, so write order is not id order for
        #: those rows; the chain that must be monotone is the live one.
        chains: dict[str, _TradeChain] = {}

        for row in rows:
            try:
                event = parse_event(row)
            except Exception as exc:
                violations.append(f"unreadable row: {exc}")
                continue
            row_count += 1
            key = f"{event.market.value}/{event.symbol}/{event.event_type.value}"
            counts[key] = counts.get(key, 0) + 1

            if event.event_type is EventType.AGG_TRADE:
                symbol_key = f"{event.market.value}/{event.symbol}"
                trade_id = int(event.exchange_event_id or 0)
                detail = row.get("detail")
                is_repaired = isinstance(detail, dict) and detail.get("origin") == BACKFILL_ORIGIN
                chain = chains.setdefault(symbol_key, _TradeChain())
                if is_repaired:
                    repaired[0] += 1
                    problem = chain.on_repaired(trade_id)
                else:
                    problem = chain.on_live(trade_id)
                if problem is not None:
                    violations.append(f"{symbol_key}: {problem}")
            elif event.event_type in (
                EventType.OPEN_INTEREST,
                EventType.FUNDING,
                EventType.MARK_PRICE,
            ):
                stats = series.setdefault(
                    f"{event.market.value}/{event.symbol}",
                    {"samples": 0, "max_ts": 0, "regressions": 0},
                )
                stats["samples"] += 1
                stamp = event.exchange_event_time or event.receive_time
                if stamp < stats["max_ts"]:
                    stats["regressions"] += 1
                stats["max_ts"] = max(stats["max_ts"], stamp)

            if event.event_type in (
                EventType.DEPTH_DIFF,
                EventType.DEPTH_SNAPSHOT,
                EventType.BOOK_CHECKPOINT,
            ):
                syncer = books.get(f"{event.market.value}|{event.symbol}")
                if syncer is None:
                    # The book parameters come from the manifest, not from this
                    # module's defaults: replay must rebuild the *same* book the
                    # collector held, so it may not silently pick its own knobs.
                    syncer = BookSyncer(
                        symbol=event.symbol,
                        market=event.market.value,
                        policy=self._policy(event.market.value),
                        depth_n=int(self.manifest.get("depth_n") or 10),
                        stale_after_ms=int(self.manifest.get("stale_after_ms") or 5_000),
                    )
                    books[f"{event.market.value}|{event.symbol}"] = syncer
                comparison = comparisons.setdefault(
                    f"{event.market.value}|{event.symbol}",
                    BookComparison(market=event.market.value, symbol=event.symbol),
                )
                if event.event_type is EventType.DEPTH_SNAPSHOT:
                    try:
                        bids = parse_depth_levels(event.bids or [], "bids")
                        asks = parse_depth_levels(event.asks or [], "asks")
                        outcome = syncer.on_snapshot(
                            int(event.exchange_event_id or 0), bids, asks, event.receive_time
                        )
                        comparison.snapshot_outcomes[outcome.value] = (
                            comparison.snapshot_outcomes.get(outcome.value, 0) + 1
                        )
                    except BookStateError as exc:
                        comparison.mismatches.append(
                            {
                                "reason": "snapshot_rejected",
                                "at_ms": event.receive_time,
                                "detail": str(exc),
                            }
                        )
                elif event.event_type is EventType.DEPTH_DIFF:
                    try:
                        update = DepthUpdate(
                            first_id=int(event.sequence.first)
                            if event.sequence and event.sequence.first is not None
                            else 0,
                            last_id=int(event.sequence.last)
                            if event.sequence and event.sequence.last is not None
                            else 0,
                            prev_id=event.sequence.prev if event.sequence else None,
                            bids=parse_depth_levels(event.bids or [], "bids"),
                            asks=parse_depth_levels(event.asks or [], "asks"),
                            exchange_event_time=event.exchange_event_time,
                            received_time=event.receive_time,
                        )
                        disposition = syncer.on_diff(update)
                        comparison.dispositions[disposition.value] = (
                            comparison.dispositions.get(disposition.value, 0) + 1
                        )
                    except BookStateError as exc:
                        comparison.mismatches.append(
                            {
                                "reason": "diff_rejected",
                                "at_ms": event.receive_time,
                                "detail": str(exc),
                            }
                        )
                else:
                    comparison.checkpoints += 1
                    health = syncer.health(event.receive_time)
                    replayed = syncer.book.checkpoint(health)
                    differences = _compare_checkpoint(event, replayed)
                    if differences:
                        comparison.mismatches.append(
                            {
                                "reason": "checkpoint_mismatch",
                                "at_ms": event.receive_time,
                                "differences": differences,
                            }
                        )
                    else:
                        comparison.matches += 1
        trade_state = {
            "unresolved_holes": sum(len(chain.holes) for chain in chains.values()),
            "saturated": any(chain.saturated for chain in chains.values()),
            "chains": {key: chain.as_dict() for key, chain in sorted(chains.items())},
        }
        return row_count, counts, list(comparisons.values()), violations, series, trade_state

    def replay(self) -> ReplayVerification:
        partial_box = [0]
        repaired_box = [0]

        def _rows() -> Iterator[dict[str, Any]]:
            for row, partial in self.iter_rows():
                partial_box[0] = partial
                yield row

        rows_seen, counts, comparisons, violations, series, trade_state = self._reconstruct(
            _rows(), repaired_box
        )
        partial_tails = partial_box[0]
        repaired_rows = repaired_box[0]

        manifest_counts = {
            f"{s['market']}/{s['symbol']}/{s['event_type']}": int(s["events"])
            for s in self.manifest.get("streams", [])
        }
        differences = [
            {
                "stream": key,
                "replayed": replayed,
                "manifest": manifest_counts.get(key, 0),
            }
            for key, replayed in sorted(counts.items())
            if manifest_counts.get(key, 0) != replayed
        ]
        differences += [
            {"stream": key, "replayed": 0, "manifest": value}
            for key, value in sorted(manifest_counts.items())
            if key not in counts and value != 0
        ]

        fingerprint_mismatches: list[dict[str, Any]] = []
        checks = 0
        matches = 0
        manifest_fingerprints = {f["path"]: f for f in self.manifest.get("fingerprints", [])}
        for path in self.segment_files():
            relative = path.relative_to(self.root).as_posix()
            checks += 1
            recomputed = fingerprint_segment(path, self.root, sealed=True)
            expected = manifest_fingerprints.get(relative)
            if expected is None:
                fingerprint_mismatches.append({"path": relative, "reason": "absent_from_manifest"})
                continue
            if recomputed.sha256 != expected["sha256"]:
                fingerprint_mismatches.append(
                    {
                        "path": relative,
                        "reason": "sha256_changed",
                        "expected": expected["sha256"],
                        "recomputed": recomputed.sha256,
                    }
                )
                continue
            if recomputed.row_count != expected["row_count"]:
                fingerprint_mismatches.append(
                    {
                        "path": relative,
                        "reason": "row_count_changed",
                        "expected": expected["row_count"],
                        "recomputed": recomputed.row_count,
                    }
                )
                continue
            matches += 1

        # §32 — the digest has to be a function of the persisted bytes alone. It was
        # seeded here with the manifest's stream counters, while the report built the
        # digest it records by letting the aggregator tally the rows itself, so the
        # two digests carried different ``event_counts`` and could never agree: the
        # check reported a feature mismatch that was only the two call sites
        # disagreeing about an input. Both sides now tally the rows. The manifest is
        # still reconciled against that tally through ``event_count_match``, so
        # nothing that used to be checked stopped being checked.
        loss_windows, window = self.capture_bounds_from_manifest()
        aggregation = aggregate_dataset(
            self.iter_events,
            run_id=self.run_id,
            loss_windows=loss_windows,
            window=window,
        )
        digest = aggregation_digest(aggregation)
        recorded = self._load_recorded_aggregation()
        recorded_digest = recorded.get("digest") if recorded else None

        # A second, independent pass over the same bytes: same counters, same
        # book comparisons, same aggregation digest, or the replay is not
        # deterministic and the dataset is not evidence.
        second_repaired_box = [0]
        _, second_counts, second_comparisons, _, _, second_trade_state = self._reconstruct(
            (row for row, _ in self.iter_rows()), second_repaired_box
        )
        second_aggregation = aggregate_dataset(
            self.iter_events,
            run_id=self.run_id,
            loss_windows=loss_windows,
            window=window,
        )
        second_digest = aggregation_digest(second_aggregation)
        deterministic = (
            second_digest == digest
            and second_counts == counts
            and second_repaired_box[0] == repaired_rows
            and second_trade_state == trade_state
            and json.dumps([c.as_dict() for c in second_comparisons], sort_keys=True)
            == json.dumps([c.as_dict() for c in comparisons], sort_keys=True)
            and second_digest == aggregation_digest(second_aggregation)
        )

        return ReplayVerification(
            run_id=self.run_id,
            root=str(self.root),
            segments=len(self.segment_files()),
            rows=rows_seen,
            partial_tails=partial_tails,
            internet_access=False,
            event_counts=counts,
            manifest_event_counts=manifest_counts,
            event_count_match=not differences,
            event_count_differences=differences,
            trade_sequence_ok=not violations,
            trade_sequence_violations=violations[:50],
            trade_sequence_violation_count=len(violations),
            repaired_trade_rows=repaired_rows,
            trade_unresolved_holes=int(trade_state["unresolved_holes"]),
            trade_hole_tracker_saturated=bool(trade_state["saturated"]),
            trade_chains={str(k): dict(v) for k, v in trade_state["chains"].items()},
            books=comparisons,
            book_match=all(c.ok for c in comparisons),
            fingerprint_checks=checks,
            fingerprint_matches=matches,
            fingerprint_mismatches=fingerprint_mismatches,
            fingerprints_match=not fingerprint_mismatches,
            aggregation_digest=digest,
            recorded_aggregation_digest=recorded_digest,
            feature_match=(None if recorded_digest is None else bool(recorded_digest == digest)),
            deterministic=deterministic,
            second_pass_digest=second_digest,
            series=series,
            errors=[],
            version=REPLAY_VERSION,
        )

    def _load_recorded_aggregation(self) -> dict[str, Any] | None:
        path = self.root / "aggregation" / f"{self.run_id}.json"
        if not path.exists():
            return None
        payload = load_json(path)
        return payload if isinstance(payload, dict) else None

    def capture_bounds_from_manifest(
        self,
    ) -> tuple[dict[str, list[tuple[int, int]]], dict[str, tuple[int, int]]]:
        loss: dict[str, list[tuple[int, int]]] = {}
        window: dict[str, tuple[int, int]] = {}
        for gap in self.manifest.get("gaps", []):
            if not gap.get("data_lost"):
                continue
            key = f"{gap['market']}/{gap['symbol']}"
            loss.setdefault(key, []).append((int(gap["start_ms"]), int(gap["end_ms"])))
        for stream in self.manifest.get("streams", []):
            key = f"{stream['market']}/{stream['symbol']}"
            start = stream.get("first_receive_time")
            end = stream.get("last_receive_time")
            if start is None or end is None:
                continue
            current = window.get(key)
            window[key] = (
                min(current[0], start) if current else start,
                max(current[1], end) if current else end,
            )
        # A capture window is only usable if it is bounded on both sides.
        for key in list(loss):
            window.setdefault(key, (0, 0))
        return loss, window


def _compare_checkpoint(persisted: RawEvent, replayed: Any) -> list[str]:
    """Field-by-field comparison of a persisted vs reconstructed checkpoint."""
    detail = persisted.detail or {}
    checks = [
        (
            "last_update_id",
            persisted.sequence.last if persisted.sequence else None,
            replayed.last_update_id,
        ),
        ("best_bid", persisted.bid, replayed.best_bid),
        ("best_ask", persisted.ask, replayed.best_ask),
        ("mid", detail.get("mid"), replayed.mid),
        ("spread_bps", detail.get("spread_bps"), replayed.spread_bps),
        ("depth_imbalance", detail.get("depth_imbalance"), replayed.depth_imbalance),
        ("microprice", detail.get("microprice"), replayed.microprice),
        ("best_bid_qty", persisted.bid_qty, replayed.best_bid_qty),
        ("best_ask_qty", persisted.ask_qty, replayed.best_ask_qty),
        ("bid_depth_notional", detail.get("bid_depth_notional"), replayed.bid_depth_n),
        ("ask_depth_notional", detail.get("ask_depth_notional"), replayed.ask_depth_n),
        ("bid_levels", detail.get("bid_levels"), replayed.bid_levels),
        ("ask_levels", detail.get("ask_levels"), replayed.ask_levels),
        ("health", detail.get("health"), replayed.health.value),
    ]
    return [
        f"{name}: persisted={expected!r} replayed={actual!r}"
        for name, expected, actual in checks
        if expected != actual
    ]


def replay_microstructure_dataset(
    root: Path | str, run_id: str | None = None
) -> ReplayVerification:
    """Reconstruct a forward dataset offline and verify it against the manifest.

    Never touches the network; a caller that needs network access has a bug.
    """
    return ForwardReplay(root, run_id).replay()
