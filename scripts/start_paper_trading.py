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
import time
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
        choices=["fake", "ccxt", "public"],
        default="fake",
        help=(
            "Data provider: fake (demo, no credentials), ccxt (read-only venue), "
            "or public (read-only public REST klines; no exchange session)"
        ),
    )
    parser.add_argument("--config-dir", default="config", help="Config directory (default config)")
    parser.add_argument(
        "--state-path",
        default=None,
        help=(
            "Durable paper-state file (default data/storage/paper_state.json; "
            "PAPER_STATE_PATH env overrides for tests)"
        ),
    )
    parser.add_argument(
        "--ledger",
        default=None,
        help=(
            "Admission ledger (default config/strategy_admission.json; "
            "ADMISSION_LEDGER_PATH env overrides for tests)"
        ),
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help=(
            "Rotate any existing durable state before starting (explicit fresh "
            "book). Default is fail-closed recovery of the persisted book."
        ),
    )
    parser.add_argument(
        "--burnin-events",
        default=None,
        help="Append one JSONL event per session to this path (burn-in observability).",
    )
    parser.add_argument(
        "--data-audit",
        default=None,
        help=(
            "Append one JSONL record per public-data request (provider, endpoint, "
            "timestamp, authenticated=false). Only used by --provider public."
        ),
    )
    parser.add_argument(
        "--run-dir",
        default=None,
        help=(
            "Operator-stop directory (default data/storage/paper; PAPER_RUN_DIR "
            "overrides for tests). The live kill-switch CLI writes <run-dir>/KILL_SWITCH."
        ),
    )
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
    settings: Settings,
    provider: str,
    *,
    timeframe: str | None = None,
    data_audit_path: Path | str | None = None,
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
    elif provider == "public":
        from trading_bot.market_data.public_rest import PublicRestKlineSource

        resolved_timeframe = timeframe or (
            settings.universe.timeframes[0] if settings.universe.timeframes else "5m"
        )
        source = PublicRestKlineSource(
            timeframe=resolved_timeframe,
            audit_path=data_audit_path,
        )
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


def _default_state_path() -> Path:
    import os

    env_path = os.environ.get("PAPER_STATE_PATH", "")
    if env_path:
        return Path(env_path)
    return Path("data/storage/paper_state.json")


def _default_ledger_path() -> Path:
    """Committed admission ledger: the launcher's authority (DEF-AUTO-4)."""
    import os

    env_path = os.environ.get("ADMISSION_LEDGER_PATH", "")
    if env_path:
        return Path(env_path)
    return Path(__file__).resolve().parents[1] / "config" / "strategy_admission.json"


def _default_run_dir() -> Path:
    """Where the paper process watches for ``KILL_SWITCH``.

    ``data/storage`` is local runtime state (gitignored), not an evidence tree;
    the marker is an operator control, not a report. ``PAPER_RUN_DIR`` exists so
    tests and supervisors can give each process a private control directory.
    """
    import os

    env_path = os.environ.get("PAPER_RUN_DIR", "")
    if env_path:
        return Path(env_path)
    return Path("data/storage/paper")


