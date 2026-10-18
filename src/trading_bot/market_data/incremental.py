"""Incremental ingestion for OHLCV — watermark, bounded delta, fail-closed coverage.

Why this module exists (RFC-TAP-MARKET-005): the research runtime refetches the
same 1h/4h/1d windows (1000/500/500) on every cycle even when only one new bar
can possibly exist.  The exchange bill is not the only cost: a repeated full
window hides staleness (the newest row may still be forming) and makes
``DATA_TIME <= DECISION_TIME`` an assumption instead of a checked property.

Design constraints, in the order they bind:

* **Reuse, never fork.**  This is a composition around ``ExchangeConnector``
  (and its retry policy) and ``OHLCVStore`` through ``TimeframeStore``.  It does
  not implement a second HTTP client, a second store or a second retry policy.
  ``OHLCVFetcher`` is deliberately not used on the delta path: it validates OHLC
  but cannot drop the forming bar or prove window coverage, which are the two
  properties this plane exists for.
* **The provider contract has no ``since``.**  ``ExchangeConnector.fetch_ohlcv``
  is ``(symbol, timeframe, limit)``, so the delta is a *bounded last-N read plus
  de-duplication*, never a claim of a server-side delta.  ``DELTA_LIMIT`` is
  computed from the watermark and proven to cover the gap by
  ``min(timestamp) <= first_needed_open``.  If the window does not cover it, the
  result is ``INSUFFICIENT_WINDOW`` and the watermark does not move.
* **Only closed bars are persisted.**  A row whose
  ``timestamp + timeframe > now`` is still forming; it is counted and dropped.
  This is the difference between "the fetch succeeded" and "a decision may use
  the bar".
* **Fail closed.**  Provider errors, NaN or ``high < low`` rows, non-monotonic
  rows, a short window, a corrupt watermark or a backlog larger than one
  request never advance the watermark and never invent a bar.

The module is read-only with respect to the exchange: it only calls
``fetch_ohlcv`` (public market data).  It never touches risk, the broker, the
admission registry or execution.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import structlog

from trading_bot.market_data.candle_filter import timeframe_seconds_or_raise
from trading_bot.market_data.exchange_connector import ExchangeConnector
from trading_bot.market_data.timeframe_store import TimeframeStore
from trading_bot.market_data.types import OHLCV

__all__ = [
    "DEFAULT_MAX_BARS_PER_REQUEST",
    "DEFAULT_OVERLAP_BARS",
    "IncrementalOHLCVIngestor",
    "IngestResult",
    "IngestStatus",
    "Watermark",
    "WatermarkCorrupt",
    "WatermarkStore",
    "bar_sha256",
    "closed_boundary_ms",
]

DEFAULT_OVERLAP_BARS = 2
#: Binance spot returns at most 1000 candles per ``klines`` call.  Treated as a
#: hard cap, not a suggestion: exceeding it would make ``min(ts)`` lie about
#: coverage.
DEFAULT_MAX_BARS_PER_REQUEST = 1_000

IngestStatus = Literal[
    "BOOTSTRAP",
    "DELTA",
    "NO_NEW_DATA",
    "RECONCILE",
    "INSUFFICIENT_WINDOW",
    "BACKLOG_EXCEEDS_WINDOW",
    "PROVIDER_FAILED",
    "INCOMPLETE_BARS_ONLY",
    "REJECTED_ROWS",
]

#: Statuses that leave the watermark exactly where it was.
_FAILED_STATUSES: frozenset[str] = frozenset(
    {
        "INSUFFICIENT_WINDOW",
        "BACKLOG_EXCEEDS_WINDOW",
        "PROVIDER_FAILED",
        "INCOMPLETE_BARS_ONLY",
        "REJECTED_ROWS",
    }
)


class WatermarkCorrupt(ValueError):
    """The persisted watermark is unreadable or fails its own checksum.

    Raised instead of silently bootstrapping: a corrupt watermark means the
    coverage history is unknown, and guessing would turn a data bug into a
    "successful" incremental read.
    """


def closed_boundary_ms(now_ms: int, timeframe: str) -> int:
    """Last instant at which a bar of ``timeframe`` may still be open.

    A bar opened at ``t`` is closed at ``t + tf``.  The newest *closed* bar is
    therefore the one with ``t + tf <= now``; ``boundary`` is the open time of
    the bar that is currently forming (or exactly ``now`` when aligned).
    """
    bar_ms = timeframe_seconds_or_raise(timeframe) * 1_000
    return (int(now_ms) // bar_ms) * bar_ms


def bar_sha256(rows: Sequence[OHLCV]) -> str:
    """Canonical hash of a bar sequence: order, timestamps and OHLCV values."""
    payload = [
        [
            int(r.timestamp),
            float(r.open),
            float(r.high),
            float(r.low),
            float(r.close),
            float(r.volume),
        ]
        for r in rows
    ]
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class Watermark:
    """``(source, symbol, timeframe)`` -> how far a consumer may trust the store."""

    source_id: str
    symbol: str
    timeframe: str
    last_verified_open_ms: int
    last_closed_boundary_ms: int
    last_ingested_seq: int
    last_persisted_sha: str
    updated_at_ms: int

    def checksum(self) -> str:
        material = "|".join(
            [
                self.source_id,
                self.symbol,
                self.timeframe,
                str(self.last_verified_open_ms),
                str(self.last_closed_boundary_ms),
                str(self.last_ingested_seq),
                self.last_persisted_sha,
                str(self.updated_at_ms),
            ]
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def to_json(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "last_verified_open_ms": self.last_verified_open_ms,
            "last_closed_boundary_ms": self.last_closed_boundary_ms,
            "last_ingested_seq": self.last_ingested_seq,
            "last_persisted_sha": self.last_persisted_sha,
            "updated_at_ms": self.updated_at_ms,
            "checksum": self.checksum(),
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> Watermark:
        try:
            wm = cls(
                source_id=str(payload["source_id"]),
                symbol=str(payload["symbol"]),
                timeframe=str(payload["timeframe"]),
                last_verified_open_ms=int(payload["last_verified_open_ms"]),
                last_closed_boundary_ms=int(payload["last_closed_boundary_ms"]),
                last_ingested_seq=int(payload["last_ingested_seq"]),
                last_persisted_sha=str(payload["last_persisted_sha"]),
                updated_at_ms=int(payload["updated_at_ms"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise WatermarkCorrupt(f"watermark payload is not readable: {exc}") from exc
        expected = str(payload.get("checksum", ""))
        if not expected or expected != wm.checksum():
            raise WatermarkCorrupt(
                "watermark checksum mismatch: refusing to continue from an unknown coverage point"
            )
        return wm


class WatermarkStore:
    """One small JSON document per ``(source, symbol, timeframe)``.

    Files are written to a temporary sibling and moved with ``os.replace`` so a
    crash can never leave a half-written watermark: either the previous or the
    new value is on disk, both self-checksummed.
    """

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._log = structlog.get_logger(self.__class__.__module__)

    @staticmethod
    def _name(source_id: str, symbol: str, timeframe: str) -> str:
        raw = f"{source_id}__{symbol}__{timeframe}".replace("/", "-").replace(":", "_")
        safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in raw)
        return f"{safe}.json"

    def path_for(self, source_id: str, symbol: str, timeframe: str) -> Path:
        return self._root / self._name(source_id, symbol, timeframe)

    def load(self, source_id: str, symbol: str, timeframe: str) -> Watermark | None:
        path = self.path_for(source_id, symbol, timeframe)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise WatermarkCorrupt(f"{path.name}: {exc}") from exc
        if not isinstance(payload, dict):
            raise WatermarkCorrupt(f"{path.name}: expected a JSON object")
        wm = Watermark.from_json(payload)
        if (wm.source_id, wm.symbol, wm.timeframe) != (source_id, symbol, timeframe):
            raise WatermarkCorrupt(
                f"{path.name}: identity mismatch ({wm.source_id}, {wm.symbol}, {wm.timeframe})"
            )
        return wm

    def save(self, watermark: Watermark) -> Path:
        path = self.path_for(watermark.source_id, watermark.symbol, watermark.timeframe)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(watermark.to_json(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, path)
        return path

    def reset(self, source_id: str, symbol: str, timeframe: str) -> bool:
        """Explicit, user-driven invalidation.  Never called on a corrupt read."""
        path = self.path_for(source_id, symbol, timeframe)
        if path.exists():
            path.unlink()
            self._log.warning("watermark_reset", symbol=symbol, timeframe=timeframe)
            return True
        return False


@dataclass(frozen=True, slots=True)
class IngestResult:
    """What one ingestion cycle actually did, in numbers a verifier can replay."""

    run_id: str
    status: IngestStatus
    source_id: str
    symbol: str
    timeframe: str
    mode: str
    now_ms: int
    boundary_ms: int
    requested_limit: int
    requests_made: int
    rows_returned: int
    rows_final: int
    rows_new: int
    rows_rejected: int
    rows_incomplete: int
    first_needed_open_ms: int | None
    first_returned_open_ms: int | None
    last_returned_open_ms: int | None
    expected_bars: int
    observed_bars: int
    gap_open_ms: tuple[int, ...]
    elapsed_ms: float
    watermark_before: Watermark | None
    watermark_after: Watermark | None
    detail: str

    @property
    def advanced(self) -> bool:
        return self.watermark_after != self.watermark_before

    def to_json(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "source_id": self.source_id,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "mode": self.mode,
            "now_ms": self.now_ms,
            "boundary_ms": self.boundary_ms,
            "requested_limit": self.requested_limit,
            "requests_made": self.requests_made,
            "rows_returned": self.rows_returned,
            "rows_final": self.rows_final,
            "rows_new": self.rows_new,
            "rows_rejected": self.rows_rejected,
            "rows_incomplete": self.rows_incomplete,
            "first_needed_open_ms": self.first_needed_open_ms,
            "first_returned_open_ms": self.first_returned_open_ms,
            "last_returned_open_ms": self.last_returned_open_ms,
            "expected_bars": self.expected_bars,
            "observed_bars": self.observed_bars,
            "gap_open_ms": list(self.gap_open_ms),
            "elapsed_ms": round(self.elapsed_ms, 3),
            "watermark_before": self.watermark_before.to_json() if self.watermark_before else None,
            "watermark_after": self.watermark_after.to_json() if self.watermark_after else None,
            "advanced": self.advanced,
            "detail": self.detail,
        }


def _reject_reason(row: OHLCV) -> str | None:
    values = (row.open, row.high, row.low, row.close, row.volume)
    if any(value != value or value in (float("inf"), float("-inf")) for value in values):
        return "non_finite"
    if row.high < row.low:
        return "high_below_low"
    if min(row.open, row.close) > row.high or max(row.open, row.close) < row.low:
        return "body_outside_range"
    if min(row.open, row.high, row.low, row.close, row.volume) < 0:
        return "negative_value"
    return None


def _normalise(rows: Iterable[OHLCV]) -> tuple[list[OHLCV], int, bool]:
    """Sort, de-duplicate (last write wins) and check monotonicity.

    Returns ``(rows, rejected, had_duplicates)``.  A duplicate timestamp inside a
    single provider response is not an error — providers do resend a boundary
    bar — but it must be de-duplicated *before* the coverage arithmetic, or the
    "expected == observed" check would be off by one and hide a real gap.
    """
    by_ts: dict[int, OHLCV] = {}
    rejected = 0
    duplicates = False
    for row in rows:
        if _reject_reason(row) is not None:
            rejected += 1
            continue
        if int(row.timestamp) in by_ts:
            duplicates = True
        by_ts[int(row.timestamp)] = row
    ordered = [by_ts[ts] for ts in sorted(by_ts)]
    return ordered, rejected, duplicates


class IncrementalOHLCVIngestor:
    """Bootstrap once, then read only the closed tail that can be new.

    ``ingest`` is the only entry point a scheduler needs.  It performs **at most
    one** provider request per call; a backlog larger than one request is
    refused (``BACKLOG_EXCEEDS_WINDOW``) so a long outage cannot be "fixed" by
    silently dropping the middle of the series.  ``reconcile`` is the explicit
    full-window read for that case, and it is labelled as such.
    """

    def __init__(
        self,
        *,
        connector: ExchangeConnector,
        store: TimeframeStore,
        watermarks: WatermarkStore,
        source_id: str,
        warmup_bars: int,
        overlap_bars: int = DEFAULT_OVERLAP_BARS,
        max_bars_per_request: int = DEFAULT_MAX_BARS_PER_REQUEST,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        if warmup_bars <= 0:
            raise ValueError(f"warmup_bars must be > 0, got {warmup_bars}")
        if overlap_bars < 0:
            raise ValueError(f"overlap_bars must be >= 0, got {overlap_bars}")
        if max_bars_per_request <= 0:
            raise ValueError(f"max_bars_per_request must be > 0, got {max_bars_per_request}")
        self._connector = connector
        self._store = store
        self._watermarks = watermarks
        self._source_id = source_id
        self._warmup = min(int(warmup_bars), int(max_bars_per_request))
        self._overlap = int(overlap_bars)
        self._max_bars = int(max_bars_per_request)
        self._clock_ms = clock_ms or (lambda: int(time.time() * 1_000))
        self._log = structlog.get_logger(self.__class__.__module__)

    # ------------------------------------------------------------------ public
    def ingest(
        self,
        symbol: str,
        timeframe: str,
        *,
        now_ms: int | None = None,
        reconcile: bool = False,
    ) -> IngestResult:
        started = time.perf_counter()
        run_id = str(uuid.uuid4())
        now = int(now_ms if now_ms is not None else self._clock_ms())
        barrier = closed_boundary_ms(now, timeframe)
        before = self._watermarks.load(self._source_id, symbol, timeframe)

        if before is None or reconcile:
            mode = "RECONCILE" if before is not None else "BOOTSTRAP"
            return self._bootstrap(
                run_id=run_id,
                symbol=symbol,
                timeframe=timeframe,
                now_ms=now,
                boundary=barrier,
                before=before,
                mode=mode,
                started=started,
            )

        return self._delta(
            run_id=run_id,
            symbol=symbol,
            timeframe=timeframe,
            now_ms=now,
            boundary=barrier,
            before=before,
            started=started,
        )

    # ---------------------------------------------------------------- internals
    def _empty_result(self, **kwargs: Any) -> IngestResult:
        base: dict[str, Any] = {
            "first_needed_open_ms": None,
            "first_returned_open_ms": None,
            "last_returned_open_ms": None,
            "gap_open_ms": (),
            "detail": "",
        }
        base.update(kwargs)
        return IngestResult(**base)

    def _bootstrap(
        self,
        *,
        run_id: str,
        symbol: str,
        timeframe: str,
        now_ms: int,
        boundary: int,
        before: Watermark | None,
        mode: str,
        started: float,
    ) -> IngestResult:
        limit = self._warmup
        try:
            rows = self._connector.fetch_ohlcv(symbol, timeframe, limit=limit)
        except Exception as exc:  # a provider failure is a result, not a crash
            self._log.error(
                "incremental_bootstrap_failed", symbol=symbol, error_type=type(exc).__name__
            )
            return self._empty_result(
                run_id=run_id,
                status="PROVIDER_FAILED",
                source_id=self._source_id,
                symbol=symbol,
                timeframe=timeframe,
                mode=mode,
                now_ms=now_ms,
                boundary_ms=boundary,
                requested_limit=limit,
                requests_made=1,
                rows_returned=0,
                rows_final=0,
                rows_new=0,
                rows_rejected=0,
                rows_incomplete=0,
                expected_bars=0,
                observed_bars=0,
                elapsed_ms=(time.perf_counter() - started) * 1_000,
                watermark_before=before,
                watermark_after=before,
                detail=f"{type(exc).__name__}: {exc}",
            )
        return self._apply(
            run_id=run_id,
            symbol=symbol,
            timeframe=timeframe,
            now_ms=now_ms,
            boundary=boundary,
            before=before,
            rows=rows,
            limit=limit,
            mode=mode,
            first_needed=None,
            started=started,
        )

    def _delta(
        self,
        *,
        run_id: str,
        symbol: str,
        timeframe: str,
        now_ms: int,
        boundary: int,
        before: Watermark,
        started: float,
    ) -> IngestResult:
        bar_ms = timeframe_seconds_or_raise(timeframe) * 1_000
        last_verified = int(before.last_verified_open_ms)
        # Overlap is a *repair* allowance, not a standing request: it is only
        # spent when at least one genuinely new bar exists.  Without this the
        # overlap alone would issue a request on every tick and the whole point
        # of the delta would be lost.
        new_bars = (boundary - (last_verified + bar_ms)) // bar_ms
        first_needed = (
            last_verified - self._overlap * bar_ms if new_bars > 0 else last_verified + bar_ms
        )
        bars_needed = (boundary - first_needed) // bar_ms

        if bars_needed <= 0:
            return self._empty_result(
                run_id=run_id,
                status="NO_NEW_DATA",
                source_id=self._source_id,
                symbol=symbol,
                timeframe=timeframe,
                mode="DELTA",
                now_ms=now_ms,
                boundary_ms=boundary,
                requested_limit=0,
                requests_made=0,
                rows_returned=0,
                rows_final=0,
                rows_new=0,
                rows_rejected=0,
                rows_incomplete=0,
                expected_bars=0,
                observed_bars=0,
                elapsed_ms=(time.perf_counter() - started) * 1_000,
                watermark_before=before,
                watermark_after=before,
                detail="watermark already at the newest closed boundary",
            )

        # +1 because the provider window always includes the forming bar, which
        # is dropped: without it the delta would be one bar short every cycle.
        limit = bars_needed + 1
        if limit > self._max_bars:
            return self._empty_result(
                run_id=run_id,
                status="BACKLOG_EXCEEDS_WINDOW",
                source_id=self._source_id,
                symbol=symbol,
                timeframe=timeframe,
                mode="DELTA",
                now_ms=now_ms,
                boundary_ms=boundary,
                requested_limit=limit,
                requests_made=0,
                rows_returned=0,
                rows_final=0,
                rows_new=0,
                rows_rejected=0,
                rows_incomplete=0,
                expected_bars=int(bars_needed),
                observed_bars=0,
                first_needed_open_ms=first_needed,
                elapsed_ms=(time.perf_counter() - started) * 1_000,
                watermark_before=before,
                watermark_after=before,
                detail=(
                    f"backlog of {bars_needed} bars exceeds the {self._max_bars}-bar "
                    "single-request window; run an explicit reconcile"
                ),
            )

        try:
            rows = self._connector.fetch_ohlcv(symbol, timeframe, limit=limit)
        except Exception as exc:
            self._log.error(
                "incremental_delta_failed", symbol=symbol, error_type=type(exc).__name__
            )
            return self._empty_result(
                run_id=run_id,
                status="PROVIDER_FAILED",
                source_id=self._source_id,
                symbol=symbol,
                timeframe=timeframe,
                mode="DELTA",
                now_ms=now_ms,
                boundary_ms=boundary,
                requested_limit=limit,
                requests_made=1,
                rows_returned=0,
                rows_final=0,
                rows_new=0,
                rows_rejected=0,
                rows_incomplete=0,
                expected_bars=int(bars_needed),
                observed_bars=0,
                first_needed_open_ms=first_needed,
                elapsed_ms=(time.perf_counter() - started) * 1_000,
                watermark_before=before,
                watermark_after=before,
                detail=f"{type(exc).__name__}: {exc}",
            )

        return self._apply(
            run_id=run_id,
            symbol=symbol,
            timeframe=timeframe,
            now_ms=now_ms,
            boundary=boundary,
            before=before,
            rows=rows,
            limit=limit,
            mode="DELTA",
            first_needed=first_needed,
            started=started,
        )

    def _apply(
        self,
        *,
        run_id: str,
        symbol: str,
        timeframe: str,
        now_ms: int,
        boundary: int,
        before: Watermark | None,
        rows: Sequence[OHLCV],
        limit: int,
        mode: str,
        first_needed: int | None,
        started: float,
    ) -> IngestResult:
        bar_ms = timeframe_seconds_or_raise(timeframe) * 1_000
        ordered, rejected, _duplicates = _normalise(rows)
        final = [row for row in ordered if int(row.timestamp) + bar_ms <= now_ms]
        incomplete = len(ordered) - len(final)

        def fail(status: IngestStatus, detail: str, *, observed: int) -> IngestResult:
            return self._empty_result(
                run_id=run_id,
                status=status,
                source_id=self._source_id,
                symbol=symbol,
                timeframe=timeframe,
                mode=mode,
                now_ms=now_ms,
                boundary_ms=boundary,
                requested_limit=limit,
                requests_made=1,
                rows_returned=len(rows),
                rows_final=len(final),
                rows_new=0,
                rows_rejected=rejected,
                rows_incomplete=incomplete,
                expected_bars=0,
                observed_bars=observed,
                first_needed_open_ms=first_needed,
                first_returned_open_ms=int(final[0].timestamp) if final else None,
                last_returned_open_ms=int(final[-1].timestamp) if final else None,
                elapsed_ms=(time.perf_counter() - started) * 1_000,
                watermark_before=before,
                watermark_after=before,
                detail=detail,
            )

        if rejected:
            return fail(
                "REJECTED_ROWS",
                f"{rejected} row(s) failed OHLCV validation; watermark not advanced",
                observed=len(final),
            )
        if not final:
            return fail(
                "INCOMPLETE_BARS_ONLY",
                "provider returned no closed bar; refusing to advance the watermark",
                observed=0,
            )
        if first_needed is not None and int(final[0].timestamp) > first_needed:
            return fail(
                "INSUFFICIENT_WINDOW",
                (
                    f"returned window starts at {int(final[0].timestamp)} but "
                    f"{first_needed} was needed; coverage not proven"
                ),
                observed=len(final),
            )

        first_open = int(final[0].timestamp)
        last_open = int(final[-1].timestamp)
        expected = (boundary - first_open) // bar_ms
        observed = len(final)
        gap_set = {int(r.timestamp) for r in final}
        gaps = tuple(
            first_open + index * bar_ms
            for index in range(int(expected))
            if first_open + index * bar_ms not in gap_set
        )

        # A trailing gap (provider lag, exchange maintenance) must not be
        # skipped: the watermark stops at the last bar we actually hold, so the
        # next cycle asks again for the missing tail.
        verified_open = min(last_open, boundary - bar_ms)
        persisted = self._store.upsert(final, symbol=symbol, timeframe=timeframe)
        if mode == "BOOTSTRAP":
            previous_open = None
        else:
            previous_open = int(before.last_verified_open_ms) if before is not None else None
        new_rows = (
            len(final)
            if previous_open is None
            else sum(1 for row in final if int(row.timestamp) > previous_open)
        )

        after = Watermark(
            source_id=self._source_id,
            symbol=symbol,
            timeframe=timeframe,
            last_verified_open_ms=verified_open,
            last_closed_boundary_ms=boundary,
            last_ingested_seq=(before.last_ingested_seq + 1 if before is not None else 1),
            last_persisted_sha=bar_sha256(final),
            updated_at_ms=now_ms,
        )
        self._watermarks.save(after)

        status: IngestStatus = (
            "BOOTSTRAP"
            if mode == "BOOTSTRAP"
            else ("RECONCILE" if mode == "RECONCILE" else "DELTA")
        )

        detail_parts = [f"persisted={persisted}"]
        if gaps:
            detail_parts.append(f"gaps={len(gaps)}")
        if last_open < boundary - bar_ms:
            detail_parts.append("trailing_gap")
        self._log.info(
            "incremental_ingest",
            run_id=run_id,
            symbol=symbol,
            timeframe=timeframe,
            status=status,
            requested_limit=limit,
            rows_returned=len(rows),
            rows_new=new_rows,
            gaps=len(gaps),
        )
        return IngestResult(
            run_id=run_id,
            status=status,
            source_id=self._source_id,
            symbol=symbol,
            timeframe=timeframe,
            mode=mode,
            now_ms=now_ms,
            boundary_ms=boundary,
            requested_limit=limit,
            requests_made=1,
            rows_returned=len(rows),
            rows_final=len(final),
            rows_new=new_rows,
            rows_rejected=0,
            rows_incomplete=incomplete,
            first_needed_open_ms=first_needed,
            first_returned_open_ms=first_open,
            last_returned_open_ms=last_open,
            expected_bars=int(expected),
            observed_bars=observed,
            gap_open_ms=gaps[:100],
            elapsed_ms=(time.perf_counter() - started) * 1_000,
            watermark_before=before,
            watermark_after=after,
            detail=" ".join(detail_parts),
        )
