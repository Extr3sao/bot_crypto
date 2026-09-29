"""Autonomous PAPER/SHADOW entrypoint (AUTONOMOUS-PAPER-RUNTIME-V1).

    uv run python scripts/autonomous_paper.py --cycles 3 --assets BTC,ETH,SOL
    uv run python scripts/autonomous_paper.py --continuous --interval 60

One-shot is ``--cycles 1``; a bounded loop is any ``--cycles N`` with
``--interval``; ``--continuous`` runs until stopped. There is no code path that
can reach LIVE: the script refuses to start unless ``runtime.mode`` is
``paper``, the only execution boundary it composes is ``PaperBroker``, and the
strategy vocabulary it consumes has no live state at all.

Composition (canonical components only):

    settings → scanner source (read-only market data) → UniverseScanner
             → FetcherBarReader (PIT history) → CryptoAssetAgentRegistry
             → StrategyRegistry (lifecycle states, DEF-AUTO-4)
             → StrategyRouter + committed AlphaFamilies
             → autonomous decision layer (proposal → reviews → verifier →
               decision engine → deterministic Risk) → PaperBroker
             → DecisionTrace / Outcome / StrategyPerformance
             → heartbeat + PAPER_DAILY_REPORT + RUN_REPORT

Continuous operation adds three things and changes nothing about a cycle:
a heartbeat written per cycle, a daily report regenerated on a cadence, and a
stop that flushes state instead of killing the process (§13-§15, §51).

Nothing here writes to an exchange, holds a private key or moves capital.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.config.runtime import TradingMode  # noqa: E402
from trading_bot.config.settings import Settings, load_settings  # noqa: E402

DEFAULT_RUN_ROOT = Path("reports/autonomous-paper")
DEFAULT_STATE_PATH = Path("data/storage/autonomous_paper_state.json")
DEFAULT_DAILY_REPORT_SECONDS = 3600.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", default="BTC,ETH,SOL")
    parser.add_argument("--timeframe", default="5m")
    parser.add_argument("--cycles", type=int, default=1, help="1 = ONE_SHOT")
    parser.add_argument(
        "--continuous",
        action="store_true",
        help="run until stopped (STOP file or SIGINT/SIGTERM); implies unlimited cycles",
    )
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
    parser.add_argument(
        "--verify-provider",
        dest="verify_provider",
        action="store_true",
        default=True,
        help="Ask the provider which markets it lists (best effort, DEF-AUTO-2).",
    )
    parser.add_argument(
        "--no-verify-provider",
        dest="verify_provider",
        action="store_false",
        help="Skip the provider half of the universe preflight (offline runs).",
    )
    parser.add_argument(
        "--daily-report-seconds",
        type=float,
        default=DEFAULT_DAILY_REPORT_SECONDS,
        help="How often to rewrite PAPER_DAILY_REPORT while running continuously.",
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


def build_registry(ledger: Any, assets: list[str]) -> Any:
    """Build the strategy registry: the runtime's only view of what exists."""
    from trading_bot.autonomous.strategy_state import StrategyRegistry

    return StrategyRegistry.from_ledger(ledger, assets=assets)


def report_registry(registry: Any, timeframe: str) -> None:
    """Print the lifecycle state and say why nothing can trade (never silent)."""
    for line in registry.describe(timeframe):
        print(line)


def provider_markets(source: Any) -> tuple[str, ...] | None:
    """Best-effort list of markets the provider serves; ``None`` when unknown.

    The point is to *try*, not to pretend: an offline host returns ``None`` and
    the preflight reports provider support as unverified rather than inventing
    a verdict in either direction.
    """
    try:
        loader = getattr(source, "load_markets", None)
        if callable(loader):
            loader()
        markets = getattr(source, "markets", None)
        if isinstance(markets, dict) and markets:
            return tuple(sorted({str(symbol).split("/")[0].upper() for symbol in markets}))
    except Exception:
        return None
    return None


def preflight_run_universe(
    *,
    ledger: Any,
    assets: list[str],
    registry: Any,
    provider: str,
    source: Any = None,
    verify_provider: bool = True,
) -> Any:
    """§39/DEF-AUTO-2 — configured ∩ provider ∩ strategy, before the first cycle."""
    from trading_bot.autonomous.universe_preflight import (
        preflight_universe,
        research_universe_from_sources,
    )
    from trading_bot.research.asset_intelligence.registry import CryptoAssetAgentRegistry

    strategy_assets, strategy_source = research_universe_from_sources(
        ledger.sources, repo_root=REPO_ROOT
    )
    provider_supported = None
    if verify_provider and provider != "fake" and source is not None:
        provider_supported = provider_markets(source)
    return preflight_universe(
        configured=assets,
        asset_agents=CryptoAssetAgentRegistry().supported_assets(),
        strategy_assets=strategy_assets or None,
        provider_supported=provider_supported,
        strategy_universe_source=strategy_source,
    )


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


