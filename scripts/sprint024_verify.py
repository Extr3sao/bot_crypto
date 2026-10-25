"""RFC-024 — independent verifier (builder != verifier).

Recomputes the central numbers from first principles and audits the process
constraints: registry frozen, cost unchanged, splits unchanged, results
recomputable, multiple-testing correction correct, best-of-N null independently
recomputed, no hypothesis silently removed, no strategy promoted, holdout never
read.
"""

from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import sprint002_lib as L  # noqa: E402
import sprint024_lib as R  # noqa: E402

OUT = R.OUT


def norm_sf(z: float) -> float:
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def main() -> int:
    checks: dict[str, bool] = {}
    detail: dict[str, Any] = {}

    # 1. registry frozen and unchanged
    reg = json.loads((OUT / "RFC024_HYPOTHESIS_REGISTRY.json").read_text(encoding="utf-8"))
    checks["registry_frozen_hash"] = reg["hash"] == R.REGISTRY_HASH
    checks["registry_count_6"] = reg["count"] == 6 and len(R.REGISTRY) == 6
    detail["registry_hash"] = R.REGISTRY_HASH
    detail["hypothesis_ids"] = [h["hypothesis_id"] for h in R.REGISTRY]

    # 2. no hypothesis silently removed (ids unique and complete)
    ids = [h["hypothesis_id"] for h in R.REGISTRY]
    checks["no_hypothesis_removed"] = len(set(ids)) == 6 and all(i.startswith("H-DIR-") for i in ids)

    # 3. cost model unchanged
    checks["cost_unchanged"] = L.CERTIFIED_ROUND_TRIP_BPS == 23.790569 == R.COST

    # 4. splits unchanged (certified hashes)
    sh = L.split_hashes()
    checks["split_hashes_unchanged"] = (
        sh["DISCOVERY"]["sha256"] == "6b0d8f61e0a5d98117dc2af241d9f8487cfa26b6e3e82c074ea4ff7498b00892"
        and sh["VALIDATION"]["sha256"] == "7b2ed3a086ec5ce0ebeaf122e8fcadeaf6c6e9185050ea20b7e512a429d7756e"
        and sh["HOLDOUT"]["sha256"] == "3acc341089247b3c142f87eae62845057ac09db7923b7c253a7ea03ce4b23238"
    )
    detail["split_files"] = {k: v["files"] for k, v in sh.items()}

    # 5. results recomputable: re-run the observed-best hypothesis independently
    run = json.loads((OUT / "RUN_REPORT.json").read_text(encoding="utf-8"))
    best_id = run["best_of_n_null"]["observed_best_hypothesis"]
    best_hyp = next(h for h in R.REGISTRY if h["hypothesis_id"] == best_id)
    tr, _eb = R.run_hypothesis(best_hyp, "DISCOVERY")
    recomputed_disc = float(np.mean([t.net_bps for t in tr]))
    stored_disc = float(run["hypotheses"][best_id]["discovery_net_bps"])
    checks["results_recomputable"] = abs(recomputed_disc - stored_disc) <= 1e-3
    detail["recomputed_best_discovery_net_bps"] = round(recomputed_disc, 6)
    detail["stored_best_discovery_net_bps"] = stored_disc

    # 6. best-of-N null independently recomputed from the cached draws
    draws = json.loads((OUT / "_null_draws.json").read_text(encoding="utf-8"))
    bn = np.array([d["best_net_bps"] for d in draws], dtype=np.float64)
    stored_null = json.loads((OUT / "BEST_OF_N_NULL.json").read_text(encoding="utf-8"))
    obs = float(stored_null["observed_best_bps"])
    p_ind = float(np.mean(bn >= obs))
    checks["null_summary_matches"] = (
        len(draws) == stored_null["n_draws"]
        and abs(float(np.median(bn)) - stored_null["median_best_net_bps"]) <= 1e-3
        and abs(float(np.percentile(bn, 95)) - stored_null["p95_best_net_bps"]) <= 1e-3
    )
    checks["null_p_matches"] = abs(p_ind - stored_null["p_best_ge_observed"]["p_value"]) <= 1e-9
    detail["null_median"] = round(float(np.median(bn)), 4)
    detail["p_best_ge_observed"] = round(p_ind, 4)

    # 7. multiple-testing correction correct (recompute BH + Holm + raw p)
    mt = json.loads((OUT / "MULTIPLE_TESTING_REPORT.json").read_text(encoding="utf-8"))
    pairs = [(hid, v["t_stat_discovery"]) for hid, v in run["hypotheses"].items()
             if v["t_stat_discovery"] is not None]
    pv = {hid: norm_sf(float(t)) for hid, t in pairs}
    checks["raw_p_recomputed"] = all(
        abs(pv[hid] - mt["raw_p"][hid]) <= 1e-3 for hid in pv
    )
    # BH at q=0.10
    order = sorted(pv.items(), key=lambda kv: kv[1])
    m = len(order)
    kmax = 0
    for ki in range(1, m + 1):
        if order[ki - 1][1] <= 0.10 * ki / m:
            kmax = ki
    bh = sorted(h for h, _ in order[:kmax])
    holm: list[str] = []
    for ki in range(m):
        if order[ki][1] <= 0.10 / (m - ki):
            holm.append(order[ki][0])
        else:
            break
    checks["bh_fdr_correct"] = bh == sorted(mt["bh_pass"])
    checks["holm_correct"] = holm == mt["holm_pass"]
    detail["bh_pass"] = bh
    detail["holm_pass"] = holm

    # 8. no new volatility detector (shock event imported from frozen signals)
    sig_src = (REPO / "scripts" / "sprint024_signals.py").read_text(encoding="utf-8")
    checks["reuses_frozen_shock"] = "S._vol_shock(b)" in sig_src
    checks["no_new_vol_detector"] = not re.search(r"def .*vol_shock.*\(.*rank_q", sig_src)

    # 9. holdout never read
    used = False
    for name in ("sprint024_lib.py", "sprint024_null.py", "sprint024_analysis.py"):
        text = (REPO / "scripts" / name).read_text(encoding="utf-8")
        if re.search(r'SPLITS\["HOLDOUT"\]', text) or re.search(r'"HOLDOUT"\s*,\s*tf', text):
            used = True
    # sprint024_lib references SPLITS["HOLDOUT"] only inside the guard; assert run refuses it
    refused = False
    try:
        R.run_hypothesis(R.REGISTRY[0], "HOLDOUT")
    except ValueError:
        refused = True
    checks["holdout_not_read"] = (not used) and refused
    checks["holdout_windows_locked"] = L.SPLITS["HOLDOUT"] == ("W6", "W7")

    # 10. no strategy promoted (no production registry / runtime import)
    checks["no_strategy_promoted"] = True
    for name in ("sprint024_lib.py", "sprint024_analysis.py", "sprint024_signals.py"):
        text = (REPO / "scripts" / name).read_text(encoding="utf-8")
        if re.search(r"StrategyRegistry|strategy_registry|from trading_bot", text):
            checks["no_strategy_promoted"] = False

    passed = all(checks.values())
    result = {"checks": checks, "detail": detail, "verifier_result": "PASS" if passed else "FAIL"}
    R.write_json(OUT / "RFC024_VERIFICATION.json", result)
    md = ["# RFC-024 — INDEPENDENT VERIFICATION", "", f"VERIFIER_RESULT = {result['verifier_result']}", ""]
    for key, val in checks.items():
        md.append(f"- {key}: {'PASS' if val else 'FAIL'}")
    md += ["", "```text", json.dumps(detail, indent=2), "```"]
    (OUT / "RFC024_VERIFICATION.md").write_text("\n".join(md), encoding="utf-8")
    print(json.dumps(checks, indent=2))
    print(f"VERIFIER_RESULT {result['verifier_result']}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
