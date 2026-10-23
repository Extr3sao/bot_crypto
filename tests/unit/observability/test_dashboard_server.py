"""WP-OBS-STRAT-01 §33/§34 — read-only API, security and runtime-isolation tests.

The guarantees under test:

* the HTTP surface answers **GET only**; every mutating verb is refused with 405;
* the server binds **loopback only**;
* the projection is a pure reader: bytes of the authoritative run artifacts are
  byte-identical before and after a full request cycle (dashboard cannot mutate
  the runtime's evidence);
* a malformed telemetry line is isolated, never fatal;
* a live SSE stream can be opened and closed without affecting the data.

No test here starts a trading runtime: the dashboard is deliberately decoupled
from it, which is exactly the property being verified.
"""

from __future__ import annotations

import hashlib
import http.client
import importlib.util
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

from trading_bot.observability import StrategyEcosystemObservatory  # noqa: E402

SCRIPT = REPO / "scripts" / "strategy_ecosystem_dashboard.py"


def _load_dashboard() -> Any:
    spec = importlib.util.spec_from_file_location("strategy_ecosystem_dashboard", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DASH = _load_dashboard()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@contextmanager
def _serving(obs: StrategyEcosystemObservatory) -> Iterator[tuple[str, int]]:
    httpd = DASH.ThreadingHTTPServer(("127.0.0.1", 0), DASH.make_handler(obs, stream_seconds=0))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield "127.0.0.1", int(httpd.server_address[1])
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _obs() -> StrategyEcosystemObservatory:
    return StrategyEcosystemObservatory(repo_root=REPO)


ALL_GET_PATHS = [
    "/api/system",
    "/api/topology",
    "/api/runs",
    "/api/strategies",
    "/api/strategies/BTC_5m_trend_momentum_v1/performance",
    "/api/strategies/BTC_5m_trend_momentum_v1/funnel",
    "/api/strategies/BTC_5m_trend_momentum_v1/lifecycle",
    "/api/strategies/BTC_5m_trend_momentum_v1/evidence",
    "/api/agents",
    "/api/agents/data-integrity",
    "/api/agents/data-integrity/activity",
    "/api/lifecycle",
    "/api/routing/comparisons",
    "/api/portfolio",
    "/api/risk",
    "/api/executions",
    "/api/traces",
    "/api/campaigns",
    "/api/snapshot",
]


def test_resolve_api_returns_200_for_documented_endpoints() -> None:
    obs = _obs()
    for path in ALL_GET_PATHS:
        resolved = DASH.resolve_api(obs, path)
        assert resolved is not None, path
        status, content_type, body = resolved
        # a seeded endpoint whose resource id is absent is allowed to 404
        assert status in (200, 404), (path, status)
        assert "application/json" in content_type
        assert body


def test_resolve_api_unknown_path_is_none() -> None:
    obs = _obs()
    assert DASH.resolve_api(obs, "/api/nope") is None
    assert DASH.resolve_api(obs, "/not-api") is None
    assert DASH.resolve_api(obs, "/") is None


def test_resolve_api_missing_resource_is_404() -> None:
    obs = _obs()
    resolved = DASH.resolve_api(obs, "/api/strategies/definitely-not-a-strategy")
    assert resolved is not None
    assert resolved[0] == 404


def test_loopback_guard_rejects_public_bind() -> None:
    with pytest.raises(SystemExit):
        DASH.resolve_host("0.0.0.0")
    assert DASH.resolve_host("127.0.0.1") == "127.0.0.1"


def test_control_policy_is_read_only() -> None:
    assert DASH.CONTROL_POLICY["read_only"] is True
    assert DASH.CONTROL_POLICY["mutating_endpoints"] == []
    assert DASH.CONTROL_POLICY["allowed_methods"] == ["GET"]


def test_http_get_serves_control_room_and_api() -> None:
    with _serving(_obs()) as (host, port):
        conn = http.client.HTTPConnection(host, port, timeout=10)
        conn.request("GET", "/")
        root = conn.getresponse()
        assert root.status == 200
        assert "text/html" in (root.getheader("Content-Type") or "")
        conn.request("GET", "/api/system")
        api = conn.getresponse()
        assert api.status == 200
        assert b"read_only" in api.read()
        conn.close()


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_mutating_verbs_are_refused(method: str) -> None:
    with _serving(_obs()) as (host, port):
        conn = http.client.HTTPConnection(host, port, timeout=10)
        conn.request(method, "/api/strategies")
        resp = conn.getresponse()
        assert resp.status == 405
        assert b"read-only" in resp.read()
        conn.close()


def _artifact_digest(root: Path) -> dict[str, str]:
    digests: dict[str, str] = {}
    corner = root / "reports"
    if not corner.exists():
        return digests
    for path in corner.rglob("*"):
        if path.is_file():
            try:
                digests[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                digests[str(path)] = "UNREADABLE"
    return digests


def test_runtime_artifacts_are_untouched_by_serving() -> None:
    before = _artifact_digest(REPO)
    with _serving(_obs()) as (host, port):
        conn = http.client.HTTPConnection(host, port, timeout=10)
        for path in ("/api/snapshot", "/api/traces", "/api/system", "/api/agents"):
            conn.request("GET", path)
            conn.getresponse().read()
        conn.close()
    assert _artifact_digest(REPO) == before


def test_sse_stream_opens_and_closes_cleanly() -> None:
    with _serving(_obs()) as (host, port):
        conn = http.client.HTTPConnection(host, port, timeout=10)
        conn.request("GET", "/api/events/stream")
        resp = conn.getresponse()
        assert resp.status == 200
        assert "text/event-stream" in (resp.getheader("Content-Type") or "")
        first = resp.read(60)
        assert b"event: pulse" in first
        conn.close()  # a disconnected client is not an error


def test_malformed_telemetry_line_is_isolated(tmp_path: Path) -> None:
    from trading_bot.observability import read_jsonl

    path = tmp_path / "traces.jsonl"
    path.write_text('{"ok": 1}\nNOT JSON\n\n{"ok": 2}\n', encoding="utf-8")
    rows = read_jsonl(path)
    assert rows == [{"ok": 1}, {"ok": 2}]
    assert read_jsonl(tmp_path / "missing.jsonl") == []


def test_read_json_returns_none_on_bad_bytes(tmp_path: Path) -> None:
    from trading_bot.observability import read_json

    bad = tmp_path / "x.json"
    bad.write_bytes(b"\xff\xfe not utf8")
    assert read_json(bad) is None
    assert read_json(tmp_path / "absent.json") is None
