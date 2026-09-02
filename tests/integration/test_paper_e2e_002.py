"""PAPER-E2E-002 — canonical cycle through the real runner (CP-PO-002).

Proves the full decision path on deterministic fake market data through
``PaperSessionRunner`` (the per-session authority):

    scanner → MarketSnapshot → PIT history (same source)
    → AssetContext → StrategyRouter → AlphaFamily (deterministic driver)
    → SignalAdapter → CandidatePortfolio → RiskManager → PaperBroker
    → reconcile (SL/TP) → PaperExecutionSummary → report

The alpha family here is a DETERMINISTIC TEST DRIVER (a test double for
the committed AlphaFamilies): it maps the seeded OHLCV shape to
AlphaSignals exactly like a real family would (last-bar entry, structural
stop, features). Market shape — not fabricated prices — drives direction.

Negative matrix (each proves orders_created == 0):
    N1 stale data (no history at decision ts)   → context error
    N2 provider unavailable (reader raises)     → history error, 0 orders
    N4 router failure                            → router error
    N6 duplicate intent across sessions          → exactly 1 execution total
    N8 risk rejection (daily limit exhausted)    → 0 orders
    N9 kill switch engaged                       → 0 orders

Note: engine-level unit matrix lives in tests/unit/paper/test_paper_cycle.py.
"""

from __future__ import annotations

import asyncio
from typing import Any

from trading_bot.execution.idempotency import IdempotencyGuard
from trading_bot.market_data.fake import FakeMarketDataSource
from trading_bot.market_data.types import OHLCV
from trading_bot.paper.broker import PaperBroker
from trading_bot.paper.paper_cycle import PaperCycleEngine
from trading_bot.paper.snapshot_history import FetcherBarReader
from trading_bot.research.asset_intelligence.registry import CryptoAssetAgentRegistry
from trading_bot.research.strategy_router import StrategyRouter
from trading_bot.research.types import AlphaSignal
from trading_bot.risk.manager import RiskManager

TS0 = 1_700_000_000_000
BAR_MS = 60_000


def _bars(symbol: str, n: int = 100, *, rising: bool = True, offset_bars: int = 0) -> list[OHLCV]:
    """100 bars = the scanner's fetch window, so snapshot last_price and the
    engine's decision bar agree (same newest bar, same timestamp)."""
    out: list[OHLCV] = []
    for i in range(n):
        price = 100.0 + (i * 1.0 if rising else 0.0)
        out.append(
            OHLCV(
                symbol=symbol,
                timestamp=TS0 + (offset_bars + i) * BAR_MS,
                open=price,
                high=price + 1.0,
                low=price - 1.0,
                close=price + 0.5,
                volume=1_000.0,
            )
        )
    return out


class _ShapeFamily:
    """Deterministic family: LONG on a rising window, SHORT on falling."""

    family_name = "ema_crossover"

    def generate(
        self, candles: list[OHLCV], indicators: Any, features: Any = None, **kw: Any
    ) -> list[AlphaSignal]:
        if len(candles) < 30:
            return []
        rising = candles[-1].close > candles[0].close
        last = candles[-1]
        stop = last.close * (0.99 if rising else 1.01)
        return [
            AlphaSignal(
                family=self.family_name,
                symbol=last.symbol,
                timestamp=last.timestamp,
                direction="LONG" if rising else "SHORT",
                entry_reference=last.close,
                structural_stop=max(stop, 0.01),
                timeframe="5m",
            )
        ]


def _settings(kill_switch_enabled: bool = True):
    """Armed settings (kill_switch_enabled=True = healthy, per RiskManager)."""
    from trading_bot.market_data.fake import build_demo_settings

    return build_demo_settings(
        pairs=[("BTC/USDT", True), ("ETH/USDT", True), ("SOL/USDT", True)],
        mode="paper",
        kill_switch_enabled=kill_switch_enabled,
    )


def _engine(
    settings,
    broker: PaperBroker,
    *,
    idempotency: IdempotencyGuard | None = None,
    risk: RiskManager | None = None,
) -> PaperCycleEngine:
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
            }
        },
        families={"ema_crossover": _ShapeFamily()},
        risk_manager=risk or RiskManager(risk=settings.risk, equity=broker.equity),
        broker=broker,
        indicator_fn=lambda candles: {},
        idempotency=idempotency or IdempotencyGuard(),
    )


