"""Independent FRONTEND-OBSERVABILITY-V1 validator.

Audits the read-only frontend from outside its modules:
1 overview data            2 funnel               3 agents/debates view
4 decisions view           5 risk visibility      6 PnL passthrough
7 strategies view          8 assets view          9 reports access
10 read-only boundary     11 campaign isolation   12 no authority imports

Return value: FRONTEND_OBSERVABILITY_V1_FUNCTIONAL (functional, not
production-ready).
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from trading_bot.frontend_observability import projections
from trading_bot.frontend_observability.server import create_server

CHECKS: list[tuple[str, bool, str]] = []


def _check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail and not ok else ""))


def _get(base: str, path: str) -> tuple[int, dict | bytes]:
    req = urllib.request.Request(f"{base}{path}", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read()
            return resp.status, (json.loads(body) if body.startswith(b"{") else body)
    except urllib.error.HTTPError as exc:
        body = exc.read()
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, body


def _post(base: str, path: str) -> int:
    req = urllib.request.Request(f"{base}{path}", data=b"{}", method="POST")
    try:
        urllib.request.urlopen(req, timeout=5)
        return 200
    except urllib.error.HTTPError as exc:
        return exc.code


def main() -> int:
    server: ThreadingHTTPServer = create_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    time.sleep(0.2)

    try:
        # 1 overview data
        status, payload = _get(base, "/overview")
        _check("overview_data", status == 200 and "mode" in payload and "live_disabled" in payload)
        # 2 funnel
        status, payload = _get(base, "/funnel")
        has_funnel = status == 200 and "counts" in payload and "conversions" in payload
        _check("funnel", has_funnel)
        # 3 agents/debates
        status, payload = _get(base, "/agents")
        _check("agents_debates_view", status == 200 and isinstance(payload, dict) and "items" in payload)
        # 4 decisions
        status, payload = _get(base, "/decisions")
        _check("decisions_view", status == 200 and "decisions" in payload and "campaign_aggregates" in payload)
        # 5 risk visibility (risk accept/reject present in funnel counts)
        risk_visible = (
            "RISK_ACCEPT" in payload.get("campaign_aggregates", {})
            or True  # decisions aggregates always expose verifier/risk fields
        )
        _status_f, funnel_payload = _get(base, "/funnel")
        risk_visible = "RISK_ACCEPT" in funnel_payload.get("counts", {}) and "RISK_REJECT" in funnel_payload.get("counts", {})
        _check("risk_visibility", risk_visible)
        # 6 PnL passthrough (value passthrough + explicit no-authority note)
        status, payload = _get(base, "/trades")
        note = str(payload.get("note", "")).lower() if isinstance(payload, dict) else ""
        _check(
            "pnl_passthrough",
            status == 200
            and isinstance(payload, dict)
            and "realized_pnl" in payload
            and "frontend" in note
            and ("paperbroker" in note or "accounting" in note),
        )
        # 7 strategies
        status, payload = _get(base, "/strategies")
        ok = status == 200 and all("sample" in s for s in payload.get("strategies", []))
        _check("strategies_view", ok)
        # 8 assets
        status, payload = _get(base, "/assets")
        ok = status == 200 and all("sample" in a for a in payload.get("assets", []))
        _check("assets_view", ok)
        # 9 reports
        status, payload = _get(base, "/reports")
        _check("reports_access", status == 200 and isinstance(payload, dict))
        jail = projections.report_content("../../../pyproject.toml")
        _check("reports_path_jail", "error" in jail)
        # 10 read-only boundary
        codes = [_post(base, p) for p in ("/", "/overview", "/funnel", "/trades", "/decisions")]
        _check("read_only_boundary", all(c == 405 for c in codes), str(codes))
        # 11 campaign isolation (server reads artifacts; never writes them)
        root = projections.campaign_root()
        before = {p: p.stat().st_mtime for p in root.rglob("*.json")} if root.is_dir() else {}
        for _ in range(3):
            _get(base, "/overview")
            _get(base, "/trades")
        after = {p: p.stat().st_mtime for p in root.rglob("*.json")} if root.is_dir() else {}
        _check("campaign_isolation_readonly", before == after)
        # 12 no authority imports (scan import lines only; mentions in notes are fine)
        import trading_bot.frontend_observability.projections as proj_mod
        import trading_bot.frontend_observability.server as server_mod

        forbidden = ("RiskManager", "PaperBroker", "DecisionEngine", "place_order", "create_order", "execute_signal")
        clean = True
        for mod in (proj_mod, server_mod):
            for line in Path(mod.__file__).read_text(encoding="utf-8").splitlines():
                s = line.strip()
                if (s.startswith("import ") or s.startswith("from ")) and any(f in s for f in forbidden):
                    clean = False
        _check("no_authority_imports", clean)
        # 13 SPA index (V1.1): polished single-page UI, still zero control surface
        status, body = _get(base, "/")
        html = body.decode("utf-8", "replace") if isinstance(body, bytes) else str(body)
        spa_ok = (
            status == 200
            and "POC01 · Paper Observation" in html
            and "LIVE DISABLED" in html
            and "<form" not in html
            and "method=\"POST\"" not in html
            and "method:'POST'" not in html
            and all(t in html for t in ("Overview", "Funnel", "Agents", "Strategies", "Assets", "Decisions", "Trades", "Reports", "Replay"))
        )
        _check("spa_index_readonly", spa_ok)
        # 14 daily-series endpoint (V1.1)
        status, payload = _get(base, "/daily")
        _check("daily_series_endpoint", status == 200 and isinstance(payload, dict) and "days" in payload)
        # 15 webui module is also free of authority imports
        import trading_bot.frontend_observability.webui as webui_mod

        clean2 = True
        for line in Path(webui_mod.__file__).read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if (s.startswith("import ") or s.startswith("from ")) and any(f in s for f in forbidden):
                clean2 = False
        _check("webui_no_authority_imports", clean2)
        # 16 DEF-FE-003: package import must be side-effect free; -m execution warning-free
        proc = subprocess.run(
            [sys.executable, "-c",
             "import sys, trading_bot.frontend_observability as p;"
             "assert 'trading_bot.frontend_observability.server' not in sys.modules, 'server preloaded';"
             "assert 'trading_bot.frontend_observability.projections' not in sys.modules, 'projections preloaded';"],
            capture_output=True, text=True, timeout=120, check=False,
        )
        _check("no_premature_server_import", proc.returncode == 0, proc.stderr.strip()[:200])
        help_run = subprocess.run(
            [sys.executable, "-m", "trading_bot.frontend_observability.server", "--help"],
            capture_output=True, text=True, timeout=120, check=False,
        )
        _check(
            "module_help_warning_free",
            help_run.returncode == 0
            and "RuntimeWarning" not in help_run.stderr
            and "--reports-root" in help_run.stdout,
            help_run.stderr.strip()[:200],
        )
    finally:
        server.shutdown()
        server.server_close()

    passed = sum(1 for _, ok, _ in CHECKS if ok)
    print(f"\nFRONTEND-OBSERVABILITY-V1.1 validator: {passed}/{len(CHECKS)} PASS")
    if passed == len(CHECKS):
        print("RESULT: FRONTEND_OBSERVABILITY_V1_FUNCTIONAL")
        return 0
    print("RESULT: REPAIR_REQUIRED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
