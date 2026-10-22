"""WP-EDGE-01 runner — execute the campaign and write the required artefacts.

    python scripts/edge01_run.py [--outdir reports/edge-recovery/WP-EDGE-01]

Writes ``STRATEGY_RESULTS.md``, ``STRATEGY_RESULTS.json``, ``TRADES.csv``,
``EQUITY_CURVE.csv``, ``RUN_REPORT.md`` and ``RUN_REPORT.json``.

This is the runtime a reader can reproduce: no network, no credentials, no
orders. It reads the local corpora, runs the three candidates (plus the FVG
ablation) over the pre-registered splits and cost scenarios, and prints the
verdicts so a terminal reader sees the same numbers the artefacts carry.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + "/src")

from trading_bot.research.edge01.campaign import run_campaign, write_artifacts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--outdir", default="reports/edge-recovery/WP-EDGE-01", help="where the artefacts go"
    )
    args = parser.parse_args(argv)

    outdir = Path(args.outdir)
    campaign = run_campaign()
    written = write_artifacts(campaign, outdir)

    for candidate_id, payload in campaign["candidates"].items():
        oos = payload["splits"]["OOS"]["BASE"]
        print(
            f"[{payload['verdict']:>21}] {candidate_id:<22} "
            f"OOS trades={oos['trades']:<4} net={oos['net_usdt']:>10.2f} "
            f"expectancy={oos['expectancy_usdt'] if oos['expectancy_usdt'] is not None else float('nan'):>9.2f} "
            f"dd={oos['max_drawdown_pct']:>6.2f}%"
        )
        for reason in payload["verdict_reasons"]:
            print(f"    - {reason}")
    print("artifacts:")
    for name, path in written.items():
        print(f"  {name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
