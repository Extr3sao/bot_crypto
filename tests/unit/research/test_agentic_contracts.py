"""CAP-001 — unit tests for the agentic market intelligence contracts.

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from trading_bot.research import agentic_contracts as ac

REPO = Path(__file__).resolve().parents[3]
HAS_ARTIFACTS = (REPO / "reports" / "CAP001_FINAL_REPORT.json").is_file()


def _snapshot(**overrides: Any) -> ac.MarketSnapshot:
    base: dict[str, Any] = {
        "timestamp": 1767225600,
        "asset": "BINANCE:BTCUSDT",
        "price_state": ac.PriceState(
            symbol="BINANCE:BTCUSDT", last=64000.0, change_pct=1.5, bar_interval="4h", bar_count=18
        ),
        "multi_timeframe": (
            ac.TimeframeState(interval="1h", last=64000.0, change_pct=0.2, trend="up"),
            ac.TimeframeState(interval="4h", last=64000.0, change_pct=0.9, trend="up"),
            ac.TimeframeState(interval="1D", last=64000.0, change_pct=2.4, trend="up"),
        ),
        "technical_state": ac.TechnicalState(
            rsi=61.0, macd=410.0, adx=28.0, momentum=3.0, sma50=61000.0, ema200=55000.0, recommendation="BUY"
        ),
        "relative_strength": ac.RelativeStrength(symbol="BINANCE:BTCUSDT", reference="SP:SPX", value=1.8),
        "volume_state": ac.VolumeState(last=1200.0, relative=1.2),
        "market_regime": "trend_up_low_volatility",
        "news": (ac.NewsItem(title="synthetic", published=1767223000, provider="x", urgency=1),),
        "macro_events": (ac.MacroEvent(name="US CPI", country="US", when=1767225600, importance=1),),
        "evidence": (
            ac.Evidence(kind="technical", source="tradingview_mcp.get_technicals_rating", detail="RSI=61", value=61.0),
        ),
        "data_freshness": ac.DataFreshness(
            snapshot_at=1767225600,
            newest_source_at=1767222000,
            oldest_source_at=1767222000,
            age_seconds=3600,
            level="FRESH",
            degraded=False,
        ),
    }
    base.update(overrides)
    return ac.MarketSnapshot(**base)


# --------------------------------------------------------------------------- #
# governance surface
# --------------------------------------------------------------------------- #


def test_governance_constants_are_intact() -> None:
    assert ac.SPIKE_ID == "CAP-001"
    assert ac.GOVERNANCE_FRAMING == "CAPABILITY_SPIKE_OUTSIDE_ALPHA_FREEZE"
    assert ac.ALPHA_RESEARCH_FREEZE == "ACTIVE"
    assert ac.NEXT_ALPHA_RFC_ALLOWED == "NO"
    assert ac.ALPHA_CLAIMED == "NONE"
    assert ac.TRADES_AUTHORIZED == 0
    assert ac.RFC_CREATED == "NONE"


def test_snapshot_contract_declares_twelve_fields() -> None:
    assert len(ac.MARKET_SNAPSHOT_FIELDS) == 12
    assert set(ac.MARKET_SNAPSHOT_FIELDS) == {f.name for f in dataclasses.fields(ac.MarketSnapshot)}


def test_authority_map_never_promotes_tradingview() -> None:
    assert ac.AUTHORITY_MAP["tradingview"] == "INTELLIGENCE_SOURCE"
    assert ac.AUTHORITY_MAP["pnl"] == "PORTFOLIO_ACCOUNTING"
    assert ac.TRADINGVIEW_IS_ACCOUNTING_SOURCE_OF_TRUTH is False


def test_determinism_split_is_disjoint() -> None:
    assert set(ac.NON_DETERMINISTIC_DOMAINS).isdisjoint(ac.DETERMINISTIC_DOMAINS)
    assert "position_sizing" in ac.DETERMINISTIC_DOMAINS
    assert "confidence" in ac.NON_DETERMINISTIC_DOMAINS
    assert ac.LLM_SIZING_FORBIDDEN is True
    assert ac.LLM_LEVERAGE_FORBIDDEN is True


def test_kpis_and_budget_are_frozen_at_zero_and_two() -> None:
    assert all(value == 0 for value in ac.KPI_VALUES.values())
    assert ac.BUDGET_BEFORE_G3["MAX_AI_AGENTS"] == 2
    assert ac.BUDGET_BEFORE_G3["MAX_TRADINGVIEW_CONNECTORS"] == 1
    assert ac.G_TV_CONTEXT == "NOT_VERIFIED"


# --------------------------------------------------------------------------- #
# freshness + snapshot validation
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("age", "expected"),
    [(-1, "UNKNOWN"), (0, "FRESH"), (3600, "FRESH"), (3601, "AGING"), (86400, "AGING"), (86401, "STALE")],
)
def test_freshness_class_boundaries(age: int, expected: str) -> None:
    assert ac.freshness_class(age) == expected


def test_valid_snapshot_has_no_problems() -> None:
    assert ac.validate_snapshot(_snapshot()) == []
    assert ac.snapshot_is_usable(_snapshot()) is True


def test_snapshot_missing_multi_timeframe_is_rejected() -> None:
    problems = ac.validate_snapshot(_snapshot(multi_timeframe=()))
    assert any("multi_timeframe" in problem for problem in problems)


def test_snapshot_repeated_interval_is_rejected() -> None:
    repeated = (
        ac.TimeframeState(interval="4h", last=1.0, change_pct=0.0, trend="up"),
        ac.TimeframeState(interval="4h", last=1.0, change_pct=0.0, trend="up"),
    )
    problems = ac.validate_snapshot(_snapshot(multi_timeframe=repeated))
    assert any("repeat" in problem for problem in problems)


def test_snapshot_forbidden_timeframe_is_rejected() -> None:
    fast = (ac.TimeframeState(interval="5m", last=1.0, change_pct=0.0, trend="range"),)
    problems = ac.validate_snapshot(_snapshot(multi_timeframe=fast))
    assert any("5m" in problem for problem in problems)


def test_snapshot_unknown_evidence_kind_is_rejected() -> None:
    bad = (ac.Evidence(kind="vibes", source="tradingview_mcp.get_ohlcv", detail="x"),)
    problems = ac.validate_snapshot(_snapshot(evidence=bad))
    assert any("vibes" in problem for problem in problems)


def test_snapshot_bad_macro_importance_is_rejected() -> None:
    bad = (ac.MacroEvent(name="US CPI", country="US", when=1, importance=5),)
    problems = ac.validate_snapshot(_snapshot(macro_events=bad))
    assert any("importance" in problem for problem in problems)


def test_stale_snapshot_is_not_usable() -> None:
    stale = ac.DataFreshness(
        snapshot_at=1767225600,
        newest_source_at=1767000000,
        oldest_source_at=1767000000,
        age_seconds=225600,
        level="STALE",
        degraded=True,
    )
    assert ac.validate_snapshot(_snapshot(data_freshness=stale)) == []
    assert ac.snapshot_is_usable(_snapshot(data_freshness=stale)) is False


def test_snapshot_payload_round_trips() -> None:
    payload = ac.snapshot_payload(_snapshot())
    assert set(payload) == set(ac.MARKET_SNAPSHOT_FIELDS)
    # Canonicalization must survive the tuple -> JSON array boundary.
    assert ac.payload_digest(payload) == ac.payload_digest(json.loads(json.dumps(payload)))


# --------------------------------------------------------------------------- #
# hypothesis
# --------------------------------------------------------------------------- #


def test_no_trade_hypothesis_requires_a_reason() -> None:
    hypothesis = ac.MarketHypothesis(
        asset="BINANCE:BTCUSDT",
        horizon="1-3d",
        direction="NO_TRADE",
        thesis="range",
        catalysts=(),
        evidence=(),
        counter_evidence=(),
        invalidation="",
        confidence=0.34,
        expected_holding_period="n/a",
        no_trade_reason="",
    )
    assert any("no_trade_reason" in problem for problem in ac.validate_hypothesis(hypothesis))
    assert ac.validate_hypothesis(dataclasses.replace(hypothesis, no_trade_reason="no edge")) == []


def test_directional_hypothesis_requires_invalidation_and_evidence() -> None:
    hypothesis = ac.MarketHypothesis(
        asset="BINANCE:BTCUSDT",
        horizon="1-3d",
        direction="LONG",
        thesis="breakout",
        catalysts=("etf inflows",),
        evidence=(),
        counter_evidence=(),
        invalidation="",
        confidence=0.71,
        expected_holding_period="1-3d",
    )
    problems = ac.validate_hypothesis(hypothesis)
    assert any("invalidation" in problem for problem in problems)
    assert any("evidence" in problem for problem in problems)


def test_confidence_out_of_range_is_rejected() -> None:
    hypothesis = ac.MarketHypothesis(
        asset="BINANCE:BTCUSDT",
        horizon="1d",
        direction="NO_TRADE",
        thesis="x",
        catalysts=(),
        evidence=(),
        counter_evidence=(),
        invalidation="",
        confidence=1.4,
        expected_holding_period="n/a",
        no_trade_reason="range",
    )
    assert any("confidence" in problem for problem in ac.validate_hypothesis(hypothesis))


def test_unknown_direction_is_rejected() -> None:
    hypothesis = ac.MarketHypothesis(
        asset="X",
        horizon="1d",
        direction="MAYBE",
        thesis="",
        catalysts=(),
        evidence=(),
        counter_evidence=(),
        invalidation="",
        confidence=0.5,
        expected_holding_period="",
    )
    assert any("direction" in problem for problem in ac.validate_hypothesis(hypothesis))


# --------------------------------------------------------------------------- #
# proposal — the LLM never sizes
# --------------------------------------------------------------------------- #


def test_forbidden_proposal_keys_are_detected_recursively() -> None:
    payload = {"asset": "X", "legs": [{"size": 3}], "notes": {"leverage": 8}}
    assert ac.forbidden_proposal_keys(payload) == ["leverage", "size"]
    assert ac.proposal_payload_is_safe(payload) is False
    assert ac.proposal_payload_is_safe({"asset": "X"}) is True


def _proposal(**overrides: Any) -> ac.TradeProposal:
    base: dict[str, Any] = {
        "asset": "BINANCE:BTCUSDT",
        "direction": "LONG",
        "horizon": "1-3d",
        "claim": "range breakout with volume confirmation",
        "evidence": ("3 timeframes aligned",),
        "counter_evidence": ("overextended RSI",),
        "invalidation": "daily close below 62000",
        "confidence": 0.62,
        "expected_reward_zone": ac.ExpectedZone(low=66000.0, high=68000.0),
        "expected_risk_zone": ac.ExpectedZone(low=62000.0, high=63000.0),
        "decision_time": 1767225600,
    }
    base.update(overrides)
    return ac.TradeProposal(**base)


def test_valid_proposal_has_no_problems() -> None:
    assert ac.validate_proposal(_proposal()) == []


def test_proposal_cannot_be_no_trade() -> None:
    assert any("NO_TRADE" in problem for problem in ac.validate_proposal(_proposal(direction="NO_TRADE")))


def test_proposal_requires_invalidation() -> None:
    assert any("invalidation" in problem for problem in ac.validate_proposal(_proposal(invalidation="")))


def test_proposal_zone_order_is_checked() -> None:
    inverted = ac.ExpectedZone(low=10.0, high=1.0)
    problems = ac.validate_proposal(_proposal(expected_reward_zone=inverted))
    assert any("reward_zone" in problem for problem in problems)


def test_free_text_claim_is_not_treated_as_sizing() -> None:
    # The narrative claim is free text; only structured sizing fields are forbidden.
    assert ac.validate_proposal(_proposal(claim="buy 8x leverage")) == []
    payload = _proposal().to_dict()
    payload["size"] = 1.0
    assert ac.proposal_payload_is_safe(payload) is False


def test_sizing_fields_are_declared_forbidden() -> None:
    assert "size" in ac.FORBIDDEN_PROPOSAL_FIELDS
    assert "leverage" in ac.FORBIDDEN_PROPOSAL_FIELDS


# --------------------------------------------------------------------------- #
# sealed decision records
# --------------------------------------------------------------------------- #


def _seal(decision: str = "NO_TRADE") -> ac.DecisionRecord:
    return ac.seal_decision_record(
        timestamp=1767225600,
        prompt_version="MARKET_ANALYST_V1",
        evidence_snapshot_hash=ac.payload_digest({"a": 1}),
        agent_output={"direction": decision},
        critic_output={"stance": "uncertainty"},
        decision=decision,
    )


def test_sealed_record_verifies() -> None:
    record = _seal()
    assert record.is_verified() is True
    assert len(record.decision_hash) == 64


def test_sealing_is_deterministic() -> None:
    assert _seal().decision_hash == _seal().decision_hash


def test_sealing_rejects_an_unknown_decision() -> None:
    with pytest.raises(ValueError, match="decision must be one of"):
        _seal("MAYBE")


def test_sealing_requires_a_prompt_version_and_evidence_hash() -> None:
    with pytest.raises(ValueError, match="prompt_version"):
        ac.seal_decision_record(
            timestamp=1,
            prompt_version=" ",
            evidence_snapshot_hash="h",
            agent_output={},
            critic_output=None,
            decision="NO_TRADE",
        )
    with pytest.raises(ValueError, match="evidence_snapshot_hash"):
        ac.seal_decision_record(
            timestamp=1,
            prompt_version="v1",
            evidence_snapshot_hash="",
            agent_output={},
            critic_output=None,
            decision="NO_TRADE",
        )


def test_hindsight_editing_is_detected() -> None:
    record = _seal()
    edited = dataclasses.replace(record, decision="LONG")
    assert edited.decision_hash == record.decision_hash
    assert edited.is_verified() is False
    assert ac.detect_tampering([edited, record]) == [0]


def test_ledger_rejects_unsealed_and_duplicate_records() -> None:
    ledger = ac.DecisionLedger()
    record = _seal()
    ledger.append(record)
    assert ledger.hashes() == (record.decision_hash,)
    with pytest.raises(ValueError, match="duplicate"):
        ledger.append(record)
    with pytest.raises(ValueError, match="unsealed or tampered"):
        ledger.append(dataclasses.replace(record, decision="LONG", decision_hash="0" * 64))


def test_ledger_digest_changes_with_content() -> None:
    ledger = ac.DecisionLedger()
    ledger.append(_seal())
    before = ledger.digest()
    ledger.append(_seal("LONG"))
    assert ledger.digest() != before


# --------------------------------------------------------------------------- #
# evaluator primitives
# --------------------------------------------------------------------------- #


def test_incremental_edge_subtracts_baseline_and_cost() -> None:
    edge = ac.incremental_edge(
        agent_outcome=120.0, baseline_outcome=90.0, cost=5.0, baseline="B_BUY_AND_HOLD"
    )
    assert edge.edge == pytest.approx(25.0)
    assert edge.positive is True
    assert ac.incremental_edge(
        agent_outcome=1.0, baseline_outcome=1.0, cost=0.5, baseline="A_NO_TRADE"
    ).positive is False


def test_incremental_edge_guards_its_inputs() -> None:
    with pytest.raises(ValueError, match="baseline must be one of"):
        ac.incremental_edge(agent_outcome=1.0, baseline_outcome=1.0, cost=0.0, baseline="E_RANDOM")
    with pytest.raises(ValueError, match="cost must not be negative"):
        ac.incremental_edge(agent_outcome=1.0, baseline_outcome=1.0, cost=-1.0, baseline="A_NO_TRADE")


def test_hit_rate_and_expectancy() -> None:
    returns = [1.0, -0.5, 2.0, -1.0]
    assert ac.hit_rate(returns) == pytest.approx(0.5)
    assert ac.expectancy(returns) == pytest.approx(0.375)
    with pytest.raises(ValueError):
        ac.hit_rate([])


def test_profit_factor_is_none_without_losses() -> None:
    assert ac.profit_factor([1.0, 2.0]) is None
    assert ac.profit_factor([3.0, -1.0]) == pytest.approx(3.0)


def test_max_drawdown_is_a_positive_fraction() -> None:
    assert ac.max_drawdown([100.0, 120.0, 90.0, 130.0]) == pytest.approx(0.25)
    assert ac.max_drawdown([100.0, 110.0]) == pytest.approx(0.0)
    with pytest.raises(ValueError):
        ac.max_drawdown([])


def test_brier_score_rewards_calibration() -> None:
    assert ac.brier_score([(1.0, True), (0.0, False)]) == pytest.approx(0.0)
    assert ac.brier_score([(0.5, True)]) == pytest.approx(0.25)
    with pytest.raises(ValueError):
        ac.brier_score([])


def test_baselines_are_the_four_declared_ones() -> None:
    assert ac.BASELINES == ("A_NO_TRADE", "B_BUY_AND_HOLD", "C_SIMPLE_TREND", "D_PASSIVE_PORTFOLIO")


# --------------------------------------------------------------------------- #
# written artifacts
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(not HAS_ARTIFACTS, reason="CAP-001 artifacts not generated yet")
def test_final_report_header_and_gate_are_honest() -> None:
    report = json.loads((REPO / "reports" / "CAP001_FINAL_REPORT.json").read_text(encoding="utf-8"))
    md = (REPO / "reports" / "CAP001_FINAL_REPORT.md").read_text(encoding="utf-8").splitlines()
    assert md[0] == "CAP-001 AGENTIC MARKET INTELLIGENCE CAPABILITY SPIKE"
    assert report["g_tv_context"] == "NOT_VERIFIED"
    assert report["rfc_created"] == "NONE"
    assert report["alpha_claimed"] == "NONE"
    assert report["llm_invoked"] is False
    assert report["snapshot_source"] == "SYNTHETIC_FIXTURE"


@pytest.mark.skipif(not HAS_ARTIFACTS, reason="CAP-001 artifacts not generated yet")
def test_verification_artifact_passed() -> None:
    verification = json.loads(
        (REPO / "reports" / "agentic-spike-cap001" / "CAP001_VERIFICATION.json").read_text(encoding="utf-8")
    )
    assert verification["status"] == "PASS"
    assert verification["mismatches"] == 0
    assert verification["false_success"] == 0
    assert verification["passed"] == verification["total"]


@pytest.mark.skipif(not HAS_ARTIFACTS, reason="CAP-001 artifacts not generated yet")
def test_artifacts_never_present_synthetic_data_as_live() -> None:
    snapshot = json.loads(
        (REPO / "reports" / "agentic-spike-cap001" / "CAP001_MARKET_SNAPSHOT.json").read_text(encoding="utf-8")
    )
    assert snapshot["_synthetic"] is True
    assert snapshot["_source"] == "SYNTHETIC_FIXTURE"
    assert snapshot["_validation_problems"] == []
