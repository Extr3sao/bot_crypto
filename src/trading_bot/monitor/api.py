"""Read-only HTTP API + SSE stream for the Trading Decision Monitor.

Stack: Python standard library ``http.server`` — the same precedent the repository
already uses (``src/trading_bot/app.py``, ``scripts/strategy_ecosystem_dashboard.py``).
No FastAPI/Flask/React/Vite is introduced (RFC §2.5, REQ-TDM-014).

Guarantees:

* **Read-only by construction.** Only ``GET`` and ``HEAD`` are implemented; every
  other method is answered ``405`` with an ``Allow`` header. There is no handler
  that could mutate risk, sizing, strategies or credentials, and no code path
  imports a broker.
* **No fabrications.** Missing artifacts produce an explicit error or a
  ``NOT_RECORDED`` field — never a synthetic event.
* **Point-in-time.** ``/candles`` accepts ``as_of`` and drops bars that close
  after the decision instant.
* **Honest liveness.** ``connection_state`` is derived from the producing run's
  heartbeat; it can say ``DELAYED``/``DISCONNECTED`` but never claims ``LIVE_DATA``
  without a fresh heartbeat.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import defaultdict
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, Thread
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from trading_bot import __version__

from .candles import (
    MAX_BARS_PER_REQUEST,
    CandleSource,
    CandleUnavailable,
    CcxtCandleSource,
    validate_timeframe,
)
from .contracts import ConnectionState, TradingDecisionEventV1
from .projector import (
    ArtifactError,
    RunArtifacts,
    RunProjection,
    discover_runs,
    load_run,
    project_run,
)

__all__ = [
    "API_VERSION",
    "MonitorApp",
    "MonitorConfig",
    "build_server",
    "main",
]

API_VERSION = "tdm-api-v1"
STATIC_DIR = Path(__file__).resolve().parent / "static"

#: Heartbeat age thresholds for the connection state (milliseconds).
LIVE_MAX_AGE_MS = 120_000
DISCONNECT_AFTER_MS = 300_000

#: Pagination caps.
MAX_PAGE_LIMIT = 500
DEFAULT_PAGE_LIMIT = 100

#: Very small in-memory rate limiter (read-only API, single user, loopback).
RATE_WINDOW_SECONDS = 10.0
RATE_MAX_REQUESTS = 240

_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,16}/[A-Z0-9]{2,10}$")
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/vendor/lightweight-charts.standalone.production.js": (
        "vendor/lightweight-charts.standalone.production.js",
        "text/javascript; charset=utf-8",
    ),
}

_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "font-src 'self'; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "form-action 'none'; "
    "frame-ancestors 'none'"
)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000.0, tz=UTC).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


@dataclass(slots=True)
class MonitorConfig:
    """Everything the app needs; nothing it doesn't."""

    runs_root: Path
    candle_source: CandleSource | None = None
    exchange_id: str = "binance"
    replay_as_of_ms: int | None = None
    fixture_mode: bool = False
    static_dir: Path = STATIC_DIR
    read_only_notice: str = (
        "Vista de solo lectura sobre evidencia PAPER. No envía órdenes, no modifica "
        "riesgo, sizing ni estrategias."
    )

    def resolved_candle_source(self) -> CandleSource:
        if self.candle_source is None:
            self.candle_source = CcxtCandleSource(exchange_id=self.exchange_id)
        return self.candle_source


@dataclass(slots=True)
class RunCache:
    """Caches one projection until its artifacts change on disk."""

    run_dir: Path
    signature: tuple[Any, ...] = ()
    artifacts: RunArtifacts | None = None
    projection: RunProjection | None = None


