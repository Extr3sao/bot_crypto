"""TEST_ONLY — WP-016B: the complete PAPER order cycle, proved end to end.

These are *integration* tests over the real runtime classes, not mocks:

    PIT bars -> AssetContext -> StrategyRouter -> EmaCrossoverFamily
    -> SignalAdapter -> RiskManager.check_signal -> PaperBroker.execute_signal
    -> mark-to-market -> SL/TP close -> net PnL -> durable state store
    -> StartupReconcilerV4 -> intent ledger -> duplicate suppression

They are labelled ``TEST_ONLY`` on purpose and the label is not decoration:

* the prices are deterministic fixtures, not market data — nothing here is
  evidence of profit, and no number below is presented as a track record;
* the only thing these tests claim is **mechanical**: a PAPER order that the
  risk engine approved becomes exactly one fill, that fill closes once, the
  closed trade's PnL is net of both commissions, the persisted book restores
  with the same equity identity, and re-issuing the same intent after a
  restart places no second order.

The economics of the strategy itself are decided in WP-016A/C from research
artifacts; this module never touches that verdict, no exchange is contacted,
no credential is read and LIVE is not reachable from this path.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from trading_bot.execution.idempotency import IdempotencyGuard
from trading_bot.market_data.types import OHLCV
from trading_bot.paper.broker import BrokerOrderError, PaperBroker
from trading_bot.paper.paper_cycle import PaperCycleEngine
from trading_bot.paper.paper_runtime_state import save_session_state
from trading_bot.paper.paper_state_store import PaperStateStore
from trading_bot.paper.reconciliation_v4 import ReconciliationStatusV4, StartupReconcilerV4
from trading_bot.research.asset_intelligence.registry import CryptoAssetAgentRegistry
from trading_bot.research.families.ema_crossover_family import EmaCrossoverFamily
from trading_bot.research.strategy_router import StrategyRouter
from trading_bot.risk.manager import RiskManager

#: Explicit, machine-readable label: every artefact built from this module says
#: TEST_ONLY, and the evidence JSON records it next to the numbers.
LABEL = "TEST_ONLY"

TS0 = 1_700_000_000_000
BAR_MS = 60_000
SYMBOL = "BTC/USDT"
EQUITY = 10_000.0


def _bars(symbol: str = SYMBOL, n: int = 100) -> list[OHLCV]:
    """Deterministic rising market: fast EMA above slow, RSI high."""
    out: list[OHLCV] = []
    for i in range(n):
        price = 100.0 + i * 1.0
        out.append(
            OHLCV(
                symbol=symbol,
                timestamp=TS0 + i * BAR_MS,
                open=price,
                high=price + 1.0,
                low=price - 1.0,
                close=price + 0.5,
                volume=1_000.0,
            )
        )
    return out


def _settings():
    from trading_bot.market_data.fake import build_demo_settings

    return build_demo_settings(
        pairs=[(SYMBOL, True)],
        mode="paper",
        kill_switch_enabled=True,  # armed and healthy, as in PAPER-E2E-003
    )


def _engine(settings, broker: PaperBroker, risk: RiskManager, guard: IdempotencyGuard):
    return PaperCycleEngine(
        asset_registry=CryptoAssetAgentRegistry(),
        router=StrategyRouter(),
        strategy_map={
            "ema_crossover": {
                "family": "ema_crossover",
                "regimes": [],
                "direction": "BOTH",
                "enabled": True,
                "status": "PAPER_ACTIVE",
            }
        },
        families={"ema_crossover": EmaCrossoverFamily()},
        risk_manager=risk,
        broker=broker,
        indicator_fn=lambda candles: {},
        idempotency=guard,
    )


def _decide(engine: PaperCycleEngine, bars: list[OHLCV]):
    return engine.run_cycle_sync(
        {SYMBOL: bars}, {SYMBOL: bars[-1].timestamp}
    )


def _emit(trace: dict) -> None:
    """Write the cycle trace where the evidence runner asked for it, if asked.

    Kept opt-in so the test stays hermetic when run on its own: without the env
    var nothing is written anywhere.
    """
    target = os.environ.get("WP016_TRACE_DIR")
    if not target:
        return
    out = Path(target)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{trace['name']}.json").write_text(
        json.dumps({**trace, "label": LABEL}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _close_at_take_profit(broker: PaperBroker, symbol: str = SYMBOL):
    pos = broker.positions[symbol]
    tp = pos.take_profit_price
    return broker.check_positions_ohlc(
        {symbol: (pos.entry_price, tp * 1.001, pos.entry_price * 0.999, tp)}
    )


def test_order_fill_pnl_and_reconciliation_are_one_consistent_cycle(tmp_path):
    """Order → fill → close → net PnL → persist → restart → reconcile."""
    settings = _settings()
    broker = PaperBroker(equity=EQUITY, slippage_bps=1.0, commission_bps=5.0)
    risk = RiskManager(risk=settings.risk, equity=broker.equity)
    guard = IdempotencyGuard()
    engine = _engine(settings, broker, risk, guard)
    bars = _bars()

    counts = _decide(engine, bars)

    # 1. ORDER: the risk engine approved a size and the broker received it.
    assert counts.orders_created == 1, counts.to_dict()
    assert counts.risk_accepted == 1
    assert counts.broker_errors == 0
    cloids = guard.sent_cloids
    assert len(cloids) == 1, "exactly one intent identity for one order"

    position = broker.positions[SYMBOL]
    entry = position.entry_price
    notional = position.notional_usdt
    commission_bps = 5.0
    expected_entry_fee = notional * commission_bps / 10_000.0

    # 2. FILL: the fill is the bar close plus the configured slippage, and the
    #    size comes from risk — never invented by the broker.
    assert entry == pytest.approx(bars[-1].close * (1.0 + 1.0 / 10_000.0), rel=1e-12)
    assert notional > 0
    assert position.entry_commission == pytest.approx(expected_entry_fee, rel=1e-12)

    # 3. MARK-TO-MARKET: unrealized PnL uses the last close, not a guess.
    unrealized = broker.unrealized_pnl({SYMBOL: bars[-1].close})
    assert unrealized == pytest.approx(
        (bars[-1].close - entry) * position.quantity, rel=1e-12
    )

    # 4. CLOSE: the take-profit level is touched; the trade closes once.
    closed = _close_at_take_profit(broker)
    assert len(closed) == 1
    trade = closed[0]
    assert trade.exit_reason == "take_profit"
    assert broker.positions == {}

    # 5. PnL: net of BOTH commissions and of the exit slippage.
    gross = (trade.exit_price - trade.entry_price) * trade.quantity
    exit_fee = notional * commission_bps / 10_000.0
    assert trade.pnl == pytest.approx(gross - expected_entry_fee - exit_fee, rel=1e-12)
    assert trade.pnl < gross, "costs must reduce the result: this is net PnL"
    fees_paid = expected_entry_fee + exit_fee

    # 6. EQUITY IDENTITY: the book is the ledger, to the cent.
    assert broker.equity == pytest.approx(EQUITY + trade.pnl, rel=1e-12)
    summary = broker.reconcile_session("wp016-session", [], risk)
    assert summary.new_closed_trades == (trade,)
    assert summary.realized_pnl == pytest.approx(trade.pnl, rel=1e-12)
    # The ledger cursor advanced: a second reconcile re-reports nothing (DEF-101).
    assert broker.reconcile_session("wp016-session", [], risk).new_closed_trades == ()

    # 7. PERSIST: the same objects the runtime persists, through the runtime glue.
    store = PaperStateStore(tmp_path / "paper_state.json")
    save_session_state(
        store=store, run_id="wp016-restart", broker=broker, risk=risk, idempotency=guard
    )
    assert store.path.exists()

    # 8. RESTART: fresh objects, restored from disk only.
    restored_broker = PaperBroker(equity=EQUITY, slippage_bps=1.0, commission_bps=5.0)
    restored_risk = RiskManager(risk=settings.risk, equity=EQUITY)
    restored_guard = IdempotencyGuard()
    report = StartupReconcilerV4(
        store=store,
        broker=restored_broker,
        risk_manager=restored_risk,
        idempotency=restored_guard,
    ).reconcile()

    assert report.status == ReconciliationStatusV4.RECOVERED, report.to_dict()
    assert report.restored_closed_trades == 1
    assert report.restored_equity == pytest.approx(broker.equity, rel=1e-12)
    assert restored_broker.equity == pytest.approx(broker.equity, rel=1e-12)
    assert restored_broker.closed_trades[0].pnl == pytest.approx(trade.pnl, rel=1e-12)
    assert restored_risk.equity == pytest.approx(broker.equity, rel=1e-12)
    assert set(restored_guard.sent_cloids) == set(cloids)

    # 9. EXACTLY-ONCE ACROSS THE RESTART: the same intent, same bar, no order.
    restored_engine = _engine(settings, restored_broker, restored_risk, restored_guard)
    again = _decide(restored_engine, bars)
    assert again.orders_created == 0
    assert again.duplicate_intents == 1
    assert restored_broker.positions == {}

    _emit(
        {
            "name": "cycle",
            "label": LABEL,
            "orders_created": counts.orders_created,
            "fills_opened": broker.extract_state()["fills_opened"],
            "fills_closed": broker.extract_state()["fills_closed"],
            "notional_usdt": notional,
            "entry_price": entry,
            "exit_price": trade.exit_price,
            "exit_reason": trade.exit_reason,
            "gross_pnl_usd": gross,
            "fees_usd": fees_paid,
            "net_pnl_usd": trade.pnl,
            "net_bps": trade.pnl / notional * 10_000.0,
            "gross_bps": gross / notional * 10_000.0,
            "equity_after": broker.equity,
            "equity_identity_error": abs(broker.equity - (EQUITY + trade.pnl)),
            "reconciliation_status": report.status,
            "restored_equity": report.restored_equity,
            "cloids": list(cloids),
            "duplicate_orders_after_restart": again.orders_created,
        }
    )


def test_the_cost_line_of_the_cycle_is_measured_from_the_fees_paid(tmp_path):
    """The cycle carries its own cost line: fees are subtracted, not assumed.

    Two round trips — one stopped out, one at target — so the sign of the result
    is not an artefact of one lucky exit. This is where a PAPER cycle would show
    that a 10 bps round trip on 5 bps/side is a floor, not a detail.
    """
    settings = _settings()
    broker = PaperBroker(equity=EQUITY, slippage_bps=1.0, commission_bps=5.0)
    risk = RiskManager(risk=settings.risk, equity=broker.equity)
    guard = IdempotencyGuard()
    engine = _engine(settings, broker, risk, guard)
    bars = _bars()

    assert _decide(engine, bars).orders_created == 1
    pos = broker.positions[SYMBOL]
    # Stop out on a lower low, then let the next cycle open a second position.
    broker.check_positions_ohlc(
        {SYMBOL: (pos.entry_price, pos.entry_price * 0.999, pos.stop_loss_price * 0.999, pos.stop_loss_price)}
    )
    assert broker.closed_trades[0].exit_reason == "stop_loss"

    # A new bar is a new intent: the previous one stays suppressed, this one is
    # legitimately tradable. Re-sending the same bar would (correctly) be a
    # duplicate, which is what the first test asserts after the restart.
    engine.bump_state_version("position closed")
    next_bars = _bars(n=101)
    assert _decide(engine, next_bars).orders_created == 1
    _close_at_take_profit(broker)
    assert len(broker.closed_trades) == 2

    fees = 0.0
    for trade in broker.closed_trades:
        notional = trade.entry_price * trade.quantity
        gross = (
            (trade.exit_price - trade.entry_price)
            if trade.side == "buy"
            else (trade.entry_price - trade.exit_price)
        ) * trade.quantity
        fees += 2.0 * notional * 5.0 / 10_000.0
        assert trade.pnl == pytest.approx(gross - 2.0 * notional * 5.0 / 10_000.0, rel=1e-9)

    total_net = sum(t.pnl for t in broker.closed_trades)
    assert broker.equity == pytest.approx(EQUITY + total_net, rel=1e-12)
    assert total_net < sum(
        ((t.exit_price - t.entry_price) * (1 if t.side == "buy" else -1)) * t.quantity
        for t in broker.closed_trades
    ), "two round trips must cost more than their gross"

    _emit(
        {
            "name": "cost_line",
            "label": LABEL,
            "round_trips": len(broker.closed_trades),
            "fees_usd": fees,
            "net_pnl_usd": total_net,
            "exit_reasons": [t.exit_reason for t in broker.closed_trades],
            "equity_identity_error": abs(broker.equity - (EQUITY + total_net)),
            "round_trip_cost_bps_floor": 2.0 * 5.0,
        }
    )


def test_a_refused_order_leaves_no_trace_and_reconciles_consistent(tmp_path):
    """Fail closed: no approval, no order, and an empty store is CONSISTENT."""
    settings = _settings()
    broker = PaperBroker(equity=EQUITY)
    risk = RiskManager(risk=settings.risk, equity=broker.equity)
    risk.activate_kill_switch("wp016 test")
    guard = IdempotencyGuard()
    engine = _engine(settings, broker, risk, guard)

    counts = _decide(engine, _bars())

    assert counts.orders_created == 0
    assert broker.positions == {}
    assert broker.closed_trades == []
    assert broker.equity == EQUITY
    assert guard.sent_cloids == set()
    assert any(r["stage"] == "risk" for r in counts.rejections)

    # The broker refuses to size an order that risk never approved.
    from trading_bot.strategies.types import Signal

    with pytest.raises(BrokerOrderError):
        broker.execute_signal(
            Signal(
                symbol=SYMBOL,
                side="buy",
                strategy_name="ema_crossover",
                timeframe="5m",
                confidence=0.5,
                price=100.0,
                metadata={},
            )
        )
    assert broker.positions == {}

    report = StartupReconcilerV4(
        store=PaperStateStore(tmp_path / "empty.json"), broker=broker
    ).reconcile()
    assert report.status == ReconciliationStatusV4.CONSISTENT, report.to_dict()

    _emit(
        {
            "name": "fail_closed",
            "label": LABEL,
            "orders_created": counts.orders_created,
            "reconciliation_status": report.status,
            "equity": broker.equity,
        }
    )
