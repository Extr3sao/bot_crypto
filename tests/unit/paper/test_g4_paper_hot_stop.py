"""G-4 — the paper cycle must consult the runtime stop before it trades.

The defect this file reproduces is not theoretical. ``scripts/start_paper_trading.py``
composes ``PaperCycleEngine`` and ``PaperBroker``; before G-4 the engine had no
operator-stop boundary at all, so a ``KILL_SWITCH`` marker written by the real
``trading-bot kill-switch`` CLI was ignored and the next cycle opened a paper
position. These tests pin the boundary, the positive control and the fact that
a stop still lets a reduction flatten the book.

The gate is injected with a fresh ``KillSwitch`` per test. Production wires the
process switch in ``scripts/start_paper_trading.py``; using the process singleton
here would make these tests depend on the order of unrelated autonomous tests.
"""

from __future__ import annotations

from typing import Any

from trading_bot.autonomous.hot_stop import HotStopGate
from trading_bot.domain.enums.kill_switch import KillSwitchAction, KillSwitchState
from trading_bot.execution.idempotency import IdempotencyGuard
from trading_bot.market_data.types import OHLCV
from trading_bot.paper.broker import PaperBroker
from trading_bot.paper.kill_switch_v2 import KillSwitch
from trading_bot.paper.paper_cycle import PaperCycleEngine
from trading_bot.research.asset_intelligence.registry import CryptoAssetAgentRegistry
from trading_bot.research.strategy_router import StrategyRouter
from trading_bot.research.types import AlphaSignal
from trading_bot.risk.manager import RiskManager

TS0 = 1_700_000_000_000
SYMBOL = "BTC/USDT"


def _bars(n: int = 60) -> list[OHLCV]:
    return [
        OHLCV(
            symbol=SYMBOL,
            timestamp=TS0 + i * 60_000,
            open=100.0 + i,
            high=101.0 + i,
            low=99.0 + i,
            close=100.5 + i,
            volume=1_000.0,
        )
        for i in range(n)
    ]


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


class _DirectionFamily:
    family_name = "ema_crossover"

    def __init__(self, direction: str = "LONG") -> None:
        self.direction = direction

    def generate(
        self, candles: Any, indicators: Any, features: Any = None, **kw: Any
    ) -> list[AlphaSignal]:
        last = candles[-1]
        stop = last.close * (0.99 if self.direction == "LONG" else 1.01)
        return [
            AlphaSignal(
                family=self.family_name,
                symbol=last.symbol,
                timestamp=last.timestamp,
                direction=self.direction,
                entry_reference=last.close,
                structural_stop=stop,
                timeframe="5m",
            )
        ]


class _CountingBroker(PaperBroker):
    def __init__(self, equity: float = 10_000.0) -> None:
        super().__init__(equity=equity)
        self.execute_calls = 0
        self.close_calls = 0

    def execute_signal(self, signal: Any) -> Any:
        self.execute_calls += 1
        return super().execute_signal(signal)

    def close_position(self, *args: Any, **kwargs: Any) -> Any:
        self.close_calls += 1
        return super().close_position(*args, **kwargs)


def _engine(
    *,
    broker: _CountingBroker,
    family: _DirectionFamily | None = None,
    gate: HotStopGate | None = None,
) -> PaperCycleEngine:
    fam = family or _DirectionFamily()
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
                "priority": 0.0,
            }
        },
        families={"ema_crossover": fam},
        risk_manager=RiskManager(risk=_risk_settings(), equity=broker.equity),
        broker=broker,
        indicator_fn=lambda candles: {},
        idempotency=IdempotencyGuard(),
        hot_stop=gate,
    )


def _gate(tmp_path: Any, *, marker: bool = False) -> HotStopGate:
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    if marker:
        (run_dir / "KILL_SWITCH").write_text("operator stop\n", encoding="utf-8")
    return HotStopGate(kill_switch=KillSwitch(), run_dir=run_dir)


