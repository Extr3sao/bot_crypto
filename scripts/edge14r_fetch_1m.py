"""edge14r_fetch_1m — the 1-minute source rows Jesse's engine requires.

Jesse 3.3.5 stores every instrument as a 1-minute series and *generates* each
higher timeframe from it inside the backtest loop.  Feeding it the frozen 1-hour
rows therefore produces a run in which the 1h route is never published to the
strategy: the aggregation release is keyed on a source row at
``bucket_end - 60_000``, and a 1h-spaced series has no such row.  That is an
engine constraint, not a settings choice.

So this script fetches the same window at 1-minute resolution from the same
public venue through ccxt, writes it next to the frozen dataset, and then
audits it: the 1h bars Jesse will generate from these rows must equal the
frozen 1h bars the other engines were given, bar for bar.  If they differed,
the comparison would be between two datasets and the parity claim would be
worthless.

    python scripts/edge14r_fetch_1m.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "economic-recovery" / "RFC-EDGE-014R"
FROZEN_1H = OUT / "scratch" / "PAPER_REPLAY_BARS.jsonl"
DEST_1M = OUT / "scratch" / "JESSE_1M_BARS.jsonl"
AUDIT = OUT / "JESSE_1M_SOURCE_AUDIT.json"

TIMEFRAME_MS = 60_000


def _load_frozen(path: Path) -> dict[str, list[list[float]]]:
    out: dict[str, list[list[float]]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        out.setdefault(row["symbol"], []).append(
            [
                int(row["timestamp"]),
                float(row["open"]),
                float(row["high"]),
                float(row["low"]),
                float(row["close"]),
                float(row["volume"]),
            ]
        )
    for series in out.values():
        series.sort(key=lambda r: r[0])
    return out


def _fetch_1m(symbol: str, start_ms: int, end_ms: int, exchange_id: str) -> list[list[float]]:
    import ccxt

    exchange = getattr(ccxt, exchange_id)()
    cursor = start_ms
    rows: dict[int, list[float]] = {}
    empty_pages = 0
    while cursor < end_ms:
        batch = exchange.fetch_ohlcv(symbol, "1m", since=cursor, limit=1000)
        if not batch:
            empty_pages += 1
            if empty_pages > 3:
                break
            cursor += 1000 * TIMEFRAME_MS
            continue
        empty_pages = 0
        for row in batch:
            ts = int(row[0])
            if start_ms <= ts < end_ms:
                rows[ts] = [float(v) for v in row]
        cursor = int(batch[-1][0]) + TIMEFRAME_MS
        time.sleep(exchange.rateLimit / 1000.0)
    return [rows[k] for k in sorted(rows)]


def _aggregate_1h(rows: list[list[float]]) -> dict[int, list[float]]:
    buckets: dict[int, list[list[float]]] = {}
    for row in rows:
        bucket = (int(row[0]) // 3_600_000) * 3_600_000
        buckets.setdefault(bucket, []).append(row)
    out: dict[int, list[float]] = {}
    for bucket, members in buckets.items():
        out[bucket] = [
            float(bucket),
            members[0][1],
            max(m[2] for m in members),
            min(m[3] for m in members),
            members[-1][4],
            sum(m[5] for m in members),
        ]
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="WP-EDGE-14R 1m source fetch")
    parser.add_argument("--symbols", default="BTC/USDT,ETH/USDT")
    parser.add_argument("--exchange", default="binance")
    parser.add_argument("--out", default=str(DEST_1M))
    parser.add_argument(
        "--include-partial-final-bar",
        action="store_true",
        help="Keep the final frozen bar, which was captured mid-hour and is not closed",
    )
    args = parser.parse_args()

    if not FROZEN_1H.is_file():
        print(f"[fetch] frozen 1h dataset not found: {FROZEN_1H}", file=sys.stderr)
        return 1

    frozen = _load_frozen(FROZEN_1H)
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    dest = Path(args.out)

    audit: dict[str, Any] = {
        "exchange": args.exchange,
        "source_timeframe": "1m",
        "route_timeframe": "1h",
        "frozen_1h_dataset": str(FROZEN_1H),
        "frozen_1h_sha256": hashlib.sha256(FROZEN_1H.read_bytes()).hexdigest(),
        "dest_1m_dataset": str(dest),
        "partial_final_bar_included": bool(args.include_partial_final_bar),
        "frozen_final_bar": None,
        "symbols": {},
    }
    audit["frozen_final_bar"] = {symbol: int(series[-1][0]) for symbol, series in frozen.items()}

    all_rows: dict[str, list[list[float]]] = {}
    for symbol in symbols:
        series = frozen[symbol]
        start_ms = int(series[0][0])
        # The frozen dataset's final row was captured while its hour was still
        # forming, so it is not a closed bar.  The 1m window therefore stops at
        # that bar's own start: the bucket is then complete, and Jesse's
        # generated 1h series equals the frozen bars up to it exactly.
        last_ts = int(series[-1][0])
        end_ms = last_ts + 3_600_000 if args.include_partial_final_bar else last_ts
        rows = _fetch_1m(symbol, start_ms, end_ms, args.exchange)
        all_rows[symbol] = rows
        agg = _aggregate_1h(rows)
        frozen_by_ts = {int(r[0]): r for r in series if int(r[0]) < end_ms}
        missing = sorted(set(frozen_by_ts) - set(agg))
        extra = sorted(set(agg) - set(frozen_by_ts))
        mismatched = []
        for ts, expected in frozen_by_ts.items():
            got = agg.get(ts)
            if got is None:
                continue
            # volume is summed from a different feed granularity; OHLC must be exact
            if [round(v, 10) for v in expected[1:5]] != [round(v, 10) for v in got[1:5]]:
                mismatched.append(
                    {"timestamp": ts, "frozen": expected[1:5], "aggregated": got[1:5]}
                )
        audit["symbols"][symbol] = {
            "window_start_ms": start_ms,
            "window_end_ms": end_ms,
            "rows_1m": len(rows),
            "expected_rows_1m": (end_ms - start_ms) // TIMEFRAME_MS,
            "coverage": round(len(rows) / max(1, (end_ms - start_ms) // TIMEFRAME_MS), 6),
            "frozen_1h_bars": len(series),
            "bars_missing_after_aggregation": len(missing),
            "bars_extra_after_aggregation": len(extra),
            "ohlc_mismatched_bars": len(mismatched),
            "ohlc_mismatch_examples": mismatched[:5],
        }
        print(
            f"[fetch] {symbol}: {len(rows)} 1m rows, {len(series)} frozen 1h bars, "
            f"mismatched={len(mismatched)}"
        )

    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8") as handle:
        for symbol in sorted(all_rows):
            for row in all_rows[symbol]:
                handle.write(
                    json.dumps(
                        {
                            "symbol": symbol,
                            "timestamp": int(row[0]),
                            "open": row[1],
                            "high": row[2],
                            "low": row[3],
                            "close": row[4],
                            "volume": row[5],
                        },
                        sort_keys=True,
                    )
                    + "\n"
                )
    audit["dest_1m_sha256"] = hashlib.sha256(dest.read_bytes()).hexdigest()
    audit["dest_1m_bytes"] = dest.stat().st_size
    audit["identical_to_frozen_1h"] = all(
        v["ohlc_mismatched_bars"] == 0
        and v["bars_missing_after_aggregation"] == 0
        and v["bars_extra_after_aggregation"] == 0
        for v in audit["symbols"].values()
    )
    AUDIT.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"[fetch] wrote {dest} ({audit['dest_1m_bytes']} bytes)")
    print(f"[fetch] 1m source aggregates to the frozen 1h bars: {audit['identical_to_frozen_1h']}")
    print(f"[fetch] wrote {AUDIT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
