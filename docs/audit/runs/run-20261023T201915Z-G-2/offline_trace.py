"""Offline reproduction of G-2: operational -> engaged -> NO_ORDER.

Deterministic fixtures, a scripted broker, no network, no real order. The point
is that the *same* runtime object places the first order and refuses the one
after the control file appears, which is what "hot" means.

Run from the repository root:

    PYTHONPATH=src:. python docs/audit/runs/<run-id>/offline_trace.py --json out.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from trading_bot.autonomous.contracts import DecisionMode
from trading_bot.autonomous.decision import DecisionResult
from trading_bot.autonomous.hot_stop import HOT_STOP_FILE_NAME
from trading_bot.autonomous.runtime import AutonomousPaperRuntime
from trading_bot.market_data.types import OHLCV
from trading_bot.paper.kill_switch_v2 import KillSwitch

from tests.unit.autonomous.helpers import (
    BAR_MS,
    FakeSnapshot,
    StaticFamily,
    bars,
    make_admitted_ledger,
    risk_manager,
)


class ScriptedBroker:
    """Counts the one call that would create an order."""

    def __init__(self) -> None:
        self.calls = 0
        self.positions: dict[str, Any] = {}
        self.equity = 10_000.0

    def execute_signal(self, signal: Any) -> Any:
        self.calls += 1
        return object()

    def reconcile_session(self, session_id: str, snapshots: Any, risk: Any) -> Any:
        class _Summary:
            def __init__(self) -> None:
                self.new_closed_trades: list[Any] = []
                self.fills_opened = 0
                self.fills_closed = 0

        return _Summary()


class HostileEngine:
    """Ignores rule 0 on purpose: proves the boundary is not rule 0."""

    version = "hostile"

    def intend(self, request: Any) -> DecisionResult:
        return DecisionResult(
            mode=DecisionMode.TRADE_PAPER,
            reason="hostile_intent",
            classification="PAPER_ADMITTED",
            order_authorised=False,
        )

    def decide(self, request: Any) -> DecisionResult:
        return DecisionResult(
            mode=DecisionMode.TRADE_PAPER,
            reason="hostile_decision",
            classification="PAPER_ADMITTED",
            order_authorised=True,
            notional_usdt=250.0,
        )


class _State:
    def __init__(self, n: int = 90) -> None:
        self.history: dict[str, list[OHLCV]] = {"BTC/USDT": bars("BTC/USDT", n)}

    def advance(self) -> None:
        series = self.history["BTC/USDT"]
        last = series[-1]
        price = last.close + 1.0
        series.append(
            OHLCV(
                symbol=last.symbol,
                timestamp=last.timestamp + BAR_MS,
                open=price,
                high=price + 1.0,
                low=price - 1.0,
                close=price + 0.5,
                volume=1_000.0,
            )
        )

    def last_ts(self) -> int:
        return self.history["BTC/USDT"][-1].timestamp


class _Scanner:
    def __init__(self, state: _State) -> None:
        self._state = state
        self.counters: Any = None

    async def run(self) -> list[FakeSnapshot]:
        return [FakeSnapshot(symbol="BTC/USDT", timestamp=self._state.last_ts() + BAR_MS)]


class _Reader:
    def __init__(self, state: _State) -> None:
        self._state = state

    async def get_ohlcv(
        self, symbol: str, *, as_of_timestamp_ms: int, lookback_bars: int
    ) -> list[OHLCV]:
        window = [
            b for b in self._state.history.get(symbol, []) if b.timestamp <= as_of_timestamp_ms
        ]
        return window[-lookback_bars:]


class _Settings:
    class runtime:
        mode = "PAPER"
        exchange_id = "offline"

    class risk:
        kill_switch_enabled = True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", default=None)
    parser.add_argument("--json", dest="json_path", default=None)
    args = parser.parse_args(argv)

    run_dir = Path(args.run_dir or "./g2-offline-run")
    run_dir.mkdir(parents=True, exist_ok=True)
    for stale in (HOT_STOP_FILE_NAME, "kill_switch_events.jsonl"):
        (run_dir / stale).unlink(missing_ok=True)

    state = _State()
    broker = ScriptedBroker()
    ledger = make_admitted_ledger(gross_bps=50.0)
    strategy_map = {
        strategy_id: {
            "family": entry.family,
            "regimes": [],
            "direction": "BOTH",
            "enabled": True,
            "status": entry.status.value,
            "priority": 0.0,
        }
        for strategy_id, entry in ledger.entries_for_timeframe("5m").items()
    }
    families = {
        entry.family: StaticFamily(entry.family)
        for entry in ledger.entries_for_timeframe("5m").values()
    }

    runtime = AutonomousPaperRuntime(
        settings=_Settings(),
        scanner_factory=lambda: _Scanner(state),
        history_reader=_Reader(state),
        broker=broker,
        risk_manager=risk_manager(),
        families=families,
        strategy_map=strategy_map,
        ledger=ledger,
        run_dir=run_dir,
        assets=("BTC",),
        timeframe="5m",
        horizon_minutes=5.0,
        size_usd=1_000.0,
        decision_engine=HostileEngine(),
        hot_stop=None,  # the runtime builds its own gate over run_dir
    )
    # The gate must be able to close the same authority rule 0 reads. The
    # runtime defaults to the process authority; point this demo at a private
    # switch so the trace cannot disturb a developer's process state.
    runtime.hot_stop.kill_switch = KillSwitch()

    trace: dict[str, Any] = {"engine": "hostile", "run_dir": str(run_dir.resolve())}
    steps: list[dict[str, Any]] = []

    first = asyncio.run(runtime.run_cycle(cycle=1))
    steps.append(
        {
            "step": 1,
            "phase": "operational",
            "gate_engaged": runtime.hot_stop.engaged,
            "mode": first.assets[0].mode.value,
            "order_created": first.assets[0].order_created,
            "broker_calls": broker.calls,
            "switch_state": runtime.hot_stop.kill_switch.state.value,
        }
    )

    (run_dir / HOT_STOP_FILE_NAME).write_text("offline trace: operator stop\n", encoding="utf-8")
    state.advance()
    second = asyncio.run(runtime.run_cycle(cycle=2))
    steps.append(
        {
            "step": 2,
            "phase": "engaged",
            "gate_engaged": runtime.hot_stop.engaged,
            "mode": second.assets[0].mode.value,
            "order_created": second.assets[0].order_created,
            "broker_calls": broker.calls,
            "switch_state": runtime.hot_stop.kill_switch.state.value,
        }
    )

    state.advance()
    third = asyncio.run(runtime.run_cycle(cycle=3))
    steps.append(
        {
            "step": 3,
            "phase": "engaged (second cycle)",
            "gate_engaged": runtime.hot_stop.engaged,
            "mode": third.assets[0].mode.value,
            "order_created": third.assets[0].order_created,
            "broker_calls": broker.calls,
            "switch_state": runtime.hot_stop.kill_switch.state.value,
        }
    )

    trace["steps"] = steps
    trace["events"] = [
        json.loads(line)
        for line in (run_dir / "kill_switch_events.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    trace["gate_stats"] = runtime.hot_stop.stats()
    trace["verdict"] = (
        "OPERATIONAL_THEN_ENGAGED_NO_NEW_ORDER"
        if steps[0]["broker_calls"] == 1
        and steps[1]["broker_calls"] == 1
        and steps[2]["broker_calls"] == 1
        and steps[1]["gate_engaged"]
        else "TRACE_FAILED"
    )

    text = json.dumps(trace, indent=2, sort_keys=True)
    print(text)
    if args.json_path:
        Path(args.json_path).write_text(text + "\n", encoding="utf-8")
    return 0 if trace["verdict"] == "OPERATIONAL_THEN_ENGAGED_NO_NEW_ORDER" else 1


if __name__ == "__main__":
    sys.exit(main())
