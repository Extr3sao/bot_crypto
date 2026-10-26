"""Read-only public market data for the PAPER vertical (G-7).

This module is deliberately a *data client*, not an exchange client:

* only Binance's public market-data routes are allowed (klines, 24h ticker,
  book ticker, server time);
* no API key, secret, signature or order endpoint exists in the adapter;
* every request is journalled with a content hash and ``authenticated: false``;
* forming candles are dropped before the runtime sees them;
* :class:`ReplayMarketDataSource` can serve the same captured bars at a pinned
  decision instant, so a historical replay remains a replay and never pretends
  to be a forward session.

The adapter implements the repository's existing
``scanner.protocols.MarketDataSourceProtocol`` (``fetch_recent``,
``fetch_24h_volume_usdt``, ``fetch_spread_bps``), so the canonical
``PaperOrchestrator`` can consume it without a second market-data subsystem.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any

from trading_bot.market_data import real_data_validation
from trading_bot.market_data.timeframe import TIMEFRAME_SECONDS
from trading_bot.market_data.types import OHLCV

__all__ = [
    "PUBLIC_PROVIDER",
    "PublicDataError",
    "PublicRestKlineSource",
    "ReplayMarketDataSource",
    "capture_from_source",
    "capture_sha256",
    "load_capture",
    "ms_to_iso",
]


PUBLIC_PROVIDER = "binance-public-rest"
PUBLIC_BASE_URL = "https://api.binance.com"
_ALLOWED_PATHS = frozenset(
    {
        "/api/v3/klines",
        "/api/v3/ticker/24hr",
        "/api/v3/ticker/bookTicker",
        "/api/v3/time",
    }
)
_TIMEFRAME_ALIASES = {"60m": "1h", "1d": "1d"}


class PublicDataError(RuntimeError):
    """Raised when public data cannot be trusted or fetched."""


def ms_to_iso(ms: int | None) -> str | None:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000.0, tz=UTC).isoformat()


def _tf_ms(timeframe: str) -> int:
    normalized = _TIMEFRAME_ALIASES.get(timeframe, timeframe).lower()
    seconds = TIMEFRAME_SECONDS.get(normalized)
    if seconds is None:
        raise PublicDataError(f"unsupported timeframe {timeframe!r}")
    return seconds * 1000


def _api_symbol(symbol: str) -> str:
    return symbol.replace("/", "").replace("-", "").upper()


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass(frozen=True, slots=True)
class _Capture:
    bars: tuple[OHLCV, ...]
    received_at_ms: int


class PublicRestKlineSource:
    """Public klines/ticker source with a request journal and no private calls."""

    provider = PUBLIC_PROVIDER

    def __init__(
        self,
        *,
        timeframe: str = "5m",
        base_url: str = PUBLIC_BASE_URL,
        audit_path: Path | str | None = None,
        timeout_seconds: float = 20.0,
        clock: Any | None = None,
    ) -> None:
        self.timeframe = timeframe
        self._tf_ms = _tf_ms(timeframe)
        self._base_url = base_url.rstrip("/")
        self._timeout = float(timeout_seconds)
        self._clock = clock or _now_ms
        self._audit_path = Path(audit_path) if audit_path is not None else None
        self._audit_lock = Lock()
        self._captures: dict[str, _Capture] = {}
        self._quotes: dict[str, dict[str, Any]] = {}
        if self._audit_path is not None:
            self._audit_path.parent.mkdir(parents=True, exist_ok=True)
            self._audit_path.write_text("", encoding="utf-8")

    # -- public source protocol ------------------------------------------------

    async def fetch_recent(self, symbol: str, limit: int = 100) -> list[OHLCV]:
        return await asyncio.to_thread(self._fetch_recent_sync, symbol, limit)

    async def fetch_24h_volume_usdt(self, symbol: str) -> float:
        return await asyncio.to_thread(self._fetch_volume_sync, symbol)

    async def fetch_spread_bps(self, symbol: str) -> float:
        return await asyncio.to_thread(self._fetch_spread_sync, symbol)

    # -- capture / provenance ---------------------------------------------------

    def capture(self) -> dict[str, Any]:
        """The exact rows most recently served, ready to be persisted."""
        return capture_from_source(self)

    def snapshot_records(self, decision_time_ms: int) -> list[dict[str, Any]]:
        """Provenance rows for the capture, at one decision instant."""
        records: list[dict[str, Any]] = []
        for symbol, capture in sorted(self._captures.items()):
            assets = symbol.split("/")[0]
            validation = real_data_validation.validate_closed_bars(
                list(capture.bars),
                provider=self.provider,
                asset=assets,
                symbol=symbol,
                timeframe=self.timeframe,
                decision_time_ms=decision_time_ms,
                received_at_ms=capture.received_at_ms,
                min_bars=100,
            )
            record = validation.to_dict()
            record.update(
                {
                    "data_mode": "FORWARD",
                    "event_time": ms_to_iso(validation.data_time_ms),
                    "received_at": ms_to_iso(validation.received_at_ms),
                    "decision_time": ms_to_iso(decision_time_ms),
                    "quote": dict(self._quotes.get(symbol, {})),
                }
            )
            records.append(record)
        return records

    # -- HTTP ------------------------------------------------------------------

    def _request_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if path not in _ALLOWED_PATHS:
            raise PublicDataError(
                f"public data endpoint {path!r} is not on the read-only allowlist "
                f"({sorted(_ALLOWED_PATHS)})"
            )
        query = urllib.parse.urlencode(params or {})
        url = f"{self._base_url}{path}" + (f"?{query}" if query else "")
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "User-Agent": "trading-agentic-portable/1.0 (paper public data)",
                "Accept": "application/json",
            },
        )
        started = _now_ms()
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                body = response.read().decode("utf-8")
        except Exception as exc:  # provider failure is explicit, never a fake bar
            self._journal(
                {
                    "kind": "request_error",
                    "path": path,
                    "params": params or {},
                    "started_at_ms": started,
                    "error": f"{type(exc).__name__}: {exc}",
                    "authenticated": False,
                }
            )
            raise PublicDataError(f"public data request failed: {path}: {exc}") from exc
        try:
            payload = json.loads(body)
        except Exception as exc:
            raise PublicDataError(f"public data response is not JSON: {path}") from exc
        self._journal(
            {
                "kind": "request",
                "path": path,
                "params": params or {},
                "started_at_ms": started,
                "received_at_ms": _now_ms(),
                "authenticated": False,
                "request_url": url,
            }
        )
        return payload

    def _journal(self, record: dict[str, Any]) -> None:
        if self._audit_path is None:
            return
        row = {"provider": self.provider, **record}
        with self._audit_lock, self._audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")
            handle.flush()

    def _fetch_recent_sync(self, symbol: str, limit: int) -> list[OHLCV]:
        requested = max(1, min(int(limit), 1000))
        # Ask for one extra row: the provider includes the forming candle in
        # its limit, and dropping it must not leave the caller one bar short
        # (the scanner's ATR filter requires exactly ``min_history`` closed
        # bars).
        fetch_limit = min(requested + 1, 1000)
        payload = self._request_json(
            "/api/v3/klines",
            {
                "symbol": _api_symbol(symbol),
                "interval": self.timeframe,
                "limit": fetch_limit,
            },
        )
        if not isinstance(payload, list):
            raise PublicDataError(f"klines payload for {symbol} is not a list")
        received_at_ms = int(self._clock())
        rows: list[OHLCV] = []
        for raw in payload:
            if not isinstance(raw, list) or len(raw) < 6:
                raise PublicDataError(f"malformed kline row for {symbol}: {raw!r}")
            rows.append(
                OHLCV(
                    symbol=symbol,
                    timestamp=int(raw[0]),
                    open=float(raw[1]),
                    high=float(raw[2]),
                    low=float(raw[3]),
                    close=float(raw[4]),
                    volume=float(raw[5]),
                )
            )
        # Drop the forming candle: a bar is usable only after its close.
        closed = [bar for bar in rows if int(bar.timestamp) + self._tf_ms <= received_at_ms]
        if not closed:
            raise PublicDataError(f"no closed {self.timeframe} bars for {symbol}")
        prior = self._captures.get(symbol)
        if prior is None or len(closed) >= len(prior.bars):
            self._captures[symbol] = _Capture(bars=tuple(closed), received_at_ms=received_at_ms)
        return closed[-requested:]

    def _fetch_volume_sync(self, symbol: str) -> float:
        payload = self._request_json(
            "/api/v3/ticker/24hr",
            {"symbol": _api_symbol(symbol)},
        )
        if not isinstance(payload, dict):
            raise PublicDataError(f"24h ticker payload for {symbol} is not an object")
        raw = payload.get("quoteVolume")
        if raw is None:
            raise PublicDataError(f"24h ticker has no quoteVolume for {symbol}")
        try:
            volume = float(raw)
        except (TypeError, ValueError) as exc:
            raise PublicDataError(f"24h ticker has no quoteVolume for {symbol}") from exc
        if not math.isfinite(volume) or volume < 0:
            raise PublicDataError(f"24h quoteVolume is invalid for {symbol}: {raw!r}")
        self._quotes.setdefault(symbol, {})["volume_24h_usdt"] = volume
        self._quotes[symbol]["quote_observed_at_ms"] = int(self._clock())
        self._quotes[symbol]["quote_source"] = "binance-public-24hr-ticker"
        return volume

    def _fetch_spread_sync(self, symbol: str) -> float:
        payload = self._request_json(
            "/api/v3/ticker/bookTicker",
            {"symbol": _api_symbol(symbol)},
        )
        if not isinstance(payload, dict):
            raise PublicDataError(f"bookTicker payload for {symbol} is not an object")
        try:
            bid = float(payload["bidPrice"])
            ask = float(payload["askPrice"])
        except (KeyError, TypeError, ValueError) as exc:
            raise PublicDataError(f"bookTicker has no valid bid/ask for {symbol}") from exc
        if not (math.isfinite(bid) and math.isfinite(ask)) or bid <= 0 or ask <= 0:
            raise PublicDataError(f"bookTicker prices are invalid for {symbol}")
        if ask < bid:
            raise PublicDataError(f"bookTicker ask < bid for {symbol}")
        mid = (ask + bid) / 2.0
        spread = (ask - bid) / mid * 10_000.0
        self._quotes.setdefault(symbol, {})["spread_bps"] = spread
        self._quotes[symbol]["quote_observed_at_ms"] = int(self._clock())
        self._quotes[symbol]["quote_source"] = "binance-public-bookTicker"
        return spread


class ReplayMarketDataSource:
    """Serve a persisted public capture at a pinned decision instant.

    ``fetch_recent`` returns only bars that were already closed at
    ``decision_time_ms``.  The capture carries the real provider, receive time
    and quote observations; the replay never fabricates a bar.
    """

    provider = PUBLIC_PROVIDER

    def __init__(
        self,
        capture: dict[str, Any],
        *,
        decision_time_ms: int,
        timeframe: str | None = None,
        data_mode: str = "HISTORICAL_REPLAY",
    ) -> None:
        self._capture = capture
        self.timeframe = timeframe or str(capture.get("timeframe", "5m"))
        self._tf_ms = _tf_ms(self.timeframe)
        self._decision_time_ms = int(decision_time_ms)
        # A capture consumed immediately after the provider answered is a
        # FORWARD observation, not a historical replay.  The label is explicit
        # so a replay can never be presented as a live session (G-7 §2).
        self.data_mode = data_mode
        self._bars: dict[str, list[OHLCV]] = {}
        self._quotes: dict[str, dict[str, Any]] = {}
        symbols = capture.get("symbols")
        if not isinstance(symbols, dict) or not symbols:
            raise PublicDataError("capture has no symbols")
        for symbol, item in symbols.items():
            if not isinstance(item, dict) or not isinstance(item.get("bars"), list):
                raise PublicDataError(f"capture entry for {symbol} has no bars")
            bars = [
                OHLCV(
                    symbol=str(symbol),
                    timestamp=int(row[0]),
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                )
                for row in item["bars"]
            ]
            self._bars[str(symbol)] = bars
            self._quotes[str(symbol)] = dict(item.get("quote") or {})

    @property
    def decision_time_ms(self) -> int:
        return self._decision_time_ms

    def set_decision_time(self, decision_time_ms: int) -> None:
        self._decision_time_ms = int(decision_time_ms)

    def _visible(self, symbol: str) -> list[OHLCV]:
        return [
            bar
            for bar in self._bars.get(symbol, [])
            if int(bar.timestamp) + self._tf_ms <= self._decision_time_ms
        ]

    async def fetch_recent(self, symbol: str, limit: int = 100) -> list[OHLCV]:
        return self._visible(symbol)[-max(1, int(limit)) :]

    async def fetch_24h_volume_usdt(self, symbol: str) -> float:
        quote = self._quotes.get(symbol, {})
        if "volume_24h_usdt" in quote:
            return float(quote["volume_24h_usdt"])
        visible = self._visible(symbol)
        if not visible:
            raise PublicDataError(f"replay has no bars for {symbol}")
        start = self._decision_time_ms - 24 * 60 * 60 * 1000
        window = [bar for bar in visible if int(bar.timestamp) >= start]
        if not window:
            window = visible
        # Real bars, no synthetic quote: quote turnover is close * base volume.
        return float(sum(float(bar.close) * float(bar.volume) for bar in window))

    async def fetch_spread_bps(self, symbol: str) -> float:
        quote = self._quotes.get(symbol, {})
        raw = quote.get("spread_bps")
        if raw is None:
            raise PublicDataError(f"replay has no captured spread for {symbol}")
        spread = float(raw)
        if not math.isfinite(spread) or spread < 0:
            raise PublicDataError(f"replay spread is invalid for {symbol}: {raw!r}")
        return spread

    def snapshot_records(self, decision_time_ms: int) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        captured_at_ms = int(self._capture.get("captured_at_ms", 0) or 0)
        for symbol in sorted(self._bars):
            validation = real_data_validation.validate_closed_bars(
                self._visible(symbol),
                provider=str(self._capture.get("provider", self.provider)),
                asset=symbol.split("/")[0],
                symbol=symbol,
                timeframe=self.timeframe,
                decision_time_ms=decision_time_ms,
                received_at_ms=captured_at_ms,
                min_bars=100,
            )
            record = validation.to_dict()
            record.update(
                {
                    "data_mode": self.data_mode,
                    "event_time": ms_to_iso(validation.data_time_ms),
                    "received_at": ms_to_iso(validation.received_at_ms),
                    "decision_time": ms_to_iso(decision_time_ms),
                    "quote": dict(self._quotes.get(symbol, {})),
                }
            )
            records.append(record)
        return records


def capture_from_source(source: PublicRestKlineSource) -> dict[str, Any]:
    """Export the exact bars and quote observations served by ``source``."""
    symbols: dict[str, Any] = {}
    for symbol, capture in sorted(source._captures.items()):
        symbols[symbol] = {
            "bars": [
                [
                    int(b.timestamp),
                    float(b.open),
                    float(b.high),
                    float(b.low),
                    float(b.close),
                    float(b.volume),
                ]
                for b in capture.bars
            ],
            "received_at_ms": capture.received_at_ms,
            "quote": dict(source._quotes.get(symbol, {})),
        }
    return {
        "schema_version": "g7-public-capture/v1",
        "provider": source.provider,
        "timeframe": source.timeframe,
        "captured_at_ms": _now_ms(),
        "symbols": symbols,
    }


def load_capture(path: Path | str) -> dict[str, Any]:
    raw = Path(path).read_text(encoding="utf-8")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise PublicDataError("capture must be a JSON object")
    if payload.get("schema_version") != "g7-public-capture/v1":
        raise PublicDataError("capture has an unsupported schema_version")
    return payload


def capture_sha256(capture: dict[str, Any]) -> str:
    payload = json.dumps(capture, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
