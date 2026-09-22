from __future__ import annotations

from trading_bot.research.regime_eligibility import (
    FALLBACK_CHAIN,
    EligibilityMetrics,
    EligibilityStatus,
    EligibilityThresholds,
    SignatureLevel,
    evaluate_regime_eligibility,
    regime_signature,
)
from trading_bot.research.regime_v2 import (
    CorrelationRegime,
    MarketRegimeState,
    MarketStructure,
    StressLevel,
    TrendDirection,
    TrendStrength,
    VolatilityLevel,
)


def _regime(**overrides: object) -> MarketRegimeState:
    kwargs: dict[str, object] = {
        "bar_ts": 1,
        "trend_direction": TrendDirection.BULL,
        "trend_strength": TrendStrength.STRONG,
        "volatility": VolatilityLevel.NORMAL,
        "market_structure": MarketStructure.TREND,
        "stress": StressLevel.NORMAL,
        "correlation_regime": CorrelationRegime.NORMAL,
    }
    kwargs.update(overrides)
    return MarketRegimeState(**kwargs)  # type: ignore[arg-type]


def _metrics(**overrides: object) -> EligibilityMetrics:
    kwargs: dict[str, object] = {
        "n": 40,
        "expectancy": 0.4,
        "profit_factor": 1.5,
        "sharpe": 1.1,
        "drawdown": 0.08,
        "cost_adjusted_expectancy": 0.3,
        "health_state": "MONITORING",
        "admission_evidence": True,
    }
    kwargs.update(overrides)
    return EligibilityMetrics(**kwargs)  # type: ignore[arg-type]


def test_exact_regime_eligible() -> None:
    regime = _regime()
    result = evaluate_regime_eligibility(
        strategy_id="momentum",
        version="v1",
        asset="SOL",
        timeframe="5m",
        regime=regime,
        metrics_by_level={SignatureLevel.EXACT: _metrics()},
    )
    assert result.status is EligibilityStatus.ELIGIBLE
    assert result.signature_level is SignatureLevel.EXACT
    assert result.regime_signature == regime.key()


def test_predeclared_fallback_on_insufficient_exact_sample() -> None:
    regime = _regime()
    result = evaluate_regime_eligibility(
        strategy_id="momentum",
        version="v1",
        asset="SOL",
        timeframe="5m",
        regime=regime,
        metrics_by_level={
            SignatureLevel.EXACT: _metrics(n=5),  # insufficient at exact
            SignatureLevel.STRUCTURE: _metrics(n=35),
        },
    )
    assert result.signature_level is SignatureLevel.STRUCTURE
    assert result.status is EligibilityStatus.ELIGIBLE
    assert result.regime_signature.startswith("S:")
    assert "STRUCTURE" in result.basis


def test_fallback_chain_is_predeclared_and_fixed() -> None:
    assert FALLBACK_CHAIN == (
        SignatureLevel.EXACT,
        SignatureLevel.STRUCTURE,
        SignatureLevel.DIRECTION,
        SignatureLevel.GLOBAL,
    )


def test_full_fallback_chain_to_global() -> None:
    regime = _regime()
    result = evaluate_regime_eligibility(
        strategy_id="momentum",
        version="v1",
        asset="SOL",
        timeframe="5m",
        regime=regime,
        metrics_by_level={
            SignatureLevel.EXACT: _metrics(n=2),
            SignatureLevel.STRUCTURE: _metrics(n=3),
            SignatureLevel.DIRECTION: _metrics(n=4),
            SignatureLevel.GLOBAL: _metrics(n=50),
        },
    )
    assert result.signature_level is SignatureLevel.GLOBAL
    assert result.regime_signature == "GLOBAL"
    assert result.status is EligibilityStatus.ELIGIBLE


def test_no_data_anywhere_fails_closed() -> None:
    regime = _regime()
    result = evaluate_regime_eligibility(
        strategy_id="momentum",
        version="v1",
        asset="SOL",
        timeframe="5m",
        regime=regime,
        metrics_by_level={},
    )
    assert result.status is EligibilityStatus.INSUFFICIENT_EVIDENCE
    assert result.metrics.n == 0


