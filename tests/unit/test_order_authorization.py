"""RFC-TAP-EXEC-SEC-002 — order classification, sink revalidation and proof.

The P0 boundary took ``opens_risk`` from its caller. These tests pin the
replacement: the category is derived from the order's primitive, its fields, the
position it acts on and the venue's real payload, and only a venue-enforced
reduction may skip the opening gate.

The last group is about the *wire* payload: a guard installed by the boundary is
invoked inside the adapter immediately before ``_request``. Dropping
``reduceOnly`` or injecting a side must refuse with zero HTTP calls.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from trading_bot import app as app_module
from trading_bot.autonomous.hot_stop import HotStopGate
from trading_bot.config.runtime import TradingMode
from trading_bot.domain.enums.kill_switch import KillSwitchAction
from trading_bot.execution.order_authorization import (
    BITUNIX_FUTURES,
    BITUNIX_SPOT,
    CONNECTOR,
    LiveOrderAuthorizationError,
    OrderCategory,
    OrderIntent,
    OrderPrimitive,
    PositionState,
    build_reduction_payload_guard,
    classify_order,
    reduction_payload_violations,
)
from trading_bot.market_data.bitunix_futures import BitunixFuturesClient
from trading_bot.market_data.fake import build_demo_settings
from trading_bot.paper.kill_switch_v2 import KillSwitch


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


def _position(**overrides: Any) -> PositionState:
    values: dict[str, Any] = {
        "position_id": "pos-1",
        "symbol": "BTCUSDT",
        "side": "BUY",
        "qty": 0.01,
        "position_mode": "ONE_WAY",
        "observed_at": time.time(),
    }
    values.update(overrides)
    return PositionState(**values)


def _close_intent(**overrides: Any) -> OrderIntent:
    values: dict[str, Any] = {
        "entrypoint": "place-order",
        "primitive": OrderPrimitive.FUTURES_PLACE_ORDER,
        "symbol": "BTCUSDT",
        "side": "SELL",
        "qty": 0.01,
        "trade_side": "CLOSE",
        "reduce_only": True,
        "position_id": "pos-1",
    }
    values.update(overrides)
    return OrderIntent(**values)


def _classify(intent: OrderIntent, *, position: PositionState | None, capabilities: Any = None):
    return classify_order(
        intent,
        position=position,
        capabilities=capabilities or BITUNIX_FUTURES,
        now=time.time(),
    )


# ---------------------------------------------------------------------------
# Classification: only a venue-enforced reduction is exempt
# ---------------------------------------------------------------------------


def test_a_futures_open_is_opening() -> None:
    intent = OrderIntent(
        entrypoint="place-order",
        primitive=OrderPrimitive.FUTURES_PLACE_ORDER,
        symbol="BTCUSDT",
        side="BUY",
        qty=0.01,
        trade_side="OPEN",
    )
    assert _classify(intent, position=None).category is OrderCategory.OPEN_OR_INCREASE


def test_reduce_only_close_on_a_matching_one_way_position_is_proven() -> None:
    decision = _classify(_close_intent(), position=_position())
    assert decision.category is OrderCategory.PROVEN_REDUCTION
    assert decision.rule == "R-REDUCE-ONLY"


def test_close_side_must_oppose_the_position() -> None:
    """`sell` is not a reduction when the position is already short."""
    decision = _classify(_close_intent(side="BUY"), position=_position(side="BUY"))
    assert decision.category is OrderCategory.UNKNOWN
    assert decision.rule == "R-CLOSE-WRONG-SIDE"


def test_closing_a_short_position_uses_buy() -> None:
    decision = _classify(
        _close_intent(side="BUY", qty=0.5), position=_position(side="SELL", qty=0.5)
    )
    assert decision.category is OrderCategory.PROVEN_REDUCTION


def test_trade_side_close_without_reduce_only_is_not_a_proof() -> None:
    decision = _classify(_close_intent(reduce_only=False), position=_position())
    assert decision.category is OrderCategory.UNKNOWN
    assert decision.rule == "R-CLOSE-NO-REDUCE-ONLY"


def test_reduce_only_without_trade_side_close_is_not_a_proof() -> None:
    decision = _classify(_close_intent(trade_side="OPEN"), position=_position())
    assert decision.category is OrderCategory.UNKNOWN
    assert decision.rule == "R-CLOSE-WRONG-TRADE-SIDE"


def test_a_quantity_above_the_position_is_not_a_proof() -> None:
    decision = _classify(_close_intent(qty=0.02), position=_position(qty=0.01))
    assert decision.category is OrderCategory.UNKNOWN
    assert decision.rule == "R-CLOSE-QTY-EXCESS"


@pytest.mark.parametrize("qty", [0.0, -0.01])
def test_a_non_positive_quantity_is_not_a_proof(qty: float) -> None:
    decision = _classify(_close_intent(qty=qty), position=_position())
    assert decision.category is OrderCategory.UNKNOWN
    assert decision.rule == "R-CLOSE-QTY-INVALID"


def test_a_zero_position_cannot_be_reduced() -> None:
    decision = _classify(_close_intent(), position=_position(qty=0.0))
    assert decision.category is OrderCategory.UNKNOWN
    assert decision.rule == "R-CLOSE-ZERO-POSITION"


def test_a_missing_position_is_unknown() -> None:
    decision = _classify(_close_intent(), position=None)
    assert decision.category is OrderCategory.UNKNOWN
    assert decision.rule == "R-CLOSE-NO-POSITION"


def test_a_stale_position_is_unknown() -> None:
    decision = _classify(_close_intent(), position=_position(observed_at=time.time() - 120))
    assert decision.category is OrderCategory.UNKNOWN
    assert decision.rule == "R-CLOSE-STALE"


def test_hedge_mode_is_ambiguous_and_unknown() -> None:
    for mode in ("HEDGE", "", "UNKNOWN"):
        decision = _classify(_close_intent(), position=_position(position_mode=mode))
        assert decision.category is OrderCategory.UNKNOWN, mode
        assert decision.rule == "R-CLOSE-HEDGE-AMBIGUOUS", mode


def test_a_venue_without_reduce_only_cannot_prove_a_reduction() -> None:
    decision = _classify(_close_intent(), position=_position(), capabilities=BITUNIX_SPOT)
    assert decision.category is OrderCategory.UNKNOWN
    assert decision.rule == "R-VENUE-NO-REDUCE-ONLY"


def test_flash_close_is_proven_by_the_endpoint_shape() -> None:
    intent = OrderIntent(
        entrypoint="close-position",
        primitive=OrderPrimitive.FUTURES_FLASH_CLOSE,
        symbol="BTCUSDT",
        side="",
        qty=0.01,
        trade_side="CLOSE",
        reduce_only=True,
        position_id="pos-1",
    )
    decision = _classify(intent, position=_position())
    assert decision.category is OrderCategory.PROVEN_REDUCTION
    assert decision.rule == "R-FLASH-CLOSE"


def test_flash_close_with_a_stale_position_is_unknown() -> None:
    intent = OrderIntent(
        entrypoint="close-position",
        primitive=OrderPrimitive.FUTURES_FLASH_CLOSE,
        symbol="BTCUSDT",
        side="",
        qty=0.01,
        position_id="pos-1",
    )
    decision = _classify(intent, position=_position(observed_at=time.time() - 120))
    assert decision.category is OrderCategory.UNKNOWN
    assert decision.rule == "R-FLASH-STALE"


def test_flash_close_without_a_position_is_unknown() -> None:
    intent = OrderIntent(
        entrypoint="close-position",
        primitive=OrderPrimitive.FUTURES_FLASH_CLOSE,
        symbol="BTCUSDT",
        side="",
        qty=0.01,
        position_id="pos-1",
    )
    assert _classify(intent, position=None).category is OrderCategory.UNKNOWN


def test_set_tpsl_is_never_a_proven_reduction() -> None:
    intent = OrderIntent(
        entrypoint="set-tpsl",
        primitive=OrderPrimitive.FUTURES_TP_SL,
        symbol="BTCUSDT",
        side="",
        qty=0.01,
        position_id="pos-1",
        changes_protection=True,
    )
    decision = _classify(intent, position=_position())
    assert decision.category is OrderCategory.UNKNOWN
    assert decision.rule == "R-TPSL-NOT-MONOTONIC"


def test_spot_buy_is_opening_and_spot_sell_is_unknown() -> None:
    buy = OrderIntent(
        entrypoint="place-order",
        primitive=OrderPrimitive.SPOT_PLACE_ORDER,
        symbol="BTC/USDT",
        side="buy",
        qty=0.01,
    )
    sell = OrderIntent(
        entrypoint="place-order",
        primitive=OrderPrimitive.SPOT_PLACE_ORDER,
        symbol="BTC/USDT",
        side="sell",
        qty=0.01,
    )
    assert _classify(buy, position=None).category is OrderCategory.OPEN_OR_INCREASE
    assert _classify(sell, position=None).category is OrderCategory.UNKNOWN
    connector_sell = OrderIntent(
        entrypoint="run",
        primitive=OrderPrimitive.CONNECTOR_CREATE_ORDER,
        symbol="BTC/USDT",
        side="sell",
        qty=0.01,
    )
    assert _classify(connector_sell, position=None, capabilities=CONNECTOR).category is (
        OrderCategory.UNKNOWN
    )


# ---------------------------------------------------------------------------
# The final wire payload is revalidated
# ---------------------------------------------------------------------------


def _wire_payload() -> dict[str, Any]:
    return {
        "symbol": "BTCUSDT",
        "side": "SELL",
        "qty": "0.01",
        "orderType": "MARKET",
        "tradeSide": "CLOSE",
        "reduceOnly": True,
        "positionId": "pos-1",
    }


def test_a_valid_reduction_payload_has_no_violations() -> None:
    violations = reduction_payload_violations(
        intent=_close_intent(), payload=_wire_payload(), position=_position()
    )
    assert violations == ()


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (lambda payload: payload.pop("reduceOnly"), "reduce_only_not_true"),
        (lambda payload: payload.update(reduceOnly="true"), "reduce_only_not_true"),
        (lambda payload: payload.update(reduceOnly=False), "reduce_only_not_true"),
        (lambda payload: payload.update(tradeSide="OPEN"), "trade_side_not_close"),
        (lambda payload: payload.update(side="BUY"), "side_does_not_close_position"),
        (lambda payload: payload.update(positionId="other"), "position_id_mismatch"),
        (lambda payload: payload.update(positionSide="LONG"), "unexpected_position_side"),
        (lambda payload: payload.update(qty="0.02"), "payload_qty_exceeds_position"),
        (lambda payload: payload.update(qty="0.005"), "payload_qty_differs_from_authorised_intent"),
        (lambda payload: payload.update(qty="nan"), "payload_qty_invalid"),
    ],
)
def test_a_mutated_payload_is_refused(mutation: Any, expected: str) -> None:
    payload = _wire_payload()
    mutation(payload)
    violations = reduction_payload_violations(
        intent=_close_intent(), payload=payload, position=_position()
    )
    assert expected in violations, violations


def test_flash_close_payload_cannot_gain_a_side() -> None:
    intent = OrderIntent(
        entrypoint="close-position",
        primitive=OrderPrimitive.FUTURES_FLASH_CLOSE,
        symbol="BTCUSDT",
        side="",
        qty=0.01,
        position_id="pos-1",
    )
    clean = reduction_payload_violations(
        intent=intent, payload={"positionId": "pos-1"}, position=_position()
    )
    assert clean == ()
    mutated = reduction_payload_violations(
        intent=intent,
        payload={"positionId": "pos-1", "side": "BUY", "qty": "0.01"},
        position=_position(),
    )
    assert "flash_close_extra_fields:qty,side" in mutated


# ---------------------------------------------------------------------------
# The sink: confirmation, stop, gate and the typed category
# ---------------------------------------------------------------------------


def _boundary(
    gate: HotStopGate,
    *,
    intent: OrderIntent,
    position: PositionState | None,
    settings: Any,
    confirm_live: bool,
    capabilities: Any = BITUNIX_FUTURES,
    audit_path: Path | None = None,
) -> app_module.LiveOrderAuthorization:
    with app_module._live_order_boundary(
        gate,
        intent=intent,
        position=position,
        capabilities=capabilities,
        settings=settings,
        confirm_live=confirm_live,
        run_id="test-run",
        audit_path=audit_path,
    ) as authorization:
        return authorization


def _opening_intent() -> OrderIntent:
    return OrderIntent(
        entrypoint="run",
        primitive=OrderPrimitive.FUTURES_PLACE_ORDER,
        symbol="BTCUSDT",
        side="BUY",
        qty=0.01,
        trade_side="OPEN",
    )


def test_a_live_entrypoint_without_confirmation_never_reaches_the_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        app_module,
        "_evaluate_live_gate",
        lambda settings: calls.append("gate") or app_module.LiveGateVerdict(True),
    )
    gate = HotStopGate(kill_switch=KillSwitch(), run_dir=tmp_path)

    authorization = _boundary(
        gate,
        intent=_opening_intent(),
        position=None,
        settings=_legal_settings(),
        confirm_live=False,
    )

    assert authorization.allowed is False
    assert authorization.reason == "live_confirmation_missing"
    assert calls == [], "the gate ran for an invocation that was never confirmed"


def test_confirmation_present_still_requires_all_ten_checks(tmp_path: Path) -> None:
    gate = HotStopGate(kill_switch=KillSwitch(), run_dir=tmp_path)
    authorization = _boundary(
        gate,
        intent=_opening_intent(),
        position=None,
        settings=_broken_settings(),
        confirm_live=True,
    )
    assert authorization.allowed is False
    assert authorization.reason.startswith("live_gate_blocked:")
    assert "GATE-004" in authorization.reason


def test_a_proven_reduction_is_allowed_with_a_rejecting_gate_and_an_active_stop(
    tmp_path: Path,
) -> None:
    switch = KillSwitch()
    switch.activate(KillSwitchAction.USER)
    gate = HotStopGate(kill_switch=switch, run_dir=tmp_path)

    authorization = _boundary(
        gate,
        intent=_close_intent(),
        position=_position(),
        settings=_broken_settings(),
        confirm_live=False,
    )

    assert authorization.allowed is True
    assert authorization.category is OrderCategory.PROVEN_REDUCTION
    assert authorization.gate is None, "a proven reduction must not consult the opening gate"


def test_an_unknown_order_with_a_rejecting_gate_is_refused(tmp_path: Path) -> None:
    gate = HotStopGate(kill_switch=KillSwitch(), run_dir=tmp_path)
    sell = OrderIntent(
        entrypoint="place-order",
        primitive=OrderPrimitive.SPOT_PLACE_ORDER,
        symbol="BTC/USDT",
        side="sell",
        qty=0.01,
    )
    authorization = _boundary(
        gate,
        intent=sell,
        position=None,
        settings=_broken_settings(),
        confirm_live=True,
        capabilities=BITUNIX_SPOT,
    )
    assert authorization.allowed is False
    assert authorization.category is OrderCategory.UNKNOWN
    assert authorization.reason.startswith("live_gate_blocked:")


def test_an_unknown_protective_change_is_refused_while_stopped(tmp_path: Path) -> None:
    switch = KillSwitch()
    switch.activate(KillSwitchAction.USER)
    gate = HotStopGate(kill_switch=switch, run_dir=tmp_path)
    tpsl = OrderIntent(
        entrypoint="set-tpsl",
        primitive=OrderPrimitive.FUTURES_TP_SL,
        symbol="BTCUSDT",
        side="",
        qty=0.01,
        position_id="pos-1",
        changes_protection=True,
    )
    authorization = _boundary(
        gate,
        intent=tpsl,
        position=None,
        settings=_legal_settings(),
        confirm_live=False,
    )
    assert authorization.allowed is False
    assert authorization.reason == "process_kill_switch_active"


def test_a_stop_engages_between_the_check_and_the_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The in-flight lock is the authority, not the earlier read."""
    gate = HotStopGate(kill_switch=KillSwitch(), run_dir=tmp_path)
    real_boundary = gate.order_boundary

    def engaged_on_entry(*, run_id: str = "") -> Any:
        gate.engage("operator stop", run_id=run_id)
        return real_boundary(run_id=run_id)

    monkeypatch.setattr(gate, "order_boundary", engaged_on_entry)
    authorization = _boundary(
        gate,
        intent=_opening_intent(),
        position=None,
        settings=_legal_settings(),
        confirm_live=True,
    )
    assert authorization.allowed is False
    assert authorization.reason.startswith("kill_switch_engaged_hot")


