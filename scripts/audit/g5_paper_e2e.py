"""G-5 — deterministic paper end-to-end evidence over the REAL paper engine.

PAPER_ONLY. This command never creates an exchange client, never reads a
credential and never sends an order. Market data is a controlled synthetic
fixture; the decision path, risk manager, hot-stop gate, paper broker,
durable state store and startup reconciler are the repository's own classes.

Scenarios (all executed in one process, isolated state/run directories):

    TRADE       rising bars -> signal -> risk -> HotStopGate -> PaperBroker
                -> open position -> durable state
    RESTART     new broker/engine/reconciler over the same state file ->
                RECOVERED position + intent ledger -> price spike ->
                take-profit close -> accounting identity
    NO_TRADE    flat bars -> no alpha -> zero orders
    STALE       bars behind the decision clock -> router stale_context -> zero orders
    KILL_SWITCH operator marker -> zero broker calls / zero orders
    EXCEPTION   provider raises -> scanner error -> zero orders

The pinned clock is a test-only control: the scanner's ``_now_ms`` and the
runner's ``now_fn`` are both pinned to a Wednesday, because the committed
policy forbids weekend trading. This is recorded in the output; production
uses the wall clock (the default).
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import hashlib
import json
import sys
import time
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
from trading_bot.paper.broker import PaperBroker  # noqa: E402
from trading_bot.paper.kill_switch_v2 import KillSwitch  # noqa: E402
from trading_bot.paper.paper_orchestrator import PaperOrchestrator  # noqa: E402
from trading_bot.paper.paper_state_store import PaperStateStore  # noqa: E402
from trading_bot.paper.reconciliation_v4 import StartupReconcilerV4  # noqa: E402
from trading_bot.paper.snapshot_history import FetcherBarReader  # noqa: E402
from trading_bot.scanner.mode_filters import build_filter_set_per_mode  # noqa: E402
from trading_bot.scanner.scanner import UniverseScanner  # noqa: E402

PINNED = datetime.datetime(2026, 10, 21, 12, 0, tzinfo=datetime.UTC)  # Wednesday
PINNED_MS = int(PINNED.timestamp() * 1000)
BAR_MS = 5 * 60_000
SYMBOL = "BTC/USDT"
DEFAULT_LEDGER = REPO_ROOT / "docs" / "audit" / "fixtures" / "g5_paper_ledger.json"


class Clock:
    """Deterministic session clock; advances only when a scenario says so."""

    def __init__(self, at: datetime.datetime = PINNED) -> None:
        self.at = at

    @property
    def now_ms(self) -> int:
        return int(self.at.timestamp() * 1000)

    def now(self) -> datetime.datetime:
        return self.at

    def advance_bars(self, bars: int = 1) -> None:
        self.at = self.at + datetime.timedelta(milliseconds=BAR_MS * bars)


def rising_bars(
    *,
    end_ms: int,
    n: int = 100,
    multiplier: float = 1.0,
    spacing_ms: int = BAR_MS,
) -> list[OHLCV]:
    """Deterministic 5m bars ending with a closed candle at ``end_ms``."""
    base = end_ms - n * spacing_ms
    return [
        OHLCV(
            symbol=SYMBOL,
            timestamp=base + i * spacing_ms,
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


class CountingBroker(PaperBroker):
    """Real broker with call counters, so 'zero calls' is measured, not inferred."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.execute_calls = 0
        self.close_calls = 0

    def execute_signal(self, signal: Any) -> Any:
        self.execute_calls += 1
        return super().execute_signal(signal)

    def close_position(self, *args: Any, **kwargs: Any) -> Any:
        self.close_calls += 1
        return super().close_position(*args, **kwargs)


class ExplodingSource(FakeMarketDataSource):
    """Provider failure fixture: the scanner must record it and place no order."""

    async def fetch_recent(self, symbol: str, limit: int = 100) -> list[OHLCV]:
        raise ConnectionError(f"controlled provider outage for {symbol}")


def _settings() -> Settings:
    settings = load_settings(config_dir=str(REPO_ROOT / "config"), env_file=None)
    pairs = [PairSpec(symbol=SYMBOL, enabled=True)]
    return settings.model_copy(
        update={
            "universe": settings.universe.model_copy(update={"pairs": pairs, "timeframes": ["5m"]})
        }
    )


def _scanner(settings: Settings, source: Any) -> UniverseScanner:
    """Same scanner composition as ``scripts/start_paper_trading.py``."""
    scan_settings = settings.model_copy(
        update={"risk": settings.risk.model_copy(update={"kill_switch_enabled": False})}
    )
    return UniverseScanner(
        source=source,
        registry_per_mode=build_filter_set_per_mode(scan_settings),
        settings=scan_settings,
    )


def _source(bars: list[OHLCV] | None = None) -> FakeMarketDataSource:
    source = FakeMarketDataSource()
    source.volume_by_symbol[SYMBOL] = 50_000_000.0
    source.spread_by_symbol[SYMBOL] = 5.0
    if bars is not None:
        source.ohlcv_by_symbol[SYMBOL] = list(bars)
    return source


