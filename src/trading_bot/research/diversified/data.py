"""ARP-006 DIVERSIFIED ALPHA SEARCH §2,§6,§8 — the broader daily research corpus.

Loads the native ``1d`` shards fetched by ``scripts/fetch_diversified_history.py``
into ``reports/alpha-diversified-v1/data/``. This is a **DISCOVERY / RESEARCH
PLANE** artifact: it never modifies production market-data behaviour and does not
touch the frozen 5m baselines (``9d51385d…``) or the ARP-005 corpus
(``2ce6e6b5…``).

Split policy (frozen before any result; identical boundaries to ARP-005 so the two
programs share one time axis):

* ``DEV``         2019-01-01 .. 2023-12-31
* ``VALIDATION``  2024-01-01 .. 2025-06-30
* ``OOS_LOCK``    2025-07-01 .. 2026-02-28  (sealed; never read unless every gate passes)
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "CORPUS",
    "DEV_END_MS",
    "DEV_VAL_RANGE",
    "SPLIT_RANGES",
    "SURVIVORSHIP_LIMITATION",
    "VAL_END_MS",
    "DailyBar",
    "_2019_01_01",
    "corpus_digest",
    "listing_times",
    "load_corpus",
    "load_corpus_range",
    "load_manifest",
    "load_symbol",
    "split_of",
]

REPO = Path(__file__).resolve().parents[4]
CORPUS = REPO / "reports/alpha-diversified-v1/data"
MANIFEST = CORPUS / "_FETCH_MANIFEST.json"

MS_PER_DAY = 86_400_000
_2019_01_01 = 1_546_300_800_000
_2024_01_01 = 1_704_067_200_000
_2025_07_01 = 1_751_328_000_000
_2026_03_01 = 1_772_323_200_000

DEV_END_MS = _2024_01_01
VAL_END_MS = _2025_07_01

#: split ranges. DEV starts at 2019-01-01 so the corpus' 2017-2018 warm-up years
#: stay outside every reported window (the specs define DEV as 2019-2023).
SPLIT_RANGES: dict[str, tuple[int, int]] = {
    "DEV": (_2019_01_01, DEV_END_MS),
    "VALIDATION": (DEV_END_MS, VAL_END_MS),
    "OOS_LOCK": (VAL_END_MS, _2026_03_01),
}

SURVIVORSHIP_LIMITATION = (
    "exchangeInfo lists only symbols trading at fetch time; markets delisted on or "
    "before the fetch date are absent, so the corpus cannot reconstruct delisted "
    "history. Recorded as SURVIVORSHIP_DATA_LIMITATION."
)


@dataclass(frozen=True, slots=True)
class DailyBar:
    """One complete UTC daily bar, carrying the kline's quote-asset volume."""

    symbol: str
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float
    trades: int = 0


def split_of(timestamp_ms: int) -> str | None:
    for name, (start, end) in SPLIT_RANGES.items():
        if start <= timestamp_ms < end:
            return name
    return None


def load_manifest() -> dict[str, Any]:
    if not MANIFEST.exists():
        return {}
    loaded: dict[str, Any] = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return loaded


def listing_times() -> dict[str, int]:
    """PIT listing time (first available kline) per symbol, from the manifest."""
    man = load_manifest()
    return {
        sym: int(meta["listing_time"])
        for sym, meta in man.get("symbols", {}).items()
        if meta.get("listing_time") is not None
    }


def available_symbols() -> list[str]:
    man = load_manifest()
    return sorted(man.get("included_symbols", []))


def load_symbol(symbol: str, split: str | None = None) -> list[DailyBar]:
    """Load one symbol's complete daily bars, optionally restricted to a split."""
    path = CORPUS / f"{symbol}.json"
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    start, end = (0, 1 << 62)
    if split is not None:
        if split not in SPLIT_RANGES:
            raise KeyError(f"unknown split {split!r}")
        start, end = SPLIT_RANGES[split]
    out: list[DailyBar] = []
    for b in raw:
        ts = int(b["ts"])
        if start <= ts < end:
            out.append(
                DailyBar(
                    symbol=symbol,
                    timestamp=ts,
                    open=float(b["open"]),
                    high=float(b["high"]),
                    low=float(b["low"]),
                    close=float(b["close"]),
                    volume=float(b["volume"]),
                    quote_volume=float(b["quote_volume"]),
                    trades=int(b.get("trades", 0)),
                )
            )
    return out


def load_corpus(
    symbols: list[str] | None = None, split: str | None = None
) -> dict[str, list[DailyBar]]:
    """Load a mapping ``symbol -> [DailyBar]`` (sorted by timestamp)."""
    if symbols is None:
        symbols = available_symbols()
    return {s: load_symbol(s, split) for s in symbols}


#: contiguous development span (DEV + VALIDATION); never includes OOS_LOCK
DEV_VAL_RANGE = (_2019_01_01, VAL_END_MS)


def load_corpus_range(
    symbols: list[str] | None = None, start_ms: int = 0, end_ms: int = _2026_03_01
) -> dict[str, list[DailyBar]]:
    """Load bars with ``start_ms <= timestamp < end_ms`` per symbol."""
    if symbols is None:
        symbols = available_symbols()
    corpus: dict[str, list[DailyBar]] = {}
    for s in symbols:
        corpus[s] = [b for b in load_symbol(s) if start_ms <= b.timestamp < end_ms]
    return corpus


def corpus_digest() -> str:
    man = load_manifest()
    digest = man.get("corpus_digest")
    if digest:
        return str(digest)
    combined = hashlib.sha256()
    if CORPUS.exists():
        for path in sorted(p for p in CORPUS.glob("*.json") if not p.name.startswith("_")):
            combined.update(path.read_bytes())
    return combined.hexdigest()
