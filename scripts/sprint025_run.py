"""RFC-025 Part C — hypothesis registry, plan, and experiment runner.

Pre-registers the directional hypotheses derived from the Part B information
gate, then runs ONE frozen configuration per variant on DISCOVERY (W1-W4) and
VALIDATION (W5). The HOLDOUT (W6-W7) is never loaded here.

Frozen shared exit (identical to RFC-024 for comparability): target 2.0xATR,
stop 1.5xATR, hold 16 bars. Cost = COST_MODEL_V3 (23.790569 bps).
"""

from __future__ import annotations

import csv
import sys
from typing import Any

sys.path.insert(0, "scripts")
import sprint002_lib as L
import sprint002_pipeline as P
import sprint025_lib as OL
import sprint025_signals as SG

OUT = OL.SPRINT_OUT
WARM = 262
TARGET_MULT = 2.0
STOP_MULT = 1.5
HOLD_BARS = 16
MIN_TRADES = L.MIN_TRADES

CORE_HYPOTHESES: list[dict[str, Any]] = [
    {"id": "H-ORTHO-01", "family": "basis_reversion", "feature": "basis_z", "cond": "VOL",
     "statement": "extreme standardised basis during a certified vol event reverts (fade the sign)"},
    {"id": "H-ORTHO-02", "family": "basis_reversion", "feature": "basis", "cond": "VOL",
     "statement": "extreme raw basis level during a vol event reverts"},
    {"id": "H-ORTHO-03", "family": "basis_change", "feature": "basis_diff", "cond": "VOL",
     "statement": "a basis jump during a vol event fades"},
    {"id": "H-ORTHO-04", "family": "taker_persistence", "feature": "taker_persist", "cond": "VOL",
     "statement": "persistent aggressor imbalance during a vol event reverts"},
    {"id": "H-ORTHO-05", "family": "taker_imbalance", "feature": "taker_imbalance", "cond": "VOL",
     "statement": "one-bar aggressor imbalance during a vol event reverts"},
    {"id": "H-ORTHO-06", "family": "funding_reversion", "feature": "funding_z", "cond": "VOL",
     "statement": "extreme funding during a vol event reverts (Part B sign flipped -> expected fail)"},
    {"id": "H-ORTHO-07", "family": "basis_reversion_ablation", "feature": "basis_z", "cond": "ALL",
     "statement": "basis reversion WITHOUT the volatility condition (ablation A)"},
    {"id": "H-ORTHO-08", "family": "taker_reversion_ablation", "feature": "taker_persist", "cond": "ALL",
     "statement": "taker persistence reversion WITHOUT the volatility condition (ablation A)"},
    {"id": "H-ORTHO-09", "family": "interaction_vol_basis", "feature": "basis_z", "cond": "VOL",
     "statement": "interaction: vol shock x basis (targets basis only where volatility expands)"},
    {"id": "H-ORTHO-10", "family": "interaction_vol_taker", "feature": "taker_persist", "cond": "VOL",
     "statement": "interaction: vol shock x taker persistence"},
]

FEATURES = ("basis_z", "basis", "basis_diff", "taker_persist", "taker_imbalance")
CONDS = ("VOL", "ALL")
Z_THRS = (1.0, 1.5, 2.0)
TFS = ("30m", "1h")

MAX_CORE_HYPOTHESES = 20
MAX_PARAMETER_VARIANTS = 100


def registry_payload() -> dict[str, Any]:
    variants: list[dict[str, Any]] = []
    n = 0
    for hyp in CORE_HYPOTHESES:
        for tf in TFS:
            for z in Z_THRS:
                n += 1
                variants.append({
                    "experiment_id": f"EXP-S003-{n:04d}",
                    "hypothesis_id": hyp["id"],
                    "family": hyp["family"],
                    "feature": hyp["feature"],
                    "condition": hyp["cond"],
                    "z_thr": z,
                    "timeframe": tf,
                    "direction": "contrarian (IC<0)",
                    "exit": {"target": TARGET_MULT, "stop": STOP_MULT, "hold": HOLD_BARS},
                })
        # interactions only get one tight variant each (duplicate of 01/04 with vol=True)
    return {
        "max_core_hypotheses": MAX_CORE_HYPOTHESES,
        "max_parameter_variants": MAX_PARAMETER_VARIANTS,
        "core_hypotheses": CORE_HYPOTHESES,
        "n_core": len(CORE_HYPOTHESES),
        "n_variants": len(variants),
        "variants": variants,
    }


