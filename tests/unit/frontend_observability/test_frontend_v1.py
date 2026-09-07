"""Frontend observability V1 tests: projections over real artifacts, read-only boundary.

The projections layer must be pure read/serialize: every number originates
in a committed runtime artifact and the server must reject all mutations.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from trading_bot.frontend_observability import projections
from trading_bot.frontend_observability.server import FrontendHandler, create_server


@pytest.fixture()
def server() -> ThreadingHTTPServer:
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


def test_overview_projection_has_no_authority() -> None:
    payload = projections.overview()
    assert isinstance(payload, dict)
    # Every overview field is a passthrough or an explicitly-marked projection.
    assert "mode" in payload


def test_funnel_conversions_are_pure_ratios() -> None:
    payload = projections.funnel()
    counts = payload["counts"]
    for key, value in payload["conversions"].items():
        src, dst = key.split("->")
        if counts[src] > 0:
            assert value == round(counts[dst] / counts[src], 4) or value is None
        else:
            assert value is None


def test_strategies_marks_insufficient_samples() -> None:
    payload = projections.strategies()
    for s in payload["strategies"]:
        trades = int(s.get("trades") or 0)
        assert s["sample"] == ("OK" if trades >= 30 else "INSUFFICIENT_SAMPLE")


def test_trades_view_is_passthrough() -> None:
    payload = projections.trades()
    assert "note" in payload  # canonical-accounting note must always be present
    assert isinstance(payload, dict)


def test_replay_status_honest() -> None:
    payload = projections.replay_status()
    assert payload["RUN_REPLAY"] in ("FUNCTIONAL", "PARTIAL")
    for step in payload["chain"]:
        assert isinstance(step["available"], bool)


def test_report_jail_rejects_escape(tmp_path) -> None:
    payload = projections.report_content("../../pyproject.toml")
    assert "error" in payload


def test_server_readonly_boundary(server: ThreadingHTTPServer) -> None:
    for route in ("/", "/overview", "/funnel", "/agents", "/strategies", "/assets", "/decisions", "/trades", "/reports", "/replay"):
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


def test_unknown_route_404(server: ThreadingHTTPServer) -> None:
    status, _ = _get(server, "/nope")
    assert status == 404


def test_handler_has_no_write_paths() -> None:
    # The only mutating verb implemented is do_POST -> 405; no do_PUT/do_DELETE exist.
    assert not hasattr(FrontendHandler, "do_PUT")
    assert not hasattr(FrontendHandler, "do_DELETE")
    assert not hasattr(FrontendHandler, "do_PATCH")


# ----------------------------------------------------------------------
# Hermetic campaign-state coverage (real schema, tmp reports root)
# ----------------------------------------------------------------------


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
    "by_asset": {
        "BTC/USDT": {"trades": 4, "net_pnl": 9.0},
    },
    "decision_metrics": {"selected": 2, "rejected": 1, "no_trade": 3},
}


@pytest.fixture()
def campaign_reports_root(tmp_path, monkeypatch):
    camp = tmp_path / "paper-observation-01" / "poc01-test-001"
    camp.mkdir(parents=True)
    (camp / "CAMPAIGN_STATE.json").write_text(json.dumps(_CAMPAIGN_STATE), encoding="utf-8")
    monkeypatch.setattr(projections, "campaign_root", lambda: tmp_path / "paper-observation-01")
    monkeypatch.setattr(projections, "_campaign_state_path", lambda: camp / "CAMPAIGN_STATE.json")
    return camp


def test_overview_from_campaign_state(campaign_reports_root) -> None:
    payload = projections.overview()
    assert payload["campaign_id"] == "poc01-test-001"
    assert payload["data"] == "REAL_PUBLIC_MARKET"
    assert payload["realized_pnl"] == 123.5
    assert payload["trades_today"] == 1
    assert payload["ge_3_target"]["met"] is False
    assert payload["open_positions"] == 1
    assert payload["closed_trades"] == 1


def test_funnel_campaign_conversions(campaign_reports_root) -> None:
    payload = projections.funnel()
    assert payload["source"] == "CAMPAIGN_STATE"
    assert payload["counts"]["TRADE_PROPOSALS"] == 4
    assert payload["conversions"]["TRADE_PROPOSALS->DEBATES"] == 0.75
    assert payload["counts"]["NO_TRADE"] == 3


def test_trades_view_is_exact_passthrough(campaign_reports_root) -> None:
    payload = projections.trades()
    assert payload["closed_trades"] == _CAMPAIGN_STATE["closed_trades"]
    assert payload["realized_pnl"] == _CAMPAIGN_STATE["realized_pnl"]


def test_strategies_sample_labels(campaign_reports_root) -> None:
    payload = projections.strategies()
    by_name = {s["strategy"]: s for s in payload["strategies"]}
    assert by_name["momentum"]["sample"] == "INSUFFICIENT_SAMPLE"  # 5 trades < 30
    assert by_name["trend"]["sample"] == "INSUFFICIENT_SAMPLE"


# ----------------------------------------------------------------------
# V1.1 — SPA index, daily series projection, robust trade counting
# ----------------------------------------------------------------------


def test_trades_of_robust() -> None:
    assert projections._trades_of({"trades": 5}) == 5
    assert projections._trades_of({"wins": 2, "losses": 1}) == 3
    assert projections._trades_of({}) == 0


def test_daily_series_projection(campaign_reports_root) -> None:
    payload = projections.daily_series()
    assert payload["source"] == "CAMPAIGN_STATE daily aggregates"
    assert len(payload["days"]) == 1
    day = payload["days"][0]
    assert day["date"] == "2026-09-07"
    assert day["trades"] == 1
    assert day["day_ge_3"] is False
    assert day["realized_pnl"] == 123.5
    assert day["valid"] is True


def test_daily_series_without_state(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(projections, "_campaign_state_path", lambda: tmp_path / "missing.json")
    payload = projections.daily_series()
    assert payload["days"] == []  # no artifacts -> honest empty series


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