def _cycle(engine: PaperCycleEngine) -> Any:
    return engine.run_cycle_sync({SYMBOL: _bars()}, {SYMBOL: TS0 + 59 * 60_000})


def test_a_marker_blocks_the_paper_entry_at_the_broker(tmp_path: Any) -> None:
    """BEFORE G-4: one order and one broker call with the marker present."""
    broker = _CountingBroker()
    gate = _gate(tmp_path, marker=True)
    counts = _cycle(_engine(broker=broker, gate=gate))

    assert gate.engaged is True
    assert broker.execute_calls == 0, "the broker was reached while the stop was engaged"
    assert counts.orders_created == 0
    assert counts.hot_stop_blocked == 1
    assert counts.rejections[-1]["stage"] == "hot_stop"


def test_the_clean_boundary_still_trades(tmp_path: Any) -> None:
    """Positive control: without a marker the legitimate paper path is unchanged."""
    broker = _CountingBroker()
    gate = _gate(tmp_path, marker=False)
    counts = _cycle(_engine(broker=broker, gate=gate))

    assert gate.engaged is False
    assert broker.execute_calls == 1
    assert counts.orders_created == 1
    assert counts.hot_stop_blocked == 0
    assert counts.rejections == []


def test_the_process_authority_blocks_a_paper_entry(tmp_path: Any) -> None:
    """The boot-time process switch is authority even without a marker."""
    switch = KillSwitch()
    switch.activate(KillSwitchAction.USER, target=KillSwitchState.HALTED)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    gate = HotStopGate(kill_switch=switch, run_dir=run_dir)

    broker = _CountingBroker()
    counts = _cycle(_engine(broker=broker, gate=gate))

    assert broker.execute_calls == 0
    assert counts.orders_created == 0
    assert counts.hot_stop_blocked == 1


def test_a_marker_written_while_the_engine_is_alive_blocks_the_next_entry(tmp_path: Any) -> None:
    """The boundary polls the file; it is not a constructor-only decision."""
    broker = _CountingBroker()
    gate = _gate(tmp_path, marker=False)
    engine = _engine(broker=broker, gate=gate)

    # The constructor saw no marker. The operator writes one before the first
    # dispatch, exactly the window a constructor-only check would miss.
    (tmp_path / "run" / "KILL_SWITCH").write_text("operator stop\n", encoding="utf-8")
    counts = _cycle(engine)

    assert gate.engaged is True
    assert broker.execute_calls == 0, "the dispatch after the marker reached the broker"
    assert counts.orders_created == 0
    assert counts.hot_stop_blocked == 1


def test_a_stop_does_not_trap_a_reduction(tmp_path: Any) -> None:
    """A stop halts new risk; it must not make the book impossible to flatten."""
    broker = _CountingBroker()
    gate = _gate(tmp_path, marker=False)
    family = _DirectionFamily("LONG")
    engine = _engine(broker=broker, family=family, gate=gate)
    assert _cycle(engine).orders_created == 1

    family.direction = "SHORT"
    engine.bump_state_version("opposite_signal")
    (tmp_path / "run" / "KILL_SWITCH").write_text("operator stop\n", encoding="utf-8")
    counts = _cycle(engine)

    assert broker.close_calls == 1, "a reduction was trapped by the stop"
    assert broker.execute_calls == 1, "an entry was opened while stopped"
    assert counts.exits_closed == 1
    assert counts.orders_created == 0
    assert counts.hot_stop_blocked == 0


def test_the_paper_launcher_wires_the_gate_to_the_engine(tmp_path: Any) -> None:
    """The route that exists, not just the engine API, carries the authority."""
    from scripts.start_paper_trading import build_cycle_engine
    from trading_bot.market_data.fake import build_demo_settings

    settings = build_demo_settings(
        pairs=[("BTC/USDT", True)], mode="paper", kill_switch_enabled=True
    )
    broker = PaperBroker(equity=10_000.0)
    run_dir = tmp_path / "paper-run"
    run_dir.mkdir()
    engine = build_cycle_engine(
        settings,
        broker,
        assets=["BTC"],
        ledger_path="reports/edge-recovery/runs/WP-EDGE-00-smoke-fixture/fixture_ledger.json",
        run_dir=run_dir,
    )

    assert engine.hot_stop is not None
    assert engine.hot_stop.control_path == run_dir / "KILL_SWITCH"


