"""ARP-003 — deterministic cost-feasibility / horizon screen (research-only).

Reads the frozen 5-minute corpus for DEV + VALIDATION windows only (the locked
OOS window W7 is *never* opened), computes the cost-compatibility frontier with
``trading_bot.research.alpha_recovery.feasibility``, and writes
``reports/alpha-recovery-v1-2/COST_FEASIBILITY.json``.

The cost figure is the authoritative ``COST_MODEL_V3`` round trip obtained from
the live ``CostEngine`` — never a literal. Run:

    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/alpha_recovery_feasibility.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.research.alpha_recovery.campaign import (  # noqa: E402
    SPLIT_WINDOWS,
    SYMBOLS,
    corpus_digest,
    cost_model_v3_rt_bps,
    load_bars,
)
from trading_bot.research.alpha_recovery.feasibility import horizon_frontier  # noqa: E402

OUT = REPO / "reports/alpha-recovery-v1-2"


def main() -> int:
    cost_bps_rt = cost_model_v3_rt_bps()

    windows = list(SPLIT_WINDOWS["DEV"]) + list(SPLIT_WINDOWS["VALIDATION"])
    series_by_key: dict[str, list[float]] = {}
    window_rows: list[dict[str, object]] = []
    for symbol in SYMBOLS.values():
        for window in windows:
            bars = load_bars(symbol, window)
            if not bars:
                continue
            series_by_key[f"{symbol}_{window}"] = [b.close for b in bars]
            window_rows.append(
                {
                    "key": f"{symbol}_{window}",
                    "rows": len(bars),
                    "start_ms": bars[0].timestamp,
                    "end_ms": bars[-1].timestamp,
                }
            )

    frontier = horizon_frontier(series_by_key, cost_bps_rt=cost_bps_rt)
    payload = {
        "schema": "arp003-cost-feasibility-v1",
        "cost_model": "COST_MODEL_V3",
        "admission_scenario": "BINANCE_SPOT_STANDARD_TAKER",
        "cost_bps_rt": round(cost_bps_rt, 6),
        "windows_used": windows,
        "oos_window_read": False,
        "dataset_fingerprint": corpus_digest(),
        "series": window_rows,
        "frontier": frontier,
        "caveat": (
            "Feasibility diagnostic only. GROSS_OPPORTUNITY_BPS is the mean |forward move| "
            "available over a horizon; a real mechanism captures only a fraction of it. "
            "Nothing here is evidence of edge and nothing here promotes a strategy."
        ),
    }

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "COST_FEASIBILITY.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    print(f"cost_bps_rt = {cost_bps_rt:.6f}")
    print(f"dataset_fingerprint = {payload['dataset_fingerprint']}")
    print(f"series = {len(window_rows)}  (DEV+VALIDATION only; OOS not read)")
    print(
        f"{'horizon':>8} {'bars':>6} {'gross_bps':>10} {'median':>9} {'p90':>9} "
        f"{'frac>=cost':>10} {'ratio':>7}"
    )
    for label, row in frontier["per_horizon"].items():
        print(
            f"{label:>8} {row['horizon_bars']:>6} {row['gross_opportunity_bps']:>10.3f} "
            f"{row['median_abs_bps']:>9.3f} {row['p90_abs_bps']:>9.3f} "
            f"{row['frac_abs_ge_cost']:>10.4f} {row['opportunity_to_cost_ratio']:>7.3f}"
        )
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
