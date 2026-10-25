"""ARP-006 DIVERSIFIED ALPHA SEARCH §10-§25 — execution driver.

Runs only the pre-registered / newly pre-registered experiments over the broader PIT
daily universe:

* ``EXP-ARP-006`` ``STRAT-CAND-016-VARIANT-B``  daily liquidity-reversal (3 assets);
* ``EXP-ARP-008`` ``H-DAILY-TSMOM-001``         daily time-series momentum (3 assets);
* ``EXP-ARP-016`` ``H-XSEC-MOM-LONG-002``       broad-universe xsec momentum;
* ``EXP-ARP-017`` ``H-XSEC-REV-002``            broad-universe xsec reversal;
* ``EXP-ARP-018`` ``H-XSEC-LOWVOL-002``         broad-universe xsec low-volatility.

Stage order (frozen): universe -> DEV -> DEV kill gate -> COST stress -> VALIDATION
-> ROBUSTNESS -> OOS gate (opens only if every gate passes). Kill early on failure.

Run:

    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/alpha_diversified_v1.py

Writes ``reports/alpha-diversified-v1/RESULTS.json``. Reads the isolated diversified
corpus; touches no runtime authority, no Risk module, no lifecycle, no promotion.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.research.alpha_recovery import campaign as C  # noqa: E402
from trading_bot.research.alpha_recovery.metrics import summarize  # noqa: E402
from trading_bot.research.diversified import analytics as A  # noqa: E402
from trading_bot.research.diversified import daily as DL  # noqa: E402
from trading_bot.research.diversified import data as D  # noqa: E402
from trading_bot.research.diversified import universe as U  # noqa: E402
from trading_bot.research.diversified import xsec as X  # noqa: E402

OUT = REPO / "reports/alpha-diversified-v1"
ADMISSION_CFG = REPO / "config/strategy_admission.json"
COST_MULTIPLES = [0.5, 1.0, 1.25, 1.5, 2.0]
DAILY_ASSETS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")

CODE_FILES: tuple[str, ...] = (
    "src/trading_bot/research/diversified/__init__.py",
    "src/trading_bot/research/diversified/data.py",
    "src/trading_bot/research/diversified/universe.py",
    "src/trading_bot/research/diversified/daily.py",
    "src/trading_bot/research/diversified/xsec.py",
    "src/trading_bot/research/diversified/analytics.py",
    "src/trading_bot/research/alpha_expansion/xsec.py",
    "src/trading_bot/research/alpha_expansion/strategies.py",
    "src/trading_bot/research/alpha_recovery/metrics.py",
    "scripts/alpha_diversified_v1.py",
)

IDENTITY: dict[str, dict[str, Any]] = {
    "EXP-ARP-006": {"strategy_id": "STRAT-CAND-016-VARIANT-B", "arm": "PROJECT_DERIVED_VARIANT", "min_trades": 10},
    "EXP-ARP-008": {"strategy_id": "H-DAILY-TSMOM-001", "arm": "PROJECT_DERIVED_VARIANT", "min_trades": 20},
    "EXP-ARP-016": {"strategy_id": "H-XSEC-MOM-LONG-002", "arm": "NEW_HYPOTHESIS", "min_trades": 20},
    "EXP-ARP-017": {"strategy_id": "H-XSEC-REV-002", "arm": "NEW_HYPOTHESIS", "min_trades": 20},
    "EXP-ARP-018": {"strategy_id": "H-XSEC-LOWVOL-002", "arm": "NEW_HYPOTHESIS", "min_trades": 15},
}


def code_hash() -> str:
    h = hashlib.sha256()
    for rel in CODE_FILES:
        path = REPO / rel
        h.update(rel.encode())
        h.update(path.read_bytes() if path.exists() else b"")
    return h.hexdigest()


def config_hash() -> str:
    return hashlib.sha256(ADMISSION_CFG.read_bytes()).hexdigest()


# --------------------------------------------------------------------- run helpers


def run_daily(exp_id: str, corpus: dict[str, Any], *, cost: float) -> list[Any]:
    if exp_id == "EXP-ARP-006":
        by_sym = DL.simulate_exp006(corpus, cost_bps_rt=cost)
    else:
        by_sym = DL.simulate_exp008(corpus, cost_bps_rt=cost)
    return DL.tag_trades(by_sym)


def daily_corpus(split: str) -> dict[str, Any]:
    return {s: D.load_symbol(s, split) for s in DAILY_ASSETS}


def xsec_corpus(split: str) -> dict[str, Any]:
    return D.load_corpus(split=split)


def run_xsec(exp_id: str, corpus: dict[str, Any], *, cost: float, subset: Sequence[str] | None = None,
             override: X.XsecUniverseConfig | None = None) -> tuple[list[Any], dict[str, int]]:
    cfg = override or X.xsec_universe_configs()[exp_id]
    return X.simulate_universe_xsec(
        corpus, D.listing_times(), D.corpus_digest(), config=cfg, cost_bps_rt=cost, subset=subset
    )


def decision_from(dev: dict[str, Any], *, min_trades: int, cost: float) -> str:
    if dev["trades"] < min_trades:
        return "REJECT_INSUFFICIENT_SAMPLE"
    gross = dev["expectancy_gross_bps"]
    if gross is None or gross <= 0:
        return "REJECT_NO_EDGE"
    if gross <= cost:
        return "REJECT_COSTS"
    if (dev["concentration"].get("top1_share") or 0.0) > 0.5:
        return "REJECT_FRAGILE"
    return "DEV_PASS"


def cost_stress(gross_bps: float | None, base_cost: float) -> dict[str, Any]:
    if gross_bps is None:
        return {}
    return {
        f"{m}x": {
            "cost_bps_rt": round(base_cost * m, 4),
            "expectancy_net_bps": round(gross_bps - base_cost * m, 4),
            "positive": gross_bps - base_cost * m > 0,
        }
        for m in COST_MULTIPLES
    }


def params_key(exp_id: str) -> dict[str, Any]:
    if exp_id == "EXP-ARP-006":
        c6 = DL.Exp006Config()
        return {"void_min_days": c6.void_min_days, "retest_lookback_days": c6.retest_lookback_days,
                "stop_atr": c6.stop_atr, "target_atr": c6.target_atr, "max_hold_days": c6.max_hold_days}
    if exp_id == "EXP-ARP-008":
        c8 = DL.Exp008Config()
        return {"lookback_days": c8.lookback_days, "max_hold_days": c8.max_hold_days}
    cx = X.xsec_universe_configs()[exp_id]
    return {"ranking_window": cx.ranking_window, "rebalance_days": cx.rebalance_days,
            "max_hold_days": cx.max_hold_days, "ascending": cx.ascending}


# --------------------------------------------------------------------- robustness


def robustness_daily(exp_id: str, *, cost: float, base: dict[str, Any]) -> dict[str, Any]:
    val = daily_corpus("VALIDATION")
    out: dict[str, Any] = {}
    if exp_id == "EXP-ARP-006":
        c6 = DL.Exp006Config()
        neigh6 = {
            "lookback_8": DL.Exp006Config(retest_lookback_days=8),
            "lookback_12": DL.Exp006Config(retest_lookback_days=12),
            "hold_4": DL.Exp006Config(max_hold_days=4),
            "hold_6": DL.Exp006Config(max_hold_days=6),
        }
        for name6, cfg6 in neigh6.items():
            tr = [t for v in DL.simulate_exp006(val, cost_bps_rt=cost, config=cfg6).values() for t in v]
            out[f"neighborhood_{name6}"] = summarize(tr, cost_bps_rt=cost)
        tr = [t for v in DL.simulate_exp006(val, cost_bps_rt=cost, config=c6, entry_delay_days=1).values() for t in v]
        out["execution_delay_1d"] = summarize(tr, cost_bps_rt=cost)
    else:
        c8 = DL.Exp008Config()
        neigh8 = {
            "lookback_24": DL.Exp008Config(lookback_days=24),
            "lookback_40": DL.Exp008Config(lookback_days=40),
            "hold_12": DL.Exp008Config(max_hold_days=12),
            "hold_28": DL.Exp008Config(max_hold_days=28),
        }
        for name8, cfg8 in neigh8.items():
            tr = [t for v in DL.simulate_exp008(val, cost_bps_rt=cost, config=cfg8).values() for t in v]
            out[f"neighborhood_{name8}"] = summarize(tr, cost_bps_rt=cost)
        tr = [t for v in DL.simulate_exp008(val, cost_bps_rt=cost, config=c8, entry_delay_days=1).values() for t in v]
        out["execution_delay_1d"] = summarize(tr, cost_bps_rt=cost)
    for m in (1.25, 1.5, 2.0):
        tr = run_daily(exp_id, val, cost=cost * m)
        out[f"cost_{m}x"] = summarize(tr, cost_bps_rt=cost * m)
    for sym in DAILY_ASSETS:
        tr = run_daily(exp_id, {sym: val[sym]}, cost=cost)
        out[f"asset_{sym}"] = summarize(tr, cost_bps_rt=cost)
    # time blocks + regimes from the DEV+VALIDATION run
    full = {s: D.load_corpus_range([s], *D.DEV_VAL_RANGE)[s] for s in DAILY_ASSETS}
    tr_full = run_daily(exp_id, full, cost=cost)
    out["pnl_by_year"] = A.pnl_by_year(tr_full)
    out["pnl_by_asset"] = A.pnl_by_asset(tr_full)
    out["concentration"] = A.concentration_by_asset_and_period(tr_full)
    bench = DL.to_ohlcv(D.load_corpus_range(["BTCUSDT"], *D.DEV_VAL_RANGE)["BTCUSDT"])
    regimes = A.regime_by_day(bench)
    out["pnl_by_regime"] = A.regime_pnl(tr_full, regimes)
    return out


def robustness_xsec(exp_id: str, *, cost: float, base: dict[str, Any], val_corpus: dict[str, Any],
                    full_corpus: dict[str, Any]) -> dict[str, Any]:
    cfg = X.xsec_universe_configs()[exp_id]
    out: dict[str, Any] = {}
    neigh = {
        "window_minus": X.XsecUniverseConfig(cfg.ranking_feature, max(2, int(cfg.ranking_window * 0.8)), cfg.ascending, cfg.rebalance_days, cfg.max_hold_days),
        "window_plus": X.XsecUniverseConfig(cfg.ranking_feature, int(cfg.ranking_window * 1.2), cfg.ascending, cfg.rebalance_days, cfg.max_hold_days),
        "rebalance_plus": X.XsecUniverseConfig(cfg.ranking_feature, cfg.ranking_window, cfg.ascending, cfg.rebalance_days + 2, cfg.max_hold_days),
    }
    for name, oc in neigh.items():
        tr, _ = run_xsec(exp_id, val_corpus, cost=cost, override=oc)
        out[f"neighborhood_{name}"] = summarize(tr, cost_bps_rt=cost)
    tr, _ = run_xsec(exp_id, val_corpus, cost=cost, override=X.XsecUniverseConfig(
        cfg.ranking_feature, cfg.ranking_window, cfg.ascending, cfg.rebalance_days, cfg.max_hold_days, entry_delay_days=1))
    out["execution_delay_1d"] = summarize(tr, cost_bps_rt=cost)
    for m in (1.25, 1.5, 2.0):
        tr, _ = run_xsec(exp_id, val_corpus, cost=cost * m)
        out[f"cost_{m}x"] = summarize(tr, cost_bps_rt=cost * m)
    # universe perturbation: leave-one-asset-out on the top contributors
    val_trades = run_xsec(exp_id, val_corpus, cost=cost)[0]
    by_asset = A.pnl_by_asset(val_trades)
    top_assets = [s for s, _ in sorted(by_asset.items(), key=lambda kv: kv[1], reverse=True)[:5]]
    loo: dict[str, Any] = {}
    for sym in top_assets:
        subset = [s for s in D.available_symbols() if s != sym]
        tr, _ = run_xsec(exp_id, val_corpus, cost=cost, subset=subset)
        loo[sym] = summarize(tr, cost_bps_rt=cost)
    out["leave_one_out"] = loo
    out["top_contributors"] = top_assets
    full_trades, elig = run_xsec(exp_id, full_corpus, cost=cost)
    out["pnl_by_year"] = A.pnl_by_year(full_trades)
    out["pnl_by_asset"] = A.pnl_by_asset(full_trades)
    out["concentration"] = A.concentration_by_asset_and_period(full_trades)
    bench = DL.to_ohlcv(D.load_corpus_range(["BTCUSDT"], *D.DEV_VAL_RANGE)["BTCUSDT"])
    regimes = A.regime_by_day(bench)
    out["pnl_by_regime"] = A.regime_pnl(full_trades, regimes)
    out["eligible_count_by_decision"] = {"min": min(elig.values()) if elig else 0,
                                         "max": max(elig.values()) if elig else 0}
    return out


# --------------------------------------------------------------------- universe census


def universe_census() -> dict[str, Any]:
    corpus = D.load_corpus()
    uverse = U.DynamicAssetUniverse(corpus, D.listing_times(), D.corpus_digest())
    sizes_by_split: dict[str, list[int]] = {}
    week = 7 * D.MS_PER_DAY
    ranges = {
        "DEV": (D._2019_01_01, D.DEV_END_MS),
        "VALIDATION": D.SPLIT_RANGES["VALIDATION"],
        "DEV_VAL": D.DEV_VAL_RANGE,
    }
    for split, (start, end) in ranges.items():
        times = list(range(start + 30 * D.MS_PER_DAY, end, week))
        sizes_by_split[split] = uverse.size_series(times)
    lt = D.listing_times()
    listings = {
        "first": min(lt.values()), "last_max": max(lt.values()), "count": len(lt),
    }
    return {
        "assets_available": len(D.available_symbols()),
        "total_bars": sum(len(v) for v in corpus.values()),
        "corpus_digest": D.corpus_digest(),
        "size_distribution": A.universe_size_distribution(sizes_by_split),
        "listing_range": listings,
        "survivorship_limitation": D.SURVIVORSHIP_LIMITATION,
    }


# --------------------------------------------------------------------- main


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    base_cost = C.cost_model_v3_rt_bps()
    report: dict[str, Any] = {
        "program": "ARP-006 DIVERSIFIED ALPHA SEARCH",
        "code_hash": code_hash(),
        "config_hash": config_hash(),
        "cost_bps_rt": base_cost,
        "cost_model": "COST_MODEL_V3",
        "isolation": "research-only; no runtime/Risk/lifecycle/promotion authority",
        "universe": universe_census(),
        "experiments": {},
    }
    print("universe:", json.dumps(report["universe"]["size_distribution"]), flush=True)

    dev_corpus = daily_corpus("DEV")
    val_corpus = daily_corpus("VALIDATION")
    for exp_id in ("EXP-ARP-006", "EXP-ARP-008"):
        print(f"== {exp_id}", flush=True)
        dev_tr = run_daily(exp_id, dev_corpus, cost=base_cost)
        dev = summarize(dev_tr, cost_bps_rt=base_cost)
        decision = decision_from(dev, min_trades=IDENTITY[exp_id]["min_trades"], cost=base_cost)
        entry: dict[str, Any] = {
            "identity": IDENTITY[exp_id], "params": params_key(exp_id),
            "DEV": dev, "DEV_decision": decision,
            "COST_stress": cost_stress(dev["expectancy_gross_bps"], base_cost),
        }
        if decision == "DEV_PASS":
            val_tr = run_daily(exp_id, val_corpus, cost=base_cost)
            val = summarize(val_tr, cost_bps_rt=base_cost)
            entry["VALIDATION"] = val
            entry["VALIDATION_decision"] = (
                "VALIDATION_PASS" if (val["expectancy_net_bps"] or -1) > 0 and val["trades"] >= IDENTITY[exp_id]["min_trades"]
                else "REJECT_VALIDATION"
            )
            if entry["VALIDATION_decision"] == "VALIDATION_PASS":
                entry["ROBUSTNESS"] = robustness_daily(exp_id, cost=base_cost, base=dev)
                rob = entry["ROBUSTNESS"]
                robust_ok = _robust_ok(rob)
                entry["ROBUSTNESS_decision"] = "ROBUSTNESS_SURVIVOR" if robust_ok else "ROBUSTNESS_FAILED"
        report["experiments"][exp_id] = entry

    xsec_val = xsec_corpus("VALIDATION")
    xsec_full = D.load_corpus_range(None, *D.DEV_VAL_RANGE)
    for exp_id in ("EXP-ARP-016", "EXP-ARP-017", "EXP-ARP-018"):
        print(f"== {exp_id}", flush=True)
        dev_tr, dev_elig = run_xsec(exp_id, xsec_corpus("DEV"), cost=base_cost)
        dev = summarize(dev_tr, cost_bps_rt=base_cost)
        dev["concentration_broad"] = A.concentration_by_asset_and_period(dev_tr)
        decision = decision_from(dev, min_trades=IDENTITY[exp_id]["min_trades"], cost=base_cost)
        entry = {
            "identity": IDENTITY[exp_id], "params": params_key(exp_id),
            "DEV": dev, "DEV_decision": decision,
            "DEV_eligible_universe": {"min": min(dev_elig.values()) if dev_elig else 0,
                                      "max": max(dev_elig.values()) if dev_elig else 0},
            "COST_stress": cost_stress(dev["expectancy_gross_bps"], base_cost),
        }
        if decision == "DEV_PASS":
            val_tr, _ = run_xsec(exp_id, xsec_val, cost=base_cost)
            val = summarize(val_tr, cost_bps_rt=base_cost)
            val["concentration_broad"] = A.concentration_by_asset_and_period(val_tr)
            entry["VALIDATION"] = val
            conc_ok = (val["concentration_broad"].get("top_asset_share") or 0) <= 0.5
            entry["VALIDATION_decision"] = (
                "VALIDATION_PASS" if (val["expectancy_net_bps"] or -1) > 0 and val["trades"] >= IDENTITY[exp_id]["min_trades"] and conc_ok
                else "REJECT_VALIDATION"
            )
            if entry["VALIDATION_decision"] == "VALIDATION_PASS":
                entry["ROBUSTNESS"] = robustness_xsec(exp_id, cost=base_cost, base=dev,
                                                      val_corpus=xsec_val, full_corpus=xsec_full)
                entry["ROBUSTNESS_decision"] = "ROBUSTNESS_SURVIVOR" if _robust_ok(entry["ROBUSTNESS"]) else "ROBUSTNESS_FAILED"
            elif exp_id == "EXP-ARP-017":
                entry["VALIDATION_NOTE"] = "previous reversal VALIDATION consumed by EXP-ARP-014"
        report["experiments"][exp_id] = entry
        print(f"   DEV={decision} net={dev['expectancy_net_bps']}", flush=True)

    survivors = [e for e in report["experiments"].values() if e.get("ROBUSTNESS_decision") == "ROBUSTNESS_SURVIVOR"]
    report["summary"] = {
        "dev_survivors": [k for k, v in report["experiments"].items() if v["DEV_decision"] == "DEV_PASS"],
        "cost_survivors": [k for k, v in report["experiments"].items() if v["DEV_decision"] == "DEV_PASS"],
        "validation_survivors": [k for k, v in report["experiments"].items() if v.get("VALIDATION_decision") == "VALIDATION_PASS"],
        "robustness_survivors": [k for k, v in report["experiments"].items() if v.get("ROBUSTNESS_decision") == "ROBUSTNESS_SURVIVOR"],
        "oos_opened": False,
        "oos_survivors": [],
        # OOS is closed, so no strategy is a promotion candidate yet: survivors are
        # OOS-gate-eligible pending independent verification (§26/§27).
        "oos_gate_eligible_pending_independent_verification": [
            e.get("identity", {}).get("strategy_id") for e in survivors
        ],
        "promotion_candidates": [],
    }
    (OUT / "RESULTS.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print("survivors:", report["summary"]["robustness_survivors"], flush=True)
    print("wrote", OUT / "RESULTS.json", flush=True)


def _robust_ok(rob: dict[str, Any]) -> bool:
    """A robustness survivor must keep positive net in the majority of perturbations."""
    vals: list[float] = []
    for key, v in rob.items():
        perturbed = key.startswith(("neighborhood_", "cost_", "asset_")) or key == "execution_delay_1d"
        if perturbed and isinstance(v, dict) and v.get("expectancy_net_bps") is not None:
            vals.append(float(v["expectancy_net_bps"]))
    if not vals:
        return False
    return sum(1 for v in vals if v > 0) / len(vals) >= 0.6


if __name__ == "__main__":
    main()
