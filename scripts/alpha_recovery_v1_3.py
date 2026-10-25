"""ARP-004 — cost-compatible edge campaign driver (research-only, deterministic).

Executes **only** the two pre-registered ARP-004 experiments:

* ``EXP-ARP-007`` — ``STRAT-CAND-019-VARIANT-B`` daily pivot fade;
* ``EXP-ARP-010`` — ``H-VOLSPIKE-MR-001`` volatility-spike mean reversion.

Stage order: manifest validation -> DEV -> DEV kill gate -> COST stress ->
VALIDATION -> ROBUSTNESS -> OOS gate (W7 opens only if every prior gate passes).

Run:

    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/alpha_recovery_v1_3.py

Writes JSON/Markdown under ``reports/alpha-recovery-v1-3/``. It reads the frozen
5-minute corpus and touches no runtime authority, no Risk module and no lifecycle.
"""

from __future__ import annotations

import hashlib
import json
import statistics
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.research.alpha_recovery import campaign as C  # noqa: E402
from trading_bot.research.alpha_recovery.daily import (  # noqa: E402
    Exp007Config,
    Exp007DailyPivotFade,
    Exp010Config,
    Exp010VolSpikeMR,
    daily_bars_from_5m,
    realized_daily_vol,
    simulate_daily,
)
from trading_bot.research.alpha_recovery.simulate import Trade  # noqa: E402

OUT = REPO / "reports/alpha-recovery-v1-3"
V12_EXP = REPO / "docs/research/alpha_recovery_v1_2/experiments"
ADMISSION_CFG = REPO / "config/strategy_admission.json"

COST_MULTIPLES = [0.5, 1.0, 1.25, 1.5, 2.0]
MIN_TRADES = 10
GROSS_KILL_BPS = 23.559  # COST_MODEL_V3 round trip (spec kill threshold)

#: Tracked files whose bytes define the frozen ARP-004 experiment code.
CODE_FILES: tuple[str, ...] = (
    "src/trading_bot/research/alpha_recovery/__init__.py",
    "src/trading_bot/research/alpha_recovery/series.py",
    "src/trading_bot/research/alpha_recovery/simulate.py",
    "src/trading_bot/research/alpha_recovery/experiments.py",
    "src/trading_bot/research/alpha_recovery/metrics.py",
    "src/trading_bot/research/alpha_recovery/campaign.py",
    "src/trading_bot/research/alpha_recovery/daily.py",
    "scripts/alpha_recovery_v1_3.py",
)

#: Robustness parameter perturbations, declared BEFORE any result is read.
ROBUSTNESS: dict[str, dict[str, Any]] = {
    "EXP-ARP-007": {
        "stop_atr_0_75": {"stop_atr": 0.75},
        "stop_atr_1_25": {"stop_atr": 1.25},
        "atr_period_10": {"atr_period": 10},
        "atr_period_20": {"atr_period": 20},
        "max_hold_days_2": {"max_hold_days": 2},
        "max_hold_days_4": {"max_hold_days": 4},
    },
    "EXP-ARP-010": {
        "vol_z_entry_1_75": {"vol_z_entry": 1.75},
        "vol_z_entry_2_25": {"vol_z_entry": 2.25},
        "vol_lookback_40": {"vol_lookback_days": 40},
        "vol_lookback_80": {"vol_lookback_days": 80},
        "stop_atr_1_5": {"stop_atr": 1.5},
        "stop_atr_2_5": {"stop_atr": 2.5},
        "target_atr_0_75": {"target_atr": 0.75},
        "target_atr_1_25": {"target_atr": 1.25},
        "ret_atr_0_75": {"ret_atr": 0.75},
        "ret_atr_1_25": {"ret_atr": 1.25},
        "max_hold_days_1": {"max_hold_days": 1},
        "max_hold_days_3": {"max_hold_days": 3},
    },
}

