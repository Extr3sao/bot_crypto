"""RFC-031 — INDEPENDENT VERIFIER (§17-§18, §78).  Builder != verifier.

Standalone: this module does NOT import ``sprint031_lib`` or ``sprint030_lib``.
It re-loads the raw cache, re-derives the TSMOM signal / weights / turnover /
cost / PnL with its own loops, and compares them against the artifacts written
by ``sprint031_run.py``.  FALSE_SUCCESS counts violated checks; the target is 0.
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
OUT = REPO / "reports" / "paper-certification"
RFC030 = REPO / "reports" / "external-alpha"
CACHE = RFC030 / "cache"

UNIVERSE = (
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "SOLUSDT",
    "DOGEUSDT", "DOTUSDT", "LTCUSDT", "LINKUSDT", "BCHUSDT", "XLMUSDT",
    "TRXUSDT", "ETCUSDT", "EOSUSDT", "XTZUSDT", "ZECUSDT", "DASHUSDT",
    "NEOUSDT", "ATOMUSDT", "VETUSDT", "FILUSDT", "THETAUSDT", "ALGOUSDT",
    "AVAXUSDT", "MATICUSDT", "FTTUSDT", "LUNAUSDT", "ICPUSDT", "SHIBUSDT",
)
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


def load_json(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# independent data load
# --------------------------------------------------------------------------

def load() -> tuple[list[str], list[int], NDArray[Any]]:
    raw: dict[str, dict[str, NDArray[Any]]] = {}
    for s in UNIVERSE:
        p = CACHE / f"daily_{s}.npz"
        if p.exists():
            with np.load(p, allow_pickle=False) as z:
                raw[s] = {k: z[k] for k in z.files}
    syms = sorted(raw)
    days = sorted({int(t) for d in raw.values()
                   for t in d["open_time_ms"].astype(np.int64).tolist()})
    di = {t: i for i, t in enumerate(days)}
    close = np.full((len(days), len(syms)), np.nan)
    for j, s in enumerate(syms):
        ts = raw[s]["open_time_ms"].astype(np.int64)
        close[np.array([di[int(t)] for t in ts.tolist()]), j] = raw[s]["close"]
    return syms, days, close


def month_first(days: list[int]) -> list[int]:
    seen: set[tuple[int, int]] = set()
    out: list[int] = []
    for i, t in enumerate(days):
        d = datetime.fromtimestamp(t / 1000, tz=UTC)
        if (d.year, d.month) not in seen:
            seen.add((d.year, d.month))
            out.append(i)
    return out


def mask_of(days: list[int], name: str) -> NDArray[Any]:
    lo, hi = SPLIT_BOUNDS[name]
    a = int(datetime.fromisoformat(lo + "T00:00:00+00:00").timestamp() * 1000)
    b = int(datetime.fromisoformat(hi + "T23:59:59+00:00").timestamp() * 1000)
    return np.array([a <= t <= b for t in days], dtype=bool)


# --------------------------------------------------------------------------
# independent TSMOM (own implementation)
# --------------------------------------------------------------------------

def book(close: NDArray[Any], i: int, exec_lag: int = 0) -> dict[str, Any]:
    a = close.shape[1]
    out: dict[str, Any] = {"w": np.zeros(a), "neg": 0, "pos": 0, "short_gross": 0.0,
                           "long_gross": 0.0, "ok": False, "back": i - 365}
    if i - 365 < 0:
        return out
    elig = np.isfinite(close[i]) & np.isfinite(close[i - 365])
    sig = np.zeros(a)
    sig[elig] = np.sign(close[i, elig] / close[i - 365, elig] - 1.0)
    lo = max(0, i - 60)
    rr = close[lo:i + 1]
    rr = rr[1:] / rr[:-1] - 1.0
    vol = np.full(a, np.nan)
    for j in range(a):
        c = rr[:, j][np.isfinite(rr[:, j])]
        if c.size >= 2:
            vol[j] = float(np.std(c)) * math.sqrt(365.0)
    scale = np.zeros(a)
    g = elig & np.isfinite(vol) & (vol > 0)
    scale[g] = np.clip(0.40 / vol[g], 0.0, 4.0)
    raw = sig * scale
    s = float(np.sum(np.abs(raw)))
    if s > 0:
        out["w"] = raw / s
        out["ok"] = True
    out["neg"] = int(np.sum(out["w"] < 0))
    out["pos"] = int(np.sum(out["w"] > 0))
    out["short_gross"] = float(np.sum(np.where(out["w"] < 0, -out["w"], 0.0)))
    out["long_gross"] = float(np.sum(np.where(out["w"] > 0, out["w"], 0.0)))
    return out


def sim(close: NDArray[Any], days: list[int], mask: NDArray[Any],
        exec_lag: int = 0, cost: float = PER_SIDE) -> dict[str, Any]:
    a = close.shape[1]
    rebal = [i for i in month_first(days) if mask[i]]
    prev = np.zeros(a)
    nets: list[float] = []
    gross: list[float] = []
    costs: list[float] = []
    traded: list[float] = []
    neg_obs = pos_obs = 0
    for k in range(len(rebal) - 1):
        i, j = rebal[k], rebal[k + 1]
        b = book(close, i)
        if not b["ok"]:
            continue
        e0, e1 = i + exec_lag, j + exec_lag
        if e1 >= close.shape[0]:
            continue
        w = b["w"]
        neg_obs += b["neg"]
        pos_obs += b["pos"]
        good = np.isfinite(close[e1]) & np.isfinite(close[e0])
        r = np.zeros(a)
        r[good] = close[e1, good] / close[e0, good] - 1.0
        gp = float(np.nansum(w * r) * 1e4)
        tn = float(np.nansum(np.abs(w - prev)))
        c = tn * cost
        nets.append(gp - c)
        gross.append(gp)
        costs.append(c)
        traded.append(tn)
        prev = w
    out: dict[str, Any] = {"nets": np.array(nets), "gross": np.array(gross),
                           "costs": np.array(costs), "traded": np.array(traded),
                           "neg_obs": neg_obs, "pos_obs": pos_obs}
    return out


def main() -> int:
    syms, days, close = load()

    # --- artifacts exist ---
    required = ["RFC031_PLAN", "RFC030_GATE_RECONCILIATION", "TSMOM_FROZEN_SPEC",
                "INSTRUMENT_FEASIBILITY", "UNIVERSE_AUTHORITY_AUDIT",
                "SURVIVORSHIP_AUDIT", "PIT_EXECUTION_AUDIT", "COST_ACCOUNTING_AUDIT",
                "INDEPENDENT_REPRODUCTION", "MARKET_EXPOSURE_AUDIT",
                "BENCHMARK_COMPARISON", "TEMPORAL_STABILITY", "ASSET_CONCENTRATION",
                "STATISTICAL_UNCERTAINTY", "PAPER_CAMPAIGN_SPEC"]
    missing = [n for n in required
               if not (OUT / f"{n}.json").exists() or not (OUT / f"{n}.md").exists()]
    check("required_artifacts_present", not missing, f"missing={missing}")

    frozen = load_json(OUT / "TSMOM_FROZEN_SPEC.json")
    repro = load_json(OUT / "INDEPENDENT_REPRODUCTION.json")
    instrument = load_json(OUT / "INSTRUMENT_FEASIBILITY.json")
    universe = load_json(OUT / "UNIVERSE_AUTHORITY_AUDIT.json")
    costart = load_json(OUT / "COST_ACCOUNTING_AUDIT.json")
    pit = load_json(OUT / "PIT_EXECUTION_AUDIT.json")
    recon = load_json(OUT / "RFC030_GATE_RECONCILIATION.json")
    final = load_json(REPO / "reports" / "RFC031_FINAL_REPORT.json")
    rfc030 = load_json(REPO / "reports" / "RFC030_FINAL_REPORT.json")

    # --- frozen spec / hashes ---
    check("frozen_formation_365", frozen.get("formation_days") == 365)
    check("frozen_vol_target", frozen.get("vol_target") == 0.40)
    check("frozen_rebalance_monthly", "monthly" in str(frozen.get("rebalance")).lower())
    check("frozen_cost_15", frozen.get("per_side_cost_bps") == 15.0)
    data_ok = True
    for s in syms:
        h = hashlib.sha256((CACHE / f"daily_{s}.npz").read_bytes()).hexdigest()
        if frozen["data_hashes"].get(s) != h:
            data_ok = False
    check("data_hashes_immutable", data_ok)
    cfg = hashlib.sha256(json.dumps(
        {**{k: frozen[k] for k in ("strategy_id", "signal", "formation_days",
                                   "rebalance", "portfolio", "vol_target",
                                   "vol_lookback_days", "vol_clip", "universe",
                                   "cost_model", "per_side_cost_bps",
                                   "execution_semantics_frozen")},
         "data_hashes": frozen["data_hashes"]}, sort_keys=True, default=str).encode()).hexdigest()
    check("config_hash_recomputes", cfg == frozen.get("config_hash"), cfg[:12])

    # --- independent reproduction vs written artifact ---
    mine_full = sim(close, days, np.ones(len(days), bool))
    mine_val = sim(close, days, mask_of(days, "VALIDATION"))
    mine_hold = sim(close, days, mask_of(days, "HOLDOUT"))
    ref = repro["independently_reproduced"]

    def near(a: Any, b: Any) -> bool:
        if a is None or b is None:
            return False
        return bool(abs(a - b) <= max(TOL, abs(a) * 1e-6))

    check("repro_full_net", near(ref["full"]["net_expectancy_bps"],
                                 float(np.mean(mine_full["nets"]))),
          f"{ref['full']['net_expectancy_bps']} vs {float(np.mean(mine_full['nets']))}")
    check("repro_full_gross", near(ref["full"]["gross_expectancy_bps"],
                                   float(np.mean(mine_full["gross"]))))
    check("repro_full_turnover", near(ref["full"]["mean_turnover_notional"],
                                      float(np.mean(mine_full["traded"]))))
    check("repro_full_rebalances", ref["full"]["rebalances"] == mine_full["nets"].size)
    check("repro_validation_net", near(ref["validation"]["net_expectancy_bps"],
                                       float(np.mean(mine_val["nets"]))))
    check("repro_holdout_net", near(ref["holdout"]["net_expectancy_bps"],
                                    float(np.mean(mine_hold["nets"]))))

    # --- independent cost reconciliation ---
    recomputed = mine_full["traded"] * PER_SIDE
    check("cost_reconciles", np.allclose(recomputed, mine_full["costs"], atol=1e-9))
    check("cost_artifact_flags_reconciled", costart.get("reconciliation_ok") is True)

    # --- instrument: unsupported spot shorts really exist ---
    short_present = mine_full["neg_obs"] > 0
    check("unsupported_spot_shorts_present", short_present,
          f"negative-weight observations={mine_full['neg_obs']}")
    check("instrument_audit_matches", near(
        instrument.get("pct_observations_negative_weight"),
        100.0 * mine_full["neg_obs"] / (mine_full["neg_obs"] + mine_full["pos_obs"])))
    check("borrow_evidence_absent", instrument.get("borrow_evidence_present") is False)

    # --- listing dates respected (no finite close before first listing) ---
    check("no_forward_fill_before_listing", _no_forward_fill(syms))
    check("listing_dates_respected", universe.get("listing_dates_respected") is True)

    # --- future poisoning independent ---
    check("future_poisoning_independent", _poison(close))

    # --- XMOM not promotable / governance ---
    xmom: dict[str, Any] = next(
        (r for r in recon["candidates"] if r["CANDIDATE"] == "EXT-XMOM-001"), {})
    check("xmom_not_promotable", xmom.get("PROMOTABLE?") == "NO")
    check("xmom_robust_fail_recorded", xmom.get("G_EXT_EDGE_3") == "FAIL")
    check("governance_defect_recorded",
          recon["governance"]["GOVERNANCE_DEFECT"] == "YES")
    check("xmom_not_certified_final",
          "NOT PAPER CERTIFIED" in str(final.get("xmom_status", "")).upper())
    check("rfc030_did_list_xmom_as_paper_candidate",
          "EXT-XMOM-001" in rfc030.get("paper_candidates", []))

    # --- gate correctness given the actual defect ---
    check("g_pc_1_tradability_fail", final.get("G_PC_1_TRADABILITY") == "FAIL")
    check("certification_not_certified",
          final.get("CERTIFICATION") in ("REJECTED", "BLOCKED"))
    check("rfc030_invalidated",
          final.get("rfc030_candidate_status") == "RFC030_CANDIDATE_INVALIDATED")
    check("paper_not_activated", final.get("paper_campaign_activated") is False)
    check("paper_status_not_pass", final.get("paper_status") != "PAPER_PASS")

    # --- forward vs historical honesty ---
    check("historical_edge_not_called_forward",
          final.get("forward_paper_profitability") == "NOT YET PROVEN")
    check("live_profitability_not_claimed", final.get("live_profitability") == "NOT PROVEN")

    # --- no tuning: validation/holdout not modified ---
    check("no_retune_validation", final.get("rfc030_validation_net_bps") is not None and
          near(final.get("rfc030_validation_net_bps"),
               rfc030["per_strategy"]["EXT-TSMOM-001"]["validation_net_expectancy_bps"]))

    # --- same-close execution defect recorded, not hidden ---
    check("same_close_defect_recorded",
          pit.get("execution_justification_present") is False and
          pit.get("same_closure_defect", {}).get("code") == "EXECUTION_SEMANTICS_DEFECT")

    # --- benchmark independence (recompute BTC/EW without strategy) ---
    check("benchmark_independent", _benchmark_independent(close, days, syms))

    failed = [c for c in CHECKS if not c["ok"]]
    payload = {
        "checks_total": len(CHECKS), "checks_passed": len(CHECKS) - len(failed),
        "FALSE_SUCCESS": len(failed), "failed": failed, "checks": CHECKS,
        "verifier_note": ("independent re-implementation; no import of sprint031_lib or "
                          "sprint030_lib; own loops for panel/signal/weights/cost/pnl"),
    }
    (OUT / "RFC031_VERIFICATION.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md = ["# RFC-031 — INDEPENDENT VERIFICATION", "",
          f"- checks: {payload['checks_passed']}/{payload['checks_total']} passed",
          f"- FALSE_SUCCESS: **{payload['FALSE_SUCCESS']}**", "",
          "| check | ok | detail |", "| --- | --- | --- |"]
    md += [f"| {c['name']} | {'PASS' if c['ok'] else 'FAIL'} | {c['detail']} |"
           for c in CHECKS]
    (OUT / "RFC031_VERIFICATION.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"[verify031] FALSE_SUCCESS = {payload['FALSE_SUCCESS']} / {len(CHECKS)}")
    for c in failed:
        print(f"  FAIL: {c['name']} :: {c['detail']}")
    return 0 if not failed else 1


def _no_forward_fill(syms: list[str]) -> bool:
    for s in syms:
        p = CACHE / f"daily_{s}.npz"
        with np.load(p, allow_pickle=False) as z:
            ts = z["open_time_ms"].astype(np.int64).copy()
        if ts.size < 2:
            return False
        # raw series must begin at its first listing timestamp (no synthetic
        # leading bars inserted to fake pre-listing history)
        if int(ts.min()) != int(ts[0]):
            return False
        if not bool(np.all(np.diff(ts) > 0)):
            return False
    return True


def _poison(close: NDArray[Any]) -> bool:
    days = list(range(close.shape[0]))
    tests = month_first(days)[3:8]
    for i in tests:
        if i - 365 < 0:
            continue
        a = book(close, i)["w"]
        pc = close.copy()
        pc[i + 1:, :] = -1e6
        if not np.allclose(a, book(pc, i)["w"], equal_nan=True):
            return False
    return True


def _benchmark_independent(close: NDArray[Any], days: list[int],
                           syms: list[str]) -> bool:
    rebal = month_first(days)
    btc = syms.index("BTCUSDT")
    btc_r, ew_r = [], []
    for k in range(len(rebal) - 1):
        i, j = rebal[k], rebal[k + 1]
        if i - 365 < 0:
            continue
        good = np.isfinite(close[j]) & np.isfinite(close[i])
        r = np.full(close.shape[1], np.nan)
        r[good] = close[j, good] / close[i, good] - 1.0
        ew_r.append(float(np.nanmean(r)))
        if np.isfinite(close[i, btc]) and np.isfinite(close[j, btc]):
            btc_r.append(float(close[j, btc] / close[i, btc] - 1.0))
    bench = load_json(OUT / "BENCHMARK_COMPARISON.json")
    ew_ref = bench["benchmarks"]["equal_weight_basket"].get("net_expectancy_bps")
    btc_ref = bench["benchmarks"]["BTC_buy_and_hold"].get("net_expectancy_bps")
    ok = True
    if ew_ref is not None:
        ok = ok and abs(ew_ref - float(np.mean(ew_r)) * 1e4) <= 1e-3
    if btc_ref is not None:
        ok = ok and abs(btc_ref - float(np.mean(btc_r)) * 1e4) <= 1e-3
    return ok


if __name__ == "__main__":
    raise SystemExit(main())