def _runner(settings, broker, engine, source, session_ts: int):
    from trading_bot.paper.harness import PaperSessionRunner
    from trading_bot.scanner.mode_filters import build_filter_set_per_mode
    from trading_bot.scanner.scanner import UniverseScanner

    # Pre-existing scanner/risk divergence (documented tech debt): the
    # scanner aborts every iteration when risk.kill_switch_enabled=True,
    # while RiskManager needs True to be ARMED and approve. The canonical
    # loop must scan, so the scanner receives a scan-safe VIEW of settings;
    # the risk engine keeps the armed flag. (Same composition is used in
    # scripts/start_paper_trading.py.)
    scan_settings = settings.model_copy(
        update={"risk": settings.risk.model_copy(update={"kill_switch_enabled": False})}
    )
    scanner = UniverseScanner(
        source=source,
        registry_per_mode=build_filter_set_per_mode(scan_settings),
        settings=scan_settings,
    )
    return PaperSessionRunner(
        scanner=scanner,
        settings=settings,
        broker=broker,
        cycle_engine=engine,
        cycle_history_reader=FetcherBarReader(source),
        now_fn=lambda: __import__("datetime").datetime.fromtimestamp(
            session_ts / 1000, tz=__import__("datetime").timezone.utc
        ),
    )


# ---------------------------------------------------------------------------
# GATE-L5-01/02/03/04/05/06/07/09: deterministic trade path through runner
# ---------------------------------------------------------------------------


def test_e2e_cycle_opens_position_on_rising_market() -> None:
    """Rising BTC window → context → router → alpha → risk → paper fill."""
    settings = _settings()
    source = FakeMarketDataSource(
        volume_by_symbol={"BTC/USDT": 50e6, "ETH/USDT": 30e6, "SOL/USDT": 8e6},
        spread_by_symbol={"BTC/USDT": 5.0, "ETH/USDT": 8.0, "SOL/USDT": 12.0},
    )
    for sym in ("BTC/USDT", "ETH/USDT", "SOL/USDT"):
        source.ohlcv_by_symbol[sym] = _bars(sym, 100, rising=True)

    broker = PaperBroker(equity=10_000.0)
    engine = _engine(settings, broker)
    session_ts = TS0 + 99 * BAR_MS + 5_000
    runner = _runner(settings, broker, engine, source, session_ts)

    result = asyncio.run(runner.run_session())

    counts = result.cycle_counts
    assert counts is not None
    # All three assets routed; rising windows produced alphas.
    assert counts.contexts_built == 3
    assert counts.context_errors == 0
    assert counts.risk_accepted >= 1
    assert counts.orders_created >= 1
    # PaperBroker-only execution: the fill lives in the broker.
    assert len(broker.positions) >= 1
    assert broker.equity < 10_000.0 + 1e-9  # commission charged, nothing fabricated
    # Position lifecycle stage 1: opened with risk-approved SL/TP.
    pos = next(iter(broker.positions.values()))
    assert pos.stop_loss_pct > 0 and pos.take_profit_pct > 0


def test_e2e_cycle_reconciles_stop_loss_to_close() -> None:
    """Open in cycle 1, then price collapse → reconcile closes with loss."""
    settings = _settings()
    source = FakeMarketDataSource(
        volume_by_symbol={"BTC/USDT": 50e6, "ETH/USDT": 30e6, "SOL/USDT": 8e6},
        spread_by_symbol={"BTC/USDT": 5.0, "ETH/USDT": 8.0, "SOL/USDT": 12.0},
    )
    for sym in ("BTC/USDT", "ETH/USDT", "SOL/USDT"):
        source.ohlcv_by_symbol[sym] = _bars(sym, 100, rising=True)

    broker = PaperBroker(equity=10_000.0)
    engine = _engine(settings, broker)
    ts1 = TS0 + 99 * BAR_MS + 5_000
    runner = _runner(settings, broker, engine, source, ts1)
    asyncio.run(runner.run_session())
    assert len(broker.positions) >= 1

    # Cycle 2: falling window (new timestamps, offset 100) → snapshot price
    # collapses below the longs' stop → reconcile closes them (SL hit).
    for sym in ("BTC/USDT", "ETH/USDT", "SOL/USDT"):
        source.ohlcv_by_symbol[sym] = _bars(sym, 100, rising=False, offset_bars=100)
    ts2 = TS0 + 199 * BAR_MS + 5_000
    runner2 = _runner(settings, broker, engine, source, ts2)
    result2 = asyncio.run(runner2.run_session())

    # Position lifecycle stage 2: closed with realized PnL recorded.
    assert result2.execution_summary is not None
    assert len(result2.execution_summary.closed_trades) >= 1
    assert result2.execution_summary.realized_pnl != 0.0
    opened_total = engine.idempotency.active_count
    assert opened_total >= 1
    assert len(result2.execution_summary.closed_trades) + len(broker.positions) >= 1  # nothing lost


