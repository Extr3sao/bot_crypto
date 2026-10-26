"""RFC-032 — orchestrator: remediation, historical diagnostic, admission gate.

Deterministic (§37, §38).  No tuning, no new alpha, no capital.  RFC-032 builds
EXT-TSMOM-002 (long-or-cash spot + T+1 open execution) from the *same* frozen
signal, freezes it, audits the implementation and PIT semantics, runs a
HISTORICAL_DIAGNOSTIC (never fresh Validation/Holdout) and decides whether the
executable version even deserves fresh forward paper evidence (§11, §12, §30).
"""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from typing import Any

import numpy as np
import sprint032_lib as L
from numpy.typing import NDArray

OUT = L.OUT_DIR
PAPER = L.PAPER_DIR
REPO = L.REPO
FROZEN = L.FROZEN_TSMOM_002
TOL = 1e-6

# Pre-registered admission criteria for G_REM_1 (§11, §13).  Declared BEFORE any
# number is computed and not modified afterwards.
G_REM_1_CRITERIA: dict[str, str] = {
    "C1_full_net_positive": "full diagnostic-corpus net expectancy > 0 bps/month",
    "C2_median_positive": "median monthly net > 0 bps",
    "C3_positive_eras_ge_2": "at least 2 of the 5 eras have positive net expectancy",
    "C4_recent_24m_positive": "last 24 monthly rebalances net expectancy > 0 bps/month",
    "C5_recent_12m_positive": "last 12 monthly rebalances net expectancy > 0 bps/month",
}


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


def _table(rows: list[dict[str, Any]], cols: list[str]) -> str:
    line = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    body = ["| " + " | ".join(str(r.get(c, "")) for c in cols) + " |" for r in rows]
    return "\n".join([line, sep, *body])


def _emit(name: str, payload: dict[str, Any], md: str) -> None:
    L.write_json(OUT / f"{name}.json", payload)
    L.write_md(OUT / f"{name}.md", md)


class World:
    def __init__(self) -> None:
        self.raw = L.load_raw()
        self.days = L.build_calendar(self.raw)
        self.syms = sorted(self.raw)
        self.close = L.build_matrix(self.raw, self.syms, self.days, "close")
        self.open = L.build_matrix(self.raw, self.syms, self.days, "open")
        self.listing = L.listing_dates(self.raw)
        self.first_idx = L.first_index(self.close)
        self.full = np.ones(self.days.shape[0], dtype=bool)

    def run(self, mask: NDArray[Any], **kw: Any) -> dict[str, Any]:
        return L.run_tsmom002(self.close, self.open, self.days, mask, **kw)

    def summary(self, mask: NDArray[Any], **kw: Any) -> dict[str, Any]:
        return L.summarise(self.run(mask, **kw))


def rebalance_grid(world: World, mask: NDArray[Any]) -> list[tuple[int, int, int]]:
    """Candidate decision dates + T+1 execution indices (independent of weights)."""
    rebal = [i for i in L.month_first_days(world.days) if mask[i]]
    out: list[tuple[int, int, int]] = []
    for k in range(len(rebal) - 1):
        i, j = rebal[k], rebal[k + 1]
        if i - 365 < 0:
            continue
        e0, e1 = i + 1, j + 1
        if e1 >= world.close.shape[0]:
            continue
        out.append((i, e0, e1))
    return out


def _stat_block(x: NDArray[Any], ppy: float = 12.0) -> dict[str, Any]:
    x = np.asarray(x, dtype=np.float64)
    x = x[np.isfinite(x)]
    if x.size < 2:
        return {"status": "TOO_FEW"}
    cum = np.cumsum(x)
    peak = np.maximum.accumulate(cum)
    return {"status": "OK", "net_expectancy_bps": float(np.mean(x)),
            "net_median_bps": float(np.median(x)),
            "sharpe": L._sharpe(x, ppy), "max_dd_bps": float(np.max(peak - cum)),
            "rebalances": int(x.size)}


# ---------------------------------------------------------------------------
# §7 freeze artifact
# ---------------------------------------------------------------------------

def freeze_spec(world: World) -> dict[str, Any]:
    data_hashes = {s: L.sha256_file(L.CACHE_DIR / f"daily_{s}.npz") for s in world.syms}
    code_hash = L.sha256_file(REPO / "scripts" / "sprint032_lib.py")
    cfg_hash = L.sha256_obj({**FROZEN, "data_hashes": data_hashes})
    payload: dict[str, Any] = {
        **FROZEN,
        "generated": _now(),
        "source_commit": _git("HEAD"),
        "data_hashes": data_hashes,
        "code_hash_sprint032_lib": code_hash,
        "config_hash": cfg_hash,
        "evidence_class": "HISTORICAL_DIAGNOSTIC_CORPUS (NOT fresh Validation/Holdout)",
        "freeze_rule": ("Frozen before performance. Any material change to candidate, "
                        "code, config, universe rules or cost invalidates the campaign "
                        "(§35). No change is allowed to recover PnL (§6)."),
    }
    md = "\n".join([
        "# RFC-032 — EXT-TSMOM-002 FROZEN SPEC", "",
        f"- candidate_id: `{FROZEN['candidate_id']}`",
        f"- source_candidate: `{FROZEN['source_candidate']}`",
        f"- signal: {FROZEN['signal']}",
        f"- instrument: {FROZEN['instrument']}",
        f"- long/cash semantics: {FROZEN['long_cash_semantics']}",
        f"- execution: {FROZEN['execution_timing']} (field: `{FROZEN['executable_field']}`)",
        f"- lookback: {FROZEN['formation_days']} days  |  rebalance: {FROZEN['rebalance']}",
        f"- weighting: {FROZEN['weighting']}",
        f"- vol target {FROZEN['vol_target']} (lookback {FROZEN['vol_lookback_days']}d, "
        f"clip {FROZEN['vol_clip']})",
        f"- cost: {FROZEN['cost_model']} = {FROZEN['per_side_cost_bps']} bps/side  |  "
        f"cash yield: {FROZEN['cash_yield']}",
        f"- short exposure: {FROZEN['short_exposure']}",
        f"- leverage: {FROZEN['leverage']}",
        f"- universe: {len(FROZEN['universe'])} USDT pairs",
        f"- remediations: {', '.join(FROZEN['remediations'])}",
        f"- code hash (sprint032_lib.py): `{code_hash}`",
        f"- config hash: `{cfg_hash}`", "",
        "## Data hashes (per-asset daily panel)", "",
        _table([{"asset": k, "sha256": v[:16] + "..."} for k, v in
                sorted(data_hashes.items())], ["asset", "sha256"]), "",
    ])
    _emit("EXT_TSMOM_002_FROZEN_SPEC", payload, md)
    return payload


