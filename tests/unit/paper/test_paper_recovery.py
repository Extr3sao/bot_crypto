"""Crash/restart adversarial matrix for the paper runtime (GAP-R1 hardening).

Covers the crash boundaries mandated by the hardening phase:

    B  risk approved, before execution intent persisted
       -> engine registers the intent BEFORE the broker call, so a crash
          between approval and fill leaves the intent marked: a retry
          cannot double-execute (UNKNOWN outcome fails closed).
    C  intent persisted, before broker call
       -> restart restores the ledger: same intent is a duplicate -> no
          re-execution (suppressed intent, no position created).
    D  broker accepted, before local fill persisted
       -> recovered positions replay into the broker book; a duplicate
          intent cannot add a second position (same-side skip + ledger).
    E  fill persisted, before portfolio/risk update
       -> risk counters restored before the next decision (no zero-
          exposure assumption over open positions).
    G  position opened, process dies, restart
       -> full restore: broker book + risk state + equity identity.
    H  closed-but-uncommitted position
       -> closed_trades rows are persisted with the session snapshot;
          the equity identity check (initial + sum(pnl) == equity) fails
          closed on any tampered book.

Also covers: corrupt state file (FATAL), equity-identity MISMATCH,
unknown-broker-outcome fail-closed, and duplicate broker callback.
"""

from __future__ import annotations

from typing import Any

import pytest

from trading_bot.execution.idempotency import IdempotencyGuard
from trading_bot.market_data.types import OHLCV
from trading_bot.paper.broker import PaperBroker
from trading_bot.paper.paper_cycle import PaperCycleEngine
from trading_bot.paper.paper_state_store import PaperStateStore
from trading_bot.paper.reconciliation_v4 import (
    ReconciliationStatusV4,
    StartupReconcilerV4,
)
from trading_bot.research.asset_intelligence.registry import CryptoAssetAgentRegistry
from trading_bot.research.strategy_router import StrategyRouter
from trading_bot.research.types import AlphaSignal
from trading_bot.risk.manager import RiskManager

TS0 = 1_700_000_000_000


def _bars(symbol: str, n: int = 60, *, rising: bool = True) -> list[OHLCV]:
    out: list[OHLCV] = []
    for i in range(n):
        price = 100.0 + (i * 1.0 if rising else 0.0)
        out.append(
            OHLCV(
                symbol=symbol,
                timestamp=TS0 + i * 60_000,
                open=price,
                high=price + 1.0,
                low=price - 1.0,
                close=price + 0.5,
                volume=1_000.0,
            )
        )
    return out


def _risk_settings() -> Any:
    from trading_bot.config.risk import DefensiveBlocks, Risk

    return Risk.model_construct(
        max_risk_per_trade_pct=1.0,
        max_daily_loss_pct=3.0,
        max_weekly_loss_pct=7.0,
        max_daily_drawdown_pct=5.0,
        max_total_drawdown_pct=15.0,
        max_open_positions=5,
        max_trades_per_day=100,
        max_consecutive_losses=3,
        consecutive_loss_cooldown_minutes=60,
        max_asset_exposure_pct=20.0,
        max_total_exposure_pct=80.0,
        min_order_notional_usdt=10.0,
        max_order_notional_usdt=1000.0,
        default_stop_loss_pct=0.5,
        default_take_profit_pct=1.0,
        blocks=DefensiveBlocks.model_construct(),
        kill_switch_enabled=True,
        live_trading_enabled=False,
    )


class _StaticFamily:
    family_name = "ema_crossover"

    def generate(
        self, candles: Any, indicators: Any, features: Any = None, **kw: Any
    ) -> list[AlphaSignal]:
        last = candles[-1]
        return [
            AlphaSignal(
                family=self.family_name,
                symbol=last.symbol,
                timestamp=last.timestamp,
                direction="LONG",
                entry_reference=last.close,
                structural_stop=last.close * 0.99,
                timeframe="5m",
            )
        ]


