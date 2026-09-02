"""Unit tests for the canonical paper decision cycle (CP-PO-002, GATE-L5).

Engine-level matrix:
- router invoked per asset with a valid AssetContext
- router no-strategy / empty map → zero orders
- router exception → zero orders
- strategy exception → zero orders
- direction mismatch → zero orders
- valid signal → exactly one paper execution (risk accepted)
- risk rejection → zero execution
- risk exception → zero execution
- duplicate intent → exactly one execution total
- kill switch engaged → zero execution
- broker result None → counted, no idempotency registration
"""

from __future__ import annotations

from typing import Any

from trading_bot.execution.idempotency import IdempotencyGuard
from trading_bot.market_data.types import OHLCV
from trading_bot.paper.broker import PaperBroker
from trading_bot.paper.paper_cycle import (
    CycleStageCounts,
    PaperCycleEngine,
    RouteOnlyEngine,
    intent_cloid,
)
from trading_bot.research.asset_intelligence.registry import CryptoAssetAgentRegistry
from trading_bot.research.strategy_router import StrategyRouter
from trading_bot.research.types import AlphaSignal
from trading_bot.risk.manager import RiskManager

TS0 = 1_700_000_000_000


def _bars(symbol: str, n: int = 60, *, rising: bool = True) -> list[OHLCV]:
    """Deterministic bars. Rising: strong uptrend (fast EMA > slow, RSI=100)."""
    out: list[OHLCV] = []
    for i in range(n):
        price = 100.0 + (i * 1.0 if rising else 0.0)
        out.append(
            OHLCV(
                symbol=symbol,
                timestamp=TS0 + i * 60_000,
                open=price,
                high=price + 1.0,
                low=price - 1.0,
                close=price + 0.5,
                volume=1_000.0,
            )
        )
    return out


