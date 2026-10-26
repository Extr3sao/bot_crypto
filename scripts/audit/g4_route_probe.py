"""G-4 probe — which reachable routes touch a protected sink?

The probe is deliberately independent of the test suite. It builds the same
components the paper launcher composes, writes the real ``KILL_SWITCH`` marker
with the real control-file primitive, and counts calls at the broker. It also
runs ``trading-bot run --demo`` (and ``--mode paper --auto-trade``) in-process
with the paper cycle, the paper broker and every exchange client replaced by
counting sentinels, so a route that reaches one of them cannot pass silently.

Two modes, both meaningful:

* without ``--attach-gate`` the probe exercises a tree that has no paper gate.
  A marker present in the run directory is ignored and one order is created.
  This is the BEFORE evidence for G-4.
* with ``--attach-gate`` the probe passes a real :class:`HotStopGate` to the
  engine and asserts the boundary. This is the AFTER evidence.

No exchange is contacted, no credential is read and no live order is built.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

TS0 = 1_700_000_000_000
SYMBOL = "BTC/USDT"


def _bars(n: int = 60) -> list[Any]:
    from trading_bot.market_data.types import OHLCV

    return [
        OHLCV(
            symbol=SYMBOL,
            timestamp=TS0 + i * 60_000,
            open=100.0 + i,
            high=101.0 + i,
            low=99.0 + i,
            close=100.5 + i,
            volume=1_000.0,
        )
        for i in range(n)
    ]


class _StaticFamily:
    family_name = "ema_crossover"

    def generate(self, candles: Any, indicators: Any, features: Any = None, **kw: Any) -> list[Any]:
        from trading_bot.research.types import AlphaSignal

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


class _CountingBroker:
    """The small surface ``PaperCycleEngine`` needs, with call counters."""

    def __init__(self) -> None:
        from trading_bot.paper.broker import PaperBroker

        self._delegate = PaperBroker(equity=10_000.0)
        self.execute_calls = 0
        self.close_calls = 0
        self.positions = self._delegate.positions
        self.equity = self._delegate.equity

    def execute_signal(self, signal: Any) -> Any:
        self.execute_calls += 1
        return self._delegate.execute_signal(signal)

    def close_position(self, *args: Any, **kwargs: Any) -> Any:
        self.close_calls += 1
        return self._delegate.close_position(*args, **kwargs)


def _risk() -> Any:
    from trading_bot.config.risk import DefensiveBlocks, Risk
    from trading_bot.risk.manager import RiskManager

    policy = Risk.model_construct(
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
    return RiskManager(risk=policy, equity=10_000.0)


def _engine(broker: Any, hot_stop: Any | None) -> Any:
    from trading_bot.execution.idempotency import IdempotencyGuard
    from trading_bot.paper.paper_cycle import PaperCycleEngine
    from trading_bot.research.asset_intelligence.registry import CryptoAssetAgentRegistry
    from trading_bot.research.strategy_router import StrategyRouter

    kwargs: dict[str, Any] = {
        "asset_registry": CryptoAssetAgentRegistry(),
        "router": StrategyRouter(),
        "strategy_map": {
            "ema_crossover": {
                "family": "ema_crossover",
                "regimes": [],
                "direction": "BOTH",
                "enabled": True,
                "status": "PAPER_ACTIVE",
                "priority": 0.0,
            }
        },
        "families": {"ema_crossover": _StaticFamily()},
        "risk_manager": _risk(),
        "broker": broker,
        "indicator_fn": lambda candles: {},
        "idempotency": IdempotencyGuard(),
    }
    if hot_stop is not None:
        kwargs["hot_stop"] = hot_stop
    return PaperCycleEngine(**kwargs)


def _paper_cycle(*, marker: bool, process_stop: bool, attach_gate: bool) -> dict[str, Any]:
    from trading_bot.autonomous.hot_stop import HotStopGate, write_control_file
    from trading_bot.domain.enums.kill_switch import KillSwitchAction, KillSwitchState
    from trading_bot.paper.kill_switch_v2 import KillSwitch

    run_dir = Path(tempfile.mkdtemp(prefix="g4-paper-"))
    if marker:
        # The same atomic primitive the ``kill-switch`` CLI uses, not a test
        # approximation: the probe must exercise the authority an operator has.
        write_control_file(run_dir / "KILL_SWITCH", "g4 probe operator stop")

    switch = KillSwitch()
    if process_stop:
        switch.activate(KillSwitchAction.USER, target=KillSwitchState.HALTED)
    gate = HotStopGate(kill_switch=switch, run_dir=run_dir) if attach_gate else None

    broker = _CountingBroker()
    gate_supported = True
    try:
        engine = _engine(broker, gate)
    except TypeError as exc:
        if "hot_stop" not in str(exc):
            raise
        gate_supported = False
        engine = _engine(broker, None)
        gate = None

    counts = engine.run_cycle_sync({SYMBOL: _bars()}, {SYMBOL: TS0 + 59 * 60_000})
    payload = counts.to_dict()
    return {
        "scenario": "paper_cycle",
        "marker": marker,
        "process_stop": process_stop,
        "attach_gate": attach_gate,
        "gate_supported": gate_supported,
        "gate_engaged": bool(getattr(gate, "engaged", False)),
        "gate_stats": gate.stats() if gate is not None else None,
        "broker_execute_calls": broker.execute_calls,
        "broker_close_calls": broker.close_calls,
        "orders_created": payload["orders_created"],
        "hot_stop_blocked": payload.get("hot_stop_blocked", 0),
        "rejections": payload["rejections"],
    }


def _demo_run(mode: str, auto_trade: bool) -> dict[str, Any]:
    """Run the CLI with every sink replaced by a sentinel."""

    import contextlib
    import io
    from unittest.mock import patch

    import trading_bot.app as app
    from trading_bot.paper import paper_cycle

    calls = {
        "paper_cycle": 0,
        "paper_broker": 0,
        "futures_client": 0,
        "spot_client": 0,
        "live_source": 0,
    }
    original_cycle = paper_cycle.PaperCycleEngine.run_cycle_sync

    def counting_cycle(self: Any, *args: Any, **kwargs: Any) -> Any:
        calls["paper_cycle"] += 1
        return original_cycle(self, *args, **kwargs)

    class RefusingClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise AssertionError("an exchange client was constructed")

    class RefusingFutures(RefusingClient):
        pass

    class RefusingSpot(RefusingClient):
        pass

    def refusing_source(*args: Any, **kwargs: Any) -> Any:
        calls["live_source"] += 1
        raise AssertionError("the live scanner source was resolved")

    argv = ["run", "--once", "--mode", mode, "--loop-seconds", "1"]
    if auto_trade:
        argv.append("--auto-trade")

    stdout = io.StringIO()
    stderr = io.StringIO()
    exit_code: int | None = None
    error: str | None = None
    with (
        patch.object(paper_cycle.PaperCycleEngine, "run_cycle_sync", counting_cycle),
        patch.object(app, "BitunixFuturesClient", RefusingFutures),
        patch.object(app, "BitunixSpotClient", RefusingSpot),
        patch("trading_bot.market_data.wiring.resolve_scanner_source", refusing_source),
        contextlib.redirect_stdout(stdout),
        contextlib.redirect_stderr(stderr),
    ):
        from trading_bot.paper.broker import PaperBroker

        original_execute = PaperBroker.execute_signal

        def counting_execute(self: Any, signal: Any) -> Any:
            calls["paper_broker"] += 1
            return original_execute(self, signal)

        with patch.object(PaperBroker, "execute_signal", counting_execute):
            try:
                exit_code = int(app.main(argv))
            except BaseException as exc:  # a route that refuses loudly is evidence too
                error = f"{type(exc).__name__}: {exc}"
                traceback.print_exc(file=stderr)

    return {
        "scenario": "demo_run",
        "mode": mode,
        "auto_trade": auto_trade,
        "exit_code": exit_code,
        "error": error,
        "calls": calls,
        "stdout_tail": stdout.getvalue()[-600:],
        "stderr_tail": stderr.getvalue()[-600:],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        choices=[
            "demo-paper",
            "demo-live-flag",
            "paper-marker",
            "paper-clean",
            "paper-process-stop",
        ],
        required=True,
    )
    parser.add_argument("--attach-gate", action="store_true")
    parser.add_argument("--json", default=None)
    args = parser.parse_args(argv)

    if args.scenario == "demo-paper":
        result = _demo_run("paper", auto_trade=False)
    elif args.scenario == "demo-live-flag":
        result = _demo_run("paper", auto_trade=True)
    elif args.scenario == "paper-marker":
        result = _paper_cycle(marker=True, process_stop=False, attach_gate=args.attach_gate)
    elif args.scenario == "paper-clean":
        result = _paper_cycle(marker=False, process_stop=False, attach_gate=args.attach_gate)
    else:
        result = _paper_cycle(marker=False, process_stop=True, attach_gate=args.attach_gate)

    text = json.dumps(result, indent=2, default=str)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
