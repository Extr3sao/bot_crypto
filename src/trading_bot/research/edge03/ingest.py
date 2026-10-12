"""EDGE-03 ingestion — incremental, append-only, closed-bars-only forward corpus.

The frozen corpora are evidence and are never written to. This module reads them (only
to learn where they end) and grows a **separate** store of what the venue said
afterwards, one closed bar at a time.

The contract, in the order it is enforced:

1. **Only closed bars.** A bar is admissible when ``ts + interval <= server time`` at the
   instant of the fetch. An open bar is counted and dropped — storing one would let a
   decision read a close that had not happened yet.
2. **Only bars after the frozen end.** ``ts`` must be strictly greater than the frozen
   end of its source timeframe, so a forward reading can never quietly re-measure the
   past an earlier work package already published.
3. **Append-only.** New rows are appended below the bytes already on disk, and the
   operation is refused if the existing prefix would change. A later fetch that
   disagrees with a stored bar is recorded as a *revision*, and the stored value wins:
   the first observation is the observation.
4. **Nothing is invented.** A missing grid slot is a gap: counted, published, never
   filled or interpolated. A corrupt OHLC block is rejected, never repaired.

The store is local (``data/forward/``) because raw bars are large; what is versioned is
the *manifest*: per-file sha256, bar counts, first/last instant and the full quality
audit, so the evidence survives even though the bytes stay on the host.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from trading_bot.research.edge01.data import BAR_MS

__all__ = [
    "BinancePublicKlines",
    "FetchResult",
    "ForwardStore",
    "IngestLedger",
    "ScriptedKlineSource",
    "audit_series",
    "default_store_root",
    "ingest_series",
    "store_manifest",
]

#: The venue's REST host. Public market data only; there is no authenticated call here.
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
BINANCE_TIME_URL = "https://api.binance.com/api/v3/time"
PAGE_LIMIT = 1000  # the endpoint's own maximum rows per response


def default_store_root(repo_root: Path) -> Path:
    """Where the forward store lives: local, large, out of the versioned tree."""
    return repo_root / "data" / "forward" / "edge03"


@dataclass(frozen=True, slots=True)
class FetchResult:
    """What one fetch returned, plus the digest of the bytes it returned."""

    rows: list[list[Any]]
    payload_sha256: str
    pages: int
    requests: list[str]


class KlineSource(Protocol):
    """Anything that can hand back closed OHLCV rows for a window.

    Deliberately tiny: the ingestion logic must be exercisable without a network, and a
    test double that cannot lie about the clock is worth more than a mock.
    """

    name: str

    def server_time_ms(self) -> int:  # pragma: no cover - protocol definition
        ...

    def fetch(  # pragma: no cover - protocol definition
        self, symbol: str, interval: str, start_ms: int, end_ms: int
    ) -> FetchResult:
        ...


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class BinancePublicKlines:
    """The real source: Binance public REST, paginated, retried, no credentials."""

    name = "BINANCE_PUBLIC_REST:/api/v3/klines"

    def __init__(
        self,
        *,
        timeout: float = 20.0,
        attempts: int = 3,
        backoff_seconds: float = 1.5,
        sleep: Callable[[float], None] = time.sleep,
        limit: int = PAGE_LIMIT,
    ) -> None:
        self._timeout = timeout
        self._attempts = attempts
        self._backoff = backoff_seconds
        self._sleep = sleep
        self._limit = limit

    # -- transport ---------------------------------------------------------
    def _get(self, url: str) -> bytes:
        last: Exception | None = None
        for attempt in range(self._attempts):
            try:
                request = urllib.request.Request(
                    url, headers={"User-Agent": "edge03-forward/1.0", "Accept": "application/json"}
                )
                with urllib.request.urlopen(request, timeout=self._timeout) as response:
                    if response.status != 200:
                        raise urllib.error.HTTPError(
                            url, response.status, "unexpected status", response.headers, None
                        )
                    return response.read()
            except Exception as exc:  # noqa: BLE001 - retried, then re-raised verbatim
                last = exc
                if attempt + 1 < self._attempts:
                    self._sleep(self._backoff * (attempt + 1))
        assert last is not None
        raise last

    # -- protocol ----------------------------------------------------------
    def server_time_ms(self) -> int:
        payload = json.loads(self._get(BINANCE_TIME_URL).decode("utf-8"))
        return int(payload["serverTime"])

    @staticmethod
    def venue_symbol(symbol: str) -> str:
        """The venue's own spelling of a pair. This is the only place that knows it."""
        head = symbol.upper()
        return head if head.endswith("USDT") else f"{head}USDT"

    def fetch(self, symbol: str, interval: str, start_ms: int, end_ms: int) -> FetchResult:
        rows: list[list[Any]] = []
        requests: list[str] = []
        digest = hashlib.sha256()
        pages = 0
        cursor = start_ms
        pair = self.venue_symbol(symbol)
        while cursor < end_ms:
            url = (
                f"{BINANCE_KLINES_URL}?symbol={pair}&interval={interval}"
                f"&startTime={cursor}&endTime={end_ms - 1}&limit={self._limit}"
            )
            raw = self._get(url)
            requests.append(url.replace(BINANCE_KLINES_URL, ""))
            digest.update(raw)
            page = json.loads(raw.decode("utf-8"))
            pages += 1
            if not page:
                break
            rows.extend(page)
            last_open = int(page[-1][0])
            if len(page) < self._limit:
                break
            if last_open <= cursor:
                break  # a non-advancing page: stop rather than loop forever
            cursor = last_open + BAR_MS[interval]
            if len(page) == self._limit:
                self._sleep(0.25)  # be a good citizen with the public endpoint
        return FetchResult(
            rows=rows,
            payload_sha256=digest.hexdigest(),
            pages=pages,
            requests=requests,
        )


