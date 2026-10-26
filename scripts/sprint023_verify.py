"""RFC-023 — independent verifier (builder != verifier).

Recomputes the central numbers from first principles and audits the process
constraints: no new strategy, no retuning, no cost change, no silent experiment
deletion and no holdout access.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import sprint002_lib as L  # noqa: E402
import sprint002_pipeline as P  # noqa: E402
import sprint023_lib as G  # noqa: E402

OUT = G.OUT
REPORTS = REPO / "reports"


def closest(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol


def main() -> int:
    checks: dict[str, bool] = {}
    detail: dict[str, Any] = {}

    # 1. dataset integrity (certified hashes, unchanged)
    sh = L.split_hashes()
    checks["dataset_hashes_unchanged"] = (
        sh["DISCOVERY"]["sha256"] == "6b0d8f61e0a5d98117dc2af241d9f8487cfa26b6e3e82c074ea4ff7498b00892"
        and sh["VALIDATION"]["sha256"] == "7b2ed3a086ec5ce0ebeaf122e8fcadeaf6c6e9185050ea20b7e512a429d7756e"
        and sh["HOLDOUT"]["sha256"] == "3acc341089247b3c142f87eae62845057ac09db7923b7c253a7ea03ce4b23238"
    )
    detail["split_files"] = {k: v["files"] for k, v in sh.items()}

    # 2. experiment count and winners (recomputed)
    disc = G.discovery()
    checks["experiment_count_106"] = len(disc) == 106
    winners = [
        r for r in disc
        if r["metrics"].get("trades", 0) >= G.MIN_TRADES
        and r["metrics"].get("net_bps", -1) > 0
        and not r["metrics"].get("single_trade_dependency")
    ]
    checks["discovery_winners_2"] = len(winners) == 2
    detail["winner_ids"] = sorted(r["experiment_id"] for r in winners)

    # 3. validation passes recomputed (n>=50, net>0, no single-trade dependency)
    vpass = 0
    for w in winners:
        tr, _ = P.rerun(w, L.SPLITS["VALIDATION"])
        net = G.net_of(tr)
        m = L.metrics(tr, 1, L.TF_MIN[str(w["timeframe"]).split("+")[0]])
        if m.get("trades", 0) >= G.MIN_TRADES and m.get("net_bps", -1) > 0 and not m.get("single_trade_dependency"):
            vpass += 1
        detail.setdefault("validation_net", {})[w["experiment_id"]] = round(float(np.mean(net)), 4) if net.shape[0] else None
    checks["validation_passes_0"] = vpass == 0

    # 4. best-of-N null recomputed independently from the cached draws
    draws = json.loads((OUT / "_null_draws.json").read_text(encoding="utf-8"))
    bn = np.array([d["best_net_bps"] for d in draws], dtype=np.float64)
    stored = json.loads((OUT / "BEST_OF_N_NULL.json").read_text(encoding="utf-8"))
    checks["null_summary_matches"] = (
        len(draws) == stored["n_draws"]
        and closest(float(np.median(bn)), stored["median_best_net_bps"], 1e-3)
        and closest(float(np.percentile(bn, 95)), stored["p95_best_net_bps"], 1e-3)
    )
    detail["null_median"] = round(float(np.median(bn)), 4)
    detail["p_best_ge_observed"] = round(float(np.mean(bn >= 16.0652)), 4)

    # 5. trade concentration recomputed independently for the winners
    conc = json.loads((OUT / "TRADE_CONCENTRATION.json").read_text(encoding="utf-8"))
    ok = True
    for w in winners:
        ordered = sorted(G.net_of(w["trades"]).tolist(), reverse=True)
        top1 = ordered[0] / sum(ordered) if sum(ordered) else 0.0
        stored_c = conc["winners"][w["experiment_id"]]["discovery"]
        if stored_c["pct_top1"] is None or not closest(round(top1, 4), stored_c["pct_top1"], 1e-4):
            ok = False
    checks["concentration_matches"] = ok

    # 6. sample-size MDE recomputed independently
    ss = json.loads((OUT / "SAMPLE_SIZE_ANALYSIS.json").read_text(encoding="utf-8"))
    sigma = ss["pooled_std_bps"]
    mde100 = (1.959964 + 0.841621) * sigma / np.sqrt(100)
    checks["mde_matches"] = closest(round(float(mde100), 4), ss["mde_bps_by_n"]["100"], 1e-3)

    # 7. cost model unchanged
    checks["cost_unchanged"] = L.CERTIFIED_ROUND_TRIP_BPS == 23.790569

    # 8. no new strategy / no retuning: analysis scripts import the frozen signals
    src = (REPO / "scripts" / "sprint023_lib.py").read_text(encoding="utf-8")
    checks["imports_frozen_signals"] = "import sprint002_signals as S" in src and "import sprint002_pipeline as P" in src
    checks["no_new_signal_definitions"] = not re.search(r"^def sig_", src, flags=re.MULTILINE)

    # 9. holdout access state
    checks["holdout_windows_locked"] = L.SPLITS["HOLDOUT"] == ("W6", "W7")
    used_holdout = False
    for name in ("sprint023_lib.py", "sprint023_null.py", "sprint023_analysis.py", "sprint023_verify.py"):
        text = (REPO / "scripts" / name).read_text(encoding="utf-8")
        if re.search(r'SPLITS\["HOLDOUT"\]\s*\)', text) or re.search(r'split_bundles\(\s*"HOLDOUT"', text):
            used_holdout = True
    checks["holdout_not_read"] = not used_holdout

    # 10. no silent experiment deletion (registry size conserved)
    registry = (OUT.parent / "edge-discovery" / "sprint002" / "EXPERIMENT_REGISTRY.jsonl")
    n_reg = sum(1 for _ in registry.open(encoding="utf-8")) if registry.exists() else -1
    checks["no_experiment_deleted"] = n_reg == 106

    passed = all(checks.values())
    result = {"checks": checks, "detail": detail, "verifier_result": "PASS" if passed else "FAIL"}
    G.write_json(OUT / "RFC023_VERIFICATION.json", result)
    md = ["# RFC-023 — INDEPENDENT VERIFICATION", "", f"VERIFIER_RESULT = {result['verifier_result']}", ""]
    for k, v in checks.items():
        md.append(f"- {k}: {'PASS' if v else 'FAIL'}")
    md += ["", "```text", json.dumps(detail, indent=2), "```"]
    (OUT / "RFC023_VERIFICATION.md").write_text("\n".join(md), encoding="utf-8")
    print(json.dumps(checks, indent=2))
    print(f"VERIFIER_RESULT {result['verifier_result']}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
