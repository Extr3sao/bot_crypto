"""ALPHA-002 — capture and persist the derivatives series before they expire.

Run this often.  Binance keeps every ``/futures/data/*`` series for exactly 30 days
at every granularity (measured, not read from a doc), so the only lasting copy of
that history is the one this job writes to disk.  Nothing in ALPHA-002 can be
answered retroactively without it.

Each run:

1. pages **backwards** from now until the venue returns an empty page — that is the
   retention edge — so a run after a long outage still recovers everything that is
   still available rather than only the newest window;
2. stops early once it has reached the oldest bucket already stored, so a routine
   run costs a handful of requests;
3. merges by timestamp and rewrites the series atomically, so re-running a window
   is a no-op and a venue correction overwrites the earlier reading;
4. appends one line per series to ``CAPTURE_LOG.jsonl`` — the proof of *when* each
   piece of data entered the dataset, which is the only audit trail a
   forward-only source can have;
5. records coverage, gaps and a content digest in ``MANIFEST.json``.

Funding rate is the one full-history series; it is paged forwards instead.

Public market data only: no credentials, no orders, no capital.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.research.alpha002_capture import (  # noqa: E402
    PAGE_LIMIT,
    PERIODS,
    RETAINED_DAYS,
    SERIES,
    UNIVERSE,
    coverage,
    find_gaps,
    merge_records,
    period_ms,
    series_digest,
)

FAPI = "https://fapi.binance.com"
OUT_DIR = REPO / "data" / "raw" / "alpha002"
MANIFEST_PATH = OUT_DIR / "MANIFEST.json"
LOG_PATH = OUT_DIR / "CAPTURE_LOG.jsonl"

HEADERS = {"User-Agent": "trading-agentic-research/alpha002 (research; public market data)"}

#: Funding page size.  The venue returns 1000 rows per page when a startTime is
#: given (and silently fewer when it is not).
FUNDING_PAGE_LIMIT = 1000

#: Before any perpetual existed, so a forward page walk starts at the true beginning.
FUNDING_START_MS = 1_500_000_000_000

SLEEP_SECONDS = 0.15
MAX_RETRIES = 4
ACCEPTED_STATUS = 200


def get_json(path: str, *, retries: int = MAX_RETRIES) -> Any:
    """GET a public endpoint, backing off on venue rate limiting."""
    url = FAPI + path
    for attempt in range(retries):
        request = urllib.request.Request(url, headers=HEADERS)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                if response.status != ACCEPTED_STATUS:
                    raise RuntimeError(f"unexpected status {response.status} for {path}")
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            if error.code in (429, 418) and attempt + 1 < retries:
                time.sleep(2.0 * (attempt + 1))
                continue
            raise
    raise RuntimeError(f"exhausted retries for {path}")


def series_path(series_id: str, symbol: str, period: str | None) -> Path:
    directory = OUT_DIR / series_id
    name = f"{symbol}_{period}.json" if period else f"{symbol}.json"
    return directory / name


def load_series(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, list):
        raise ValueError(f"{path} does not hold a record list")
    return [record for record in loaded if isinstance(record, dict)]


def save_series(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(records, separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def retention_floor_ms(now_ms: int) -> int:
    """The oldest instant a retention-limited series can still return."""
    return now_ms - int(RETAINED_DAYS * 86_400_000)


def fetch_window(
    series: dict[str, Any], symbol: str, period: str, start_ms: int, end_ms: int
) -> list[dict[str, Any]]:
    """One explicit window request, newest page's worth of rows."""
    page = get_json(
        f"{series['path']}?symbol={symbol}&period={period}&limit={PAGE_LIMIT}"
        f"&startTime={start_ms}&endTime={end_ms}"
    )
    if not isinstance(page, list):
        raise RuntimeError(f"{series['series_id']} returned a non-list payload")
    return [record for record in page if isinstance(record, dict)]


