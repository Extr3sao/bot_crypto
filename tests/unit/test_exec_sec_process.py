"""RFC-TAP-EXEC-SEC-002 — program-level cases T01-T11.

These tests call ``trading_bot.app.main`` with the real parser and the real
command functions. Only the exchange clients, ``load_settings`` and the scanner
iteration are doubled, so the code under test is the code an operator runs.

The subprocess cases for the ten gate checks live in
``test_live_gate_enforcement.py``. This file is about the *new* contract: explicit
confirmation, the derived category, and the payload that would reach the venue.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from trading_bot import app as app_module
from trading_bot.autonomous.hot_stop import HOT_STOP_FILE_NAME
from trading_bot.config.runtime import TradingMode
from trading_bot.execution.order_authorization import BITUNIX_FUTURES
from trading_bot.market_data.fake import build_demo_settings


def _legal_settings() -> Any:
    settings = build_demo_settings(mode="live")
    return settings.model_copy(
        update={
            "exchange": settings.exchange.model_copy(
                update={
                    "id": "bitunix",
                    "sandbox": False,
                    "api_key": "test-key",
                    "api_secret": "test-secret",
                }
            ),
            "risk": settings.risk.model_copy(
                update={"kill_switch_enabled": True, "live_trading_enabled": False}
            ),
            "runtime": settings.runtime.model_copy(
                update={
                    "mode": TradingMode.LIVE,
                    "live_trading_enabled": True,
                    "exchange_id": "bitunix",
                }
            ),
        }
    )


def _broken_settings() -> Any:
    settings = _legal_settings()
    return settings.model_copy(
        update={"exchange": settings.exchange.model_copy(update={"api_key": "", "api_secret": ""})}
    )


def _position(**overrides: Any) -> SimpleNamespace:
    values: dict[str, Any] = {
        "position_id": "pos-1",
        "symbol": "BTCUSDT",
        "side": "BUY",
        "qty": 0.01,
        "position_mode": "ONE_WAY",
        "avg_open_price": 100.0,
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@dataclass
class Broker:
    """Every call that would leave the process, and the knobs to shape it."""

    positions: list[Any] = field(default_factory=list)
    position_error: bool = False
    mutate: Any = None
    calls: list[dict[str, Any]] = field(default_factory=list)
    constructions: int = 0
    scanners: int = 0

    def payload_for(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        return {
            "symbol": kwargs.get("symbol"),
            "side": str(kwargs.get("side", "")).upper(),
            "qty": str(kwargs.get("qty")),
            "tradeSide": str(kwargs.get("trade_side", "")).upper(),
            "reduceOnly": bool(kwargs.get("reduce_only")),
            "positionId": kwargs.get("position_id"),
        }

    def futures(self) -> Any:
        broker = self

        class FakeFutures:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                broker.constructions += 1

            def place_order(self, **kwargs: Any) -> dict[str, Any]:
                guard = kwargs.pop("payload_guard", None)
                payload = broker.payload_for(kwargs)
                if broker.mutate is not None:
                    broker.mutate(payload)
                if guard is not None:
                    guard(payload)
                broker.calls.append(
                    {"sink": "futures.place_order", "payload": payload, "kwargs": kwargs}
                )
                return {"orderId": "order-1", "clientId": None}

            def flash_close_position(
                self, position_id: str, *, payload_guard: Any = None
            ) -> dict[str, Any]:
                payload = {"positionId": position_id}
                if broker.mutate is not None:
                    broker.mutate(payload)
                if payload_guard is not None:
                    payload_guard(payload)
                broker.calls.append(
                    {"sink": "futures.flash_close_position", "payload": payload, "kwargs": {}}
                )
                return {"positionId": position_id, "closed": True}

            def place_position_tpsl(self, **kwargs: Any) -> dict[str, Any]:
                broker.calls.append(
                    {"sink": "futures.place_position_tpsl", "payload": {}, "kwargs": kwargs}
                )
                return {"positionId": kwargs.get("position_id"), "tpsl": True}

            def get_pending_positions(self, symbol: str | None = None) -> list[Any]:
                if broker.position_error:
                    from trading_bot.market_data.bitunix import BitunixAPIError

                    raise BitunixAPIError("position read failed")
                return list(broker.positions)

            def get_account(self, asset: str = "USDT") -> Any:
                return SimpleNamespace(available=1_000.0, cross_unrealized_pnl=0.0)

            def get_symbol(self, symbol: str) -> Any:
                return SimpleNamespace(
                    symbol_status="OPEN",
                    is_api_supported=True,
                    base_precision=4,
                    min_trade_volume=0.0001,
                    max_market_order_volume=0.0,
                    quote_precision=2,
                )

            def fetch_recent_ohlcv(self, symbol: str, limit: int = 80) -> list[Any]:
                return [SimpleNamespace(close=100.0 + index) for index in range(6)]

        return FakeFutures

    def spot(self) -> Any:
        broker = self

        class FakeSpot:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                broker.constructions += 1

            def place_spot_order(self, **kwargs: Any) -> dict[str, Any]:
                broker.calls.append(
                    {"sink": "spot.place_spot_order", "payload": {}, "kwargs": kwargs}
                )
                return {"orderId": "spot-1", "placeStatus": "FILLED"}

            def fetch_last_price(self, symbol: str) -> float:
                return 100.0

            def fetch_recent_ohlcv(self, symbol: str, limit: int = 80) -> list[Any]:
                return [SimpleNamespace(close=100.0 + index) for index in range(6)]

        return FakeSpot

    def connector(self) -> Any:
        broker = self

        class FakeConnector:
            def load_markets(self) -> None:
                return None

            def fetch_balance(self) -> list[Any]:
                from trading_bot.market_data.types import Balance

                return [Balance(asset="USDT", free=1_000.0, used=0.0, total=1_000.0)]

            def fetch_market_rules(self, symbol: str) -> Any:
                from trading_bot.market_data.types import MarketRules

                return MarketRules(
                    symbol=symbol,
                    is_open=True,
                    quote="USDT",
                    min_trade_value_usdt=10.0,
                    min_volume=0.0001,
                    base_precision=4,
                    quote_precision=2,
                )

            def create_order(self, **kwargs: Any) -> Any:
                broker.calls.append(
                    {"sink": "connector.create_order", "payload": {}, "kwargs": kwargs}
                )
                return SimpleNamespace(id="connector-1", client_order_id="cid", status="closed")

        return FakeConnector


@pytest.fixture()
def broker(monkeypatch: pytest.MonkeyPatch) -> Broker:
    instance = Broker()
    monkeypatch.setattr(app_module, "BitunixFuturesClient", instance.futures())
    monkeypatch.setattr(app_module, "BitunixSpotClient", instance.spot())
    monkeypatch.setattr(
        app_module,
        "_create_futures_trade_case",
        lambda **kwargs: ("tc-1", "snapshot.png"),
    )
    monkeypatch.setattr(app_module, "_mark_trade_case_order_open", lambda **kwargs: None)
    monkeypatch.setattr(app_module, "_mark_trade_case_order_rejected", lambda **kwargs: None)
    monkeypatch.setattr(
        app_module, "_reconcile_open_trade_cases_with_positions", lambda **kwargs: []
    )
    monkeypatch.setattr(app_module, "_mark_trade_case_closed_from_position", lambda **kwargs: None)

    def iteration(config_dir: str, env_file: str | None) -> Any:
        instance.scanners += 1
        snapshot = SimpleNamespace(
            symbol="BTC/USDT",
            active=True,
            last_price=100.0,
            rank_score=0.9,
            spread_bps=1.0,
            volume_24h_usdt=5_000_000.0,
            atr_pct=0.5,
            volatility_pct=0.5,
            timestamp=0,
            rejection_reason=None,
        )
        counters = SimpleNamespace(
            pairs_processed=1, pairs_active=1, pairs_inactive=0, scanner_errors=0
        )
        return [snapshot], counters, instance.connector(), _legal_settings()

    monkeypatch.setattr(app_module, "_run_single_live_iteration", iteration)
    monkeypatch.setattr(
        app_module,
        "_run_single_iteration",
        lambda mode: (
            [],
            SimpleNamespace(pairs_processed=0, pairs_active=0, pairs_inactive=0, scanner_errors=0),
        ),
    )
    return instance


def _run(
    monkeypatch: pytest.MonkeyPatch,
    broker: Broker,
    settings: Any,
    argv: list[str],
    *,
    run_dir: Path,
) -> int:
    monkeypatch.setattr(app_module, "load_settings", lambda **kwargs: settings)
    return int(app_module.main([*argv, "--run-dir", str(run_dir)]))


def _place_order_argv(
    *, side: str = "buy", trade_side: str = "OPEN", reduce_only: bool = False, qty: float = 0.01
) -> list[str]:
    argv = [
        "place-order",
        "--symbol",
        "BTCUSDT",
        "--side",
        side,
        "--order-type",
        "market",
        "--amount",
        str(qty),
        "--confirm-live",
        "--market-kind",
        "futures",
        "--trade-side",
        trade_side,
    ]
    if reduce_only:
        argv += ["--reduce-only", "--position-id", "pos-1"]
    return argv


def _run_argv(market_kind: str = "futures", *, confirm: bool = True) -> list[str]:
    argv = [
        "run",
        "--mode",
        "live",
        "--once",
        "--auto-trade",
        "--market-kind",
        market_kind,
        "--trade-quote-usdt",
        "50",
        "--env-file",
        "",
    ]
    if confirm:
        argv.append("--confirm-live")
    return argv


# ---------------------------------------------------------------------------
# T01 / T04 — confirmation is for live dispatch only
# ---------------------------------------------------------------------------


def test_t01_run_without_confirmation_never_scans_or_builds_a_client(
    broker: Broker, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    exit_code = _run(
        monkeypatch, broker, _legal_settings(), _run_argv(confirm=False), run_dir=tmp_path
    )
    assert exit_code == 2
    assert broker.calls == []
    assert broker.scanners == 0
    assert broker.constructions == 0


def test_t04_paper_is_not_blocked_by_the_flag(
    broker: Broker, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    exit_code = _run(
        monkeypatch,
        broker,
        _legal_settings(),
        ["run", "--mode", "paper", "--once", "--auto-trade"],
        run_dir=tmp_path,
    )
    assert exit_code == 0
    assert broker.calls == []


# ---------------------------------------------------------------------------
# T05 — a close is exempt only when the venue and the position prove it
# ---------------------------------------------------------------------------


def test_t05_closing_a_long_is_a_proven_reduction(
    broker: Broker, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    broker.positions = [_position(side="BUY", qty=0.01)]
    exit_code = _run(
        monkeypatch,
        broker,
        _broken_settings(),
        _place_order_argv(side="sell", trade_side="CLOSE", reduce_only=True),
        run_dir=tmp_path,
    )
    assert exit_code == 0
    assert [call["sink"] for call in broker.calls] == ["futures.place_order"]
    assert broker.calls[0]["payload"]["reduceOnly"] is True


def test_t05_closing_a_short_is_a_proven_reduction(
    broker: Broker, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    broker.positions = [_position(side="SELL", qty=0.5)]
    exit_code = _run(
        monkeypatch,
        broker,
        _broken_settings(),
        _place_order_argv(side="buy", trade_side="CLOSE", reduce_only=True, qty=0.5),
        run_dir=tmp_path,
    )
    assert exit_code == 0
    assert len(broker.calls) == 1


def test_t05_flash_close_is_allowed_while_the_gate_rejects(
    broker: Broker, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    broker.positions = [_position()]
    exit_code = _run(
        monkeypatch,
        broker,
        _broken_settings(),
        ["close-position", "--position-id", "pos-1"],
        run_dir=tmp_path,
    )
    assert exit_code == 0
    assert [call["sink"] for call in broker.calls] == ["futures.flash_close_position"]


# ---------------------------------------------------------------------------
# T06 — a name or a side is never proof
# ---------------------------------------------------------------------------


def test_t06_sell_without_reduce_only_is_not_a_reduction(
    broker: Broker, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    broker.positions = [_position(side="BUY", qty=0.01)]
    exit_code = _run(
        monkeypatch,
        broker,
        _broken_settings(),
        _place_order_argv(side="sell", trade_side="CLOSE", reduce_only=False),
        run_dir=tmp_path,
    )
    assert exit_code == 2
    assert broker.calls == []


def test_t06_excess_quantity_cannot_use_the_exemption(
    broker: Broker, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    broker.positions = [_position(side="BUY", qty=0.01)]
    exit_code = _run(
        monkeypatch,
        broker,
        _broken_settings(),
        _place_order_argv(side="sell", trade_side="CLOSE", reduce_only=True, qty=0.5),
        run_dir=tmp_path,
    )
    assert exit_code == 2
    assert broker.calls == []


def test_t06_a_zero_position_cannot_be_reduced(
    broker: Broker, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    broker.positions = [_position(side="BUY", qty=0.0)]
    exit_code = _run(
        monkeypatch,
        broker,
        _broken_settings(),
        _place_order_argv(side="sell", trade_side="CLOSE", reduce_only=True),
        run_dir=tmp_path,
    )
    assert exit_code == 2
    assert broker.calls == []


def test_t06_buying_the_same_side_as_the_position_is_not_a_reduction(
    broker: Broker, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    broker.positions = [_position(side="BUY", qty=1.0)]
    exit_code = _run(
        monkeypatch,
        broker,
        _broken_settings(),
        _place_order_argv(side="buy", trade_side="CLOSE", reduce_only=True),
        run_dir=tmp_path,
    )
    assert exit_code == 2
    assert broker.calls == []


def test_t06_a_spot_sell_is_not_a_reduction(
    broker: Broker, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    exit_code = _run(
        monkeypatch,
        broker,
        _broken_settings(),
        [
            "place-order",
            "--symbol",
            "BTC/USDT",
            "--side",
            "sell",
            "--order-type",
            "market",
            "--amount",
            "0.01",
            "--price",
            "100",
            "--confirm-live",
            "--market-kind",
            "spot",
        ],
        run_dir=tmp_path,
    )
    assert exit_code == 2
    assert broker.calls == []


# ---------------------------------------------------------------------------
# T07 / T08 — the last payload, and what cannot be seen
# ---------------------------------------------------------------------------


def test_t07_a_dropped_reduce_only_is_refused_at_the_payload(
    broker: Broker, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The app passed the order; the adapter's payload lost its proof."""
    broker.positions = [_position(side="BUY", qty=0.01)]
    broker.mutate = lambda payload: payload.pop("reduceOnly", None)
    exit_code = _run(
        monkeypatch,
        broker,
        _broken_settings(),
        _place_order_argv(side="sell", trade_side="CLOSE", reduce_only=True),
        run_dir=tmp_path,
    )
    assert exit_code == 2
    assert broker.calls == []


