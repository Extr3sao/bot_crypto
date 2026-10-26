"""EDGE-01 data plane — local OHLCV corpora with explicit provenance.

Two authoritative local corpora are used, and nothing is synthesised:

* **15m** — ``data/raw/alpha003/price/<SYM>USDT_15m.json``, rows
  ``[ts, open, high, low, close, volume]`` with ``ts`` = bar OPEN time (ms UTC),
  contiguous 15m spacing (verified: 0 irregular steps).
* **1h** — ``reports/alpha-expansion-v1/data/<SYM>USDT_<YEAR>.json``, rows as
  objects ``{"ts","open","high","low","close","volume"}``, downloaded from
  Binance public REST by ``scripts/fetch_alpha_expansion_history.py`` with a
  per-shard SHA256 in ``_FETCH_MANIFEST.json``.

Higher timeframes (4h, 1d) are **aggregated** from the 1h corpus, never fetched
twice: a bucket is emitted only when it is complete (all of its source bars are
present and contiguous), so a partial or gappy session is dropped instead of
producing a bar nobody could have traded. Aggregating upwards cannot invent
information; splitting a bar (1h -> 15m) could, which is why the 15m window is
read from its own source and its coverage is reported separately.

``Corpus.sha256`` digests the exact shard files used, so a result can be tied to
the bytes it was measured on.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "ASSETS",
    "BAR_MS",
    "CORPUS_1H",
    "CORPUS_15M",
    "RESAMPLE_EXPECTED",
    "Corpus",
    "OHLCVBar",
    "load_1h",
    "load_15m",
    "os_sha256",
    "resample",
]

REPO = Path(__file__).resolve().parents[4]
CORPUS_15M = REPO / "data" / "raw" / "alpha003" / "price"
CORPUS_1H = REPO / "reports" / "alpha-expansion-v1" / "data"

ASSETS: tuple[str, ...] = ("BTC", "ETH", "SOL")

BAR_MS: dict[str, int] = {
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}

#: Source bars a complete bucket of each aggregated timeframe must contain.
RESAMPLE_EXPECTED: dict[str, int] = {"4h": 4, "1d": 24}


@dataclass(frozen=True, slots=True)
class OHLCVBar:
    """One closed bar. ``ts`` is the bar OPEN time in ms UTC."""

    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def close_ts(self) -> int:
        return self.ts


@dataclass(frozen=True, slots=True)
class Corpus:
    """Bars plus the provenance needed to tie a result to its bytes."""

    symbol: str
    timeframe: str
    bars: tuple[OHLCVBar, ...]
    sources: tuple[str, ...]
    sha256: str

    @property
    def n(self) -> int:
        return len(self.bars)

    @property
    def first_ts(self) -> int:
        return self.bars[0].ts if self.bars else 0

    @property
    def last_ts(self) -> int:
        return self.bars[-1].ts if self.bars else 0

    def closes(self) -> list[float]:
        return [b.close for b in self.bars]

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "bars": self.n,
            "first_ts": self.first_ts,
            "last_ts": self.last_ts,
            "sources": list(self.sources),
            "sha256": self.sha256,
        }


def os_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _digest(paths: Iterable[Path]) -> str:
    combined = hashlib.sha256()
    for path in sorted(paths):
        combined.update(path.name.encode("utf-8"))
        combined.update(os_sha256(path).encode("utf-8"))
    return combined.hexdigest()


def _to_float(value: Any) -> float:
    """Binance shards mix numbers and numeric strings; both mean the same bar."""
    return float(value)


def _parse_row(row: Any) -> OHLCVBar:
    if isinstance(row, dict):
        return OHLCVBar(
            ts=int(row["ts"]),
            open=_to_float(row["open"]),
            high=_to_float(row["high"]),
            low=_to_float(row["low"]),
            close=_to_float(row["close"]),
            volume=_to_float(row.get("volume", 0.0)),
        )
    ts, o, h, low, c, v = row[:6]
    return OHLCVBar(int(ts), _to_float(o), _to_float(h), _to_float(low), _to_float(c), _to_float(v))


def load_15m(symbol: str, *, corpus: Path | None = None) -> Corpus:
    """Read one symbol's 15m corpus exactly as stored (no gaps filled)."""
    root = CORPUS_15M if corpus is None else corpus
    path = root / f"{symbol}USDT_15m.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = raw if isinstance(raw, list) else (raw.get("bars") or raw.get("data") or [])
    bars = tuple(_parse_row(r) for r in rows)
    return Corpus(
        symbol=symbol,
        timeframe="15m",
        bars=bars,
        sources=(str(path.relative_to(REPO)).replace("\\", "/"),),
        sha256=_digest([path]),
    )


