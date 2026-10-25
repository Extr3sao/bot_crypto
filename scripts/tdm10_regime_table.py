"""WP-TDM-10 — regime and stability table (evidence for ROBUSTNESS_REPORT).

Uses the same estimator module as the builder, on the holdout window only, and
writes counts next to means: a regime mean without its trade count is not
evidence. This script produces no verdict; it exists so §7 of the frozen spec is
reported with sample sizes instead of bare averages.
"""

from __future__ import annotations

import csv
import importlib.util
import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

ART = REPO_ROOT / ".tdm10"
OUT = ART / "regime_table.csv"
HOLD_START = "2026-09-25T00:00:00Z"
HOLD_END = "2026-10-25T00:00:00Z"

FIELDS = [
    "strategy_id",
    "trades",
    "trades_per_day",
    "regime",
    "label",
    "count",
    "share_pct",
    "gross_bps",
    "net_bps",
    "net_ci_low",
    "net_ci_high",
    "first_half_net",
    "second_half_net",
]


def load_builder() -> object:
    spec = importlib.util.spec_from_file_location(
        "tdm10_experiment", REPO_ROOT / "scripts" / "tdm10_experiment.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    builder = load_builder()
    cost = builder.base_cost_bps()
    start_ms, end_ms = builder.utc_ms(HOLD_START), builder.utc_ms(HOLD_END)
    days = (end_ms - start_ms) / 86_400_000.0

    rows: list[dict[str, object]] = []
    for tf, minutes in builder.TIMEFRAMES.items():
        horizon_bars = max(1, round(builder.PRIMARY_HORIZON / minutes))
        for family_name in builder.FAMILIES:
            cell = f"{family_name}@{tf}"
            trades: list[dict[str, object]] = []
            for asset in builder.ASSETS:
                series = builder.Series(builder.load_bars(builder.HOLD_DIR / f"{asset}_{tf}.json"))
                signals = builder.compute_signals(builder.family_instance(family_name), series.bars)
                trades.extend(
                    builder.build_trades(
                        series,
                        signals,
                        horizon_bars=horizon_bars,
                        start_ms=start_ms,
                        end_ms=end_ms,
                        annotate=True,
                    )
                )
            trades.sort(key=lambda t: int(t["decision_ms"]))
            if not trades:
                continue
            for axis in ("regime_trend", "regime_vol"):
                buckets: dict[str, list[dict[str, object]]] = {}
                for trade in trades:
                    buckets.setdefault(str(trade[axis]), []).append(trade)
                for label, bucket in sorted(buckets.items()):
                    gross = [float(t["gross_bps"]) for t in bucket]
                    net = [g - cost for g in gross]
                    ci = builder.bootstrap_ci(net) if len(net) > 1 else (float("nan"), float("nan"))
                    rows.append(
                        {
                            "strategy_id": cell,
                            "trades": len(trades),
                            "trades_per_day": round(len(trades) / days, 3),
                            "regime": axis,
                            "label": label,
                            "count": len(bucket),
                            "share_pct": round(100.0 * len(bucket) / len(trades), 2),
                            "gross_bps": round(statistics.fmean(gross), 4),
                            "net_bps": round(statistics.fmean(net), 4),
                            "net_ci_low": None if ci[0] != ci[0] else round(ci[0], 4),
                            "net_ci_high": None if ci[1] != ci[1] else round(ci[1], 4),
                            "first_half_net": None,
                            "second_half_net": None,
                        }
                    )
            net_all = [float(t["gross_bps"]) - cost for t in trades]
            half = len(net_all) // 2
            rows.append(
                {
                    "strategy_id": cell,
                    "trades": len(trades),
                    "trades_per_day": round(len(trades) / days, 3),
                    "regime": "time",
                    "label": "first_half",
                    "count": half,
                    "share_pct": 50.0,
                    "gross_bps": None,
                    "net_bps": round(statistics.fmean(net_all[:half]), 4) if half else None,
                    "net_ci_low": None,
                    "net_ci_high": None,
                    "first_half_net": None,
                    "second_half_net": None,
                }
            )
            rows.append(
                {
                    "strategy_id": cell,
                    "trades": len(trades),
                    "trades_per_day": round(len(trades) / days, 3),
                    "regime": "time",
                    "label": "second_half",
                    "count": len(net_all) - half,
                    "share_pct": 50.0,
                    "gross_bps": None,
                    "net_bps": (
                        round(statistics.fmean(net_all[half:]), 4) if len(net_all) - half else None
                    ),
                    "net_ci_low": None,
                    "net_ci_high": None,
                    "first_half_net": None,
                    "second_half_net": None,
                }
            )
            print(f"  {cell:22s} trades={len(trades):5d}", flush=True)

    ART.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {OUT} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
