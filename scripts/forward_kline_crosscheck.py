"""Volume cross-check: captured aggTrades against the venue's own klines (§16).

A capture can be internally consistent and still be wrong: the ids can be
contiguous, the book reconciling and the replay deterministic, while the trades
themselves are a filtered subset of what happened. This script closes that hole
by comparing what the capture recorded for a minute with what the venue says
happened in that same minute, using a public endpoint that has no relationship
with the collector's WebSocket path.

It is a **data-quality** check, never a strategy measurement.

Buckets that overlap an unrecovered hole are excluded and counted, because a
bucket with a known hole is expected to disagree — including it would either
hide the hole or manufacture a failure. The output records how many were
excluded and why, so the exclusion is auditable.

Writes ``docs/FORWARD_DATA_KLINE_CROSSCHECK.json``.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trading_bot.research.forward.replay import ForwardReplay  # noqa: E402
from trading_bot.research.forward.reporting import load_run  # noqa: E402

SPOT_REST = "https://api.binance.com"
KLINES_PATH = "/api/v3/klines"
MINUTE_MS = 60_000
#: Enough buckets to be meaningful, few enough to stay a quick public request.
MAX_BUCKETS_PER_SYMBOL = 25
OUTPUT = ROOT / "docs" / "FORWARD_DATA_KLINE_CROSSCHECK.json"


def _fetch_klines(symbol: str, start_ms: int, end_ms: int) -> list[list[Any]]:
    query = urllib.parse.urlencode(
        {
            "symbol": symbol,
            "interval": "1m",
            "startTime": start_ms,
            "endTime": end_ms,
            "limit": MAX_BUCKETS_PER_SYMBOL * 2,
        }
    )
    url = f"{SPOT_REST}{KLINES_PATH}?{query}"
    request = urllib.request.Request(url, headers={"User-Agent": "forward-kline-crosscheck/1"})
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, list):
        raise RuntimeError(f"unexpected kline payload from {url}")
    return payload


def _gap_windows(manifest: dict[str, Any], market: str, symbol: str) -> list[tuple[int, int]]:
    windows: list[tuple[int, int]] = []
    for gap in manifest.get("gaps", []):
        if gap.get("market") != market or gap.get("symbol") != symbol:
            continue
        if gap.get("event_type") != "agg_trade" or not gap.get("data_lost"):
            continue
        windows.append((int(gap["start_ms"]), int(gap["end_ms"])))
    return windows


def crosscheck(run_id: str | None, docs_dir: Path) -> dict[str, Any]:
    base = ROOT / "reports" / "microstructure-forward"
    resolved, manifest = load_run(base, run_id)
    # Streamed, never materialised: an hour of one busy stream is a single
    # segment of ~10^6 rows, and this helper must run on the real capture (§34).
    rows = ForwardReplay(base, resolved).iter_rows()

    buckets: dict[tuple[str, int], Decimal] = {}
    trades: dict[tuple[str, int], int] = {}
    for row, _partial in rows:
        if row.get("event_type") != "agg_trade" or row.get("market") != "spot":
            continue
        event_time = row.get("exchange_event_time")
        quantity = row.get("quantity")
        if not isinstance(event_time, int) or not isinstance(quantity, str):
            continue
        try:
            size = Decimal(quantity)
        except InvalidOperation:  # pragma: no cover - contract forbids this
            continue
        key = (str(row.get("symbol")), (event_time // MINUTE_MS) * MINUTE_MS)
        buckets[key] = buckets.get(key, Decimal(0)) + size
        trades[key] = trades.get(key, 0) + 1

    captured_from = min((open_ms for _, open_ms in buckets), default=None)
    captured_to = max((open_ms for _, open_ms in buckets), default=None)
    compared: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    symbols = sorted({symbol for symbol, _ in buckets})

    for symbol in symbols:
        holes = _gap_windows(manifest, "spot", symbol)
        start = (captured_from or 0) + MINUTE_MS
        end = (captured_to or 0) - MINUTE_MS
        if end <= start:
            continue
        try:
            klines = _fetch_klines(symbol, start, end)
        except (urllib.error.URLError, TimeoutError, RuntimeError) as exc:
            return {
                "run_id": resolved,
                "commit": manifest.get("commit"),
                "error": f"{type(exc).__name__}: {exc}",
                "buckets": compared,
                "note": "the public kline endpoint was unreachable; no comparison was made",
            }
        wanted = [(b, size) for (sym, b), size in buckets.items() if sym == symbol and start <= b <= end]
        wanted.sort()
        used = 0
        for open_ms, size in wanted:
            if used >= MAX_BUCKETS_PER_SYMBOL:
                break
            close_ms = open_ms + MINUTE_MS - 1
            if any(start_ms <= close_ms and open_ms <= end_ms for start_ms, end_ms in holes):
                excluded.append({"symbol": symbol, "open_time_ms": open_ms, "reason": "data_loss"})
                continue
            close_price = None
            for kline in klines:
                if int(kline[0]) != open_ms:
                    continue
                volume = Decimal(str(kline[5]))
                close_price = str(kline[4])
                break
            else:
                excluded.append({"symbol": symbol, "open_time_ms": open_ms, "reason": "no_kline"})
                continue
            if volume <= 0:
                excluded.append({"symbol": symbol, "open_time_ms": open_ms, "reason": "zero_volume"})
                continue
            compared.append(
                {
                    "symbol": symbol,
                    "open_time_ms": open_ms,
                    "trades": trades.get((symbol, open_ms), 0),
                    "capture_volume": str(size),
                    "kline_volume": str(volume),
                    "ratio": str(round(float(size / volume), 6)),
                    "kline_close": close_price,
                }
            )
            used += 1

    ratios = [float(entry["ratio"]) for entry in compared]
    ratios.sort()
    payload = {
        "run_id": resolved,
        "commit": manifest.get("commit"),
        "capture_started_at": manifest.get("started_at"),
        "capture_ended_at": manifest.get("ended_at"),
        "source": f"{SPOT_REST}{KLINES_PATH} (public, 1m)",
        "method": (
            "sum of captured aggTrade quantity per completed minute against the venue's "
            "own 1m kline volume for the same minute; buckets overlapping an unrecovered "
            "hole are excluded and listed"
        ),
        "buckets_compared": len(compared),
        "buckets_excluded": len(excluded),
        "exclusions": excluded[:20],
        "worst_ratio_deviation": max((abs(value - 1.0) for value in ratios), default=None),
        "median_ratio": ratios[len(ratios) // 2] if ratios else None,
        "buckets": compared,
        "note": (
            "agreement means the persisted trades are the venue's trades for that minute; "
            "it is a data-quality check and carries no information about edge or returns"
        ),
    }
    docs_dir.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--docs-dir", default="docs")
    args = parser.parse_args(argv)
    payload = crosscheck(args.run_id, ROOT / args.docs_dir)
    print(json.dumps({key: payload[key] for key in payload if key != "buckets"}, indent=2))
    return 0 if payload.get("buckets_compared") else 1


if __name__ == "__main__":
    raise SystemExit(main())
