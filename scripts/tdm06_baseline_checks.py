"""WP-TDM-06 §B — baseline integrity checks on an authoritative checkout.

Consolidates the checks the Work Package requires before any runtime run is
trusted: YAML configuration actually loads, COST_MODEL_V3 is the model in force,
the admission ledger blocks what it should, and point-in-time slicing drops a bar
that is still forming.

    PYTHONPATH=src python scripts/tdm06_baseline_checks.py --out reports/.../baseline_checks.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

YAML_FILES = (
    "config/assets.yaml",
    "config/exchange.yaml",
    "config/indicators.yaml",
    "config/risk.yaml",
    "config/runtime.yaml",
    "config/strategies.yaml",
    "config/realdata/assets.yaml",
    "config/realdata/exchange.yaml",
    "config/realdata/indicators.yaml",
    "config/realdata/risk.yaml",
    "config/realdata/runtime.yaml",
    "config/realdata/strategies.yaml",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_settings() -> dict[str, Any]:
    from trading_bot.config.settings import load_settings

    settings = load_settings(config_dir="config/realdata")
    return {
        "loaded": True,
        "type": f"{type(settings).__module__}.{type(settings).__name__}",
        "runtime_mode": str(getattr(settings.runtime, "mode", None)),
        "live_trading_enabled": bool(getattr(settings.runtime, "live_trading_enabled", None)),
        "exchange_id": str(
            getattr(settings.exchange, "id", None) or getattr(settings.exchange, "exchange_id", None)
        ),
        "universe_pairs": len(getattr(settings.universe, "pairs", []) or []),
        "timeframes": list(getattr(settings.universe, "timeframes", []) or []),
        "risk": {
            "max_risk_per_trade_pct": getattr(settings.risk, "max_risk_per_trade_pct", None),
            "max_open_positions": getattr(settings.risk, "max_open_positions", None),
            "max_total_exposure_pct": getattr(settings.risk, "max_total_exposure_pct", None),
            "max_daily_drawdown_pct": getattr(settings.risk, "max_daily_drawdown_pct", None),
            "kill_switch_enabled": getattr(settings.risk, "kill_switch_enabled", None),
        },
    }


def check_cost_model() -> dict[str, Any]:
    from trading_bot.autonomous.costs import (
        ADMISSION_SCENARIO,
        COST_MODEL_VERSION,
        MODEL_V3_COMPONENT_NAMES,
        CostEngine,
    )

    engine = CostEngine()
    rows = {}
    for symbol, spread in (("BTC/USDT", 1.0), ("ETH/USDT", 1.2), ("SOL/USDT", 2.0)):
        breakdown = engine.evaluate(size_usd=1_000.0, horizon_minutes=5.0, spread_bps=spread)
        rows[symbol] = {
            "round_trip_bps": round(breakdown.round_trip_bps, 4),
            "fee_bps": round(breakdown.fee_bps, 4),
            "slippage_bps": round(breakdown.slippage_bps, 4),
            "impact_bps": round(breakdown.impact_bps, 4),
            "funding_bps": round(breakdown.funding_bps, 4),
            "components": len(breakdown.components),
        }
    return {
        "cost_model_version": COST_MODEL_VERSION,
        "scenario_id": ADMISSION_SCENARIO,
        "venue": engine.venue,
        "product": engine.product,
        "model_component_names": list(MODEL_V3_COMPONENT_NAMES),
        "rows": rows,
    }


def check_admission() -> dict[str, Any]:
    from trading_bot.autonomous.admission_ledger import AdmissionLedger

    ledger = AdmissionLedger.load(REPO_ROOT / "config" / "strategy_admission.json")
    entries = {}
    for timeframe in ("5m", "15m"):
        for sid, entry in sorted(ledger.entries_for_timeframe(timeframe).items()):
            entries[sid] = {
                "status": entry.status.value,
                "expected_gross_edge_bps": entry.expected_gross_edge_bps,
                "admitted_for_paper": entry.admitted_for_paper,
            }
    candidates = sorted(
        sid
        for timeframe in ("5m", "15m")
        for sid in ledger.entries_for_timeframe(timeframe)
        if ledger.entries_for_timeframe(timeframe)[sid].admitted_for_paper
    )
    worst_cost = 23.79
    blocked_by_cost = [
        sid
        for sid, row in entries.items()
        if row["expected_gross_edge_bps"] is not None and row["expected_gross_edge_bps"] < worst_cost
    ]
    return {
        "ledger_path": "config/strategy_admission.json",
        "ledger_sha256": sha256(REPO_ROOT / "config" / "strategy_admission.json"),
        "entries": entries,
        "paper_candidates": candidates,
        "blocked_below_single_side_cost": blocked_by_cost,
        "barrier_bps_reference": worst_cost,
        "verdict": "NO_PAPER_CANDIDATE" if not candidates else "PAPER_CANDIDATE_PRESENT",
    }


def check_pit() -> dict[str, Any]:
    from trading_bot.autonomous.pit import closed_bar_slice

    bar_ms = 5 * 60 * 1000
    start = 1_790_000_000_000
    bars = [
        type("Bar", (), {"timestamp": start + i * bar_ms, "close": 100.0 + i})()
        for i in range(4)
    ]
    decision_ts = bars[-1].timestamp + bar_ms // 2  # the last bar is still forming
    slice_ = closed_bar_slice(bars, decision_ts, interval_ms=bar_ms)
    return {
        "bars_supplied": len(bars),
        "decision_ts": decision_ts,
        "last_bar_open": bars[-1].timestamp,
        "bars_returned": len(slice_),
        "forming_bar_excluded": len(slice_) == len(bars) - 1
        and all(b.timestamp <= decision_ts for b in slice_),
        "no_future_bar": all(b.timestamp <= decision_ts for b in slice_),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    payload: dict[str, Any] = {
        "schema": "wp-tdm-06-baseline-v1",
        "repo_root": str(REPO_ROOT),
        "head_commit": __import__("subprocess")
        .run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True)
        .stdout.strip(),
        "config_files": {
            rel: {"sha256": sha256(REPO_ROOT / rel), "present": (REPO_ROOT / rel).exists()}
            for rel in YAML_FILES
        },
    }
    for name, fn in (
        ("settings", check_settings),
        ("cost_model", check_cost_model),
        ("admission", check_admission),
        ("pit", check_pit),
    ):
        try:
            payload[name] = fn()
        except Exception as exc:
            payload[name] = {"error": f"{type(exc).__name__}: {exc}"}

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: payload[k] for k in ("settings", "admission", "pit")}, indent=2, default=str)[:2500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
