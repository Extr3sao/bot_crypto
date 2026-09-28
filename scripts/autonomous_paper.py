"""Autonomous PAPER/SHADOW entrypoint (AUTONOMOUS-PAPER-RUNTIME-V1).

    uv run python scripts/autonomous_paper.py --cycles 3 --assets BTC,ETH,SOL

One-shot is ``--cycles 1``; a bounded loop is any ``--cycles N`` with
``--interval``. There is no infinite loop and no code path that can reach
LIVE: the script refuses to start unless ``runtime.mode`` is ``paper`` and the
only execution boundary it composes is ``PaperBroker``.

Composition (canonical components only):

    settings → scanner source (read-only market data) → UniverseScanner
             → FetcherBarReader (PIT history) → CryptoAssetAgentRegistry
             → StrategyRouter + committed AlphaFamilies
             → autonomous decision layer (proposal → reviews → verifier →
               decision engine → deterministic Risk) → PaperBroker
             → DecisionTrace / Outcome / StrategyPerformance

Nothing here writes to an exchange, holds a private key or moves capital.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.config.runtime import TradingMode  # noqa: E402
from trading_bot.config.settings import Settings, load_settings  # noqa: E402

DEFAULT_RUN_ROOT = Path("reports/autonomous-paper")
DEFAULT_STATE_PATH = Path("data/storage/autonomous_paper_state.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", default="BTC,ETH,SOL")
    parser.add_argument("--timeframe", default="5m")
    parser.add_argument("--cycles", type=int, default=1, help="1 = ONE_SHOT")
    parser.add_argument(
        "--interval",
        type=float,
        default=0.0,
        help="Seconds between cycles (bounded loop). 0 = back-to-back.",
    )
    parser.add_argument("--balance", type=float, default=10_000.0)
    parser.add_argument(
        "--horizon-minutes",
        type=float,
        default=5.0,
        help="Pre-registered forecast horizon for proposals (default: one 5m bar).",
    )
    parser.add_argument("--size-usd", type=float, default=1_000.0)
    parser.add_argument("--lookback-bars", type=int, default=120)
    parser.add_argument("--config-dir", default="config/realdata")
    parser.add_argument("--provider", choices=["ccxt", "fake"], default="ccxt")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--run-root", default=str(DEFAULT_RUN_ROOT))
    parser.add_argument("--state-path", default=str(DEFAULT_STATE_PATH))
    parser.add_argument(
        "--ledger",
        default="config/strategy_admission.json",
        help="Admission ledger (fail closed when missing).",
    )
    parser.add_argument(
        "--no-shadow",
        action="store_true",
        help="Disable SHADOW evaluation (research observations) for this run.",
    )
    return parser.parse_args()


def build_settings(args: argparse.Namespace, assets: list[str]) -> Settings:
    from trading_bot.config.universe import PairSpec

    settings = load_settings(config_dir=args.config_dir)
    pairs = [PairSpec(symbol=f"{asset}/USDT", enabled=True) for asset in assets]
    universe = settings.universe.model_copy(
        update={"pairs": pairs, "timeframes": [args.timeframe]}
    )
    return settings.model_copy(update={"universe": universe})


def parse_assets(raw: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for token in raw.split(","):
        normalized = token.strip().upper()
        if normalized and normalized not in seen:
            seen.add(normalized)
            out.append(normalized)
    if not out:
        raise ValueError("--assets requires at least one non-empty asset code")
    return out


def build_strategy_map(ledger: Any, timeframe: str) -> dict[str, dict[str, Any]]:
    """One strategy spec per ledger entry measured on this timeframe.

    The key is the ledger key (``<family>@<timeframe>``) so the trace, the
    proposal and the admission verdict all refer to the same identity; the
    ``family`` field points at the executable AlphaFamily.
    """
    return {
        strategy_id: {
            "family": entry.family,
            "regimes": [],
            "direction": "BOTH",
            "enabled": True,
            "status": "CONFIRMED" if entry.admitted_for_paper else "RESEARCH_ONLY",
            "priority": 0.0,
        }
        for strategy_id, entry in ledger.entries_for_timeframe(timeframe).items()
    }


def build_scanner_factory(settings: Settings, provider: str) -> Any:
    from trading_bot.scanner.mode_filters import build_filter_set_per_mode
    from trading_bot.scanner.scanner import UniverseScanner

    if provider == "fake":
        from trading_bot.market_data.fake import build_demo_fetcher

        source: Any = build_demo_fetcher(settings)
    else:
        from trading_bot.market_data.wiring import resolve_scanner_source

        source = resolve_scanner_source(settings, session_id="autonomous-paper")

    def factory() -> Any:
        scan_settings = settings.model_copy(
            update={"risk": settings.risk.model_copy(update={"kill_switch_enabled": False})}
        )
        return UniverseScanner(
            source=source,
            registry_per_mode=build_filter_set_per_mode(scan_settings),
            settings=scan_settings,
        )

    return factory, source


async def main() -> int:
    args = parse_args()
    try:
        assets = parse_assets(args.assets)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.cycles < 1:
        print("--cycles must be >= 1", file=sys.stderr)
        return 1

    settings = build_settings(args, assets)
    if settings.runtime.mode is not TradingMode.PAPER:
        print(
            f"Refusing to start: runtime.mode={settings.runtime.mode.value!r} "
            "(autonomous_paper only runs PAPER).",
            file=sys.stderr,
        )
        return 1

    from trading_bot.autonomous.admission_ledger import AdmissionLedger
    from trading_bot.autonomous.reporting import write_run_report
    from trading_bot.autonomous.runtime import AutonomousPaperRuntime
    from trading_bot.paper.broker import PaperBroker
    from trading_bot.paper.paper_state_store import PaperStateStore
    from trading_bot.paper.reconciliation_v4 import StartupReconcilerV4
    from trading_bot.paper.snapshot_history import FetcherBarReader
    from trading_bot.research.families import (
        BreakoutFamily,
        EmaCrossoverFamily,
        MeanReversionFamily,
        MomentumFamily,
        TrendFamily,
        VolatilityFamily,
    )
    from trading_bot.risk.manager import RiskManager

    ledger = AdmissionLedger.load(REPO_ROOT / args.ledger)
    print(f"[admission] ledger={ledger.source_path}")
    print(f"[admission] strategies={ledger.strategy_ids()}")
    print(f"[admission] paper candidates={ledger.paper_candidates() or 'NONE'}")

    run_id = args.run_id or f"autonomous-paper-{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}"
    run_dir = REPO_ROOT / args.run_root / run_id

    scanner_factory, data_source = build_scanner_factory(settings, args.provider)
    reader = FetcherBarReader(data_source, timeframe=args.timeframe)
    broker = PaperBroker(equity=args.balance)
    risk = RiskManager(risk=settings.risk, equity=args.balance)

    from trading_bot.execution.idempotency import IdempotencyGuard

    idempotency = IdempotencyGuard()
    store = PaperStateStore(REPO_ROOT / args.state_path)
    reconciler = StartupReconcilerV4(
        store=store, broker=broker, risk_manager=risk, idempotency=idempotency
    )
    report = reconciler.reconcile()
    print(f"[startup] reconciliation={report.status}")

    families = {
        "ema_crossover": EmaCrossoverFamily(),
        "momentum": MomentumFamily(),
        "breakout": BreakoutFamily(),
        "trend": TrendFamily(),
        "mean_reversion": MeanReversionFamily(),
        "volatility": VolatilityFamily(),
    }
    runtime = AutonomousPaperRuntime(
        settings=settings,
        scanner_factory=scanner_factory,
        history_reader=reader,
        broker=broker,
        risk_manager=risk,
        families=families,
        strategy_map=build_strategy_map(ledger, args.timeframe),
        ledger=ledger,
        run_dir=run_dir,
        assets=assets,
        timeframe=args.timeframe,
        horizon_minutes=args.horizon_minutes,
        size_usd=args.size_usd,
        lookback_bars=args.lookback_bars,
        shadow_evaluation_enabled=not args.no_shadow,
        environment=f"{args.provider}:{settings.runtime.exchange_id or 'unset'}",
        idempotency=idempotency,
    )

    print(
        f"[run] {run_id} cycles={args.cycles} interval={args.interval}s "
        f"assets={assets} timeframe={args.timeframe} config={args.config_dir}"
    )
    print(f"[run] agents={[c['agent_id'] for c in runtime.agent_capabilities()]}")
    summary = None
    try:
        summary = await runtime.run(cycles=args.cycles, interval_seconds=args.interval, run_id=run_id)
    finally:
        try:
            from trading_bot.paper.paper_runtime_state import save_session_state

            save_session_state(
                store=store, run_id=run_id, broker=broker, risk=risk, idempotency=idempotency
            )
            print(f"[run] paper state saved to {store.path}")
        except Exception as exc:  # never hide the run result behind a save error
            print(f"[run] state save failed: {type(exc).__name__}: {exc}", file=sys.stderr)
    if summary is None:
        return 1

    md_path, json_path = write_run_report(summary, run_dir)
    print(json.dumps(summary.totals(), indent=2))
    print(f"[run] report: {md_path}")
    print(f"[run] report: {json_path}")
    print(f"[run] traces: {runtime.trace_store.trace_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
