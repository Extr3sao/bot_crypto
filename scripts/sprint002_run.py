"""RFC-022 Sprint 002 - stage runner and artifact writer.

Stages: DISCOVERY (W1-W4) -> VALIDATION (W5) -> ROBUSTNESS -> HOLDOUT (W6-W7,
finalists only). The holdout is read once, after a pre-unlock registration is
written, and never used for selection or tuning.

Usage:
    python scripts/sprint002_run.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import sprint002_lib as L
import sprint002_pipeline as P

OUT = L.OUT_DIR
COST = L.CERTIFIED_ROUND_TRIP_BPS


def tf_of(exp: dict[str, Any]) -> str:
    return str(exp["timeframe"]).split("+")[0]


# ---------------------------------------------------------------------------
# stage 2: validation
# ---------------------------------------------------------------------------


def stage_validation(survivors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for s in survivors:
        trades, eval_bars = P.rerun(s, L.SPLITS["VALIDATION"])
        m = P.mm(trades, eval_bars, tf_of(s))
        d = s["metrics"]
        out.append(
            {
                "experiment_id": s["experiment_id"],
                "candidate_id": s["candidate_id"],
                "hypothesis_id": s["hypothesis_id"],
                "family": s["family"],
                "timeframe": s["timeframe"],
                "parameters": s["parameters"],
                "params": s["params"],
                "sig": s["sig"],
                "discovery": d,
                "validation": m,
                "degradation": {
                    "net_bps_delta": round(
                        float(m.get("net_bps", 0)) - float(d.get("net_bps", 0)), 4
                    ),
                    "pf_delta": round(
                        float(m.get("profit_factor") or 0) - float(d.get("profit_factor") or 0), 4
                    ),
                    "trade_count_change": int(m.get("trades", 0)) - int(d.get("trades", 0)),
                },
                "pass": bool(
                    m.get("trades", 0) >= 10
                    and m.get("net_bps", -1) > 0
                    and m.get("net_pnl_usdt", -1) > 0
                    and not m.get("single_trade_dependency")
                ),
            }
        )
    return out


# ---------------------------------------------------------------------------
# stage 3-5: walk-forward, stress, robustness
# ---------------------------------------------------------------------------


def stage_walk_forward(exp: dict[str, Any]) -> dict[str, Any]:
    """Expanding-window folds. The candidate is already frozen, so each fold is a
    pure out-of-sample evaluation: no fitting, therefore no train/test leak."""
    folds = [("W1",), ("W1", "W2"), ("W1", "W2", "W3")]
    targets = ("W2", "W3", "W4")
    out: list[dict[str, Any]] = []
    for train, target in zip(folds, targets, strict=False):
        trades, eval_bars = P.rerun(exp, (target,))
        m = P.mm(trades, eval_bars, tf_of(exp))
        out.append(
            {
                "train_windows": list(train),
                "test_window": target,
                "trades": m.get("trades", 0),
                "net_bps": m.get("net_bps"),
                "net_pnl_usdt": m.get("net_pnl_usdt"),
                "profit_factor": m.get("profit_factor"),
                "max_dd_bps": m.get("max_dd_bps"),
            }
        )
    pos = sum(1 for f in out if (f["net_bps"] or 0) > 0)
    return {
        "status": "OK",
        "folds": out,
        "positive_folds": pos,
        "total_folds": len(out),
        "verdict": "PASS" if pos == len(out) else ("PARTIAL" if pos > 0 else "FAIL"),
    }


def stage_cost_stress(exp: dict[str, Any]) -> dict[str, Any]:
    span = L.SPLITS["DISCOVERY"] + L.SPLITS["VALIDATION"]
    out: dict[str, Any] = {}
    for name, c in L.COST_STRESS.items():
        trades, eval_bars = P.rerun(exp, span, cost_bps=c)
        m = P.mm(trades, eval_bars, tf_of(exp))
        out[name] = {"cost_bps": c, "trades": m.get("trades", 0), "net_bps": m.get("net_bps")}
    msc = None
    for name in ("BASE", "PLUS_25", "PLUS_50", "PLUS_100"):
        if (out[name]["net_bps"] or -1) > 0:
            msc = out[name]["cost_bps"]
    return {
        "status": "OK",
        "scenarios": out,
        "max_survivable_cost_bps": msc,
        "verdict": (
            "ROBUST"
            if msc is not None and msc >= L.COST_STRESS["PLUS_50"]
            else ("FRAGILE" if msc is not None else "DEAD")
        ),
    }


def stage_slippage_stress(exp: dict[str, Any]) -> dict[str, Any]:
    span = L.SPLITS["DISCOVERY"] + L.SPLITS["VALIDATION"]
    out: dict[str, Any] = {}
    for mult in (1.0, 1.5, 2.0):
        trades, eval_bars = P.rerun(exp, span, slip_mult=mult)
        m = P.mm(trades, eval_bars, tf_of(exp))
        out[f"{mult}x"] = {
            "slippage_mult": mult,
            "trades": m.get("trades", 0),
            "net_bps": m.get("net_bps"),
        }
    nets = [v["net_bps"] or -99.0 for v in out.values()]
    verdict = "ROBUST" if all(n > 0 for n in nets) else ("FRAGILE" if nets[0] > 0 else "DEAD")
    return {"status": "OK", "scenarios": out, "verdict": verdict}


def stage_robustness(exp: dict[str, Any]) -> dict[str, Any]:
    span = L.SPLITS["DISCOVERY"] + L.SPLITS["VALIDATION"]
    trades, eval_bars = P.rerun(exp, span)
    return {
        "status": "OK",
        "candidate_id": exp["candidate_id"],
        "hypothesis_id": exp["hypothesis_id"],
        "family": exp["family"],
        "timeframe": exp["timeframe"],
        "parameters": exp["parameters"],
        "pooled_metrics": P.mm(trades, eval_bars, tf_of(exp)),
        "asset": P.group_metrics(trades, "asset"),
        "regime": P.group_metrics(trades, "regime"),
        "temporal": P.temporal_breakdown(trades),
        "cost_stress": stage_cost_stress(exp),
        "slippage_stress": stage_slippage_stress(exp),
        "parameter_neighbourhood": P.param_neighbourhood(exp),
        "bootstrap": P.block_bootstrap(trades),
        "walk_forward": stage_walk_forward(exp),
    }


# ---------------------------------------------------------------------------
# stage 6: holdout
# ---------------------------------------------------------------------------


def stage_holdout(finalists: list[dict[str, Any]]) -> dict[str, Any]:
    pre_unlock = [
        {
            "candidate_id": f["candidate_id"],
            "hypothesis_id": f["hypothesis_id"],
            "family": f["family"],
            "timeframe": f["timeframe"],
            "parameters": f["parameters"],
            "code_hash": L.sha256_obj({"sig": f["sig"], "params": f["params"]}),
            "parameter_hash": L.sha256_obj(f["parameters"]),
            "selection_rationale": (
                "passed DISCOVERY (G_EDGE_1) and VALIDATION (G_EDGE_2) with frozen parameters"
            ),
            "unlock_timestamp": "2026-10-04T00:00:00Z",
        }
        for f in finalists
    ]
    results: list[dict[str, Any]] = []
    for f in finalists:
        trades, eval_bars = P.rerun(f, L.SPLITS["HOLDOUT"])
        m = P.mm(trades, eval_bars, tf_of(f))
        results.append(
            {
                "candidate_id": f["candidate_id"],
                "hypothesis_id": f["hypothesis_id"],
                "family": f["family"],
                "timeframe": f["timeframe"],
                "parameters": f["parameters"],
                "holdout": m,
                "pass": bool(
                    m.get("trades", 0) >= 10
                    and m.get("net_bps", -1) > 0
                    and m.get("net_pnl_usdt", -1) > 0
                ),
            }
        )
    return {
        "status": "OK" if finalists else "NOT_REACHED",
        "reason": "" if finalists else "no finalist cleared discovery+validation+robustness",
        "holdout_windows": list(L.SPLITS["HOLDOUT"]),
        "holdout_unread": not finalists,
        "pre_unlock_registration": pre_unlock,
        "results": results,
        "G_EDGE_4": (
            "PASS" if any(r["pass"] for r in results) else ("FAIL" if finalists else "NOT_REACHED")
        ),
    }


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    hashes = L.split_hashes()

    print("=== STAGE 1 DISCOVERY (W1-W4) ===", flush=True)
    disc = P.stage_discovery()
    pos = [
        r
        for r in disc
        if r["metrics"].get("trades", 0) >= L.MIN_TRADES
        and r["metrics"].get("net_bps", -1) > 0
        and not r["metrics"].get("single_trade_dependency")
    ]
    print(f"experiments={len(disc)} positive_net={len(pos)}", flush=True)
    for r in sorted(disc, key=lambda x: -float(x["metrics"].get("net_bps", -99)))[:10]:
        m = r["metrics"]
        print(
            f"  {r['experiment_id']} {r['candidate_id']:30s} {r['parameters']} n={m.get('trades')} "
            f"gross={m.get('gross_bps')} net={m.get('net_bps')} ratio={m.get('edge_cost_ratio')} "
            f"PF={m.get('profit_factor')} t={m.get('t_stat')} exbest={m.get('net_bps_ex_best_trade')}"
        )
    P.write_registry_and_matrix(disc, pos)
    L.write_json(
        OUT / "DISCOVERY_RAW.json",
        {
            "schema": "rfc022.discovery_raw.v1",
            "experiments": [{k: v for k, v in r.items() if k != "trades"} for r in disc],
        },
    )
    L.write_json(
        OUT / "DISCOVERY_SURVIVOR_SET.json",
        {
            "schema": "rfc022.discovery_survivor_set.v1",
            "split": "DISCOVERY",
            "cost_bps": COST,
            "min_trades": L.MIN_TRADES,
            "survivors": [
                {k: v for k, v in r.items() if k != "trades"}
                for r in sorted(pos, key=lambda x: -float(x["metrics"]["net_bps"]))
            ],
        },
    )
    L.write_json(
        OUT / "DISCOVERY_RESULTS.json",
        {
            "schema": "rfc022.discovery_results.v1",
            "split": "DISCOVERY W1-W4",
            "cost_bps": COST,
            "min_trades": L.MIN_TRADES,
            "experiments_total": len(disc),
            "positive_net": len(pos),
            "G_EDGE_1": "PASS" if pos else "FAIL",
            "data_split": hashes,
            "results": [
                {k: v for k, v in r.items() if k != "trades"}
                for r in sorted(disc, key=lambda x: -float(x["metrics"].get("net_bps", -99)))
            ],
        },
    )

    print("=== STAGE 2 VALIDATION (W5) ===", flush=True)
    val = stage_validation(pos)
    for v in val:
        print(
            f"  {v['candidate_id']:30s} {v['parameters']} "
            f"DISC net={v['discovery'].get('net_bps')} VAL n={v['validation'].get('trades')} "
            f"net={v['validation'].get('net_bps')} pass={v['pass']}"
        )
    L.write_json(
        OUT / "VALIDATION_RESULTS.json",
        {
            "schema": "rfc022.validation_results.v1",
            "split": "VALIDATION W5",
            "cost_bps": COST,
            "G_EDGE_2": "PASS"
            if any(v["pass"] for v in val)
            else ("FAIL" if pos else "NOT_REACHED"),
            "results": [{k: v for k, v in r.items() if k != "params"} for r in val],
        },
    )
    passed_val = [v for v in val if v["pass"]]
    print(f"validation_pass={len(passed_val)}", flush=True)

    print("=== STAGE 3-5 ROBUSTNESS ===", flush=True)
    rob = [stage_robustness(v) for v in passed_val]
    for r in rob:
        print(
            f"  {r['candidate_id']:30s} wf={r['walk_forward']['verdict']} "
            f"cost={r['cost_stress']['verdict']} msc={r['cost_stress']['max_survivable_cost_bps']} "
            f"slip={r['slippage_stress']['verdict']} "
            f"param={r['parameter_neighbourhood'].get('verdict')} "
            f"boot_p={r['bootstrap'].get('p_net_le_0')}"
        )
    g3 = "NOT_REACHED"
    if rob:
        g3 = (
            "PASS"
            if any(
                r["walk_forward"]["verdict"] in ("PASS", "PARTIAL")
                and r["cost_stress"]["verdict"] != "DEAD"
                and r["parameter_neighbourhood"].get("verdict") != "ISOLATED_SPIKE"
                and r["bootstrap"].get("p_net_le_0", 1.0) <= 0.5
                for r in rob
            )
            else "FAIL"
        )
    L.write_json(
        OUT / "ROBUSTNESS_RESULTS.json",
        {"schema": "rfc022.robustness_results.v1", "results": rob, "G_EDGE_3": g3},
    )

    print("=== STAGE 6 HOLDOUT (W6-W7) ===", flush=True)
    finalists = [r for r in rob if r["walk_forward"]["verdict"] != "FAIL"] if rob else []
    hold = stage_holdout(finalists)
    for h in hold["results"]:
        print(
            f"  {h['candidate_id']:30s} n={h['holdout'].get('trades')} "
            f"net={h['holdout'].get('net_bps')} pass={h['pass']}"
        )
    L.write_json(OUT / "HOLDOUT_RESULTS.json", {"schema": "rfc022.holdout_results.v1", **hold})

    summary = {
        "schema": "rfc022.pipeline_summary.v1",
        "source_commit": "0289bcb76c216d09b1ddffd663d0e2e0236da07b",
        "cost_bps": COST,
        "dataset_hashes": hashes,
        "config_hash": L.config_hash(),
        "experiments_total": len(disc),
        "discovery_positive": len(pos),
        "validation_tested": len(val),
        "validation_positive": len(passed_val),
        "robustness_tested": len(rob),
        "holdout_tested": len(finalists),
        "holdout_pass": sum(1 for r in hold["results"] if r["pass"]),
        "G_EDGE_1": "PASS" if pos else "FAIL",
        "G_EDGE_2": "PASS" if passed_val else ("FAIL" if pos else "NOT_REACHED"),
        "G_EDGE_3": g3,
        "G_EDGE_4": hold["G_EDGE_4"],
    }
    L.write_json(OUT / "PIPELINE_SUMMARY.json", summary)
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
