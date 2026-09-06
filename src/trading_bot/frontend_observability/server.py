"""Read-only frontend observability server.

Serves HTML views + JSON projections built exclusively from committed
runtime artifacts.  Zero control surface: POST returns 405 on every
route; a dashboard outage cannot affect the trading runtime because this
server only reads files written by it.
"""

from __future__ import annotations

import json
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from trading_bot.frontend_observability import projections

DEFAULT_PORT = 8767


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, indent=2, default=str).encode()


def render_overview_html(payload: dict[str, Any]) -> str:
    rows = "".join(
        f"<tr><th>{escape(str(k))}</th><td>{escape(str(v))}</td></tr>" for k, v in payload.items()
    )
    return f"<h1>OVERVIEW</h1><table>{rows}</table>"


def render_funnel_html(payload: dict[str, Any]) -> str:
    counts = payload.get("counts", {})
    conv = payload.get("conversions", {})
    names = list(counts)
    rows = []
    for i, (k, v) in enumerate(counts.items()):
        nxt = names[i + 1] if i + 1 < len(names) else "-"
        rows.append(
            f"<tr><th>{escape(k)}</th><td>{v}</td><td>{escape(str(conv.get(f'{k}->{nxt}', '')))}</td></tr>"
        )
    return f"<h1>OPPORTUNITY FUNNEL</h1><p>source: {escape(str(payload.get('source')))}</p><table>{''.join(rows)}</table>"


def render_strategies_html(payload: dict[str, Any]) -> str:
    rows = []
    for s in payload.get("strategies", []):
        rows.append(
            "<tr><td>"
            + "</td><td>".join(escape(str(s.get(k))) for k in ("strategy", "evaluations", "proposals", "selected", "trades", "wins", "losses", "net_pnl", "expectancy", "profit_factor", "sample"))
            + "</td></tr>"
        )
    head = "<tr><th>strategy</th><th>evals</th><th>proposals</th><th>selected</th><th>trades</th><th>wins</th><th>losses</th><th>net PnL</th><th>expectancy</th><th>PF</th><th>sample</th></tr>"
    return f"<h1>STRATEGIES</h1><table>{head}{''.join(rows)}</table>"


def render_assets_html(payload: dict[str, Any]) -> str:
    rows = []
    for a in payload.get("assets", []):
        rows.append(
            "<tr><td>"
            + "</td><td>".join(escape(str(a.get(k))) for k in ("asset", "proposals", "selected", "risk_accepted", "trades", "net_pnl", "sample"))
            + "</td></tr>"
        )
    head = "<tr><th>asset</th><th>proposals</th><th>selected</th><th>risk accepted</th><th>trades</th><th>net PnL</th><th>sample</th></tr>"
    return f"<h1>ASSETS</h1><table>{head}{''.join(rows)}</table>"


def render_decisions_html(payload: dict[str, Any]) -> str:
    parts = ["<h1>DECISIONS</h1>"]
    agg = payload.get("campaign_aggregates", {})
    parts.append(f"<p>campaign aggregates: {escape(json.dumps(agg, default=str))}</p><ul>")
    for d in payload.get("decisions", []):
        parts.append(f"<li><b>{escape(str(d.get('outcome')))}</b> verifier={escape(str(d.get('verifier')))} winner={escape(str(d.get('winner')))}</li>")
    parts.append("</ul>")
    return "".join(parts)


def render_trades_html(payload: dict[str, Any]) -> str:
    return (
        "<h1>TRADES / PORTFOLIO</h1><p>canonical accounting passthrough — the frontend computes nothing</p>"
        f"<pre>{escape(json.dumps(payload, indent=2, default=str)[:20000])}</pre>"
    )


def render_timeline_html(payload: dict[str, Any]) -> str:
    parts = ["<h1>AGENT CONVERSATION (structured artifacts only)</h1><ol>"]
    for item in payload.get("items", []):
        parts.append(f"<li>{escape(json.dumps(item, default=str))}</li>")
    parts.append("</ol>")
    return "".join(parts)


