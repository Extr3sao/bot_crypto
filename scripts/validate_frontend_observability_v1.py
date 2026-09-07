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

REPO_ROOT = Path(__file__).resolve().parents[1]

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
    # Bind the artifact source like an operator would (V1.2 source authority):
    # explicit argv > well-known live campaign worktree > fail loud.  Discovery
    # is intentionally ambiguous in this repository (multiple worktrees hold
    # campaign artifacts), so the validator never picks positionally.
    args = sys.argv[1:]
    if "--reports-root" in args:
        root = Path(args[args.index("--reports-root") + 1])
    else:
        default = REPO_ROOT.parent / "poc01-execution" / "reports"
        if (default / "paper-observation-01").is_dir():
            root = default
        else:
            print("FAIL source_binding — no --reports-root given and no "
                  f"campaign artifacts at {default}")
            print("usage: uv run python scripts/validate_frontend_observability_v1.py "
                  "--reports-root <PATH>")
            return 1
    projections.configure_source(reports_root=root)
    _check("source_binding", True, str(root))

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
            and "--reports-root" in help_run.stdout
            and "--campaign-api" in help_run.stdout,
            help_run.stderr.strip()[:200],
        )
        # 17 V1.2: source authority model — discovery must fail loud, never pick positionally
        import trading_bot.frontend_observability.projections as proj2

        _check(
            "fail_loud_source_resolution",
            hasattr(proj2, "SourceNotConfigured")
            and hasattr(proj2, "AmbiguousSource")
            and hasattr(proj2, "resolve_source"),
        )
        # 18 V1.2: staleness visibility contract
        info = proj2.source_info()
        _check(
            "staleness_visibility",
            all(
                k in info
                for k in (
                    "data_source",
                    "reports_root",
                    "last_persisted_at",
                    "stale_age_seconds",
                    "stale",
                    "stale_threshold_seconds",
                )
            ),
            str(sorted(info))[:160],
        )
        # 19 V1.2: live campaign identity from the bound source
        ov = proj2.overview()
        _check(
            "live_campaign_identity",
            ov.get("campaign_id") == "poc01-paper-observation-01-001"
            and ov.get("campaign_state") == "ACTIVE"
            and ov.get("data") == "REAL_PUBLIC_MARKET",
            str(ov.get("campaign_id")),
        )
        # 20 V1.2: campaign report isolation — no demo/legacy/fixture reports surfaced
        items = proj2.report_list()
        _check(
            "campaign_report_isolation",
            bool(items)
            and all(i["campaign_id"] == "poc01-paper-observation-01-001" for i in items)
            and all("RUN_REPORT" not in i["name"] for i in items),
            f"{len(items)} files",
        )
        # 21 V1.2: real funnel projection (non-zero scans from the live campaign)
        fu = proj2.funnel()
        _check(
            "real_funnel_projection",
            fu["counts"].get("MARKET_SCANS", 0) > 0
            and "PAPER_OPEN" in fu["counts"]
            and "PAPER_CLOSE" in fu["counts"],
            str(fu["counts"].get("MARKET_SCANS")),
        )
        # 22 V1.2: real trade projection + canonical PnL equality
        tr = proj2.trades()
        closed = tr.get("closed_trades", [])
        _check(
            "real_trade_projection",
            len(closed) >= 1
            and all(t.get("decision_id") for t in closed)
            and tr.get("closed_trades_pnl_sum") is not None,
            f"{len(closed)} closed trades",
        )
        _check(
            "frontend_pnl_equals_canonical",
            abs(float(tr.get("realized_pnl") or 0) - float(tr.get("closed_trades_pnl_sum") or 0)) < 0.005
            and abs(float(tr.get("realized_pnl") or 0) - float(ov.get("realized_pnl") or 0)) < 0.000001,
            f"realized={tr.get('realized_pnl')} sum={tr.get('closed_trades_pnl_sum')}",
        )
        # 23 V1.2: risk reasons visible (typed MAX_POSITIONS / CONSECUTIVE_LOSS_COOLDOWN)
        de = proj2.decisions()
        reasons = set((de.get("risk", {}) or {}).get("reason_distribution", {}) or {})
        _check(
            "real_risk_reason_projection",
            bool(reasons & {"MAX_POSITIONS", "CONSECUTIVE_LOSS_COOLDOWN"}),
            str(sorted(reasons)),
        )
        # 24 V1.2: SPA hash-router routes exist for all 9 tabs
        html = webui_mod.INDEX_HTML
        tabs = ("overview", "funnel", "agents", "strategies", "assets", "decisions", "trades", "reports", "replay")
        _check(
            "hash_router_9_routes",
            all(f'data-t="{t}"' in html for t in tabs) and "TABS=" in html and "hashchange" in html,
        )
        # 25 V1.2: unknown-hash fallback present
        _check("unknown_hash_fallback", "location.replace(" in html and "#overview" in html)
        # 26 V1.2: no fixture leakage in campaign-served payloads
        leak = json.dumps({"agents": proj2.agent_timeline(), "decisions": de, "trades": tr})
        _check("no_fixture_leakage", "demo" not in leak.lower() and "fixture" not in leak.lower())
        # 27 V1.2: browser E2E suite exists and covers the §19 sequence
        e2e = Path("tests/e2e/test_browser_v1_2.py")
        e2e_src = e2e.read_text(encoding="utf-8") if e2e.exists() else ""
        _check(
            "browser_e2e_suite",
            bool(e2e_src)
            and all(
                m in e2e_src
                for m in ("go_back", "go_forward", "reload", "auto", "console", "#trades", "tr-closed")
            ),
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