def write_plan_and_registry() -> dict[str, Any]:
    reg = registry_payload()
    reg["registry_hash"] = OL.sha256_obj(reg["variants"])
    reg["cost_bps"] = L.CERTIFIED_ROUND_TRIP_BPS
    reg["splits"] = {k: list(v) for k, v in L.SPLITS.items()}
    OL.write_json(OUT / "HYPOTHESIS_REGISTRY.json", reg)
    OL.write_json(
        OUT / "SPRINT003_PLAN.json",
        {
            "phase": "RFC-025 SPRINT 003",
            "mission": "orthogonal positioning/flow information for direction; certified volatility as context",
            "data_sources": ["ORTHO-FUNDING", "ORTHO-BASIS", "ORTHO-TAKERFLOW"],
            "information_gate": "G_ORTHO_INFO_1",
            "cost_model": "COST_MODEL_V3",
            "cost_bps": L.CERTIFIED_ROUND_TRIP_BPS,
            "frozen_exit": {"target": TARGET_MULT, "stop": STOP_MULT, "hold": HOLD_BARS},
            "registry_hash": reg["registry_hash"],
            "holdout": "LOCKED / UNREAD until G_EDGE_3",
        },
    )
    _reg_md(reg)
    _plan_md(reg)
    return reg


def run_experiment(v: dict[str, Any], windows: tuple[str, ...]) -> tuple[list[L.Trade], int]:
    trades: list[L.Trade] = []
    eval_bars = 0
    for asset in OL.ASSETS:
        for window in windows:
            b = OL.bundle_for(asset, window, v["timeframe"])
            sig = SG.signal_array(asset, b, v["feature"], v["z_thr"], v["condition"] == "VOL")
            spec = L.Spec(
                candidate_id=f"{v['feature']}@{v['timeframe']}|{v['condition']}|z{v['z_thr']}",
                hypothesis_id=v["hypothesis_id"],
                family=v["family"],
                timeframe=v["timeframe"],
                signals=P._const_signal(sig),
                warmup=WARM,
                atr_target_mult=TARGET_MULT,
                atr_target_is_atr=True,
                atr_stop_mult=STOP_MULT,
                hold_bars=HOLD_BARS,
            )
            trades.extend(L.run_spec(spec, b, asset, window))
            eval_bars += max(0, len(b) - WARM)
    return trades, eval_bars


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    reg = write_plan_and_registry()
    rows: list[dict[str, Any]] = []
    for v in reg["variants"]:
        d_tr, d_bars = run_experiment(v, L.SPLITS["DISCOVERY"])
        v_tr, v_bars = run_experiment(v, L.SPLITS["VALIDATION"])
        tf = v["timeframe"]
        dm = L.metrics(d_tr, d_bars, L.TF_MIN[tf]) if d_tr else {"trades": 0}
        vm = L.metrics(v_tr, v_bars, L.TF_MIN[tf]) if v_tr else {"trades": 0}
        row = {
            **v,
            "discovery": dm,
            "validation": vm,
            "g_edge_1": _g_edge_1(dm),
            "g_edge_2": _g_edge_2(dm, vm),
        }
        rows.append(row)
    with (OUT / "EXPERIMENT_REGISTRY.jsonl").open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(_json_line(row))
    _write_matrix(rows)
    _write_results(rows)
    print("variants:", len(rows))
    pos = [r for r in rows if r["g_edge_1"] == "PASS_DISCOVERY"]
    print("G_EDGE_1 passes:", len(pos))
    for r in pos[:10]:
        print("  ", r["candidate_id"], "D net", r["discovery"].get("net_bps"), "V net", r["validation"].get("net_bps"))


def _g_edge_1(m: dict[str, Any]) -> str:
    if not m or m.get("trades", 0) < MIN_TRADES:
        return "INSUFFICIENT_SAMPLE"
    if m.get("net_bps", -1) <= 0 or m.get("net_pnl_usdt", -1) <= 0:
        return "NEGATIVE_NET_EDGE"
    if m.get("single_trade_dependency"):
        return "TRADE_CONCENTRATION"
    return "PASS_DISCOVERY"


def _g_edge_2(dm: dict[str, Any], vm: dict[str, Any]) -> str:
    if not dm or dm.get("trades", 0) < MIN_TRADES:
        return "NOT_REACHED"
    if dm.get("net_bps", -1) <= 0:
        return "NOT_REACHED"
    if not vm or vm.get("trades", 0) < 10:
        return "VALIDATION_INCONCLUSIVE"
    if vm.get("net_bps", -1) <= 0:
        return "VALIDATION_FAIL"
    return "PASS_VALIDATION"


def _json_line(row: dict[str, Any]) -> str:
    import json

    return json.dumps(row, sort_keys=True, default=str, ensure_ascii=False) + "\n"