def render_replay_html(payload: dict[str, Any]) -> str:
    parts = [f"<h1>REPLAY — {escape(str(payload.get('RUN_REPLAY')))}</h1><ul>"]
    for c in payload.get("chain", []):
        parts.append(f"<li>{escape(c['step'])}: {'available' if c['available'] else 'missing'} ({escape(c['evidence'])})</li>")
    parts.append(f"</ul><p>{escape(str(payload.get('note')))}</p>")
    return "".join(parts)


def render_reports_html(payload: list[dict[str, Any]]) -> str:
    parts = ["<h1>REPORTS</h1><ul>"]
    for r in payload:
        parts.append(f"<li><a href=\"/api/reports/content?path={escape(r['path'], quote=True)}\">{escape(r['path'])}</a> ({r['bytes']} B)</li>")
    parts.append("</ul>")
    return "".join(parts)


class FrontendHandler(BaseHTTPRequestHandler):
    server_version = "FrontendObservabilityV1/1.0"

    # ---------------------------------------------------------------- GET
    def do_GET(self) -> None:
        path, _, query = self.path.partition("?")
        path = path.rstrip("/") or "/"
        try:
            if path == "/":
                links = "".join(
                    f"<li><a href='{p}'>{t}</a></li>"
                    for p, t in (
                        ("/overview", "Overview"),
                        ("/funnel", "Opportunity funnel"),
                        ("/agents", "Agent conversation"),
                        ("/strategies", "Strategies"),
                        ("/assets", "Assets"),
                        ("/decisions", "Decisions"),
                        ("/trades", "Trades/Portfolio"),
                        ("/reports", "Reports"),
                        ("/replay", "Replay status"),
                    )
                )
                self._html(f"<h1>PAPER · REAL PUBLIC MARKET · LIVE DISABLED</h1><ul>{links}</ul>")
            elif path == "/overview":
                payload = projections.overview()
                self._both(render_overview_html(payload), payload)
            elif path == "/funnel":
                payload = projections.funnel()
                self._both(render_funnel_html(payload), payload)
            elif path == "/agents":
                payload = projections.agent_timeline()
                self._both(render_timeline_html(payload), payload)
            elif path == "/strategies":
                payload = projections.strategies()
                self._both(render_strategies_html(payload), payload)
            elif path == "/assets":
                payload = projections.assets_view()
                self._both(render_assets_html(payload), payload)
            elif path == "/decisions":
                payload = projections.decisions()
                self._both(render_decisions_html(payload), payload)
            elif path == "/trades":
                payload = projections.trades()
                self._both(render_trades_html(payload), payload)
            elif path == "/replay":
                payload = projections.replay_status()
                self._both(render_replay_html(payload), payload)
            elif path == "/reports":
                items = projections.report_list()
                self._both(render_reports_html(items), {"reports": items})
            elif path == "/api/reports/content":
                params = dict(pair.split("=", 1) for pair in query.split("&") if "=" in pair)
                payload = projections.report_content(params.get("path", ""))
                self._json(payload)
            else:
                self._plain(b"not found", 404)
        except Exception as exc:
            self._json({"error": str(exc)}, status=500)

    # --------------------------------------------------------------- POST
    def do_POST(self) -> None:
        self.send_response(405)
        self.send_header("Allow", "GET")
        self.end_headers()

    # ----------------------------------------------------------- helpers
    def _html(self, body: str, status: int = 200) -> None:
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, payload: dict[str, Any], status: int = 200) -> None:
        data = _json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _both(self, html: str, payload: dict[str, Any]) -> None:
        if "application/json" in self.headers.get("Accept", ""):
            self._json(payload)
        else:
            self._html(html)

    def _plain(self, body: bytes, status: int) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:
        return


def create_server(host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), FrontendHandler)


def main() -> int:
    import argparse
    import threading

    parser = argparse.ArgumentParser(description="read-only frontend observability server")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    server = create_server(args.host, args.port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"frontend observability (read-only): http://{args.host}:{server.server_port}/  — Ctrl+C to stop")
    try:
        while True:
            threading.Event().wait(3600)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