def _gate(run_dir: Path, *, marker: str | None = None) -> HotStopGate:
    run_dir.mkdir(parents=True, exist_ok=True)
    if marker is not None:
        (run_dir / "KILL_SWITCH").write_text(marker + "\n", encoding="utf-8")
    return HotStopGate(kill_switch=KillSwitch(), run_dir=run_dir)


async def run_scenario(
    *,
    name: str,
    clock: Clock,
    source: Any,
    state_path: Path,
    run_dir: Path,
    marker: str | None = None,
    ledger: Path = DEFAULT_LEDGER,
    broker: CountingBroker | None = None,
) -> dict[str, Any]:
    """Run one real paper session and return raw observations."""
    settings = _settings()
    run_dir.mkdir(parents=True, exist_ok=True)
    broker = broker or CountingBroker(
        equity=10_000.0,
        clock=lambda: clock.at.timestamp(),
        book_id=f"g5-{name}",
    )
    gate = _gate(run_dir, marker=marker)
    engine = build_cycle_engine(
        settings,
        broker,
        assets=[SYMBOL.split("/")[0]],
        timeframe="5m",
        ledger_path=ledger,
        hot_stop=gate,
    )
    store = PaperStateStore(state_path)
    reconciler = StartupReconcilerV4(
        store=store,
        broker=broker,
        risk_manager=engine.risk_manager,
        idempotency=engine.idempotency,
    )
    before = reconciler.reconcile()
    positions_after_reconcile = [p.to_row() for p in broker.positions.values()]
    risk_open_positions_after_reconcile = len(
        getattr(engine.risk_manager, "open_positions", {}) or {}
    )
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

    # The scanner stamps snapshots with its module clock; pin it so a replay
    # cannot mix a synthetic decision with the real calendar.
    previous_now_ms = scanner_module._now_ms
    scanner_module._now_ms = lambda: clock.now_ms
    started = time.perf_counter()
    try:
        await orchestrator.run()
    finally:
        scanner_module._now_ms = previous_now_ms
    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)

    status = orchestrator.status()
    closed = broker.closed_trades
    positions = broker.positions
    # A failing provider must not turn the evidence writer into a second
    # failure: mark-to-market is omitted (MTM_INCOMPLETE) instead.
    marks: dict[str, float] = {}
    try:
        bars = await source.fetch_recent(SYMBOL, limit=10_000)
        if bars and float(bars[-1].close) > 0:
            marks[SYMBOL] = float(bars[-1].close)
    except Exception:
        marks = {}
    accounting = broker.accounting_snapshot(marks)
    persisted = store.load_or_recover()
    return {
        "scenario": name,
        "clock_utc": clock.at.isoformat(),
        "synthetic_data": True,
        "reconciliation_before": before.to_dict(),
        "positions_after_reconcile": positions_after_reconcile,
        "risk_open_positions_after_reconcile": risk_open_positions_after_reconcile,
        "state_after": {
            "open_positions": len(persisted.open_positions),
            "closed_trades": len(persisted.closed_trades),
            "sent_intents": len(persisted.sent_intents),
            "equity": float(persisted.broker_state.get("equity", 0.0)),
        },
        "status": status,
        "cycle": status.get("cycle") or {},
        "positions": [p.to_row() for p in positions.values()],
        "closed_trades": [
            {
                "symbol": t.symbol,
                "side": t.side,
                "pnl": t.pnl,
                "exit_reason": t.exit_reason,
                "position_id": t.position_id,
                "entry_order_id": t.entry_order_id,
                "exit_order_id": t.exit_order_id,
                "gross_pnl": t.gross_pnl,
                "entry_commission": t.entry_commission,
                "exit_commission": t.exit_commission,
                "reference_gross_pnl": t.reference_gross_pnl,
                "execution_cost_usdt": t.execution_cost_usdt,
            }
            for t in closed
        ],
        "broker_calls": {
            "execute_signal": broker.execute_calls,
            "close_position": broker.close_calls,
        },
        "equity": broker.equity,
        "realized_pnl": sum(t.pnl for t in closed),
        "realized_pnl_matches_equity": abs(broker.equity - (10_000.0 + sum(t.pnl for t in closed)))
        <= 1e-9,
        "accounting": accounting,
        "state_path": str(state_path),
        "state_bytes": state_path.stat().st_size if state_path.exists() else 0,
        "elapsed_ms": elapsed_ms,
    }


