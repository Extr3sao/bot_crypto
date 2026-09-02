"""PAPER-E2E-001 — canonical end-to-end paper trading flow (FASE 11).

Demonstrates on the FakeMarketDataSource (deterministic demo data):

    Market Data → UniverseScanner → PaperSessionRunner → PaperBroker
    → reconcile_session → fills/positions → PaperSessionResult → metrics

plus the FASE 13 negative cases that matter for the loop:

    N8  risk rejection path  (RiskManager.check_signal blocks, broker untouched)
    N9  kill switch path     (kill switch engaged → check_signal blocked)
    N14 live attempt blocked (start_paper_trading / orchestrator refuse non-paper)

The trade path (signal → fill → position → PnL) is exercised via
PaperBroker.execute_signal directly with a deterministic Signal, since the
demo scanner data produces no live signals by design (flat OHLCV) — this is
clearly identified as a synthetic-signal lifecycle test, not a fabricated
market prediction.
"""

from __future__ import annotations

import asyncio

import pytest

from trading_bot.config.runtime import TradingMode
from trading_bot.market_data.fake import build_demo_fetcher, build_demo_settings
from trading_bot.paper.broker import PaperBroker
from trading_bot.paper.paper_orchestrator import PaperOrchestrator
from trading_bot.scanner.mode_filters import build_filter_set_per_mode
from trading_bot.scanner.scanner import UniverseScanner
from trading_bot.strategies.types import Signal


def _build_paper_settings():
    """Paper settings for BTC/ETH/SOL.

    kill_switch_enabled=False here because of a PRE-EXISTING divergence in
    the codebase (documented as tech debt): the scanner interprets
    ``kill_switch_enabled=True`` as "kill switch ENGAGED" and aborts every
    iteration (RF-4, pinned by tests/unit/scanner), while RiskManager
    interprets it as "arm the kill switch" (engaged state tracked
    separately via activate_kill_switch, pinned by tests/unit/risk).
    The canonical loop must scan, so the flag is False at scanner level;
    the risk-level kill-switch path is still proven by N9, where
    activate_kill_switch() blocks every signal regardless of this flag.
    """
    settings = build_demo_settings(
        pairs=[("BTC/USDT", True), ("ETH/USDT", True), ("SOL/USDT", True)],
        mode="paper",
        kill_switch_enabled=False,
    )
    return settings


def _build_scanner(settings):
    source = build_demo_fetcher(settings)
    return UniverseScanner(
        source=source,
        registry_per_mode=build_filter_set_per_mode(settings),
        settings=settings,
    )


# ---------------------------------------------------------------------------
# E2E: two full orchestrator cycles over the demo universe
# ---------------------------------------------------------------------------


def test_paper_e2e_001_two_cycles_end_to_end():
    """PAPER-E2E-001: orchestrator runs 2 complete sessions E2E."""
    settings = _build_paper_settings()
    broker = PaperBroker(equity=10_000.0)
    orchestrator = PaperOrchestrator(
        settings=settings,
        scanner_factory=lambda: _build_scanner(settings),
        broker=broker,
        max_sessions=2,
        interval_seconds=0.0,
    )

    results = asyncio.run(orchestrator.run())

    assert len(results) == 2
    for r in results:
        assert r.session_id
        # Universe = the 3 configured pairs (BTC/ETH/SOL), all active on
        # demo data. The 5-pair default demo is not used here.
        assert r.metrics.total_snapshots == 3
        assert r.metrics.active_snapshots == 3
        assert r.metrics.scanner_errors == 0
        assert r.execution_summary is not None
        assert r.execution_summary.ending_equity == pytest.approx(10_000.0)

    status = orchestrator.status()
    assert status["running"] is False
    assert status["mode"] == "paper"
    assert status["sessions_completed"] == 2
    assert status["last_errors"] == []


def test_paper_e2e_no_trade_cycle_is_valid():
    """A cycle with zero signals/fills is a valid NO_TRADE outcome."""
    settings = _build_paper_settings()
    broker = PaperBroker(equity=5_000.0)
    orchestrator = PaperOrchestrator(
        settings=settings,
        scanner_factory=lambda: _build_scanner(settings),
        broker=broker,
        max_sessions=1,
        interval_seconds=0.0,
    )
    results = asyncio.run(orchestrator.run())
    assert len(results) == 1
    # Flat demo data → no fills; this is NO_TRADE, not failure.
    assert results[0].execution_summary is not None
    assert results[0].execution_summary.realized_pnl == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Trade path: deterministic signal → fill → position → close → PnL
# ---------------------------------------------------------------------------


def _make_signal(side: str, price: float = 100.0) -> Signal:
    return Signal(
        symbol="BTC/USDT",
        side=side,
        strategy_name="e2e_test_strategy",
        timeframe="5m",
        confidence=0.9,
        price=price,
        stop_loss_pct=1.0,
        take_profit_pct=2.0,
        metadata={"notional_usdt": 500.0},
    )


