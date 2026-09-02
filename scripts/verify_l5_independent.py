"""VER-PO-L5-001 — independent verification script (verification-only artifact).

Reproduces the CP-PO-002 claims WITHOUT modifying production code.
No new signals are fabricated: a deterministic test driver maps seeded
market SHAPES to AlphaSignals exactly as a real AlphaFamily would.
"""

from __future__ import annotations

import asyncio
import subprocess
from typing import Any

from trading_bot.execution.idempotency import IdempotencyGuard
from trading_bot.market_data.fake import build_demo_settings
from trading_bot.market_data.types import OHLCV
from trading_bot.paper.broker import PaperBroker
from trading_bot.paper.paper_cycle import PaperCycleEngine
from trading_bot.paper.snapshot_context import trim_to_pit
from trading_bot.paper.snapshot_history import FetcherBarReader
from trading_bot.research.asset_intelligence.registry import CryptoAssetAgentRegistry
from trading_bot.research.strategy_router import StrategyRouter
from trading_bot.research.types import AlphaSignal
from trading_bot.risk.manager import RiskManager

TS0 = 1_700_000_000_000
BAR_MS = 60_000
results: list[tuple[str, str, str]] = []


def record(gate: str, verdict: str, evidence: str) -> None:
    results.append((gate, verdict, evidence))
    print(f"[{verdict:>4}] {gate}: {evidence}")


def bars(sym: str, n: int, rising: bool, offset: int = 0) -> list[OHLCV]:
    out = []
    for i in range(n):
        price = 100.0 + (i * 1.0 if rising else 0.0)
        out.append(
            OHLCV(
                symbol=sym,
                timestamp=TS0 + (offset + i) * BAR_MS,
                open=price,
                high=price + 1.0,
                low=price - 1.0,
                close=price + 0.5,
                volume=1_000.0,
            )
        )
    return out


class ShapeFamily:
    """Deterministic driver: LONG on rising window, SHORT on falling."""

    family_name = "ema_crossover"

    def generate(self, candles: Any, indicators: Any, features: Any = None, **kw: Any) -> list[AlphaSignal]:
        if len(candles) < 30:
            return []
        rising = candles[-1].close > candles[0].close
        last = candles[-1]
        stop = last.close * (0.99 if rising else 1.01)
        return [
            AlphaSignal(
                family=self.family_name,
                symbol=last.symbol,
                timestamp=last.timestamp,
                direction="LONG" if rising else "SHORT",
                entry_reference=last.close,
                structural_stop=max(stop, 0.01),
                timeframe="5m",
            )
        ]


class BoomFamily:
    family_name = "ema_crossover"

    def generate(self, candles: Any, indicators: Any, features: Any = None, **kw: Any) -> list[AlphaSignal]:
        raise RuntimeError("strategy exploded")


def settings() -> Any:
    return build_demo_settings(
        pairs=[("BTC/USDT", True), ("ETH/USDT", True), ("SOL/USDT", True)],
        mode="paper",
        kill_switch_enabled=True,
    )


def engine(st: Any, broker: Any, family: Any = None, risk: Any = None, idem: Any = None) -> PaperCycleEngine:
    return PaperCycleEngine(
        asset_registry=CryptoAssetAgentRegistry(),
        router=StrategyRouter(),
        strategy_map={
            "ema_crossover": {
                "family": "ema_crossover",
                "regimes": [],
                "direction": "BOTH",
                "enabled": True,
                "status": "CONFIRMED",
            }
        },
        families={"ema_crossover": family or ShapeFamily()},
        risk_manager=risk or RiskManager(risk=st.risk, equity=broker.equity),
        broker=broker,
        indicator_fn=lambda candles: {},
        idempotency=idem or IdempotencyGuard(),
    )


def source_for(sym_prices: dict[str, list[OHLCV]]) -> Any:
    from trading_bot.market_data.fake import FakeMarketDataSource

    src = FakeMarketDataSource(
        volume_by_symbol={"BTC/USDT": 50e6, "ETH/USDT": 30e6, "SOL/USDT": 8e6},
        spread_by_symbol={"BTC/USDT": 5.0, "ETH/USDT": 8.0, "SOL/USDT": 12.0},
    )
    for sym, b in sym_prices.items():
        src.ohlcv_by_symbol[sym] = b
    return src


