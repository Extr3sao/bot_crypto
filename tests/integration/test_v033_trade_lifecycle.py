"""
V0.3.3 Phase 5: Full Trade Lifecycle Integration Tests.

Proves the complete cycle:
BAR → SIGNAL → PORTFOLIO ACCEPT → RISK APPROVE → ORDER → ENTRY FILL
→ POSITION OPEN → SL or TP TRIGGER → EXIT FILL → POSITION CLOSED
→ REALIZED PNL → EQUITY UPDATE → JOURNAL → RECONCILIATION

Includes scenarios for: LONG TP, LONG SL, SHORT TP, SHORT SL,
SL+TP same candle (intrabar ambiguity), fees, slippage.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from src.trading_bot.paper.agents import RiskDecision
from src.trading_bot.paper.execution_agent import (
    ExecutionBrokerType,
    ExitReason,
    IntrabarPolicy,
    PaperBrokerAdapter,
    PaperExecutionAgent,
)
from src.trading_bot.paper.signal_types import SignalCandidate, SignalDirection


# ---------------------------------------------------------------------------
# Minimal OHLCV bar for testing
# ---------------------------------------------------------------------------
@dataclass
class FakeBar:
    timestamp: int  # epoch ms
    open: float
    high: float
    low: float
    close: float
    volume: float = 100.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def make_signal(direction: str, entry: float, stop: float, target: float) -> SignalCandidate:
    risk_abs = abs(entry - stop)
    reward_abs = abs(target - entry)
    rr = reward_abs / risk_abs if risk_abs > 0 else 2.0
    return SignalCandidate(
        signal_id=uuid.uuid4(),
        setup_id=f"setup_{uuid.uuid4().hex[:8]}",
        alpha_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        family="infrastructure_control",
        version="v0.3.3",
        symbol="BTCUSDT",
        timeframe="5m",
        direction=SignalDirection(direction.lower()),
        signal_timestamp=datetime.utcnow(),
        source_bar_timestamp=datetime.utcnow(),
        entry_reference=entry,
        stop=stop,
        target=target,
        planned_risk=risk_abs * 0.01,
        planned_rr=rr,
        planned_net_rr=rr * 0.99,
    )


def make_risk(signal: SignalCandidate, quantity: float) -> RiskDecision:
    notional = quantity * signal.entry_reference
    return RiskDecision(
        signal_id=signal.signal_id,
        decision_id=uuid.uuid4(),
        portfolio_decision_id=uuid.uuid4(),
        approved=True,
        quantity=quantity,
        notional_usdt=notional,
        stop_risk_usdt=abs(signal.entry_reference - signal.stop) * quantity,
        equity=10_000.0,
        portfolio_exposure_before_pct=0.0,
        portfolio_exposure_after_pct=notional / 10_000.0 * 100,
    )


def make_broker(**kwargs) -> tuple[PaperBrokerAdapter, PaperExecutionAgent]:
    broker = PaperBrokerAdapter(
        initial_equity=kwargs.get("equity", 10_000.0),
        commission_bps=kwargs.get("commission_bps", 5.0),
        slippage_bps=kwargs.get("slippage_bps", 2.0),
        intrabar_policy=kwargs.get("intrabar_policy", IntrabarPolicy.SL_FIRST),
    )
    agent = PaperExecutionAgent(
        broker=broker,
        broker_type=ExecutionBrokerType.PAPER,
    )
    return broker, agent


# ===========================================================================
# PHASE 5.1 — LONG TAKE PROFIT
# ===========================================================================
class TestLongTakeProfit:
    def test_long_tp_full_lifecycle(self):
        """LONG position hits TP → realized profit, equity increases."""
        broker, agent = make_broker(equity=10_000.0)

        signal = make_signal("BUY", entry=50_000.0, stop=49_500.0, target=51_000.0)
        risk = make_risk(signal, quantity=0.01)

        # Execute entry
        fill = agent.execute(risk, signal)
        assert fill.filled is True
        assert fill.fill_price > signal.entry_reference  # slippage on buy

        # Verify position opened
        positions = broker.get_open_positions()
        assert len(positions) == 1
        pos = positions[0]
        assert pos.direction == "BUY"
        assert pos.symbol == "BTCUSDT"

        # Simulate bar that hits TP
        entry_ts = int(datetime.utcnow().timestamp() * 1000)
        tp_bar = FakeBar(
            timestamp=entry_ts + 300_000,  # 5 min later
            open=50_800.0,
            high=51_200.0,  # above target
            low=50_600.0,
            close=51_100.0,
        )

        exit_fills = broker.check_exits(
            {"BTCUSDT": [tp_bar]},
            tp_bar.timestamp,
        )

        assert len(exit_fills) == 1
        ef = exit_fills[0]
        assert ef.exit_reason == ExitReason.TAKE_PROFIT
        assert ef.gross_pnl > 0  # profitable TP

        # Verify position closed
        assert len(broker.get_open_positions()) == 0
        assert len(broker.get_closed_positions()) == 1

        # Accounting
        summary = broker.get_accounting_summary()
        assert summary["ClosedTrades"] == 1
        assert summary["OpenPositions"] == 0
        assert summary["RealizedGrossPnL"] > 0
        assert summary["RealizedNetPnL"] > 0
        assert summary["ReconciliationDelta"] < 0.01  # floating point tolerance


# ===========================================================================
# PHASE 5.2 — LONG STOP LOSS
# ===========================================================================
class TestLongStopLoss:
    def test_long_sl_full_lifecycle(self):
        """LONG position hits SL → realized loss, equity decreases."""
        broker, agent = make_broker(equity=10_000.0)

        signal = make_signal("BUY", entry=50_000.0, stop=49_500.0, target=51_000.0)
        risk = make_risk(signal, quantity=0.01)

        fill = agent.execute(risk, signal)
        assert fill.filled is True

        # Simulate bar that hits SL
        entry_ts = int(datetime.utcnow().timestamp() * 1000)
        sl_bar = FakeBar(
            timestamp=entry_ts + 300_000,
            open=49_600.0,
            high=49_800.0,
            low=49_300.0,  # below stop
            close=49_400.0,
        )

        exit_fills = broker.check_exits(
            {"BTCUSDT": [sl_bar]},
            sl_bar.timestamp,
        )

        assert len(exit_fills) == 1
        ef = exit_fills[0]
        assert ef.exit_reason == ExitReason.STOP_LOSS
        assert ef.gross_pnl < 0  # loss

        assert len(broker.get_open_positions()) == 0

        summary = broker.get_accounting_summary()
        assert summary["ClosedTrades"] == 1
        assert summary["RealizedNetPnL"] < 0
        assert summary["ReconciliationDelta"] < 0.01


# ===========================================================================
# PHASE 5.3 — SHORT TAKE PROFIT
# ===========================================================================
class TestShortTakeProfit:
    def test_short_tp_full_lifecycle(self):
        """SHORT position hits TP → realized profit."""
        broker, agent = make_broker(equity=10_000.0)

        signal = make_signal("SELL", entry=50_000.0, stop=50_500.0, target=49_000.0)
        risk = make_risk(signal, quantity=0.01)

        fill = agent.execute(risk, signal)
        assert fill.filled is True

        entry_ts = int(datetime.utcnow().timestamp() * 1000)
        tp_bar = FakeBar(
            timestamp=entry_ts + 300_000,
            open=49_200.0,
            high=49_400.0,
            low=48_800.0,  # below target
            close=48_900.0,
        )

        exit_fills = broker.check_exits(
            {"BTCUSDT": [tp_bar]},
            tp_bar.timestamp,
        )

        assert len(exit_fills) == 1
        ef = exit_fills[0]
        assert ef.exit_reason == ExitReason.TAKE_PROFIT
        assert ef.gross_pnl > 0

        summary = broker.get_accounting_summary()
        assert summary["ClosedTrades"] == 1
        assert summary["RealizedNetPnL"] > 0


# ===========================================================================
# PHASE 5.4 — SHORT STOP LOSS
# ===========================================================================
class TestShortStopLoss:
    def test_short_sl_full_lifecycle(self):
        """SHORT position hits SL → realized loss."""
        broker, agent = make_broker(equity=10_000.0)

        signal = make_signal("SELL", entry=50_000.0, stop=50_500.0, target=49_000.0)
        risk = make_risk(signal, quantity=0.01)

        fill = agent.execute(risk, signal)
        assert fill.filled is True

        entry_ts = int(datetime.utcnow().timestamp() * 1000)
        sl_bar = FakeBar(
            timestamp=entry_ts + 300_000,
            open=50_200.0,
            high=50_700.0,  # above stop
            low=50_100.0,
            close=50_600.0,
        )

        exit_fills = broker.check_exits(
            {"BTCUSDT": [sl_bar]},
            sl_bar.timestamp,
        )

        assert len(exit_fills) == 1
        ef = exit_fills[0]
        assert ef.exit_reason == ExitReason.STOP_LOSS
        assert ef.gross_pnl < 0

        summary = broker.get_accounting_summary()
        assert summary["ClosedTrades"] == 1
        assert summary["RealizedNetPnL"] < 0


# ===========================================================================
# PHASE 5.5 — INTRABAR AMBIGUITY (SL + TP same candle)
# ===========================================================================
class TestIntrabarAmbiguity:
    def test_both_sl_tp_same_bar_sl_first(self):
        """When both SL and TP are touched in same bar, SL_FIRST policy → SL exit."""
        broker, agent = make_broker(
            equity=10_000.0,
            intrabar_policy=IntrabarPolicy.SL_FIRST,
        )

        signal = make_signal("BUY", entry=50_000.0, stop=49_500.0, target=51_000.0)
        risk = make_risk(signal, quantity=0.01)

        agent.execute(risk, signal)

        entry_ts = int(datetime.utcnow().timestamp() * 1000)
        ambiguous_bar = FakeBar(
            timestamp=entry_ts + 300_000,
            open=50_200.0,
            high=51_200.0,  # above target → TP hit
            low=49_300.0,  # below stop → SL hit
            close=50_500.0,
        )

        exit_fills = broker.check_exits(
            {"BTCUSDT": [ambiguous_bar]},
            ambiguous_bar.timestamp,
        )

        assert len(exit_fills) == 1
        ef = exit_fills[0]
        assert ef.exit_reason == ExitReason.INTRABAR_AMBIGUOUS_SL_FIRST

    def test_both_sl_tp_same_bar_tp_first(self):
        """TP_FIRST policy → TP exit when both touched."""
        broker, agent = make_broker(
            equity=10_000.0,
            intrabar_policy=IntrabarPolicy.TP_FIRST,
        )

        signal = make_signal("BUY", entry=50_000.0, stop=49_500.0, target=51_000.0)
        risk = make_risk(signal, quantity=0.01)

        agent.execute(risk, signal)

        entry_ts = int(datetime.utcnow().timestamp() * 1000)
        ambiguous_bar = FakeBar(
            timestamp=entry_ts + 300_000,
            open=50_200.0,
            high=51_200.0,
            low=49_300.0,
            close=50_500.0,
        )

        exit_fills = broker.check_exits(
            {"BTCUSDT": [ambiguous_bar]},
            ambiguous_bar.timestamp,
        )

        assert len(exit_fills) == 1
        ef = exit_fills[0]
        assert ef.exit_reason == ExitReason.TAKE_PROFIT


# ===========================================================================
# PHASE 5.6 — FEES AND SLIPPAGE VERIFICATION
# ===========================================================================
class TestFeesAndSlippage:
    def test_entry_and_exit_costs_accounted(self):
        """Both entry and exit commissions and slippage are tracked."""
        broker, agent = make_broker(
            equity=10_000.0,
            commission_bps=5.0,
            slippage_bps=2.0,
        )

        signal = make_signal("BUY", entry=50_000.0, stop=49_500.0, target=51_000.0)
        risk = make_risk(signal, quantity=0.01)

        fill = agent.execute(risk, signal)
        assert fill.filled is True

        # Entry slippage: buy side = fill_price > entry_price
        assert fill.fill_price > signal.entry_reference

        entry_ts = int(datetime.utcnow().timestamp() * 1000)
        tp_bar = FakeBar(
            timestamp=entry_ts + 300_000,
            open=50_800.0,
            high=51_200.0,
            low=50_600.0,
            close=51_100.0,
        )

        exit_fills = broker.check_exits(
            {"BTCUSDT": [tp_bar]},
            tp_bar.timestamp,
        )

        assert len(exit_fills) == 1
        ef = exit_fills[0]

        # Exit slippage: sell side = fill_price < target
        assert ef.fill_price < 51_000.0  # TP is 51000

        # Fees > 0
        assert ef.entry_commission > 0
        assert ef.exit_commission > 0
        assert ef.total_fees > 0

        # Slippage > 0
        assert ef.entry_slippage > 0
        assert ef.exit_slippage > 0
        assert ef.total_slippage > 0

        # Net PnL < Gross PnL (costs deducted)
        assert ef.net_pnl < ef.gross_pnl

    def test_accounting_reconciliation(self):
        """StartingEquity + RealizedNetPnL + UnrealizedPnL ≈ EndingEquity."""
        broker, agent = make_broker(equity=10_000.0)

        signal = make_signal("BUY", entry=50_000.0, stop=49_500.0, target=51_000.0)
        risk = make_risk(signal, quantity=0.01)

        agent.execute(risk, signal)

        entry_ts = int(datetime.utcnow().timestamp() * 1000)
        tp_bar = FakeBar(
            timestamp=entry_ts + 300_000,
            open=50_800.0,
            high=51_200.0,
            low=50_600.0,
            close=51_100.0,
        )

        broker.check_exits({"BTCUSDT": [tp_bar]}, tp_bar.timestamp)

        summary = broker.get_accounting_summary()

        # Core reconciliation: StartingEquity + RealizedNet ≈ EndingEquity (no open positions)
        expected = summary["StartingEquity"] + summary["RealizedNetPnL"]
        actual = summary["EndingEquity"]
        assert abs(expected - actual) < 0.01, (
            f"Reconciliation failed: expected={expected}, actual={actual}"
        )
        assert summary["ReconciliationDelta"] < 0.01


# ===========================================================================
# PHASE 5.7 — NO EXIT WHEN NOT TRIGGERED
# ===========================================================================
class TestNoExitWhenNotTriggered:
    def test_position_stays_open_within_range(self):
        """Position stays open if price is within SL/TP range."""
        broker, agent = make_broker(equity=10_000.0)

        signal = make_signal("BUY", entry=50_000.0, stop=49_500.0, target=51_000.0)
        risk = make_risk(signal, quantity=0.01)

        agent.execute(risk, signal)

        entry_ts = int(datetime.utcnow().timestamp() * 1000)
        safe_bar = FakeBar(
            timestamp=entry_ts + 300_000,
            open=50_100.0,
            high=50_500.0,  # below TP
            low=49_800.0,  # above SL
            close=50_200.0,
        )

        exit_fills = broker.check_exits(
            {"BTCUSDT": [safe_bar]},
            safe_bar.timestamp,
        )

        assert len(exit_fills) == 0
        assert len(broker.get_open_positions()) == 1


# ===========================================================================
# PHASE 5.8 — CLOSE ALL OPEN (end of replay)
# ===========================================================================
class TestCloseAllOpen:
    def test_close_all_open_positions(self):
        """close_all_open closes all remaining positions at mark-to-market."""
        broker, agent = make_broker(equity=10_000.0)

        signal = make_signal("BUY", entry=50_000.0, stop=49_500.0, target=51_000.0)
        risk = make_risk(signal, quantity=0.01)

        agent.execute(risk, signal)
        assert len(broker.get_open_positions()) == 1

        closed = broker.close_all_open(
            exit_reason=ExitReason.END_OF_REPLAY,
            last_prices={"BTCUSDT": 50_500.0},
        )

        assert len(closed) == 1
        assert closed[0].exit_reason == ExitReason.END_OF_REPLAY
        assert len(broker.get_open_positions()) == 0

        summary = broker.get_accounting_summary()
        assert summary["ClosedTrades"] == 1
        assert summary["ReconciliationDelta"] < 0.01
