"""Independent verification of MICROSTRUCTURE-FORWARD-COLLECTION-V1.

BUILDER != VERIFIER (§53, §54). This module is invoked by
``scripts/research_verification.py`` and it does not modify the audited code or
the audited dataset: it only reads raw bytes and writes its own report.

Nothing here trusts a builder figure. Specifically:

* every segment fingerprint is recomputed from the file's raw bytes;
* the order book is rebuilt by a **second, separate implementation** written
  for this file, and compared against every persisted checkpoint — if the two
  disagree, the collector's book is not verified;
* the aggregate-trade id chain, the timestamp invariant and the transport of
  every high-frequency row are re-derived from the rows themselves;
* replay is re-run with sockets disabled to prove it cannot reach the network;
* the phase diff is checked against the list of modules this phase must never
  touch (RiskManager, PaperBroker, StrategyRouter, DecisionEngine, Portfolio,
  Reconciliation, DecisionTrace, Outcome contract).

Emits ``docs/MICROSTRUCTURE_FORWARD_COLLECTION_INDEPENDENT_VERIFICATION.{json,md}``.
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import gzip
import hashlib
import heapq
import importlib.util
import json
import os
import socket
import subprocess
import sys
import tempfile
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

DOCS = ROOT / "docs"
#: The captured bytes are external to the repository (``reports/*`` is ignored),
#: so a verification run in a fresh worktree reads the dataset from an explicit
#: root while the *code* under test stays the worktree's own checkout. The
#: resolved value is recorded in the payload, so the isolation claim is auditable
#: rather than implied.
FORWARD_ROOT = Path(
    os.environ.get("FORWARD_CAPTURE_ROOT") or ROOT / "reports" / "microstructure-forward"
)
FORWARD_PACKAGE_DIR = ROOT / "src" / "trading_bot" / "research" / "forward"
CLI = ROOT / "scripts" / "forward_collector.py"

#: HEAD this phase started from. The phase diff is measured against it.
FORWARD_PHASE_BASE = "faf39927b153da2e7e6c1ef532ddd031da00e7c7"

#: §36: a technical forward capture worth calling operational.
REQUIRED_CAPTURE_SECONDS = 3600.0

#: §10: documented tolerance for venue clock skew.
CLOCK_TOLERANCE_MS = 500

#: Cross-stream receive-time inversions come from the writer's own bookkeeping
#: rows being stamped at the instant of detection and interleaved with the rows
#: that triggered them (observed worst: 2 ms). A real ordering failure is orders
#: of magnitude larger — this run's own delivery p95 is 32 s — so a small
#: tolerance separates stamping resolution from an out-of-order write without
#: hiding one. Per-stream monotonicity is enforced strictly on top of it.
CROSS_STREAM_TOLERANCE_MS = 50

#: §3: files this phase must never have touched.
PROTECTED_PREFIXES = (
    "src/trading_bot/risk/",
    "src/trading_bot/paper/",
    "src/trading_bot/execution/",
    "src/trading_bot/autonomous/",
    "src/trading_bot/portfolio/",
    "src/trading_bot/strategies/",
    "src/trading_bot/scanner/",
    "src/trading_bot/feedback/",
    "config/risk.yaml",
)

FORBIDDEN_MODULE_PREFIXES = (
    "trading_bot.risk",
    "trading_bot.paper",
    "trading_bot.execution",
    "trading_bot.autonomous",
    "trading_bot.portfolio",
    "trading_bot.strategies",
    "trading_bot.scanner",
    "trading_bot.backtesting",
    "trading_bot.feedback",
    "trading_bot.market_structure",
)

REQUIRED_EVENT_FIELDS = (
    "schema_version",
    "contract_version",
    "collector_version",
    "source",
    "market",
    "symbol",
    "stream",
    "event_type",
    "transport",
    "run_id",
    "write_seq",
    "exchange_event_id",
    "exchange_event_time",
    "receive_time",
    "process_time",
    "network_delay_ms",
    "processing_delay_ms",
    "clock_skew_ms",
    "sequence",
    "raw_reference",
    "raw",
)

LOSSLESS_EVENT_TYPES = ("agg_trade", "depth_diff", "book_ticker")

BANNED_OUTPUT_TOKENS = (
    "paper_candidate",
    "profitable",
    "live_ready",
    "PROFITABLE",
    "LIVE_READY",
)

ALLOWED_FINAL_STATUSES = (
    "MICROSTRUCTURE_FORWARD_DATA_VERIFIED",
    "MICROSTRUCTURE_FORWARD_DATA_PARTIAL",
    "MICROSTRUCTURE_FORWARD_DATA_FAILED",
)


# --------------------------------------------------------------------- plumbing


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(args: list[str]) -> str:
    """Run git and decode its output as UTF-8.

    The default text mode decodes with the platform locale codec, which on this
    host is cp1252: a source file containing ``§`` or ``Ⓢ`` then differs from the
    same file read as UTF-8 on *every* line, and a byte-comparison check would
    report that every symbol had changed. Decoding both sides the same way is
    what makes the comparison mean something.
    """
    out = subprocess.run(
        ["git", *args],
        capture_output=True,
        cwd=str(ROOT),
        check=False,
        encoding="utf-8",
        errors="replace",
    )
    return out.stdout.strip()


def git_file(revision: str, relative: str) -> str:
    """The exact content of ``relative`` at ``revision``, UTF-8, unstripped."""
    out = subprocess.run(
        ["git", "show", f"{revision}:{relative}"],
        capture_output=True,
        cwd=str(ROOT),
        check=False,
        encoding="utf-8",
        errors="replace",
    )
    return out.stdout


def latest_run_id() -> str | None:
    manifest_dir = FORWARD_ROOT / "manifest"
    if not manifest_dir.is_dir():
        return None
    candidates = sorted(manifest_dir.glob("*.json"))
    return candidates[-1].stem if candidates else None


def read_segment_rows(path: Path) -> tuple[list[dict[str, Any]], bool]:
    """Independent JSONL/gzip reader. Returns ``(rows, partial_tail)``.

    Hand-rolled on purpose: verifying a file with the same code that wrote it
    proves nothing, so this shares no logic with the builder's storage module.
    """
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8", newline="") as compressed:
            return _consume(compressed)
    with path.open("r", encoding="utf-8", newline="") as plain:
        return _consume(plain)


def _consume(handle: Any) -> tuple[list[dict[str, Any]], bool]:
    rows: list[dict[str, Any]] = []
    partial = False
    try:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                partial = True
                continue
            if isinstance(payload, dict):
                rows.append(payload)
            else:
                partial = True
    except (EOFError, OSError):
        # A gzip member without a trailer (an open segment, or a crash) is a
        # partial tail, not a reason to discard the rows before it.
        partial = True
    return rows, partial


def segment_files() -> list[Path]:
    return sorted(
        set((FORWARD_ROOT / "segments").rglob("*.jsonl"))
        | set((FORWARD_ROOT / "segments").rglob("*.jsonl.gz"))
    )


def _rows_of(path: Path) -> Iterator[tuple[dict[str, Any] | None, bool]]:
    """Stream one segment's rows: ``(row, partial_tail)`` per line."""
    with contextlib.ExitStack() as stack:
        handle: Any = (
            stack.enter_context(gzip.open(path, "rt", encoding="utf-8", newline=""))
            if path.suffix == ".gz"
            else stack.enter_context(path.open("r", encoding="utf-8", newline=""))
        )
        try:
            yield from _lines_of(handle)
        except (EOFError, OSError):
            # A gzip member without a trailer (an open segment, or a crash) is a
            # partial tail, not a reason to discard the rows before it.
            yield None, True


def _lines_of(handle: Any) -> Iterator[tuple[dict[str, Any] | None, bool]]:
    """Parse one handle into rows, flagging the first unreadable line as a tail."""
    for line in handle:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            yield None, True
            return
        yield (payload, False) if isinstance(payload, dict) else (None, True)


def _clean_rows(
    source: Iterator[tuple[dict[str, Any] | None, bool]], truncated: list[int]
) -> Iterator[dict[str, Any]]:
    """Drop unreadable rows while remembering that the segment had a bad tail."""
    for row, tail in source:
        if tail:
            truncated[0] = 1
            continue
        if row is not None:
            yield row


def count_segment_rows(path: Path) -> tuple[int, bool]:
    """Row count straight off the bytes, without materialising the segment."""
    count = 0
    partial = False
    for row, tail in _rows_of(path):
        if tail:
            partial = True
        if row is not None:
            count += 1
    return count, partial