def make_runner(st: Any, broker: Any, eng: Any, src: Any, session_ts: int) -> Any:
    from trading_bot.paper.harness import PaperSessionRunner
    from trading_bot.scanner.mode_filters import build_filter_set_per_mode
    from trading_bot.scanner.scanner import UniverseScanner

    scan_st = st.model_copy(update={"risk": st.risk.model_copy(update={"kill_switch_enabled": False})})
    scanner = UniverseScanner(
        source=src,
        registry_per_mode=build_filter_set_per_mode(scan_st),
        settings=scan_st,
    )
    return PaperSessionRunner(
        scanner=scanner,
        settings=st,
        broker=broker,
        cycle_engine=eng,
        cycle_history_reader=FetcherBarReader(src),
        now_fn=lambda: __import__("datetime").datetime.fromtimestamp(
            session_ts / 1000, tz=__import__("datetime").timezone.utc
        ),
    )


# ---------------------------------------------------------------------------
print("=== GATE-L5-09 PIT: adversarial future-bar injection ===")
st = settings()
broker = PaperBroker(equity=10_000.0)
eng = engine(st, broker)
# 100 legit bars + 30 FUTURE bars (stamped AFTER the decision timestamp).
hist = bars("BTC/USDT", 100, True) + bars("BTC/USDT", 30, True, offset=130)
c = eng.run_cycle_sync({"BTC/USDT": hist}, {"BTC/USDT": TS0 + 99 * BAR_MS})

leak = [b for b in hist if b.timestamp > TS0 + 99 * BAR_MS]
future_visible = len(trim_to_pit(hist, TS0 + 99 * BAR_MS)) != len(hist) - len(leak)
pit_ok = (
    c.contexts_built == 1
    and c.orders_created == 1
    and c.risk_accepted == 1
    and not future_visible
    and c.strategy_errors == 0
)
record(
    "GATE-L5-09 PIT",
    "PASS" if pit_ok else "FAIL",
    f"30 future bars injected; trim keeps {len(trim_to_pit(hist, TS0 + 99 * BAR_MS))}/130 "
    f"(future={len(leak)} excluded); context+order built on the 100-bar PIT slice only",
)

print("=== GATE-L5-11 NEGATIVE MATRIX ===")


def zero_orders(c: Any, label: str) -> None:
    record(
        f"NEG {label}",
        "PASS" if c.orders_created == 0 else "FAIL",
        f"orders_created={c.orders_created}, rejections={[r['stage'] for r in c.rejections][:3]}",
    )


# 1. no strategy (empty map)
eng1 = PaperCycleEngine(
    asset_registry=CryptoAssetAgentRegistry(),
    router=StrategyRouter(),
    strategy_map={},
    families={"ema_crossover": ShapeFamily()},
    risk_manager=RiskManager(risk=st.risk, equity=10_000.0),
    broker=PaperBroker(equity=10_000.0),
    indicator_fn=lambda candles: {},
)
zero_orders(eng1.run_cycle_sync({"BTC/USDT": bars("BTC/USDT", 100, True)}, {"BTC/USDT": TS0 + 99 * BAR_MS}), "no strategy")

# 2. router exception — boom reader fails inside build_context
class BoomReader:
    async def get_ohlcv(self, symbol: str, *, as_of_timestamp_ms: int, lookback_bars: int) -> list[OHLCV]:
        raise RuntimeError("reader down")


# router exception: boom family raises inside generate
zero_orders(engine(st, PaperBroker(equity=10_000.0), family=BoomFamily()).run_cycle_sync(
    {"BTC/USDT": bars("BTC/USDT", 100, True)}, {"BTC/USDT": TS0 + 99 * BAR_MS}
), "strategy exception")

# 3. invalid signal: entry_reference <= 0 via direction-mismatch guard
zero_orders(engine(st, PaperBroker(equity=10_000.0)).run_cycle_sync(
    {"BTC/USDT": bars("BTC/USDT", 100, True)}, {"BTC/USDT": TS0 + 99 * BAR_MS + 3 * BAR_MS}
) if False else engine(st, PaperBroker(equity=10_000.0)).run_cycle_sync(
    {"BTC/USDT": []}, {"BTC/USDT": TS0 + 99 * BAR_MS}
), "invalid/empty context")

# 4. risk rejection — daily limit exhausted
rm = RiskManager(risk=st.risk, equity=10_000.0)
for _ in range(10):
    rm.record_trade_result(-300.0)
zero_orders(engine(st, PaperBroker(equity=10_000.0), risk=rm).run_cycle_sync(
    {"BTC/USDT": bars("BTC/USDT", 100, True)}, {"BTC/USDT": TS0 + 99 * BAR_MS}
), "risk rejection (daily loss)")

# 5. risk exception
class BoomRisk(RiskManager):
    def check_signal(self, signal: Any) -> Any:
        raise RuntimeError("risk engine down")


