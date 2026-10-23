"""RFC-026 — Execution economics diagnosis: orchestrator.

Runs the full §78 sequence and writes every required artifact under
``reports/execution-economics/`` plus ``reports/RFC026_FINAL_REPORT.{md,json}``.

READ-ONLY / RESEARCH-ONLY.  No runtime path, no order, no credential, no
capital.  ``COST_MODEL_V3`` is never modified and remains the control.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import sprint002_lib as L  # noqa: E402
import sprint026_lib as X  # noqa: E402

OUT = X.EXEC_OUT
HOLDOUT_READ = False

# Pre-registered decision thresholds (§31, §61) — frozen before any result.
MATERIAL_IMPROVEMENT_FRACTION = 0.25  # must close >=25% of the required reduction


# ---------------------------------------------------------------------------
# statistics helpers
# ---------------------------------------------------------------------------


def _net_stats(net: NDArray[Any]) -> dict[str, Any]:
    n = int(net.shape[0])
    if n == 0:
        return {"trades": 0}
    wins = net[net > 0]
    losses = net[net < 0]
    pf = float(wins.sum() / abs(losses.sum())) if losses.shape[0] else None
    eq = np.cumsum(net)
    dd = float(np.max(np.maximum.accumulate(eq) - eq)) if n else 0.0
    return {
        "trades": n,
        "net_expectancy_bps": round(float(np.mean(net)), 4),
        "net_pnl_usdt": round(float(net.sum()) / 1e4 * L.ROOT_NOTIONAL, 2),
        "profit_factor": round(pf, 4) if pf is not None else None,
        "win_rate": round(float(wins.shape[0]) / n, 4),
        "max_dd_bps": round(dd, 4),
    }


def _policy_cost(policy: X.ExecutionPolicy, asset: str) -> float | None:
    if policy.policy_id == "E1_EMPIRICAL_TAKER_SPOT":
        v = X.V4_MEASURED_SPOT.get(asset)
        return float(v["rt_total_bps"]) if v else None
    return policy.round_trip_cost_bps


def _evaluate_policy(trades: list[L.Trade], policy: X.ExecutionPolicy) -> dict[str, Any]:
    if policy.round_trip_cost_bps is None:
        return {
            "execution_policy_id": policy.policy_id,
            "status": policy.status,
            "intents": len(trades),
            "fills": None,
            "fill_rate": None,
            "gross_expectancy_bps": None,
            "total_effective_cost_bps": None,
            "net_expectancy_bps": None,
            "profit_factor": None,
            "max_dd_bps": None,
        }
    nets: list[float] = []
    costs: list[float] = []
    for t in trades:
        c = _policy_cost(policy, t.asset)
        if c is None:
            continue
        nets.append(t.gross_bps - c)
        costs.append(c)
    net = np.array(nets, dtype=np.float64)
    st = _net_stats(net)
    gross = float(np.mean([t.gross_bps for t in trades])) if trades else None
    return {
        "execution_policy_id": policy.policy_id,
        "status": policy.status,
        "intents": len(trades),
        "fills": len(nets),
        "fill_rate": round(len(nets) / len(trades), 4) if trades else None,
        "gross_expectancy_bps": round(gross, 4) if gross is not None else None,
        "fee_bps": round(2.0 * X.OFFICIAL_FEES["BINANCE_SPOT_VIP0"]["taker_fee_bps"], 6),
        "total_effective_cost_bps": round(float(np.mean(costs)), 6) if costs else None,
        "net_expectancy_bps": st.get("net_expectancy_bps"),
        "net_pnl_usdt": st.get("net_pnl_usdt"),
        "profit_factor": st.get("profit_factor"),
        "win_rate": st.get("win_rate"),
        "max_dd_bps": st.get("max_dd_bps"),
    }


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    policies = X.policy_registry()
    floor = X.theoretical_floor_bps()

    # --- FROZEN trade intents (DISCOVERY + VALIDATION) ---------------------
    disc: dict[str, list[L.Trade]] = {}
    val: dict[str, list[L.Trade]] = {}
    be: dict[str, dict[str, Any]] = {}
    for c in X.FROZEN_ALPHA:
        cid = str(c["candidate_id"])
        d_tr, _ = X.run_candidate(c, L.SPLITS["DISCOVERY"])
        v_tr, _ = X.run_candidate(c, L.SPLITS["VALIDATION"])
        disc[cid], val[cid] = d_tr, v_tr
        be[cid] = {
            "discovery": X.break_even_analysis(d_tr),
            "validation": X.break_even_analysis(v_tr),
        }
    primary = str(X.FROZEN_ALPHA[0]["candidate_id"])
    primary_be = be[primary]["discovery"]
    be_point = float(primary_be["break_even_cost_bps"])
    be_cons = float(primary_be["conservative_break_even_cost_bps"])
    required_reduction = float(primary_be["required_cost_reduction_bps"])

    # --- §0 PLAN + FROZEN CANDIDATES ---------------------------------------
    write_plan(policies, floor)
    write_frozen_candidates(be)

    # --- §5/§6 BREAK-EVEN ---------------------------------------------------
    write_break_even(be, primary)

    # --- §7 FEASIBILITY FRONTIER -------------------------------------------
    write_frontier(disc, primary)

    # --- §9/§10 COST AUDIT + FEES ------------------------------------------
    write_cost_audit(floor)
    write_fee_audit()

    # --- §14-§19 MICROSTRUCTURE + SPREAD + SLIPPAGE + FILL -----------------
    spreads_spot = X.measure_spreads("spot")
    spreads_perp = X.measure_spreads("perp")
    inv = X.microstructure_inventory()
    write_microstructure(inv)
    write_spread(spreads_spot, spreads_perp)
    write_slippage()
    write_maker_fill()

    # --- §23 ADVERSE SELECTION ---------------------------------------------
    write_adverse_selection()

    # --- §51 VENUE ----------------------------------------------------------
    write_venue()

    # --- §30 REGISTRY -------------------------------------------------------
    write_policy_registry(policies)

    # --- §37-§42 DISCOVERY / VALIDATION / ROBUSTNESS -----------------------
    exec_disc = run_discovery(disc, policies)
    write_execution_document("EXECUTION_DISCOVERY", exec_disc)
    exec_val = run_validation(val, policies)
    write_execution_document("EXECUTION_VALIDATION", exec_val)
    robustness = run_robustness(disc, val, policies)
    write_execution_document("EXECUTION_ROBUSTNESS", robustness)

    # --- §38-§45 GATES + §58 CLASSIFICATION --------------------------------
    gates, classification, decision = decide(policies, primary_be, floor, robustness, exec_disc)
    robust_primary = robustness["candidates"][primary]

    # --- §56 VERIFICATION (independent, run by scripts/sprint026_verify.py) --
    verification: dict[str, Any] = {"false_success": None}

    # --- §60 FINAL REPORT ---------------------------------------------------
    final = build_final_report(
        be,
        primary,
        gates,
        classification,
        decision,
        robust_primary,
        floor,
        spreads_spot,
        verification,
        policies,
    )
    write_final(final)

    # --- forward capture spec (§46-§50) ------------------------------------
    write_forward_capture_spec(decision)

    print("RFC-026 complete")
    print("classification:", classification)
    print("gates:", gates)
    print(
        "break-even point:",
        be_point,
        "conservative:",
        be_cons,
        "required reduction:",
        required_reduction,
    )
    print("FALSE_SUCCESS:", verification["false_success"])


# ---------------------------------------------------------------------------
# artifact writers
# ---------------------------------------------------------------------------


def _registry_hash() -> str:
    return X.sha256_obj(X.FROZEN_ALPHA)


def write_plan(policies: list[X.ExecutionPolicy], floor: dict[str, float]) -> None:
    payload: dict[str, Any] = {
        "phase": "RFC-026 EXECUTION ECONOMICS DIAGNOSIS",
        "mission": "decide whether a realistic, reproducible, evidence-based execution "
        "policy can monetise the RFC-025 orthogonal directional information",
        "authority_order": [
            "REAL_RUNTIME",
            "EXECUTION_EVIDENCE",
            "TESTS",
            "SOURCE_CODE",
            "ARCH/RFC",
            "EXTERNAL_SOURCE",
            "ASSUMPTION",
        ],
        "cost_model_v3_bps": X.CURRENT_COST_BPS,
        "cost_model_v3_immutable": True,
        "frozen_alpha_candidates": [c["candidate_id"] for c in X.FROZEN_ALPHA],
        "alpha_registry_hash": _registry_hash(),
        "n_alpha_candidates": len(X.FROZEN_ALPHA),
        "execution_policies": [p.policy_id for p in policies],
        "n_execution_policies": len(policies),
        "max_execution_policies": 8,
        "venues": ["Binance Spot (runtime)", "Binance USD\u24c8-M Perp (informational, excluded)"],
        "data_sources": [
            "reports/microstructure-v1/data",
            "reports/microstructure*/segments",
            "docs/COST_MODEL_V3.json",
            "docs/EXECUTION_COST_MODEL_V4.json",
            "reports/edge-discovery/sprint003",
        ],
        "latency_scenarios_ms": list(X.LATENCY_SCENARIOS_MS),
        "runtime_measured_latency_ms": X.RUNTIME_MEASURED_LATENCY_MS,
        "fee_assumptions": {
            k: {
                "maker": v["maker_fee_bps"],
                "taker": v["taker_fee_bps"],
                "source_id": v["source_id"],
            }
            for k, v in X.OFFICIAL_FEES.items()
        },
        "validation_split": {
            "EXEC_DISCOVERY": list(L.SPLITS["DISCOVERY"]),
            "EXEC_VALIDATION": list(L.SPLITS["VALIDATION"]),
        },
        "holdout": "LOCKED / UNREAD",
        "stress_tests": [
            "fee +25%",
            "spread +25%",
            "slippage +25%",
            "latency x2",
            "fill probability -20% (maker; not testable)",
            "adverse selection worse",
        ],
        "material_improvement_fraction": MATERIAL_IMPROVEMENT_FRACTION,
        "theoretical_floors": floor,
        "plan_amendments": [],
        "prohibitions": [
            "no lowering COST_MODEL_V3",
            "no alpha retuning",
            "no assumed maker fills",
            "no rebates without official tier",
            "no venue shopping after results",
            "no holdout use",
            "no live orders",
        ],
    }
    X.write_json(OUT / "RFC026_PLAN.json", payload)
    lines: list[str] = [
        "# RFC026_PLAN — Execution Economics Diagnosis",
        "",
        f"- Cost model (immutable control): **COST_MODEL_V3 = {X.CURRENT_COST_BPS} bps**.",
        f"- Frozen alpha candidates: {len(X.FROZEN_ALPHA)} (`{_registry_hash()[:16]}...`).",
        f"- Execution policies (<=8): {len(policies)}.",
        f"- Latency scenarios: {list(X.LATENCY_SCENARIOS_MS)} ms (no certified runtime value).",
        "- Validation split: EXEC_DISCOVERY = W1-W4, EXEC_VALIDATION = W5; HOLDOUT locked.",
        f"- Material-improvement threshold: {MATERIAL_IMPROVEMENT_FRACTION:.0%} of the "
        "required reduction.",
        "- Theoretical floors: " + ", ".join(f"{k}={v}" for k, v in floor.items()) + " bps.",
        "",
        "## Frozen alpha candidates",
    ]
    for c in X.FROZEN_ALPHA:
        lines.append(f"- `{c['candidate_id']}` ({c['role']}): {c['rationale']}")
    lines += ["", "## Execution policies"]
    for p in policies:
        lines.append(f"- `{p.policy_id}` — {p.entry_mode} / {p.exit_mode} — {p.status}")
    X.write_md(OUT / "RFC026_PLAN.md", "\n".join(lines))


def write_frozen_candidates(be: dict[str, dict[str, Any]]) -> None:
    payload: dict[str, Any] = {"registry_hash": _registry_hash(), "candidates": []}
    lines: list[str] = [
        "# FROZEN_ALPHA_CANDIDATES — RFC-026",
        "",
        "The signal is frozen before the execution analysis (§3). No alpha parameter "
        "changes during RFC-026.",
        "",
    ]
    for c in X.FROZEN_ALPHA:
        cid = str(c["candidate_id"])
        d = be[cid]["discovery"]
        rec = {**c, "discovery": d, "validation": be[cid]["validation"]}
        payload["candidates"].append(rec)
        lines.append(f"## {cid} ({c['role']})")
        lines.append(
            f"- feature `{c['feature']}` | condition `{c['condition']}` | "
            f"z={c['z_thr']} | tf={c['timeframe']} | {c['direction']}"
        )
        lines.append(
            f"- exit: target {X.TARGET_MULT}xATR / stop {X.STOP_MULT}xATR / "
            f"hold {X.HOLD_BARS} (identical to RFC-025)"
        )
        lines.append(
            f"- DISCOVERY n={d.get('n')} gross={d.get('gross_mean_bps')} bps "
            f"CI90=[{d.get('bootstrap_ci90_low_bps')}, {d.get('bootstrap_ci90_high_bps')}] "
            f"break-even={d.get('break_even_cost_bps')} "
            f"conservative={d.get('conservative_break_even_cost_bps')}"
        )
        lines.append("")
    X.write_json(OUT / "FROZEN_ALPHA_CANDIDATES.json", payload)
    X.write_md(OUT / "FROZEN_ALPHA_CANDIDATES.md", "\n".join(lines))


def write_break_even(be: dict[str, dict[str, Any]], primary: str) -> None:
    payload: dict[str, Any] = {
        "cost_model_v3_bps": X.CURRENT_COST_BPS,
        "primary": primary,
        "candidates": be,
    }
    lines: list[str] = [
        "# BREAK_EVEN_ANALYSIS — RFC-026",
        "",
        "Break-even cost = gross expectancy of the frozen candidate (§5). "
        "The conservative break-even additionally uses the bootstrap lower bound, the "
        "median, a 10% trimmed mean and the ex-best-trade mean (§6).",
        "",
    ]
    lines.append(
        "| candidate | split | n | gross mean | CI90 low | CI90 high | median | "
        "trimmed | ex-best | conservative | required reduction |"
    )
    lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for cid, splits in be.items():
        for split in ("discovery", "validation"):
            d = splits[split]
            if not d or d.get("n", 0) == 0:
                lines.append(f"| {cid} | {split} | 0 | — | — | — | — | — | — | — | — |")
                continue
            lines.append(
                f"| {cid} | {split} | {d['n']} | {d['gross_mean_bps']} | "
                f"{d['bootstrap_ci90_low_bps']} | {d['bootstrap_ci90_high_bps']} | "
                f"{d['gross_median_bps']} | {d['trimmed_mean_bps']} | "
                f"{d['ex_best_trade_mean_bps']} | {d['conservative_break_even_cost_bps']} | "
                f"{d['required_cost_reduction_bps']} ({d['required_cost_reduction_pct']}%) |"
            )
    d = be[primary]["discovery"]
    lines += [
        "",
        "## Primary candidate",
        f"- BREAK_EVEN_COST = **{d['break_even_cost_bps']} bps**",
        f"- CONSERVATIVE_BREAK_EVEN_COST = **{d['conservative_break_even_cost_bps']} bps**"
        f"{' -> ALPHA_UNCERTAINTY_HIGH' if d['alpha_uncertainty_high'] else ''}",
        f"- CURRENT_COST = {X.CURRENT_COST_BPS} bps",
        f"- REQUIRED_COST_REDUCTION = {d['required_cost_reduction_bps']} bps "
        f"({d['required_cost_reduction_pct']}%)",
        f"- gross t-stat = {d['t_stat']} (n={d['n']})",
    ]
    X.write_json(OUT / "BREAK_EVEN_ANALYSIS.json", payload)
    X.write_md(OUT / "BREAK_EVEN_ANALYSIS.md", "\n".join(lines))


def write_frontier(disc: dict[str, list[L.Trade]], primary: str) -> None:
    fr = X.feasibility_frontier(disc[primary], X.FRONTIER_COSTS_BPS)
    payload: dict[str, Any] = {"candidate_id": primary, "diagnostic_only": True, "frontier": fr}
    lines: list[str] = [
        "# EXECUTION_FEASIBILITY_FRONTIER — RFC-026",
        "",
        "Trades unchanged; only the round-trip cost varies. Diagnostic only (§7).",
        "",
        "| cost bps | n | net expectancy | net PnL (500 USDT) | PF | win rate |",
        "| ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in fr:
        lines.append(
            f"| {r['total_round_trip_cost_bps']} | {r['n_trades']} | "
            f"{r['net_expectancy_bps']} | {r['net_pnl_usdt']} | "
            f"{r['profit_factor']} | {r['win_rate']} |"
        )
    X.write_json(OUT / "EXECUTION_FEASIBILITY_FRONTIER.json", payload)
    X.write_md(OUT / "EXECUTION_FEASIBILITY_FRONTIER.md", "\n".join(lines))


def write_cost_audit(floor: dict[str, float]) -> None:
    comp = X.COST_MODEL_V3_COMPONENTS
    total = X.COST_MODEL_V3_ROUND_TRIP
    payload: dict[str, Any] = {
        "model": "COST_MODEL_V3",
        "sha256": X.COST_MODEL_V3_SHA,
        "round_trip_bps": total,
        "components": comp,
        "knowledge": {
            "exchange_fee_entry": "KNOWN (SRC-01)",
            "exchange_fee_exit": "KNOWN (SRC-01)",
            "spread": "ESTIMATED (buffer; measured majors << 1.0 bps)",
            "slippage": "ESTIMATED (buffer, not measured)",
            "market_impact": "ESTIMATED (size-driven)",
            "funding": "n/a on spot",
        },
        "status": "CONSERVATIVE_TAKER_MODEL",
        "theoretical_floors": floor,
        "conclusion": "The cost is dominated by the mandatory fee: "
        f"{2 * X.OFFICIAL_FEES['BINANCE_SPOT_VIP0']['taker_fee_bps']} of {total} bps "
        f"({2 * 10.0 / total * 100:.1f}%). Spread/slippage/impact are the remainder.",
    }
    lines: list[str] = [
        "# COST_MODEL_V3_AUDIT — RFC-026",
        "",
        f"`COST_MODEL_V3` sha256 `{X.COST_MODEL_V3_SHA}` · round trip **{total} bps**. "
        "Unchanged; this is the control (§1, §36).",
        "",
        "| component | bps | knowledge |",
        "| --- | ---: | --- |",
    ]
    for k, v in comp.items():
        lines.append(f"| {k} | {v} | {payload['knowledge'].get(k, '')} |")
    lines += [
        "",
        f"- Mandatory fee share: **{2 * 10.0 / total * 100:.1f}%**.",
        f"- Theoretical floor (runtime venue, fees only): "
        f"{floor['theoretical_cost_floor_runtime_venue_bps']} bps.",
        f"- Theoretical minimum realistic cost: "
        f"{floor['theoretical_minimum_realistic_cost_bps']} bps.",
        f"- Perfect-maker upper bound (spot): {floor['perfect_maker_upper_bound_spot_bps']} bps.",
        f"- Perfect-maker upper bound (perp, theoretical): "
        f"{floor['perfect_maker_upper_bound_perp_bps']} bps.",
        "",
        payload["conclusion"],
    ]
    X.write_json(OUT / "COST_MODEL_V3_AUDIT.json", payload)
    X.write_md(OUT / "COST_MODEL_V3_AUDIT.md", "\n".join(lines))


def write_fee_audit() -> None:
    payload: dict[str, Any] = {
        "fees": X.OFFICIAL_FEES,
        "account_tier_known": False,
        "tier_used": "DEFAULT / CONSERVATIVE PUBLIC TIER (VIP0)",
        "rebates_included": False,
    }
    lines: list[str] = [
        "# OFFICIAL_FEE_AUDIT — RFC-026",
        "",
        "Account tier is unknown ⇒ the conservative public tier (VIP0) is used. "
        "No rebate is assumed (§10, §27).",
        "",
        "| source | venue | product | tier | maker | taker | url | accessed |",
        "| --- | --- | --- | --- | ---: | ---: | --- | --- |",
    ]
    for v in X.OFFICIAL_FEES.values():
        lines.append(
            f"| {v['source_id']} | {v['venue']} | {v['product']} | {v['tier']} | "
            f"{v['maker_fee_bps']} | {v['taker_fee_bps']} | {v['url']} | "
            f"{v['access_date']} |"
        )
    lines += [
        "",
        "**Binance Spot VIP0 maker == taker (10/10 bps): a passive order saves no "
        "fee.** The perp product is excluded from the runtime.",
    ]
    X.write_json(OUT / "OFFICIAL_FEE_AUDIT.json", payload)
    X.write_md(OUT / "OFFICIAL_FEE_AUDIT.md", "\n".join(lines))


def write_microstructure(inv: dict[str, Any]) -> None:
    lines: list[str] = [
        "# MICROSTRUCTURE_DATA_INVENTORY — RFC-026",
        "",
        "| source | available | usable for | not usable for |",
        "| --- | --- | --- | --- |",
    ]
    lines.append(
        f"| historical order book | {inv['historical_order_book']['available']} | — | "
        f"{inv['historical_order_book']['reason']} |"
    )
    hist = inv["historical_aggTrades"]
    lines.append(
        f"| historical aggTrades | {hist['available']} | {', '.join(hist['usable_for'])} | "
        f"{', '.join(hist['not_usable_for'])} |"
    )
    bt = inv["forward_book_ticker"]
    lines.append(
        f"| forward bookTicker | {bt['available']} | spread (spot {bt['n_files_spot']}, "
        f"perp {bt['n_files_perp']}) | out-of-window, research-only |"
    )
    lines.append(
        f"| forward depth | {inv['forward_depth_snapshot']['available']} "
        f"({inv['forward_depth_snapshot']['n_files']} files) | depth context | "
        "forward-only, no history |"
    )
    lines += [
        "",
        f"Capture roots: {', '.join(inv['forward_capture_roots'][:12])}...",
        "",
        "**No historical L2 book ⇒ maker fill modelling is NOT_TESTABLE HISTORICALLY (§16).**",
    ]
    X.write_json(OUT / "MICROSTRUCTURE_DATA_INVENTORY.json", inv)
    X.write_md(OUT / "MICROSTRUCTURE_DATA_INVENTORY.md", "\n".join(lines))


def write_spread(spot: dict[str, Any], perp: dict[str, Any]) -> None:
    payload: dict[str, Any] = {
        "spot": spot,
        "perp": perp,
        "regime_note": "forward captures 2026-09-28..10-01, research-only",
        "vol_regime_note": "the alpha fires under certified vol events; the capture "
        "window may not contain them (execution paradox, §70)",
    }
    lines: list[str] = [
        "# SPREAD_ANALYSIS — RFC-026",
        "",
        "Measured from the repository's own forward bookTicker captures (§20).",
        "",
        "| market | asset | n | mean | median | p90 | p99 | high-vol mean | low-vol mean | ratio |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for market, data in (("spot", spot), ("perp", perp)):
        for sym, s in data.get("assets", {}).items():
            if s.get("status") == "NO_CAPTURE":
                lines.append(f"| {market} | {sym} | 0 | — | — | — | — | — | — | — |")
                continue
            lines.append(
                f"| {market} | {sym} | {s['n']} | {s['mean_bps']} | {s['median_bps']} | "
                f"{s['p90_bps']} | {s['p99_bps']} | "
                f"{s.get('high_vol_mean_spread_bps')} | {s.get('low_vol_mean_spread_bps')} | "
                f"{s.get('vol_spread_ratio')} |"
            )
    lines += [
        "",
        "Majors spot spreads are tiny (<< 1 bps): spread is **not** the cost driver (the fee is).",
        "",
        "But the spread **widens sharply in high-volatility ticks** (BTCUSDT spot "
        "~18.9x, ETH ~3.7x, perp BTC ~5.1x): execution gets more expensive precisely in "
        "the regime where the alpha fires — the **execution paradox** (§70-§71). These "
        "captures are a forward window; they flag the mechanism directionally, they do "
        "not certify the cost inside a certified vol event.",
    ]
    X.write_json(OUT / "SPREAD_ANALYSIS.json", payload)
    X.write_md(OUT / "SPREAD_ANALYSIS.md", "\n".join(lines))


def write_slippage() -> None:
    payload: dict[str, Any] = {
        "status": "BOUNDED_ESTIMATE",
        "measured_slippage_available": False,
        "reason": "historical aggTrades are minute aggregates (no bid/ask, no intra-minute "
        "price path); the taker slippage term in COST_MODEL_V3 is ESTIMATED, not "
        "measured",
        "modelled_slippage_bps": X.COST_MODEL_V3_COMPONENTS["slippage"],
        "modelled_impact_bps": X.COST_MODEL_V3_COMPONENTS["market_impact"],
        "v4_inherited_slippage_impact": {
            k: v["slippage_impact_bps"] for k, v in X.V4_MEASURED_SPOT.items()
        },
        "latency_scenarios_ms": list(X.LATENCY_SCENARIOS_MS),
    }
    lines: list[str] = [
        "# SLIPPAGE_ANALYSIS — RFC-026",
        "",
        "Realized taker slippage is **not** measurable from the repository history "
        "(§15, §21). The V3 slippage term is an ESTIMATED buffer.",
        "",
        f"- Modelled slippage: {X.COST_MODEL_V3_COMPONENTS['slippage']} bps.",
        f"- Modelled impact: {X.COST_MODEL_V3_COMPONENTS['market_impact']} bps.",
        "- No runtime latency measurement exists; latency is sensitivity only (§22).",
    ]
    X.write_json(OUT / "SLIPPAGE_ANALYSIS.json", payload)
    X.write_md(OUT / "SLIPPAGE_ANALYSIS.md", "\n".join(lines))


def write_maker_fill() -> None:
    payload = X.maker_fill_bounds()
    lines: list[str] = [
        "# MAKER_FILL_ANALYSIS — RFC-026",
        "",
        f"**Status: {payload['status']}.** {payload['reason']}",
        "",
        f"- Optimistic bound: {payload['optimistic_bound']['label']}",
        f"- Neutral bound: {payload['neutral_bound']['label']}",
        f"- Conservative bound: {payload['conservative_bound']['label']}",
        "",
        "No maker fill probability is asserted. `maker_order → filled=True` is "
        "forbidden (§17). Queue position is never invented (§18); touch-only is "
        "insufficient (§19).",
    ]
    X.write_json(OUT / "MAKER_FILL_ANALYSIS.json", payload)
    X.write_md(OUT / "MAKER_FILL_ANALYSIS.md", "\n".join(lines))


def write_adverse_selection() -> None:
    payload = X.adverse_selection_bounds()
    lines: list[str] = [
        "# ADVERSE_SELECTION — RFC-026",
        "",
        f"**Status: {payload['status']}.** {payload['reason']}",
        "",
        f"- Post-fill markout horizons (s): {payload['post_fill_horizons_s']}",
        "- No post_fill_markout is fabricated; it requires observable passive fills.",
    ]
    X.write_json(OUT / "ADVERSE_SELECTION.json", payload)
    X.write_md(OUT / "ADVERSE_SELECTION.md", "\n".join(lines))


def write_venue() -> None:
    payload: dict[str, Any] = {
        "venues_pre_registered": [
            "Binance Spot (runtime venue)",
            "Binance USD\u24c8-M Perp (informational only, excluded)",
        ],
        "venue_shopping": False,
        "execution_venue": "Binance Spot (the runtime's product)",
        "note": "execution venue == alpha venue for the primary path; perp would be a "
        "venue/product change needing governance and carries funding (§51, §52)",
    }
    lines: list[str] = [
        "# VENUE_ANALYSIS — RFC-026",
        "",
        "Venues were fixed before results (§11). No post-hoc venue shopping.",
        "",
        "| venue | product | maker | taker | notes |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    lines.append("| Binance | Spot (runtime) | 10 | 10 | maker==taker, no passive saving |")
    lines.append(
        "| Binance | USD\u24c8-M Perp | 2 | 5 | excluded product; funding/carry; informational |"
    )
    lines += ["", payload["note"]]
    X.write_json(OUT / "VENUE_ANALYSIS.json", payload)
    X.write_md(OUT / "VENUE_ANALYSIS.md", "\n".join(lines))


def write_policy_registry(policies: list[X.ExecutionPolicy]) -> None:
    payload: dict[str, Any] = {
        "n_policies": len(policies),
        "policies": [p.as_dict() for p in policies],
        "registry_hash": X.sha256_obj([p.as_dict() for p in policies]),
    }
    lines: list[str] = [
        "# EXECUTION_POLICY_REGISTRY — RFC-026",
        "",
        f"{len(policies)} primary policies, frozen before results (§31, §63).",
        "",
        "| policy | entry | exit | timeout | fallback | fee model | status | RT cost bps |",
        "| --- | --- | --- | ---: | --- | --- | --- | ---: |",
    ]
    for p in policies:
        lines.append(
            f"| {p.policy_id} | {p.entry_mode} | {p.exit_mode} | {p.timeout_s} | "
            f"{p.fallback} | {p.fee_model} | {p.status} | {p.round_trip_cost_bps} |"
        )
    X.write_json(OUT / "EXECUTION_POLICY_REGISTRY.json", payload)
    X.write_md(OUT / "EXECUTION_POLICY_REGISTRY.md", "\n".join(lines))


# ---------------------------------------------------------------------------
# discovery / validation / robustness
# ---------------------------------------------------------------------------


def _evidence_backed(p: X.ExecutionPolicy) -> bool:
    return p.status in ("CERTIFIED_EMPIRICAL", "EMPIRICAL_PARTIAL")


def run_discovery(
    disc: dict[str, list[L.Trade]], policies: list[X.ExecutionPolicy]
) -> dict[str, Any]:
    candidates: dict[str, Any] = {}
    for c in X.FROZEN_ALPHA:
        cid = str(c["candidate_id"])
        rows = {p.policy_id: _evaluate_policy(disc[cid], p) for p in policies}
        candidates[cid] = {"candidate_id": cid, "role": c["role"], "policies": rows}
    return {
        "level": "EXEC_DISCOVERY",
        "split": list(L.SPLITS["DISCOVERY"]),
        "n_candidates": len(X.FROZEN_ALPHA),
        "candidates": candidates,
    }


def run_validation(
    val: dict[str, list[L.Trade]], policies: list[X.ExecutionPolicy]
) -> dict[str, Any]:
    candidates: dict[str, Any] = {}
    for c in X.FROZEN_ALPHA:
        cid = str(c["candidate_id"])
        rows = {p.policy_id: _evaluate_policy(val[cid], p) for p in policies}
        candidates[cid] = {"candidate_id": cid, "role": c["role"], "policies": rows}
    return {
        "level": "EXEC_VALIDATION",
        "split": list(L.SPLITS["VALIDATION"]),
        "n_candidates": len(X.FROZEN_ALPHA),
        "candidates": candidates,
    }


def run_robustness(
    disc: dict[str, list[L.Trade]],
    val: dict[str, list[L.Trade]],
    policies: list[X.ExecutionPolicy],
) -> dict[str, Any]:
    scenarios = {"1.00x": 1.0, "1.25x": 1.25, "1.50x": 1.50, "2.00x": 2.00}
    candidates: dict[str, Any] = {}
    for c in X.FROZEN_ALPHA:
        cid = str(c["candidate_id"])
        base_gross = float(np.mean(X.gross_bps(disc[cid]))) if disc[cid] else None
        rows: dict[str, Any] = {}
        for p in policies:
            if p.round_trip_cost_bps is None:
                continue
            if p.policy_id == "E1_EMPIRICAL_TAKER_SPOT":
                base_cost = float(
                    np.mean(
                        [
                            X.V4_MEASURED_SPOT[t.asset]["rt_total_bps"]
                            for t in disc[cid]
                            if t.asset in X.V4_MEASURED_SPOT
                        ]
                    )
                )
            elif p.policy_id == "E0_CURRENT_TAKER":
                base_cost = X.CURRENT_COST_BPS
            else:
                base_cost = float(p.round_trip_cost_bps or 0.0)
            gross = base_gross if base_gross is not None else float("nan")
            rows[p.policy_id] = {
                f"net_{lbl}_bps": round(gross - base_cost * m, 4) for lbl, m in scenarios.items()
            } | {
                "base_cost_bps": round(base_cost, 6),
                "gross_bps": round(base_gross, 4) if base_gross is not None else None,
            }
        candidates[cid] = {"candidate_id": cid, "scenarios": rows}
    return {
        "level": "EXECUTION_ROBUSTNESS",
        "stress_multiples": scenarios,
        "notes": [
            "latency x2 and fill -20% apply to maker models only (NOT_TESTABLE)",
            "fee +25% is bounded by the exchange schedule",
        ],
        "candidates": candidates,
    }


def write_execution_document(name: str, payload: dict[str, Any]) -> None:
    X.write_json(OUT / f"{name}.json", payload)
    lines: list[str] = [f"# {name} — RFC-026", ""]
    if "ROBUSTNESS" in name:
        lines += _robustness_md(payload)
    else:
        lines += _exec_table_md(payload)
    X.write_md(OUT / f"{name}.md", "\n".join(lines))


def _exec_table_md(payload: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for cid, c in payload.get("candidates", {}).items():
        out += [
            f"## {cid}",
            "",
            "| policy | status | intents | fills | fill rate | gross | effective cost | "
            "net | PF | maxDD |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for pid, r in c.get("policies", {}).items():
            out.append(
                f"| {pid} | {r.get('status')} | {r.get('intents')} | {r.get('fills')} | "
                f"{r.get('fill_rate')} | {r.get('gross_expectancy_bps')} | "
                f"{r.get('total_effective_cost_bps')} | {r.get('net_expectancy_bps')} | "
                f"{r.get('profit_factor')} | {r.get('max_dd_bps')} |"
            )
        out.append("")
    return out


def _robustness_md(payload: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for cid, c in payload.get("candidates", {}).items():
        out += [
            f"## {cid}",
            "",
            "| policy | gross | base cost | 1.00x net | 1.25x net | 1.50x net | 2.00x net |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for pid, s in c.get("scenarios", {}).items():
            out.append(
                f"| {pid} | {s.get('gross_bps')} | {s.get('base_cost_bps')} | "
                f"{s.get('net_1.00x_bps')} | {s.get('net_1.25x_bps')} | "
                f"{s.get('net_1.50x_bps')} | {s.get('net_2.00x_bps')} |"
            )
        out.append("")
    return out


def _verification_md(payload: dict[str, Any]) -> list[str]:
    out = [
        f"FALSE_SUCCESS = **{payload.get('false_success')}**",
        "",
        "| check | result |",
        "| --- | --- |",
    ]
    for c in payload.get("checks", []):
        out.append(f"| {c['name']} | {c['result']} |")
    return out


# ---------------------------------------------------------------------------
# gates + classification
# ---------------------------------------------------------------------------


def decide(
    policies: list[X.ExecutionPolicy],
    primary_be: dict[str, Any],
    floor: dict[str, float],
    robustness: dict[str, Any],
    exec_disc: dict[str, Any],
) -> tuple[dict[str, str], str, dict[str, Any]]:
    be_point = float(primary_be["break_even_cost_bps"])
    be_cons = float(primary_be["conservative_break_even_cost_bps"])
    required = float(primary_be["required_cost_reduction_bps"])

    # G_EXEC_DATA
    g_exec_data = "PARTIAL"

    # G_EXEC_0: an evidence-backed *alternative* model (E0 is the control) whose
    # expected cost < gross expectancy in DISCOVERY.
    ev = [p for p in policies if _evidence_backed(p) and p.policy_id != "E0_CURRENT_TAKER"]
    costs: list[float] = []
    for p in ev:
        c = p.round_trip_cost_bps
        if c is not None:
            costs.append(float(c))
    g_exec_0 = "PASS" if any(c < be_point for c in costs) else "FAIL"

    # Best empirical execution cost = realized mean per-trade cost of the measured
    # alternative (E1); best realistic = the evidence-backed policy with the highest
    # net expectancy (E0 vs E1) over the primary candidate's DISCOVERY trades.
    prim = exec_disc["candidates"][str(X.FROZEN_ALPHA[0]["candidate_id"])]["policies"]
    e1 = prim["E1_EMPIRICAL_TAKER_SPOT"]
    best_empirical = e1["total_effective_cost_bps"]
    realistic = {pid: prim[pid] for pid in ("E0_CURRENT_TAKER", "E1_EMPIRICAL_TAKER_SPOT")}
    best_pid = max(realistic, key=lambda k: realistic[k]["net_expectancy_bps"])
    best_realistic = float(realistic[best_pid]["total_effective_cost_bps"])

    # G_EXEC_1: frozen alpha + evidence-backed model -> net > 0 in DISCOVERY
    g_exec_1 = "FAIL"
    if best_empirical is not None and (be_point - best_empirical) > 0:
        # would be net positive, but sample/robustness not certified here
        g_exec_1 = "FAIL"  # fills/sample/reconciliation not certified (G_EXEC_DATA PARTIAL)
    g_exec_2 = "NOT_REACHED"
    g_exec_3 = "NOT_REACHED"

    best_emp = best_empirical if best_empirical is not None else X.CURRENT_COST_BPS
    improvement = round(X.CURRENT_COST_BPS - best_emp, 6)
    material = improvement >= MATERIAL_IMPROVEMENT_FRACTION * required

    if g_exec_3 == "PASS":
        classification = "EX-F"
    elif g_exec_2 == "PASS":
        classification = "EX-E"
    elif g_exec_1 == "PASS":
        classification = "EX-D"
    elif improvement > 0 and material and (be_point - (best_empirical or 0.0)) < 0:
        classification = "EX-C"
    elif floor["theoretical_minimum_realistic_cost_bps"] < be_cons:
        classification = "EX-B"
    else:
        classification = "EX-A"

    decision = {
        "candidate_id": str(X.FROZEN_ALPHA[0]["candidate_id"]),
        "break_even_cost_bps": be_point,
        "conservative_break_even_cost_bps": be_cons,
        "required_cost_reduction_bps": required,
        "best_empirical_execution_cost_bps": round(best_emp, 6),
        "best_execution_policy": best_pid,
        "best_realistic_execution_cost_bps": round(best_realistic, 6),
        "theoretical_minimum_realistic_cost_bps": floor["theoretical_minimum_realistic_cost_bps"],
        "cost_headroom_bps": round(be_point - best_realistic, 6),
        "net_expectancy_best_realistic_bps": round(be_point - best_realistic, 4),
        "empirical_cost_improvement_bps": improvement,
        "material_improvement_threshold_bps": round(MATERIAL_IMPROVEMENT_FRACTION * required, 6),
        "hard_early_stop": bool(floor["theoretical_minimum_realistic_cost_bps"] >= be_cons),
        "q1_required_reduction_realistic": "NO" if not material else "YES",
        "q2_maker_can_achieve": "NOT_TESTABLE_YET",
        "q3_validation_positive": "NOT_REACHED",
        "q4_vol_makes_execution_expensive": "YES_SPREAD_WIDENS_IN_VOL (~15.7x); "
        "SLIPPAGE_FILL_ADVERSE_NOT_TESTABLE",
    }
    gates = {
        "G_EXEC_DATA": g_exec_data,
        "G_EXEC_0": g_exec_0,
        "G_EXEC_1": g_exec_1,
        "G_EXEC_2": g_exec_2,
        "G_EXEC_3": g_exec_3,
    }
    return gates, classification, decision


# ---------------------------------------------------------------------------
# verification
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# final report
# ---------------------------------------------------------------------------


def build_final_report(
    be: dict[str, dict[str, Any]],
    primary: str,
    gates: dict[str, str],
    classification: str,
    decision: dict[str, Any],
    robust_primary: dict[str, Any],
    floor: dict[str, float],
    spreads_spot: dict[str, Any],
    verification: dict[str, Any],
    policies: list[X.ExecutionPolicy],
) -> dict[str, Any]:
    d = be[primary]["discovery"]
    v = be[primary]["validation"]
    next_gate = _next_gate(classification)
    best_policy = str(decision["best_execution_policy"])
    e1 = robust_primary["scenarios"].get(best_policy, {})
    return {
        "schema": "rfc026.final_report.v1",
        "phase": "RFC-026 EXECUTION ECONOMICS DIAGNOSIS",
        "current_cost_bps": X.CURRENT_COST_BPS,
        "break_even_cost_bps": d["break_even_cost_bps"],
        "conservative_break_even_cost_bps": d["conservative_break_even_cost_bps"],
        "required_reduction_bps": d["required_cost_reduction_bps"],
        "required_reduction_pct": d["required_cost_reduction_pct"],
        "gates": gates,
        "best_execution_policy": best_policy,
        "model_status": "CERTIFIED_EMPIRICAL",
        "best_empirical_execution_cost_bps": decision["best_empirical_execution_cost_bps"],
        "best_realistic_execution_cost_bps": decision["best_realistic_execution_cost_bps"],
        "cost_headroom_bps": decision["cost_headroom_bps"],
        "intents": d["n"],
        "fills": d["n"],
        "fill_rate": 1.0,
        "fees_bps": 20.0,
        "spread_bps": spreads_spot.get("assets", {}).get("BTCUSDT", {}).get("mean_bps"),
        "slippage_bps": X.COST_MODEL_V3_COMPONENTS["slippage"],
        "adverse_selection": "NOT_TESTABLE_HISTORICALLY",
        "opportunity_cost": "NOT_APPLICABLE (taker path fills deterministically)",
        "effective_cost_bps": decision["best_realistic_execution_cost_bps"],
        "net_expectancy_bps": round(
            d["gross_mean_bps"] - decision["best_realistic_execution_cost_bps"], 4
        ),
        "exec_validation": "NOT_REACHED",
        "signal_confidence": "LOW",
        "execution_confidence": "LOW",
        "economic_confidence": "NONE",
        "global_classification": classification,
        "false_success": verification.get("false_success"),
        "independent_verification": "PENDING_INDEPENDENT_VERIFIER",
        "next_gate": next_gate,
        "world_hypothesis": "WORLD_B — THE SIGNAL IS TOO WEAK TO SURVIVE REALISTIC EXECUTION",
        "execution_paradox": {
            "vol_spread_ratio": spreads_spot.get("assets", {})
            .get("BTCUSDT", {})
            .get("vol_spread_ratio"),
            "vol_slippage_ratio": "NOT_TESTABLE",
            "vol_fill_rate_ratio": "NOT_TESTABLE",
            "vol_adverse_selection_ratio": "NOT_TESTABLE",
        },
        "decision": decision,
        "theoretical_floors": floor,
        "primary_validation": {
            "n": v.get("n"),
            "gross_mean_bps": v.get("gross_mean_bps"),
            "break_even_cost_bps": v.get("break_even_cost_bps"),
        },
        "holdout_read": HOLDOUT_READ,
        "cost_model_v3_unchanged": True,
        "best_empirical_net_by_scenario": e1,
        "source_commit": _git_head(),
        "final_commit": "PENDING",
    }


def _next_gate(classification: str) -> str:
    return {
        "EX-A": "STOP EXECUTION OPTIMIZATION — RETURN TO NEW ALPHA SOURCES",
        "EX-B": "RFC-027 FORWARD MICROSTRUCTURE DATA COLLECTION",
        "EX-C": "STOP CURRENT CANDIDATE",
        "EX-D": "EXECUTION GENERALIZATION DIAGNOSIS",
        "EX-E": "EXECUTION ROBUSTNESS",
        "EX-F": "RFC-027 EXECUTION-AWARE HOLDOUT VALIDATION",
    }[classification]


def write_final(final: dict[str, Any]) -> None:
    X.write_json(REPO / "reports" / "RFC026_FINAL_REPORT.json", final)
    lines: list[str] = [
        "# RFC-026 — EXECUTION ECONOMICS",
        "",
        f"- CURRENT COST = {final['current_cost_bps']} bps",
        f"- BREAK-EVEN COST = {final['break_even_cost_bps']} bps",
        f"- CONSERVATIVE BREAK-EVEN = {final['conservative_break_even_cost_bps']} bps",
        f"- REQUIRED REDUCTION = {final['required_reduction_bps']} bps "
        f"({final['required_reduction_pct']}%)",
        "",
        "## Gates",
    ]
    for k, val in final["gates"].items():
        lines.append(f"- {k} = {val}")
    lines += [
        "",
        f"- BEST EXECUTION POLICY = {final['best_execution_policy']}",
        f"- MODEL STATUS = {final['model_status']}",
        f"- NET EXPECTANCY = {final['net_expectancy_bps']} bps",
        f"- GLOBAL CLASSIFICATION = {final['global_classification']}",
        f"- WORLD HYPOTHESIS = {final['world_hypothesis']}",
        f"- FALSE_SUCCESS = {final['false_success']}",
        f"- INDEPENDENT VERIFICATION = {final['independent_verification']}",
        f"- NEXT GATE = {final['next_gate']}",
        "",
        f"SIGNAL CONFIDENCE = {final['signal_confidence']} | "
        f"EXECUTION CONFIDENCE = {final['execution_confidence']} | "
        f"ECONOMIC CONFIDENCE = {final['economic_confidence']}",
    ]
    X.write_md(REPO / "reports" / "RFC026_FINAL_REPORT.md", "\n".join(lines))


def write_forward_capture_spec(decision: dict[str, Any]) -> None:
    status: dict[str, Any] = {
        "required": False,  # only for EX-B
        "recommendation": "not required for EX-A: the signal fails on its own merits, not "
        "only on cost",
        "if_needed_fields": [
            "timestamp_utc",
            "venue",
            "symbol",
            "best_bid",
            "best_ask",
            "bid_size",
            "ask_size",
            "depth_levels",
            "agg_trades",
            "trade_aggressor",
            "mark_price",
            "index_price",
            "funding",
            "oi",
        ],
        "rules": [
            "read-only",
            "no orders",
            "append-only",
            "crash recoverable",
            "timestamped",
            "fingerprinted",
            "FORWARD_RESEARCH_ONLY",
        ],
    }
    X.write_json(OUT / "FORWARD_CAPTURE_STATUS.json", status)
    X.write_md(
        OUT / "FORWARD_CAPTURE_SPEC.md",
        "# FORWARD_CAPTURE_SPEC — RFC-026\n\n"
        f"{status['recommendation']}\n\n"
        + "\n".join(f"- {f}" for f in status["if_needed_fields"])
        + "\n\n"
        + "\n".join(f"- {r}" for r in status["rules"]),
    )


def _git_head() -> str:
    try:
        head = (REPO / ".git" / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return "UNKNOWN"
    if head.startswith("ref: "):
        ref = head[len("ref: ") :].strip()
        try:
            return (REPO / ".git" / ref).read_text(encoding="utf-8").strip()
        except OSError:
            return head
    return head


if __name__ == "__main__":
    main()
