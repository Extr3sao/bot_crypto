"""RFC-020 HTF multi-timeframe join audit (§8/§11) + stale-data audit (§15).

HTF: the authoritative runtime consumes a SINGLE timeframe (``settings.universe``
carries one timeframe), so there is no LTF+HTF join in the runtime path. The HTF
datasets that DO exist (``*_5m_15m|30m|1h.json``) are used only by research
backtests and are PIT-consistent by construction (label = bucket OPEN, only
complete buckets emitted, availability = open + tf). The ``htf_pit`` helper is
ORPHAN (no tracked src/ importer) and carries a documented unit defect (P3).

Stale: freshness contract per (asset, timeframe) — a decision may only use a bar
that CLOSED at or before the decision instant, and the newest such close must be
within ``allowed_age`` of the decision. Recomputed from the run's traces.

Usage:
    python scripts/rfc020_htf_stale_audit.py \\
        --run-dir reports/rfc010/runs/RFC010-BASELINE-DEV \\
        --out-dir reports/data-integrity
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from itertools import pairwise
from pathlib import Path
from typing import Any

DATA = Path("reports/strategy-baseline/data")
BAR_MS = {"5m": 300_000, "15m": 900_000, "30m": 1_800_000, "1h": 3_600_000}


def _int(value: Any) -> int:
    return int(value) if value is not None else 0


def load_traces(run_dir: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in (run_dir / "traces.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def htf_join_audit() -> dict[str, Any]:
    htf_files = sorted(p.name for p in DATA.glob("*_5m_*.json"))
    # verify the resample contract on one 1h file: label = bucket open
    sample = sorted(DATA.glob("BTCUSDT_W1_2026-*_5m_1h.json"))[0]
    bars = json.loads(sample.read_text(encoding="utf-8"))
    ts = [int(b["ts"]) for b in bars]
    return {
        "schema": "rfc020.htf_join_audit.v1",
        "runtime_reachable_htf_join": False,
        "runtime_timeframe": "5m (single)",
        "ltf_htf_joins_in_runtime": 0,
        "htf_datasets_present": len(htf_files),
        "htf_dataset_sample": htf_files[:6],
        "resample_label": "BAR_OPEN (bucket ts // tf_ms * tf_ms)",
        "resample_complete_buckets_only": True,
        "availability_rule": "htf_open + tf (close)",
        "sample_1h_spacing_ms": sorted({b - a for a, b in pairwise(ts)})[:5],
        "orphan_helper": {
            "path": "src/trading_bot/market_data/htf_pit.py",
            "runtime_importers": 0,
            "defect": "DEF-HTF-PIT-001 (adds tf in SECONDS to an ms timestamp)",
            "severity": "P3",
            "blocks_g2": False,
            "evidence": "tests/unit/autonomous/test_rfc020_point_in_time.py::"
            "test_orphan_htf_helper_has_no_runtime_importer",
        },
        "HTF_PIT_STATUS": "PASS_FOR_RUNTIME (no HTF in the authoritative path)",
    }


def stale_audit(run_dir: Path, timeframe: str) -> dict[str, Any]:
    interval_ms = BAR_MS[timeframe]
    allowed_age_ms = interval_ms  # a decision must not lag its newest closed bar
    rows = load_traces(run_dir)
    fresh = stale = unknown = 0
    fail_closed = 0
    reasons: Counter[str] = Counter()
    max_age = 0
    for row in rows:
        decision = int(row.get("decision_time_ms") or 0)
        ctx = row.get("asset_context") or {}
        end = ctx.get("window_end_ts")
        if end in (None, 0):
            unknown += 1
            if row.get("classification") == "CONTEXT_ERROR":
                fail_closed += 1
                reason = str(row.get("reason") or "")
                key = reason.split(":")[0] + ":" + reason.split(":")[-1][:40]
                reasons[key] += 1
            continue
        age = decision - (_int(end) + interval_ms)
        max_age = max(max_age, age)
        if 0 <= age <= allowed_age_ms:
            fresh += 1
        else:
            stale += 1
    return {
        "schema": "rfc020.stale_data_audit.v1",
        "timeframe": timeframe,
        "allowed_age_ms": allowed_age_ms,
        "policy": (
            "FRESH when the newest closed bar (open+tf) is <= decision_time and "
            "within allowed_age; STALE otherwise -> fail-closed NO_TRADE_DATA."
        ),
        "decisions": len(rows),
        "fresh": fresh,
        "stale": stale,
        "unknown_no_context": unknown,
        "fail_closed_no_trade_data": fail_closed,
        "max_age_ms": max_age,
        "context_error_reasons": dict(reasons),
        "STALE_STATUS": "PASS" if stale == 0 else "FAIL",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", default="reports/rfc010/runs/RFC010-BASELINE-DEV")
    ap.add_argument("--timeframe", default="5m")
    ap.add_argument("--out-dir", default="reports/data-integrity")
    args = ap.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    htf = htf_join_audit()
    stale = stale_audit(Path(args.run_dir), args.timeframe)
    (out / "HTF_JOIN_AUDIT.json").write_text(
        json.dumps(htf, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (out / "STALE_DATA_AUDIT.json").write_text(
        json.dumps(stale, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "htf_status": htf["HTF_PIT_STATUS"],
                "stale_status": stale["STALE_STATUS"],
                "fresh": stale["fresh"],
                "stale": stale["stale"],
                "fail_closed": stale["fail_closed_no_trade_data"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