def test_t07_flash_close_payload_cannot_gain_a_side(
    broker: Broker, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    broker.positions = [_position()]
    broker.mutate = lambda payload: payload.update(side="BUY", qty="0.01")
    exit_code = _run(
        monkeypatch,
        broker,
        _broken_settings(),
        ["close-position", "--position-id", "pos-1"],
        run_dir=tmp_path,
    )
    assert exit_code == 2
    assert broker.calls == []


def test_t08_an_unreadable_position_is_not_an_exemption(
    broker: Broker, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    broker.position_error = True
    exit_code = _run(
        monkeypatch,
        broker,
        _broken_settings(),
        _place_order_argv(side="sell", trade_side="CLOSE", reduce_only=True),
        run_dir=tmp_path,
    )
    assert exit_code == 2
    assert broker.calls == []


def test_t08_a_missing_position_mode_is_ambiguous(
    broker: Broker, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    broker.positions = [_position(position_mode="")]
    exit_code = _run(
        monkeypatch,
        broker,
        _broken_settings(),
        _place_order_argv(side="sell", trade_side="CLOSE", reduce_only=True),
        run_dir=tmp_path,
    )
    assert exit_code == 2
    assert broker.calls == []


def test_t08_a_stale_snapshot_is_not_an_exemption(
    broker: Broker, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from trading_bot.execution.order_authorization import PositionState

    broker.positions = [_position()]
    monkeypatch.setattr(
        app_module,
        "_position_state",
        lambda position: PositionState(
            position_id=position.position_id,
            symbol=position.symbol,
            side=position.side,
            qty=position.qty,
            position_mode=position.position_mode,
            observed_at=time.time() - 120,
        ),
    )
    exit_code = _run(
        monkeypatch,
        broker,
        _broken_settings(),
        _place_order_argv(side="sell", trade_side="CLOSE", reduce_only=True),
        run_dir=tmp_path,
    )
    assert exit_code == 2
    assert broker.calls == []


# ---------------------------------------------------------------------------
# T09 / T10 — TP/SL is not a reduction; the stop keeps its priority
# ---------------------------------------------------------------------------


def test_t09_set_tpsl_takes_the_gate(
    broker: Broker, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    exit_code = _run(
        monkeypatch,
        broker,
        _broken_settings(),
        [
            "set-tpsl",
            "--symbol",
            "BTCUSDT",
            "--position-id",
            "pos-1",
            "--qty",
            "0.01",
            "--tp-price",
            "110",
            "--sl-price",
            "90",
        ],
        run_dir=tmp_path,
    )
    assert exit_code == 2
    assert broker.calls == []


def test_t09_set_tpsl_still_works_when_every_check_passes(
    broker: Broker, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    exit_code = _run(
        monkeypatch,
        broker,
        _legal_settings(),
        [
            "set-tpsl",
            "--symbol",
            "BTCUSDT",
            "--position-id",
            "pos-1",
            "--qty",
            "0.01",
            "--tp-price",
            "110",
            "--sl-price",
            "90",
        ],
        run_dir=tmp_path,
    )
    assert exit_code == 0
    assert [call["sink"] for call in broker.calls] == ["futures.place_position_tpsl"]


def test_t10_the_stop_skips_the_loop_without_sending(
    broker: Broker, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / HOT_STOP_FILE_NAME).write_text("operator stop\n", encoding="utf-8")
    exit_code = _run(
        monkeypatch, broker, _legal_settings(), _run_argv(confirm=True), run_dir=tmp_path
    )
    assert exit_code == 0
    assert broker.calls == []


def test_t10_a_proven_close_survives_the_stop(
    broker: Broker, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / HOT_STOP_FILE_NAME).write_text("operator stop\n", encoding="utf-8")
    broker.positions = [_position()]
    exit_code = _run(
        monkeypatch,
        broker,
        _legal_settings(),
        ["close-position", "--position-id", "pos-1"],
        run_dir=tmp_path,
    )
    assert exit_code == 0
    assert len(broker.calls) == 1


# ---------------------------------------------------------------------------
# T11 — the boundary refuses a direct call that skipped the CLI check
# ---------------------------------------------------------------------------


def test_t11_the_sink_blocks_a_direct_unconfirmed_call(
    broker: Broker, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from trading_bot.autonomous.hot_stop import HotStopGate
    from trading_bot.execution.order_authorization import OrderIntent, OrderPrimitive
    from trading_bot.paper.kill_switch_v2 import KillSwitch

    gate = HotStopGate(kill_switch=KillSwitch(), run_dir=tmp_path)
    intent = OrderIntent(
        entrypoint="run",
        primitive=OrderPrimitive.FUTURES_PLACE_ORDER,
        symbol="BTCUSDT",
        side="BUY",
        qty=0.01,
        trade_side="OPEN",
    )
    with app_module._live_order_boundary(
        gate,
        intent=intent,
        position=None,
        capabilities=BITUNIX_FUTURES,
        settings=_legal_settings(),
        confirm_live=False,
    ) as authorization:
        assert authorization.allowed is False
        assert authorization.reason == "live_confirmation_missing"
