from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from trading_bot.paper_dashboard.events import DashboardEventBus
from trading_bot.paper_dashboard.projection import DashboardStore
from trading_bot.paper_dashboard.server import PaperDashboardServer


@pytest.fixture()
def running_server():
    bus, store = DashboardEventBus(), DashboardStore()
    bus.add_listener(store.handle_event)
    server = PaperDashboardServer(store=store, bus=bus, host="127.0.0.1", port=0)
    url = server.start()
    yield url, server, bus
    server.stop()


def get(url: str, path: str):
    try:
        with urllib.request.urlopen(url + path, timeout=5) as response:
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode())


def test_rest_contract_and_local_binding(running_server) -> None:
    url, _server, _bus = running_server
    assert url.startswith("http://127.0.0.1:")
    for path in (
        "/api/status",
        "/api/portfolio",
        "/api/positions",
        "/api/trades",
        "/api/signals",
        "/api/risk-decisions",
        "/api/metrics",
        "/api/assets",
        "/api/strategies",
        "/api/events",
    ):
        status, payload = get(url, path)
        assert status == 200 and isinstance(payload, dict)
    assert get(url, "/api/status")[1]["read_only"] is True


def test_non_get_methods_are_405(running_server) -> None:
    url, _server, _bus = running_server
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        request = urllib.request.Request(url + "/api/positions", data=b"{}", method=method)
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request, timeout=5)
        assert error.value.code == 405


def test_projection_endpoints_and_secret_free_payload(running_server) -> None:
    url, _server, bus = running_server
    bus.publish("position_opened", {"symbol": "BTC/USDT", "entry_price": 100, "quantity": 1})
    assert get(url, "/api/positions")[1]["positions"][0]["symbol"] == "BTC/USDT"
    for path in ("/api/status", "/api/snapshot", "/api/portfolio", "/api/events", "/health"):
        text = json.dumps(get(url, path)[1]).lower()
        assert not any(
            secret in text for secret in ("api_key", "api_secret", "password", "credentials")
        )


def test_sse_delivers_events_and_survives_disconnect(running_server) -> None:
    url, server, bus = running_server
    received: list[dict] = []
    done = threading.Event()

    def consume() -> None:
        try:
            with urllib.request.urlopen(url + "/ws/events", timeout=10) as response:
                for raw in response:
                    line = raw.decode().strip()
                    if line.startswith("data: "):
                        received.append(json.loads(line[6:]))
                        if received[-1]["type"] == "risk_rejected":
                            done.set()
                            return
        except Exception:
            done.set()

    thread = threading.Thread(target=consume, daemon=True)
    thread.start()
    import time

    time.sleep(0.2)
    bus.publish("cycle_completed", {"contexts_built": 1})
    bus.publish("risk_rejected", {"symbol": "BTC/USDT", "reason": "max_exposure"})
    assert done.wait(5)
    assert {event["type"] for event in received} >= {"cycle_completed", "risk_rejected"}
    response = urllib.request.urlopen(url + "/ws/events", timeout=5)
    response.close()
    bus.publish("cycle_completed", {"contexts_built": 1})
    assert get(url, "/health")[0] == 200
    server.stop()