def _write_matrix(rows: list[dict[str, Any]]) -> None:
    cols = ["experiment_id", "hypothesis_id", "feature", "condition", "z_thr", "timeframe",
            "d_trades", "d_gross_bps", "d_net_bps", "d_pf", "d_win_rate", "d_sharpe",
            "v_trades", "v_gross_bps", "v_net_bps", "v_pf", "v_win_rate", "v_sharpe",
            "g_edge_1", "g_edge_2"]
    with (OUT / "EXPERIMENT_MATRIX.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for r in rows:
            d, v = r["discovery"], r["validation"]
            w.writerow([
                r["experiment_id"], r["hypothesis_id"], r["feature"], r["condition"], r["z_thr"],
                r["timeframe"], d.get("trades"), d.get("gross_bps"), d.get("net_bps"),
                d.get("profit_factor"), d.get("win_rate"), d.get("sharpe"),
                v.get("trades"), v.get("gross_bps"), v.get("net_bps"),
                v.get("profit_factor"), v.get("win_rate"), v.get("sharpe"),
                r["g_edge_1"], r["g_edge_2"],
            ])


def _write_results(rows: list[dict[str, Any]]) -> None:
    disc = {"level": "DISCOVERY", "experiments": rows}
    val = {"level": "VALIDATION", "experiments": rows}
    OL.write_json(OUT / "DISCOVERY_RESULTS.json", disc)
    OL.write_json(OUT / "VALIDATION_RESULTS.json", val)
    lines = [
        "# DISCOVERY_RESULTS — RFC-025 Part C",
        "",
        "Engine: certified event engine, frozen exit 2.0xATR/1.5xATR/hold 16, cost 23.790569 bps.",
        "",
        "| experiment | hyp | feature | cond | z | tf | trades | gross | net | PF | G_EDGE_1 |",
        "| --- | --- | --- | --- | ---: | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for r in rows:
        d = r["discovery"]
        lines.append(
            f"| {r['experiment_id']} | {r['hypothesis_id']} | {r['feature']} | {r['condition']} | "
            f"{r['z_thr']} | {r['timeframe']} | {d.get('trades')} | {d.get('gross_bps')} | "
            f"{d.get('net_bps')} | {d.get('profit_factor')} | {r['g_edge_1']} |"
        )
    OL.write_md(OUT / "DISCOVERY_RESULTS.md", "\n".join(lines))
    vlines = [
        "# VALIDATION_RESULTS — RFC-025 Part C",
        "",
        "| experiment | hyp | feature | cond | z | tf | trades | gross | net | PF | G_EDGE_2 |",
        "| --- | --- | --- | --- | ---: | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for r in rows:
        v = r["validation"]
        vlines.append(
            f"| {r['experiment_id']} | {r['hypothesis_id']} | {r['feature']} | {r['condition']} | "
            f"{r['z_thr']} | {r['timeframe']} | {v.get('trades')} | {v.get('gross_bps')} | "
            f"{v.get('net_bps')} | {v.get('profit_factor')} | {r['g_edge_2']} |"
        )
    OL.write_md(OUT / "VALIDATION_RESULTS.md", "\n".join(vlines))


def _reg_md(reg: dict[str, Any]) -> None:
    lines = [
        "# HYPOTHESIS_REGISTRY — RFC-025",
        "",
        f"Presupuesto: {reg['max_core_hypotheses']} hipótesis core, {reg['max_parameter_variants']} variantes.",
        f"Registradas: {reg['n_core']} core, {reg['n_variants']} variantes. Hash: `{reg['registry_hash']}`.",
        "",
        "| id | family | feature | condición | dirección |",
        "| --- | --- | --- | --- | --- |",
    ]
    for h in reg["core_hypotheses"]:
        lines.append(f"| {h['id']} | {h['family']} | {h['feature']} | {h['cond']} | contrarian |")
    lines += ["", "## Variantes", "", "| exp | hyp | feature | cond | z | tf |", "| --- | --- | --- | --- | ---: | --- |"]
    for v in reg["variants"]:
        lines.append(f"| {v['experiment_id']} | {v['hypothesis_id']} | {v['feature']} | {v['condition']} | {v['z_thr']} | {v['timeframe']} |")
    lines.append("")
    OL.write_md(OUT / "HYPOTHESIS_REGISTRY.md", "\n".join(lines))


def _plan_md(reg: dict[str, Any]) -> None:
    lines = [
        "# SPRINT003_PLAN — RFC-025",
        "",
        "1. Auditoría de datos ortogonales (G_ORTHO_DATA).",
        "2. Certificación PIT + future poisoning.",
        "3. Auditoría de información ANTES de estrategias (G_ORTHO_INFO_1).",
        "4. Sólo las hipótesis que pasan el information gate pasan a Parte C.",
        "5. Discovery → Validation → Robustness → Holdout (bloqueado hasta G_EDGE_3).",
        "",
        f"Coste congelado: COST_MODEL_V3 = {reg['cost_bps']} bps round trip.",
        f"Salida congelada: target {TARGET_MULT}xATR / stop {STOP_MULT}xATR / hold {HOLD_BARS} barras.",
        "",
    ]
    OL.write_md(OUT / "SPRINT003_PLAN.md", "\n".join(lines))


if __name__ == "__main__":
    main()
