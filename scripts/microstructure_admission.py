"""MICROSTRUCTURE-EDGE-V1 — machine-readable deliverables + admission (§52-57).

Read-only. Consumes the experiment outputs and applies the PRE-REGISTERED
classification, then reconstructs the docs/*.json deliverables:
  docs/COST_MODEL_V2.json
  docs/MARKET_MICROSTRUCTURE_DATA_AUDIT.json
  docs/MICROSTRUCTURE_RESULTS_V1.json
  docs/MICROSTRUCTURE_ADMISSION_V1.json

Classification is deterministic and never relaxed after the fact.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from trading_bot.research.microstructure.cost_model import (
    ADMISSION_COST_MODEL,
    ADMISSION_SAFETY_MULTIPLE,
    component_table,
    cost_model_status,
)

HERE = os.path.dirname(os.path.abspath(__file__))
REPORTS = os.path.join(HERE, "..", "reports", "microstructure-v1")
DOCS = os.path.join(HERE, "..", "docs")

RT_COST = ADMISSION_COST_MODEL.round_trip_bps()


# --------------------------------------------------------------------------
# data source audit (SRC registry condensed to machine-readable form)
# --------------------------------------------------------------------------

DATA_SOURCES = [
    {
        "source_id": "DS-01", "field": "klines OHLCV + taker flow",
        "provider": "Binance Spot", "endpoint": "/api/v3/klines + data.binance.vision",
        "product": "spot", "history": "full (2017+)", "resolution": "1m..1M",
        "rate_limit": "weight-based, 6000/min", "credentials": False,
        "public": True, "pit_safe": True, "status": "DATA_SUFFICIENT",
    },
    {
        "source_id": "DS-02", "field": "aggTrades (tick aggressor flow)",
        "provider": "Binance Spot", "endpoint": "data.binance.vision aggTrades + /api/v3/aggTrades",
        "product": "spot", "history": "full (monthly/daily zips)", "resolution": "tick",
        "rate_limit": "bulk download", "credentials": False,
        "public": True, "pit_safe": True, "status": "DATA_SUFFICIENT",
    },
    {
        "source_id": "DS-03", "field": "bookTicker (best bid/ask)",
        "provider": "Binance Spot", "endpoint": "/api/v3/ticker/bookTicker (live only)",
        "product": "spot", "history": "none", "resolution": "live",
        "rate_limit": "n/a", "credentials": False,
        "public": True, "pit_safe": True, "status": "LIVE_ONLY",
    },
    {
        "source_id": "DS-04", "field": "order book depth",
        "provider": "Binance Spot", "endpoint": "/api/v3/depth + WS @depth (live only)",
        "product": "spot", "history": "none", "resolution": "live",
        "rate_limit": "n/a", "credentials": False,
        "public": True, "pit_safe": True, "status": "LIVE_ONLY",
    },
    {
        "source_id": "DS-05", "field": "funding rate",
        "provider": "Binance USD-M", "endpoint": "/fapi/v1/fundingRate",
        "product": "perpetual", "history": "full", "resolution": "1h/4h/8h",
        "rate_limit": "weight-based", "credentials": False,
        "public": True, "pit_safe": True, "status": "DATA_SUFFICIENT",
    },
    {
        "source_id": "DS-06", "field": "premium index / mark",
        "provider": "Binance USD-M", "endpoint": "/fapi/v1/premiumIndexKlines",
        "product": "perpetual", "history": "full", "resolution": "1m..1d",
        "rate_limit": "weight-based", "credentials": False,
        "public": True, "pit_safe": True, "status": "DATA_SUFFICIENT",
    },
    {
        "source_id": "DS-07", "field": "open interest",
        "provider": "Binance USD-M", "endpoint": "/futures/data/openInterestHist",
        "product": "perpetual", "history": "latest 30 days only", "resolution": "5m..1d",
        "rate_limit": "1000/5min", "credentials": False,
        "public": True, "pit_safe": True, "status": "LIMITED_HISTORY",
    },
    {
        "source_id": "DS-08", "field": "basis / long-short ratio",
        "provider": "Binance USD-M", "endpoint": "/futures/data/basis",
        "product": "perpetual", "history": "latest 30 days only (pagination unstable)",
        "resolution": "5m..1d", "rate_limit": "1000/5min", "credentials": False,
        "public": True, "pit_safe": True, "status": "LIMITED_HISTORY",
    },
]


def _load_json(path: str) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _write_json(path: str, obj: Any) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2)


def build_cost_model_json() -> dict[str, Any]:
    return {
        "generated_by": "scripts/microstructure_admission.py",
        "venue": "Binance",
        "product": "Spot",
        "sandbox": True,
        "previous_model": {"name": "CURRENT_PROJECT_COST_MODEL", "round_trip_bps": 12.0},
        "status": cost_model_status(),
        "admission_model": ADMISSION_COST_MODEL.name,
        "admission_safety_multiple": ADMISSION_SAFETY_MULTIPLE,
        "admission_required_edge_bps": round(
            ADMISSION_COST_MODEL.required_edge_bps(ADMISSION_SAFETY_MULTIPLE), 3
        ),
        "scenarios": component_table(),
    }


# --------------------------------------------------------------------------
# classification (§54)
# --------------------------------------------------------------------------


def classify(base: dict[str, Any], stress: dict[str, Any]) -> str:
    """Deterministic, pre-registered classification."""
    if base["n"] == 0:
        return "NO_INFORMATION"
    if base["gross_bps"] <= 0.0:
        return "NO_GROSS_EDGE"
    if base["gross_bps"] < RT_COST:
        return "COST_KILLED"
    if base["net_bps"] <= 0.0:
        return "COST_KILLED"
    splits = base.get("splits", {})
    if any(splits.get(s, {}).get("net_bps", 0.0) <= 0.0 for s in ("DEV", "VAL", "OOS")):
        return "OOS_FAILED"
    if stress.get("1.5X", {}).get("net_bps", 0.0) <= 0.0:
        return "REGIME_FRAGILE"
    return "PAPER_CANDIDATE"


def build_results() -> dict[str, Any]:
    raw = _load_json(os.path.join(REPORTS, "RESULTS.json"))
    signals = raw["signals"]
    experiments: list[dict[str, object]] = []
    for sid, r in signals.items():
        if sid == "S-06_S-07_oi":
            for sym, d in r.items():
                for sub, payload in d.items():
                    base = payload["scenarios"]["BASE"]
                    experiments.append(
                        {
                            "experiment_id": f"EXP-{sid}-{sym}",
                            "hypothesis_id": "M-06" if "S-06" in sub else "M-07",
                            "signal_id": sub,
                            "asset": sym,
                            "horizon_bars": 15 if "S-06" in sub else 30,
                            "scenarios": payload["scenarios"],
                            "classification": "LIMITED_HISTORY"
                            if base["n"] < 100
                            else classify(base, payload["scenarios"]),
                        }
                    )
            continue
        base = r["scenarios"]["BASE"]
        experiments.append(
            {
                "experiment_id": f"EXP-{sid}",
                "hypothesis_id": r["hypothesis"],
                "signal_id": sid,
                "assets": "BTC,ETH,SOL",
                "horizon_bars": r["horizon_bars"],
                "scenarios": r["scenarios"],
                "classification": classify(base, r["scenarios"]),
            }
        )
    # M-02 untestable historically
    experiments.append(
        {
            "experiment_id": "EXP-S-02_book_imbalance",
            "hypothesis_id": "M-02",
            "signal_id": "S-02",
            "assets": "BTC,ETH,SOL",
            "horizon_bars": None,
            "scenarios": {},
            "classification": "EXECUTION_MODEL_REQUIRED",
            "note": "order book / bookTicker have no historical source (DS-03/DS-04 = LIVE_ONLY)",
        }
    )
    return {
        "cost_bps_rt": RT_COST,
        "cost_model": ADMISSION_COST_MODEL.name,
        "stress": raw["stress"],
        "experiments": experiments,
    }


def build_admission(results: dict[str, Any]) -> dict[str, Any]:
    exps = results["experiments"]
    admitted = [e for e in exps if e["classification"] == "PAPER_CANDIDATE"]
    by_class: dict[str, int] = {}
    for e in exps:
        by_class[e["classification"]] = by_class.get(e["classification"], 0) + 1
    table = []
    for e in exps:
        base = e["scenarios"].get("BASE", {}) if e["scenarios"] else {}
        table.append(
            {
                "candidate": e["signal_id"],
                "hypothesis": e["hypothesis_id"],
                "data": "spot_klines_flow" if e["hypothesis_id"] in ("M-01", "M-03") else
                        "usdm_funding_premium" if e["hypothesis_id"] in ("M-04", "M-05") else
                        "usdm_oi" if e["hypothesis_id"] in ("M-06", "M-07") else
                        "spot_cross" if e["hypothesis_id"] == "M-08" else "order_book",
                "horizon": e["horizon_bars"],
                "trades": base.get("n", 0),
                "gross_edge_bps": base.get("gross_bps"),
                "realistic_cost_bps": RT_COST,
                "net_edge_bps": base.get("net_bps"),
                "oos_pf": None,
                "oos_net_bps": (base.get("splits", {}).get("OOS", {}) or {}).get("net_bps"),
                "max_dd_bps": base.get("max_dd_bps"),
                "status": e["classification"],
            }
        )
    return {
        "admission_cost_model": ADMISSION_COST_MODEL.name,
        "admission_required_edge_bps": round(
            ADMISSION_COST_MODEL.required_edge_bps(ADMISSION_SAFETY_MULTIPLE), 3
        ),
        "candidates_total": len(exps),
        "admitted": [e["signal_id"] for e in admitted],
        "by_classification": by_class,
        "candidate_table": table,
    }


def main() -> None:
    os.makedirs(DOCS, exist_ok=True)

    cm = build_cost_model_json()
    _write_json(os.path.join(DOCS, "COST_MODEL_V2.json"), cm)

    ds = {
        "generated_by": "scripts/microstructure_admission.py",
        "sources": DATA_SOURCES,
        "summary": {
            "DATA_SUFFICIENT": sum(1 for s in DATA_SOURCES if s["status"] == "DATA_SUFFICIENT"),
            "LIMITED_HISTORY": sum(1 for s in DATA_SOURCES if s["status"] == "LIMITED_HISTORY"),
            "LIVE_ONLY": sum(1 for s in DATA_SOURCES if s["status"] == "LIVE_ONLY"),
            "NOT_USABLE": sum(1 for s in DATA_SOURCES if s["status"] == "NOT_USABLE"),
        },
    }
    _write_json(os.path.join(DOCS, "MARKET_MICROSTRUCTURE_DATA_AUDIT.json"), ds)

    results = build_results()
    _write_json(os.path.join(DOCS, "MICROSTRUCTURE_RESULTS_V1.json"), results)

    adm = build_admission(results)
    _write_json(os.path.join(DOCS, "MICROSTRUCTURE_ADMISSION_V1.json"), adm)

    print("COST_MODEL_STATUS:", cm["status"], "RT:", cm["admission_model"], RT_COST, "bps")
    print("by classification:", adm["by_classification"])
    print("admitted:", adm["admitted"])
    print("-> docs/COST_MODEL_V2.json, MARKET_MICROSTRUCTURE_DATA_AUDIT.json,")
    print("   MICROSTRUCTURE_RESULTS_V1.json, MICROSTRUCTURE_ADMISSION_V1.json")


if __name__ == "__main__":
    main()
