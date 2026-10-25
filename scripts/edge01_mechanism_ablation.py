"""Run the WP-EDGE-01 mechanism experiments on DEV only.

    python scripts/edge01_mechanism_ablation.py [--experiment h2|h4|all]

* `h2` — entry timing: does the intraday breakout lose money because the entry
  lands too far past the level it breaks? A diagnostic: it changes no rule, it
  re-runs the frozen candidate under the runtime's own risk budget and splits
  the trades the budget let through by their distance to the broken level.
* `h4` — entry volatility: does refusing the least volatile breakouts help
  EDGE-TREND-01? An ablation with a declared GRID of minimum ATR/close
  thresholds; one threshold may be frozen on DEV, never promoted.

Both experiments are DEV only, deterministic, offline, and are verified by a
separate process (`scripts/edge01_mechanism_ablation_verify.py`) that imports
nothing from this package.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trading_bot.research.edge01.campaign import (  # noqa: E402
    run_entry_timing_h2,
    run_vol_filter_h4,
    write_entry_timing_artifacts,
    write_vol_filter_artifacts,
)

#: Where each experiment publishes its evidence. DEV-only artefacts, kept next to
#: the WP run they belong to.
OUTDIRS: dict[str, str] = {
    "h2": "reports/edge-recovery/WP-EDGE-01/entry-timing-h2",
    "h4": "reports/edge-recovery/WP-EDGE-01/vol-filter-h4",
}

RUNNERS = {
    "h2": (run_entry_timing_h2, write_entry_timing_artifacts),
    "h4": (run_vol_filter_h4, write_vol_filter_artifacts),
}


def run_one(name: str, *, root: Path) -> dict[str, object]:
    run, write = RUNNERS[name]
    payload = run()
    outdir = root / OUTDIRS[name]
    written = write(payload, outdir)
    verdict = payload["verdict"]["verdict"]
    print(
        f"[{name}] {payload['run_id']}: {len(written)} artefactos en "
        f"{outdir.relative_to(root)} -> veredicto {verdict}"
    )
    print(f"[{name}] {verdict}: {payload['verdict']['reason']}")
    return {
        "experiment": name,
        "run_id": payload["run_id"],
        "verdict": verdict,
        "artifacts": sorted(written),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", choices=("h2", "h4", "all"), default="all")
    parser.add_argument("--root", default=str(ROOT))
    args = parser.parse_args(argv)

    names = ("h2", "h4") if args.experiment == "all" else (args.experiment,)
    for name in names:
        run_one(name, root=Path(args.root))
    return 0


if __name__ == "__main__":
    sys.exit(main())