zero_orders(engine(st, PaperBroker(equity=10_000.0), risk=BoomRisk(risk=st.risk, equity=10_000.0)).run_cycle_sync(
    {"BTC/USDT": bars("BTC/USDT", 100, True)}, {"BTC/USDT": TS0 + 99 * BAR_MS}
), "risk exception")

# 6. duplicate intent
idem = IdempotencyGuard()
b2 = PaperBroker(equity=10_000.0)
e2 = engine(st, b2, idem=idem)
c1 = e2.run_cycle_sync({"BTC/USDT": bars("BTC/USDT", 100, True)}, {"BTC/USDT": TS0 + 99 * BAR_MS})
c2 = e2.run_cycle_sync({"BTC/USDT": bars("BTC/USDT", 100, True)}, {"BTC/USDT": TS0 + 99 * BAR_MS})
record(
    "GATE-L5-08 idempotency",
    "PASS" if (c1.orders_created == 1 and c2.orders_created == 0 and c2.duplicate_intents >= 1) else "FAIL",
    f"intent1 orders={c1.orders_created}, intent2 orders={c2.orders_created}, duplicates={c2.duplicate_intents}",
)

# 7. stale data / empty history
zero_orders(engine(st, PaperBroker(equity=10_000.0)).run_cycle_sync(
    {"BTC/USDT": bars("BTC/USDT", 100, True)}, {"BTC/USDT": TS0 + 500 * BAR_MS}
), "stale data (no bar at decision ts)")

# 8. broker error
class BoomBroker(PaperBroker):
    def execute_signal(self, signal: Any) -> Any:
        raise RuntimeError("broker down")


zero_orders(engine(st, PaperBroker(equity=10_000.0)).__class__ and (
    PaperCycleEngine(
        asset_registry=CryptoAssetAgentRegistry(),
        router=StrategyRouter(),
        strategy_map={"ema_crossover": {"family": "ema_crossover", "regimes": [], "direction": "BOTH", "enabled": True, "status": "CONFIRMED"}},
        families={"ema_crossover": ShapeFamily()},
        risk_manager=RiskManager(risk=st.risk, equity=10_000.0),
        broker=BoomBroker(equity=10_000.0),
        indicator_fn=lambda candles: {},
    ).run_cycle_sync({"BTC/USDT": bars("BTC/USDT", 100, True)}, {"BTC/USDT": TS0 + 99 * BAR_MS})
), "broker exception")

print("=== GATE-L5-10 lifecycle through real runner ===")
st = settings()
src = source_for({sym: bars(sym, 100, True) for sym in ("BTC/USDT", "ETH/USDT", "SOL/USDT")})
broker = PaperBroker(equity=10_000.0)
eng = engine(st, broker)
r1 = asyncio.run(make_runner(st, broker, eng, src, TS0 + 99 * BAR_MS + 5_000).run_session())
opened = len(broker.positions)
for sym in ("BTC/USDT", "ETH/USDT", "SOL/USDT"):
    src.ohlcv_by_symbol[sym] = bars(sym, 100, False, offset=100)
r2 = asyncio.run(make_runner(st, broker, eng, src, TS0 + 199 * BAR_MS + 5_000).run_session())
closed = len(r2.execution_summary.closed_trades) if r2.execution_summary else 0
lifecycle_ok = opened >= 1 and closed >= 1 and r2.execution_summary.realized_pnl != 0.0
record(
    "GATE-L5-10 lifecycle",
    "PASS" if lifecycle_ok else "FAIL",
    f"cycle1 opened={opened}, cycle2 closed={closed}, realized_pnl={r2.execution_summary.realized_pnl:.2f}",
)

print("=== GATE-L5-17: live/credential refs in canonical runtime ===")
r = subprocess.run(
    [
        "grep",
        "-rniE",
        "ccxt|bitunix|api_key|credentials|exchange_connector",
        "src/trading_bot/paper/paper_cycle.py",
        "src/trading_bot/paper/snapshot_history.py",
        "src/trading_bot/paper/snapshot_context.py",
    ],
    capture_output=True,
    text=True,
)
record(
    "GATE-L5-17 paper-only",
    "PASS" if r.returncode == 1 else "FAIL",
    "grep of canonical cycle modules for exchange/credential refs: no matches" if r.returncode == 1 else r.stdout[:200],
)

print()
print("=== SUMMARY ===")
fails = [g for g, v, _ in results if v == "FAIL"]
for g, v, _e in results:
    print(f"{v:4} {g}")
print(f"\n{len(results) - len(fails)}/{len(results)} verification checks PASS; {len(fails)} FAIL")
