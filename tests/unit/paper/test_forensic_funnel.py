"""Tests: POC01 forensic funnel (Track A2)."""

from __future__ import annotations

from trading_bot.paper.forensic_funnel import (
    FunnelGates,
    attribute_losses,
    build_funnel,
)


class TestFunnelConversions:
    def test_zero_signal_day_records_honest_gaps(self) -> None:
        activity = {
            "market_scans": 1,
            "trade_proposals": 0,
            "debates": 0,
            "selected_decisions": 0,
            "no_trade": 1,
            "risk_accepts": 0,
            "risk_rejects": 0,
            "executed_paper_trades": 0,
        }
        conv = {c.gate: c for c in build_funnel(activity)}
        assert conv[FunnelGates.MARKET_SCAN].count == 1
        # SIGNAL not persisted by runtime -> NOT_RECORDED (count -1, rate -1)
        assert conv[FunnelGates.SIGNAL].count == -1
        assert conv[FunnelGates.SIGNAL].rate == -1.0
        assert conv[FunnelGates.PROPOSAL].count == 0
        assert conv[FunnelGates.PROPOSAL].rate == 0.0

    def test_full_funnel_rates(self) -> None:
        activity = {
            "market_scans": 100,
            "signals": 40,
            "trade_proposals": 20,
            "debates": 20,
            "selected_decisions": 10,
            "verified": 9,
            "risk_accepts": 6,
            "risk_rejects": 3,
            "executed_paper_trades": 6,
        }
        conv = {c.gate: c for c in build_funnel(activity)}
        assert conv[FunnelGates.SIGNAL].rate == 0.40
        assert conv[FunnelGates.PROPOSAL].rate == 0.50
        assert conv[FunnelGates.SELECTED].rate == 0.50
        assert conv[FunnelGates.VERIFIED].rate == 0.90
        assert conv[FunnelGates.RISK].rate == 1.0  # 9 verified -> 9 risk decisions
        # 6 of the 9 risk decisions accepted became paper trades.
        assert conv[FunnelGates.PAPER].rate == 6 / 9


class TestLossAttribution:
    def test_no_signal_bucket(self) -> None:
        attr = attribute_losses({"market_scans": 24, "trade_proposals": 0})
        assert attr.bottleneck_gate == FunnelGates.PROPOSAL
        assert attr.primary_loss_bucket == "NO_SIGNAL"
        assert "per-strategy signal counts not persisted" in attr.notes[0]

    def test_agent_decision_bucket(self) -> None:
        attr = attribute_losses(
            {
                "market_scans": 24,
                "trade_proposals": 5,
                "selected_decisions": 0,
                "risk_rejects": 0,
            }
        )
        assert attr.bottleneck_gate == FunnelGates.SELECTED
        assert attr.primary_loss_bucket == "AGENT_DECISION"

    def test_risk_reason_buckets(self) -> None:
        attr = attribute_losses(
            {
                "market_scans": 24,
                "trade_proposals": 5,
                "selected_decisions": 5,
                "risk_accepts": 0,
                "risk_rejects": 5,
            },
            risk_rejects_by_reason={
                "MAX_POSITIONS": 3,
                "CONSECUTIVE_LOSS_COOLDOWN": 2,
            },
        )
        assert attr.bottleneck_gate == FunnelGates.RISK
        assert attr.by_risk_reason == {
            "MAX_POSITIONS": 3,
            "CONSECUTIVE_LOSS_COOLDOWN": 2,
        }
        assert attr.buckets["RISK_MAX_POSITIONS"] == 3
        assert attr.primary_loss_bucket.startswith("RISK_")

    def test_no_paper_fill_bucket(self) -> None:
        attr = attribute_losses(
            {
                "market_scans": 24,
                "trade_proposals": 3,
                "selected_decisions": 3,
                "risk_accepts": 3,
                "risk_rejects": 0,
                "executed_paper_trades": 1,
            }
        )
        assert attr.bottleneck_gate == FunnelGates.PAPER
        assert attr.primary_loss_bucket == "NO_PAPER_FILL"

    def test_strategy_asset_regime_dimensions_recorded_when_supplied(self) -> None:
        attr = attribute_losses(
            {"market_scans": 24, "trade_proposals": 0},
            by_strategy={"momentum": 12, "trend": 12},
            by_asset={"BTC": 24},
            by_regime={"TREND": 24},
        )
        assert attr.by_strategy == {"momentum": 12, "trend": 12}
        assert attr.by_asset == {"BTC": 24}
        assert attr.by_regime == {"TREND": 24}
