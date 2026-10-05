"""RFC-039 data plane — free daily adjusted closes for the 6 ETF sleeves.

Source: Yahoo Finance chart API (public, no key). One JSON file per symbol is
cached under ``reports/small-capital-v1/data/`` (gitignored, like every other
``reports/`` artifact). The frozen dataset digest is the SHA-256 of the
concatenated per-symbol close series, so a re-run is reproducible.

No paid data, no credentials, no orders. Network is used only to populate the
local cache; the research core reads the cache.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.request
from pathlib import Path
from typing import Any

from trading_bot.research.small_capital_v1 import DEFAULT_UNIVERSE, PriceSeries

REPO = Path(__file__).resolve().parents[1]
CACHE_DIR = REPO / "reports" / "small-capital-v1" / "data"

_CHART_URL = (
    "https://query2.finance.yahoo.com/v8/finance/chart/{sym}"
    "?period1=0&period2={p2}&interval=1d&events=div%2Csplit"
)
_UA = "Mozilla/5.0 (compatible; trading-agentic-research/1.0)"


def fetch_symbol(symbol: str, *, timeout: float = 30.0) -> dict[str, Any]:
    """Fetch one symbol's full daily adjusted-close history from Yahoo."""
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
        if a is None:
            continue
        if a <= 0.0:
            continue
        dates.append(int(t) * 1000)
        closes.append(float(a))
    if len(dates) < 50:
        raise RuntimeError(f"{symbol}: only {len(dates)} usable observations")
    return {
        "symbol": symbol,
        "source": _CHART_URL.format(sym=symbol, p2="<now>"),
        "n": len(dates),
        "dates_ms": dates,
        "adjclose": closes,
    }


def cache_path(symbol: str) -> Path:
    return CACHE_DIR / f"{symbol}.json"


def ensure_cache(symbols: tuple[str, ...] = DEFAULT_UNIVERSE, *, refresh: bool = False) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for sym in symbols:
        path = cache_path(sym)
        if path.exists() and not refresh:
            continue
        payload = fetch_symbol(sym)
        path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")


def load_series(symbol: str) -> PriceSeries:
    payload = json.loads(cache_path(symbol).read_text(encoding="utf-8"))
    return PriceSeries(
        symbol=symbol,
        dates_ms=tuple(int(x) for x in payload["dates_ms"]),
        closes=tuple(float(x) for x in payload["adjclose"]),
    )


def load_universe(symbols: tuple[str, ...] = DEFAULT_UNIVERSE) -> list[PriceSeries]:
    ensure_cache(symbols)
    return [load_series(s) for s in symbols]


def dataset_digest(symbols: tuple[str, ...] = DEFAULT_UNIVERSE) -> dict[str, Any]:
    """SHA-256 over every symbol's (date, close) pairs, plus per-symbol metadata."""
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
        }
        h.update(f"{sym}={digest};".encode())
    return {
        "universe": list(sorted(symbols)),
        "per_symbol": per_symbol,
        "dataset_sha256": h.hexdigest(),
        "source": "Yahoo Finance chart API (public, free)",
    }


if __name__ == "__main__":  # pragma: no cover - manual refresh helper
    ensure_cache(refresh=True)
    print(json.dumps(dataset_digest(), indent=2))