def test_a_classifier_that_raises_denies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("classifier crashed")

    monkeypatch.setattr(app_module, "classify_order", explode)
    gate = HotStopGate(kill_switch=KillSwitch(), run_dir=tmp_path)
    authorization = _boundary(
        gate,
        intent=_opening_intent(),
        position=None,
        settings=_legal_settings(),
        confirm_live=True,
    )
    assert authorization.allowed is False
    assert authorization.rule == "R-CLASSIFIER-ERROR"
    assert authorization.reason == "classifier_error:RuntimeError"


def test_every_decision_is_recorded_without_secrets(tmp_path: Path) -> None:
    audit = tmp_path / "authorizations.jsonl"
    gate = HotStopGate(kill_switch=KillSwitch(), run_dir=tmp_path)

    _boundary(
        gate,
        intent=_opening_intent(),
        position=None,
        settings=_legal_settings(),
        confirm_live=True,
        audit_path=audit,
    )
    _boundary(
        gate,
        intent=_close_intent(),
        position=_position(),
        settings=_legal_settings(),
        confirm_live=False,
        audit_path=audit,
    )

    lines = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]
    assert [line["category"] for line in lines] == [
        OrderCategory.OPEN_OR_INCREASE.value,
        OrderCategory.PROVEN_REDUCTION.value,
    ]
    assert lines[0]["gate_evaluated"] is True
    assert lines[1]["gate_evaluated"] is False
    assert all(len(line["settings_fingerprint"]) == 16 for line in lines)
    text = audit.read_text(encoding="utf-8")
    assert "test-key" not in text and "test-secret" not in text
    assert lines[0]["entrypoint"] == "run"
    assert lines[1]["rule"] == "R-REDUCE-ONLY"


