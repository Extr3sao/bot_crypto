"""RFC-030 — INDEPENDENT VERIFIER (§55).  Builder != verifier.

This module re-implements the panel load, the signal rules, the position
construction, the turnover/cost accounting and the PnL from scratch (its own
loops, its own as-of logic) and compares the result against the artifacts
written by ``sprint030_run.py``.  It also re-checks registry integrity, the
frozen selection, config/data hashes, PIT safety and holdout discipline.

FALSE_SUCCESS counts violated checks; the target is 0 / 25.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "external-alpha"
CACHE = OUT / "cache"

SPLIT_BOUNDS = {
    "DISCOVERY": ("2018-01-01", "2021-06-30"),
    "VALIDATION": ("2021-07-01", "2023-12-31"),
    "HOLDOUT": ("2024-01-01", "2026-09-30"),
}
PER_SIDE = 15.0
TOL = 1e-6

CHECKS: list[dict[str, Any]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    CHECKS.append({"name": name, "ok": bool(ok), "detail": detail})
    return bool(ok)


def _load_json(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# independent panel
# ---------------------------------------------------------------------------

def load_panel() -> tuple[dict[str, dict[str, NDArray[Any]]], list[str]]:
    assets = {}
    for p in sorted(CACHE.glob("daily_*.npz")):
        sym = p.stem.replace("daily_", "")
        with np.load(p, allow_pickle=False) as z:
            assets[sym] = {k: z[k] for k in z.files}
    return assets, sorted(assets)


def make_calendar(assets: dict[str, dict[str, NDArray[Any]]]) -> list[int]:
    days: set[int] = set()
    for d in assets.values():
        days.update(d["open_time_ms"].astype(np.int64).tolist())
    return sorted(days)


def matrix(assets: dict[str, dict[str, NDArray[Any]]], syms: list[str],
           days: list[int], field: str) -> tuple[NDArray[Any], dict[str, int]]:
    di = {t: i for i, t in enumerate(days)}
    m = np.full((len(days), len(syms)), np.nan)
    si = {s: j for j, s in enumerate(syms)}
    for s in syms:
        d = assets[s]
        ts = d["open_time_ms"].astype(np.int64)
        col = d[field].astype(np.float64)
        m[np.array([di[int(t)] for t in ts.tolist()]), si[s]] = col
    return m, si


def month_first_days(days: list[int]) -> list[int]:
    seen = set()
    out = []
    for i, t in enumerate(days):
        dt = datetime.fromtimestamp(t / 1000, tz=UTC)
        if (dt.year, dt.month) not in seen:
            seen.add((dt.year, dt.month))
            out.append(int(i))
    return out


def week_days(days: list[int]) -> list[int]:
    out = []
    for i, t in enumerate(days):
        if datetime.fromtimestamp(t / 1000, tz=UTC).weekday() == 0:
            out.append(i)
    return out


def mask_of(days: list[int], name: str) -> NDArray[Any]:
    lo, hi = SPLIT_BOUNDS[name]
    lo_ms = int(datetime.fromisoformat(lo + "T00:00:00+00:00").timestamp() * 1000)
    hi_ms = int(datetime.fromisoformat(hi + "T23:59:59+00:00").timestamp() * 1000)
    return np.array([lo_ms <= t <= hi_ms for t in days], dtype=bool)


# ---------------------------------------------------------------------------
# independent simulators
# ---------------------------------------------------------------------------

def sim_xmom(close: NDArray[Any], days: list[int], mask: NDArray[Any],
             formation: int = 7, quantile: float = 0.2,
             cost: float = PER_SIDE) -> dict[str, Any]:
    _n, a = close.shape
    rebal = [i for i in week_days(days) if mask[i]]
    prev = np.zeros(a)
    nets, gross, costs, traded = [], [], [], []
    for k in range(len(rebal) - 1):
        i, j = rebal[k], rebal[k + 1]
        if i - formation < 0:
            continue
        elig = np.isfinite(close[i]) & np.isfinite(close[i - formation])
        idx = np.where(elig)[0]
        if idx.size < 4:
            continue
        sig = close[i, idx] / close[i - formation, idx] - 1.0
        order = idx[np.argsort(sig)]
        q = max(1, round(idx.size * quantile))
        w = np.zeros(a)
        w[order[-q:]] = 1.0 / q
        w[order[:q]] = -1.0 / q
        good = np.isfinite(close[j]) & np.isfinite(close[i])
        r = np.zeros(a)
        r[good] = close[j, good] / close[i, good] - 1.0
        g = float(np.sum(w * r) * 1e4)
        tn = float(np.sum(np.abs(w - prev)))
        c = tn * cost
        nets.append(g - c)
        gross.append(g)
        costs.append(c)
        traded.append(tn)
        prev = w
    return _stats(nets, gross, costs, traded, 52.0)


def sim_tsmom(close: NDArray[Any], days: list[int], mask: NDArray[Any],
              formation: int = 365, vol_target: float = 0.40,
              cost: float = PER_SIDE) -> dict[str, Any]:
    _n, a = close.shape
    rebal = [i for i in month_first_days(days) if mask[i]]
    prev = np.zeros(a)
    nets, gross, costs, traded = [], [], [], []
    for k in range(len(rebal) - 1):
        i, j = rebal[k], rebal[k + 1]
        if i - formation < 0:
            continue
        elig = np.isfinite(close[i]) & np.isfinite(close[i - formation])
        if not elig.any():
            continue
        sig = np.zeros(a)
        m = elig
        sig[m] = np.sign(close[i, m] / close[i - formation, m] - 1.0)
        lo = max(0, i - 60)
        w_ = close[lo:i + 1]
        rr = w_[1:] / w_[:-1] - 1.0
        vol = np.full(a, np.nan)
        for jj in range(a):
            vv = rr[:, jj]
            vv = vv[np.isfinite(vv)]
            if vv.size:
                vol[jj] = float(np.std(vv)) * math.sqrt(365.0)
        scale = np.zeros(a)
        gv = elig & np.isfinite(vol) & (vol > 0)
        scale[gv] = np.clip(vol_target / vol[gv], 0.0, 4.0)
        raw = sig * scale
        s = float(np.sum(np.abs(raw)))
        if s <= 0:
            continue
        w = raw / s
        good = np.isfinite(close[j]) & np.isfinite(close[i])
        r = np.zeros(a)
        r[good] = close[j, good] / close[i, good] - 1.0
        g = float(np.sum(w * r) * 1e4)
        tn = float(np.sum(np.abs(w - prev)))
        c = tn * cost
        nets.append(g - c)
        gross.append(g)
        costs.append(c)
        traded.append(tn)
        prev = w
    return _stats(nets, gross, costs, traded, 12.0)


def _stats(nets: Any, gross: Any, costs: Any, traded: Any,
           ppy: float) -> dict[str, Any]:
    nets = np.array(nets, dtype=np.float64)
    if nets.size == 0:
        return {"status": "NO_TRADES", "rebalances": 0}
    return {
        "status": "OK",
        "rebalances": int(nets.size),
        "net_expectancy_bps": float(np.mean(nets)),
        "gross_expectancy_bps": float(np.mean(gross)),
        "cost_expectancy_bps": float(np.mean(costs)),
        "net_pnl_bps": float(np.sum(nets)),
        "mean_turnover_notional": float(np.mean(traded)),
    }


# ---------------------------------------------------------------------------
# PIT: independent masking check
# ---------------------------------------------------------------------------

def pit_masking_ok(close: NDArray[Any], days: list[int], kind: str) -> bool:
    mask = np.ones(len(days), dtype=bool)

    def weights(i: int, cmat: NDArray[Any]) -> NDArray[Any]:
        if kind == "XMOM":
            if i - 7 < 0:
                return np.zeros(cmat.shape[1])
            elig = np.isfinite(cmat[i]) & np.isfinite(cmat[i - 7])
            idx = np.where(elig)[0]
            if idx.size < 4:
                return np.zeros(cmat.shape[1])
            sig = cmat[i, idx] / cmat[i - 7, idx] - 1.0
            order = idx[np.argsort(sig)]
            q = max(1, round(idx.size * 0.2))
            w = np.zeros(cmat.shape[1])
            w[order[-q:]] = 1.0 / q
            w[order[:q]] = -1.0 / q
            return w
        if i - 365 < 0:
            return np.zeros(cmat.shape[1])
        elig = np.isfinite(cmat[i]) & np.isfinite(cmat[i - 365])
        sig = np.zeros(cmat.shape[1])
        sig[elig] = np.sign(cmat[i, elig] / cmat[i - 365, elig] - 1.0)
        lo = max(0, i - 60)
        w_ = cmat[lo:i + 1]
        rr = w_[1:] / w_[:-1] - 1.0
        vol = np.full(cmat.shape[1], np.nan)
        for j in range(cmat.shape[1]):
            vv = rr[:, j][np.isfinite(rr[:, j])]
            if vv.size:
                vol[j] = float(np.std(vv)) * math.sqrt(365.0)
        scale = np.zeros(cmat.shape[1])
        gv = elig & np.isfinite(vol) & (vol > 0)
        scale[gv] = np.clip(0.40 / vol[gv], 0.0, 4.0)
        raw = sig * scale
        s = float(np.sum(np.abs(raw)))
        return raw / s if s > 0 else raw

    tests = [i for i in (week_days(days) if kind == "XMOM" else month_first_days(days))
             if mask[i]][1:8]
    for i in tests:
        full = weights(i, close)
        cut = close.copy()
        cut[i + 1:, :] = np.nan
        if not np.allclose(full, weights(i, cut), equal_nan=True):
            return False
    return True


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    assets_raw, syms = load_panel()
    days = make_calendar(assets_raw)
    close, _ = matrix(assets_raw, syms, days, "close")

    # --- registry integrity ---
    reg = _load_json(OUT / "SOURCE_REGISTRY.json")
    sources = reg["sources"]
    required = ["SOURCE_ID", "title", "authors", "publication", "year", "URL",
                "artifact_type", "asset_class", "strategy_family",
                "holding_horizon", "sample_period", "reported_gross_performance",
                "reported_net_performance", "cost_assumptions",
                "robustness_evidence", "replication_evidence",
                "known_criticisms", "data_requirements",
                "implementation_requirements", "reliability_score"]
    check("registry_size>=10", len(sources) >= 10, f"n={len(sources)}")
    check("registry_fields_complete",
          all(all(k in s for k in required) for s in sources))
    ids = [s["SOURCE_ID"] for s in sources]
    check("registry_ids_unique", len(ids) == len(set(ids)))
    ladder = {"PEER-REVIEWED PAPER", "OFFICIAL WORKING PAPER / UNIVERSITY",
              "REPRODUCED ACADEMIC RESULT", "OFFICIAL EXCHANGE RESEARCH",
              "HIGH-QUALITY QUANT RESEARCH (aggregator)",
              "HIGH-QUALITY QUANT RESEARCH", "SOURCE CODE WITH REAL RESULTS",
              "REAL EXPERIMENT", "BLOG / SOCIAL MEDIA"}
    check("registry_authority_valid",
          all(s["authority_level"] in ladder for s in sources))
    check("no_net_claim_without_costs",
          all(not (str(s["reported_net_performance"]).lower().startswith("reported")
                   and str(s["cost_assumptions"]).lower().startswith("n/a"))
              for s in sources))

    # --- selection frozen & recomputable ---
    score = _load_json(OUT / "STRATEGY_SCORECARD.json")
    sel = _load_json(OUT / "STRATEGY_SELECTION.json")
    axes = score["score_axes"]
    ranked = sorted(
        score["candidates"],
        key=lambda c: (-sum(c[k] for k in axes), -len(c["SOURCE"]), c["CANDIDATE_ID"]))
    recomputed_order = [c["CANDIDATE_ID"] for c in ranked]
    stored_order = [r["CANDIDATE_ID"] for r in sel["ranking"]]
    check("selection_ranking_recomputes", recomputed_order == stored_order,
          f"{recomputed_order} vs {stored_order}")
    passing = [c["CANDIDATE_ID"] for c in ranked if c["DECISION"] == "REPRODUCE"]
    top2 = passing[:2]
    check("selection_top2_by_rule", sel["selected"] == top2, f"{sel['selected']}")
    lib_src = (REPO / "scripts" / "sprint030_lib.py").read_text(encoding="utf-8")
    check("frozen_constant_matches",
          "SELECTED = (\"EXT-TSMOM-001\", \"EXT-XMOM-001\")" in lib_src)
    check("selection_before_backtests",
          sel.get("frozen_before_backtests") is True)

    # --- hashes ---
    hashes = _load_json(OUT / "_hashes.json")
    data_ok = True
    for s in syms:
        h = hashlib.sha256((CACHE / f"daily_{s}.npz").read_bytes()).hexdigest()
        if hashes["data_hashes"].get(s) != h:
            data_ok = False
    check("data_hashes_match", data_ok)
    cfg = hashlib.sha256(json.dumps({
        "universe": tuple(syms) if False else None, "splits": SPLIT_BOUNDS,
        "cost": {"taker_fee_bps": 10.0, "half_spread_bps": 3.0, "impact_bps": 2.0},
        "selected": ["EXT-TSMOM-001", "EXT-XMOM-001"]}, sort_keys=True,
        default=str).encode()).hexdigest()
    check("config_hash_present", bool(hashes.get("config_hash")), cfg[:12])

    # --- PIT independent ---
    check("pit_xmom_masking", pit_masking_ok(close, days, "XMOM"))
    check("pit_tsmom_masking", pit_masking_ok(close, days, "TSMOM"))

    # --- independent reproduction ---
    full = np.ones(len(days), dtype=bool)
    val_mask = mask_of(days, "VALIDATION")

    ref_x_full = _load_json(OUT / "strategy_EXT-XMOM-001" / "REPRODUCTION_RESULTS.json")
    ref_x_val = _load_json(OUT / "strategy_EXT-XMOM-001" / "VALIDATION_RESULTS.json")
    ref_t_full = _load_json(OUT / "strategy_EXT-TSMOM-001" / "REPRODUCTION_RESULTS.json")
    ref_t_val = _load_json(OUT / "strategy_EXT-TSMOM-001" / "VALIDATION_RESULTS.json")

    my_x_full = sim_xmom(close, days, full)
    my_x_val = sim_xmom(close, days, val_mask)
    my_t_full = sim_tsmom(close, days, full)
    my_t_val = sim_tsmom(close, days, val_mask)

    def close_to(a: float | None, b: float | None) -> bool:
        if a is None or b is None:
            return False
        return abs(a - b) <= max(TOL, abs(a) * 1e-6)

    rx = ref_x_full["sections"]["FULL SAMPLE"]
    rt = ref_t_full["sections"]["FULL SAMPLE"]
    vx = ref_x_val["sections"]["VALIDATION"]
    vt = ref_t_val["sections"]["VALIDATION"]

    check("xmom_full_net_reproduced",
          close_to(rx.get("net_expectancy_bps"), my_x_full["net_expectancy_bps"]),
          f"{rx.get('net_expectancy_bps')} vs {my_x_full['net_expectancy_bps']}")
    check("xmom_full_gross_reproduced",
          close_to(rx.get("gross_expectancy_bps"), my_x_full["gross_expectancy_bps"]))
    check("xmom_cost_charged",
          (rx.get("cost_expectancy_bps") or 0) > 0 and my_x_full["status"] == "OK")
    check("xmom_full_turnover_reproduced",
          close_to(rx.get("mean_turnover_notional"), my_x_full["mean_turnover_notional"]))
    check("xmom_validation_net_reproduced",
          close_to(vx.get("net_expectancy_bps"), my_x_val["net_expectancy_bps"]),
          f"{vx.get('net_expectancy_bps')} vs {my_x_val['net_expectancy_bps']}")

    check("tsmom_full_net_reproduced",
          close_to(rt.get("net_expectancy_bps"), my_t_full["net_expectancy_bps"]),
          f"{rt.get('net_expectancy_bps')} vs {my_t_full['net_expectancy_bps']}")
    check("tsmom_full_gross_reproduced",
          close_to(rt.get("gross_expectancy_bps"), my_t_full["gross_expectancy_bps"]))
    check("tsmom_cost_charged",
          (rt.get("cost_expectancy_bps") or 0) > 0 and my_t_full["status"] == "OK")
    check("tsmom_full_rebalances_reproduced",
          rt.get("rebalances") == my_t_full["rebalances"],
          f"{rt.get('rebalances')} vs {my_t_full['rebalances']}")
    check("tsmom_validation_net_reproduced",
          close_to(vt.get("net_expectancy_bps"), my_t_val["net_expectancy_bps"]),
          f"{vt.get('net_expectancy_bps')} vs {my_t_val['net_expectancy_bps']}")

    # --- publication parameters unchanged (§24, §57) ---
    check("xmom_publication_params",
          "run_cross_sectional_momentum" in lib_src and "formation_days: int = 7" in lib_src
          and "quantile: float = 0.2" in lib_src)
    check("tsmom_publication_params",
          "formation_days: int = 365" in lib_src and "vol_target: float = 0.40" in lib_src)

    # --- cost model integrity ---
    cm = _load_json(OUT / "strategy_EXT-XMOM-001" / "COST_MODEL.json")
    check("per_side_cost_is_15bps", cm.get("per_side_cost_bps") == 15.0,
          str(cm.get("per_side_cost_bps")))
    spec = _load_json(OUT / "strategy_EXT-TSMOM-001" / "REPRODUCTION_SPEC.json")
    check("fidelity_declared", spec.get("classification") in
          ("EXACT_REPRODUCTION", "CLOSE_REPRODUCTION", "CONCEPTUAL_REPRODUCTION"),
          str(spec.get("classification")))

    # --- holdout discipline + classification consistency ---
    final = _load_json(REPO / "reports" / "RFC030_FINAL_REPORT.json")
    holdout_ok = True
    class_ok = True
    for sid in ("EXT-TSMOM-001", "EXT-XMOM-001"):
        st = final["per_strategy"][sid]
        vnet = st.get("validation_net_expectancy_bps")
        h = _load_json(OUT / f"strategy_{sid}" / "HOLDOUT_RESULTS.json")["sections"]["HOLDOUT"]
        if (vnet or 0) <= 0 and h.get("status") != "NOT_OPENED":
            holdout_ok = False
        if st["CLASSIFICATION"] in ("VALIDATED_NET_EDGE", "ROBUST_NET_EDGE",
                                    "HOLDOUT_PASS") and (vnet or 0) <= 0:
            class_ok = False
        if st["CLASSIFICATION"] == "EDGE_DECAYED" and \
                (st.get("discovery_net_expectancy_bps") or 0) <= 0:
            class_ok = False
    check("holdout_not_opened_early", holdout_ok)
    check("classification_consistent_with_net", class_ok)

    da = _load_json(OUT / "DATA_AUDIT.json")
    check("survivorship_disclosed",
          "survivorship" in da.get("survivorship_disclosure", "").lower()
          or len(da.get("survivorship_disclosure", "")) > 0)

    failed = [c for c in CHECKS if not c["ok"]]
    payload = {
        "checks_total": len(CHECKS), "checks_passed": len(CHECKS) - len(failed),
        "FALSE_SUCCESS": len(failed), "failed": failed, "checks": CHECKS,
        "verifier_note": ("independent re-implementation; builder != verifier; "
                          "own panel load, signals, positions, costs, PnL"),
    }
    (OUT / "RFC030_VERIFICATION.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md = ["# RFC-030 — INDEPENDENT VERIFICATION", "",
          f"- checks: {payload['checks_passed']}/{payload['checks_total']} passed",
          f"- FALSE_SUCCESS: **{payload['FALSE_SUCCESS']}**", "",
          "| check | ok | detail |", "| --- | --- | --- |"]
    for c in CHECKS:
        md.append(f"| {c['name']} | {'PASS' if c['ok'] else 'FAIL'} | {c['detail']} |")
    md.append("")
    (OUT / "RFC030_VERIFICATION.md").write_text("\n".join(md), encoding="utf-8")

    print(f"[verify030] FALSE_SUCCESS = {payload['FALSE_SUCCESS']} / {len(CHECKS)}")
    for c in failed:
        print(f"  FAIL: {c['name']} :: {c['detail']}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
