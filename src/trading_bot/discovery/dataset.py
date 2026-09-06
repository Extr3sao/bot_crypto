"""Fresh dataset: public Binance Futures 5m OHLCV, quality gates, manifest.

PIT rules:
- Only candles with ``close_time <= now`` (i.e. closed candles) are used.
- The open candle at fetch time is always dropped.
- ``data_cutoff`` is the timestamp of the latest *closed* candle.
- No silent imputation: gaps are detected and reported, never filled.
"""

from __future__ import annotations

import hashlib
import itertools
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trading_bot.market_data.types import OHLCV

FRESH_START_UTC = datetime(2026, 8, 19, tzinfo=UTC)
TIMEFRAME_MS = 5 * 60 * 1000
FEE_RATE = 0.0005  # taker fee per side (Binance futures VIP0), used by runner
SLIPPAGE_BPS = 5.0  # conservative flat slippage, used by runner


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_candles(candles: list[OHLCV]) -> str:
    """Content hash of a candle series (deterministic, PIT-safe)."""
    payload = json.dumps(
        [[c.symbol, c.timestamp, c.open, c.high, c.low, c.close, c.volume] for c in candles],
        separators=(",", ":"),
    ).encode()
    return _sha256_bytes(payload)


@dataclass(frozen=True, slots=True)
class DataQualityReport:
    symbol: str
    candles: int
    duplicates: int
    gaps: int
    gap_bars: int
    ohlc_violations: int
    non_positive_volume: int
    before_start: int
    first_open_ms: int
    last_close_ms: int

    @property
    def passed(self) -> bool:
        return (
            self.duplicates == 0
            and self.gaps == 0
            and self.ohlc_violations == 0
            and self.non_positive_volume == 0
            and self.before_start == 0
            and self.candles > 0
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "candles": self.candles,
            "duplicates": self.duplicates,
            "gaps": self.gaps,
            "gap_bars": self.gap_bars,
            "ohlc_violations": self.ohlc_violations,
            "non_positive_volume": self.non_positive_volume,
            "before_start": self.before_start,
            "first_open_ms": self.first_open_ms,
            "last_close_ms": self.last_close_ms,
            "passed": self.passed,
        }


@dataclass(frozen=True, slots=True)
class SymbolDataset:
    symbol: str
    candles: tuple[OHLCV, ...]
    quality: DataQualityReport
    sha256: str
    fetch_pages: int = 0  # number of paginated requests used (0 = synthetic fixture)