# ---------------------------------------------------------------------------
# The adapter invokes the guard before it builds a request
# ---------------------------------------------------------------------------


def test_place_order_calls_the_guard_before_the_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = BitunixFuturesClient(api_key="k", api_secret="s")
    requests: list[dict[str, Any]] = []

    def fake_request(method: str, path: str, **kwargs: Any) -> Any:
        requests.append({"method": method, "path": path, **kwargs})
        return {"orderId": "1"}

    monkeypatch.setattr(client, "_request", fake_request)
    seen: list[dict[str, Any]] = []

    client.place_order(
        symbol="BTCUSDT",
        side="SELL",
        qty=0.01,
        trade_side="CLOSE",
        reduce_only=True,
        position_id="pos-1",
        payload_guard=seen.append,
    )

    assert len(seen) == 1
    assert seen[0]["reduceOnly"] is True
    assert seen[0]["tradeSide"] == "CLOSE"
    assert len(requests) == 1


def test_a_raising_guard_prevents_the_request(monkeypatch: pytest.MonkeyPatch) -> None:
    client = BitunixFuturesClient(api_key="k", api_secret="s")
    requests: list[str] = []

    def fake_request(method: str, path: str, **kwargs: Any) -> Any:
        requests.append(path)
        return {"orderId": "1"}

    monkeypatch.setattr(client, "_request", fake_request)
    guard = build_reduction_payload_guard(intent=_close_intent(), position=_position())

    with pytest.raises(LiveOrderAuthorizationError):
        client.place_order(
            symbol="BTCUSDT",
            side="SELL",
            qty=0.01,
            trade_side="CLOSE",
            reduce_only=False,  # dropped: the guard must catch it
            position_id="pos-1",
            payload_guard=guard,
        )
    assert requests == []


def test_flash_close_guard_sees_the_exact_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    client = BitunixFuturesClient(api_key="k", api_secret="s")
    seen: list[dict[str, Any]] = []
    monkeypatch.setattr(client, "_request", lambda *a, **k: {"positionId": "pos-1"})

    client.flash_close_position("pos-1", payload_guard=seen.append)

    assert seen == [{"positionId": "pos-1"}]
