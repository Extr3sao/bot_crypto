"""RFC-036 data layer: fetch + cache the free individual-futures-contract archive.

The TurtleTrader free historical futures archive (https://www.turtletrader.com/hpd/)
publishes, per market, a ZIP containing **one text file per individual contract**
(e.g. ``CL00G.txt`` = Crude Oil Feb-2000) with columns
``Date,Open,High,Low,Close,Volume,OpenInterest``.  That contract-level grain is
exactly what RFC-036 §7/§10 require (an actually-tradable contract must be
identifiable at each historical decision).  No paid data is used (§9).

This module only fetches and parses raw bytes; it contains no strategy logic.
"""

from __future__ import annotations

import io
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from trading_bot.research.managed_futures_v1 import (
    MARKET_SPECS,
    ChainMarket,
    build_market,
)

REPO = Path(__file__).resolve().parents[1]
RAW_DIR = REPO / "reports" / "managed-futures-v1" / "raw"
BASE_URL = "https://www.turtletrader.com/cddata/{root}.zip"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"


def fetch_root(root: str, timeout: int = 60) -> Path:
    """Download the per-market ZIP once and cache it under reports/ (gitignored)."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    dst = RAW_DIR / f"{root}.zip"
    if dst.exists() and dst.stat().st_size > 0:
        return dst
    req = urllib.request.Request(BASE_URL.format(root=root), headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    dst.write_bytes(data)
    return dst


def load_files(root: str) -> dict[str, str]:
    """Return {filename: text} for every .txt contract file in the market ZIP."""
    zp = fetch_root(root)
    out: dict[str, str] = {}
    with zipfile.ZipFile(io.BytesIO(zp.read_bytes())) as z:
        for name in z.namelist():
            if not name.lower().endswith(".txt"):
                continue
            out[name] = z.read(name).decode("latin-1")
    return out


def load_market(root: str) -> ChainMarket:
    return build_market(root, load_files(root))


def load_all_markets(roots: list[str] | None = None) -> dict[str, ChainMarket]:
    roots = roots if roots is not None else sorted(MARKET_SPECS)
    return {r: load_market(r) for r in roots}


def market_summary(md: ChainMarket) -> dict[str, Any]:
    """Per-market audit facts for FUTURES_DATA_SOURCE_AUDIT."""
    n_contracts = len(md.series)
    rows = sum(len(s.bars) for s in md.series.values())
    min_od = min((b.ordinal for s in md.series.values() for b in s.bars), default=0)
    max_od = max((b.ordinal for s in md.series.values() for b in s.bars), default=0)
    from datetime import date

    return {
        "root": md.root,
        "name": md.spec["name"],
        "asset_class": md.asset_class,
        "multiplier": md.multiplier,
        "n_contracts": n_contracts,
        "n_rows": rows,
        "first_date": date.fromordinal(min_od).isoformat() if min_od else None,
        "last_date": date.fromordinal(max_od).isoformat() if max_od else None,
        "individual_contracts": n_contracts > 0,
    }
