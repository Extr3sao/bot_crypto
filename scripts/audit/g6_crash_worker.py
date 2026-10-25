"""G-6 crash worker: run the REAL paper cycle in its own process.

The parent harness starts this script, waits for the durable boundary marker,
and then kills the process with a forced OS termination.  The worker uses the
repository's own ``PaperCycleEngine``, ``DurablePaperBroker``, durable state
store and startup reconciler; only the market data and clock are pinned test
fixtures (the same controlled pattern as G-5).
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

import trading_bot.scanner.scanner as scanner_module  # noqa: E402
from scripts.start_paper_trading import build_cycle_engine  # noqa: E402
from trading_bot.autonomous.hot_stop import HotStopGate  # noqa: E402
from trading_bot.config.settings import Settings, load_settings  # noqa: E402
from trading_bot.config.universe import PairSpec  # noqa: E402
from trading_bot.market_data.fake import FakeMarketDataSource  # noqa: E402
from trading_bot.market_data.types import OHLCV  # noqa: E402
from trading_bot.paper.crash_injection import enabled_point  # noqa: E402
from trading_bot.paper.durable_broker import DurablePaperBroker  # noqa: E402
from trading_bot.paper.kill_switch_v2 import KillSwitch  # noqa: E402
from trading_bot.paper.paper_orchestrator import PaperOrchestrator  # noqa: E402
from trading_bot.paper.paper_runtime_state import save_session_state  # noqa: E402
from trading_bot.paper.paper_state_store import PaperStateStore  # noqa: E402
from trading_bot.paper.reconciliation_v4 import StartupReconcilerV4  # noqa: E402
from trading_bot.paper.snapshot_history import FetcherBarReader  # noqa: E402
from trading_bot.scanner.mode_filters import build_filter_set_per_mode  # noqa: E402
from trading_bot.scanner.scanner import UniverseScanner  # noqa: E402

PINNED = datetime.datetime(2026, 10, 21, 12, 0, tzinfo=datetime.UTC)  # Wednesday
BAR_MS = 5 * 60_000
SYMBOL = "BTC/USDT"
DEFAULT_LEDGER = REPO_ROOT / "docs" / "audit" / "fixtures" / "g6_paper_ledger.json"


class Clock:
    def __init__(self, offset_bars: int = 0) -> None:
        self.at = PINNED + datetime.timedelta(milliseconds=BAR_MS * offset_bars)

    @property
    def now_ms(self) -> int:
        return int(self.at.timestamp() * 1000)

    def now(self) -> datetime.datetime:
        return self.at


def rising_bars(*, end_ms: int, n: int = 100, multiplier: float = 1.0) -> list[OHLCV]:
    base = end_ms - n * BAR_MS
    return [
        OHLCV(
            symbol=SYMBOL,
            timestamp=base + i * BAR_MS,
            open=(100.0 + i) * multiplier,
            high=(101.0 + i) * multiplier,
            low=(99.0 + i) * multiplier,
            close=(100.5 + i) * multiplier,
            volume=1_000.0,
        )
        for i in range(n)
    ]


def flat_bars(*, end_ms: int, n: int = 100, level: float = 100.0) -> list[OHLCV]:
    base = end_ms - n * BAR_MS
    return [
        OHLCV(
            symbol=SYMBOL,
            timestamp=base + i * BAR_MS,
            open=level,
            high=level + 0.5,
            low=level - 0.5,
            close=level,
            volume=1_000.0,
        )
        for i in range(n)
    ]


def _settings() -> Settings:
    settings = load_settings(config_dir=str(REPO_ROOT / "config"), env_file=None)
    pairs = [PairSpec(symbol=SYMBOL, enabled=True)]
    return settings.model_copy(
        update={
            "universe": settings.universe.model_copy(update={"pairs": pairs, "timeframes": ["5m"]})
        }
    )


def _scanner(settings: Settings, source: Any) -> UniverseScanner:
    scan_settings = settings.model_copy(
        update={"risk": settings.risk.model_copy(update={"kill_switch_enabled": False})}
    )
    return UniverseScanner(
        source=source,
        registry_per_mode=build_filter_set_per_mode(scan_settings),
        settings=scan_settings,
    )


def _source(mode: str, clock: Clock) -> FakeMarketDataSource:
    source = FakeMarketDataSource()
    source.volume_by_symbol[SYMBOL] = 50_000_000.0
    source.spread_by_symbol[SYMBOL] = 5.0
    if mode == "spike":
        bars = rising_bars(
            end_ms=clock.now_ms,
            multiplier=1.10,
        )
    elif mode == "flat":
        bars = flat_bars(end_ms=clock.now_ms)
    else:
        bars = rising_bars(end_ms=clock.now_ms)
    source.ohlcv_by_symbol[SYMBOL] = bars
    return source


class CountingDurableBroker(DurablePaperBroker):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.execute_calls = 0
        self.close_calls = 0

    def execute_signal(self, signal: Any) -> Any:
        self.execute_calls += 1
        return super().execute_signal(signal)


def _state_summary(store: PaperStateStore) -> dict[str, Any]:
    if not store.exists():
        return {
            "exists": False,
            "sha256": None,
            "bytes": 0,
            "open_positions": 0,
            "closed_trades": 0,
            "sent_intents": 0,
            "orders": [],
            "equity": 0.0,
        }
    raw = store.path.read_bytes()
    try:
        doc = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        return {
            "exists": True,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
            "parse_error": f"{type(exc).__name__}: {exc}",
        }
    broker = dict(doc.get("broker_state", {}) or {})
    return {
        "exists": True,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "open_positions": len(doc.get("open_positions", []) or []),
        "closed_trades": len(doc.get("closed_trades", []) or []),
        "sent_intents": len(doc.get("sent_intents", []) or []),
        "orders": [dict(row) for row in doc.get("orders", []) or []],
        "equity": float(broker.get("equity", 0.0) or 0.0),
        "run_id": doc.get("run_id", ""),
        "updated_at_ms": doc.get("updated_at_ms", 0),
    }


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    clock = Clock(args.clock_offset_bars)
    settings = _settings()
    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    state_path = Path(args.state)
    store = PaperStateStore(state_path)
    source = _source(args.bars, clock)

    if args.kill_switch:
        (run_dir / "KILL_SWITCH").write_text("G-6 recovery stop\n", encoding="utf-8")
    gate = HotStopGate(kill_switch=KillSwitch(), run_dir=run_dir)
    broker = CountingDurableBroker(
        equity=10_000.0,
        clock=lambda: clock.at.timestamp(),
        book_id=f"g6-{os.getpid()}",
    )
    engine = build_cycle_engine(
        settings,
        broker,
        assets=[SYMBOL.split("/")[0]],
        timeframe="5m",
        ledger_path=Path(args.ledger),
        hot_stop=gate,
    )
    broker.attach_durability(
        store=store,
        risk=engine.risk_manager,
        idempotency=engine.idempotency,
        run_id=f"g6-{os.getpid()}",
    )
    reconciler = StartupReconcilerV4(
        store=store,
        broker=broker,
        risk_manager=engine.risk_manager,
        idempotency=engine.idempotency,
    )
    reconciliation = reconciler.reconcile()
    if reconciliation.status == "FATAL":
        return {
            "worker": "g6",
            "pid": os.getpid(),
            "crash_point": enabled_point(),
            "reconciliation": reconciliation.to_dict(),
            "status": "FATAL",
            "state_after": _state_summary(store),
        }

    positions_after_reconcile = [p.to_row() for p in broker.positions.values()]
    orchestrator = PaperOrchestrator(
        settings=settings,
        scanner_factory=lambda: _scanner(settings, source),
        broker=broker,
        max_sessions=1,
        interval_seconds=0.0,
        cycle_engine=engine,
        cycle_history_reader=FetcherBarReader(source, timeframe="5m"),
        state_store=store,
        now_fn=clock.now,
        report_output_dir=str(run_dir / "reports"),
    )
    previous_now_ms = scanner_module._now_ms
    scanner_module._now_ms = lambda: clock.now_ms
    try:
        await orchestrator.run()
    finally:
        scanner_module._now_ms = previous_now_ms

    save_session_state(
        store=store,
        run_id=f"g6-{os.getpid()}",
        broker=broker,
        risk=engine.risk_manager,
        idempotency=engine.idempotency,
        orders=broker.orders_snapshot(),
    )
    marks: dict[str, float] = {}
    try:
        bars = await source.fetch_recent(SYMBOL, limit=10_000)
        if bars and float(bars[-1].close) > 0:
            marks[SYMBOL] = float(bars[-1].close)
    except Exception:
        marks = {}
    status = orchestrator.status()
    return {
        "worker": "g6",
        "pid": os.getpid(),
        "crash_point": enabled_point(),
        "reconciliation": reconciliation.to_dict(),
        "positions_after_reconcile": positions_after_reconcile,
        "status": status,
        "cycle": status.get("cycle") or {},
        "broker_calls": {
            "execute_signal": broker.execute_calls,
            "close_position": broker.close_calls,
        },
        "positions": [p.to_row() for p in broker.positions.values()],
        "closed_trades": [
            {
                "symbol": trade.symbol,
                "side": trade.side,
                "pnl": trade.pnl,
                "exit_reason": trade.exit_reason,
                "position_id": trade.position_id,
                "entry_order_id": trade.entry_order_id,
                "exit_order_id": trade.exit_order_id,
            }
            for trade in broker.closed_trades
        ],
        "accounting": broker.accounting_snapshot(marks),
        "state_after": _state_summary(store),
        "exit_code": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="G-6 PAPER crash worker.")
    parser.add_argument("--state", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    parser.add_argument("--crash-at", default="")
    parser.add_argument("--marker", default="")
    parser.add_argument("--bars", choices=["rising", "spike", "flat"], default="rising")
    parser.add_argument("--clock-offset-bars", type=int, default=0)
    parser.add_argument("--kill-switch", action="store_true")
    args = parser.parse_args(argv)
    if args.crash_at:
        os.environ["PAPER_CRASH_POINT"] = args.crash_at
    if args.marker:
        os.environ["PAPER_CRASH_MARKER"] = args.marker

    payload = asyncio.run(_run(args))
    print("WORKER_RESULT " + json.dumps(payload, sort_keys=True, default=str))
    return 0 if payload.get("status") != "FATAL" else 2


if __name__ == "__main__":
    raise SystemExit(main())