def capture_backwards(
    series: dict[str, Any],
    symbol: str,
    period: str,
    stored: list[dict[str, Any]],
    *,
    max_pages: int,
    now_ms: int,
) -> tuple[list[dict[str, Any]], int, bool, str]:
    """Deep sweep: page a retention-limited series backwards from now.

    Used when a series starts empty, when the store has fallen behind the retention
    window, or when ``--deep`` asks for it.  Stops at the venue's retention edge, at
    ``max_pages``, or once it has reached the oldest bucket already stored.

    The venue answers ``400`` rather than an empty page when a window falls wholly
    before the retention floor, so a ``400`` counts as the edge *only* when the
    requested boundary is at or before that floor; anywhere else it is a real error
    and is re-raised.
    """
    key = str(series["timestamp_key"])
    step = period_ms(period)
    floor = retention_floor_ms(now_ms)
    oldest_stored = int(stored[0][key]) if stored else None
    end_time = now_ms
    fetched: list[dict[str, Any]] = []
    pages = 0
    exhausted = False
    for _ in range(max_pages):
        if end_time < floor:
            exhausted = True
            break
        try:
            page = get_json(
                f"{series['path']}?symbol={symbol}&period={period}&limit={PAGE_LIMIT}"
                f"&endTime={end_time}"
            )
        except urllib.error.HTTPError as error:
            if error.code == 400 and end_time <= floor + 2 * step:
                exhausted = True
                break
            raise
        pages += 1
        if not page:
            exhausted = True
            break
        if not isinstance(page, list):
            raise RuntimeError(f"{series['series_id']} returned a non-list payload")
        fetched.extend(record for record in page if isinstance(record, dict))
        first = int(page[0][key])
        end_time = first - 1
        if oldest_stored is not None and first <= oldest_stored:
            break
        time.sleep(SLEEP_SECONDS)
    return fetched, pages, exhausted, key


def capture_forward(
    series: dict[str, Any],
    symbol: str,
    period: str,
    stored: list[dict[str, Any]],
    *,
    max_pages: int,
    now_ms: int,
) -> tuple[list[dict[str, Any]], int, bool, str]:
    """Routine path: extend a series from its last stored bucket to now.

    A scheduled run normally costs a single request per series, which is what makes
    a 15-minute cadence cheap enough to actually keep running.
    """
    key = str(series["timestamp_key"])
    step = period_ms(period)
    start_time = int(stored[-1][key]) + step
    fetched: list[dict[str, Any]] = []
    pages = 0
    exhausted = False
    for _ in range(max_pages):
        page = get_json(
            f"{series['path']}?symbol={symbol}&period={period}&limit={PAGE_LIMIT}"
            f"&startTime={start_time}"
        )
        pages += 1
        if not page:
            exhausted = True
            break
        if not isinstance(page, list):
            raise RuntimeError(f"{series['series_id']} returned a non-list payload")
        rows = [record for record in page if isinstance(record, dict)]
        fetched.extend(rows)
        newest = int(rows[-1][key])
        if newest + step > now_ms or len(rows) < PAGE_LIMIT:
            exhausted = True
            break
        start_time = newest + step
        time.sleep(SLEEP_SECONDS)
    return fetched, pages, exhausted, key


def fill_gaps(
    series: dict[str, Any],
    symbol: str,
    period: str,
    stored: list[dict[str, Any]],
    *,
    now_ms: int,
    max_passes: int = 3,
) -> tuple[list[dict[str, Any]], int, int, str]:
    """Repair holes with explicit windows instead of hoping the pager covered them.

    Page-boundary requests can drop the boundary bucket, and an outage leaves a hole
    in the middle of a series.  Both are repaired the same way: ask for the missing
    window with a one-bucket margin on each side and merge, which is idempotent.
    """
    key = str(series["timestamp_key"])
    step = period_ms(period)
    floor = retention_floor_ms(now_ms)
    requested = 0
    fetched: list[dict[str, Any]] = []
    merged = list(stored)
    for _ in range(max_passes):
        gaps = find_gaps(merged, step_ms=step, timestamp_key=key)
        repairable = [gap for gap in gaps if int(gap["before_ts"]) + step > floor]
        if not repairable:
            break
        before = len(merged)
        for gap in repairable:
            left = max(floor, int(gap["after_ts"]) - step)
            right = min(now_ms, int(gap["before_ts"]) + step)
            rows = fetch_window(series, symbol, period, left, right)
            requested += 1
            fetched.extend(rows)
            merged = merge_records(merged, rows, timestamp_key=key)
            time.sleep(SLEEP_SECONDS)
        if len(merged) == before:
            break
    return fetched, requested, len(merged) - len(stored), key


