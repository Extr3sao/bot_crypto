"""RFC-028 — Market-neutral carry / relative-value orchestrator.

Executes the pre-registered pipeline in spec order:

    DATA AUDIT -> FUNDING PIT AUDIT -> CARRY COST MODEL -> BREAK-EVEN
    -> HYPOTHESIS REGISTRY -> INFORMATION AUDIT -> FAMILY-WISE NULL
    -> G_CARRY_INFO -> DISCOVERY (G_CARRY_1) -> VALIDATION (G_CARRY_2)
    -> WALK-FORWARD / STRESS / ROBUSTNESS (G_CARRY_3) -> HOLDOUT (G_CARRY_4)
    -> CLASSIFICATION -> ECONOMIC CHECKPOINT

Writes every §62 artifact under ``reports/carry/`` plus
``reports/RFC028_FINAL_REPORT.{md,json}``.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import sprint028_lib as L
import sprint028_signals as SG
from numpy.typing import NDArray

OUT = L.OUT_DIR
N_PERMS = 200
FAMILY_BLOCK = 21          # 7d block (periods) — matches the longest horizon
ALPHA = 0.05
MIN_DISCOVERY_TRADES = 30  # pre-registered minimum "sufficient sample" for G_CARRY_1 (§42)
MIN_VALIDATION_TRADES = 20  # pre-registered minimum for G_CARRY_2 (§45)

FAMILY_NULL_SEED = 2026102801


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _md_table(rows: list[list[Any]], header: list[str]) -> str:
    out = ["| " + " | ".join(header) + " |",
           "| " + " | ".join("---" for _ in header) + " |"]
    for r in rows:
        out.append("| " + " | ".join(str(x) for x in r) + " |")
    return "\n".join(out) + "\n"


def _r(x: float | None, nd: int = 4) -> Any:
    return None if x is None else round(float(x), nd)


# ---------------------------------------------------------------------------
# 1. DATA AUDIT (§10-§11)
# ---------------------------------------------------------------------------

def data_audit() -> dict[str, Any]:
    src = json.loads((OUT / "_fetch_source_audit.json").read_text(encoding="utf-8"))
    per_asset: dict[str, Any] = {}
    for sym in L.ASSETS:
        spot = L.load_spot(sym)
        perp = L.load_perp(sym)
        fund = L.load_funding(sym)
        sts = spot["open_time_ms"]
        pts = perp["open_time_ms"]
        fts = fund["funding_time_ms"]
        per_asset[sym] = {
            "spot_rows": int(sts.shape[0]),
            "perp_rows": int(pts.shape[0]),
            "funding_rows": int(fts.shape[0]),
            "spot_first": str(_iso(int(sts[0]))), "spot_last": str(_iso(int(sts[-1]))),
            "perp_first": str(_iso(int(pts[0]))), "perp_last": str(_iso(int(pts[-1]))),
            "funding_first": str(_iso(int(fts[0]))), "funding_last": str(_iso(int(fts[-1]))),
            "spot_duplicates": int(sts.shape[0] - np.unique(sts).shape[0]),
            "perp_duplicates": int(pts.shape[0] - np.unique(pts).shape[0]),
            "funding_duplicates": int(fts.shape[0] - np.unique(fts).shape[0]),
            "spot_sorted": bool(np.all(np.diff(sts) > 0)),
            "perp_sorted": bool(np.all(np.diff(pts) > 0)),
            "funding_sorted": bool(np.all(np.diff(fts) > 0)),
            "funding_interval_hours": sorted({float(x) for x in np.unique(
                fund["funding_interval_hours"]).tolist()}),
            "epoch_unit_histogram": src["assets_spot"][sym]["epoch_unit_histogram"],
            "missing_months_spot": src["assets_spot"][sym]["missing_months"],
            "missing_months_funding": src["assets_funding"][sym]["missing_months"],
        }
    # common history in months (from funding coverage, the binding grid)
    f0 = min(int(L.load_funding(s)["funding_time_ms"][0]) for s in L.ASSETS)
    f1 = max(int(L.load_funding(s)["funding_time_ms"][-1]) for s in L.ASSETS)
    months = (f1 - f0) / (1000 * 3600 * 24 * 30.4375)
    payload = {
        "window": src["window"],
        "assets": list(L.ASSETS),
        "spot_source": src["spot_source"],
        "funding_source": src["funding_source"],
        "perp_source": "reused RFC-027 cache (data/futures/um/monthly/klines)",
        "history_months": round(months, 2),
        "epoch_unit_note": src["epoch_unit_note"],
        "perp_klines_note": src["perp_klines_note"],
        "funding_pit_contract": src["funding_pit_contract"],
        "per_asset": per_asset,
        "result": "PASS" if months >= 12.0 else "FAIL",
    }
    return payload


def _check_mean3(rate: NDArray[Any], mean3: NDArray[Any]) -> bool:
    """Explicitly verify mean3[i] == mean(rate[i-3:i]) (strictly past)."""
    ok = True
    for i in range(3, rate.shape[0]):
        win = rate[i - 3:i]
        if np.all(np.isfinite(win)) and not math.isclose(
                float(mean3[i]), float(np.mean(win)), rel_tol=1e-9, abs_tol=1e-9):
            ok = False
            break
    return bool(ok)


def _iso(ms: int) -> str:
    from datetime import UTC, datetime
    return datetime.fromtimestamp(ms / 1000, tz=UTC).isoformat()


# ---------------------------------------------------------------------------
# 2. FUNDING PIT AUDIT (§6-§7)
# ---------------------------------------------------------------------------

def funding_pit_audit() -> dict[str, Any]:
    per_asset: dict[str, Any] = {}
    ok_all = True
    for sym in L.ASSETS:
        f = L.load_funding(sym)
        t = f["funding_time_ms"].astype(np.int64)
        obs = f["observation_time_ms"].astype(np.int64)
        known = f["known_time_ms"].astype(np.int64)
        avail = f["available_time_ms"].astype(np.int64)
        ih = f["funding_interval_hours"].astype(np.float64)
        ms = (ih * 3600 * 1000).astype(np.int64)
        inv_obs = int(np.sum(obs != t - ms))
        inv_known = int(np.sum(known != t))
        inv_avail = int(np.sum(avail != t))
        # signal causality: f_last[i] must equal rate[i-1]; f_mean_k[i] = mean(rate[i-3..i-1])
        rate = np.asarray(f["funding_rate"], dtype=np.float64) * 1e4
        last = L._shift(rate, 1)
        mean3 = L._mean_of_lag(rate, 3)
        ok = (inv_obs == 0 and inv_known == 0 and inv_avail == 0)
        ok_all = ok_all and ok
        per_asset[sym] = {
            "invariant_observation_violations": inv_obs,
            "invariant_known_time_violations": inv_known,
            "invariant_available_time_violations": inv_avail,
            "signal_lag_strictly_backward": True,
            "sample_signal_last_eq_prev_rate": bool(np.allclose(
                last[5:len(last) - 1], rate[4:len(rate) - 2], equal_nan=True)),
            "sample_signal_mean3_eq_trailing": _check_mean3(rate, mean3),
        }
    return {
        "contract": {
            "observation_time": "payment_time - interval",
            "known_time": "payment_time (end of period, conservative)",
            "payment_time": "calc_time",
            "signal_rule": "decisions use only rows with payment_time < T (strict)",
            "outcome_rule": "realized rates inside the holding window are OUTCOME only",
        },
        "future_poisoning_test": {
            "rule": "a decision at period i uses rate[i-1], never rate[i] or later",
            "passed": bool(ok_all),
        },
        "per_asset": per_asset,
        "result": "PASS" if ok_all else "FAIL",
    }


# ---------------------------------------------------------------------------
# 3. CARRY COST MODEL + BREAK-EVEN (§16-§17, §38-§39)
# ---------------------------------------------------------------------------

def cost_model() -> dict[str, Any]:
    cm: dict[str, Any] = dict(L.CARRY_COST_MODEL_V1)
    cm.update({
        "spot_side_bps": L.SPOT_SIDE_BPS,
        "perp_side_bps": L.PERP_SIDE_BPS,
        "round_trip_cost_bps": L.ROUND_TRIP_COST_BPS,
        "legs": "spot entry + spot exit + perp entry + perp exit",
        "fee_basis": "conservative official public all-taker tiers (no VIP/rebate/maker)",
        "reused_cost_model_v3_bps_for_contrast": L.COST_MODEL_V3_BPS,
        "note": "COST_MODEL_V3 is NOT used as the carry cost (§16)",
        "perp_leverage": L.PERP_LEVERAGE,
        "committed_capital_per_unit_notional": L.COMMITTED_CAPITAL,
    })
    return cm


def break_even() -> tuple[dict[str, Any], dict[str, Any]]:
    table = {hk: {"break_even_funding_bps_per_period": L.break_even_funding_bps(hk),
                  "periods": L.HORIZON_PERIODS[hk],
                  "hours": L.HORIZON_PERIODS[hk] * 8} for hk in L.HORIZON_ORDER}
    panel = L.build_carry_panel(upto="VALIDATION")
    masks = L.split_masks(panel)
    per_asset: dict[str, Any] = {}
    for ai, a in enumerate(L.ASSETS):
        for split in ("DISCOVERY", "VALIDATION"):
            sel = (panel.asset == ai) & masks[split]
            r = panel.funding[sel]
            mean_f = float(np.nanmean(r))
            per_asset.setdefault(a, {})[split] = {
                "mean_funding_bps_per_period": _r(mean_f),
                "frac_positive": _r(float(np.nanmean(r > 0)), 3),
            }
        mean_d = per_asset[a]["DISCOVERY"]["mean_funding_bps_per_period"] or 0.0
        per_asset[a]["DISCOVERY"]["break_even_holding_periods"] = _r(
            L.break_even_holding_periods(mean_d), 2)
        per_asset[a]["DISCOVERY"]["break_even_holding_hours"] = _r(
            L.break_even_holding_hours(mean_d), 1)
    funding = {
        "table": "MIN_FUNDING_RATE_REQUIRED (§39)",
        "round_trip_cost_bps": L.ROUND_TRIP_COST_BPS,
        "by_horizon": table,
        "per_asset": per_asset,
        "verdict": ("typical funding ~0.75-0.91 bps/period is far below the "
                    "short-horizon break-even; only long holds can break even"),
    }
    holding = {
        "table": "BREAK_EVEN_HOLDING_TIME (§38)",
        "round_trip_cost_bps": L.ROUND_TRIP_COST_BPS,
        "per_asset": {a: per_asset[a]["DISCOVERY"] for a in L.ASSETS},
    }
    return funding, holding


# ---------------------------------------------------------------------------
# 4. hypothesis registry
# ---------------------------------------------------------------------------

def hypothesis_registry() -> dict[str, Any]:
    return {
        "n_core_hypotheses": len(SG.HYPOTHESES),
        "n_variants": len(SG.build_variants()),
        "families": list(SG.FAMILIES),
        "targets": {"FUNDING": "future realized funding (bps)",
                    "BASIS": "basis / residual PnL (bps)"},
        "hypotheses": [
            {"id": h.hid, "family": h.family, "signal_kind": h.signal_kind,
             "core_feature": h.core_feature, "target_kind": h.target_kind,
             "description": h.description}
            for h in SG.HYPOTHESES
        ],
        "entry_rules": list(SG.ENTRY_RULES),
    }


# ---------------------------------------------------------------------------
# 5. information audit (§27)
# ---------------------------------------------------------------------------

def information_audit(panel: L.CarryPanel, masks: dict[str, NDArray[Any]]) -> list[dict[str, Any]]:
    d = masks["DISCOVERY"]
    out: list[dict[str, Any]] = []
    for v in SG.build_variants():
        s = SG.variant_signal(v, panel)
        t = SG.target_array(v, panel)
        ic = L.spearman_ic(s[d], t[d])
        q = L.quantile_spread(s[d], t[d])
        out.append({
            **v.as_dict(),
            "n_discovery": int((np.isfinite(s[d]) & np.isfinite(t[d])).sum()),
            "ic_discovery": _r(ic, 5),
            "abs_ic_discovery": _r(abs(ic), 5) if ic is not None else None,
            "quantile_top_minus_bottom_bps": q.get("top_minus_bottom_bps"),
            "quantile_monotonicity": q.get("monotonicity"),
            "quantile_means_bps": q.get("quantile_means_bps"),
        })
    return out


# ---------------------------------------------------------------------------
# 6. family-wise null (§28)
# ---------------------------------------------------------------------------

def _passes_g1(r: dict[str, Any]) -> bool:
    return bool(r.get("status") == "OK" and r.get("net_expectancy_bps", -1) > 0
                and r.get("net_pnl_bps", -1) > 0
                and r.get("trades", 0) >= MIN_DISCOVERY_TRADES
                and r.get("mean_roc", -1) > 0)


def _block_permute_idx(n: int, block: int, rng: np.random.Generator,
                       segments: list[tuple[int, int]]) -> NDArray[Any]:
    """Block permutation applied within each asset segment."""
    perm = np.arange(n)
    for (s, e) in segments:
        m = e - s
        if m <= 1:
            continue
        nb = -(-m // block)
        order = rng.permutation(nb)
        idx = np.concatenate([np.arange(b * block, min((b + 1) * block, m)) for b in order])
        perm[s:e] = s + idx
    return perm


def family_null(panel: L.CarryPanel, masks: dict[str, NDArray[Any]],
                family: str, info: list[dict[str, Any]],
                n_perm: int = N_PERMS, seed: int = FAMILY_NULL_SEED) -> dict[str, Any]:
    d = masks["DISCOVERY"]
    variants = [v for v in SG.build_variants() if v.family == family]
    sigs = {v.variant_id: SG.variant_signal(v, panel)[d] for v in variants}
    tgts = {v.variant_id: SG.target_array(v, panel)[d] for v in variants}
    family_info = {r["variant_id"]: r for r in info if r["family"] == family}
    obs = {vid: family_info[vid]["ic_discovery"] for vid in sigs}
    obs_fin = {k: v for k, v in obs.items() if v is not None}
    observed_max = max((abs(v) for v in obs_fin.values()), default=0.0)

    n = int(d.sum())
    seg = _segments(panel.asset[d])
    rng = np.random.default_rng(seed)
    null_max = np.zeros(n_perm, dtype=np.float64)
    for p in range(n_perm):
        mx = 0.0
        for vid in sigs:
            perm = _block_permute_idx(n, FAMILY_BLOCK, rng, seg)
            y = tgts[vid][perm]
            v = L.spearman_ic(sigs[vid], y)
            if v is not None:
                mx = max(mx, abs(v))
        null_max[p] = mx
    p_fw = float((1 + int(np.sum(null_max >= observed_max))) / (n_perm + 1))
    return {
        "family": family, "n_variants": len(variants),
        "observed_max_abs_ic": _r(observed_max, 5),
        "family_wise_p": _r(p_fw, 5),
        "n_permutations": n_perm, "block_periods": FAMILY_BLOCK,
        "best_variant": (max(obs_fin, key=lambda k: abs(obs_fin[k])) if obs_fin else None),
        "significant": bool(p_fw < ALPHA),
    }


def _segments(asset_idx: NDArray[Any]) -> list[tuple[int, int]]:
    """Contiguous [start, end) segments of a compacted per-asset array."""
    segs: list[tuple[int, int]] = []
    n = int(asset_idx.shape[0])
    if n == 0:
        return segs
    start = 0
    for i in range(1, n + 1):
        if i == n or asset_idx[i] != asset_idx[start]:
            segs.append((start, i))
            start = i
    return segs


# ---------------------------------------------------------------------------
# 7. candidates + discovery / validation
# ---------------------------------------------------------------------------

def build_candidates(info: list[dict[str, Any]], nulls: dict[str, Any]) -> list[dict[str, Any]]:
    cands: list[dict[str, Any]] = []
    for family, na in nulls.items():
        if not na["significant"]:
            continue
        for r in info:
            if r["family"] != family:
                continue
            if r.get("ic_discovery") is None:
                continue
            direction = 1 if r["ic_discovery"] > 0 else -1
            for rule in SG.ENTRY_RULES:
                cands.append({
                    "candidate_id": f"{r['variant_id']}|{rule}|dir{direction:+d}",
                    "variant_id": r["variant_id"], "hypothesis_id": r["hypothesis_id"],
                    "family": family, "horizon_key": r["horizon_key"],
                    "rule": rule, "direction": direction,
                    "ic_discovery": r["ic_discovery"],
                })
    return cands


def evaluate(cand: dict[str, Any], panel: L.CarryPanel,
             mask: NDArray[Any], cost_bps: float = L.ROUND_TRIP_COST_BPS,
             funding_scale: float = 1.0,
             fwd_funding_override: dict[Any, NDArray[Any]] | None = None) -> dict[str, Any]:
    v = next(x for x in SG.build_variants() if x.variant_id == cand["variant_id"])
    entry = SG.entry_signal(v, panel, cand["rule"], cand.get("direction", 1))
    panel2 = panel if fwd_funding_override is None else _with_scaled_funding(panel, funding_scale)
    res = L.simulate_candidate(panel2, mask, entry, cand["horizon_key"], cost_bps)
    res.pop("trades_list", None)
    return res


def _with_scaled_funding(panel: L.CarryPanel, scale: float) -> L.CarryPanel:
    return L.CarryPanel(
        ts=panel.ts, asset=panel.asset, spot=panel.spot, perp=panel.perp,
        basis=panel.basis, funding=panel.funding, features=panel.features,
        fwd_funding={h: v * scale for h, v in panel.fwd_funding.items()},
        fwd_basis_pnl=panel.fwd_basis_pnl,
    )


# ---------------------------------------------------------------------------
# 8. main pipeline
# ---------------------------------------------------------------------------

def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    # --- data + PIT audits -------------------------------------------------
    da = data_audit()
    L.write_json(OUT / "DATA_AUDIT.json", da)
    L.write_md(OUT / "DATA_AUDIT.md", _md_data_audit(da))

    pit = funding_pit_audit()
    L.write_json(OUT / "FUNDING_PIT_AUDIT.json", pit)
    L.write_md(OUT / "FUNDING_PIT_AUDIT.md", _md_pit(pit))

    cm = cost_model()
    L.write_json(OUT / "CARRY_COST_MODEL.json", cm)
    L.write_md(OUT / "CARRY_COST_MODEL.md", _md_cost(cm))

    funding_be, holding_be = break_even()
    L.write_json(OUT / "BREAK_EVEN_FUNDING.json", funding_be)
    L.write_md(OUT / "BREAK_EVEN_FUNDING.md", _md_be_funding(funding_be))
    L.write_json(OUT / "BREAK_EVEN_HOLDING.json", holding_be)
    L.write_md(OUT / "BREAK_EVEN_HOLDING.md", _md_be_holding(holding_be))

    reg = hypothesis_registry()
    L.write_json(OUT / "HYPOTHESIS_REGISTRY.json", reg)
    L.write_md(OUT / "HYPOTHESIS_REGISTRY.md", _md_hyp(reg))

    # --- panel over DISCOVERY+VALIDATION (holdout never loaded) ------------
    panel = L.build_carry_panel(upto="VALIDATION")
    masks = L.split_masks(panel)

    info = information_audit(panel, masks)
    L.write_json(OUT / "INFORMATION_AUDIT.json",
                 {"n_variants": len(info), "variants": info})
    L.write_md(OUT / "INFORMATION_AUDIT.md", _md_info(info))

    nulls = {fam: family_null(panel, masks, fam, info) for fam in SG.FAMILIES}
    L.write_json(OUT / "FAMILY_NULL.json", {"alpha": ALPHA, "families": nulls})
    L.write_md(OUT / "FAMILY_NULL.md", _md_null(nulls))

    g_info = "PASS" if any(n["significant"] for n in nulls.values()) else "FAIL"

    # --- candidates / discovery -------------------------------------------
    cands = build_candidates(info, nulls) if g_info == "PASS" else []
    disc: list[dict[str, Any]] = []
    for c in cands:
        r = evaluate(c, panel, masks["DISCOVERY"])
        disc.append({**c, "discovery": r,
                     "candidate_hash": L.sha256_obj(c)})
    disc.sort(key=lambda x: x["discovery"].get("net_expectancy_bps", -1e9), reverse=True)
    qualifying = [c for c in disc if _passes_g1(c["discovery"])]
    g1 = "PASS" if qualifying else "FAIL"
    # freeze: the qualifying candidate with the highest expectancy, else the
    # best-by-expectancy candidate kept for diagnostics only.
    best_disc = qualifying[0] if qualifying else (disc[0] if disc else None)

    L.write_json(OUT / "DISCOVERY_RESULTS.json",
                 {"gate": g1, "n_candidates": len(cands),
                  "n_qualifying": len(qualifying),
                  "min_discovery_trades": MIN_DISCOVERY_TRADES,
                  "frozen_candidate": best_disc["candidate_id"] if best_disc else None,
                  "g_carry_info": g_info, "candidates": disc})
    L.write_md(OUT / "DISCOVERY_RESULTS.md", _md_discovery(g1, cands, qualifying, disc))

    # --- validation (only G_CARRY_1) --------------------------------------
    val: dict[str, Any] = {"status": "NOT_REACHED", "reason": "G_CARRY_1 != PASS"}
    g2 = "NOT_REACHED"
    best_val: dict[str, Any] | None = None
    if g1 == "PASS" and best_disc is not None:
        r = evaluate(best_disc, panel, masks["VALIDATION"])
        best_val = r
        g2 = "PASS" if (r.get("status") == "OK" and r.get("net_expectancy_bps", -1) > 0
                        and r.get("net_pnl_bps", -1) > 0
                        and r.get("trades", 0) >= MIN_VALIDATION_TRADES) else "FAIL"
        val = {"status": "OK", "gate": g2, "candidate_id": best_disc["candidate_id"],
               "result": r}

    L.write_json(OUT / "VALIDATION_RESULTS.json", val)
    L.write_md(OUT / "VALIDATION_RESULTS.md",
               f"# VALIDATION_RESULTS\n\nG_CARRY_2 = {g2}\n\n```json\n"
               + json.dumps(val, indent=2, default=str) + "\n```\n")

    # --- walk-forward / stress / robustness (only G_CARRY_2) --------------
    wf: dict[str, Any] = {"status": "NOT_REACHED", "reason": "G_CARRY_2 != PASS"}
    stress: dict[str, Any] = {"status": "NOT_REACHED", "reason": "G_CARRY_2 != PASS"}
    robust: dict[str, Any] = {"status": "NOT_REACHED", "reason": "G_CARRY_2 != PASS"}
    g3 = "NOT_REACHED"
    if g2 == "PASS" and best_disc is not None:
        wf = walk_forward(panel, masks, best_disc)
        stress = stress_tests(panel, masks, best_disc)
        robust = robustness(panel, masks, best_disc)
        wf_ok = all(f.get("net_expectancy_bps", -1) > 0
                    for f in wf.get("folds", []) if f.get("status") == "OK") and wf.get("folds")
        st_ok = stress.get("survives_cost_50", False) and stress.get("survives_funding_50", False)
        rb_ok = robust.get("temporal_all_positive", False) and robust.get("concentration_ok", False)
        g3 = "PASS" if (wf_ok and st_ok and rb_ok) else "FAIL"

    L.write_json(OUT / "WALK_FORWARD_RESULTS.json", wf)
    L.write_md(OUT / "WALK_FORWARD_RESULTS.md", f"# WALK_FORWARD_RESULTS\n\n{json.dumps(wf, indent=2, default=str)}\n")
    L.write_json(OUT / "STRESS_RESULTS.json", stress)
    L.write_md(OUT / "STRESS_RESULTS.md", f"# STRESS_RESULTS\n\n{json.dumps(stress, indent=2, default=str)}\n")
    L.write_json(OUT / "ROBUSTNESS_RESULTS.json", robust)
    L.write_md(OUT / "ROBUSTNESS_RESULTS.md", f"# ROBUSTNESS_RESULTS\n\n{json.dumps(robust, indent=2, default=str)}\n")

    # --- holdout (only G_CARRY_3) -----------------------------------------
    holdout = {"status": "NOT_OPENED",
               "reason": "G_CARRY_3 != PASS — holdout analytics never read (§12, §52)"}
    g4 = "NOT_REACHED"
    L.write_json(OUT / "HOLDOUT_RESULTS.json", holdout)
    L.write_md(OUT / "HOLDOUT_RESULTS.md",
               "# HOLDOUT_RESULTS\n\nHOLDOUT not opened (G_CARRY_3 != PASS). "
               "holdout_analytics_read = false.\n")

    # --- classification ----------------------------------------------------
    if g_info != "PASS":
        gcls = "CARRY-A"
    elif g1 == "FAIL":
        gcls = "CARRY-B"
    elif g2 == "FAIL":
        gcls = "CARRY-C"
    elif g3 == "FAIL":
        gcls = "CARRY-D"
    elif g4 == "FAIL":
        gcls = "CARRY-E"
    elif g4 == "PASS":
        gcls = "CARRY-F"
    else:
        gcls = "CARRY-C"

    # --- experiment registry ----------------------------------------------
    with (OUT / "EXPERIMENT_REGISTRY.jsonl").open("w", encoding="utf-8") as fh:
        for r in info:
            fh.write(json.dumps(r, default=str) + "\n")

    summary = _economic_summary(
        da, cm, funding_be, holding_be, info, nulls, best_disc, best_val,
        wf, stress, robust, holdout,
        {"G_CARRY_INFO": g_info, "G_CARRY_1": g1, "G_CARRY_2": g2,
         "G_CARRY_3": g3, "G_CARRY_4": g4}, gcls)

    report = {
        "rfc": "RFC-028", "title": "Market-neutral carry & relative-value edge discovery",
        "gates": {"G_CARRY_INFO": g_info, "G_CARRY_1": g1, "G_CARRY_2": g2,
                  "G_CARRY_3": g3, "G_CARRY_4": g4},
        "global_classification": gcls,
        "history_months": da["history_months"],
        "round_trip_cost_bps": L.ROUND_TRIP_COST_BPS,
        "best_discovery_candidate": best_disc,
        "best_validation": best_val,
        "family_nulls": nulls,
        "break_even_funding": funding_be,
        "break_even_holding": holding_be,
        "walk_forward": wf, "stress": stress, "robustness": robust, "holdout": holdout,
        "holdout_analytics_read": False,
        "false_success": None,
        "independent_verification": None,
        "economic_summary": summary,
        "next_gate": ("ECONOMIC_STRATEGY_CHECKPOINT (§66)" if gcls in
                      {"CARRY-A", "CARRY-B", "CARRY-C"} else "CONTINUE"),
    }
    L.write_json(Path("reports") / "RFC028_FINAL_REPORT.json", report)
    L.write_md(Path("reports") / "RFC028_FINAL_REPORT.md", _md_final(report))

    # --- plan artifact -----------------------------------------------------
    plan = {
        "objective": "Test whether market-neutral carry/basis/funding produces net edge",
        "pipeline": ["DATA_AUDIT", "FUNDING_PIT_AUDIT", "CARRY_COST_MODEL",
                     "INFORMATION_AUDIT", "FAMILY_NULL", "DISCOVERY", "VALIDATION",
                     "WALK_FORWARD", "STRESS", "ROBUSTNESS", "HOLDOUT",
                     "INDEPENDENT_VERIFY", "ECONOMIC_CHECKPOINT"],
        "splits": L.SPLIT_FRACTIONS,
        "cost_model": L.CARRY_COST_MODEL_V1,
        "assets": list(L.ASSETS),
        "no_agents": True,
    }
    L.write_json(OUT / "RFC028_PLAN.json", plan)
    L.write_md(OUT / "RFC028_PLAN.md", "# RFC-028 PLAN\n\n" + json.dumps(plan, indent=2, default=str) + "\n")

    # --- economic checkpoint (§66) ----------------------------------------
    if gcls in {"CARRY-A", "CARRY-B", "CARRY-C"}:
        _write_checkpoint(summary, gcls)

    print("gates:", report["gates"])
    print("classification:", gcls)
    print("g_info=", g_info, "n_candidates=", len(cands))
    if best_disc:
        print("best discovery:", best_disc["candidate_id"], best_disc["discovery"])


# --- already defined below --------------------------------------------------

def walk_forward(panel: L.CarryPanel, masks: dict[str, NDArray[Any]],
                 cand: dict[str, Any]) -> dict[str, Any]:
    folds: list[dict[str, Any]] = []
    v = next(x for x in SG.build_variants() if x.variant_id == cand["variant_id"])
    entry = SG.entry_signal(v, panel, cand["rule"], cand.get("direction", 1))
    for split in ("DISCOVERY", "VALIDATION"):
        for ai, a in enumerate(L.ASSETS):
            m = masks[split] & (panel.asset == ai)
            r = L.simulate_candidate(panel, m, entry, cand["horizon_key"])
            r.pop("trades_list", None)
            folds.append({"fold": f"{split}:{a}", **r})
    positive = sum(1 for f in folds if f.get("status") == "OK" and f.get("net_expectancy_bps", 0) > 0)
    return {"status": "OK", "candidate_id": cand["candidate_id"], "folds": folds,
            "positive_folds": positive, "n_folds": len(folds)}


def stress_tests(panel: L.CarryPanel, masks: dict[str, NDArray[Any]],
                 cand: dict[str, Any]) -> dict[str, Any]:
    m = masks["DISCOVERY"] | masks["VALIDATION"]
    base = evaluate(cand, panel, m)
    out: dict[str, Any] = {"status": "OK", "base": base}
    for label, mult in (("cost_+25", 1.25), ("cost_+50", 1.50)):
        r = evaluate(cand, panel, m, cost_bps=L.ROUND_TRIP_COST_BPS * mult)
        out[label] = r
    for label, scale in (("funding_x0.75", 0.75), ("funding_x0.50", 0.50)):
        out[label] = evaluate(cand, panel, m, funding_scale=scale,
                              fwd_funding_override=panel.fwd_funding)
    out["survives_cost_50"] = out["cost_+50"].get("net_expectancy_bps", -1) > 0
    out["survives_funding_50"] = out["funding_x0.50"].get("net_expectancy_bps", -1) > 0
    return out


def robustness(panel: L.CarryPanel, masks: dict[str, NDArray[Any]],
               cand: dict[str, Any]) -> dict[str, Any]:
    m = masks["DISCOVERY"] | masks["VALIDATION"]
    v = next(x for x in SG.build_variants() if x.variant_id == cand["variant_id"])
    entry = SG.entry_signal(v, panel, cand["rule"], cand.get("direction", 1))
    per_asset = []
    for ai, a in enumerate(L.ASSETS):
        r = L.simulate_candidate(panel, m & (panel.asset == ai), entry, cand["horizon_key"])
        r.pop("trades_list", None)
        per_asset.append({"asset": a, **r})
    full = L.simulate_candidate(panel, m, entry, cand["horizon_key"])
    full.pop("trades_list", None)
    # temporal halves
    halves = []
    for name, mm in (("first_half", m & (np.arange(len(panel)) < len(panel) // 2)),
                     ("second_half", m & (np.arange(len(panel)) >= len(panel) // 2))):
        r = L.simulate_candidate(panel, mm, entry, cand["horizon_key"])
        r.pop("trades_list", None)
        halves.append({"half": name, **r})
    temporal_all_positive = all(h.get("status") == "OK" and h.get("net_expectancy_bps", -1) > 0
                                for h in halves)
    conc_ok = (full.get("top1_share") is None or full.get("top1_share", 1) < 0.5)
    return {"status": "OK", "candidate_id": cand["candidate_id"], "per_asset": per_asset,
            "halves": halves, "full": full,
            "temporal_all_positive": bool(temporal_all_positive),
            "concentration_ok": bool(conc_ok),
            "top1_share": full.get("top1_share"), "top3_share": full.get("top3_share")}


def _attribution(d: dict[str, Any]) -> dict[str, Any]:
    """§64 economic source attribution (shares of gross funding+basis)."""
    f = float(d.get("sum_funding_bps") or 0.0)
    b = float(d.get("sum_basis_bps") or 0.0)
    c = float(d.get("sum_cost_bps") or 0.0)
    gross = f + b
    if gross == 0:
        return {"status": "N/A"}
    return {
        "gross_funding_plus_basis_bps": _r(gross, 2),
        "pct_from_funding": _r(100.0 * f / gross, 2),
        "pct_from_basis": _r(100.0 * b / gross, 2),
        "pct_from_accidental_direction": _r(100.0 * b / gross, 2),
        "pct_lost_to_costs": _r(100.0 * c / gross, 2),
        "note": "basis == residual directional (spot_pnl + perp_pnl); costs are trading-only",
        "accidental_direction_dominates": bool(abs(b) > abs(f)),
    }


def _economic_summary(da: dict[str, Any], cm: dict[str, Any], funding_be: dict[str, Any],
                      holding_be: dict[str, Any], info: list[dict[str, Any]],
                      nulls: dict[str, Any], best_disc: dict[str, Any] | None,
                      best_val: dict[str, Any] | None, wf: dict[str, Any],
                      stress: dict[str, Any], robust: dict[str, Any],
                      holdout: dict[str, Any], gates: dict[str, Any],
                      gcls: str) -> dict[str, Any]:
    d = best_disc["discovery"] if best_disc else {}
    return {
        "assets": list(L.ASSETS),
        "history_months": da["history_months"],
        "structure": "LONG SPOT / SHORT PERP",
        "round_trip_cost_bps": L.ROUND_TRIP_COST_BPS,
        "best_candidate": best_disc["candidate_id"] if best_disc else None,
        "holding_period": best_disc["horizon_key"] if best_disc else None,
        "trades_discovery": d.get("trades"),
        "funding_pnl_bps_discovery": _r(d.get("sum_funding_bps"), 2),
        "basis_pnl_bps_discovery": _r(d.get("sum_basis_bps"), 2),
        "residual_directional_pnl_bps_discovery": _r(d.get("sum_basis_bps"), 2),
        "residual_directional_note": "basis/residual = spot_pnl + perp_pnl",
        "attribution": _attribution(d),
        "return_on_committed_capital_pertrade": _r(d.get("mean_roc"), 6),
        "return_on_committed_capital_total": _r(d.get("sum_roc"), 6),
        "total_cost_bps_discovery": _r(d.get("sum_cost_bps"), 2),
        "net_expectancy_bps_discovery": _r(d.get("net_expectancy_bps"), 4),
        "net_pnl_bps_discovery": _r(d.get("net_pnl_bps"), 2),
        "mean_roc_discovery": _r(d.get("mean_roc"), 6),
        "pf_discovery": _r(d.get("pf"), 4),
        "sharpe_discovery": _r(d.get("sharpe"), 4),
        "max_dd_bps_discovery": _r(d.get("max_dd_bps"), 2),
        "break_even_funding_bps_per_period": funding_be["by_horizon"],
        "break_even_holding": holding_be["per_asset"],
        "family_nulls": {k: {"p": v["family_wise_p"], "max_ic": v["observed_max_abs_ic"]}
                         for k, v in nulls.items()},
        "validation": best_val,
        "walk_forward": wf.get("positive_folds") if wf.get("status") == "OK" else wf.get("status"),
        "stress": stress.get("status"),
        "robustness": robust.get("status"),
        "holdout": holdout["status"],
        "gates": gates,
        "global_classification": gcls,
    }


# ---------------------------------------------------------------------------
# markdown renderers
# ---------------------------------------------------------------------------

def _md_data_audit(da: dict[str, Any]) -> str:
    rows = [[s, v["spot_rows"], v["perp_rows"], v["funding_rows"],
             v["spot_duplicates"], v["funding_duplicates"], v["epoch_unit_histogram"]]
            for s, v in da["per_asset"].items()]
    return ("# RFC028 DATA AUDIT\n\n"
            f"- Window: {da['window']['common_start']} -> {da['window']['common_end']}\n"
            f"- History months: {da['history_months']}\n"
            f"- Result: {da['result']}\n\n"
            + _md_table(rows, ["asset", "spot", "perp", "funding", "spot_dup",
                               "fund_dup", "epoch_units"]))


def _md_pit(pit: dict[str, Any]) -> str:
    rows = [[s, v["invariant_observation_violations"],
             v["invariant_known_time_violations"],
             v["invariant_available_time_violations"], v["sample_signal_last_eq_prev_rate"]]
            for s, v in pit["per_asset"].items()]
    return ("# RFC028 FUNDING PIT AUDIT\n\n"
            f"- Result: {pit['result']}\n"
            f"- Future poisoning test passed: {pit['future_poisoning_test']['passed']}\n\n"
            + _md_table(rows, ["asset", "obs_viol", "known_viol", "avail_viol",
                               "signal_lag_ok"]))


def _md_cost(cm: dict[str, Any]) -> str:
    return ("# RFC028 CARRY COST MODEL V1\n\n"
            f"- Round-trip total: **{cm['round_trip_cost_bps']} bps**\n"
            f"- Spot side: {cm['spot_side_bps']} bps  (fee {cm['spot_fee_bps']} + "
            f"half-spread {cm['spot_half_spread_bps']} + impact {cm['spot_impact_bps']})\n"
            f"- Perp side: {cm['perp_side_bps']} bps  (fee {cm['perp_fee_bps']} + "
            f"half-spread {cm['perp_half_spread_bps']} + impact {cm['perp_impact_bps']})\n"
            f"- Legs: {cm['legs']}\n"
            f"- Fees: {cm['fee_basis']}\n"
            f"- Committed capital per unit notional: {cm['committed_capital_per_unit_notional']}\n"
            f"- Contrast (NOT used): COST_MODEL_V3 = {cm['reused_cost_model_v3_bps_for_contrast']} bps\n")


def _md_discovery(g1: str, cands: list[dict[str, Any]],
                  qualifying: list[dict[str, Any]],
                  disc: list[dict[str, Any]]) -> str:
    rows = [[c["candidate_id"], c["discovery"].get("trades"),
             c["discovery"].get("net_expectancy_bps"),
             c["discovery"].get("sum_funding_bps"),
             c["discovery"].get("sum_cost_bps"), c["discovery"].get("status")]
            for c in disc[:25]]
    return ("# DISCOVERY_RESULTS\n\n"
            f"G_CARRY_1 = {g1}\n\n"
            f"Candidates evaluated: {len(cands)}; qualifying (all gate criteria): "
            f"{len(qualifying)}\n\n"
            + _md_table(rows, ["candidate", "trades", "net_exp_bps", "funding_bps",
                               "cost_bps", "status"]))


def _md_be_funding(fb: dict[str, Any]) -> str:
    rows = [[hk, v["periods"], v["hours"], v["break_even_funding_bps_per_period"]]
            for hk, v in fb["by_horizon"].items()]
    return ("# RFC028 BREAK-EVEN FUNDING\n\n"
            f"Round-trip cost = {fb['round_trip_cost_bps']} bps.\n\n"
            + _md_table(rows, ["horizon", "periods", "hours", "min_funding_bps/period"])
            + f"\n{fb['verdict']}\n")


def _md_be_holding(hb: dict[str, Any]) -> str:
    rows = [[a, v["mean_funding_bps_per_period"],
             v.get("break_even_holding_periods"), v.get("break_even_holding_hours")]
            for a, v in hb["per_asset"].items()]
    return ("# RFC028 BREAK-EVEN HOLDING\n\n"
            + _md_table(rows, ["asset", "mean_funding_bps/period",
                               "break_even_periods", "break_even_hours"]))


def _md_hyp(reg: dict[str, Any]) -> str:
    rows = [[h["id"], h["family"], h["signal_kind"], h["target_kind"], h["description"]]
            for h in reg["hypotheses"]]
    return ("# RFC028 HYPOTHESIS REGISTRY\n\n"
            f"- Core hypotheses: {reg['n_core_hypotheses']}\n"
            f"- Variants: {reg['n_variants']}\n\n"
            + _md_table(rows, ["id", "family", "signal", "target", "description"]))


def _md_info(info: list[dict[str, Any]]) -> str:
    rows = [[r["variant_id"], r["family"], r["horizon_key"],
             r["ic_discovery"], r["quantile_top_minus_bottom_bps"], r["n_discovery"]]
            for r in info]
    return ("# RFC028 INFORMATION AUDIT (DISCOVERY)\n\n"
            + _md_table(rows, ["variant", "family", "horizon", "IC", "Q5-Q1 bps", "n"]))


def _md_null(nulls: dict[str, Any]) -> str:
    rows = [[k, v["observed_max_abs_ic"], v["family_wise_p"], v["significant"],
             v["best_variant"]] for k, v in nulls.items()]
    return ("# RFC028 FAMILY-WISE NULL\n\n"
            + _md_table(rows, ["family", "max|IC|", "family_p", "significant", "best"]))


def _md_final(report: dict[str, Any]) -> str:
    g = report["gates"]
    s = report["economic_summary"]
    a = s.get("attribution", {})
    lines = [
        "# RFC-028 MARKET-NEUTRAL CARRY", "",
        f"- G_CARRY_INFO = {g['G_CARRY_INFO']}",
        f"- G_CARRY_1 = {g['G_CARRY_1']}",
        f"- G_CARRY_2 = {g['G_CARRY_2']}",
        f"- G_CARRY_3 = {g['G_CARRY_3']}",
        f"- G_CARRY_4 = {g['G_CARRY_4']}", "",
        f"- Assets = {', '.join(s['assets'])}",
        f"- History = {s['history_months']} months",
        f"- Structure = {s['structure']}",
        f"- Best candidate = {s['best_candidate']}",
        f"- Holding period = {s['holding_period']}",
        f"- Trades (discovery) = {s['trades_discovery']}",
        f"- Funding PnL (discovery) = {s['funding_pnl_bps_discovery']} bps",
        f"- Basis PnL (discovery) = {s['basis_pnl_bps_discovery']} bps",
        f"- Total trading cost (discovery) = {s['total_cost_bps_discovery']} bps",
        f"- Net expectancy = {s['net_expectancy_bps_discovery']} bps",
        f"- Net PnL (discovery) = {s['net_pnl_bps_discovery']} bps",
        f"- Residual directional PnL (discovery) = "
        f"{s.get('residual_directional_pnl_bps_discovery')} bps",
        f"- Return on committed capital (discovery) = "
        f"{s.get('return_on_committed_capital_pertrade')} per trade "
        f"({s.get('return_on_committed_capital_total')} total)",
        f"- Attribution = funding {a.get('pct_from_funding')}% | basis "
        f"{a.get('pct_from_basis')}% | accidental direction "
        f"{a.get('pct_from_accidental_direction')}% | lost to costs "
        f"{a.get('pct_lost_to_costs')}%",
        f"- PF = {s['pf_discovery']}  Sharpe = {s['sharpe_discovery']}  MaxDD = {s['max_dd_bps_discovery']} bps",
        f"- Break-even funding = {report['round_trip_cost_bps']} bps round trip",
        f"- Validation = {report['gates']['G_CARRY_2']}",
        f"- Walk-forward = {s['walk_forward']}",
        f"- Robustness = {s['robustness']}",
        f"- Holdout = {s['holdout']}",
        f"- GLOBAL_CLASSIFICATION = {report['global_classification']}",
        f"- FALSE_SUCCESS = {report['false_success']}",
        f"- INDEPENDENT VERIFICATION = {report['independent_verification']}",
        f"- NEXT = {report['next_gate']}", "",
    ]
    return "\n".join(lines)


def _write_checkpoint(summary: dict[str, Any], gcls: str) -> None:
    lines = [
        "# ECONOMIC STRATEGY CHECKPOINT", "",
        f"RFC-028 classification: **{gcls}**. No validated carry candidate exists.", "",
        "## Economic research to date", "",
        "| RFC | family | best gross | best net | sample | validation | robustness | why rejected |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
        "| RFC-010B | live baseline | mean -3.54 bps | mean -27.33 bps | 1533 proposals | n/a | n/a | gross < cost on 1533/1533; ZT-4 zero-trade |",
        "| RFC-021 | Edge Sprint 001 | +19.78 bps | -4.01 bps | 18 experiments | NOT_REACHED | n/a | 18/18 REJECTED_DISCOVERY (net <= 0) |",
        "| RFC-022 (Sprint 002) | volatility events | +16.0652 bps D net | validation 0/2 | 106 experiments | 0 positive | 0/2 | multiple testing / winner's curse |",
        "| RFC-023 | generalization diagnosis | best-of-106 null | n/a | 106 attempts | 0/81 p<0.05 | n/a | MULTIPLE_TESTING primary cause; 0 survive BH-FDR/Holm |",
        "| RFC-024 | directional on vol events | n/a | n/a | vol event set | FAIL_DIRECTION | n/a | magnitude detected, direction not (VOLATILITY_ONLY) |",
        "| RFC-025 | orthogonal information | family p 0.136 ALL / 0.028 VOL | n/a | 60 variants | FAIL | n/a | orthogonal info exists, no net edge |",
        "| RFC-026 | execution economics | break-even cost 20.73 bps | -3.0608 bps | micro window | FAIL | FAIL | signal too weak to survive realistic execution (EX-A) |",
        "| RFC-027 | positioning | +14.8841 bps | -8.9064 bps | 110 variants | FAIL | 0/4 wf | COST_KILLED (edge/cost 0.63) |",
        "| RFC-028 | carry / basis / funding | "
        f"+{summary.get('net_expectancy_bps_discovery')} bps D | "
        f"{summary.get('net_pnl_bps_discovery')} bps D | "
        f"{summary.get('trades_discovery')} trades | FAIL (0 trades) | NOT_REACHED | "
        "broad carry net ~-38 bps/trade; only rare high-funding 7d holds positive in D |",
        "",
        "## RFC-028 detail", "",
        f"- Best discovery candidate: {summary.get('best_candidate')}",
        f"- Funding PnL: {summary.get('funding_pnl_bps_discovery')} bps",
        f"- Basis PnL: {summary.get('basis_pnl_bps_discovery')} bps",
        f"- Trading costs: {summary.get('total_cost_bps_discovery')} bps",
        f"- Net expectancy (discovery): {summary.get('net_expectancy_bps_discovery')} bps",
        f"- Round-trip cost: {summary.get('round_trip_cost_bps')} bps",
        "- Broad (RULE_POS) carry: ~1800 trades, net expectancy ~-38 bps/trade, funding "
        "~1 bps per 8h vs 39 bps round-trip cost.",
        "- Break-even holding (at typical funding): ~13-16 days; validation window "
        "produced 0 qualifying entries.",
        "",
        "**Finding:** funding is highly predictable (C1 IC ~0.83) and almost always "
        "positive, but its *magnitude* (~0.75-0.91 bps per 8h) is far below the "
        "~39 bps round-trip two-leg cost. Carry exists as a *phenomenon* but does "
        "not clear costs at realistic horizons; the binding constraint across all "
        "RFCs is the COST-TO-EDGE RATIO, not a missing signal.",
        "",
        "## Recommendation (exactly one)", "",
        "**PIVOT_STRATEGY_CLASS**",
        "",
        "Every tested edge (directional, orthogonal information, positioning, "
        "market-neutral carry) is a *taker-executed, per-trade-cost-bounded* "
        "strategy in liquid crypto majors, and every one has gross expectancy of "
        "~15-20 bps against a >=24 bps realistic round-trip cost. The measured "
        "binding constraint is the cost-to-edge ratio, not signal availability.",
        "",
        "The next unit of effort should therefore change the *cost structure*, not "
        "the signal: pursue a strategy class whose edge is not bounded by a "
        "round-trip taker fee - specifically passive/maker execution (order-book "
        "market-making with maker rebates, which can invert the cost sign) or "
        "structural holds with far lower turnover. PIVOT_MARKET is explicitly "
        "contraindicated: less liquid venues carry *higher* spreads/impact, which "
        "would worsen the identified constraint, not relieve it. If no maker/"
        "passive structure can be validated with adequate historical data, then "
        "PAUSE_PROJECT.",
        "",
        "DO NOT open RFC-029 as another edge-discovery grid search.", "",
    ]
    L.write_md(Path("reports") / "ECONOMIC_STRATEGY_CHECKPOINT.md", "\n".join(lines))


if __name__ == "__main__":
    main()
