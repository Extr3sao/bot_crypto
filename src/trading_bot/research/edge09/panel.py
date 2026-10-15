"""Read the forward microstructure capture onto a declared decision grid.

The capture stores one JSON row per venue event (``book_ticker``, ``agg_trade``,
``depth_snapshot``, ``open_interest``, ``funding``, ``mark_price``). This module
turns that into a panel with **one row per (run, market, symbol, second)**:

* the decision instant of a second is the ``receive_time`` of the LAST quote
  event inside it, so a feature is only built from data the consumer already
  had at that instant (point-in-time by construction, not by convention);
* a second with no quote event is *absent*, never carried forward silently: the
  carry-forward is applied by the caller and counted there;
* trade flow is aggregated per second with the venue's own ``aggressor_side``;
* open interest, funding and mark price are sparse samples kept as they are;
* depth snapshots keep the first ``DEPTH_LEVELS`` levels of each side.

Nothing in this module invents a quote, an order book or an event time.
"""

from __future__ import annotations

import gzip
import json
import re
from bisect import bisect_left
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

from .registration import GRID_SECONDS, REPO_ROOT, UNIVERSE

#: Levels kept from a depth snapshot. The barrier band is a few bps wide, so
#: deeper levels cannot change the answer and would only cost memory.
DEPTH_LEVELS = 10

STREAMS: tuple[str, ...] = ("book_ticker", "agg_trade", "depth_snapshot", "open_interest")


@dataclass(slots=True)
class SecondRow:
    """One second of one stream, as the consumer could have seen it."""

    run: str
    market: str
    symbol: str
    second_ms: int
    decision_time: int
    mid: float
    bid: float
    ask: float
    spread_bps: float
    bid_qty: float
    ask_qty: float
    quote_events: int
    trades: int = 0
    signed_volume: float = 0.0
    last_trade_price: float = 0.0

    def as_csv(self) -> str:
        return (
            f"{self.run},{self.market},{self.symbol},{self.second_ms},{self.decision_time},"
            f"{self.mid:.8f},{self.bid:.8f},{self.ask:.8f},{self.spread_bps:.6f},"
            f"{self.bid_qty:.8f},{self.ask_qty:.8f},{self.quote_events},"
            f"{self.trades},{self.signed_volume:.10f},{self.last_trade_price:.8f}"
        )


@dataclass(slots=True)
class PanelStats:
    quotes: int = 0
    seconds: int = 0
    trades: int = 0
    trade_volume: float = 0.0
    oi_samples: int = 0
    depth_snapshots: int = 0
    files: int = 0
    missing_seconds: int = 0
    truncated_segments: int = 0
    truncated_paths: list[str] = field(default_factory=list)
    first_second_ms: int | None = None
    last_second_ms: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "quotes": self.quotes,
            "seconds": self.seconds,
            "trades": self.trades,
            "trade_volume": round(self.trade_volume, 6),
            "oi_samples": self.oi_samples,
            "depth_snapshots": self.depth_snapshots,
            "files": self.files,
            "missing_seconds": self.missing_seconds,
            "truncated_segments": self.truncated_segments,
            "truncated_paths": self.truncated_paths[:20],
            "first_second_ms": self.first_second_ms,
            "last_second_ms": self.last_second_ms,
        }


def _truncation_hook(stat: PanelStats) -> Callable[[Path, str], None]:
    """Count a segment whose gzip stream ended early, with the reason."""

    def hook(path: Path, message: str) -> None:
        stat.truncated_segments += 1
        stat.truncated_paths.append(f"{path.name}: {message}")

    return hook


def _segments(root: Path, market: str, symbol: str, stream: str) -> list[Path]:
    base = root / "segments" / "binance" / market / symbol / stream
    if not base.is_dir():
        return []
    return sorted(base.rglob("*.jsonl.gz"))


def capture_roots(runs: tuple[str, ...] | None = None) -> list[Path]:
    """Capture roots holding a manifest, filtered by run id when one is given.

    A run id is the manifest's stem (``paper-lab-continuous-02``), not the
    directory name (``microstructure-forward-continuous``); both are accepted
    because a reader may reasonably quote either one.
    """
    roots = [
        parent
        for parent in sorted(REPO_ROOT.glob("reports/microstructure-forward*"))
        if (parent / "manifest").is_dir()
    ]
    if runs:
        wanted = set(runs)
        roots = [
            root
            for root in roots
            if root.name in wanted
            or any(manifest.stem in wanted for manifest in (root / "manifest").glob("*.json"))
        ]
    return roots


def run_id_of(root: Path) -> str:
    manifests = sorted((root / "manifest").glob("*.json"))
    return manifests[-1].stem if manifests else root.name


