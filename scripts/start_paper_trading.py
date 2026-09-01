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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading_bot.config.runtime import TradingMode
from trading_bot.config.settings import load_settings
from trading_bot.paper.paper_orchestrator import PaperOrchestrator


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start the paper trading loop (PAPER only, never LIVE).")
    parser.add_argument("--assets", default="BTC,ETH,SOL", help="Comma-separated assets (default BTC,ETH,SOL)")
    parser.add_argument("--timeframe", default="5m", help="Candle timeframe (default 5m)")
    parser.add_argument("--interval", type=float, default=60.0, help="Seconds between cycles (default 60)")
    parser.add_argument("--balance", type=float, default=10_000.0, help="Paper balance in USDT (default 10000)")
    parser.add_argument("--max-cycles", type=int, default=None, help="Stop after N cycles (default: run forever)")
    parser.add_argument("--provider", choices=["fake", "ccxt"], default="fake",
                        help="Data provider: fake (demo, no credentials) or ccxt (read-only)")
    parser.add_argument("--config-dir", default="config", help="Config directory (default config)")
    return parser.parse_args()


def build_settings(args: argparse.Namespace):
    """Load settings and restrict the universe to the requested assets.

    Assets are given as base codes (BTC, ETH, ...); they are mapped to
    '<ASSET>/USDT' pairs so the scanner only visits the requested assets.
    """
    from trading_bot.config.universe import PairSpec

    settings = load_settings(config_dir=args.config_dir)
    pairs = [PairSpec(symbol=f"{asset}/USDT", enabled=True) for asset in args.assets]
    universe = settings.universe.model_copy(update={"pairs": pairs, "timeframes": [args.timeframe]})
    return settings.model_copy(update={"universe": universe})


def build_scanner_factory(settings, provider: str):
    """Return a zero-argument factory producing a fresh UniverseScanner per session."""
    if provider == "fake":
        from trading_bot.app import _build_demo_scanner

        return lambda: _build_demo_scanner(mode="paper")
    from trading_bot.market_data.wiring import resolve_scanner_source
    from trading_bot.scanner.mode_filters import build_filter_set_per_mode
    from trading_bot.scanner.scanner import UniverseScanner

    def factory():
        source = resolve_scanner_source(settings, session_id="paper-orchestrator")
        return UniverseScanner(
            source=source,
            registry_per_mode=build_filter_set_per_mode(settings),
            settings=settings,
        )

    return factory


async def main() -> int:
    args = parse_args()

    assets = [a.strip().upper() for a in args.assets.split(",") if a.strip()]
    if not assets:
        print("No assets configured — nothing to do.", file=sys.stderr)
        return 1

    settings = build_settings(args)

    # Hard PAPER guarantee: this entrypoint never runs LIVE, regardless of YAML/env.
    if settings.runtime.mode is not TradingMode.PAPER:
        print(
            f"Refusing to start: runtime.mode={settings.runtime.mode.value!r}. "
            "start_paper_trading only runs in PAPER mode.",
            file=sys.stderr,
        )
        return 1

    from trading_bot.paper.broker import PaperBroker

    scanner_factory = build_scanner_factory(settings, args.provider)
    broker = PaperBroker(equity=args.balance)

    orchestrator = PaperOrchestrator(
        settings=settings,
        scanner_factory=scanner_factory,
        broker=broker,
        max_sessions=args.max_cycles,
        interval_seconds=args.interval,
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
