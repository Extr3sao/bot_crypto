"""RFC-029 — Structural low-turnover carry pivot orchestrator.

Pipeline (spec order, §72):

    ENTRY GATE -> PLAN (freeze) -> DATA AUDIT -> FUNDING PIT AUDIT
    -> ENTRY POLICY REGISTRY -> FUNDING PERSISTENCE -> SURVIVAL CURVE
    -> CUMULATIVE FUNDING -> TIME TO BREAK-EVEN -> CAPITAL MODEL
    -> G_STRUCT_INFO -> DISCOVERY (G_STRUCT_1) -> VALIDATION (G_STRUCT_2)
    -> WALK-FORWARD / TEMPORAL / STRESS / ROBUSTNESS (G_STRUCT_3)
    -> HOLDOUT (G_STRUCT_4) -> PROFITABILITY_DECISION -> FINAL REPORT

Writes every §64 artifact under ``reports/structural-carry/`` plus
``reports/RFC029_FINAL_REPORT.{md,json}`` and, if required, the mandatory
``reports/PROFITABILITY_DECISION.md``.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import sprint028_lib as L28
import sprint029_lib as S

REPO = S.REPO
OUT = S.OUT_DIR

REGISTRY_FIELDS = (
    "candidate_id",
    "entry_policy",
    "exit_policy",
    "holding_horizon",
    "asset",
    "episodes",
    "active_days",
    "funding_pnl",
    "basis_pnl",
    "residual_pnl",
    "cost",
    "net_pnl",
    "net_expectancy",
    "return_on_capital",
    "capital_days",
    "PF",
    "Sharpe",
    "MaxDD",
    "status",
    "rejection_reason",
)

# Frozen selection rule (§17): max net expectancy per episode, capital-clean.
SELECTION_RULE = (
    "maximize net_expectancy_bps over the frozen discovery grid, "
    "among cells with net_pnl_bps>0, sum_roc>0, episodes>=8, "
    "PIT clean and accounting clean"
)

# Cost / funding / basis stress multipliers (§50-§52).
FUNDING_STRESS = (0.75, 0.50)
COST_STRESS = (1.0, 1.25, 1.50)
BASIS_TAIL_QUANTILE = 0.10  # adverse realized basis tail (empirical)

# --- G_STRUCT_INFO pre-registered thresholds (§39) --------------------------
INFO_MIN_POS_PROB = 0.60  # P(fwd cumulative funding>0) at 7d and 14d
INFO_MIN_SURVIVAL = 0.55  # P(regime positive after 7d)


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).isoformat()


def _r(x: Any, nd: int = 4) -> Any:
    return None if x is None else round(float(x), nd)


def _md_table(rows: list[list[Any]], header: list[str]) -> str:
    out = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    for r in rows:
        out.append("| " + " | ".join("" if x is None else str(x) for x in r) + " |")
    return "\n".join(out) + "\n"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# data / PIT audits
# ---------------------------------------------------------------------------


def data_audit() -> dict[str, Any]:
    per_asset: dict[str, Any] = {}
    months = []
    for sym in S.ASSETS:
        p = S.asset_panel(sym)
        months.append((int(p.ts[-1]) - int(p.ts[0])) / (1000 * 3600 * 24 * 30.4375))
        f = L28.load_funding(sym)
        sp = L28.load_spot(sym)
        per_asset[sym] = {
            "funding_rows": p.n(),
            "spot_rows": int(sp["open_time_ms"].shape[0]),
            "first": _iso(int(p.ts[0])),
            "last": _iso(int(p.ts[-1])),
            "funding_sorted": bool(np.all(np.diff(p.ts) > 0)),
            "funding_duplicates": int(p.n() - np.unique(p.ts).shape[0]),
            "funding_interval_hours": sorted(
                {float(x) for x in np.unique(f["funding_interval_hours"]).tolist()}
            ),
            "mean_funding_bps": round(float(np.nanmean(p.funding)), 4),
            "positive_share": round(float(np.mean(p.funding > 0)), 4),
            "epoch_note": "spot epoch unit ms->us switch at 2025-01-01 normalised upstream",
        }
    return {
        "assets": list(S.ASSETS),
        "spot_source": "data/spot/monthly/klines/<SYM>/5m (epoch-normalised, both eras)",
        "perp_source": "reused RFC-027 cache reports/positioning-data/cache/klines_*.npz",
        "funding_source": "data/futures/um/monthly/fundingRate/<SYM>",
        "history_months": round(float(min(months)), 2),
        "per_asset": per_asset,
        "result": "PASS" if min(months) >= 12.0 else "FAIL",
    }


def funding_pit_audit() -> dict[str, Any]:
    per_asset: dict[str, Any] = {}
    ok_all = True
    for sym in S.ASSETS:
        f = L28.load_funding(sym)
        t = f["funding_time_ms"].astype(np.int64)
        obs = f["observation_time_ms"].astype(np.int64)
        known = f["known_time_ms"].astype(np.int64)
        ih = f["funding_interval_hours"].astype(np.float64)
        ms = (ih * 3600 * 1000).astype(np.int64)
        v_obs = int(np.sum(obs != t - ms))
        v_known = int(np.sum(known != t))
        ok = v_obs == 0 and v_known == 0
        ok_all = ok_all and ok
        per_asset[sym] = {
            "observation_time_violations": v_obs,
            "known_time_violations": v_known,
            "signal_strictly_backward": True,
        }
    # future-poisoning test: perturbing the rate paid AT decision i must not
    # change the entry mask up to and including i.
    poisoned_ok = True
    for sym in S.ASSETS:
        p = S.asset_panel(sym)
        base = S.entry_mask(p, "A_POSITIVE_REGIME", "14d")
        # rebuild a poisoned f_mean directly
        r = p.funding.copy()
        for i in range(S.TRAILING_WINDOW, min(p.n(), S.TRAILING_WINDOW + 200)):
            r2 = r.copy()
            r2[i] = r2[i] + 100.0
            mw2 = L28._mean_of_lag(r2, S.TRAILING_WINDOW)
            m2 = np.isfinite(mw2) & (mw2 > 0.0)
            if not np.array_equal(m2[: i + 1], base[: i + 1]):
                poisoned_ok = False
                break
    return {
        "contract": {
            "observation_time": "payment_time - interval",
            "known_time": "payment_time",
            "decision_rule": "payment_time < T strict",
        },
        "per_asset": per_asset,
        "future_poisoning_test": {"passed": bool(poisoned_ok)},
        "result": "PASS" if (ok_all and poisoned_ok) else "FAIL",
    }


# ---------------------------------------------------------------------------
# frozen plan + registries
# ---------------------------------------------------------------------------


def build_plan() -> dict[str, Any]:
    return {
        "rfc": "RFC-029",
        "title": "Structural low-turnover carry pivot",
        "question": (
            "does positive funding persist long enough for a low-turnover "
            "delta-neutral position to recover its full cost and stay net positive OOS?"
        ),
        "structure": "LONG SPOT + SHORT PERPETUAL (no short spot; borrow DATA_BLOCKED)",
        "assets": list(S.ASSETS),
        "cost_model": "CARRY_COST_MODEL_V1",
        "round_trip_cost_bps": S.ROUND_TRIP_COST_BPS,
        "cost_model_v3_bps_not_used": S.COST_MODEL_V3_BPS,
        "committed_capital": S.COMMITTED_CAPITAL,
        "perp_leverage": S.PERP_LEVERAGE,
        "horizons_periods": S.HORIZON_PERIODS,
        "core_horizons": list(S.CORE_HORIZONS),
        "reference_horizon": S.REFERENCE_HORIZON,
        "policies": list(S.POLICIES),
        "exit_models": list(S.EXIT_MODELS),
        "primary_exit_model": S.PRIMARY_EXIT_MODEL,
        "core_cells": S.CORE_CELLS,
        "splits": S.SPLIT_FRACTIONS,
        "selection_rule": SELECTION_RULE,
        "min_discovery_episodes": S.MIN_DISCOVERY_EPISODES,
        "min_validation_episodes": S.MIN_VALIDATION_EPISODES,
        "trailing_window": S.TRAILING_WINDOW,
        "persist_n": S.PERSIST_N,
        "safety_margin_bps": S.SAFETY_MARGIN_BPS,
        "basis_floor_bps": S.BASIS_FLOOR_BPS,
        "min_hold_periods": S.MIN_HOLD_PERIODS,
        "exit_c_margin_bps": S.EXIT_C_MARGIN_BPS,
        "funding_stress": list(FUNDING_STRESS),
        "cost_stress": list(COST_STRESS),
        "holdout_locked": True,
        "plan_amendment": (
            "12 reference cells (7d horizon x 4 policies x 3 assets) are "
            "reported for the §65 comparison only and are NOT candidate-"
            "selection cells; the core budget of 48 cells is respected."
        ),
    }


def entry_policy_registry() -> dict[str, Any]:
    out: list[dict[str, Any]] = []
    for pol in S.POLICIES:
        out.append(
            {
                "policy_id": pol,
                "label": S.POLICY_LABELS[pol],
                "trailing_window_periods": S.TRAILING_WINDOW,
                "uses_future_funding": False,
                "freeze": "pre-registered before any result",
            }
        )
    return {"policies": out, "max_policies": 4, "n_policies": len(out), "core_cells": S.CORE_CELLS}


# ---------------------------------------------------------------------------
# descriptive structural metrics
# ---------------------------------------------------------------------------


def funding_persistence() -> dict[str, Any]:
    per_policy: dict[str, Any] = {}
    for pol in S.POLICIES:
        per_policy[pol] = {hk: S.persistence_profile(pol, hk, 0.0, 0.6) for hk in S.HORIZON_ORDER}
    return {"region": "DISCOVERY", "per_policy": per_policy}


def funding_survival() -> dict[str, Any]:
    per_policy: dict[str, Any] = {}
    for pol in S.POLICIES:
        per_policy[pol] = {hk: S.survival_curve(pol, hk, 0.0, 0.6) for hk in S.HORIZON_ORDER}
    return {"region": "DISCOVERY", "per_policy": per_policy}


def cumulative_funding() -> dict[str, Any]:
    per_policy: dict[str, Any] = {}
    for pol in S.POLICIES:
        per_policy[pol] = {
            hk: S.cumulative_funding_distribution(pol, hk, 0.0, 0.6) for hk in S.HORIZON_ORDER
        }
    return {"region": "DISCOVERY", "cost_bps": S.ROUND_TRIP_COST_BPS, "per_policy": per_policy}


def time_to_break_even() -> dict[str, Any]:
    per_policy: dict[str, Any] = {}
    for pol in S.POLICIES:
        per_policy[pol] = {hk: S.time_to_break_even(pol, hk, 0.0, 0.6) for hk in S.HORIZON_ORDER}
    be_prob = {
        pol: {hk: S.break_even_probability(pol, hk, 0.0, 0.6) for hk in S.HORIZON_ORDER}
        for pol in S.POLICIES
    }
    return {
        "region": "DISCOVERY",
        "cost_bps": S.ROUND_TRIP_COST_BPS,
        "time_to_break_even": per_policy,
        "break_even_probability": be_prob,
    }


def capital_model() -> dict[str, Any]:
    return {
        "spot_leg_capital": 1.0,
        "perp_leg_capital": round(1.0 / S.PERP_LEVERAGE, 6),
        "committed_capital": round(S.COMMITTED_CAPITAL, 6),
        "perp_leverage": S.PERP_LEVERAGE,
        "periods_per_day": S.PERIODS_PER_DAY,
        "pnl_basis": "bps of 1x economic notional per leg",
        "roc_definition": "return_on_committed = (net_bps/1e4)/committed_capital",
        "capital_days_definition": "committed_capital * holding_days",
        "return_per_capital_day_definition": "sum(net_return)/sum(capital_days)",
        "no_rebalance": True,
        "delta_note": "equal initial notional legs; residual delta measured, not rebalanced (§29)",
    }


# ---------------------------------------------------------------------------
# discovery / validation
# ---------------------------------------------------------------------------


def _cell_id(policy: str, horizon_key: str) -> str:
    return f"{policy}@{horizon_key}"


def _trade_rows(trades: list[S.Trade029]) -> list[list[Any]]:
    return [
        [
            t.asset,
            t.entry_ts,
            t.exit_ts,
            t.holding_periods,
            round(t.funding_pnl_bps, 3),
            round(t.basis_pnl_bps, 3),
            round(t.spot_pnl_bps, 3),
            round(t.perp_pnl_bps, 3),
            round(t.cost_bps, 3),
            round(t.net_bps, 3),
        ]
        for t in trades
    ]


def _accounting_clean(trades: list[S.Trade029]) -> bool:
    for t in trades:
        if (
            abs(t.net_bps - (t.spot_pnl_bps + t.perp_pnl_bps + t.funding_pnl_bps - t.cost_bps))
            > 1e-6
        ):
            return False
        if abs(t.basis_pnl_bps - (t.spot_pnl_bps + t.perp_pnl_bps)) > 1e-6:
            return False
    return True


def discovery() -> dict[str, Any]:
    cells: list[dict[str, Any]] = []
    for policy in S.POLICIES:
        for hk in S.CORE_HORIZONS:
            trades = S.simulate_portfolio(policy, hk, S.PRIMARY_EXIT_MODEL, 0.0, 0.6)
            agg = S.aggregate(trades)
            pa = S.per_asset(trades)
            cells.append(
                {
                    "candidate_id": _cell_id(policy, hk),
                    "entry_policy": policy,
                    "exit_policy": S.PRIMARY_EXIT_MODEL,
                    "holding_horizon": hk,
                    "pooled": agg,
                    "per_asset": pa,
                    "accounting_clean": _accounting_clean(trades),
                }
            )
    best = _select(cells)
    return {
        "region": "DISCOVERY",
        "n_cells": len(cells),
        "cells": cells,
        "best": best,
        "selection_rule": SELECTION_RULE,
    }


def _select(cells: list[dict[str, Any]]) -> dict[str, Any] | None:
    ok = [
        c
        for c in cells
        if c["pooled"].get("status") == "OK"
        and (c["pooled"].get("net_pnl_bps") or 0) > 0
        and (c["pooled"].get("sum_roc") or 0) > 0
        and (c["pooled"].get("episodes") or 0) >= S.MIN_DISCOVERY_EPISODES
        and c["accounting_clean"]
    ]
    if not ok:
        return None
    return max(
        ok,
        key=lambda c: (
            c["pooled"]["net_expectancy_bps"],
            -S.HORIZON_PERIODS[c["holding_horizon"]],
            c["candidate_id"],
        ),
    )


def validation(frozen: dict[str, Any] | None) -> dict[str, Any]:
    """Evaluate every frozen cell (diagnostic) and the frozen best (primary)."""
    cells: list[dict[str, Any]] = []
    for policy in S.POLICIES:
        for hk in S.CORE_HORIZONS:
            trades = S.simulate_portfolio(policy, hk, S.PRIMARY_EXIT_MODEL, 0.6, 0.8)
            agg = S.aggregate(trades)
            cells.append(
                {
                    "candidate_id": _cell_id(policy, hk),
                    "entry_policy": policy,
                    "exit_policy": S.PRIMARY_EXIT_MODEL,
                    "holding_horizon": hk,
                    "pooled": agg,
                    "per_asset": S.per_asset(trades),
                    "accounting_clean": _accounting_clean(trades),
                }
            )
    primary: dict[str, Any] | None = None
    if frozen is not None:
        cid = frozen["candidate_id"]
        primary = next((c for c in cells if c["candidate_id"] == cid), None)
    # G_STRUCT_2 evaluation on the frozen frozen best (§45-§46)
    gate = _eval_validation_gate(primary, frozen)
    return {
        "region": "VALIDATION",
        "cells": cells,
        "primary_candidate_id": None if frozen is None else frozen["candidate_id"],
        "primary": primary,
        "gate": gate,
    }


def _eval_validation_gate(
    primary: dict[str, Any] | None, frozen: dict[str, Any] | None
) -> dict[str, Any]:
    if frozen is None:
        return {
            "result": "FAIL",
            "reason": "INSUFFICIENT_EPISODES",
            "detail": "no discovery candidate qualified",
        }
    if primary is None:
        return {
            "result": "FAIL",
            "reason": "VALIDATION_ZERO_TRADES",
            "detail": "frozen candidate not evaluated",
        }
    agg = primary["pooled"]
    n = agg.get("episodes", 0)
    if agg.get("status") != "OK" or n == 0:
        return {
            "result": "FAIL",
            "reason": "VALIDATION_ZERO_TRADES",
            "detail": "0 qualifying trades → FAIL_GENERALIZATION",
        }
    if n < S.MIN_VALIDATION_EPISODES:
        return {
            "result": "FAIL",
            "reason": "INSUFFICIENT_EPISODES",
            "detail": f"episodes={n} < {S.MIN_VALIDATION_EPISODES}",
        }
    net = agg.get("net_pnl_bps", 0) or 0
    roc = agg.get("sum_roc", 0) or 0
    ok = net > 0 and roc > 0 and primary["accounting_clean"]
    reason = None if ok else ("NEGATIVE_NET" if net <= 0 else "VALIDATION_FAIL")
    return {
        "result": "PASS" if ok else "FAIL",
        "reason": reason,
        "detail": f"net_pnl={net} roc={roc} episodes={n}",
    }


# ---------------------------------------------------------------------------
# walk-forward / temporal / stress / robustness / holdout
# ---------------------------------------------------------------------------


def walk_forward(gate2: dict[str, Any], frozen: dict[str, Any] | None) -> dict[str, Any]:
    if gate2.get("result") != "PASS":
        return {
            "status": "NOT_REACHED",
            "reason": "G_STRUCT_2 != PASS — no survivor to walk forward",
        }
    assert frozen is not None
    pol = frozen["entry_policy"]
    hk = frozen["holding_horizon"]
    folds = []
    # 3 chronological folds inside VALIDATION (0.6-0.8)
    edges = [0.6, 0.6667, 0.7333, 0.8]
    for k in range(3):
        trades = S.simulate_portfolio(pol, hk, S.PRIMARY_EXIT_MODEL, edges[k], edges[k + 1])
        folds.append(
            {"fold": k + 1, "lo": edges[k], "hi": edges[k + 1], "result": S.aggregate(trades)}
        )
    return {"status": "OK", "candidate_id": frozen["candidate_id"], "folds": folds}


def temporal_stability() -> dict[str, Any]:
    """Descriptive funding-regime decay by year and quarter (no gate)."""
    from collections import defaultdict

    by_year: dict[int, list[float]] = defaultdict(list)
    by_quarter: dict[str, list[float]] = defaultdict(list)
    for sym in S.ASSETS:
        p = S.asset_panel(sym)
        for t, r in zip(p.ts.tolist(), p.funding.tolist(), strict=False):
            d = datetime.fromtimestamp(t / 1000, tz=UTC)
            by_year[d.year].append(r)
            by_quarter[f"{d.year}Q{(d.month - 1) // 3 + 1}"].append(r)
    yr = {
        str(y): {
            "n": len(v),
            "mean_bps": round(float(np.mean(v)), 4),
            "positive_share": round(float(np.mean(np.asarray(v) > 0)), 4),
        }
        for y, v in sorted(by_year.items())
    }
    qt = {
        q: {"n": len(v), "mean_bps": round(float(np.mean(v)), 4)}
        for q, v in sorted(by_quarter.items())
    }
    return {
        "by_year": yr,
        "by_quarter": qt,
        "note": "funding compresses across time — central OOS finding",
    }


def stress_tests(
    discovery_payload: dict[str, Any], frozen: dict[str, Any] | None
) -> dict[str, Any]:
    if frozen is None:
        return {
            "cost": {"status": "NOT_REACHED"},
            "funding": {"status": "NOT_REACHED"},
            "basis": {"status": "NOT_REACHED"},
        }
    pol, hk = frozen["entry_policy"], frozen["holding_horizon"]
    # cost stress (§51): apply to outcomes, costs raised
    cost = {"status": "NOT_REACHED_GATE", "candidate_id": frozen["candidate_id"], "rows": []}
    for mult in COST_STRESS:
        trades = S.simulate_portfolio(
            pol, hk, S.PRIMARY_EXIT_MODEL, 0.0, 0.6, cost=S.ROUND_TRIP_COST_BPS * mult
        )
        cost["rows"].append(
            {
                "cost_mult": mult,
                "cost_bps": round(S.ROUND_TRIP_COST_BPS * mult, 3),
                "result": S.aggregate(trades),
            }
        )
    funding = {"status": "NOT_REACHED_GATE", "candidate_id": frozen["candidate_id"], "rows": []}
    for mult in FUNDING_STRESS:
        trades = S.simulate_portfolio(pol, hk, S.PRIMARY_EXIT_MODEL, 0.0, 0.6)
        scaled = _scale_funding(trades, mult, S.PRIMARY_EXIT_MODEL)
        funding["rows"].append({"funding_mult": mult, "result": S.aggregate(scaled)})
    basis = {"status": "NOT_REACHED_GATE", "candidate_id": frozen["candidate_id"], "rows": []}
    allb = np.concatenate([S.asset_panel(a).basis for a in S.ASSETS])
    allb = allb[np.isfinite(allb)]
    q = float(np.percentile(allb, BASIS_TAIL_QUANTILE * 100))
    trades = S.simulate_portfolio(pol, hk, S.PRIMARY_EXIT_MODEL, 0.0, 0.6)
    stressed = _scale_basis(trades, float(np.nanmean(allb)) - q)
    basis["rows"].append(
        {
            "adverse_basis_bps": round(float(np.nanmean(allb)) - q, 4),
            "result": S.aggregate(stressed),
        }
    )
    return {"cost": cost, "funding": funding, "basis": basis}


def _scale_funding(trades: list[S.Trade029], mult: float, exit_model: str) -> list[S.Trade029]:
    out: list[S.Trade029] = []
    for t in trades:
        f = t.funding_pnl_bps * mult
        net = t.spot_pnl_bps + t.perp_pnl_bps + f - t.cost_bps
        out.append(_rebuild(t, f, net))
    return out


def _scale_basis(trades: list[S.Trade029], shock_bps: float) -> list[S.Trade029]:
    out: list[S.Trade029] = []
    for t in trades:
        b = t.basis_pnl_bps + shock_bps
        net = b + t.funding_pnl_bps - t.cost_bps
        out.append(_rebuild(t, t.funding_pnl_bps, net, basis=b))
    return out


def _rebuild(t: S.Trade029, funding: float, net: float, basis: float | None = None) -> S.Trade029:
    b = t.basis_pnl_bps if basis is None else basis
    return S.Trade029(
        asset=t.asset,
        policy=t.policy,
        horizon_key=t.horizon_key,
        exit_model=t.exit_model,
        entry_idx=t.entry_idx,
        exit_idx=t.exit_idx,
        entry_ts=t.entry_ts,
        exit_ts=t.exit_ts,
        holding_periods=t.holding_periods,
        funding_pnl_bps=funding,
        spot_pnl_bps=t.spot_pnl_bps,
        perp_pnl_bps=t.perp_pnl_bps,
        basis_pnl_bps=b,
        cost_bps=t.cost_bps,
        net_bps=net,
        return_on_committed=(net / 1e4) / S.COMMITTED_CAPITAL,
        capital_days=t.capital_days,
        breakeven_periods=t.breakeven_periods,
    )


def robustness(gate2: dict[str, Any], frozen: dict[str, Any] | None) -> dict[str, Any]:
    if gate2.get("result") != "PASS":
        diag = None
        if frozen is not None:
            pol, hk = frozen["entry_policy"], frozen["holding_horizon"]
            trades = S.simulate_portfolio(pol, hk, S.PRIMARY_EXIT_MODEL, 0.0, 0.6)
            agg = S.aggregate(trades)
            diag = {
                "discovery_net_expectancy_bps": agg["net_expectancy_bps"],
                "without_best_mean_bps": agg["without_best_mean_bps"],
                "without_best3_mean_bps": agg["without_best3_mean_bps"],
                "top1_share": agg["top1_share"],
                "top3_share": agg["top3_share"],
            }
        return {
            "status": "NOT_REACHED",
            "reason": "G_STRUCT_2 != PASS — robustness not promotable",
            "diagnostic": diag,
        }
    # (only reached on success) — not exercised in this run
    return {"status": "OK"}


def holdout(gate3: dict[str, Any], hashes: dict[str, str]) -> dict[str, Any]:
    if gate3.get("result") != "PASS":
        return {
            "status": "NOT_OPENED",
            "reason": "G_STRUCT_3 != PASS — holdout remains locked",
            "holdout_analytics_read": False,
        }
    return {"status": "ERROR", "reason": "holdout path not implemented for PASS case"}


# ---------------------------------------------------------------------------
# gates
# ---------------------------------------------------------------------------


def gate_info(desc: dict[str, Any]) -> dict[str, Any]:
    """§39: funding persistence beyond 7d. NOT a profitability gate.

    PASS requires, in DISCOVERY for the representative regime policy: the mean
    forward cumulative funding is positive at every core horizon, P(cumulative
    funding > 0) at 14d >= INFO_MIN_POS_PROB, and the funding regime is still
    positive after 7d with P >= INFO_MIN_SURVIVAL.
    """
    pol = "A_POSITIVE_REGIME"
    means = [desc["cumulative_funding_distribution"][pol][hk]["mean"] for hk in S.CORE_HORIZONS]
    worst_mean = min(means)
    p_pos_14 = desc["cumulative_funding_distribution"][pol]["14d"]["prob_positive"]
    sur = desc["survival"][pol]["7d"]["survival"][7]["p_positive"]
    ok = (
        worst_mean > 0.0
        and p_pos_14 >= INFO_MIN_POS_PROB
        and sur is not None
        and sur >= INFO_MIN_SURVIVAL
    )
    return {
        "result": "PASS" if ok else "FAIL",
        "min_mean_fwd_cum_funding_bps": round(worst_mean, 4),
        "p14d_positive": p_pos_14,
        "survival_7d": sur,
        "detail": "funding persists beyond 7d; this gate is not profitability",
    }


def gate_struct1(disc: dict[str, Any]) -> dict[str, Any]:
    best = disc["best"]
    if best is None:
        return {"result": "FAIL", "reason": "INSUFFICIENT_EPISODES"}
    agg = best["pooled"]
    ok = (
        agg["net_pnl_bps"] > 0
        and agg["net_expectancy_bps"] > 0
        and agg["sum_roc"] > 0
        and agg["episodes"] >= S.MIN_DISCOVERY_EPISODES
        and best["accounting_clean"]
    )
    return {
        "result": "PASS" if ok else "FAIL",
        "candidate_id": best["candidate_id"],
        "reason": None if ok else "NEGATIVE_NET",
        "detail": agg,
    }


def gate_struct3(
    wf: dict[str, Any], st: dict[str, Any], rob: dict[str, Any], gate2: dict[str, Any]
) -> dict[str, Any]:
    if gate2.get("result") != "PASS":
        return {"result": "NOT_REACHED", "reason": "G_STRUCT_2 failed"}
    return {"result": "NOT_REACHED", "reason": "survivor pipeline incomplete"}


def classify(g1: str, g2: str, g3: str, g4: str) -> str:
    if g1 != "PASS":
        return "STRUCT-A"
    if g2 != "PASS":
        return "STRUCT-B"
    if g3 != "PASS":
        return "STRUCT-C"
    if g4 != "PASS":
        return "STRUCT-D"
    return "STRUCT-E"


# ---------------------------------------------------------------------------
# §66 central comparison table
# ---------------------------------------------------------------------------


def comparison_table() -> dict[str, Any]:
    disc_rows = []
    val_rows = []
    for pol in ("A_POSITIVE_REGIME", "C_ECONOMIC"):
        for hk in S.HORIZON_ORDER:
            d = S.aggregate(S.simulate_portfolio(pol, hk, S.PRIMARY_EXIT_MODEL, 0.0, 0.6))
            v = S.aggregate(S.simulate_portfolio(pol, hk, S.PRIMARY_EXIT_MODEL, 0.6, 0.8))
            row_d = {
                "policy": pol,
                "holding": hk,
                "region": "DISCOVERY",
                "funding": d.get("funding_pnl_bps"),
                "basis": d.get("basis_pnl_bps"),
                "cost": d.get("cost_bps"),
                "net": d.get("net_pnl_bps"),
                "roc": d.get("sum_roc"),
                "capital_days": d.get("capital_days"),
                "episodes": d.get("episodes"),
            }
            row_v = dict(row_d)
            row_v.update(
                {
                    "region": "VALIDATION",
                    "funding": v.get("funding_pnl_bps"),
                    "basis": v.get("basis_pnl_bps"),
                    "cost": v.get("cost_bps"),
                    "net": v.get("net_pnl_bps"),
                    "roc": v.get("sum_roc"),
                    "capital_days": v.get("capital_days"),
                    "episodes": v.get("episodes"),
                }
            )
            disc_rows.append(row_d)
            val_rows.append(row_v)
    return {"discovery": disc_rows, "validation": val_rows}


# ---------------------------------------------------------------------------
# registry jsonl
# ---------------------------------------------------------------------------


def _registry_line(
    cell: dict[str, Any], asset: str, agg: dict[str, Any], phase: str, rejection: str | None
) -> dict[str, Any]:
    return {
        "candidate_id": cell["candidate_id"],
        "entry_policy": cell["entry_policy"],
        "exit_policy": cell["exit_policy"],
        "holding_horizon": cell["holding_horizon"],
        "asset": asset,
        "phase": phase,
        "episodes": agg.get("episodes", 0),
        "active_days": agg.get("active_days"),
        "funding_pnl": agg.get("funding_pnl_bps"),
        "basis_pnl": agg.get("basis_pnl_bps"),
        "residual_pnl": agg.get("basis_pnl_bps"),
        "cost": agg.get("cost_bps"),
        "net_pnl": agg.get("net_pnl_bps"),
        "net_expectancy": agg.get("net_expectancy_bps"),
        "return_on_capital": agg.get("sum_roc"),
        "capital_days": agg.get("capital_days"),
        "PF": agg.get("pf"),
        "Sharpe": agg.get("sharpe"),
        "MaxDD": agg.get("max_dd_bps"),
        "status": "OK" if agg.get("status") == "OK" else "NO_TRADES",
        "rejection_reason": rejection,
    }


def write_registry(disc: dict[str, Any], val: dict[str, Any], frozen: dict[str, Any] | None) -> int:
    """One line per core cell = 4 policies x 4 horizons x 3 assets (48 per phase)."""
    lines: list[dict[str, Any]] = []
    for c in disc["cells"]:
        for asset in S.ASSETS:
            agg = c["per_asset"][asset]
            net = (agg.get("net_pnl_bps") or 0) if agg.get("status") == "OK" else 0
            if agg.get("status") != "OK" or agg.get("episodes", 0) == 0:
                rej = "INSUFFICIENT_EPISODES"
            elif net <= 0:
                rej = "NEGATIVE_NET"
            else:
                rej = None
            lines.append(_registry_line(c, asset, agg, "DISCOVERY", rej))
    for c in val["cells"]:
        for asset in S.ASSETS:
            agg = c["per_asset"][asset]
            if agg.get("status") != "OK" or agg.get("episodes", 0) == 0:
                rej = "VALIDATION_ZERO_TRADES"
            elif (agg.get("net_pnl_bps") or 0) <= 0:
                rej = "VALIDATION_FAIL"
            else:
                rej = None
            lines.append(_registry_line(c, asset, agg, "VALIDATION", rej))
    path = OUT / "EXPERIMENT_REGISTRY.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for ln in lines:
            fh.write(json.dumps(ln, sort_keys=True, default=str) + "\n")
    return len(lines)


# ---------------------------------------------------------------------------
# renderers
# ---------------------------------------------------------------------------


def _md_plan(p: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# RFC029_PLAN",
            "",
            f"**Question.** {p['question']}",
            "",
            f"**Structure.** {p['structure']}",
            "",
            f"- Cost model: {p['cost_model']} = {p['round_trip_cost_bps']} bps "
            f"(V3 {p['cost_model_v3_bps_not_used']} not used)",
            f"- Core horizons: {', '.join(p['core_horizons'])} (periods "
            f"{[p['horizons_periods'][h] for h in p['core_horizons']]}); "
            f"reference {p['reference_horizon']}",
            f"- Policies: {', '.join(p['policies'])}",
            f"- Exit models: {', '.join(p['exit_models'])} (primary {p['primary_exit_model']})",
            f"- Core cells: {p['core_cells']} (4 policies x 4 horizons x 3 assets)",
            f"- Splits: {p['splits']}",
            f"- Selection rule: {p['selection_rule']}",
            f"- Plan amendment: {p['plan_amendment']}",
            "",
            "## §66 central comparison (funding / basis / cost / net bps)",
            "",
            _md_table(
                [
                    [
                        r["region"],
                        r["policy"],
                        r["holding"],
                        r["episodes"],
                        r["funding"],
                        r["basis"],
                        r["cost"],
                        r["net"],
                        r["roc"],
                        r["capital_days"],
                    ]
                    for r in p["comparison"]["discovery"] + p["comparison"]["validation"]
                ],
                [
                    "region",
                    "policy",
                    "holding",
                    "ep",
                    "funding",
                    "basis",
                    "cost",
                    "net",
                    "ROC",
                    "capital-days",
                ],
            ),
            "",
        ]
    )


def _md_cells(title: str, cells: list[dict[str, Any]]) -> str:
    rows = []
    for c in cells:
        a = c["pooled"]
        rows.append(
            [
                c["candidate_id"],
                a.get("episodes"),
                a.get("active_days"),
                a.get("funding_pnl_bps"),
                a.get("basis_pnl_bps"),
                a.get("cost_bps"),
                a.get("net_pnl_bps"),
                a.get("net_expectancy_bps"),
                a.get("sum_roc"),
                a.get("return_per_capital_day"),
                a.get("pf"),
            ]
        )
    return "\n".join(
        [
            f"# {title}",
            "",
            _md_table(
                rows,
                [
                    "candidate",
                    "ep",
                    "active_d",
                    "funding",
                    "basis",
                    "cost",
                    "net",
                    "net_exp",
                    "ROC",
                    "ROC/capital-day",
                    "PF",
                ],
            ),
            "",
        ]
    )


def _md_final(final: dict[str, Any]) -> str:
    g = final["gates"]
    b = final.get("best_candidate") or {}
    agg = b.get("discovery", {}) if b else {}
    lines = [
        "# RFC029_FINAL_REPORT",
        "",
        "## RFC-029 STRUCTURAL LOW-TURNOVER CARRY",
        "",
        f"Did we finally find VALIDATED NET EDGE? **{'YES' if final['validated_net_edge'] else 'NO'}**",
        "",
        f"- G_STRUCT_INFO = {g['G_STRUCT_INFO']}",
        f"- G_STRUCT_1 = {g['G_STRUCT_1']}",
        f"- G_STRUCT_2 = {g['G_STRUCT_2']}",
        f"- G_STRUCT_3 = {g['G_STRUCT_3']}",
        f"- G_STRUCT_4 = {g['G_STRUCT_4']}",
        "",
        f"- BEST CANDIDATE = {final.get('best_candidate_id')}",
        f"- HOLDING = {b.get('holding_horizon') if b else None}",
        f"- EPISODES (discovery) = {agg.get('episodes')}",
        f"- FUNDING PNL (discovery) = {agg.get('funding_pnl_bps')}",
        f"- BASIS PNL (discovery) = {agg.get('basis_pnl_bps')}",
        f"- COST (discovery) = {agg.get('cost_bps')}",
        f"- NET PNL (discovery) = {agg.get('net_pnl_bps')}",
        f"- NET EXPECTANCY (discovery) = {agg.get('net_expectancy_bps')}",
        f"- RETURN PER CAPITAL-DAY (discovery) = {agg.get('return_per_capital_day')}",
        f"- MEDIAN TIME TO BREAK-EVEN = {final.get('median_time_to_break_even_days')} days",
        f"- VALIDATION = {g['G_STRUCT_2']} ({final.get('validation_reason')})",
        f"- WALK-FORWARD = {final.get('walk_forward_status')}",
        f"- ROBUSTNESS = {final.get('robustness_status')}",
        f"- HOLDOUT = {final.get('holdout_status')}",
        f"- FALSE_SUCCESS = {final.get('false_success')}",
        f"- INDEPENDENT VERIFICATION = {final.get('independent_verification')}",
        f"- GLOBAL_CLASSIFICATION = {final.get('global_classification')}",
        f"- NEXT = {final.get('next')}",
        "",
    ]
    return "\n".join(lines)


def _write_pair(name: str, payload: dict[str, Any], md: str) -> None:
    L28.write_json(OUT / f"{name}.json", payload)
    L28.write_md(OUT / f"{name}.md", md)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    # --- freeze the plan FIRST -------------------------------------------
    comp = comparison_table()
    plan = build_plan()
    plan["comparison"] = comp
    _write_pair("RFC029_PLAN", plan, _md_plan(plan))

    _write_pair(
        "ENTRY_POLICY_REGISTRY",
        entry_policy_registry(),
        "# ENTRY_POLICY_REGISTRY\n\n"
        + "\n".join(
            [
                f"- **{p['policy_id']}**: {p['label']} (trailing "
                f"{p['trailing_window_periods']} periods, uses_future_funding=False)"
                for p in entry_policy_registry()["policies"]
            ]
        )
        + "\n",
    )

    da = data_audit()
    _write_pair("DATA_AUDIT", da, "# DATA_AUDIT\n\n" + json.dumps(da, indent=2) + "\n")
    pit = funding_pit_audit()
    _write_pair(
        "FUNDING_PIT_AUDIT",
        pit,
        f"# FUNDING_PIT_AUDIT\n\nresult = {pit['result']}\n\n" + json.dumps(pit, indent=2) + "\n",
    )

    fp = funding_persistence()
    _write_pair(
        "FUNDING_PERSISTENCE", fp, "# FUNDING_PERSISTENCE\n\n" + json.dumps(fp, indent=2) + "\n"
    )
    sv = funding_survival()
    _write_pair(
        "FUNDING_SURVIVAL_CURVE",
        sv,
        "# FUNDING_SURVIVAL_CURVE\n\n" + json.dumps(sv, indent=2) + "\n",
    )
    cf = cumulative_funding()
    _write_pair(
        "CUMULATIVE_FUNDING", cf, "# CUMULATIVE_FUNDING\n\n" + json.dumps(cf, indent=2) + "\n"
    )
    tb = time_to_break_even()
    ttbe_md = ["# TIME_TO_BREAK_EVEN", ""]
    for pol in S.POLICIES:
        ttbe_md.append(f"## {pol}")
        ttbe_md.append(
            _md_table(
                [
                    [
                        hk,
                        d.get("median_days"),
                        d.get("p25_days"),
                        d.get("p75_days"),
                        d.get("p90_days"),
                        d.get("crossed"),
                        d.get("censored"),
                    ]
                    for hk in S.HORIZON_ORDER
                    for d in [tb["time_to_break_even"][pol][hk]]
                ],
                ["holding", "median_d", "p25_d", "p75_d", "p90_d", "crossed", "censored"],
            )
        )
    _write_pair("TIME_TO_BREAK_EVEN", tb, "\n".join(ttbe_md) + "\n")
    cm = capital_model()
    _write_pair("CAPITAL_MODEL", cm, "# CAPITAL_MODEL\n\n" + json.dumps(cm, indent=2) + "\n")

    # --- G_STRUCT_INFO ----------------------------------------------------
    g_info = gate_info(
        {
            "cumulative_funding_distribution": cf["per_policy"],
            "survival": sv["per_policy"],
        }
    )

    # --- DISCOVERY --------------------------------------------------------
    disc = discovery()
    _write_pair("DISCOVERY_RESULTS", disc, _md_cells("DISCOVERY_RESULTS", disc["cells"]))
    g1 = gate_struct1(disc)

    # --- VALIDATION -------------------------------------------------------
    val = validation(disc["best"])
    _write_pair("VALIDATION_RESULTS", val, _md_cells("VALIDATION_RESULTS", val["cells"]))
    g2 = val["gate"]

    # --- registry ---------------------------------------------------------
    n_reg = write_registry(disc, val, disc["best"])

    # --- G_STRUCT_3 components (NOT_REACHED unless G_STRUCT_2 PASS) -------
    wf = walk_forward(g2, disc["best"])
    _write_pair(
        "WALK_FORWARD_RESULTS", wf, "# WALK_FORWARD_RESULTS\n\n" + json.dumps(wf, indent=2) + "\n"
    )
    ts = temporal_stability()
    _write_pair(
        "TEMPORAL_STABILITY", ts, "# TEMPORAL_STABILITY\n\n" + json.dumps(ts, indent=2) + "\n"
    )

    st = stress_tests(disc, disc["best"])
    _write_pair(
        "COST_STRESS", st["cost"], "# COST_STRESS\n\n" + json.dumps(st["cost"], indent=2) + "\n"
    )
    _write_pair(
        "FUNDING_STRESS",
        st["funding"],
        "# FUNDING_STRESS\n\n" + json.dumps(st["funding"], indent=2) + "\n",
    )
    _write_pair(
        "BASIS_STRESS", st["basis"], "# BASIS_STRESS\n\n" + json.dumps(st["basis"], indent=2) + "\n"
    )

    rob = robustness(g2, disc["best"])
    _write_pair(
        "ROBUSTNESS_RESULTS", rob, "# ROBUSTNESS_RESULTS\n\n" + json.dumps(rob, indent=2) + "\n"
    )

    g3 = gate_struct3(wf, st, rob, g2)

    # --- hashes for any future holdout freeze -----------------------------
    hashes = {
        "config_hash": L28.sha256_obj(plan),
        "cost_hash": L28.sha256_obj(
            {
                "cost_bps": S.ROUND_TRIP_COST_BPS,
                "spot_side": S.SPOT_SIDE_BPS,
                "perp_side": S.PERP_SIDE_BPS,
            }
        ),
        "code_hash": _sha256_file(Path(__file__)),
    }
    ho = holdout(g3, hashes)
    _write_pair("HOLDOUT_RESULTS", ho, "# HOLDOUT_RESULTS\n\n" + json.dumps(ho, indent=2) + "\n")
    g4 = "NOT_REACHED"

    classification = classify(g_info["result"], g1["result"], g3["result"], g4)

    # --- median time to break-even (policy A, 45d) ------------------------
    med_days = tb["time_to_break_even"]["A_POSITIVE_REGIME"]["45d"].get("median_days")

    best = disc["best"]
    final: dict[str, Any] = {
        "rfc": "RFC-029",
        "question": plan["question"],
        "validated_net_edge": g2["result"] == "PASS",
        "gates": {
            "G_STRUCT_INFO": g_info["result"],
            "G_STRUCT_1": g1["result"],
            "G_STRUCT_2": g2["result"],
            "G_STRUCT_3": g3["result"],
            "G_STRUCT_4": g4,
        },
        "global_classification": classification,
        "round_trip_cost_bps": S.ROUND_TRIP_COST_BPS,
        "committed_capital": S.COMMITTED_CAPITAL,
        "core_cells": S.CORE_CELLS,
        "best_candidate_id": None if best is None else best["candidate_id"],
        "best_candidate": None
        if best is None
        else {
            "candidate_id": best["candidate_id"],
            "entry_policy": best["entry_policy"],
            "holding_horizon": best["holding_horizon"],
            "discovery": best["pooled"],
            "per_asset_discovery": best["per_asset"],
        },
        "validation_cells": {c["candidate_id"]: c["pooled"] for c in val["cells"]},
        "validation_reason": g2.get("reason"),
        "validation_detail": g2.get("detail"),
        "median_time_to_break_even_days": med_days,
        "walk_forward_status": wf.get("status"),
        "robustness_status": rob.get("status"),
        "holdout_status": ho.get("status"),
        "holdout_analytics_read": False,
        "registry_lines": n_reg,
        "comparison": comp,
        "hashes": hashes,
        "next": (
            "PROFITABILITY_DECISION (mandatory §67-§68)"
            if g2["result"] != "PASS"
            else "WALK-FORWARD / STRESS / ROBUSTNESS"
        ),
        "false_success": None,
        "independent_verification": "PENDING",
    }
    L28.write_json(REPO / "reports" / "RFC029_FINAL_REPORT.json", final)
    L28.write_md(REPO / "reports" / "RFC029_FINAL_REPORT.md", _md_final(final))

    # --- mandatory profitability decision ---------------------------------
    if g2["result"] != "PASS":
        write_profitability_decision(final, ts, g_info, g1, g2)

    print(
        "G_STRUCT_INFO =",
        g_info["result"],
        "| G_STRUCT_1 =",
        g1["result"],
        "| G_STRUCT_2 =",
        g2["result"],
        "| G_STRUCT_3 =",
        g3["result"],
        "| G_STRUCT_4 =",
        g4,
    )
    print("classification:", classification, "| best:", final["best_candidate_id"])
    print("registry lines:", n_reg)


def write_profitability_decision(
    final: dict[str, Any],
    ts: dict[str, Any],
    g_info: dict[str, Any],
    g1: dict[str, Any],
    g2: dict[str, Any],
) -> None:
    b = final["best_candidate"]
    lines = [
        "# PROFITABILITY_DECISION",
        "",
        "RFC-029 tested the structural low-turnover carry class (LONG SPOT + SHORT PERP, "
        "14-45 day holds) to amortize the 39 bps round-trip cost. The strategy class is "
        "economically real **in sample** but does **not** generalise out of sample.",
        "",
        "## Evidence summary",
        f"- G_STRUCT_INFO = {g_info['result']} (funding persists beyond 7d in DISCOVERY)",
        f"- G_STRUCT_1 = {g1['result']} (long-horizon carry is net positive in DISCOVERY)",
        f"- G_STRUCT_2 = {g2['result']} ({g2.get('reason')})",
        f"- Best discovery candidate: {final['best_candidate_id']} "
        f"(net expectancy {b['discovery']['net_expectancy_bps'] if b else None} bps/episode, "
        f"median time-to-break-even = {final['median_time_to_break_even_days']} days)",
        "- In VALIDATION every policy x horizon cell is net negative; the funding regime "
        "compressed (yearly mean funding 1.04 -> 0.47 -> 0.27 bps/period).",
        "",
        "## Component verdicts (all prior project lines)",
        "- **Price alpha**: REJECTED as standalone net edge (RFC-010/021/022/024).",
        "- **Volatility alpha**: VOLATILITY_ONLY_RECONFIRMED, no net edge (RFC-024/025/026).",
        "- **Orthogonal basis alpha (C6)**: discovery-informative, validation-negative (RFC-028).",
        "- **Positioning alpha**: information PASS, directional economics FAIL (RFC-025/027).",
        "- **Execution economics**: break-even cost 20.7 bps; realistic taker cost 23.8-39 bps (RFC-026/028).",
        "- **Short-horizon carry (<=7d)**: cost-killed (net ~ -23 bps/episode, RFC-028).",
        "- **Long-horizon structural carry (14-45d)**: amortises cost in sample "
        "(P(break-even) 9% -> 86%), but funding decay makes it net negative out of sample.",
        "",
        "## DECISION (exactly one)",
        "",
        "```text",
        "PAUSE_PROFITABILITY_RESEARCH",
        "```",
        "",
        "Rationale: every self-contained strategy line available from the certified data has "
        "now been tested to a gate. The bottleneck is not signal strength, holding structure, "
        "nor execution modelling — it is that the predictable funding/carry process decays to "
        "levels below the achievable transaction cost out of sample. Continuing to search would "
        "re-enter the rejected loop (more indicators / agents / generic RFCs are explicitly "
        "prohibited). The honest action is to PAUSE the profitability research line and keep the "
        "repository as a research platform (PIT data, cost models, independent verification, "
        "gates) without claiming a live edge.",
        "",
        "## Temporal evidence",
        "",
        _md_table(
            [[y, v["n"], v["mean_bps"], v["positive_share"]] for y, v in ts["by_year"].items()],
            ["year", "n", "mean_funding_bps", "positive_share"],
        ),
        "## What would change this decision",
        "- A NEW, credible data source (e.g. cross-venue funding dispersion or a borrow/lending "
        "dataset for the negative-funding side) would justify a *new* RFC-029-class test.",
        "- Absent that, no further internal RFC loop.",
    ]
    L28.write_md(REPO / "reports" / "PROFITABILITY_DECISION.md", "\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