def iter_lines(
    path: Path, *, on_truncated: Callable[[Path, str], None] | None = None
) -> Iterator[str]:
    """Yield the raw text lines of a segment, failing soft on a torn tail."""
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    yield line
    except (EOFError, OSError, gzip.BadGzipFile) as exc:
        if on_truncated is not None:
            on_truncated(path, f"{type(exc).__name__}: {exc}")


def iter_rows(
    path: Path, *, on_truncated: Callable[[Path, str], None] | None = None
) -> Iterator[dict[str, Any]]:
    """Yield the raw rows of a segment, in the order they were written.

    The capture declares ``INCOMPLETE_DATA``: a collector that was killed leaves a
    segment whose gzip stream ends early. Such a tail is cut off and *counted* —
    never repaired, and never silently treated as a complete file.
    """
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except ValueError:
                    continue
    except (EOFError, OSError, gzip.BadGzipFile) as exc:
        if on_truncated is not None:
            on_truncated(path, f"{type(exc).__name__}: {exc}")


def _second(ms: int) -> int:
    return ms - (ms % (GRID_SECONDS * 1000))


#: The contract writes one JSON object per line, so the decision clock and the
#: run a row belongs to can be read without parsing the whole row. That is what
#: makes a quote-level panel affordable on tens of millions of events without
#: changing which rows are kept.
_RECEIVE_TIME = re.compile(r'"receive_time":\s*(\d+)')


def run_needle(run: str) -> re.Pattern[str]:
    """A matcher for one run's rows inside a segment shared by several runs.

    A capture root's ``segments`` tree is NOT partitioned by run: the same
    directory holds the segments of every run written into that root, and the
    run id lives inside each row. Filtering on the path would therefore mix
    runs, so the panel filters on the row itself.
    """
    return re.compile(r'"run_id":\s*"' + re.escape(run) + r'"')


#: Declared sampling rule for the quote stream: a row is emitted for every
#: one-second boundary, carrying the state at the FIRST quote event at or after
#: that boundary. It is observable at that instant (point-in-time), it does not
#: depend on how many events followed, and the row count is the number of
#: seconds rather than the number of quotes.
SAMPLE_RULE = (
    "one row per one-second boundary, taken from the first quote event at or after "
    "the boundary; the first sample of a stream after a gap only establishes state"
)


@dataclass(slots=True)
class _Pending:
    run: str
    market: str
    symbol: str
    bucket: int | None = None
    events: int = 0
    bid: float = 0.0
    ask: float = 0.0
    bid_qty: float = 0.0
    ask_qty: float = 0.0
    decision_time: int = 0
    extra: dict[str, float] = field(default_factory=dict)


class PanelWriter:
    """Writes panel rows to the three CSV layers it is handed.

    The handles are opened by the caller (``panel.build`` holds them in ``with``
    blocks for the whole fold), so the lifetime of a file is visible where it is
    created rather than hidden inside a long-lived object.
    """

    def __init__(self, seconds: TextIO, oi: TextIO, depth: TextIO) -> None:
        self._seconds = seconds
        self._oi = oi
        self._depth = depth
        self._seconds.write(
            "run,market,symbol,second_ms,decision_time,mid,bid,ask,spread_bps,"
            "bid_qty,ask_qty,quote_events,trades,signed_volume,last_trade_price\n"
        )
        self._oi.write("run,market,symbol,ts_ms,open_interest,mark_price,funding_rate\n")
        self._depth.write("run,market,symbol,ts_ms,side,level,price,qty\n")
        self.stats: dict[str, PanelStats] = {}

    def _stat(self, run: str, market: str, symbol: str) -> PanelStats:
        key = f"{run}|{market}|{symbol}"
        return self.stats.setdefault(key, PanelStats())

    def write_second(self, row: SecondRow) -> None:
        self._seconds.write(row.as_csv() + "\n")
        stat = self._stat(row.run, row.market, row.symbol)
        stat.seconds += 1
        stat.first_second_ms = (
            row.decision_time
            if stat.first_second_ms is None
            else min(stat.first_second_ms, row.decision_time)
        )
        stat.last_second_ms = (
            row.decision_time
            if stat.last_second_ms is None
            else max(stat.last_second_ms, row.decision_time)
        )

    def write_oi(self, run: str, market: str, symbol: str, row: dict[str, Any]) -> None:
        self._oi.write(
            f"{run},{market},{symbol},{row.get('exchange_event_time') or ''},"
            f"{row.get('open_interest') or ''},{row.get('mark_price') or ''},"
            f"{row.get('funding_rate') or ''}\n"
        )
        self._stat(run, market, symbol).oi_samples += 1

    def write_depth(
        self,
        run: str,
        market: str,
        symbol: str,
        ts_ms: int,
        side: str,
        level: int,
        price: str,
        qty: str,
    ) -> None:
        self._depth.write(f"{run},{market},{symbol},{ts_ms},{side},{level},{price},{qty}\n")

    def flush(self) -> None:
        """Push what is buffered to disk; the handles stay the caller's."""
        for handle in (self._seconds, self._oi, self._depth):
            handle.flush()