IDENTITY: dict[str, dict[str, Any]] = {
    "EXP-ARP-007": {
        "strategy_id": "STRAT-CAND-019-VARIANT-B",
        "arm": "PROJECT_DERIVED_VARIANT",
        "source_attribution": "NONE",
        "note": "NOT a source-faithful test of STRAT-CAND-019 (BLOCKED_NEEDS_SPEC).",
    },
    "EXP-ARP-010": {
        "strategy_id": "H-VOLSPIKE-MR-001",
        "arm": "PROJECT_DERIVED_VARIANT",
        "source_attribution": "NONE",
        "note": "New project hypothesis; no STRAT-CAND lineage.",
    },
}


# ------------------------------------------------------------------ helpers


def _lf_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def code_hash() -> str:
    combined = hashlib.sha256()
    for rel in CODE_FILES:
        combined.update(_lf_digest(REPO / rel).encode())
    return combined.hexdigest()


def write_json(path: Path, doc: Any) -> str:
    payload = json.dumps(doc, indent=2, sort_keys=True).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def config_hash() -> str:
    return C.sha256_file(ADMISSION_CFG)


# ------------------------------------------------------- manifest validation


def validate_manifests() -> dict[str, Any]:
    """Verify the frozen ARP-003 manifests still match config / data / cost."""
    report: dict[str, Any] = {"config_hash": config_hash(), "dataset_fingerprint": C.corpus_digest(),
                              "cost_bps_rt": C.cost_model_v3_rt_bps(), "experiments": {}}
    problems: list[str] = []
    for exp_id in IDENTITY:
        manifest_path = V12_EXP / exp_id / "MANIFEST.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        checks = {
            "manifest_sha256": _lf_digest(manifest_path),
            "spec_sha256": _lf_digest(V12_EXP / exp_id / "SPEC.md"),
            "config_hash_match": manifest["config_hash"] == report["config_hash"],
            "dataset_fingerprint_match": manifest["data"]["dataset_fingerprint"]
            == report["dataset_fingerprint"],
            "cost_model_match": abs(
                manifest["cost_model"]["round_trip_bps"] - report["cost_bps_rt"]
            )
            < 1e-9,
            "splits_match": manifest["splits"]["DEV"] == list(C.SPLIT_WINDOWS["DEV"])
            and manifest["splits"]["VALIDATION"] == list(C.SPLIT_WINDOWS["VALIDATION"])
            and manifest["splits"]["OOS_LOCK"] == list(C.SPLIT_WINDOWS["OOS_LOCK"]),
            "oos_locked": manifest["splits"]["oos_opened"] is False,
            "strategy_id_match": manifest["strategy_id"] == IDENTITY[exp_id]["strategy_id"],
        }
        if not all(v for k, v in checks.items() if k.endswith(("_match", "_locked"))):
            problems.append(exp_id)
        report["experiments"][exp_id] = checks
    report["all_valid"] = not problems
    report["problems"] = problems
    return report


# ------------------------------------------------------------- daily series


def daily_series(symbol: str, split: str) -> tuple[list[Any], dict[int, float]]:
    windows = C.SPLIT_WINDOWS[split]
    bars5: list[Any] = []
    for window in windows:
        bars5.extend(C.load_bars(symbol, window))
    return daily_bars_from_5m(bars5), realized_daily_vol(bars5)


def make_strategy(exp_id: str, params: dict[str, Any], vol: dict[int, float]) -> Any:
    if exp_id == "EXP-ARP-007":
        return Exp007DailyPivotFade(Exp007Config(**params))
    return Exp010VolSpikeMR(vol, Exp010Config(**params))


def run_split(
    exp_id: str,
    split: str,
    params: dict[str, Any],
    *,
    cost_bps_rt: float,
    entry_delay_days: int = 0,
) -> dict[str, list[Trade]]:
    out: dict[str, list[Trade]] = {}
    for key, symbol in C.SYMBOLS.items():
        daily, vol = daily_series(symbol, split)
        if not daily:
            out[key] = []
            continue
        strategy = make_strategy(exp_id, params, vol)
        out[key] = simulate_daily(
            strategy, daily, cost_bps_rt=cost_bps_rt, entry_delay_days=entry_delay_days
        ).trades
    return out


def summarize(exp_id: str, split: str, params: dict[str, Any], cost_bps_rt: float) -> dict[str, Any]:
    trades = run_split(exp_id, split, params, cost_bps_rt=cost_bps_rt)
    return C.summarize_run(trades, cost_bps_rt=cost_bps_rt)


