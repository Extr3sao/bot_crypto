"""WP-TDM-11C — availability gate for the confirmatory window.

No confirmatory bar has been fetched or read by this WP. This script proves that
the window cannot yet support the preregistered test, using only:

* the cutoff (first bar that would be admissible),
* the wall clock,
* the preregistered trade rate from DEV,

so it never touches confirmatory prices. The gate is deliberately expressed in
*expected trades*, because the raw bar count is not the binding constraint: the
rule only trades while the trailing 200-bar trend z-score is below -1.5, and its
minimum sample is 36 trades.

Usage::  python scripts/tdm11_availability.py
Writes ``.tdm11/availability.json``; exit code 0 if the gate was evaluated.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ART = REPO_ROOT / ".tdm11"

CONFIRMATORY_START_MS = 1_792_857_600_000  # 2026-10-24T16:00:00Z
MIN_TRADES = 36
MIN_DAYS = 28.0
TF_MS = 5 * 60_000


def main() -> int:
    ART.mkdir(parents=True, exist_ok=True)
    prereg = json.loads((ART / "prereg.json").read_text(encoding="utf-8"))
    controls = json.loads((ART / "controls.json").read_text(encoding="utf-8"))
    tpd = float(prereg["power"]["expected_trades_per_day"])
    now_ms = int(time.time() * 1000)
    elapsed_ms = now_ms - CONFIRMATORY_START_MS
    elapsed_days = elapsed_ms / 86_400_000.0
    bars = max(0, elapsed_ms // TF_MS)
    # hard ceiling: one position at a time, 30 min hold, so at most one trade
    # per 6 bars *if* a valid SHORT signal and a down regime existed on every bar.
    hard_ceiling = bars // 6
    expected = tpd * elapsed_days
    earliest_days = max(MIN_DAYS, MIN_TRADES / tpd if tpd else MIN_DAYS)
    earliest_ms = CONFIRMATORY_START_MS + int(earliest_days * 86_400_000)

    gates = {
        "elapsed_at_least_min_days": elapsed_days >= MIN_DAYS,
        "expected_trades_at_least_min": expected >= MIN_TRADES,
        "hard_ceiling_at_least_min": hard_ceiling >= MIN_TRADES,
        "adversarial_controls_passed": bool(controls.get("all_passed")),
    }
    decision = {
        "confirmatory_window_opened": False,
        "confirmatory_bars_read": 0,
        "dataset_id": None,
        "result": "AWAITING_NEW_DATA",
        "reason_code": "NO_CONFIRMATORY_SAMPLE",
        "detail": (
            "the admissible window starts at 2026-10-24T16:00Z; as of the run the "
            "expected yield is far below the preregistered minimum, and no confirmatory "
            "bar was fetched or read"
        ),
    }
    payload = {
        "computed_at_ms": now_ms,
        "cutoff_ms": CONFIRMATORY_START_MS,
        "elapsed_days": round(elapsed_days, 3),
        "bars_if_fully_populated": int(bars),
        "hard_ceiling_trades": int(hard_ceiling),
        "expected_trades_now": round(expected, 2),
        "min_trades_required": MIN_TRADES,
        "min_days_required": MIN_DAYS,
        "trades_per_day_used": round(tpd, 3),
        "shortfall_trades": round(max(0.0, MIN_TRADES - expected), 2),
        "earliest_feasible_ms": earliest_ms,
        "earliest_feasible_days": round(earliest_days, 1),
        "earliest_feasible_utc": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(earliest_ms / 1000)
        ),
        "gates": gates,
        "decision": decision,
        "fetched_confirmatory_data": False,
        "note": (
            "the gate is expressed in expected trades, not bar count: 19h of 5m bars "
            "could physically hold at most "
            f"{int(hard_ceiling)} sequential 30-minute positions"
        ),
    }
    (ART / "availability.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
