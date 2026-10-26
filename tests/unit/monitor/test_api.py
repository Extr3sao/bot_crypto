"""API tests (WP-TDM-02).

The server is started on an ephemeral loopback port exactly as the CLI starts it,
and driven over real HTTP. No handler is mocked: these tests exercise the same
code path a browser uses, which is what makes the read-only claim testable.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from tests.unit.monitor import helpers as h
from trading_bot.autonomous.contracts import DecisionMode
from trading_bot.monitor.api import MonitorConfig, build_server
from trading_bot.monitor.candles import Bar, StaticCandleSource

TS_NOW = int(time.time() * 1000)


def _bars(symbol: str = "BTC/USDT", n: int = 6, start: int | None = None) -> list[Bar]:
    start = start if start is not None else TS_NOW - n * h.BAR_MS
    return [
        Bar(
            time_ms=start + i * h.BAR_MS,
            open=100.0 + i,
            high=101.0 + i,
            low=99.0 + i,
            close=100.5 + i,
            volume=10.0,
            timeframe="5m",
            symbol=symbol,
            venue="BINANCE",
            is_closed=True,
            source="static-fixture",
            ingested_at="2026-10-24T07:15:00.000Z",
        )
        for i in range(n)
    ]


def _run(tmp_path: Path, *, heartbeat_ms: int | None = None) -> Path:
    traces = [
        h.make_trace(
            "dec-btc",
            proposal_payload=h.proposal(gross_bps=-4.56),
        ),
        h.make_trace(
            "dec-eth",
            symbol="ETH/USDT",
            asset="ETH",
            mode=DecisionMode.SHADOW_TRADE,
            classification="COST_KILLED",
            reason="gross 1.490bps vs cost 22.833bps",
            no_trade_kind=None,
            proposal_payload=h.proposal(gross_bps=1.49, cost_bps=22.833),
            decision_time_ms=h.TS0 + h.BAR_MS,
            market_time_ms=h.TS0,
        ),
    ]
    run_dir = h.write_run(tmp_path, traces, executions=[], environment="ccxt:binance")
    if heartbeat_ms is not None:
        payload = json.loads((run_dir / "heartbeat.json").read_text(encoding="utf-8"))
        payload["timestamp_ms"] = heartbeat_ms
        (run_dir / "heartbeat.json").write_text(json.dumps(payload), encoding="utf-8")
    return run_dir


@contextmanager
def serve(root: Path, **kwargs: Any) -> Iterator[str]:
    config = MonitorConfig(
        runs_root=root,
        candle_source=StaticCandleSource({"BTC/USDT": _bars(), "ETH/USDT": _bars("ETH/USDT")}),
    )
    server, _app = build_server(config, port=0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()


def get(base: str, path: str) -> tuple[int, dict[str, Any], dict[str, str]]:
    try:
        with urllib.request.urlopen(base + path, timeout=5) as response:
            return response.status, json.loads(response.read()), dict(response.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}"), dict(exc.headers)


def request(base: str, path: str, method: str, data: bytes = b"") -> tuple[int, dict[str, str]]:
    req = urllib.request.Request(base + path, data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, dict(response.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers)


# ---------------------------------------------------------------------------
# health / discovery
# ---------------------------------------------------------------------------


def test_health_declares_read_only_and_lists_runs(tmp_path: Path) -> None:
    _run(tmp_path)
    with serve(tmp_path) as base:
        status, body, headers = get(base, "/api/monitor/health")
    assert status == 200
    assert body["read_only"] is True
    assert body["status"] == "ok"
    assert body["runs"][0]["run_id"] == "run-a"
    assert body["runs"][0]["chain_ok"] is True
    assert body["asset_digests"], "delivered assets must be hash-verifiable"
    assert headers["Content-Type"].startswith("application/json")


def test_security_headers_are_present(tmp_path: Path) -> None:
    _run(tmp_path)
    with serve(tmp_path) as base:
        import http.client
        import urllib.parse

        url = urllib.parse.urlparse(base)
        conn = http.client.HTTPConnection(url.hostname, url.port, timeout=5)
        conn.request("GET", "/")
        response = conn.getresponse()
        body = response.read()
        headers = dict(response.headers)
        conn.close()
    assert response.status == 200
    assert b"Trading Decision Monitor" in body
    csp = headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert headers["X-Content-Type-Options"] == "nosniff"


def test_runs_endpoint_lists_run_directories(tmp_path: Path) -> None:
    _run(tmp_path)
    with serve(tmp_path) as base:
        status, body, _ = get(base, "/api/monitor/runs")
    assert status == 200
    assert [r["run_id"] for r in body["runs"]] == ["run-a"]


def test_assets_only_reports_what_the_events_contain(tmp_path: Path) -> None:
    _run(tmp_path)
    with serve(tmp_path) as base:
        _, body, _ = get(base, "/api/monitor/assets")
    assert body["symbols"] == ["BTC/USDT", "ETH/USDT"]
    assert body["venue"] == "BINANCE"
    assert body["timeframes"] == ["5m"]
    # SIGNAL_ONLY belongs to intermediate events; a decision cannot be filtered by it
    assert body["statuses"] == ["NO_TRADE", "SHADOW_OBSERVED"]


# ---------------------------------------------------------------------------
# decisions
# ---------------------------------------------------------------------------


def test_decisions_lists_one_row_per_decision_with_explicit_status(tmp_path: Path) -> None:
    _run(tmp_path)
    with serve(tmp_path) as base:
        status, body, _ = get(base, "/api/monitor/decisions")
    assert status == 200
    assert body["count"] == 2
    statuses = {row["decision_id"]: row["status"] for row in body["items"]}
    assert statuses == {"dec-btc": "NO_TRADE", "dec-eth": "SHADOW_OBSERVED"}
    assert all(row["has_fill"] is False for row in body["items"])
    labels = {row["decision_id"]: row["status_label"] for row in body["items"]}
    assert labels["dec-eth"] != labels["dec-btc"]


def test_decisions_support_symbol_and_status_filters(tmp_path: Path) -> None:
    _run(tmp_path)
    with serve(tmp_path) as base:
        _, by_symbol, _ = get(base, "/api/monitor/decisions?symbol=ETH/USDT")
        _, by_status, _ = get(base, "/api/monitor/decisions?status=SHADOW_OBSERVED")
    assert [r["decision_id"] for r in by_symbol["items"]] == ["dec-eth"]
    assert [r["decision_id"] for r in by_status["items"]] == ["dec-eth"]


def test_decisions_paginate_without_duplicates(tmp_path: Path) -> None:
    _run(tmp_path)
    with serve(tmp_path) as base:
        _, first, _ = get(base, "/api/monitor/decisions?limit=1")
        cursor = first["next_cursor"]
        _, second, _ = get(base, f"/api/monitor/decisions?limit=1&cursor={cursor}")
    assert first["count"] == 1
    assert first["has_more"] is True
    assert second["count"] == 1
    assert {r["decision_id"] for r in first["items"]}.isdisjoint(
        {r["decision_id"] for r in second["items"]}
    )


def test_cursor_beyond_the_stream_is_rejected(tmp_path: Path) -> None:
    _run(tmp_path)
    with serve(tmp_path) as base:
        status, body, _ = get(base, "/api/monitor/decisions?cursor=9999")
    assert status == 400
    assert body["error"]["code"] == "BAD_REQUEST"


def test_decision_detail_returns_trace_and_replay(tmp_path: Path) -> None:
    _run(tmp_path)
    with serve(tmp_path) as base:
        status, body, _ = get(base, "/api/monitor/decisions/dec-btc")
    assert status == 200
    assert body["trace"]["recorded"] is True
    assert body["trace"]["chain_ok"] is True
    assert body["trace"]["replay"]["ok"] is True
    assert body["trace"]["trace"]["classification"] == "NO_GROSS_EDGE"
    fields = {item["field"] for item in body["not_recorded"]}
    assert {"order_id", "fill_price", "position_close", "under_review"} <= fields


def test_unknown_decision_is_404(tmp_path: Path) -> None:
    _run(tmp_path)
    with serve(tmp_path) as base:
        status, body, _ = get(base, "/api/monitor/decisions/does-not-exist")
    assert status == 404
    assert body["error"]["code"] == "NOT_FOUND"


def test_run_trace_reports_not_recorded_events_and_digests(tmp_path: Path) -> None:
    _run(tmp_path)
    with serve(tmp_path) as base:
        status, body, _ = get(base, "/api/monitor/runs/run-a/trace")
    assert status == 200
    assert body["chain"]["ok"] is True
    assert "traces.jsonl" in body["artifact_digests"]
    assert set(body["not_recorded"]) == {"ORDER_SUBMITTED", "POSITION_CLOSED", "UNDER_REVIEW"}
    assert [d["decision_id"] for d in body["decisions"]] == ["dec-btc", "dec-eth"]


# ---------------------------------------------------------------------------
# candles
# ---------------------------------------------------------------------------


def test_candles_are_served_as_a_fixture_with_source_metadata(tmp_path: Path) -> None:
    _run(tmp_path)
    with serve(tmp_path) as base:
        status, body, _ = get(base, "/api/monitor/candles?symbol=BTC/USDT&timeframe=5m")
    assert status == 200
    assert body["fixture"] is True
    assert body["source"] == "static-fixture"
    bar = body["bars"][0]
    assert {"bar_open_time_ms", "bar_close_time_ms", "is_closed", "source", "ingested_at"} <= set(bar)


def test_candles_respect_point_in_time(tmp_path: Path) -> None:
    _run(tmp_path)
    as_of = TS_NOW - 3 * h.BAR_MS + 1
    with serve(tmp_path) as base:
        _, all_bars, _ = get(base, "/api/monitor/candles?symbol=BTC/USDT&timeframe=5m")
        _, pit_bars, _ = get(
            base, f"/api/monitor/candles?symbol=BTC/USDT&timeframe=5m&as_of={as_of}"
        )
    assert pit_bars["count"] < all_bars["count"]
    assert all(bar["bar_close_time_ms"] <= as_of for bar in pit_bars["bars"])


@pytest.mark.parametrize(
    "query,code",
    [
        ("symbol=BTCUSDT&timeframe=5m", "BAD_REQUEST"),
        ("symbol=BTC/USDT&timeframe=7m", "BAD_REQUEST"),
        ("symbol=BTC/USDT&timeframe=5m&limit=-1", "BAD_REQUEST"),
    ],
)
def test_invalid_candle_inputs_are_rejected(tmp_path: Path, query: str, code: str) -> None:
    _run(tmp_path)
    with serve(tmp_path) as base:
        status, body, _ = get(base, f"/api/monitor/candles?{query}")
    assert status == 400
    assert body["error"]["code"] == code


# ---------------------------------------------------------------------------
# read-only enforcement
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
def test_mutating_methods_are_405_with_allow_header(tmp_path: Path, method: str) -> None:
    _run(tmp_path)
    with serve(tmp_path) as base:
        status, headers = request(base, "/api/monitor/health", method, data=b"{}")
    assert status == 405
    assert headers["Allow"] == "GET, HEAD"


def test_unknown_route_is_404(tmp_path: Path) -> None:
    _run(tmp_path)
    with serve(tmp_path) as base:
        status, body, _ = get(base, "/api/monitor/definitely-not-a-route")
    assert status == 404
    assert body["error"]["code"] == "NOT_FOUND"


def test_path_traversal_is_refused(tmp_path: Path) -> None:
    _run(tmp_path)
    with serve(tmp_path) as base:
        status, body, _ = get(base, "/../../../../etc/passwd")
    assert status == 404
    assert body["error"]["code"] == "NOT_FOUND"


# ---------------------------------------------------------------------------
# connection state honesty
# ---------------------------------------------------------------------------


def test_stale_heartbeat_never_reports_live(tmp_path: Path) -> None:
    _run(tmp_path, heartbeat_ms=h.TS0)  # baseline-era stamp: hours old
    with serve(tmp_path) as base:
        _, health, _ = get(base, "/api/monitor/health")
        _, decisions, _ = get(base, "/api/monitor/decisions")
    assert health["runs"][0]["connection_state"] in {"DELAYED", "DISCONNECTED"}
    assert decisions["connection_state"] in {"DELAYED", "DISCONNECTED"}


def test_fresh_heartbeat_reports_live_data(tmp_path: Path) -> None:
    _run(tmp_path, heartbeat_ms=TS_NOW - 1_000)
    with serve(tmp_path) as base:
        _, health, _ = get(base, "/api/monitor/health")
    assert health["runs"][0]["connection_state"] == "LIVE_DATA"


# ---------------------------------------------------------------------------
# SSE
# ---------------------------------------------------------------------------


def _read_stream(base: str, path: str, *, max_bytes: int = 8192, wait: float = 2.2) -> str:
    import http.client

    url = urllib.parse.urlparse(base)
    conn = http.client.HTTPConnection(url.hostname, url.port, timeout=5)
    conn.request("GET", path)
    response = conn.getresponse()
    assert response.status == 200
    assert response.getheader("Content-Type").startswith("text/event-stream")
    chunks: list[bytes] = []
    deadline = time.time() + wait
    try:
        while time.time() < deadline and sum(len(c) for c in chunks) < max_bytes:
            try:
                line = response.readline()
            except TimeoutError:
                break  # no traffic before the socket timeout: that is the observation
            if not line:
                break
            chunks.append(line)
    finally:
        conn.close()
    return b"".join(chunks).decode("utf-8")


def test_sse_sends_snapshot_then_every_event_with_ids(tmp_path: Path) -> None:
    _run(tmp_path)
    with serve(tmp_path) as base:
        text = _read_stream(base, "/api/monitor/events/stream?cursor=0")
    assert "event: snapshot" in text
    ids = [int(line.split(":", 1)[1]) for line in text.splitlines() if line.startswith("id: ")]
    assert ids == sorted(ids)
    assert len(ids) == len(set(ids)), "duplicate delivery must be impossible within a stream"
    payloads = [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: {")]
    assert all(p["run_id"] == "run-a" for p in payloads)


def test_sse_reconnect_with_cursor_does_not_replay_old_events(tmp_path: Path) -> None:
    _run(tmp_path)
    with serve(tmp_path) as base:
        _, decisions, _ = get(base, "/api/monitor/decisions")
        cursor = decisions["snapshot_sequence"]
        text = _read_stream(base, f"/api/monitor/events/stream?cursor={cursor}", wait=1.6)
    ids = [line for line in text.splitlines() if line.startswith("id: ")]
    assert ids == [], "a reconnect at the current cursor must not resend events"
    assert "event: snapshot" in text


def test_sse_rejects_a_cursor_past_the_end(tmp_path: Path) -> None:
    _run(tmp_path)
    with serve(tmp_path) as base:
        status, body, _ = get(base, "/api/monitor/events/stream?cursor=99999")
    assert status == 400
    assert body["error"]["code"] == "BAD_REQUEST"


def test_a_fake_provider_run_is_never_presented_as_live(tmp_path: Path) -> None:
    """RFC §4.1: a synthetic run may not show ``LIVE_DATA`` because of a heartbeat."""
    run_dir = h.write_run(
        tmp_path,
        [h.make_trace("dec-1", proposal_payload=h.proposal())],
        executions=[],
        environment="fake:binance",
    )
    with serve(tmp_path) as base:
        _, body, _ = get(base, f"/api/monitor/decisions?run_id={run_dir.name}")
    assert body["connection_state"] == "SIMULATED_FIXTURE"
    assert "fake" in body["connection_reason"]


def test_run_trace_exposes_the_runtime_run_id_when_it_differs(tmp_path: Path) -> None:
    run_dir = h.write_run(tmp_path, [h.make_trace("dec-1")], executions=[], run_id="run-a")
    report = json.loads((run_dir / "RUN_REPORT.json").read_text(encoding="utf-8"))
    report["run_id"] = "autonomous-paper-deadbeef"
    (run_dir / "RUN_REPORT.json").write_text(json.dumps(report), encoding="utf-8")
    with serve(tmp_path) as base:
        _, body, _ = get(base, "/api/monitor/runs/run-a/trace")
    assert body["run_id"] == "run-a"
    assert body["runtime_run_id"] == "autonomous-paper-deadbeef"
    assert body["run_id_mismatch"] is True


def test_pagination_reports_a_stable_total_and_loses_no_decision(tmp_path: Path) -> None:
    """A run larger than one page must still be readable end to end.

    Regression (WP-TDM-06): ``total_matching`` was computed *after* the cursor
    filter, so it shrank page by page and a client could not tell a complete read
    from a truncated one. Found by the independent verifier on a 2 232-decision
    replay, not by the unit suite, which only ever used a single page.
    """
    page_limit = 500
    count = page_limit + 1
    traces = [
        h.make_trace(
            f"dec-{index:04d}",
            decision_time_ms=h.TS0 + index,
            market_time_ms=h.TS0,
        )
        for index in range(count)
    ]
    h.write_run(tmp_path, traces, executions=[])

    with serve(tmp_path) as base:
        seen: dict[str, str] = {}
        totals: set[int] = set()
        cursor = 0
        pages = 0
        while True:
            status, body, _ = get(
                base, f"/api/monitor/decisions?run_id=run-a&limit={page_limit}&cursor={cursor}"
            )
            assert status == 200
            pages += 1
            assert pages <= 10, "pagination did not terminate"
            totals.add(int(body["total_matching"]))
            assert body["count"] <= page_limit
            for row in body["items"]:
                assert row["decision_id"] not in seen, "a decision must not repeat across pages"
                seen[row["decision_id"]] = row["status"]
            if not body["has_more"]:
                break
            cursor = int(body["next_cursor"])

    assert totals == {count}, "total_matching must not depend on the cursor"
    assert len(seen) == count
    assert pages == 2