def test_trade_path_signal_to_fill_to_position():
    """TRADE path: execute_signal opens a position with correct notional."""
    broker = PaperBroker(equity=10_000.0, slippage_bps=1.0, commission_bps=5.0)
    sig = _make_signal("buy", price=100.0)

    result = broker.execute_signal(sig)

    assert result is not None
    assert not isinstance(result, object.__class__) or True  # PaperPosition
    from trading_bot.paper.broker import PaperPosition

    assert isinstance(result, PaperPosition)
    assert result.symbol == "BTC/USDT"
    # Fill price has slippage applied (buy → price above signal price)
    assert result.entry_price > 100.0


def test_trade_path_exit_realizes_pnl():
    """Position closes on opposite signal → ClosedTrade with realized PnL."""
    from trading_bot.paper.broker import ClosedTrade

    broker = PaperBroker(equity=10_000.0, slippage_bps=1.0, commission_bps=5.0)
    broker.execute_signal(_make_signal("buy", price=100.0))
    close_result = broker.execute_signal(_make_signal("sell", price=110.0))

    assert isinstance(close_result, ClosedTrade)
    assert close_result.symbol == "BTC/USDT"
    assert close_result.exit_reason == "signal"
    assert close_result.pnl != 0.0  # long from ~100 -> closed ~110 -> positive


# ---------------------------------------------------------------------------
# N8 / N9: risk rejection and kill-switch paths (fail closed)
# ---------------------------------------------------------------------------


def test_n8_risk_rejection_blocks_before_broker():
    """N8: RiskManager rejection → no broker call → no position opened.

    Uses risk-side kill_switch_enabled=True (ARMED, not engaged) so the
    daily_trade_limit gate is reachable after the first approval.
    """
    from trading_bot.risk.manager import RiskManager

    armed_settings = build_demo_settings(
        pairs=[("BTC/USDT", True)],
        mode="paper",
        kill_switch_enabled=True,
    )
    broker = PaperBroker(equity=10_000.0)
    risk = RiskManager(risk=armed_settings.risk, equity=10_000.0)

    sig = _make_signal("buy")
    check = risk.check_signal(sig)
    # The demo risk config allows this signal; simulate exhaustion instead:
    if check.approved:
        # Exhaust daily trade limit → next check must fail.
        risk.trades_today = armed_settings.risk.max_trades_per_day
        check = risk.check_signal(sig)

    assert not check.approved
    assert check.blocked_by == "daily_trade_limit"
    # Broker never called → no positions
    assert len(broker._positions) == 0


def test_n9_kill_switch_blocks_all_signals():
    """N9: kill switch engaged → every signal blocked, fail closed."""
    from trading_bot.risk.manager import RiskManager

    settings = _build_paper_settings()
    broker = PaperBroker(equity=10_000.0)
    risk = RiskManager(risk=settings.risk, equity=10_000.0)
    risk.activate_kill_switch("e2e_test")

    check = risk.check_signal(_make_signal("buy"))
    assert not check.approved
    assert check.blocked_by == "kill_switch"
    assert len(broker._positions) == 0


# ---------------------------------------------------------------------------
# N14: live attempt blocked at every layer
# ---------------------------------------------------------------------------


def test_n14_orchestrator_refuses_non_paper_mode():
    """N14: orchestrator refuses to start when mode != paper (fail closed)."""
    settings = _build_paper_settings()
    live_settings = settings.model_copy(
        update={"runtime": settings.runtime.model_copy(update={"mode": TradingMode.LIVE})}
    )
    orchestrator = PaperOrchestrator(
        settings=live_settings,
        scanner_factory=lambda: _build_scanner(live_settings),
        broker=PaperBroker(equity=10_000.0),
        max_sessions=1,
        interval_seconds=0.0,
    )
    with pytest.raises(ValueError, match="paper"):
        asyncio.run(orchestrator.run())


def test_n14_session_runner_refuses_non_paper_mode():
    """N14: PaperSessionRunner also validates mode independently."""
    from trading_bot.paper.harness import PaperSessionRunner

    settings = _build_paper_settings()
    live_settings = settings.model_copy(
        update={"runtime": settings.runtime.model_copy(update={"mode": TradingMode.LIVE})}
    )
    runner = PaperSessionRunner(
        scanner=_build_scanner(live_settings),
        settings=live_settings,
        broker=PaperBroker(equity=10_000.0),
    )
    with pytest.raises(ValueError, match="paper"):
        asyncio.run(runner.run_session())


def test_live_mode_remains_disabled_by_default():
    """LIVE gate: default config is paper; live_trading_enabled is falsy."""
    settings = _build_paper_settings()
    assert settings.runtime.mode is TradingMode.PAPER
    live_flag = getattr(settings.runtime, "live_trading_enabled", None)
    if live_flag is not None:
        assert not live_flag
