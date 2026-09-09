"""Track B tests — ShadowCandidateCapture, PIT outcome engine, reject metrics."""

from __future__ import annotations

import pytest

from trading_bot.shadow import (
    SHADOW_LABELS,
    ShadowBar,
    ShadowCandidateCapture,
    ShadowCandidateLedger,
    ShadowOutcomeEngine,
)
from trading_bot.shadow.outcome import ShadowOutcomeLedger, ShadowTradeOutcome
from trading_bot.shadow.reject_metrics import RejectReasonAnalysis


def _capture(**overrides: object) -> ShadowCandidateCapture:
    base: dict[str, object] = {
        "decision_id": "decision:x",
        "trace_id": "t1",
        "run_id": "r1",
        "asset": "BTC",
        "direction": "LONG",
        "strategy_id": "Momentum",
        "strategy_version": "v1",
        "timeframe": "5m",
        "proposal_ref": "p1",
        "decision_ref": "d1",
        "verifier_ref": "v1",
        "decision_time": "2026-09-01T00:00:00+00:00",
        "decision_price": 100.0,
        "entry_reference": 100.0,
        "stop_loss": 98.0,
        "take_profit": 104.0,
        "invalidation": "sl",
        "regime_signature": "TREND|BULL",
        "strategy_health_state": "HEALTHY",
        "portfolio_context_ref": "ctx1",
        "correlation_state": "NORMAL",
        "risk_verdict": "REJECT",
        "risk_rejection_reason": "MAX_POSITIONS",
        "market_data_fingerprint": "md5x",
        "cost_model_sha256": "cm5x",
    }
    base.update(overrides)
    return ShadowCandidateCapture(**base)  # type: ignore[arg-type]


class TestCapture:
    def test_deterministic_identity_ignores_non_economic_fields(self) -> None:
        a = _capture(trace_id="trace-A", run_id="run-A")
        b = _capture(trace_id="trace-B", run_id="run-B")
        assert a.shadow_candidate_id == b.shadow_candidate_id

    def test_identity_changes_with_economic_fields(self) -> None:
        a = _capture()
        b = _capture(decision_time="2026-09-02T00:00:00+00:00")
        c = _capture(direction="SHORT")
        assert len({a.shadow_candidate_id, b.shadow_candidate_id, c.shadow_candidate_id}) == 3

    def test_labels_are_canonical_and_immutable(self) -> None:
        cap = _capture()
        assert cap.labels == SHADOW_LABELS
        with pytest.raises(ValueError):
            ShadowCandidateCapture(
                **{
                    **{f: getattr(cap, f) for f in cap.__dataclass_fields__ if f != "labels"},
                    "labels": ("SHADOW_ONLY",),
                }  # type: ignore[arg-type]
            )

    def test_only_rejects_captured(self) -> None:
        with pytest.raises(ValueError, match="REJECT"):
            _capture(risk_verdict="ACCEPT")

    def test_direction_fail_closed(self) -> None:
        with pytest.raises(ValueError, match="direction"):
            _capture(direction="FLAT")

    def test_round_trip_preserves_identity_and_economics(self, tmp_path) -> None:
        ledger = ShadowCandidateLedger()
        cap = _capture()
        ledger.record(cap)
        path = tmp_path / "shadow_captures.jsonl"
        ledger.save(path)
        reloaded = ShadowCandidateLedger.load(path)
        assert len(reloaded) == 1
        other = reloaded.captures[0]
        assert other.shadow_candidate_id == cap.shadow_candidate_id
        assert other.entry_reference == cap.entry_reference
        assert other.risk_rejection_reason == cap.risk_rejection_reason

    def test_duplicate_capture_rejected(self) -> None:
        ledger = ShadowCandidateLedger()
        ledger.record(_capture())
        with pytest.raises(ValueError, match="duplicate"):
            ledger.record(_capture())


