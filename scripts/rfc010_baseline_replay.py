"""RFC-010 economic baseline replay harness.

Drives the **authoritative** autonomous runtime (``AutonomousPaperRuntime`` +
``StrategyRouter`` + the 6 productive ``AlphaFamilies`` + ``RiskManager`` +
``PaperBroker``) over REAL historical OHLCV, deterministically.

Design rules (RFC-010 §11/§12):

* NO strategy / router / risk / sizing / accounting logic is reimplemented here.
  The only new code is a *market-data adapter* (``ReplayMarketSource``) and a
  *clock adapter* (``ReplayClock``). Everything else is the certified runtime.
* The scanner is the real ``UniverseScanner`` with the real per-mode filters, so
  the funnel (market-data validation) is the runtime's, not a research proxy.
* PIT is enforced by the runtime itself: the decision timestamp is
  ``min(snapshot_ts, now_fn())`` and ``closed_bar_slice`` trims to closed bars.

Data: ``reports/strategy-baseline/data/<SYM>_<WINDOW>.json`` (5m bars).
No network, no credentials, no LIVE.

Usage:
    python scripts/rfc010_baseline_replay.py --assets BTC,ETH,SOL \
        --windows W1,W2,W3,W4 --step 1 --out reports/rfc010/baseline_run.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.config.settings import load_settings  # noqa: E402
from trading_bot.config.universe import PairSpec  # noqa: E402
from trading_bot.market_data.types import OHLCV  # noqa: E402

DATA_DIR = REPO_ROOT / "reports" / "strategy-baseline" / "data"
TF_MS = {"5m": 300_000, "15m": 900_000, "30m": 1_800_000, "1h": 3_600_000}
DEFAULT_SPREAD_BPS = 1.0  # COST_MODEL_V3 majors default (BINANCE_SPOT_STANDARD_TAKER)


class ReplayClock:
    """Deterministic epoch-millisecond clock for the replay."""

    def __init__(self, start_ms: int) -> None:
        self.now_ms = int(start_ms)

    def __call__(self) -> int:
        return self.now_ms

    def seconds(self) -> float:
        return self.now_ms / 1000.0


class ReplayMarketSource:
    """``MarketDataSourceProtocol`` over historical bars, as-of a replay clock.

    ``fetch_recent`` returns the LAST ``limit`` bars whose timestamp is at or
    before the replay clock (like a real provider at that instant). Volume is the
    trailing-24h quote volume implied by those bars. Spread has no historical
    series in this dataset, so the COST_MODEL_V3 majors default is used and the
    class is recorded as ESTIMATED (never treated as observed zero).
    """

    def __init__(
        self, bars_by_symbol: dict[str, list[OHLCV]], clock: ReplayClock, *, spread_bps: float
    ) -> None:
        self._bars = bars_by_symbol
        self._clock = clock
        self._spread_bps = float(spread_bps)

    def _visible(self, symbol: str) -> list[OHLCV]:
        cutoff = self._clock()
        return [b for b in self._bars.get(symbol, []) if b.timestamp <= cutoff]

    async def fetch_recent(self, symbol: str, limit: int = 100) -> list[OHLCV]:
        visible = self._visible(symbol)
        return visible[-int(limit) :] if limit > 0 else []

    async def fetch_24h_volume_usdt(self, symbol: str) -> float:
        visible = self._visible(symbol)
        window = visible[-288:]  # 24h of 5m bars
        return float(sum(b.volume * b.close for b in window))

    async def fetch_spread_bps(self, symbol: str) -> float:
        return self._spread_bps


def load_bars(assets: list[str], windows: list[str]) -> dict[str, list[OHLCV]]:
    """Load and concatenate the frozen 5m dataset per asset (sorted, deduped)."""
    out: dict[str, list[OHLCV]] = {}
    for asset in assets:
        bars: list[OHLCV] = []
        for window in windows:
            path = DATA_DIR / f"{asset}USDT_{window}_2026-0*.json"
            matches = sorted(DATA_DIR.glob(f"{asset}USDT_{window}_2026-*.json"))
            if not matches:
                raise FileNotFoundError(f"no dataset for {asset} {window}")
            path = matches[0]
            rows = json.loads(path.read_text(encoding="utf-8"))
            bars.extend(
                OHLCV(
                    symbol=f"{asset}/USDT",
                    timestamp=int(r["ts"]),
                    open=float(r["open"]),
                    high=float(r["high"]),
                    low=float(r["low"]),
                    close=float(r["close"]),
                    volume=float(r["volume"]),
                )
                for r in rows
            )
        seen: set[int] = set()
        deduped: list[OHLCV] = []
        for bar in sorted(bars, key=lambda b: b.timestamp):
            if bar.timestamp in seen:
                continue
            seen.add(bar.timestamp)
            deduped.append(bar)
        out[f"{asset}/USDT"] = deduped
    return out


def build_runtime(
    *, assets: list[str], timeframe: str, bars_by_symbol: dict[str, list[OHLCV]],
    clock: ReplayClock, run_dir: Path, initial_equity: float, size_usd: float,
    lookback_bars: int, spread_bps: float,
) -> Any:
    from trading_bot.autonomous.admission_ledger import AdmissionLedger
    from trading_bot.autonomous.runtime import AutonomousPaperRuntime
    from trading_bot.autonomous.strategy_state import StrategyRegistry
    from trading_bot.paper.broker import PaperBroker
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
    from trading_bot.scanner.mode_filters import build_filter_set_per_mode
    from trading_bot.scanner.scanner import UniverseScanner

    settings = load_settings(config_dir="config/realdata")
    pairs = [PairSpec(symbol=f"{a}/USDT", enabled=True) for a in assets]
    universe = settings.universe.model_copy(update={"pairs": pairs, "timeframes": [timeframe]})
    settings = settings.model_copy(update={"universe": universe})

    source = ReplayMarketSource(bars_by_symbol, clock, spread_bps=spread_bps)

    def scanner_factory() -> Any:
        scan_settings = settings.model_copy(
            update={"risk": settings.risk.model_copy(update={"kill_switch_enabled": False})}
        )
        return UniverseScanner(
            source=source,
            registry_per_mode=build_filter_set_per_mode(scan_settings),
            settings=scan_settings,
        )

    ledger = AdmissionLedger.load(REPO_ROOT / "config" / "strategy_admission.json")
    registry = StrategyRegistry.from_ledger(ledger, assets=assets)
    reader = FetcherBarReader(source, timeframe=timeframe)
    broker = PaperBroker(equity=initial_equity)
    risk = RiskManager(risk=settings.risk, equity=initial_equity, _clock=clock.seconds)

    families = {
        "ema_crossover": EmaCrossoverFamily(),
        "momentum": MomentumFamily(),
        "breakout": BreakoutFamily(),
        "trend": TrendFamily(),
        "mean_reversion": MeanReversionFamily(),
        "volatility": VolatilityFamily(),
    }
    return AutonomousPaperRuntime(
        settings=settings,
        scanner_factory=scanner_factory,
        history_reader=reader,
        broker=broker,
        risk_manager=risk,
        families=families,
        strategy_map=registry.strategy_map(timeframe),
        ledger=ledger,
        run_dir=run_dir,
        assets=assets,
        timeframe=timeframe,
        size_usd=size_usd,
        lookback_bars=lookback_bars,
        shadow_evaluation_enabled=True,
        environment="rfc010-replay",
        now_fn=clock,
        routing_mode="LEGACY",
    ), registry


def timeline(bars_by_symbol: dict[str, list[OHLCV]], step: int, interval_ms: int) -> list[int]:
    """Replay decision instants: the CLOSE of every ``step``-th sealed bar."""
    stamps = sorted({b.timestamp for bars in bars_by_symbol.values() for b in bars})
    return [t + interval_ms for i, t in enumerate(stamps) if i % step == 0]


async def run(args: argparse.Namespace) -> dict[str, Any]:
    assets = [a.strip().upper() for a in args.assets.split(",") if a.strip()]
    windows = [w.strip().upper() for w in args.windows.split(",") if w.strip()]
    bars_by_symbol = load_bars(assets, windows)
    if getattr(args, "max_bars", 0):
        # RFC-010B §5 — a controlled window: every cadence sees the SAME slice,
        # so a step/step comparison isolates the sampling effect.
        bars_by_symbol = {s: b[: args.max_bars] for s, b in bars_by_symbol.items()}
    interval_ms = TF_MS[args.timeframe]

    run_dir = REPO_ROOT / "reports" / "rfc010" / "runs" / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    instants = timeline(bars_by_symbol, args.step, interval_ms)
    start_ms = instants[0]
    clock = ReplayClock(start_ms)

    runtime, registry = build_runtime(
        assets=assets, timeframe=args.timeframe, bars_by_symbol=bars_by_symbol, clock=clock,
        run_dir=run_dir, initial_equity=args.initial_equity, size_usd=args.size_usd,
        lookback_bars=args.lookback_bars, spread_bps=args.spread_bps,
    )

    cycles: list[Any] = []
    errors: list[str] = []
    for i, instant in enumerate(instants, start=1):
        clock.now_ms = instant
        try:
            report = await runtime.run_cycle(cycle=i)
        except Exception as exc:  # a cycle failure is visible, never silent
            errors.append(f"cycle {i}: {type(exc).__name__}: {exc}")
            continue
        cycles.append(report)

    summary = runtime.finalize_summary(
        run_id=args.run_id, started_at_ms=start_ms, cycle_reports=cycles, errors=errors
    )
    broker = runtime._broker  # harness inspection of the authoritative broker
    closed = broker.closed_trades

    result: dict[str, Any] = {
        "run_id": args.run_id,
        "assets": assets,
        "windows": windows,
        "timeframe": args.timeframe,
        "step_bars": args.step,
        "decision_instants": len(instants),
        "cycles_completed": len(cycles),
        "cycles_failed": len(errors),
        "initial_equity": args.initial_equity,
        "final_equity": broker.equity,
        "totals": summary.totals(),
        "registry_counts": registry.counts_by_status(),
        "paper_executable": list(registry.paper_candidates(args.timeframe)),
        "closed_trades": len(closed),
        "closed_trades_pnl": [round(float(t.pnl), 6) for t in closed],
        "realized_pnl": round(sum(float(t.pnl) for t in closed), 6),
        "errors": errors[:20],
        "trace_chain": summary.chain,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", default="BTC")
    parser.add_argument("--windows", default="W1")
    parser.add_argument("--timeframe", default="5m")
    parser.add_argument("--step", type=int, default=1, help="evaluate every Nth sealed bar")
    parser.add_argument(
        "--max-bars", type=int, default=0, help="slice each asset to its first N bars (0=all)"
    )
    parser.add_argument("--initial-equity", type=float, default=10_000.0)
    parser.add_argument("--size-usd", type=float, default=1_000.0)
    parser.add_argument("--lookback-bars", type=int, default=120)
    parser.add_argument("--spread-bps", type=float, default=DEFAULT_SPREAD_BPS)
    parser.add_argument("--run-id", default="RFC010-RUN0")
    parser.add_argument("--out", default="reports/rfc010/baseline_run.json")
    args = parser.parse_args()
    result = asyncio.run(run(args))
    print(json.dumps({k: result[k] for k in (
        "decision_instants", "cycles_completed", "cycles_failed", "totals",
        "paper_executable", "closed_trades", "realized_pnl", "final_equity",
    )}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