def ingest_book_ticker(
    writer: PanelWriter,
    run: str,
    market: str,
    symbol: str,
    paths: list[Path],
    flow: dict[int, tuple[float, int, float]] | None = None,
) -> None:
    """Fold the quote stream into one row per second, last quote wins.

    ``flow`` is that same second's own tape (signed volume, prints, last price),
    joined here so a row is one second of everything the consumer could see.
    """
    stat = writer._stat(run, market, symbol)
    pending = _Pending(run=run, market=market, symbol=symbol)
    previous: int | None = None
    tape = flow or {}

    def flush() -> None:
        if pending.bucket is None or pending.bid <= 0 or pending.ask <= 0:
            return
        mid = (pending.bid + pending.ask) / 2.0
        spread_bps = (pending.ask - pending.bid) / mid * 10_000.0 if mid > 0 else 0.0
        signed, prints, last_price = tape.get(pending.bucket, (0.0, 0, 0.0))
        writer.write_second(
            SecondRow(
                run=run,
                market=market,
                symbol=symbol,
                second_ms=pending.bucket,
                decision_time=pending.decision_time,
                mid=mid,
                bid=pending.bid,
                ask=pending.ask,
                spread_bps=spread_bps,
                bid_qty=pending.bid_qty,
                ask_qty=pending.ask_qty,
                quote_events=pending.events,
                trades=prints,
                signed_volume=signed,
                last_trade_price=last_price,
            )
        )

    hook = _truncation_hook(stat)
    needle = run_needle(run)
    for path in paths:
        stat.files += 1
        for line in iter_lines(path, on_truncated=hook):
            if not needle.search(line):
                continue
            found = _RECEIVE_TIME.search(line)
            if found is None:
                continue
            stat.quotes += 1
            bucket = _second(int(found.group(1)))
            if pending.bucket is None:
                pending.bucket = bucket
                continue
            if bucket == pending.bucket:
                continue
            raw = json.loads(line)
            bid, ask = raw.get("bid"), raw.get("ask")
            if not bid or not ask:
                pending.bucket = bucket
                continue
            pending.decision_time = int(raw["receive_time"])
            pending.bid = float(bid)
            pending.ask = float(ask)
            pending.bid_qty = float(raw.get("bid_qty") or 0.0)
            pending.ask_qty = float(raw.get("ask_qty") or 0.0)
            pending.events = 1
            pending.bucket = bucket
            flush()
            if previous is not None and bucket - previous > GRID_SECONDS * 1000:
                stat.missing_seconds += int((bucket - previous) / (GRID_SECONDS * 1000) - 1)
            previous = bucket
    # No trailing flush: a row is emitted when the stream moves to a later
    # second, so the last bucket that was emitted is already on disk and a
    # closing flush would write it twice.
    if pending.bucket is not None and previous is None:
        flush()


def ingest_agg_trades(
    writer: PanelWriter, run: str, market: str, symbol: str, paths: list[Path]
) -> dict[int, tuple[float, int, float]]:
    """Signed volume and the last print price per second (a second's own tape)."""
    stat = writer._stat(run, market, symbol)
    flow: dict[int, tuple[float, int, float]] = {}
    hook = _truncation_hook(stat)
    for path in paths:
        stat.files += 1
        for raw in iter_rows(path, on_truncated=hook):
            if raw.get("run_id") != run or raw.get("event_type") != "agg_trade":
                continue
            receive_time = raw.get("receive_time")
            price, quantity = raw.get("price"), raw.get("quantity")
            side = raw.get("aggressor_side")
            if not isinstance(receive_time, int) or not price or not quantity:
                continue
            sign = 1.0 if side == "buy" else -1.0
            quantity_f = float(quantity)
            bucket = _second(receive_time)
            signed, count, last_price = flow.get(bucket, (0.0, 0, 0.0))
            flow[bucket] = (
                signed + sign * quantity_f,
                count + 1,
                float(price),
            )
            stat.trades += 1
            stat.trade_volume += quantity_f
            _ = last_price
    return flow


