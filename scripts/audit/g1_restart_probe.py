"""G-1 probe — boot the real autonomous runtime over an existing run directory.

This is the cross-process half of the G-1 evidence. It is deliberately a
*separate entrypoint*, not a helper imported by a test, because the claim is
about what a new **operating-system process** does: the marker on disk is the
only thing it inherits.

It composes the production runtime with two test doubles that make a false pass
impossible:

* the decision engine is **hostile** — it always returns ``TRADE_PAPER``, so a
  blocked order can only come from the dispatch boundary, never from rule 0;
* the broker is a **counter** — one increment per ``execute_signal`` call.

Usage::

    python scripts/audit/g1_restart_probe.py --run-dir reports/autonomous-paper/run-1

stdout is one JSON object. Exit 0 means the probe ran; the caller asserts the
fields. It never contacts a network and never sends a real order.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]

#: ``trading_bot`` must resolve to the tree this file belongs to. Inserted
#: before any project import; the payload below reports the resolved file so the
#: caller can prove TEST_TARGET == RUNTIME_TARGET instead of trusting it.
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))


class SpyBroker:
    """Counts dispatches; never fills anything."""

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


def _hostile_engine() -> Any:
    from trading_bot.autonomous.contracts import DecisionMode
    from trading_bot.autonomous.decision import DecisionResult

    class _AlwaysTrade:
        version = "hostile"

        def intend(self, request: Any) -> Any:
            return DecisionResult(
                mode=DecisionMode.TRADE_PAPER,
                reason="hostile_intent",
                classification="PAPER_ADMITTED",
                order_authorised=False,
            )

        def decide(self, request: Any) -> Any:
            return DecisionResult(
                mode=DecisionMode.TRADE_PAPER,
                reason="hostile_decision",
                classification="PAPER_ADMITTED",
                order_authorised=True,
                notional_usdt=250.0,
            )

    return _AlwaysTrade()


def build_runtime(run_dir: Path, *, broker: Any) -> Any:
    """Compose the production runtime over deterministic inputs, no network."""
    from tests.unit.autonomous.helpers import (
        BAR_MS,
        FakeSnapshot,
        StaticFamily,
        StaticReader,
        bars,
        make_admitted_ledger,
        risk_manager,
    )
    from trading_bot.autonomous.runtime import AutonomousPaperRuntime

    ledger = make_admitted_ledger(gross_bps=50.0)
    history = {"BTC/USDT": bars("BTC/USDT", 80)}
    snapshot = FakeSnapshot(symbol="BTC/USDT", timestamp=history["BTC/USDT"][-1].timestamp + BAR_MS)

    class _FixedScanner:
        async def run(self) -> list[Any]:
            return [snapshot]

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

    class _Settings:
        class runtime:
            mode = "PAPER"
            exchange_id = "fake"

        class risk:
            kill_switch_enabled = True

    return AutonomousPaperRuntime(
        settings=_Settings(),
        scanner_factory=lambda: _FixedScanner(),
        history_reader=StaticReader(history),
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
        decision_engine=_hostile_engine(),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, help="existing run directory to boot over")
    args = parser.parse_args(argv)

    import trading_bot

    run_dir = Path(args.run_dir).resolve()
    broker = SpyBroker()
    # structlog writes to stdout by default (risk.signal_approved et al.). The
    # probe's contract is "stdout is one JSON object", so the runtime's own
    # output is captured and discarded rather than parsed by the caller.
    with contextlib.redirect_stdout(io.StringIO()):
        runtime = build_runtime(run_dir, broker=broker)
        # Read the gate *before* the first cycle: "restored at construction" is
        # the property, and a value sampled after a cycle could have been set by
        # poll().
        engaged_before_first_cycle = runtime.hot_stop.engaged
        restored = bool(runtime.hot_stop.stats().get("restored"))
        summary = asyncio.run(runtime.run(cycles=1))
    row = summary.cycle_reports[0].assets[0]

    print(
        json.dumps(
            {
                "run_dir": str(run_dir),
                "module_file": str(Path(trading_bot.__file__).resolve()),
                "engaged_before_first_cycle": engaged_before_first_cycle,
                "engaged_after_cycle": runtime.hot_stop.engaged,
                "restored": restored,
                "broker_calls": broker.calls,
                "orders_created": summary.totals()["orders_created"],
                "mode": row.mode.value,
                "risk_verdict": row.risk_verdict,
                "control_path": str(runtime.hot_stop.control_path),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