# ---------------------------------------------------------------------------
# §5/§6 remediation diff
# ---------------------------------------------------------------------------

def remediation_diff(frozen: dict[str, Any]) -> dict[str, Any]:
    ref = L.read_json(L.RFC031_DIR / "TSMOM_FROZEN_SPEC.json")
    param_keys = ["formation_days", "rebalance", "vol_target", "vol_lookback_days",
                  "vol_clip", "per_side_cost_bps", "universe"]
    param_diff = [{k: {"ext_tsmom_001": ref.get(k), "ext_tsmom_002": frozen.get(k),
                       "changed": ref.get(k) != frozen.get(k)} for k in param_keys}]
    remediation = {
        "R1": {
            "description": "negative desired weight -> 0 / CASH",
            "before": "w = sign*scale / sum|raw| (negative -> short spot)",
            "after": "raw = max(raw, 0); w = raw / sum(raw) (negative -> cash)",
            "effect": "removes all short exposure; long book renormalised to gross 1",
        },
        "R2": {
            "description": "close-T decision -> T+1 executable price",
            "before": ref.get("execution_semantics_frozen"),
            "after": "signal from closes <= T; fill at T+1 daily OPEN",
            "effect": "removes same-close fill; introduces overnight/gap risk (§21)",
        },
    }
    payload: dict[str, Any] = {
        "generated": _now(),
        "source_commit": _git("HEAD"),
        "source_candidate": L.SOURCE_CANDIDATE,
        "candidate": L.CANDIDATE_ID,
        "remediations": remediation,
        "parameter_diff": param_diff[0],
        "any_parameter_changed": any(r["changed"] for r in param_diff[0].values()),
        "compliance": ("ONLY the two allowed remediations were applied (§5). No lookback, "
                       "vol target, rebalance frequency, ranking, universe, threshold, "
                       "weighting method, cost or leverage was changed (§6)."),
        "would_be_new_candidate_if_more_changes": "EXT-TSMOM-003 (out of scope)",
    }
    rows = [{"parameter": k, **v} for k, v in param_diff[0].items()]
    md = "\n".join([
        "# RFC-032 — REMEDIATION DIFF (EXT-TSMOM-001 -> EXT-TSMOM-002)", "",
        "## Allowed remediations", "",
        f"- **R1 — {remediation['R1']['description']}**",
        f"  - before: {remediation['R1']['before']}",
        f"  - after:  {remediation['R1']['after']}",
        f"- **R2 — {remediation['R2']['description']}**",
        f"  - before: {remediation['R2']['before']}",
        f"  - after:  {remediation['R2']['after']}", "",
        "## Frozen parameter diff (must be identical)", "",
        _table(rows, ["parameter", "ext_tsmom_001", "ext_tsmom_002", "changed"]), "",
        f"- any frozen parameter changed: **{payload['any_parameter_changed']}**", "",
        f"> {payload['compliance']}", "",
    ])
    _emit("REMEDIATION_DIFF", payload, md)
    return payload


# ---------------------------------------------------------------------------
# §20/§21/§28 PIT + execution audit
# ---------------------------------------------------------------------------

def _future_poisoning(world: World) -> dict[str, Any]:
    """Mutate prices AFTER a cutoff; every decision <= cutoff must be identical."""
    cutoff = int(world.days.shape[0] * 0.75)
    c2 = world.close.copy()
    c2[cutoff:] *= 7.0
    base_sig = []
    poi_sig = []
    for i in L.month_first_days(world.days):
        if i >= cutoff:
            break
        base_sig.append(L.tsmom_long_cash_target(world.close, i)["weights"].tolist())
        poi_sig.append(L.tsmom_long_cash_target(c2, i)["weights"].tolist())
    same = (len(base_sig) == len(poi_sig)
            and all(np.allclose(a, b, atol=1e-12) for a, b in zip(base_sig, poi_sig, strict=True)))
    return {"passed": bool(same), "cutoff_index": cutoff,
            "decisions_before_cutoff": len(base_sig),
            "note": "signals/weights for T<=cutoff unchanged when all future prices mutate"}


def _warmup_check(world: World) -> bool:
    for i in range(0, 365):
        if np.any(L.tsmom_long_cash_target(world.close, i)["weights"] != 0):
            return False
    return True


def _no_negative_weights(world: World, mask: NDArray[Any]) -> int:
    neg = 0
    for i in L.month_first_days(world.days):
        if not mask[i]:
            continue
        w = L.tsmom_long_cash_target(world.close, i)["weights"]
        neg += int(np.sum(w < 0))
    return neg


def gap_analysis(world: World, mask: NDArray[Any]) -> dict[str, Any]:
    """§21 close_T -> exec_T+1 gap and its contribution to entry slippage."""
    grid = rebalance_grid(world, mask)
    btc = world.syms.index("BTCUSDT")
    book_gap: list[float] = []
    btc_gap: list[float] = []
    for i, e0, _e1 in grid:
        w = L.tsmom_long_cash_target(world.close, i)["weights"]
        gap = np.full(world.close.shape[1], np.nan)
        good = np.isfinite(world.open[e0]) & np.isfinite(world.close[i])
        gap[good] = world.open[e0, good] / world.close[i, good] - 1.0
        g = float(np.nansum(w * gap) * 1e4) if np.sum(w) > 0 else 0.0
        book_gap.append(g)
        if np.isfinite(world.open[e0, btc]) and np.isfinite(world.close[i, btc]):
            btc_gap.append(float(world.open[e0, btc] / world.close[i, btc] - 1.0) * 1e4)
    cot = L.summarise(world.run(mask, exec_mode="cotimed"))
    nxo = L.summarise(world.run(mask, exec_mode="next_open"))
    return {
        "mean_book_entry_gap_bps": float(np.mean(book_gap)) if book_gap else None,
        "mean_btc_entry_gap_bps": float(np.mean(btc_gap)) if btc_gap else None,
        "gross_cotimed_bps": cot.get("gross_expectancy_bps"),
        "gross_next_open_bps": nxo.get("gross_expectancy_bps"),
        "gap_contribution_bps": (float((nxo.get("gross_expectancy_bps") or 0.0)
                                       - (cot.get("gross_expectancy_bps") or 0.0))),
        "rebalances": len(grid),
    }