@dataclass(slots=True)
class MonitorApp:
    """Query layer shared by every request. Thread-safe by a single lock."""

    config: MonitorConfig
    started_at_ms: int = field(default_factory=_now_ms)
    _cache: dict[str, RunCache] = field(default_factory=dict, repr=False)
    _lock: Lock = field(default_factory=Lock, repr=False)
    _rate: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list), repr=False)
    _asset_digests: dict[str, str] = field(default_factory=dict, repr=False)

    # -- infrastructure -----------------------------------------------------

    def _signature(self, run_dir: Path) -> tuple[Any, ...]:
        parts: list[Any] = []
        for name in ("traces.jsonl", "RUN_REPORT.json", "PAPER_RUN.json", "heartbeat.json"):
            path = run_dir / name
            try:
                stat = path.stat()
            except OSError:
                parts.append(None)
                continue
            parts.append((stat.st_size, stat.st_mtime_ns))
        return tuple(parts)

    def projection_for(self, run_dir: Path) -> RunProjection:
        key = str(run_dir.resolve())
        signature = self._signature(run_dir)
        with self._lock:
            cached = self._cache.get(key)
            if cached and cached.signature == signature:
                assert cached.projection is not None
                return cached.projection
        artifacts = load_run(run_dir)
        projection = project_run(artifacts)
        with self._lock:
            self._cache[key] = RunCache(
                run_dir=run_dir,
                signature=signature,
                artifacts=artifacts,
                projection=projection,
            )
        return projection

    def artifacts_for(self, run_dir: Path) -> RunArtifacts:
        self.projection_for(run_dir)
        with self._lock:
            cached = self._cache[str(run_dir.resolve())]
            assert cached.artifacts is not None
            return cached.artifacts

    def run_dirs(self) -> list[Path]:
        return discover_runs(self.config.runs_root)

    def resolve_run(self, run_id: str | None) -> Path:
        if not run_id:
            dirs = self.run_dirs()
            if not dirs:
                raise LookupError("no PAPER runs found under the configured root")
            return dirs[0]
        if not _RUN_ID_RE.match(run_id):
            raise ValueError("invalid run_id")
        for candidate in self.run_dirs():
            if candidate.name == run_id:
                return candidate
        raise LookupError(f"run {run_id!r} not found")

    def rate_limited(self, client: str) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = [t for t in self._rate[client] if now - t < RATE_WINDOW_SECONDS]
            hits.append(now)
            self._rate[client] = hits
            return len(hits) > RATE_MAX_REQUESTS

    # -- derived state ------------------------------------------------------

    def connection_state(self, run_dir: Path) -> dict[str, Any]:
        """Liveness of the *producing process*, never an assumption."""
        try:
            artifacts = load_run(run_dir)
        except ArtifactError:
            artifacts = None
        # A run whose own report says it was produced by the fake provider can
        # never be presented as live venue data, whatever its heartbeat says.
        environment = str(artifacts.environment if artifacts else "").lower()
        synthetic = self.config.fixture_mode or environment.startswith("fake")
        if synthetic:
            state = ConnectionState.SIMULATED_FIXTURE
            reason = (
                "run built from test fixtures"
                if self.config.fixture_mode
                else f"run report declares environment={environment!r}"
            )
        elif self.config.replay_as_of_ms is not None:
            state = ConnectionState.REPLAY
            reason = "replay clock pinned with as_of"
        else:
            state, reason = ConnectionState.DISCONNECTED, "no heartbeat artifact"
            heartbeat = artifacts.heartbeat if artifacts else None
            if heartbeat:
                stamp = heartbeat.get("timestamp_ms")
                if isinstance(stamp, (int, float)):
                    age = _now_ms() - int(stamp)
                    if age > DISCONNECT_AFTER_MS:
                        state, reason = (
                            ConnectionState.DISCONNECTED,
                            f"last heartbeat {age // 1000}s old",
                        )
                    elif age > LIVE_MAX_AGE_MS:
                        state, reason = (
                            ConnectionState.DELAYED,
                            f"last heartbeat {age // 1000}s old",
                        )
                    else:
                        state, reason = ConnectionState.LIVE_DATA, "heartbeat fresh"
                else:
                    state, reason = ConnectionState.DELAYED, "heartbeat has no timestamp"
            elif artifacts is not None:
                state, reason = ConnectionState.DELAYED, "run has traces but no heartbeat"

        events: tuple[TradingDecisionEventV1, ...] = ()
        with suppress(ArtifactError, LookupError):
            events = self.projection_for(run_dir).events
        last_emitted = max((e.decision_time_ms for e in events), default=None)
        return {
            "connection_state": state.value,
            "connection_reason": reason,
            "last_sequence": max((e.sequence for e in events), default=0),
            "last_event_ms": last_emitted,
            "data_age_ms": None if last_emitted is None else max(0, _now_ms() - last_emitted),
            "as_of": _iso(self.config.replay_as_of_ms)
            if self.config.replay_as_of_ms is not None
            else None,
        }

    def events(self, run_dir: Path) -> tuple[TradingDecisionEventV1, ...]:
        events = self.projection_for(run_dir).events
        as_of = self.config.replay_as_of_ms
        if as_of is None:
            return events
        return tuple(e for e in events if e.decision_time_ms <= as_of)

    # -- query operations ---------------------------------------------------

    def health(self) -> dict[str, Any]:
        runs: list[dict[str, Any]] = []
        for run_dir in self.run_dirs():
            try:
                projection = self.projection_for(run_dir)
            except ArtifactError as exc:
                runs.append({"run_id": run_dir.name, "error": str(exc)})
                continue
            state = self.connection_state(run_dir)
            runs.append(
                {
                    "run_id": projection.run_id,
                    "event_count": len(projection.events),
                    "chain_ok": projection.chain.get("ok"),
                    "invalid_records": projection.invalid_records,
                    "mode": projection.mode,
                    "venue": projection.venue,
                    "timeframe": projection.timeframe,
                    "connection_state": state["connection_state"],
                    "connection_reason": state["connection_reason"],
                    "last_sequence": state["last_sequence"],
                }
            )
        return {
            "schema": API_VERSION,
            "status": "ok" if runs else "no_runs",
            "version": __version__,
            "uptime_seconds": round((_now_ms() - self.started_at_ms) / 1000.0, 3),
            "generated_at": _iso(_now_ms()),
            "read_only": True,
            "notice": self.config.read_only_notice,
            "runs_root": str(self.config.runs_root),
            "runs": runs,
            "candle_source": getattr(
                self.config.candle_source, "name", self.config.exchange_id
            ),
            "asset_digests": self.asset_digests(),
            "rate_limit": {"window_seconds": RATE_WINDOW_SECONDS, "max_requests": RATE_MAX_REQUESTS},
        }

    def asset_digests(self) -> dict[str, str]:
        if self._asset_digests:
            return dict(self._asset_digests)
        digests: dict[str, str] = {}
        for relative in sorted({v[0] for v in _STATIC_FILES.values()}):
            path = self.config.static_dir / relative
            try:
                digests[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                continue
        self._asset_digests = digests
        return dict(digests)

    def assets(self, run_id: str | None = None) -> dict[str, Any]:
        run_dir = self.resolve_run(run_id)
        projection = self.projection_for(run_dir)
        events = self.events(run_dir)
        symbols = sorted({e.symbol for e in events if e.symbol})
        strategies = sorted({e.strategy_id for e in events if e.strategy_id})
        timeframes = sorted({e.timeframe for e in events if e.timeframe})
        # Only *decision-level* states are offered as filters. An intermediate
        # state (e.g. ``SIGNAL_ONLY`` from a signal event) is not something a
        # decision can be filtered by, and offering it would return zero rows.
        terminal: dict[str, TradingDecisionEventV1] = {}
        for event in events:
            current = terminal.get(event.decision_id)
            if current is None or event.sequence > current.sequence:
                terminal[event.decision_id] = event
        return {
            "run_id": projection.run_id,
            "venue": projection.venue,
            "symbols": symbols,
            "timeframes": timeframes,
            "strategies": strategies,
            "statuses": sorted({e.decision_status.value for e in terminal.values()}),
            "modes": sorted({e.mode for e in events}),
            "decision_ids": sorted({e.decision_id for e in events}),
            "time_range": {
                "from": _iso(min((e.decision_time_ms for e in events), default=0)) if events else None,
                "to": _iso(max((e.decision_time_ms for e in events), default=0)) if events else None,
            },
        }

    def decisions(
        self,
        *,
        run_id: str | None,
        symbol: str | None,
        status: str | None,
        strategy: str | None,
        cursor: int,
        limit: int,
    ) -> dict[str, Any]:
        run_dir = self.resolve_run(run_id)
        projection = self.projection_for(run_dir)
        events = self.events(run_dir)
        if cursor > max((e.sequence for e in events), default=0):
            raise ValueError("cursor beyond the last available sequence")

        grouped: dict[str, list[TradingDecisionEventV1]] = defaultdict(list)
        for event in events:
            grouped[event.decision_id].append(event)

        rows: list[dict[str, Any]] = []
        for decision_id, group in grouped.items():
            group.sort(key=lambda e: e.sequence)
            terminal = group[-1]
            if symbol and terminal.symbol != symbol:
                continue
            if status and terminal.decision_status.value != status:
                continue
            if strategy and terminal.strategy_id != strategy:
                continue
            rows.append(
                {
                    "decision_id": decision_id,
                    "run_id": terminal.run_id,
                    "symbol": terminal.symbol,
                    "venue": terminal.venue,
                    "timeframe": terminal.timeframe,
                    "mode": terminal.mode,
                    "strategy_id": terminal.strategy_id,
                    "signal_direction": terminal.signal_direction,
                    "decision_time": terminal.decision_time,
                    "decision_time_ms": terminal.decision_time_ms,
                    "observed_market_time": terminal.observed_market_time,
                    "status": terminal.decision_status.value,
                    "status_label": terminal.to_dict()["decision_status_label"],
                    "event_type": terminal.event_type.value,
                    "reason_summary": terminal.reason_summary,
                    "reason_codes": [r.code for r in terminal.reason_codes][:6],
                    "severity": terminal.severity,
                    "price_observed": terminal.price_observed,
                    "verification": terminal.verification,
                    "risk_gate": terminal.risk_gate,
                    "has_fill": any(
                        e.event_type.value == "ORDER_FILLED" for e in group
                    ),
                    "first_sequence": group[0].sequence,
                    "last_sequence": terminal.sequence,
                    "event_count": len(group),
                }
            )

        rows.sort(key=lambda r: (r["decision_time_ms"], r["last_sequence"]))
        # ``total_matching`` counts every decision that matches the filters, not
        # just the ones left after the cursor: otherwise the number shrinks page
        # by page and a client cannot tell a complete read from a truncated one.
        total = len(rows)
        remaining = [row for row in rows if row["last_sequence"] > cursor]
        page = remaining[: max(1, min(limit, MAX_PAGE_LIMIT))]
        next_cursor = page[-1]["last_sequence"] if page else cursor
        state = self.connection_state(run_dir)
        return {
            "schema": API_VERSION,
            "run_id": projection.run_id,
            "items": page,
            "count": len(page),
            "total_matching": total,
            "next_cursor": next_cursor,
            # Read from the remaining slice: comparing with ``total`` would keep
            # ``has_more`` true after the last page and send a client in circles.
            "has_more": len(remaining) > len(page),
            "snapshot_sequence": state["last_sequence"],
            "generated_at": _iso(_now_ms()),
            **state,
        }

    def decision_detail(self, decision_id: str, *, run_id: str | None) -> dict[str, Any]:
        run_dir = self.resolve_run(run_id)
        events = self.events(run_dir)
        group = [e for e in events if e.decision_id == decision_id]
        if not group:
            raise LookupError(f"decision {decision_id!r} not found in run")
        group.sort(key=lambda e: e.sequence)
        terminal = group[-1]
        trace = self._trace_evidence(run_dir, decision_id)
        return {
            "schema": API_VERSION,
            "run_id": terminal.run_id,
            "decision_id": decision_id,
            "terminal_status": terminal.decision_status.value,
            "status_label": terminal.to_dict()["decision_status_label"],
            "events": [e.to_dict() for e in group],
            "trace": trace,
            "not_recorded": _not_recorded_fields(terminal),
        }

    def _trace_evidence(self, run_dir: Path, decision_id: str) -> dict[str, Any]:
        """The persisted trace + its replay, or an explicit NOT_RECORDED."""
        artifacts = self.artifacts_for(run_dir)
        for row in artifacts.rows:
            if row.trace is None or row.trace.decision_id != decision_id:
                continue
            replay: dict[str, Any]
            try:
                from trading_bot.autonomous.trace import DecisionTraceStore

                store = DecisionTraceStore(run_dir)
                replay = store.replay(decision_id).to_dict()
            except Exception as exc:  # replay failure is reported, never hidden
                replay = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            return {
                "recorded": True,
                "sequence": row.trace.sequence,
                "trace_hash": row.trace.trace_hash,
                "chain_ok": row.chain_ok,
                "trace": row.trace.to_dict(),
                "replay": replay,
            }
        return {"recorded": False, "reason": "NOT_RECORDED"}

    def run_trace(self, run_id: str | None) -> dict[str, Any]:
        run_dir = self.resolve_run(run_id)
        artifacts = self.artifacts_for(run_dir)
        projection = self.projection_for(run_dir)
        counts = _counters(artifacts, projection)
        decisions = []
        for row in artifacts.rows:
            trace = row.trace
            decisions.append(
                {
                    "decision_id": None if trace is None else trace.decision_id,
                    "sequence": None if trace is None else trace.sequence,
                    "mode": None if trace is None else trace.mode.value,
                    "classification": None if trace is None else trace.classification,
                    "no_trade_kind": None if trace is None else trace.no_trade_kind,
                    "decision_time": None
                    if trace is None
                    else _iso(trace.decision_time_ms),
                    "order_created": None if trace is None else trace.order_created,
                    "trace_hash": None if trace is None else trace.trace_hash,
                    "chain_ok": row.chain_ok,
                    "record_error": row.error,
                }
            )
        return {
            "schema": API_VERSION,
            "run_id": projection.run_id,
            "runtime_run_id": artifacts.runtime_run_id,
            "run_id_mismatch": artifacts.runtime_run_id != artifacts.run_id,
            "chain": projection.chain,
            "invalid_records": projection.invalid_records,
            "duplicate_decision_ids": list(projection.duplicate_decision_ids),
            "artifact_digests": projection.artifact_digests,
            "venue": projection.venue,
            "timeframe": projection.timeframe,
            "mode": projection.mode,
            "commit": projection.commit,
            "counters": counts,
            "last_observable_step": _last_step(projection),
            "decisions": decisions,
            "not_recorded": [
                "ORDER_SUBMITTED",
                "POSITION_CLOSED",
                "UNDER_REVIEW",
            ],
            "not_recorded_reason": (
                "El runtime PAPER no persiste estos eventos; el monitor no los infiere "
                "(GAP-TDM-01/03/04)."
            ),
        }

    def candles(
        self,
        *,
        symbol: str,
        timeframe: str,
        start_ms: int | None,
        end_ms: int | None,
        limit: int,
        as_of_ms: int | None,
    ) -> dict[str, Any]:
        if not _SYMBOL_RE.match(symbol):
            raise ValueError("invalid symbol; expected BASE/QUOTE in upper case")
        validate_timeframe(timeframe)
        limit = max(1, min(limit, MAX_BARS_PER_REQUEST))
        source = self.config.resolved_candle_source()
        bars = source.fetch(
            symbol=symbol,
            timeframe=timeframe,
            start_ms=start_ms,
            end_ms=end_ms,
            limit=limit,
            as_of_ms=as_of_ms,
        )
        return {
            "schema": API_VERSION,
            "symbol": symbol,
            "timeframe": timeframe,
            "source": getattr(source, "name", "unknown"),
            "as_of": _iso(as_of_ms) if as_of_ms is not None else None,
            "bars": [b.to_dict() for b in bars],
            "count": len(bars),
            # a fixture source can never be presented as live venue data
            "fixture": bool(self.config.fixture_mode or getattr(source, "fixture", False)),
            "generated_at": _iso(_now_ms()),
        }


def _counters(artifacts: RunArtifacts, projection: RunProjection) -> dict[str, Any]:
    """Funnel counters derived from the events, plus what the runtime itself said.

    ``order_submitted`` is always ``None`` because the runtime does not persist
    that step (GAP-TDM-01): the UI shows ``NOT_RECORDED`` instead of a zero that
    would read like "no orders were submitted".
    """
    events = projection.events
    by_type: dict[str, int] = defaultdict(int)
    by_status: dict[str, int] = defaultdict(int)
    for event in events:
        by_type[event.event_type.value] += 1
        by_status[event.decision_status.value] += 1
    decisions = {e.decision_id for e in events}
    considered: list[tuple[str, bool]] = [
        (str(row.get("strategy_id")), bool(row.get("emitted_alpha")))
        for artifact_row in artifacts.rows
        if artifact_row.trace is not None
        for row in artifact_row.trace.strategies_considered
    ]
    return {
        "candles_received": None,  # not persisted by the runtime (GAP-TDM-05)
        "strategies_distinct": len({sid for sid, _ in considered}),
        "strategy_evaluations": len(considered),
        "signals": by_type.get("SIGNAL_DETECTED", 0),
        "proposals": by_type.get("PROPOSAL_CREATED", 0),
        "decisions": len(decisions),
        "no_trade": by_status.get("NO_TRADE", 0),
        "shadow": by_status.get("SHADOW_OBSERVED", 0),
        "accepted_not_executed": by_status.get("ACCEPTED_NOT_EXECUTED", 0),
        "executed_paper": by_status.get("EXECUTED_PAPER", 0),
        "execution_failed": by_status.get("EXECUTION_FAILED", 0),
        "order_submitted": None,
        "fills": by_type.get("ORDER_FILLED", 0),
        "pipeline_errors": by_type.get("PIPELINE_ERROR", 0),
        "events": len(events),
        "by_type": dict(by_type),
    }


def _last_step(projection: RunProjection) -> dict[str, Any] | None:
    """The last thing that demonstrably happened, in plain words."""
    if not projection.events:
        return None
    last = max(projection.events, key=lambda e: e.sequence)
    return {
        "sequence": last.sequence,
        "event_type": last.event_type.value,
        "decision_id": last.decision_id,
        "symbol": last.symbol,
        "at": last.decision_time,
        "text": f"{last.to_dict()['event_label']} · {last.symbol} · {last.reason_summary}",
    }


def _not_recorded_fields(event: TradingDecisionEventV1) -> list[dict[str, str]]:
    """What the drilldown must label ``NOT_RECORDED`` instead of inventing."""
    fields = [
        {
            "field": "order_id",
            "status": "NOT_RECORDED",
            "reason": "el runtime no persiste un identificador de orden de exchange",
        },
        {
            "field": "fill_price",
            "status": "NOT_RECORDED",
            "reason": "executions[] no incluye precio de fill",
        },
        {
            "field": "position_close",
            "status": "NOT_RECORDED",
            "reason": "no se persiste evento de cierre/reconciliación",
        },
        {
            "field": "under_review",
            "status": "NOT_RECORDED",
            "reason": "no se persisten transiciones de revisión",
        },
    ]
    if event.decision_status.value == "ACCEPTED_NOT_EXECUTED":
        fields.append(
            {
                "field": "order_submitted",
                "status": "NOT_RECORDED",
                "reason": "el envío de la orden no se distingue del fill (GAP-TDM-01)",
            }
        )
    return fields


# ---------------------------------------------------------------------------
# HTTP plumbing
# ---------------------------------------------------------------------------


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "TDM/1.0"
    app: MonitorApp  # injected by build_server

    # -- helpers ------------------------------------------------------------

    def log_message(self, format: str, *args: object) -> None:
        return  # keep the console quiet; the app logs its own summary

    def _security_headers(self) -> None:
        self.send_header("Content-Security-Policy", _CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")

    def _send_json(self, status: int, payload: dict[str, Any], *, cache: str = "no-store") -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=None).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self._security_headers()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _error(self, status: int, code: str, message: str) -> None:
        self._send_json(status, {"error": {"code": code, "message": message}})

    def _query(self) -> dict[str, str]:
        parsed = parse_qs(urlparse(self.path).query, keep_blank_values=True)
        return {key: values[-1] for key, values in parsed.items() if values}

    def _int_param(self, query: dict[str, str], name: str, default: int | None = None) -> int | None:
        raw = query.get(name)
        if raw is None or raw == "":
            return default
        try:
            value = int(raw)
        except ValueError as exc:
            raise ValueError(f"{name} must be an integer") from exc
        if value < 0:
            raise ValueError(f"{name} must be >= 0")
        return value

    def _method_not_allowed(self) -> None:
        body = json.dumps(
            {
                "error": {
                    "code": "READ_ONLY",
                    "message": "This monitor is read-only: only GET and HEAD are supported.",
                }
            }
        ).encode("utf-8")
        self.send_response(405)
        self.send_header("Allow", "GET, HEAD")
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._security_headers()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    # -- verbs --------------------------------------------------------------

    def do_POST(self) -> None:
        self._method_not_allowed()

    def do_PUT(self) -> None:
        self._method_not_allowed()

    def do_PATCH(self) -> None:
        self._method_not_allowed()

    def do_DELETE(self) -> None:
        self._method_not_allowed()

    def do_OPTIONS(self) -> None:
        self._method_not_allowed()

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        client = self.client_address[0] if self.client_address else "unknown"
        if self.app.rate_limited(client):
            self._error(429, "RATE_LIMITED", "too many requests")
            return
        path = unquote(urlparse(self.path).path)
        try:
            if path in _STATIC_FILES:
                self._serve_static(path)
                return
            if path.startswith("/api/monitor/"):
                self._serve_api(path)
                return
            self._error(404, "NOT_FOUND", f"no route for {path}")
        except ValueError as exc:
            self._error(400, "BAD_REQUEST", str(exc))
        except LookupError as exc:
            self._error(404, "NOT_FOUND", str(exc))
        except CandleUnavailable as exc:
            self._error(503, "CANDLES_UNAVAILABLE", str(exc))
        except ArtifactError as exc:
            self._error(503, "ARTIFACT_UNAVAILABLE", str(exc))
        except (BrokenPipeError, ConnectionResetError):  # client went away mid-response
            return
        except Exception as exc:  # never leak a traceback to the browser
            self._error(500, "INTERNAL_ERROR", f"{type(exc).__name__}")

    # -- static -------------------------------------------------------------

    def _serve_static(self, path: str) -> None:
        relative, content_type = _STATIC_FILES[path]
        target = (self.app.config.static_dir / relative).resolve()
        static_root = self.app.config.static_dir.resolve()
        if not str(target).startswith(str(static_root)):  # path traversal guard
            self._error(403, "FORBIDDEN", "path outside the static root")
            return
        try:
            body = target.read_bytes()
        except OSError:
            self._error(404, "NOT_FOUND", f"{relative} is not present")
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self._security_headers()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    # -- api ----------------------------------------------------------------

    def _serve_api(self, path: str) -> None:
        query = self._query()
        app = self.app

        if path == "/api/monitor/health":
            self._send_json(200, app.health())
            return

        if path == "/api/monitor/runs":
            self._send_json(
                200,
                {
                    "schema": API_VERSION,
                    "runs": [
                        {
                            "run_id": d.name,
                            "path": str(d),
                            "modified_ms": int(d.stat().st_mtime * 1000),
                        }
                        for d in app.run_dirs()
                    ],
                },
            )
            return

        if path == "/api/monitor/assets":
            self._send_json(200, app.assets(query.get("run_id")))
            return

        if path == "/api/monitor/candles":
            symbol = (query.get("symbol") or "").strip().upper()
            timeframe = (query.get("timeframe") or "5m").strip()
            self._send_json(
                200,
                app.candles(
                    symbol=symbol,
                    timeframe=timeframe,
                    start_ms=self._int_param(query, "from"),
                    end_ms=self._int_param(query, "to"),
                    limit=self._int_param(query, "limit", 500) or 500,
                    as_of_ms=self._int_param(query, "as_of"),
                ),
            )
            return

        if path == "/api/monitor/decisions":
            self._send_json(
                200,
                app.decisions(
                    run_id=query.get("run_id"),
                    symbol=(query.get("symbol") or "").upper() or None,
                    status=(query.get("status") or "").upper() or None,
                    strategy=query.get("strategy"),
                    cursor=self._int_param(query, "cursor", 0) or 0,
                    limit=self._int_param(query, "limit", DEFAULT_PAGE_LIMIT) or DEFAULT_PAGE_LIMIT,
                ),
            )
            return

        if path.startswith("/api/monitor/decisions/"):
            decision_id = path.rsplit("/", 1)[-1]
            if not decision_id:
                raise ValueError("decision_id is required")
            self._send_json(
                200, app.decision_detail(decision_id, run_id=query.get("run_id"))
            )
            return

        if path.startswith("/api/monitor/runs/") and path.endswith("/trace"):
            run_id = path[len("/api/monitor/runs/") : -len("/trace")]
            self._send_json(200, app.run_trace(run_id or None))
            return

        if path == "/api/monitor/events/stream":
            self._stream(query)
            return

        raise LookupError(f"no route for {path}")

    # -- SSE ----------------------------------------------------------------

    def _stream(self, query: dict[str, str]) -> None:
        run_dir = self.app.resolve_run(query.get("run_id"))
        cursor = self._int_param(query, "cursor", 0) or 0
        projection = self.app.projection_for(run_dir)
        max_sequence = max((e.sequence for e in projection.events), default=0)
        if cursor > max_sequence:
            raise ValueError("cursor beyond the last available sequence")

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self._security_headers()
        self.end_headers()
        self.close_connection = True
        if self.command == "HEAD":
            return

        def write(chunk: str) -> None:
            self.wfile.write(chunk.encode("utf-8"))
            self.wfile.flush()

        try:
            write("retry: 2000\n\n")
            state = self.app.connection_state(run_dir)
            write(
                "event: snapshot\ndata: "
                + json.dumps(
                    {
                        "run_id": projection.run_id,
                        "snapshot_sequence": max_sequence,
                        "cursor": cursor,
                        **state,
                    },
                    ensure_ascii=False,
                )
                + "\n\n"
            )
            last_heartbeat = time.monotonic()
            while True:
                events = self.app.events(run_dir)
                pending = [e for e in events if e.sequence > cursor]
                for event in pending:
                    cursor = event.sequence
                    write(f"id: {cursor}\ndata: {json.dumps(event.to_dict(), ensure_ascii=False)}\n\n")
                if time.monotonic() - last_heartbeat >= 15:
                    last_heartbeat = time.monotonic()
                    state = self.app.connection_state(run_dir)
                    write(
                        "event: heartbeat\ndata: "
                        + json.dumps(
                            {"last_sequence": cursor, **state}, ensure_ascii=False
                        )
                        + "\n\n"
                    )
                time.sleep(1.0)
        except (BrokenPipeError, ConnectionResetError):
            return


class _Server(ThreadingHTTPServer):
    """Threaded server that refuses to share its port.

    ``allow_reuse_address`` is disabled on Windows: there it lets a second
    process bind the same port silently, so a stale monitor keeps answering and
    the freshly started one is never reached (observed during WP-TDM-03).
    """

    daemon_threads = True
    allow_reuse_address = __import__("os").name != "nt"


def build_server(
    config: MonitorConfig, *, host: str = "127.0.0.1", port: int = 8770
) -> tuple[ThreadingHTTPServer, MonitorApp]:
    """Create (but do not start) the read-only server."""
    app = MonitorApp(config=config)
    handler = type("TDMHandler", (_Handler,), {"app": app})
    server = _Server((host, port), handler)
    server.daemon_threads = True
    return server, app


def serve(config: MonitorConfig, *, host: str = "127.0.0.1", port: int = 8770) -> None:
    server, _app = build_server(config, host=host, port=port)
    bound_host, bound_port = server.server_address[:2]
    # ``server_address`` is typed as ``str | bytes`` for the host component.
    host_label = bound_host.decode() if isinstance(bound_host, bytes) else bound_host
    print(f"[tdm] read-only monitor en http://{host_label}:{bound_port}")
    print(f"[tdm] runs root: {config.runs_root}")
    print(f"[tdm] candle source: {getattr(config.candle_source, 'name', config.exchange_id)}")
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\n[tdm] parada manual; cerrando servidor.")
    finally:
        server.shutdown()
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Trading Decision Monitor (read-only, PAPER)")
    parser.add_argument("--runs-root", default="reports/autonomous-paper")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument("--exchange", default="binance")
    parser.add_argument("--as-of", type=int, default=None, help="replay clock (epoch ms)")
    parser.add_argument(
        "--fixture",
        action="store_true",
        help="declare the run root as synthetic so the UI never shows it as live",
    )
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help="permit binding to a non-loopback address (off by default)",
    )
    args = parser.parse_args(argv)
    loopback = args.host.startswith("127.") or args.host in {"localhost", "::1"}
    if not loopback and not args.allow_remote:
        print(
            "[tdm] refusing to bind a non-loopback address without --allow-remote",
            file=__import__("sys").stderr,
        )
        return 2
    config = MonitorConfig(
        runs_root=Path(args.runs_root),
        exchange_id=args.exchange,
        replay_as_of_ms=args.as_of,
        fixture_mode=args.fixture,
    )
    serve(config, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
