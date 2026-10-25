"""WP-EDGE-01 H5 runner — EDGE-INTRA-01 under a risk budget whose drawdown halt is inert.

    python scripts/edge01_risk_ablation.py [--outdir reports/edge-recovery/WP-EDGE-01/risk-budget-h5]

Writes ``RISK_ABLATION.json``, ``RISK_ABLATION.md``, ``RISK_TRADES.csv``,
``RISK_REFUSALS.csv``, ``RISK_SIGNALS.csv`` and ``MARKET_CONTEXT.csv``.

H1 showed the extra intraday signals were refused by the RISK layer rather than by
the entry rules: the 5% peak-to-trough drawdown halt fired on 493 DEV entries.
This experiment changes exactly one field of the risk budget — the halt is made
inert — and asks whether that halt was the ceiling on intraday participation and
whether the trades it refused were worth taking.

The variant budget is a RESEARCH INSTRUMENT, not a policy change:

* ``config/risk.yaml`` is read verbatim for the base arm and never written;
* nothing here is wired into ``src/trading_bot/autonomous/**`` or the PAPER path;
* removing a kill switch removes a protection, not just a limit, so the drawdown
  it buys back is published next to the result;
* DEV only, because the halt's behaviour in VAL/OOS was already observed in the
  WP run and re-reading those windows would not be out of sample.

A favourable verdict is a hypothesis to take back through the pre-registered
process (freeze, validate, measure OOS once), never a promotion.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + "/src")

from trading_bot.research.edge01.campaign import (
    run_risk_budget_ablation,
    write_risk_ablation_artifacts,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--outdir",
        default="reports/edge-recovery/WP-EDGE-01/risk-budget-h5",
        help="where the risk-ablation artefacts go",
    )
    args = parser.parse_args(argv)

    payload = run_risk_budget_ablation()
    outdir = Path(args.outdir)
    written = write_risk_ablation_artifacts(payload, outdir)

    abl = payload["risk_ablation"]
    print(
        f"H5 risk-budget ablation on {abl['window']} only "
        f"({abl['window_start_utc'][:10]}..{abl['window_end_utc'][:10]}, {abl['scenario']} costs)"
    )
    print(f"  candidate: {abl['candidate']}  |  only field changed: {abl['changed_field']}")
    print(f"  {'run':<9} {'halt%':>7} {'trades':>7} {'gross':>12} {'net':>12} {'maxDD%':>8} {'halt refs':>10}")
    for role in ("base", "variant"):
        arm = payload["arms"][role]
        print(
            f"  {role:<9} {arm['policy']['drawdown_halt_pct']:>7.1f} {arm['trades']:>7,} "
            f"{arm['gross_usdt']:>12,.2f} {arm['net_usdt']:>12,.2f} "
            f"{arm['max_drawdown_pct']:>8.2f} {arm['halt_refusals']:>10,}"
        )
    verdict = payload["verdict"]
    print(
        f"\nmarginal trades: {verdict['extra_trades']:+,}  "
        f"marginal net: {verdict['marginal_net_usdt']:+,.2f} USDT  "
        f"drawdown delta: {verdict['drawdown_delta_pct']:+,.2f} points"
    )
    top = sorted(verdict["funnel_delta"].items(), key=lambda kv: abs(kv[1]), reverse=True)[:5]
    print("  largest funnel deltas (variant - base):")
    for key, delta in top:
        print(f"    {key:<34} {delta:+,}")
    print(f"\nVERDICT: {verdict['verdict']}\n  {verdict['reason']}")
    print("artifacts:")
    for name, path in written.items():
        print(f"  {name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