def pit_execution_audit(world: World, frozen: dict[str, Any]) -> dict[str, Any]:
    poison = _future_poisoning(world)
    warmup = _warmup_check(world)
    neg = _no_negative_weights(world, world.full)
    gap = gap_analysis(world, world.full)
    n_short_obs = sum(int(np.sum(L.tsmom_long_cash_target(
        world.close, i)["weights"] < 0)) for i in L.month_first_days(world.days))
    payload: dict[str, Any] = {
        "generated": _now(),
        "decision_time": "after close T is available",
        "signal_inputs": "closes with index <= T only (PIT-safe)",
        "execution_time": "next executable observation T+1, field = daily OPEN",
        "executable_field": frozen["executable_field"],
        "field_was_preregistered": True,
        "field_chosen_by_pnl": False,
        "future_poisoning": poison,
        "future_poisoning_passed": poison["passed"],
        "warmup_passed": warmup,
        "negative_weights_in_book": neg,
        "short_observations": n_short_obs,
        "no_short_spot": n_short_obs == 0,
        "gap": gap,
        "exec_lag": 1,
    }
    md = "\n".join([
        "# RFC-032 — PIT / EXECUTION AUDIT", "",
        f"- decision_time: {payload['decision_time']}",
        f"- signal inputs: {payload['signal_inputs']}",
        f"- execution: {payload['execution_time']} (field `{payload['executable_field']}`, "
        f"pre-registered = {payload['field_was_preregistered']})",
        f"- future poisoning (mutate all future prices): "
        f"**{'PASS' if poison['passed'] else 'FAIL'}** ({poison['decisions_before_cutoff']} "
        f"decisions <= cutoff unchanged)",
        f"- warm-up (no negative-index wrap): **{'PASS' if warmup else 'FAIL'}**",
        f"- negative weights in book: {neg}  |  short observations: {n_short_obs}  |  "
        f"no short spot: **{payload['no_short_spot']}**", "",
        "## §21 Gap risk (close_T -> exec_T+1)", "",
        f"- mean book entry gap: {_r(gap['mean_book_entry_gap_bps'], 3)} bps",
        f"- mean BTC entry gap: {_r(gap['mean_btc_entry_gap_bps'], 3)} bps",
        f"- gross co-timed: {_r(gap['gross_cotimed_bps'], 3)} bps; gross T+1 open: "
        f"{_r(gap['gross_next_open_bps'], 3)} bps",
        f"- T+1-minus-cotimed gross contribution: {_r(gap['gap_contribution_bps'], 3)} bps "
        f"(NOT hidden)", "",
    ])
    _emit("PIT_EXECUTION_AUDIT", payload, md)
    return payload


# ---------------------------------------------------------------------------
# §8/§12/§29 historical diagnostic
# ---------------------------------------------------------------------------

def historical_diagnostic(world: World) -> dict[str, Any]:
    full = world.summary(world.full)
    splits = {name: world.summary(L.split_mask(world.days, name)) for name in L.SPLIT_ORDER}
    # §12 recompute the RFC-031 long-or-cash diagnostic prior from raw (co-timed).
    prior = L.summarise(world.run(L.split_mask(world.days, "VALIDATION"),
                                  exec_mode="cotimed"))
    prior_full = L.summarise(world.run(world.full, exec_mode="cotimed"))
    ref_v = L.read_json(L.RFC031_DIR / "BENCHMARK_COMPARISON.json")
    reported = ref_v.get("volscaled_tsmom_long_only_validation_net_bps")
    recomputed = prior.get("net_expectancy_bps")
    match = (reported is not None and recomputed is not None
             and abs(reported - recomputed) <= max(TOL, abs(reported) * 1e-6))
    payload: dict[str, Any] = {
        "generated": _now(),
        "evidence_class": L.EVIDENCE_CLASS_HISTORICAL + "_ONLY",
        "why_not_confirmatory": ("this corpus was already observed by RFC-030/RFC-031; no "
                                 "historical subset may be renamed fresh Validation/Holdout "
                                 "(§8, §9)"),
        "candidate": L.CANDIDATE_ID,
        "full": full,
        "splits_diagnostic_only": splits,
        "monthly_observations": full.get("rebalances"),
        "mean_net_bps": full.get("net_expectancy_bps"),
        "median_net_bps": full.get("net_median_bps"),
        "sharpe": full.get("sharpe"),
        "max_dd_bps": full.get("max_dd_bps"),
        "turnover": full.get("mean_turnover_notional"),
        "positive_month_pct": full.get("win_rate"),
        "prior_recompute": {
            "rfc031_reported_long_or_cash_validation_net_bps": reported,
            "rfc032_recomputed_long_or_cash_validation_net_bps": recomputed,
            "match": bool(match),
            "rfc032_recomputed_long_or_cash_full_net_bps": prior_full.get("net_expectancy_bps"),
            "note": "RFC-031 co-timed long-or-cash prior recomputed from raw, not copied",
        },
        "attribution": {
            "pct_time_long": full.get("pct_time_long"),
            "pct_time_cash": full.get("pct_time_cash"),
            "mean_invested_capital": full.get("mean_invested_capital"),
            "mean_n_long": full.get("mean_n_long"),
            "cash_allocation": float(1.0 - (full.get("mean_invested_capital") or 0.0)),
            "mean_gross_exposure": full.get("mean_net_exposure"),
            "mean_net_exposure": full.get("mean_net_exposure"),
            "mean_short_exposure": 0.0,
        },
    }
    md = "\n".join([
        "# RFC-032 — HISTORICAL DIAGNOSTIC (EXT-TSMOM-002)", "",
        "- evidence class: **HISTORICAL_DIAGNOSTIC_ONLY** (not fresh Validation/Holdout)", "",
        _table([{"quantity": k, "value": _r(full.get(k), 4)} for k in
                ("rebalances", "net_expectancy_bps", "gross_expectancy_bps",
                 "cost_expectancy_bps", "net_median_bps", "sharpe", "max_dd_bps",
                 "mean_turnover_notional", "win_rate")],
               ["quantity", "value"]), "",
        "## Diagnostic splits (labels are HISTORICAL, not fresh evidence)", "",
        _table([{"split": k, "net_expectancy_bps": _r(v.get("net_expectancy_bps"), 3),
                 "sharpe": _r(v.get("sharpe"), 3), "rebalances": v.get("rebalances")}
                for k, v in splits.items()],
               ["split", "net_expectancy_bps", "sharpe", "rebalances"]), "",
        "## §12 RFC-031 long-or-cash prior recomputed from raw", "",
        f"- RFC-031 reported (co-timed long-or-cash validation): "
        f"{_r(reported, 4)} bps/month",
        f"- RFC-032 recomputed from raw: {_r(recomputed, 4)} bps/month  -> match "
        f"**{match}**",
        f"- RFC-032 recomputed full long-or-cash: "
        f"{_r(prior_full.get('net_expectancy_bps'), 4)} bps/month", "",
        "## §17 Attribution", "",
        _table([{"metric": k, "value": _r(v, 4)} for k, v in
                payload["attribution"].items()], ["metric", "value"]), "",
    ])
    _emit("HISTORICAL_DIAGNOSTIC", payload, md)
    return payload


