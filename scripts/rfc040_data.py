"""RFC-040 data plane — free daily adjusted closes for EU UCITS ETFs.

Same free public source as RFC-039 (Yahoo Finance chart API, no key). Cached
under ``reports/small-capital-dual-momentum-v1/data/`` (gitignored). No paid
data, no credentials, no orders.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.research.small_capital_dual_momentum_v1 import (  # noqa: E402
    SMALL_CAP_UNIVERSE,
)
from trading_bot.research.small_capital_v1 import PriceSeries  # noqa: E402

CACHE_DIR = REPO / "reports" / "small-capital-dual-momentum-v1" / "data"

_CHART_URL = (
    "https://query2.finance.yahoo.com/v8/finance/chart/{sym}"
    "?period1=0&period2={p2}&interval=1d&events=div%2Csplit"
)
_UA = "Mozilla/5.0 (compatible; trading-agentic-research/1.0)"


def fetch_symbol(symbol: str, *, timeout: float = 30.0) -> dict[str, Any]:
    url = _CHART_URL.format(sym=symbol, p2=int(time.time()))
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    raw = urllib.request.urlopen(req, timeout=timeout).read()
    payload = json.loads(raw.decode("utf-8"))
    result = payload["chart"]["result"][0]
    ts: list[int] = result["timestamp"]
    adj_block = result["indicators"].get("adjclose")
    if not adj_block:
        raise RuntimeError(f"{symbol}: no adjclose in payload")
    adj: list[float | None] = adj_block[0]["adjclose"]
    dates: list[int] = []
    closes: list[float] = []
    for t, a in zip(ts, adj, strict=True):
        if a is None or a <= 0.0:
            continue
        dates.append(int(t) * 1000)
        closes.append(float(a))
    if len(dates) < 50:
        raise RuntimeError(f"{symbol}: only {len(dates)} usable observations")
    return {
        "symbol": symbol,
        "meta": {
            "currency": result["meta"].get("currency"),
            "exchange": result["meta"].get("fullExchangeName"),
            "instrument_type": result["meta"].get("instrumentType"),
            "long_name": result["meta"].get("longName") or result["meta"].get("shortName"),
        },
        "n": len(dates),
        "dates_ms": dates,
        "adjclose": closes,
    }


def cache_path(symbol: str) -> Path:
    return CACHE_DIR / f"{symbol}.json"


def ensure_cache(symbols: tuple[str, ...] = SMALL_CAP_UNIVERSE, *, refresh: bool = False) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for sym in symbols:
        path = cache_path(sym)
        if path.exists() and not refresh:
            continue
        path.write_text(json.dumps(fetch_symbol(sym), separators=(",", ":")), encoding="utf-8")


def load_series(symbol: str) -> PriceSeries:
    payload = json.loads(cache_path(symbol).read_text(encoding="utf-8"))
    return PriceSeries(
        symbol=symbol,
        dates_ms=tuple(int(x) for x in payload["dates_ms"]),
        closes=tuple(float(x) for x in payload["adjclose"]),
    )


def load_universe(symbols: tuple[str, ...] = SMALL_CAP_UNIVERSE) -> list[PriceSeries]:
    ensure_cache(symbols)
    return [load_series(s) for s in symbols]


def load_aligned_universe(symbols: tuple[str, ...] = SMALL_CAP_UNIVERSE) -> list[PriceSeries]:
    """Load the universe restricted to the INTERSECTION of trading dates.

    These UCITS ETFs are quoted on Xetra/LSE and do not share an identical
    holiday calendar. Research on the intersection gives one common axis with
    no missing prints, so valuation can never silently drop a held position.
    """
    series = load_universe(symbols)
    common: set[int] = set(series[0].dates_ms)
    for s in series[1:]:
        common &= set(s.dates_ms)
    if not common:
        raise RuntimeError("no common trading dates across the universe")
    out: list[PriceSeries] = []
    for s in series:
        pairs = [(d, c) for d, c in zip(s.dates_ms, s.closes, strict=True) if d in common]
        out.append(
            PriceSeries(
                symbol=s.symbol,
                dates_ms=tuple(d for d, _ in pairs),
                closes=tuple(c for _, c in pairs),
            )
        )
    return out


def dataset_digest(symbols: tuple[str, ...] = SMALL_CAP_UNIVERSE) -> dict[str, Any]:
    h = hashlib.sha256()
    per_symbol: dict[str, Any] = {}
    for sym in sorted(symbols):
        payload = json.loads(cache_path(sym).read_text(encoding="utf-8"))
        sh = hashlib.sha256()
        for d, c in zip(payload["dates_ms"], payload["adjclose"], strict=True):
            sh.update(f"{d}:{c:.10f};".encode())
        digest = sh.hexdigest()
        per_symbol[sym] = {
            "n": payload["n"],
            "first_ms": payload["dates_ms"][0],
            "last_ms": payload["dates_ms"][-1],
            "sha256": digest,
            "meta": payload.get("meta"),
        }
        h.update(f"{sym}={digest};".encode())
    return {
        "universe": sorted(symbols),
        "per_symbol": per_symbol,
        "dataset_sha256": h.hexdigest(),
        "source": "Yahoo Finance chart API (public, free)",
        "instrument_class": "UCITS ETF (EU-retail accessible, EUR-quoted)",
    }


if __name__ == "__main__":  # pragma: no cover - manual refresh helper
    ensure_cache(refresh=True)
    print(json.dumps(dataset_digest(), indent=2))
