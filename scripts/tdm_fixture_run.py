"""Build a synthetic run that exercises the PAPER *execution* states.

The live market run used in WP-TDM-05 (``tdm-live-20261024``) legitimately ends in
``NO_TRADE`` on every asset, so an independent verifier can only see acceptance and
fill semantics if some run actually contains them. This script produces such a run
through the **real runtime path** (``DecisionEngine`` → ``IndependentVerifier`` →
``RiskManager`` → ``PaperBroker`` → ``DecisionTraceStore``), with two substitutions
that make it reproducible and explicitly *not* a market claim:

* the admission ledger is synthetic (``gross_bps=300`` so the cost barrier passes);
* the market reader and strategy families are deterministic fixtures.

The resulting run is served with ``--fixture`` so the UI reports
``SIMULATED_FIXTURE`` and never ``LIVE_DATA``. It is coverage for the verifier, not
evidence that the venue produced a fill.

    python scripts/tdm_fixture_run.py --out .tmp/tdm-sim/runs
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from tests.unit.autonomous.helpers import (  # noqa: E402
    make_admitted_ledger,
    make_runtime,
)
from tests.unit.monitor.test_runtime_e2e import ExplodingBroker  # noqa: E402
from trading_bot.autonomous.reporting import write_run_report  # noqa: E402


def build(run_root: Path, run_id: str, *, broker: object | None = None) -> Path:
    run_dir = run_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    runtime, _scanner, _broker = make_runtime(
        run_dir=run_dir,
        ledger=make_admitted_ledger(gross_bps=300.0),
        broker=broker,
    )
    summary = asyncio.run(runtime.run(cycles=1))
    write_run_report(summary, run_dir)
    totals = summary.totals()
    print(
        f"[tdm-fixture-run] {run_id}: paper_trades={totals.get('paper_trades')} "
        f"orders={totals.get('orders_created')} no_trades={totals.get('no_trades')} "
        f"failures={totals.get('runtime_failures')}"
    )
    return run_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=".tmp/tdm-sim/runs")
    args = parser.parse_args()
    run_root = Path(args.out)
    if not run_root.is_absolute():
        run_root = REPO_ROOT / run_root
    run_root.mkdir(parents=True, exist_ok=True)
    build(run_root, "tdm-sim-filled")
    build(run_root, "tdm-sim-order-rejected", broker=ExplodingBroker())
    print(f"[tdm-fixture-run] wrote {run_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
