"""GET-only local PAPER observability server with an SSE event stream."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .events import DashboardEventBus
from .projection import DashboardStore

_HTML = (Path(__file__).parent / "dashboard.html").read_text(encoding="utf-8")


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class PaperDashboardServer:
    """Local read-only REST/SSE projection; it has no trading command route."""

    def __init__(
        self,
        *,
        store: DashboardStore,
        bus: DashboardEventBus | None = None,
        orchestrator: Any | None = None,
        broker: Any | None = None,
        host: str = "127.0.0.1",
        port: int = 8000,
    ) -> None:
        self._store, self._bus = store, bus
        self._orchestrator, self._broker = orchestrator, broker
        self._host, self._port = host, port
        self._server: _Server | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    @property
    def url(self) -> str:
        port = self._server.server_address[1] if self._server else self._port
        return f"http://{self._host}:{port}"

    def start(self) -> str:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _fmt: str, *_args: object) -> None:
                return

            def _json(self, data: object, status: int = 200) -> None:
                body = json.dumps(data, ensure_ascii=False, default=str).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def _method_not_allowed(self) -> None:
                self._json({"error": "read-only dashboard: method not allowed"}, 405)

            do_POST = _method_not_allowed
            do_PUT = _method_not_allowed
            do_PATCH = _method_not_allowed
            do_DELETE = _method_not_allowed

            def _sse(self) -> None:
                if owner._bus is None:
                    self._json({"error": "event bus not configured"}, 503)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                queue = owner._bus.subscribe()
                try:
                    self.wfile.write(b": connected\n\n")
                    self.wfile.flush()
                    while not owner._stop.is_set():
                        try:
                            event = queue.popleft()
                        except IndexError:
                            self.wfile.write(b": ping\n\n")
                            self.wfile.flush()
                            time.sleep(0.5)
                            continue
                        data = json.dumps(event.to_dict(), ensure_ascii=False, default=str)
                        self.wfile.write(f"event: {event.type}\ndata: {data}\n\n".encode())
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                except Exception:
                    pass
                finally:
                    owner._bus.unsubscribe(queue)

            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                path, query = parsed.path, parse_qs(parsed.query)
                owner._refresh()
                snap = owner._store.snapshot()
                if path in ("/", "/index.html"):
                    body = _HTML.encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif path == "/api/status":
                    self._json(owner._status())
                elif path == "/api/portfolio":
                    self._json(
                        {
                            "equity": snap.equity,
                            "initial_equity": snap.initial_equity,
                            "cash": snap.cash,
                            "realized_pnl": snap.realized_pnl,
                            "unrealized_pnl": snap.unrealized_pnl,
                            "drawdown_pct": snap.drawdown_pct,
                            "equity_curve": list(snap.equity_curve),
                            "timestamp": snap.timestamp,
                        }
                    )
                elif path == "/api/positions":
                    self._json({"positions": list(snap.open_positions)})
                elif path == "/api/trades":
                    self._json({"trades": list(snap.recent_trades)})
                elif path == "/api/signals":
                    self._json({"signals": list(snap.recent_signals)})
                elif path == "/api/risk-decisions":
                    self._json({"risk_decisions": list(snap.recent_risk_decisions)})
                elif path == "/api/metrics":
                    self._json(
                        {
                            name: getattr(snap, name)
                            for name in (
                                "cycles",
                                "assets_scanned",
                                "contexts_built",
                                "signals_generated",
                                "risk_accepted",
                                "risk_rejected",
                                "router_no_trade",
                                "orders_created",
                                "positions_open",
                                "positions_closed",
                                "trades_today",
                                "wins",
                                "losses",
                                "drawdown_pct",
                            )
                        }
                        | {"win_rate": snap.win_rate, "timestamp": snap.timestamp}
                    )
                elif path == "/api/assets":
                    self._json({"assets": list(snap.assets)})
                elif path == "/api/strategies":
                    self._json({"strategies": list(snap.strategies)})
                elif path == "/api/events":
                    limit = max(1, min(int((query.get("limit") or ["100"])[0]), 500))
                    self._json(
                        {
                            "events": [
                                e.to_dict()
                                for e in (owner._bus.recent(limit) if owner._bus else [])
                            ]
                        }
                    )
                elif path == "/api/snapshot":
                    self._json(snap.to_dict())
                elif path == "/health":
                    self._json({"status": "ok", **owner._status()})
                elif path == "/ws/events":
                    self._sse()
                else:
                    self._json({"error": "not found"}, 404)

        self._server = _Server((self._host, self._port), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="paper-dashboard", daemon=True
        )
        self._thread.start()
        print(f"[paper-dashboard] READ-ONLY dashboard available at {self.url}")
        return self.url

    def set_orchestrator(self, orchestrator: Any) -> None:
        self._orchestrator = orchestrator

    def set_broker(self, broker: Any) -> None:
        self._broker = broker

    def stop(self) -> None:
        self._stop.set()
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    def _refresh(self) -> None:
        try:
            status = self._orchestrator.status() if self._orchestrator else None
            self._store.sync_runtime(
                broker=self._broker,
                orchestrator_status=status,
                running=bool(status.get("running")) if status else None,
                last_errors=list(status.get("last_errors") or []) if status else None,
            )
        except Exception:
            return

    def _status(self) -> dict[str, Any]:
        snap = self._store.snapshot()
        return {
            "mode": snap.mode,
            "runtime_status": snap.runtime_status,
            "read_only": True,
            "cycles": snap.cycles,
            "equity": snap.equity,
            "trades_today": snap.trades_today,
            "positions_open": snap.positions_open,
            "last_update": snap.timestamp,
            "errors": list(snap.errors),
        }


__all__ = ["PaperDashboardServer"]
