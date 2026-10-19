"""minute_collector — real 1-minute bars with provenance, integrity and recovery.

The vision lane can only execute causally if it is fed bars that really closed. The
repository already had a *historical* 1-minute archive (``vision.quotes``) and a lane that
refuses a quote older than the answer, but no component that watched a live venue minute
by minute. This module is that component, and it is deliberately strict about what it
calls data:

* **Closed means closed.** A kline whose ``open + 60 s`` is still in the future when the
  exchange answered is a bar *in formation*. It is never stored, never counted and never
  handed to a decision: a forming bar's high/low/close change after the fact, so using it
  is look-ahead by construction. The comparison uses the exchange's clock, not the host's.
* **Two timestamps, always.** ``open_ms`` is the origin instant (the bar's own open, UTC);
  ``received_at_ms`` is when this host received the answer; ``server_time_ms`` is the
  exchange's clock at that answer. The triple is what lets a verifier tell a late bar
  from an early decision.
* **A duplicate is not a refresh.** Re-seeing the same minute with identical OHLCV is
  recorded and ignored; seeing the same minute with *different* OHLCV means one of the two
  observations is not the bar, so the symbol is blocked instead of overwritten.
* **A hole is not permission.** Minutes the provider never delivered are recorded as a
  gap. The collector never interpolates, never carries a price forward, and refuses to
  hand a gapped series to a decision: after a disconnect it reconciles forward from the
  last stored minute, and if the hole cannot be filled the symbol stays blocked.
* **Append-only, hashed.** Each symbol's minutes are appended to a JSONL file in strictly
  increasing order and fingerprinted; the manifest publishes the digest so a report can
  name the exact bytes a run consumed.

Nothing here talks to an exchange account, holds a credential or can place an order.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

MINUTE_MS = 60_000
SOURCE_NAME = "binance_spot_rest_1m"
SOURCE_BASE_URL = "https://api.binance.com"
DEFAULT_MAX_SKEW_MS = 5_000
DEFAULT_STALE_AFTER_MS = 150_000
#: A minute is only called closed once this much wall time has passed after its close,
#: so a response that crosses the boundary cannot be mistaken for a completed bar.
DEFAULT_SETTLE_MS = 2_500


class MinuteBarError(ValueError):
    """A row that is not a closed, well-formed 1-minute bar."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class FormingBarError(MinuteBarError):
    """The row's minute had not closed when the exchange answered."""

    def __init__(self, symbol: str, open_ms: int, server_time_ms: int) -> None:
        super().__init__(
            "FORMING_BAR",
            f"{symbol} minute {open_ms} closes at {open_ms + MINUTE_MS} but the exchange "
            f"clock was {server_time_ms}: the bar was still in formation",
        )


