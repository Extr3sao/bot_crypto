"""Frontend observability tests: projections over real artifacts, read-only boundary.

The projections layer must be pure read/serialize: every number originates
in a committed runtime artifact and the server must reject all mutations.
V1.2 adds source-authority resolution (explicit root > campaign-api >
unambiguous discovery > fail loud), staleness visibility, campaign-scoped
report isolation and a correct hash router (browser E2E lives in tests/e2e).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from trading_bot.frontend_observability import projections
from trading_bot.frontend_observability.projections import AmbiguousSource, SourceNotConfigured
from trading_bot.frontend_observability.server import FrontendHandler, create_server

_CAMPAIGN_STATE = {
    "schema_version": 1,
    "campaign_id": "poc01-test-001",
    "campaign_status": "ACTIVE",
    "campaign_start": "2026-09-07T00:00:00+00:00",
    "provider": "ccxt",
    "equity": 10123.5,
    "initial_equity": 10000.0,
    "realized_pnl": 123.5,
    "unrealized_pnl": -4.25,
    "fees": 1.0,
    "last_market_timestamp": 1786003540000,
    "last_successful_scan_time": "2026-09-07T00:05:00+00:00",
    "run_id": "run-test",
    "open_positions": {"BTC/USDT": {"qty": 0.1}},
    "closed_trades": [
        {"asset": "ETH/USDT", "strategy": "Momentum", "pnl": 123.5, "entry": 2510.0, "exit": 2540.0}
    ],
    "daily": {
        "2026-09-07": {
            "trades": 1,
            "realized_pnl": 123.5,
            "valid": True,
        }
    },
    "funnel": {
        "MARKET_SCANS": 10,
        "TRADE_PROPOSALS": 4,
        "DEBATES": 3,
        "DECISION_SELECTED": 2,
        "VERIFIER_VERIFIED": 2,
        "CANDIDATE_ADMITTED": 2,
        "RISK_ACCEPT": 1,
        "RISK_REJECT": 1,
        "NO_TRADE": 3,
        "PAPER_OPEN": 1,
        "PAPER_CLOSE": 1,
    },
    "by_strategy": {
        "momentum": {
            "evaluations": 9,
            "proposals": 2,
            "selected": 1,
            "trades": 5,
            "wins": 3,
            "losses": 2,
            "net_pnl": 12.0,
            "expectancy": 0.4,
            "profit_factor": 1.8,
        },
        "trend": {"trades": 2, "net_pnl": -1.0},
    },
    "strategies": ["momentum", "trend"],
    "by_asset": {
        "BTC/USDT": {"trades": 4, "net_pnl": 9.0},
    },
    "assets": ["BTC/USDT"],
    "decision_metrics": {"selected": 2, "rejected": 1, "no_trade": 3},
    "risk_metrics": {
        "accepts": 1,
        "rejects": 1,
        "rejection_rate": 0.5,
        "reason_distribution": {"MAX_POSITIONS": 1},
    },
    "reasons": {"NO_PROPOSAL": 2, "UNRESOLVED_CONFLICT": 1},
    "debate_metrics": {"debates": 3, "critiques": 5, "counter_evidence": 1, "material_dissent": 1},
    "last_processed_decision_ids": ["decision:abc"],
}


@pytest.fixture()
def bound_source(tmp_path: Path):
    """Bind projections to a hermetic reports root for the duration of a test."""
    root = tmp_path / "reports"
    camp = root / "paper-observation-01" / "poc01-test-001"
    camp.mkdir(parents=True)
    (camp / "CAMPAIGN_STATE.json").write_text(json.dumps(_CAMPAIGN_STATE), encoding="utf-8")
    (camp / "CAMPAIGN_REPORT.json").write_text(json.dumps({"campaign_id": "poc01-test-001"}), encoding="utf-8")
    day = camp / "2026-09-07"
    day.mkdir()
    (day / "DAILY_REPORT.json").write_text("{}", encoding="utf-8")
    (day / "DAILY_REPORT.md").write_text("# daily", encoding="utf-8")
    projections.configure_source(reports_root=root)
    yield root
    projections.configure_source(reports_root=None, campaign_api=None)


@pytest.fixture(autouse=True)
def _auto_source(bound_source: Path):
    yield


@pytest.fixture()
def server(bound_source: Path) -> ThreadingHTTPServer:
    srv = create_server("127.0.0.1", 0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()


def _base(server: ThreadingHTTPServer) -> str:
    return f"http://127.0.0.1:{server.server_port}"


def _get(server: ThreadingHTTPServer, path: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(f"{_base(server)}{path}", timeout=5) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


# ----------------------------------------------------------------------
# projection correctness over canonical artifacts
# ----------------------------------------------------------------------


def test_overview_projection_has_no_authority(bound_source: Path) -> None:
    payload = projections.overview()
    assert isinstance(payload, dict)
    assert "mode" in payload
    assert payload["mode"] == "PAPER"
    assert payload["data"] == "REAL_PUBLIC_MARKET"
    assert payload["campaign_id"] == "poc01-test-001"
    assert payload["realized_pnl"] == 123.5
    assert payload["reports_root"] == str(bound_source.resolve())


def test_overview_source_staleness_visible(bound_source: Path) -> None:
    payload = projections.overview()
    assert payload["data_source"] in ("ARTIFACT_SNAPSHOT", "POC01_API+ARTIFACTS")
    assert payload["last_persisted_at"]
    assert payload["stale_age_seconds"] is not None
    assert payload["stale"] is False  # just written
    assert payload["stale_threshold_seconds"] == projections.STALE_AFTER_SECONDS


def test_stale_detection_after_threshold(bound_source: Path) -> None:
    state_path = bound_source / "paper-observation-01" / "poc01-test-001" / "CAMPAIGN_STATE.json"
    old = (os.stat(state_path).st_mtime) - (projections.STALE_AFTER_SECONDS + 600)
    os.utime(state_path, (old, old))
    info = projections.source_info()
    assert info["stale"] is True
    assert info["stale_marker"] == "STALE_DATA"
    assert info["stale_age_seconds"] > projections.STALE_AFTER_SECONDS


def test_funnel_conversions_are_pure_ratios(bound_source: Path) -> None:
    payload = projections.funnel()
    counts = payload["counts"]
    assert counts["PAPER_OPEN"] == 1 and counts["PAPER_CLOSE"] == 1
    assert counts["MARKET_SCANS"] == 10
    for key, value in payload["conversions"].items():
        src, dst = key.split("->")
        if counts[src] > 0:
            assert value == round(counts[dst] / counts[src], 4) or value is None
        else:
            assert value is None


def test_strategies_marks_insufficient_samples(bound_source: Path) -> None:
    payload = projections.strategies()
    by_name = {s["strategy"]: s for s in payload["strategies"]}
    assert set(by_name) >= {"momentum", "trend"}
    assert by_name["momentum"]["sample"] == "INSUFFICIENT_SAMPLE"  # 5 trades < 30
    assert by_name["trend"]["sample"] == "INSUFFICIENT_SAMPLE"


def test_trades_view_is_passthrough(bound_source: Path) -> None:
    payload = projections.trades()
    assert "note" in payload
    assert payload["realized_pnl"] == _CAMPAIGN_STATE["realized_pnl"]
    assert len(payload["closed_trades"]) == 1
    row = payload["closed_trades"][0]
    original = _CAMPAIGN_STATE["closed_trades"][0]
    for key, value in original.items():
        assert row[key] == value, f"canonical field mutated: {key}"
    assert row["opened_at"] == "NOT_PERSISTED"
    assert row["closed_at"] == "NOT_PERSISTED"  # fixture has no closed_at_ms
    assert isinstance(payload["open_positions"], list)
    assert payload["open_positions"][0]["symbol"] == "BTC/USDT"


def test_replay_status_honest(bound_source: Path) -> None:
    payload = projections.replay_status()
    assert payload["RUN_REPLAY"] in ("FUNCTIONAL", "PARTIAL")
    for step in payload["chain"]:
        assert isinstance(step["available"], bool)


def test_report_jail_rejects_escape(bound_source: Path) -> None:
    payload = projections.report_content("../../pyproject.toml")
    assert "error" in payload


def test_agent_timeline_no_fixture_leakage(bound_source: Path) -> None:
    payload = projections.agent_timeline()
    assert payload["source"].startswith("CAMPAIGN_STATE")
    assert payload["per_event_messages"] == "NOT_PERSISTED"
    assert payload["aggregates"]["counter_evidence"] == 1
    # never falls back to the legacy demo RUN_REPORT
    assert "demo" not in json.dumps(payload).lower()


def test_decisions_expose_risk_reasons(bound_source: Path) -> None:
    payload = projections.decisions()
    assert payload["campaign_aggregates"]["selected"] == 2
    assert payload["risk"]["reason_distribution"] == {"MAX_POSITIONS": 1}
    assert payload["block_reasons"] == {"NO_PROPOSAL": 2, "UNRESOLVED_CONFLICT": 1}
    assert payload["per_decision_detail"] == "NOT_PERSISTED"


def test_report_list_campaign_isolation(bound_source: Path) -> None:
    # a legacy demo report sits in the same root — it must NOT be surfaced
    demo = bound_source / "demo-paper-01"
    demo.mkdir()
    (demo / "RUN_REPORT.json").write_text("{}", encoding="utf-8")
    items = projections.report_list()
    assert items, "campaign reports must be listed"
    assert all(i["campaign_id"] == "poc01-test-001" for i in items)
    names = {i["name"] for i in items}
    assert "RUN_REPORT.json" not in names  # the legacy demo file
    assert "CAMPAIGN_REPORT.json" in names
    assert "DAILY_REPORT.json" in names


def test_daily_series_projection(bound_source: Path) -> None:
    payload = projections.daily_series()
    assert payload["source"] == "CAMPAIGN_STATE daily aggregates"
    assert len(payload["days"]) == 1
    day = payload["days"][0]
    assert day["date"] == "2026-09-07"
    assert day["trades"] == 1
    assert day["day_ge_3"] is False
    assert day["realized_pnl"] == 123.5
    assert day["valid"] is True


# ----------------------------------------------------------------------
# source authority model (§5): explicit > api > discovery > fail loud
# ----------------------------------------------------------------------


def test_explicit_root_wins_without_discovery(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(projections, "candidate_report_roots", lambda: [])
    root = tmp_path / "explicit-root"
    root.mkdir()
    projections.configure_source(reports_root=root)
    assert projections.reports_root() == root.resolve()


def test_discovery_unconfigured_fails_loud(monkeypatch) -> None:
    monkeypatch.setattr(projections, "candidate_report_roots", lambda: [])
    projections.configure_source(reports_root=None, campaign_api=None)
    with pytest.raises(SourceNotConfigured):
        projections.reports_root()


def test_discovery_ambiguous_fails_loud(monkeypatch, tmp_path: Path) -> None:
    cands = []
    for name in ("root-a", "root-b"):
        d = tmp_path / name / "reports"
        (d / "paper-observation-01" / "c").mkdir(parents=True)
        (d / "paper-observation-01" / "c" / "CAMPAIGN_STATE.json").write_text("{}", encoding="utf-8")
        cands.append(d)
    monkeypatch.setattr(projections, "candidate_report_roots", lambda: cands)
    projections.configure_source(reports_root=None, campaign_api=None)
    with pytest.raises(AmbiguousSource) as excinfo:
        projections.reports_root()
    assert "FAIL_AMBIGUOUS_SOURCE" in str(excinfo.value)


def test_discovery_single_root_unambiguous(monkeypatch, tmp_path: Path) -> None:
    d = tmp_path / "only" / "reports"
    (d / "paper-observation-01" / "c").mkdir(parents=True)
    (d / "paper-observation-01" / "c" / "CAMPAIGN_STATE.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(projections, "candidate_report_roots", lambda: [d])
    projections.configure_source(reports_root=None, campaign_api=None)
    assert projections.reports_root() == d


def test_campaign_api_unreachable_falls_back_to_artifacts(bound_source: Path) -> None:
    projections.configure_source(
        reports_root=bound_source, campaign_api="http://127.0.0.1:1/api/campaign"  # nothing listens
    )
    payload = projections.overview()
    assert payload["campaign_id"] == "poc01-test-001"  # artifact snapshot served
    assert payload["data_source"] == "ARTIFACT_SNAPSHOT"
    assert payload["api_error"]  # failure is visible, never silent
    assert payload["last_persisted_at"]


def test_campaign_api_live_overlay(bound_source: Path) -> None:
    api_payload = {
        "campaign_id": "poc01-live-999",
        "campaign_state": "ACTIVE",
        "runtime_health": {"provider_status": "OK"},
        "funnel": {"MARKET_SCANS": 999},
        "performance": {"net_pnl": 42.0},
        "elapsed_hours": 1.5,
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = json.dumps(api_payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args: object) -> None:
            return

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        projections.configure_source(
            reports_root=bound_source,
            campaign_api=f"http://127.0.0.1:{httpd.server_port}/api/campaign",
        )
        payload = projections.overview()
        assert payload["campaign_id"] == "poc01-live-999"  # API identity wins for summary
        assert payload["provider_status"] == "OK"
        assert payload["data_source"] == "POC01_API+ARTIFACTS"
        assert payload["campaign_api_summary"]["funnel"]["MARKET_SCANS"] == 999
        # canonical accounting still comes from artifacts, not the API overlay
        assert payload["realized_pnl"] == 123.5
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_set_reports_root_redirects_projections(tmp_path: Path) -> None:
    camp = tmp_path / "paper-observation-01" / "poc01-x"
    camp.mkdir(parents=True)
    (camp / "CAMPAIGN_STATE.json").write_text(json.dumps(_CAMPAIGN_STATE), encoding="utf-8")
    original = projections.reports_root()
    try:
        projections.set_reports_root(tmp_path)
        assert projections.reports_root() == tmp_path.resolve()
        payload = projections.overview()
        assert payload["campaign_id"] == "poc01-test-001"
        assert payload["reports_root"] == str(tmp_path.resolve())
        names = [r["name"] for r in projections.report_list()]
        assert "CAMPAIGN_STATE.json" in names
    finally:
        projections.set_reports_root(original)


def test_trades_of_robust() -> None:
    assert projections._trades_of({"trades": 5}) == 5
    assert projections._trades_of({"wins": 2, "losses": 1}) == 3
    assert projections._trades_of({}) == 0


def test_daily_series_without_state(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(projections, "_campaign_state_path", lambda: tmp_path / "missing.json")
    payload = projections.daily_series()
    assert payload["days"] == []  # no artifacts -> honest empty series


# ----------------------------------------------------------------------
# server: routes, read-only boundary, favicon silence
# ----------------------------------------------------------------------


def test_server_readonly_boundary(server: ThreadingHTTPServer) -> None:
    for route in ("/", "/overview", "/funnel", "/agents", "/strategies", "/assets", "/decisions", "/trades", "/reports", "/replay", "/source", "/daily"):
        status, _ = _get(server, route)
        assert status == 200, route
    # every POST route is rejected with 405
    for route in ("/", "/overview", "/trades"):
        req = urllib.request.Request(f"{_base(server)}{route}", data=b"{}", method="POST")
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(req, timeout=5)
        assert excinfo.value.code == 405


def test_server_reports_content_endpoint(server: ThreadingHTTPServer) -> None:
    status, body = _get(server, "/reports")
    assert status == 200
    payload = json.loads(body) if body.startswith(b"{") else None
    assert payload is None or "reports" in payload


def test_favicon_is_silent(server: ThreadingHTTPServer) -> None:
    status, _ = _get(server, "/favicon.ico")
    assert status == 204  # no 404 console noise in the browser


def test_unknown_route_404(server: ThreadingHTTPServer) -> None:
    status, _ = _get(server, "/nope")
    assert status == 404


def test_handler_has_no_write_paths() -> None:
    # The only mutating verb implemented is do_POST -> 405; no do_PUT/do_DELETE exist.
    assert not hasattr(FrontendHandler, "do_PUT")
    assert not hasattr(FrontendHandler, "do_DELETE")
    assert not hasattr(FrontendHandler, "do_PATCH")


# ----------------------------------------------------------------------
# V1.1 — SPA index, daily series route
# ----------------------------------------------------------------------


def test_index_serves_spa(server: ThreadingHTTPServer) -> None:
    status, body = _get(server, "/")
    assert status == 200
    html = body.decode("utf-8")
    assert "POC01 · Paper Observation" in html
    assert "LIVE DISABLED" in html
    # read-only by construction: no forms, no POST method usage in the UI
    assert "<form" not in html
    assert "method=\"POST\"" not in html and "method:'POST'" not in html


def test_daily_route_json(server: ThreadingHTTPServer) -> None:
    req = urllib.request.Request(f"{_base(server)}/daily", headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        assert resp.status == 200
        payload = json.loads(resp.read())
    assert "days" in payload


# ----------------------------------------------------------------------
# DEF-FE-003 (premature server import) — lazy package imports
# ----------------------------------------------------------------------


def _subprocess(*args: str, code: str | None = None) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, *(["-c", code] if code else args)]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)


def test_package_import_is_side_effect_free() -> None:
    """DEF-FE-003: importing the package must not preload server/projections."""
    proc = _subprocess(
        code=(
            "import sys, trading_bot.frontend_observability as p;"
            "assert 'trading_bot.frontend_observability.server' not in sys.modules, 'server preloaded';"
            "assert 'trading_bot.frontend_observability.projections' not in sys.modules, 'projections preloaded';"
            "print('OK')"
        )
    )
    assert proc.returncode == 0, proc.stderr
    assert "OK" in proc.stdout


def test_module_execution_no_runtime_warning() -> None:
    """`python -m ...server --help` must be warning-free and expose --reports-root."""
    proc = _subprocess("-m", "trading_bot.frontend_observability.server", "--help")
    assert proc.returncode == 0, proc.stderr
    assert "RuntimeWarning" not in proc.stderr, proc.stderr
    assert "--reports-root" in proc.stdout
    assert "--campaign-api" in proc.stdout


def test_lazy_package_reexports_resolve() -> None:
    import trading_bot.frontend_observability as pkg

    assert callable(pkg.create_server)
    assert callable(pkg.main)
    assert callable(pkg.overview)
    assert "create_server" in dir(pkg)
    with pytest.raises(AttributeError):
        _ = pkg.definitely_not_an_export  # intentional attribute probe