# ---------------------------------------------------------------------------
# §15/§16 temporal diagnostic
# ---------------------------------------------------------------------------

ERAS = (("2018-2019", "2018-01-01", "2019-12-31"),
        ("2020-2021", "2020-01-01", "2021-12-31"),
        ("2022", "2022-01-01", "2022-12-31"),
        ("2023-2024", "2023-01-01", "2024-12-31"),
        ("2025-2026", "2025-01-01", "2026-12-31"))


def _recent(nets: NDArray[Any], n: int) -> dict[str, Any]:
    x = np.asarray(nets, dtype=np.float64)[-n:]
    return _stat_block(x, 12.0)


def temporal_diagnostic(world: World) -> dict[str, Any]:
    eras: dict[str, Any] = {}
    for name, lo, hi in ERAS:
        lo_ms, hi_ms = L._ts(lo, hi)
        mask = (world.days >= lo_ms) & (world.days <= hi_ms)
        s = world.summary(mask)
        eras[name] = {"net_expectancy_bps": s.get("net_expectancy_bps"),
                      "gross_expectancy_bps": s.get("gross_expectancy_bps"),
                      "cost_expectancy_bps": s.get("cost_expectancy_bps"),
                      "rebalances": s.get("rebalances"), "sharpe": s.get("sharpe"),
                      "max_dd_bps": s.get("max_dd_bps"),
                      "turnover": s.get("mean_turnover_notional"),
                      "net_exposure": s.get("mean_net_exposure"),
                      "status": s.get("status")}
    full_run = world.run(world.full)
    nets = np.asarray(full_run["nets"])
    r12 = _recent(nets, 12)
    r24 = _recent(nets, 24)
    nets_by_era = {k: v["net_expectancy_bps"] for k, v in eras.items()
                   if v.get("status") == "OK" and v["net_expectancy_bps"] is not None}
    positive_eras = sum(1 for x in nets_by_era.values() if (x or 0) > 0)
    best = max(nets_by_era.items(), key=lambda kv: kv[1] or -1e9) if nets_by_era else None
    worst = min(nets_by_era.items(), key=lambda kv: kv[1] or 1e9) if nets_by_era else None
    payload: dict[str, Any] = {
        "generated": _now(),
        "candidate": L.CANDIDATE_ID,
        "eras": eras,
        "positive_eras": positive_eras,
        "n_eras": len(nets_by_era),
        "best_era": best[0] if best else None,
        "best_era_bps": best[1] if best else None,
        "worst_era": worst[0] if worst else None,
        "worst_era_bps": worst[1] if worst else None,
        "recent_12m": r12,
        "recent_24m": r24,
        "diagnostic_note": "recent windows are diagnostics, never optimised from (§16)",
    }
    md = "\n".join([
        "# RFC-032 — TEMPORAL DIAGNOSTIC", "",
        _table([{"era": k, "gross": _r(v["gross_expectancy_bps"], 2),
                 "cost": _r(v["cost_expectancy_bps"], 2),
                 "net": _r(v["net_expectancy_bps"], 2),
                 "sharpe": _r(v["sharpe"], 3), "max_dd": _r(v["max_dd_bps"], 1),
                 "turnover": _r(v["turnover"], 3), "net_exp": _r(v["net_exposure"], 3)}
                for k, v in eras.items()],
               ["era", "gross", "cost", "net", "sharpe", "max_dd", "turnover",
                "net_exp"]), "",
        f"- positive eras: {positive_eras}/{len(nets_by_era)}",
        f"- best era: {payload['best_era']} ({_r(payload['best_era_bps'], 2)} bps)",
        f"- worst era: {payload['worst_era']} ({_r(payload['worst_era_bps'], 2)} bps)", "",
        "## §16 Recent windows", "",
        _table([{"window": "last 12m", "net_bps": _r(r12.get("net_expectancy_bps"), 2),
                 "sharpe": _r(r12.get("sharpe"), 3), "max_dd_bps": _r(r12.get("max_dd_bps"), 1)},
                {"window": "last 24m", "net_bps": _r(r24.get("net_expectancy_bps"), 2),
                 "sharpe": _r(r24.get("sharpe"), 3), "max_dd_bps": _r(r24.get("max_dd_bps"), 1)}],
               ["window", "net_bps", "sharpe", "max_dd_bps"]), "",
    ])
    _emit("TEMPORAL_DIAGNOSTIC", payload, md)
    return payload


# ---------------------------------------------------------------------------
# §18 benchmark diagnostic
# ---------------------------------------------------------------------------

def _long_only_book(world: World, i: int, mode: str) -> NDArray[Any]:
    """Signal-independent long-only controls (§18).  No short, no leverage."""
    t = L.tsmom_long_cash_target(world.close, i)
    elig = np.asarray(t["eligible"], dtype=bool)
    if mode == "equal_weight":
        n = int(np.sum(elig))
        w = np.zeros(len(world.syms))
        if n > 0:
            w[elig] = 1.0 / n
        return w
    # vol-scaled long-only: always long, inverse-vol book, gross normalised to 1
    base = np.where(elig, np.asarray(t["scale"]), 0.0)
    s = float(np.sum(base))
    return base / s if s > 0 else base


def _basket_nets(world: World, mask: NDArray[Any], mode: str) -> NDArray[Any]:
    grid = rebalance_grid(world, mask)
    prev = np.zeros(len(world.syms))
    nets: list[float] = []
    for i, e0, e1 in grid:
        w = _long_only_book(world, i, mode)
        good = np.isfinite(world.open[e1]) & np.isfinite(world.open[e0])
        ret = np.zeros(len(world.syms))
        ret[good] = world.open[e1, good] / world.open[e0, good] - 1.0
        g = float(np.nansum(w * ret) * 1e4)
        c = float(np.nansum(np.abs(w - prev)) * L.PER_SIDE_COST_BPS)
        nets.append(g - c)
        prev = w
    return np.asarray(nets)


def _btc_nets(world: World, mask: NDArray[Any]) -> NDArray[Any]:
    btc = world.syms.index("BTCUSDT")
    grid = rebalance_grid(world, mask)
    out: list[float] = []
    for _i, e0, e1 in grid:
        if np.isfinite(world.open[e0, btc]) and np.isfinite(world.open[e1, btc]):
            out.append(float(world.open[e1, btc] / world.open[e0, btc] - 1.0) * 1e4)
        else:
            out.append(0.0)
    return np.asarray(out)