def write_run_descriptor(run_dir: Path, payload: dict[str, Any]) -> Path:
    """The supervisor's view of a live run: pid, mode, candidates, commit."""
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "PAPER_RUN.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


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
    from trading_bot.autonomous.paper_loop import (
        ArtifactWriteFailures,
        HeartbeatWriter,
        PaperHeartbeat,
        StopController,
        build_daily_report,
        durable_write,
        write_daily_report,
    )
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
    registry = build_registry(ledger, assets)
    report_registry(registry, args.timeframe)

    run_id = args.run_id or f"autonomous-paper-{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}"
    run_dir = REPO_ROOT / args.run_root / run_id

    scanner_factory, data_source = build_scanner_factory(settings, args.provider)

    support = preflight_run_universe(
        ledger=ledger,
        assets=assets,
        registry=registry,
        provider=args.provider,
        source=data_source,
        verify_provider=args.verify_provider,
    )
    print(f"[preflight] universe: {json.dumps(support.to_dict(), ensure_ascii=False)}")
    if not support.ok:
        print(
            "Refusing to start: the configured universe cannot be served before the "
            f"first cycle ({support.blocking_reason})",
            file=sys.stderr,
        )
        return 1

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
    environment = f"{args.provider}:{settings.runtime.exchange_id or 'unset'}"
    runtime = AutonomousPaperRuntime(
        settings=settings,
        scanner_factory=scanner_factory,
        history_reader=reader,
        broker=broker,
        risk_manager=risk,
        families=families,
        strategy_map=registry.strategy_map(args.timeframe),
        ledger=ledger,
        run_dir=run_dir,
        assets=assets,
        timeframe=args.timeframe,
        horizon_minutes=args.horizon_minutes,
        size_usd=args.size_usd,
        lookback_bars=args.lookback_bars,
        shadow_evaluation_enabled=not args.no_shadow,
        environment=environment,
        idempotency=idempotency,
    )

    heartbeat = HeartbeatWriter(run_dir=run_dir)
    stop = StopController(run_dir=run_dir)
    stop.clear_stop_file()
    stop.install()
    goal = "CONTINUOUS" if args.continuous else f"{args.cycles} cycle(s)"
    print(
        f"[run] {run_id} goal={goal} interval={args.interval}s "
        f"assets={assets} timeframe={args.timeframe} config={args.config_dir}"
    )
    print(f"[run] agents={[c['agent_id'] for c in runtime.agent_capabilities()]}")
    write_run_descriptor(
        run_dir,
        {
            "run_id": run_id,
            "pid": os.getpid(),
            "mode": settings.runtime.mode.value,
            "continuous": bool(args.continuous),
            "assets": assets,
            "timeframe": args.timeframe,
            "provider": args.provider,
            "environment": environment,
            "paper_candidates": registry.paper_candidates(args.timeframe),
            "registry_counts": registry.counts_by_status(),
            "universe_preflight": support.to_dict(),
            "stop_signals_installed": list(stop.installed),
            "started_at_ms": int(time.time() * 1000),
        },
    )

    def state_age_seconds() -> float | None:
        """How old the persisted PAPER state is, from the file itself (§14)."""
        try:
            stamp = store.path.stat().st_mtime
        except OSError:
            return None
        return round(max(0.0, time.time() - stamp), 3)

    started_at_ms = int(time.time() * 1000)
    cycle_reports: list[Any] = []
    cycle_errors: list[str] = []
    stop_reason: str | None = None
    #: §22 — evidence writes that failed. PAPER keeps deciding: a research volume
    #: filling up degrades what we can prove about the run, not the run itself.
    storage_failures = ArtifactWriteFailures()
    next_daily_report_at = time.monotonic() + max(1.0, args.daily_report_seconds)
    cycle = 0
    summary: Any = None
    daily: tuple[Path, Path] | None = None

    try:
        while True:
            if stop.stopped:
                stop_reason = stop.reason or "STOP file"
                break
            if not args.continuous and cycle >= args.cycles:
                break
            cycle += 1
            try:
                cycle_report = await runtime.run_cycle(cycle=cycle)
            except Exception as exc:  # a cycle failure is visible, never silent
                message = f"cycle {cycle}: {type(exc).__name__}: {exc}"
                cycle_errors.append(message)
                print(f"[run] {message}", file=sys.stderr)
                failed_beat = PaperHeartbeat.from_cycle(
                    run_id=run_id,
                    cycle=cycle,
                    report=None,
                    started_at_ms=started_at_ms,
                    timeframe=args.timeframe,
                    paper_candidates=registry.paper_candidates(args.timeframe),
                )
                failed_beat = replace(
                    failed_beat,
                    storage_failures=storage_failures.count,
                    storage_errors=storage_failures.recent(),
                )
                durable_write(
                    lambda beat=failed_beat: heartbeat.write(beat),
                    what="heartbeat",
                    failures=storage_failures,
                )
            else:
                cycle_reports.append(cycle_report)
                hb = PaperHeartbeat.from_cycle(
                    run_id=run_id,
                    cycle=cycle,
                    report=cycle_report,
                    started_at_ms=started_at_ms,
                    timeframe=args.timeframe,
                    paper_candidates=registry.paper_candidates(args.timeframe),
                    state_age_seconds=state_age_seconds(),
                )
                hb = replace(
                    hb,
                    storage_failures=storage_failures.count,
                    storage_errors=storage_failures.recent(),
                )
                durable_write(
                    lambda beat=hb: heartbeat.write(beat),
                    what="heartbeat",
                    failures=storage_failures,
                )
                print(
                    f"[cycle {cycle}] decisions={hb.decisions} no_trade={hb.no_trade} "
                    f"shadow={hb.shadow_trades} paper={hb.paper_trades} "
                    f"failures={hb.runtime_failures} strategies={hb.strategies_evaluated}"
                )
            if time.monotonic() >= next_daily_report_at:
                durable_write(
                    lambda: _write_daily(
                        cycle_reports, cycle_errors, runtime, registry, started_at_ms,
                        run_id, args, stop, write_daily_report, build_daily_report,
                    ),
                    what="daily report",
                    failures=storage_failures,
                )
                next_daily_report_at = time.monotonic() + max(1.0, args.daily_report_seconds)
            if not args.continuous and cycle >= args.cycles:
                break
            if args.interval > 0:
                await asyncio.sleep(args.interval)
    finally:
        summary = runtime.finalize_summary(
            run_id=run_id, started_at_ms=started_at_ms, cycle_reports=cycle_reports,
            errors=cycle_errors,
        )
        try:
            from trading_bot.paper.paper_runtime_state import save_session_state

            save_session_state(
                store=store, run_id=run_id, broker=broker, risk=risk, idempotency=idempotency
            )
            print(f"[run] paper state saved to {store.path}")
        except Exception as exc:  # never hide the run result behind a save error
            print(f"[run] state save failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        daily = durable_write(
            lambda: _write_daily(
                cycle_reports, cycle_errors, runtime, registry, started_at_ms, run_id, args,
                stop, write_daily_report, build_daily_report,
            ),
            what="final daily report",
            failures=storage_failures,
        )

    assert summary is not None, "the run loop must produce a summary"
    # The run report is the run's own evidence, so it is requested the same way: a
    # full disk must not turn a completed run into a process that died.
    reported = durable_write(
        lambda: write_run_report(summary, run_dir), what="run report", failures=storage_failures
    )
    md_path, json_path = reported if reported is not None else (None, None)
    print(json.dumps(summary.totals(), indent=2))
    print(f"[run] stop reason: {stop_reason or 'completed'}")
    print(f"[run] report: {md_path}")
    print(f"[run] report: {json_path}")
    print(f"[run] traces: {runtime.trace_store.trace_path}")
    print(f"[run] heartbeat: {heartbeat.current_path} ({heartbeat.written} beats)")
    print(f"[run] daily report: {daily[1] if daily else 'not written'}")
    if storage_failures.count:
        print(
            f"[run] storage failures: {storage_failures.count} "
            f"(the run continued; see {heartbeat.current_path})",
            file=sys.stderr,
        )
    durable_write(
        lambda: write_run_descriptor(
            run_dir,
            {
                "run_id": run_id,
                "pid": os.getpid(),
                "state": "STOPPED",
                "stop_reason": stop_reason or "completed",
                "cycles": len(cycle_reports),
                "totals": summary.totals(),
                "storage_failures": storage_failures.count,
                "storage_errors": list(storage_failures.recent()),
                "ended_at_ms": int(time.time() * 1000),
            },
        ),
        what="run descriptor",
        failures=storage_failures,
    )
    return 0


def _write_daily(
    cycle_reports: list[Any],
    cycle_errors: list[str],
    runtime: Any,
    registry: Any,
    started_at_ms: int,
    run_id: str,
    args: argparse.Namespace,
    stop: Any,
    write_daily_report: Any,
    build_daily_report: Any,
) -> tuple[Path, Path] | None:
    """Regenerate the day's report from the cycles actually completed (§15)."""
    if not cycle_reports:
        return None
    assets = [a.strip().upper() for a in args.assets.split(",") if a.strip()]
    summary = runtime.finalize_summary(
        run_id=run_id, started_at_ms=started_at_ms, cycle_reports=cycle_reports,
        errors=cycle_errors,
    )
    payload = build_daily_report(
        run_id=run_id,
        timeframe=args.timeframe,
        assets=assets,
        started_at_ms=started_at_ms,
        cycles=cycle_reports,
        totals=summary.totals(),
        paper_candidates=registry.paper_candidates(args.timeframe),
        performance=summary.performance,
        outcomes=summary.outcomes,
        errors=summary.errors,
        restarts=[{"reason": stop.reason}] if stop.reason else [],
    )
    paths: tuple[Path, Path] = write_daily_report(runtime.run_dir, payload)
    return paths


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
