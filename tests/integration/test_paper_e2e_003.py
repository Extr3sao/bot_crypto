"""PAPER-E2E-003 — deterministic full-chain through the RUNTIME family (RUN-OP-004).

RUN-OP-003 proved the authoritative EMA crossover path is:

    UniverseScanner -> AssetContext -> StrategyRouter
    -> EmaCrossoverFamily.generate -> SignalAdapter -> RiskManager
    -> PaperBroker.execute_signal

This E2E exercises that exact chain with the REAL runtime classes
(including the real ``EmaCrossoverFamily`` — not a stub, and not
``EmaCrossoverStrategy``) on a deterministic rising market.

Distinct from the canonical smoke (flat fake feed, orders MAY be 0): here
a signal is legitimately produced, so the FULL chain must execute:

    FULL_CHAIN_SIGNAL = PASS  (signals_generated > 0)
    RISK_EXECUTED     = PASS  (risk_accepted > 0)
    PAPER_ORDER_CREATED = PASS (orders_created > 0)

Determinism: fixed candle epoch + injected ``now_fn`` (no wall-clock race);
LIVE=false, no credentials, no external exchange.
"""

from __future__ import annotations

import asyncio

from trading_bot.execution.idempotency import IdempotencyGuard
from trading_bot.market_data.types import OHLCV
from trading_bot.paper.broker import PaperBroker
from trading_bot.paper.paper_cycle import PaperCycleEngine
from trading_bot.paper.snapshot_history import FetcherBarReader
from trading_bot.research.asset_intelligence.registry import CryptoAssetAgentRegistry
from trading_bot.research.families.ema_crossover_family import EmaCrossoverFamily
from trading_bot.research.strategy_router import StrategyRouter
from trading_bot.risk.manager import RiskManager

# Past epoch (same pattern as PAPER-E2E-002): the injected ``now_fn`` pins
# the session clock to the newest bar, so ``decision_ts = newest bar`` and
# the router's freshness gate passes by construction (no wall-clock race).
TS0 = 1_700_000_000_000
BAR_MS = 60_000


def _rising_bars(symbol: str, n: int = 100) -> list[OHLCV]:
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


class _RisingSource:
    """Deterministic in-test feed: fresh-ish timestamps + uptrend prices."""

    def __init__(self, bars_by_symbol: dict[str, list[OHLCV]]) -> None:
        self._bars = bars_by_symbol

    async def fetch_recent(self, symbol: str, limit: int = 100) -> list[OHLCV]:
        return list(self._bars.get(symbol, []))[-limit:]

    async def fetch_24h_volume_usdt(self, symbol: str) -> float:
        return 50_000_000.0

    async def fetch_spread_bps(self, symbol: str) -> float:
        return 5.0


def _settings():
    from trading_bot.market_data.fake import build_demo_settings

    return build_demo_settings(
        pairs=[("BTC/USDT", True), ("ETH/USDT", True), ("SOL/USDT", True)],
        mode="paper",
        kill_switch_enabled=True,  # armed = healthy per RiskManager (same as e2e-002)
    )


def _engine(settings, broker: PaperBroker) -> PaperCycleEngine:
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
        # THE RUNTIME-AUTHORITATIVE IMPLEMENTATION — not a stub.
        families={"ema_crossover": EmaCrossoverFamily()},
        risk_manager=RiskManager(risk=settings.risk, equity=broker.equity),
        broker=broker,
        indicator_fn=lambda candles: {},  # family self-computes (real runtime path)
        idempotency=IdempotencyGuard(),
    )


def _runner(settings, broker, engine, source):
    import datetime

    from trading_bot.paper.harness import PaperSessionRunner
    from trading_bot.scanner.mode_filters import build_filter_set_per_mode
    from trading_bot.scanner.scanner import UniverseScanner

    scan_settings = settings.model_copy(
        update={"risk": settings.risk.model_copy(update={"kill_switch_enabled": False})}
    )
    scanner = UniverseScanner(
        source=source,
        registry_per_mode=build_filter_set_per_mode(scan_settings),
        settings=scan_settings,
    )
    decision_ts = TS0 + 99 * BAR_MS  # newest bar
    return PaperSessionRunner(
        scanner=scanner,
        settings=settings,
        broker=broker,
        cycle_engine=engine,
        cycle_history_reader=FetcherBarReader(source),
        now_fn=lambda: datetime.datetime.fromtimestamp(decision_ts / 1000, tz=datetime.UTC),
    )


def test_full_chain_through_runtime_family() -> None:
    settings = _settings()
    broker = PaperBroker(equity=10_000.0)
    source = _RisingSource({s: _rising_bars(s) for s in ("BTC/USDT", "ETH/USDT", "SOL/USDT")})
    runner = _runner(settings, broker, _engine(settings, broker), source)

    result = asyncio.run(runner.run_session())

    assert result.metrics.total_snapshots == 3
    assert result.metrics.active_snapshots == 3
    counts = result.cycle_counts
    assert counts is not None
    # Decision path executed
    assert counts.contexts_built == 3
    assert counts.router_invocations == 3
    assert counts.strategy_invocations == 3
    assert counts.router_no_trade == 0
    # FULL CHAIN: signal -> risk -> paper order (the runtime family produced a LONG)
    assert counts.signals_generated > 0, "family produced no alpha on a rising market"
    assert counts.risk_accepted > 0, "risk did not approve"
    assert counts.orders_created > 0, "paper broker created no order"
    # Hermetic invariants
    assert settings.runtime.mode.value == "paper"
    assert settings.runtime.live_trading_enabled is False


def test_full_chain_rejects_falling_market_via_family() -> None:
    """SHORT path of the runtime family also flows through the full chain."""
    settings = _settings()
    broker = PaperBroker(equity=10_000.0)
    fall = [
        OHLCV(
            symbol=s,
            timestamp=TS0 + i * BAR_MS,
            open=200.0 - i,
            high=200.0 - i + 1.0,
            low=200.0 - i - 1.0,
            close=200.0 - i - 0.5,
            volume=1_000.0,
        )
        for s in ("BTC/USDT",)
        for i in range(100)
    ]
    source = _RisingSource({"BTC/USDT": fall})
    runner = _runner(settings, broker, _engine(settings, broker), source)
    result = asyncio.run(runner.run_session())
    counts = result.cycle_counts
    assert counts is not None
    assert counts.strategy_invocations == 1
    assert counts.signals_generated > 0
    assert counts.orders_created > 0