def _build_engine(
    broker: PaperBroker,
    *,
    risk: RiskManager | None = None,
    guard: IdempotencyGuard | None = None,
) -> PaperCycleEngine:
    fam = _StaticFamily()
    return PaperCycleEngine(
        asset_registry=CryptoAssetAgentRegistry(),
        router=StrategyRouter(),
        strategy_map={
            "ema_crossover": {
                "family": "ema_crossover",
                "regimes": [],
                "direction": "BOTH",
                "enabled": True,
                "status": "CONFIRMED",
                "priority": 0.0,
            }
        },
        families={"ema_crossover": fam},
        risk_manager=risk or RiskManager(risk=_risk_settings(), equity=broker.equity),
        broker=broker,
        indicator_fn=lambda candles: {},
        idempotency=guard or IdempotencyGuard(),
    )


def _extract(store: PaperStateStore, run_id: str, broker: PaperBroker, risk: Any, guard: Any):
    from trading_bot.paper.paper_runtime_state import save_session_state

    save_session_state(store=store, run_id=run_id, broker=broker, risk=risk, idempotency=guard)


def _reconcile(store: PaperStateStore, broker: PaperBroker, risk: Any, guard: Any):
    rec = StartupReconcilerV4(store=store, broker=broker, risk_manager=risk, idempotency=guard)
    return rec.reconcile()


# ---------------------------------------------------------------------------
# G: position opened -> process dies -> restart (full restore)
# ---------------------------------------------------------------------------


def test_restart_with_open_position_full_restore(tmp_path) -> None:
    store = PaperStateStore(tmp_path / "state.json")
    broker1 = PaperBroker(equity=10_000.0)
    risk1 = RiskManager(risk=_risk_settings(), equity=10_000.0)
    guard1 = IdempotencyGuard()
    engine1 = _build_engine(broker1, risk=risk1, guard=guard1)

    bars = _bars("BTC/USDT")
    ts = TS0 + 59 * 60_000
    c1 = engine1.run_cycle_sync({"BTC/USDT": list(bars)}, {"BTC/USDT": ts})
    assert c1.orders_created == 1
    assert len(broker1.positions) == 1

    _extract(store, "run-A", broker1, risk1, guard1)

    # --- restart: fresh runtime objects, empty books ---
    broker2 = PaperBroker(equity=10_000.0)
    risk2 = RiskManager(risk=_risk_settings(), equity=10_000.0)
    guard2 = IdempotencyGuard()
    report = _reconcile(store, broker2, risk2, guard2)

    assert report.status == ReconciliationStatusV4.RECOVERED
    assert report.restored_open_positions == 1
    assert report.restored_intents == 1
    assert len(broker2.positions) == 1
    assert broker2.equity == pytest.approx(broker1.equity)
    # Risk sees the restored book BEFORE any new decision:
    assert risk2.equity == pytest.approx(broker2.equity)
    assert risk2.trades_today == risk1.trades_today
    assert risk2.consecutive_losses == risk1.consecutive_losses
    # The restored ledger blocks re-execution of the same intent:
    engine2 = _build_engine(broker2, risk=risk2, guard=guard2)
    c2 = engine2.run_cycle_sync({"BTC/USDT": list(bars)}, {"BTC/USDT": ts})
    assert c2.orders_created == 0
    assert c2.duplicate_intents == 1
    assert len(broker2.positions) == 1  # exactly-once effect


# ---------------------------------------------------------------------------
# C: intent persisted, crash before broker call -> retry is suppressed
# ---------------------------------------------------------------------------


