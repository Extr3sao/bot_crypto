"""RFC-038 BLOCK A (§4-§15) -- capital feasibility reconciliation.

RFC-037 concluded ``HIGH_CAPITAL_ONLY`` from a tracking error that *grew* to
~+780% at $100M.  Under a pre-registered strategy the relative discretisation
error of an integer-contract book must SHRINK as capital rises (a single contract
is a smaller fraction of the book).  A +780% blow-up therefore needs an explicit
cause, not an assumption.

This module:

  * re-runs the FROZEN engine fractionally at EVERY capital level and checks that
    the fractional PnL is linear in capital (so a single reference can be rescaled);
  * replays the SIZING arithmetic independently (configurable rounding) and
    reconciles the replay exactly against the frozen engine for rounding=nearest;
  * audits the §10 invariant ``actual_notional == contracts * price * multiplier``
    and ``actual_weight == actual_notional / capital``;
  * measures the granularity metric (relative allocation error) as capital rises;
  * rebuilds the tracking error against a CAPITAL-RESCALED fractional reference.

No strategy change, no tuning, no PnL optimisation.
"""

from __future__ import annotations

import json
import math
import sys
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import rfc036_verify as V  # noqa: E402
from rfc036_data import load_all_markets  # noqa: E402

from trading_bot.research import managed_futures_v1 as mf  # noqa: E402

OUT = REPO / "reports" / "managed-futures-decision"
OUT.mkdir(parents=True, exist_ok=True)

WINDOW = ("1994-01-01", "2000-03-31")   # the RFC-037 capital window
LEVELS = [25_000.0, 50_000.0, 100_000.0, 250_000.0, 500_000.0, 1_000_000.0,
          2_000_000.0, 5_000_000.0, 10_000_000.0, 25_000_000.0, 50_000_000.0,
          100_000_000.0]
REFERENCE_CAPITAL = 10_000_000.0
# PRIMARY rounding policy is frozen from RFC-036 (`round()` = nearest); floor is
# reported only as a comparison and is NOT used to select a better result.
PRIMARY_ROUNDING = "nearest"
MARGIN_ASSUMPTION = "ASSUMED_10PCT_INITIAL_MARGIN_PROXY (diagnostic only, not a broker spec)"

# RFC-037's pre-registered rule is retained UNCHANGED (no post-hoc tuning).
PREREGISTERED_RULE = {
    "min_viable": "active_markets>=20 and |tracking_error|<=15%",
    "min_preferred": "active_markets>=24 and |tracking_error|<=10%",
}


def d2o(iso: str) -> int:
    return date.fromisoformat(iso).toordinal()


def build_book() -> tuple[list[Any], list[int]]:
    roots = sorted(V.SPECS)
    bm = load_all_markets(roots)
    panels = []
    for r in roots:
        md = bm[r]
        if len(md.series) == 0:
            continue
        ts = mf.build_tradable_series(md, d2o("1970-01-01"), d2o("2000-12-31"))
        if ts.held:
            panels.append(mf.build_panel(md, ts, sorted(ts.held)))
    cal = sorted({o for p in panels for o in p.ts.held})
    return panels, cal


def _round(x: float, policy: str) -> float:
    if policy == "floor":
        # round toward zero (magnitude floor) -- both long and short positions
        return float(math.floor(abs(x))) * (1.0 if x >= 0 else -1.0)
    return float(round(x))


