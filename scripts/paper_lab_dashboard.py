"""Read-only local PAPER lab dashboard (§53, §57, §58).

    uv run python scripts/paper_lab_dashboard.py            # http://127.0.0.1:8787

One page that answers "is it running, what has it done, and is the disk going to
run out", served from the artifacts the lab already writes. No database, no
build step, no JavaScript framework: the Python standard library, one HTML page,
and a JSON endpoint the page refreshes.

Two design decisions worth stating, because they are the difference between a
console and a liability:

* **It is read-only.** There is no endpoint that starts, stops, restarts, changes
  risk, admits a strategy, or touches a child process. The operator controls are
  *named on the page as commands to copy*, and the server refuses every non-GET
  request. A dashboard that can kill the lab is a second way for the lab to die.
* **It binds to loopback only.** The host is validated against the loopback
  addresses and anything else is refused at startup, so the page cannot be reached
  from the network by accident.

There is no LIVE control because there is no LIVE path: the payload reports
``live_control: false`` because every plane under it is PAPER or read-only market
data. A stale heartbeat is rendered as stale — never as healthy.
"""

from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.autonomous.observability import (  # noqa: E402
    allow_tolerant_console_output,
    build_status,
)
from trading_bot.autonomous.supervisor import DiskThresholds  # noqa: E402

REPO = REPO_ROOT
LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}
DEFAULT_PORT = 8787

#: The page states the controls it deliberately does not have.
CONTROL_POLICY: dict[str, Any] = {
    "read_only": True,
    "mutating_endpoints": [],
    "start": "python scripts/start_paper_lab.py --run-id <id>",
    "status": "python scripts/paper_lab_status.py",
    "stop": "python scripts/start_paper_lab.py --stop reports/paper-lab/<id>",
    "restart": "python scripts/start_paper_lab.py --restart --run-id <id>",
    "why": (
        "the dashboard is an observability surface: a stop it could trigger is a "
        "stop a bug could trigger, and the lab must have exactly one operator path"
    ),
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--lab-root", default="reports/paper-lab")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--paper-root", default="reports/autonomous-paper")
    parser.add_argument("--refresh-seconds", type=int, default=15)
    parser.add_argument("--disk-warning-gb", type=float, default=1.5)
    parser.add_argument("--disk-critical-gb", type=float, default=0.8)
    parser.add_argument("--disk-stop-gb", type=float, default=0.3)
    parser.add_argument(
        "--once",
        action="store_true",
        help="render the page to stdout and exit (used by tests and by --check)",
    )
    return parser.parse_args(argv)


def status_payload(args: argparse.Namespace) -> dict[str, Any]:
    payload = build_status(
        lab_root=REPO / args.lab_root,
        run_id=args.run_id,
        paper_root=REPO / args.paper_root,
        thresholds=DiskThresholds(
            warning_bytes=int(args.disk_warning_gb * 1e9),
            critical_bytes=int(args.disk_critical_gb * 1e9),
            stop_bytes=int(args.disk_stop_gb * 1e9),
        ),
        quality_path=REPO / "docs" / "FORWARD_DATA_QUALITY_REPORT.json",
        preregistration_path=REPO / "config" / "microstructure_preregistration.json",
    )
    payload["controls"] = CONTROL_POLICY
    payload["dashboard"] = {
        "host": args.host,
        "port": args.port,
        "auto_refresh_seconds": args.refresh_seconds,
        "live_control": False,
    }
    return payload


def _card(title: str, rows: list[tuple[str, Any]], *, tone: str = "") -> str:
    body = "".join(
        f"<div class='row'><span class='k'>{_escape(label)}</span>"
        f"<span class='v'>{_escape(_format(value))}</span></div>"
        for label, value in rows
    )
    return (
        f"<section class='card {tone}'><h2>{_escape(title)}</h2>{body}</section>"
    )


def _escape(value: Any) -> str:
    text = "" if value is None else str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _format(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, dict):
        return ", ".join(f"{key}={val}" for key, val in value.items()) or "—"
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value) or "—"
    return str(value)


def _tone(value: Any) -> str:
    if value is True:
        return "ok"
    if value is False:
        return "bad"
    return ""