def test_e2e_duplicate_intent_across_sessions_executes_once() -> None:
    """GATE-L5-08: same market state twice → exactly one execution total."""
    settings = _settings()
    source = FakeMarketDataSource(
        volume_by_symbol={"BTC/USDT": 50e6, "ETH/USDT": 30e6, "SOL/USDT": 8e6},
        spread_by_symbol={"BTC/USDT": 5.0, "ETH/USDT": 8.0, "SOL/USDT": 12.0},
    )
    for sym in ("BTC/USDT", "ETH/USDT", "SOL/USDT"):
        source.ohlcv_by_symbol[sym] = _bars(sym, 100, rising=True)

    broker = PaperBroker(equity=10_000.0)
    guard = IdempotencyGuard()
    engine = _engine(settings, broker, idempotency=guard)
    ts = TS0 + 99 * BAR_MS + 5_000

    r1 = asyncio.run(_runner(settings, broker, engine, source, ts).run_session())
    r2 = asyncio.run(_runner(settings, broker, engine, source, ts).run_session())

    assert r1.cycle_counts.orders_created >= 1
    assert r2.cycle_counts.orders_created == 0
    assert r2.cycle_counts.duplicate_intents >= 1
    assert guard.active_count == r1.cycle_counts.orders_created


# ---------------------------------------------------------------------------
# Negative matrix through the runner (fail closed, orders_created == 0)
# ---------------------------------------------------------------------------


def test_n1_missing_history_zero_orders() -> None:
    """Missing OHLCV at the decision time → context errors, 0 orders.

    (True staleness cannot occur by construction on the runner path:
    decision_ts = snapshot ts = newest bar. Engine-level staleness/short
    windows are covered in tests/unit/paper/test_paper_cycle.py and by the
    scanner's insufficient_history rejection.)
    """
    settings = _settings()
    source = FakeMarketDataSource(
        volume_by_symbol={"BTC/USDT": 50e6, "ETH/USDT": 30e6, "SOL/USDT": 8e6},
        spread_by_symbol={"BTC/USDT": 5.0, "ETH/USDT": 8.0, "SOL/USDT": 12.0},
    )
    for sym in ("BTC/USDT", "ETH/USDT", "SOL/USDT"):
        source.ohlcv_by_symbol[sym] = _bars(sym, 100, rising=True)

    class EmptyReader:
        async def get_ohlcv(self, *_a: object, **_k: object) -> list[OHLCV]:
            return []

    broker = PaperBroker(equity=10_000.0)
    engine = _engine(settings, broker)
    session_ts = TS0 + 119 * BAR_MS + 5_000
    runner = _runner(settings, broker, engine, source, session_ts)
    runner._history_reader = EmptyReader()  # type: ignore[assignment]
    result = asyncio.run(runner.run_session())

    counts = result.cycle_counts
    assert counts is not None
    assert counts.orders_created == 0
    assert counts.context_errors == 3  # one per active asset, each observed


def test_n2_provider_unavailable_zero_orders() -> None:
    """History reader raises → no orders, failures observable.

    Bars are seeded so the scanner marks pairs ACTIVE; the decision-cycle
    history provider then fails for every asset — the canonical loop must
    still record each failure and create zero orders.
    """
    settings = _settings()
    source = FakeMarketDataSource(
        volume_by_symbol={"BTC/USDT": 50e6, "ETH/USDT": 30e6, "SOL/USDT": 8e6},
        spread_by_symbol={"BTC/USDT": 5.0, "ETH/USDT": 8.0, "SOL/USDT": 12.0},
    )
    for sym in ("BTC/USDT", "ETH/USDT", "SOL/USDT"):
        source.ohlcv_by_symbol[sym] = _bars(sym, 100, rising=True)

    class BoomReader:
        async def get_ohlcv(self, *_a: Any, **_k: Any) -> list[OHLCV]:
            raise ConnectionError("provider down")

    broker = PaperBroker(equity=10_000.0)
    engine = _engine(settings, broker)
    session_ts = TS0 + 99 * BAR_MS + 5_000
    runner = _runner(settings, broker, engine, source, session_ts)
    runner._history_reader = BoomReader()  # type: ignore[assignment]
    result = asyncio.run(runner.run_session())

    counts = result.cycle_counts
    assert counts is not None
    assert counts.orders_created == 0
    # No history → every active asset recorded as a context failure.
    assert counts.context_errors == 3


