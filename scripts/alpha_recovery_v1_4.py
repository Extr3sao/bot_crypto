"""ARP-005 — cost-compatible alpha discovery + research-infrastructure recovery.

Executes only the three pre-registered ARP-005 experiments:

* ``EXP-ARP-009`` — ``H-XSEC-RELSTR-001`` cross-sectional relative strength
  (baseline corpus, new minimal PIT-safe ranker);
* ``EXP-ARP-011`` — ``H-VOLEXP-BREAK-001`` daily volatility-expansion breakout
  (baseline corpus);
* ``EXP-ARP-012`` — ``STRAT-CAND-016-VARIANT-B`` liquidity-void reversal
  (EXTENDED corpus, the ``EXP-ARP-006`` rules).

Stage order: manifest validation -> DEV -> DEV kill gate -> COST stress ->
VALIDATION -> ROBUSTNESS -> OOS gate (W7 opens only if every prior gate passes).

Run:

    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/alpha_recovery_v1_4.py

Writes JSON/Markdown under ``reports/alpha-recovery-v1-4/``. It reads the frozen and
extended 5m corpora and touches no runtime authority, no Risk module and no lifecycle.
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

from trading_bot.market_data.types import OHLCV  # noqa: E402
from trading_bot.research.alpha_recovery import campaign as C  # noqa: E402
from trading_bot.research.alpha_recovery import extended as E  # noqa: E402
from trading_bot.research.alpha_recovery.daily import (  # noqa: E402
    daily_bars_from_5m,
    realized_daily_vol,
    simulate_daily,
)
from trading_bot.research.alpha_recovery.daily_v1_4 import (  # noqa: E402
    Exp006Config,
    Exp006LiquidityVoidReversal,
    Exp011Config,
    Exp011VolExpansionBreakout,
    XsecConfig,
    simulate_xsec,
)

OUT = REPO / "reports/alpha-recovery-v1-4"
V14_EXP = REPO / "docs/research/alpha_recovery_v1_4/experiments"
ADMISSION_CFG = REPO / "config/strategy_admission.json"

COST_MULTIPLES = [0.5, 1.0, 1.25, 1.5, 2.0]
GROSS_KILL_BPS = 23.559016994374947

CODE_FILES: tuple[str, ...] = (
    "src/trading_bot/research/alpha_recovery/__init__.py",
    "src/trading_bot/research/alpha_recovery/series.py",
    "src/trading_bot/research/alpha_recovery/simulate.py",
    "src/trading_bot/research/alpha_recovery/experiments.py",
    "src/trading_bot/research/alpha_recovery/metrics.py",
    "src/trading_bot/research/alpha_recovery/campaign.py",
    "src/trading_bot/research/alpha_recovery/daily.py",
    "src/trading_bot/research/alpha_recovery/xsec.py",
    "src/trading_bot/research/alpha_recovery/extended.py",
    "src/trading_bot/research/alpha_recovery/daily_v1_4.py",
    "scripts/alpha_recovery_v1_4.py",
)

IDENTITY: dict[str, dict[str, Any]] = {
    "EXP-ARP-009": {"strategy_id": "H-XSEC-RELSTR-001", "dataset": "baseline",
                    "kind": "xsec", "min_trades": 20, "max_hold_days": 30},
    "EXP-ARP-011": {"strategy_id": "H-VOLEXP-BREAK-001", "dataset": "baseline",
                    "kind": "daily", "min_trades": 10, "max_hold_days": 10},
    "EXP-ARP-012": {"strategy_id": "STRAT-CAND-016-VARIANT-B", "dataset": "extended",
                    "kind": "daily", "min_trades": 10, "max_hold_days": 5},
}

BASE_PARAMS: dict[str, dict[str, Any]] = {
    "EXP-ARP-009": {"lookback_days": 30, "max_hold_days": 30, "long_only": True},
    "EXP-ARP-011": {"atr_period": 14, "breakout_lookback_days": 20, "vol_gate_days": 20,
                    "stop_atr": 1.5, "target_atr": 3.0, "max_hold_days": 10},
    "EXP-ARP-012": {"atr_period": 14, "void_min_days": 3, "void_min_atr": 2.0,
                    "retest_lookback_days": 10, "stop_atr": 1.5, "target_atr": 3.0,
                    "max_hold_days": 5},
}

#: Robustness perturbations declared BEFORE any result is read (§13).
ROBUSTNESS: dict[str, dict[str, Any]] = {
    "EXP-ARP-009": {
        "lookback_20": {"lookback_days": 20}, "lookback_40": {"lookback_days": 40},
        "max_hold_20": {"max_hold_days": 20}, "max_hold_45": {"max_hold_days": 45},
    },
    "EXP-ARP-011": {
        "breakout_lookback_15": {"breakout_lookback_days": 15},
        "breakout_lookback_25": {"breakout_lookback_days": 25},
        "vol_gate_15": {"vol_gate_days": 15}, "vol_gate_25": {"vol_gate_days": 25},
        "stop_atr_1_25": {"stop_atr": 1.25}, "stop_atr_1_75": {"stop_atr": 1.75},
        "max_hold_5": {"max_hold_days": 5}, "max_hold_15": {"max_hold_days": 15},
    },
    "EXP-ARP-012": {
        "stop_atr_1_25": {"stop_atr": 1.25}, "stop_atr_1_75": {"stop_atr": 1.75},
        "target_atr_2_5": {"target_atr": 2.5}, "target_atr_3_5": {"target_atr": 3.5},
        "retest_7": {"retest_lookback_days": 7}, "retest_13": {"retest_lookback_days": 13},
        "void_atr_1_75": {"void_min_atr": 1.75}, "void_atr_2_25": {"void_min_atr": 2.25},
        "max_hold_3": {"max_hold_days": 3}, "max_hold_7": {"max_hold_days": 7},
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


def split_windows(exp_id: str, split: str) -> tuple[str, ...]:
    src = E.EXT_SPLIT_WINDOWS if IDENTITY[exp_id]["dataset"] == "extended" else C.SPLIT_WINDOWS
    return src[split]


def dataset_digest(exp_id: str) -> str:
    return E.ext_corpus_digest() if IDENTITY[exp_id]["dataset"] == "extended" else C.corpus_digest()


def load_daily(symbol: str, exp_id: str, split: str) -> list[OHLCV]:
    bars5: list[OHLCV] = []
    for window in split_windows(exp_id, split):
        bars5.extend(E.load_ext_bars(symbol, window))
    return daily_bars_from_5m(bars5)


def load_daily_with_vol(symbol: str, exp_id: str, split: str) -> tuple[list[OHLCV], dict[int, float]]:
    bars5: list[OHLCV] = []
    for window in split_windows(exp_id, split):
        bars5.extend(E.load_ext_bars(symbol, window))
    return daily_bars_from_5m(bars5), realized_daily_vol(bars5)


# ---------------------------------------------------- manifest validation


def validate_manifests() -> dict[str, Any]:
    report: dict[str, Any] = {"config_hash": config_hash(), "cost_bps_rt": C.cost_model_v3_rt_bps(),
                              "experiments": {}}
    problems: list[str] = []
    for exp_id in IDENTITY:
        manifest_path = V14_EXP / exp_id / "MANIFEST.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected_splits = {
            s: list(split_windows(exp_id, s)) for s in ("DEV", "VALIDATION", "OOS_LOCK")
        }
        dataset = dataset_digest(exp_id)
        checks = {
            "manifest_sha256": _lf_digest(manifest_path),
            "spec_sha256": _lf_digest(V14_EXP / exp_id / "SPEC.md"),
            "config_hash_match": manifest["config_hash"] == report["config_hash"],
            "dataset_fingerprint_match": manifest["data"]["dataset_fingerprint"] == dataset,
            "cost_model_match": manifest["cost_model"]["version"] == "COST_MODEL_V3",
            "splits_match": all(manifest["splits"][s] == expected_splits[s]
                                for s in ("DEV", "VALIDATION", "OOS_LOCK")),
            "oos_locked": manifest["splits"]["oos_opened"] is False,
            "strategy_id_match": manifest["strategy_id"] == IDENTITY[exp_id]["strategy_id"],
        }
        if not all(v for k, v in checks.items() if k.endswith(("_match", "_locked"))):
            problems.append(exp_id)
        report["experiments"][exp_id] = checks
    report["all_valid"] = not problems
    report["problems"] = problems
    return report


# ------------------------------------------------------------- running


def make_daily_strategy(exp_id: str, params: dict[str, Any]) -> Any:
    if exp_id == "EXP-ARP-011":
        return Exp011VolExpansionBreakout(Exp011Config(**params))
    return Exp006LiquidityVoidReversal(Exp006Config(**params))


def run_daily_split(exp_id: str, split: str, params: dict[str, Any], *, cost_bps_rt: float,
                    entry_delay_days: int = 0) -> dict[str, list[Any]]:
    out: dict[str, list[Any]] = {}
    for key, symbol in C.SYMBOLS.items():
        daily = load_daily(symbol, exp_id, split)
        if not daily:
            out[key] = []
            continue
        strategy = make_daily_strategy(exp_id, params)
        out[key] = simulate_daily(strategy, daily, cost_bps_rt=cost_bps_rt,
                                  entry_delay_days=entry_delay_days).trades
    return out


def run_xsec_split(exp_id: str, split: str, params: dict[str, Any], *, cost_bps_rt: float) -> dict[str, list[Any]]:
    series = {s: load_daily(s, exp_id, split) for s in C.SYMBOLS.values()}
    cfg = XsecConfig(lookback_days=int(params["lookback_days"]),
                     max_hold_days=int(params["max_hold_days"]),
                     long_only=bool(params.get("long_only", True)))
    result = simulate_xsec(series, config=cfg, cost_bps_rt=cost_bps_rt)
    return {"XSEC": result.trades}


def run_split(exp_id: str, split: str, params: dict[str, Any], *, cost_bps_rt: float,
              entry_delay_days: int = 0) -> dict[str, list[Any]]:
    if IDENTITY[exp_id]["kind"] == "xsec":
        return run_xsec_split(exp_id, split, params, cost_bps_rt=cost_bps_rt)
    return run_daily_split(exp_id, split, params, cost_bps_rt=cost_bps_rt,
                           entry_delay_days=entry_delay_days)


def summarize(exp_id: str, split: str, params: dict[str, Any], cost_bps_rt: float) -> dict[str, Any]:
    trades = run_split(exp_id, split, params, cost_bps_rt=cost_bps_rt)
    return C.summarize_run(trades, cost_bps_rt=cost_bps_rt)


def sample_stats(exp_id: str, split: str, params: dict[str, Any], cost_bps_rt: float) -> dict[str, Any]:
    """§10 sample-sufficiency descriptors (not thresholds)."""
    trades = run_split(exp_id, split, params, cost_bps_rt=cost_bps_rt)
    all_trades = [t for ts in trades.values() for t in ts]
    days: set[int] = set()
    for symbol in C.SYMBOLS.values():
        for b in load_daily(symbol, exp_id, split):
            days.add(b.timestamp)
    n_days = len(days)
    n = len(all_trades)
    durations = [t.duration_min for t in all_trades]
    active_days = len({t.entry_ts for t in all_trades})
    return {
        "trades": n,
        "evaluable_days": n_days,
        "trades_per_day": round(n / n_days, 4) if n_days else None,
        "active_trading_days": active_days,
        "zero_trade_days": n_days - active_days,
        "median_holding_minutes": round(statistics.median(durations), 1) if durations else None,
        "median_holding_days": round(statistics.median(durations) / 1440.0, 2) if durations else None,
    }


# ------------------------------------------------------------- verdicts


def dev_verdict(exp_id: str, dev: dict[str, Any]) -> dict[str, Any]:
    comb = dev["combined"]
    n = comb["trades"]
    gross = comb["expectancy_gross_bps"]
    top1 = comb["concentration"]["top1_share"]
    min_trades = IDENTITY[exp_id]["min_trades"]
    checks = {
        "sample_sufficient": n >= min_trades,
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
    return {"result": result, "checks": checks,
            "thresholds": {"min_trades": min_trades, "top1_share_max": 0.5}}


def duplicate_check(exp_id: str, params: dict[str, Any]) -> dict[str, Any]:
    """EXP-ARP-009 only: must genuinely rank across assets, not ride one name."""
    if IDENTITY[exp_id]["kind"] != "xsec":
        return {"applicable": False}
    trades = run_xsec_split(exp_id, "DEV", params, cost_bps_rt=0.0)["XSEC"]
    held_symbols = sorted({t.rule for t in trades})
    degenerate = len(held_symbols) <= 1
    return {"applicable": True, "episodes": len(trades), "held_symbols": held_symbols,
            "degenerate_single_name": degenerate,
            "result": "REJECT_DUPLICATE" if degenerate else "PASS"}


def cost_gate(exp_id: str, params: dict[str, Any], base_bps: float) -> dict[str, Any]:
    stress: dict[str, Any] = {}
    for mult in COST_MULTIPLES:
        cost = base_bps * mult
        comb = summarize(exp_id, "DEV", params, cost)["combined"]
        stress[f"{mult}x"] = {
            "cost_bps_rt": round(cost, 4), "trades": comb["trades"],
            "expectancy_gross_bps": comb["expectancy_gross_bps"],
            "expectancy_net_bps": comb["expectancy_net_bps"],
            "profit_factor": comb["profit_factor"],
        }
    base_net = stress["1.0x"]["expectancy_net_bps"]
    gross = stress["1.0x"]["expectancy_gross_bps"]
    break_even = round(gross, 4) if gross is not None else None
    if base_net is not None and base_net > 0 and (gross or 0) > GROSS_KILL_BPS:
        result = "PASS"
    else:
        result = "REJECT_COSTS"
    return {"result": result, "base_cost_bps_rt": round(base_bps, 4),
            "gross_kill_bps": GROSS_KILL_BPS, "break_even_cost_bps": break_even, "stress": stress}


def validation_verdict(dev: dict[str, Any], val: dict[str, Any]) -> dict[str, Any]:
    d, v = dev["combined"], val["combined"]
    dg, vg = d["expectancy_gross_bps"], v["expectancy_gross_bps"]
    checks = {
        "val_gross_positive": bool(vg is not None and vg > 0),
        "no_material_collapse": bool(dg is not None and vg is not None and dg > 0 and vg >= 0.5 * dg),
        "val_net_positive": bool(v["expectancy_net_bps"] is not None and v["expectancy_net_bps"] > 0),
    }
    return {"result": "PASS" if all(checks.values()) else "REJECT_VALIDATION", "checks": checks,
            "dev_gross_bps": dg, "val_gross_bps": vg, "dev_trades": d["trades"], "val_trades": v["trades"]}


def robustness(exp_id: str, params: dict[str, Any], base_bps: float) -> dict[str, Any]:
    out: dict[str, Any] = {}
    gross_bps: list[float] = []
    for name, delta in ROBUSTNESS[exp_id].items():
        merged = dict(params)
        merged.update(delta)
        comb = summarize(exp_id, "DEV", merged, base_bps)["combined"]
        g = comb["expectancy_gross_bps"]
        out[name] = {"params": merged, "trades": comb["trades"], "expectancy_gross_bps": g,
                     "expectancy_net_bps": comb["expectancy_net_bps"]}
        if g is not None:
            gross_bps.append(g)
    base = summarize(exp_id, "DEV", params, base_bps)["combined"]["expectancy_gross_bps"]
    positives = [g for g in gross_bps if g > 0]
    one_point = bool(base is not None and base > 0 and len(positives) <= 1)
    return {"result": "REJECT_FRAGILE" if one_point else "PASS", "one_point_optimum": one_point,
            "base_gross_bps": base, "variants": out}


# ------------------------------------------------------------- pipeline


def run_experiment(exp_id: str) -> dict[str, Any]:
    out_dir = OUT / exp_id
    identity = IDENTITY[exp_id]
    params = BASE_PARAMS[exp_id]
    base_cost = C.cost_model_v3_rt_bps()

    sample = {"DEV": sample_stats(exp_id, "DEV", params, base_cost)}
    write_json(out_dir / "SAMPLE.json", sample)

    dev = summarize(exp_id, "DEV", params, base_cost)
    dev["verdict"] = dev_verdict(exp_id, dev)
    dev["duplicate_check"] = duplicate_check(exp_id, params)
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
        return {"decision": decision, "dev": dev}

    cost_res = cost_gate(exp_id, params, base_cost)
    write_json(out_dir / "COST_STRESS.json", cost_res)
    decision["stages"]["COST"] = cost_res["result"]
    decision["stages"]["VALIDATION"] = "NOT_REACHED"
    decision["stages"]["ROBUSTNESS"] = "NOT_REACHED"
    if cost_res["result"] != "PASS":
        decision["final"] = cost_res["result"]
        write_json(out_dir / "DECISION.json", decision)
        return {"decision": decision, "dev": dev, "cost": cost_res}

    val = summarize(exp_id, "VALIDATION", params, base_cost)
    val["verdict"] = validation_verdict(dev, val)
    write_json(out_dir / "VALIDATION.json", val)
    decision["stages"]["VALIDATION"] = val["verdict"]["result"]
    if val["verdict"]["result"] != "PASS":
        decision["final"] = "REJECT_VALIDATION"
        write_json(out_dir / "DECISION.json", decision)
        return {"decision": decision, "dev": dev, "cost": cost_res, "val": val}

    rob = robustness(exp_id, params, base_cost)
    write_json(out_dir / "ROBUSTNESS.json", rob)
    decision["stages"]["ROBUSTNESS"] = rob["result"]
    if rob["result"] != "PASS":
        decision["final"] = "REJECT_FRAGILE"
        write_json(out_dir / "DECISION.json", decision)
        return {"decision": decision, "dev": dev, "cost": cost_res, "val": val, "rob": rob}

    decision["stages"]["OOS"] = "OOS_GATE_ELIGIBLE"
    oos = summarize(exp_id, "OOS_LOCK", params, base_cost)
    write_json(out_dir / "OOS.json", oos)
    decision["oos_opened"] = True
    oos_pass = bool(
        oos["combined"]["expectancy_gross_bps"] is not None
        and oos["combined"]["expectancy_gross_bps"] > 0
        and oos["combined"]["expectancy_net_bps"] is not None
        and oos["combined"]["expectancy_net_bps"] > 0
    )
    decision["stages"]["OOS"] = "OOS_PASS" if oos_pass else "OOS_FAIL"
    decision["final"] = "PROMOTION_CANDIDATE" if oos_pass else "REJECT_VALIDATION"
    write_json(out_dir / "DECISION.json", decision)
    return {"decision": decision, "dev": dev, "cost": cost_res, "val": val, "rob": rob, "oos": oos}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = validate_manifests()
    write_json(OUT / "MANIFEST_VALIDATION.json", manifest)
    if not manifest["all_valid"]:
        print("FROZEN MANIFEST MISMATCH — STOP")
        print(json.dumps(manifest, indent=2))
        return 2
    env = {"code_hash": code_hash(), "config_hash": config_hash(),
           "cost_bps_rt": C.cost_model_v3_rt_bps(),
           "baseline_dataset_fingerprint": C.corpus_digest(),
           "extended_corpus_digest": E.ext_corpus_digest(),
           "code_files": list(CODE_FILES), "branch_head": _head()}
    write_json(OUT / "ENVIRONMENT.json", env)
    print(f"code_hash = {env['code_hash']}")
    print(f"extended_corpus_digest = {env['extended_corpus_digest']}")

    summary: dict[str, Any] = {}
    for exp_id in IDENTITY:
        res = run_experiment(exp_id)
        dec = res["decision"]
        comb = res["dev"]["combined"]
        summary[exp_id] = {
            "strategy_id": IDENTITY[exp_id]["strategy_id"], "dataset": IDENTITY[exp_id]["dataset"],
            "stages": dec["stages"], "final": dec["final"], "oos_opened": dec["oos_opened"],
            "dev_trades": comb["trades"], "dev_gross_bps": comb["expectancy_gross_bps"],
            "dev_net_bps": comb["expectancy_net_bps"],
        }
        print(f"{exp_id}: DEV trades={comb['trades']} gross={comb['expectancy_gross_bps']} "
              f"net={comb['expectancy_net_bps']} -> {dec['final']}")
    write_json(OUT / "RUN_REPORT.json", {"environment": env, "experiments": summary})
    return 0


def _head() -> str:
    import subprocess

    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True,
                              text=True, check=True).stdout.strip()
    except Exception:
        return "UNKNOWN"


if __name__ == "__main__":
    raise SystemExit(main())
