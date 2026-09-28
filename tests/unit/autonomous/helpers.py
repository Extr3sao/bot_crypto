"""Deterministic test doubles for the autonomous runtime tests.

Nothing here talks to a network: bars, snapshots, families and the admission
ledger are all explicit inputs, so every test names the exact market shape
and the exact research evidence it is exercising.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from trading_bot.autonomous.admission_ledger import AdmissionLedger
from trading_bot.autonomous.runtime import AutonomousPaperRuntime
from trading_bot.market_data.types import OHLCV

TS0 = 1_700_000_000_000
BAR_MS = 5 * 60 * 1000


def bars(
    symbol: str,
    n: int = 80,
    *,
    rising: bool = True,
    start: int = TS0,
    step: int = BAR_MS,
) -> list[OHLCV]:
    """Deterministic 5m bars: a clean uptrend or a flat series."""
    out: list[OHLCV] = []
    for i in range(n):
        price = 100.0 + (i * 1.0 if rising else 0.0)
        out.append(
            OHLCV(
                symbol=symbol,
                timestamp=start + i * step,
                open=price,
                high=price + 1.0,
                low=price - 1.0,
                close=price + 0.5,
                volume=1_000.0,
            )
        )
    return out


@dataclass
class FakeSnapshot:
    symbol: str
    active: bool = True
    last_price: float = 100.5
    spread_bps: float = 1.0
    volume_24h_usdt: float = 5_000_000.0
    rank_score: float = 0.9
    rejection_reason: str | None = None
    timestamp: int = TS0
    atr_pct: float = 0.5
    volatility_pct: float = 0.5
    sector: str = "major"


@dataclass
class FakeCounters:
    pairs_processed: int = 0
    pairs_active: int = 0
    pairs_inactive: int = 0
    scanner_errors: int = 0


@dataclass
class FakeScanner:
    """Returns fixed snapshots; counts invocations."""

    snapshots: list[FakeSnapshot]
    runs: int = 0
    counters: FakeCounters = field(default_factory=FakeCounters)

    async def run(self) -> list[FakeSnapshot]:
        self.runs += 1
        self.counters = FakeCounters(
            pairs_processed=len(self.snapshots),
            pairs_active=sum(1 for s in self.snapshots if s.active),
        )
        return list(self.snapshots)


class StaticReader:
    """PIT history reader over a fixed bar map (never returns future bars)."""

    def __init__(self, history: dict[str, list[OHLCV]]) -> None:
        self._history = history

    async def get_ohlcv(
        self, symbol: str, *, as_of_timestamp_ms: int, lookback_bars: int
    ) -> list[OHLCV]:
        series = self._history.get(symbol, [])
        window = [b for b in series if b.timestamp <= as_of_timestamp_ms]
        return window[-lookback_bars:]


class BoomReader:
    """Reader that always fails (provider outage)."""

    async def get_ohlcv(
        self, symbol: str, *, as_of_timestamp_ms: int, lookback_bars: int
    ) -> list[OHLCV]:
        raise RuntimeError("provider down")


class StaticFamily:
    """Deterministic family: one LONG alpha on the newest bar."""

    def __init__(self, family_name: str = "ema_crossover", direction: str = "LONG") -> None:
        self.family_name = family_name
        self.direction = direction
        self.calls = 0

    def generate(
        self, candles: Any, indicators: Any, features: Any = None, **kwargs: Any
    ) -> list[Any]:
        self.calls += 1
        if not candles:
            return []
        from trading_bot.research.types import AlphaSignal

        last = candles[-1]
        return [
            AlphaSignal(
                family=self.family_name,
                symbol=last.symbol,
                timestamp=last.timestamp,
                direction=self.direction,  # type: ignore[arg-type]
                entry_reference=last.close,
                structural_stop=last.close * 0.99,
                timeframe="5m",
            )
        ]


class SilentFamily:
    """Family that never emits (flat market)."""

    def __init__(self, family_name: str = "trend") -> None:
        self.family_name = family_name

    def generate(
        self, candles: Any, indicators: Any, features: Any = None, **kwargs: Any
    ) -> list[Any]:
        return []


class BoomFamily:
    """Family that raises (strategy failure must fail closed)."""

    family_name = "boom"

    def generate(
        self, candles: Any, indicators: Any, features: Any = None, **kwargs: Any
    ) -> list[Any]:
        raise RuntimeError("strategy exploded")


def ledger_payload(
    *,
    strategy_id: str = "ema_crossover@5m",
    family: str = "ema_crossover",
    gross_bps: float = 8.0,
    status: str = "COST_KILLED",
    admitted: bool = False,
    trades: int = 1500,
    timeframe: str = "5m",
) -> dict[str, Any]:
    return {
        "strategies": {
            strategy_id: {
                "family": family,
                "status": status,
                "admitted_for_paper": admitted,
                "expected_gross_edge_bps": gross_bps,
                "edge_evidence": {
                    "source_doc": "docs/TEST_EVIDENCE.json",
                    "metric": "gross_bps_per_trade",
                    "value_bps": gross_bps,
                    "knowledge": "ESTIMATED",
                    "sample_trades": trades,
                    "note": "unit-test evidence",
                },
                "source_doc": "docs/TEST_EVIDENCE.json",
                "rationale": f"test ledger entry ({status})",
                "timeframe": timeframe,
                "known": True,
            }
        }
    }


def make_ledger(**kwargs: Any) -> AdmissionLedger:
    return AdmissionLedger.from_dict(ledger_payload(**kwargs), source_path="test-ledger.json")


def make_admitted_ledger(**kwargs: Any) -> AdmissionLedger:
    kwargs.setdefault("status", "PAPER_CANDIDATE")
    kwargs.setdefault("admitted", True)
    kwargs.setdefault("gross_bps", 30.0)
    return make_ledger(**kwargs)


def risk_manager() -> Any:
    from trading_bot.config.risk import DefensiveBlocks, Risk
    from trading_bot.risk.manager import RiskManager

    risk = Risk.model_construct(
        max_risk_per_trade_pct=1.0,
        max_daily_loss_pct=3.0,
        max_weekly_loss_pct=7.0,
        max_daily_drawdown_pct=5.0,
        max_total_drawdown_pct=15.0,
        max_open_positions=5,
        max_trades_per_day=100,
        max_consecutive_losses=3,
        consecutive_loss_cooldown_minutes=60,
        max_asset_exposure_pct=20.0,
        max_total_exposure_pct=80.0,
        min_order_notional_usdt=10.0,
        max_order_notional_usdt=1000.0,
        default_stop_loss_pct=0.5,
        default_take_profit_pct=1.0,
        blocks=DefensiveBlocks.model_construct(),
        kill_switch_enabled=True,
        live_trading_enabled=False,
    )
    return RiskManager(risk=risk, equity=10_000.0)


def make_runtime(
    *,
    run_dir: Path,
    ledger: AdmissionLedger | None = None,
    families: dict[str, Any] | None = None,
    strategy_map: dict[str, dict[str, Any]] | None = None,
    history: dict[str, list[OHLCV]] | None = None,
    snapshots: list[FakeSnapshot] | None = None,
    assets: tuple[str, ...] = ("BTC",),
    broker: Any | None = None,
    reader: Any | None = None,
    timeframe: str = "5m",
    horizon_minutes: float = 5.0,
) -> tuple[AutonomousPaperRuntime, FakeScanner, Any]:
    """Compose a runtime over deterministic inputs (no network)."""
    from trading_bot.config.runtime import TradingMode
    from trading_bot.paper.broker import PaperBroker

    ledger = ledger or make_ledger()
    if strategy_map is None:
        strategy_map = {
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
    if families is None:
        families = {entry.family: StaticFamily(entry.family) for entry in ledger.entries_for_timeframe(timeframe).values()}
    if history is None:
        history = {f"{a}/USDT": bars(f"{a}/USDT", 80) for a in assets}
    if snapshots is None:
        snapshots = [
            FakeSnapshot(symbol=f"{a}/USDT", timestamp=history[f"{a}/USDT"][-1].timestamp)
            for a in assets
        ]

    scanner = FakeScanner(snapshots=snapshots)
    broker = broker if broker is not None else PaperBroker(equity=10_000.0)
    risk = risk_manager()

    class _Settings:
        class runtime:
            mode = TradingMode.PAPER
            exchange_id = "fake"

        class risk:
            kill_switch_enabled = True

    runtime = AutonomousPaperRuntime(
        settings=_Settings(),
        scanner_factory=lambda: scanner,
        history_reader=reader if reader is not None else StaticReader(history),
        broker=broker,
        risk_manager=risk,
        families=families,
        strategy_map=strategy_map,
        ledger=ledger,
        run_dir=run_dir,
        assets=assets,
        timeframe=timeframe,
        horizon_minutes=horizon_minutes,
        size_usd=1_000.0,
    )
    return runtime, scanner, broker