@dataclass
class Evidence:
    """Everything the checks below need, from one streaming pass (§34).

    A forward hour is millions of rows, so the verifier may not hold them: it
    accumulates counters and keeps only the two things that are inherently small
    (the timestamp distributions it must compute percentiles from, and the book
    rows needed for the independent reconstruction).
    """

    files: list[Path] = field(default_factory=list)
    rows: int = 0
    partial_tails: int = 0
    missing_fields: dict[str, int] = field(default_factory=dict)
    schema_versions: set[str] = field(default_factory=set)
    transport_violations: int = 0
    raw_absent: int = 0
    #: Delay distributions as value -> count. A verifier that keeps one entry per
    #: row cannot verify a capture larger than its own memory, and one busy stream
    #: is ~10^6 rows/hour, so the distribution is bucketed by exact millisecond
    #: value instead. Percentiles from it are identical to the sorted-list ones.
    delay_counts: dict[int, int] = field(default_factory=dict)
    live_delay_counts: dict[int, int] = field(default_factory=dict)
    negative_processing: int = 0
    #: Rows whose receive time is earlier than the highest receive time already
    #: seen anywhere. Cross-stream write order is not a contract guarantee: the
    #: writer's own bookkeeping rows (``gap``/``lifecycle``) are stamped with the
    #: instant of detection and interleave with the rows that caused them, so two
    #: streams can invert within the same millisecond. What the contract does
    #: guarantee is per-stream monotonicity, which is what is enforced.
    back_in_time: int = 0
    #: Rows that go backwards within their own stream. This must be zero.
    stream_back_in_time: int = 0
    #: Worst cross-stream inversion seen, in milliseconds.
    worst_cross_stream_ms: int = 0
    #: Last receive time per stream, to check each stream against itself.
    stream_receive: dict[str, int] = field(default_factory=dict)
    labelled_backfilled: int = 0
    #: Downtime windows re-derived from the persisted lifecycle rows: a
    #: WS_DISCONNECTED for a market paired with the next WS_CONNECTED for the same
    #: market. The report adds these to the gap windows to get degraded time, so an
    #: independent derivation is what lets the verifier check that arithmetic
    #: instead of reading its own answer back out of the report.
    downtime_open: dict[str, int] = field(default_factory=dict)
    downtime_windows: list[tuple[int, int]] = field(default_factory=list)
    disconnected_without_reconnect: int = 0
    counts: dict[str, int] = field(default_factory=dict)
    #: event_type -> transport -> rows, re-derived from the rows themselves.
    transports: dict[str, dict[str, int]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(int))
    )
    run_ids: set[str] = field(default_factory=set)
    ids: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: The independent book reconstruction is applied *as the rows stream past*,
    #: so nothing per-row is retained: state is one book per (market, symbol).
    books: BookRebuilder = field(default_factory=lambda: BookRebuilder())

    def id_entry(self, key: str) -> dict[str, Any]:
        return self.ids.setdefault(
            key,
            {
                "rows": 0,
                "seen": set(),
                "min": None,
                "max": None,
                "duplicates": 0,
                "regressions": 0,
                "repaired_out_of_order": 0,
                "jumps": 0,
                "max_jump": 0,
                "last": None,
            },
        )


#: Book-related rows are kept for the independent reconstruction. They are three
#: streams of one symbol, not the whole dataset, so this list stays small.
BOOK_EVENT_TYPES = ("depth_diff", "depth_snapshot", "book_checkpoint")


def collect_evidence() -> Evidence:
    """One streaming pass over every persisted row, in the collector's order."""
    evidence = Evidence(files=segment_files())
    boxes: list[list[int]] = []
    streams: list[Iterator[dict[str, Any]]] = []
    for path in evidence.files:
        truncated: list[int] = [0]
        boxes.append(truncated)
        streams.append(_clean_rows(_rows_of(path), truncated))

    merged = heapq.merge(*streams, key=_row_order) if streams else iter(())
    previous_receive = -1
    known_fields = tuple(REQUIRED_EVENT_FIELDS)
    for row in merged:
        evidence.rows += 1
        evidence.schema_versions.add(str(row.get("schema_version")))
        for name in known_fields:
            if name not in row:
                evidence.missing_fields[name] = evidence.missing_fields.get(name, 0) + 1
        event_type = row.get("event_type")
        if event_type in LOSSLESS_EVENT_TYPES and row.get("transport") != "ws":
            evidence.transport_violations += 1
        if event_type in LOSSLESS_EVENT_TYPES and row.get("raw") is None:
            evidence.raw_absent += 1
        evidence.run_ids.add(str(row.get("run_id")))
        key = f"{row.get('market')}/{row.get('symbol')}/{row.get('event_type')}"
        evidence.counts[key] = evidence.counts.get(key, 0) + 1
        if isinstance(event_type, str):
            evidence.transports[event_type][str(row.get("transport"))] += 1

        receive = int(row.get("receive_time") or 0)
        process = int(row.get("process_time") or 0)
        if process < receive:
            evidence.negative_processing += 1
        if receive < previous_receive:
            evidence.back_in_time += 1
            evidence.worst_cross_stream_ms = max(
                evidence.worst_cross_stream_ms, previous_receive - receive
            )
        previous_receive = max(previous_receive, receive)
        stream_previous = evidence.stream_receive.get(key)
        if stream_previous is not None and receive < stream_previous:
            evidence.stream_back_in_time += 1
        evidence.stream_receive[key] = max(receive, stream_previous or receive)
        event_time = row.get("exchange_event_time")

        detail = row.get("detail")
        origin = detail.get("origin") if isinstance(detail, dict) else None
        if event_type == "lifecycle" and isinstance(detail, dict):
            kind = detail.get("kind")
            lifecycle_market = detail.get("market")
            if isinstance(lifecycle_market, str):
                if kind == "WS_DISCONNECTED":
                    evidence.downtime_open[lifecycle_market] = receive
                elif kind == "WS_CONNECTED":
                    opened = evidence.downtime_open.pop(lifecycle_market, None)
                    if opened is not None and receive > opened:
                        evidence.downtime_windows.append((opened, receive))
        backfilled = origin == "agg_trade_backfill"
        if backfilled:
            evidence.labelled_backfilled += 1
        if isinstance(event_time, int):
            delay = receive - event_time
            evidence.delay_counts[delay] = evidence.delay_counts.get(delay, 0) + 1
            if not backfilled:
                evidence.live_delay_counts[delay] = evidence.live_delay_counts.get(delay, 0) + 1

        if event_type == "agg_trade":
            stream_key = f"{row.get('market')}/{row.get('symbol')}"
            entry = evidence.id_entry(stream_key)
            trade_id = int(row.get("exchange_event_id") or 0)
            entry["rows"] += 1
            entry["seen"].add(trade_id)
            entry["min"] = trade_id if entry["min"] is None else min(entry["min"], trade_id)
            entry["max"] = trade_id if entry["max"] is None else max(entry["max"], trade_id)
            last = entry["last"]
            if last is not None:
                if trade_id == last:
                    entry["duplicates"] += 1
                elif trade_id < last:
                    # A repaired row is written when the public index answers,
                    # which can be after the live stream already moved past it:
                    # that is the §4 property (logical order by id, not by write
                    # order), not a corrupted chain. A *live* row that goes
                    # backwards would be corruption, and is counted as such.
                    if backfilled:
                        entry["repaired_out_of_order"] += 1
                    else:
                        entry["regressions"] += 1
                elif trade_id > last + 1:
                    entry["jumps"] += 1
                    entry["max_jump"] = max(entry["max_jump"], trade_id - last - 1)
            entry["last"] = max(trade_id, last if last is not None else trade_id)
        elif event_type in BOOK_EVENT_TYPES:
            evidence.books.feed(row)

    evidence.partial_tails = sum(box[0] for box in boxes)
    return evidence


def _histogram_percentile(counts: dict[int, int], fraction: float) -> float | None:
    """Nearest-rank percentile with interpolation, over a value -> count mapping.

    Reimplemented here rather than imported: a verifier that borrows the
    builder's arithmetic is checking the builder against itself. The answer is
    the same one ``sorted(values)`` interpolation gives.
    """
    total = sum(counts.values())
    if total == 0:
        return None
    values = sorted(counts)
    if total == 1:
        return float(values[0])

    def at(index: int) -> float:
        seen = 0
        for value in values:
            seen += counts[value]
            if seen > index:
                return float(value)
        return float(values[-1])

    rank = fraction * (total - 1)
    lower = int(rank)
    upper = min(lower + 1, total - 1)
    weight = rank - lower
    return at(lower) * (1.0 - weight) + at(upper) * weight


def _row_order(row: dict[str, Any]) -> tuple[int, int]:
    """The collector's ordering, re-derived by the verifier independently."""
    return int(row.get("write_seq") or 0), int(row.get("receive_time") or 0)


# ------------------------------------------------- independent book reconstruction


#: The health labels that mean "this state is coherent": the book may be old, but
#: its contents are the result of an unbroken chain.
COHERENT_HEALTH = ("HEALTHY", "STALE")

#: The health labels under which the collector itself refuses to feed features
#: from the book (``detail.feature_usable`` is false). A rebuild from a live chain
#: is not evidence about such a book, so those checkpoints are classified and
#: traced rather than graded as equal or unequal.
UNUSABLE_HEALTH = ("INVALID", "RECOVERING")


class _BookState:
    """One book, rebuilt by the verifier's own implementation."""

    __slots__ = (
        "asks",
        "bids",
        "checkpoints",
        "declared_unusable",
        "health_tally",
        "healthy_while_chain_broken",
        "last_id",
        "live",
        "matches",
        "mismatches",
        "unusable_difference_examples",
        "unusable_differences",
        "unusable_open",
        "unusable_windows",
        "unverifiable",
    )

    def __init__(self) -> None:
        self.bids: dict[Decimal, Decimal] = {}
        self.asks: dict[Decimal, Decimal] = {}
        self.last_id: int | None = None
        self.live = False
        self.checkpoints = 0
        self.matches = 0
        self.unverifiable = 0
        self.mismatches: list[dict[str, Any]] = []
        self.healthy_while_chain_broken = 0
        self.declared_unusable = 0
        self.health_tally: dict[str, int] = {}
        self.unusable_differences = 0
        self.unusable_difference_examples: list[dict[str, Any]] = []
        self.unusable_windows: list[dict[str, Any]] = []
        self.unusable_open: dict[str, Any] | None = None