# --------------------------------------------------------------- data coverage


def data_coverage(exp_id: str, params: dict[str, Any]) -> dict[str, Any]:
    cov: dict[str, Any] = {"experiment_id": exp_id, "splits": {}}
    for split in ("DEV", "VALIDATION", "OOS_LOCK"):
        rows: list[dict[str, Any]] = []
        eligible = 0
        for symbol in C.SYMBOLS.values():
            daily, vol = daily_series(symbol, split)
            if not daily:
                continue
            strategy = make_strategy(exp_id, params, vol)
            strategy.prepare(daily)
            sig = sum(1 for i in range(len(daily)) if strategy.entry(i) is not None)
            eligible += sig
            rows.append(
                {
                    "symbol": symbol,
                    "bars": len(daily),
                    "first_day": daily[0].timestamp // 86_400_000,
                    "last_day": daily[-1].timestamp // 86_400_000,
                    "signal_days": sig,
                }
            )
        cov["splits"][split] = {"assets": rows, "eligible_signal_days": eligible}
    return cov


# --------------------------------------------------------------- verdicts


def dev_verdict(dev: dict[str, Any]) -> dict[str, Any]:
    comb = dev["combined"]
    n = comb["trades"]
    gross = comb["expectancy_gross_bps"]
    top1 = comb["concentration"]["top1_share"]
    # §8 DEV first kill gate only: no-edge, sample, single-trade fragility. The
    # frozen "gross <= 23.559 bps -> REJECT_COSTS" criterion is a cost threshold,
    # so it is evaluated at the §9/§10 COST stage (identical final verdict).
    checks = {
        "sample_sufficient": n >= MIN_TRADES,
        "gross_expectancy_gt_0": bool(gross is not None and gross > 0),
        "not_single_trade_concentrated": bool(top1 is None or top1 <= 0.5),
    }
    if not checks["sample_sufficient"]:
        result = "INSUFFICIENT_EVIDENCE"
    elif not checks["gross_expectancy_gt_0"]:
        result = "REJECT_NO_EDGE"
    elif not checks["not_single_trade_concentrated"]:
        result = "REJECT_FRAGILE"
    else:
        result = "PASS"
    return {
        "result": result,
        "checks": checks,
        "thresholds": {"min_trades": MIN_TRADES, "top1_share_max": 0.5},
    }


def cost_gate(exp_id: str, params: dict[str, Any], base_bps: float) -> dict[str, Any]:
    stress: dict[str, Any] = {}
    for mult in COST_MULTIPLES:
        cost = base_bps * mult
        comb = C.summarize_run(
            run_split(exp_id, "DEV", params, cost_bps_rt=cost), cost_bps_rt=cost
        )["combined"]
        stress[f"{mult}x"] = {
            "cost_bps_rt": round(cost, 4),
            "trades": comb["trades"],
            "expectancy_gross_bps": comb["expectancy_gross_bps"],
            "expectancy_net_bps": comb["expectancy_net_bps"],
            "profit_factor": comb["profit_factor"],
        }
    base_net = stress["1.0x"]["expectancy_net_bps"]
    half_net = stress["0.5x"]["expectancy_net_bps"]
    gross = stress["1.0x"]["expectancy_gross_bps"]
    # break-even cost = the round-trip cost at which net expectancy hits zero.
    break_even = round(gross, 4) if gross is not None else None
    if base_net is not None and base_net > 0 and (gross or 0) > GROSS_KILL_BPS:
        result = "PASS"
    elif base_net is not None and base_net > 0:
        # positive net but below the frozen gross kill threshold -> cost-dominated
        result = "REJECT_COSTS"
    elif half_net is not None and half_net > 0:
        result = "REJECT_COST_FRAGILE"
    else:
        result = "REJECT_COSTS"
    return {"result": result, "base_cost_bps_rt": round(base_bps, 4),
            "gross_kill_bps": GROSS_KILL_BPS, "break_even_cost_bps": break_even,
            "stress": stress}


