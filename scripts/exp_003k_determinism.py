"""exp_003k_determinism — the same slice, twice, for every strategy 003K ran.

    ./.venv/Scripts/python.exe scripts/exp_003k_determinism.py --days 2

Whole-lane determinism is expensive: a 46-day replay of one family takes tens of minutes,
and six of them twice is an afternoon. The property that can go wrong when the adapter is
generalised, though, is per-decision, and it shows up in the first days as reliably as in
the last. So this script replays a fixed slice of the research window **twice** for each
strategy and compares the two ledgers row by row (wall-clock stamps excluded).

What it claims: for this slice, the same bars and the same code produce the same decisions,
the same fills, the same closes and the same PnL. What it does not claim: that the 46-day
result is reproducible in full. That is declared in the report as a slice, not as a whole.

It writes ``runs/<strategy>/real/research/DETERMINISM.json`` without touching the run's
ledger: the comparison happens in a temporary directory and only the verdict is stored.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

from exp_003j_replay import _normalized, _parse_utc, run_arm  # noqa: E402
from trading_bot.vision.ledger import read_entries  # noqa: E402

OUT = REPO / "reports" / "ai-bots" / "EXP-003K-CANDIDATE-001"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


def _utc(ms: int) -> str:
    return datetime.fromtimestamp(int(ms) / 1000.0, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=2)
    parser.add_argument("--strategy-id", nargs="*", default=None)
    args = parser.parse_args(argv)

    partitions = json.loads((OUT / "PARTITIONS.json").read_text(encoding="utf-8"))
    start_ms = _parse_utc(partitions["research"]["start_utc"])
    end_ms = start_ms + args.days * 86_400_000
    strategies = args.strategy_id or sorted(
        path.name for path in (OUT / "runs").iterdir() if (path / "real" / "research").is_dir()
    )
    ok = True
    with tempfile.TemporaryDirectory(prefix="003k-det-") as tmp:
        scratch = Path(tmp)
        for strategy_id in strategies:
            spec_min = {"trend": 56}.get(strategy_id, 60)
            kwargs = {
                "arm": "real",
                "partition": "research",
                "symbols": list(SYMBOLS),
                "start_ms": start_ms,
                "end_ms": end_ms,
                "timeframe": "5m",
                "window_bars": max(60, spec_min),
                "decision_every": 24,
                "equity": 10_000.0,
                "dataset_dir": OUT / "dataset",
                "strategy_id": strategy_id,
                "book_prefix": f"paper-003k-det-{strategy_id}",
                "run_schema": "AI_BOTS_003K_DET_SLICE_V1",
                "experiment": "EXP-003K-CANDIDATE-001",
            }
            first = run_arm(out_dir=scratch / strategy_id / "a", **kwargs)
            second = run_arm(out_dir=scratch / strategy_id / "b", **kwargs)
            left = _normalized(read_entries(first["dir"] / "ledger.jsonl"))
            right = _normalized(read_entries(second["dir"] / "ledger.jsonl"))
            verdict: dict[str, Any] = {
                "arm": "real",
                "partition": "research",
                "strategy_id": strategy_id,
                "rows": len(left),
                "identical": left == right,
                "first_sha256": first["ledger_sha256"],
                "second_sha256": second["ledger_sha256"],
                "slice_start_utc": _utc(start_ms),
                "slice_end_utc": _utc(end_ms),
                "slice_days": args.days,
                "scope": (
                    "a fixed slice of the research window, replayed twice; the 46-day run "
                    "was not re-executed"
                ),
            }
            verdict["ok"] = bool(verdict["identical"])
            ok &= verdict["ok"]
            target = OUT / "runs" / strategy_id / "real" / "research" / "DETERMINISM.json"
            target.write_text(
                json.dumps(verdict, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
            )
            print(
                f"[003k-det] {strategy_id}: rows={verdict['rows']} identical={verdict['identical']}",
                flush=True,
            )
    print(f"[003k-det] {'PASS' if ok else 'FAIL'}", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
