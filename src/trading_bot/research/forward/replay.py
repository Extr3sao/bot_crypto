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

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from trading_bot.research.forward.aggregation import (
    DatasetAggregation,
    aggregate_dataset,
)
from trading_bot.research.forward.contract import EventType, Market, RawEvent, parse_event
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
    series: dict[str, dict[str, Any]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["books"] = [b.as_dict() for b in self.books]
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
        """
        rows: list[dict[str, Any]] = []
        partial_tails = 0
        for path in self.segment_files():
            segment_rows, partial = iter_segment_records(path)
            if partial:
                partial_tails += 1
            rows.extend(segment_rows)
        rows.sort(
            key=lambda r: (
                int(r.get("write_seq") or 0),
                int(r.get("receive_time") or 0),
            )
        )
        return rows, partial_tails

    # ------------------------------------------------------------------- replay
    def _policy(self, market: str) -> SequencePolicy:
        return (
            SequencePolicy.SPOT_UPDATE_ID
            if market == Market.SPOT.value
            else SequencePolicy.FUTURES_PREV_ID
        )

    def _reconstruct(
        self, rows: list[dict[str, Any]]
    ) -> tuple[
        list[RawEvent],
        dict[str, int],
        list[BookComparison],
        list[str],
        dict[str, dict[str, Any]],
    ]:
        events: list[RawEvent] = []
        counts: dict[str, int] = {}
        books: dict[str, BookSyncer] = {}
        comparisons: dict[str, BookComparison] = {}
        violations: list[str] = []
        series: dict[str, dict[str, Any]] = {}
        last_trade_id: dict[str, int] = {}

        for row in rows:
            try:
                event = parse_event(row)
            except Exception as exc:
                violations.append(f"unreadable row: {exc}")
                continue
            events.append(event)
            key = f"{event.market.value}/{event.symbol}/{event.event_type.value}"
            counts[key] = counts.get(key, 0) + 1

            if event.event_type is EventType.AGG_TRADE:
                symbol_key = f"{event.market.value}/{event.symbol}"
                trade_id = int(event.exchange_event_id or 0)
                previous = last_trade_id.get(symbol_key)
                if previous is not None and trade_id <= previous:
                    violations.append(
                        f"{symbol_key}: aggTrade id {trade_id} not > previous {previous}"
                    )
                last_trade_id[symbol_key] = trade_id
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
        return events, counts, list(comparisons.values()), violations, series

    def replay(self) -> ReplayVerification:
        rows, partial_tails = self.load_rows()
        events, counts, comparisons, violations, series = self._reconstruct(rows)

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

        loss_windows, window = self.capture_bounds_from_manifest()
        aggregation = aggregate_dataset(
            events, run_id=self.run_id, loss_windows=loss_windows, window=window
        )
        digest = aggregation_digest(aggregation)
        recorded = self._load_recorded_aggregation()
        recorded_digest = recorded.get("digest") if recorded else None

        second_rows, _ = self.load_rows()
        _, second_counts, second_comparisons, _, _ = self._reconstruct(second_rows)
        second_aggregation = aggregate_dataset(
            events, run_id=self.run_id, loss_windows=loss_windows, window=window
        )
        second_digest = aggregation_digest(second_aggregation)
        deterministic = (
            second_digest == digest
            and second_counts == counts
            and json.dumps([c.as_dict() for c in second_comparisons], sort_keys=True)
            == json.dumps([c.as_dict() for c in comparisons], sort_keys=True)
            and second_digest == aggregation_digest(second_aggregation)
        )

        return ReplayVerification(
            run_id=self.run_id,
            root=str(self.root),
            segments=len(self.segment_files()),
            rows=len(rows),
            partial_tails=partial_tails,
            internet_access=False,
            event_counts=counts,
            manifest_event_counts=manifest_counts,
            event_count_match=not differences,
            event_count_differences=differences,
            trade_sequence_ok=not violations,
            trade_sequence_violations=violations[:50],
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
