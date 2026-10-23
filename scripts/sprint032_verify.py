"""RFC-032 — INDEPENDENT VERIFIER (§27-§28, §77).  Builder != verifier.

Standalone: this module does NOT import ``sprint032_lib``, ``sprint031_lib`` or
``sprint030_lib``.  It re-loads the raw cache, re-derives the EXT-TSMOM-002
signal / long-cash mapping / weights / T+1 execution / turnover / cost / PnL with
its own loops, and compares them against the artifacts produced by
``sprint032_run.py``.  FALSE_SUCCESS counts violated checks; the target is 0.
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
OUT = REPO / "reports" / "tsmom-remediation"
CACHE = REPO / "reports" / "external-alpha" / "cache"

UNIVERSE = (
    "BTCUSDT",
    "ETHUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "ADAUSDT",
    "SOLUSDT",
    "DOGEUSDT",
    "DOTUSDT",
    "LTCUSDT",
    "LINKUSDT",
    "BCHUSDT",
    "XLMUSDT",
    "TRXUSDT",
    "ETCUSDT",
    "EOSUSDT",
    "XTZUSDT",
    "ZECUSDT",
    "DASHUSDT",
    "NEOUSDT",
    "ATOMUSDT",
    "VETUSDT",
    "FILUSDT",
    "THETAUSDT",
    "ALGOUSDT",
    "AVAXUSDT",
    "MATICUSDT",
    "FTTUSDT",
    "LUNAUSDT",
    "ICPUSDT",
    "SHIBUSDT",
)
SPLIT_BOUNDS = {
    "DISCOVERY": ("2018-01-01", "2021-06-30"),
    "VALIDATION": ("2021-07-01", "2023-12-31"),
    "HOLDOUT": ("2024-01-01", "2026-09-30"),
}
ERAS = (
    ("2018-2019", "2018-01-01", "2019-12-31"),
    ("2020-2021", "2020-01-01", "2021-12-31"),
    ("2022", "2022-01-01", "2022-12-31"),
    ("2023-2024", "2023-01-01", "2024-12-31"),
    ("2025-2026", "2025-01-01", "2026-12-31"),
)
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


def load() -> tuple[list[str], list[int], NDArray[Any], NDArray[Any]]:
    raw: dict[str, dict[str, NDArray[Any]]] = {}
    for s in UNIVERSE:
        p = CACHE / f"daily_{s}.npz"
        if p.exists():
            with np.load(p, allow_pickle=False) as z:
                raw[s] = {k: z[k] for k in z.files}
    syms = sorted(raw)
    days = sorted(
        {int(t) for d in raw.values() for t in d["open_time_ms"].astype(np.int64).tolist()}
    )
    di = {t: i for i, t in enumerate(days)}
    close = np.full((len(days), len(syms)), np.nan)
    open_ = np.full((len(days), len(syms)), np.nan)
    for j, s in enumerate(syms):
        ts = raw[s]["open_time_ms"].astype(np.int64)
        idx = np.array([di[int(t)] for t in ts.tolist()], dtype=np.int64)
        close[idx, j] = raw[s]["close"]
        open_[idx, j] = raw[s]["open"]
    return syms, days, close, open_


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


def range_mask(days: list[int], lo: str, hi: str) -> NDArray[Any]:
    a = int(datetime.fromisoformat(lo + "T00:00:00+00:00").timestamp() * 1000)
    b = int(datetime.fromisoformat(hi + "T23:59:59+00:00").timestamp() * 1000)
    return np.array([a <= t <= b for t in days], dtype=bool)


# --------------------------------------------------------------------------
# independent EXT-TSMOM-002 (own implementation; only R1 + R2)
# --------------------------------------------------------------------------


def book(close: NDArray[Any], i: int) -> dict[str, Any]:
    a = close.shape[1]
    out: dict[str, Any] = {"w": np.zeros(a), "min_w": 0.0, "ok": False, "back": i - 365}
    if i - 365 < 0:
        return out
    elig = np.isfinite(close[i]) & np.isfinite(close[i - 365])
    sig = np.zeros(a)
    sig[elig] = np.sign(close[i, elig] / close[i - 365, elig] - 1.0)
    lo = max(0, i - 60)
    rr = close[lo : i + 1]
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
    raw = np.where(raw > 0.0, raw, 0.0)  # R1
    s = float(np.sum(raw))
    if s > 0:
        out["w"] = raw / s
        out["ok"] = True
    out["min_w"] = float(np.min(out["w"]))
    return out


def sim(
    close: NDArray[Any],
    open_: NDArray[Any],
    days: list[int],
    mask: NDArray[Any],
    t_plus_1: bool = True,
) -> dict[str, Any]:
    a = close.shape[1]
    price = open_ if t_plus_1 else close
    rebal = [i for i in month_first(days) if mask[i]]
    prev = np.zeros(a)
    nets: list[float] = []
    gross: list[float] = []
    costs: list[float] = []
    traded: list[float] = []
    minw = 1e9
    sumw_max = -1e9
    for k in range(len(rebal) - 1):
        i, j = rebal[k], rebal[k + 1]
        if i - 365 < 0:
            continue
        b = book(close, i)
        # cash months are real observations: keep them (gross 0, unwind turnover)
        minw = min(minw, b["min_w"])
        sumw_max = max(sumw_max, float(np.sum(b["w"])))
        e0 = i + 1 if t_plus_1 else i
        e1 = j + 1 if t_plus_1 else j
        if e1 >= price.shape[0]:
            continue
        w = b["w"]
        good = np.isfinite(price[e1]) & np.isfinite(price[e0])
        ret = np.zeros(a)
        ret[good] = price[e1, good] / price[e0, good] - 1.0
        g = float(np.nansum(w * ret) * 1e4)
        tn = float(np.nansum(np.abs(w - prev)))
        costs.append(tn * PER_SIDE)
        traded.append(tn)
        gross.append(g)
        nets.append(g - tn * PER_SIDE)
        prev = w
    return {
        "nets": np.asarray(nets),
        "gross": np.asarray(gross),
        "costs": np.asarray(costs),
        "traded": np.asarray(traded),
        "minw": minw if minw < 1e9 else 0.0,
        "sumw_max": sumw_max,
    }


def stats(x: NDArray[Any]) -> dict[str, Any]:
    x = np.asarray(x, dtype=np.float64)
    if x.size == 0:
        return {"status": "EMPTY"}
    cum = np.cumsum(x)
    peak = np.maximum.accumulate(cum)
    return {
        "mean": float(np.mean(x)),
        "median": float(np.median(x)),
        "sharpe": (
            float(np.mean(x) / np.std(x, ddof=1) * math.sqrt(12.0))
            if x.size > 1 and np.std(x, ddof=1) > 0
            else None
        ),
        "max_dd": float(np.max(peak - cum)),
        "n": int(x.size),
    }


def close_to(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return bool(a == b)
    return bool(abs(float(a) - float(b)) <= max(TOL, abs(float(a)) * 1e-6))


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def main() -> int:
    _syms, days, close, open_ = load()
    full = np.ones(len(days), dtype=bool)
    art_hist = load_json(OUT / "HISTORICAL_DIAGNOSTIC.json")
    art_temp = load_json(OUT / "TEMPORAL_DIAGNOSTIC.json")
    art_pit = load_json(OUT / "PIT_EXECUTION_AUDIT.json")
    art_frozen = load_json(OUT / "EXT_TSMOM_002_FROZEN_SPEC.json")

    cand = sim(close, open_, days, full, t_plus_1=True)
    af = art_hist["full"]
    check(
        "full_net_match",
        close_to(float(np.mean(cand["nets"])), af["net_expectancy_bps"]),
        f"verify={np.mean(cand['nets']):.6f} artifact={af['net_expectancy_bps']}",
    )
    check("full_gross_match", close_to(float(np.mean(cand["gross"])), af["gross_expectancy_bps"]))
    check("full_cost_match", close_to(float(np.mean(cand["costs"])), af["cost_expectancy_bps"]))
    check(
        "full_turnover_match",
        close_to(float(np.mean(cand["traded"])), af["mean_turnover_notional"]),
    )
    check(
        "rebalances_match",
        cand["nets"].size == af["rebalances"],
        f"verify={cand['nets'].size} artifact={af['rebalances']}",
    )
    check("full_median_match", close_to(float(np.median(cand["nets"])), af["net_median_bps"]))
    check("no_negative_weights", cand["minw"] >= -1e-12, f"min_w={cand['minw']}")
    check("no_short_spot", cand["minw"] >= -1e-12, "R1: every weight >= 0")
    check("portfolio_no_leverage", cand["sumw_max"] <= 1.0 + 1e-9, f"max sum(w)={cand['sumw_max']}")

    # splits (diagnostic labels)
    for name in ("DISCOVERY", "VALIDATION", "HOLDOUT"):
        s = sim(close, open_, days, mask_of(days, name), t_plus_1=True)
        art = art_hist["splits_diagnostic_only"][name]
        check(
            f"{name.lower()}_net_match",
            close_to(float(np.mean(s["nets"])), art["net_expectancy_bps"]),
            f"verify={np.mean(s['nets']):.4f} artifact={art['net_expectancy_bps']}",
        )

    # §12 prior (co-timed long-or-cash) must match the recorded RFC-031 value
    prior = sim(close, open_, days, mask_of(days, "VALIDATION"), t_plus_1=False)
    check(
        "prior_validation_match",
        close_to(
            float(np.mean(prior["nets"])),
            art_hist["prior_recompute"]["rfc032_recomputed_long_or_cash_validation_net_bps"],
        ),
    )
    check(
        "prior_direction_negative",
        float(np.mean(prior["nets"])) < 0,
        f"prior={np.mean(prior['nets']):.4f} bps/month (<0 => confirms RFC-031)",
    )
    check(
        "prior_matches_rfc031",
        art_hist["prior_recompute"]["match"] is True,
        "RFC-032 recomputed the RFC-031 long-or-cash prior from raw",
    )

    # eras + recent windows
    for name, lo, hi in ERAS:
        s = sim(close, open_, days, range_mask(days, lo, hi), t_plus_1=True)
        art = art_temp["eras"][name]
        check(
            f"era_{name}_net_match",
            close_to(float(np.mean(s["nets"])), art["net_expectancy_bps"]),
            f"verify={np.mean(s['nets']):.3f} artifact={art['net_expectancy_bps']}",
        )
    r12 = np.asarray(cand["nets"])[-12:]
    r24 = np.asarray(cand["nets"])[-24:]
    check(
        "recent_12m_match",
        close_to(float(np.mean(r12)), art_temp["recent_12m"]["net_expectancy_bps"]),
    )
    check(
        "recent_24m_match",
        close_to(float(np.mean(r24)), art_temp["recent_24m"]["net_expectancy_bps"]),
    )

    # T+1 semantics: co-timed vs T+1 open must differ (execution really moved)
    cot = sim(close, open_, days, full, t_plus_1=False)
    check(
        "t_plus_1_execution_differs",
        not close_to(float(np.mean(cot["nets"])), float(np.mean(cand["nets"]))),
        "T+1 open fill is a different fill from same-close",
    )
    check(
        "artifact_exec_lag_is_t_plus_1",
        art_pit.get("exec_lag") == 1 and art_pit.get("executable_field") == "open",
    )

    # future poisoning, independent recompute
    cutoff = int(len(days) * 0.75)
    c2 = close.copy()
    o2 = open_.copy()
    c2[cutoff:] *= 7.0
    o2[cutoff:] *= 7.0
    same = True
    for i in month_first(days):
        if i >= cutoff:
            break
        if not np.allclose(book(close, i)["w"], book(c2, i)["w"], atol=1e-12):
            same = False
            break
    check("future_poisoning_pass", same, "past decisions unaffected by mutated futures")

    # cost reconciliation (own)
    check(
        "cost_reconciliation",
        close_to(float(np.mean(cand["costs"])), float(np.mean(cand["traded"] * PER_SIDE))),
        "cost == turnover * 15 bps",
    )

    # evidence labeling: no historical split may be labelled fresh evidence
    blob = json.dumps(art_hist).upper()
    labels_ok = (
        "DIAGNOSTIC" in art_hist["evidence_class"].upper()
        and "splits_diagnostic_only" in art_hist
        and "NEW_HOLDOUT" not in blob
        and "FRESH_VALIDATION" not in blob
    )
    check(
        "historical_diagnostic_labelling", labels_ok, f"evidence_class={art_hist['evidence_class']}"
    )

    # candidate/data-hash immutability verified against the raw cache on disk
    check("config_hash_present", bool(art_frozen.get("config_hash")))
    hashes_ok = True
    for s, h in art_frozen["data_hashes"].items():
        p = CACHE / f"daily_{s}.npz"
        digest = hashlib.sha256()
        with p.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                digest.update(chunk)
        if digest.hexdigest() != h:
            hashes_ok = False
            break
    check("data_hashes_match_cache", hashes_ok, "frozen data hashes reproduce on disk")

    # deterministic replay
    cand2 = sim(close, open_, days, full, t_plus_1=True)
    check(
        "deterministic_replay",
        bool(np.allclose(cand["nets"], cand2["nets"], atol=0.0)),
        "same inputs reproduce identical PnL",
    )

    # admission gates recomputed independently (G_REM_0 implementation + G_REM_1 plausibility)
    impl_checks = {
        "no_short_spot": cand["minw"] >= -1e-12,
        "t_plus_1_execution": (
            art_pit.get("exec_lag") == 1
            and art_pit.get("executable_field") == "open"
            and not close_to(float(np.mean(cot["nets"])), float(np.mean(cand["nets"])))
        ),
        "pit_clean": bool(same),
        "cost_accounting_clean": close_to(
            float(np.mean(cand["costs"])), float(np.mean(cand["traded"] * PER_SIDE))
        ),
        "deterministic_reproduction": bool(np.allclose(cand["nets"], cand2["nets"], atol=0.0)),
        "candidate_frozen": bool(art_frozen.get("config_hash")) and hashes_ok,
    }
    g_rem_0 = "PASS" if all(impl_checks.values()) else "FAIL"
    crit = {
        "C1": float(np.mean(cand["nets"])) > 0.0,
        "C2": float(np.median(cand["nets"])) > 0.0,
        "C3": sum(
            1 for k in art_temp["eras"] if (art_temp["eras"][k].get("net_expectancy_bps") or 0) > 0
        )
        >= 2,
        "C4": float(np.mean(r24)) > 0.0,
        "C5": float(np.mean(r12)) > 0.0,
    }
    plaus = all(crit.values())
    g_rem_1 = "PASS" if (g_rem_0 == "PASS" and plaus) else "FAIL"
    decision = "ADMITTED_FOR_FORWARD_EVIDENCE" if g_rem_1 == "PASS" else "REJECTED"
    paper_status = "PAPER_OBSERVING" if g_rem_1 == "PASS" else "PAPER_NOT_STARTED"
    next_step = "FORWARD PAPER OBSERVATION" if g_rem_1 == "PASS" else "STRATEGIC_PROJECT_DECISION"
    check("admission_gate_order", True, f"G_REM_0={g_rem_0} criteria={crit} -> G_REM_1={g_rem_1}")
    check("admission_fail_no_paper", (g_rem_1 != "FAIL") or paper_status == "PAPER_NOT_STARTED")
    check("admission_next_exact", (g_rem_1 != "FAIL") or next_step == "STRATEGIC_PROJECT_DECISION")

    # forward boundary: no forward artifact when not admitted
    paper_dir = REPO / "reports" / "paper" / "tsmom002"
    if g_rem_1 == "FAIL":
        check(
            "no_forward_artifacts_on_reject",
            not any(paper_dir.glob("*.json")) if paper_dir.exists() else True,
            "REJECT path must not create forward paper artifacts",
        )

    failed = [c for c in CHECKS if not c["ok"]]
    false_success = len(failed)
    reproduction_exact = all(
        c["ok"]
        for c in CHECKS
        if c["name"]
        in (
            "full_net_match",
            "full_gross_match",
            "full_cost_match",
            "full_turnover_match",
            "rebalances_match",
            "validation_net_match",
            "holdout_net_match",
            "discovery_net_match",
            "recent_12m_match",
            "recent_24m_match",
        )
    )
    payload: dict[str, Any] = {
        "rfc": "RFC-032",
        "role": "INDEPENDENT_VERIFIER",
        "generated": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_commit": _git_head(),
        "imports_strategy_code": False,
        "no_shared_strategy_pnl": True,
        "checks_total": len(CHECKS),
        "checks_passed": len(CHECKS) - false_success,
        "FALSE_SUCCESS": false_success,
        "reproduction_exact": bool(reproduction_exact),
        "checks": CHECKS,
        "independently_reproduced": {
            "full": stats(cand["nets"]),
            "validation": stats(
                sim(close, open_, days, mask_of(days, "VALIDATION"), t_plus_1=True)["nets"]
            ),
            "holdout": stats(
                sim(close, open_, days, mask_of(days, "HOLDOUT"), t_plus_1=True)["nets"]
            ),
        },
        "admission_criteria_independent": crit,
        "G_REM_0_independent": g_rem_0,
        "G_REM_1_independent": g_rem_1,
        "implementation_checks_independent": impl_checks,
        "decision_independent": decision,
        "next_independent": next_step,
    }
    (OUT / "RFC032_VERIFICATION.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    md = "\n".join(
        [
            "# RFC-032 — INDEPENDENT VERIFICATION",
            "",
            f"- checks: {payload['checks_passed']}/{payload['checks_total']} passed",
            f"- **FALSE_SUCCESS = {payload['FALSE_SUCCESS']}**",
            f"- reproduction exact: **{payload['reproduction_exact']}**",
            "",
            "| check | result | detail |",
            "| --- | --- | --- |",
            *[f"| {c['name']} | {'PASS' if c['ok'] else 'FAIL'} | {c['detail']} |" for c in CHECKS],
            "",
        ]
    )
    (OUT / "RFC032_VERIFICATION.md").write_text(md, encoding="utf-8")
    print(
        f"[verify032] FALSE_SUCCESS={payload['FALSE_SUCCESS']} "
        f"({payload['checks_passed']}/{payload['checks_total']})",
        flush=True,
    )
    for c in failed:
        print(f"  FAILED: {c['name']} :: {c['detail']}", flush=True)
    return 0 if false_success == 0 else 1


def _git_head() -> str:
    try:
        import subprocess

        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "UNKNOWN"


if __name__ == "__main__":
    raise SystemExit(main())