def test_the_stop_decision_is_published_in_the_cycle_counters(tmp_path: Any) -> None:
    broker = _CountingBroker()
    counts = _cycle(_engine(broker=broker, gate=_gate(tmp_path, marker=True)))
    payload = counts.to_dict()
    assert payload["hot_stop_blocked"] == 1
    assert payload["rejections"][-1]["stage"] == "hot_stop"


def test_the_gate_is_optional_for_embedding_callers(tmp_path: Any) -> None:
    """``None`` keeps the engine usable as an embedding API; the launcher wires it."""
    del tmp_path
    broker = _CountingBroker()
    counts = _cycle(_engine(broker=broker, gate=None))
    assert counts.orders_created == 1
    assert broker.execute_calls == 1


def test_a_marker_written_after_risk_approval_still_blocks_the_dispatch(
    tmp_path: Any, monkeypatch: Any
) -> None:
    """The boundary is after risk: approval is not permission to dispatch."""
    broker = _CountingBroker()
    gate = _gate(tmp_path, marker=False)
    engine = _engine(broker=broker, gate=gate)
    original = engine._risk.check_signal

    def approve_and_stop(signal: Any) -> Any:
        verdict = original(signal)
        (tmp_path / "run" / "KILL_SWITCH").write_text(
            "operator stop during risk\n", encoding="utf-8"
        )
        return verdict

    monkeypatch.setattr(engine._risk, "check_signal", approve_and_stop)
    counts = _cycle(engine)

    assert broker.execute_calls == 0
    assert counts.risk_accepted == 1
    assert counts.orders_created == 0
    assert counts.hot_stop_blocked == 1
    assert broker.positions == {}
    assert broker.equity == 10_000.0


def test_an_unreadable_marker_blocks_instead_of_authorising(tmp_path: Any) -> None:
    """A directory in place of the file is not absence; fail closed."""
    broker = _CountingBroker()
    gate = _gate(tmp_path, marker=False)
    (tmp_path / "run" / "KILL_SWITCH").mkdir()
    engine = _engine(broker=broker, gate=gate)

    counts = _cycle(engine)

    assert gate.engaged is True
    assert broker.execute_calls == 0
    assert counts.orders_created == 0
    assert counts.hot_stop_blocked == 1


def test_a_poll_exception_blocks_instead_of_authorising(tmp_path: Any, monkeypatch: Any) -> None:
    broker = _CountingBroker()
    gate = _gate(tmp_path, marker=False)
    engine = _engine(broker=broker, gate=gate)

    def broken_poll(**kwargs: Any) -> bool:
        raise OSError("control path vanished")

    monkeypatch.setattr(gate, "poll", broken_poll)
    counts = _cycle(engine)

    assert broker.execute_calls == 0
    assert counts.orders_created == 0
    assert counts.hot_stop_blocked == 1


def test_the_boundary_rechecks_after_the_precheck(tmp_path: Any, monkeypatch: Any) -> None:
    """Defence in depth: a marker that appears after the precheck still blocks."""
    broker = _CountingBroker()
    gate = _gate(tmp_path, marker=False)
    engine = _engine(broker=broker, gate=gate)
    calls = {"poll": 0}

    def late_poll(**kwargs: Any) -> bool:
        calls["poll"] += 1
        if calls["poll"] == 1:
            return False
        gate.engage("marker appeared after the precheck")
        return True

    monkeypatch.setattr(gate, "poll", late_poll)
    counts = _cycle(engine)

    assert calls["poll"] >= 2, "the dispatch boundary did not re-check the gate"
    assert gate.engaged is True
    assert broker.execute_calls == 0
    assert counts.orders_created == 0
    assert counts.hot_stop_blocked == 1
