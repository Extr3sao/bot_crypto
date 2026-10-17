"""edge16_adversarial — run the causal scenarios against real tapes and publish the result.

WP-EDGE-016/16B. ``trading_bot.research.economic_recovery.causality`` defines each
adversarial scenario once; this script runs them on the three holdout symbols, adds
the before/after fill evidence (how far each exit moved, and how many exits the
pre-repair rules filled at their own signal bar), and writes ``CAUSALITY_ADVERSARIAL.json``.

The pytest module asserts the same rows are caught, so the published artifact and the
executed test cannot drift apart.

    python scripts/edge16_adversarial.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading_bot.research.economic_recovery import alpha15 as A
from trading_bot.research.economic_recovery.causality import adversarial_rows
from trading_bot.research.economic_recovery.experiments import Bar, load_ohlcv

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "economic-recovery" / "RFC-EDGE-016"
UNIVERSE = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
WINDOW = 2000


def series(symbol: str) -> list[Bar]:
    return load_ohlcv(REPO / "data" / "edge07" / "holdout-1h" / f"{symbol}_holdout2026.json")[-WINDOW:]


def shift_evidence(symbol: str, bars: list[Bar]) -> dict[str, Any]:
    """How the repair moved each exit, family by family, on the window the tests run on.

    The pre-repair runners publish timestamps and no indices, and every one of their
    exits was filled at the bar whose close decided it — so the exit index *is* the
    signal index there, and that is what makes the old row causally impossible.
    """
    index_of = {bar.ts_ms: index for index, bar in enumerate(bars)}
    rows: list[dict[str, Any]] = []
    for family in A.SINGLE_ASSET_FAMILIES:
        old = A.PRE_PIT_RUNNERS[family.name](bars, family.parameters)
        new = A.family_trades(family, bars)
        by_entry_ts = {int(trade["entry_ts_ms"]): trade for trade in new}
        moved = 0
        matched = 0
        for trade in old:
            candidate = by_entry_ts.get(int(trade["entry_ts_ms"]))
            if candidate is None:
                continue
            matched += 1
            if (
                not candidate["is_mark"]
                and int(candidate["exit_fill_index"]) == int(candidate["exit_signal_index"]) + 1
            ):
                moved += 1
        pre_same_bar = sum(1 for trade in old if index_of.get(trade["exit_ts_ms"], 0) > 0)
        post_same_bar = sum(
            1
            for trade in new
            if not trade["is_mark"]
            and int(trade["exit_fill_index"]) <= int(trade["exit_signal_index"])
        )
        rows.append(
            {
                "family": family.name,
                "pre_pit_trades": len(old),
                "pre_pit_exits_filled_at_their_own_signal_bar": pre_same_bar,
                "post_pit_trades": len(new),
                "post_pit_exits_filled_at_their_own_signal_bar": post_same_bar,
                "entries_matched_by_timestamp": matched,
                "of_those_exits_moved_one_bar": moved,
                "post_pit_terminal_marks": sum(1 for trade in new if trade["is_mark"]),
            }
        )
    return {
        "symbol": symbol,
        "window_bars": len(bars),
        "families": rows,
        "pre_pit_exploit_total": sum(
            row["pre_pit_exits_filled_at_their_own_signal_bar"] for row in rows
        ),
        "pre_pit_trades_total": sum(row["pre_pit_trades"] for row in rows),
        "post_pit_exploit_total": sum(
            row["post_pit_exits_filled_at_their_own_signal_bar"] for row in rows
        ),
        "entries_matched_total": sum(row["entries_matched_by_timestamp"] for row in rows),
        "exits_moved_total": sum(row["of_those_exits_moved_one_bar"] for row in rows),
    }


def main() -> int:
    payload: dict[str, Any] = {
        "schema_version": "EDGE16_CAUSALITY_ADVERSARIAL_V1",
        "work_package": "WP-EDGE-016/16B",
        "method": (
            "each scenario is defined once in trading_bot.research.economic_recovery.causality, "
            "run here against real holdout tapes, and asserted caught by "
            "tests/unit/research/test_edge16_causality.py"
        ),
        "scenarios": {},
        "shift_evidence": {},
    }
    uncaught: list[str] = []
    for symbol in UNIVERSE:
        bars = series(symbol)
        rows = adversarial_rows(bars)
        payload["scenarios"][symbol] = rows
        payload["shift_evidence"][symbol] = shift_evidence(symbol, bars)
        uncaught.extend(f"{symbol}/{row['scenario']}" for row in rows if not row["caught"])

    payload["counts"] = {
        "scenarios": sum(len(rows) for rows in payload["scenarios"].values()),
        "caught": sum(
            1 for rows in payload["scenarios"].values() for row in rows if row["caught"]
        ),
        "uncaught": len(uncaught),
    }
    payload["uncaught"] = uncaught
    payload["verdict"] = "CAUGHT_EVERY_SCENARIO" if not uncaught else "UNCAUGHT_SCENARIOS_PRESENT"
    (OUT / "CAUSALITY_ADVERSARIAL.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"[adversarial16] {payload['counts']['caught']}/{payload['counts']['scenarios']} "
        f"scenarios caught; verdict {payload['verdict']}"
    )
    for symbol, evidence in payload["shift_evidence"].items():
        print(
            f"[adversarial16] {symbol}: pre-PIT {evidence['pre_pit_exploit_total']}/"
            f"{evidence['pre_pit_trades_total']} exits filled at their own signal bar, "
            f"post-PIT {evidence['post_pit_exploit_total']}"
        )
    return 0 if not uncaught else 1


if __name__ == "__main__":
    raise SystemExit(main())
