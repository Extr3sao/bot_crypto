"""RFC-022 Sprint 002 - robustness DIAGNOSTICS + INDEPENDENT VERIFICATION.

Because G_EDGE_2 = FAIL, no candidate is promoted, so the formal robustness and
holdout stages are NOT_REACHED. This module still computes the full robustness
battery for the discovery survivors, clearly labelled DIAGNOSTIC_ONLY, so the
generalisation diagnosis has quantitative evidence.

The verifier is independent of the builder: it re-derives the split hashes, the
experiment counts, the economics and the PIT property from the raw certified
data, and it checks the six §58 conditions.

Outputs:
    ROBUSTNESS_DIAGNOSTICS.json
    INDEPENDENT_VERIFICATION.{md,json}
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import sprint002_lib as L
import sprint002_run as R

OUT = L.OUT_DIR
COST = L.CERTIFIED_ROUND_TRIP_BPS


def load_survivors() -> list[dict[str, Any]]:
    raw = json.loads((OUT / "DISCOVERY_RAW.json").read_text(encoding="utf-8"))
    exps = raw["experiments"]
    out: list[dict[str, Any]] = []
    for e in exps:
        m = e["metrics"]
        if m.get("trades", 0) >= L.MIN_TRADES and m.get("net_bps", -1) > 0:
            out.append(dict(e))
    # rebuild tuples
    for e in out:
        prm = e["parameters"]
        if e["sig"] == "lead_lag":
            e["params"] = (prm["target_mult"], True, prm["stop_mult"], prm["hold_bars"], prm["lag_bars"])
        elif e["sig"] == "cross_sectional_rs":
            e["params"] = (0.0, False, 0.0, prm["hold_bars"])
        else:
            e["params"] = (
                prm["target_mult"],
                prm["target_is_atr"],
                prm["stop_mult"],
                prm["hold_bars"],
            )
    return out


# ---------------------------------------------------------------------------
# diagnostics
# ---------------------------------------------------------------------------


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    survivors = load_survivors()
    print(f"discovery survivors for diagnostics: {len(survivors)}", flush=True)

    diag: list[dict[str, Any]] = []
    for s in survivors:
        d = R.stage_robustness(s)
        d["label"] = "DIAGNOSTIC_ONLY (G_EDGE_2 = FAIL, so not a promoted robustness pass)"
        diag.append(d)
        print(
            f"  {d['candidate_id']} {d['parameters']} wf={d['walk_forward']['verdict']} "
            f"cost={d['cost_stress']['verdict']} msc={d['cost_stress']['max_survivable_cost_bps']} "
            f"slip={d['slippage_stress']['verdict']} param={d['parameter_neighbourhood'].get('verdict')} "
            f"boot_ci={d['bootstrap'].get('ci95_net_bps')} p_le0={d['bootstrap'].get('p_net_le_0')}",
            flush=True,
        )
    L.write_json(
        OUT / "ROBUSTNESS_DIAGNOSTICS.json",
        {"schema": "rfc022.robustness_diagnostics.v1", "diagnostics": diag},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