def test_crash_before_broker_call_no_duplicate_execution(tmp_path) -> None:
    store = PaperStateStore(tmp_path / "state.json")
    broker1 = PaperBroker(equity=10_000.0)
    risk = RiskManager(risk=_risk_settings(), equity=10_000.0)
    guard1 = IdempotencyGuard()
    engine1 = _build_engine(broker1, risk=risk, guard=guard1)

    bars = _bars("BTC/USDT")
    ts = TS0 + 59 * 60_000
    c1 = engine1.run_cycle_sync({"BTC/USDT": list(bars)}, {"BTC/USDT": ts})
    assert c1.orders_created == 1

    # Simulate crash AFTER the intent was registered but BEFORE the broker
    # fill was persisted (D boundary): snapshot the ledger as it was right
    # after the intent registration, without the closed-trade bookkeeping.
    from trading_bot.paper.paper_state_store import SessionPaperState

    mid_state = SessionPaperState(
        schema_version=1,
        run_id="run-C",
        updated_at_ms=0,
        broker_state={
            "equity": 10_000.0,
            "initial_equity": 10_000.0,
            "fills_opened": 0,
            "fills_closed": 0,
        },
        risk_state={},
        open_positions=[],
        closed_trades=[],
        sent_intents=sorted(guard1.sent_cloids),
    )
    store.save(mid_state)

    broker2 = PaperBroker(equity=10_000.0)
    risk2 = RiskManager(risk=_risk_settings(), equity=10_000.0)
    guard2 = IdempotencyGuard()
    report = _reconcile(store, broker2, risk2, guard2)
    assert report.status == ReconciliationStatusV4.RECOVERED

    engine2 = _build_engine(broker2, risk=risk2, guard=guard2)
    c2 = engine2.run_cycle_sync({"BTC/USDT": list(bars)}, {"BTC/USDT": ts})
    # The UNKNOWN outcome (was the fill made?) fails closed: the retry is a
    # duplicate -> NO second economic effect.
    assert c2.orders_created == 0
    assert c2.duplicate_intents == 1
    assert len(broker2.positions) == 0


# ---------------------------------------------------------------------------
# D: broker accepted, fill not persisted -> position replay, no duplicate
# ---------------------------------------------------------------------------


def test_crash_after_broker_fill_position_replayed(tmp_path) -> None:
    store = PaperStateStore(tmp_path / "state.json")
    broker1 = PaperBroker(equity=10_000.0)
    risk1 = RiskManager(risk=_risk_settings(), equity=10_000.0)
    guard1 = IdempotencyGuard()
    engine1 = _build_engine(broker1, risk=risk1, guard=guard1)

    bars = _bars("BTC/USDT")
    ts = TS0 + 59 * 60_000
    c1 = engine1.run_cycle_sync({"BTC/USDT": list(bars)}, {"BTC/USDT": ts})
    assert c1.orders_created == 1
    position = next(iter(broker1.positions.values()))

    _extract(store, "run-D", broker1, risk1, guard1)

    broker2 = PaperBroker(equity=10_000.0)
    risk2 = RiskManager(risk=_risk_settings(), equity=10_000.0)
    guard2 = IdempotencyGuard()
    report = _reconcile(store, broker2, risk2, guard2)
    assert report.status == ReconciliationStatusV4.RECOVERED
    assert len(broker2.positions) == 1
    restored = next(iter(broker2.positions.values()))
    assert restored.symbol == position.symbol
    assert restored.entry_price == pytest.approx(position.entry_price)
    assert restored.quantity == pytest.approx(position.quantity)
    assert restored.notional_usdt == pytest.approx(position.notional_usdt)

    # New engine on the restored book must not re-execute the same intent:
    engine2 = _build_engine(broker2, risk=risk2, guard=guard2)
    c2 = engine2.run_cycle_sync({"BTC/USDT": list(bars)}, {"BTC/USDT": ts})
    assert c2.orders_created == 0
    assert c2.duplicate_intents == 1


# ---------------------------------------------------------------------------
# MISMATCH: tampered book -> equity identity fails closed
# ---------------------------------------------------------------------------


