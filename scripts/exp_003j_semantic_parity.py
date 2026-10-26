"""exp_003j_semantic_parity — is the frozen 003J ledger still *the same run*?

    ./.venv/Scripts/python.exe scripts/exp_003j_semantic_parity.py --days 10

``exp_003j_determinism.py`` re-ran the research partition and found the two fresh ledgers
identical while neither was byte-identical to the frozen one. A byte difference is not by
itself a behaviour difference: 003K generalised the adapter, which changed the *text* of a
decision (its rationale and its invalidation sentence) and the provider's metadata. It
would be dishonest to call that reproducible, and equally dishonest to call it a regression
without looking.

So this script replays a fixed slice of the research window under the **current** code and
compares it with the frozen ledger's rows for the same slice, on everything that can move
money or a position:

``kind, symbol, side, intent, entry_price, exit_price, pnl_net_usdt``

and on the aggregate the report quotes: fills, closes and net realised. It also records
which keys *did* differ, so the drift is named rather than waved away. The verdict is
``SEMANTIC_PARITY`` only when every structural row matches and the aggregates agree to the
cent; otherwise ``STRUCTURAL_DRIFT``.

Writes ``runs/real/research/SEMANTIC_PARITY.json``; the frozen ledger is only read.
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

OUT = REPO / "reports" / "ai-bots" / "EXP-003J-REAL-SIGNAL-PAPER-001"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
STRUCTURAL = ("kind", "symbol", "side", "intent", "entry_price", "exit_price", "pnl_net_usdt")


def _utc(ms: int) -> str:
    return datetime.fromtimestamp(int(ms) / 1000.0, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _num(value: Any) -> float | None:
    return None if value is None else round(float(value), 8)


def _signature(rows: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    return tuple(
        tuple(_num(row.get(key)) if key in {"entry_price", "exit_price", "pnl_net_usdt"} else row.get(key) for key in STRUCTURAL)
        for row in rows
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=10)
    args = parser.parse_args(argv)

    partitions = json.loads((OUT / "PARTITIONS.json").read_text(encoding="utf-8"))
    start_ms = _parse_utc(partitions["research"]["start_utc"])
    end_ms = start_ms + args.days * 86_400_000
    with tempfile.TemporaryDirectory(prefix="003j-parity-") as tmp:
        run = run_arm(
            arm="real",
            partition="research",
            symbols=list(SYMBOLS),
            start_ms=start_ms,
            end_ms=end_ms,
            timeframe="5m",
            window_bars=60,
            decision_every=24,
            equity=10_000.0,
            out_dir=Path(tmp),
        )
        fresh = _normalized(read_entries(run["dir"] / "ledger.jsonl"))
    frozen = [
        row
        for row in _normalized(read_entries(OUT / "runs" / "real" / "research" / "ledger.jsonl"))
        if int(row.get("ts_ms") or 0) < end_ms
    ]

    differing: dict[str, int] = {}
    for left, right in zip(fresh, frozen):
        for key in set(left) | set(right):
            if left.get(key) != right.get(key):
                differing[key] = differing.get(key, 0) + 1

    def total(rows: list[dict[str, Any]], kind: str, field: str) -> float:
        return round(sum(float(row[field]) for row in rows if row.get("kind") == kind), 8)

    structural_identical = len(fresh) == len(frozen) and _signature(fresh) == _signature(frozen)
    aggregates = {
        "fills": [total(fresh, "FILL", "quantity"), total(frozen, "FILL", "quantity")],
        "closes": [total(fresh, "CLOSE", "pnl_net_usdt"), total(frozen, "CLOSE", "pnl_net_usdt")],
        "net_realised_usdt": [total(fresh, "CLOSE", "pnl_net_usdt"), total(frozen, "CLOSE", "pnl_net_usdt")],
    }
    aggregates_equal = all(
        abs(left - right) <= 1e-6 for left, right in aggregates.values()
    ) and sum(1 for row in fresh if row.get("kind") == "CLOSE") == sum(
        1 for row in frozen if row.get("kind") == "CLOSE"
    )

    verdict = {
        "schema_version": "AI_BOTS_003J_SEMANTIC_PARITY_V1",
        "generated_at_utc": _utc(int(datetime.now(tz=UTC).timestamp() * 1000)),
        "slice_start_utc": _utc(start_ms),
        "slice_end_utc": _utc(end_ms),
        "slice_days": args.days,
        "rows": {"fresh": len(fresh), "frozen": len(frozen)},
        "structural_fields": list(STRUCTURAL),
        "structural_identical": structural_identical,
        "fills": sum(1 for row in fresh if row.get("kind") == "FILL"),
        "closes": sum(1 for row in fresh if row.get("kind") == "CLOSE"),
        "net_realised_usdt": total(fresh, "CLOSE", "pnl_net_usdt"),
        "frozen_net_realised_usdt": total(frozen, "CLOSE", "pnl_net_usdt"),
        "aggregates_equal": aggregates_equal,
        "differing_keys": differing,
        "drift_explanation": (
            "Decision text (rationale/invalidation) and provider.response_chars changed when the "
            "adapter was generalised to several families in 003K. No action, price, fill, close "
            "or PnL differs on this slice."
            if structural_identical and aggregates_equal
            else "Structural difference — this is a behaviour change, not a text change."
        ),
        "verdict": "SEMANTIC_PARITY" if (structural_identical and aggregates_equal) else "STRUCTURAL_DRIFT",
    }
    target = OUT / "runs" / "real" / "research" / "SEMANTIC_PARITY.json"
    target.write_text(
        json.dumps(verdict, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(
        f"[003j-parity] rows={verdict['rows']} structural_identical={structural_identical} "
        f"fills={verdict['fills']} closes={verdict['closes']} "
        f"net={verdict['net_realised_usdt']} verdict={verdict['verdict']}",
        flush=True,
    )
    print(f"[003j-parity] differing keys: {differing}", flush=True)
    return 0 if verdict["verdict"] == "SEMANTIC_PARITY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
