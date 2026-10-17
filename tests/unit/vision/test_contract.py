"""The contract tests are the ones that keep a language model from inventing a trade."""

from __future__ import annotations

import json

import pytest

from trading_bot.vision.contract import (
    DecisionParseError,
    VisionDecision,
    parse_decision,
    resolve_intent,
)

VALID_LONG = {
    "schema_version": "ai-vision-decision/1",
    "symbol": "BTC/USDT",
    "action": "LONG",
    "confidence": 0.62,
    "horizon_bars": 12,
    "stop_loss_pct": 1.2,
    "take_profit_pct": 2.4,
    "invalidation": "close back below 61 800",
    "rationale": "Higher lows into resistance, wick rejected at 62 000 twice.",
}


def _json(**overrides: object) -> str:
    payload = {**VALID_LONG, **overrides}
    return json.dumps(payload)


def test_a_well_formed_answer_parses_into_a_decision():
    decision = parse_decision(_json(), symbol="BTC/USDT")

    assert isinstance(decision, VisionDecision)
    assert decision.action == "LONG"
    assert decision.confidence == pytest.approx(0.62)
    assert decision.directional is True


def test_a_fenced_json_block_is_accepted():
    text = "Here is my read.\n```json\n" + _json() + "\n```\n"

    assert parse_decision(text, symbol="BTC/USDT").action == "LONG"


def test_leading_prose_does_not_hide_a_valid_object():
    text = "Looking at the structure I would go long here: " + _json()

    assert parse_decision(text, symbol="BTC/USDT").action == "LONG"


def test_lowercase_action_and_symbol_are_normalised():
    decision = parse_decision(_json(action="long", symbol="btc/usdt"), symbol="BTC/USDT")

    assert decision.action == "LONG"
    assert decision.symbol == "BTC/USDT"


@pytest.mark.parametrize("action", ["LONG", "SHORT"])
def test_a_directional_call_without_a_stop_is_refused(action):
    payload = {key: value for key, value in VALID_LONG.items() if key != "stop_loss_pct"}
    payload["action"] = action

    with pytest.raises(DecisionParseError) as caught:
        parse_decision(json.dumps(payload), symbol="BTC/USDT")

    assert caught.value.code == "SCHEMA_VIOLATION"
    assert "stop_loss_pct" in caught.value.detail


def test_an_empty_answer_is_a_parse_failure_not_a_no_trade():
    with pytest.raises(DecisionParseError) as caught:
        parse_decision("   \n ", symbol="BTC/USDT")

    assert caught.value.code == "EMPTY_RESPONSE"


def test_prose_without_json_is_rejected():
    with pytest.raises(DecisionParseError) as caught:
        parse_decision("I think bitcoin looks bullish, I would buy.", symbol="BTC/USDT")

    assert caught.value.code == "NO_JSON"


def test_broken_json_is_rejected():
    with pytest.raises(DecisionParseError) as caught:
        parse_decision('{"action": "LONG", "symbol": ', symbol="BTC/USDT")

    assert caught.value.code == "INVALID_JSON"


def test_nan_conviction_is_rejected():
    """``nan`` compares false against every limit, so it must never reach the risk gate."""
    text = _json(confidence=float("nan")).replace("NaN", "NaN")

    with pytest.raises(DecisionParseError) as caught:
        parse_decision(text, symbol="BTC/USDT")

    assert caught.value.code in {"INVALID_JSON", "SCHEMA_VIOLATION"}


def test_infinity_is_rejected():
    with pytest.raises(DecisionParseError):
        parse_decision(_json(confidence=float("inf")), symbol="BTC/USDT")


def test_an_invented_field_is_an_error_not_an_ignored_extra():
    with pytest.raises(DecisionParseError) as caught:
        parse_decision(_json(leverage=50, size_usdt=9_000), symbol="BTC/USDT")

    assert caught.value.code == "SCHEMA_VIOLATION"
    assert "leverage" in caught.value.detail


@pytest.mark.parametrize(
    "overrides",
    [
        {"confidence": 1.4},
        {"confidence": -0.1},
        {"horizon_bars": 0},
        {"horizon_bars": 500},
        {"stop_loss_pct": 0},
        {"stop_loss_pct": 90},
        {"action": "BUY"},
        {"symbol": "NOT A SYMBOL"},
        {"rationale": ""},
    ],
)
def test_out_of_range_or_mistyped_values_are_rejected(overrides):
    with pytest.raises(DecisionParseError) as caught:
        parse_decision(_json(**overrides), symbol="BTC/USDT")

    assert caught.value.code == "SCHEMA_VIOLATION"


def test_a_decision_about_another_symbol_is_a_mismatch():
    with pytest.raises(DecisionParseError) as caught:
        parse_decision(_json(symbol="ETH/USDT"), symbol="BTC/USDT")

    assert caught.value.code == "SYMBOL_MISMATCH"


def test_confidence_accepts_the_edges_of_its_range():
    assert parse_decision(_json(confidence=0), symbol="BTC/USDT").confidence == 0.0
    assert parse_decision(_json(confidence=1), symbol="BTC/USDT").confidence == 1.0


@pytest.mark.parametrize(
    ("action", "side", "intent", "reason"),
    [
        ("LONG", None, "OPEN_LONG", "MODEL_LONG"),
        ("SHORT", None, "OPEN_SHORT", "MODEL_SHORT"),
        ("LONG", "buy", "NONE", "ALREADY_LONG"),
        ("LONG", "sell", "NONE", "OPPOSITE_SHORT_OPEN"),
        ("SHORT", "sell", "NONE", "ALREADY_SHORT"),
        ("SHORT", "buy", "NONE", "OPPOSITE_LONG_OPEN"),
        ("CLOSE", None, "NONE", "NO_POSITION_TO_CLOSE"),
        ("CLOSE", "buy", "CLOSE", "MODEL_CLOSE"),
        ("CLOSE", "sell", "CLOSE", "MODEL_CLOSE"),
        ("NO_TRADE", None, "NONE", "MODEL_NO_TRADE"),
        ("NO_TRADE", "buy", "NONE", "MODEL_NO_TRADE"),
    ],
)
def test_coherence_with_the_book_is_mechanical(action, side, intent, reason):
    decision = parse_decision(_json(action=action), symbol="BTC/USDT")
    resolved = resolve_intent(decision, position_side=side)

    assert resolved.intent == intent
    assert resolved.reason == reason
    assert resolved.actionable is (intent != "NONE")