def ingest_periodic(
    writer: PanelWriter, run: str, market: str, symbol: str, paths: list[Path]
) -> None:
    for path in paths:
        stat = writer._stat(run, market, symbol)
        stat.files += 1
        for raw in iter_rows(path, on_truncated=_truncation_hook(stat)):
            if raw.get("run_id") == run and raw.get("event_type") in (
                "open_interest",
                "funding",
                "mark_price",
            ):
                writer.write_oi(run, market, symbol, raw)


def ingest_depth(
    writer: PanelWriter, run: str, market: str, symbol: str, paths: list[Path]
) -> None:
    for path in paths:
        stat = writer._stat(run, market, symbol)
        stat.files += 1
        for raw in iter_rows(path, on_truncated=_truncation_hook(stat)):
            if raw.get("run_id") != run or raw.get("event_type") != "depth_snapshot":
                continue
            ts_ms = raw.get("receive_time") or raw.get("exchange_event_time")
            if not isinstance(ts_ms, int):
                continue
            for side_key, side in (("bids", "bid"), ("asks", "ask")):
                levels = raw.get(side_key) or []
                for level, entry in enumerate(levels[:DEPTH_LEVELS]):
                    if not isinstance(entry, list) or len(entry) < 2:
                        continue
                    writer.write_depth(run, market, symbol, ts_ms, side, level, entry[0], entry[1])
            writer._stat(run, market, symbol).depth_snapshots += 1


LAYERS: tuple[str, ...] = ("PANEL_SECONDS.csv", "OI_SAMPLES.csv", "DEPTH_SNAPSHOTS.csv")


def build(
    base: Path,
    *,
    runs: tuple[str, ...] | None = None,
    symbols: tuple[str, ...] = UNIVERSE,
    markets: tuple[str, ...] = ("spot", "perp"),
) -> dict[str, Any]:
    """Build the panel over the declared runs, symbols and markets."""
    base.mkdir(parents=True, exist_ok=True)
    roots = capture_roots(runs)
    coverage: list[dict[str, Any]] = []
    with (
        (base / "PANEL_SECONDS.csv").open("w", encoding="utf-8", newline="\n") as seconds,
        (base / "OI_SAMPLES.csv").open("w", encoding="utf-8", newline="\n") as oi,
        (base / "DEPTH_SNAPSHOTS.csv").open("w", encoding="utf-8", newline="\n") as depth,
    ):
        writer = PanelWriter(seconds, oi, depth)
        for root in roots:
            run = run_id_of(root)
            for market in markets:
                for symbol in symbols:
                    book = _segments(root, market, symbol, "book_ticker")
                    trades = _segments(root, market, symbol, "agg_trade")
                    periodic = _segments(root, market, symbol, "open_interest") + _segments(
                        root, market, symbol, "funding"
                    )
                    depth_files = _segments(root, market, symbol, "depth_snapshot")
                    if not book:
                        continue
                    flow = ingest_agg_trades(writer, run, market, symbol, trades)
                    ingest_book_ticker(writer, run, market, symbol, book, flow)
                    ingest_periodic(writer, run, market, symbol, periodic)
                    ingest_depth(writer, run, market, symbol, depth_files)
                    coverage.append(
                        {
                            "root": str(root.relative_to(REPO_ROOT)).replace("\\", "/"),
                            "run": run,
                            "market": market,
                            "symbol": symbol,
                            "book_ticker_files": len(book),
                            "agg_trade_files": len(trades),
                            "periodic_files": len(periodic),
                            "depth_snapshot_files": len(depth_files),
                            "tape_seconds": len(flow),
                        }
                    )
        writer.flush()
        stats = writer.stats
    return {
        "runs": [run_id_of(root) for root in roots],
        "coverage": coverage,
        "stats": stats,
        "paths": {
            "panel_seconds": str(base / "PANEL_SECONDS.csv"),
            "oi_samples": str(base / "OI_SAMPLES.csv"),
            "depth_snapshots": str(base / "DEPTH_SNAPSHOTS.csv"),
        },
        "grid_seconds": GRID_SECONDS,
        "depth_levels_kept": DEPTH_LEVELS,
        "sample_rule": SAMPLE_RULE,
    }


