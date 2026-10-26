"""ARP-005 ALPHA EXPANSION §2-§4 — the isolated expanded research corpus.

Loads the native 1h year shards fetched by
``scripts/fetch_alpha_expansion_history.py`` into
``reports/alpha-expansion-v1/data/``. This corpus is a **DISCOVERY / RESEARCH
PLANE** artifact: it never modifies production market-data behaviour, and it
does not touch the frozen baseline (``9d51385d…``) or extended
(``d3669d28…``) corpora pinned by upstream manifests.

Split policy (frozen before any result) — time ranges, not window names, because
the shards are calendar years:

* ``DEV``         2019-01-01 .. 2023-12-31  (multiple regimes)
* ``VALIDATION``  2024-01-01 .. 2025-06-30
* ``OOS_LOCK``    2025-07-01 .. 2026-02-28  (sealed; never read unless every gate passes)

Every boundary is a UTC instant; membership is by bar ``timestamp`` (1h open
time). ``OOS_LOCK`` deliberately precedes the frozen W7 window (2026-09) and the
paper run (2026-09-25), so it cannot leak the upstream holdout.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from trading_bot.market_data.types import OHLCV

__all__ = [
    "DEV_END_MS",
    "EXPANSION_CORPUS",
    "SPLIT_RANGES",
    "SYMBOLS",
    "VAL_END_MS",
    "expansion_corpus_digest",
    "load_lower_bars",
    "load_shard_manifest",
    "split_of",
]

REPO = Path(__file__).resolve().parents[4]
EXPANSION_CORPUS = REPO / "reports/alpha-expansion-v1/data"
MANIFEST = EXPANSION_CORPUS / "_FETCH_MANIFEST.json"

SYMBOLS: dict[str, str] = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT"}

_HOUR_MS = 3_600_000
_DAY_MS = 86_400_000
_2024_01_01 = 1_704_067_200_000
_2025_07_01 = 1_751_328_000_000
_2026_03_01 = 1_772_323_200_000

#: exclusive end boundaries used by the split lookup below
DEV_END_MS = _2024_01_01
VAL_END_MS = _2025_07_01

#: (start_ms inclusive, end_ms exclusive) per split
SPLIT_RANGES: dict[str, tuple[int, int]] = {
    "DEV": (0, DEV_END_MS),
    "VALIDATION": (DEV_END_MS, VAL_END_MS),
    "OOS_LOCK": (VAL_END_MS, _2026_03_01),
}


def split_of(timestamp_ms: int) -> str | None:
    """Which split a 1h timestamp belongs to, or ``None`` if outside all splits."""
    for name, (start, end) in SPLIT_RANGES.items():
        if start <= timestamp_ms < end:
            return name
    return None


def load_shard_manifest() -> dict[str, Any]:
    if not MANIFEST.exists():
        return {}
    loaded: dict[str, Any] = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return loaded


def _years_for(start_ms: int, end_ms: int) -> list[int]:
    from datetime import UTC, datetime

    first = datetime.fromtimestamp(start_ms / 1000, tz=UTC).year if start_ms else 2019
    last = datetime.fromtimestamp((end_ms - 1) / 1000, tz=UTC).year
    return list(range(first, last + 1))


def load_lower_bars(symbol: str, split: str) -> list[OHLCV]:
    """Load one symbol's 1h bars restricted to a split's UTC range."""
    if split not in SPLIT_RANGES:
        raise KeyError(f"unknown split {split!r}")
    start, end = SPLIT_RANGES[split]
    out: list[OHLCV] = []
    for year in _years_for(start, end):
        path = EXPANSION_CORPUS / f"{symbol}_{year}.json"
        if not path.exists():
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        for b in raw:
            ts = int(b["ts"])
            if start <= ts < end:
                out.append(
                    OHLCV(
                        symbol=symbol,
                        timestamp=ts,
                        open=float(b["open"]),
                        high=float(b["high"]),
                        low=float(b["low"]),
                        close=float(b["close"]),
                        volume=float(b["volume"]),
                    )
                )
    return out


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def expansion_corpus_digest() -> str:
    """sha256 over every year shard in sorted name order (new corpus only)."""
    combined = hashlib.sha256()
    if not EXPANSION_CORPUS.exists():
        return combined.hexdigest()
    for path in sorted(p for p in EXPANSION_CORPUS.glob("*.json") if not p.name.startswith("_")):
        combined.update(_sha256_file(path).encode())
    return combined.hexdigest()
