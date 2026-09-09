"""Track E tests — Strategy Lab intake contract (RS-01..03)."""

from __future__ import annotations

import pytest

from trading_bot.research.lab_intake import (
    EXISTING_FAMILIES,
    RESEARCH_CATEGORIES,
    ExternalStrategyIdea,
    IntakeDecision,
    StrategyLabIntake,
)


def _idea(**overrides: object) -> ExternalStrategyIdea:
    base: dict[str, object] = {
        "idea_id": "idea-001",
        "source": "paper:10.1000/example",
        "title": "Funding-carry delta-neutral drift",
        "hypothesis": (
            "May perform during FUSED_CORRELATION and RANGE because "
            "funding-rate carry is orthogonal to directional momentum."
        ),
        "research_category": "carry_funding",
        "target_regimes": ("FUSED_CORRELATION", "RANGE"),
        "proposed_assets": ("BTC", "ETH"),
        "proposed_timeframes": ("1h",),
        "orthogonal_to": ("momentum",),
        "complement_of": (),
    }
    base.update(overrides)
    return ExternalStrategyIdea(**base)  # type: ignore[arg-type]


def _spec() -> dict[str, object]:
    return {
        "entry_rule": "funding z-score > 2 while basis positive",
        "exit_rule": "funding z-score < 0.5 or 72h hold",
        "stop_rule": "notional loss > 1.5R",
        "sizing_rule": "vol-targeted 0.5% equity risk",
    }


class TestIntakeContract:
    def test_accepts_orthogonal_regime_first_idea(self) -> None:
        lab = StrategyLabIntake()
        decision, candidate = lab.submit(_idea(), _spec(), admitted_at_utc="2026-09-09T00:00:00Z")
        assert decision is IntakeDecision.ACCEPTED_TO_LAB
        assert candidate is not None
        assert candidate.status == "ACCEPTED_TO_LAB"
        assert candidate.spec_fingerprint

    def test_spec_fingerprint_is_deterministic(self) -> None:
        lab = StrategyLabIntake()
        _, c1 = lab.submit(_idea(), _spec(), admitted_at_utc="2026-09-09T00:00:00Z")
        lab2 = StrategyLabIntake()
        _, c2 = lab2.submit(_idea(), _spec(), admitted_at_utc="2026-09-10T00:00:00Z")
        assert c1 is not None and c2 is not None
        assert c1.spec_fingerprint == c2.spec_fingerprint

    def test_duplicate_of_existing_family_rejected(self) -> None:
        lab = StrategyLabIntake()
        # A copy of an existing family has nothing truthful to declare as
        # orthogonal/complementary, so it cannot pass the intake gate.
        idea = _idea(
            hypothesis="Another SOL LONG momentum copy.",
            research_category="relative_strength",
            target_regimes=("ANY",),
            orthogonal_to=(),
            complement_of=(),
        )
        decision, candidate = lab.submit(idea, _spec(), admitted_at_utc="2026-09-09T00:00:00Z")
        assert decision is IntakeDecision.REJECTED_DUPLICATE
        assert candidate is None

    def test_no_orthogonality_declaration_rejected(self) -> None:
        lab = StrategyLabIntake()
        idea = _idea(orthogonal_to=(), complement_of=())
        decision, _ = lab.submit(idea, _spec(), admitted_at_utc="2026-09-09T00:00:00Z")
        assert decision is IntakeDecision.REJECTED_DUPLICATE

    def test_missing_regime_hypothesis_rejected(self) -> None:
        lab = StrategyLabIntake()
        idea = _idea(target_regimes=())
        decision, _ = lab.submit(idea, _spec(), admitted_at_utc="2026-09-09T00:00:00Z")
        assert decision is IntakeDecision.REJECTED_NO_REGIME_HYPOTHESIS

    def test_incomplete_spec_fail_closed(self) -> None:
        lab = StrategyLabIntake()
        decision, _ = lab.submit(_idea(), {"entry_rule": "x"}, admitted_at_utc="2026-09-09T00:00:00Z")
        assert decision is IntakeDecision.REJECTED_INCOMPLETE_SPEC

    def test_unknown_category_or_regime_fail_closed(self) -> None:
        with pytest.raises(ValueError, match="research_category"):
            _idea(research_category="astrology")
        with pytest.raises(ValueError, match="target regimes"):
            _idea(target_regimes=("MOON",))

    def test_categories_cover_declared_research_space(self) -> None:
        # RS-02: the declared research categories span the checkpoint's
        # orthogonal behavior space (never more SOL-LONG momentum copies).
        for expected in (
            "carry_funding",
            "relative_strength",
            "cross_sectional",
            "liquidity_flow",
            "volatility_structure",
            "session_time",
            "multi_timeframe_context",
        ):
            assert expected in RESEARCH_CATEGORIES
        assert EXISTING_FAMILIES == (
            "momentum",
            "trend",
            "breakout",
            "mean_reversion",
            "volatility",
        )
