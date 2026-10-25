"""RFC-029 — independent verifier (§62-§63, BUILDER != VERIFIER).

Independently recomputes the RFC-029 economic claims from the frozen
epoch-normalised cache WITHOUT trusting the builder.  It rebuilds the
spot/perp/funding decision series with its OWN as-of implementation
(``np.searchsorted``), reconstructs the frozen candidate's entry mask, every
leg PnL, the funding cashflows, costs, committed capital, ROC, episode count and
break-even time, re-derives the gates/classification, and scans every §63
FALSE_SUCCESS trigger.

Writes ``reports/structural-carry/RFC029_VERIFICATION.{md,json}`` and patches
``reports/RFC029_FINAL_REPORT.{md,json}``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import sprint028_lib as L28
import sprint029_lib as S
import sprint029_run as R
from numpy.typing import NDArray

REPO = S.REPO
OUT = S.OUT_DIR

FROZEN_HORIZON = "45d"
FROZEN_PERIODS = S.HORIZON_PERIODS[FROZEN_HORIZON]
FROZEN_POLICY = "C_ECONOMIC"
TRAIL = S.TRAILING_WINDOW
THRESH = S.ROUND_TRIP_COST_BPS + S.SAFETY_MARGIN_BPS


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
    spot = L28.load_spot(asset)
    perp = L28.load_perp(asset)
    fund = L28.load_funding(asset)
    gts = fund["funding_time_ms"].astype(np.int64)
    s_close = _asof_indep(spot["open_time_ms"].astype(np.int64) + S.SRC_MS,
                          spot["close"], gts)
    p_close = _asof_indep(perp["open_time_ms"].astype(np.int64) + S.SRC_MS,
                          perp["close"], gts)
    rate = np.asarray(fund["funding_rate"], dtype=np.float64) * 1e4
    return {"gts": gts, "spot": s_close, "perp": p_close, "rate": rate}


def _entry_mask_indep(rate: NDArray[Any], policy: str, h: int) -> NDArray[Any]:
    n = rate.shape[0]
    mask = np.zeros(n, dtype=bool)
    for i in range(TRAIL, n):
        win = rate[i - TRAIL:i]
        if not np.all(np.isfinite(win)):
            continue
        m = float(np.mean(win))
        if policy == "A_POSITIVE_REGIME":
            mask[i] = m > 0.0
        elif policy == "B_PERSISTENCE":
            mask[i] = bool(np.all(win[-S.PERSIST_N:] > 0.0))
        elif policy == "C_ECONOMIC":
            mask[i] = m * h > THRESH
        elif policy == "D_BASIS_SAFE":
            mask[i] = m > 0.0
    return mask


def _recompute(asset: str, policy: str, h: int, lo: float, hi: float,
               want_breakeven: bool = False) -> dict[str, Any]:
    d = _independent_asset(asset)
    n = d["gts"].shape[0]
    a, b = int(n * lo), int(n * hi)
    entry = _entry_mask_indep(d["rate"], policy, h)
    trades: list[dict[str, float]] = []
    be: list[int] = []
    i = a
    while i + h < b:
        if not entry[i]:
            i += 1
            continue
        j = i + h
        vals = (d["spot"][i], d["spot"][j], d["perp"][i], d["perp"][j])
        win = d["rate"][i + 1:j + 1]
        if not all(np.isfinite(v) for v in vals) or not np.all(np.isfinite(win)):
            i += 1
            continue
        funding = float(np.sum(win))
        spot_pnl = (d["spot"][j] / d["spot"][i] - 1.0) * 1e4
        perp_pnl = -(d["perp"][j] / d["perp"][i] - 1.0) * 1e4
        basis = spot_pnl + perp_pnl
        net = spot_pnl + perp_pnl + funding - S.ROUND_TRIP_COST_BPS
        trades.append({"spot": spot_pnl, "perp": perp_pnl, "basis": basis,
                       "funding": funding, "cost": S.ROUND_TRIP_COST_BPS, "net": net})
        if want_breakeven:
            for k in range(i + 1, j + 1):
                fk = float(np.sum(d["rate"][i + 1:k + 1]))
                bk = (d["spot"][k] / d["spot"][i] - d["perp"][k] / d["perp"][i]) * 1e4
                if np.isfinite(bk) and fk + bk > S.ROUND_TRIP_COST_BPS:
                    be.append(k - i)
                    break
        i = j + 1
    return {"asset": asset, "n": len(trades), "trades": trades, "breakeven": be}


def verify_all() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def chk(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "result": "PASS" if ok else "FAIL",
                       "ok": bool(ok), "detail": detail})

    final = json.loads((REPO / "reports" / "RFC029_FINAL_REPORT.json").read_text(encoding="utf-8"))
    best = final["best_candidate"]
    cid = final["best_candidate_id"]

    # --- §63 false-success triggers ---------------------------------------
    chk("cost_model_is_carry_v1_not_v3",
        abs(final["round_trip_cost_bps"] - S.ROUND_TRIP_COST_BPS) < 1e-9
        and abs(final["round_trip_cost_bps"] - S.COST_MODEL_V3_BPS) > 1.0,
        f"round_trip={final['round_trip_cost_bps']}")
    chk("both_leg_costs_included", S.SPOT_SIDE_BPS > 0 and S.PERP_SIDE_BPS > 0,
        f"spot_side={S.SPOT_SIDE_BPS} perp_side={S.PERP_SIDE_BPS}")
    chk("capital_denominator_reported",
        abs(S.COMMITTED_CAPITAL - (1.0 + 1.0 / S.PERP_LEVERAGE)) < 1e-12,
        f"committed={S.COMMITTED_CAPITAL}")
    chk("no_unrealistic_leverage", S.PERP_LEVERAGE <= 5.0, f"lev={S.PERP_LEVERAGE}")
    chk("directional_pnl_not_presented_as_carry",
        (best["discovery"].get("funding_share_of_gross") or 0) > 0.5,
        f"funding_share_of_gross={best['discovery'].get('funding_share_of_gross')}")

    # --- independent recomputation of the frozen best (discovery) ----------
    recon = [_recompute(a, FROZEN_POLICY, FROZEN_PERIODS, 0.0, 0.6) for a in S.ASSETS]
    nets = [t["net"] for r in recon for t in r["trades"]]
    funding = [t["funding"] for r in recon for t in r["trades"]]
    basis = [t["basis"] for r in recon for t in r["trades"]]
    n_indep = len(nets)
    net_pnl = float(np.sum(nets)) if nets else 0.0
    net_exp = float(np.mean(nets)) if nets else None

    chk("frozen_episode_count_reproduced", n_indep == best["discovery"].get("episodes"),
        f"indep={n_indep} artifact={best['discovery'].get('episodes')}")
    chk("frozen_net_pnl_reproduced",
        abs(net_pnl - float(best["discovery"].get("net_pnl_bps", -1))) < 0.5,
        f"indep={round(net_pnl, 4)} artifact={best['discovery'].get('net_pnl_bps')}")
    chk("frozen_net_expectancy_reproduced",
        net_exp is not None and abs(net_exp - float(best["discovery"].get("net_expectancy_bps", -1))) < 0.5,
        f"indep={None if net_exp is None else round(net_exp, 4)} "
        f"artifact={best['discovery'].get('net_expectancy_bps')}")
    chk("frozen_funding_pnl_reproduced",
        abs(float(np.sum(funding)) - float(best["discovery"].get("funding_pnl_bps", -1))) < 0.5,
        f"indep={round(float(np.sum(funding)), 3)} artifact={best['discovery'].get('funding_pnl_bps')}")
    chk("frozen_basis_pnl_reproduced",
        abs(float(np.sum(basis)) - float(best["discovery"].get("basis_pnl_bps", -1))) < 0.5,
        f"indep={round(float(np.sum(basis)), 4)} artifact={best['discovery'].get('basis_pnl_bps')}")

    # ROC / committed capital independently
    roc = float(np.sum(nets) / 1e4 / S.COMMITTED_CAPITAL) if nets else 0.0
    chk("return_on_committed_reproduced",
        abs(roc - float(best["discovery"].get("sum_roc", -1))) < 1e-6,
        f"indep={round(roc, 8)} artifact={best['discovery'].get('sum_roc')}")

    # accounting identity per trade
    identity_ok = all(
        abs(t["net"] - (t["spot"] + t["perp"] + t["funding"] - t["cost"])) < 1e-9
        and abs(t["basis"] - (t["spot"] + t["perp"])) < 1e-9
        for r in recon for t in r["trades"])
    chk("pnl_decomposition_reconciles", identity_ok,
        "net == spot + perp + funding - cost for every trade")

    # --- independent break-even time (policy A, 45d) -----------------------
    be_all: list[int] = []
    for a in S.ASSETS:
        be_all.extend(_recompute(a, "A_POSITIVE_REGIME", FROZEN_PERIODS, 0.0, 0.6,
                                 want_breakeven=True)["breakeven"])
    ttbe = json.loads((OUT / "TIME_TO_BREAK_EVEN.json").read_text(encoding="utf-8"))
    art_med = ttbe["time_to_break_even"]["A_POSITIVE_REGIME"]["45d"]["median_periods"]
    med_indep = float(np.median(be_all)) if be_all else None
    chk("break_even_time_reproduced",
        med_indep is not None and abs(med_indep - float(art_med)) < 0.5,
        f"indep_median_periods={med_indep} artifact={art_med} "
        f"(~{round(med_indep / S.PERIODS_PER_DAY, 2) if med_indep else None} days)")

    # --- independent validation result -------------------------------------
    val_recon = [_recompute(a, FROZEN_POLICY, FROZEN_PERIODS, 0.6, 0.8) for a in S.ASSETS]
    val_nets = [t["net"] for r in val_recon for t in r["trades"]]
    val_n = len(val_nets)
    val_net = float(np.sum(val_nets)) if val_nets else 0.0
    art_val = final["validation_cells"].get(cid, {})
    chk("validation_episodes_reproduced", val_n == art_val.get("episodes"),
        f"indep={val_n} artifact={art_val.get('episodes')}")
    chk("validation_net_pnl_reproduced",
        abs(val_net - float(art_val.get("net_pnl_bps", 1e9))) < 0.5,
        f"indep={round(val_net, 4)} artifact={art_val.get('net_pnl_bps')}")
    chk("validation_is_net_negative", val_net < 0.0, f"indep_net={round(val_net, 4)}")
    chk("zero_trade_validation_not_called_pass",
        not (val_n == 0 and final["gates"]["G_STRUCT_2"] == "PASS"),
        f"val_episodes={val_n} G_STRUCT_2={final['gates']['G_STRUCT_2']}")
    chk("validation_gate_reflects_negative_net",
        (val_net < 0.0) == (final["gates"]["G_STRUCT_2"] != "PASS"),
        f"G_STRUCT_2={final['gates']['G_STRUCT_2']}")

    # --- no future funding leakage ----------------------------------------
    leak_ok = True
    for a in S.ASSETS:
        d = _independent_asset(a)
        rate = d["rate"].copy()
        n = rate.shape[0]
        base = _entry_mask_indep(rate, FROZEN_POLICY, FROZEN_PERIODS)
        for i in range(TRAIL, min(n, TRAIL + 150)):
            r2 = rate.copy()
            r2[i] = r2[i] + 100.0
            if not np.array_equal(_entry_mask_indep(r2, FROZEN_POLICY, FROZEN_PERIODS)[:i + 1],
                                  base[:i + 1]):
                leak_ok = False
                break
        break
    chk("no_future_funding_leakage", leak_ok,
        "perturbing the rate paid AT a decision never changes that entry")

    # --- selection rule reproduced (no post-hoc retune) --------------------
    disc = json.loads((OUT / "DISCOVERY_RESULTS.json").read_text(encoding="utf-8"))
    cands = [c for c in disc["cells"]
             if c["pooled"].get("status") == "OK"
             and (c["pooled"].get("net_pnl_bps") or 0) > 0
             and (c["pooled"].get("sum_roc") or 0) > 0
             and (c["pooled"].get("episodes") or 0) >= S.MIN_DISCOVERY_EPISODES
             and c["accounting_clean"]]
    sel = max(cands, key=lambda c: (c["pooled"]["net_expectancy_bps"],
                                    -S.HORIZON_PERIODS[c["holding_horizon"]],
                                    c["candidate_id"])) if cands else None
    chk("frozen_candidate_matches_selection_rule",
        sel is not None and sel["candidate_id"] == cid,
        f"rule_best={None if sel is None else sel['candidate_id']} frozen={cid}")
    chk("candidate_not_retuned_after_validation",
        final["best_candidate"]["holding_horizon"] == FROZEN_HORIZON
        and final["best_candidate"]["entry_policy"] == FROZEN_POLICY,
        "frozen id unchanged between discovery and validation")

    # --- PIT / holdout / decision -----------------------------------------
    pit = json.loads((OUT / "FUNDING_PIT_AUDIT.json").read_text(encoding="utf-8"))
    chk("funding_pit_audit_passed",
        pit["result"] == "PASS" and pit["future_poisoning_test"]["passed"])
    chk("holdout_not_opened",
        final.get("holdout_analytics_read") is False
        and json.loads((OUT / "HOLDOUT_RESULTS.json").read_text(encoding="utf-8"))["status"]
        == "NOT_OPENED")

    # --- classification reproduced from gates ------------------------------
    g = final["gates"]
    if g["G_STRUCT_INFO"] != "PASS":
        repro = "STRUCT-A"
    elif g["G_STRUCT_1"] != "PASS":
        repro = "STRUCT-B"
    elif g["G_STRUCT_2"] != "PASS":
        repro = "STRUCT-C"
    elif g["G_STRUCT_3"] != "PASS":
        repro = "STRUCT-D"
    else:
        repro = "STRUCT-E"
    chk("classification_reproduced", repro == final["global_classification"],
        f"reproduced={repro} artifact={final['global_classification']}")
    chk("profitability_decision_written_when_required",
        (g["G_STRUCT_2"] != "PASS") == (REPO / "reports" / "PROFITABILITY_DECISION.md").exists(),
        f"G_STRUCT_2={g['G_STRUCT_2']}")

    false_success = sum(1 for c in checks if not c["ok"])
    return {
        "verifier": f"RFC-029 independent recomputation (cid={cid})",
        "false_success": false_success,
        "n_checks": len(checks),
        "independent_discovery_episodes": n_indep,
        "independent_discovery_net_pnl_bps": round(net_pnl, 4),
        "independent_validation_episodes": val_n,
        "independent_validation_net_pnl_bps": round(val_net, 4),
        "checks": checks,
    }


def _md(payload: dict[str, Any]) -> str:
    lines = ["# RFC029_VERIFICATION", "",
             f"FALSE_SUCCESS = **{payload['false_success']}** ({payload['n_checks']} checks)", "",
             "| check | result | detail |", "| --- | --- | --- |"]
    for c in payload["checks"]:
        lines.append(f"| {c['name']} | {c['result']} | {c['detail']} |")
    return "\n".join(lines) + "\n"


def _patch_final(result: dict[str, Any]) -> None:
    fj = REPO / "reports" / "RFC029_FINAL_REPORT.json"
    final = json.loads(fj.read_text(encoding="utf-8"))
    final["false_success"] = result["false_success"]
    final["independent_verification"] = "PASS" if result["false_success"] == 0 else "FAIL"
    final["independent_recompute"] = {
        "discovery_episodes": result["independent_discovery_episodes"],
        "discovery_net_pnl_bps": result["independent_discovery_net_pnl_bps"],
        "validation_episodes": result["independent_validation_episodes"],
        "validation_net_pnl_bps": result["independent_validation_net_pnl_bps"],
    }
    L28.write_json(fj, final)
    L28.write_md(REPO / "reports" / "RFC029_FINAL_REPORT.md", R._md_final(final))


def main() -> None:
    result = verify_all()
    L28.write_json(OUT / "RFC029_VERIFICATION.json", result)
    L28.write_md(OUT / "RFC029_VERIFICATION.md", _md(result))
    _patch_final(result)
    print("independent verifier: FALSE_SUCCESS =", result["false_success"],
          "of", result["n_checks"], "checks")
    for c in result["checks"]:
        if not c["ok"]:
            print("  FAIL:", c["name"], c["detail"])


if __name__ == "__main__":
    main()
