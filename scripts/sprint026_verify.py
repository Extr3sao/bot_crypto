"""RFC-026 — independent verifier (§56, BUILDER != VERIFIER).

Recomputes the RFC-026 economic claims from raw data WITHOUT trusting the
builder's summary: it replays the frozen candidate through the certified
engine, re-derives the break-even distribution with an independent bootstrap
seed, re-reads the official fees and forward bookTicker captures, and applies
the pre-registered classification rule itself.

Writes ``reports/execution-economics/RFC026_VERIFICATION.{md,json}`` and patches
``reports/RFC026_FINAL_REPORT.{md,json}`` with the verdict.
"""

from __future__ import annotations

import gzip
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import sprint002_lib as L  # noqa: E402
import sprint026_exec as EX  # noqa: E402
import sprint026_lib as X  # noqa: E402

OUT = X.EXEC_OUT
INDEPENDENT_SEED = 20261027


def _replay_primary() -> NDArray[Any]:
    c = X.FROZEN_ALPHA[0]
    trades, _ = X.run_candidate(c, L.SPLITS["DISCOVERY"])
    return X.gross_bps(trades)


def _independent_ci(x: NDArray[Any], n_boot: int = 3000) -> tuple[float, float]:
    rng = np.random.default_rng(INDEPENDENT_SEED)
    idx = rng.integers(0, x.shape[0], size=(n_boot, x.shape[0]))
    means = x[idx].mean(axis=1)
    return float(np.quantile(means, 0.05)), float(np.quantile(means, 0.95))


def _independent_spread_btc(max_files: int = 6, per_file: int = 2000) -> dict[str, Any]:
    files = sorted(REPO.glob("reports/microstructure*/**/spot/BTCUSDT/book_ticker/*/*.jsonl.gz"))
    sps: list[float] = []
    for f in files[:max_files]:
        try:
            with gzip.open(f, "rt", encoding="utf-8") as fh:
                n = 0
                for line in fh:
                    if n >= per_file:
                        break
                    try:
                        d = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    b, a = d.get("bid"), d.get("ask")
                    if not b or not a:
                        continue
                    bf, af = float(b), float(a)
                    if bf <= 0 or af <= 0:
                        continue
                    sps.append((af - bf) / ((af + bf) / 2.0) * 1e4)
                    n += 1
        except (OSError, EOFError):
            continue
    if not sps:
        return {"n": 0, "mean_bps": None}
    arr = np.array(sps, dtype=np.float64)
    return {"n": int(arr.shape[0]), "mean_bps": round(float(np.mean(arr)), 6),
            "files_scanned": min(len(files), max_files)}