def load_1h(symbol: str, *, corpus: Path | None = None) -> Corpus:
    """Read every year shard of one symbol's 1h corpus, in ts order."""
    root = CORPUS_1H if corpus is None else corpus
    paths = sorted(
        p for p in root.glob(f"{symbol}USDT_*.json") if not p.name.startswith("_")
    )
    if not paths:
        raise FileNotFoundError(f"no 1h shards for {symbol} under {root}")
    bars: list[OHLCVBar] = []
    for path in paths:
        raw = json.loads(path.read_text(encoding="utf-8"))
        rows = raw if isinstance(raw, list) else (raw.get("bars") or raw.get("data") or [])
        bars.extend(_parse_row(r) for r in rows)
    bars.sort(key=lambda b: b.ts)
    deduped: list[OHLCVBar] = []
    for bar in bars:
        if deduped and deduped[-1].ts == bar.ts:
            continue
        deduped.append(bar)
    return Corpus(
        symbol=symbol,
        timeframe="1h",
        bars=tuple(deduped),
        sources=tuple(str(p.relative_to(REPO)).replace("\\", "/") for p in paths),
        sha256=_digest(paths),
    )


def resample(corpus: Corpus, timeframe: str) -> Corpus:
    """Aggregate a 1h corpus up to 4h/1d using complete, contiguous UTC buckets.

    A bucket is emitted only if it holds exactly ``RESAMPLE_EXPECTED[tf]`` source
    bars, all on the bucket's own grid. Anything else (a gap inside the bucket,
    or a bucket the feed cut short) is dropped rather than extrapolated, so the
    aggregated bar is one that could have existed.
    """
    if timeframe not in RESAMPLE_EXPECTED:
        raise KeyError(f"{timeframe!r} is not an aggregated timeframe")
    if corpus.timeframe != "1h":
        raise ValueError(f"can only aggregate from 1h, got {corpus.timeframe!r}")
    expected = RESAMPLE_EXPECTED[timeframe]
    step = BAR_MS["1h"]
    tf_ms = BAR_MS[timeframe]
    out: list[OHLCVBar] = []
    bucket: int | None = None
    members: list[OHLCVBar] = []
    for bar in corpus.bars:
        current = bar.ts // tf_ms
        if bucket is None:
            bucket = current
        if current != bucket:
            if len(members) == expected:
                out.append(_merge(members[0].ts // tf_ms * tf_ms, members))
            members = []
            bucket = current
        members.append(bar)
        if len(members) > 1 and members[-1].ts - members[-2].ts != step:
            # A hole inside the bucket: the bucket cannot be completed.
            members = [bar]
            bucket = current
    if len(members) == expected:
        out.append(_merge(members[0].ts // tf_ms * tf_ms, members))
    return Corpus(
        symbol=corpus.symbol,
        timeframe=timeframe,
        bars=tuple(out),
        sources=corpus.sources,
        sha256=corpus.sha256,
    )


def _merge(ts: int, members: list[OHLCVBar]) -> OHLCVBar:
    return OHLCVBar(
        ts=ts,
        open=members[0].open,
        high=max(b.high for b in members),
        low=min(b.low for b in members),
        close=members[-1].close,
        volume=sum(b.volume for b in members),
    )