class BookRebuilder:
    """Rebuild every book with a second implementation, as the rows stream past.

    This is deliberately *not* the collector's algorithm restated: it walks a
    snapshot forward and refuses to evaluate a checkpoint whose chain is broken,
    requiring that the collector also declined to call such a book HEALTHY.

    A checkpoint the *collector* declared unusable is a different case again. The
    collector refuses to feed features from an INVALID/RECOVERING book, so its
    persisted fields are the record of a state it has already disowned: comparing
    them with a live rebuild produces a difference that means nothing. Those
    checkpoints are counted, their differences recorded, and the state is held to
    the §8 obligation instead — it must end, and an INVALID book must come back
    through a snapshot fresher than the one it discarded.

    Rows are consumed one at a time and never retained. A book's state depends
    only on its own rows and the order among them is preserved by the global
    write order, so feeding interleaved rows is equivalent to grouping first —
    which is what lets the verifier run on a capture larger than its own memory.
    """

    def __init__(self) -> None:
        self._books: dict[str, _BookState] = {}
        self.rows_fed = 0
        self.rows_ignored = 0

    def feed(self, row: dict[str, Any]) -> None:
        kind = row.get("event_type")
        if kind not in ("depth_diff", "depth_snapshot", "book_checkpoint"):
            self.rows_ignored += 1
            return
        self.rows_fed += 1
        key = f"{row.get('market')}/{row.get('symbol')}"
        state = self._books.setdefault(key, _BookState())

        if kind == "depth_snapshot":
            snapshot_id = row.get("exchange_event_id")
            if snapshot_id is None:
                return
            state.bids = _levels(row.get("bids"))
            state.asks = _levels(row.get("asks"))
            state.last_id = int(snapshot_id)
            state.live = False
            # §8: a book the collector declared INVALID must come back through a
            # snapshot that is *newer* than the state it discarded. A snapshot at
            # or below that id would put the same stale state back.
            for window in state.unusable_windows:
                if window["health"] != "INVALID" or window["fresh_snapshot_after"]:
                    continue
                discarded = window["last_update_id"]
                if discarded is None or int(snapshot_id) > discarded:
                    window["fresh_snapshot_after"] = True
            return

        if kind == "depth_diff":
            sequence = row.get("sequence") or {}
            first = sequence.get("first")
            last = sequence.get("last")
            prev = sequence.get("prev")
            if state.last_id is None or first is None or last is None:
                state.live = False
                return
            # The two markets chain depth differently and the row records which
            # one applies. Futures chains by ``pu``: ``U`` is deliberately not
            # contiguous with the last applied id because the venue consumes ids
            # on events the book does not publish, so requiring
            # ``U <= last_id + 1 <= u`` alone declares a perfectly healthy
            # futures chain broken. Spot chains contiguously and carries
            # ``prev = None``. An independent rebuild that only knew the spot
            # rule would report every futures checkpoint unverifiable while
            # finding no mismatch — which is exactly what this check used to do.
            contiguous = int(first) <= int(state.last_id) + 1 <= int(last)
            chained = prev is not None and int(prev) == int(state.last_id)
            if not (contiguous or chained):
                state.live = False
                return
            for price, qty in _levels(row.get("bids")).items():
                state.bids.pop(price, None) if qty == 0 else state.bids.__setitem__(price, qty)
            for price, qty in _levels(row.get("asks")).items():
                state.asks.pop(price, None) if qty == 0 else state.asks.__setitem__(price, qty)
            state.last_id = int(last)
            state.live = True
            return

        state.checkpoints += 1
        detail = row.get("detail") or {}
        health = detail.get("health")
        tallied = str(health)
        state.health_tally[tallied] = state.health_tally.get(tallied, 0) + 1
        declared_unusable = health in UNUSABLE_HEALTH
        if declared_unusable:
            if state.unusable_open is None or state.unusable_open["health"] != health:
                state.unusable_open = {
                    "health": health,
                    "at_ms": row.get("receive_time"),
                    "last_update_id": (row.get("sequence") or {}).get("last"),
                    "fresh_snapshot_after": False,
                    "closed": False,
                    "next_health": None,
                }
                state.unusable_windows.append(state.unusable_open)
        elif state.unusable_open is not None:
            # Any coherent label ends the window: the state the collector refused
            # to trust must not be the state it later called coherent.
            state.unusable_open["closed"] = True
            state.unusable_open["next_health"] = health
            state.unusable_open = None

        if not state.live:
            # The collector must not have claimed health here either.
            if health == "HEALTHY":
                state.healthy_while_chain_broken += 1
            state.unverifiable += 1
            return
        rebuilt = _checkpoint_from(
            state.bids,
            state.asks,
            state.last_id,
            int(detail.get("depth_n") or 10),
        )
        differences = _compare(row, rebuilt)
        if declared_unusable:
            # The collector declared this state unusable, so a difference here is
            # expected rather than a defect; it is counted and exemplified so the
            # number is visible instead of being laundered into a pass.
            state.declared_unusable += 1
            if differences:
                state.unusable_differences += 1
                if len(state.unusable_difference_examples) < 3:
                    state.unusable_difference_examples.append(
                        {
                            "at_ms": row.get("receive_time"),
                            "health": health,
                            "differences": differences[:4],
                        }
                    )
            return
        if differences:
            state.mismatches.append({"at_ms": row.get("receive_time"), "differences": differences})
        else:
            state.matches += 1

    def summary(self) -> dict[str, Any]:
        return {
            key: {
                "checkpoints": state.checkpoints,
                "health_tally": dict(sorted(state.health_tally.items())),
                "matches": state.matches,
                "unverifiable": state.unverifiable,
                "declared_unusable": state.declared_unusable,
                "not_usable_differences": state.unusable_differences,
                "not_usable_difference_examples": state.unusable_difference_examples,
                "mismatches": len(state.mismatches),
                "mismatch_examples": state.mismatches[:3],
                "healthy_while_chain_broken": state.healthy_while_chain_broken,
                "unusable_windows": [dict(window) for window in state.unusable_windows],
                "invalid_without_fresh_snapshot": [
                    window
                    for window in state.unusable_windows
                    if window["health"] == "INVALID" and not window["fresh_snapshot_after"]
                ],
                "unusable_windows_still_open": sum(
                    1 for window in state.unusable_windows if not window["closed"]
                ),
                "ok": not state.mismatches
                and state.healthy_while_chain_broken == 0
                and all(window["closed"] for window in state.unusable_windows)
                and all(
                    window["fresh_snapshot_after"]
                    for window in state.unusable_windows
                    if window["health"] == "INVALID"
                ),
            }
            for key, state in sorted(self._books.items())
        }


