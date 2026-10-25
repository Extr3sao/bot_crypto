"""RFC-020 decision-time provenance (§22).

For every persisted decision in a real run, reconstruct the newest information
the decision could have used and prove it was already available:

    MAX_SOURCE_AVAILABLE_TIME <= decision_time_ms

where ``MAX_SOURCE_AVAILABLE_TIME`` is the CLOSE (``open + interval``) of the
newest bar in the AssetContext window, and also the trace's ``market_time_ms``
(the newest market instant the decision admits). Recomputed independently from
the run's ``traces.jsonl`` and the frozen dataset — never trusted from a summary.

Usage:
    python scripts/rfc020_provenance.py \\
        --run-dir reports/rfc010/runs/RFC010-BASELINE-DEV \\
        --data-dir reports/strategy-baseline/data \\
        --out reports/data-integrity/DECISION_TIME_PROVENANCE.json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from itertools import pairwise
from pathlib import Path
from typing import Any

TF_MS = {"5m": 300_000, "15m": 900_000, "30m": 1_800_000, "1h": 3_600_000}


def _int(value: Any) -> int:
    return int(value) if value is not None else 0


def load_rows(run_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in (run_dir / "traces.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def dataset_bounds(data_dir: Path) -> dict[str, int]:
    """Newest/oldest bar OPEN per asset from the frozen 5m files."""
    bounds: dict[str, int] = {}
    for asset in ("BTC", "ETH", "SOL"):
        last = None
        for path in sorted(data_dir.glob(f"{asset}USDT_W*_2026-*.json")):
            if "_5m_" in path.name:  # skip derived HTF files
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            ts = [int(r["ts"]) for r in payload]
            if ts:
                last = max(last or 0, max(ts))
        if last is not None:
            bounds[f"{asset}/USDT"] = last
    return bounds


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--data-dir", default="reports/strategy-baseline/data")
    ap.add_argument("--timeframe", default="5m")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    interval_ms = TF_MS[args.timeframe]
    rows = load_rows(Path(args.run_dir))
    bounds = dataset_bounds(Path(args.data_dir))

    violations: list[dict[str, Any]] = []
    checked = 0
    with_window = 0
    max_lag_ms = 0
    worst: dict[str, Any] | None = None
    for row in rows:
        decision_ms = int(row.get("decision_time_ms") or 0)
        market_ms = int(row.get("market_time_ms") or 0)
        symbol = str(row.get("symbol") or "")
        ctx = row.get("asset_context") or {}
        window_end = ctx.get("window_end_ts")
        if window_end in (None, 0):
            # terminal row without a context: only the trace market time applies
            if market_ms > decision_ms:
                violations.append(
                    {
                        "decision_id": row.get("decision_id"),
                        "kind": "market_time_after_decision",
                        "market_time_ms": market_ms,
                        "decision_time_ms": decision_ms,
                    }
                )
            continue
        checked += 1
        with_window += 1
        source_available = _int(window_end) + interval_ms
        lag = decision_ms - source_available
        if lag > max_lag_ms:
            max_lag_ms = lag
            worst = {
                "decision_id": row.get("decision_id"),
                "decision_time_ms": decision_ms,
                "window_end_ts": _int(window_end),
                "max_source_available_ms": source_available,
                "lag_ms": lag,
            }
        if source_available > decision_ms or market_ms > decision_ms:
            violations.append(
                {
                    "decision_id": row.get("decision_id"),
                    "symbol": symbol,
                    "decision_time_ms": decision_ms,
                    "market_time_ms": market_ms,
                    "window_end_ts": _int(window_end),
                    "max_source_available_ms": source_available,
                    "kind": (
                        "window_bar_after_decision"
                        if source_available > decision_ms
                        else "market_time_after_decision"
                    ),
                }
            )

    # decision instants must also be monotonically non-decreasing
    instants = [int(r.get("decision_time_ms") or 0) for r in rows]
    monotonic = all(b >= a for a, b in pairwise(instants))

    report = {
        "schema": "rfc020.decision_time_provenance.v1",
        "run_dir": args.run_dir,
        "rows": len(rows),
        "context_rows_checked": checked,
        "rows_with_window": with_window,
        "interval_ms": interval_ms,
        "decision_instants_monotonic": monotonic,
        "violations": len(violations),
        "violation_samples": violations[:10],
        "max_source_lag_ms": max_lag_ms,
        "worst_case": worst,
        "dataset_newest_bar_open_ms": bounds,
        "MAX_SOURCE_AVAILABLE_TIME_LE_DECISION_TIME": len(violations) == 0,
        "regime_counts": dict(Counter(str(r.get("regime")) for r in rows).most_common()),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "rows": len(rows),
                "checked": checked,
                "violations": len(violations),
                "max_lag_ms": max_lag_ms,
                "ok": report["MAX_SOURCE_AVAILABLE_TIME_LE_DECISION_TIME"],
            },
            indent=2,
        )
    )
    return 0 if report["MAX_SOURCE_AVAILABLE_TIME_LE_DECISION_TIME"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