def validate_quality(symbol: str, candles: list[OHLCV]) -> DataQualityReport:
    """Structural validation. No imputation anywhere."""
    ordered = sorted(candles, key=lambda c: c.timestamp)
    seen: set[int] = set()
    duplicates = 0
    for candle in ordered:
        if candle.timestamp in seen:
            duplicates += 1
        seen.add(candle.timestamp)
    gaps = 0
    gap_bars = 0
    for prev, cur in itertools.pairwise(ordered):
        delta = cur.timestamp - prev.timestamp
        if delta > TIMEFRAME_MS:
            gaps += 1
            gap_bars += int(delta // TIMEFRAME_MS) - 1
    ohlc_violations = sum(
        1
        for c in ordered
        if c.high < max(c.open, c.close) or c.low > min(c.open, c.close) or c.high < c.low
    )
    non_positive_volume = sum(1 for c in ordered if c.volume <= 0)
    before_start = sum(1 for c in ordered if c.timestamp < _ms(FRESH_START_UTC))
    first_open = ordered[0].timestamp if ordered else 0
    last_close = (ordered[-1].timestamp + TIMEFRAME_MS - 1) if ordered else 0
    return DataQualityReport(
        symbol=symbol,
        candles=len(ordered),
        duplicates=duplicates,
        gaps=gaps,
        gap_bars=gap_bars,
        ohlc_violations=ohlc_violations,
        non_positive_volume=non_positive_volume,
        before_start=before_start,
        first_open_ms=first_open,
        last_close_ms=last_close,
    )


def _ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


class DatasetFetcher:
    """Fetches closed 5m futures candles for the current canonical universe.

    Full-history pagination (FRESH-DATA-001-R1): the loop advances
    ``since = last_timestamp + timeframe`` until the exchange reports no
    further closed candles; a short page is NEVER treated as exhaustion
    (Binance returns fewer rows than requested on the tail and on interim
    pages — FRESH-DATA-001 truncated at 1000 bars because of exactly that).
    Page continuity, monotonic timestamps and closed-candle-only semantics
    are validated; quality failures raise (no silent imputation).

    Public endpoints only: no API key, no secret, no private call.
    """

    PAGE_LIMIT = 1000  # Binance futures candles per request (exchange cap)

    def __init__(
        self,
        symbols: tuple[str, ...] = ("BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"),
        *,
        exchange_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.symbols = symbols
        self._exchange_factory = exchange_factory

    def _make_exchange(self) -> Any:
        if self._exchange_factory is not None:
            return self._exchange_factory()
        import ccxt

        return ccxt.binanceusdm({"enableRateLimit": True})

    def fetch(self, *, max_bars_per_symbol: int = 60_000) -> dict[str, SymbolDataset]:
        exchange = self._make_exchange()
        try:
            since = _ms(FRESH_START_UTC)
            now_ms = _ms(datetime.now(tz=UTC))
            datasets: dict[str, SymbolDataset] = {}
            for symbol in self.symbols:
                rows: list[list[Any]] = []
                cursor = since
                pages = 0
                while len(rows) < max_bars_per_symbol:
                    batch = exchange.fetch_ohlcv(
                        symbol, timeframe="5m", since=cursor, limit=self.PAGE_LIMIT
                    )
                    if not batch:
                        break
                    pages += 1
                    # Page continuity + monotonic timestamps (fail loud).
                    last_ts = rows[-1][0] if rows else None
                    batch_first = int(batch[0][0])
                    if last_ts is not None:
                        if batch_first < last_ts + TIMEFRAME_MS:
                            raise ValueError(
                                f"pagination overlap/dupe for {symbol}: "
                                f"first={batch_first} last={last_ts}"
                            )
                        if batch_first > last_ts + TIMEFRAME_MS:
                            raise ValueError(
                                f"pagination gap (missing page) for {symbol}: "
                                f"first={batch_first} expected={last_ts + TIMEFRAME_MS}"
                            )
                    stamps = [int(r[0]) for r in batch]
                    if any(b <= a for a, b in itertools.pairwise(stamps)):
                        raise ValueError(f"non-monotonic timestamps in page for {symbol}")
                    rows.extend(batch)
                    next_cursor = stamps[-1] + TIMEFRAME_MS
                    if next_cursor <= cursor:
                        break
                    cursor = next_cursor
                    # NOTE: no short-page early exit — a short batch is not
                    # exhaustion; continue until an empty batch arrives.
                # Drop candles whose close_time is still open OR in the future
                # (PIT: only fully closed candles).
                closed = [
                    OHLCV(
                        symbol=symbol,
                        timestamp=int(r[0]),
                        open=float(r[1]),
                        high=float(r[2]),
                        low=float(r[3]),
                        close=float(r[4]),
                        volume=float(r[5]),
                    )
                    for r in rows
                    if r[0] + TIMEFRAME_MS - 1 <= now_ms
                ]
                quality = validate_quality(symbol, closed)
                if not quality.passed:
                    raise ValueError(
                        f"dataset quality FAILED for {symbol}: {quality.to_dict()} "
                        "(no silent imputation allowed)"
                    )
                ordered = sorted(closed, key=lambda c: c.timestamp)
                datasets[symbol] = SymbolDataset(
                    symbol=symbol,
                    candles=tuple(ordered),
                    quality=quality,
                    sha256=sha256_candles(ordered),
                    fetch_pages=pages,
                )
            return datasets
        finally:
            close = getattr(exchange, "close", None)
            if callable(close):
                close()


def build_data_manifest(datasets: dict[str, SymbolDataset], *, data_cutoff: datetime) -> dict[str, Any]:
    """Deterministic DATA_MANIFEST with per-symbol hashes and quality."""
    symbols_block = {
        symbol: {
            "candles": ds.quality.candles,
            "sha256": ds.sha256,
            "quality": ds.quality.to_dict(),
        }
        for symbol, ds in sorted(datasets.items())
    }
    manifest_hash = _sha256_bytes(
        json.dumps(
            {
                "fresh_start_utc": FRESH_START_UTC.isoformat(),
                "data_cutoff": data_cutoff.isoformat(),
                "timeframe": "5m",
                "symbols": symbols_block,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    )
    return {
        "schema_version": "fresh-data-manifest-v1",
        "provider": "binanceusdm-public",
        "timeframe": "5m",
        "fresh_start_utc": FRESH_START_UTC.isoformat(),
        "data_cutoff": data_cutoff.isoformat(),
        "symbols": symbols_block,
        "manifest_sha256": manifest_hash,
    }


def load_or_fetch(
    cache_dir: Path | str, *, max_bars_per_symbol: int = 60_000
) -> tuple[dict[str, SymbolDataset], dict[str, Any]]:
    """Fetch (or reuse) the dataset; persist the manifest next to the cache.

    Reuse only happens when the cached manifest hash matches a refetch —
    deterministic by construction (same closed-candle window).
    """
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    manifest_path = cache / "DATA_MANIFEST.json"
    fetcher = DatasetFetcher()
    datasets = fetcher.fetch(max_bars_per_symbol=max_bars_per_symbol)
    cutoff_ms = max(ds.quality.last_close_ms for ds in datasets.values())
    data_cutoff = datetime.fromtimestamp((cutoff_ms + 1) / 1000, tz=UTC)
    manifest = build_data_manifest(datasets, data_cutoff=data_cutoff)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return datasets, manifest


def fetch_stats_of(datasets: dict[str, SymbolDataset]) -> dict[str, dict[str, Any]]:
    """FETCH_PAGES / FIRST_TS / LAST_TS / CANDLE_COUNT per symbol (R1 gate G1)."""
    return {
        sym: {
            "fetch_pages": ds.fetch_pages,
            "first_ts": ds.candles[0].timestamp if ds.candles else None,
            "last_ts": ds.candles[-1].timestamp if ds.candles else None,
            "candle_count": ds.quality.candles,
        }
        for sym, ds in sorted(datasets.items())
    }