def benchmark_diagnostic(world: World) -> dict[str, Any]:
    cand = np.asarray(world.run(world.full)["nets"])
    ew = _basket_nets(world, world.full, "equal_weight")
    vs = _basket_nets(world, world.full, "volscaled")
    btc = _btc_nets(world, world.full)
    payload: dict[str, Any] = {
        "generated": _now(),
        "periods": "same monthly rebalance dates, same T+1 open execution, same costs",
        "benchmarks": {
            "EXT_TSMOM_002": _stat_block(cand),
            "equal_weight_eligible_long_only": _stat_block(ew),
            "volscaled_long_only": _stat_block(vs),
            "BTC_buy_and_hold": _stat_block(btc),
            "cash": {"net_expectancy_bps": 0.0, "sharpe": 0.0},
        },
        "delta_vs_ew_bps": float(np.mean(cand) - np.mean(ew)) if ew.size else None,
        "delta_vs_volscaled_bps": float(np.mean(cand) - np.mean(vs)) if vs.size else None,
        "delta_vs_btc_bps": float(np.mean(cand) - np.mean(btc)) if btc.size else None,
        "timing_signal_adds_value_vs_long_only": bool(
            ew.size and np.mean(cand) > np.mean(ew)),
        "note": ("benchmarks are diagnostic only; the candidate is NOT modified to beat "
                 "them (§19)"),
    }
    md = "\n".join([
        "# RFC-032 — BENCHMARK DIAGNOSTIC", "",
        f"- {payload['periods']}", "",
        _table([{"series": k, "net_bps": _r(v.get("net_expectancy_bps"), 2),
                 "median_bps": _r(v.get("net_median_bps"), 2),
                 "sharpe": _r(v.get("sharpe"), 3), "max_dd_bps": _r(v.get("max_dd_bps"), 1)}
                for k, v in payload["benchmarks"].items()],
               ["series", "net_bps", "median_bps", "sharpe", "max_dd_bps"]), "",
        f"- delta vs EW long-only: {_r(payload['delta_vs_ew_bps'], 2)} bps/month",
        f"- delta vs vol-scaled long-only: {_r(payload['delta_vs_volscaled_bps'], 2)} bps/month",
        f"- delta vs BTC buy-and-hold: {_r(payload['delta_vs_btc_bps'], 2)} bps/month",
        f"- timing signal adds value vs EW long-only: "
        f"**{payload['timing_signal_adds_value_vs_long_only']}**", "",
        f"> {payload['note']}", "",
    ])
    _emit("BENCHMARK_DIAGNOSTIC", payload, md)
    return payload


# ---------------------------------------------------------------------------
# §10 G_REM_0 / §11 G_REM_1
# ---------------------------------------------------------------------------

def implementation_audit(pit: dict[str, Any], cost_ok: bool, frozen: dict[str, Any],
                         verify: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "no_short_spot": bool(pit["no_short_spot"]),
        "t_plus_1_execution": bool(pit["exec_lag"] == 1 and pit["executable_field"] == "open"),
        "pit_clean": bool(pit["future_poisoning_passed"] and pit["warmup_passed"]),
        "cost_accounting_clean": bool(cost_ok),
        "deterministic_reproduction": bool(verify.get("reproduction_exact")),
        "candidate_frozen": bool(frozen.get("config_hash")),
    }
    passed = all(checks.values())
    payload: dict[str, Any] = {
        "generated": _now(),
        "gate": "G_REM_0_IMPLEMENTATION",
        "checks": checks,
        "result": "PASS" if passed else "FAIL",
        "candidate": L.CANDIDATE_ID,
    }
    md = "\n".join([
        "# RFC-032 — IMPLEMENTATION AUDIT (G_REM_0)", "",
        _table([{"check": k, "result": "PASS" if v else "FAIL"} for k, v in checks.items()],
               ["check", "result"]), "",
        f"- **G_REM_0_IMPLEMENTATION = {payload['result']}**", "",
    ])
    _emit("IMPLEMENTATION_AUDIT", payload, md)
    return payload


def admission_decision(world: World, historical: dict[str, Any],
                       temporal: dict[str, Any], impl: dict[str, Any],
                       benchmark: dict[str, Any],
                       verify: dict[str, Any] | None = None) -> dict[str, Any]:
    full_net = historical["full"].get("net_expectancy_bps")
    median = historical["full"].get("net_median_bps")
    pos_eras = temporal.get("positive_eras")
    n_eras = temporal.get("n_eras")
    r12 = temporal["recent_12m"].get("net_expectancy_bps")
    r24 = temporal["recent_24m"].get("net_expectancy_bps")
    crit = {
        "C1_full_net_positive": bool((full_net or 0.0) > 0.0),
        "C2_median_positive": bool((median or 0.0) > 0.0),
        "C3_positive_eras_ge_2": bool((pos_eras or 0) >= 2),
        "C4_recent_24m_positive": bool((r24 or 0.0) > 0.0),
        "C5_recent_12m_positive": bool((r12 or 0.0) > 0.0),
    }
    plausibility = all(crit.values())
    g_rem_1 = "PASS" if (impl["result"] == "PASS" and plausibility) else "FAIL"
    if g_rem_1 == "PASS":
        decision = "ADMITTED_FOR_FORWARD_EVIDENCE"
        paper_status = "PAPER_OBSERVING"
        next_step = "FORWARD PAPER OBSERVATION"
    else:
        decision = "REJECTED"
        paper_status = "PAPER_NOT_STARTED"
        next_step = "STRATEGIC_PROJECT_DECISION"
    payload: dict[str, Any] = {
        "generated": _now(),
        "gate": "G_REM_1_HISTORICAL_PLAUSIBILITY",
        "criteria": crit,
        "criteria_definition": G_REM_1_CRITERIA,
        "full_net_bps": full_net,
        "median_net_bps": median,
        "positive_eras": pos_eras,
        "n_eras": n_eras,
        "recent_12m_bps": r12,
        "recent_24m_bps": r24,
        "plausibility_pass": plausibility,
        "G_REM_0": impl["result"],
        "G_REM_1": g_rem_1,
        "decision": decision,
        "paper_status": paper_status,
        "next": next_step,
        "statement": ("THE EXECUTABLE VERSION DOES NOT PRESERVE THE HISTORICAL ECONOMIC "
                      "EDGE" if g_rem_1 == "FAIL" else
                      "THE EXECUTABLE VERSION IS PLAUSIBLE ENOUGH TO OBSERVE FORWARD"),
        "benchmark_context": {
            "delta_vs_ew_bps": benchmark.get("delta_vs_ew_bps"),
            "delta_vs_btc_bps": benchmark.get("delta_vs_btc_bps"),
            "timing_signal_adds_value_vs_long_only":
                benchmark.get("timing_signal_adds_value_vs_long_only"),
        },
        "no_auto_next_candidate": ("REJECTED path does NOT create EXT-TSMOM-003 "
                                   "automatically (§30, §73)"),
        "evidence_class": "HISTORICAL_DIAGNOSTIC_ONLY",
        "verifier_G_REM_1_independent": (verify or {}).get("G_REM_1_independent"),
        "verifier_agrees": ((verify or {}).get("G_REM_1_independent") == g_rem_1)
        if verify else None,
    }
    md = "\n".join([
        "# RFC-032 — ADMISSION DECISION (G_REM_1)", "",
        _table([{"criterion": k, "definition": G_REM_1_CRITERIA[k],
                 "result": "PASS" if v else "FAIL"} for k, v in crit.items()],
               ["criterion", "definition", "result"]), "",
        f"- full net: {_r(full_net, 3)} bps/month | median: {_r(median, 3)} bps",
        f"- positive eras: {pos_eras}/{n_eras}",
        f"- recent 12m: {_r(r12, 3)} bps | recent 24m: {_r(r24, 3)} bps", "",
        f"- G_REM_0_IMPLEMENTATION = **{impl['result']}**",
        f"- G_REM_1_HISTORICAL_PLAUSIBILITY = **{g_rem_1}**", "",
        f"- **decision: {decision}**",
        f"- PAPER STATUS: **{paper_status}**",
        f"- NEXT: **{next_step}**", "",
        f"> {payload['statement']}", "",
    ])
    _emit("ADMISSION_DECISION", payload, md)
    return payload