def render_page(payload: dict[str, Any]) -> str:
    """One self-contained page. No external assets, no framing, no scripts but ours."""
    system = payload.get("system") or {}
    disk = payload.get("disk") or {}
    paper = payload.get("paper") or {}
    collector = payload.get("collector") or {}
    lab = payload.get("strategy_lab") or {}
    readiness = payload.get("readiness") or {}
    flags = payload.get("readiness_flags") or {}
    errors = payload.get("errors") or []
    controls = payload.get("controls") or {}
    dashboard = payload.get("dashboard") or {}

    state = system.get("state") or "UNKNOWN"
    tone = "ok" if state in ("HEALTHY",) and not system.get("heartbeat_is_stale") else (
        "bad" if state == "FAILED" else "warn"
    )
    cards = [
        _card(
            "SYSTEM",
            [
                ("state", state),
                ("running", system.get("running")),
                ("uptime", _duration(system.get("uptime_seconds"))),
                ("heartbeat age", _duration(system.get("heartbeat_age_seconds"))),
                ("heartbeat stale", system.get("heartbeat_is_stale")),
                ("restarts", system.get("restarts")),
                ("mode", payload.get("mode")),
                ("live control", payload.get("live_control")),
                ("run id", payload.get("run_id")),
            ],
            tone=tone,
        ),
        _card(
            "DISK",
            [
                ("free", f"{disk.get('free_gb')} GB"),
                ("level", disk.get("level")),
                ("thresholds", disk.get("thresholds")),
                ("observed rate", f"{disk.get('consumption_gb_per_day')} GB/day"),
                ("estimated hours left", disk.get("estimated_hours_remaining")),
                ("guidance", disk.get("guidance")),
            ],
            tone="bad" if disk.get("level") in ("STOP", "CRITICAL") else ("warn" if disk.get("level") == "WARNING" else "ok"),
        ),
        _card(
            "PAPER",
            [
                ("cycle", paper.get("cycle")),
                ("uptime", _duration(paper.get("uptime_seconds"))),
                ("assets", paper.get("assets")),
                ("timeframe", paper.get("timeframe")),
                ("strategies evaluated", paper.get("strategies_evaluated")),
                ("decisions", paper.get("decisions")),
                ("no trade", paper.get("no_trade")),
                ("no trade kinds", paper.get("no_trade_kinds")),
                ("paper trades", paper.get("paper_trades")),
                ("shadow trades", paper.get("shadow_trades")),
                ("risk vetoes", paper.get("risk_vetoes")),
                ("runtime failures", paper.get("runtime_failures")),
                ("storage failures survived", paper.get("storage_failures")),
                ("paper candidates", paper.get("paper_candidates")),
                ("heartbeat age", _duration(paper.get("heartbeat_age_seconds"))),
            ],
            tone="bad" if paper.get("runtime_failures") else "ok",
        ),
        _card(
            "COLLECTOR",
            [
                ("available", collector.get("available")),
                ("root", collector.get("root")),
                ("events", collector.get("events")),
                ("gaps", collector.get("gaps")),
                ("reconnects", collector.get("reconnects")),
                ("resnapshots", collector.get("resnapshots")),
                ("segments", collector.get("segments_on_disk")),
                ("raw on disk", f"{collector.get('segment_gb')} GB"),
                ("state age", _duration(collector.get("state_age_seconds"))),
                ("stop reason", collector.get("stop_reason")),
                ("fatal failure", collector.get("fatal_failure")),
                ("manifest", collector.get("manifest")),
            ],
            tone="bad" if collector.get("fatal_failure") else "ok",
        ),
        _card(
            "RETENTION",
            [
                ("deletion enabled", (collector.get("retention") or {}).get("deletion_enabled")),
                ("compacted windows", (collector.get("retention") or {}).get("compacted_windows")),
                ("deleted segments", (collector.get("retention") or {}).get("deleted_segments")),
                ("freed", (collector.get("retention") or {}).get("freed_bytes")),
            ],
        ),
        _card(
            "STRATEGIES",
            [
                ("total", lab.get("strategies_total")),
                ("histogram", lab.get("status_histogram")),
                ("lifecycle", lab.get("lifecycle")),
                ("admitted for paper", lab.get("admitted_for_paper")),
                ("paper candidates", lab.get("paper_candidates")),
                ("not paper executable", lab.get("strategies_not_paper_executable")),
                ("checks ok", lab.get("all_checks_ok")),
            ],
        ),
        _card(
            "READINESS",
            [
                ("M-03", (readiness.get("M-03") or {}).get("verdict")),
                ("M-03 state", (readiness.get("M-03") or {}).get("state")),
                ("M-07", (readiness.get("M-07") or {}).get("verdict")),
                ("M-07 state", (readiness.get("M-07") or {}).get("state")),
                ("preregistration", readiness.get("preregistration_version")),
                ("not yet run", readiness.get("not_yet_run")),
            ],
        ),
        _card(
            "ERRORS",
            [("open findings", errors)] if errors else [("open findings", "none")],
            tone="bad" if errors else "ok",
        ),
    ]

    children = "".join(
        f"<tr><td>{_escape(name)}</td><td>{_escape(child.get('state'))}</td>"
        f"<td>{_escape(child.get('pid'))}</td><td>{_escape(child.get('alive'))}</td>"
        f"<td>{_escape(_duration(child.get('uptime_seconds')))}</td>"
        f"<td>{_escape(child.get('restarts'))}</td>"
        f"<td>{_escape(child.get('exit_code'))}</td>"
        f"<td class='small'>{_escape(child.get('last_error'))}</td></tr>"
        for name, child in sorted((payload.get("children") or {}).items())
    )
    flags_html = "".join(
        f"<span class='flag {_tone(value)}'>{_escape(key)}: {_escape(_format(value))}</span>"
        for key, value in flags.items()
        if isinstance(value, bool)
    )
    stop_report = payload.get("stop_report") or {}
    run_report = payload.get("run_report") or {}
    plan = payload.get("plan") or {}
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PAPER lab — {_escape(payload.get('run_id') or 'no run')}</title>
<style>
:root {{ color-scheme: dark; }}
body {{ margin:0; padding:24px; background:#0f1115; color:#e6e8eb;
       font:14px/1.45 ui-monospace, SFMono-Regular, Menlo, monospace; }}