def test_n4_router_failure_zero_orders() -> None:
    """Router exception → no orders for that asset (fail closed)."""
    settings = _settings()
    source = FakeMarketDataSource(
        volume_by_symbol={"BTC/USDT": 50e6, "ETH/USDT": 30e6, "SOL/USDT": 8e6},
        spread_by_symbol={"BTC/USDT": 5.0, "ETH/USDT": 8.0, "SOL/USDT": 12.0},
    )
    for sym in ("BTC/USDT", "ETH/USDT", "SOL/USDT"):
        source.ohlcv_by_symbol[sym] = _bars(sym, 100, rising=True)

    class BoomRouter:
        def route(self, *_a: Any, **_k: Any) -> Any:
            raise RuntimeError("router exploded")

    broker = PaperBroker(equity=10_000.0)
    engine = _engine(settings, broker)
    engine._router = BoomRouter()
    session_ts = TS0 + 99 * BAR_MS + 5_000
    result = asyncio.run(_runner(settings, broker, engine, source, session_ts).run_session())

    counts = result.cycle_counts
    assert counts is not None
    assert counts.orders_created == 0
    assert counts.router_errors == 3


def test_n6_duplicate_intent_across_sessions() -> None:
    """Duplicate detection across sessions (see GATE-L5-08 test above)."""
    settings = _settings()
    source = FakeMarketDataSource(
        volume_by_symbol={"BTC/USDT": 50e6},
        spread_by_symbol={"BTC/USDT": 5.0},
    )
    source.ohlcv_by_symbol["BTC/USDT"] = _bars("BTC/USDT", 100, rising=True)
    broker = PaperBroker(equity=10_000.0)
    guard = IdempotencyGuard()
    engine = _engine(settings, broker, idempotency=guard)
    ts = TS0 + 99 * BAR_MS + 5_000
    r1 = asyncio.run(_runner(settings, broker, engine, source, ts).run_session())
    r2 = asyncio.run(_runner(settings, broker, engine, source, ts).run_session())
    assert r1.cycle_counts.orders_created == 1
    assert r2.cycle_counts.orders_created == 0
    assert guard.active_count == 1


def test_n8_risk_rejection_zero_orders() -> None:
    """Daily trade limit exhausted → every signal rejected, 0 orders."""
    settings = _settings()
    source = FakeMarketDataSource(
        volume_by_symbol={"BTC/USDT": 50e6, "ETH/USDT": 30e6, "SOL/USDT": 8e6},
        spread_by_symbol={"BTC/USDT": 5.0, "ETH/USDT": 8.0, "SOL/USDT": 12.0},
    )
    for sym in ("BTC/USDT", "ETH/USDT", "SOL/USDT"):
        source.ohlcv_by_symbol[sym] = _bars(sym, 100, rising=True)

    broker = PaperBroker(equity=10_000.0)
    risk = RiskManager(risk=settings.risk, equity=broker.equity)
    risk.trades_today = settings.risk.max_trades_per_day
    engine = _engine(settings, broker, risk=risk)
    session_ts = TS0 + 99 * BAR_MS + 5_000
    result = asyncio.run(_runner(settings, broker, engine, source, session_ts).run_session())

    counts = result.cycle_counts
    assert counts is not None
    assert counts.orders_created == 0
    assert counts.risk_rejected >= 1


def test_n9_kill_switch_engaged_zero_orders() -> None:
    """Kill switch engaged → check_signal blocks everything, 0 orders."""
    settings = _settings()
    source = FakeMarketDataSource(
        volume_by_symbol={"BTC/USDT": 50e6, "ETH/USDT": 30e6, "SOL/USDT": 8e6},
        spread_by_symbol={"BTC/USDT": 5.0, "ETH/USDT": 8.0, "SOL/USDT": 12.0},
    )
    for sym in ("BTC/USDT", "ETH/USDT", "SOL/USDT"):
        source.ohlcv_by_symbol[sym] = _bars(sym, 100, rising=True)

    broker = PaperBroker(equity=10_000.0)
    risk = RiskManager(risk=settings.risk, equity=broker.equity)
    risk.activate_kill_switch("e2e")
    engine = _engine(settings, broker, risk=risk)
    session_ts = TS0 + 99 * BAR_MS + 5_000
    result = asyncio.run(_runner(settings, broker, engine, source, session_ts).run_session())

    counts = result.cycle_counts
    assert counts is not None
    assert counts.orders_created == 0
    assert counts.risk_rejected >= 1
    assert any("kill" in r["reason"].lower() for r in counts.rejections if r["stage"] == "risk")
