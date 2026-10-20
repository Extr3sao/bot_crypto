"""exp_003k_run — run one 003K strategy through the production lane on frozen bars.

    ./.venv/Scripts/python.exe scripts/exp_003k_run.py --partition research \
        --strategy-id ema_crossover momentum breakout
    ./.venv/Scripts/python.exe scripts/exp_003k_run.py --partition oos \
        --strategy-id ema_crossover momentum

This script owns no signal logic, no risk policy and no accounting. It loads the frozen
003K dataset, hands the bars to ``VisionLane`` exactly as 003J did, and lets the real
``RiskManager`` / ``PaperBroker`` / exit policy run unchanged. The strategy is selected by
``strategy_id`` through the adapter in ``trading_bot.vision.signal_sources``.

The partitions come from ``PARTITIONS.json``, which was frozen before the first run. The
strategy list is the caller's, not a default: a run that silently picked a candidate would
be a selection nobody recorded.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics as stats
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

from exp_003j_replay import _parse_utc, _utc, run_arm  # noqa: E402

from trading_bot.vision.signal_sources import (  # noqa: E402
    STRATEGY_SPECS,
    SUPPORTED_STRATEGIES,
)

OUT = REPO / "reports" / "ai-bots" / "EXP-003K-CANDIDATE-001"
DATASET = OUT / "dataset"
RUNS = OUT / "runs"


def _metrics(run_dir: Path) -> dict[str, Any]:
    """Aggregate one run's CLOSE rows. Costs are read, never recomputed."""

    entries = [
        json.loads(line)["entry"]
        for line in (run_dir / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    closes = [row for row in entries if row.get("kind") == "CLOSE"]
    summary = json.loads((run_dir / "SUMMARY.json").read_text(encoding="utf-8"))
    meta = json.loads((run_dir / "RUN_META.json").read_text(encoding="utf-8"))
    decisions = [row for row in entries if row.get("kind") == "DECISION"]
    outcomes = [row for row in entries if row.get("kind") == "DECISION_OUTCOME"]

    def col(name: str) -> list[float]:
        return [float(row[name]) for row in closes]

    by_reason: dict[str, int] = {}
    for row in closes:
        by_reason[str(row.get("exit_reason"))] = by_reason.get(str(row.get("exit_reason")), 0) + 1
    by_asset: dict[str, dict[str, float]] = {}
    for row in closes:
        symbol = str(row.get("symbol"))
        block = by_asset.setdefault(
            symbol, {"closes": 0, "net": 0.0, "reference_gross": 0.0, "commissions": 0.0}
        )
        block["closes"] += 1
        block["net"] += float(row["pnl_net_usdt"])
        block["reference_gross"] += float(row["reference_gross_pnl_usdt"])
        block["commissions"] += float(row["commissions_usdt"])

    holdings = [
        (int(row["ts_ms"]) - int(row["entry_quote_ts_ms"])) / 60_000.0 for row in closes
    ]
    net = sum(col("pnl_net_usdt"))
    reference = sum(col("reference_gross_pnl_usdt"))
    execution = sum(col("execution_cost_usdt"))
    commissions = sum(col("commissions_usdt"))
    n = len(closes)
    return {
        "strategy_id": meta.get("strategy_id"),
        "partition": run_dir.name,
        "decisions": len(decisions),
        "directional": sum(1 for row in decisions if row.get("intent") not in (None, "NONE")),
        "risk_outcomes": len(outcomes),
        "fills": int(summary.get("fills") or 0),
        "closes": n,
        "open_at_end": len(summary.get("open_positions_at_end") or {}),
        "exit_reasons": by_reason,
        "reference_gross_usdt": round(reference, 8),
        "execution_cost_usdt": round(execution, 8),
        "commissions_usdt": round(commissions, 8),
        "net_pnl_usdt": round(net, 8),
        "expectancy_usdt": round(net / n, 8) if n else None,
        "reference_gross_per_trade_usdt": round(reference / n, 8) if n else None,
        "cost_per_trade_usdt": round((execution + commissions) / n, 8) if n else None,
        "win_rate": round(sum(1 for value in col("pnl_net_usdt") if value > 0) / n, 6)
        if n
        else None,
        "holding_minutes_mean": round(stats.mean(holdings), 4) if holdings else None,
        "holding_minutes_median": round(stats.median(holdings), 4) if holdings else None,
        "drawdown_pct": summary.get("drawdown_pct"),
        "final_equity_usdt": (summary.get("accounting") or {}).get("marked_equity_usdt"),
        "by_asset": by_asset,
        "counters": summary.get("counters"),
        "live_orders": meta.get("live_orders"),
        "mode": summary.get("mode"),
        "ledger_sha256": meta.get("ledger", {}).get("sha256"),
        "window_start_utc": meta.get("window_start_utc"),
        "window_end_utc": meta.get("window_end_utc"),
        "commit": meta.get("commit"),
        "decision_every_bars": meta.get("decision_every_bars"),
        "window_bars": meta.get("window_bars"),
        "strategy_version": (meta.get("provider_counters") or {}).get("strategy_version"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--partition", required=True, choices=("research", "oos"))
    parser.add_argument("--strategy-id", nargs="+", required=True, choices=SUPPORTED_STRATEGIES)
    parser.add_argument("--symbols", nargs="*", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    parser.add_argument("--timeframe", default="5m")
    parser.add_argument("--window-bars", type=int, default=60)
    parser.add_argument("--decision-every", type=int, default=24)
    parser.add_argument("--equity", type=float, default=10_000.0)
    parser.add_argument("--out", default=str(RUNS))
    args = parser.parse_args(argv)

    partitions = json.loads((OUT / "PARTITIONS.json").read_text(encoding="utf-8"))
    window = partitions[args.partition]
    start = _parse_utc(window["start_utc"])
    end = _parse_utc(window["end_utc"])
    out = Path(args.out)
    rows: list[dict[str, Any]] = []
    for strategy_id in args.strategy_id:
        spec = STRATEGY_SPECS[strategy_id]
        print(
            f"[003k] {strategy_id} ({spec.family_name}) {args.partition} "
            f"{_utc(start)} -> {_utc(end)}",
            flush=True,
        )
        result = run_arm(
            arm="real",
            partition=args.partition,
            symbols=list(args.symbols),
            start_ms=start,
            end_ms=end,
            timeframe=args.timeframe,
            window_bars=max(args.window_bars, spec.min_candles),
            decision_every=args.decision_every,
            equity=args.equity,
            # One directory per strategy: the partition name stays a partition name, and a
            # second family cannot quietly overwrite the first one's ledger.
            out_dir=out / strategy_id,
            dataset_dir=DATASET,
            strategy_id=strategy_id,
            book_prefix=f"paper-003k-{strategy_id}",
            run_schema="AI_BOTS_003K_RUN_V1",
            experiment="EXP-003K-CANDIDATE-001",
        )
        run_dir = Path(result["dir"])
        metrics = _metrics(run_dir)
        metrics["strategy_name"] = spec.family_name
        metrics["classification"] = spec.classification
        metrics["min_candles"] = spec.min_candles
        metrics["generated_at_utc"] = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        (run_dir / "METRICS.json").write_text(
            json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
        )
        rows.append(metrics)
        print(
            f"[003k]   closes={metrics['closes']} net={metrics['net_pnl_usdt']} "
            f"expectancy={metrics['expectancy_usdt']} ref/trade="
            f"{metrics['reference_gross_per_trade_usdt']}",
            flush=True,
        )

    table = OUT / f"METRICS_{args.partition.upper()}.csv"
    if rows:
        fields = [
            key
            for key, value in rows[0].items()
            if not isinstance(value, (dict, list)) and value is not None
        ]
        with table.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({key: row.get(key) for key in fields})
    print(f"[003k] wrote {table.relative_to(REPO)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
