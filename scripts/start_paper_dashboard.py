"""Launch the local PAPER runtime and its read-only dashboard.

``--observer-only`` starts only the local HTTP/SSE projection. It does not
attach to another process: dashboard state remains empty until this process
publishes events.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading_bot.config.runtime import TradingMode
from trading_bot.config.settings import load_settings

if TYPE_CHECKING:
    from trading_bot.config.settings import Settings
    from trading_bot.market_data.types import OHLCV
    from trading_bot.paper.broker import PaperBroker
    from trading_bot.paper_dashboard.events import DashboardEventBus
    from trading_bot.paper_dashboard.projection import DashboardStore
    from trading_bot.paper_dashboard.server import PaperDashboardServer
    from trading_bot.scanner.protocols import MarketDataSourceProtocol
    from trading_bot.scanner.scanner import UniverseScanner


DASHBOARD_REFRESH_SECONDS = 2.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start PAPER trading + read-only dashboard.")
    parser.add_argument("--assets", default="BTC,ETH,SOL")
    parser.add_argument("--timeframe", default="5m")
    parser.add_argument("--interval", type=float, default=60.0)
    parser.add_argument("--balance", type=float, default=10_000.0)
    parser.add_argument("--max-cycles", type=int, default=None)
    parser.add_argument("--provider", choices=["fake", "ccxt"], default="fake")
    parser.add_argument("--config-dir", default="config")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--observer-only",
        "--no-trading",
        dest="no_trading",
        action="store_true",
        help="Serve a local projection without starting trading; does not attach to another process",
    )
    return parser.parse_args()


def build_settings(args: argparse.Namespace) -> Settings:
    from trading_bot.config.universe import PairSpec

    settings = load_settings(config_dir=args.config_dir)
    assets = [asset.strip().upper() for asset in str(args.assets).split(",") if asset.strip()]
    pairs = [PairSpec(symbol=f"{asset}/USDT", enabled=True) for asset in assets]
    universe = settings.universe.model_copy(update={"pairs": pairs, "timeframes": [args.timeframe]})
    return settings.model_copy(update={"universe": universe})


def build_scanner_factory(
    settings: Settings, provider: str
) -> tuple[Callable[[], UniverseScanner], MarketDataSourceProtocol]:
    from trading_bot.scanner.mode_filters import build_filter_set_per_mode
    from trading_bot.scanner.scanner import UniverseScanner

    if provider == "fake":
        from trading_bot.market_data.fake import build_demo_fetcher

        source: MarketDataSourceProtocol = build_demo_fetcher(settings)
    else:
        from trading_bot.market_data.wiring import resolve_scanner_source

        source = resolve_scanner_source(settings, session_id="paper-dashboard")

    def factory() -> UniverseScanner:
        scan_settings = settings.model_copy(
            update={"risk": settings.risk.model_copy(update={"kill_switch_enabled": False})}
        )
        return UniverseScanner(
            source=source,
            registry_per_mode=build_filter_set_per_mode(scan_settings),
            settings=scan_settings,
        )

    return factory, source


def _default_indicators(candles: list[OHLCV]) -> dict[str, Any]:
    from trading_bot.indicators.builtin import AtrIndicator, EmaIndicator, RsiIndicator

    try:
        return {
            "ema_fast": EmaIndicator().compute(candles, {"period": 9}),
            "ema_slow": EmaIndicator().compute(candles, {"period": 21}),
            "rsi": RsiIndicator().compute(candles, {"period": 14}),
            "atr": AtrIndicator().compute(candles, {"period": 14}),
        }
    except Exception:
        return {}


def build_cycle_engine(
    settings: Settings,
    broker: PaperBroker,
    router: Any = None,
    indicator_fn: Callable[[list[OHLCV]], dict[str, Any]] | None = None,
) -> Any:
    from trading_bot.execution.idempotency import IdempotencyGuard
    from trading_bot.paper.paper_cycle import PaperCycleEngine
    from trading_bot.research.asset_intelligence.registry import CryptoAssetAgentRegistry
    from trading_bot.research.families import (
        BreakoutFamily,
        EmaCrossoverFamily,
        MeanReversionFamily,
        MomentumFamily,
        TrendFamily,
        VolatilityFamily,
    )
    from trading_bot.research.strategy_router import StrategyRouter
    from trading_bot.risk.manager import RiskManager

    family_classes = {
        "ema_crossover": EmaCrossoverFamily,
        "momentum": MomentumFamily,
        "breakout": BreakoutFamily,
        "trend": TrendFamily,
        "mean_reversion": MeanReversionFamily,
        "volatility": VolatilityFamily,
    }
    families = {name: cls() for name, cls in family_classes.items()}
    strategy_map = {
        name: {
            "family": name,
            "regimes": [],
            "direction": "BOTH",
            "enabled": True,
            "status": "CONFIRMED",
            "priority": 0.0,
        }
        for name in family_classes
    }
    return PaperCycleEngine(
        asset_registry=CryptoAssetAgentRegistry(),
        router=router or StrategyRouter(),
        strategy_map=strategy_map,
        families=families,
        risk_manager=RiskManager(risk=settings.risk, equity=broker.equity),
        broker=broker,
        indicator_fn=indicator_fn or _default_indicators,
        idempotency=IdempotencyGuard(),
    )


async def _run_all(
    args: argparse.Namespace,
    settings: Settings,
    store: DashboardStore,
    bus: DashboardEventBus,
    server: PaperDashboardServer,
) -> int:
    from trading_bot.paper.broker import PaperBroker
    from trading_bot.paper.paper_orchestrator import PaperOrchestrator
    from trading_bot.paper.snapshot_history import FetcherBarReader
    from trading_bot.paper_dashboard.taps import ObservedBroker, ObservedEngine, ObservedRouter
    from trading_bot.research.strategy_router import StrategyRouter

    broker = PaperBroker(equity=args.balance)
    observed_broker = ObservedBroker(broker, bus)
    observed_router = ObservedRouter(StrategyRouter(), bus)
    observed_engine = ObservedEngine(
        build_cycle_engine(settings, cast(PaperBroker, observed_broker), router=observed_router),
        bus,
    )
    scanner_factory, data_source = build_scanner_factory(settings, args.provider)
    orchestrator = PaperOrchestrator(
        settings=settings,
        scanner_factory=scanner_factory,
        broker=cast(PaperBroker, observed_broker),
        max_sessions=args.max_cycles,
        interval_seconds=args.interval,
        cycle_engine=observed_engine,
        cycle_history_reader=FetcherBarReader(data_source),
    )

    server.set_orchestrator(orchestrator)
    server.set_broker(observed_broker)
    stop = asyncio.Event()

    async def refresh_prices() -> None:
        while not stop.is_set():
            try:
                prices = {}
                for pair in settings.universe.pairs:
                    if pair.enabled:
                        candles = await data_source.fetch_recent(pair.symbol, limit=1)
                        if candles:
                            prices[pair.symbol] = float(candles[-1].close)
                if prices:
                    store.update_prices(prices)
            except Exception:
                pass
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=DASHBOARD_REFRESH_SECONDS)

    price_task = asyncio.create_task(refresh_prices())
    try:
        await orchestrator.run()
    finally:
        stop.set()
        price_task.cancel()
        print(json.dumps(orchestrator.status(), ensure_ascii=False, indent=2, default=str))
    return 0


def main() -> int:
    args = parse_args()
    settings = build_settings(args)
    if settings.runtime.mode is not TradingMode.PAPER:
        print(
            f"Refusing to start: runtime.mode={settings.runtime.mode.value!r}; PAPER only.",
            file=sys.stderr,
        )
        return 1
    from trading_bot.paper_dashboard.events import DashboardEventBus
    from trading_bot.paper_dashboard.projection import DashboardStore
    from trading_bot.paper_dashboard.wiring import (
        DASHBOARD_HOST,
        build_dashboard,
        validate_paper_mode,
    )

    validate_paper_mode(settings)
    store, bus = DashboardStore(), DashboardEventBus()
    bus.add_listener(store.handle_event)
    server = build_dashboard(
        settings=settings, store=store, bus=bus, host=DASHBOARD_HOST, port=args.port
    )
    try:
        if args.no_trading:
            print(
                "[paper-dashboard] observer-only: local projection only; no process attachment; state remains empty"
            )
            while True:
                time.sleep(3600)
        return asyncio.run(_run_all(args, settings, store, bus, server))
    except KeyboardInterrupt:
        return 0
    finally:
        server.stop()


if __name__ == "__main__":
    raise SystemExit(main())