class ScriptedKlineSource:
    """A deterministic source for tests and rehearsals: rows are handed over verbatim."""

    def __init__(
        self,
        *,
        rows_by_symbol: dict[str, list[Sequence[Any]]],
        server_time: int,
        name: str = "SCRIPTED",
    ) -> None:
        # Keyed by BASE asset (``BTC``); a pair spelling is accepted and normalised, so a
        # test can hand over the same rows the real source would have returned.
        self.rows_by_symbol = {
            k.upper().removesuffix("USDT"): [list(r) for r in v] for k, v in rows_by_symbol.items()
        }
        self.server_time = int(server_time)
        self.name = name
        self.calls: list[tuple[str, str, int, int]] = []

    def server_time_ms(self) -> int:
        return self.server_time

    def fetch(self, symbol: str, interval: str, start_ms: int, end_ms: int) -> FetchResult:
        self.calls.append((symbol, interval, start_ms, end_ms))
        rows = [
            row
            for row in self.rows_by_symbol.get(symbol.upper().removesuffix("USDT"), [])
            if start_ms <= int(row[0]) < end_ms
        ]
        payload = json.dumps(rows, separators=(",", ":")).encode("utf-8")
        return FetchResult(
            rows=rows,
            payload_sha256=_digest(payload),
            pages=1,
            requests=[f"scripted:{symbol}:{interval}:{start_ms}:{end_ms}"],
        )


