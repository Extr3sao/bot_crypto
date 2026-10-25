"""WP-PAPER-REAL-DATA-001 — real 1h market-data quality gate (read-only).

This script answers ONE question with evidence instead of prose: *are the bars
the PAPER runtime is about to consume real, closed, gap-free and free of
look-ahead?*

Provenance rules applied here:

* the bars come from the exchange's **public** kline endpoint
  (``https://api.binance.com/api/v3/klines``) over plain HTTPS, with **no**
  credential, no signature and no authenticated route;
* the exact response bytes are hashed (``raw_sha256``) and the server ``Date``
  header is recorded, so the artefact is tied to the HTTP exchange that
  produced it;
* the same window is fetched a second time through **CCXT** (the library the
  runtime's connector uses) and every overlapping closed bar must be identical.
  Two independent client paths agreeing is what lets us call the series real
  rather than "whatever one library returned".

PIT rule: a bar stamped ``ts`` (OPEN) is only tradable evidence once it closes,
i.e. ``ts + tf <= now``. The last bar of a Klines response is normally the
*forming* one; it is excluded from every computed quantity here and counted so
the exclusion is visible.

Usage::

    uv run python scripts/wp_prd001_data_quality.py --out-dir <dir>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
import urllib.request
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

SYMBOLS: tuple[str, ...] = ("BTC", "ETH", "SOL")
TIMEFRAME = "1h"
TF_MS = 3_600_000
#: Bars requested per symbol: enough to fill the runtime's default 120-bar
#: lookback window with closed bars, plus slack.
WINDOW = 200
#: The runtime's default ``--lookback-bars``. The decision window digest is
#: computed over exactly this many newest CLOSED bars.
LOOKBACK_BARS = 120
#: ``router_gates.DEFAULT_FRESHNESS_GRACE_BARS`` — 1.5 bars. A sealed 1h bar may
#: be at most this old before the router calls the context stale.
STALE_BUDGET_MS = int(TF_MS * 1.5)

KLINE_URL = "https://api.binance.com/api/v3/klines"


def iso(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000.0, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _http_get_json(url: str) -> tuple[bytes, dict[str, str], Any]:
    """Plain public GET: no headers carrying identity, no signing."""
    request = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read()
        headers = {k.lower(): v for k, v in response.headers.items()}
    return body, headers, json.loads(body)


def fetch_raw(symbol: str, *, limit: int = WINDOW) -> dict[str, Any]:
    """Public klines, exactly as served, plus the digest of those bytes."""
    pair = f"{symbol}USDT"
    url = f"{KLINE_URL}?symbol={pair}&interval={TIMEFRAME}&limit={limit}"
    body, headers, payload = _http_get_json(url)
    rows = [
        {
            "ts": int(row[0]),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
            "close_ts": int(row[6]),
        }
        for row in payload
    ]
    return {
        "pair": pair,
        "url": url,
        "http_date": headers.get("date"),
        "raw_sha256": hashlib.sha256(body).hexdigest(),
        "raw_bytes": len(body),
        "rows": rows,
    }


def fetch_ccxt(symbol: str, *, limit: int = WINDOW) -> dict[str, Any]:
    """Second client path: CCXT (what the runtime connector itself uses)."""
    import ccxt

    exchange = ccxt.binance({"enableRateLimit": True, "apiKey": "", "secret": ""})
    raw = exchange.fetch_ohlcv(f"{symbol}/USDT", TIMEFRAME, limit=limit)
    rows = [
        {
            "ts": int(row[0]),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
            "close_ts": int(row[0]) + TF_MS,
        }
        for row in raw
    ]
    return {"rows": rows, "provider": "ccxt", "exchange": "binance"}


def validate(symbol: str, rows: list[dict[str, Any]], *, now_ms: int) -> dict[str, Any]:
    """Every check names the failure it would have caught."""
    stamps = [r["ts"] for r in rows]
    closed = [r for r in rows if r["close_ts"] <= now_ms]
    forming = [r for r in rows if r["close_ts"] > now_ms]

    duplicates = len(stamps) - len(set(stamps))
    strictly_increasing = all(b > a for a, b in pairwise(stamps))
    grid_misaligned = [ts for ts in stamps if ts % TF_MS != 0]

    gaps: list[dict[str, Any]] = []
    for prev, current in pairwise(closed):
        delta = current["ts"] - prev["ts"]
        if delta != TF_MS:
            gaps.append(
                {
                    "after": iso(prev["ts"]),
                    "before": iso(current["ts"]),
                    "missing_bars": delta // TF_MS - 1,
                }
            )

    ohlc_bad: list[str] = []
    for row in closed:
        values = [row["open"], row["high"], row["low"], row["close"], row["volume"]]
        if not all(isinstance(v, float) and math.isfinite(v) for v in values):
            ohlc_bad.append(f"{iso(row['ts'])}:non_finite")
            continue
        if row["low"] > min(row["open"], row["close"]) or row["high"] < max(
            row["open"], row["close"]
        ):
            ohlc_bad.append(f"{iso(row['ts'])}:body_outside_range")
        if row["high"] < row["low"] or min(row["open"], row["high"], row["low"], row["close"]) <= 0:
            ohlc_bad.append(f"{iso(row['ts'])}:non_positive_or_inverted")
        if row["volume"] < 0:
            ohlc_bad.append(f"{iso(row['ts'])}:negative_volume")

    last_closed = closed[-1] if closed else None
    age_ms = None if last_closed is None else now_ms - last_closed["close_ts"]

    # The exact PIT slice a decision taken `now` may use: newest CLOSED bars.
    window = closed[-LOOKBACK_BARS:]
    window_payload = json.dumps(
        [[r["ts"], r["open"], r["high"], r["low"], r["close"], r["volume"]] for r in window],
        separators=(",", ":"),
    )

    checks = {
        "bars_present": len(rows) > 0,
        "grid_aligned": not grid_misaligned,
        "strictly_increasing": strictly_increasing,
        "no_duplicates": duplicates == 0,
        "no_gaps": not gaps,
        "closed_bars_available": len(closed) >= LOOKBACK_BARS,
        "ohlcv_sane": not ohlc_bad,
        "fresh_last_closed_bar": age_ms is not None and age_ms <= STALE_BUDGET_MS,
        "forming_bar_excluded": True,  # by construction: all metrics use `closed`
    }
    return {
        "symbol": symbol,
        "timeframe": TIMEFRAME,
        "bars_returned": len(rows),
        "closed_bars": len(closed),
        "forming_bars_dropped": len(forming),
        "first_closed": None if not closed else iso(closed[0]["ts"]),
        "last_closed_open": None if last_closed is None else iso(last_closed["ts"]),
        "last_closed_close": None if last_closed is None else iso(last_closed["close_ts"]),
        "last_closed_close_price": None if last_closed is None else last_closed["close"],
        "age_of_last_closed_bar_ms": age_ms,
        "stale_budget_ms": STALE_BUDGET_MS,
        "duplicates": duplicates,
        "gaps": gaps,
        "ohlcv_violations": ohlc_bad,
        "grid_misaligned_timestamps": [iso(ts) for ts in grid_misaligned],
        "lookahead_bars_in_window": 0,
        "pit_window_bars": len(window),
        # Exact millisecond bounds. A human-readable ISO string truncates to the
        # second, and this feed's close stamps end in ...999 ms: selecting a
        # window with the rounded bound silently dropped one bar (found by this
        # WP's own verifier). The verifier selects on these integers.
        "pit_window_first_open_ms": None if not window else window[0]["ts"],
        "pit_window_last_open_ms": None if not window else window[-1]["ts"],
        "pit_window_first_close": None if not window else iso(window[0]["close_ts"]),
        "pit_window_last_close": None if not window else iso(window[-1]["close_ts"]),
        "pit_window_sha256": hashlib.sha256(window_payload.encode("utf-8")).hexdigest(),
        "checks": checks,
        "ok": all(checks.values()),
    }


def cross_check(
    symbol: str,
    raw_rows: list[dict[str, Any]],
    ccxt_rows: list[dict[str, Any]],
    *,
    now_ms: int,
) -> dict[str, Any]:
    """Overlapping CLOSED bars must be byte-equal between two client paths.

    Only closed bars are comparable: the forming bar legitimately changes
    between two reads (its volume and close keep moving until it seals), so
    comparing it would flag the market's own progress as a data defect.
    """
    right = {r["ts"]: r for r in ccxt_rows}
    compared = 0
    skipped_forming = 0
    mismatches: list[str] = []
    for row in raw_rows:
        if row["close_ts"] > now_ms:
            skipped_forming += 1
            continue
        other = right.get(row["ts"])
        if other is None:
            continue
        compared += 1
        if any(
            abs(float(row[key]) - float(other[key])) > 1e-12
            for key in ("open", "high", "low", "close", "volume")
        ):
            mismatches.append(iso(row["ts"]))
    return {
        "symbol": symbol,
        "bars_compared": compared,
        "forming_bars_skipped": skipped_forming,
        "mismatches": mismatches,
        "agrees": compared > 0 and not mismatches,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default=str(REPO_ROOT / "docs/agentic/paper_reald"))
    parser.add_argument("--symbols", default=",".join(SYMBOLS))
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    symbols = tuple(s.strip().upper() for s in args.symbols.split(",") if s.strip())

    started_ms = int(time.time() * 1000)
    per_symbol: list[dict[str, Any]] = []
    for symbol in symbols:
        raw = fetch_raw(symbol)
        # Second client path fetched AFTER the raw one: a bar that closed in
        # between is compared only when both sides carry it.
        ccxt_page = fetch_ccxt(symbol)
        now_ms = int(time.time() * 1000)
        result = validate(symbol, raw["rows"], now_ms=now_ms)
        result.update(
            {
                "pair": raw["pair"],
                "endpoint": raw["url"],
                "http_date": raw["http_date"],
                "raw_sha256": raw["raw_sha256"],
                "raw_bytes": raw["raw_bytes"],
                "authenticated": False,
                "cross_check": cross_check(
                    symbol, raw["rows"], ccxt_page["rows"], now_ms=now_ms
                ),
            }
        )
        result["ok"] = result["ok"] and result["cross_check"]["agrees"]
        result["checks"]["cross_source_agreement"] = result["cross_check"]["agrees"]
        per_symbol.append(result)
        print(
            f"[data] {symbol:4s} closed={result['closed_bars']:3d} "
            f"dropped_forming={result['forming_bars_dropped']} "
            f"age={result['age_of_last_closed_bar_ms']}ms "
            f"gaps={len(result['gaps'])} cross={result['cross_check']['agrees']} "
            f"ok={result['ok']}"
        )

    payload = {
        "wp": "WP-PAPER-REAL-DATA-001",
        "generated_at_ms": started_ms,
        "generated_at": iso(started_ms),
        "source": {
            "provider": "binance",
            "route": "public klines (api.binance.com/api/v3/klines)",
            "authenticated": False,
            "credentials_present": False,
            "timeframe": TIMEFRAME,
            "symbols": list(symbols),
        },
        "policy": {
            "pit_rule": "a bar is usable only when its CLOSE (ts + timeframe) <= decision time",
            "stale_budget_ms": STALE_BUDGET_MS,
            "stale_budget_basis": "router_gates.DEFAULT_FRESHNESS_GRACE_BARS (1.5 bars)",
            "lookback_bars": LOOKBACK_BARS,
        },
        "symbols_detail": per_symbol,
        "verdict": "DATA_QUALITY_PASS" if all(s["ok"] for s in per_symbol) else "DATA_QUALITY_FAIL",
        "failures": {
            s["symbol"]: [k for k, v in s["checks"].items() if not v]
            for s in per_symbol
            if not s["ok"]
        },
    }
    path = out_dir / "DATA_QUALITY.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"[data] verdict={payload['verdict']} -> {path}")
    return 0 if payload["verdict"] == "DATA_QUALITY_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