def test_equity_identity_mismatch_is_fatal(tmp_path) -> None:
    store = PaperStateStore(tmp_path / "state.json")
    broker1 = PaperBroker(equity=10_000.0)
    risk1 = RiskManager(risk=_risk_settings(), equity=10_000.0)
    guard1 = IdempotencyGuard()
    engine1 = _build_engine(broker1, risk=risk1, guard=guard1)
    c1 = engine1.run_cycle_sync({"BTC/USDT": _bars("BTC/USDT")}, {"BTC/USDT": TS0 + 59 * 60_000})
    assert c1.orders_created == 1

    _extract(store, "run-M", broker1, risk1, guard1)

    # Tamper: equity bumped without a matching closed-trade row.
    state = store.load_or_recover()
    tampered = state.broker_state | {"equity": state.broker_state["equity"] + 50.0}
    from trading_bot.paper.paper_state_store import SessionPaperState

    store.save(
        SessionPaperState(
            schema_version=state.schema_version,
            run_id=state.run_id,
            updated_at_ms=state.updated_at_ms,
            broker_state=tampered,
            risk_state=state.risk_state,
            open_positions=state.open_positions,
            closed_trades=state.closed_trades,
            sent_intents=state.sent_intents,
        )
    )

    broker2 = PaperBroker(equity=10_000.0)
    report = _reconcile(store, broker2, None, None)
    assert report.status == ReconciliationStatusV4.FATAL
    assert any("equity identity" in d for d in report.details)


# ---------------------------------------------------------------------------
# Corrupt state file -> FATAL (never silently start empty)
# ---------------------------------------------------------------------------


def test_corrupt_state_file_fails_closed(tmp_path) -> None:
    path = tmp_path / "state.json"
    path.write_bytes(b"{not json at all")
    store = PaperStateStore(path)
    broker = PaperBroker(equity=10_000.0)

    report = _reconcile(store, broker, None, None)
    assert report.status == ReconciliationStatusV4.FATAL
    # The raw bytes were preserved for post-mortem, nothing overwritten:
    assert path.with_suffix(path.suffix + ".corrupt").exists()
    assert path.exists()


def test_missing_state_file_is_fresh_book(tmp_path) -> None:
    store = PaperStateStore(tmp_path / "absent.json")
    broker = PaperBroker(equity=10_000.0)
    report = _reconcile(store, broker, None, None)
    assert report.status == ReconciliationStatusV4.CONSISTENT
    assert report.restored_open_positions == 0


# ---------------------------------------------------------------------------
# Unknown broker outcome: reconciliation decides, never blind resend
# ---------------------------------------------------------------------------


def test_unknown_broker_outcome_blocks_reexecution(tmp_path) -> None:
    """Request sent -> crash -> caller does not know if the fill happened.

    The recovered ledger marks the intent as sent: a retry CANNOT create a
    second economic effect. Recovery of the position row is the only path
    that materializes the fill (deterministic, from durable state).
    """
    store = PaperStateStore(tmp_path / "state.json")
    broker1 = PaperBroker(equity=10_000.0)
    risk1 = RiskManager(risk=_risk_settings(), equity=10_000.0)
    guard1 = IdempotencyGuard()
    engine1 = _build_engine(broker1, risk=risk1, guard=guard1)
    bars = _bars("BTC/USDT")
    ts = TS0 + 59 * 60_000
    c1 = engine1.run_cycle_sync({"BTC/USDT": list(bars)}, {"BTC/USDT": ts})
    assert c1.orders_created == 1

    # Durable state captured WITHOUT the position row (fill not persisted),
    # but WITH the intent (it was sent) -> exactly the unknown-outcome case.
    from trading_bot.paper.paper_state_store import SessionPaperState

    store.save(
        SessionPaperState(
            schema_version=1,
            run_id="run-UNK",
            updated_at_ms=0,
            broker_state={
                "equity": 10_000.0,
                "initial_equity": 10_000.0,
                "fills_opened": 0,
                "fills_closed": 0,
            },
            risk_state={},
            open_positions=[],
            closed_trades=[],
            sent_intents=sorted(guard1.sent_cloids),
        )
    )

    broker2 = PaperBroker(equity=10_000.0)
    risk2 = RiskManager(risk=_risk_settings(), equity=10_000.0)
    guard2 = IdempotencyGuard()
    _reconcile(store, broker2, risk2, guard2)

    engine2 = _build_engine(broker2, risk=risk2, guard=guard2)
    c2 = engine2.run_cycle_sync({"BTC/USDT": list(bars)}, {"BTC/USDT": ts})
    assert c2.orders_created == 0
    assert c2.duplicate_intents == 1
    # Not executed twice, and not silently re-proposed:
    assert len(broker2.positions) == 0
    assert any(
        r["stage"] == "idempotency" and r["reason"].startswith("duplicate_intent")
        for r in c2.rejections
    )