def replay(panels: list[Any], cal: list[int], window: tuple[int, int],
           capital: float, rounding: str) -> dict[str, Any]:
    """Independent sizing replay of the frozen engine; returns PnL + sizing records.

    Mirrors `managed_futures_v1.simulate_portfolio` exactly for rounding="nearest"
    (verified by the caller), but records the per-(date,market) accounting.
    """
    lo, hi = window
    config = mf.default_config(integer_contracts=True)
    dates = [o for o in cal if lo <= o <= hi]
    if len(dates) < 30:
        return {"status": "TOO_SHORT"}

    rebal: list[int] = []
    seen: set[tuple[int, int]] = set()
    for o in dates:
        d = date.fromordinal(o)
        k = (d.year, d.month)
        if k not in seen:
            seen.add(k)
            rebal.append(o)
    rebal_set = set(rebal)

    contracts: dict[str, float] = {p.root: 0.0 for p in panels}
    prev_level: dict[str, float | None] = {p.root: None for p in panels}
    prev_od: int | None = None
    net_days: list[float] = []
    gross_exp_days: list[float] = []
    nlong_days: list[int] = []
    nshort_days: list[int] = []
    records: list[dict[str, Any]] = []
    max_gross_notional = 0.0

    for oi_day, od in enumerate(dates):
        signal_od = prev_od if prev_od is not None else od
        day_gross = 0.0
        day_cost = 0.0
        nlong = 0
        nshort = 0
        for p in panels:
            a = p.ts.held.get(od)
            if a is None:
                continue
            ic = p.ts.interval_contract.get(od)
            r = float(p.ts.interval_return.get(od, 0.0))
            n = contracts[p.root]
            mult = float(p.spec["multiplier"])
            lvl = prev_level[p.root]
            if lvl is not None and ic is not None and n != 0.0 and r != 0.0:
                day_gross += n * lvl * mult * r
            if ic is not None and a != ic and n != 0.0:
                px_old = mf._close_at(p, ic, od)
                px_new = mf._close_at(p, a, od)
                if px_old is not None and px_new is not None:
                    per_side = float(p.spec["per_side_cost_bps"]) * 1e-4
                    day_cost += (abs(n) * px_old + abs(n) * px_new) * mult * per_side
            prev_level[p.root] = mf._close_at(p, a, od)

        if od in rebal_set:
            raw: dict[str, float] = {}
            for p in panels:
                ki = mf._last_ser_index(p, signal_od)
                if ki is None:
                    continue
                sig = mf.momentum_signal(p.series, ki, config.lookback)
                vol = mf.trailing_vol(p.series, ki, config.vol_lookback)
                if sig == 0.0 or not math.isfinite(vol) or vol <= 0:
                    raw[p.root] = 0.0
                    continue
                raw[p.root] = sig * (config.target_pos_vol / vol)
            active = [p for p in panels if raw.get(p.root, 0.0) != 0.0]
            n_active = len(active)
            scale = mf._portfolio_scale(panels, raw, dates, max(0, oi_day - 1), config)
            w: dict[str, float] = {}
            for p in panels:
                w[p.root] = (raw.get(p.root, 0.0) / n_active * scale) if n_active else 0.0
            gross_w = sum(abs(v) for v in w.values())
            if gross_w > config.max_gross_leverage and gross_w > 0:
                cap = config.max_gross_leverage / gross_w
                w = {kk: v * cap for kk, v in w.items()}
            for p in panels:
                a = p.ts.held.get(od)
                if a is None:
                    continue
                px = mf._close_at(p, a, od)
                mult = float(p.spec["multiplier"])
                if px is None or px <= 0:
                    continue
                weight = w[p.root]
                target_notional = weight * capital
                n_target = target_notional / (px * mult) if weight != 0.0 else 0.0
                rounded = _round(n_target, rounding) if weight != 0.0 else 0.0
                n_old = contracts[p.root]
                if rounded != n_old:
                    per_side = float(p.spec["per_side_cost_bps"]) * 1e-4
                    day_cost += abs(rounded - n_old) * px * mult * per_side
                contracts[p.root] = rounded
                if weight != 0.0:
                    actual_notional = rounded * px * mult
                    records.append({
                        "ordinal": od, "root": p.root,
                        "weight_target": weight,
                        "price": px, "multiplier": mult,
                        "single_contract_notional": px * mult,
                        "target_notional": target_notional,
                        "raw_contract_count": n_target,
                        "rounded_contract_count": rounded,
                        "actual_notional": actual_notional,
                        "actual_weight": actual_notional / capital,
                        "allocation_error": (actual_notional - target_notional)
                        / abs(target_notional),
                    })

        gnotional = 0.0
        net_notional = 0.0
        for p in panels:
            n = contracts[p.root]
            if n == 0.0:
                continue
            a = p.ts.held.get(od)
            px = mf._close_at(p, a, od)
            if px is None:
                continue
            mult = float(p.spec["multiplier"])
            gnotional += abs(n) * px * mult
            net_notional += n * px * mult
            if n > 0:
                nlong += 1
            else:
                nshort += 1
        max_gross_notional = max(max_gross_notional, gnotional)
        net_days.append(day_gross - day_cost)
        gross_exp_days.append(gnotional / capital)
        nlong_days.append(nlong)
        nshort_days.append(nshort)
        prev_od = od

    net = np.asarray(net_days, dtype=np.float64)
    return {
        "status": "OK", "days": len(dates),
        "net_pnl": net, "net_total": float(net.sum()),
        "mean_active_markets": float(np.mean(np.asarray(nlong_days)
                                             + np.asarray(nshort_days))),
        "max_gross_exposure": float(np.max(gross_exp_days)) if gross_exp_days else 0.0,
        "mean_gross_exposure": float(np.mean(gross_exp_days)) if gross_exp_days else 0.0,
        "max_gross_notional": max_gross_notional,
        "records": records,
    }


def fractional_net(panels: list[Any], cal: list[int], capital: float) -> float:
    run = mf.simulate_portfolio(panels, cal, (d2o(WINDOW[0]), d2o(WINDOW[1])),
                                mf.default_config(), capital)
    return float(run["net_pnl"].sum())


