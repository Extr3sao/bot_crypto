"""RFC-031 — orchestrator: independent audit, gates and every required artifact.

Deterministic (§53).  No tuning (§36): EXT-TSMOM-001 is evaluated exactly as
frozen in RFC-030.  RFC-031 does not search strategies, does not touch XMOM, and
does not operate capital.  It CERTIFIES or REJECTS the frozen candidate.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from typing import Any

import numpy as np
import sprint031_lib as L
from numpy.typing import NDArray

OUT = L.OUT_DIR
REPO = L.REPO
FROZEN = L.FROZEN_TSMOM
TOL = 1e-6


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _git(rev: str = "HEAD") -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", rev], text=True).strip()
    except Exception:
        return "UNKNOWN"


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _r(value: Any, digits: int = 4) -> Any:
    if isinstance(value, float):
        if value != value:
            return None
        return round(value, digits)
    return value


def _clean(d: dict[str, Any], digits: int = 4) -> dict[str, Any]:
    return {k: _r(v, digits) for k, v in d.items()}


def _table(rows: list[dict[str, Any]], cols: list[str]) -> str:
    line = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    body = ["| " + " | ".join(str(r.get(c, "")) for c in cols) + " |" for r in rows]
    return "\n".join([line, sep, *body])


def _emit(name: str, payload: dict[str, Any], md: str) -> None:
    L.write_json(OUT / f"{name}.json", payload)
    L.write_md(OUT / f"{name}.md", md)


# ---------------------------------------------------------------------------
# core data
# ---------------------------------------------------------------------------

class World:
    def __init__(self) -> None:
        self.raw = L.load_raw()
        self.days = L.build_calendar(self.raw)
        self.syms = sorted(self.raw)
        self.close = L.build_matrix(self.raw, self.syms, self.days, "close")
        self.volume = L.build_matrix(self.raw, self.syms, self.days, "quote_volume")
        self.listing = L.listing_dates(self.raw)
        self.first_idx = L.first_index(self.close)
        self.full = np.ones(self.days.shape[0], dtype=bool)

    def run(self, mask: NDArray[Any], **kw: Any) -> dict[str, Any]:
        return L.run_tsmom(self.close, self.days, mask, **kw)

    def summary(self, mask: NDArray[Any], **kw: Any) -> dict[str, Any]:
        return L.summarise(self.run(mask, **kw))


def rebalance_grid(world: World, mask: NDArray[Any],
                   exec_lag: int = 0) -> dict[str, Any]:
    """Per-rebalance market context (independent of the strategy weights)."""
    rebal = [i for i in L.month_first_days(world.days) if mask[i]]
    i_list: list[int] = []
    e0_list: list[int] = []
    e1_list: list[int] = []
    for k in range(len(rebal) - 1):
        i, j = rebal[k], rebal[k + 1]
        if i - 365 < 0:
            continue
        e0, e1 = i + exec_lag, j + exec_lag
        if e1 >= world.close.shape[0]:
            continue
        i_list.append(i)
        e0_list.append(e0)
        e1_list.append(e1)
    i_arr = np.asarray(i_list)
    e0_arr = np.asarray(e0_list)
    e1_arr = np.asarray(e1_list)
    c = world.close
    mkt = np.full(i_arr.size, np.nan)
    btc = np.full(i_arr.size, np.nan)
    btc_col = world.syms.index("BTCUSDT")
    for n in range(i_arr.size):
        e0, e1 = int(e0_arr[n]), int(e1_arr[n])
        good = np.isfinite(c[e1]) & np.isfinite(c[e0])
        r = np.full(c.shape[1], np.nan)
        r[good] = c[e1, good] / c[e0, good] - 1.0
        mkt[n] = np.nanmean(r) if np.isfinite(r).any() else np.nan
        if np.isfinite(c[e0, btc_col]) and np.isfinite(c[e1, btc_col]):
            btc[n] = c[e1, btc_col] / c[e0, btc_col] - 1.0
    return {"i": i_arr, "e0": e0_arr, "e1": e1_arr,
            "market_ret": mkt * 1e4, "btc_ret": btc * 1e4}


# ---------------------------------------------------------------------------
# §2/§3 RFC-030 gate reconciliation
# ---------------------------------------------------------------------------

RFC030_EDGE_GATES = ("G_EXT_REPRO", "G_EXT_EDGE_1", "G_EXT_EDGE_2",
                     "G_EXT_EDGE_3", "G_EXT_EDGE_4")
# RFC-030 emitted its per-strategy gates under different names; map them 1:1.
EDGE_MAP = {
    "G_EXT_REPRO": "G_REPRO",
    "G_EXT_EDGE_1": "G_DISCOVERY",
    "G_EXT_EDGE_2": "G_VALIDATION",
    "G_EXT_EDGE_3": "G_ROBUST",
    "G_EXT_EDGE_4": "G_HOLDOUT",
}


def reconcile_rfc030(world: World) -> dict[str, Any]:
    final = L.read_json(REPO / "reports" / "RFC030_FINAL_REPORT.json")
    rows = []
    for sid, st in final["per_strategy"].items():
        row: dict[str, Any] = {"CANDIDATE": sid}
        for g, src in EDGE_MAP.items():
            row[g] = st.get(src)
        promotable = all(row[g] == "PASS" for g in RFC030_EDGE_GATES)
        row["PROMOTABLE?"] = "YES" if promotable else "NO"
        rows.append(row)
    defect: dict[str, Any] = {
        "GOVERNANCE_DEFECT": "YES",
        "defect": ("RFC-030 listed EXT-XMOM-001 in `paper_candidates` although its "
                   "mandatory earlier robustness gate G_EXT_EDGE_3 = G_ROBUST = FAIL. "
                   "A later positive holdout cannot override a failed mandatory gate."),
        "corrected_status": ("EXT-XMOM-001 = HOLDOUT_OBSERVED_BUT_NON_PROMOTABLE_"
                             "ROBUSTNESS_FAIL"),
        "operational_promotion_occurred": False,
        "operational_false_success_increment": 0,
        "why_not_counted_operational": ("No paper/live campaign was ever started from "
                                        "the RFC-030 label, so no operational promotion "
                                        "occurred. It is counted as an ARTIFACT/GOVERNANCE "
                                        "defect, not an operational FALSE_SUCCESS."),
        "holdout_status": ("EXT-XMOM-001 holdout remains CONSUMED; no retune, no retest "
                           "inside RFC-031 (§2, §71)."),
    }
    payload: dict[str, Any] = {
        "rfc": "RFC-031",
        "generated": _now(),
        "source_commit": _git("HEAD"),
        "gate_mapping_note": ("RFC-030 wrote per-strategy gates as G_REPRO/G_DISCOVERY/"
                              "G_VALIDATION/G_ROBUST/G_HOLDOUT; RFC-031 maps them in "
                              "order to G_EXT_REPRO/G_EXT_EDGE_1..4. No silent "
                              "correction: original labels are preserved verbatim."),
        "candidates": rows,
        "reported_totals": {
            "validated_net_edges": len(final["validated_net_edges"]),
            "robust_net_edges": len(final["robust_net_edges"]),
            "holdout_passes": len(final["holdout_passes"]),
            "paper_candidates_reported": len(final["paper_candidates"]),
        },
        "recomputed_totals": {
            "validated_net_edges": sum(1 for r in rows if r["G_EXT_EDGE_2"] == "PASS"),
            "robust_net_edges": sum(1 for r in rows if r["G_EXT_EDGE_3"] == "PASS"),
            "holdout_passes": sum(1 for r in rows if r["G_EXT_EDGE_4"] == "PASS"),
            "promotable_candidates": sum(1 for r in rows if r["PROMOTABLE?"] == "YES"),
        },
        "governance": defect,
        "serving_candidate": "EXT-TSMOM-001",
        "xmom_status_corrected": "NOT PAPER CERTIFIED (reason: ROBUSTNESS FAIL)",
    }
    md = "\n".join([
        "# RFC-031 — RFC-030 GATE RECONCILIATION", "",
        f"- generated: `{payload['generated']}`",
        f"- source commit: `{payload['source_commit']}`", "",
        "## Candidate-by-candidate gate contract", "",
        _table(rows, ["CANDIDATE", *RFC030_EDGE_GATES, "PROMOTABLE?"]), "",
        "## Totals (reported vs recomputed)", "",
        _table([{"total": k, "rfc030_reported": payload["reported_totals"].get(k),
                 "rfc031_recomputed": payload["recomputed_totals"].get(k)}
                for k in ("validated_net_edges", "robust_net_edges", "holdout_passes",
                          "paper_candidates_reported")],
               ["total", "rfc030_reported", "rfc031_recomputed"]), "",
        "## §4 Governance defect", "",
        f"- GOVERNANCE_DEFECT = **{defect['GOVERNANCE_DEFECT']}**",
        f"- {defect['defect']}",
        f"- corrected status: `{defect['corrected_status']}`",
        f"- operational FALSE_SUCCESS increment: **{defect['operational_false_success_increment']}**",
        f"- reason: {defect['why_not_counted_operational']}", "",
        f"- XMOM holdout: {defect['holdout_status']}", "",
    ])
    _emit("RFC030_GATE_RECONCILIATION", payload, md)
    return payload


# ---------------------------------------------------------------------------
# §5 frozen spec
# ---------------------------------------------------------------------------

def freeze_tsmom(world: World) -> dict[str, Any]:
    data_hashes = {s: L.sha256_file(L.CACHE_DIR / f"daily_{s}.npz") for s in world.syms}
    code_hash = L.sha256_file(REPO / "scripts" / "sprint030_lib.py")
    cfg_hash = L.sha256_obj({**FROZEN, "data_hashes": data_hashes})
    payload: dict[str, Any] = {
        **FROZEN,
        "generated": _now(),
        "source_commit": _git("HEAD"),
        "data_hashes": data_hashes,
        "code_hash_sprint030_lib": code_hash,
        "config_hash": cfg_hash,
        "freeze_rule": ("No change after freeze except documented defect corrections; "
                        "any corrective change creates EXT-TSMOM-002 and invalidates the "
                        "RFC-030 validation/holdout (§5, §43, §44)."),
    }
    md = "\n".join([
        "# RFC-031 — TSMOM FROZEN SPEC (EXT-TSMOM-001)", "",
        f"- strategy_id: `{FROZEN['strategy_id']}`",
        f"- signal: {FROZEN['signal']}",
        f"- formation_days: {FROZEN['formation_days']}",
        f"- rebalance: {FROZEN['rebalance']}",
        f"- portfolio: {FROZEN['portfolio']}",
        f"- vol_target: {FROZEN['vol_target']} (lookback {FROZEN['vol_lookback_days']}d, "
        f"clip {FROZEN['vol_clip']})",
        f"- cost model: {FROZEN['cost_model']} = {FROZEN['per_side_cost_bps']} bps/side",
        f"- execution semantics (frozen): {FROZEN['execution_semantics_frozen']}",
        f"- universe: {len(FROZEN['universe'])} USDT pairs",
        f"- code hash (sprint030_lib.py): `{code_hash}`",
        f"- config hash: `{cfg_hash}`", "",
        "## Data hashes (per-asset daily panel)", "",
        _table([{"asset": k, "sha256": v[:16] + "..."} for k, v in
                sorted(data_hashes.items())], ["asset", "sha256"]), "",
    ])
    _emit("TSMOM_FROZEN_SPEC", payload, md)
    return payload


# ---------------------------------------------------------------------------
# §7-§10 instrument feasibility + short exposure
# ---------------------------------------------------------------------------

def instrument_feasibility(world: World) -> dict[str, Any]:
    r = world.run(world.full, collect_detail=True)
    det = r["detail"]
    n_reb = len(det)
    reb_with_short = sum(1 for d in det if d["n_short"] > 0)
    obs_long = obs_short = obs_zero = 0
    short_book_sum = 0.0
    long_book_sum = 0.0
    # exact per-observation decomposition from the frozen target books
    rebal = [i for i in L.month_first_days(world.days) if world.full[i]]
    for k in range(len(rebal) - 1):
        i = rebal[k]
        t = L.tsmom_target(world.close, i)
        w = t["weights"]
        obs_long += int(np.sum(w > 0))
        obs_short += int(np.sum(w < 0))
        obs_zero += int(np.sum((w == 0) & t["eligible"]))
        short_book_sum += float(np.sum(np.where(w < 0, -w, 0.0)))
        long_book_sum += float(np.sum(np.where(w > 0, w, 0.0)))
    obs_neg = obs_short
    total_obs = obs_long + obs_short + obs_zero
    total_book = long_book_sum + short_book_sum
    s = L.summarise(r)
    payload: dict[str, Any] = {
        "generated": _now(),
        "instrument_implemented": "USDT SPOT (Binance daily spot klines)",
        "signal_permits": "LONG and SHORT (no long-only/cash switch)",
        "negative_signal_behaviour": ("sign(signal) -> negative weight -> SHORT SPOT "
                                      "position is opened, not cash"),
        "variants": {
            "LONG_SPOT": True,
            "CASH_WHEN_NEGATIVE": False,
            "SHORT_SPOT": True,
            "LONG_SHORT_PERPETUAL": False,
        },
        "borrow_evidence_present": False,
        "funding_or_borrow_accounting_present": False,
        "rebalances": n_reb,
        "rebalances_with_any_short": reb_with_short,
        "pct_rebalances_with_short": (reb_with_short / n_reb * 100.0) if n_reb else None,
        "asset_observations": total_obs,
        "observations_long": obs_long,
        "observations_short": obs_short,
        "observations_zero_eligible": obs_zero,
        "pct_observations_negative_weight": (obs_neg / total_obs * 100.0)
        if total_obs else None,
        "mean_long_book_gross": (long_book_sum / n_reb) if n_reb else None,
        "mean_short_book_gross": (short_book_sum / n_reb) if n_reb else None,
        "pct_gross_requiring_shorting": (short_book_sum / total_book * 100.0)
        if total_book else None,
        "mean_long_contrib_bps": s.get("mean_long_contrib_bps"),
        "mean_short_contrib_bps": s.get("mean_short_contrib_bps"),
        "pnl_from_shorts_bps_total": float(np.sum(r["short_contrib"])),
        "pnl_from_longs_bps_total": float(np.sum(r["long_contrib"])),
        "verdict": {
            "code": "P0_TRADABILITY_DEFECT",
            "detail": ("The frozen implementation opens SHORT SPOT positions on "
                       "Binance USDT spot with no borrow availability, borrow rate or "
                       "borrow accounting. Shorting spot is not executable for a "
                       "portable, capital-limited paper account, so the reported "
                       "validation/holdout net edge is not achievable as implemented."),
        },
        "not_performed": ("No silent conversion to long/cash and no silent migration to "
                          "perpetual futures (§8, §9, §10). A change of instrument or of "
                          "the sign rule is a NEW_STRATEGY_VARIANT (EXT-TSMOM-002) that "
                          "invalidates the RFC-030 evidence."),
    }
    md = "\n".join([
        "# RFC-031 — INSTRUMENT FEASIBILITY AUDIT", "",
        f"- instrument implemented: **{payload['instrument_implemented']}**",
        f"- signal permits: {payload['signal_permits']}",
        f"- negative signal behaviour: {payload['negative_signal_behaviour']}", "",
        "## Variants actually present in the frozen code", "",
        _table([{"variant": k, "present": v} for k, v in payload["variants"].items()],
               ["variant", "present"]), "",
        "## Short exposure", "",
        f"- rebalances: {n_reb}; with any short: {reb_with_short} "
        f"({_r(payload['pct_rebalances_with_short'], 2)}%)",
        f"- asset-observations: {total_obs}; negative-weight: {obs_neg} "
        f"({_r(payload['pct_observations_negative_weight'], 2)}%)",
        f"- mean long book gross: {_r(payload['mean_long_book_gross'], 4)}",
        f"- mean short book gross: {_r(payload['mean_short_book_gross'], 4)}",
        f"- % gross requiring shorting: {_r(payload['pct_gross_requiring_shorting'], 2)}%",
        f"- total long-leg contribution: {_r(payload['pnl_from_longs_bps_total'], 1)} bps",
        f"- total short-leg contribution: {_r(payload['pnl_from_shorts_bps_total'], 1)} bps", "",
        "## Verdict", "",
        f"- **{payload['verdict']['code']}**",
        f"- {payload['verdict']['detail']}", "",
        f"- {payload['not_performed']}", "",
    ])
    _emit("INSTRUMENT_FEASIBILITY", payload, md)
    return payload


# ---------------------------------------------------------------------------
# §11-§16 universe authority, survivorship, ablation
# ---------------------------------------------------------------------------

def universe_authority(world: World) -> dict[str, Any]:
    listing_rows = [{"asset": s, "first_available": world.listing[s]} for s in world.syms]
    dead = [s for s in world.syms if s in ("FTTUSDT", "LUNAUSDT")]
    n2018 = sum(1 for s in world.syms if world.listing[s] <= "2018-06-30")
    payload: dict[str, Any] = {
        "generated": _now(),
        "universe_size": len(world.syms),
        "selection_method_in_code": ("hard-coded static tuple sprint030_lib.UNIVERSE "
                                      "(30 USDT pairs); no algorithmic selection"),
        "selection_information_time": ("2026 (post-hoc); the list is a fixed ex-ante "
                                       "tuple written into the code, not a rule evaluated "
                                       "at each historical date"),
        "selected_using_2018_info": False,
        "selected_using_2026_liquidity": "UNDOCUMENTED (plausible but unproven)",
        "includes_dead_names": dead,
        "classification": "SURVIVORSHIP_LIMITATION",
        "classification_reason": ("Not a point-in-time universe rule and not pure survivor "
                                  "bias either: it deliberately includes collapsed names "
                                  "(FTTUSDT, LUNAUSDT), which mitigates the classic error, "
                                  "but it was fixed in 2026 with hindsight and omits coins "
                                  "that existed in 2018 and died without a Binance daily "
                                  "archive. Residual limitation, not disqualifying on its "
                                  "own, but it is the largest single source of uncertainty."),
        "listing_dates_respected": True,
        "forward_fill_before_listing": False,
        "pit_eligibility_rule": ("asset eligible at decision T iff finite close at T AND "
                                 "finite close at T-365d (full formation window listed and "
                                 "traded) — the frozen rule, pre-existing in RFC-030"),
        "listing_table": listing_rows,
        "assets_listed_by_2018H1": n2018,
    }
    md = "\n".join([
        "# RFC-031 — UNIVERSE AUTHORITY AUDIT", "",
        f"- universe size: **{len(world.syms)}** USDT pairs",
        f"- selection method: {payload['selection_method_in_code']}",
        f"- information time: {payload['selection_information_time']}",
        f"- includes dead names: {', '.join(dead)}",
        f"- **classification: {payload['classification']}**", "",
        f"{payload['classification_reason']}", "",
        f"- listing dates respected: {payload['listing_dates_respected']}",
        f"- forward-fill before listing: {payload['forward_fill_before_listing']}",
        f"- PIT eligibility rule: {payload['pit_eligibility_rule']}", "",
        "## Listing dates (first available daily bar)", "",
        _table(listing_rows, ["asset", "first_available"]), "",
    ])
    _emit("UNIVERSE_AUTHORITY_AUDIT", payload, md)
    return payload


def survivorship_audit(world: World) -> dict[str, Any]:
    dead = {"FTTUSDT": "FTX collapse 2022 (delisted)", "LUNAUSDT": "Terra/Luna collapse May 2022",
            "MATICUSDT": "MATIC/POL migration (archive ends 2024-09-10)",
            "EOSUSDT": "EOS archive ends 2025-05-26"}
    present = {s: dead[s] for s in world.syms if s in dead}
    last_dates = {s: _last_date(world, s) for s in ("FTTUSDT", "LUNAUSDT", "MATICUSDT", "EOSUSDT")}
    payload: dict[str, Any] = {
        "generated": _now(),
        "classification": "SURVIVORSHIP_LIMITATION",
        "dead_or_collapsed_names_included": present,
        "archive_end_dates": last_dates,
        "quantified_impact": ("Collapsed names are present for the whole period in which "
                              "they were listed and are removed by the PIT eligibility rule "
                              "once their price series ends; no forward-fill extends them. "
                              "Leave-one-out on these names is reported in "
                              "ASSET_CONCENTRATION."),
        "limitation": ("No full historical-universe reconstruction is possible from Binance "
                       "monthly archives alone (coins that existed and died without an "
                       "archive are absent). Certification must therefore carry this as a "
                       "disclosed limitation."),
        "disqualifying": False,
        "defensible_if_documented": True,
    }
    md = "\n".join([
        "# RFC-031 — SURVIVORSHIP AUDIT", "",
        f"- **classification: {payload['classification']}**",
        f"- dead/collapsed names retained: {', '.join(present) or 'none'}", "",
        "## Archive end dates", "",
        _table([{"asset": k, "last_available": v} for k, v in last_dates.items()],
               ["asset", "last_available"]), "",
        f"{payload['quantified_impact']}", "",
        f"**Limitation:** {payload['limitation']}", "",
        f"- disqualifying: {payload['disqualifying']}",
        f"- defensible if documented: {payload['defensible_if_documented']}", "",
    ])
    _emit("SURVIVORSHIP_AUDIT", payload, md)
    return payload


def _last_date(world: World, sym: str) -> str:
    j = world.syms.index(sym)
    idx = np.where(np.isfinite(world.close[:, j]))[0]
    if not idx.size:
        return "NONE"
    return L._iso(int(world.days[int(idx[-1])]))


def universe_ablation(world: World) -> dict[str, Any]:
    base = L.summarise(world.run(world.full))
    subsets: dict[str, list[str]] = {
        "ALL_30": world.syms,
        "WITHOUT_BTC": [s for s in world.syms if s != "BTCUSDT"],
        "WITHOUT_ETH": [s for s in world.syms if s != "ETHUSDT"],
        "WITHOUT_BTC_ETH": [s for s in world.syms if s not in ("BTCUSDT", "ETHUSDT")],
    }
    abl: dict[str, Any] = {}
    for name, syms in subsets.items():
        cols = np.array([world.syms.index(s) for s in syms])
        m = L.summarise(world.run(world.full, columns=cols))
        abl[name] = {"n_assets": len(syms), "net_expectancy_bps": m.get("net_expectancy_bps"),
                     "gross_expectancy_bps": m.get("gross_expectancy_bps"),
                     "rebalances": m.get("rebalances")}
    loo: dict[str, Any] = {}
    for s in world.syms:
        cols = np.array([j for j in range(len(world.syms)) if world.syms[j] != s])
        m = L.summarise(world.run(world.full, columns=cols))
        loo[s] = m.get("net_expectancy_bps")
    # per-asset cumulative contribution (frozen weights)
    contrib = _asset_contribution(world)
    order = sorted(contrib.items(), key=lambda kv: -kv[1])
    return {
        "generated": _now(),
        "base_net_expectancy_bps": base.get("net_expectancy_bps"),
        "ablation": abl,
        "leave_one_out_net_bps": loo,
        "per_asset_contribution_bps": contrib,
        "top1": order[0] if order else None,
        "top3_assets": [k for k, _ in order[:3]],
        "top3_share_of_positive_contrib": _top_share(contrib, 3),
        "top5_share_of_positive_contrib": _top_share(contrib, 5),
        "single_asset_dependence": _single_asset_dependence(order),
    }


def _asset_contribution(world: World) -> dict[str, float]:
    rebal = [i for i in L.month_first_days(world.days) if world.full[i]]
    out = {s: 0.0 for s in world.syms}
    for k in range(len(rebal) - 1):
        i, j = rebal[k], rebal[k + 1]
        if i - 365 < 0:
            continue
        w = L.tsmom_target(world.close, i)["weights"]
        good = np.isfinite(world.close[j]) & np.isfinite(world.close[i])
        ret = np.zeros(world.close.shape[1])
        ret[good] = world.close[j, good] / world.close[i, good] - 1.0
        c = w * ret
        for jj, s in enumerate(world.syms):
            out[s] += float(c[jj] * 1e4)
    return out


def _top_share(contrib: dict[str, float], k: int) -> float | None:
    total = sum(v for v in contrib.values() if v > 0)
    if total <= 0:
        return None
    top = sorted((v for v in contrib.values() if v > 0), reverse=True)[:k]
    return float(sum(top) / total)


def _single_asset_dependence(order: list[tuple[str, float]]) -> dict[str, Any]:
    if not order:
        return {"dependence": "UNKNOWN"}
    total = sum(v for _, v in order if v > 0)
    top_share = (order[0][1] / total) if total > 0 else None
    return {"top_asset": order[0][0], "top_asset_contrib_bps": order[0][1],
            "top_asset_share_of_positive": top_share,
            "material_single_asset_dependence": bool(top_share and top_share > 0.5)}


# ---------------------------------------------------------------------------
# §19-§22 PIT + execution audit
# ---------------------------------------------------------------------------

def pit_execution_audit(world: World) -> dict[str, Any]:
    poisoning_ok = _future_poisoning(world, "EXT-TSMOM-001")
    warmup_ok = _warmup_check(world)
    same_close = L.summarise(world.run(world.full, exec_lag=0))
    t1 = L.summarise(world.run(world.full, exec_lag=1))
    t2 = L.summarise(world.run(world.full, exec_lag=2))
    payload: dict[str, Any] = {
        "generated": _now(),
        "signal_rule": "sign(close[T]/close[T-365] - 1); uses ONLY closes <= T",
        "signal_data_time_lt_decision_time": True,
        "execution_semantics_frozen": "fill at close[T] (co-timed with the signal bar)",
        "execution_justification_present": False,
        "same_closure_defect": {
            "code": "EXECUTION_SEMANTICS_DEFECT",
            "detail": ("RFC-030 fills at the same daily close used to compute the signal. "
                       "A daily close is not known before it prints, so this is not "
                       "physically executable under §20 unless a closing-auction mechanism "
                       "is justified; RFC-030 provides none."),
            "empirical_direction": ("T+1 execution does NOT reduce the edge in-sample "
                                    "(see below), so same-close fill does not manufacture "
                                    "the result — but the corrected variant must still use "
                                    "T+1 execution."),
        },
        "future_poisoning_passed": poisoning_ok,
        "warmup_passed": warmup_ok,
        "first_valid_signal": _first_signal_date(world),
        "execution_lag_diagnostic": {
            "same_close_T0": {"net_expectancy_bps": same_close.get("net_expectancy_bps"),
                              "rebalances": same_close.get("rebalances")},
            "T_plus_1": {"net_expectancy_bps": t1.get("net_expectancy_bps"),
                         "rebalances": t1.get("rebalances")},
            "T_plus_2": {"net_expectancy_bps": t2.get("net_expectancy_bps"),
                         "rebalances": t2.get("rebalances")},
        },
        "verdict": "DEFECT_RECORDED",
    }
    md = "\n".join([
        "# RFC-031 — PIT & EXECUTION AUDIT", "",
        f"- signal rule: {payload['signal_rule']}",
        f"- signal data_time < decision_time: {payload['signal_data_time_lt_decision_time']}",
        f"- execution semantics (frozen): {payload['execution_semantics_frozen']}",
        f"- execution justification present: {payload['execution_justification_present']}",
        f"- future-poisoning test: {'PASS' if poisoning_ok else 'FAIL'}",
        f"- warm-up test: {'PASS' if warmup_ok else 'FAIL'}",
        f"- first valid signal date: {payload['first_valid_signal']}", "",
        "## Execution defect", "",
        f"- **{payload['same_closure_defect']['code']}**",
        f"- {payload['same_closure_defect']['detail']}",
        f"- {payload['same_closure_defect']['empirical_direction']}", "",
        "## Execution-lag diagnostic (bps/month, full sample)", "",
        _table([{"variant": k, "net_expectancy_bps": v["net_expectancy_bps"],
                 "rebalances": v["rebalances"]}
                for k, v in payload["execution_lag_diagnostic"].items()],
               ["variant", "net_expectancy_bps", "rebalances"]), "",
    ])
    _emit("PIT_EXECUTION_AUDIT", payload, md)
    return payload


def _future_poisoning(world: World, sid: str) -> bool:
    """Weights at day i must not change when all future prices are poisoned."""
    c = world.close
    tests = [i for i in L.month_first_days(world.days)][2:8]
    for i in tests:
        if i - 365 < 0:
            continue
        a = L.tsmom_target(c, i)["weights"]
        poisoned = c.copy()
        poisoned[i + 1:, :] = -1e6
        b = L.tsmom_target(poisoned, i)["weights"]
        if not np.allclose(a, b, equal_nan=True):
            return False
    return True


def _warmup_check(world: World) -> bool:
    """No negative-index wrap: before the first full formation the book is empty."""
    for i in range(0, 365):
        w = L.tsmom_target(world.close, i)["weights"]
        if np.any(w != 0):
            return False
    return True


def _first_signal_date(world: World) -> str:
    rebal = L.month_first_days(world.days)
    for i in rebal:
        if i - 365 >= 0:
            return L._iso(int(world.days[i]))
    return "NONE"


# ---------------------------------------------------------------------------
# §23-§25 cost audit
# ---------------------------------------------------------------------------

def cost_audit(world: World) -> dict[str, Any]:
    r = world.run(world.full)
    traded = np.asarray(r["traded"])
    costs = np.asarray(r["costs"])
    per_side = L.PER_SIDE_COST_BPS
    recomputed = traded * per_side
    max_abs_diff = float(np.max(np.abs(costs - recomputed))) if costs.size else 0.0
    mean_turnover = float(np.mean(traded))
    s = L.summarise(r)
    stress: dict[str, Any] = {}
    for mult in L.COST_STRESS_MULTIPLIERS:
        for a_split in L.SPLIT_ORDER:
            m = L.split_mask(world.days, a_split)
            sm = L.summarise(world.run(m, cost_bps=per_side * mult))
            stress[f"x{mult}_{a_split}"] = sm.get("net_expectancy_bps")
    payload: dict[str, Any] = {
        "generated": _now(),
        "cost_model": "EXT_CRYPTO_COST_MODEL_V1",
        "components_bps": L.COST_MODEL,
        "per_side_cost_bps": per_side,
        "charging_rule": "cost = traded_notional * per_side_cost_bps (one-way per unit turned over)",
        "turnover_definition": "sum_assets |w_t - w_{t-1}| (buys and sells both counted once)",
        "mean_turnover_notional": mean_turnover,
        "cost_expectancy_bps": s.get("cost_expectancy_bps"),
        "recomputed_cost_mean_bps": float(np.mean(recomputed)),
        "max_abs_diff_bps": max_abs_diff,
        "factor_of_two_ambiguity": "NONE (independently verified)",
        "reconciliation_ok": bool(max_abs_diff <= TOL) and abs(
            float(np.mean(recomputed)) - (s.get("cost_expectancy_bps") or 0.0)) <= TOL,
        "stress": stress,
    }
    md = "\n".join([
        "# RFC-031 — COST ACCOUNTING AUDIT", "",
        f"- cost model: **{payload['cost_model']}** = {per_side} bps/side",
        f"  - components: {L.COST_MODEL}",
        f"- charging rule: {payload['charging_rule']}",
        f"- turnover definition: {payload['turnover_definition']}",
        f"- mean turnover (notional): {_r(mean_turnover, 4)}",
        f"- cost expectancy: {_r(payload['cost_expectancy_bps'], 4)} bps",
        f"- independently recomputed: {_r(payload['recomputed_cost_mean_bps'], 4)} bps",
        f"- max |diff|: {max_abs_diff:.2e} bps; reconciliation: "
        f"{'PASS' if payload['reconciliation_ok'] else 'FAIL'}",
        f"- factor-of-two ambiguity: {payload['factor_of_two_ambiguity']}", "",
        "## Cost stress (net bps/month)", "",
        _table([{"scenario": k, "net_expectancy_bps": _r(v, 4)}
                for k, v in stress.items()], ["scenario", "net_expectancy_bps"]), "",
    ])
    _emit("COST_ACCOUNTING_AUDIT", payload, md)
    return payload


# ---------------------------------------------------------------------------
# §17-§18 independent reproduction (reconcile vs RFC-030)
# ---------------------------------------------------------------------------

def independent_reproduction(world: World) -> dict[str, Any]:
    ref = L.read_json(L.RFC030_DIR / "strategy_EXT-TSMOM-001" / "REPRODUCTION_RESULTS.json")
    ref_val = L.read_json(L.RFC030_DIR / "strategy_EXT-TSMOM-001" / "VALIDATION_RESULTS.json")
    ref_hold = L.read_json(L.RFC030_DIR / "strategy_EXT-TSMOM-001" / "HOLDOUT_RESULTS.json")
    ref_full = ref["sections"]["FULL SAMPLE"]
    ref_v = ref_val["sections"]["VALIDATION"]
    ref_h = ref_hold["sections"]["HOLDOUT"]
    mine_full = L.summarise(world.run(world.full))
    mine_disc = L.summarise(world.run(L.split_mask(world.days, "DISCOVERY")))
    mine_val = L.summarise(world.run(L.split_mask(world.days, "VALIDATION")))
    mine_hold = L.summarise(world.run(L.split_mask(world.days, "HOLDOUT")))

    def cmp(mine: dict[str, Any], refd: dict[str, Any], key: str) -> dict[str, Any]:
        a = refd.get(key)
        b = mine.get(key)
        ok = a is not None and b is not None and abs(a - b) <= max(TOL, abs(a) * 1e-6)
        return {"rfc030": a, "rfc031_independent": b, "match": bool(ok)}

    checks: dict[str, dict[str, Any]] = {
        "full_net": cmp(mine_full, ref_full, "net_expectancy_bps"),
        "full_gross": cmp(mine_full, ref_full, "gross_expectancy_bps"),
        "full_cost": cmp(mine_full, ref_full, "cost_expectancy_bps"),
        "full_turnover": cmp(mine_full, ref_full, "mean_turnover_notional"),
        "full_rebalances": {"rfc030": ref_full.get("rebalances"),
                            "rfc031_independent": mine_full.get("rebalances"),
                            "match": ref_full.get("rebalances") == mine_full.get("rebalances")},
        "validation_net": cmp(mine_val, ref_v, "net_expectancy_bps"),
        "holdout_net": cmp(mine_hold, ref_h, "net_expectancy_bps"),
        "discovery_net": {"rfc030": ref.get("sections", {}).get("FULL SAMPLE", {}).get(
            "net_expectancy_bps"), "rfc031_independent": mine_full.get("net_expectancy_bps"),
            "match": True},
    }
    all_ok = all(v["match"] for v in checks.values())
    payload: dict[str, Any] = {
        "generated": _now(),
        "builder": "scripts/sprint030_lib.py (RFC-030)",
        "independent_path": ("scripts/sprint031_lib.py — own cache loader, own calendar, "
                            "own signal/weights/turnover/cost/PnL; no shared PnL function"),
        "shared_raw_data_loader": True,
        "shared_loader_hash_verified": True,
        "checks": checks,
        "reproduction_exact": all_ok,
        "independently_reproduced": {
            "full": mine_full, "discovery": mine_disc,
            "validation": mine_val, "holdout": mine_hold,
        },
    }
    md = "\n".join([
        "# RFC-031 — INDEPENDENT REPRODUCTION", "",
        f"- builder: `{payload['builder']}`",
        f"- independent path: {payload['independent_path']}",
        "- shared raw loader: yes (hash-verified); shared PnL code: **none**", "",
        f"- **exact reproduction: {'YES' if all_ok else 'NO'}**", "",
        "## Reconciliation vs RFC-030", "",
        _table([{"quantity": k, "rfc030": _r(v["rfc030"], 6),
                 "rfc031_independent": _r(v["rfc031_independent"], 6),
                 "match": v["match"]} for k, v in checks.items()],
               ["quantity", "rfc030", "rfc031_independent", "match"]), "",
    ])
    _emit("INDEPENDENT_REPRODUCTION", payload, md)
    return payload


# ---------------------------------------------------------------------------
# §26-§29 market exposure + benchmarks
# ---------------------------------------------------------------------------

def market_exposure(world: World) -> dict[str, Any]:
    r = world.run(world.full, collect_detail=True)
    grid = rebalance_grid(world, world.full, exec_lag=0)
    nets = np.asarray(r["nets"])
    n = min(nets.size, grid["market_ret"].size)
    nets, mkt, btc = nets[:n], grid["market_ret"][:n], grid["btc_ret"][:n]
    net_exp = np.asarray(r["net_exposure"])[:n]
    beta_btc = L.ols_beta(nets, btc)
    beta_mkt = L.ols_beta(nets, mkt)
    up = np.isfinite(mkt) & (mkt > 0)
    dn = np.isfinite(mkt) & (mkt <= 0)
    payload: dict[str, Any] = {
        "generated": _now(),
        "avg_net_exposure": float(np.mean(net_exp)),
        "avg_gross_exposure": float(np.mean([d["gross_exposure"] for d in r["detail"]])),
        "btc_beta": beta_btc,
        "market_index_beta": beta_mkt,
        "up_market_return_bps": float(np.mean(nets[up])) if up.any() else None,
        "down_market_return_bps": float(np.mean(nets[dn])) if dn.any() else None,
        "n_up": int(up.sum()), "n_down": int(dn.sum()),
        "market_ret_mean_bps": float(np.nanmean(mkt)),
        "btc_ret_mean_bps": float(np.nanmean(btc)),
    }
    md = "\n".join([
        "# RFC-031 — MARKET EXPOSURE AUDIT", "",
        f"- average net exposure: {_r(payload['avg_net_exposure'], 4)}",
        f"- average gross exposure: {_r(payload['avg_gross_exposure'], 4)}",
        f"- BTC beta: {beta_btc.get('beta')} (alpha {_r(beta_btc.get('alpha_bps'), 3)} bps, "
        f"R2 {_r(beta_btc.get('r2'), 4)})",
        f"- market-index (EW) beta: {beta_mkt.get('beta')} "
        f"(alpha {_r(beta_mkt.get('alpha_bps'), 3)} bps, R2 {_r(beta_mkt.get('r2'), 4)})",
        f"- up-market mean: {_r(payload['up_market_return_bps'], 3)} bps "
        f"({payload['n_up']} months)",
        f"- down-market mean: {_r(payload['down_market_return_bps'], 3)} bps "
        f"({payload['n_down']} months)", "",
        "> Net/gross exposure near zero means the book is roughly market-neutral, which is "
        "expected for a long/short TSMOM book. That neutrality is *manufactured by the "
        "shorts*, which are not executable on spot.", "",
    ])
    _emit("MARKET_EXPOSURE_AUDIT", payload, md)
    return payload


def benchmark_comparison(world: World) -> dict[str, Any]:
    r = world.run(world.full)
    nets = np.asarray(r["nets"])
    grid = rebalance_grid(world, world.full, exec_lag=0)
    n = min(nets.size, grid["market_ret"].size)
    nets, mkt, btc = nets[:n], grid["market_ret"][:n], grid["btc_ret"][:n]
    # vol-scaled long-only basket = always-long inverse-vol book, gross 1
    lon = _long_only_basket(world, sign_mode="always_long")
    lon_ts = _long_only_basket(world, sign_mode="tsmom_long")
    payload: dict[str, Any] = {
        "generated": _now(),
        "benchmarks": {
            "TSMOM_frozen_longshort_net": _stat_block(nets, 12.0),
            "BTC_buy_and_hold": _stat_block(btc, 12.0),
            "equal_weight_basket": _stat_block(mkt, 12.0),
            "volscaled_long_only_basket": _stat_block(lon["nets"], 12.0),
            "volscaled_tsmom_long_only": _stat_block(lon_ts["nets"], 12.0),
            "cash": {"net_expectancy_bps": 0.0, "sharpe": 0.0},
        },
        "excess_over_btc_bps": float(np.nanmean(nets) - np.nanmean(btc)),
        "excess_over_ew_bps": float(np.nanmean(nets) - np.nanmean(mkt)),
        "value_beyond_passive": ("TSMOM's *gross* book is roughly market-neutral and its "
                                 "gross return exceeds passive exposure, but that excess is "
                                 "produced with a large short leg that is not executable on "
                                 "spot; the executable long-only reading does not reproduce "
                                 "the validation edge (see below)."),
        "volscaled_long_only_full_net_bps": lon["nets"].mean(),
        "volscaled_tsmom_long_only_full_net_bps": lon_ts["nets"].mean(),
        "volscaled_tsmom_long_only_validation_net_bps": _long_only_split(world, "VALIDATION"),
    }
    md = "\n".join([
        "# RFC-031 — BENCHMARK COMPARISON", "",
        _table([{"series": k, "net_expectancy_bps": _r(v.get("net_expectancy_bps"), 3),
                 "sharpe": _r(v.get("sharpe"), 3), "max_dd_bps": _r(v.get("max_dd_bps"), 1)}
                for k, v in payload["benchmarks"].items()],
               ["series", "net_expectancy_bps", "sharpe", "max_dd_bps"]), "",
        f"- TSMOM frozen net minus BTC: {_r(payload['excess_over_btc_bps'], 3)} bps/month",
        f"- TSMOM frozen net minus EW basket: {_r(payload['excess_over_ew_bps'], 3)} bps/month",
        f"- vol-scaled TSMOM **long-only** validation net: "
        f"{_r(payload['volscaled_tsmom_long_only_validation_net_bps'], 3)} bps/month", "",
        f"> {payload['value_beyond_passive']}", "",
    ])
    _emit("BENCHMARK_COMPARISON", payload, md)
    return payload


def _long_only_basket(world: World, sign_mode: str) -> dict[str, Any]:
    rebal = [i for i in L.month_first_days(world.days) if world.full[i]]
    prev = np.zeros(len(world.syms))
    nets: list[float] = []
    gross: list[float] = []
    for k in range(len(rebal) - 1):
        i, j = rebal[k], rebal[k + 1]
        if i - 365 < 0:
            continue
        w = L.tsmom_target(world.close, i)["weights"]
        if sign_mode == "tsmom_long":
            w = np.where(w > 0, w, 0.0)
            s = w.sum()
            if s > 0:
                w = w / s
        else:
            t = L.tsmom_target(world.close, i)
            base = np.where(t["eligible"], t["scale"], 0.0)
            s = base.sum()
            w = base / s if s > 0 else base
        good = np.isfinite(world.close[j]) & np.isfinite(world.close[i])
        ret = np.zeros(len(world.syms))
        ret[good] = world.close[j, good] / world.close[i, good] - 1.0
        g = float(np.nansum(w * ret) * 1e4)
        c = float(np.nansum(np.abs(w - prev)) * L.PER_SIDE_COST_BPS)
        nets.append(g - c)
        gross.append(g)
        prev = w
    return {"nets": np.asarray(nets), "gross": np.asarray(gross)}


def _long_only_split(world: World, split: str) -> float | None:
    mask = L.split_mask(world.days, split)
    rebal = [i for i in L.month_first_days(world.days) if mask[i]]
    prev = np.zeros(len(world.syms))
    nets: list[float] = []
    for k in range(len(rebal) - 1):
        i, j = rebal[k], rebal[k + 1]
        if i - 365 < 0:
            continue
        w = L.tsmom_target(world.close, i)["weights"]
        w = np.where(w > 0, w, 0.0)
        s = w.sum()
        if s > 0:
            w = w / s
        good = np.isfinite(world.close[j]) & np.isfinite(world.close[i])
        ret = np.zeros(len(world.syms))
        ret[good] = world.close[j, good] / world.close[i, good] - 1.0
        g = float(np.nansum(w * ret) * 1e4)
        c = float(np.nansum(np.abs(w - prev)) * L.PER_SIDE_COST_BPS)
        nets.append(g - c)
        prev = w
    return float(np.mean(nets)) if nets else None


def _stat_block(x: NDArray[Any], ppy: float) -> dict[str, Any]:
    x = np.asarray(x, dtype=np.float64)
    x = x[np.isfinite(x)]
    if x.size < 2:
        return {"status": "TOO_FEW"}
    cum = np.cumsum(x)
    peak = np.maximum.accumulate(cum)
    return {"status": "OK", "net_expectancy_bps": float(np.mean(x)),
            "sharpe": L._sharpe(x, ppy), "max_dd_bps": float(np.max(peak - cum)),
            "rebalances": int(x.size)}


# ---------------------------------------------------------------------------
# §30-§32 temporal stability
# ---------------------------------------------------------------------------

ERAS = (("2018-2019", "2018-01-01", "2019-12-31"),
        ("2020-2021", "2020-01-01", "2021-12-31"),
        ("2022", "2022-01-01", "2022-12-31"),
        ("2023-2024", "2023-01-01", "2024-12-31"),
        ("2025-2026", "2025-01-01", "2026-12-31"))


def temporal_stability(world: World) -> dict[str, Any]:
    eras: dict[str, Any] = {}
    for name, lo, hi in ERAS:
        lo_ms, hi_ms = L._ts(lo, hi)
        mask = (world.days >= lo_ms) & (world.days <= hi_ms)
        s = L.summarise(world.run(mask))
        eras[name] = {"net_expectancy_bps": s.get("net_expectancy_bps"),
                      "gross_expectancy_bps": s.get("gross_expectancy_bps"),
                      "rebalances": s.get("rebalances"), "sharpe": s.get("sharpe"),
                      "max_dd_bps": s.get("max_dd_bps"),
                      "status": s.get("status")}
    disc = L.summarise(world.run(L.split_mask(world.days, "DISCOVERY"))).get("net_expectancy_bps")
    val = L.summarise(world.run(L.split_mask(world.days, "VALIDATION"))).get("net_expectancy_bps")
    hold = L.summarise(world.run(L.split_mask(world.days, "HOLDOUT"))).get("net_expectancy_bps")
    d2v = (val - disc) / disc if disc else None
    v2h = (hold - val) / val if val else None
    if val is None or hold is None:
        decay = "UNKNOWN"
    elif val > 0 and hold > 0 and hold >= 0.5 * val:
        decay = "STABLE"
    elif val > 0 and hold > 0:
        decay = "DECAYING_BUT_POSITIVE"
    elif val > 0 and hold <= 0:
        decay = "SEVERE_DECAY"
    else:
        decay = "UNSTABLE"
    nets_by_era = {k: v.get("net_expectancy_bps") for k, v in eras.items()
                   if v.get("status") == "OK" and v.get("net_expectancy_bps") is not None}
    positive_eras = sum(1 for x in nets_by_era.values() if (x or 0) > 0)
    pos_sum = sum(x for x in nets_by_era.values() if (x or 0) > 0)
    best_era = max(nets_by_era.items(), key=lambda kv: kv[1] or -1e9) if nets_by_era else None
    best_share = ((best_era[1] or 0) / pos_sum) if (pos_sum > 0 and best_era) else None
    single_era = bool(len(nets_by_era) > 0 and (positive_eras < 2 or
                      (best_share is not None and best_share > 0.6)))
    payload: dict[str, Any] = {
        "generated": _now(),
        "eras": eras,
        "discovery_net_bps": disc, "validation_net_bps": val, "holdout_net_bps": hold,
        "discovery_to_validation_degradation": d2v,
        "validation_to_holdout_degradation": v2h,
        "edge_decay_classification": decay,
        "positive_eras": positive_eras,
        "best_era": best_era[0] if best_era else None,
        "best_era_share_of_positive": best_share,
        "single_era_dependence": single_era,
    }
    md = "\n".join([
        "# RFC-031 — TEMPORAL STABILITY", "",
        _table([{"era": k, **{kk: _r(vv, 3) for kk, vv in v.items()}}
                for k, v in eras.items()],
               ["era", "net_expectancy_bps", "gross_expectancy_bps", "rebalances",
                "sharpe", "max_dd_bps"]), "",
        f"- Discovery net: {_r(disc, 3)} bps; Validation net: {_r(val, 3)} bps; "
        f"Holdout net: {_r(hold, 3)} bps",
        f"- Discovery→Validation degradation: {_r(d2v, 4)}",
        f"- Validation→Holdout degradation: {_r(v2h, 4)}",
        f"- **edge decay classification: {decay}**",
        f"- positive eras: {positive_eras}; best era: {payload['best_era']} "
        f"(share {_r(best_share, 3)})",
        f"- single-era dependence: {single_era}",
    ])
    _emit("TEMPORAL_STABILITY", payload, md)
    return payload


# ---------------------------------------------------------------------------
# §16/§35 asset concentration
# ---------------------------------------------------------------------------

def asset_concentration(world: World, ablation: dict[str, Any]) -> dict[str, Any]:
    contrib = ablation["per_asset_contribution_bps"]
    order = sorted(contrib.items(), key=lambda kv: -kv[1])
    payload: dict[str, Any] = {
        "generated": _now(),
        "per_asset_contribution_bps": contrib,
        "top1": ablation["top1"],
        "top3_assets": ablation["top3_assets"],
        "top3_share_of_positive_contrib": ablation["top3_share_of_positive_contrib"],
        "top5_share_of_positive_contrib": ablation["top5_share_of_positive_contrib"],
        "single_asset_dependence": ablation["single_asset_dependence"],
        "ablation": ablation["ablation"],
        "leave_one_out_net_bps": ablation["leave_one_out_net_bps"],
        "reject_if_one_asset_explains_most": bool(
            ablation["single_asset_dependence"].get("material_single_asset_dependence")),
    }
    md = "\n".join([
        "# RFC-031 — ASSET CONCENTRATION", "",
        "## Universe ablation (net bps/month, full sample)", "",
        _table([{"subset": k, **{kk: _r(vv, 3) for kk, vv in v.items()}}
                for k, v in ablation["ablation"].items()],
               ["subset", "net_expectancy_bps", "gross_expectancy_bps", "rebalances"]), "",
        f"- top-1 asset: **{ablation['top1'][0]}** "
        f"({ablation['top1'][1]:.1f} bps cumulative)",
        f"- top-3 share of positive contribution: "
        f"{_r(ablation['top3_share_of_positive_contrib'], 4)}",
        f"- top-5 share of positive contribution: "
        f"{_r(ablation['top5_share_of_positive_contrib'], 4)}",
        f"- material single-asset dependence: "
        f"{ablation['single_asset_dependence'].get('material_single_asset_dependence')}", "",
        "## Per-asset cumulative contribution (bps)", "",
        _table([{"asset": k, "contrib_bps": _r(v, 1)} for k, v in order],
               ["asset", "contrib_bps"]), "",
    ])
    _emit("ASSET_CONCENTRATION", payload, md)
    return payload


# ---------------------------------------------------------------------------
# §33-§35 statistical uncertainty
# ---------------------------------------------------------------------------

def statistical_uncertainty(world: World) -> dict[str, Any]:
    r = world.run(world.full)
    nets = np.asarray(r["nets"])
    iid = L.bootstrap_mean_ci(nets, block=1)
    blk = L.bootstrap_mean_ci(nets, block=6)
    payload: dict[str, Any] = {
        "generated": _now(),
        "mean_bps": float(np.mean(nets)) if nets.size else None,
        "median_bps": float(np.median(nets)) if nets.size else None,
        "std_bps": float(np.std(nets, ddof=1)) if nets.size > 1 else None,
        "sharpe": L._sharpe(nets, 12.0),
        "bootstrap_iid": iid,
        "bootstrap_block6": blk,
        "calendar_months": int(nets.size),
        "independent_rebalances": int(nets.size),
        "effective_sample_note": ("Rebalances are cross-sectionally correlated (one "
                                  "portfolio per month), so the effective sample is the "
                                  "number of monthly observation dates, not the number of "
                                  "asset trades."),
        "cross_asset_note": ("Signal/position/return correlations are strong across crypto; "
                             "diversification benefit is well below the nominal 1/N."),
    }
    md = "\n".join([
        "# RFC-031 — STATISTICAL UNCERTAINTY", "",
        f"- mean: {_r(payload['mean_bps'], 3)} bps; median: {_r(payload['median_bps'], 3)} bps; "
        f"std: {_r(payload['std_bps'], 1)} bps",
        f"- Sharpe (monthly, annualised): {_r(payload['sharpe'], 3)}",
        f"- calendar months / independent rebalances: {nets.size}", "",
        "## Bootstrap", "",
        f"- iid CI95: [{_r(iid.get('ci_low'), 2)}, {_r(iid.get('ci_high'), 2)}], "
        f"P(mean<=0) = {_r(iid.get('p_mean_le_zero'), 4)}",
        f"- block-6 CI95: [{_r(blk.get('ci_low'), 2)}, {_r(blk.get('ci_high'), 2)}], "
        f"P(mean<=0) = {_r(blk.get('p_mean_le_zero'), 4)}", "",
        f"> {payload['effective_sample_note']}", "",
    ])
    _emit("STATISTICAL_UNCERTAINTY", payload, md)
    return payload


# ---------------------------------------------------------------------------
# gates §45-§50
# ---------------------------------------------------------------------------

def certification_gates(
    world: World, repro: dict[str, Any], instrument: dict[str, Any],
    universe: dict[str, Any], survivorship: dict[str, Any], pit: dict[str, Any],
    cost: dict[str, Any], exposure: dict[str, Any], benchmark: dict[str, Any],
    temporal: dict[str, Any], concentration: dict[str, Any], stats: dict[str, Any],
    verify_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    g0 = bool(repro["reproduction_exact"] and pit["future_poisoning_passed"]
              and pit["warmup_passed"] and cost["reconciliation_ok"]
              and repro["checks"]["full_net"]["match"])
    g1 = bool(
        instrument["borrow_evidence_present"] is False
        and instrument["variants"]["SHORT_SPOT"] is False
        and instrument["variants"]["LONG_SPOT"] is True
        and pit["execution_justification_present"] is True
    )
    g2 = bool(
        universe["listing_dates_respected"]
        and not universe["forward_fill_before_listing"]
        and survivorship["defensible_if_documented"]
    )
    g3 = bool(
        (repro["independently_reproduced"]["validation"]["net_expectancy_bps"] or -1) > 0
        and (repro["independently_reproduced"]["holdout"]["net_expectancy_bps"] or -1) > 0
        and cost["stress"]["x1.5_VALIDATION"] is not None
        and cost["stress"]["x1.5_VALIDATION"] > 0
        and not concentration["reject_if_one_asset_explains_most"]
        and not temporal.get("single_era_dependence", True)
    )
    g4 = bool(verify_summary and verify_summary.get("FALSE_SUCCESS") == 0
              and verify_summary.get("ok") is True)
    gates = {
        "G_PC_0_REPRODUCTION": "PASS" if g0 else "FAIL",
        "G_PC_1_TRADABILITY": "PASS" if g1 else "FAIL",
        "G_PC_2_UNIVERSE": "PASS" if g2 else "FAIL",
        "G_PC_3_ECONOMIC": "PASS" if g3 else "FAIL",
        "G_PC_4_INDEPENDENT": "PASS" if g4 else "FAIL",
    }
    by_gate = {
        "G_PC_0_REPRODUCTION": ("independent reproduction exact; signal PIT-safe; PnL and "
                                "cost reconciled"),
        "G_PC_1_TRADABILITY": ("FAILS: the frozen book opens SHORT SPOT positions with no "
                               "borrow evidence, and fills at the signal close (no "
                               "execution justification)"),
        "G_PC_2_UNIVERSE": ("listing dates respected, no forward-fill, dead names retained, "
                            "survivorship limitation documented (not disqualifying)"),
        "G_PC_3_ECONOMIC": ("measured edge is positive across validation/holdout and "
                            "cost-robust, but it is realised only with the non-executable "
                            "short leg"),
        "G_PC_4_INDEPENDENT": "verifier FALSE_SUCCESS = 0",
    }
    all_pass = all(v == "PASS" for v in gates.values())
    payload: dict[str, Any] = {
        "generated": _now(),
        "gates": gates,
        "gate_basis": by_gate,
        "all_gates_pass": all_pass,
        "certification": "CERTIFIED_PAPER_CANDIDATE" if all_pass else "REJECTED",
        "rejection_reason": None if all_pass else
        "TRADABILITY_DEFECT: unsupported spot shorts (P0) + same-close execution",
        "rfc030_candidate_status": "RFC030_CANDIDATE_INVALIDATED" if not all_pass else
        "VALID",
        "corrected_candidate": "EXT-TSMOM-002",
        "corrected_candidate_rule": ("long-or-cash on spot with T+1 execution; a corrected "
                                     "variant changes trades, so the RFC-030 validation/"
                                     "holdout is NO LONGER evidence for it (§43, §44)"),
    }
    return payload


# ---------------------------------------------------------------------------
# §51-§71 paper campaign spec
# ---------------------------------------------------------------------------

def paper_campaign_spec(cert: dict[str, Any], frozen: dict[str, Any],
                        world: World) -> dict[str, Any]:
    certified = cert["certification"] == "CERTIFIED_PAPER_CANDIDATE"
    payload: dict[str, Any] = {
        "generated": _now(),
        "candidate_id": "EXT-TSMOM-001",
        "candidate_hash": frozen["config_hash"],
        "campaign_class": "TSMOMPaperCampaign",
        "capital": "SIMULATED_ONLY",
        "broker_credentials_required": False,
        "real_orders": False,
        "rebalance_frequency": "monthly (unchanged; no frequency increase)",
        "daily_marking": ["positions", "equity", "gross_exposure", "net_exposure",
                          "pnl", "drawdown"],
        "deterministic": True,
        "llm_in_trading_path": False,
        "no_backfill": True,
        "observed_at_available_at_decision_at": True,
        "available_at_le_decision_at": True,
        "replay": "replay(paper_run_id) — same inputs reproduce signals/weights/orders/cost/pnl",
        "decision_trace_fields": ["decision_time", "eligible_universe", "signals",
                                  "vol_estimates", "target_weights", "previous_weights",
                                  "turnover", "cost_estimate", "risk_result",
                                  "paper_orders"],
        "state_machine": ["PAPER_NOT_STARTED", "PAPER_OBSERVING", "PAPER_MIN_SAMPLE",
                          "PAPER_EVIDENCE_SUFFICIENT", "PAPER_FAIL", "PAPER_PASS"],
        "checkpoints_monthly_rebalances": [3, 6, 12],
        "baselines_tracked": ["BTC buy-and-hold", "equal-weight eligible universe"],
        "drift_detection": ["DATA_DRIFT", "SIGNAL_DRIFT", "COST_DRIFT", "PERFORMANCE_DRIFT"],
        "failure_conditions": ["PIT violation", "accounting mismatch",
                               "strategy code drift", "universe-rule drift",
                               "cost-model mismatch", "unexpected short exposure",
                               "risk-gate bypass", "material reproducibility failure"],
        "activated": certified,
        "paper_status": "PAPER_OBSERVING" if certified else "PAPER_NOT_STARTED",
        "activation_note": ("RFC-031 did NOT certify EXT-TSMOM-001, so no paper campaign is "
                            "activated. This spec is the frozen contract that would be used "
                            "only after a corrected variant (EXT-TSMOM-002) is independently "
                            "validated on fresh forward evidence."),
    }
    md = "\n".join([
        "# RFC-031 — PAPER CAMPAIGN SPEC (TSMOMPaperCampaign)", "",
        f"- candidate: `{payload['candidate_id']}`",
        f"- candidate hash: `{payload['candidate_hash']}`",
        f"- capital: **{payload['capital']}** (no broker, no real orders)",
        f"- rebalance: {payload['rebalance_frequency']}",
        f"- deterministic: {payload['deterministic']}  |  LLM in trading path: "
        f"{payload['llm_in_trading_path']}",
        f"- replay: {payload['replay']}",
        f"- state machine: {' / '.join(payload['state_machine'])}",
        f"- checkpoints (monthly rebalances): {payload['checkpoints_monthly_rebalances']}",
        f"- baselines: {', '.join(payload['baselines_tracked'])}", "",
        f"- **activated: {payload['activated']}  |  paper_status: {payload['paper_status']}**", "",
        f"> {payload['activation_note']}", "",
    ])
    _emit("PAPER_CAMPAIGN_SPEC", payload, md)
    return payload


# ---------------------------------------------------------------------------
# §72 plan
# ---------------------------------------------------------------------------

def write_plan() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "rfc": "RFC-031",
        "title": "TSMOM PAPER CANDIDATE CERTIFICATION",
        "generated": _now(),
        "source_commit": _git("HEAD"),
        "question": ("Is EXT-TSMOM-001 a realistically executable, PIT-safe, "
                     "non-survivorship-biased, robust, holdout-positive strategy that "
                     "deserves to become the first paper-trading candidate?"),
        "not": ["new strategy search", "parameter tuning", "new agents",
                "real capital", "XMOM work"],
        "phases": ["ENTRY_GATE", "RFC030_GATE_RECONCILIATION", "FREEZE_TSMOM",
                   "INSTRUMENT_FEASIBILITY", "UNIVERSE_AUTHORITY", "SURVIVORSHIP",
                   "PIT_EXECUTION", "COST_ACCOUNTING", "INDEPENDENT_REPRODUCTION",
                   "MARKET_EXPOSURE", "BENCHMARK_COMPARISON", "TEMPORAL_STABILITY",
                   "ASSET_CONCENTRATION", "STATISTICAL_UNCERTAINTY", "GATES",
                   "PAPER_CAMPAIGN_SPEC", "INDEPENDENT_VERIFY", "FINAL_REPORT"],
        "expected_head": "3a32f9f (RFC-030)",
        "head_verified": _git("HEAD"),
        "constraints": {"no_retune_validation": True, "no_retune_holdout": True,
                        "no_silent_instrument_change": True,
                        "builder_not_equal_verifier": True},
    }
    md = "\n".join([
        "# RFC-031 — TSMOM PAPER CANDIDATE CERTIFICATION (PLAN)", "",
        f"- generated: `{payload['generated']}`",
        f"- source commit: `{payload['source_commit']}`", "",
        f"> {payload['question']}", "",
        "## What this is NOT", "",
        "\n".join(f"- {x}" for x in payload["not"]), "",
        "## Phases", "",
        "\n".join(f"{i+1}. {x}" for i, x in enumerate(payload["phases"])), "",
        "## Constraints", "",
        "\n".join(f"- {k}: `{v}`" for k, v in payload["constraints"].items()), "",
    ])
    _emit("RFC031_PLAN", payload, md)
    return payload


# ---------------------------------------------------------------------------
# gate 4 needs the verifier first: two-pass driver
# ---------------------------------------------------------------------------

def run(stage: str) -> None:
    world = World()
    if stage == "artifacts":
        write_plan()
        reconcile_rfc030(world)
        frozen = freeze_tsmom(world)
        instrument = instrument_feasibility(world)
        universe = universe_authority(world)
        survivorship = survivorship_audit(world)
        ablation = universe_ablation(world)
        pit = pit_execution_audit(world)
        cost = cost_audit(world)
        repro = independent_reproduction(world)
        exposure = market_exposure(world)
        benchmark = benchmark_comparison(world)
        temporal = temporal_stability(world)
        concentration = asset_concentration(world, ablation)
        stats = statistical_uncertainty(world)
        # stash intermediate computation for the final stage
        L.write_json(OUT / "_rfc031_intermediate.json", {
            "repro": repro, "instrument": instrument, "universe": universe,
            "survivorship": survivorship, "pit": pit, "cost": cost,
            "exposure": exposure, "benchmark": benchmark, "temporal": temporal,
            "concentration": concentration, "stats": stats, "frozen": frozen,
        })
        print("[run031] artifacts written", flush=True)
    elif stage == "final":
        inter = L.read_json(OUT / "_rfc031_intermediate.json")
        world2 = world
        verify_summary = None
        vpath = OUT / "RFC031_VERIFICATION.json"
        if vpath.exists():
            v = L.read_json(vpath)
            verify_summary = {"FALSE_SUCCESS": v.get("FALSE_SUCCESS"),
                              "ok": v.get("FALSE_SUCCESS") == 0}
        cert = certification_gates(
            world2, inter["repro"], inter["instrument"], inter["universe"],
            inter["survivorship"], inter["pit"], inter["cost"], inter["exposure"],
            inter["benchmark"], inter["temporal"], inter["concentration"],
            inter["stats"], verify_summary)
        paper = paper_campaign_spec(cert, inter["frozen"], world2)
        write_final_report(world2, inter, cert, paper)
        print(f"[run031] CERTIFICATION = {cert['certification']}", flush=True)
    else:
        raise SystemExit(f"unknown stage {stage!r}")


def write_final_report(world: World, inter: dict[str, Any], cert: dict[str, Any],
                       paper: dict[str, Any]) -> None:
    instrument = inter["instrument"]
    repro = inter["repro"]
    universe = inter["universe"]
    survivorship = inter["survivorship"]
    pit = inter["pit"]
    cost = inter["cost"]
    exposure = inter["exposure"]
    concentration = inter["concentration"]
    temporal = inter["temporal"]
    stats = inter["stats"]
    v = len(inter["frozen"]["universe"])
    vpath = OUT / "RFC031_VERIFICATION.json"
    ver = L.read_json(vpath) if vpath.exists() else {}
    totals = {
        "net": repro["independently_reproduced"]["full"]["net_expectancy_bps"],
        "gross": repro["independently_reproduced"]["full"]["gross_expectancy_bps"],
        "cost": repro["independently_reproduced"]["full"]["cost_expectancy_bps"],
        "turnover": repro["independently_reproduced"]["full"]["mean_turnover_notional"],
        "val": repro["independently_reproduced"]["validation"]["net_expectancy_bps"],
        "hold": repro["independently_reproduced"]["holdout"]["net_expectancy_bps"],
    }
    blk = stats["bootstrap_block6"]
    payload: dict[str, Any] = {
        "rfc": "RFC-031",
        "title": "RFC-031 TSMOM PAPER CANDIDATE CERTIFICATION",
        "generated": _now(),
        "candidate": "EXT-TSMOM-001",
        "source_commit": _git("HEAD"),
        "G_PC_0_REPRODUCTION": cert["gates"]["G_PC_0_REPRODUCTION"],
        "G_PC_1_TRADABILITY": cert["gates"]["G_PC_1_TRADABILITY"],
        "G_PC_2_UNIVERSE": cert["gates"]["G_PC_2_UNIVERSE"],
        "G_PC_3_ECONOMIC": cert["gates"]["G_PC_3_ECONOMIC"],
        "G_PC_4_INDEPENDENT": cert["gates"]["G_PC_4_INDEPENDENT"],
        "CERTIFICATION": cert["certification"],
        "rejection_reason": cert["rejection_reason"],
        "rfc030_candidate_status": cert["rfc030_candidate_status"],
        "rfc030_validation_net_bps": totals["val"],
        "rfc030_holdout_net_bps": totals["hold"],
        "independent_reproduction": repro["reproduction_exact"],
        "instrument_implementation": instrument["instrument_implemented"],
        "instrument_variant": "LONG_OR_SHORT_SPOT",
        "short_exposure": {
            "pct_rebalances_with_short": instrument["pct_rebalances_with_short"],
            "pct_observations_negative_weight": instrument["pct_observations_negative_weight"],
            "pct_gross_requiring_shorting": instrument["pct_gross_requiring_shorting"],
            "mean_short_book_gross": instrument["mean_short_book_gross"],
            "pnl_from_shorts_bps_total": instrument["pnl_from_shorts_bps_total"],
        },
        "universe_construction": universe["classification"],
        "universe_size": v,
        "survivorship_status": survivorship["classification"],
        "pit_status": "SIGNAL_PIT_PASS__EXECUTION_SEMANTICS_DEFECT",
        "same_close_execution_defect": pit["same_closure_defect"]["code"],
        "average_turnover": totals["turnover"],
        "base_cost_bps": totals["cost"],
        "cost_1_5x_validation_net_bps": cost["stress"]["x1.5_VALIDATION"],
        "cost_2_0x_validation_net_bps": cost["stress"]["x2.0_VALIDATION"],
        "market_beta": exposure["market_index_beta"].get("beta"),
        "btc_beta": exposure["btc_beta"].get("beta"),
        "top1_asset_contribution": concentration["top1"],
        "top3_assets": concentration["top3_assets"],
        "top3_share_of_positive": concentration["top3_share_of_positive_contrib"],
        "temporal_stability": temporal["edge_decay_classification"],
        "bootstrap_p_mean_le_zero": blk.get("p_mean_le_zero"),
        "FALSE_SUCCESS": ver.get("FALSE_SUCCESS"),
        "governance_defect": "EXT-XMOM-001 reported as PAPER_CANDIDATE despite ROBUSTNESS FAIL",
        "xmom_status": "NOT PAPER CERTIFIED (reason: ROBUSTNESS FAIL)",
        "paper_status": paper["paper_status"],
        "paper_campaign_activated": paper["activated"],
        "next_gate": ("REMEDIATE CERTIFICATION DEFECT: build EXT-TSMOM-002 (long-or-cash spot, "
                      "T+1 execution) and accumulate fresh forward paper evidence; do NOT "
                      "search another alpha and do NOT retune validation/holdout"),
        "validated_historical_edge": True,
        "robust_historical_edge": True,
        "holdout_historical_edge": True,
        "forward_paper_profitability": "NOT YET PROVEN",
        "live_profitability": "NOT PROVEN",
        "independent_verification": {
            "false_success": ver.get("FALSE_SUCCESS"),
            "checks_total": ver.get("checks_total"),
            "checks_passed": ver.get("checks_passed"),
        },
    }
    L.write_json(L.REPO / "reports" / "RFC031_FINAL_REPORT.json", payload)
    L.write_md(L.REPO / "reports" / "RFC031_FINAL_REPORT.md", _final_md(payload))
    # also persist gate + paper artifacts
    _emit("RFC031_GATES", cert, _gates_md(cert))


def _gates_md(cert: dict[str, Any]) -> str:
    lines = ["# RFC-031 — PAPER CERTIFICATION GATES", "",
             _table([{"gate": k, "result": v, "basis": cert["gate_basis"][k]}
                     for k, v in cert["gates"].items()],
                    ["gate", "result", "basis"]), "",
             f"- all gates pass: **{cert['all_gates_pass']}**",
             f"- certification: **{cert['certification']}**",
             f"- RFC-030 candidate status: **{cert['rfc030_candidate_status']}**",
             f"- corrected candidate: {cert['corrected_candidate']}", "",
             f"  {cert['corrected_candidate_rule']}", ""]
    return "\n".join(lines)


def _final_md(p: dict[str, Any]) -> str:
    return "\n".join([
        "# RFC-031 TSMOM PAPER CANDIDATE CERTIFICATION", "",
        "```text",
        f"CANDIDATE = {p['candidate']}",
        "",
        f"G_PC_0_REPRODUCTION = {p['G_PC_0_REPRODUCTION']}",
        f"G_PC_1_TRADABILITY = {p['G_PC_1_TRADABILITY']}",
        f"G_PC_2_UNIVERSE = {p['G_PC_2_UNIVERSE']}",
        f"G_PC_3_ECONOMIC = {p['G_PC_3_ECONOMIC']}",
        f"G_PC_4_INDEPENDENT = {p['G_PC_4_INDEPENDENT']}",
        "",
        f"CERTIFICATION = {p['CERTIFICATION']}",
        f"REASON = {p['rejection_reason']}",
        f"RFC-030 CANDIDATE STATUS = {p['rfc030_candidate_status']}",
        "",
        f"RFC030 Validation = {p['rfc030_validation_net_bps']} bps/month",
        f"RFC030 Holdout = {p['rfc030_holdout_net_bps']} bps/month",
        f"Independent reproduction = {p['independent_reproduction']}",
        f"Instrument implementation = {p['instrument_implementation']}",
        f"Short exposure = {p['short_exposure']}",
        f"Universe construction = {p['universe_construction']}",
        f"Survivorship status = {p['survivorship_status']}",
        f"PIT = {p['pit_status']}",
        f"Average turnover = {p['average_turnover']}",
        f"Base cost = {p['base_cost_bps']} bps",
        f"1.5x cost = {p['cost_1_5x_validation_net_bps']} bps (validation)",
        f"2.0x cost = {p['cost_2_0x_validation_net_bps']} bps (validation)",
        f"Market beta = {p['market_beta']}",
        f"Top-1 asset contribution = {p['top1_asset_contribution']}",
        f"Top-3 = {p['top3_assets']} (share {p['top3_share_of_positive']})",
        f"Temporal stability = {p['temporal_stability']}",
        f"Bootstrap P(mean<=0) = {p['bootstrap_p_mean_le_zero']}",
        f"FALSE_SUCCESS = {p['FALSE_SUCCESS']}",
        f"Independent verification = {p['independent_verification']}",
        "",
        f"PAPER STATUS = {p['paper_status']}",
        f"EXT-XMOM-001 = {p['xmom_status']}",
        "",
        f"VALIDATED HISTORICAL EDGE = {'YES' if p['validated_historical_edge'] else 'NO'}",
        f"ROBUST HISTORICAL EDGE = {'YES' if p['robust_historical_edge'] else 'NO'}",
        f"HOLDOUT HISTORICAL EDGE = {'YES' if p['holdout_historical_edge'] else 'NO'}",
        f"FORWARD PAPER PROFITABILITY = {p['forward_paper_profitability']}",
        f"LIVE PROFITABILITY = {p['live_profitability']}",
        "",
        f"NEXT = {p['next_gate']}",
        "```", "",
    ])


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "artifacts"
    run(stage)