class TestOutcomeEngine:
    def test_pre_decision_bars_ignored(self) -> None:
        eng = ShadowOutcomeEngine()
        bars = [ShadowBar("2026-08-31T23:59:00+00:00", 200.0, 90.0, 100.0)]
        trade = eng.resolve(_capture(), bars)
        assert trade.outcome is ShadowTradeOutcome.STILL_OPEN
        assert trade.bars_evaluated == 0
        assert trade.exit_price is None

    def test_append_after_resolution_is_stable(self) -> None:
        eng = ShadowOutcomeEngine()
        resolving = [ShadowBar("2026-09-01T00:05:00+00:00", 104.5, 100.5, 104.0)]
        next_bar = ShadowBar("2026-09-01T00:10:00+00:00", 500.0, 10.0, 250.0)
        extended = [*resolving, next_bar]
        t1 = eng.resolve(_capture(), resolving)
        t2 = eng.resolve(_capture(), extended)
        assert t1.outcome is ShadowTradeOutcome.TAKE_PROFIT_HIT
        assert t2.outcome is t1.outcome
        assert t2.exit_price == t1.exit_price
        assert t2.exit_time == t1.exit_time
        assert t2.net_pnl == pytest.approx(t1.net_pnl)

    def test_adverse_first_when_both_hit_same_bar(self) -> None:
        eng = ShadowOutcomeEngine()
        bars = [ShadowBar("2026-09-01T00:05:00+00:00", 104.5, 97.5, 101.0)]
        trade = eng.resolve(_capture(), bars)
        assert trade.outcome is ShadowTradeOutcome.STOP_LOSS_HIT

    def test_short_tp_hit(self) -> None:
        eng = ShadowOutcomeEngine()
        cap = _capture(
            direction="SHORT",
            entry_reference=100.0,
            stop_loss=102.0,
            take_profit=96.0,
        )
        bars = [ShadowBar("2026-09-01T00:05:00+00:00", 101.0, 95.5, 96.2)]
        trade = eng.resolve(cap, bars)
        assert trade.outcome is ShadowTradeOutcome.TAKE_PROFIT_HIT
        assert trade.gross_pnl == pytest.approx(4.0)

    def test_short_sl_adverse_first(self) -> None:
        eng = ShadowOutcomeEngine()
        cap = _capture(
            direction="SHORT",
            entry_reference=100.0,
            stop_loss=102.0,
            take_profit=96.0,
        )
        bars = [ShadowBar("2026-09-01T00:05:00+00:00", 102.5, 95.5, 96.2)]
        trade = eng.resolve(cap, bars)
        assert trade.outcome is ShadowTradeOutcome.STOP_LOSS_HIT
        assert trade.gross_pnl == pytest.approx(-2.0)

    def test_costs_flows_through_canonical_model(self) -> None:
        eng = ShadowOutcomeEngine()
        bars = [ShadowBar("2026-09-01T00:05:00+00:00", 104.5, 99.5, 104.0)]
        trade = eng.resolve(_capture(), bars)
        explicit = (
            trade.entry_fee_usdt
            + trade.exit_fee_usdt
            + trade.entry_slippage_usdt
            + trade.exit_slippage_usdt
        )
        assert explicit > 0
        assert trade.net_pnl == pytest.approx(trade.gross_pnl - explicit)
        # R multiple on net pnl over 1R risk (2.0 USDT per unit, qty 1)
        assert trade.r_multiple == pytest.approx(trade.net_pnl / 2.0)

    def test_plan_geometry_fail_closed(self) -> None:
        eng = ShadowOutcomeEngine()
        with pytest.raises(ValueError, match="LONG plan"):
            eng.resolve(_capture(stop_loss=105.0), [])
        with pytest.raises(ValueError, match="SHORT plan"):
            eng.resolve(_capture(direction="SHORT", stop_loss=95.0, take_profit=105.0), [])

    def test_partial_fill_style_partial_move_still_open(self) -> None:
        eng = ShadowOutcomeEngine()
        bars = [ShadowBar("2026-09-01T00:05:00+00:00", 103.0, 99.0, 101.0)]
        trade = eng.resolve(_capture(), bars)
        assert trade.outcome is ShadowTradeOutcome.STILL_OPEN
        # Unresolved: no exit exists yet; costs are still registered for the
        # hypothetical entry + end-of-window mark via the canonical model.
        assert trade.exit_price is None
        assert trade.exit_time is None
        assert trade.r_multiple is None


