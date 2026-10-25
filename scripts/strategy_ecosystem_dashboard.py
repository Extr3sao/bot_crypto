"""Strategy Ecosystem & Agent Observability Dashboard (WP-OBS-STRAT-01 §5-§9).

READ-ONLY. This server consumes the observability projection layer
(``trading_bot.observability``), which reads the runtime's authoritative
artifacts (DecisionTrace, performance, routing comparisons, heartbeat,
admission registry). It has **no** endpoint that starts, stops, promotes, sizes,
changes risk, admits a strategy or touches a child process: every non-GET
request is refused with 405, and the process never imports the trading runtime's
mutating surfaces.

Stack: the Python standard library (``http.server``) + one self-contained HTML
page, exactly like the existing ``scripts/paper_lab_dashboard.py``. No build
step, no framework, no package install — the repo already serves its consoles
this way, and a read-only observability surface does not need more.

    uv run python scripts/strategy_ecosystem_dashboard.py    # http://127.0.0.1:8790

Real-time updates use **SSE** (server → client), because the flow is
one-directional; there is no bidirectional need.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.observability import StrategyEcosystemObservatory  # noqa: E402

LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}
DEFAULT_PORT = 8790
STATIC_DIR = REPO_ROOT / "src" / "trading_bot" / "observability" / "static"

CONTROL_POLICY: dict[str, Any] = {
    "read_only": True,
    "mutating_endpoints": [],
    "allowed_methods": ["GET"],
    "why": (
        "the dashboard is an observability surface: a control it could trigger is a "
        "control a bug could trigger. Operator actions are commands to copy, not endpoints."
    ),
}


# --------------------------------------------------------------------- routing


def _json(payload: Any, status: int = 200) -> tuple[int, str, bytes]:
    body = (json.dumps(payload, indent=2, default=str, ensure_ascii=False) + "\n").encode("utf-8")
    return status, "application/json; charset=utf-8", body


def resolve_api(obs: StrategyEcosystemObservatory, path: str) -> tuple[int, str, bytes] | None:
    """Return (status, content_type, body) for an API path, or ``None`` if unknown.

    Kept as a pure function so tests can exercise the whole read-only API without
    opening a socket.
    """
    segments = [unquote(s) for s in path.strip("/").split("/") if s]
    if not segments or segments[0] != "api":
        return None
    tail = segments[1:]

    if tail == ["system"]:
        return _json({"system": obs.system_view(), "controls": CONTROL_POLICY})
    if tail == ["topology"]:
        return _json(obs.topology().to_dict())
    if tail == ["runs"]:
        current = obs.current_run()
        return _json(
            {
                "runs": [{"run_id": r.run_id, "path": str(r.run_dir)} for r in obs.list_runs()],
                "current": current.run_id if current else None,
            }
        )
    if tail == ["strategies"]:
        return _json(obs.strategies_view())
    if len(tail) >= 2 and tail[0] == "strategies":
        sid = tail[1]
        if len(tail) == 2:
            detail = obs.strategy_detail(sid)
            return _json(
                detail if detail is not None else {"error": "unknown strategy"},
                200 if detail else 404,
            )
        if tail[2] == "performance":
            detail = obs.strategy_detail(sid)
            if detail is None:
                return _json({"error": "unknown strategy"}, 404)
            return _json(detail["performance"])
        if tail[2] == "funnel":
            detail = obs.strategy_detail(sid)
            if detail is None:
                return _json({"error": "unknown strategy"}, 404)
            return _json(detail["funnel"])
        if tail[2] == "lifecycle":
            detail = obs.strategy_detail(sid)
            if detail is None:
                return _json({"error": "unknown strategy"}, 404)
            return _json(detail["state"])
        if tail[2] == "evidence":
            detail = obs.strategy_detail(sid)
            if detail is None:
                return _json({"error": "unknown strategy"}, 404)
            return _json(detail["evidence"])
    if tail == ["agents"]:
        return _json(obs.agents_view())
    if len(tail) >= 2 and tail[0] == "agents":
        aid = tail[1]
        if len(tail) == 2:
            agents = obs.agents_view()["agents"]
            match = next((a for a in agents if a["agent_id"] == aid), None)
            return _json(
                match if match is not None else {"error": "unknown agent"}, 200 if match else 404
            )
        if tail[2] in ("activity", "messages"):
            activity = obs.agent_activity(aid)
            return _json(
                activity if activity is not None else {"error": "unknown agent"},
                200 if activity else 404,
            )
    if tail == ["lifecycle"]:
        return _json(obs.lifecycle_view())
    if tail == ["routing", "comparisons"] or tail == ["routing"]:
        return _json(obs.routing_view())
    if tail == ["portfolio"]:
        return _json(obs.portfolio_view())
    if tail == ["risk"]:
        return _json(obs.risk_view())
    if tail == ["executions"]:
        return _json(obs.executions_view())
    if tail == ["traces"]:
        return _json(obs.traces_view())
    if len(tail) == 2 and tail[0] == "traces":
        detail = obs.trace_detail(tail[1])
        return _json(
            detail if detail is not None else {"error": "unknown trace"}, 200 if detail else 404
        )
    if tail == ["campaigns"]:
        return _json(obs.campaigns_view())
    if tail == ["snapshot"]:
        return _json(obs.snapshot())
    return None


def _pulse(obs: StrategyEcosystemObservatory) -> dict[str, Any]:
    system = obs.system_view()
    return {
        "generated_at_ms": system["freshness"]["data_timestamp_ms"],
        "run_id": system["runtime"]["run_id"],
        "state": system["runtime"]["state"],
        "routing_mode": system["routing_mode"],
        "freshness": system["freshness"],
        "totals": system["totals"],
        "false_success": system["false_success"],
    }


# ------------------------------------------------------------------- handler


def make_handler(
    obs: StrategyEcosystemObservatory, *, stream_seconds: int
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "strategy-ecosystem-dashboard/1.0"

        def _send(self, status: int, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)
            if query.get("run_id"):
                obs.run_id = query["run_id"][0]
            if path in ("/", "/index.html"):
                html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
                self._send(200, "text/html; charset=utf-8", html.encode("utf-8"))
                return
            if path == "/healthz":
                current = obs.current_run()
                self._send(
                    200,
                    "application/json; charset=utf-8",
                    json.dumps(
                        {
                            "ok": True,
                            "read_only": True,
                            "run_id": current.run_id if current else None,
                        }
                    ).encode("utf-8")
                    + b"\n",
                )
                return
            if path == "/api/events/stream":
                self._stream(obs)
                return
            resolved = resolve_api(obs, path)
            if resolved is None:
                self._send(404, "application/json; charset=utf-8", b'{"error":"not found"}\n')
                return
            status, content_type, body = resolved
            self._send(status, content_type, body)

        def _stream(self, obs: StrategyEcosystemObservatory) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            # Bounded stream: a slow or dangling client can never pin a thread forever.
            max_events = 120
            try:
                for _ in range(max_events):
                    payload = json.dumps(_pulse(obs), default=str)
                    self.wfile.write(f"event: pulse\ndata: {payload}\n\n".encode())
                    self.wfile.flush()
                    time.sleep(stream_seconds)
            except (BrokenPipeError, ConnectionResetError, OSError):
                return  # a disconnected client is not an error

        def _refuse(self) -> None:
            self._send(
                405,
                "application/json; charset=utf-8",
                b'{"error":"this dashboard is read-only","allowed":["GET"]}\n',
            )

        do_POST = _refuse
        do_PUT = _refuse
        do_DELETE = _refuse
        do_PATCH = _refuse

        def log_message(self, format: str, *args: Any) -> None:
            print(f"[dashboard] {self.address_string()} {format % args}", file=sys.stderr)

    return Handler


def resolve_host(host: str) -> str:
    if host not in LOOPBACK_HOSTS:
        raise SystemExit(
            f"refusing to bind {host!r}: the dashboard serves runtime state and is loopback-only "
            "(use 127.0.0.1 or ::1)"
        )
    return host


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--runs-root", default=None)
    parser.add_argument("--campaigns-root", default=None)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--stream-seconds", type=int, default=5)
    parser.add_argument("--once", action="store_true", help="print the control-room page and exit")
    return parser.parse_args(argv)


def build_observatory(args: argparse.Namespace) -> StrategyEcosystemObservatory:
    root = Path(args.repo_root).resolve()
    return StrategyEcosystemObservatory(
        repo_root=root,
        runs_root=Path(args.runs_root).resolve() if args.runs_root else None,
        campaigns_root=Path(args.campaigns_root).resolve() if args.campaigns_root else None,
        run_id=args.run_id,
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    resolve_host(args.host)
    obs = build_observatory(args)
    if args.once:
        print((STATIC_DIR / "index.html").read_text(encoding="utf-8"))
        return 0
    server = ThreadingHTTPServer(
        (args.host, args.port), make_handler(obs, stream_seconds=args.stream_seconds)
    )
    print(f"[dashboard] read-only strategy ecosystem console on http://{args.host}:{args.port}")
    print("[dashboard] no mutating endpoints; GET only; Ctrl-C to exit")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[dashboard] stopped")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