async def run_all(out_dir: Path, ledger: Path = DEFAULT_LEDGER) -> dict[str, Any]:
    scenario_dir = out_dir / "scenarios"
    scenario_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {}

    # 1) TRADE + durable state.
    trade_clock = Clock()
    trade_source = _source(rising_bars(end_ms=trade_clock.now_ms))
    trade = await run_scenario(
        name="trade",
        clock=trade_clock,
        source=trade_source,
        state_path=scenario_dir / "trade" / "paper_state.json",
        run_dir=scenario_dir / "trade" / "run",
        ledger=ledger,
    )
    results["trade"] = trade

    # 2) RESTART: same state file, new broker/engine/reconciler, then a price
    #    spike that closes the restored position through reconcile_session.
    restart_clock = Clock(trade_clock.at + datetime.timedelta(milliseconds=BAR_MS))
    restart_source = _source(rising_bars(end_ms=restart_clock.now_ms, multiplier=1.10))
    restart = await run_scenario(
        name="restart",
        clock=restart_clock,
        source=restart_source,
        state_path=scenario_dir / "trade" / "paper_state.json",
        run_dir=scenario_dir / "trade" / "run",
        ledger=ledger,
    )
    results["restart"] = restart

    # 3) NO_TRADE: flat market, no alpha, zero orders.
    flat_clock = Clock()
    results["no_trade"] = await run_scenario(
        name="no_trade",
        clock=flat_clock,
        source=_source(flat_bars(end_ms=flat_clock.now_ms)),
        state_path=scenario_dir / "no_trade" / "paper_state.json",
        run_dir=scenario_dir / "no_trade" / "run",
        ledger=ledger,
    )

    # 4) STALE: old bars against a current decision clock.
    stale_clock = Clock()
    stale_source = _source(rising_bars(end_ms=stale_clock.now_ms - 36 * BAR_MS))
    results["stale"] = await run_scenario(
        name="stale",
        clock=stale_clock,
        source=stale_source,
        state_path=scenario_dir / "stale" / "paper_state.json",
        run_dir=scenario_dir / "stale" / "run",
        ledger=ledger,
    )

    # 5) KILL_SWITCH: operator marker present before the gate is built.
    kill_clock = Clock()
    results["kill_switch"] = await run_scenario(
        name="kill_switch",
        clock=kill_clock,
        source=_source(rising_bars(end_ms=kill_clock.now_ms)),
        state_path=scenario_dir / "kill_switch" / "paper_state.json",
        run_dir=scenario_dir / "kill_switch" / "run",
        marker="G-5 operator stop",
        ledger=ledger,
    )

    # 6) EXCEPTION: provider outage is contained; no order is invented.
    error_clock = Clock()
    exploding = ExplodingSource()
    # Reach the history fetch: volume/spread filters run before it.
    exploding.volume_by_symbol[SYMBOL] = 50_000_000.0
    exploding.spread_by_symbol[SYMBOL] = 5.0
    results["provider_exception"] = await run_scenario(
        name="provider_exception",
        clock=error_clock,
        source=exploding,
        state_path=scenario_dir / "provider_exception" / "paper_state.json",
        run_dir=scenario_dir / "provider_exception" / "run",
        ledger=ledger,
    )

    payload = {
        "schema_version": "g5-paper-e2e-evidence/v1",
        "generated_at_utc": datetime.datetime.now(datetime.UTC).isoformat(),
        "execution_class": "PAPER_ONLY_SYNTHETIC_FIXTURE",
        "live": False,
        "credentials_used": False,
        "exchange_clients_constructed": False,
        "order_sent": False,
        "ledger": str(ledger),
        "ledger_claim": "CONTROLLED_TEST_FIXTURE — not market evidence, not a production admission",
        "pinned_clock_utc": PINNED.isoformat(),
        "pinned_clock_reason": "committed policy forbids weekend trading; Wednesday is deliberate",
        "engine": "PaperCycleEngine (scripts/start_paper_trading.py::build_cycle_engine)",
        "state_store": "PaperStateStore + StartupReconcilerV4",
        "scenarios": results,
        "summary": {
            "trade_orders": trade["cycle"].get("orders_created", 0),
            "restart_reconciliation": restart["reconciliation_before"]["status"],
            "restart_orders": restart["cycle"].get("orders_created", 0),
            "restart_closed_trades": len(restart["closed_trades"]),
            "no_trade_orders": results["no_trade"]["cycle"].get("orders_created", 0),
            "stale_orders": results["stale"]["cycle"].get("orders_created", 0),
            "kill_switch_orders": results["kill_switch"]["cycle"].get("orders_created", 0),
            "kill_switch_broker_calls": results["kill_switch"]["broker_calls"],
            "exception_orders": results["provider_exception"]["cycle"].get("orders_created", 0),
        },
    }
    payload["evidence_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="G-5 PAPER end-to-end evidence.")
    parser.add_argument(
        "--out",
        default=str(REPO_ROOT / "docs" / "audit" / "runs" / "g5-paper-e2e"),
        help="Evidence directory (default: docs/audit/runs/g5-paper-e2e).",
    )
    parser.add_argument(
        "--ledger",
        default=str(DEFAULT_LEDGER),
        help="Controlled admission fixture (not a production ledger).",
    )
    args = parser.parse_args(argv)
    out_dir = Path(args.out)
    payload = asyncio.run(run_all(out_dir, Path(args.ledger)))
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "evidence.json").write_text(
        json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload["summary"], indent=2, default=str))
    print(f"evidence written to {out_dir / 'evidence.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