def capture_funding(
    symbol: str,
    stored: list[dict[str, Any]],
    *,
    max_pages: int,
    now_ms: int,
) -> tuple[list[dict[str, Any]], int, bool, str]:
    """Page the full-history funding series forwards from the true beginning."""
    key = "fundingTime"
    start_time = int(stored[-1][key]) + 1 if stored else FUNDING_START_MS
    fetched: list[dict[str, Any]] = []
    pages = 0
    exhausted = False
    for _ in range(max_pages):
        page = get_json(
            f"/fapi/v1/fundingRate?symbol={symbol}&startTime={start_time}"
            f"&limit={FUNDING_PAGE_LIMIT}"
        )
        pages += 1
        if not page:
            exhausted = True
            break
        if not isinstance(page, list):
            raise RuntimeError("fundingRate returned a non-list payload")
        rows = [record for record in page if isinstance(record, dict)]
        fetched.extend(rows)
        first = int(rows[0][key])
        last = int(rows[-1][key])
        if last >= now_ms or len(rows) < FUNDING_PAGE_LIMIT:
            exhausted = True
            break
        if first > last:  # pragma: no cover - defensive; a page must move forwards
            raise RuntimeError("funding paging stalled")
        start_time = last + 1
        time.sleep(SLEEP_SECONDS)
    return fetched, pages, exhausted, key


def capture_series(
    series: dict[str, Any],
    symbol: str,
    period: str | None,
    *,
    max_pages: int,
    now_ms: int,
    deep: bool = False,
) -> dict[str, Any]:
    """Capture one (series, symbol, period) triple and persist it.

    Routine runs extend forwards and cost a request or two; a deep sweep is reserved
    for an empty series, a store that has fallen behind the retention window, or an
    explicit ``--deep``.  Either way the result is passed through hole repair before
    it is written, because a pager that is merely usually right is not good enough
    for a source that cannot be re-fetched.
    """
    path = series_path(str(series["series_id"]), symbol, period)
    stored = load_series(path)
    key = str(series["timestamp_key"])
    gap_requests = 0
    if bool(series["periodic"]) and period is not None:
        step = period_ms(period)
        floor = retention_floor_ms(now_ms)
        newest = int(stored[-1][key]) if stored else None
        lagging = newest is None or newest + step < floor
        if deep or lagging:
            mode = "backward"
            fetched, pages, exhausted, key = capture_backwards(
                series, symbol, period, stored, max_pages=max_pages, now_ms=now_ms
            )
        else:
            mode = "forward"
            fetched, pages, exhausted, key = capture_forward(
                series, symbol, period, stored, max_pages=max_pages, now_ms=now_ms
            )
        merged = merge_records(stored, fetched, timestamp_key=key)
        healed, gap_requests, _grown, key = fill_gaps(series, symbol, period, merged, now_ms=now_ms)
        if healed:
            fetched = [*fetched, *healed]
            merged = merge_records(merged, healed, timestamp_key=key)
    else:
        mode = "funding"
        fetched, pages, exhausted, key = capture_funding(
            symbol, stored, max_pages=max_pages, now_ms=now_ms
        )
        merged = merge_records(stored, fetched, timestamp_key=key)
    if merged != stored:
        save_series(path, merged)
    report = coverage(merged, timestamp_key=key)
    if period is not None:
        gaps: int | None = len(find_gaps(merged, step_ms=period_ms(period), timestamp_key=key))
        gap_basis = f"exact {period} grid"
    else:
        # Funding settles on a venue-defined interval that is not guaranteed constant
        # across the history, so a fixed grid would report spurious gaps.
        gaps = None
        gap_basis = "not evaluated: funding interval is venue-defined and variable"
    return {
        "series_id": series["series_id"],
        "symbol": symbol,
        "period": period,
        "mode": mode,
        "path": str(path.relative_to(REPO)).replace("\\", "/"),
        "fetched": len(fetched),
        "pages": pages,
        "gap_repair_requests": gap_requests,
        "source_exhausted": exhausted,
        "max_pages_hit": not exhausted,
        "rows": report["count"],
        "first_ts": report["first_ts"],
        "last_ts": report["last_ts"],
        "span_days": report["span_days"],
        "gaps": gaps,
        "gap_basis": gap_basis,
        "digest": series_digest(merged),
    }