class TestRejectMetrics:
    def _ledger_with_trades(self) -> ShadowOutcomeLedger:
        eng = ShadowOutcomeEngine()
        cap_win = _capture(decision_id="decision:win", take_profit=104.0, stop_loss=98.0,
                           risk_rejection_reason="MAX_POSITIONS")
        cap_loss = _capture(decision_id="decision:loss", take_profit=101.0, stop_loss=98.0,
                            risk_rejection_reason="CONSECUTIVE_LOSS_COOLDOWN",
                            strategy_health_state="MONITORING")
        ledger = ShadowOutcomeLedger()
        ledger.record(eng.resolve(cap_win, [ShadowBar("2026-09-01T00:05:00+00:00", 104.5, 99.0, 104.0)]))
        ledger.record(eng.resolve(cap_loss, [ShadowBar("2026-09-01T00:05:00+00:00", 100.5, 97.5, 98.2)]))
        return ledger

    def test_metrics_by_reason(self) -> None:
        analysis = RejectReasonAnalysis(self._ledger_with_trades())
        summary = analysis.summary()
        assert set(summary) == {"MAX_POSITIONS", "CONSECUTIVE_LOSS_COOLDOWN"}
        mp = summary["MAX_POSITIONS"]
        assert mp["wins"] == 1 and mp["losses"] == 0
        assert mp["expectancy_net"] > 0
        cl = summary["CONSECUTIVE_LOSS_COOLDOWN"]
        assert cl["wins"] == 0 and cl["losses"] == 1
        assert cl["health_state_distribution"] == {"MONITORING": 1}

    def test_classification_insufficient_sample_fail_closed(self) -> None:
        analysis = RejectReasonAnalysis(self._ledger_with_trades())
        summary = analysis.summary()
        # Only 1 sample per reason -> INSUFFICIENT_EVIDENCE regardless of outcome
        assert all(s["classification"] == "INSUFFICIENT_EVIDENCE" for s in summary.values())

    def test_classification_good_and_bad_candidates(self) -> None:
        eng = ShadowOutcomeEngine()
        ledger = ShadowOutcomeLedger()
        for i in range(25):
            cap = _capture(
                decision_id=f"decision:good-{i}",
                decision_time=f"2026-09-{(i % 28) + 1:02d}T00:00:00+00:00",
                take_profit=110.0,
                stop_loss=98.0,
                risk_rejection_reason="MAX_POSITIONS",
            )
            ledger.record(
                eng.resolve(cap, [ShadowBar("2026-09-01T01:00:00+00:00", 111.0, 99.0, 110.0)])
            )
        for i in range(25):
            cap = _capture(
                decision_id=f"decision:bad-{i}",
                decision_time=f"2026-09-{(i % 28) + 1:02d}T00:00:00+00:00",
                take_profit=101.0,  # valid geometry; bar never reaches TP
                stop_loss=98.0,
                risk_rejection_reason="CONSECUTIVE_LOSS_COOLDOWN",
            )
            ledger.record(
                eng.resolve(cap, [ShadowBar("2026-09-01T01:00:00+00:00", 100.5, 97.5, 98.5)])
            )
        analysis = RejectReasonAnalysis(ledger)
        summary = analysis.summary()
        assert summary["MAX_POSITIONS"]["classification"] == "GOOD_CANDIDATE_BLOCKED"
        assert summary["CONSECUTIVE_LOSS_COOLDOWN"]["classification"] == (
            "LOW_QUALITY_CANDIDATE_CORRECTLY_BLOCKED"
        )

    def test_empty_ledger_is_honest(self) -> None:
        analysis = RejectReasonAnalysis(ShadowOutcomeLedger())
        assert analysis.summary() == {}

    def test_outcome_ledger_round_trip(self, tmp_path) -> None:
        ledger = self._ledger_with_trades()
        path = tmp_path / "shadow_outcomes.jsonl"
        ledger.save(path)
        raw = path.read_text(encoding="utf-8")
        assert '"labels"' in raw and "EXCLUDED_FROM_PAPER_PNL" in raw
        reloaded = ShadowOutcomeLedger.load(path)
        assert len(reloaded) == len(ledger)
        a, b = ledger.trades[0], reloaded.trades[0]
        assert a.shadow_candidate_id == b.shadow_candidate_id
        assert a.net_pnl == pytest.approx(b.net_pnl)
        assert a.outcome is b.outcome