def independent_book_agreement(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Compatibility wrapper: feed a materialised list, then read the summary."""
    rebuilder = BookRebuilder()
    for row in rows:
        rebuilder.feed(row)
    return rebuilder.summary()


def _levels(raw: object) -> dict[Decimal, Decimal]:
    levels: dict[Decimal, Decimal] = {}
    if not isinstance(raw, list):
        return levels
    for level in raw:
        if not isinstance(level, (list, tuple)) or len(level) < 2:
            continue
        try:
            levels[Decimal(str(level[0]))] = Decimal(str(level[1]))
        except (InvalidOperation, ValueError):
            continue
    return levels


def _checkpoint_from(
    bids: dict[Decimal, Decimal], asks: dict[Decimal, Decimal], last_id: int | None, depth_n: int
) -> dict[str, Any]:
    if not bids or not asks:
        return {}
    best_bid = max(bids)
    best_ask = min(asks)
    mid = (best_bid + best_ask) / 2
    bid_notional = sum(
        (p * q for p, q in sorted(bids.items(), key=lambda kv: kv[0], reverse=True)[:depth_n]),
        Decimal(0),
    )
    ask_notional = sum(
        (p * q for p, q in sorted(asks.items(), key=lambda kv: kv[0])[:depth_n]), Decimal(0)
    )
    total = bid_notional + ask_notional
    bid_qty = bids[best_bid]
    ask_qty = asks[best_ask]
    top_total = bid_qty + ask_qty
    return {
        "last_update_id": last_id,
        "best_bid": str(best_bid),
        "best_ask": str(best_ask),
        "best_bid_qty": str(bid_qty),
        "best_ask_qty": str(ask_qty),
        "mid": str(mid),
        "spread_bps": str((best_ask - best_bid) / mid * Decimal(10_000)) if mid > 0 else None,
        "bid_depth_notional": str(bid_notional),
        "ask_depth_notional": str(ask_notional),
        "depth_imbalance": str((bid_notional - ask_notional) / total) if total > 0 else None,
        "microprice": (
            str((best_bid * ask_qty + best_ask * bid_qty) / top_total) if top_total > 0 else None
        ),
        "bid_levels": len(bids),
        "ask_levels": len(asks),
    }


def _compare(row: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    if not expected:
        return []
    detail = row.get("detail") or {}
    sequence = row.get("sequence") or {}
    checks = [
        ("last_update_id", sequence.get("last"), expected["last_update_id"]),
        ("best_bid", row.get("bid"), expected["best_bid"]),
        ("best_ask", row.get("ask"), expected["best_ask"]),
        ("best_bid_qty", row.get("bid_qty"), expected["best_bid_qty"]),
        ("best_ask_qty", row.get("ask_qty"), expected["best_ask_qty"]),
        ("mid", detail.get("mid"), expected["mid"]),
        ("spread_bps", detail.get("spread_bps"), expected["spread_bps"]),
        ("bid_depth_notional", detail.get("bid_depth_notional"), expected["bid_depth_notional"]),
        ("ask_depth_notional", detail.get("ask_depth_notional"), expected["ask_depth_notional"]),
        ("depth_imbalance", detail.get("depth_imbalance"), expected["depth_imbalance"]),
        ("microprice", detail.get("microprice"), expected["microprice"]),
        ("bid_levels", detail.get("bid_levels"), expected["bid_levels"]),
        ("ask_levels", detail.get("ask_levels"), expected["ask_levels"]),
    ]
    return [
        f"{name}: persisted={actual!r} independently_rebuilt={want!r}"
        for name, actual, want in checks
        if actual != want
    ]


# ------------------------------------------------------------------- phase entry


def verify_forward_collection() -> dict[str, Any]:
    """Independently re-derive every claim of the forward collection phase."""
    checks: list[dict[str, Any]] = []
    failures: list[str] = []

    def record(name: str, expected: Any, observed: Any, ok: bool, note: str = "") -> None:
        checks.append(
            {"check": name, "expected": expected, "observed": observed, "pass": ok, "note": note}
        )
        if not ok:
            failures.append(name)

    run_id = latest_run_id()
    if run_id is None:
        record(
            "a forward capture exists to verify",
            "reports/microstructure-forward/manifest/<run_id>.json",
            "absent",
            False,
            note="copy reports/ into the worktree; it is gitignored by design",
        )
        return _result(checks, failures, {})

    manifest = json.loads(
        (FORWARD_ROOT / "manifest" / f"{run_id}.json").read_text(encoding="utf-8")
    )
    # One streaming pass: a forward hour is millions of rows and the verifier
    # must remain able to read it on a laptop (§34).
    evidence = collect_evidence()
    files = evidence.files
    partial_tails = evidence.partial_tails
    head = git(["rev-parse", "HEAD"])

    # 1. Source resolution: the discovery plane resolves from this repository and
    #    pulls in nothing from the trading runtime (§3, §55).
    module_sources: dict[str, str] = {}
    resolution_problems: list[str] = []
    for path in [*sorted(FORWARD_PACKAGE_DIR.glob("*.py")), CLI]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            module_name: str | None = None
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module_name = alias.name
                    if module_name.startswith("trading_bot"):
                        module_sources[module_name] = _resolve_source(module_name) or "UNRESOLVED"
            elif isinstance(node, ast.ImportFrom) and node.module:
                module_name = node.module
                if module_name.startswith("trading_bot"):
                    module_sources[module_name] = _resolve_source(module_name) or "UNRESOLVED"
            if module_name is None:
                continue
            if module_name.startswith("trading_bot") and not module_name.startswith(
                "trading_bot.research.forward"
            ):
                resolution_problems.append(f"{path.name}: {module_name}")
    for module_name in module_sources:
        for prefix in FORBIDDEN_MODULE_PREFIXES:
            if module_name == prefix or module_name.startswith(prefix + "."):
                resolution_problems.append(f"{module_name} (forbidden: {prefix})")
    unresolved = [name for name, source in module_sources.items() if source == "UNRESOLVED"]
    outside = [
        name
        for name, source in module_sources.items()
        if source != "UNRESOLVED" and not source.startswith(str(ROOT))
    ]
    record(
        "discovery plane resolves from this repository and imports no trading runtime",
        "no forbidden import, no unresolved module, no module outside the repository",
        {
            "modules": dict(sorted(module_sources.items())),
            "problems": resolution_problems,
            "unresolved": unresolved,
            "outside_repository": outside,
        },
        not resolution_problems and not unresolved and not outside,
    )

    # 2. Fingerprints recomputed from raw bytes.
    recorded = {entry["path"]: entry for entry in manifest.get("fingerprints", [])}
    fingerprint_problems: list[dict[str, Any]] = []
    for path in files:
        relative = path.relative_to(FORWARD_ROOT).as_posix()
        digest = sha256_file(path)
        entry = recorded.get(relative)
        if entry is None:
            fingerprint_problems.append({"path": relative, "reason": "absent_from_manifest"})
            continue
        segment_row_count, _ = count_segment_rows(path)
        if entry["sha256"] != digest:
            fingerprint_problems.append(
                {
                    "path": relative,
                    "reason": "sha256",
                    "expected": entry["sha256"],
                    "observed": digest,
                }
            )
        elif entry["row_count"] != segment_row_count:
            fingerprint_problems.append(
                {
                    "path": relative,
                    "reason": "row_count",
                    "expected": entry["row_count"],
                    "observed": segment_row_count,
                }
            )
    record(
        "every segment fingerprint matches the bytes on disk",
        f"{len(files)} segments, sha256 + row_count",
        {
            "segments_on_disk": len(files),
            "segments_in_manifest": len(recorded),
            "problems": fingerprint_problems[:10],
        },
        not fingerprint_problems and len(files) == len(recorded),
    )

    # 3. The capture is real and long enough (§36) and complete enough to trust.
    duration = float(manifest.get("duration_seconds") or 0.0)
    record(
        "the capture covers the required technical window",
        f">= {REQUIRED_CAPTURE_SECONDS:.0f}s with every lossless stream observed",
        {
            "duration_seconds": duration,
            "started_at": manifest.get("started_at"),
            "ended_at": manifest.get("ended_at"),
            "lossless_streams": {
                key: value["verdict"]
                for key, value in manifest.get("provider_stream_status", {}).items()
                if value.get("lossless")
            },
        },
        duration >= REQUIRED_CAPTURE_SECONDS,
    )

    # 4. Contract conformance, re-checked row by row while streaming from disk.
    keep_raw = bool(manifest.get("integrity", {}).get("keep_raw_payloads"))
    missing_fields = evidence.missing_fields
    schema_versions = evidence.schema_versions
    raw_absent = evidence.raw_absent if keep_raw else 0
    record(
        "every persisted row satisfies the raw event contract",
        "all contract fields present, one schema version, WS transport, raw kept",
        {
            "rows": evidence.rows,
            "schema_versions": sorted(schema_versions),
            "missing_field_counts": missing_fields,
            "high_frequency_rows_over_rest": evidence.transport_violations,
            "high_frequency_rows_without_raw": raw_absent,
            "keep_raw_payloads": keep_raw,
        },
        not missing_fields
        and schema_versions == {"forward-event-v1"}
        and not evidence.transport_violations
        and not raw_absent,
    )

    # 5. Timestamp integrity, re-derived from every row (§10).
    skews = evidence.delay_counts
    samples_with_clock = sum(skews.values())
    worst_negative = min(skews) if skews else 0
    record(
        "the temporal guarantee holds for every event carrying an exchange clock",
        "event_time <= receive_time + tolerance, process_time >= receive_time, "
        "receive_time strictly monotonic within each stream",
        {
            "rows_with_exchange_time": samples_with_clock,
            "worst_network_delay_ms": worst_negative,
            "max_network_delay_ms": max(skews) if skews else None,
            "clock_tolerance_ms": CLOCK_TOLERANCE_MS,
            "process_before_receive_rows": evidence.negative_processing,
            "per_stream_receive_time_regressions": evidence.stream_back_in_time,
            "cross_stream_inversions": evidence.back_in_time,
            "worst_cross_stream_inversion_ms": evidence.worst_cross_stream_ms,
            "cross_stream_note": (
                "inversions are the writer's own detection rows (gap/lifecycle) "
                "interleaved with the rows that triggered them, so they are bounded "
                "by the stamping resolution rather than by delivery; the enforced "
                "invariant is per-stream monotonicity"
            ),
            "cross_stream_tolerance_ms": CROSS_STREAM_TOLERANCE_MS,
            "manifest_clock_violations": manifest.get("integrity", {}).get("clock_violations"),
        },
        worst_negative >= -CLOCK_TOLERANCE_MS
        and evidence.negative_processing == 0
        and evidence.stream_back_in_time == 0
        and evidence.worst_cross_stream_ms <= CROSS_STREAM_TOLERANCE_MS
        and int(manifest.get("integrity", {}).get("clock_violations") or 0) == 0,
    )

    # 6. Aggregate trade id chain, re-derived independently of the collector.
    chain = {
        key: {
            name: entry[name]
            for name in (
                "rows",
                "duplicates",
                "regressions",
                "repaired_out_of_order",
                "jumps",
                "max_jump",
            )
        }
        for key, entry in evidence.ids.items()
    }
    record(
        "the aggregate trade id chain is observable and explained",
        "every id jump is declared as a gap in the manifest",
        {
            "per_stream": chain,
            "declared_sequence_gaps": manifest.get("integrity", {}).get("sequence_gaps"),
            "declared_gap_records": sum(
                1 for gap in manifest.get("gaps", []) if gap.get("reason") == "AGG_TRADE_ID_JUMP"
            ),
        },
        all(entry["duplicates"] == 0 and entry["regressions"] == 0 for entry in chain.values()),
    )

    # 7. The book, rebuilt by a second implementation while the rows streamed.
    #    Three classifications, because a persisted checkpoint is one of three
    #    things: a state the collector declared coherent (compared, and it must
    #    match), a state the collector itself declared unusable (traced, not
    #    graded — a rebuild from a live chain says nothing about it), or a state
    #    the verifier could not evaluate because *its* chain was broken (§8).
    book = evidence.books.summary()
    classified = {
        key: entry["matches"] + entry["unverifiable"] + entry["declared_unusable"]
        for key, entry in book.items()
    }
    record(
        "every book checkpoint is reproducible by an independent implementation",
        "coherent checkpoints (HEALTHY/STALE) match; unusable ones (INVALID/RECOVERING)"
        " are classified and every INVALID state is followed by a fresher snapshot;"
        " no HEALTHY claim on a broken chain; every checkpoint accounted for",
        {
            "books": book,
            "book_rows_streamed": evidence.books.rows_fed,
            "rows_retained_for_reconstruction": 0,
            "checkpoints_classified": classified,
            "unclassified_checkpoints": {
                key: entry["checkpoints"] - classified[key] for key, entry in book.items()
            },
        },
        bool(book)
        and all(entry["ok"] for entry in book.values())
        and all(classified[key] == entry["checkpoints"] for key, entry in book.items()),
    )

    # 8. Continuity is claimed only when nothing was actually lost (§27).
    integrity = manifest.get("integrity", {})
    data_lost_gaps = int(integrity.get("data_lost_gaps") or 0)
    continuity = manifest.get("continuity")
    record(
        "continuity is claimed only when no data was lost",
        "CONTINUOUS_DATA <=> zero data-loss gaps",
        {
            "continuity": continuity,
            "data_lost_gaps": data_lost_gaps,
            "data_lost_gap_seconds": integrity.get("data_lost_gap_seconds"),
            "recovered_gaps": integrity.get("recovered_gaps"),
            "gap_reasons": sorted({gap.get("reason") for gap in manifest.get("gaps", [])}),
        },
        (continuity == "CONTINUOUS_DATA") == (data_lost_gaps == 0),
    )

    # 9. Aggregate counts recomputed from disk.
    recounted = evidence.counts
    declared = {
        f"{entry['market']}/{entry['symbol']}/{entry['event_type']}": int(entry["events"])
        for entry in manifest.get("streams", [])
    }
    count_differences = {
        key: {"on_disk": recounted.get(key, 0), "in_manifest": declared.get(key, 0)}
        for key in sorted(set(recounted) | set(declared))
        if recounted.get(key, 0) != declared.get(key, 0)
    }
    record(
        "the manifest event counts are exactly what is on disk",
        "no stream differs",
        {
            "streams": len(declared),
            "rows_on_disk": evidence.rows,
            "differences": count_differences,
        },
        not count_differences,
    )

    # 10. Replay runs offline and agrees with the capture.
    replay_report = DOCS / "FORWARD_DATA_REPLAY_VALIDATION.json"
    replay_payload: dict[str, Any] = {}
    if replay_report.exists():
        replay_payload = json.loads(replay_report.read_text(encoding="utf-8"))
    offline_ok, offline_note = _replay_without_network(run_id)
    record(
        "replay reconstructs the capture without any network access",
        "no socket touched; event counts, book checkpoints and fingerprints agree",
        {
            "replay_run_id": replay_payload.get("run_id"),
            "offline_replay": offline_ok,
            "event_count_match": replay_payload.get("event_count_match"),
            "book_match": replay_payload.get("book_match"),
            "fingerprints_match": replay_payload.get("fingerprints_match"),
            "feature_match": replay_payload.get("feature_match"),
            "deterministic": replay_payload.get("deterministic"),
            "partial_tails": replay_payload.get("partial_tails"),
            "rows": replay_payload.get("rows"),
        },
        bool(replay_payload)
        and offline_ok
        and all(
            replay_payload.get(key) is True
            for key in (
                "event_count_match",
                "book_match",
                "fingerprints_match",
                "deterministic",
            )
        )
        and (replay_payload.get("feature_match") is not False)
        and int(replay_payload.get("partial_tails") or 0) == 0,
        note=offline_note,
    )

    # 11. The phase touched nothing on the trading path (§3, §54).
    changed = [
        line
        for line in git(["diff", "--name-only", FORWARD_PHASE_BASE, "HEAD"]).splitlines()
        if line.strip()
    ]
    touched_protected = [
        path for path in changed if any(path.startswith(prefix) for prefix in PROTECTED_PREFIXES)
    ]
    record(
        "the phase left the trading core untouched",
        "no file under the protected prefixes changed",
        {
            "base": FORWARD_PHASE_BASE,
            "head": head,
            "changed_files": len(changed),
            "protected_files_changed": touched_protected,
            "changed_prefixes": sorted({path.split("/")[0] for path in changed}),
        },
        not touched_protected,
    )

    # 12. No false success: the artifacts must not overclaim (§55).
    artifact_texts = {
        name: (DOCS / name).read_text(encoding="utf-8")
        for name in (
            "FORWARD_DATA_QUALITY_REPORT.json",
            "FORWARD_DATA_REPLAY_VALIDATION.json",
            "FORWARD_DATA_RESOURCE_REPORT.json",
            "MICROSTRUCTURE_FORWARD_COLLECTION_FINAL.json",
        )
        if (DOCS / name).exists()
    }
    overclaims = {
        name: [token for token in BANNED_OUTPUT_TOKENS if token in text]
        for name, text in artifact_texts.items()
    }
    overclaims = {name: tokens for name, tokens in overclaims.items() if tokens}
    final_path = DOCS / "MICROSTRUCTURE_FORWARD_COLLECTION_FINAL.json"
    final_status = (
        json.loads(final_path.read_text(encoding="utf-8")).get("final_status")
        if final_path.exists()
        else None
    )
    record(
        "no artifact claims a strategy outcome and the final status is one of three",
        f"status in {list(ALLOWED_FINAL_STATUSES)}; no profitability vocabulary",
        {
            "final_status": final_status,
            "artifacts_present": sorted(artifact_texts),
            "overclaiming_artifacts": overclaims,
        },
        final_status in ALLOWED_FINAL_STATUSES and not overclaims,
    )

    # 13. Gap lifecycle: every gap states an outcome its own numbers support (§2).
    gap_statuses = ("RECOVERED_COMPLETE", "RECOVERED_PARTIAL", "UNRECOVERABLE")
    gap_problems: list[dict[str, Any]] = []
    declared_backfilled = 0
    for gap in manifest.get("gaps", []):
        problems: list[str] = []
        recovered = bool(gap.get("recovered"))
        data_lost = bool(gap.get("data_lost"))
        restored = int(gap.get("recovered_events") or 0)
        declared_backfilled += restored
        estimated = gap.get("estimated_lost_events")
        remaining = gap.get("remaining_missing")
        if not gap.get("gap_id"):
            problems.append("no gap_id")
        if gap.get("status") not in gap_statuses:
            problems.append(f"status={gap.get('status')!r}")
        if recovered != (gap.get("status") == "RECOVERED_COMPLETE"):
            problems.append("recovered flag disagrees with status")
        if recovered and data_lost:
            problems.append("recovered and data_lost at the same time")
        if not recovered and restored == 0 and gap.get("status") != "UNRECOVERABLE":
            problems.append("nothing recovered and not declared UNRECOVERABLE")
        if not recovered and not data_lost and int(estimated or 0) > 0:
            problems.append("lossless window with an estimated loss")
        if estimated is not None:
            if restored > int(estimated):
                problems.append("restored more events than were estimated lost")
            if remaining != max(0, int(estimated) - restored):
                problems.append("remaining_missing is not estimated - restored")
        if problems:
            gap_problems.append(
                {"gap_id": gap.get("gap_id"), "reason": gap.get("reason"), "problems": problems}
            )
    record(
        "every gap records an outcome its own numbers support",
        "traceable gap_id, status in {RECOVERED_COMPLETE, RECOVERED_PARTIAL, UNRECOVERABLE},"
        " recovered/data_lost never contradict",
        {
            "gaps": len(manifest.get("gaps", [])),
            "by_status": manifest.get("integrity", {}).get("gaps_by_status"),
            "declared_backfilled_events": declared_backfilled,
            "problems": gap_problems[:10],
        },
        not gap_problems,
    )

    # 14. Logical identity: no duplicate aggregate trades, and the id space is
    #     explained by the declared holes (§3, §11).
    id_space = evidence.ids
    labelled_backfilled = evidence.labelled_backfilled
    live_delays = evidence.live_delay_counts

    gaps_by_stream: dict[str, list[dict[str, Any]]] = {}
    for gap in manifest.get("gaps", []):
        if gap.get("event_type") != "agg_trade":
            continue
        gaps_by_stream.setdefault(f"{gap.get('market')}/{gap.get('symbol')}", []).append(gap)

    id_space_problems: list[dict[str, Any]] = []
    for key, entry in sorted(id_space.items()):
        if entry["min"] is None:
            continue
        expected_ids = int(entry["max"]) - int(entry["min"]) + 1
        missing = expected_ids - len(entry["seen"])
        duplicate_rows = entry["rows"] - len(entry["seen"])
        stream_gaps = gaps_by_stream.get(key, [])
        explained = sum(int(gap.get("remaining_missing") or 0) for gap in stream_gaps)
        unknown_width = [
            gap
            for gap in stream_gaps
            if gap.get("data_lost") and gap.get("estimated_lost_events") is None
        ]
        entry["expected_ids"] = expected_ids
        entry["missing_from_id_space"] = missing
        entry["declared_remaining_missing"] = explained
        entry["duplicate_rows"] = duplicate_rows
        entry["losses_with_unknown_width"] = len(unknown_width)
        entry["ids"] = len(entry["seen"])
        entry.pop("seen", None)
        if duplicate_rows != 0:
            id_space_problems.append({"stream": key, "problem": "duplicate rows on disk"})
        unexplained = missing - explained
        entry["unexplained_missing_ids"] = unexplained
        if unexplained != 0 and not unknown_width:
            id_space_problems.append(
                {"stream": key, "problem": "missing ids not explained by a declared gap"}
            )
        if missing == 0 and any(gap.get("data_lost") for gap in stream_gaps):
            id_space_problems.append(
                {"stream": key, "problem": "a loss is declared but the id space has no hole"}
            )
    record(
        "the aggregate trade id space is fully explained by the declared holes",
        "zero duplicate rows; missing ids == declared remaining_missing, or an"
        " unknown-width loss is declared for the stream",
        {"per_stream": id_space, "problems": id_space_problems[:10]},
        not id_space_problems,
    )

    # 15. Recovered rows are labelled, and the reported latency is the live one.
    quality_path = DOCS / "FORWARD_DATA_QUALITY_REPORT.json"
    quality = json.loads(quality_path.read_text(encoding="utf-8")) if quality_path.exists() else {}
    reported_latency = (quality.get("event_latency_ms") or {}).get("p99")
    live_p99 = _histogram_percentile(live_delays, 0.99)
    live_samples = sum(live_delays.values())
    latency_agrees = (reported_latency is None and live_p99 is None) or (
        reported_latency is not None
        and live_p99 is not None
        and abs(float(reported_latency) - float(live_p99)) <= 1.0
    )
    record(
        "recovered rows are labelled and excluded from the latency distribution",
        "backfilled rows carry detail.origin; reported p99 equals the live-only p99",
        {
            "labelled_backfilled_rows": labelled_backfilled,
            "manifest_backfilled_events": manifest.get("integrity", {}).get("backfilled_events"),
            "reported_latency_p99_ms": reported_latency,
            "live_only_latency_p99_ms": live_p99,
            "live_samples": live_samples,
            "live_delay_distinct_values": len(live_delays),
            "latency_note": (quality.get("event_latency_ms") or {}).get("note"),
        },
        labelled_backfilled == int(manifest.get("integrity", {}).get("backfilled_events") or 0)
        and labelled_backfilled == int((quality.get("loss") or {}).get("backfilled_events") or 0)
        and latency_agrees,
    )

    # 16. One root, one run: nothing from another capture is fused in (§12).
    row_runs = sorted(evidence.run_ids)
    record(
        "the verified root holds exactly one capture run",
        f"every row belongs to {run_id}",
        {"row_run_ids": row_runs, "manifest_run_id": manifest.get("run_id")},
        row_runs == [run_id] and manifest.get("run_id") == run_id,
    )

    # 17. Footprint: compression and the daily rate, measured by this verifier.
    stored_bytes = 0
    uncompressed_bytes = 0
    for path in files:
        stored_bytes += path.stat().st_size
        # Blocked, not slurped: the verifier must be able to measure a capture
        # larger than the memory it runs in (§34), and it runs on the same laptop.
        try:
            with gzip.open(path, "rb") as handle:
                while True:
                    block = handle.read(4 * 1024 * 1024)
                    if not block:
                        break
                    uncompressed_bytes += len(block)
        except (EOFError, OSError):  # pragma: no cover - a sealed run has no live member
            continue
    resource_path = DOCS / "FORWARD_DATA_RESOURCE_REPORT.json"
    resource = (
        json.loads(resource_path.read_text(encoding="utf-8")) if resource_path.exists() else {}
    )
    footprint = resource.get("footprint", {})
    verifier_ratio = round(uncompressed_bytes / stored_bytes, 3) if stored_bytes else None
    ratio_agrees = (
        verifier_ratio is None
        or footprint.get("compression_ratio") is None
        or abs(float(footprint["compression_ratio"]) - verifier_ratio) <= 0.05
    )
    record(
        "the storage footprint is measured, not assumed",
        "compression ratio and GB/day recomputed from the files agree with the report",
        {
            "segments": len(files),
            "stored_bytes": stored_bytes,
            "uncompressed_bytes": uncompressed_bytes,
            "verifier_compression_ratio": verifier_ratio,
            "report_compression_ratio": footprint.get("compression_ratio"),
            "report_stored_gb_per_day": footprint.get("stored_gb_per_day"),
            "report_raw_gb_per_day": footprint.get("raw_gb_per_day"),
        },
        bool(footprint) and ratio_agrees and (verifier_ratio is None or verifier_ratio >= 2.0),
    )

    # 18. The disk guard is auditable and the capture ended cleanly (§8).
    budget = manifest.get("max_total_bytes")
    unfinished = [f["path"] for f in manifest.get("fingerprints", []) if f.get("partial_tail")]
    record(
        "the disk budget is recorded and the capture ended with sealed segments",
        "manifest carries max_total_bytes; no segment has a partial tail",
        {
            "max_total_bytes": budget,
            "stopped_on_disk_budget": manifest.get("stopped_on_disk_budget"),
            "segments_with_partial_tail": unfinished,
            "disk_bytes_per_hour": manifest.get("disk_bytes_per_hour"),
            "uncompressed_bytes_written": manifest.get("uncompressed_bytes_written"),
        },
        budget is not None and not unfinished,
    )

    # 19. Two seconds of evidence beat any claim of realism (§16).
    kline_path = DOCS / "FORWARD_DATA_KLINE_CROSSCHECK.json"
    kline = json.loads(kline_path.read_text(encoding="utf-8")) if kline_path.exists() else {}
    ratios = [float(entry["ratio"]) for entry in kline.get("buckets", []) if entry.get("ratio")]
    recomputed = [
        round(float(entry["capture_volume"]) / float(entry["kline_volume"]), 6)
        for entry in kline.get("buckets", [])
        if float(entry.get("kline_volume") or 0) > 0
    ]
    arithmetic_ok = bool(recomputed) and all(
        abs(value - ratio) <= 1e-6 for value, ratio in zip(recomputed, ratios, strict=False)
    )
    worst_ratio = max((abs(value - 1.0) for value in ratios), default=None)
    record(
        "captured trade volume agrees with the venue's own klines",
        "recomputed ratios match the artifact; worst deviation <= 2%",
        {
            "run_id_in_artifact": kline.get("run_id"),
            "buckets_compared": len(ratios),
            "worst_ratio_deviation": worst_ratio,
            "median_ratio": sorted(ratios)[len(ratios) // 2] if ratios else None,
            "arithmetic_agrees": arithmetic_ok,
            "note": kline.get("note"),
        },
        bool(kline)
        and kline.get("run_id") == run_id
        and arithmetic_ok
        and worst_ratio is not None
        and worst_ratio <= 0.02,
    )

    # 20. Coexistence with PAPER is demonstrated, not asserted (§19, §20).
    coexist_path = DOCS / "FORWARD_DATA_PAPER_COEXISTENCE.json"
    coexist = json.loads(coexist_path.read_text(encoding="utf-8")) if coexist_path.exists() else {}
    with_collector = coexist.get("with_collector", {})
    without = coexist.get("without_collector", {})
    record(
        "the collector coexists with the PAPER runtime without touching it",
        "PAPER ran with the collector up (0 orders, 0 failures) and the collector "
        "kept writing throughout",
        {
            "paper_run_with_collector": with_collector.get("run_id"),
            "paper_run_without_collector": without.get("run_id"),
            "with_collector": with_collector,
            "without_collector": without,
            "collector_events_during": coexist.get("collector_events_during"),
        },
        bool(with_collector)
        and int(with_collector.get("orders_created") or 0) == 0
        and int(with_collector.get("runtime_failures") or 0) == 0
        and int(coexist.get("collector_events_during") or 0) > 0,
    )

    # 21. Transport provenance, restated independently of the artifact (§7).
    transport_problems: list[dict[str, Any]] = []
    for event_type, tally in sorted(evidence.transports.items()):
        observed = sorted(tally)
        if event_type in WS_ONLY_EVENT_TYPES and observed != ["ws"]:
            transport_problems.append(
                {"event_type": event_type, "expected": ["ws"], "observed": observed}
            )
        elif event_type in REST_ONLY_EVENT_TYPES and any(value == "ws" for value in observed):
            transport_problems.append(
                {"event_type": event_type, "expected": "rest-only", "observed": observed}
            )
    record(
        "every row's transport label matches the source the contract declares",
        "lossless streams are ws-only; snapshot and polling streams are never ws",
        {
            "by_event_type": {k: dict(v) for k, v in sorted(evidence.transports.items())},
            "problems": transport_problems,
            "lossless_examples": list(WS_ONLY_EVENT_TYPES),
            "rest_examples": list(REST_ONLY_EVENT_TYPES),
        },
        not transport_problems,
    )

    # 22. The real recovery chain: WS gap -> REST walk -> persistence -> later WS
    #     overlap -> dedup -> exactly one logical event (§4).
    integrity_recovery = manifest.get("integrity", {})
    recovered_gaps = [gap for gap in manifest.get("gaps", []) if gap.get("recovered")]
    recovered_events_declared = int(integrity_recovery.get("backfilled_events") or 0)
    labelled_backfill_rows = evidence.labelled_backfilled
    overlap_deduped = int(integrity_recovery.get("duplicates") or 0)
    duplicate_rows_on_disk = sum(
        int(entry.get("duplicate_rows") or 0) for entry in id_space.values()
    )
    recovered_width_mismatch = [
        {
            "gap_id": gap.get("gap_id"),
            "declared_recovered": gap.get("recovered_events"),
            "recovered_flag": gap.get("recovered"),
            "data_lost": gap.get("data_lost"),
        }
        for gap in recovered_gaps
        if int(gap.get("recovered_events") or 0) <= 0 or gap.get("data_lost")
    ]
    record(
        "a WS gap was closed by the public index, persisted once, and deduped",
        "recovered gaps declare recovered_events > 0 and data_lost false; labelled "
        "backfill rows equal the declared total; a WS overlap was deduped and no "
        "duplicate row reached disk",
        {
            "gaps_recovered_complete": len(recovered_gaps),
            "declared_backfilled_events": recovered_events_declared,
            "labelled_backfill_rows_on_disk": labelled_backfill_rows,
            "live_rows_deduped_after_backfill": overlap_deduped,
            "duplicate_rows_on_disk": duplicate_rows_on_disk,
            "inconsistent_recovered_gaps": recovered_width_mismatch[:5],
            "backfill_failures": integrity_recovery.get("backfill_failures"),
            "backfill_deferred": integrity_recovery.get("backfill_deferred"),
        },
        bool(recovered_gaps)
        and not recovered_width_mismatch
        and labelled_backfill_rows == recovered_events_declared
        and labelled_backfill_rows > 0
        and overlap_deduped > 0
        and duplicate_rows_on_disk == 0,
    )

    # 23. Health accounting: recomputed here from the manifest's own windows, so
    #     the reported degraded time is not taken on trust (§6).
    recovery_windows: list[tuple[int, int]] = []
    for gap in manifest.get("gaps", []):
        start, end = int(gap.get("start_ms") or 0), int(gap.get("end_ms") or 0)
        if end > start:
            recovery_windows.append((start, end))
    gap_window_count = len(recovery_windows)
    # The report's degraded time is the union of the gap windows *and* the
    # reconnect downtime, the second of which the verifier re-derives above from
    # the lifecycle rows rather than reading it out of the report it is checking.
    recovery_windows.extend(evidence.downtime_windows)
    recovery_windows.sort()
    union_ms = 0
    cursor: int | None = None
    for start, end in recovery_windows:
        if cursor is None or start > cursor:
            union_ms += end - start
            cursor = end
        elif end > cursor:
            union_ms += end - cursor
            cursor = end
    reported_health = quality.get("health") or {}
    reported_degraded = (reported_health.get("live") or {}).get("degraded_seconds")
    reported_capture = (reported_health.get("live") or {}).get("healthy_seconds")
    health_agrees = reported_degraded is not None and abs(
        float(reported_degraded) - union_ms / 1000.0
    ) <= 0.001 + 0.001 * len(recovery_windows)
    record(
        "the health accounting is re-derivable from the gap windows",
        "report degraded_seconds == the verifier's union of the recorded windows"
        " (the report may add reconnect downtime, which is bounded separately)",
        {
            "gap_windows": gap_window_count,
            "reconnect_downtime_windows": len(evidence.downtime_windows),
            "windows": len(recovery_windows),
            "union_seconds_from_manifest": round(union_ms / 1000.0, 3),
            "reported_degraded_seconds": reported_degraded,
            "reported_healthy_seconds": reported_capture,
            "reported_failed_seconds": (reported_health.get("live") or {}).get("failed_seconds"),
            "reconnect_downtime": reported_health.get("reconnect_downtime"),
            "collector_state_sticky": (reported_health.get("collector_state") or {}).get("sticky"),
            "accounting_agrees": health_agrees,
        },
        bool(reported_health) and health_agrees,
    )

    # 24. The disk guard is armed, recorded, and did not silently swallow data.
    guard = resource.get("disk_guard", {})
    storage = resource.get("storage_capacity", {})
    guard_test_path = DOCS / "FORWARD_DATA_DISK_GUARD.json"
    guard_test = (
        json.loads(guard_test_path.read_text(encoding="utf-8")) if guard_test_path.exists() else {}
    )
    record(
        "the disk guard is armed, and a controlled low-budget run stopped cleanly",
        "the official run records its budget and finished within it; the controlled "
        "run tripped the guard, sealed its segments, finalised its manifest and "
        "exited 0",
        {
            "max_total_bytes": guard.get("max_total_bytes"),
            "stopped_on_disk_budget_official": guard.get("stopped_on_disk_budget"),
            "controlled_run": guard_test.get("result"),
            "storage_capacity_verdict": storage.get("verdict"),
            "capacity_days_at_observed_rate": storage.get("capacity_days_at_observed_rate"),
        },
        guard.get("enabled") is True
        and guard.get("stopped_on_disk_budget") is False
        and bool(guard_test)
        and guard_test.get("tripped") is True
        and guard_test.get("clean_exit") is True
        and guard_test.get("segments_sealed") is True
        and guard_test.get("manifest_finalised") is True
        and int(guard_test.get("partial_tails") or 0) == 0,
    )

    # 25. Memory is bounded by streams, not by rows (§9, §34).
    memory_path = DOCS / "FORWARD_DATA_STREAMING_MEMORY.json"
    memory = json.loads(memory_path.read_text(encoding="utf-8")) if memory_path.exists() else {}
    materialised_mb = memory.get("materialised_equivalent_mb")
    worst_growth = memory.get("worst_rss_growth_mb")
    memory_ratio = memory.get("ratio_vs_materialised")
    record(
        "the analysis paths stream: memory does not grow with the row count",
        "measured growth stays a small fraction of the materialised equivalent",
        {
            "rows_measured": memory.get("rows_measured"),
            "materialised_equivalent_mb": materialised_mb,
            "worst_rss_growth_mb": worst_growth,
            "ratio_vs_materialised": memory_ratio,
            "stages": [stage.get("stage") for stage in memory.get("stages", [])],
            "bounded": memory.get("bounded"),
        },
        bool(memory)
        and memory.get("bounded") is True
        and memory_ratio is not None
        and float(memory_ratio) <= 0.10
        and int(memory.get("rows_measured") or 0) > 0,
    )

    # 26. The capture and the final HEAD are the same code, at the granularity
    #     that matters: the top-level definition. A read-side-only delta is
    #     acceptable and must be shown to be unreachable from the writer (§24).
    equivalence = _writer_equivalence(str(manifest.get("commit") or ""), head)
    record(
        "the writing path at HEAD is the writing path that produced the capture",
        "collector, book, contract and CLI identical; any storage delta unreachable "
        "from the names the writer imports",
        equivalence,
        bool(equivalence.get("capture_code_equivalent"))
        and bool(str(manifest.get("commit") or "")),
    )

    # 27. Backfill cannot recurse: a page that contains a hole does not schedule
    #     another walk. Executed here, not read from a builder claim (§5).
    recursion = _backfill_recursion_probe()
    record(
        "a hole found inside a backfill page never restarts recovery",
        "exactly one index request, no scheduled task, the hole stays recorded",
        recursion,
        recursion.get("requests") == 1
        and recursion.get("deferred") == 1
        and recursion.get("scheduled_tasks") == 0
        and recursion.get("inner_hole_recorded") is True,
    )

    return _result(
        checks,
        failures,
        {
            "run_id": run_id,
            "head": head,
            "rows": evidence.rows,
            "segments": len(files),
            "partial_tails": partial_tails,
            "manifest": {
                "collector_version": manifest.get("collector_version"),
                "contract_version": manifest.get("contract_version"),
                "schema_version": manifest.get("schema_version"),
                "continuity": continuity,
                "provider_stream_status": manifest.get("provider_stream_status"),
                "integrity": integrity,
                "resources": manifest.get("resources"),
                "books": manifest.get("book_health"),
            },
            "book_independence": book,
            #: Published as its own artifact as well, because the closing summary
            #: cites it and a citation has to point at a file, not at a check row.
            "writer_equivalence": equivalence,
        },
    )


def _symbol_sources(source: str) -> dict[str, str]:
    """Top-level def/class name -> its exact source, for code-equivalence checks."""
    lines = source.splitlines(keepends=True)
    found: dict[str, str] = {}
    try:
        tree = ast.parse(source)
    except SyntaxError:  # pragma: no cover - a revision that does not parse
        return found
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start = node.lineno - 1
            end = getattr(node, "end_lineno", node.lineno)
            found[node.name] = "".join(lines[start:end])
    return found


def _imported_names(source: str, suffix: str) -> tuple[set[str], bool]:
    """Names imported from a module ending in ``suffix``, plus a module alias flag.

    A writer that binds the module itself (``import x.storage``) could reach any
    name through it, so that form is reported rather than assumed harmless.
    """
    names: set[str] = set()
    module_alias = False
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith(suffix):
            names |= {alias.name for alias in node.names}
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.endswith(suffix):
                    module_alias = True
    return names, module_alias


#: Transport the contract requires per event type, restated by the verifier so it
#: is not read back from the artifact it is supposed to be checking (§7).
WS_ONLY_EVENT_TYPES = ("agg_trade", "book_ticker", "depth_diff")
REST_ONLY_EVENT_TYPES = ("depth_snapshot", "open_interest", "funding", "mark_price")


#: Every path the capture executed. The first four are the writer: the collector
#: loop, the book, the contract that validates a row, and the storage layer. The
#: CLI is included because it is what selected the configuration that ran.
WRITER_PATHS = (
    "src/trading_bot/research/forward/collector.py",
    "src/trading_bot/research/forward/orderbook.py",
    "src/trading_bot/research/forward/contract.py",
    "src/trading_bot/research/forward/storage.py",
    "scripts/forward_collector.py",
)

#: Modules the capture imports from *and* the read side extends. A change here is
#: only harmless if the changed name is one the writer never binds: the writer can
#: reach a shared module, but only through the names it imports from it.
SHARED_WRITER_MODULES = {
    "src/trading_bot/research/forward/storage.py": "forward.storage",
    "src/trading_bot/research/forward/resources.py": "forward.resources",
}


def _normalised(text: str) -> str:
    return text.replace("\r\n", "\n")


def _writer_equivalence(capture_commit: str, head: str) -> dict[str, Any]:
    """§24 — is the code that wrote the capture the code at the final HEAD?

    A raw diff is not the question, and it is not enough either way: a line-ending
    change would look like a rewrite, while a real edit inside a function the
    writer never calls would look harmless. So the comparison is made at the
    granularity that matters — the source of each top-level definition — and for
    the storage layer it is intersected with the names the collector actually
    imports, since the writer can only reach what it binds.
    """
    report: dict[str, Any] = {
        "capture_commit": capture_commit,
        "head": head,
        "numstat": {},
        "files": {},
    }
    for relative in WRITER_PATHS:
        raw = git(["diff", "--numstat", f"{capture_commit}..{head}", "--", relative])
        report["numstat"][relative] = raw or "unchanged"

    for relative in WRITER_PATHS:
        if relative in SHARED_WRITER_MODULES:
            continue
        capture_source = git_file(capture_commit, relative)
        head_source = (ROOT / relative).read_text(encoding="utf-8")
        capture_symbols = _symbol_sources(_normalised(capture_source))
        head_symbols = _symbol_sources(_normalised(head_source))
        changed = sorted(
            name
            for name in set(capture_symbols) | set(head_symbols)
            if capture_symbols.get(name) != head_symbols.get(name)
        )
        report["files"][relative] = {
            "role": "writer",
            "changed_symbols": changed,
            "identical": not changed,
        }

    collector_source = _normalised(
        (ROOT / "src/trading_bot/research/forward/collector.py").read_text(encoding="utf-8")
    )
    reachable_total: list[str] = []
    module_alias_total = False
    shares = 0
    for relative, suffix in SHARED_WRITER_MODULES.items():
        capture_source = _normalised(git_file(capture_commit, relative))
        head_source = _normalised((ROOT / relative).read_text(encoding="utf-8"))
        capture_symbols = _symbol_sources(capture_source)
        head_symbols = _symbol_sources(head_source)
        changed = sorted(
            name
            for name in set(capture_symbols) | set(head_symbols)
            if capture_symbols.get(name) != head_symbols.get(name)
        )
        imported, module_alias = _imported_names(collector_source, suffix)
        reachable = sorted(set(changed) & imported)
        reachable_total += reachable
        module_alias_total = module_alias_total or module_alias
        if changed:
            shares += 1
        report["files"][relative] = {
            "role": "shared module: the capture imports from it, the analysis path extends it",
            "changed_symbols": changed,
            "symbols_the_writer_imports": sorted(imported),
            "changed_symbols_the_writer_can_reach": reachable,
            "writer_binds_the_module_itself": module_alias,
            "identical": not changed,
        }

    writer_changed = [
        relative
        for relative in WRITER_PATHS
        if relative not in SHARED_WRITER_MODULES
        and not report["files"].get(relative, {}).get("identical", False)
    ]
    report["shared_modules_extended"] = shares
    report["writer_modules_changed"] = writer_changed
    report["changed_symbols_the_writer_can_reach"] = sorted(set(reachable_total))
    report["writer_binds_a_shared_module_itself"] = module_alias_total
    report["capture_code_equivalent"] = bool(
        not writer_changed and not reachable_total and not module_alias_total
    )
    report["classification"] = (
        "CAPTURE_CODE_EQUIVALENT"
        if report["capture_code_equivalent"]
        else "WRITER_CHANGED_SINCE_CAPTURE"
    )
    report["note"] = (
        "the collector, book, contract and CLI are identical definition-by-definition "
        "at the capture commit and at HEAD; the shared storage and resource modules "
        "only gained read-side helpers whose names the writer never imports, so "
        "nothing the capture executed has changed"
        if report["capture_code_equivalent"]
        else "the writing path differs between the capture commit and HEAD; the "
        "capture cannot be certified by the final tree without a re-run"
    )
    return report


def _backfill_recursion_probe() -> dict[str, Any]:
    """§5 — run the recovery guard once and report what it actually did.

    Non-termination is a property of behaviour, so the probe drives the real
    ingest path in a throwaway root: a page from the public index that itself
    contains a hole must be recorded, and must not schedule another walk over the
    very index being walked.
    """
    from trading_bot.research.forward.collector import (
        CollectorConfig,
        ForwardCollector,
        subscriptions_for,
    )
    from trading_bot.research.forward.contract import Market

    result: dict[str, Any] = {
        "requests": 0,
        "deferred": None,
        "scheduled_tasks": None,
        "inner_hole_recorded": False,
        "error": None,
    }
    try:
        with tempfile.TemporaryDirectory() as directory:
            collector = ForwardCollector(
                CollectorConfig(
                    root=Path(directory),
                    symbols=("BTCUSDT",),
                    markets=(Market.SPOT,),
                    keep_raw=False,
                    stale_after_ms=10**15,
                )
            )
            plan = subscriptions_for(("BTCUSDT",))
            collector.handle_message(
                Market.SPOT,
                plan,
                {
                    "e": "aggTrade",
                    "E": 1_000,
                    "s": "BTCUSDT",
                    "a": 100,
                    "p": "100.00",
                    "q": "1",
                    "f": 10,
                    "l": 10,
                    "T": 1_000,
                    "m": False,
                },
                1_000,
                1,
                "btcusdt@aggTrade",
            )
            requests: list[int] = []

            async def _index(_session: Any, _market: Any, _path: str, params: Any) -> Any:
                requests.append(int(params["fromId"]))
                first = int(params["fromId"])
                limit = int(params["limit"])
                # The index is missing id 103, so the page it returns has a hole.
                return [
                    {
                        "e": "aggTrade",
                        "E": 1_000,
                        "T": 1_000,
                        "s": "BTCUSDT",
                        "a": agg_id,
                        "p": "100.00",
                        "q": "1",
                        "f": agg_id,
                        "l": agg_id,
                        "m": False,
                    }
                    for agg_id in range(first, min(first + limit, 106))
                    if agg_id != 103
                ]

            collector._session = object()  # type: ignore[assignment]
            collector._rest_get = _index  # type: ignore[assignment]
            asyncio.run(
                collector._recover_agg_trade_gap(
                    Market.SPOT, "BTCUSDT", 5_000, 6_000, "websocket CLOSED"
                )
            )
            result["requests"] = len(requests)
            result["requested_from_ids"] = requests
            result["deferred"] = collector.backfill_deferred
            result["scheduled_tasks"] = len(collector._backfill_tasks)
            result["inner_hole_recorded"] = any(
                gap.reason == "AGG_TRADE_ID_JUMP" for gap in collector.gaps
            )
            # Windows will not let the temporary directory go while the segment
            # writer still holds its handle, and the probe must leave no trace.
            with contextlib.suppress(Exception):
                collector.writer.close()
    except Exception as exc:  # pragma: no cover - reported, never swallowed
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def _resolve_source(module_name: str) -> str | None:
    try:
        spec = importlib.util.find_spec(module_name)
    except (ImportError, ModuleNotFoundError, ValueError):
        return None
    if spec is None or spec.origin is None:
        return None
    return spec.origin


def _replay_without_network(run_id: str) -> tuple[bool, str]:
    """Run the builder's replay with sockets disabled and report the outcome."""
    from trading_bot.research.forward.replay import replay_microstructure_dataset

    def _forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("replay attempted network access")

    original: dict[str, Any] = {
        "socket": socket.socket,
        "create_connection": socket.create_connection,
        "getaddrinfo": socket.getaddrinfo,
    }
    for attribute in ("socket", "create_connection", "getaddrinfo"):
        setattr(socket, attribute, _forbidden)
    try:
        verification = replay_microstructure_dataset(FORWARD_ROOT, run_id)
    except AssertionError as exc:
        return False, f"network access attempted: {exc}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    finally:
        for attribute, replacement in original.items():
            setattr(socket, attribute, replacement)
    return (
        verification.ok,
        f"replay ok={verification.ok} rows={verification.rows} "
        f"checkpoints={sum(b.checkpoints for b in verification.books)}",
    )


def _environment() -> dict[str, Any]:
    """Where this verification ran: the code tree, and the dataset it read.

    §27 asks for the module the verifier imported to resolve *inside* the tree
    being verified. That is a property of the run, so it is recorded by the run.
    """
    package = _resolve_source("trading_bot.research.forward.collector")
    try:
        top_level = git(["rev-parse", "--show-toplevel"])
    except Exception:  # pragma: no cover - a non-repo checkout
        top_level = ""
    return {
        "source_root": str(ROOT),
        "capture_root": str(FORWARD_ROOT),
        "capture_root_is_inside_source_root": str(FORWARD_ROOT).startswith(str(ROOT)),
        "collector_module_file": package,
        "collector_module_is_inside_source_root": bool(
            package and str(Path(package).resolve()).startswith(str(ROOT))
        ),
        "git_toplevel": top_level,
        "python": sys.version.split()[0],
    }


def _result(
    checks: list[dict[str, Any]], failures: list[str], detail: dict[str, Any]
) -> dict[str, Any]:
    return {
        "scope": "MICROSTRUCTURE-FORWARD-COLLECTION-V1 (forward dataset)",
        "head": git(["rev-parse", "HEAD"]),
        "environment": _environment(),
        "checks": checks,
        "detail": detail,
        "failures": failures,
        "status": "VERIFIED" if not failures else "FAILED_VERIFICATION",
    }


def render_forward_md(payload: dict[str, Any]) -> str:
    passed = sum(1 for check in payload["checks"] if check["pass"])
    lines = [
        "# MICROSTRUCTURE_FORWARD_COLLECTION_INDEPENDENT_VERIFICATION",
        "",
        "Verificador: `scripts/research_verification.py` "
        "(fase `scripts/forward_collection_verification.py`) — "
        f"HEAD `{payload['head']}`.",
        f"Alcance: `{payload['scope']}`.",
        "",
        "BUILDER != VERIFIER: este verificador no importa ninguna cifra del colector.",
        "Reconstruye el libro con una **segunda implementación** escrita aparte,",
        "recalcula cada huella desde los bytes crudos, re-deriva la cadena de aggTrades,",
        "y ejecuta el replay con los sockets deshabilitados.",
        "",
        "```text",
        f"STATUS: {payload['status']}",
        f"CHECKS: {passed}/{len(payload['checks'])} PASS",
        f"FAILURES: {len(payload['failures'])}",
        f"SOURCE ROOT: {(payload.get('environment') or {}).get('source_root')}",
        f"CAPTURE ROOT: {(payload.get('environment') or {}).get('capture_root')}",
        "COLLECTOR MODULE INSIDE SOURCE ROOT: "
        f"{(payload.get('environment') or {}).get('collector_module_is_inside_source_root')}",
        "```",
        "",
        "| check | esperado | observado | pass |",
        "| --- | --- | --- | :-: |",
    ]
    for check in payload["checks"]:
        observed = str(check["observed"]).replace("|", "/")
        expected = str(check["expected"]).replace("|", "/")
        if len(observed) > 260:
            observed = observed[:257] + "..."
        if len(expected) > 200:
            expected = expected[:197] + "..."
        lines.append(
            f"| {check['check']} | {expected} | {observed} | "
            f"{'PASS' if check['pass'] else 'FAIL'} |"
        )
    lines.append("")
    return "\n".join(lines)
