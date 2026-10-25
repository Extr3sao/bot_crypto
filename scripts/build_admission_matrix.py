"""Apply the PRE-REGISTERED admission criteria to multi-family results.

Criteria source: docs/STRATEGY_ADMISSION_CRITERIA.md (committed BEFORE the
baselines ran — commit c1ffbaa). This script only MECHANICALLY evaluates
them; no thresholds are adjusted here. ema_crossover is included for
completeness using its own committed baseline.
"""

from __future__ import annotations

import json
import os
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
OUTDIR = os.path.join(HERE, "..", "reports", "strategy-baseline")
DOCS = os.path.join(HERE, "..", "docs")


def evaluate(fam: str, base: dict[str, Any], x2: dict[str, Any]) -> dict[str, Any]:
    checks: dict[str, bool | None] = {}
    tot, oos, dev = base["totals"], base["OOS_W7"], base["DEV_W1_W4"]

    checks["c1_sample"] = (
        tot["trades"] >= 100 and oos["trades"] >= 30
        if tot["trades"] > 0
        else None
    )
    checks["c2_net_positive"] = tot["net"] > 0 and tot["expectancy"] > 0
    checks["c3_pf_gt1"] = (tot["profit_factor"] or 0.0) > 1.0
    checks["c4_oos_positive"] = (
        oos["net"] > 0 and (oos["profit_factor"] or 0.0) > 1.0
        if oos["trades"] > 0
        else None
    )
    checks["c5_dev_consistent"] = (dev["profit_factor"] or 0.0) > 0.8
    checks["c6_dd"] = None  # filled by caller if max_dd available
    checks["c7_survives_2x"] = (x2["totals"]["profit_factor"] or 0.0) > 0.9
    checks["c8_no_window_dominance"] = None  # needs per-window; filled by caller

    mandatory_fail = [
        k for k, v in checks.items()
        if k in ("c1_sample", "c2_net_positive", "c3_pf_gt1", "c4_oos_positive", "c7_survives_2x")
        and v is False
    ]
    unknown = [k for k, v in checks.items() if v is None]

    if mandatory_fail:
        status = "REJECT"
    elif unknown:
        status = "RESEARCH_REQUIRED"  # cannot certify with missing evidence
    else:
        status = "PAPER_CANDIDATE"

    return {
        "family": fam,
        "status": status,
        "checks": {k: (None if v is None else bool(v)) for k, v in checks.items()},
        "mandatory_failures": mandatory_fail,
        "unknown_checks": unknown,
        "totals_base": tot,
        "totals_2x": x2["totals"],
        "oos": oos,
        "dev": dev,
    }


def main() -> None:
    rows: dict[str, dict[str, Any]] = {}
    # ema_crossover: committed baseline (docs/EMA_CROSSOVER_PERFORMANCE_BASELINE.json)
    with open(os.path.join(DOCS, "EMA_CROSSOVER_PERFORMANCE_BASELINE.json"), encoding="utf-8") as fh:
        ema = json.load(fh)
    tot = ema["totals"]
    oos = ema["splits"]["oos_W7"]
    dev = ema["splits"]["development_W1_W4"]
    rows["ema_crossover"] = {
        "family": "ema_crossover",
        "status": "REJECT",
        "checks": {
            "c1_sample": tot["trades"] >= 100 and oos["trades"] >= 30,
            "c2_net_positive": tot["net"] > 0,
            "c3_pf_gt1": (tot["profit_factor"] or 0.0) > 1.0,
            "c4_oos_positive": oos["net"] > 0 and (oos["profit_factor"] or 0.0) > 1.0,
            "c5_dev_consistent": (dev["profit_factor"] or 0.0) > 0.8,
            "c7_survives_2x": False,  # PF 0.57 at BASE; 2X_COST strictly worse
        },
        "mandatory_failures": ["c2_net_positive", "c3_pf_gt1", "c4_oos_positive", "c7_survives_2x"],
        "totals_base": tot,
        "oos": oos,
        "note": "rejected by its own committed baseline (PF 0.57, OOS 0.41, negative-robust)",
    }

    for suffix, fam in [("momentum", "momentum"), ("breakout", "breakout"),
                        ("trend", "trend"), ("mean_reversion", "mean_reversion"),
                        ("volatility", "volatility"), ("ema_crossover", "ema_crossover")]:
        path = os.path.join(OUTDIR, f"MULTI_FAMILY_RESULTS_{suffix}.json")
        if not fam or not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        r = data[fam]
        rows[fam] = evaluate(fam, r["BASE"], r["2X_COST"])

    out = {
        "criteria_source": "docs/STRATEGY_ADMISSION_CRITERIA.md (pre-registered, c1ffbaa)",
        "admissions": rows,
        "paper_candidates": [f for f, r in rows.items() if r["status"] == "PAPER_CANDIDATE"],
        "rejected": [f for f, r in rows.items() if r["status"] == "REJECT"],
        "research_required": [f for f, r in rows.items() if r["status"] == "RESEARCH_REQUIRED"],
    }
    with open(os.path.join(DOCS, "STRATEGY_ADMISSION_MATRIX.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
    for fam, r in rows.items():
        print(f"{fam}: {r['status']} | failures={r.get('mandatory_failures', [])}")
    print("-> docs/STRATEGY_ADMISSION_MATRIX.json")


if __name__ == "__main__":
    main()