class ForwardStore:
    """One JSONL file per (timeframe, symbol), append-only, rewritten atomically."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def path(self, timeframe: str, symbol: str) -> Path:
        """One file per (timeframe, base asset): the store speaks assets, not venue pairs."""
        return self.root / timeframe / f"{symbol.upper()}.jsonl"

    def read(self, timeframe: str, symbol: str) -> list[dict[str, Any]]:
        path = self.path(timeframe, symbol)
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
        return rows

    def append(self, timeframe: str, symbol: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
        """Append ``rows`` below the existing bytes; refuse if the prefix would move."""
        path = self.path(timeframe, symbol)
        path.parent.mkdir(parents=True, exist_ok=True)
        previous = path.read_bytes() if path.exists() else b""
        if not rows:
            return {"appended": 0, "bytes": len(previous), "prefix_preserved": True}
        block = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows).encode("utf-8")
        candidate = previous + block
        path.write_bytes(candidate)
        head = path.read_bytes()[: len(previous)]
        if head != previous:
            raise AssertionError(
                f"the append to {path} did not preserve the {len(previous)} stored bytes"
            )
        return {
            "appended": len(rows),
            "bytes": len(candidate),
            "prefix_preserved": True,
            "bytes_prefix": len(previous),
        }

    def sha256(self, timeframe: str, symbol: str) -> str | None:
        path = self.path(timeframe, symbol)
        return _digest(path.read_bytes()) if path.exists() else None


class IngestLedger:
    """Append-only record of every ingestion run, including the empty ones."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def append(self, row: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")

    def read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [
            json.loads(line)
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


def venue_symbol(source: Any, symbol: str) -> str:
    """The pair the source was actually asked for, spelled the way the source spells it."""
    spell = getattr(source, "venue_symbol", None)
    if callable(spell):
        return str(spell(symbol))
    return f"{symbol.upper()}USDT"


def _bar_row(
    raw: Sequence[Any], *, timeframe: str, source: str, fetched_at_ms: int, payload_sha256: str
) -> dict[str, Any]:
    ts, open_, high, low, close, volume = (int(raw[0]), *(_num(v) for v in raw[1:6]))
    return {
        "ts": ts,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "interval": timeframe,
        "source": source,
        "fetched_at_ms": fetched_at_ms,
        "payload_sha256": payload_sha256,
        "closed": True,
    }


def _num(value: Any) -> float:
    return float(value)


def _finite(*values: float) -> bool:
    return all(math.isfinite(v) for v in values)


def validate_rows(
    rows: Iterable[dict[str, Any]], *, timeframe: str, frozen_end_ms: int, observed_at_ms: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Apply the declared admissibility rules to freshly built rows.

    Everything rejected is counted under its own name, so a run can show *why* a bar did
    not make it into the store instead of looking like the venue never sent it.
    """
    span = BAR_MS[timeframe]
    kept: list[dict[str, Any]] = []
    seen: set[int] = set()
    counts = {
        "not_closed": 0,
        "at_or_before_frozen_end": 0,
        "off_grid": 0,
        "duplicate_in_fetch": 0,
        "incomplete_ohlc": 0,
    }
    for row in rows:
        ts = int(row["ts"])
        if ts + span > observed_at_ms:
            counts["not_closed"] += 1
            continue
        if ts <= frozen_end_ms:
            counts["at_or_before_frozen_end"] += 1
            continue
        if ts % span != 0:
            counts["off_grid"] += 1
            continue
        if ts in seen:
            counts["duplicate_in_fetch"] += 1
            continue
        o, h, low, c = row["open"], row["high"], row["low"], row["close"]
        if not _finite(o, h, low, c, row["volume"]) or min(o, h, low, c) <= 0:
            counts["incomplete_ohlc"] += 1
            continue
        if h < low or h < max(o, c) or low > min(o, c):
            counts["incomplete_ohlc"] += 1
            continue
        seen.add(ts)
        kept.append(row)
    kept.sort(key=lambda r: int(r["ts"]))
    return kept, counts


def audit_series(
    stored: list[dict[str, Any]], *, timeframe: str, frozen_end_ms: int
) -> dict[str, Any]:
    """Full quality audit of what is stored: gaps, duplicates, order, boundaries."""
    span = BAR_MS[timeframe]
    stamps = [int(r["ts"]) for r in stored]
    duplicates = len(stamps) - len(set(stamps))
    out_of_order = sum(1 for a, b in zip(stamps, stamps[1:]) if b <= a)
    gaps: list[dict[str, Any]] = []
    missing_slots = 0
    for a, b in zip(stamps, stamps[1:]):
        if b - a <= span:
            continue
        slots = (b - a) // span - 1
        missing_slots += int(slots)
        gaps.append({"after_ts": a, "before_ts": b, "missing_bars": int(slots)})
    if stamps:
        first_expected = frozen_end_ms + span
        if stamps[0] > first_expected:
            slots = (stamps[0] - first_expected) // span
            missing_slots += int(slots)
            gaps.insert(
                0,
                {
                    "after_ts": frozen_end_ms,
                    "before_ts": stamps[0],
                    "missing_bars": int(slots),
                    "note": "gap between the frozen end and the first stored bar",
                },
            )
    return {
        "timeframe": timeframe,
        "bars": len(stamps),
        "first_ts": stamps[0] if stamps else None,
        "last_ts": stamps[-1] if stamps else None,
        "first_expected_ts": frozen_end_ms + span,
        "duplicates": duplicates,
        "out_of_order": out_of_order,
        "gaps": gaps,
        "gap_count": len(gaps),
        "missing_bars": missing_slots,
        "contiguous": missing_slots == 0 and duplicates == 0 and out_of_order == 0,
    }


def detect_revisions(
    stored: list[dict[str, Any]], refetched: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Compare a re-fetch of already-stored bars against what was stored first.

    The store keeps the first observation; a disagreement is published as a revision
    (price or volume moved after the bar closed), which is the only honest way to report
    that the venue's history is not immutable.
    """
    index = {int(r["ts"]): r for r in stored}
    revisions: list[dict[str, Any]] = []
    for row in refetched:
        ts = int(row["ts"])
        known = index.get(ts)
        if known is None:
            continue
        moved = {
            field: (known[field], row[field])
            for field in ("open", "high", "low", "close", "volume")
            if abs(float(known[field]) - float(row[field])) > 1e-12
        }
        if moved:
            revisions.append({"ts": ts, "fields": moved, "kept": "the first observation"})
    return revisions


def ingest_series(
    *,
    source: KlineSource,
    store: ForwardStore,
    ledger: IngestLedger,
    timeframe: str,
    symbol: str,
    frozen_end_ms: int,
    observed_at_ms: int | None = None,
    overlap_bars: int = 48,
) -> dict[str, Any]:
    """Grow one (timeframe, symbol) series by the bars that closed since the last run.

    Returns the ledger row it appended, so the caller publishes exactly what happened —
    including ``no_new_data``, which is a result and not an error.
    """
    span = BAR_MS[timeframe]
    stored = store.read(timeframe, symbol)
    now = int(observed_at_ms if observed_at_ms is not None else source.server_time_ms())
    high_water = max([int(r["ts"]) for r in stored], default=frozen_end_ms)
    next_expected = high_water + span
    row: dict[str, Any] = {
        "run_at_ms": now,
        "timeframe": timeframe,
        "symbol": symbol,
        "source": getattr(source, "name", "UNKNOWN"),
        "venue_symbol": venue_symbol(source, symbol),
        "frozen_end_ms": frozen_end_ms,
        "high_water_ts": high_water if stored else None,
        "next_expected_ts": next_expected,
        "stored_before": len(stored),
    }

    if next_expected + span > now:
        row.update(
            {
                "outcome": "no_new_data",
                "reason": (
                    f"the next {timeframe} bar (open {next_expected}) had not closed at "
                    f"{now}; nothing to ingest"
                ),
                "fetched_rows": 0,
                "appended": 0,
                "rejected": {},
                "revisions": [],
                "audit": audit_series(stored, timeframe=timeframe, frozen_end_ms=frozen_end_ms),
            }
        )
        ledger.append(row)
        return row

    fetched = source.fetch(symbol, timeframe, next_expected, now)
    built = [
        _bar_row(
            raw,
            timeframe=timeframe,
            source=getattr(source, "name", "UNKNOWN"),
            fetched_at_ms=now,
            payload_sha256=fetched.payload_sha256,
        )
        for raw in fetched.rows
        if raw
    ]
    admissible, rejected = validate_rows(
        built, timeframe=timeframe, frozen_end_ms=frozen_end_ms, observed_at_ms=now
    )
    known = {int(r["ts"]) for r in stored}
    already = [r for r in admissible if int(r["ts"]) in known]
    fresh = [r for r in admissible if int(r["ts"]) not in known]

    # A revision check re-reads bars already stored; the stored value is kept.
    revisions: list[dict[str, Any]] = []
    if stored and overlap_bars > 0:
        reference = stored[-overlap_bars:]
        start = int(reference[0]["ts"])
        end = int(reference[-1]["ts"]) + span
        if end > start:
            refetch = source.fetch(symbol, timeframe, start, end)
            refetched = [
                _bar_row(
                    raw,
                    timeframe=timeframe,
                    source=getattr(source, "name", "UNKNOWN"),
                    fetched_at_ms=now,
                    payload_sha256=refetch.payload_sha256,
                )
                for raw in refetch.rows
                if raw
            ]
            revisions = detect_revisions(reference, refetched)

    write = store.append(timeframe, symbol, fresh)
    after = store.read(timeframe, symbol)
    audit = audit_series(after, timeframe=timeframe, frozen_end_ms=frozen_end_ms)
    outcome = "ingested" if fresh else "no_new_data"
    row.update(
        {
            "outcome": outcome,
            "reason": None
            if fresh
            else f"the fetch returned no bar after {high_water} that had closed",
            "fetched_rows": len(fetched.rows),
            "pages": fetched.pages,
            "requests": fetched.requests,
            "payload_sha256": fetched.payload_sha256,
            "rejected": {**rejected, "already_stored": len(already)},
            "appended": write["appended"],
            "store_bytes": write["bytes"],
            "store_sha256": store.sha256(timeframe, symbol),
            "prefix_preserved": write["prefix_preserved"],
            "revisions": revisions,
            "audit": audit,
            "stored_after": len(after),
        }
    )
    ledger.append(row)
    return row


def store_manifest(store: ForwardStore, *, series: Iterable[tuple[str, str]]) -> dict[str, Any]:
    """Per-file sha256, bar counts and instants: the part of the store worth versioning."""
    files: dict[str, Any] = {}
    for timeframe, symbol in series:
        stored = store.read(timeframe, symbol)
        key = f"{timeframe}:{symbol}"
        files[key] = {
            "path": store.path(timeframe, symbol).name,
            "relative_path": f"{timeframe}/{store.path(timeframe, symbol).name}",
            "bars": len(stored),
            "first_ts": int(stored[0]["ts"]) if stored else None,
            "last_ts": int(stored[-1]["ts"]) if stored else None,
            "sha256": store.sha256(timeframe, symbol),
            "bytes": store.path(timeframe, symbol).stat().st_size
            if store.path(timeframe, symbol).exists()
            else 0,
        }
    return {"files": files, "series": len(files), "total_bars": sum(f["bars"] for f in files.values())}


def observation_days(
    stored: list[dict[str, Any]], *, timeframe: str, coverage: float
) -> dict[str, Any]:
    """Count UTC dates the store covers densely enough to call them observed."""
    expected = {"1h": 24, "15m": 96}[timeframe]
    per_day: dict[str, int] = {}
    per_day_appended: dict[str, int] = {}
    newest_fetch = max((int(row.get("fetched_at_ms") or 0) for row in stored), default=0)
    for row in stored:
        day = time.strftime("%Y-%m-%d", time.gmtime(int(row["ts"]) / 1000))
        per_day[day] = per_day.get(day, 0) + 1
        if int(row.get("fetched_at_ms") or 0) == newest_fetch:
            per_day_appended[day] = per_day_appended.get(day, 0) + 1
    complete = sorted(day for day, seen in per_day.items() if seen >= coverage * expected)
    return {
        "days_with_data": len(per_day),
        "observation_days": len(complete),
        "days": complete,
        "expected_bars_per_day": expected,
        "coverage_required": coverage,
        "per_day_bars": dict(sorted(per_day.items())),
        # Bars that arrived in the MOST RECENT ingest, by the date of the bar itself: the
        # daily report can then say which of the day's bars this run is responsible for
        # instead of crediting the whole store to the day the run happened.
        "newest_fetch_ms": newest_fetch,
        "per_day_appended": dict(sorted(per_day_appended.items())),
    }