class PanelSeries:
    """One (run, market, symbol) stream, ordered by the instant it was knowable.

    ``forward_mid(seconds)`` walks the same array, so a feature built from row
    *i* is paired only with a mid whose decision clock is at or after
    ``decision_time + h``; a horizon that lands in a gap returns ``None`` and the
    observation is counted as a miss rather than interpolated.
    """

    __slots__ = ("_times", "market", "rows", "run", "symbol")

    def __init__(self, run: str, market: str, symbol: str, rows: list[dict[str, Any]]) -> None:
        self.run = run
        self.market = market
        self.symbol = symbol
        self.rows = sorted(rows, key=lambda row: int(row["decision_time"]))
        self._times = [int(row["decision_time"]) for row in self.rows]

    def __len__(self) -> int:
        return len(self.rows)

    def index_at_or_after(self, ts_ms: int) -> int | None:
        """The first row whose decision clock is not before ``ts_ms``."""
        position = bisect_left(self._times, ts_ms)
        return position if position < len(self._times) else None

    def forward_mid(self, index: int, horizon_seconds: int) -> float | None:
        target = int(self.rows[index]["decision_time"]) + horizon_seconds * 1000
        position = self.index_at_or_after(target)
        return None if position is None else float(self.rows[position]["mid"])

    def forward_return_bps(self, index: int, horizon_seconds: int) -> float | None:
        mid = float(self.rows[index]["mid"])
        later = self.forward_mid(index, horizon_seconds)
        if later is None or mid <= 0:
            return None
        return (later - mid) / mid * 10_000.0

    def first_trade_after(self, index: int) -> tuple[float, int] | None:
        """The first print at or after this row's decision clock, price and delay."""
        for position in range(index, min(index + 5, len(self.rows))):
            row = self.rows[position]
            if int(row["trades"]) > 0 and float(row["last_trade_price"]) > 0:
                return float(row["last_trade_price"]), position - index
        return None

    def span_seconds(self) -> float:
        if not self.rows:
            return 0.0
        span_ms = int(self.rows[-1]["decision_time"]) - int(self.rows[0]["decision_time"])
        return span_ms / 1000.0


PanelMap = dict[tuple[str, str, str], PanelSeries]


def read_panel_map(path: Path) -> PanelMap:
    """Read the panel into one series per (run, market, symbol)."""
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in read_panel(path):
        key = (row["run"], row["market"], row["symbol"])
        grouped.setdefault(key, []).append(row)
    return {key: PanelSeries(*key, rows) for key, rows in grouped.items()}


def read_depth(path: Path) -> list[dict[str, Any]]:
    """Read the kept depth levels, as numbers."""
    snapshots: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        header = handle.readline().strip().split(",")
        for line in handle:
            parts = line.strip().split(",")
            if len(parts) != len(header):
                continue
            raw = dict(zip(header, parts, strict=True))
            row: dict[str, Any] = dict(raw)
            row["ts_ms"] = int(raw["ts_ms"])
            row["level"] = int(raw["level"])
            row["price"] = float(raw["price"])
            row["qty"] = float(raw["qty"])
            snapshots.append(row)
    return snapshots


def read_oi(path: Path) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        header = handle.readline().strip().split(",")
        for line in handle:
            parts = line.strip().split(",")
            if len(parts) != len(header):
                continue
            raw = dict(zip(header, parts, strict=True))
            if not raw["ts_ms"] or not raw["open_interest"]:
                continue
            row: dict[str, Any] = dict(raw)
            row["ts_ms"] = int(raw["ts_ms"])
            row["open_interest"] = float(raw["open_interest"])
            row["mark_price"] = float(raw["mark_price"]) if raw["mark_price"] else None
            samples.append(row)
    return samples


def read_panel(path: Path) -> list[dict[str, Any]]:
    """Read the panel back as numbers (the experiment and verifier read this)."""
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        header = handle.readline().strip().split(",")
        for line in handle:
            parts = line.strip().split(",")
            if len(parts) != len(header):
                continue
            raw = dict(zip(header, parts, strict=True))
            row: dict[str, Any] = dict(raw)
            row["second_ms"] = int(raw["second_ms"])
            row["decision_time"] = int(raw["decision_time"])
            for key in ("quote_events", "trades"):
                row[key] = int(raw[key])
            for key in (
                "mid",
                "bid",
                "ask",
                "spread_bps",
                "bid_qty",
                "ask_qty",
                "signed_volume",
                "last_trade_price",
            ):
                row[key] = float(raw[key])
            rows.append(row)
    return rows


__all__ = [
    "DEPTH_LEVELS",
    "SAMPLE_RULE",
    "STREAMS",
    "PanelMap",
    "PanelSeries",
    "PanelStats",
    "PanelWriter",
    "SecondRow",
    "build",
    "capture_roots",
    "ingest_agg_trades",
    "ingest_book_ticker",
    "ingest_depth",
    "ingest_periodic",
    "iter_lines",
    "iter_rows",
    "read_depth",
    "read_oi",
    "read_panel",
    "read_panel_map",
    "run_id_of",
]