class SourceUnavailable(RuntimeError):
    """The venue could not be read. Never converted into an empty page."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def _utc_iso(ms: int) -> str:
    return datetime.fromtimestamp(int(ms) / 1000.0, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def last_closed_minute_open(server_time_ms: int) -> int:
    """Open stamp of the newest minute that has closed by ``server_time_ms``."""

    return (int(server_time_ms) // MINUTE_MS) * MINUTE_MS - MINUTE_MS


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass(frozen=True, slots=True)
class MinuteBar:
    """One closed minute, with when it happened and when it arrived."""

    symbol: str
    open_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    received_at_ms: int
    server_time_ms: int
    source: str = SOURCE_NAME

    def __post_init__(self) -> None:
        stamp = int(self.open_ms)
        if stamp % MINUTE_MS:
            raise MinuteBarError(
                "UNALIGNED_MINUTE",
                f"{self.symbol}: {stamp} is not on a 1-minute boundary",
            )
        if not all(
            value > 0 for value in (self.open, self.high, self.low, self.close)
        ):
            raise MinuteBarError(
                "NON_POSITIVE_PRICE",
                f"{self.symbol}: minute {stamp} has a non-positive price",
            )
        if self.volume < 0:
            raise MinuteBarError(
                "NEGATIVE_VOLUME", f"{self.symbol}: minute {stamp} has negative volume"
            )
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise MinuteBarError(
                "OHLC_INCONSISTENT",
                f"{self.symbol}: minute {stamp} has OHLC outside its own high/low",
            )
        if self.high < self.low:
            raise MinuteBarError(
                "HIGH_BELOW_LOW", f"{self.symbol}: minute {stamp} has high < low"
            )
        if int(self.server_time_ms) < self.close_ms:
            raise FormingBarError(self.symbol, int(self.open_ms), int(self.server_time_ms))

    @property
    def close_ms(self) -> int:
        return int(self.open_ms) + MINUTE_MS

    @property
    def delivery_latency_ms(self) -> int:
        return int(self.received_at_ms) - self.close_ms

    @classmethod
    def from_kline(
        cls,
        symbol: str,
        row: Sequence[Any],
        *,
        received_at_ms: int,
        server_time_ms: int,
        source: str = SOURCE_NAME,
    ) -> MinuteBar:
        """Binance kline row → validated closed minute. Refuses anything else."""

        if len(row) < 6:
            raise MinuteBarError(
                "SHORT_ROW", f"{symbol}: a kline needs at least 6 fields, got {len(row)}"
            )
        try:
            open_ms = int(row[0])
            values = [float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5])]
        except (TypeError, ValueError) as exc:
            raise MinuteBarError(
                "UNPARSABLE_ROW", f"{symbol}: kline is not numeric ({exc})"
            ) from exc
        return cls(
            symbol=symbol,
            open_ms=open_ms,
            open=values[0],
            high=values[1],
            low=values[2],
            close=values[3],
            volume=values[4],
            received_at_ms=int(received_at_ms),
            server_time_ms=int(server_time_ms),
            source=source,
        )

    def to_row(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "open_ms": int(self.open_ms),
            "open_utc": _utc_iso(self.open_ms),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "close_ms": self.close_ms,
            "received_at_ms": int(self.received_at_ms),
            "server_time_ms": int(self.server_time_ms),
            "delivery_latency_ms": self.delivery_latency_ms,
            "source": self.source,
        }

    def ohlcv(self) -> tuple[float, float, float, float, float]:
        return (self.open, self.high, self.low, self.close, self.volume)

    def to_bar(self) -> Any:
        """The research ``Bar`` shape the lane consumes (open-stamped)."""

        from trading_bot.research.economic_recovery.experiments import Bar

        return Bar(
            ts_ms=int(self.open_ms),
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
        )


@dataclass(frozen=True, slots=True)
class CollectorHealth:
    symbol: str
    state: str
    reason: str
    last_open_ms: int | None
    last_close_ms: int | None
    age_ms: int | None
    minutes: int
    gaps: int
    blocked_reason: str | None = None

    @property
    def tradeable(self) -> bool:
        return self.state == "OK" and self.blocked_reason is None


class MinuteStore:
    """Append-only JSONL of minutes for one symbol, strictly increasing."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        self._lock_fd: int | None = None
        self._bars: dict[int, MinuteBar] = {}
        self._order: list[int] = []
        self._digest = hashlib.sha256()

    # -- lifecycle -----------------------------------------------------------

    def open(self) -> MinuteStore:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._lock_fd = os.open(self._lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise RuntimeError(
                f"{self._lock_path} exists: another collector owns this store"
            ) from exc
        os.write(self._lock_fd, str(os.getpid()).encode())
        self._load()
        return self

    def close(self) -> None:
        if self._lock_fd is not None:
            os.close(self._lock_fd)
            self._lock_fd = None
            with contextlib.suppress(FileNotFoundError):  # pragma: no cover - already gone
                self._lock_path.unlink()

    def __enter__(self) -> MinuteStore:
        return self.open()

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _load(self) -> None:
        if not self.path.exists():
            return
        previous = 0
        with self.path.open("r", encoding="utf-8", newline="\n") as handle:
            for number, raw in enumerate(handle, start=1):
                if not raw.strip():
                    continue
                try:
                    row = json.loads(raw)
                    bar = MinuteBar(
                        symbol=str(row["symbol"]),
                        open_ms=int(row["open_ms"]),
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=float(row["volume"]),
                        received_at_ms=int(row["received_at_ms"]),
                        server_time_ms=int(row["server_time_ms"]),
                        source=str(row.get("source", SOURCE_NAME)),
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    raise MinuteBarError(
                        "CORRUPT_STORE",
                        f"{self.path}:{number} is not a stored minute ({exc})",
                    ) from exc
                if bar.open_ms <= previous:
                    raise MinuteBarError(
                        "CORRUPT_STORE",
                        f"{self.path}:{number} minute {bar.open_ms} does not follow "
                        f"{previous}; an append-only store must be strictly increasing",
                    )
                previous = bar.open_ms
                self._bars[bar.open_ms] = bar
                self._order.append(bar.open_ms)

    # -- writes --------------------------------------------------------------

    def append(self, bar: MinuteBar) -> str:
        """``APPENDED``, ``DUPLICATE_IDENTICAL`` or raise on conflict/order."""

        if self._lock_fd is None:
            raise RuntimeError("MinuteStore.append() before open()")
        known = self._bars.get(bar.open_ms)
        if known is not None:
            if known.ohlcv() == bar.ohlcv():
                return "DUPLICATE_IDENTICAL"
            raise MinuteBarError(
                "DUPLICATE_CONFLICT",
                f"{bar.symbol} minute {bar.open_ms} was already stored as "
                f"{known.ohlcv()} and arrived again as {bar.ohlcv()}; one of the two "
                "observations is not the bar, so the symbol is blocked rather than "
                "silently overwritten",
            )
        if self._order and bar.open_ms < self._order[-1]:
            raise MinuteBarError(
                "OUT_OF_ORDER",
                f"{bar.symbol} minute {bar.open_ms} arrived after {self._order[-1]}; "
                "an append-only store cannot be rewritten, so this is a reconciliation "
                "failure rather than a new observation",
            )
        line = _canonical(bar.to_row())
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._bars[bar.open_ms] = bar
        self._order.append(bar.open_ms)
        self._digest.update((line + "\n").encode("utf-8"))
        return "APPENDED"

    # -- inspection ----------------------------------------------------------

    def __len__(self) -> int:
        return len(self._order)

    @property
    def last_open_ms(self) -> int | None:
        return self._order[-1] if self._order else None

    @property
    def last_close_ms(self) -> int | None:
        last = self.last_open_ms
        return None if last is None else last + MINUTE_MS

    @property
    def first_open_ms(self) -> int | None:
        return self._order[0] if self._order else None

    def bars(self) -> list[MinuteBar]:
        return [self._bars[stamp] for stamp in self._order]

    def has(self, open_ms: int) -> bool:
        return int(open_ms) in self._bars

    def digest(self) -> str:
        """sha256 of the file as stored (re-read, never the in-memory form)."""

        if not self.path.exists():
            return hashlib.sha256(b"").hexdigest()
        digest = hashlib.sha256()
        with self.path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def gaps(self) -> list[dict[str, int]]:
        """Missing minute ranges inside ``[first, last]``, as half-open intervals."""

        out: list[dict[str, int]] = []
        run_start: int | None = None
        for previous, current in zip(self._order, self._order[1:], strict=False):
            expected = previous + MINUTE_MS
            if current == expected:
                if run_start is not None:
                    out.append({"from_ms": run_start, "to_ms": previous + MINUTE_MS})
                    run_start = None
                continue
            if run_start is None:
                run_start = expected
        if run_start is not None:
            out.append({"from_ms": run_start, "to_ms": self._order[-1]})
        return out

    def contiguous_tail(self) -> list[MinuteBar]:
        """The trailing run of consecutive minutes, newest last.

        A hole before it is history, not permission: the caller gets the part it can
        trust minute by minute, and the manifest records what was dropped.
        """

        if not self._order:
            return []
        end = len(self._order) - 1
        start = end
        while start > 0 and self._order[start] - self._order[start - 1] == MINUTE_MS:
            start -= 1
        return [self._bars[stamp] for stamp in self._order[start:]]


@dataclass(frozen=True, slots=True)
class KlinePage:
    symbol: str
    rows: tuple[tuple[Any, ...], ...]
    server_time_ms: int
    received_at_ms: int


class KlineSource(Protocol):
    """The only thing the collector is allowed to know about a venue."""

    name: str

    def fetch(
        self,
        symbol: str,
        *,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 500,
    ) -> KlinePage: ...

    def server_time(self) -> int: ...


class BinanceRestSource:
    """Public, credential-free 1-minute klines from Binance spot."""

    name = SOURCE_NAME

    def __init__(
        self,
        *,
        base_url: str = SOURCE_BASE_URL,
        timeout_s: float = 20.0,
        user_agent: str = "trading-agentic-portable/1.0",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = float(timeout_s)
        self.user_agent = user_agent

    def _get(self, path: str, params: dict[str, Any]) -> tuple[Any, int, int]:
        url = f"{self.base_url}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                received = int(time.time() * 1000)
                payload = json.loads(response.read().decode("utf-8"))
                return payload, received, int(response.status)
        except urllib.error.HTTPError as exc:
            raise SourceUnavailable(
                f"HTTP_{exc.code}",
                f"{path} answered {exc.code}; not treating it as an empty page",
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise SourceUnavailable(
                "NETWORK", f"{path} could not be read: {type(exc).__name__}: {exc}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise SourceUnavailable("BAD_JSON", f"{path} returned unparsable JSON") from exc

    def server_time(self) -> int:
        payload, _, _ = self._get("/api/v3/time", {})
        if not isinstance(payload, dict) or "serverTime" not in payload:
            raise SourceUnavailable("BAD_TIME", "the venue did not report a server clock")
        try:
            return int(payload["serverTime"])
        except (TypeError, ValueError) as exc:
            raise SourceUnavailable(
                "BAD_TIME", f"the venue clock is not a number: {payload['serverTime']!r}"
            ) from exc

    def fetch(
        self,
        symbol: str,
        *,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 500,
    ) -> KlinePage:
        params: dict[str, Any] = {
            "symbol": symbol,
            "interval": "1m",
            "limit": max(1, min(int(limit), 1000)),
        }
        if start_ms is not None:
            params["startTime"] = int(start_ms)
        if end_ms is not None:
            params["endTime"] = int(end_ms)
        rows, received, _ = self._get("/api/v3/klines", params)
        if not isinstance(rows, list):
            raise SourceUnavailable("BAD_PAGE", f"{symbol}: klines was not a list")
        server = self.server_time()
        return KlinePage(
            symbol=symbol,
            rows=tuple(tuple(row) for row in rows),
            server_time_ms=server,
            received_at_ms=received,
        )


@dataclass
class MinuteCollector:
    """Polls a :class:`KlineSource` into per-symbol append-only minute stores."""

    source: KlineSource
    root: Path
    symbols: Sequence[str]
    max_skew_ms: int = DEFAULT_MAX_SKEW_MS
    stale_after_ms: int = DEFAULT_STALE_AFTER_MS
    settle_ms: int = DEFAULT_SETTLE_MS
    local_clock: Callable[[], int] = lambda: int(time.time() * 1000)
    lookback: int = 3
    stores: dict[str, MinuteStore] = field(default_factory=dict, init=False)
    events: list[dict[str, Any]] = field(default_factory=list, init=False)
    blocked: dict[str, str] = field(default_factory=dict, init=False)
    _ignored_forming: set[tuple[str, int]] = field(default_factory=set, init=False)
    _deferred_settle: set[tuple[str, int]] = field(default_factory=set, init=False)
    _skew_ms: int = 0
    _last_server_time_ms: int = 0
    _events_path: Path = field(init=False)
    _events_chain: str = field(default="0" * 64, init=False)
    _opened: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        self.symbols = tuple(dict.fromkeys(str(s) for s in self.symbols))
        if not self.symbols:
            raise ValueError("a collector with no symbols cannot collect anything")
        self.root = Path(self.root)
        self._events_path = Path(self.root) / "EVENTS.jsonl"

    # -- lifecycle -----------------------------------------------------------

    def open(self) -> MinuteCollector:
        self.root.mkdir(parents=True, exist_ok=True)
        for symbol in self.symbols:
            store = MinuteStore(self.root / f"{symbol}.jsonl").open()
            self.stores[symbol] = store
        self._opened = True
        return self

    def close(self) -> None:
        for store in self.stores.values():
            store.close()
        self._opened = False

    def __enter__(self) -> MinuteCollector:
        return self.open()

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- events --------------------------------------------------------------

    def _event(self, kind: str, *, symbol: str = "", detail: dict[str, Any] | None = None) -> dict[str, Any]:
        at_ms = int(self.local_clock())
        payload = {
            "kind": kind,
            "symbol": symbol,
            "at_ms": at_ms,
            "at_utc": _utc_iso(at_ms),
            "detail": detail or {},
        }
        digest = hashlib.sha256(
            _canonical({"prev": self._events_chain, **payload}).encode("utf-8")
        ).hexdigest()
        row = {**payload, "prev_sha256": self._events_chain, "sha256": digest}
        self._events_chain = digest
        self.events.append(row)
        if self._opened:
            with self._events_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        return row

    # -- ingestion -----------------------------------------------------------

    def _parse_page(
        self, page: KlinePage, *, require_settled: bool = True
    ) -> tuple[list[MinuteBar], dict[str, int]]:
        """Validated, closed minutes from one page, sorted by origin.

        ``require_settled`` is the answer to a measured defect: Binance can still amend a
        minute that has just closed (observed at 07:18:01 and again at 07:27 with a
        different low). A bar is therefore not stored until it has been closed for at
        least ``settle_ms`` on the exchange clock. Historical pages fetched by
        reconciliation are already old, so they bypass the wait.
        """

        symbol = page.symbol
        parsed: list[MinuteBar] = []
        ignored = 0
        deferred = 0
        for row in page.rows:
            try:
                bar = MinuteBar.from_kline(
                    symbol,
                    row,
                    received_at_ms=page.received_at_ms,
                    server_time_ms=page.server_time_ms,
                    source=self.source.name,
                )
            except FormingBarError:
                open_ms = int(row[0]) if row else 0
                key = (symbol, open_ms)
                if key not in self._ignored_forming:
                    self._ignored_forming.add(key)
                    self._event(
                        "FORMING_BAR_IGNORED",
                        symbol=symbol,
                        detail={
                            "open_ms": open_ms,
                            "server_time_ms": page.server_time_ms,
                            "reason": "the minute had not closed when the venue answered",
                        },
                    )
                ignored += 1
                continue
            except MinuteBarError as exc:
                self._block(symbol, f"{exc.code}: {exc.detail}")
                self._event(exc.code, symbol=symbol, detail={"detail": exc.detail})
                continue
            if require_settled and int(page.server_time_ms) < bar.close_ms + int(self.settle_ms):
                key = (symbol, bar.open_ms)
                if key not in self._deferred_settle:
                    self._deferred_settle.add(key)
                    self._event(
                        "SETTLE_DEFERRED",
                        symbol=symbol,
                        detail={
                            "open_ms": bar.open_ms,
                            "close_ms": bar.close_ms,
                            "server_time_ms": page.server_time_ms,
                            "settle_ms": int(self.settle_ms),
                            "reason": "the venue can still amend a minute just after it "
                            "closes; it is not stored until it has settled",
                        },
                    )
                deferred += 1
                continue
            parsed.append(bar)
        parsed.sort(key=lambda item: item.open_ms)
        return parsed, {"forming_ignored": ignored, "settle_deferred": deferred}

    def _store_bar(self, bar: MinuteBar) -> str:
        try:
            outcome = self.stores[bar.symbol].append(bar)
        except MinuteBarError as exc:
            self._block(bar.symbol, f"{exc.code}: {exc.detail}")
            self._event(exc.code, symbol=bar.symbol, detail={"detail": exc.detail})
            return "REJECTED"
        if outcome == "DUPLICATE_IDENTICAL":
            self._event(
                "DUPLICATE_IDENTICAL",
                symbol=bar.symbol,
                detail={"open_ms": bar.open_ms},
            )
        return outcome

    def _fill_forward(self, symbol: str, *, until_open_ms: int, max_pages: int = 8) -> bool:
        """Fetch the minutes between the store's last bar and ``until_open_ms``.

        Called *before* a later minute is appended, so the store never has to be rewritten
        and a hole is never crossed by a later price. Returns ``False`` when the venue
        cannot supply the hole: the caller blocks the symbol instead of continuing.
        """

        store = self.stores[symbol]
        target = int(until_open_ms)
        for _ in range(max_pages):
            last = store.last_open_ms
            if last is None:
                return False
            if last + MINUTE_MS >= target:
                return True
            page = self.source.fetch(symbol, start_ms=last + MINUTE_MS, limit=1000)
            # These minutes are older than the bar that triggered the fill, so they are
            # already settled; the gate applies to the newest page only.
            parsed, _ = self._parse_page(page, require_settled=False)
            progressed = False
            for bar in parsed:
                current = store.last_open_ms
                if current is None:  # pragma: no cover - store cannot be emptied
                    break
                if bar.open_ms > current + MINUTE_MS:
                    # The venue skipped a minute inside the range it was asked for.
                    break
                if bar.open_ms >= target:
                    break
                if self._store_bar(bar) == "APPENDED":
                    progressed = True
            if not progressed:
                return False
        last = store.last_open_ms
        return last is not None and last + MINUTE_MS >= target

    def _merge_page(self, page: KlinePage) -> dict[str, Any]:
        """Store a page strictly forward, filling any hole *before* crossing it."""

        symbol = page.symbol
        parsed, meta = self._parse_page(page)
        appended = 0
        duplicates = 0
        for bar in parsed:
            last = self.stores[symbol].last_open_ms
            if last is not None and bar.open_ms > last + MINUTE_MS:
                missing = (bar.open_ms - last) // MINUTE_MS - 1
                self._event(
                    "GAP",
                    symbol=symbol,
                    detail={
                        "from_ms": last + MINUTE_MS,
                        "to_ms": bar.open_ms,
                        "missing_minutes": missing,
                    },
                )
                if not self._fill_forward(symbol, until_open_ms=bar.open_ms):
                    self._block(
                        symbol,
                        f"UNRESOLVED_GAP: {missing} minute(s) before {bar.open_ms} could "
                        "not be reconciled; the later minute is not stored either",
                    )
                    self._event(
                        "RECONCILE_FAILED",
                        symbol=symbol,
                        detail={"from_ms": last + MINUTE_MS, "to_ms": bar.open_ms},
                    )
                    break
                self._event(
                    "GAP_FILLED",
                    symbol=symbol,
                    detail={"to_ms": bar.open_ms, "missing_minutes": missing},
                )
            outcome = self._store_bar(bar)
            if outcome == "APPENDED":
                appended += 1
            elif outcome == "DUPLICATE_IDENTICAL":
                duplicates += 1
            elif outcome == "REJECTED":
                break
        return {
            "appended": appended,
            "duplicates": duplicates,
            "forming_ignored": meta["forming_ignored"],
            "settle_deferred": meta.get("settle_deferred", 0),
        }

    def _block(self, symbol: str, reason: str) -> None:
        self.blocked[symbol] = reason

    def _unblock(self, symbol: str) -> None:
        self.blocked.pop(symbol, None)

    def _clear_recoverable_block(self, symbol: str) -> None:
        reason = self.blocked.get(symbol)
        if reason and reason.split(":", 1)[0] in {
            "RECONCILE_FAILED",
            "UNRESOLVED_GAP",
            "NO_DATA",
            "FEED_DOWN",
        }:
            self._unblock(symbol)

    def bootstrap(self, *, minutes: int = 240) -> dict[str, Any]:
        """Load recent history so a decision window exists immediately.

        The window is real venue data, not a synthetic warm-up: if the provider cannot
        supply it, the symbol starts blocked instead of starting with invented bars.
        """

        started = int(self.local_clock())
        server = self.source.server_time()
        skew = started - int(server)
        self._skew_ms = skew
        self._last_server_time_ms = int(server)
        if abs(skew) > self.max_skew_ms:
            self._event(
                "CLOCK_SKEW",
                detail={"local_ms": started, "server_time_ms": int(server), "skew_ms": skew},
            )
        result: dict[str, Any] = {"server_time_ms": int(server), "skew_ms": skew, "symbols": {}}
        limit = max(10, min(int(minutes) + 5, 1000))
        for symbol in self.symbols:
            page = self.source.fetch(symbol, limit=limit)
            merged = self._merge_page(page)
            result["symbols"][symbol] = {
                **merged,
                "minutes": len(self.stores[symbol]),
                "first_open_ms": self.stores[symbol].first_open_ms,
                "last_open_ms": self.stores[symbol].last_open_ms,
            }
            if len(self.stores[symbol]) == 0 and symbol not in self.blocked:
                self._block(symbol, "NO_DATA: the bootstrap page contained no closed minute")
        self.write_manifest()
        return result

    def poll(self) -> dict[str, Any]:
        """One pass: read the venue clock, then the last few minutes per symbol."""

        if not self._opened:
            raise RuntimeError("MinuteCollector.poll() before open()")
        local = int(self.local_clock())
        server = self.source.server_time()
        skew = local - int(server)
        self._skew_ms = skew
        self._last_server_time_ms = int(server)
        if abs(skew) > self.max_skew_ms:
            self._event(
                "CLOCK_SKEW",
                detail={"local_ms": local, "server_time_ms": int(server), "skew_ms": skew},
            )
        per_symbol: dict[str, Any] = {}
        for symbol in self.symbols:
            page = self.source.fetch(symbol, limit=self.lookback)
            per_symbol[symbol] = self._merge_page(page)
            last = self.stores[symbol].last_open_ms
            if last is None:
                if symbol not in self.blocked:
                    self._block(symbol, "NO_DATA: no closed minute has been observed")
                continue
            if int(server) - (last + MINUTE_MS) > self.stale_after_ms:
                self._event(
                    "STALE",
                    symbol=symbol,
                    detail={
                        "last_open_ms": last,
                        "age_ms": int(server) - (last + MINUTE_MS),
                        "threshold_ms": self.stale_after_ms,
                    },
                )
        self.write_manifest()
        return {
            "ok": True,
            "server_time_ms": int(server),
            "skew_ms": skew,
            "symbols": per_symbol,
            "health": self.health(),
        }

    def reconcile(self, symbol: str, *, max_pages: int = 8) -> dict[str, Any]:
        """Fill forward from the last stored minute to the venue's last closed minute."""

        store = self.stores[symbol]
        before = len(store)
        server = self.source.server_time()
        self._last_server_time_ms = int(server)
        target = last_closed_minute_open(int(server) - int(self.settle_ms))
        if store.last_open_ms is None:
            page = self.source.fetch(symbol, limit=240)
            self._merge_page(page)
            ok = len(store) > 0
        else:
            ok = self._fill_forward(
                symbol, until_open_ms=target + MINUTE_MS, max_pages=max_pages
            )
        appended = len(store) - before
        gaps = store.gaps()
        if not ok or gaps or store.last_open_ms != target:
            self._block(
                symbol,
                "RECONCILE_FAILED: the venue could not fill the minutes between the last "
                f"stored one and {target} (stored {store.last_open_ms}, gaps {len(gaps)})",
            )
            self._event(
                "RECONCILE_FAILED",
                symbol=symbol,
                detail={
                    "target_open_ms": target,
                    "last_open_ms": store.last_open_ms,
                    "gaps": gaps,
                },
            )
        else:
            self._clear_recoverable_block(symbol)
            self._event("RECONCILED", symbol=symbol, detail={"appended": appended})
        return {
            "symbol": symbol,
            "appended": appended,
            "ok": bool(ok and not gaps and store.last_open_ms == target),
            "last_open_ms": store.last_open_ms,
            "target_open_ms": target,
        }

    def collect(
        self, *, max_attempts: int = 4, base_backoff_s: float = 1.5
    ) -> dict[str, Any]:
        """Poll with bounded retries; after a disconnect, reconcile before trading."""

        delay = float(base_backoff_s)
        last_error: SourceUnavailable | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                result = self.poll()
            except SourceUnavailable as exc:
                last_error = exc
                self._event(
                    "DISCONNECT",
                    detail={
                        "code": exc.code,
                        "detail": exc.detail,
                        "attempt": attempt,
                        "retry_in_s": delay,
                    },
                )
                if attempt < max_attempts:
                    time.sleep(delay)
                    delay = min(delay * 2, 30.0)
                continue
            if attempt > 1:
                self._event("RECONNECT", detail={"attempt": attempt})
                for symbol in self.symbols:
                    try:
                        self.reconcile(symbol)
                    except SourceUnavailable as exc:
                        self._block(
                            symbol,
                            f"RECONCILE_FAILED: {exc.code}: {exc.detail}",
                        )
                        self._event(
                            "RECONCILE_FAILED",
                            symbol=symbol,
                            detail={"code": exc.code, "detail": exc.detail},
                        )
                result = self.poll()
            return result
        assert last_error is not None
        for symbol in self.symbols:
            self._block(symbol, f"FEED_DOWN: {last_error.code}: {last_error.detail}")
        self.write_manifest()
        return {
            "ok": False,
            "code": last_error.code,
            "detail": last_error.detail,
            "health": self.health(),
        }

    # -- read side -----------------------------------------------------------

    def health(self) -> dict[str, CollectorHealth]:
        """Health per symbol at the last exchange-clock instant that was observed."""

        if self._last_server_time_ms <= 0:
            raise RuntimeError(
                "health() before bootstrap/poll: there is no venue clock to judge freshness "
                "against, and the host clock is not a substitute"
            )
        return self.health_at(self._last_server_time_ms)

    def health_at(self, now_ms: int) -> dict[str, CollectorHealth]:
        """Health per symbol, judged against a supplied exchange-clock instant."""

        out: dict[str, CollectorHealth] = {}
        for symbol in self.symbols:
            store = self.stores[symbol]
            last_open = store.last_open_ms
            last_close = store.last_close_ms
            age = None if last_close is None else int(now_ms) - int(last_close)
            gaps = store.gaps()
            blocked_reason = self.blocked.get(symbol)
            if blocked_reason:
                state, reason = "BLOCKED", blocked_reason
            elif abs(self._skew_ms) > self.max_skew_ms:
                state, reason = (
                    "CLOCK_SKEW",
                    f"host clock differs from the venue by {self._skew_ms} ms",
                )
            elif gaps:
                state, reason = (
                    "GAP",
                    f"{len(gaps)} minute range(s) missing inside the stored series",
                )
            elif age is not None and age > self.stale_after_ms:
                state, reason = "STALE", f"last closed minute is {age} ms old"
            elif last_open is None:
                state, reason = "BLOCKED", "NO_DATA: no closed minute has been observed"
            else:
                state, reason = "OK", "the last closed minute arrived inside its window"
            out[symbol] = CollectorHealth(
                symbol=symbol,
                state=state,
                reason=reason,
                last_open_ms=last_open,
                last_close_ms=last_close,
                age_ms=age,
                minutes=len(store),
                gaps=len(gaps),
                blocked_reason=blocked_reason,
            )
        return out

    def series(self) -> dict[str, list[Any]]:
        """Contiguous minute tail per symbol, as research ``Bar`` objects."""

        return {
            symbol: [bar.to_bar() for bar in self.stores[symbol].contiguous_tail()]
            for symbol in self.symbols
        }

    def minute_bars(self) -> dict[str, list[MinuteBar]]:
        return {symbol: self.stores[symbol].contiguous_tail() for symbol in self.symbols}

    def manifest(self) -> dict[str, Any]:
        now = int(self.local_clock())
        health = self.health_at(self._last_server_time_ms)
        symbols: dict[str, Any] = {}
        for symbol in self.symbols:
            store = self.stores[symbol]
            tail = store.contiguous_tail()
            symbols[symbol] = {
                "minutes": len(store),
                "first_open_ms": store.first_open_ms,
                "last_open_ms": store.last_open_ms,
                "first_open_utc": None
                if store.first_open_ms is None
                else _utc_iso(store.first_open_ms),
                "last_open_utc": None
                if store.last_open_ms is None
                else _utc_iso(store.last_open_ms),
                "sha256": store.digest(),
                "gaps": store.gaps(),
                "contiguous_tail_minutes": len(tail),
                "dropped_prefix_minutes": len(store) - len(tail),
                "health": {
                    "state": health[symbol].state,
                    "reason": health[symbol].reason,
                },
            }
        return {
            "schema_version": "MINUTE_COLLECTOR_MANIFEST_V1",
            "source": self.source.name,
            "generated_at_utc": _utc_iso(now),
            "skew_ms": self._skew_ms,
            "max_skew_ms": self.max_skew_ms,
            "stale_after_ms": self.stale_after_ms,
            "settle_ms": self.settle_ms,
            "symbols": symbols,
            "events": len(self.events),
            "blocked": dict(sorted(self.blocked.items())),
            "events_sha256": self._events_chain,
        }

    def write_manifest(self) -> Path:
        path = self.root / "MANIFEST.json"
        payload = json.dumps(self.manifest(), indent=2, sort_keys=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(payload, encoding="utf-8", newline="\n")
        os.replace(tmp, path)
        return path


def replay_source(pages: Iterable[KlinePage]) -> KlineSource:
    """A deterministic source for tests: one page per ``fetch`` call.

    Kept in the module (not in the test file) because the contract it stands for is the
    source protocol itself: a page carries its own exchange clock and receipt instant.
    """

    queue = list(pages)

    class _Replay:
        name = "replay_source"

        def fetch(
            self,
            symbol: str,
            *,
            start_ms: int | None = None,
            end_ms: int | None = None,
            limit: int = 500,
        ) -> KlinePage:
            for index, page in enumerate(queue):
                if page.symbol == symbol:
                    return queue.pop(index)
            raise SourceUnavailable("REPLAY_EXHAUSTED", f"no page left for {symbol}")

        def server_time(self) -> int:
            if not queue:
                raise SourceUnavailable("REPLAY_EXHAUSTED", "no page left for the clock")
            return int(queue[0].server_time_ms)

    return _Replay()


def aggregate_complete(
    bars: Sequence[MinuteBar], *, interval_ms: int
) -> tuple[list[Any], dict[str, Any]]:
    """Minutes → bars of ``interval_ms``, only when every minute was observed.

    A group with a missing minute is *not* resampled from the minutes around it: its
    high/low would be a claim nobody observed. The group is dropped and counted.
    """

    from trading_bot.research.economic_recovery.experiments import Bar

    if interval_ms <= 0 or interval_ms % MINUTE_MS:
        raise ValueError("interval_ms must be a positive multiple of one minute")
    per_group = interval_ms // MINUTE_MS
    groups: dict[int, list[MinuteBar]] = {}
    for bar in bars:
        group = (int(bar.open_ms) // interval_ms) * interval_ms
        groups.setdefault(group, []).append(bar)
    out: list[Any] = []
    incomplete: list[int] = []
    pending: int | None = None
    leading: int | None = None
    ordered_groups = sorted(groups)
    for position, group in enumerate(ordered_groups):
        members = sorted(groups[group], key=lambda item: item.open_ms)
        expected = [group + index * MINUTE_MS for index in range(per_group)]
        observed = [item.open_ms for item in members]
        if observed == expected:
            out.append(
                Bar(
                    ts_ms=group,
                    open=members[0].open,
                    high=max(item.high for item in members),
                    low=min(item.low for item in members),
                    close=members[-1].close,
                    volume=sum(item.volume for item in members),
                )
            )
            continue
        if position == len(ordered_groups) - 1 and observed == expected[: len(observed)]:
            # The newest group simply has not finished closing yet. That is the normal
            # state of the last bar, not missing data, so it is not an error.
            pending = group
            continue
        if position == 0 and observed == expected[per_group - len(observed) :]:
            # The oldest group was cut by the start of the requested window, not by a
            # hole in the feed: its first minutes were never asked for. Dropping it is
            # honest; calling it a gap would block a healthy session at every start.
            leading = group
            continue
        incomplete.append(group)
    return out, {
        "interval_ms": interval_ms,
        "minutes_per_bar": per_group,
        "bars": len(out),
        "incomplete_groups": incomplete,
        "pending_group": pending,
        "leading_partial_group": leading,
    }
