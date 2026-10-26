"""WP-TDM-06 runtime probe: measure what a checkout *actually* configures.

Runs identically in the shared (possibly mutated) checkout and in a clean HEAD
worktree, so the difference in cost model, settings loading and admission is
measured rather than asserted. Read-only: imports and evaluates, never writes.

    PYTHONPATH=src python scripts/tdm06_runtime_probe.py > out.json
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))


def _attempt(name: str, fn: Any, out: dict[str, Any]) -> None:
    try:
        out[name] = fn()
    except Exception as exc:  # a broken import IS the measurement
        out[name] = {
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(limit=2).splitlines()[-1:],
        }


def main() -> int:
    out: dict[str, Any] = {
        "repo_root": str(REPO_ROOT),
        "python": sys.version.split()[0],
    }

    def settings_probe() -> dict[str, Any]:
        from trading_bot.config import settings as settings_mod

        loaded = settings_mod.load_settings(config_dir=str(REPO_ROOT / "config"))
        payload: dict[str, Any] = {
            "type": type(loaded).__module__ + "." + type(loaded).__name__,
            "has_runtime_mode": hasattr(loaded, "runtime"),
        }
        if hasattr(loaded, "universe"):
            payload["universe_pairs"] = len(getattr(loaded.universe, "pairs", []) or [])
        if hasattr(loaded, "risk"):
            payload["risk_max_open_positions"] = getattr(
                loaded.risk, "max_open_positions", None
            )
        return payload

    def cost_probe() -> dict[str, Any]:
        from trading_bot.autonomous.costs import COST_MODEL_VERSION, CostEngine

        engine = CostEngine()
        rows = {}
        for symbol, spread in (("BTC/USDT", 1.0), ("ETH/USDT", 1.2)):
            breakdown = engine.evaluate(
                size_usd=1_000.0, horizon_minutes=5.0, spread_bps=spread
            )
            rows[symbol] = {
                "round_trip_bps": round(breakdown.round_trip_bps, 4),
                "fee_bps": round(breakdown.fee_bps, 4),
                "slippage_bps": round(breakdown.slippage_bps, 4),
                "impact_bps": round(breakdown.impact_bps, 4),
                "spread_bps": breakdown.spread_bps,
            }
        return {"cost_model_version": COST_MODEL_VERSION, "rows": rows}

    def admission_probe() -> dict[str, Any]:
        from trading_bot.research import admission

        controller = admission.AdmissionController()
        result = controller.admit({"symbol": "BTC/USDT"})
        return {
            "module_file": admission.__file__,
            "verdict": getattr(result, "verdict", None),
            "reason_codes": list(getattr(result, "reason_codes", []) or []),
        }

    def ledger_probe() -> dict[str, Any]:
        from trading_bot.autonomous.admission_ledger import AdmissionLedger

        ledger = AdmissionLedger.load(REPO_ROOT / "config" / "strategy_admission.json")
        rows: dict[str, Any] = {}
        for sid in sorted(ledger.entries_for_timeframe("5m")):
            entry = ledger.entries_for_timeframe("5m")[sid]
            rows[sid] = {
                "status": entry.status.value,
                "expected_gross_edge_bps": entry.expected_gross_edge_bps,
                "admitted_for_paper": entry.admitted_for_paper,
            }
        return {
            "path": "config/strategy_admission.json",
            "entries": rows,
            "paper_candidates_5m": sorted(
                sid
                for sid in rows
                if rows[sid]["admitted_for_paper"] or rows[sid]["status"] == "PAPER_CANDIDATE"
            ),
        }

    def market_data_probe() -> dict[str, Any]:
        from trading_bot.market_data import exchange_connector, ohlcv_fetcher

        return {
            "exchange_connector_file": exchange_connector.__file__,
            "exchange_connector_lines": len(
                Path(exchange_connector.__file__).read_text(encoding="utf-8").splitlines()
            ),
            "ohlcv_fetcher_file": ohlcv_fetcher.__file__,
            "ohlcv_fetcher_lines": len(
                Path(ohlcv_fetcher.__file__).read_text(encoding="utf-8").splitlines()
            ),
            "exchange_connector_symbols": sorted(
                n for n in dir(exchange_connector) if not n.startswith("_")
            )[:12],
        }

    _attempt("settings", settings_probe, out)
    _attempt("cost", cost_probe, out)
    _attempt("admission", admission_probe, out)
    _attempt("ledger", ledger_probe, out)
    _attempt("market_data", market_data_probe, out)
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
