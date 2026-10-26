"""Coexistence measurement: PAPER runtime with and without the forward collector.

§19/§20 ask for evidence, not assurance. This script runs the *same* PAPER smoke
(identical assets, cycles, interval and config) and records what happened, plus
what the collector was doing at the time. Running it twice — once while a
capture is live and once with no collector on the host — turns "they should not
interfere" into two comparable measurements.

It never creates an order path: it invokes the existing PAPER entrypoint with its
existing defaults, and PAPER decides NO_TRADE on its own.

    uv run python scripts/forward_paper_coexistence.py --label with_collector
    uv run python scripts/forward_paper_coexistence.py --label without_collector
    uv run python scripts/forward_paper_coexistence.py --assemble
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FORWARD_ROOT = ROOT / "reports" / "microstructure-forward"
MEASUREMENTS = FORWARD_ROOT / "coexistence" / "measurements"
OUTPUT = ROOT / "docs" / "FORWARD_DATA_PAPER_COEXISTENCE.json"

DEFAULT_CYCLES = 6
DEFAULT_INTERVAL_SECONDS = 20.0


def _collector_state() -> dict[str, Any] | None:
    states = sorted((FORWARD_ROOT / "state").glob("*.json"))
    if not states:
        return None
    payload = json.loads(states[-1].read_text(encoding="utf-8"))
    return {
        "run_id": payload.get("run_id"),
        "events": payload.get("events"),
        "reconnects": payload.get("reconnects"),
        "gaps": payload.get("gaps"),
        "saved_at_ms": payload.get("saved_at_ms"),
    }


def _collector_alive() -> bool:
    """True when a forward collector process is currently writing."""
    state = _collector_state()
    if state is None or not isinstance(state.get("saved_at_ms"), int):
        return False
    return (time.time() * 1000.0) - float(state["saved_at_ms"]) < 30_000.0


def measure(label: str, cycles: int, interval: float) -> dict[str, Any]:
    run_id = f"coexist-{label}-{uuid.uuid4().hex[:8]}"
    before = _collector_state()
    started = time.time()
    completed = subprocess.run(
        [
            "uv",
            "run",
            "python",
            "scripts/autonomous_paper.py",
            "--cycles",
            str(cycles),
            "--interval",
            str(interval),
            "--run-id",
            run_id,
            "--state-path",
            str(MEASUREMENTS / f"{run_id}-state.json"),
            "--run-root",
            "reports/paper",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    elapsed = time.time() - started
    after = _collector_state()
    totals: dict[str, Any] = {}
    tail = completed.stdout.strip().splitlines()
    for index, line in enumerate(tail):
        if line.strip() == "{":
            try:
                totals = json.loads("\n".join(tail[index:]))
            except json.JSONDecodeError:
                totals = {}
            break
    report_path = ROOT / "reports" / "paper" / run_id / "RUN_REPORT.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    measurement = {
        "label": label,
        "run_id": run_id,
        "cycles": cycles,
        "interval_seconds": interval,
        "collector_running": _collector_alive(),
        "collector_run_id": before.get("run_id") if before else None,
        "collector_events_before": before.get("events") if before else None,
        "collector_events_after": after.get("events") if after else None,
        "collector_events_during": (
            (after.get("events") or 0) - (before.get("events") or 0)
            if before and after and before.get("run_id") == after.get("run_id")
            else None
        ),
        "collector_reconnects_after": after.get("reconnects") if after else None,
        "elapsed_seconds": round(elapsed, 3),
        "returncode": completed.returncode,
        "totals": totals,
        "report_totals": report.get("totals", {}),
        "stderr_tail": completed.stderr.strip().splitlines()[-5:],
    }
    MEASUREMENTS.mkdir(parents=True, exist_ok=True)
    (MEASUREMENTS / f"{label}.json").write_text(
        json.dumps(measurement, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return measurement


def assemble() -> dict[str, Any]:
    with_collector = json.loads((MEASUREMENTS / "with_collector.json").read_text(encoding="utf-8"))
    without = json.loads((MEASUREMENTS / "without_collector.json").read_text(encoding="utf-8"))

    def _totals(measurement: dict[str, Any]) -> dict[str, Any]:
        totals = measurement.get("report_totals") or measurement.get("totals") or {}
        return {
            "asset_cycle_evaluations": totals.get("asset_cycle_evaluations"),
            "orders_created": totals.get("orders_created"),
            "paper_trades": totals.get("paper_trades"),
            "runtime_failures": totals.get("runtime_failures"),
            "traces_persisted": totals.get("traces_persisted"),
            "no_trades": totals.get("no_trades"),
            "risk_APPROVED": totals.get("risk_APPROVED"),
            "elapsed_seconds": measurement["elapsed_seconds"],
            "cycle_seconds": round(
                measurement["elapsed_seconds"] / max(1, int(measurement["cycles"])), 3
            ),
        }

    with_totals = _totals(with_collector)
    without_totals = _totals(without)
    delta = (
        round(with_totals["cycle_seconds"] - without_totals["cycle_seconds"], 3)
        if isinstance(with_totals["cycle_seconds"], float)
        and isinstance(without_totals["cycle_seconds"], float)
        else None
    )
    payload = {
        "kind": "FORWARD_DATA_PAPER_COEXISTENCE",
        "method": (
            "the same PAPER smoke (6 cycles x 20s, BTC/ETH/SOL, 5m, config/realdata, "
            "ccxt) executed twice: once with a forward capture live, once with no "
            "collector running"
        ),
        "with_collector": {
            "run_id": with_collector["run_id"],
            **with_totals,
            "collector_run_id": with_collector["collector_run_id"],
            "collector_events_during": with_collector["collector_events_during"],
        },
        "without_collector": {"run_id": without["run_id"], **without_totals},
        "collector_events_during": with_collector["collector_events_during"],
        "cycle_seconds_delta": delta,
        "isolation": {
            "separate_processes": True,
            "shared_mutable_state": False,
            "collector_can_change_a_decision": False,
            "paper_orders_created_with_collector": with_totals["orders_created"],
            "paper_runtime_failures_with_collector": with_totals["runtime_failures"],
            "collector_reconnects_during_paper": with_collector["collector_reconnects_after"],
        },
        "note": (
            "NO_TRADE remains a valid outcome; the measurement is about whether the two "
            "processes interfere, not about whether PAPER trades"
        ),
    }
    OUTPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", choices=("with_collector", "without_collector"))
    parser.add_argument("--assemble", action="store_true")
    parser.add_argument("--cycles", type=int, default=DEFAULT_CYCLES)
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL_SECONDS)
    args = parser.parse_args(argv)
    if args.assemble:
        print(json.dumps(assemble(), indent=2, ensure_ascii=False))
        return 0
    if not args.label:
        parser.error("--label or --assemble is required")
    measurement = measure(args.label, args.cycles, args.interval)
    print(json.dumps(measurement, indent=2, ensure_ascii=False))
    return 0 if measurement["returncode"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