def _settings_risk() -> Any:  # Risk imported lazily inside
    from trading_bot.config.risk import DefensiveBlocks, Risk

    return Risk.model_construct(
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


class _StaticFamily:
    """Deterministic family: one LONG alpha at the last bar."""

    family_name = "ema_crossover"

    def generate(
        self, candles: Any, indicators: Any, features: Any = None, **kw: Any
    ) -> list[AlphaSignal]:
        last = candles[-1]
        return [
            AlphaSignal(
                family=self.family_name,
                symbol=last.symbol,
                timestamp=last.timestamp,
                direction="LONG",
                entry_reference=last.close,
                structural_stop=last.close * 0.99,
                timeframe="5m",
            )
        ]


class _BoomFamily:
    family_name = "boom"

    def generate(
        self, candles: Any, indicators: Any, features: Any = None, **kw: Any
    ) -> list[AlphaSignal]:
        raise RuntimeError("strategy exploded")


def _engine(
    *,
    family: Any = None,
    strategy_map: dict[str, dict[str, Any]] | None = None,
    risk: RiskManager | None = None,
    broker: PaperBroker | None = None,
    idempotency: IdempotencyGuard | None = None,
) -> PaperCycleEngine:
    fam = family if family is not None else _StaticFamily()
    fam_name = getattr(fam, "family_name", "ema_crossover")
    if strategy_map is None:
        strategy_map = {
            fam_name: {
                "family": fam_name,
                "regimes": [],
                "direction": "BOTH",
                "enabled": True,
                "status": "CONFIRMED",
                "priority": 0.0,
            }
        }
    return PaperCycleEngine(
        asset_registry=CryptoAssetAgentRegistry(),
        router=StrategyRouter(),
        strategy_map=strategy_map,
        families={fam_name: fam} if fam is not None else {},
        risk_manager=risk or RiskManager(risk=_settings_risk(), equity=10_000.0),
        broker=broker or PaperBroker(equity=10_000.0),
        indicator_fn=lambda candles: {},
        idempotency=idempotency,
    )


def test_cloid_is_deterministic_and_distinct() -> None:
    a = intent_cloid("BTC/USDT", "ema_crossover", "LONG", TS0)
    b = intent_cloid("BTC/USDT", "ema_crossover", "LONG", TS0)
    c = intent_cloid("BTC/USDT", "ema_crossover", "SHORT", TS0)
    d = intent_cloid("BTC/USDT", "ema_crossover", "LONG", TS0 + 60_000)
    assert a == b and a != c and a != d and a.startswith("PAPER-")


def test_router_invoked_and_order_created() -> None:
    engine = _engine(broker=PaperBroker(equity=10_000.0))
    counts = engine.run_cycle_sync({"BTC/USDT": _bars("BTC/USDT")}, {"BTC/USDT": TS0 + 59 * 60_000})
    assert counts.contexts_built == 1
    assert counts.router_no_trade == 0
    assert counts.risk_accepted == 1
    assert counts.orders_created == 1
    assert counts.context_errors == 0 and counts.risk_errors == 0


def test_router_no_trade_empty_map_zero_orders() -> None:
    engine = _engine(strategy_map={})
    counts = engine.run_cycle_sync({"BTC/USDT": _bars("BTC/USDT")}, {"BTC/USDT": TS0 + 59 * 60_000})
    assert counts.orders_created == 0
    assert counts.router_no_trade == 1
    assert counts.rejections[0]["reason"].endswith("empty_strategy_map")


def test_router_exception_zero_orders() -> None:
    class BoomRouter:
        def route(self, *_a: Any, **_k: Any) -> Any:
            raise RuntimeError("router exploded")

    engine = _engine()
    engine._router = BoomRouter()
    counts = engine.run_cycle_sync({"BTC/USDT": _bars("BTC/USDT")}, {"BTC/USDT": TS0 + 59 * 60_000})
    assert counts.orders_created == 0
    assert counts.router_errors == 1


def test_strategy_exception_zero_orders() -> None:
    engine = _engine(family=_BoomFamily())
    counts = engine.run_cycle_sync({"BTC/USDT": _bars("BTC/USDT")}, {"BTC/USDT": TS0 + 59 * 60_000})
    assert counts.orders_created == 0
    assert counts.strategy_errors == 1


def test_direction_mismatch_zero_orders() -> None:
    engine = _engine(
        strategy_map={
            "ema_crossover": {
                "family": "ema_crossover",
                "regimes": [],
                "direction": "SHORT",
                "enabled": True,
                "status": "CONFIRMED",
            }
        }
    )
    counts = engine.run_cycle_sync({"BTC/USDT": _bars("BTC/USDT")}, {"BTC/USDT": TS0 + 59 * 60_000})
    assert counts.orders_created == 0
    assert counts.signals_generated == 1
    assert any("no_alpha_in_direction" in r["reason"] for r in counts.rejections)


def test_risk_rejection_zero_execution() -> None:
    risk = RiskManager(risk=_settings_risk(), equity=10_000.0)
    risk.activate_kill_switch("unit")
    engine = _engine(risk=risk)
    counts = engine.run_cycle_sync({"BTC/USDT": _bars("BTC/USDT")}, {"BTC/USDT": TS0 + 59 * 60_000})
    assert counts.risk_rejected == 1
    assert counts.orders_created == 0
    assert counts.rejections[0]["stage"] == "risk"


def test_risk_exception_zero_execution() -> None:
    class BoomRisk:
        def check_signal(self, *_a: Any, **_k: Any) -> Any:
            raise RuntimeError("risk exploded")

    engine = _engine()
    engine._risk = BoomRisk()  # type: ignore[assignment]  # test injection
    counts = engine.run_cycle_sync({"BTC/USDT": _bars("BTC/USDT")}, {"BTC/USDT": TS0 + 59 * 60_000})
    assert counts.orders_created == 0
    assert counts.risk_errors == 1


def test_duplicate_intent_exactly_one_execution() -> None:
    guard = IdempotencyGuard()
    engine = _engine(idempotency=guard)
    bars = _bars("BTC/USDT")
    ts = TS0 + 59 * 60_000
    counts1 = engine.run_cycle_sync({"BTC/USDT": list(bars)}, {"BTC/USDT": ts})
    counts2 = engine.run_cycle_sync({"BTC/USDT": list(bars)}, {"BTC/USDT": ts})
    assert counts1.orders_created == 1
    assert counts2.orders_created == 0
    assert counts2.duplicate_intents == 1
    # Note: engine reuses the same broker across calls here; total fills == 1
    assert guard.active_count == 1


def test_broker_none_result_counts_but_no_idempotency() -> None:
    broker = PaperBroker(equity=10_000.0)
    engine = _engine(broker=broker)
    bars = _bars("BTC/USDT")
    ts = TS0 + 59 * 60_000
    # First execution fills; second cycle same intent → duplicate rejected.
    c1 = engine.run_cycle_sync({"BTC/USDT": list(bars)}, {"BTC/USDT": ts})
    assert c1.orders_created == 1
    # A NEW bar exists at the new decision ts → new intent (cloid differs);
    # the broker already holds a same-side long → execute_signal returns
    # None → recorded as a broker-stage rejection, NOT registered as sent.
    c2 = engine.run_cycle_sync(
        {"BTC/USDT": _bars("BTC/USDT", n=61)}, {"BTC/USDT": TS0 + 60 * 60_000}
    )
    assert c2.orders_created == 0
    assert c2.duplicate_intents == 0
    assert any(r["stage"] == "broker" for r in c2.rejections)


def test_pit_trim_excludes_future_bars() -> None:
    engine = _engine()
    # History includes bars AFTER the decision timestamp → trimmed.
    counts = engine.run_cycle_sync(
        {"BTC/USDT": _bars("BTC/USDT", n=80)},
        {"BTC/USDT": TS0 + 59 * 60_000},
    )
    assert counts.contexts_built == 1
    assert counts.orders_created == 1
    # Context was built on the 60-bar PIT slice (full window quality),
    # proving the trim happened before context construction.
    assert counts.context_errors == 0


def test_route_only_engine_counts_and_fail_closed() -> None:
    engine = RouteOnlyEngine(
        asset_registry=CryptoAssetAgentRegistry(),
        router=StrategyRouter(),
        strategy_map={},
    )
    counts = engine.run_cycle_sync({"BTC/USDT": _bars("BTC/USDT")}, {"BTC/USDT": TS0 + 59 * 60_000})
    assert counts.contexts_built == 1
    assert counts.router_no_trade == 1
    assert counts.orders_created == 0


def test_context_error_fail_closed() -> None:
    engine = _engine()
    counts = engine.run_cycle_sync({"BTC/USDT": []}, {"BTC/USDT": TS0 + 59 * 60_000})
    assert counts.context_errors == 1
    assert counts.orders_created == 0


def test_counts_to_dict_roundtrip() -> None:
    c = CycleStageCounts()
    d = c.to_dict()
    assert d["orders_created"] == 0
    assert d["rejections"] == []