def validation_verdict(dev: dict[str, Any], val: dict[str, Any]) -> dict[str, Any]:
    d, v = dev["combined"], val["combined"]
    dg, vg = d["expectancy_gross_bps"], v["expectancy_gross_bps"]
    checks = {
        "val_gross_positive": bool(vg is not None and vg > 0),
        "no_material_collapse": bool(dg is not None and vg is not None and dg > 0 and vg >= 0.5 * dg),
        "val_net_positive": bool(v["expectancy_net_bps"] is not None and v["expectancy_net_bps"] > 0),
    }
    passed = all(checks.values())
    return {"result": "PASS" if passed else "REJECT_VALIDATION", "checks": checks,
            "dev_gross_bps": dg, "val_gross_bps": vg,
            "dev_net_bps": d["expectancy_net_bps"], "val_net_bps": v["expectancy_net_bps"],
            "dev_trades": d["trades"], "val_trades": v["trades"]}


def robustness(exp_id: str, params: dict[str, Any], base_bps: float) -> dict[str, Any]:
    out: dict[str, Any] = {}
    gross_bps: list[float] = []
    for name, delta in ROBUSTNESS[exp_id].items():
        merged = dict(params)
        merged.update(delta)
        comb = C.summarize_run(
            run_split(exp_id, "DEV", merged, cost_bps_rt=base_bps), cost_bps_rt=base_bps
        )["combined"]
        g = comb["expectancy_gross_bps"]
        out[name] = {"params": merged, "trades": comb["trades"],
                     "expectancy_gross_bps": g, "expectancy_net_bps": comb["expectancy_net_bps"]}
        if g is not None:
            gross_bps.append(g)
    base = C.summarize_run(
        run_split(exp_id, "DEV", params, cost_bps_rt=base_bps), cost_bps_rt=base_bps
    )["combined"]["expectancy_gross_bps"]
    # execution-delay and 2x-cost perturbations
    delayed = C.summarize_run(
        run_split(exp_id, "DEV", params, cost_bps_rt=base_bps, entry_delay_days=1),
        cost_bps_rt=base_bps,
    )["combined"]
    out["execution_delay_1day"] = {
        "trades": delayed["trades"],
        "expectancy_gross_bps": delayed["expectancy_gross_bps"],
        "expectancy_net_bps": delayed["expectancy_net_bps"],
    }
    stress2 = C.summarize_run(
        run_split(exp_id, "DEV", params, cost_bps_rt=base_bps * 2.0), cost_bps_rt=base_bps * 2.0
    )["combined"]
    out["cost_2_0x"] = {
        "trades": stress2["trades"],
        "expectancy_gross_bps": stress2["expectancy_gross_bps"],
        "expectancy_net_bps": stress2["expectancy_net_bps"],
    }
    positives = [g for g in gross_bps if g > 0]
    one_point = bool(base is not None and base > 0 and len(positives) <= 1)
    return {"result": "REJECT_FRAGILE" if one_point else "PASS", "one_point_optimum": one_point,
            "base_gross_bps": base, "variants": out}


# ------------------------------------------------------------------ capture


def capture_ratio(exp_id: str, params: dict[str, Any], dev: dict[str, Any]) -> dict[str, Any]:
    """Captured gross bps per trade vs the available 1-day move on the same data."""
    avail: list[float] = []
    for symbol in C.SYMBOLS.values():
        daily, _ = daily_series(symbol, "DEV")
        for i in range(len(daily) - 1):
            base = daily[i].close
            if base > 0:
                avail.append(abs(daily[i + 1].close / base - 1.0) * 10_000.0)
    measured = dev["combined"]["expectancy_gross_bps"]
    available = round(statistics.fmean(avail), 4) if avail else None
    ratio = round(measured / available, 4) if measured and available else None
    return {"measured_gross_bps_per_trade": measured, "available_1d_move_bps": available,
            "capture_ratio": ratio,
            "caveat": "available move is the mean |1-day move| over all DEV days; a mechanism "
            "captures only a fraction and this is descriptive, not evidence of edge."}


# ------------------------------------------------------------------ pipeline


