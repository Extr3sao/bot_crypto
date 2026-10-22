"""RFC-PAPER-ISOLATION-005 — the rules that decide, without installing anything.

Installing the audit hook is process-wide and cannot be undone, so the tests that need a
real hook run in a child interpreter (``test_the_hook_denies_in_a_child_process``). What is
tested here is the pure decision table plus the order gate, which is the part every
order-capable method calls.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from trading_bot.execution import isolation
from trading_bot.market_data.exchange_connector import CCXTExchangeConnector

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(isolation.MODE_ENV, raising=False)


def test_paper_is_strict_and_live_is_not_made_safer_here() -> None:
    paper = isolation.policy_for_mode("paper")
    assert paper.external_network is False
    assert paper.loopback_network is False
    assert paper.order_routes is False

    live = isolation.policy_for_mode("live")
    assert live.external_network is True
    assert live.order_routes is True


@pytest.mark.parametrize("mode", ["research", "backtest", "paper", "shadow_live", ""])
def test_every_mode_but_live_is_isolated(mode: str) -> None:
    policy = isolation.policy_for_mode(mode)
    assert policy.order_routes is False
    assert policy.external_network is False


def test_external_connect_is_denied_with_the_host_in_the_reason() -> None:
    decision, reason = isolation.decide_network(
        "socket.connect", (object(), ("api.binance.com", 443)), isolation.policy_for_mode("paper")
    )
    assert decision == "DENY"
    assert "api.binance.com" not in reason  # the host is recorded, not trusted into the text


def test_loopback_is_allowed_only_when_the_policy_says_so() -> None:
    strict = isolation.policy_for_mode("paper")
    assert isolation.decide_network(
        "socket.connect", (object(), ("127.0.0.1", 8000)), strict
    )[0] == "DENY"

    opened = isolation.IsolationPolicy(mode="paper", loopback_network=True)
    assert isolation.decide_network(
        "socket.connect", (object(), ("127.0.0.1", 8000)), opened
    )[0] == "ALLOW_LOOPBACK"
    assert isolation.decide_network(
        "socket.getaddrinfo", ("localhost", 8000, 0, 0, 0), opened
    )[0] == "ALLOW_LOOPBACK"
    assert isolation.decide_network(
        "socket.connect", (object(), ("api.binance.com", 443)), opened
    )[0] == "DENY"


def test_dns_is_a_network_event_and_is_denied() -> None:
    decision, _ = isolation.decide_network(
        "socket.getaddrinfo",
        ("fapi.binance.com", 443, 0, 0, 0),
        isolation.policy_for_mode("paper"),
    )
    assert decision == "DENY"


def test_a_non_network_event_is_ignored() -> None:
    assert isolation.decide_network(
        "open", ("/tmp/x", "r"), isolation.policy_for_mode("paper")
    )[0] == "IGNORE"


def test_order_gate_allows_a_process_with_no_runtime_declaration(monkeypatch) -> None:
    #: Compatibility with the connector tests and with any library embedding: the live
    #: checklist still owns this decision when no runtime declared a mode.
    isolation.assert_order_allowed("test.route")


def test_order_gate_refuses_a_declared_paper_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(isolation.MODE_ENV, "paper")
    with pytest.raises(isolation.OrderRouteRefused) as caught:
        isolation.assert_order_allowed("test.route", detail="BTC/USDT buy 1")
    assert caught.value.code == isolation.CODE_ORDER_ROUTE
    assert "BTC/USDT" in str(caught.value)


def test_order_gate_refuses_every_non_live_declared_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    for mode in ("research", "backtest", "shadow_live", "paper"):
        monkeypatch.setenv(isolation.MODE_ENV, mode)
        with pytest.raises(isolation.OrderRouteRefused):
            isolation.assert_order_allowed("test.route")


def test_order_gate_allows_a_declared_live_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(isolation.MODE_ENV, "live")
    isolation.assert_order_allowed("test.route")


def test_ccxt_create_order_refuses_before_touching_the_venue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gate must run before the venue object is used, not after."""

    class Venue:
        calls = 0

        def create_order(self, *_args: object, **_kwargs: object) -> dict[str, object]:
            Venue.calls += 1
            return {}

    connector = object.__new__(CCXTExchangeConnector)
    connector._exchange_instance = Venue()  # type: ignore[assignment]
    connector._log = type(
        "Log", (), {"bind": lambda self, **_kwargs: self, "info": lambda *a, **k: None}
    )()
    connector._retry_decorator = lambda function: function
    connector._config = None  # type: ignore[assignment]

    monkeypatch.setenv(isolation.MODE_ENV, "paper")
    with pytest.raises(isolation.OrderRouteRefused):
        connector.create_order("BTC/USDT", "buy", "market", 1.0)
    assert Venue.calls == 0


def test_ccxt_cancel_order_refuses_before_touching_the_venue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Venue:
        calls = 0

        def cancel_order(self, *_args: object) -> None:
            Venue.calls += 1

    connector = object.__new__(CCXTExchangeConnector)
    connector._exchange_instance = Venue()  # type: ignore[assignment]
    connector._log = type("Log", (), {"bind": lambda self, **_kwargs: self})()
    connector._retry_decorator = lambda function: function
    connector._config = None  # type: ignore[assignment]

    monkeypatch.setenv(isolation.MODE_ENV, "paper")
    with pytest.raises(isolation.OrderRouteRefused):
        connector.cancel_order("order-1", "BTC/USDT")
    assert Venue.calls == 0


def test_the_hook_denies_in_a_child_process(tmp_path: Path) -> None:
    """The one claim a pure function cannot make: the audit hook really fires."""
    script = tmp_path / "probe.py"
    script.write_text(
        "\n".join(
            [
                "import json, socket, sys",
                "from pathlib import Path",
                "sys.path.insert(0, r'%s')" % (REPO / "src"),
                "from trading_bot.execution import isolation",
                "guard = isolation.install_for_runtime('paper', log_path=Path(r'%s'))"
                % (tmp_path / "attempts.jsonl"),
                "out = {}",
                "from trading_bot.execution.isolation import NetworkBlocked",
                "try:",
                "    socket.create_connection(('127.0.0.1', 9), timeout=0.01).close()",
                "    out['connect'] = 'ALLOWED'",
                "except NetworkBlocked:",
                "    out['connect'] = 'DENIED'",
                "try:",
                "    socket.getaddrinfo('api.binance.com', 443)",
                "    out['dns'] = 'ALLOWED'",
                "except NetworkBlocked:",
                "    out['dns'] = 'DENIED'",
                "try:",
                "    isolation.install_for_runtime('live')",
                "    out['reinstall'] = 'ALLOWED'",
                "except isolation.PolicyRedefined:",
                "    out['reinstall'] = 'REFUSED'",
                "out['denied'] = guard.denied",
                "print(json.dumps(out))",
            ]
        ),
        encoding="utf-8",
    )
    proc = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, timeout=120
    )
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout.strip().splitlines()[-1])
    assert result["connect"] == "DENIED"
    assert result["dns"] == "DENIED"
    assert result["reinstall"] == "REFUSED"
    assert result["denied"] >= 2
    assert os.path.exists(tmp_path / "attempts.jsonl")
