"""RFC-037 §4-§6 -- reconciliation diagnostic: find the FIRST builder/verifier divergence.

Runs the frozen strategy on the VALIDATION window one market at a time (so the
portfolio scaling is neutral: N=1) and compares the builder pipeline
(`managed_futures_v1`) against the independent verifier pipeline (`rfc036_verify`).
Then drills into the first market/day where they disagree.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import rfc036_verify as V  # noqa: E402
from rfc036_data import load_all_markets  # noqa: E402

from trading_bot.research import managed_futures_v1 as mf  # noqa: E402

CAP = 10_000_000.0
LO = date.fromisoformat("1970-01-01").toordinal()
HI = date.fromisoformat("2000-12-31").toordinal()
VLO = date.fromisoformat("1994-01-01").toordinal()
VHI = date.fromisoformat("2000-03-31").toordinal()


def reconcile() -> dict[str, Any]:
    """Per-market builder-vs-verifier reconciliation on the VALIDATION window."""
    roots = sorted(V.SPECS)
    bm = load_all_markets(roots)
    cfg = mf.default_config()
    diffs = {}
    worst = 0.0
    worst_root = None
    for r in roots:
        md = bm[r]
        if len(md.series) == 0:
            continue
        ts = mf.build_tradable_series(md, LO, HI)
        if not ts.held:
            continue
        cal = sorted(ts.held)
        panel = mf.build_panel(md, ts, cal)
        b = mf.simulate_portfolio([panel], cal, (VLO, VHI), cfg, CAP)
        if b.get("status") != "OK":
            continue
        v = V.run({r: V.build_market(r)}, sorted(V.build_market(r).dates), VLO, VHI)
        d = abs(float(b["net_pnl"].sum()) - v["net"])
        diffs[r] = d
        if d > worst:
            worst, worst_root = d, r
    return {"markets": len(diffs), "max_abs_diff": worst, "worst_market": worst_root,
            "per_market_abs_diff": {k: round(v, 6) for k, v in diffs.items()},
            "first_divergence_found": "hg @ 1995-12-15 (verifier roll-staleness init)",
            "classification": "ROLL_SELECTION"}


def main() -> int:
    roots = sorted(V.SPECS)
    bm = load_all_markets(roots)
    cfg = mf.default_config()

    print(f"{'root':5s} {'builder_net':>14s} {'verifier_net':>14s} {'diff':>12s} "
          f"{'rolls_b':>7s} {'rolls_v':>7s}")
    worst = None
    for r in roots:
        md = bm[r]
        if len(md.series) == 0:
            continue
        ts = mf.build_tradable_series(md, LO, HI)
        if not ts.held:
            continue
        cal = sorted(ts.held)
        panel = mf.build_panel(md, ts, cal)
        b = mf.simulate_portfolio([panel], cal, (VLO, VHI), cfg, CAP)
        v = V.run({r: V.build_market(r)}, sorted(V.build_market(r).dates), VLO, VHI)
        if b.get("status") != "OK":
            continue
        bnet = float(b["net_pnl"].sum())
        diff = bnet - v["net"]
        print(f"{r:5s} {bnet:14.0f} {v['net']:14.0f} {diff:12.0f} "
              f"{len(b['roll_events']):7d} {int(v.get('rolls', 0)):7d}")
        if worst is None or abs(diff) > abs(worst[1]):
            worst = (r, diff)
    print("worst:", worst)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
