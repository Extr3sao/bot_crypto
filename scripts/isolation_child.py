"""One isolation scenario, executed in its own process.

The child installs the paper policy first and only then builds the objects it is asked to
abuse. That order is the claim: if the guard were installed after the runtime had built a
venue client, the evidence would say nothing about the window that matters.

    python scripts/isolation_child.py --root <dir> --mode <scenario>

The last stdout line is JSON; the guard writes every audited attempt to
``<root>/network.jsonl``.
"""

from __future__ import annotations

import argparse
import http.client
import importlib.util
import json
import os
import socket
import subprocess
import sys
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.execution import isolation  # noqa: E402


def _load_script(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _attempt(action: Callable[[], Any]) -> dict[str, Any]:
    """Run one abuse attempt and classify how it ended."""
    try:
        action()
    except isolation.NetworkBlocked as exc:
        return {"outcome": "DENIED", "code": exc.code, "detail": str(exc)[:200]}
    except isolation.OrderRouteRefused as exc:
        return {"outcome": "REFUSED", "code": exc.code, "detail": str(exc)[:200]}
    except isolation.PolicyRedefined as exc:
        return {"outcome": "REFUSED", "code": exc.code, "detail": str(exc)[:200]}
    except OSError as exc:
        return {"outcome": "OS_ERROR", "error": type(exc).__name__, "detail": str(exc)[:120]}
    except Exception as exc:
        return {"outcome": "OTHER", "error": type(exc).__name__, "detail": str(exc)[:200]}
    return {"outcome": "ALLOWED"}


def _fake_venue() -> Any:
    class Venue:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def create_order(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            self.calls.append("create_order")
            return {"id": "fake", "status": "closed"}

        def cancel_order(self, *args: Any) -> None:
            self.calls.append("cancel_order")

    return Venue()


def _order_ccxt() -> dict[str, Any]:
    from trading_bot.market_data.exchange_connector import CCXTExchangeConnector

    venue = _fake_venue()
    connector = object.__new__(CCXTExchangeConnector)
    connector._exchange_instance = venue  # type: ignore[assignment]
    connector._config = None  # type: ignore[assignment]
    connector._log = type(
        "Log", (), {"bind": lambda self, **_kwargs: self, "info": lambda *a, **k: None}
    )()
    connector._retry_decorator = lambda function: function
    created = _attempt(lambda: connector.create_order("BTC/USDT", "buy", "market", 1.0))
    cancelled = _attempt(lambda: connector.cancel_order("order-1", "BTC/USDT"))
    return {"create": created, "cancel": cancelled, "venue_calls": list(venue.calls)}


def _order_futures() -> dict[str, Any]:
    from trading_bot.market_data.bitunix_futures import (
        BitunixFuturesClient,
        BitunixFuturesConnector,
    )

    client = object.__new__(BitunixFuturesClient)
    attempts: list[str] = []

    def _request(*args: Any, **kwargs: Any) -> Any:
        attempts.append("request")
        raise AssertionError("the gate let an HTTP request through")

    client._request = _request  # type: ignore[method-assign]
    client.futures_base_url = "https://fapi.bitunix.com"  # type: ignore[attr-defined]
    client._symbol_cache = None  # type: ignore[attr-defined]

    direct = _attempt(
        lambda: client.place_order(symbol="BTCUSDT", side="BUY", qty=0.01, client_id="cid-1")
    )
    connector = object.__new__(BitunixFuturesConnector)
    connector._client = client  # type: ignore[assignment]
    via_connector = _attempt(
        lambda: connector.create_order("BTCUSDT", "buy", "market", 0.01)
    )
    cancelled = _attempt(lambda: connector.cancel_order("order-1", "BTCUSDT"))
    return {
        "client_place_order": direct,
        "connector_create_order": via_connector,
        "connector_cancel_order": cancelled,
        "http_requests": len(attempts),
    }


def _order_spot() -> dict[str, Any]:
    from trading_bot.market_data.bitunix import BitunixSpotConnector

    class SpotClient:
        calls = 0

    connector = object.__new__(BitunixSpotConnector)
    connector._client = SpotClient()  # type: ignore[assignment]
    connector._sandbox = True  # type: ignore[attr-defined]
    connector._log_name = "probe"  # type: ignore[attr-defined]
    connector._log = type("Log", (), {"bind": lambda self, **_kwargs: self})()  # type: ignore[attr-defined]
    return {
        "create": _attempt(lambda: connector.create_order("BTC/USDT", "buy", "market", 1.0)),
        "cancel": _attempt(lambda: connector.cancel_order("order-1", "BTC/USDT")),
        "client_calls": SpotClient.calls,
    }


def _app_route() -> dict[str, Any]:
    from trading_bot.app import _cmd_place_order

    base = {
        "confirm_live": False,
        "env_file": None,
        "config_dir": str(REPO / "config"),
        "market_kind": "futures",
        "symbol": "BTCUSDT",
        "side": "BUY",
        "amount": "0.001",
        "order_type": "MARKET",
        "trade_side": "OPEN",
        "price": None,
        "position_id": None,
        "reduce_only": False,
        "tp_price": None,
        "sl_price": None,
    }
    import argparse

    without_confirm = _cmd_place_order(argparse.Namespace(**base))
    with_confirm = _cmd_place_order(argparse.Namespace(**{**base, "confirm_live": True}))
    gate = _attempt(lambda: isolation.assert_order_allowed("app._cmd_place_order"))
    return {
        "exit_without_confirm": without_confirm,
        "exit_with_confirm_in_paper": with_confirm,
        "gate_on_command": gate,
    }


def _network() -> dict[str, Any]:
    def connect(host: str, port: int) -> Callable[[], Any]:
        def action() -> Any:
            socket.create_connection((host, port), timeout=0.05).close()

        return action

    def urlopen(url: str) -> Callable[[], Any]:
        def action() -> Any:
            urllib.request.urlopen(url, timeout=0.05).close()

        return action

    def http_connect(host: str) -> Callable[[], Any]:
        def action() -> Any:
            connection = http.client.HTTPSConnection(host, timeout=0.05)
            connection.connect()
            connection.close()

        return action

    return {
        "external_connect": _attempt(connect("api.binance.com", 443)),
        "loopback_connect": _attempt(connect("127.0.0.1", 9)),
        "external_dns": _attempt(lambda: socket.getaddrinfo("api.binance.com", 443)),
        "loopback_dns": _attempt(lambda: socket.getaddrinfo("localhost", 80)),
        "urllib": _attempt(urlopen("https://api.binance.com/api/v3/ping")),
        "http_client": _attempt(http_connect("fapi.binance.com")),
    }


def _ccxt_constructor() -> dict[str, Any]:
    import ccxt

    class_ = ccxt.binance
    constructed: dict[str, Any] = {}
    try:
        instance = class_({"enableRateLimit": True, "apiKey": "not-a-key", "secret": "not-a-secret"})
        constructed = {"outcome": "CONSTRUCTED", "id": getattr(instance, "id", "binance")}
        fetched = _attempt(lambda: instance.fetch_ticker("BTC/USDT"))
        constructed["fetch_after_construction"] = fetched
    except isolation.NetworkBlocked as exc:
        constructed = {"outcome": "DENIED", "code": exc.code, "detail": str(exc)[:200]}
    except Exception as exc:
        constructed = {"outcome": "OTHER", "error": type(exc).__name__, "detail": str(exc)[:200]}
    return {"constructor": constructed}


def _disarm() -> dict[str, Any]:
    before = _attempt(lambda: socket.getaddrinfo("api.binance.com", 443))
    os.environ["TRADING_BOT_MODE"] = "live"
    os.environ["TAP_ISOLATION"] = "0"
    os.environ["TAP_ISOLATION_DISABLE"] = "1"
    after_env_flip = _attempt(lambda: socket.getaddrinfo("api.binance.com", 443))
    reinstall = _attempt(lambda: isolation.install_for_runtime("live"))
    mutated_policy = _attempt(
        lambda: isolation.install(
            isolation.IsolationPolicy(mode="paper", external_network=True, order_routes=True)
        )
    )
    return {
        "before": before,
        "after_env_flip": after_env_flip,
        "reinstall_live": reinstall,
        "mutated_policy": mutated_policy,
    }


def _subprocess_scope() -> dict[str, Any]:
    code = (
        "import socket,sys\n"
        "s=socket.socket(); s.settimeout(0.2)\n"
        "try:\n"
        "    s.connect(('127.0.0.1', 9)); print('CONNECTED')\n"
        "except OSError as exc:\n"
        "    print('ATTEMPTED:' + type(exc).__name__)\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ},
    )
    parent = _attempt(lambda: socket.getaddrinfo("api.binance.com", 443))
    return {
        "child_output": proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "",
        "child_returncode": proc.returncode,
        "parent_attempt": parent,
    }


def _runtime(root: Path) -> dict[str, Any]:
    module = _load_script("ai_bots_run")
    out = root / "runtime"
    exit_code = module.main(
        [
            "--mode",
            "mock",
            "--out",
            str(out),
            "--limit-bars",
            "150",
            "--max-calls",
            "1",
            "--decision-every-bars",
            "20",
        ]
    )
    report_path = out / "RUN_REPORT.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    return {
        "exit_code": exit_code,
        "report_status": report.get("status"),
        "isolation": report.get("isolation"),
        "run_report_present": report_path.exists(),
    }


HANDLERS: dict[str, Callable[[Path], dict[str, Any]]] = {
    "runtime": _runtime,
    "order-ccxt": lambda _root: _order_ccxt(),
    "order-futures": lambda _root: _order_futures(),
    "order-spot": lambda _root: _order_spot(),
    "app-route": lambda _root: _app_route(),
    "network": lambda _root: _network(),
    "ccxt-constructor": lambda _root: _ccxt_constructor(),
    "disarm": lambda _root: _disarm(),
    "subprocess": lambda _root: _subprocess_scope(),
}


def main() -> int:
    parser = argparse.ArgumentParser(description="One isolation scenario, in its own process.")
    parser.add_argument("--root", required=True)
    parser.add_argument("--mode", required=True, choices=sorted(HANDLERS))
    args = parser.parse_args()
    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)

    guard = isolation.install_for_runtime("paper", log_path=root / "network.jsonl")
    payload: dict[str, Any] = {
        "mode": args.mode,
        "pid": os.getpid(),
        "policy": guard.policy.as_dict(),
        "result": {},
    }
    try:
        payload["result"] = HANDLERS[args.mode](root)
        payload["status"] = "RAN"
    except Exception as exc:
        payload["status"] = "FAILED"
        payload["error"] = f"{type(exc).__name__}: {exc}"
    payload["denied"] = guard.denied
    payload["attempts"] = [row for row in guard.attempts]
    (root / "child.json").write_text(json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))
    return 0 if payload["status"] == "RAN" else 1


if __name__ == "__main__":
    sys.exit(main())
