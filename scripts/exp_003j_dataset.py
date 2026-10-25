"""exp_003j_dataset — freeze a point-in-time 1-minute dataset, with provenance.

    ./.venv/Scripts/python.exe scripts/exp_003j_dataset.py --fetch
    ./.venv/Scripts/python.exe scripts/exp_003j_dataset.py --verify

WP-003J-01 of RFC-TA-EXP-003J-001. The experiment needs bars that were already
public when a decision was stamped, and it needs to be able to prove later that
the file it measured is the file it ran. So this script does two separate things
and never merges them:

``--fetch``
    pages the venue's public klines endpoint forward from ``--start`` to
    ``--end``, one 1 000-row page at a time, and writes every page's request,
    server clock and receipt instant into ``DATASET_MANIFEST.json``. Bars are
    stored as ``[open_ms, open, high, low, close, volume]`` in a gzip member
    whose header carries a zero mtime, so two fetches of the same range produce
    the same bytes and one hash.

``--verify``
    re-reads the frozen files, recomputes their digests and the coverage
    statistics, and refuses a dataset whose manifest no longer describes it.
    It never contacts the venue: the point of freezing is that verification does
    not depend on the network being up or on the venue still serving the range.

What this script refuses to do: invent a missing minute (a hole is counted, not
filled), accept a non-aligned or non-positive row, treat a forming bar as closed,
or claim that coverage it did not observe.

No credential is read. The endpoint is the public spot klines API the PAPER
collector already uses (``trading_bot.market_data.minute_collector``).
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import itertools
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from trading_bot.market_data.minute_collector import (  # noqa: E402
    MINUTE_MS,
    BinanceRestSource,
    SourceUnavailable,
)

DEFAULT_OUT = REPO / "reports" / "ai-bots" / "EXP-003J-REAL-SIGNAL-PAPER-001" / "dataset"
SCHEMA = "AI_BOTS_003J_DATASET_MANIFEST_V1"
PAGE_LIMIT = 1000
#: The venue answers ~1 200 weight/minute and a klines page costs 2; 0.25 s between
#: pages is an order of magnitude below the ceiling without hammering a public endpoint.
PAGE_PAUSE_S = 0.25


def _utc(ms: int) -> str:
    return datetime.fromtimestamp(int(ms) / 1000.0, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_utc(text: str) -> int:
    return int(datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp() * 1000)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _row(raw: Any) -> list[Any]:
    """One validated bar row, or a refusal.

    A row that is not a closed, aligned, positive minute is a data defect, not
    something to coerce: coercing it would put an invented price into a run whose
    whole point is that its prices are the venue's.
    """

    if len(raw) < 6:
        raise SourceUnavailable("SHORT_ROW", f"a kline needs 6 fields, got {len(raw)}")
    try:
        open_ms = int(raw[0])
        values = [float(raw[1]), float(raw[2]), float(raw[3]), float(raw[4]), float(raw[5])]
    except (TypeError, ValueError) as exc:
        raise SourceUnavailable("UNPARSABLE_ROW", f"kline is not numeric: {exc}") from exc
    if open_ms % MINUTE_MS:
        raise SourceUnavailable("UNALIGNED_MINUTE", f"{open_ms} is not on a minute boundary")
    open_, high, low, close, volume = values
    if min(open_, high, low, close) <= 0:
        raise SourceUnavailable("NON_POSITIVE_PRICE", f"minute {open_ms} has a non-positive price")
    if high < max(open_, close) or low > min(open_, close):
        raise SourceUnavailable("OHLC_INCONSISTENT", f"minute {open_ms} has OHLC outside its range")
    if volume < 0:
        raise SourceUnavailable("NEGATIVE_VOLUME", f"minute {open_ms} has negative volume")
    return [open_ms, open_, high, low, close, volume]


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_bars(path: Path, bars: list[list[Any]]) -> None:
    """Deterministic gzip: fixed mtime, fixed compression level, sorted rows."""

    lines = "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in bars)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = lines.encode("utf-8")
    # mtime=0 keeps the gzip header out of the hash: the digest describes the bars.
    with (
        path.open("wb") as handle,
        gzip.GzipFile(fileobj=handle, mode="wb", compresslevel=6, mtime=0) as gz,
    ):
        gz.write(raw)


def read_bars(path: Path) -> list[list[Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _coverage(bars: list[list[Any]]) -> dict[str, Any]:
    """Coverage and gaps, counted from the rows themselves."""

    if not bars:
        return {
            "bars": 0,
            "first_open_ms": None,
            "last_open_ms": None,
            "first_open_utc": None,
            "last_open_utc": None,
            "span_hours": 0.0,
            "expected_bars": 0,
            "missing_bars": 0,
            "duplicate_bars": 0,
            "max_gap_bars": 0,
            "gaps": [],
        }
    stamps = [int(row[0]) for row in bars]
    duplicates = len(stamps) - len(set(stamps))
    ordered = sorted(set(stamps))
    gaps: list[dict[str, Any]] = []
    missing = 0
    max_gap = 0
    for previous, current in itertools.pairwise(ordered):
        step = (current - previous) // MINUTE_MS
        if step > 1:
            count = int(step - 1)
            missing += count
            max_gap = max(max_gap, count)
            if len(gaps) < 50:
                gaps.append(
                    {
                        "after_ms": int(previous),
                        "after_utc": _utc(previous),
                        "before_ms": int(current),
                        "before_utc": _utc(current),
                        "missing_bars": count,
                    }
                )
    expected = (ordered[-1] - ordered[0]) // MINUTE_MS + 1
    return {
        "bars": len(bars),
        "first_open_ms": int(ordered[0]),
        "last_open_ms": int(ordered[-1]),
        "first_open_utc": _utc(ordered[0]),
        "last_open_utc": _utc(ordered[-1]),
        "last_close_utc": _utc(ordered[-1] + MINUTE_MS),
        "span_hours": round(len(ordered) * MINUTE_MS / 3_600_000.0, 3),
        "expected_bars": int(expected),
        "missing_bars": int(missing),
        "duplicate_bars": int(duplicates),
        "max_gap_bars": int(max_gap),
        "complete": bool(missing == 0 and duplicates == 0),
        "gaps": gaps,
    }


def fetch_symbol(
    source: BinanceRestSource,
    symbol: str,
    *,
    start_ms: int,
    end_ms: int,
    progress: Any = None,
) -> tuple[list[list[Any]], list[dict[str, Any]]]:
    """Page one symbol forward, recording every page's provenance."""

    bars: dict[int, list[Any]] = {}
    pages: list[dict[str, Any]] = []
    cursor = int(start_ms)
    while cursor < int(end_ms):
        page = source.fetch(symbol, start_ms=cursor, end_ms=end_ms, limit=PAGE_LIMIT)
        rows = [_row(raw) for raw in page.rows]
        if not rows:
            # The venue answered an empty page for a range it should serve. That is
            # a hole with a cause, not the end of the data.
            pages.append(
                {
                    "request_start_ms": cursor,
                    "request_start_utc": _utc(cursor),
                    "rows": 0,
                    "empty_page": True,
                }
            )
            cursor += PAGE_LIMIT * MINUTE_MS
            continue
        for row in rows:
            bars[int(row[0])] = row
        last_open = int(rows[-1][0])
        pages.append(
            {
                "request_start_ms": cursor,
                "request_start_utc": _utc(cursor),
                "request_start_utc_iso": _utc(cursor),
                "rows": len(rows),
                "first_open_ms": int(rows[0][0]),
                "first_open_utc": _utc(int(rows[0][0])),
                "last_open_ms": last_open,
                "last_open_utc": _utc(last_open),
                "server_time_ms": int(page.server_time_ms),
                "received_at_ms": int(page.received_at_ms),
                "http_status": 200,
            }
        )
        if progress is not None:
            progress(f"{symbol}: {len(bars)} bars through {_utc(last_open)}")
        # Advance from the last closed minute; a forming row would repeat otherwise.
        cursor = last_open + MINUTE_MS
        if last_open < start_ms:
            raise SourceUnavailable("NO_PROGRESS", f"{symbol}: the page did not advance")
        time.sleep(PAGE_PAUSE_S)
    ordered = [bars[stamp] for stamp in sorted(bars) if start_ms <= stamp < end_ms]
    return ordered, pages


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true", help="contact the public endpoint")
    parser.add_argument("--verify", action="store_true", help="re-derive from frozen files")
    parser.add_argument("--symbols", nargs="*", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    parser.add_argument("--start", default="2026-08-20T00:00:00Z")
    parser.add_argument("--end", default="2026-10-19T00:00:00Z")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)

    out = Path(args.out)
    manifest_path = out / "DATASET_MANIFEST.json"

    if args.fetch:
        start_ms, end_ms = _parse_utc(args.start), _parse_utc(args.end)
        if end_ms <= start_ms:
            print("[003j-dataset] REFUSED — end must be after start", file=sys.stderr)
            return 2
        source = BinanceRestSource()
        manifest: dict[str, Any] = {
            "schema_version": SCHEMA,
            "generated_by": "scripts/exp_003j_dataset.py --fetch",
            "venue": "binance-spot",
            "endpoint": "/api/v3/klines",
            "interval": "1m",
            "requested_start_utc": args.start,
            "requested_end_utc": args.end,
            "requested_start_ms": start_ms,
            "requested_end_ms": end_ms,
            "fetched_at_utc": _utc(int(time.time() * 1000)),
            "credential_used": False,
            "symbols": {},
        }
        failures: dict[str, str] = {}
        for symbol in args.symbols:
            try:
                bars, pages = fetch_symbol(
                    source,
                    symbol,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    progress=lambda message: print(f"[003j-dataset] {message}", flush=True),
                )
            except SourceUnavailable as exc:
                failures[symbol] = f"{exc.code}: {exc}"
                print(f"[003j-dataset] FAILED {symbol}: {exc}", file=sys.stderr)
                continue
            path = out / f"{symbol}.1m.jsonl.gz"
            _write_bars(path, bars)
            manifest["symbols"][symbol] = {
                "file": path.name,
                "sha256": _sha256_file(path),
                "bytes": path.stat().st_size,
                "coverage": _coverage(bars),
                "pages": pages,
                "page_count": len(pages),
            }
        manifest["failed_symbols"] = failures
        _write_json(manifest_path, manifest)
        print(f"[003j-dataset] wrote {manifest_path}")
        return 2 if failures else 0

    if args.verify:
        if not manifest_path.exists():
            print(f"[003j-dataset] BLOCKED — no manifest at {manifest_path}", file=sys.stderr)
            return 2
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        problems: list[str] = []
        for symbol, entry in sorted(manifest.get("symbols", {}).items()):
            path = out / entry["file"]
            if not path.exists():
                problems.append(f"{symbol}: missing {path.name}")
                continue
            digest = _sha256_file(path)
            if digest != entry["sha256"]:
                problems.append(f"{symbol}: sha256 {digest} != manifest {entry['sha256']}")
            bars = read_bars(path)
            coverage = _coverage(bars)
            if coverage["bars"] != entry["coverage"]["bars"]:
                problems.append(f"{symbol}: bars {coverage['bars']} != manifest")
            if coverage["complete"] != entry["coverage"]["complete"]:
                problems.append(f"{symbol}: completeness differs from manifest")
        verdict = "PASS" if not problems else "FAIL"
        print(f"[003j-dataset] verify {verdict} ({len(manifest.get('symbols', {}))} symbols)")
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 0 if verdict == "PASS" else 1

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