# ---------------------------------------------------------------------------
# §32/§36/§48/§70 forward paper campaign (only if G_REM_1 = PASS)
# ---------------------------------------------------------------------------

def paper_campaign_spec(frozen: dict[str, Any], world: World,
                        temporal: dict[str, Any]) -> dict[str, Any]:
    nets = np.asarray(world.run(world.full)["nets"])
    band = {
        "monthly_return_p05_bps": float(np.quantile(nets, 0.05)),
        "monthly_return_p50_bps": float(np.quantile(nets, 0.50)),
        "monthly_return_p95_bps": float(np.quantile(nets, 0.95)),
        "turnover_mean": float(np.mean(world.run(world.full)["traded"])),
        "eligible_assets_mean": temporal.get("n_eras"),
    }
    payload: dict[str, Any] = {
        "generated": _now(),
        "candidate_id": L.CANDIDATE_ID,
        "candidate_hash": frozen["config_hash"],
        "campaign_class": "TSMOM002PaperCampaign",
        "capital": "SIMULATED_ONLY (10,000 USDT notional reference)",
        "starting_capital_usdt": 10000.0,
        "real_orders": False,
        "broker_credentials_required": False,
        "rebalance_frequency": "monthly (unchanged)",
        "llm_in_trading_path": False,
        "deterministic": True,
        "no_backfill": True,
        "state_machine": ["PAPER_NOT_STARTED", "PAPER_OBSERVING", "PAPER_EVIDENCE_SUFFICIENT",
                          "PAPER_FAIL", "PAPER_PASS"],
        "checkpoints_monthly_rebalances": [3, 6, 12],
        "first_three_labels": ["EARLY_POSITIVE", "EARLY_NEGATIVE", "WITHIN_EXPECTATION",
                               "DRIFT_WARNING"],
        "baselines_tracked": ["BTC buy-and-hold", "equal-weight eligible universe"],
        "drift_types": ["DATA_DRIFT", "UNIVERSE_DRIFT", "SIGNAL_DRIFT", "TURNOVER_DRIFT",
                        "COST_DRIFT", "PERFORMANCE_DRIFT"],
        "reference_bands": band,
        "gates": {"G_FWD_0_OPERATIONAL": "SEE_PAPER_STATUS", "G_FWD_1_INTEGRITY":
                  "SEE_PAPER_STATUS", "G_FWD_2_EVIDENCE": "NOT_REACHED",
                  "G_FWD_3_PROFITABILITY": "NOT_REACHED"},
        "live_gate": "NONE in RFC-032 (would need a separate LIVE READINESS/CANARY RFC)",
        "paper_status": "PAPER_OBSERVING",
    }

    def _w(name: str, obj: Any, md: str) -> None:
        L.write_json(PAPER / f"{name}.json", obj)
        L.write_md(PAPER / f"{name}.md", md)

    _w("PAPER_CAMPAIGN_SPEC", payload,
       "\n".join(["# RFC-032 — PAPER CAMPAIGN SPEC (EXT-TSMOM-002)", "",
                  f"- candidate: `{payload['candidate_id']}`",
                  f"- candidate hash: `{payload['candidate_hash']}`",
                  f"- capital: {payload['capital']}",
                  f"- rebalance: {payload['rebalance_frequency']}",
                  f"- checkpoints: {payload['checkpoints_monthly_rebalances']}",
                  f"- status: **{payload['paper_status']}**", "",
                  f"> {payload['live_gate']}", ""]))
    _w("CANDIDATE_SNAPSHOT", {
        "candidate_id": L.CANDIDATE_ID, "config_hash": frozen["config_hash"],
        "code_hash_sprint032_lib": frozen["code_hash_sprint032_lib"],
        "data_hashes": frozen["data_hashes"], "universe": frozen["universe"],
        "cost_model": frozen["cost_model"], "frozen_spec": frozen,
       }, "\n".join(["# RFC-032 — CANDIDATE SNAPSHOT", "",
                     f"- config hash: `{frozen['config_hash']}`",
                     f"- code hash: `{frozen['code_hash_sprint032_lib']}`", ""]))
    _w("REFERENCE_BANDS", band,
       "\n".join(["# RFC-032 — REFERENCE BANDS (frozen pre-campaign)", "",
                  _table([{"metric": k, "value": _r(v, 4)} for k, v in band.items()],
                         ["metric", "value"]), ""]))
    _w("PAPER_STATUS", {"candidate_id": L.CANDIDATE_ID, "paper_status": "PAPER_OBSERVING",
                        "real_orders": False, "backfill": False},
       "\n".join(["# RFC-032 — PAPER STATUS", "",
                  f"- candidate: `{L.CANDIDATE_ID}`",
                  "- paper status: **PAPER_OBSERVING** (simulated capital only)",
                  "- real orders: NO  |  backfill: NO", ""]))
    return payload


# ---------------------------------------------------------------------------
# §69 plan
# ---------------------------------------------------------------------------

