"""Run the WP-EDGE-01 closure experiments.

    python scripts/edge01_closure_experiments.py [--experiment h6|oos|all]

* `h6` — the retest entry: the SAME frozen EDGE-INTRA-01 signals executed three
  ways (frozen market intent, plan crossed at market, plan rested as a limit at the
  broken level). The ruleset is untouched; what changes is the execution, and the
  orders that never filled are published as their own outcome.
* `oos` — the out-of-sample review of the frozen EDGE-TREND-01 4h ruleset: the
  portfolio and three single-asset books on DEV/VAL/OOS, against buy & hold, broken
  down by asset, calendar period and both regime labels, judged against an explicit
  PAPER gate frozen before the decomposition ran.

Both are deterministic, offline and DEV-declared; both are verified by a separate
process (`scripts/edge01_closure_verify.py`) that imports nothing from the package.
Neither is wired into the PAPER runtime and neither promotes anything.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trading_bot.research.edge01.closure import (  # noqa: E402
    run_oos_trend,
    run_retest_h6,
    write_oos_trend_artifacts,
    write_retest_h6_artifacts,
)

OUTDIRS: dict[str, str] = {
    "h6": "reports/edge-recovery/WP-EDGE-01/retest-h6",
    "oos": "reports/edge-recovery/WP-EDGE-01/oos-trend-4h",
}

RUNNERS = {
    "h6": (run_retest_h6, write_retest_h6_artifacts),
    "oos": (run_oos_trend, write_oos_trend_artifacts),
}


def run_one(name: str, *, root: Path) -> dict[str, object]:
    run, write = RUNNERS[name]
    payload = run()
    outdir = root / OUTDIRS[name]
    written = write(payload, outdir)
    verdict = payload["verdict"]["verdict"]
    print(f"[{name}] {payload['run_id']}: {len(written)} artefactos en {outdir.relative_to(root)}")
    if name == "h6":
        exp = payload["experiment"]
        primary = payload["runs"][f"{exp['primary_window']}:BASE"]["arms"]
        print(f"[{name}] {'rama':<15} {'ops':>5} {'neto':>12} {'expectativa':>13} {'fill rate':>10}")
        for arm_name in ("frozen_market", "plan_market", "plan_limit"):
            arm = primary[arm_name]
            rate = arm["fill_rate"]
            print(
                f"[{name}] {arm_name:<15} {arm['trades']:>5} {arm['net_usdt']:>12,.2f} "
                f"{(arm['expectancy_usdt'] or 0.0):>13,.4f} "
                f"{('n/a' if rate is None else f'{rate:.2%}'):>10}"
            )
        print(f"[{name}] ordenes: {primary['plan_limit']['orders_by_outcome']}")
        for window, block in payload["confirmation"].items():
            print(
                f"[{name}] confirmacion {window}: neto {block['variant_net_usdt']:,.2f} vs "
                f"{block['baseline_net_usdt']:,.2f} (delta {block['net_delta_usdt']:+,.2f}), "
                f"fill rate {block['fill_rate']:.2%}"
            )
    else:
        for key in ("DEV:BASE", "VAL:BASE", "OOS:BASE", "OOS:2X_FEES"):
            run_block = payload["runs"][key]
            combined = run_block["combined"]
            print(
                f"[{name}] {key:<12} trades={combined['trades']:<4} "
                f"net={combined['net_usdt']:>10,.2f} expectancy="
                f"{(combined['expectancy_usdt'] or 0.0):>9,.4f} dd={combined['max_drawdown_pct']:>6,.2f}%"
            )
        print(f"[{name}] admision del WP: {payload['wp_admission']['verdict']}")
    print(f"[{name}] VEREDICTO: {verdict}")
    print(f"[{name}]   {payload['verdict']['reason'] if name == 'h6' else payload['verdict']['reasons']}")
    return {
        "experiment": name,
        "run_id": payload["run_id"],
        "verdict": verdict,
        "artifacts": sorted(written),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", choices=("h6", "oos", "all"), default="all")
    parser.add_argument("--root", default=str(ROOT))
    args = parser.parse_args(argv)

    names = ("h6", "oos") if args.experiment == "all" else (args.experiment,)
    for name in names:
        run_one(name, root=Path(args.root))
    return 0


if __name__ == "__main__":
    sys.exit(main())
