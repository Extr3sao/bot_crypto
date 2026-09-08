"""Track F tests: HEALTH x RISK observational analysis contract."""

from __future__ import annotations

import pytest

from trading_bot.risk.reject_analysis import (
    RejectClassification,
    RiskRejectLedger,
    ShadowOutcome,
)


def _ledger_with_reject() -> tuple[RiskRejectLedger, int]:
    ledger = RiskRejectLedger()
    ledger.record_reject(
        strategy_id="Momentum",
        asset="SOL/USDT",
        timeframe="5m",
        regime="TREND_BULL",
        health_state="HEALTHY",
        correlation_state="NORMAL",
        risk_reason="Max open positions reached (5)",
        blocked_by="max_positions",
        signal_summary={"side": "buy", "confidence": 0.8},
        recorded_at="2026-09-08T00:00:00Z",
    )
    return ledger, 0


class TestRecording:
    def test_record_captures_full_context(self) -> None:
        ledger, idx = _ledger_with_reject()
        rec = ledger.records()[idx]
        assert rec.strategy_id == "Momentum"
        assert rec.health_state == "HEALTHY"
        assert rec.correlation_state == "NORMAL"
        assert rec.risk_reason.startswith("Max open positions")
        assert rec.blocked_by == "max_positions"

    def test_unclassified_without_shadow(self) -> None:
        ledger, _ = _ledger_with_reject()
        assert ledger.classification_counts()[RejectClassification.UNCLASSIFIED.value] == 1

    def test_read_only_export(self) -> None:
        ledger, _ = _ledger_with_reject()
        dicts = ledger.to_dicts()
        assert dicts[0]["read_only"] is True
        assert dicts[0]["classification"] == RejectClassification.UNCLASSIFIED.value
        assert dicts[0]["shadow"] is None


class TestClassification:
    def test_good_candidate_blocked_by_risk(self) -> None:
        ledger, idx = _ledger_with_reject()
        updated = ledger.attach_shadow(idx, ShadowOutcome(expectancy=0.05, profit_factor=1.6, sample_size=40))
        assert ledger.classify_index(idx) is RejectClassification.GOOD_CANDIDATE_BLOCKED_BY_RISK
        assert updated.shadow is not None

    def test_low_quality_correctly_blocked(self) -> None:
        ledger, idx = _ledger_with_reject()
        ledger.attach_shadow(idx, ShadowOutcome(expectancy=-0.02, profit_factor=0.7, sample_size=40))
        assert ledger.classify_index(idx) is RejectClassification.LOW_QUALITY_CANDIDATE_CORRECTLY_BLOCKED

    def test_small_shadow_sample_stays_unclassified(self) -> None:
        ledger, idx = _ledger_with_reject()
        ledger.attach_shadow(idx, ShadowOutcome(expectancy=0.5, profit_factor=3.0, sample_size=5))
        assert ledger.classify_index(idx) is RejectClassification.UNCLASSIFIED

    def test_breakeven_shadow_is_correctly_blocked(self) -> None:
        ledger, idx = _ledger_with_reject()
        ledger.attach_shadow(idx, ShadowOutcome(expectancy=0.0, profit_factor=1.0, sample_size=30))
        assert ledger.classify_index(idx) is RejectClassification.LOW_QUALITY_CANDIDATE_CORRECTLY_BLOCKED


class TestGuards:
    def test_shadow_requires_positive_sample(self) -> None:
        with pytest.raises(ValueError):
            ShadowOutcome(expectancy=0.1, profit_factor=1.5, sample_size=0)

    def test_counts_tally_all_records(self) -> None:
        ledger, _ = _ledger_with_reject()
        ledger.record_reject(
            strategy_id="Trend",
            asset="BTC/USDT",
            timeframe="1h",
            regime="RANGE",
            health_state="DEGRADED",
            correlation_state="FUSED",
            risk_reason="consecutive loss cooldown",
            blocked_by="consecutive_loss_cooldown",
        )
        counts = ledger.classification_counts()
        assert sum(counts.values()) == 2
