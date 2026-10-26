"""WP-EDGE-01 H1 runner — the frozen EDGE-INTRA-01 with its 1h filter removed.

    python scripts/edge01_ablation.py [--outdir reports/edge-recovery/WP-EDGE-01/ablation-h1]

Writes ``ABLATION.json``, ``ABLATION.md``, ``ABLATION_TRADES.csv``,
``ABLATION_REFUSALS.csv`` and ``ABLATION_SIGNALS.csv``.

DEV ONLY. The variant was designed after VAL and OOS had been read, so those
windows stay closed to it: reading them again would turn a post-hoc variant into
in-sample evidence. The comparison answers one question on DEV — is the intraday
loss in the 1h trend filter or in the breakout itself? — with the gross result
BEFORE costs, which is the part of the P&L the entry rule is responsible for.

This is not a promotion path: a favourable verdict here goes back through the
pre-registered process (freeze, validate, then measure OOS once) before it can
mean anything. Nothing is wired into the PAPER runtime.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + "/src")

from trading_bot.research.edge01.campaign import (
    run_trend_filter_ablation,
    write_ablation_artifacts,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--outdir",
        default="reports/edge-recovery/WP-EDGE-01/ablation-h1",
        help="where the ablation artefacts go",
    )
    args = parser.parse_args(argv)

    payload = run_trend_filter_ablation()
    outdir = Path(args.outdir)
    written = write_ablation_artifacts(payload, outdir)

    ablation = payload["ablation"]
    print(
        f"H1 ablation on {ablation['window']} only "
        f"({ablation['window_start_utc'][:10]}..{ablation['window_end_utc'][:10]}, "
        f"{ablation['scenario']} costs)"
    )
    print(f"  removed: {ablation['removed']}")
    header = f"  {'run':<9} {'filter':<7} {'signals':>9} {'trades':>7} {'gross':>12} {'net':>12}"
    print(header)
    for role in ("base", "ablation"):
        arm = payload["arms"][role]
        print(
            f"  {role:<9} {'yes' if arm['use_trend_filter'] else 'no':<7} "
            f"{arm['signal_count']:>9,} {arm['trades']:>7,} "
            f"{arm['gross_usdt']:>12,.2f} {arm['net_usdt']:>12,.2f}"
        )
    funnel = payload["verdict"]["funnel_delta"]
    top = sorted(funnel.items(), key=lambda kv: abs(kv[1]), reverse=True)[:6]
    print("  largest funnel deltas (ablation - base):")
    for key, delta in top:
        print(f"    {key:<34} {delta:+,}")
    verdict = payload["verdict"]
    print(f"\nVERDICT: {verdict['verdict']}\n  {verdict['reason']}")
    print("artifacts:")
    for name, path in written.items():
        print(f"  {name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