def build_manifest(results: list[dict[str, Any]], started: int, finished: int) -> dict[str, Any]:
    return {
        "campaign": "ALPHA-002",
        "generated_at_ms": finished,
        "generated_at_utc": dt.datetime.fromtimestamp(finished / 1000, dt.UTC).isoformat(),
        "window_seconds": round((finished - started) / 1000.0, 3),
        "universe": list(UNIVERSE),
        "periods": list(PERIODS),
        "series": [item["series_id"] for item in SERIES],
        "retention_policy": (
            "Binance retains /futures/data/* for 30 days at every granularity; fundingRate is "
            "full history. A day without a capture run is a day of information destroyed."
        ),
        "records": {
            f"{item['series_id']}|{item['symbol']}|{item['period']}": {
                "rows": item["rows"],
                "first_ts": item["first_ts"],
                "last_ts": item["last_ts"],
                "span_days": item["span_days"],
                "gaps": item["gaps"],
                "digest": item["digest"],
            }
            for item in results
        },
        "totals": {
            "series_captured": len(results),
            "rows": sum(int(item["rows"]) for item in results),
            "rows_fetched_this_run": sum(int(item["fetched"]) for item in results),
            "requests_this_run": sum(
                int(item["pages"]) + int(item["gap_repair_requests"]) for item in results
            ),
            "modes": {
                mode: sum(1 for item in results if item["mode"] == mode)
                for mode in sorted({str(item["mode"]) for item in results})
            },
            "series_with_gaps": sum(1 for item in results if int(item["gaps"] or 0) > 0),
            "gap_repair_requests": sum(int(item["gap_repair_requests"]) for item in results),
            "source_exhausted": sum(1 for item in results if bool(item["source_exhausted"])),
            "max_pages_hit": sum(1 for item in results if bool(item["max_pages_hit"])),
        },
        "source_exhausted_means": (
            "the pager stopped because the source had nothing more to give - the retention floor "
            "in a backward sweep, the present in a forward fill, the end of the payments in "
            "funding - rather than because it ran into --max-pages. A non-zero max_pages_hit "
            "count means a series may still be short and must be re-swept with --deep."
        ),
        "runs": LOG_PATH.name,
    }


def append_log(results: list[dict[str, Any]], at: int) -> None:
    """Append one line per series: the audit trail of a forward-only dataset."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        for item in results:
            handle.write(
                json.dumps(
                    {
                        "at_ms": at,
                        "at_utc": dt.datetime.fromtimestamp(at / 1000, dt.UTC).isoformat(),
                        **item,
                    },
                    separators=(",", ":"),
                    ensure_ascii=False,
                )
                + "\n"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ALPHA-002 derivatives capture")
    parser.add_argument("--symbols", default=",".join(UNIVERSE))
    parser.add_argument("--periods", default=",".join(PERIODS))
    parser.add_argument("--series", default=",".join(str(item["series_id"]) for item in SERIES))
    parser.add_argument("--max-pages", type=int, default=40)
    parser.add_argument(
        "--deep",
        action="store_true",
        help="force a full backward sweep plus gap repair instead of forward-filling",
    )
    parser.add_argument("--dry-run", action="store_true", help="report without writing")
    args = parser.parse_args(argv)

    wanted_series = {item for item in args.series.split(",") if item}
    wanted_periods = {item for item in args.periods.split(",") if item}
    symbols = [item for item in args.symbols.split(",") if item]

    started = int(time.time() * 1000)
    now_ms = started
    results: list[dict[str, Any]] = []
    for series in SERIES:
        if series["series_id"] not in wanted_series:
            continue
        for symbol in symbols:
            targets: list[str | None] = sorted(wanted_periods) if series["periodic"] else [None]
            for period in targets:
                entry = capture_series(
                    series,
                    symbol,
                    period,
                    max_pages=args.max_pages,
                    now_ms=now_ms,
                    deep=args.deep,
                )
                results.append(entry)
                gaps_shown = "n/a" if entry["gaps"] is None else str(entry["gaps"])
                print(
                    f"{entry['series_id']:34s} {entry['symbol']:9s} "
                    f"{entry['period'] or '-':4s} {entry['mode']:8s} "
                    f"rows={entry['rows']:7d} +{entry['fetched']:6d} "
                    f"span={entry['span_days']:6.2f}d gaps={gaps_shown:>4s} "
                    f"pages={entry['pages']:3d} exhausted={entry['source_exhausted']}"
                )

    finished = int(time.time() * 1000)
    if args.dry_run:
        print(json.dumps({"dry_run": True, "series": len(results)}, indent=2))
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(results, started, finished)
    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    append_log(results, finished)
    print(json.dumps(manifest["totals"], indent=2))
    print("manifest:", MANIFEST_PATH.relative_to(REPO))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
