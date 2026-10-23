"""ARP-002 campaign driver — freezes manifests, runs the staged experiment pipeline.

    .venv/Scripts/python.exe scripts/alpha_recovery_campaign.py

Stage order (§10-§17): freeze MANIFEST first -> DEV -> DEV kill gate -> VALIDATION
-> COST gate (COST_MODEL_V3 stress) -> ROBUSTNESS -> OOS (locked unless all pass).

This is research tooling: it writes JSON/Markdown under
``reports/alpha-recovery-v1-1/`` and touches no runtime authority.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.research.alpha_recovery import campaign as C  # noqa: E402

OUT = REPO / "reports/alpha-recovery-v1-1"
ARP001_EXP_DIR = REPO / "reports/alpha-recovery-v1/experiments"
DIAG_INPUTS = REPO / "reports/wp-strat-08/data/fresh_trades_base.csv"
ADMISSION_CFG = REPO / "config/strategy_admission.json"

COST_MULTIPLES = [0.5, 1.0, 1.25, 1.5, 2.0]
MIN_TRADES = 100

EXPERIMENTS: dict[str, dict[str, Any]] = {
    "EXP-ARP-001": {
        "strategy_id": "STRAT-CAND-001",
        "params": {"fast": 20, "mid": 40, "slow": 200, "cross_lookback": 60, "variant": "source"},
        "source_faithful": True,
        "kill_gross_bps": 25.0,
    },
    "EXP-ARP-002": {
        "strategy_id": "STRAT-CAND-016",
        "params": {"void_bars": 3, "void_atr_mult": 2.0, "retest_window": 48, "atr_period": 14},
        "source_faithful": False,
        "kill_gross_bps": 0.0,
    },
    "EXP-ARP-003": {
        "strategy_id": "STRAT-CAND-012",
        "params": {"divergence_window": 24, "atr_period": 14},
        "source_faithful": False,
        "kill_gross_bps": 0.0,
    },
    "EXP-ARP-005": {
        "strategy_id": "STRAT-CAND-019",
        "params": {"atr_period": 14, "stop_atr_mult": 0.5},
        "source_faithful": False,
        "kill_gross_bps": 0.0,
    },
}

KEY_TO_SYMBOL_003 = {"BTC_leader-ETH_laggard": "ETHUSDT", "SOL_leader-BTC_laggard": "BTCUSDT"}


def write_json(path: Path, doc: Any) -> str:
    import hashlib

    payload = json.dumps(doc, indent=2, sort_keys=True).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def config_hash() -> str:
    return C.sha256_file(ADMISSION_CFG)


def freeze_manifest(exp_id: str) -> dict[str, Any]:
    spec = EXPERIMENTS[exp_id]
    return {
        "experiment_id": exp_id,
        "strategy_id": spec["strategy_id"],
        "phase": "ARP-002",
        "source_faithful": spec["source_faithful"],
        "source_faithfulness_note": (
            "source rules resolvable for a source-faithful arm (MA40 exit)"
            if spec["source_faithful"]
            else "candidate spec declares SOURCE_FAITHFUL_EXPERIMENT=FALSE; parameters are "
            "PROJECT_DERIVED_VARIANT and no result may be attributed to the source"
        ),
        "code_hash": C.experiment_code_hash(),
        "code_files": list(C.CODE_FILES),
        "config_hash": config_hash(),
        "data_hash_used": C.corpus_digest(),
        "data_hash_arp001_84_files": "f873fa090dd03fbedb8b10dfcebb8f51d4cc476fb3265a7f43e1a082da5dc9d0",
        "data_files_used": 21,
        "data_note": "ARP-002 experiments read the 21 five-minute base files only; the ARP-001 "
        "digest covers all 84 files (incl. higher-timeframe variants).",
        "parameters": spec["params"],
        "dev_range": "W1_2026-03..W4_2026-06",
        "validation_range": "W5_2026-07..W6_2026-08",
        "oos_range": "W7_2026-09 (LOCKED, unopened)",
        "cost_model": "COST_MODEL_V3 / BINANCE_SPOT_STANDARD_TAKER (round trip from CostEngine)",
        "cost_bps_rt": C.cost_model_v3_rt_bps(),
        "cost_stress_multiples": COST_MULTIPLES,
        "pit_contract": "closed bars only; setup at bar i acted on close[i]; same closed bar for "
        "both legs of a cross-sectional pair; pivots from the prior completed UTC day; no HTF read",
        "kill_criteria": {
            "dev_gross_expectancy_bps_min": spec["kill_gross_bps"],
            "min_trades": MIN_TRADES,
            "single_trade_concentration_top1_share_max": 0.5,
            "cost_gate": "net expectancy must be > 0 at COST_MODEL_V3 base (1.0x)",
            "validation": "VAL gross expectancy <= 0, or VAL gross < 0.5 * DEV gross -> material collapse",
            "robustness": "one-point optimum across declared perturbations -> REJECT_FRAGILE",
            "oos": "opens only after DEV PASS + VALIDATION PASS + COST PASS + ROBUSTNESS PASS",
        },
        "builder": "ARP-002",
        "verifier": "UNASSIGNED",
    }


def make_key_map(exp_id: str) -> dict[str, str] | None:
    if exp_id == "EXP-ARP-003":
        return KEY_TO_SYMBOL_003
    return C.SYMBOLS


def run_split(exp_id: str, split: str, params: dict[str, Any], cost: float) -> dict[str, Any]:
    trades = C.run_experiment(exp_id, params, split, cost_bps_rt=cost)
    return C.summarize_run(trades, cost_bps_rt=cost, key_to_symbol=make_key_map(exp_id))


def dev_verdict(exp_id: str, dev: dict[str, Any]) -> dict[str, Any]:
    spec = EXPERIMENTS[exp_id]
    comb = dev["combined"]
    n = comb["trades"]
    gross = comb["expectancy_gross_bps"]
    top1 = comb["concentration"]["top1_share"]
    checks: dict[str, bool] = {}
    checks["gross_expectancy_positive"] = bool(gross is not None and gross > spec["kill_gross_bps"])
    checks["sample_usable"] = bool(n >= MIN_TRADES)
    checks["not_single_trade_concentrated"] = bool(top1 is None or top1 <= 0.5)
    if n == 0 or not checks["sample_usable"] or not checks["not_single_trade_concentrated"]:
        result = "INSUFFICIENT_EVIDENCE"
    elif not checks["gross_expectancy_positive"]:
        result = "REJECT_NO_EDGE"
    else:
        result = "PASS"
    return {
        "result": result,
        "checks": checks,
        "thresholds": {"gross_bps_min": spec["kill_gross_bps"], "min_trades": MIN_TRADES},
    }


def validation_verdict(dev: dict[str, Any], val: dict[str, Any]) -> dict[str, Any]:
    d, v = dev["combined"], val["combined"]
    dg, vg = d["expectancy_gross_bps"], v["expectancy_gross_bps"]
    checks: dict[str, bool] = {}
    checks["val_gross_positive"] = bool(vg is not None and vg > 0)
    checks["no_material_collapse"] = bool(
        dg is not None and vg is not None and dg > 0 and vg >= 0.5 * dg
    )
    checks["val_net_positive"] = bool(
        v["expectancy_net_bps"] is not None and v["expectancy_net_bps"] > 0
    )
    passed = all(checks.values())
    return {
        "result": "PASS" if passed else "REJECT_NO_EDGE",
        "checks": checks,
        "dev_gross_bps": dg,
        "val_gross_bps": vg,
        "dev_net_bps": d["expectancy_net_bps"],
        "val_net_bps": v["expectancy_net_bps"],
        "dev_trades": d["trades"],
        "val_trades": v["trades"],
    }


def cost_gate(exp_id: str, params: dict[str, Any], base_bps: float) -> dict[str, Any]:
    stress: dict[str, Any] = {}
    for mult in COST_MULTIPLES:
        cost = base_bps * mult
        trades = C.run_experiment(exp_id, params, "DEV", cost_bps_rt=cost)
        comb = C.summarize_run(trades, cost_bps_rt=cost)["combined"]
        stress[f"{mult}x"] = {
            "cost_bps_rt": round(cost, 4),
            "trades": comb["trades"],
            "expectancy_gross_bps": comb["expectancy_gross_bps"],
            "expectancy_net_bps": comb["expectancy_net_bps"],
            "profit_factor": comb["profit_factor"],
        }
    base_net = stress["1.0x"]["expectancy_net_bps"]
    half_net = stress["0.5x"]["expectancy_net_bps"]
    if base_net is not None and base_net > 0:
        result = "PASS"
    elif half_net is not None and half_net > 0:
        result = "REJECT_COST_FRAGILE"  # only survives at half the realistic cost
    else:
        result = "REJECT_COSTS"
    return {"result": result, "base_cost_bps_rt": round(base_bps, 4), "stress": stress}


def robustness(exp_id: str, params: dict[str, Any], cost: float) -> dict[str, Any]:
    variants = C.expand_variants(exp_id, params)
    out: dict[str, Any] = {}
    gross_bps: list[float] = []
    for ev in variants:
        trades = C.run_experiment(exp_id, ev.params, "DEV", cost_bps_rt=cost)
        comb = C.summarize_run(trades, cost_bps_rt=cost)["combined"]
        g = comb["expectancy_gross_bps"]
        out[ev.variant] = {
            "params": ev.params,
            "trades": comb["trades"],
            "expectancy_gross_bps": g,
            "expectancy_net_bps": comb["expectancy_net_bps"],
        }
        if g is not None:
            gross_bps.append(g)
    base = out["base"]["expectancy_gross_bps"]
    positives = [g for g in gross_bps if g > 0]
    one_point = bool(base is not None and base > 0 and len(positives) <= 1)
    # execution-delay and higher-cost perturbations
    delayed = C.run_experiment(exp_id, params, "DEV", cost_bps_rt=cost, entry_delay=1)
    delayed_comb = C.summarize_run(delayed, cost_bps_rt=cost)["combined"]
    out["execution_delay_1bar"] = {
        "trades": delayed_comb["trades"],
        "expectancy_gross_bps": delayed_comb["expectancy_gross_bps"],
        "expectancy_net_bps": delayed_comb["expectancy_net_bps"],
    }
    return {
        "result": "REJECT_FRAGILE" if one_point else "PASS",
        "one_point_optimum": one_point,
        "variants": out,
    }


def run_experiment(exp_id: str) -> dict[str, Any]:
    exp_dir = OUT / "experiments" / exp_id
    manifest = freeze_manifest(exp_id)
    write_json(exp_dir / "MANIFEST.json", manifest)  # frozen BEFORE any result
    params = EXPERIMENTS[exp_id]["params"]
    cost = C.cost_model_v3_rt_bps()

    dev = run_split(exp_id, "DEV", params, cost)
    dev["verdict"] = dev_verdict(exp_id, dev)
    write_json(exp_dir / "DEV.json", dev)

    decision: dict[str, Any] = {"experiment_id": exp_id, "stages": {}, "final": None}
    decision["stages"]["DEV"] = dev["verdict"]["result"]
    if dev["verdict"]["result"] != "PASS":
        decision["final"] = dev["verdict"]["result"]
        decision["oos_opened"] = False
        write_json(exp_dir / "DECISION.json", decision)
        write_decision_md(exp_dir, exp_id, manifest, decision, dev=dev)
        return {"experiment_id": exp_id, "manifest": manifest, "dev": dev, "decision": decision}

    # §11 DEV -> §13 COST -> §14 VALIDATION -> §16 ROBUSTNESS (stages recorded in this order)
    cost_res = cost_gate(exp_id, params, cost)
    write_json(exp_dir / "COST_STRESS.json", cost_res)
    decision["stages"]["COST"] = cost_res["result"]

    val = run_split(exp_id, "VALIDATION", params, cost)
    val["verdict"] = validation_verdict(dev, val)
    write_json(exp_dir / "VALIDATION.json", val)
    decision["stages"]["VALIDATION"] = val["verdict"]["result"]

    if cost_res["result"] != "PASS":
        decision["stages"]["ROBUSTNESS"] = "NOT_REACHED"
        decision["final"] = cost_res["result"]
    elif val["verdict"]["result"] != "PASS":
        decision["stages"]["ROBUSTNESS"] = "NOT_REACHED"
        decision["final"] = val["verdict"]["result"]
    else:
        rob = robustness(exp_id, params, cost)
        write_json(exp_dir / "ROBUSTNESS.json", rob)
        decision["stages"]["ROBUSTNESS"] = rob["result"]
        decision["final"] = rob["result"] if rob["result"] != "PASS" else "PROMOTION_CANDIDATE"

    decision["oos_opened"] = False
    write_json(exp_dir / "DECISION.json", decision)
    write_decision_md(exp_dir, exp_id, manifest, decision, dev=dev, val=val, cost=cost_res)
    return {
        "experiment_id": exp_id,
        "manifest": manifest,
        "dev": dev,
        "val": val,
        "cost": cost_res,
        "decision": decision,
    }


def write_decision_md(
    exp_dir: Path, exp_id: str, manifest: dict[str, Any], decision: dict[str, Any], **stages: Any
) -> None:
    lines = [
        f"# {exp_id} — DECISION",
        "",
        f"- strategy: `{manifest['strategy_id']}`",
        f"- source_faithful: `{manifest['source_faithful']}` — {manifest['source_faithfulness_note']}",
        f"- code_hash: `{manifest['code_hash']}`",
        f"- data_hash_used: `{manifest['data_hash_used']}`",
        f"- cost_bps_rt: `{manifest['cost_bps_rt']}`",
        "",
        "## Stage results",
        "",
    ]
    for stage, res in decision["stages"].items():
        lines.append(f"- {stage}: **{res}**")
    lines += [
        "",
        f"## FINAL: **{decision['final']}**",
        "",
        f"OOS opened: `{decision['oos_opened']}`",
        "",
    ]
    if "dev" in stages:
        c = stages["dev"]["combined"]
        lines += [
            "## DEV metrics (combined)",
            "",
            f"- trades: {c['trades']}",
            f"- gross expectancy: {c['expectancy_gross_bps']} bps",
            f"- net expectancy: {c['expectancy_net_bps']} bps",
            f"- win rate: {c['win_rate']} · profit factor: {c['profit_factor']}",
            f"- max drawdown: {c['max_drawdown_bps']} bps",
            f"- top1 positive-net share: {c['concentration']['top1_share']}",
            "",
        ]
    if "val" in stages:
        c = stages["val"]["combined"]
        lines += [
            "## VALIDATION metrics (combined)",
            "",
            f"- trades: {c['trades']}",
            f"- gross expectancy: {c['expectancy_gross_bps']} bps",
            f"- net expectancy: {c['expectancy_net_bps']} bps",
            "",
        ]
    if "cost" in stages:
        lines += ["## COST_MODEL_V3 stress (DEV)", ""]
        for k, v in stages["cost"]["stress"].items():
            lines.append(
                f"- {k}: net {v['expectancy_net_bps']} bps (gross {v['expectancy_gross_bps']})"
            )
        lines.append("")
    (exp_dir / "DECISION.md").write_text("\n".join(lines), encoding="utf-8")


def copy_specs() -> None:
    for exp_id in EXPERIMENTS:
        src = ARP001_EXP_DIR / exp_id / "SPEC.md"
        if src.exists():
            dst = OUT / "experiments" / exp_id / "SPEC.md"
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)


def run_diagnostics() -> dict[str, Any]:
    from trading_bot.research.strategy_failure_diagnostics import (
        DiagnosticsInputs,
        compute_diagnostics,
        write_document,
    )

    out_dir = OUT / "diagnostics"
    inputs1 = DiagnosticsInputs(
        trades=DIAG_INPUTS,
        corpus=REPO / "reports/strategy-baseline/data",
        results_dir=REPO / "reports/strategy-baseline",
        out=out_dir / "strategy_failure_metrics.json",
    )
    doc1 = compute_diagnostics(inputs1, enrich=True)
    h1 = write_document(doc1, inputs1.out)
    doc2 = compute_diagnostics(inputs1, enrich=True)
    h2 = write_document(doc2, out_dir / "strategy_failure_metrics.run2.json")
    (out_dir / "strategy_failure_metrics.run2.json").unlink()
    base = compute_diagnostics(inputs1, enrich=False)
    hbase = write_document(base, out_dir / "strategy_failure_metrics.arp001_compat.json")
    return {
        "enriched_sha256_run1": h1,
        "enriched_sha256_run2": h2,
        "deterministic": h1 == h2,
        "arp001_compat_lf_sha256": hbase,
        "hashes": {
            "code": C.sha256_file(
                REPO / "src/trading_bot/research/strategy_failure_diagnostics.py"
            ),
            "data": C.sha256_file(DIAG_INPUTS),
            "config": config_hash(),
            "corpus_used_21_files": C.corpus_digest(),
        },
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    copy_specs()
    diag = run_diagnostics()
    write_json(OUT / "DIAGNOSTICS_REPRODUCIBILITY.json", diag)
    results = {exp_id: run_experiment(exp_id) for exp_id in EXPERIMENTS}
    summary = {
        exp_id: {
            "final": r["decision"]["final"],
            "stages": r["decision"]["stages"],
            "oos_opened": r["decision"]["oos_opened"],
            "dev_gross_bps": r["dev"]["combined"]["expectancy_gross_bps"],
            "dev_net_bps": r["dev"]["combined"]["expectancy_net_bps"],
        }
        for exp_id, r in results.items()
    }
    write_json(OUT / "CAMPAIGN_SUMMARY.json", summary)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