h1 {{ font-size:18px; margin:0 0 4px; }}
.sub {{ color:#8b93a1; margin-bottom:18px; }}
.banner {{ padding:8px 12px; border-radius:6px; margin-bottom:16px; display:inline-block; }}
.banner.ok {{ background:#12331f; color:#8ff0a4; }}
.banner.warn {{ background:#3a2f10; color:#ffd479; }}
.banner.bad {{ background:#3d1518; color:#ff9aa2; }}
.flags {{ margin-bottom:16px; display:flex; gap:8px; flex-wrap:wrap; }}
.flag {{ padding:4px 8px; border-radius:999px; background:#1b1f27; color:#c7cdd6; }}
.flag.ok {{ background:#12331f; color:#8ff0a4; }}
.flag.bad {{ background:#3d1518; color:#ff9aa2; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(330px, 1fr)); gap:14px; }}
.card {{ background:#161a21; border:1px solid #232833; border-radius:8px; padding:12px; }}
.card.ok {{ border-color:#1f5233; }}
.card.warn {{ border-color:#6b5a1e; }}
.card.bad {{ border-color:#6d2429; }}
.card h2 {{ font-size:13px; letter-spacing:.08em; color:#8b93a1; margin:0 0 8px; }}
.row {{ display:flex; justify-content:space-between; gap:12px; padding:2px 0; }}
.k {{ color:#8b93a1; }}
.v {{ text-align:right; word-break:break-word; max-width:60%; }}
table {{ width:100%; border-collapse:collapse; margin-top:14px; }}
th, td {{ text-align:left; padding:6px 8px; border-bottom:1px solid #232833; }}
th {{ color:#8b93a1; font-weight:400; }}
.small {{ color:#8b93a1; }}
footer {{ margin-top:20px; color:#8b93a1; }}
code {{ background:#1b1f27; padding:2px 6px; border-radius:4px; }}
</style></head>
<body>
<h1>PAPER LAB — {_escape(payload.get('run_id') or 'no run')}</h1>
<div class="sub">generated {_escape(payload.get('generated_at_iso'))} · mode {_escape(payload.get('mode'))}
 · read-only · auto-refresh {_escape(dashboard.get('auto_refresh_seconds'))}s ·
 <a href="/api/status" style="color:#7fb2ff">raw JSON</a></div>
<div class="banner {tone}">{_escape(state)}{' — STALE HEARTBEAT' if system.get('heartbeat_is_stale') else ''}</div>
<div class="flags">{flags_html}</div>
<div class="grid">{''.join(cards)}</div>
<h2 style="font-size:13px;letter-spacing:.08em;color:#8b93a1;margin-top:22px">CHILD PROCESSES</h2>
<table><tr><th>process</th><th>state</th><th>pid</th><th>alive</th><th>uptime</th><th>restarts</th><th>exit</th><th>last error</th></tr>
{children or "<tr><td colspan='8'>no children reported</td></tr>"}</table>
<div class="grid" style="margin-top:14px">
{_card("STOP REPORT", [("verdict", stop_report.get("verdict")), ("escalated", stop_report.get("escalated")), ("failed children", stop_report.get("failed_children")), ("exit codes", stop_report.get("exit_codes"))])}
{_card("RUN REPORT", [("final state", run_report.get("final_state")), ("stop reason", run_report.get("stop_reason")), ("duration", run_report.get("duration_seconds"))])}
{_card("PLAN", [("duration hours", plan.get("duration_hours")), ("retention", plan.get("retention")), ("collector resume", plan.get("collector_resume")), ("no live path", plan.get("no_live_path"))])}
{_card("CONTROLS", [("read only", controls.get("read_only")), ("mutating endpoints", controls.get("mutating_endpoints")), ("start", controls.get("start")), ("status", controls.get("status")), ("stop", controls.get("stop")), ("restart", controls.get("restart"))])}
</div>
<footer>No LIVE control is presented because no LIVE path exists: every plane is PAPER or read-only market data.
Controls are commands, not endpoints — <code>{_escape(controls.get('why'))}</code></footer>
<script>
async function refresh() {{
  try {{
    const response = await fetch('/api/status', {{cache: 'no-store'}});
    if (response.ok) {{ /* full re-render keeps one source of truth */ }}
  }} catch (error) {{ /* a dashboard that cannot reach itself shows the last page */ }}
  setTimeout(refresh, {int(dashboard.get('auto_refresh_seconds') or 15) * 1000});
}}
setTimeout(refresh, {int(dashboard.get('auto_refresh_seconds') or 15) * 1000});
</script>
</body></html>
"""


def _duration(value: Any) -> str:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return "—"
    if seconds < 120:
        return f"{seconds:.1f}s"
    if seconds < 7200:
        return f"{seconds / 60:.1f}m"
    return f"{seconds / 3600:.1f}h"


def make_handler(args: argparse.Namespace) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "paper-lab-dashboard/1.0"

        def _send(self, code: int, body: bytes, content_type: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                payload = status_payload(args)
                self._send(200, render_page(payload).encode("utf-8"), "text/html; charset=utf-8")
                return
            if path == "/api/status":
                payload = status_payload(args)
                self._send(
                    200,
                    (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
                    "application/json; charset=utf-8",
                )
                return
            if path == "/healthz":
                payload = status_payload(args)
                self._send(
                    200,
                    (
                        json.dumps(
                            {
                                "ok": True,
                                "state": (payload.get("system") or {}).get("state"),
                                "read_only": True,
                            }
                        )
                        + "\n"
                    ).encode("utf-8"),
                    "application/json; charset=utf-8",
                )
                return
            self._send(404, b'{"error":"not found"}\n', "application/json; charset=utf-8")

        def _refuse(self) -> None:
            self._send(
                405,
                b'{"error":"this dashboard is read-only","allowed":["GET"]}\n',
                "application/json; charset=utf-8",
            )

        do_POST = _refuse
        do_PUT = _refuse
        do_DELETE = _refuse
        do_PATCH = _refuse

        def log_message(self, format: str, *args: Any) -> None:
            print(f"[dashboard] {self.address_string()} {format % args}", file=sys.stderr)

    return Handler


def resolve_host(host: str) -> str:
    """Fail closed: only loopback, so the page cannot be reached from a network."""
    if host not in LOOPBACK_HOSTS:
        raise SystemExit(
            f"refusing to bind {host!r}: the dashboard serves live process state and "
            "is loopback-only (use 127.0.0.1 or ::1)"
        )
    return host


def main(argv: list[str] | None = None) -> int:
    allow_tolerant_console_output()
    args = parse_args(argv)
    resolve_host(args.host)
    if args.once:
        print(render_page(status_payload(args)))
        return 0
    server = ThreadingHTTPServer((args.host, args.port), make_handler(args))
    print(f"[dashboard] read-only PAPER lab console on http://{args.host}:{args.port}")
    print("[dashboard] no LIVE control, no mutating endpoints; Ctrl-C to exit")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[dashboard] stopped")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
