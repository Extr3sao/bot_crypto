from __future__ import annotations

import json
from pathlib import Path
from urllib.request import urlopen

from trading_bot.demo.paper_multi_agent import (
    DecisionToCandidateAdapter,
    create_dashboard_server,
    run_fixture_demo,
)


def test_fixture_demo_is_deterministic_and_paper_only(tmp_path: Path) -> None:
    first = run_fixture_demo(output_dir=tmp_path / "first")
    second = run_fixture_demo(output_dir=tmp_path / "second")

    first_payload = json.loads(first.report_json.read_text(encoding="utf-8"))
    second_payload = json.loads(second.report_json.read_text(encoding="utf-8"))
    assert first_payload == second_payload
    assert first_payload["mode"] == "PAPER"
    assert first_payload["live_disabled"] is True
    assert first_payload["real_broker_calls"] == 0
    assert first_payload["private_exchange_calls"] == 0
    assert first_payload["live_calls"] == 0
    assert first_payload["false_success"] == 0
    assert first_payload["no_trade"] >= 1
    assert first_payload["decisions_selected"] >= 1
    assert first_payload["risk_rejects"] >= 1
    assert first_payload["paper_trades"] >= 1
    assert first_payload["closed_trades"] >= 1


def test_fixture_report_contains_ma_trace_and_run_reports(tmp_path: Path) -> None:
    result = run_fixture_demo(output_dir=tmp_path)
    payload = json.loads(result.report_json.read_text(encoding="utf-8"))
    assert result.report_markdown.exists()
    assert payload["run_id"] == "demo-paper-01-fixture"
    assert payload["trace_id"] == "trace-demo-paper-01-fixture"
    assert any(item.get("verifier") == "VERIFIED" for item in payload["decisions"])
    assert any(item.get("outcome") == "NO_TRADE" for item in payload["decisions"])
    assert any(event["event"] == "paper.position_closed" for event in payload["events"])


def test_dashboard_is_read_only(tmp_path: Path) -> None:
    result = run_fixture_demo(output_dir=tmp_path / "reports")
    server = create_dashboard_server(result.state, port=0)
    try:
        # ThreadingHTTPServer assigns an ephemeral port for port=0.
        server.port = server._server.server_port
        server.start()
        with urlopen(f"{server.url}/api/status") as response:
            payload = json.loads(response.read().decode("utf-8"))
        assert payload["mode"] == "PAPER"
        assert payload["live_disabled"] is True
        assert payload["broker_calls"] >= 1
        try:
            urlopen(f"{server.url}/api/order", timeout=2)
        except Exception as exc:
            assert "HTTP Error 404" in str(exc)
        else:
            raise AssertionError("dashboard exposed an execution endpoint")
    finally:
        server.stop()


def test_adapter_is_exported() -> None:
    assert DecisionToCandidateAdapter().verifier.version == "decision-package-verifier-v3"
