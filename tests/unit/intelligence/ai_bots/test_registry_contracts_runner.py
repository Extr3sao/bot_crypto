"""El plano de bots: registro, contratos de opinión y el runner con trazas."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trading_bot.config.settings import load_settings
from trading_bot.intelligence.ai_bots.bots import (
    TraceWriter,
    build_structured_prompt,
    mtf_features,
    resample_closed,
)
from trading_bot.intelligence.ai_bots.contracts import (
    OpinionRejectedBySchema,
    opinion_from_vision_decision,
    proposal_from_opinion,
    validate_opinion,
)
from trading_bot.intelligence.ai_bots.registry import (
    ALLOWED_CAPABILITIES,
    BotCapabilityRegistry,
    BotSpec,
    RegistryError,
    default_registry,
)
from trading_bot.intelligence.ai_bots.runner import BudgetExceeded, run_bot
from trading_bot.research.economic_recovery.experiments import Bar
from trading_bot.vision.contract import parse_decision
from trading_bot.vision.provider import ReplayProvider, VisionResponse
from trading_bot.vision.settings import load_vision_config

REPO = Path(__file__).resolve().parents[4]
HOUR_MS = 3_600_000
START_MS = 1_770_000_000_000


def bars(count: int = 96, *, start: int = START_MS, drift: float = 0.004) -> list[Bar]:
    out: list[Bar] = []
    price = 100.0
    for i in range(count):
        step = -drift if i % 12 == 11 else drift
        close = price * (1.0 + step)
        out.append(
            Bar(
                ts_ms=start + i * HOUR_MS,
                open=price,
                high=max(price, close) * 1.002,
                low=min(price, close) * 0.998,
                close=close,
                volume=150.0,
            )
        )
        price = close
    return out


def spec(**overrides) -> BotSpec:
    base = dict(
        bot_id="BOT-TEST-99",
        bot_version="0.1.0",
        family="TEST",
        enabled=True,
        model_provider="replay",
        model_id="replay",
        input_contract="none",
        output_contract="AITradeOpinion",
        allowed_tools=("read_ohlcv", "invoke_llm"),
        forbidden_actions=("place_order",),
        max_calls_per_day=5,
        max_latency_ms=1000,
        cost_budget_usd=0.0,
        paper_namespace="AI_BOTS_EXPERIMENTAL",
        reliability_status="IMPLEMENTED",
    )
    base.update(overrides)
    return BotSpec(**base)


def opinion_payload(**overrides) -> dict:
    payload = {
        "bot_id": "BOT-VIS-01",
        "run_id": "run-1",
        "asset": "BTC/USDT",
        "decision": "LONG",
        "confidence": 0.6,
        "timeframe": "1h",
        "decision_time_ms": START_MS,
        "horizon_bars": 8,
        "thesis": "Higher lows into resistance.",
        "evidence_refs": ["image:abc", "bar:123"],
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------- registry


def test_the_registry_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("AI_BOTS_ENABLED", raising=False)
    registry = default_registry(env={})

    assert registry.enabled is False
    assert registry.active() == []
    assert {spec.bot_id for spec in registry.specs.values()} == {
        "BOT-VIS-01",
        "BOT-CTX-01",
        "BOT-CRI-01",
    }


def test_enabling_globally_and_per_bot_is_required():
    registry = BotCapabilityRegistry.from_env(env={"AI_BOTS_ENABLED": "true"})
    registry.register(spec(enabled=False))
    assert registry.active() == []

    registry.register(spec(bot_id="BOT-TEST-98", enabled=True))
    assert [s.bot_id for s in registry.active()] == ["BOT-TEST-98"]


def test_duplicate_ids_are_refused():
    registry = BotCapabilityRegistry()
    registry.register(spec())
    with pytest.raises(RegistryError, match="duplicate"):
        registry.register(spec())


@pytest.mark.parametrize("capability", ["place_order", "modify_risk", "call_exchange", "withdraw"])
def test_a_bot_may_never_hold_an_execution_capability(capability):
    registry = BotCapabilityRegistry()
    with pytest.raises(RegistryError) as caught:
        registry.register(spec(allowed_tools=("read_ohlcv", capability)))
    assert capability in str(caught.value)


def test_an_unknown_capability_is_refused_rather_than_granted_silently():
    registry = BotCapabilityRegistry()
    with pytest.raises(RegistryError, match="unknown capabilities"):
        registry.register(spec(allowed_tools=("read_ohlcv", "do_magic")))


def test_no_default_bot_holds_anything_outside_the_analysis_allowlist():
    registry = default_registry(env={})
    for registered in registry.specs.values():
        assert set(registered.allowed_tools) <= ALLOWED_CAPABILITIES


def test_states_come_from_the_roadmap_vocabulary():
    registry = default_registry(env={})
    registry.set_state("BOT-CTX-01", "REAL_MODEL_CALLED")
    assert registry.get("BOT-CTX-01").reliability_status == "REAL_MODEL_CALLED"
    with pytest.raises(RegistryError):
        registry.set_state("BOT-CTX-01", "PRODUCTION_READY")


def test_the_registry_projects_to_json_with_the_switch_visible(tmp_path):
    registry = default_registry(env={"AI_BOTS_ENABLED": "true"})
    target = registry.write(tmp_path / "BOT_CAPABILITY_REGISTRY.json")
    doc = json.loads(target.read_text(encoding="utf-8"))

    assert doc["schema_version"] == "AIBOT_CAPABILITY_REGISTRY_V1"
    assert doc["enabled_globally"] is True
    assert doc["bot_count"] == 3
    assert all(row["forbidden_actions"] for row in doc["bots"])


# -------------------------------------------------------------------- contracts


def test_an_opinion_round_trips_and_carries_its_evidence():
    opinion = validate_opinion(opinion_payload())
    proposal = proposal_from_opinion("PROP-1", opinion)

    assert proposal.side == "buy"
    assert proposal.opinion_digest and len(proposal.opinion_digest) == 64
    assert proposal.evidence_refs == ["image:abc", "bar:123"]
    assert proposal.risk_approved_notional_usdt is None, "a bot never sizes"


@pytest.mark.parametrize("field", ["quantity", "leverage", "notional_usdt", "execute"])
def test_forbidden_fields_are_rejected_not_ignored(field):
    with pytest.raises(OpinionRejectedBySchema) as caught:
        validate_opinion(opinion_payload(**{field: 1}))
    assert caught.value.code == "SCHEMA_FORBIDDEN_FIELD"
    assert field in caught.value.detail


def test_no_trade_is_a_decision_not_a_proposal():
    opinion = validate_opinion(opinion_payload(decision="NO_TRADE", thesis="No edge here."))
    with pytest.raises(OpinionRejectedBySchema) as caught:
        proposal_from_opinion("PROP-2", opinion)
    assert caught.value.code == "NOT_A_PROPOSAL"


def test_a_visual_decision_lifts_into_an_opinion_with_the_image_hash():
    decision = parse_decision(
        '{"schema_version":"ai-vision-decision/1","symbol":"BTC/USDT","action":"SHORT",'
        '"confidence":0.4,"horizon_bars":6,"stop_loss_pct":1.1,"take_profit_pct":2.2,'
        '"rationale":"Lower highs.","invalidation":"above 63 000","invalidation_price":63000}',
        symbol="BTC/USDT",
    )
    opinion = opinion_from_vision_decision(
        decision,
        bot_id="BOT-VIS-01",
        run_id="run-9",
        asset="BTC/USDT",
        timeframe="1h",
        image_sha256="deadbeef",
        decision_time_ms=START_MS,
    )

    assert opinion.decision == "SHORT"
    assert "image:deadbeef" in opinion.evidence_refs
    assert opinion.invalidation_price == pytest.approx(63000.0)


# ------------------------------------------------------------------------- CTX


def test_htf_resampling_only_uses_complete_groups():
    series = bars(10)
    grouped = resample_closed(series, 4)
    assert len(grouped) == 2, "10 bars make two complete 4-bar groups; the tail is dropped"
    assert grouped[0]["open"] == pytest.approx(float(series[0].open))
    assert grouped[1]["close"] == pytest.approx(float(series[7].close))


def test_mtf_features_are_causal_and_labelled():
    features = mtf_features(bars(160, drift=0.01))

    assert features["bars"] == 160
    assert features["regime"] in {"TREND_UP", "TREND_DOWN", "RANGE", "FLAT", "UNKNOWN"}
    assert features["last_close"] == pytest.approx(float(bars(160, drift=0.01)[-1].close))
    assert features["htf_4h"]["last_closed_open_ms"] is not None


def test_the_structured_prompt_never_claims_an_image():
    prompt = build_structured_prompt(
        {
            "symbol": "BTC/USDT",
            "timeframe": "1h",
            "equity": 10_000.0,
            "open_positions": 0,
            "max_open_positions": 3,
            "risk_per_trade_pct": 0.25,
            "max_weekly_loss_pct": 3.0,
            "position": None,
        },
        bars(160),
    )

    text = (prompt.system + prompt.user).lower()
    assert "you have no chart image" in text
    assert "candlestick chart image and a short market context" not in text
    assert prompt.version == "aibot-ctx-prompt/1"


# ---------------------------------------------------------------------- runner


def long_answer(request) -> str:
    symbol = getattr(request.chart, "symbol", "BTC/USDT")
    return json.dumps(
        {
            "schema_version": "ai-vision-decision/1",
            "symbol": symbol,
            "action": "LONG",
            "confidence": 0.7,
            "horizon_bars": 8,
            "stop_loss_pct": 1.0,
            "take_profit_pct": 2.0,
            "rationale": "traction",
        }
    )


def vision_config(**lane_overrides):
    config = load_vision_config(env={})
    lane = config.lane
    merged = {
        "timeframe": "1h",
        "window_bars": 30,
        "decision_every_bars": 15,
        "max_calls_per_run": 40,
        "max_estimated_spend_usd": 5.0,
        **lane_overrides,
    }
    return config.__class__(provider=config.provider, lane=lane.__class__(**merged))


def test_the_runner_refuses_a_disabled_bot(tmp_path):
    registry = default_registry(env={})
    with pytest.raises(PermissionError, match="not enabled"):
        run_bot(
            registry=registry,
            bot_id="BOT-VIS-01",
            series={"BTC/USDT": bars()},
            provider=ReplayProvider([long_answer] * 5),
            risk_policy=load_settings(config_dir=REPO / "config", env_file=None).risk,
            out_dir=tmp_path,
            config=vision_config(),
        )


def test_a_bot_run_trades_the_canonical_book_and_writes_both_traces(tmp_path):
    registry = default_registry(env={"AI_BOTS_ENABLED": "true"})
    summary = run_bot(
        registry=registry,
        bot_id="BOT-CTX-01",
        series={"BTC/USDT": bars()},
        provider=ReplayProvider(long_answer),
        risk_policy=load_settings(config_dir=REPO / "config", env_file=None).risk,
        out_dir=tmp_path,
        config=vision_config(),
        prompt_builder=build_structured_prompt,
        allow_disabled=True,
    )

    assert summary["bot_id"] == "BOT-CTX-01"
    assert summary["fills"] >= 1, "the CTX bot must trade the same book, not a mock book"
    assert summary["closed_trades"] >= 1
    assert summary["model_status"] == "MOCK_TEST"
    invocations = (tmp_path / "MODEL_INVOCATIONS.jsonl").read_text(encoding="utf-8").splitlines()
    decisions = (tmp_path / "BOT_DECISION_TRACE.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(invocations) == summary["provider_calls_traced"]
    assert decisions, "the run must leave a decision trace"
    assert json.loads(invocations[0])["prompt_id"] == "aibot-ctx-prompt/1"


def test_the_traced_provider_stops_at_the_declared_budget(tmp_path):
    registry = default_registry(env={"AI_BOTS_ENABLED": "true"})
    summary = run_bot(
        registry=registry,
        bot_id="BOT-CTX-01",
        series={"BTC/USDT": bars()},
        provider=ReplayProvider(long_answer),
        risk_policy=load_settings(config_dir=REPO / "config", env_file=None).risk,
        out_dir=tmp_path,
        config=vision_config(decision_every_bars=5),
        prompt_builder=build_structured_prompt,
        max_calls=2,
        allow_disabled=True,
    )

    assert summary["provider_calls_traced"] == 2
    assert summary["stop_reason"] == "MAX_CALLS_REACHED"
    rows = [
        json.loads(line)
        for line in (tmp_path / "MODEL_INVOCATIONS.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 2, "the lane stops before paying for an over-budget attempt"
    assert all(row["model_status"] == "OK" for row in rows)


def test_a_traced_provider_records_a_failed_call_with_its_code(tmp_path):
    from trading_bot.intelligence.ai_bots.runner import TracedProvider
    from trading_bot.vision.chart import render_chart_png
    from trading_bot.vision.prompt import build_prompt
    from trading_bot.vision.provider import ProviderError, VisionRequest

    class Failing:
        name = "failing"

        def analyze(self, request):
            raise ProviderError("AUTH_ERROR", "no key", attempts=1)

    traces = TraceWriter(tmp_path)
    traced = TracedProvider(
        inner=Failing(), bot_id="BOT-VIS-01", run_id="r", traces=traces, max_calls=3
    )
    request = VisionRequest(
        chart=render_chart_png(bars(40), symbol="BTC/USDT"),
        prompt=build_prompt(
            {
                "symbol": "BTC/USDT",
                "timeframe": "1h",
                "window_bars": 40,
                "last_close": 100.0,
                "equity": 10_000.0,
                "open_positions": 0,
                "max_open_positions": 3,
                "risk_per_trade_pct": 0.25,
                "max_weekly_loss_pct": 3.0,
                "position": None,
            }
        ),
        decision_ts_ms=START_MS,
    )
    with pytest.raises(ProviderError):
        traced.analyze(request)

    row = json.loads((tmp_path / "MODEL_INVOCATIONS.jsonl").read_text(encoding="utf-8").strip())
    assert row["model_status"] == "AUTH_ERROR"
    assert row["image_attached"] is False


def test_budget_exceeded_is_a_provider_error_not_a_silent_stop():
    error = BudgetExceeded("BOT-VIS-01", 3)
    assert error.code == "CALL_BUDGET_EXCEEDED"
    assert "3" in error.detail


def test_the_wrapper_itself_refuses_past_the_budget(tmp_path):
    """Defence in depth: even a lane that ignores its own limit cannot overspend."""
    from trading_bot.intelligence.ai_bots.runner import TracedProvider
    from trading_bot.vision.chart import render_chart_png
    from trading_bot.vision.prompt import build_prompt
    from trading_bot.vision.provider import VisionRequest

    traced = TracedProvider(
        inner=ReplayProvider(long_answer),
        bot_id="BOT-VIS-01",
        run_id="r",
        traces=TraceWriter(tmp_path),
        max_calls=1,
    )
    request = VisionRequest(
        chart=render_chart_png(bars(40), symbol="BTC/USDT"),
        prompt=build_prompt(
            {
                "symbol": "BTC/USDT",
                "timeframe": "1h",
                "window_bars": 40,
                "last_close": 100.0,
                "equity": 10_000.0,
                "open_positions": 0,
                "max_open_positions": 3,
                "risk_per_trade_pct": 0.25,
                "max_weekly_loss_pct": 3.0,
                "position": None,
            }
        ),
        decision_ts_ms=START_MS,
    )
    traced.analyze(request)
    with pytest.raises(BudgetExceeded):
        traced.analyze(request)
    with pytest.raises(BudgetExceeded):
        traced.analyze(request)
    rows = (
        (tmp_path / "MODEL_INVOCATIONS.jsonl").read_text(encoding="utf-8").splitlines()
    )
    assert len(rows) == 2, "one paid call plus one single refusal receipt"
    assert json.loads(rows[1])["model_status"] == "CALL_BUDGET_EXCEEDED"


def test_a_text_only_response_never_claims_an_image():
    """A trace must be able to tell 'no image' from 'the image matched'."""
    response = VisionResponse(
        text="{}",
        model="m",
        provider="openai-compatible-text",
        request_id="r",
        latency_ms=1,
        attempts=1,
        image_sha256_in_request="",
    )
    assert response.image_sha256_in_request == ""
    assert bool(response.image_sha256_in_request) is False