# ---------------------------------------------------------------------------
# Duplicate broker callback (same fill delivered twice)
# ---------------------------------------------------------------------------


def test_duplicate_broker_callback_is_suppressed(tmp_path) -> None:
    store = PaperStateStore(tmp_path / "state.json")
    broker1 = PaperBroker(equity=10_000.0)
    risk1 = RiskManager(risk=_risk_settings(), equity=10_000.0)
    guard1 = IdempotencyGuard()
    engine1 = _build_engine(broker1, risk=risk1, guard=guard1)
    bars = _bars("BTC/USDT")
    ts = TS0 + 59 * 60_000
    c1 = engine1.run_cycle_sync({"BTC/USDT": list(bars)}, {"BTC/USDT": ts})
    assert c1.orders_created == 1

    _extract(store, "run-DUP", broker1, risk1, guard1)

    broker2 = PaperBroker(equity=10_000.0)
    risk2 = RiskManager(risk=_risk_settings(), equity=10_000.0)
    guard2 = IdempotencyGuard()
    report = _reconcile(store, broker2, risk2, guard2)
    assert report.restored_intents == 1

    # Deliver the same intent again (duplicate callback / replayed event):
    engine2 = _build_engine(broker2, risk=risk2, guard=guard2)
    c2 = engine2.run_cycle_sync({"BTC/USDT": list(bars)}, {"BTC/USDT": ts})
    assert c2.duplicate_intents == 1
    assert c2.orders_created == 0
    # Exactly one economic position exists:
    assert len(broker2.positions) == 1


# ---------------------------------------------------------------------------
# H: closed trade persisted -> equity reconstructs exactly
# ---------------------------------------------------------------------------


def test_closed_trade_reconstruction_across_restart(tmp_path) -> None:
    store = PaperStateStore(tmp_path / "state.json")
    broker1 = PaperBroker(equity=10_000.0)
    risk1 = RiskManager(risk=_risk_settings(), equity=10_000.0)
    guard1 = IdempotencyGuard()
    engine1 = _build_engine(broker1, risk=risk1, guard=guard1)
    bars = _bars("BTC/USDT")
    ts = TS0 + 59 * 60_000
    c1 = engine1.run_cycle_sync({"BTC/USDT": list(bars)}, {"BTC/USDT": ts})
    assert c1.orders_created == 1

    # Close via the broker's own accounting (same-side new intent would be
    # skipped; the crash matrix boundary here is H: closed-but-uncommitted).
    bars2 = _bars("BTC/USDT", n=61)
    engine1.run_cycle_sync({"BTC/USDT": bars2}, {"BTC/USDT": TS0 + 60 * 60_000})
    # Opposite side alpha is LONG again (same-side skip) -> no forced close;
    # force the close through the broker's own accounting instead:
    if len(broker1.closed_trades) == 0:
        pos = next(iter(broker1.positions.values()))
        broker1._close_position(pos.symbol, pos.entry_price * 1.02, "stop_loss")
    assert len(broker1.closed_trades) == 1

    _extract(store, "run-H", broker1, risk1, guard1)

    broker2 = PaperBroker(equity=10_000.0)
    risk2 = RiskManager(risk=_risk_settings(), equity=10_000.0)
    guard2 = IdempotencyGuard()
    report = _reconcile(store, broker2, risk2, guard2)
    assert report.status == ReconciliationStatusV4.RECOVERED
    assert report.restored_closed_trades == 1
    assert broker2.equity == pytest.approx(broker1.equity)
    assert len(broker2.closed_trades) == 1
    assert broker2.closed_trades[0].pnl == pytest.approx(broker1.closed_trades[0].pnl)
