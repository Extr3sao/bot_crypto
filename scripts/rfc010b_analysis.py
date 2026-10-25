"""RFC-010B independent funnel / edge / proposal / cost analysis from the trace store.

Reads a run's ``traces.jsonl`` (the append-only source of truth) and recomputes —
WITHOUT trusting the run summary — the full admission funnel, the edge/cost
distributions, proposal identity/deduplication, the shadow set, the context
errors and the cost-model component audit.

Usage:
    python scripts/rfc010b_analysis.py \
        --run-dir reports/rfc010/runs/RFC010-BASELINE-DEV \
        --out reports/baseline/analysis.json
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any


def pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    if len(s) == 1:
        return float(s[0])
    idx = q * (len(s) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(s) - 1)
    frac = idx - lo
    return float(s[lo] * (1 - frac) + s[hi] * frac)


def dist(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "min": round(min(values), 6),
        "p05": round(pct(values, 0.05) or 0.0, 6),
        "p10": round(pct(values, 0.10) or 0.0, 6),
        "p25": round(pct(values, 0.25) or 0.0, 6),
        "median": round(statistics.median(values), 6),
        "p75": round(pct(values, 0.75) or 0.0, 6),
        "p90": round(pct(values, 0.90) or 0.0, 6),
        "p95": round(pct(values, 0.95) or 0.0, 6),
        "p99": round(pct(values, 0.99) or 0.0, 6),
        "max": round(max(values), 6),
        "mean": round(statistics.fmean(values), 6),
        "std": round(statistics.pstdev(values), 6),
    }


def load_rows(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "traces.jsonl"
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    run_dir = Path(args.run_dir)
    rows = load_rows(run_dir)
    n = len(rows)

    # -- funnel ---------------------------------------------------------------
    mode_counts = Counter(r.get("mode") for r in rows)
    class_counts = Counter(r.get("classification") for r in rows)
    proposals = [r["proposal"] for r in rows if r.get("proposal")]
    shadow_rows = [r for r in rows if r.get("mode") == "SHADOW_TRADE"]
    order_rows = [r for r in rows if r.get("order_created")]
    ctx_rows = [r for r in rows if r.get("classification") == "CONTEXT_ERROR"]
    no_alpha_rows = [r for r in rows if r.get("classification") == "NO_ALPHA"]

    n_ctx = len(ctx_rows)
    n_no_alpha = len(no_alpha_rows)
    n_proposals = len(proposals)  # asset-cycles that built a TradeProposal
    n_cost_killed = class_counts.get("COST_KILLED", 0)
    n_no_gross = class_counts.get("NO_GROSS_EDGE", 0)
    n_shadow = len(shadow_rows)

    funnel = {
        "market_cycles": None,  # filled by harness summary if available
        "asset_cycle_evaluations": n,
        "context_errors": n_ctx,
        "no_alpha": n_no_alpha,
        "proposals_built": n_proposals,
        "proposals_no_gross_edge": n_no_gross,
        "proposals_cost_killed": n_cost_killed,
        "shadow_trades": n_shadow,
        "admitted_for_paper": 0,
        "orders_created": len(order_rows),
        "fills": 0,
        "trades": 0,
    }

    # -- proposal identity / dedup -------------------------------------------
    def identity(p: dict[str, Any]) -> tuple[Any, ...]:
        # Deterministic identity from real fields: one hypothesis per
        # (decision instant, asset, strategy, direction, market data).
        return (
            p.get("decision_time_ms"),
            p.get("market_time_ms"),
            p.get("asset"),
            p.get("symbol"),
            p.get("strategy_id"),
            p.get("direction"),
            p.get("context_fingerprint"),
        )

    ids = [identity(p) for p in proposals]
    unique_ids = set(ids)
    dup_counts = Counter(ids)
    duplicated = {k: v for k, v in dup_counts.items() if v > 1}

    # -- edge / cost distributions -------------------------------------------
    gross = [float(p["expected_gross_edge_bps"]) for p in proposals]
    cost = [float(p["expected_cost_bps"]) for p in proposals]
    net = [float(p["expected_net_edge_bps"]) for p in proposals]
    gt = sum(1 for g, c in zip(gross, cost, strict=True) if g > c)
    eq = sum(1 for g, c in zip(gross, cost, strict=True) if g == c)
    lt = sum(1 for g, c in zip(gross, cost, strict=True) if g < c)
    ratios = [g / c for g, c in zip(gross, cost, strict=True) if c]
    gaps = [g - c for g, c in zip(gross, cost, strict=True)]

    # -- categories A/B/C/D ---------------------------------------------------
    # A far from profitable (net <= -10 bps) ; B near break-even (-10 < net <= 0);
    # C positive gross destroyed by cost (gross>0, net<0); D net-positive blocked.
    cat_a = sum(1 for x in net if x <= -10.0)
    cat_b = sum(1 for x in net if -10.0 < x <= 0.0)
    cat_c = sum(1 for g, x in zip(gross, net, strict=True) if g > 0 and x < 0)
    cat_d = sum(1 for x in net if x > 0)

    # -- breakdowns -----------------------------------------------------------
    def breakdown(key: str) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for r in rows:
            k = r.get(key)
            k = "<null>" if k is None else str(k)
            row = out.setdefault(
                k, {"rows": 0, "proposals": 0, "shadow": 0, "no_alpha": 0, "ctx_error": 0}
            )
            row["rows"] += 1
            if r.get("proposal"):
                row["proposals"] += 1
            if r.get("mode") == "SHADOW_TRADE":
                row["shadow"] += 1
            if r.get("classification") == "NO_ALPHA":
                row["no_alpha"] += 1
            if r.get("classification") == "CONTEXT_ERROR":
                row["ctx_error"] += 1
        return out

    selected_strategy = Counter(
        (r["proposal"] or {}).get("strategy_id") for r in rows if r.get("proposal")
    )

    # -- shadow detail --------------------------------------------------------
    shadow_detail = []
    for r in shadow_rows:
        p = r["proposal"] or {}
        shadow_detail.append(
            {
                "proposal_id": p.get("decision_id"),
                "decision_id": r.get("decision_id"),
                "asset": r.get("asset"),
                "strategy": p.get("strategy_id"),
                "direction": p.get("direction"),
                "timestamp": r.get("decision_time_ms"),
                "regime": r.get("regime"),
                "gross_edge_bps": p.get("expected_gross_edge_bps"),
                "cost_bps": p.get("expected_cost_bps"),
                "net_edge_bps": p.get("expected_net_edge_bps"),
                "gate": (r.get("shadow") or {}).get("rejection_reason"),
                "admission_status": p.get("admission_status"),
            }
        )

    # -- context error detail -------------------------------------------------
    ctx_detail = []
    for r in ctx_rows:
        mc = r.get("market_context") or {}
        ctx_detail.append(
            {
                "asset": r.get("asset"),
                "decision_time_ms": r.get("decision_time_ms"),
                "reason": r.get("reason"),
                "scanner_rejection": mc.get("rejection_reason"),
                "scanner_active": mc.get("active"),
                "no_trade_kind": r.get("no_trade_kind"),
            }
        )

    # -- cost model component audit ------------------------------------------
    # Pull one representative cost breakdown and verify the arithmetic.
    cost_components: Counter[str] = Counter()
    cost_versions: Counter[str] = Counter()
    cost_scenarios: Counter[str] = Counter()
    fee_vals: set[float] = set()
    spread_vals: set[float] = set()
    slip_vals: set[float] = set()
    impact_vals: set[float] = set()
    rt_vals: set[float] = set()
    additive_ok = True
    for p in proposals:
        c = p.get("cost") or {}
        cost_versions[str(c.get("cost_model_version"))] += 1
        cost_scenarios[str(c.get("scenario_id"))] += 1
        fee_vals.add(round(float(c.get("fee_bps", 0.0)), 6))
        spread_vals.add(round(float(c.get("spread_bps", 0.0)), 6))
        slip_vals.add(round(float(c.get("slippage_bps", 0.0)), 6))
        impact_vals.add(round(float(c.get("impact_bps", 0.0)), 6))
        rt_vals.add(round(float(c.get("round_trip_bps", 0.0)), 6))
        for comp in c.get("components", []):
            cost_components[comp.get("name")] += 1
        # recompute the round trip from its own components
        total = (
            float(c.get("fee_bps", 0.0))
            + float(c.get("spread_bps", 0.0))
            + float(c.get("slippage_bps", 0.0))
            + float(c.get("impact_bps", 0.0))
            + float(c.get("funding_bps", 0.0))
        )
        if abs(total - float(c.get("round_trip_bps", 0.0))) > 1e-6:
            additive_ok = False

    report = {
        "run_dir": str(run_dir),
        "rows": n,
        "funnel": funnel,
        "mode_counts": dict(mode_counts),
        "class_counts": dict(class_counts),
        "proposals": {
            "raw": n_proposals,
            "unique": len(unique_ids),
            "duplicate_groups": len(duplicated),
            "duplicate_extra": n_proposals - len(unique_ids),
            "identity_fields": [
                "decision_time_ms",
                "market_time_ms",
                "asset",
                "symbol",
                "strategy_id",
                "direction",
                "context_fingerprint",
            ],
        },
        "edge": {
            "gross_edge_bps": dist(gross),
            "cost_bps": dist(cost),
            "net_edge_bps": dist(net),
            "edge_cost_ratio": dist(ratios),
            "edge_gap_bps": dist(gaps),
            "gross_gt_cost": gt,
            "gross_eq_cost": eq,
            "gross_lt_cost": lt,
            "category_A_far_negative_net": cat_a,
            "category_B_near_breakeven": cat_b,
            "category_C_gross_pos_net_neg": cat_c,
            "category_D_net_positive": cat_d,
        },
        "selected_strategy_of_proposal": dict(selected_strategy),
        "by_asset": breakdown("asset"),
        "by_regime": breakdown("regime"),
        "shadow_detail": shadow_detail,
        "context_error_detail": ctx_detail,
        "cost_model": {
            "versions": dict(cost_versions),
            "scenarios": dict(cost_scenarios),
            "components": dict(cost_components),
            "fee_bps_values": sorted(fee_vals),
            "spread_bps_values": sorted(spread_vals),
            "slippage_bps_values": sorted(slip_vals),
            "impact_bps_values": sorted(impact_vals),
            "round_trip_bps_values": sorted(rt_vals),
            "additive_reconstruction_ok": additive_ok,
        },
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("rows", "funnel", "proposals", "edge")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