def test_insufficient_sample_never_eligible() -> None:
    result = evaluate_regime_eligibility(
        strategy_id="m",
        version="v1",
        asset="SOL",
        timeframe="5m",
        regime=_regime(),
        metrics_by_level={SignatureLevel.EXACT: _metrics(n=9)},
    )
    assert result.status is EligibilityStatus.INSUFFICIENT_EVIDENCE


def test_shadow_only_without_admission_evidence() -> None:
    result = evaluate_regime_eligibility(
        strategy_id="m",
        version="v1",
        asset="SOL",
        timeframe="5m",
        regime=_regime(),
        metrics_by_level={SignatureLevel.EXACT: _metrics(admission_evidence=False)},
    )
    assert result.status is EligibilityStatus.SHADOW_ONLY
    assert "no admission evidence" in result.basis


def test_quarantined_health_overrides_good_metrics() -> None:
    result = evaluate_regime_eligibility(
        strategy_id="m",
        version="v1",
        asset="SOL",
        timeframe="5m",
        regime=_regime(),
        metrics_by_level={SignatureLevel.EXACT: _metrics(health_state="QUARANTINED")},
    )
    assert result.status is EligibilityStatus.NOT_ELIGIBLE
    assert "health_state" in result.basis


def test_not_eligible_when_metrics_fail() -> None:
    result = evaluate_regime_eligibility(
        strategy_id="m",
        version="v1",
        asset="SOL",
        timeframe="5m",
        regime=_regime(),
        metrics_by_level={SignatureLevel.EXACT: _metrics(expectancy=-0.5, profit_factor=0.6)},
    )
    assert result.status is EligibilityStatus.NOT_ELIGIBLE


def test_signature_levels_deterministic_and_distinct() -> None:
    regime = _regime()
    exact = regime_signature(regime, SignatureLevel.EXACT)
    structure = regime_signature(regime, SignatureLevel.STRUCTURE)
    direction = regime_signature(regime, SignatureLevel.DIRECTION)
    assert exact == regime.key()
    assert structure.startswith("S:")
    assert direction.startswith("D:")
    assert len({exact, structure, direction}) == 3
    # Same state twice -> identical signature (deterministic).
    assert regime_signature(regime, SignatureLevel.STRUCTURE) == structure


def test_no_opportunistic_merging_same_chain_different_data() -> None:
    # Two different strategies with different data availability must resolve
    # through the SAME fixed chain; results depend only on (chain, data).
    regime = _regime()
    a = evaluate_regime_eligibility(
        strategy_id="a",
        version="v1",
        asset="SOL",
        timeframe="5m",
        regime=regime,
        metrics_by_level={SignatureLevel.EXACT: _metrics(n=35)},
    )
    b = evaluate_regime_eligibility(
        strategy_id="b",
        version="v1",
        asset="SOL",
        timeframe="5m",
        regime=regime,
        metrics_by_level={
            SignatureLevel.EXACT: _metrics(n=5),
            SignatureLevel.STRUCTURE: _metrics(n=35),
        },
    )
    assert a.signature_level is SignatureLevel.EXACT
    assert b.signature_level is SignatureLevel.STRUCTURE
    # Both used the same chain order; b's fallback was declared, not opportunistic.
    assert b.basis.startswith("level=STRUCTURE")


def test_custom_thresholds() -> None:
    thresholds = EligibilityThresholds(min_eligible_n=5, min_shadow_n=2)
    result = evaluate_regime_eligibility(
        strategy_id="m",
        version="v1",
        asset="SOL",
        timeframe="5m",
        regime=_regime(),
        metrics_by_level={SignatureLevel.EXACT: _metrics(n=6)},
        thresholds=thresholds,
    )
    assert result.status is EligibilityStatus.ELIGIBLE