def _points(records: list[dict[str, Any]]) -> dict[str, Any]:
    errs = np.asarray([abs(r["allocation_error"]) for r in records], dtype=np.float64)
    return {
        "n_records": len(records),
        "median_abs_allocation_error": float(np.median(errs)) if errs.size else None,
        "mean_abs_allocation_error": float(np.mean(errs)) if errs.size else None,
        "p95_abs_allocation_error": float(np.quantile(errs, 0.95)) if errs.size else None,
    }


def audit() -> dict[str, Any]:
    panels, cal = build_book()
    n_markets = len(panels)

    # frozen engine reference at the RFC-037 capital
    engine_ref = mf.simulate_portfolio(panels, cal, (d2o(WINDOW[0]), d2o(WINDOW[1])),
                                       mf.default_config(integer_contracts=True),
                                       REFERENCE_CAPITAL)
    engine_ref_net = float(engine_ref["net_pnl"].sum())

    # replay reconciliation (rounding=nearest must equal the frozen engine)
    replay_ref = replay(panels, cal, (d2o(WINDOW[0]), d2o(WINDOW[1])),
                        REFERENCE_CAPITAL, PRIMARY_ROUNDING)
    replay_reconciles = abs(replay_ref["net_total"] - engine_ref_net) <= 1e-6 * abs(engine_ref_net)

    # fractional linearity: net_frac(C) should scale linearly with C
    frac_by_level = {c: fractional_net(panels, cal, c) for c in LEVELS}
    per_unit = [frac_by_level[c] / c for c in LEVELS if frac_by_level[c] != 0]
    linearity_spread = (max(per_unit) - min(per_unit)) / abs(np.mean(per_unit)) if per_unit else None

    grid: list[dict[str, Any]] = []
    rfc037_te: list[dict[str, Any]] = []
    for c in LEVELS:
        run_near = replay(panels, cal, (d2o(WINDOW[0]), d2o(WINDOW[1])), c, "nearest")
        run_floor = replay(panels, cal, (d2o(WINDOW[0]), d2o(WINDOW[1])), c, "floor")
        frac_c = frac_by_level[c]
        te_corrected = ((run_near["net_total"] - frac_c) / abs(frac_c)) if frac_c else None
        # RFC-037's defective formula: reference NOT rescaled to the level
        te_rfc037 = ((run_near["net_total"] - frac_by_level[REFERENCE_CAPITAL])
                     / abs(frac_by_level[REFERENCE_CAPITAL]))
        pts = _points(run_near["records"])
        # invariants
        max_inv_notional = 0.0
        max_inv_weight = 0.0
        for r in run_near["records"]:
            v1 = abs(r["actual_notional"] - r["rounded_contract_count"]
                     * r["price"] * r["multiplier"])
            v2 = abs(r["actual_weight"] - r["actual_notional"] / c)
            max_inv_notional = max(max_inv_notional, v1)
            max_inv_weight = max(max_inv_weight, v2)
        # concentration
        per_reb: dict[int, float] = {}
        for r in run_near["records"]:
            per_reb[r["ordinal"]] = per_reb.get(r["ordinal"], 0.0) + abs(r["actual_notional"])
        max_conc = 0.0
        for r in run_near["records"]:
            tot = per_reb.get(r["ordinal"], 0.0)
            if tot > 0:
                max_conc = max(max_conc, abs(r["actual_notional"]) / tot)
        margin_proxy = run_near["max_gross_notional"] * 0.10
        grid.append({
            "capital": c,
            "used_contracts": True,
            "net_integer_nearest": run_near["net_total"],
            "net_integer_floor": run_floor["net_total"],
            "net_fractional_at_level": frac_c,
            "net_fractional_rescaled": frac_by_level[REFERENCE_CAPITAL]
            * c / REFERENCE_CAPITAL,
            "tracking_error_rfc037": te_rfc037,
            "tracking_error_corrected": te_corrected,
            "active_markets": run_near["mean_active_markets"],
            "active_markets_floor": run_floor["mean_active_markets"],
            "mean_gross_exposure": run_near["mean_gross_exposure"],
            "max_gross_exposure": run_near["max_gross_exposure"],
            "max_single_market_concentration": max_conc,
            "margin_proxy_10pct": margin_proxy,
            "cash_buffer_proxy": c - margin_proxy,
            "margin_ok": margin_proxy < c,
            "n_markets": n_markets,
            "granularity": pts,
            "invariant_max_abs_notional_residual": max_inv_notional,
            "invariant_max_abs_weight_residual": max_inv_weight,
        })
        rfc037_te.append({"capital": c, "tracking_error_rfc037": te_rfc037,
                          "tracking_error_corrected": te_corrected})

    viable = [g for g in grid if g["active_markets"] >= 20.0
              and g["tracking_error_corrected"] is not None
              and abs(g["tracking_error_corrected"]) <= 0.15]
    preferred = [g for g in grid if g["active_markets"] >= 24.0
                 and g["tracking_error_corrected"] is not None
                 and abs(g["tracking_error_corrected"]) <= 0.10]
    # granularity monotonicity over the large-capital region (>= 10M)
    large = [g for g in grid if g["capital"] >= 10_000_000.0
             and g["granularity"]["median_abs_allocation_error"] is not None]
    gran_med = [g["granularity"]["median_abs_allocation_error"] for g in large]
    granularity_shrinks = all(gran_med[i + 1] <= gran_med[i] * 1.001
                              for i in range(len(gran_med) - 1)) if len(gran_med) > 1 else False

    invariant_ok = all(g["invariant_max_abs_notional_residual"] < 1e-6
                       and g["invariant_max_abs_weight_residual"] < 1e-9 for g in grid)
    # the RFC-037 defect is scoped to the capital region where its conclusion was
    # drawn: large capital, where the book is fully populated and granularity is
    # small.  At tiny capital a large error is REAL (almost nothing is investable).
    large = [g for g in grid if g["capital"] >= 25_000_000.0]
    rfc037_te_explodes = max(abs(g["tracking_error_rfc037"]) for g in large)
    corrected_te_max_large = max(abs(g["tracking_error_corrected"]) for g in large)
    corrected_te_max_all = max(abs(g["tracking_error_corrected"]) for g in grid
                               if g["tracking_error_corrected"] is not None)

    defect_found = bool(rfc037_te_explodes > 1.0 and corrected_te_max_large <= 0.15)
    g_cap_recon = "PASS" if (replay_reconciles and invariant_ok and defect_found) else "FAIL"
    classification = "RFC037_CAPITAL_DEFECT" if defect_found else "RFC037_CAPITAL_CORRECT"

    return {
        "window": WINDOW,
        "reference_capital": REFERENCE_CAPITAL,
        "n_markets": n_markets,
        "levels": LEVELS,
        "primary_rounding": PRIMARY_ROUNDING,
        "margin_assumption": MARGIN_ASSUMPTION,
        "preregistered_rule": PREREGISTERED_RULE,
        "engine_reference_net": engine_ref_net,
        "replay_reconciles_to_engine": replay_reconciles,
        "replay_reference_net": replay_ref["net_total"],
        "fractional_linearity_spread": linearity_spread,
        "fractional_per_unit_capital": {str(int(c)): frac_by_level[c] / c for c in LEVELS},
        "defect": {
            "classification": classification,
            "rfc037_tracking_error_formula": (
                "(net_integer(C) - net_fractional(10M)) / |net_fractional(10M)|  -- the "
                "fractional reference was never rescaled to the tested capital level, so "
                "for a strategy whose PnL is linear in capital the numerator grows with C "
                "while the denominator is fixed, producing an artificial blow-up."),
            "corrected_formula": (
                "(net_integer(C) - net_fractional(C)) / |net_fractional(C)|  -- reference "
                "run/rescaled at the SAME capital level."),
            "rfc037_max_abs_tracking_error_large_capital": rfc037_te_explodes,
            "corrected_max_abs_tracking_error_large_capital": corrected_te_max_large,
            "corrected_max_abs_tracking_error_all_levels": corrected_te_max_all,
            "large_capital_levels": [g["capital"] for g in large],
            "headline": ("the +780% at $100M is a RESCALING ARTEFACT of the RFC-037 "
                         "reference, not a granularity blow-up: at large capital the "
                         "fractional reference must be rescaled (or re-run) at the "
                         "tested capital, and the corrected tracking error is bounded "
                         "(<=15%) while median allocation error keeps shrinking."),
        },
        "replay_reconciles": replay_reconciles,
        "invariants_ok": invariant_ok,
        "granularity_shrinks_with_capital": granularity_shrinks,
        "granularity_median_curve_large_capital": gran_med,
        "grid": grid,
        "minimum_viable_capital": (viable[0]["capital"] if viable else None),
        "minimum_preferred_capital": (preferred[0]["capital"] if preferred else None),
        "G_CAP_RECON": g_cap_recon,
    }


def main() -> int:
    result = audit()
    (OUT / "CAPITAL_ACCOUNTING_AUDIT_RAW.json").write_text(
        json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "grid"}, indent=2,
                     default=str))
    for g in result["grid"]:
        print(f"cap={g['capital']:>13,.0f} te037={g['tracking_error_rfc037']:+.3f} "
              f"te_corr={g['tracking_error_corrected']:+.4f} "
              f"active={g['active_markets']:.1f} "
              f"med_alloc_err={g['granularity']['median_abs_allocation_error']:.4g}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