def run_experiment(exp_id: str) -> dict[str, Any]:
    out_dir = OUT / exp_id
    identity = IDENTITY[exp_id]
    params = {
        "EXP-ARP-007": {"atr_period": 14, "stop_atr": 1.0, "max_hold_days": 3},
        "EXP-ARP-010": {"atr_period": 14, "vol_lookback_days": 60, "vol_z_entry": 2.0,
                        "ret_atr": 1.0, "stop_atr": 2.0, "target_atr": 1.0, "max_hold_days": 2},
    }[exp_id]
    base_cost = C.cost_model_v3_rt_bps()

    coverage = data_coverage(exp_id, params)
    write_json(out_dir / "DATA_COVERAGE.json", coverage)

    dev = summarize(exp_id, "DEV", params, base_cost)
    dev["verdict"] = dev_verdict(dev)
    dev["capture"] = capture_ratio(exp_id, params, dev)
    write_json(out_dir / "DEV.json", dev)

    decision: dict[str, Any] = {"experiment_id": exp_id, "identity": identity, "stages": {},
                                "oos_opened": False, "final": None}
    decision["stages"]["DEV"] = dev["verdict"]["result"]
    if dev["verdict"]["result"] != "PASS":
        decision["final"] = dev["verdict"]["result"]
        decision["stages"]["COST"] = "NOT_REACHED"
        decision["stages"]["VALIDATION"] = "NOT_REACHED"
        decision["stages"]["ROBUSTNESS"] = "NOT_REACHED"
        write_json(out_dir / "DECISION.json", decision)
        write_decision_md(out_dir, exp_id, params, decision, dev=dev)
        return {"experiment_id": exp_id, "decision": decision, "dev": dev}

    cost_res = cost_gate(exp_id, params, base_cost)
    write_json(out_dir / "COST_STRESS.json", cost_res)
    decision["stages"]["COST"] = cost_res["result"]
    decision["stages"]["VALIDATION"] = "NOT_REACHED"
    decision["stages"]["ROBUSTNESS"] = "NOT_REACHED"

    # Only DEV + COST survivors enter VALIDATION (§11) — the unseen split is
    # never evaluated for a cost-rejected experiment.
    if cost_res["result"] != "PASS":
        decision["final"] = cost_res["result"]
        write_json(out_dir / "DECISION.json", decision)
        write_decision_md(out_dir, exp_id, params, decision, dev=dev, cost=cost_res)
        return {"experiment_id": exp_id, "decision": decision, "dev": dev}

    val = summarize(exp_id, "VALIDATION", params, base_cost)
    val["verdict"] = validation_verdict(dev, val)
    write_json(out_dir / "VALIDATION.json", val)
    decision["stages"]["VALIDATION"] = val["verdict"]["result"]

    if val["verdict"]["result"] != "PASS":
        decision["final"] = val["verdict"]["result"]
        write_json(out_dir / "DECISION.json", decision)
        write_decision_md(out_dir, exp_id, params, decision, dev=dev, val=val, cost=cost_res)
        return {"experiment_id": exp_id, "decision": decision, "dev": dev}

    rob = robustness(exp_id, params, base_cost)
    write_json(out_dir / "ROBUSTNESS.json", rob)
    decision["stages"]["ROBUSTNESS"] = rob["result"]
    if rob["result"] != "PASS":
        decision["final"] = rob["result"]
        write_json(out_dir / "DECISION.json", decision)
        write_decision_md(out_dir, exp_id, params, decision, dev=dev, val=val, cost=cost_res)
        return {"experiment_id": exp_id, "decision": decision, "dev": dev}

    # every prior gate passed -> OOS opens, frozen, once (§19/§20)
    oos = summarize(exp_id, "OOS_LOCK", params, base_cost)
    decision["oos_opened"] = True
    write_json(out_dir / "OOS.json", oos)
    oos_pass = bool(
        oos["combined"]["expectancy_gross_bps"] is not None
        and oos["combined"]["expectancy_gross_bps"] > 0
        and oos["combined"]["expectancy_net_bps"] is not None
        and oos["combined"]["expectancy_net_bps"] > 0
    )
    decision["stages"]["OOS"] = "OOS_PASS" if oos_pass else "OOS_FAIL"
    decision["final"] = "PROMOTION_CANDIDATE" if oos_pass else "REJECT_VALIDATION"
    write_json(out_dir / "DECISION.json", decision)
    write_decision_md(out_dir, exp_id, params, decision, dev=dev, val=val, cost=cost_res)
    return {"experiment_id": exp_id, "decision": decision, "dev": dev}