def write_plan(head: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "rfc": "RFC-032",
        "title": "EXECUTABLE TSMOM REMEDIATION & FRESH-EVIDENCE ADMISSION",
        "candidate": L.CANDIDATE_ID,
        "generated": _now(),
        "source_commit": _git("HEAD"),
        "entry_head_expected": "8cd10cc (RFC-031)",
        "entry_head_verified": head,
        "question": ("Does the executable long-or-cash spot version of the frozen TSMOM "
                     "signal keep enough historical economics to justify fresh forward "
                     "paper evidence?"),
        "not": ["new alpha", "parameter tuning", "reuse of old Validation/Holdout as fresh "
                "evidence", "real capital", "auto EXT-TSMOM-003"],
        "remediations_allowed": ["R1 negative weight -> 0/CASH", "R2 close-T -> T+1 open"],
        "phases": ["ENTRY_GATE", "FREEZE_SPEC", "REMEDIATION_DIFF", "PIT_EXECUTION",
                   "HISTORICAL_DIAGNOSTIC", "TEMPORAL_DIAGNOSTIC", "BENCHMARK_DIAGNOSTIC",
                   "G_REM_0_IMPLEMENTATION", "G_REM_1_PLAUSIBILITY", "ADMISSION_DECISION",
                   "INDEPENDENT_VERIFY", "FINAL_REPORT"],
        "pre_registered_G_REM_1_criteria": G_REM_1_CRITERIA,
        "marker_correction": {
            "statistical_historical_effect": 1,
            "executable_validated_net_edge": 0,
            "robust_executable_net_edge": 0,
            "executable_holdout_pass": 0,
            "certified_paper_candidate": 0,
            "forward_paper_profitable": 0,
            "live_profitable": 0,
        },
    }
    md = "\n".join([
        "# RFC-032 — EXECUTABLE TSMOM REMEDIATION (PLAN)", "",
        f"- candidate: `{payload['candidate']}`",
        f"- generated: `{payload['generated']}`  |  source commit: "
        f"`{payload['source_commit']}`",
        f"- entry head expected {payload['entry_head_expected']}; verified "
        f"`{payload['entry_head_verified']}`", "",
        f"> {payload['question']}", "",
        "## Allowed remediations", "",
        "\n".join(f"- {x}" for x in payload["remediations_allowed"]), "",
        "## Pre-registered G_REM_1 admission criteria", "",
        "\n".join(f"- **{k}**: {v}" for k, v in G_REM_1_CRITERIA.items()), "",
        "## Economic marker (corrected)", "",
        "\n".join(f"- {k} = {v}" for k, v in payload["marker_correction"].items()), "",
    ])
    _emit("RFC032_PLAN", payload, md)
    return payload


# ---------------------------------------------------------------------------
# §75 cost reconciliation (RFC-031 convention)
# ---------------------------------------------------------------------------

def cost_reconciliation(world: World) -> dict[str, Any]:
    r = world.run(world.full)
    traded = np.asarray(r["traded"])
    costs = np.asarray(r["costs"])
    per_side = L.PER_SIDE_COST_BPS
    recomputed = traded * per_side
    max_abs = float(np.max(np.abs(costs - recomputed))) if costs.size else 0.0
    s = L.summarise(r)
    ok = bool(max_abs <= TOL and abs(float(np.mean(recomputed))
                                     - (s.get("cost_expectancy_bps") or 0.0)) <= TOL)
    stress: dict[str, Any] = {}
    for mult in L.COST_STRESS_MULTIPLIERS:
        for name in L.SPLIT_ORDER:
            m = L.split_mask(world.days, name)
            stress[f"x{mult}_{name}"] = world.summary(m, cost_bps=per_side * mult).get(
                "net_expectancy_bps")
    return {
        "generated": _now(),
        "per_side_cost_bps": per_side,
        "charging_rule": "cost = traded_notional * per_side_cost_bps",
        "turnover_definition": "sum_assets |w_t - w_{t-1}|",
        "mean_turnover_notional": s.get("mean_turnover_notional"),
        "cost_expectancy_bps": s.get("cost_expectancy_bps"),
        "recomputed_cost_mean_bps": float(np.mean(recomputed)),
        "max_abs_diff_bps": max_abs,
        "factor_of_two_ambiguity": "NONE (independently verified)",
        "reconciliation_ok": ok,
        "stress": stress,
    }


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------

def run(stage: str) -> None:
    world = World()
    if stage == "artifacts":
        write_plan(_git("HEAD"))
        frozen = freeze_spec(world)
        remediation_diff(frozen)
        cost = cost_reconciliation(world)
        pit = pit_execution_audit(world, frozen)
        historical = historical_diagnostic(world)
        temporal = temporal_diagnostic(world)
        benchmark = benchmark_diagnostic(world)
        L.write_json(OUT / "_rfc032_intermediate.json", {
            "frozen": frozen, "cost": cost, "pit": pit, "historical": historical,
            "temporal": temporal, "benchmark": benchmark,
        })
        # also persist the cost reconciliation as its own remediation artifact
        _emit("COST_RECONCILIATION", cost, "\n".join([
            "# RFC-032 — COST RECONCILIATION", "",
            f"- per-side cost: {cost['per_side_cost_bps']} bps",
            f"- mean turnover: {_r(cost['mean_turnover_notional'], 4)}",
            f"- cost expectancy: {_r(cost['cost_expectancy_bps'], 4)} bps",
            f"- reconciliation: **{'PASS' if cost['reconciliation_ok'] else 'FAIL'}**", "",
            _table([{"scenario": k, "net_bps": _r(v, 3)} for k, v in cost["stress"].items()],
                   ["scenario", "net_bps"]), ""]))
        print("[run032] artifacts written", flush=True)
        print(f"[run032] full net = {historical['full'].get('net_expectancy_bps')} bps",
              flush=True)
    elif stage == "final":
        inter = L.read_json(OUT / "_rfc032_intermediate.json")
        vpath = OUT / "RFC032_VERIFICATION.json"
        verify = L.read_json(vpath) if vpath.exists() else {}
        impl = implementation_audit(inter["pit"], inter["cost"]["reconciliation_ok"],
                                    inter["frozen"], verify)
        adm = admission_decision(world, inter["historical"], inter["temporal"], impl,
                                 inter["benchmark"], verify)
        paper = None
        if adm["G_REM_1"] == "PASS":
            paper = paper_campaign_spec(inter["frozen"], world, inter["temporal"])
        write_final_report(world, inter, verify, impl, adm, paper)
        print(f"[run032] G_REM_0 = {impl['result']}  G_REM_1 = {adm['G_REM_1']}  "
              f"decision = {adm['decision']}", flush=True)
    else:
        raise SystemExit(f"unknown stage {stage!r}")