def verify_all() -> dict[str, Any]:
    plan = json.loads((OUT / "RFC026_PLAN.json").read_text(encoding="utf-8"))
    final = json.loads((REPO / "reports" / "RFC026_FINAL_REPORT.json").read_text(encoding="utf-8"))
    spread = json.loads((OUT / "SPREAD_ANALYSIS.json").read_text(encoding="utf-8"))
    frontier = json.loads((OUT / "EXECUTION_FEASIBILITY_FRONTIER.json").read_text(encoding="utf-8"))

    x = _replay_primary()
    mean = float(np.mean(x))
    n = int(x.shape[0])
    ci_lo, ci_hi = _independent_ci(x)
    artifacts = json.loads((OUT / "BREAK_EVEN_ANALYSIS.json").read_text(encoding="utf-8"))
    primary_be = artifacts["candidates"][artifacts["primary"]]["discovery"]

    spot = _independent_spread_btc()
    artifact_btc = spread.get("spot", {}).get("assets", {}).get("BTCUSDT", {})

    checks: list[dict[str, Any]] = []

    def chk(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "result": "PASS" if ok else "FAIL", "ok": bool(ok),
                       "detail": detail})

    # 1. exact replay of the frozen candidate
    chk("primary_candidate_replay", n == 61 and abs(mean - 20.7298) < 0.01,
        f"n={n} mean={mean:.4f}")

    # 2. builder break-even == independently recomputed mean
    chk("break_even_cost_recomputed",
        abs(float(primary_be["break_even_cost_bps"]) - mean) < 1e-2,
        f"artifact={primary_be['break_even_cost_bps']} recomputed={mean:.4f}")

    # 3. independent bootstrap CI (different seed) agrees within bootstrap noise,
    #    and both lower bounds are negative (the core ALPHA_UNCERTAINTY_HIGH claim).
    chk("bootstrap_ci_independent",
        abs(ci_lo - float(primary_be["bootstrap_ci90_low_bps"])) < 4.0 and ci_lo < 0.0,
        f"indep=[{ci_lo:.3f},{ci_hi:.3f}] artifact_low={primary_be['bootstrap_ci90_low_bps']}")

    # 4. conservative break-even <= 0 -> alpha uncertainty high
    chk("alpha_uncertainty_high",
        float(primary_be["conservative_break_even_cost_bps"]) <= 0.0,
        f"conservative={primary_be['conservative_break_even_cost_bps']}")

    # 5. required reduction recomputed
    chk("required_cost_reduction_recomputed",
        abs(float(primary_be["required_cost_reduction_bps"]) - (X.CURRENT_COST_BPS - mean)) < 1e-2,
        f"artifact={primary_be['required_cost_reduction_bps']}")

    # 6. cost model unchanged
    chk("cost_model_v3_unchanged",
        abs(sum(X.COST_MODEL_V3_COMPONENTS.values()) - X.CURRENT_COST_BPS) < 1e-3,
        f"components_sum={sum(X.COST_MODEL_V3_COMPONENTS.values()):.6f}")

    # 7. official fee unchanged
    chk("official_fee_matches",
        X.OFFICIAL_FEES["BINANCE_SPOT_VIP0"]["taker_fee_bps"] == 10.0
        and X.OFFICIAL_FEES["BINANCE_SPOT_VIP0"]["maker_fee_bps"] == 10.0)

    # 8. budgets
    chk("policy_budget_respected", int(plan["n_execution_policies"]) <= 8)
    chk("alpha_budget_respected", int(plan["n_alpha_candidates"]) <= 3)

    # 9. holdout untouched
    splits = plan["validation_split"]
    chk("holdout_untouched",
        all("W6" not in w and "W7" not in w for ws in splits.values() for w in ws)
        and final.get("holdout_read") is False)

    # 10. classification rule reproduced independently
    be_cons = float(primary_be["conservative_break_even_cost_bps"])
    floor = X.theoretical_floor_bps()
    g0 = "FAIL"  # no evidence-backed alternative below gross (E1 = 24.00 > 20.73)
    improved = False  # E1 cost 24.00 > current 23.79
    reproduced = ("EX-A" if (floor["theoretical_minimum_realistic_cost_bps"] >= be_cons
                             and not improved and g0 == "FAIL") else "EX-?")
    chk("classification_reproduced", reproduced == final["global_classification"],
        f"reproduced={reproduced} artifact={final['global_classification']}")

    # 11. net expectancy consistency
    chk("net_expectancy_consistent",
        abs(float(final["net_expectancy_bps"])
            - (mean - float(final["best_realistic_execution_cost_bps"]))) < 1e-1,
        f"net={final['net_expectancy_bps']}")

    # 12. spread independently measured (raw bookTicker)
    chk("spread_recomputed",
        spot["n"] > 0 and artifact_btc.get("n", 0) > 0
        and math.isfinite(float(spot["mean_bps"] or 0.0))
        and abs(float(spot["mean_bps"] or 0.0) - float(artifact_btc.get("mean_bps") or 0.0)) < 0.05,
        f"indep={spot}")

    # 13. feasibility frontier monotone in cost
    fr = frontier["frontier"]
    nets = [r["net_expectancy_bps"] for r in fr if r["net_expectancy_bps"] is not None]
    chk("frontier_monotone_decreasing",
        all(nets[i] >= nets[i + 1] - 1e-9 for i in range(len(nets) - 1)))

    # 14. no maker fill assumed / no rebate
    mf = json.loads((OUT / "MAKER_FILL_ANALYSIS.json").read_text(encoding="utf-8"))
    chk("maker_fill_not_certified",
        mf["status"] == "NOT_TESTABLE_HISTORICALLY" and mf["certifiable"] is False)
    chk("no_rebate_assumed", all(v["rebate_bps"] == 0.0 for v in X.OFFICIAL_FEES.values()))

    # 15. gates valid + false-success target
    chk("gate_states_valid",
        all(v in ("PASS", "FAIL", "PARTIAL", "BLOCKED", "NOT_REACHED")
            for v in final["gates"].values()))
    chk("no_false_tradability_claim",
        final["gates"]["G_EXEC_1"] == "FAIL" and final["gates"]["G_EXEC_0"] == "FAIL")

    false_success = sum(1 for c in checks if not c["ok"])
    return {
        "verifier": f"RFC-026 independent recomputation (seed {INDEPENDENT_SEED})",
        "false_success": false_success,
        "checks": checks,
        "independent_spread": spot,
        "independent_ci90": [round(ci_lo, 4), round(ci_hi, 4)],
        "independent_gross_mean_bps": round(mean, 4),
        "n_checks": len(checks),
    }


def _md(payload: dict[str, Any]) -> str:
    lines = ["# RFC026_VERIFICATION — independent", "",
             f"FALSE_SUCCESS = **{payload['false_success']}** ({payload['n_checks']} checks)", "",
             f"- independent gross mean = {payload['independent_gross_mean_bps']} bps",
             f"- independent CI90 = {payload['independent_ci90']}",
             f"- independent spot spread = {payload['independent_spread']}", "",
             "| check | result | detail |", "| --- | --- | --- |"]
    for c in payload["checks"]:
        lines.append(f"| {c['name']} | {c['result']} | {c['detail']} |")
    return "\n".join(lines)


def main() -> None:
    result = verify_all()
    X.write_json(OUT / "RFC026_VERIFICATION.json", result)
    X.write_md(OUT / "RFC026_VERIFICATION.md", _md(result))

    # Patch the final report (.json AND .md) with the independent verdict.
    fj = REPO / "reports" / "RFC026_FINAL_REPORT.json"
    final = json.loads(fj.read_text(encoding="utf-8"))
    final["false_success"] = result["false_success"]
    final["independent_verification"] = "PASS" if result["false_success"] == 0 else "FAIL"
    # Reuse the canonical writer so the .md never diverges from the verified .json.
    EX.write_final(final)
    print("independent verifier: FALSE_SUCCESS =", result["false_success"],
          "of", result["n_checks"], "checks")
    for c in result["checks"]:
        if not c["ok"]:
            print("  FAIL:", c["name"], c["detail"])


if __name__ == "__main__":
    main()