def _rotate_state(path: Path) -> None:
    """Explicit fresh-book request: back up the existing state, never delete.

    The previous book stays on disk as ``<name>.<ts>.bak`` so no economic
    history is silently destroyed ( destruction requires a human action).
    """
    if not path.exists():
        return
    stamp = int(time.time_ns() // 1_000_000)
    backup = path.with_name(f"{path.name}.{stamp}.bak")
    path.replace(backup)
    print(f"[startup] --fresh: previous state rotated to {backup}")


def build_cycle_engine(
    settings: Settings,
    broker: PaperBroker,
    *,
    assets: Sequence[str] = ("BTC", "ETH", "SOL"),
    timeframe: str = "5m",
    ledger_path: Path | str | None = None,
    run_dir: Path | str | None = None,
    hot_stop: Any | None = None,
) -> PaperCycleEngine:
    """Compose the canonical decision cycle (CP-PO-002, FASE 7B-8B).

    Uses ONLY canonical components: CryptoAssetAgentRegistry (context),
    StrategyRouter (routing - the single router), the six committed
    AlphaFamilies (generation), signal_adapter (conversion),
    CandidatePortfolio (consolidation), RiskManager (risk) and the shared
    PaperBroker (execution). No strategy logic lives here.

    DEF-AUTO-4: this used to hand the router a map that declared every family
    ``CONFIRMED``, which made the router's confirmation gate a formality and
    let a family that research had rejected trade paper money. The map is now
    built from the admission ledger, and the router keeps ``require_confirmed``
    on, so the gate and the ledger say the same thing. The ledger is read fail
    closed: a missing or unreadable ledger stops the launcher.
    """
    from trading_bot.autonomous.admission_ledger import AdmissionLedger
    from trading_bot.autonomous.decision import process_kill_switch
    from trading_bot.autonomous.hot_stop import HotStopGate
    from trading_bot.autonomous.strategy_state import StrategyRegistry
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
    from trading_bot.research.router_gates import RouterGates
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

    if hot_stop is None and run_dir is not None:
        hot_stop = HotStopGate(kill_switch=process_kill_switch(), run_dir=run_dir)

    ledger = AdmissionLedger.load(ledger_path or _default_ledger_path())
    registry = StrategyRegistry.from_ledger(ledger, assets=list(assets))
    for line in registry.describe(timeframe):
        print(line)
    strategy_map = registry.strategy_map(timeframe)

    return PaperCycleEngine(
        asset_registry=CryptoAssetAgentRegistry(),
        # §38/DEF-AUTO-3 — freshness budgeted from the timeframe, not a constant.
        router=StrategyRouter(gates=RouterGates(timeframe=timeframe)),
        strategy_map=strategy_map,
        families=families,
        risk_manager=RiskManager(risk=settings.risk, equity=broker.equity),
        broker=broker,
        indicator_fn=_default_indicators,
        idempotency=IdempotencyGuard(),
        # WP-EDGE-017/P0.4: the four declared defensive blocks are evaluated on the
        # real paper entrypoint, fail closed. The policy comes from
        # config/risk.yaml through the runtime's own loader; nothing is re-typed
        # and the weekend flag is not changed here.
        defensive_blocks=settings.risk.blocks,
        # G-4 — the paper route consults the SAME operator stop as the autonomous
        # runtime. It is built before the engine, so a marker left by an earlier
        # process is adopted before any cycle can run.
        hot_stop=hot_stop,
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

    from trading_bot.paper.durable_broker import DurablePaperBroker
    from trading_bot.paper.paper_runtime_state import save_session_state
    from trading_bot.paper.paper_state_store import PaperStateStore
    from trading_bot.paper.reconciliation_v4 import StartupReconcilerV4
    from trading_bot.paper.snapshot_history import FetcherBarReader

    state_path = Path(args.state_path) if args.state_path else _default_state_path()
    if args.fresh:
        _rotate_state(state_path)

    run_dir = Path(args.run_dir) if args.run_dir else _default_run_dir()
    run_dir.mkdir(parents=True, exist_ok=True)

    data_audit_path = Path(args.data_audit) if args.data_audit else None
    scanner_factory, data_source = build_scanner_factory(
        settings,
        args.provider,
        timeframe=args.timeframe,
        data_audit_path=data_audit_path,
    )
    broker = DurablePaperBroker(equity=args.balance)
    cycle_engine = build_cycle_engine(
        settings,
        broker,
        assets=assets,
        timeframe=args.timeframe,
        ledger_path=Path(args.ledger) if args.ledger else _default_ledger_path(),
        run_dir=run_dir,
    )
    store = PaperStateStore(state_path)
    broker.attach_durability(
        store=store,
        risk=cycle_engine.risk_manager,
        idempotency=cycle_engine.idempotency,
        run_id="paper-cli",
    )
    reconciler = StartupReconcilerV4(
        store=store,
        broker=broker,
        risk_manager=cycle_engine.risk_manager,
        idempotency=cycle_engine.idempotency,
    )
    report = reconciler.reconcile()
    print("[startup] reconciliation=" + report.status)
    if report.status in ("RECOVERED", "FATAL", "MISMATCH"):
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2, default=str))
    if report.status == "FATAL":
        print(
            "Refusing to start: durable paper state is unreadable/corrupt "
            "(fail closed). Inspect the .corrupt backup and resolve manually.",
            file=sys.stderr,
        )
        return 1

    # The reconciler adopted the durable order ledger; bind the runtime id so
    # every boundary write from here on names the restored book.
    broker.attach_durability(
        store=store,
        risk=cycle_engine.risk_manager,
        idempotency=cycle_engine.idempotency,
        run_id=report.restored_run_id or "paper-cli",
    )

    async def _run_with_persistence() -> dict[str, Any]:
        orchestrator = PaperOrchestrator(
            settings=settings,
            scanner_factory=scanner_factory,
            broker=broker,
            max_sessions=args.max_cycles,
            interval_seconds=args.interval,
            cycle_engine=cycle_engine,
            cycle_history_reader=FetcherBarReader(data_source, timeframe=args.timeframe),
            state_store=store,
            burnin_events_path=args.burnin_events,
        )
        try:
            await orchestrator.run()
        finally:
            # Final durable snapshot (belt and braces: the runner already
            # persists after every session; this covers interval-timer deaths).
            save_session_state(
                store=store,
                run_id=report.restored_run_id or "",
                broker=broker,
                risk=cycle_engine.risk_manager,
                idempotency=cycle_engine.idempotency,
            )
            print("[startup] paper state saved to " + str(store.path))
        return orchestrator.status()

    print(
        f"Starting PAPER trading loop — assets={assets} timeframe={args.timeframe} "
        f"interval={args.interval}s provider={args.provider} balance={args.balance}"
    )
    status = await _run_with_persistence()
    print("Paper trading loop stopped.")
    print(json.dumps(status, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
