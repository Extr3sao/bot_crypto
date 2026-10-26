"""exp_003j_determinism — close the one 003J check that was left NOT_EXECUTED.

    ./.venv/Scripts/python.exe scripts/exp_003j_determinism.py

003J ran its OOS partition twice and compared the ledgers, but the **research** partition
was only ever run once. ``exp_003j_verify.py`` therefore reported
``V14_determinism_*_research`` as ``NOT_EXECUTED``, which is the honest status but not a
closed item.

This script closes it without touching a single frozen byte: it re-runs both arms of the
research partition twice into a scratch directory, compares the two fresh ledgers row by
row (wall-clock stamps excluded), and then compares the fresh run against the ledger that
is already committed. Only a **new** file is written, ``runs/<arm>/research/DETERMINISM.json``,
in the same shape the OOS partition already carries plus the comparison against the frozen
evidence.

Exit codes: 0 when every comparison is identical, 1 when any differs. A difference is not
repaired here: it is reported, and the frozen ledger stays as it was.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

from exp_003j_replay import _normalized, _parse_utc, run_arm  # noqa: E402

from trading_bot.vision.ledger import read_entries  # noqa: E402

OUT = REPO / "reports" / "ai-bots" / "EXP-003J-REAL-SIGNAL-PAPER-001"
RUNS = OUT / "runs"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--partition", default="research", choices=("research", "oos"))
    parser.add_argument("--timeframe", default="5m")
    parser.add_argument("--window-bars", type=int, default=60)
    parser.add_argument("--decision-every", type=int, default=24)
    parser.add_argument("--equity", type=float, default=10_000.0)
    args = parser.parse_args(argv)

    boundaries = json.loads((OUT / "PARTITIONS.json").read_text(encoding="utf-8"))
    window = boundaries[args.partition]
    start_ms = _parse_utc(window["start_utc"])
    end_ms = _parse_utc(window["end_utc"])
    verdicts: list[dict[str, Any]] = []
    ok = True
    with tempfile.TemporaryDirectory(prefix="003j-determinism-") as tmp:
        scratch = Path(tmp)
        for arm in ("control", "real"):
            kwargs = {
                "arm": arm,
                "partition": args.partition,
                "symbols": list(SYMBOLS),
                "start_ms": start_ms,
                "end_ms": end_ms,
                "timeframe": args.timeframe,
                "window_bars": args.window_bars,
                "decision_every": args.decision_every,
                "equity": args.equity,
            }
            first = run_arm(out_dir=scratch / "first", **kwargs)
            second = run_arm(out_dir=scratch / "second", **kwargs)
            left = _normalized(read_entries(first["dir"] / "ledger.jsonl"))
            right = _normalized(read_entries(second["dir"] / "ledger.jsonl"))
            frozen_path = RUNS / arm / args.partition / "ledger.jsonl"
            frozen = _normalized(read_entries(frozen_path)) if frozen_path.exists() else None
            verdict = {
                "arm": arm,
                "partition": args.partition,
                "rows": len(left),
                # The comparison drops the wall-clock stamp, so the two ledgers have different
                # hashes by construction.  Both facts are published under names that say which.
                "rows_identical": left == right,
                "byte_identical": first["ledger_sha256"] == second["ledger_sha256"],
                "comparison": "ledger row bodies, with recorded_at_utc removed from each row",
                "fields_excluded": ["recorded_at_utc"],
                "first_sha256": first["ledger_sha256"],
                "second_sha256": second["ledger_sha256"],
                "frozen_rows": None if frozen is None else len(frozen),
                "fresh_matches_frozen": None if frozen is None else left == frozen,
                "fresh_vs_frozen_note": (
                    "no frozen ledger to compare against"
                    if frozen is None
                    else "row-by-row, wall-clock stamps excluded"
                ),
            }
            verdict["ok"] = bool(
                verdict["rows_identical"] and (frozen is None or verdict["fresh_matches_frozen"])
            )
            ok &= verdict["ok"]
            verdicts.append(verdict)
            print(
                f"[003j-determinism] {arm}/{args.partition}: rows={verdict['rows']} "
                f"rows_identical={verdict['rows_identical']} "
                f"byte_identical={verdict['byte_identical']} "
                f"fresh_matches_frozen={verdict['fresh_matches_frozen']}",
                flush=True,
            )
            target = RUNS / arm / args.partition / "DETERMINISM.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps(verdict, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
                newline="\n",
            )
    print(f"[003j-determinism] {'PASS' if ok else 'FAIL'}", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