def write_decision_md(out_dir: Path, exp_id: str, params: dict[str, Any],
                      decision: dict[str, Any], **stages: Any) -> None:
    lines = [
        f"# {exp_id} — DECISION",
        "",
        f"- strategy: `{IDENTITY[exp_id]['strategy_id']}`",
        f"- arm: `{IDENTITY[exp_id]['arm']}` — source attribution {IDENTITY[exp_id]['source_attribution']}",
        f"- {IDENTITY[exp_id]['note']}",
        f"- params: `{json.dumps(params, sort_keys=True)}`",
        "",
        "## Stage results",
        "",
    ]
    for stage, res in decision["stages"].items():
        lines.append(f"- {stage}: **{res}**")
    lines += ["", f"## FINAL: **{decision['final']}**", "",
              f"OOS opened: `{decision['oos_opened']}`", ""]
    if "dev" in stages:
        c = stages["dev"]["combined"]
        cap = stages["dev"]["capture"]
        lines += [
            "## DEV metrics (combined)",
            "",
            f"- trades: {c['trades']}",
            f"- gross expectancy: {c['expectancy_gross_bps']} bps",
            f"- cost: {c['cost_bps_rt']} bps · net expectancy: {c['expectancy_net_bps']} bps",
            f"- win rate: {c['win_rate']} · profit factor: {c['profit_factor']}",
            f"- max drawdown: {c['max_drawdown_bps']} bps",
            f"- top1 positive-net share: {c['concentration']['top1_share']}",
            f"- capture ratio (captured/available): {cap['capture_ratio']}",
            "",
        ]
    if "val" in stages:
        c = stages["val"]["combined"]
        lines += ["## VALIDATION metrics (combined)", "", f"- trades: {c['trades']}",
                  f"- gross expectancy: {c['expectancy_gross_bps']} bps",
                  f"- net expectancy: {c['expectancy_net_bps']} bps", ""]
    if "cost" in stages:
        lines += ["## COST_MODEL_V3 stress (DEV)", ""]
        for k, v in stages["cost"]["stress"].items():
            lines.append(f"- {k}: net {v['expectancy_net_bps']} bps (gross {v['expectancy_gross_bps']})")
        lines.append("")
    (out_dir / "DECISION.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = validate_manifests()
    write_json(OUT / "MANIFEST_VALIDATION.json", manifest)
    if not manifest["all_valid"]:
        print("FROZEN MANIFEST MISMATCH — STOP")
        print(json.dumps(manifest, indent=2))
        return 2
    env = {"code_hash": code_hash(), "config_hash": config_hash(),
           "dataset_fingerprint": C.corpus_digest(), "cost_bps_rt": C.cost_model_v3_rt_bps(),
           "code_files": list(CODE_FILES), "branch_head": _head()}
    write_json(OUT / "ENVIRONMENT.json", env)
    print(f"code_hash = {env['code_hash']}")
    print(f"cost_bps_rt = {env['cost_bps_rt']:.6f}")

    summary: dict[str, Any] = {}
    for exp_id in IDENTITY:
        res = run_experiment(exp_id)
        dec = res["decision"]
        dev = res["dev"]["combined"]
        summary[exp_id] = {
            "strategy_id": IDENTITY[exp_id]["strategy_id"],
            "stages": dec["stages"],
            "final": dec["final"],
            "oos_opened": dec["oos_opened"],
            "dev_trades": dev["trades"],
            "dev_gross_bps": dev["expectancy_gross_bps"],
            "dev_net_bps": dev["expectancy_net_bps"],
        }
        print(f"{exp_id}: DEV trades={dev['trades']} gross={dev['expectancy_gross_bps']} "
              f"net={dev['expectancy_net_bps']} -> {dec['final']}")
    write_json(OUT / "RUN_REPORT.json", {"environment": env, "experiments": summary})
    return 0


def _head() -> str:
    import subprocess

    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True
        ).stdout.strip()
    except Exception:
        return "UNKNOWN"


if __name__ == "__main__":
    raise SystemExit(main())
