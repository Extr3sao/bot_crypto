"""ARP-005 ALPHA EXPANSION §18-§24 — execution driver for the three frozen experiments.

Runs only the pre-registered experiments:

* ``EXP-ARP-013`` ``H-XSEC-MOM-LONG-001``  cross-sectional momentum;
* ``EXP-ARP-014`` ``H-XSEC-REV-001``       cross-sectional reversal;
* ``EXP-ARP-015`` ``H-XSEC-LOWVOL-001``    cross-sectional low-volatility.

Stage order: manifest validation -> DEV -> DEV kill gate -> COST stress ->
VALIDATION -> ROBUSTNESS -> OOS gate (opens only if every prior gate passes).

Run:

    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/alpha_expansion_v1.py

Writes JSON under ``reports/alpha-expansion-v1/``. Reads the isolated expanded
corpus; touches no runtime authority, no Risk module and no lifecycle.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.market_data.types import OHLCV  # noqa: E402
from trading_bot.research.alpha_expansion import data as D  # noqa: E402
from trading_bot.research.alpha_expansion import htf as H  # noqa: E402
from trading_bot.research.alpha_expansion import strategies as S  # noqa: E402
from trading_bot.research.alpha_recovery import campaign as C  # noqa: E402
from trading_bot.research.alpha_recovery.metrics import summarize  # noqa: E402

OUT = REPO / "reports/alpha-expansion-v1"
EXP_DIR = REPO / "docs/research/alpha_expansion_v1/experiments"
ADMISSION_CFG = REPO / "config/strategy_admission.json"

COST_MULTIPLES = [0.5, 1.0, 1.25, 1.5, 2.0]

CODE_FILES: tuple[str, ...] = (
    "src/trading_bot/research/alpha_expansion/__init__.py",
    "src/trading_bot/research/alpha_expansion/htf.py",
    "src/trading_bot/research/alpha_expansion/data.py",
    "src/trading_bot/research/alpha_expansion/xsec.py",
    "src/trading_bot/research/alpha_expansion/strategies.py",
    "src/trading_bot/research/alpha_recovery/metrics.py",
    "src/trading_bot/research/alpha_recovery/series.py",
    "scripts/alpha_expansion_v1.py",
)

IDENTITY: dict[str, dict[str, Any]] = {
    "EXP-ARP-013": {"strategy_id": "H-XSEC-MOM-LONG-001", "min_trades": 20},
    "EXP-ARP-014": {"strategy_id": "H-XSEC-REV-001", "min_trades": 20},
    "EXP-ARP-015": {"strategy_id": "H-XSEC-LOWVOL-001", "min_trades": 15},
}

#: Robustness perturbations declared BEFORE any result is read (§23).
ROBUSTNESS: dict[str, dict[str, Any]] = {
    "EXP-ARP-013": {
        "window_60": {"ranking_window": 60}, "window_120": {"ranking_window": 120},
        "rebalance_3": {"rebalance_days": 3}, "rebalance_10": {"rebalance_days": 10},
        "hold_20": {"max_hold_days": 20}, "hold_45": {"max_hold_days": 45},
    },
    "EXP-ARP-014": {
        "window_5": {"ranking_window": 5}, "window_10": {"ranking_window": 10},
        "rebalance_2": {"rebalance_days": 2}, "rebalance_5": {"rebalance_days": 5},
        "hold_5": {"max_hold_days": 5}, "hold_10": {"max_hold_days": 10},
    },
    "EXP-ARP-015": {
        "window_40": {"ranking_window": 40}, "window_90": {"ranking_window": 90},
        "rebalance_5": {"rebalance_days": 5}, "rebalance_20": {"rebalance_days": 20},
        "hold_20": {"max_hold_days": 20}, "hold_45": {"max_hold_days": 45},
    },
}

#: DEV sub-periods for regime variation (§23).
REGIMES: dict[str, tuple[int, int]] = {
    "bull_2019_2020": (1546300800000, 1609459200000),
    "mixed_2021": (1609459200000, 1640995200000),
    "bear_2022_2023": (1640995200000, 1704067200000),
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


def _head() -> str:
    import subprocess

    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True,
                              text=True, check=True).stdout.strip()
    except Exception:
        return "UNKNOWN"


# ------------------------------------------------------------------ data


@lru_cache(maxsize=8)
def daily_for(split: str) -> dict[str, list[OHLCV]]:
    out: dict[str, list[OHLCV]] = {}
    for key, symbol in D.SYMBOLS.items():
        bars = H.build_htf_bars(D.load_lower_bars(symbol, split), 24)
        out[key] = [b.as_ohlcv() for b in bars]
    return out


def slice_ts(daily: dict[str, list[OHLCV]], lo: int, hi: int) -> dict[str, list[OHLCV]]:
    return {k: [b for b in v if lo <= b.timestamp < hi] for k, v in daily.items()}


def cfg_for(exp_id: str, overrides: dict[str, Any] | None = None) -> S.RotationConfig:
    base = S.rotation_configs()[exp_id]
    if not overrides:
        return base
    return S.RotationConfig(
        ranking_feature=overrides.get("ranking_feature", base.ranking_feature),
        ranking_window=int(overrides.get("ranking_window", base.ranking_window)),
        ascending=bool(overrides.get("ascending", base.ascending)),
        rebalance_days=int(overrides.get("rebalance_days", base.rebalance_days)),
        max_hold_days=int(overrides.get("max_hold_days", base.max_hold_days)),
        min_members=int(overrides.get("min_members", base.min_members)),
        entry_delay_days=int(overrides.get("entry_delay_days", base.entry_delay_days)),
    )


def run(exp_id: str, split: str, cfg: S.RotationConfig, *, cost_bps_rt: float,
        subset: tuple[str, ...] | None = None) -> list[Any]:
    daily = daily_for(split)
    if subset is not None:
        daily = {k: v for k, v in daily.items() if k in subset}
    return S.simulate_xsec_rotation(daily, config=cfg, cost_bps_rt=cost_bps_rt).trades


def metrics(exp_id: str, split: str, cfg: S.RotationConfig, cost_bps_rt: float,
            subset: tuple[str, ...] | None = None) -> dict[str, Any]:
    trades = run(exp_id, split, cfg, cost_bps_rt=cost_bps_rt, subset=subset)
    # strategies.Trade is duck-type compatible with metrics.summarize
    return summarize(cast("Sequence[Any]", trades), cost_bps_rt=cost_bps_rt)


# ------------------------------------------------------------------ manifests


def validate_manifests() -> dict[str, Any]:
    report: dict[str, Any] = {"config_hash": config_hash(), "cost_bps_rt": C.cost_model_v3_rt_bps(),
                              "dataset_fingerprint": D.expansion_corpus_digest(), "experiments": {}}
    problems: list[str] = []
    for exp_id in IDENTITY:
        manifest_path = EXP_DIR / exp_id / "MANIFEST.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected_splits = {s: list(D.SPLIT_RANGES[s]) for s in ("DEV", "VALIDATION", "OOS_LOCK")}
        checks = {
            "manifest_sha256": _lf_digest(manifest_path),
            "spec_sha256": _lf_digest(EXP_DIR / exp_id / "SPEC.md"),
            "config_hash_match": manifest["config_hash"] == report["config_hash"],
            "dataset_fingerprint_match": manifest["data"]["dataset_fingerprint"] == report["dataset_fingerprint"],
            "cost_model_match": manifest["cost_model"]["version"] == "COST_MODEL_V3",
            "splits_match": all(manifest["splits"][s] == expected_splits[s] for s in ("DEV", "VALIDATION", "OOS_LOCK")),
            "oos_locked": manifest["splits"]["oos_opened"] is False,
            "strategy_id_match": manifest["strategy_id"] == IDENTITY[exp_id]["strategy_id"],
            "baseline_untouched": manifest["data"]["baseline_fingerprint_untouched"] == C.corpus_digest(),
        }
        if not all(v for k, v in checks.items() if k.endswith(("_match", "_locked", "_untouched"))):
            problems.append(exp_id)
        report["experiments"][exp_id] = checks
    report["all_valid"] = not problems
    report["problems"] = problems
    return report


# ------------------------------------------------------------------ verdicts


def dev_verdict(exp_id: str, dev: dict[str, Any]) -> dict[str, Any]:
    n = dev["trades"]
    gross = dev["expectancy_gross_bps"]
    top1 = dev["concentration"]["top1_share"]
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


def duplicate_check(exp_id: str, cfg: S.RotationConfig) -> dict[str, Any]:
    trades = run(exp_id, "DEV", cfg, cost_bps_rt=0.0)
    held = sorted({t.symbol for t in trades})
    degenerate = len(held) <= 1
    return {"episodes": len(trades), "held_symbols": held, "degenerate_single_name": degenerate,
            "result": "REJECT_DUPLICATE" if degenerate else "PASS"}


def cost_gate(exp_id: str, cfg: S.RotationConfig, base_bps: float) -> dict[str, Any]:
    stress: dict[str, Any] = {}
    for mult in COST_MULTIPLES:
        m = metrics(exp_id, "DEV", cfg, base_bps * mult)
        stress[f"{mult}x"] = {
            "cost_bps_rt": round(base_bps * mult, 4), "trades": m["trades"],
            "expectancy_gross_bps": m["expectancy_gross_bps"],
            "expectancy_net_bps": m["expectancy_net_bps"],
            "profit_factor": m["profit_factor"],
        }
    base_net = stress["1.0x"]["expectancy_net_bps"]
    gross = stress["1.0x"]["expectancy_gross_bps"]
    result = "PASS" if (base_net is not None and base_net > 0) else "REJECT_COSTS"
    return {"result": result, "base_cost_bps_rt": round(base_bps, 4),
            "break_even_cost_bps": round(gross, 4) if gross is not None else None, "stress": stress}


def validation_verdict(dev: dict[str, Any], val: dict[str, Any]) -> dict[str, Any]:
    dg, vg = dev["expectancy_gross_bps"], val["expectancy_gross_bps"]
    checks = {
        "val_gross_positive": bool(vg is not None and vg > 0),
        "no_material_collapse": bool(dg is not None and vg is not None and dg > 0 and vg >= 0.5 * dg),
        "val_net_positive": bool(val["expectancy_net_bps"] is not None and val["expectancy_net_bps"] > 0),
    }
    return {"result": "PASS" if all(checks.values()) else "REJECT_VALIDATION", "checks": checks,
            "dev_gross_bps": dg, "val_gross_bps": vg, "dev_trades": dev["trades"], "val_trades": val["trades"]}


def robustness(exp_id: str, cfg: S.RotationConfig, base_bps: float) -> dict[str, Any]:
    base = metrics(exp_id, "DEV", cfg, base_bps)
    variants: dict[str, Any] = {}
    gross_bps: list[float] = []

    def record(name: str, m: dict[str, Any]) -> None:
        g = m["expectancy_gross_bps"]
        variants[name] = {"trades": m["trades"], "expectancy_gross_bps": g,
                          "expectancy_net_bps": m["expectancy_net_bps"]}
        if g is not None:
            gross_bps.append(g)

    for name, delta in ROBUSTNESS[exp_id].items():
        record(name, metrics(exp_id, "DEV", cfg_for(exp_id, delta), base_bps))
    # execution delay (both entries and exits)
    record("entry_delay_1d", metrics(exp_id, "DEV", cfg_for(exp_id, {"entry_delay_days": 1}), base_bps))
    # higher cost
    record("cost_2x", metrics(exp_id, "DEV", cfg, base_bps * 2.0))
    # asset variation: drop each asset once
    for dropped in ("BTC", "ETH", "SOL"):
        subset = tuple(k for k in D.SYMBOLS if k != dropped)
        record(f"drop_{dropped}", metrics(exp_id, "DEV", cfg, base_bps, subset=subset))
    # regime variation: DEV sub-periods
    daily_full = daily_for("DEV")
    for name, (lo, hi) in REGIMES.items():
        sliced = slice_ts(daily_full, lo, hi)
        trades = S.simulate_xsec_rotation(sliced, config=cfg, cost_bps_rt=base_bps).trades
        record(f"regime_{name}", summarize(cast("Sequence[Any]", trades), cost_bps_rt=base_bps))

    base_g = base["expectancy_gross_bps"]
    positives = [g for g in gross_bps if g > 0]
    one_point = bool(base_g is not None and base_g > 0 and len(positives) <= 1)
    return {"result": "REJECT_FRAGILE" if one_point else "PASS", "one_point_optimum": one_point,
            "base_gross_bps": base_g, "variants": variants,
            "positive_variants": len(positives), "variant_count": len(gross_bps)}


# ------------------------------------------------------------------ pipeline


def run_experiment(exp_id: str) -> dict[str, Any]:
    out_dir = OUT / exp_id
    base_cost = C.cost_model_v3_rt_bps()
    cfg = cfg_for(exp_id)

    dev = metrics(exp_id, "DEV", cfg, base_cost)
    dev["n_dev_days"] = len({b.timestamp for b in daily_for("DEV")["BTC"]})
    dev["verdict"] = dev_verdict(exp_id, dev)
    dev["duplicate_check"] = duplicate_check(exp_id, cfg)
    write_json(out_dir / "DEV.json", dev)

    decision: dict[str, Any] = {"experiment_id": exp_id, "identity": IDENTITY[exp_id],
                               "stages": {}, "oos_opened": False, "final": None}
    decision["stages"]["DEV"] = dev["verdict"]["result"]
    if dev["verdict"]["result"] != "PASS":
        decision["stages"].update({"COST": "NOT_REACHED", "VALIDATION": "NOT_REACHED",
                                   "ROBUSTNESS": "NOT_REACHED", "OOS": "NOT_OPENED"})
        decision["final"] = dev["verdict"]["result"]
        write_json(out_dir / "DECISION.json", decision)
        return {"decision": decision, "dev": dev}

    cost_res = cost_gate(exp_id, cfg, base_cost)
    write_json(out_dir / "COST_STRESS.json", cost_res)
    decision["stages"]["COST"] = cost_res["result"]
    decision["stages"]["VALIDATION"] = "NOT_REACHED"
    decision["stages"]["ROBUSTNESS"] = "NOT_REACHED"
    decision["stages"]["OOS"] = "NOT_OPENED"
    if cost_res["result"] != "PASS":
        decision["final"] = cost_res["result"]
        write_json(out_dir / "DECISION.json", decision)
        return {"decision": decision, "dev": dev, "cost": cost_res}

    val = metrics(exp_id, "VALIDATION", cfg, base_cost)
    val["verdict"] = validation_verdict(dev, val)
    write_json(out_dir / "VALIDATION.json", val)
    decision["stages"]["VALIDATION"] = val["verdict"]["result"]
    if val["verdict"]["result"] != "PASS":
        decision["final"] = "REJECT_VALIDATION"
        write_json(out_dir / "DECISION.json", decision)
        return {"decision": decision, "dev": dev, "cost": cost_res, "val": val}

    rob = robustness(exp_id, cfg, base_cost)
    write_json(out_dir / "ROBUSTNESS.json", rob)
    decision["stages"]["ROBUSTNESS"] = rob["result"]
    if rob["result"] != "PASS":
        decision["final"] = "REJECT_FRAGILE"
        write_json(out_dir / "DECISION.json", decision)
        return {"decision": decision, "dev": dev, "cost": cost_res, "val": val, "rob": rob}

    # OOS gate: record the sealed range BEFORE reading it
    oos_range = list(D.SPLIT_RANGES["OOS_LOCK"])
    write_json(out_dir / "OOS_OPEN.json", {"oos_range_ms": oos_range, "opened": True,
                                           "opened_before_computation": True})
    decision["stages"]["OOS"] = "OOS_GATE_ELIGIBLE"
    oos = metrics(exp_id, "OOS_LOCK", cfg, base_cost)
    write_json(out_dir / "OOS.json", oos)
    decision["oos_opened"] = True
    oos_pass = bool(
        oos["expectancy_gross_bps"] is not None and oos["expectancy_gross_bps"] > 0
        and oos["expectancy_net_bps"] is not None and oos["expectancy_net_bps"] > 0
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
    env = {
        "code_hash": code_hash(), "config_hash": config_hash(),
        "cost_bps_rt": C.cost_model_v3_rt_bps(),
        "expansion_corpus_digest": D.expansion_corpus_digest(),
        "baseline_dataset_fingerprint": C.corpus_digest(),
        "splits": {k: list(v) for k, v in D.SPLIT_RANGES.items()},
        "code_files": list(CODE_FILES), "branch_head": _head(),
    }
    write_json(OUT / "ENVIRONMENT.json", env)
    print(f"code_hash = {env['code_hash']}")
    print(f"expansion_corpus_digest = {env['expansion_corpus_digest']}")

    results: dict[str, Any] = {}
    for exp_id in IDENTITY:
        res = run_experiment(exp_id)
        dec = res["decision"]
        dev = res["dev"]
        results[exp_id] = {
            "strategy_id": IDENTITY[exp_id]["strategy_id"], "stages": dec["stages"],
            "final": dec["final"], "oos_opened": dec["oos_opened"],
            "dev_trades": dev["trades"], "dev_gross_bps": dev["expectancy_gross_bps"],
            "dev_net_bps": dev["expectancy_net_bps"],
        }
        write_json(OUT / exp_id / "RESULT.json", results[exp_id])
        print(f"{exp_id}: DEV trades={dev['trades']} gross={dev['expectancy_gross_bps']} "
              f"net={dev['expectancy_net_bps']} -> {dec['final']}")
    write_json(OUT / "RUN_REPORT.json", {"environment": env, "experiments": results})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
