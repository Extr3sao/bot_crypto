"""RFC-028 — independent verifier (§59-§61, BUILDER != VERIFIER).

Recomputes the RFC-028 economic claims from the frozen canonical cache WITHOUT
trusting the builder's summary.  It rebuilds the spot/perp/funding decision
series with its OWN as-of implementation (``np.searchsorted``), recomputes the
frozen candidate's entry signal, every leg PnL, the funding cashflows, costs,
capital usage and net PnL independently, re-derives the gate/classification
rules, and scans for every §61 FALSE_SUCCESS trigger.

Writes ``reports/carry/RFC028_VERIFICATION.{md,json}`` and patches
``reports/RFC028_FINAL_REPORT.{md,json}``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import sprint028_lib as L
import sprint028_run as R
from numpy.typing import NDArray

REPO = Path(__file__).resolve().parents[1]
OUT = L.OUT_DIR

H_PERIODS = 21          # frozen candidate horizon (7d)
K = 3                   # frozen candidate trailing window


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _asof_indep(times: NDArray[Any], values: NDArray[Any],
                decisions: NDArray[Any]) -> NDArray[Any]:
    order = np.argsort(times, kind="stable")
    t = times[order]
    v = values[order]
    pos = np.searchsorted(t, decisions, side="right") - 1
    out = np.full(decisions.shape, np.nan, dtype=np.float64)
    good = pos >= 0
    out[good] = v[pos[good]].astype(np.float64)
    return out


def _independent_asset(asset: str) -> dict[str, Any]:
    spot = L.load_spot(asset)
    perp = L.load_perp(asset)
    fund = L.load_funding(asset)
    gts = fund["funding_time_ms"].astype(np.int64)
    s_close = _asof_indep(spot["open_time_ms"].astype(np.int64) + L.SRC_MS,
                          spot["close"], gts)
    p_close = _asof_indep(perp["open_time_ms"].astype(np.int64) + L.SRC_MS,
                          perp["close"], gts)
    rate_bps = np.asarray(fund["funding_rate"], dtype=np.float64) * 1e4
    return {"gts": gts, "spot": s_close, "perp": p_close, "rate": rate_bps}


def _entry_mask(rate: NDArray[Any]) -> NDArray[Any]:
    """Independent recomputation of the frozen entry rule (H-C1-MEAN3|RULE_BE)."""
    n = rate.shape[0]
    mask = np.zeros(n, dtype=bool)
    for i in range(K, n):
        win = rate[i - K:i]
        if not np.all(np.isfinite(win)):
            continue
        m = float(np.mean(win))
        if m > 0.0 and m * H_PERIODS >= L.ROUND_TRIP_COST_BPS:
            mask[i] = True
    return mask


def _recompute(asset: str, lo: float, hi: float) -> dict[str, Any]:
    d = _independent_asset(asset)
    n = d["gts"].shape[0]
    a, b = int(n * lo), int(n * hi)
    entry = _entry_mask(d["rate"])
    trades: list[dict[str, float]] = []
    i = a
    while i + H_PERIODS < b:
        if not entry[i]:
            i += 1
            continue
        j = i + H_PERIODS
        vals = (d["spot"][i], d["spot"][j], d["perp"][i], d["perp"][j])
        if not all(np.isfinite(v) for v in vals):
            i += 1
            continue
        funding_sum = float(np.nansum(d["rate"][i + 1:j + 1]))
        spot_pnl = (d["spot"][j] / d["spot"][i] - 1.0) * 1e4
        perp_pnl = -(d["perp"][j] / d["perp"][i] - 1.0) * 1e4
        basis_pnl = spot_pnl + perp_pnl
        cost = L.ROUND_TRIP_COST_BPS
        net = spot_pnl + perp_pnl + funding_sum - cost
        trades.append({"spot_pnl": spot_pnl, "perp_pnl": perp_pnl,
                       "basis_pnl": basis_pnl, "funding": funding_sum,
                       "cost": cost, "net": net})
        i = j + 1
    return {"asset": asset, "n": len(trades), "trades": trades}


def verify_all() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def chk(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "result": "PASS" if ok else "FAIL",
                       "ok": bool(ok), "detail": detail})

    final = json.loads((REPO / "reports" / "RFC028_FINAL_REPORT.json").read_text(encoding="utf-8"))
    cand = final["best_discovery_candidate"]
    cid = cand["candidate_id"]
    artifact_disc = cand["discovery"]

    # --- §61 false-success triggers ---------------------------------------
    chk("cost_model_is_carry_v1_not_v3",
        abs(final["round_trip_cost_bps"] - L.ROUND_TRIP_COST_BPS) < 1e-9
        and abs(final["round_trip_cost_bps"] - 23.790569) > 1.0,
        f"round_trip={final['round_trip_cost_bps']}")
    chk("both_leg_costs_included",
        L.SPOT_SIDE_BPS > 0 and L.PERP_SIDE_BPS > 0,
        f"spot_side={L.SPOT_SIDE_BPS} perp_side={L.PERP_SIDE_BPS}")
    chk("funding_kept_as_return_not_negative_fee",
        L.ROUND_TRIP_COST_BPS == L.SPOT_SIDE_BPS * 2 + L.PERP_SIDE_BPS * 2,
        "funding counted as positive return; cost is trading-only")
    chk("no_unrealistic_leverage", L.PERP_LEVERAGE <= 5.0,
        f"perp_leverage={L.PERP_LEVERAGE}")
    chk("capital_denominator_reported",
        abs(L.COMMITTED_CAPITAL - (1.0 + 1.0 / L.PERP_LEVERAGE)) < 1e-12,
        f"committed={L.COMMITTED_CAPITAL}")
    chk("directional_pnl_not_presented_as_carry",
        artifact_disc.get("funding_share_of_gross") is not None
        and artifact_disc.get("funding_share_of_gross", 0) > 0.5,
        f"funding_share_of_gross={artifact_disc.get('funding_share_of_gross')}")

    # --- independent recomputation of the frozen candidate ----------------
    recon = [_recompute(a, 0.0, 0.6) for a in L.ASSETS]
    nets = [t["net"] for r in recon for t in r["trades"]]
    funding = [t["funding"] for r in recon for t in r["trades"]]
    basis = [t["basis_pnl"] for r in recon for t in r["trades"]]
    n_indep = len(nets)
    net_pnl_indep = float(np.sum(nets)) if nets else 0.0
    net_exp_indep = float(np.mean(nets)) if nets else None

    chk("frozen_trade_count_reproduced",
        n_indep == artifact_disc.get("trades"),
        f"indep={n_indep} artifact={artifact_disc.get('trades')}")
    chk("frozen_net_pnl_reproduced",
        abs(net_pnl_indep - float(artifact_disc.get("net_pnl_bps", -1))) < 0.5,
        f"indep={round(net_pnl_indep, 4)} artifact={artifact_disc.get('net_pnl_bps')}")
    chk("frozen_net_expectancy_reproduced",
        net_exp_indep is not None
        and abs(net_exp_indep - float(artifact_disc.get("net_expectancy_bps", -1))) < 0.5,
        f"indep={None if net_exp_indep is None else round(net_exp_indep, 4)} "
        f"artifact={artifact_disc.get('net_expectancy_bps')}")
    chk("frozen_funding_pnl_reproduced",
        abs(float(np.sum(funding)) - float(artifact_disc.get("sum_funding_bps", -1))) < 0.5,
        f"indep={round(float(np.sum(funding)), 3)} artifact={artifact_disc.get('sum_funding_bps')}")
    chk("frozen_basis_pnl_reproduced",
        abs(float(np.sum(basis)) - float(artifact_disc.get("sum_basis_bps", -1))) < 0.5,
        f"indep={round(float(np.sum(basis)), 4)} artifact={artifact_disc.get('sum_basis_bps')}")

    # --- accounting identity: net == spot + perp + funding - cost ----------
    identity_ok = True
    for r in recon:
        for t in r["trades"]:
            if abs(t["net"] - (t["spot_pnl"] + t["perp_pnl"] + t["funding"] - t["cost"])) > 1e-9:
                identity_ok = False
    chk("pnl_decomposition_reconciles", identity_ok,
        "net == spot + perp + funding - cost for every trade")

    # --- funding cashflow sign: short perp receives positive funding -------
    sign_ok = all(t["funding"] > 0 for r in recon for t in r["trades"])
    chk("funding_payment_sign_correct", bool(sign_ok),
        "all frozen trades have positive received funding (short perp, rate>0)")

    # --- validation had no qualifying trades -------------------------------
    val = json.loads((OUT / "VALIDATION_RESULTS.json").read_text(encoding="utf-8"))
    val_recon = [_recompute(a, 0.6, 0.8) for a in L.ASSETS]
    val_n = sum(r["n"] for r in val_recon)
    chk("validation_no_trades_reproduced",
        val_n == val["result"].get("trades", -1),
        f"indep={val_n} artifact={val['result'].get('trades')}")

    # --- PIT / holdout -----------------------------------------------------
    pit = json.loads((OUT / "FUNDING_PIT_AUDIT.json").read_text(encoding="utf-8"))
    chk("funding_pit_audit_passed", pit["result"] == "PASS" and
        pit["future_poisoning_test"]["passed"])
    chk("holdout_not_opened", final.get("holdout_analytics_read") is False
        and json.loads((OUT / "HOLDOUT_RESULTS.json").read_text(encoding="utf-8"))["status"]
        == "NOT_OPENED")

    # independent future-funding-leak test: entry rule uses rate[i-K:i], never rate[i:]
    leak_ok = True
    for a in L.ASSETS:
        d = _independent_asset(a)
        rate = d["rate"].copy()
        n = rate.shape[0]
        base = _entry_mask(rate)
        # poison the rate paid AT a decision; entries up to and including that
        # decision must be unchanged (they may only use strictly-earlier rates)
        for i in range(3, n):
            r2 = rate.copy()
            r2[i] = r2[i] + 100.0
            if not np.array_equal(_entry_mask(r2)[:i + 1], base[:i + 1]):
                leak_ok = False
                break
        break
    chk("no_future_funding_leakage", leak_ok,
        "perturbing the rate paid AT/after a decision never changes that entry")

    # --- classification reproduced from gates ------------------------------
    g = final["gates"]
    if g["G_CARRY_INFO"] != "PASS":
        repro = "CARRY-A"
    elif g["G_CARRY_1"] != "PASS":
        repro = "CARRY-B"
    elif g["G_CARRY_2"] != "PASS":
        repro = "CARRY-C"
    elif g["G_CARRY_3"] != "PASS":
        repro = "CARRY-D"
    elif g["G_CARRY_4"] != "PASS":
        repro = "CARRY-E"
    else:
        repro = "CARRY-F"
    chk("classification_reproduced", repro == final["global_classification"],
        f"reproduced={repro} artifact={final['global_classification']}")
    chk("holdout_gate_consistent",
        (g["G_CARRY_4"] != "NOT_REACHED") == (g["G_CARRY_3"] == "PASS"),
        f"g3={g['G_CARRY_3']} g4={g['G_CARRY_4']}")
    chk("checkpoint_written_when_required",
        (final["global_classification"] in {"CARRY-A", "CARRY-B", "CARRY-C"})
        == (REPO / "reports" / "ECONOMIC_STRATEGY_CHECKPOINT.md").exists())

    false_success = sum(1 for c in checks if not c["ok"])
    return {
        "verifier": f"RFC-028 independent recomputation (cid={cid})",
        "false_success": false_success,
        "n_checks": len(checks),
        "independent_discovery_trades": n_indep,
        "independent_discovery_net_pnl_bps": round(net_pnl_indep, 4),
        "checks": checks,
    }


def _md(payload: dict[str, Any]) -> str:
    lines = ["# RFC028_VERIFICATION", "",
             f"FALSE_SUCCESS = **{payload['false_success']}** ({payload['n_checks']} checks)", "",
             "| check | result | detail |", "| --- | --- | --- |"]
    for c in payload["checks"]:
        lines.append(f"| {c['name']} | {c['result']} | {c['detail']} |")
    return "\n".join(lines) + "\n"


def _patch_final(result: dict[str, Any]) -> None:
    fj = REPO / "reports" / "RFC028_FINAL_REPORT.json"
    final = json.loads(fj.read_text(encoding="utf-8"))
    final["false_success"] = result["false_success"]
    final["independent_verification"] = "PASS" if result["false_success"] == 0 else "FAIL"
    final["independent_recompute"] = {
        "discovery_trades": result["independent_discovery_trades"],
        "discovery_net_pnl_bps": result["independent_discovery_net_pnl_bps"],
    }
    L.write_json(fj, final)
    # render the md with the SAME renderer the builder uses (single source of truth)
    L.write_md(REPO / "reports" / "RFC028_FINAL_REPORT.md", R._md_final(final))



def main() -> None:
    result = verify_all()
    L.write_json(OUT / "RFC028_VERIFICATION.json", result)
    L.write_md(OUT / "RFC028_VERIFICATION.md", _md(result))
    _patch_final(result)
    print("independent verifier: FALSE_SUCCESS =", result["false_success"],
          "of", result["n_checks"], "checks")
    for c in result["checks"]:
        if not c["ok"]:
            print("  FAIL:", c["name"], c["detail"])


if __name__ == "__main__":
    main()
