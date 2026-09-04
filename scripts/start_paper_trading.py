"""start_paper_trading — the single entrypoint for the paper trading loop (FASE 6).

Usage:
    uv run python scripts/start_paper_trading.py [--assets BTC,ETH,SOL]
        [--timeframe 5m] [--interval 60] [--balance 10000]
        [--max-cycles N] [--provider fake|ccxt]

Defaults to PAPER mode with read-only market data. There is no code path
here that can enable LIVE: the orchestrator only composes PaperBroker,
which never touches an exchange, and the script refuses to start unless
runtime.mode is 'paper'.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading_bot.config.runtime import TradingMode
from trading_bot.config.settings import Settings, load_settings
from trading_bot.paper.paper_orchestrator import PaperOrchestrator

if TYPE_CHECKING:
    from trading_bot.market_data.types import OHLCV
    from trading_bot.paper.broker import PaperBroker
    from trading_bot.paper.paper_cycle import PaperCycleEngine
    from trading_bot.scanner.protocols import MarketDataSourceProtocol
    from trading_bot.scanner.scanner import UniverseScanner


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Start the paper trading loop (PAPER only, never LIVE)."
    )
    parser.add_argument(
        "--assets", default="BTC,ETH,SOL", help="Comma-separated assets (default BTC,ETH,SOL)"
    )
    parser.add_argument("--timeframe", default="5m", help="Candle timeframe (default 5m)")
    parser.add_argument(
        "--interval", type=float, default=60.0, help="Seconds between cycles (default 60)"
    )
    parser.add_argument(
        "--balance", type=float, default=10_000.0, help="Paper balance in USDT (default 10000)"
    )
    parser.add_argument(
        "--max-cycles", type=int, default=None, help="Stop after N cycles (default: run forever)"
    )
    parser.add_argument(
        "--provider",
        choices=["fake", "ccxt"],
        default="fake",
        help="Data provider: fake (demo, no credentials) or ccxt (read-only)",
    )
    parser.add_argument("--config-dir", default="config", help="Config directory (default config)")
    return parser.parse_args()


def parse_assets(raw: str) -> list[str]:
    """Normalize the ``--assets`` CLI value into an ordered, de-duplicated list.

    Invariant (DEF-OP-003-ENTRYPOINT-ASSETS): the CLI text is parsed into a
    normalized asset list EXACTLY ONCE, at the boundary. Downstream code
    iterates ASSETS (a list), never the raw string, so per-character
    splitting ("BTC,ETH,SOL" -> B,T,C,...) is impossible.

    - strips and upper-cases every token;
    - drops empty tokens and de-duplicates (order-preserving);
    - raises on whitespace-only / empty input.
    """
    seen: set[str] = set()
    out: list[str] = []
    for token in raw.split(","):
        normalized = token.strip().upper()
        if not normalized:
            continue
        if normalized not in seen:
            seen.add(normalized)
            out.append(normalized)
    if not out:
        raise ValueError("--assets requires at least one non-empty asset code")
    return out


def build_settings(args: argparse.Namespace, assets: Sequence[str]) -> Settings:
    """Load settings and restrict the universe to the requested assets.

    Assets are given as base codes (BTC, ETH, ...); they are mapped to
    '<ASSET>/USDT' pairs so the scanner only visits the requested assets.
    ``assets`` MUST be the normalized list produced by ``parse_assets``
    (never the raw CLI string).
    """
    from trading_bot.config.universe import PairSpec

    settings = load_settings(config_dir=args.config_dir)
    pairs = [PairSpec(symbol=f"{asset}/USDT", enabled=True) for asset in assets]
    universe = settings.universe.model_copy(update={"pairs": pairs, "timeframes": [args.timeframe]})
    return settings.model_copy(update={"universe": universe})


def build_scanner_factory(
    settings: Settings, provider: str
) -> tuple[Callable[[], UniverseScanner], MarketDataSourceProtocol]:
    """Return (scanner_factory, data_source) for the requested provider.

    The data source is exposed so the paper decision cycle can read PIT
    history through the SAME market-data path the scanner uses (one
    provider, one quota, no duplicate connections).
    """
    from trading_bot.scanner.mode_filters import build_filter_set_per_mode
    from trading_bot.scanner.scanner import UniverseScanner

    if provider == "fake":
        from trading_bot.market_data.fake import build_demo_fetcher

        source: MarketDataSourceProtocol = build_demo_fetcher(settings)
    else:
        from trading_bot.market_data.wiring import resolve_scanner_source

        source = resolve_scanner_source(settings, session_id="paper-orchestrator")

    def factory() -> UniverseScanner:
        # Scanner receives a scan-safe VIEW: the scanner interprets
        # risk.kill_switch_enabled=True as "engaged" and would abort every
        # iteration (pre-existing RF-4 semantics, documented tech debt).
        # The risk engine keeps the armed flag for approval decisions.
        scan_settings = settings.model_copy(
            update={"risk": settings.risk.model_copy(update={"kill_switch_enabled": False})}
        )
        return UniverseScanner(
            source=source,
            registry_per_mode=build_filter_set_per_mode(scan_settings),
            settings=scan_settings,
        )

    return factory, source


def _default_indicators(candles: Sequence[OHLCV]) -> dict[str, Any]:
    """Canonical indicator precompute handed to family.generate()."""
    from trading_bot.indicators.builtin import AtrIndicator, EmaIndicator, RsiIndicator

    out = {}
    try:
        out["ema_fast"] = EmaIndicator().compute(candles, {"period": 9})
        out["ema_slow"] = EmaIndicator().compute(candles, {"period": 21})
        out["rsi"] = RsiIndicator().compute(candles, {"period": 14})
        out["atr"] = AtrIndicator().compute(candles, {"period": 14})
    except Exception:
        return {}  # insufficient history → families fail closed
    return out


def build_cycle_engine(settings: Settings, broker: PaperBroker) -> PaperCycleEngine:
    """Compose the canonical decision cycle (CP-PO-002, FASE 7B-8B).
    Uses ONLY canonical components: CryptoAssetAgentRegistry (context),
    StrategyRouter (routing - the single router), the six committed
    AlphaFamilies (generation), signal_adapter (conversion),
    CandidatePortfolio (consolidation), RiskManager (risk) and the shared
    PaperBroker (execution). No strategy logic lives here.
    """
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

    # Default paper map: one preregistered entry per canonical family.
    # Deterministic (dict order = score tie-break; EMA baseline first).
    # Regime list empty = eligible in any regime (router base score).
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
        router=StrategyRouter(),
        strategy_map=strategy_map,
        families=families,
        risk_manager=RiskManager(risk=settings.risk, equity=broker.equity),
        broker=broker,
        indicator_fn=_default_indicators,
        idempotency=IdempotencyGuard(),
    )


async def main() -> int:
    args = parse_args()

    try:
        assets = parse_assets(args.assets)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    settings = build_settings(args, assets)

    # Hard PAPER guarantee: this entrypoint never runs LIVE, regardless of YAML/env.
    if settings.runtime.mode is not TradingMode.PAPER:
        print(
            f"Refusing to start: runtime.mode={settings.runtime.mode.value!r}. "
            "start_paper_trading only runs in PAPER mode.",
            file=sys.stderr,
        )
        return 1

    from trading_bot.paper.broker import PaperBroker
    from trading_bot.paper.snapshot_history import FetcherBarReader

    scanner_factory, data_source = build_scanner_factory(settings, args.provider)
    broker = PaperBroker(equity=args.balance)
    cycle_engine = build_cycle_engine(settings, broker)

    orchestrator = PaperOrchestrator(
        settings=settings,
        scanner_factory=scanner_factory,
        broker=broker,
        max_sessions=args.max_cycles,
        interval_seconds=args.interval,
        cycle_engine=cycle_engine,
        cycle_history_reader=FetcherBarReader(data_source),
    )

    print(
        f"Starting PAPER trading loop — assets={assets} timeframe={args.timeframe} "
        f"interval={args.interval}s provider={args.provider} balance={args.balance}"
    )
    await orchestrator.run()
    print("Paper trading loop stopped.")
    print(json.dumps(orchestrator.status(), ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
