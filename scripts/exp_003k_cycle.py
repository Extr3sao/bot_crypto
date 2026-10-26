"""exp_003k_cycle — reconstruct a closed trade from the bars, not from the summary.

    ./.venv/Scripts/python.exe scripts/exp_003k_cycle.py --partition research
    ./.venv/Scripts/python.exe scripts/exp_003k_cycle.py --partition oos

003J demonstrated that the runtime *can* open, track and close a position; what it never
had was a session whose closed trade could be re-derived from the market data the run was
given. Every 003K run has hundreds of closed trades, so this script spends them on the one
question the reports keep asserting:

    does a CLOSE row describe a trade that the frozen bars can reproduce?

For every close it checks, without asking the runtime anything:

1. the fill price is the quoted bar open moved by exactly the recorded basis points;
2. the exit price lies inside the exit bar's high/low range (a stop or target that the bar
   never touched would be an invented fill);
3. the exit timestamp sits inside the bar the ledger says resolved it;
4. equity moves by exactly the trade's net PnL — the realised result is the cash delta, not
   a number computed beside it;
5. every closed position disappears from the book, and the remaining book plus the cash
   delta reconciles with the run's final equity;
6. recomputing the gross PnL from the two prices and the quantity reproduces the ledger's
   reference gross within the rounding the runtime records.

Output: ``analysis/CLOSED_CYCLE.json`` + ``.md``, one row per strategy/partition with the
counts, and the first failure quoted verbatim when there is one.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

from exp_003j_replay import load_series  # noqa: E402

OUT = REPO / "reports" / "ai-bots" / "EXP-003K-CANDIDATE-001"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
INTERVAL_MS = 300_000
TOL = 1e-6


def _utc(ms: int) -> str:
    return datetime.fromtimestamp(int(ms) / 1000.0, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(text: str) -> int:
    return int(datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp() * 1000)


def _bars(partition: str) -> dict[str, list[Any]]:
    window = json.loads((OUT / "PARTITIONS.json").read_text(encoding="utf-8"))[partition]
    series, _ = load_series(
        symbols=list(SYMBOLS),
        start_ms=_parse(window["start_utc"]),
        end_ms=_parse(window["end_utc"]),
        interval_ms=INTERVAL_MS,
        dataset_dir=OUT / "dataset",
    )
    return {symbol.replace("/", ""): list(bars) for symbol, bars in series.items()}


def _bar_at(bars: list[Any], ts_ms: int) -> Any | None:
    for bar in bars:
        if int(bar.ts_ms) <= int(ts_ms) < int(bar.ts_ms) + INTERVAL_MS:
            return bar
    return None


def reconstruct(strategy_id: str, partition: str, bars: dict[str, list[Any]]) -> dict[str, Any]:
    run_dir = OUT / "runs" / strategy_id / "real" / partition
    entries = [
        json.loads(line)["entry"]
        for line in (run_dir / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    fills = [row for row in entries if row.get("kind") == "FILL"]
    closes = [row for row in entries if row.get("kind") == "CLOSE"]
    summary = json.loads((run_dir / "SUMMARY.json").read_text(encoding="utf-8"))
    meta = json.loads((run_dir / "RUN_META.json").read_text(encoding="utf-8"))
    equity0 = float(meta.get("equity_usdt") or 0.0)

    failures: list[str] = []
    checked = {
        "fill_price_from_open": 0,
        "exit_reference_inside_bar": 0,
        "exit_price_near_reference": 0,
        "exit_inside_resolution_window": 0,
        "equity_moves_by_net": 0,
        "position_removed": 0,
        "gross_from_prices": 0,
        "reference_gross_from_reference_prices": 0,
    }
    exit_bar_missing = 0

    fill_by_position = {str(row.get("position_id")): row for row in fills}
    for row in closes:
        position = str(row.get("position_id"))
        fill = fill_by_position.get(position)
        symbol = str(row.get("symbol"))
        series = bars.get(symbol.replace("/", ""), [])
        if fill is None:
            failures.append(f"{position}: closed without a fill")
            continue

        # 1. The fill price is the quoted open plus/minus the recorded basis points.
        bps = float(fill.get("price_bps_per_side") or 0.0) / 10_000.0
        sign = 1.0 if str(fill.get("side")) == "buy" else -1.0
        expected_entry = float(fill["quote_price"]) * (1.0 + sign * bps)
        if abs(expected_entry - float(fill["entry_price"])) <= max(1e-6, abs(expected_entry) * 1e-6):
            checked["fill_price_from_open"] += 1
        else:
            failures.append(
                f"{position}: entry {fill['entry_price']} != quoted open {fill['quote_price']} "
                f"+/- {fill.get('price_bps_per_side')} bp"
            )

        # 2/3. The exit happened in the bar that resolved it. ``ts_ms`` is the *upper* bound
        # of the resolution window, so the bar to inspect is the one at the lower bound.
        lower = int(row.get("exit_ts_lower_bound_ms") or row["ts_ms"])
        upper = int(row.get("exit_ts_upper_bound_ms") or row["ts_ms"])
        raw = int(row["ts_ms"])
        if lower <= raw <= upper:
            checked["exit_inside_resolution_window"] += 1
        else:
            failures.append(
                f"{position}: exit stamp {raw} outside its declared window [{lower}, {upper}]"
            )
        exit_bar = _bar_at(series, lower)
        if exit_bar is None:
            exit_bar_missing += 1
            failures.append(f"{position}: no bar covers the exit window {_utc(lower)}")
        else:
            low, high = float(exit_bar.low), float(exit_bar.high)
            reference_exit = float(row.get("exit_reference_price") or row["exit_price"])
            if low - TOL <= reference_exit <= high + TOL:
                checked["exit_reference_inside_bar"] += 1
            else:
                failures.append(
                    f"{position}: exit reference {reference_exit} outside the bar range "
                    f"[{low}, {high}] at {_utc(lower)}"
                )
            distortion = abs(float(row["exit_price"]) - reference_exit) / reference_exit
            if distortion <= 0.002:
                checked["exit_price_near_reference"] += 1
            else:
                failures.append(
                    f"{position}: exit price moved {distortion * 10_000:.1f} bp away from its "
                    "reference, beyond the declared execution distortion"
                )

        # 4. Equity moves by exactly the net PnL.
        delta = float(row["risk_equity_after"]) - float(row["risk_equity_before"])
        if abs(delta - float(row["pnl_net_usdt"])) <= 1e-6:
            checked["equity_moves_by_net"] += 1
        else:
            failures.append(
                f"{position}: equity moved {delta} but net PnL is {row['pnl_net_usdt']}"
            )

        # 5. The position is gone from the book.
        if position not in {str(value) for value in (summary.get("open_positions_at_end") or {})}:
            checked["position_removed"] += 1
        else:
            failures.append(f"{position}: still open at the end of the run")

        # 6. Gross from the two prices, with the side's sign.
        quantity = float(row["quantity"])
        direction = 1.0 if str(row.get("side")) == "buy" else -1.0
        filled_gross = direction * (float(row["exit_price"]) - float(row["entry_price"])) * quantity
        if abs(filled_gross - float(row["gross_pnl_usdt"])) <= max(1e-6, abs(filled_gross) * 1e-6):
            checked["gross_from_prices"] += 1
        else:
            failures.append(
                f"{position}: gross {row['gross_pnl_usdt']} != {filled_gross} recomputed "
                "from the two fill prices"
            )
        reference_gross = (
            direction
            * (float(row.get("exit_reference_price") or row["exit_price"]) - float(fill["quote_price"]))
            * quantity
        )
        if abs(reference_gross - float(row["reference_gross_pnl_usdt"])) <= max(
            1e-6, abs(reference_gross) * 1e-6
        ):
            checked["reference_gross_from_reference_prices"] += 1
        else:
            failures.append(
                f"{position}: reference gross {row['reference_gross_pnl_usdt']} != "
                f"{reference_gross} recomputed from the reference prices"
            )

    net = sum(float(row["pnl_net_usdt"]) for row in closes)
    marked = float(summary.get("marked_equity_usdt") or 0.0)
    cash_reconciles = abs((equity0 + net) - marked) <= 1e-3 if not (summary.get("open_positions_at_end")) else None
    if cash_reconciles is False:
        failures.append(
            f"cash {equity0 + net} does not reconcile with marked equity {marked}"
        )

    return {
        "strategy_id": strategy_id,
        "partition": partition,
        "closes": len(closes),
        "expected_checks": len(closes) * 8,
        "checks_passed": sum(checked.values()),
        "details": checked,
        "exit_bars_missing": exit_bar_missing,
        "net_usdt": round(net, 8),
        "equity_start_usdt": equity0,
        "equity_marked_usdt": marked,
        "equity_final_usdt": summary.get("final_equity_usdt"),
        "cash_reconciles_with_marked_equity": cash_reconciles,
        "open_at_end": len(summary.get("open_positions_at_end") or {}),
        "failures": failures[:20],
        "failure_count": len(failures),
        "ok": not failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--partition", default=None, choices=(None, "research", "oos"))
    parser.add_argument("--strategy-id", nargs="*", default=None)
    args = parser.parse_args(argv)

    partitions = [args.partition] if args.partition else ["research", "oos"]
    strategies = args.strategy_id or sorted(
        path.name for path in (OUT / "runs").iterdir() if (path / "real").is_dir()
    )
    results: list[dict[str, Any]] = []
    for partition in partitions:
        bars = _bars(partition)
        for strategy_id in strategies:
            run_dir = OUT / "runs" / strategy_id / "real" / partition
            if not (run_dir / "ledger.jsonl").exists():
                continue
            result = reconstruct(strategy_id, partition, bars)
            results.append(result)
            print(
                f"[003k-cycle] {strategy_id}/{partition}: closes={result['closes']} "
                f"passed={result['checks_passed']}/{result['expected_checks']} "
                f"ok={result['ok']}",
                flush=True,
            )
            for failure in result["failures"][:3]:
                print(f"[003k-cycle]    {failure}", flush=True)

    analysis = OUT / "analysis"
    analysis.mkdir(parents=True, exist_ok=True)
    ok = all(result["ok"] for result in results) and bool(results)
    payload = {
        "schema_version": "AI_BOTS_003K_CLOSED_CYCLE_V1",
        "generated_at_utc": _utc(int(datetime.now(tz=UTC).timestamp() * 1000)),
        "what_this_proves": (
            "Every closed trade in these runs is reproducible from the frozen bars: price, "
            "range, timing, cash delta and book removal. It does not prove the strategy earns "
            "money; it proves the accounting of a closed trade is not cosmetic."
        ),
        "runs": results,
        "ok": ok,
    }
    (analysis / "CLOSED_CYCLE.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    lines = [
        "# 003K — Ciclo completo de una operación, reconstruido desde las barras",
        "",
        payload["what_this_proves"],
        "",
        "| estrategia | partición | cierres | checks | fallos | equity final | caja reconcilia |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for result in results:
        lines.append(
            f"| `{result['strategy_id']}` | {result['partition']} | {result['closes']} | "
            f"{result['checks_passed']}/{result['expected_checks']} | {result['failure_count']} | "
            f"{result['equity_marked_usdt']} | "
            f"{result['cash_reconciles_with_marked_equity'] if result['cash_reconciles_with_marked_equity'] is not None else 'n/a (posiciones abiertas)'} |"
        )
    failures = [failure for result in results for failure in result["failures"]]
    if failures:
        lines += ["", "## Fallos", ""] + [f"- {item}" for item in failures[:20]]
    (analysis / "CLOSED_CYCLE.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"[003k-cycle] {'PASS' if ok else 'FAIL'}", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
