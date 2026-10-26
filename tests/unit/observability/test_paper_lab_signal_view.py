"""WP-SIGNAL-001 — the console must show the stream without being able to change it.

What is asserted here is the operator-facing contract of the existing dashboard:

* `/api/signals` answers GET and nothing else, binds to loopback and never writes;
* the page limit is bounded by the server, not by whoever types the URL;
* filters select on the dimensions the issue names (symbol / strategy / stage);
* the state label is derived from evidence: a stream that stopped is `STALE` or
  `DOWN`, never `LIVE`, and a run with no stream is `ABSENT` rather than empty-but-ok;
* the raw JSON and the rendered fragment agree, because both come from the same
  payload.
"""

from __future__ import annotations

import http.client
import importlib.util
import json
import socket
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.autonomous.signals import (  # noqa: E402
    DataQuality,
    SignalEvent,
    SignalKind,
    SignalLedger,
    SignalSource,
    SignalStage,
    signal_id_for,
)

SCRIPT = REPO / "scripts" / "paper_lab_dashboard.py"


def _load_dashboard() -> Any:
    spec = importlib.util.spec_from_file_location("paper_lab_dashboard_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DASH = _load_dashboard()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _event(index: int, *, symbol: str = "BTC/USDT", stage: str = SignalStage.SHADOW.value) -> SignalEvent:
    decision_id = f"dec-{index}"
    return SignalEvent(
        signal_id=signal_id_for(
            run_id="run-test",
            decision_id=decision_id,
            strategy_id="ema_crossover@5m",
            stage=stage,
            bar_close_ms=1_700_000_000_000 + index,
            direction="LONG",
        ),
        run_id="run-test",
        decision_id=decision_id,
        symbol=symbol,
        venue="binance",
        timeframe="5m",
        strategy_id="ema_crossover@5m",
        strategy_version="ema_crossover@5m",
        bar_close_time_ms=1_700_000_000_000 + index,
        decision_time_ms=1_700_000_001_000 + index,
        direction="LONG",
        stage=stage,
        kind=SignalKind.ALPHA.value,
        reason="COST_KILLED",
        gross_edge_bps=4.0,
        estimated_cost_bps=23.5,
        net_edge_bps=-19.5,
        risk_state="NOT_EVALUATED",
        data_quality=DataQuality.OK.value,
        source=SignalSource.REAL.value,
        order_created=stage == SignalStage.PAPER.value,
        created_at_ms=1_700_000_002_000 + index,
    )


@pytest.fixture()
def run_dir(tmp_path: Path) -> Path:
    path = tmp_path / "paper" / "run-test"
    ledger = SignalLedger(path)
    for index in range(7):
        ledger.append(_event(index, symbol="BTC/USDT" if index % 2 == 0 else "ETH/USDT"))
    (path / "outcomes.jsonl").write_text(
        json.dumps(
            {
                "decision_id": "dec-0",
                "mode": "SHADOW_TRADE",
                "horizon_minutes": 5.0,
                "net_hypothetical_bps": -21.5,
                "gross_hypothetical_bps": 2.0,
                "outcome_time_ms": 1_700_000_400_000,
                "created_at_ms": 1_700_000_500_000,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _args(tmp_path: Path, run_dir: Path) -> Any:
    return DASH.parse_args(
        [
            "--lab-root",
            str(tmp_path / "lab"),
            "--paper-root",
            str(run_dir.parent),
            "--run-id",
            run_dir.name,
        ]
    )


@contextmanager
def _serving(tmp_path: Path, run_dir: Path) -> Iterator[int]:
    args = _args(tmp_path, run_dir)
    httpd = DASH.ThreadingHTTPServer(("127.0.0.1", 0), DASH.make_handler(args))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield int(httpd.server_address[1])
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _get(port: int, path: str) -> tuple[int, str, str]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", path)
    response = conn.getresponse()
    body = response.read().decode("utf-8")
    content_type = response.getheader("Content-Type") or ""
    conn.close()
    return response.status, content_type, body


def test_api_signals_serves_events_with_their_outcome(tmp_path: Path, run_dir: Path) -> None:
    with _serving(tmp_path, run_dir) as port:
        status, content_type, body = _get(port, "/api/signals?limit=10")
    assert status == 200
    assert "application/json" in content_type
    payload = json.loads(body)
    assert payload["schema_version"] == "paper-signals-view-v1"
    assert payload["read_only"] is True
    assert payload["available"] is True
    assert payload["page"]["returned"] == 7
    assert payload["stats"]["by_stage"]["SHADOW"] == 7
    # Newest first, and the resolved outcome is joined from the outcomes ledger
    # rather than merged into the append-only signal rows.
    assert payload["events"][0]["decision_id"] == "dec-6"
    oldest = next(e for e in payload["events"] if e["decision_id"] == "dec-0")
    assert oldest["outcome"]["net_hypothetical_bps"] == pytest.approx(-21.5)
    assert payload["integrity"]["ok"] is True
    # RFC-PAPER-008 — SHADOW outcomes and PAPER fills are counted apart, and the
    # provenance of the stream is visible without reading the run directory.
    assert payload["stats"]["by_source"] == {"REAL": 7}
    assert payload["outcomes"]["resolved"] == 1
    assert payload["outcomes"]["pending"] == 6
    assert payload["outcomes"]["by_mode"] == {"SHADOW_TRADE": 1}
    assert payload["outcomes"]["net_bps_mean_by_mode"]["SHADOW_TRADE"] == pytest.approx(-21.5)


def test_limit_is_bounded_by_the_server(tmp_path: Path, run_dir: Path) -> None:
    with _serving(tmp_path, run_dir) as port:
        _, _, body = _get(port, "/api/signals?limit=99999")
    payload = json.loads(body)
    assert payload["page"]["limit"] == DASH.MAX_PAGE_LIMIT
    assert payload["limit_bounds"] == {"default": DASH.DEFAULT_PAGE_LIMIT, "max": DASH.MAX_PAGE_LIMIT}


def test_filters_and_cursor_are_honoured(tmp_path: Path, run_dir: Path) -> None:
    with _serving(tmp_path, run_dir) as port:
        _, _, btc = _get(port, "/api/signals?symbol=BTC%2FUSDT&limit=10")
        _, _, first = _get(port, "/api/signals?limit=3")
    assert json.loads(btc)["page"]["returned"] == 4
    page = json.loads(first)
    assert page["page"]["returned"] == 3
    cursor = page["page"]["next_cursor"]
    assert cursor is not None
    with _serving(tmp_path, run_dir) as port:
        _, _, second = _get(port, f"/api/signals?limit=10&cursor={cursor}")
    older = json.loads(second)["events"]
    assert len(older) == 4
    assert not ({e["signal_id"] for e in page["events"]} & {e["signal_id"] for e in older})


def test_rendered_fragment_matches_the_payload(tmp_path: Path, run_dir: Path) -> None:
    with _serving(tmp_path, run_dir) as port:
        status, content_type, html = _get(port, "/signals")
        _, _, api = _get(port, "/api/signals")
    assert status == 200
    assert "text/html" in content_type
    assert "SIGNALS" in html
    assert "ema_crossover@5m" in html
    assert "COST_KILLED" in html
    assert json.loads(api)["stats"]["records"] == 7


def test_mutating_verbs_are_still_refused(tmp_path: Path, run_dir: Path) -> None:
    with _serving(tmp_path, run_dir) as port:
        for method in ("POST", "PUT", "DELETE", "PATCH"):
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            conn.request(method, "/api/signals")
            response = conn.getresponse()
            assert response.status == 405
            assert b"read-only" in response.read()
            conn.close()


def test_missing_stream_is_absent_not_empty_success(tmp_path: Path) -> None:
    args = DASH.parse_args(
        ["--lab-root", str(tmp_path / "lab"), "--paper-root", str(tmp_path / "paper-empty")]
    )
    payload = DASH.signals_payload(args, {})
    assert payload["available"] is False
    assert payload["state"] == "ABSENT"
    assert payload["events"] == []


def test_state_labels_follow_the_evidence(tmp_path: Path, run_dir: Path) -> None:
    args = _args(tmp_path, run_dir)
    down = DASH.signals_payload(args, {}, status={"system": {"running": False}})
    assert down["state"] == "DOWN"
    assert "not running" in down["state_reason"]

    # A stale newest event with a running lab is reported as STALE, never LIVE.
    stale = DASH.signals_payload(
        args, {}, status={"system": {"running": True, "heartbeat_is_stale": False}}
    )
    assert stale["state"] == "STALE"

    live_status = {"system": {"running": True, "heartbeat_is_stale": True}}
    assert DASH.signals_payload(args, {}, status=live_status)["state"] == "STALE"


def test_page_embeds_the_signal_board(tmp_path: Path, run_dir: Path) -> None:
    args = _args(tmp_path, run_dir)
    payload = DASH.status_payload(args)
    page = DASH.render_page(payload)
    assert 'id="signals"' in page
    assert "no analysis" in page  # nothing is invented before the analyst runs
    assert "/api/signals" in page


def test_the_page_honours_the_filter_it_was_asked_for(tmp_path: Path, run_dir: Path) -> None:
    """A submit that changes the URL must change the board on the same response.

    Observed on 2026-10-26: ``?symbol=BTC/USDT`` rendered every asset, and the
    filtered board only appeared after the auto-refresh fetched ``/signals``.
    """
    with _serving(tmp_path, run_dir) as port:
        status, _, body = _get(port, "/?symbol=BTC%2FUSDT")
    assert status == 200
    assert "showing 4/4" in body, body[body.find('showing') - 60 : body.find('showing') + 20]
    assert "ETH/USDT" not in body


def test_page_states_the_economic_verdict_while_nothing_is_admitted(
    tmp_path: Path, run_dir: Path
) -> None:
    """§6.6 — live signals must not read as a validated product."""
    args = _args(tmp_path, run_dir)
    payload = DASH.status_payload(args)
    page = DASH.render_page(payload)
    assert "REJECTED_ALPHA — EXPERIMENTAL PAPER, NOT VALIDATED" in page
    assert 'id="eligibility"' in page

    payload["strategy_lab"] = {**(payload.get("strategy_lab") or {}), "admitted_for_paper": ["x@5m"]}
    assert "REJECTED_ALPHA" not in DASH.render_page(payload), (
        "the banner is a statement about admission, not a decoration"
    )


def test_api_analysis_reports_missing_coverage_honestly(tmp_path: Path, run_dir: Path) -> None:
    with _serving(tmp_path, run_dir) as port:
        status, content_type, body = _get(port, "/api/analysis")
    assert status == 200
    assert "application/json" in content_type
    payload = json.loads(body)
    assert payload["read_only"] is True
    assert payload["authority_over_orders"] is False
    assert payload["signals_total"] == 7
    assert payload["coverage"]["covered"] == 0
    assert payload["coverage"]["coverage_pct"] == 0.0
    assert payload["state"] == "NOT_RUN"  # the sidecar never ran: not the same as empty


def test_api_analysis_counts_not_configured_separately(tmp_path: Path, run_dir: Path) -> None:
    from trading_bot.autonomous.analysis import (
        PROMPT_VERSION,
        AnalysisStore,
        SignalAnalyst,
    )

    store = AnalysisStore(run_dir)
    analyst = SignalAnalyst(store=store, provider=None, prompt_version=PROMPT_VERSION)
    ledger = SignalLedger(run_dir)
    for row in list(ledger.read(limit=3).events):
        analyst.analyze(row)
    (run_dir / "AI_ANALYST_HEARTBEAT.json").write_text(
        json.dumps({"provider_configured": False, "passed_at_ms": 1_700_000_000_000}),
        encoding="utf-8",
    )
    with _serving(tmp_path, run_dir) as port:
        _, _, body = _get(port, "/api/analysis")
    payload = json.loads(body)
    assert payload["state"] == "NOT_CONFIGURED"
    assert payload["provider_configured"] is False
    assert payload["coverage"]["not_configured"] == 3
    assert payload["coverage"]["analysed"] == 0
    # An analysis-free signal is labelled as such on the board, not left blank.
    with _serving(tmp_path, run_dir) as port:
        _, _, html = _get(port, "/signals")
    assert "NOT_CONFIGURED" in html