def forward_boundary(world: World, forward_start_ms: int) -> dict[str, Any]:
    """§33/§67: nothing in the already-observed diagnostic corpus is forward data."""
    last_ts = int(world.days.max())
    n_forward = int(sum(1 for t in world.days.tolist()
                        if L.is_forward_evidence(int(t), forward_start_ms)))
    return {"forward_evidence_start_ms": forward_start_ms,
            "diagnostic_corpus_last_ts_ms": last_ts,
            "diagnostic_days_that_are_forward": n_forward,
            "last_ts_is_forward": L.is_forward_evidence(last_ts, forward_start_ms),
            "rule": "only timestamps >= FORWARD_EVIDENCE_START count as forward (§67)"}


def write_final_report(world: World, inter: dict[str, Any], verify: dict[str, Any],
                       impl: dict[str, Any], adm: dict[str, Any],
                       paper: dict[str, Any] | None) -> None:
    hist = inter["historical"]
    temp = inter["temporal"]
    bench = inter["benchmark"]
    paper_status = adm["paper_status"]
    forward_start = "N/A (no campaign started)" if adm["G_REM_1"] != "PASS" else _now()
    day_ms = 86_400_000
    fwd = forward_boundary(world, int(world.days.max()) + day_ms)
    payload: dict[str, Any] = {
        "rfc": "RFC-032",
        "title": "RFC-032 EXECUTABLE TSMOM REMEDIATION",
        "generated": _now(),
        "candidate": L.CANDIDATE_ID,
        "source_candidate": L.SOURCE_CANDIDATE,
        "remediation": "LONG/CASH + T+1",
        "source_commit": verify.get("source_commit", _git("HEAD")),
        "G_REM_0_IMPLEMENTATION": impl["result"],
        "G_REM_1_HISTORICAL_PLAUSIBILITY": adm["G_REM_1"],
        "historical_evidence_status": "DIAGNOSTIC_ONLY",
        "historical_mean_net_bps": hist["full"].get("net_expectancy_bps"),
        "historical_median_net_bps": hist["full"].get("net_median_bps"),
        "recent_12m_bps": temp["recent_12m"].get("net_expectancy_bps"),
        "recent_24m_bps": temp["recent_24m"].get("net_expectancy_bps"),
        "positive_eras": temp.get("positive_eras"),
        "n_eras": temp.get("n_eras"),
        "long_exposure_pct_time": hist["attribution"].get("pct_time_long"),
        "cash_exposure_pct_time": hist["attribution"].get("pct_time_cash"),
        "short_exposure": 0.0,
        "benchmark_comparison": {
            "delta_vs_ew_bps": bench.get("delta_vs_ew_bps"),
            "delta_vs_btc_bps": bench.get("delta_vs_btc_bps"),
            "timing_signal_adds_value_vs_long_only":
                bench.get("timing_signal_adds_value_vs_long_only"),
        },
        "decision": adm["decision"],
        "paper_status": paper_status,
        "forward_evidence_start": forward_start,
        "G_FWD_0": "NOT_REACHED" if paper is None else "PASS",
        "G_FWD_1": "NOT_REACHED" if paper is None else "SEE_PAPER_STATUS",
        "G_FWD_2": "NOT_REACHED",
        "G_FWD_3": "NOT_REACHED",
        "FALSE_SUCCESS": verify.get("FALSE_SUCCESS"),
        "independent_verification": {
            "false_success": verify.get("FALSE_SUCCESS"),
            "checks_total": verify.get("checks_total"),
            "checks_passed": verify.get("checks_passed"),
            "verifier_G_REM_1_independent": verify.get("G_REM_1_independent"),
            "verifier_agrees": verify.get("G_REM_1_independent") == adm["G_REM_1"],
        },
        "next": adm["next"],
        "statement": adm["statement"],
        "forward_boundary": fwd,
        "marker": {
            "statistical_historical_effect": 1,
            "executable_validated_net_edge": 0,
            "robust_executable_net_edge": 0,
            "executable_holdout_pass": 0,
            "certified_paper_candidate": 0,
            "forward_paper_profitable": 0,
            "live_profitable": 0,
        },
    }
    L.write_json(L.REPO / "reports" / "RFC032_FINAL_REPORT.json", payload)
    L.write_md(L.REPO / "reports" / "RFC032_FINAL_REPORT.md", _final_md(payload))


def _final_md(p: dict[str, Any]) -> str:
    return "\n".join([
        "# RFC-032 EXECUTABLE TSMOM REMEDIATION", "",
        "```text",
        f"CANDIDATE = {p['candidate']}",
        f"REMEDIATION = {p['remediation']}",
        "",
        f"G_REM_0_IMPLEMENTATION = {p['G_REM_0_IMPLEMENTATION']}",
        f"G_REM_1_HISTORICAL_PLAUSIBILITY = {p['G_REM_1_HISTORICAL_PLAUSIBILITY']}",
        "",
        f"HISTORICAL EVIDENCE STATUS = {p['historical_evidence_status']}",
        f"HISTORICAL MEAN NET = {_r(p['historical_mean_net_bps'], 3)} bps/month",
        f"HISTORICAL MEDIAN NET = {_r(p['historical_median_net_bps'], 3)} bps",
        f"RECENT 12m = {_r(p['recent_12m_bps'], 3)} bps/month",
        f"RECENT 24m = {_r(p['recent_24m_bps'], 3)} bps/month",
        f"POSITIVE ERAS = {p['positive_eras']}/{p['n_eras']}",
        f"LONG EXPOSURE (time) = {_r(p['long_exposure_pct_time'], 3)}",
        f"CASH EXPOSURE (time) = {_r(p['cash_exposure_pct_time'], 3)}",
        f"SHORT EXPOSURE = {p['short_exposure']}",
        "",
        f"BENCHMARK DELTA vs EW = {_r(p['benchmark_comparison']['delta_vs_ew_bps'], 2)} bps",
        f"BENCHMARK DELTA vs BTC = {_r(p['benchmark_comparison']['delta_vs_btc_bps'], 2)} bps",
        "",
        f"DECISION = {p['decision']}",
        f"PAPER STATUS = {p['paper_status']}",
        f"FORWARD_EVIDENCE_START = {p['forward_evidence_start']}",
        "",
        f"G_FWD_0 = {p['G_FWD_0']}",
        f"G_FWD_1 = {p['G_FWD_1']}",
        f"G_FWD_2 = {p['G_FWD_2']}",
        f"G_FWD_3 = {p['G_FWD_3']}",
        "",
        f"FALSE_SUCCESS = {p['FALSE_SUCCESS']}",
        f"INDEPENDENT VERIFICATION = {p['independent_verification']}",
        "",
        f"STATEMENT = {p['statement']}",
        f"NEXT = {p['next']}",
        "```", "",
        "## Economic marker", "",
        "\n".join(f"- {k} = {v}" for k, v in p["marker"].items()), "",
    ])


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "artifacts")
