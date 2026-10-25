"""exp_003k_select — apply the pre-registered Stage A rule, mechanically.

    ./.venv/Scripts/python.exe scripts/exp_003k_select.py

The rule lives in ``PRE_REGISTRATION.md`` §4 and is copied here as code so that nobody
re-reads a table and picks the strategy that looks best. In order:

1. ``closes >= 60`` on the research window;
2. ``expectancy_net > ema_crossover + 0.25`` USDT per trade — an improvement, not a tie;
3. ``reference_gross_per_trade > 1.29`` USDT — the cost floor 003J measured;
4. among those that pass, the highest net expectancy. Ties break on the cost floor then on
   the strategy id, so the outcome is deterministic.

If nobody passes, the answer is ``BLOCKED / NO_VIABLE_CANDIDATE``. The thresholds are not
adjusted afterwards: a different threshold is a different experiment.

This script reads the metrics the runner already wrote and refuses to proceed if a metric
disagrees with its own ledger.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "ai-bots" / "EXP-003K-CANDIDATE-001"

MIN_CLOSES = 60
MIN_IMPROVEMENT_USDT = 0.25
COST_FLOOR_USDT = 1.29
BASELINE = "ema_crossover"


def _utc(ms: int) -> str:
    return datetime.fromtimestamp(int(ms) / 1000.0, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _closes(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "ledger.jsonl"
    return [
        json.loads(line)["entry"]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and json.loads(line)["entry"].get("kind") == "CLOSE"
    ]


def _row(strategy_id: str, partition: str) -> dict[str, Any]:
    run_dir = OUT / "runs" / strategy_id / "real" / partition
    meta = json.loads((run_dir / "RUN_META.json").read_text(encoding="utf-8"))
    closes = _closes(run_dir)
    n = len(closes)
    reference = sum(float(row["reference_gross_pnl_usdt"]) for row in closes)
    commissions = sum(float(row["commissions_usdt"]) for row in closes)
    execution = sum(float(row["execution_cost_usdt"]) for row in closes)
    net = sum(float(row["pnl_net_usdt"]) for row in closes)
    summary = json.loads((run_dir / "SUMMARY.json").read_text(encoding="utf-8"))
    summary_net = float(summary.get("net_realised_usdt") or 0.0)
    return {
        "strategy_id": strategy_id,
        "partition": partition,
        "closes": n,
        "reference_gross_usdt": round(reference, 8),
        "execution_usdt": round(execution, 8),
        "commissions_usdt": round(commissions, 8),
        "net_usdt": round(net, 8),
        "expectancy_usdt": round(net / n, 8) if n else None,
        "reference_gross_per_trade_usdt": round(reference / n, 8) if n else None,
        "cost_per_trade_usdt": round((execution + commissions) / n, 8) if n else None,
        "summary_net_usdt": round(summary_net, 8),
        "metrics_agree_with_ledger": abs(summary_net - net) <= 1e-3,
        "open_at_end": len(summary.get("open_positions_at_end") or {}),
        "live_orders": meta.get("live_orders"),
        "ledger_sha256": meta.get("ledger", {}).get("sha256"),
        "strategy_version": (meta.get("provider_counters") or {}).get("strategy_version"),
        "commit": meta.get("commit"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)

    out = Path(args.out)
    strategies = sorted(
        path.name for path in (out / "runs").iterdir() if (path / "real" / "research").is_dir()
    )
    if not strategies:
        print("[003k-select] BLOCKED — no research runs found", file=sys.stderr)
        return 2
    rows = [_row(strategy_id, "research") for strategy_id in strategies]
    baseline = next((row for row in rows if row["strategy_id"] == BASELINE), None)
    if baseline is None or baseline["expectancy_usdt"] is None:
        print(f"[003k-select] BLOCKED — baseline {BASELINE} has no research result", file=sys.stderr)
        return 2

    for row in rows:
        row["gates"] = {
            "enough_closes": row["closes"] >= MIN_CLOSES,
            "enough_improvement": (
                row["expectancy_usdt"] is not None
                and row["expectancy_usdt"] > baseline["expectancy_usdt"] + MIN_IMPROVEMENT_USDT
            ),
            "above_cost_floor": (
                row["reference_gross_per_trade_usdt"] is not None
                and row["reference_gross_per_trade_usdt"] > COST_FLOOR_USDT
            ),
            "metrics_agree_with_ledger": row["metrics_agree_with_ledger"],
        }
        row["eligible"] = (
            row["strategy_id"] != BASELINE and all(row["gates"].values())
        )

    eligible = [row for row in rows if row["eligible"]]
    eligible.sort(
        key=lambda row: (
            -float(row["expectancy_usdt"]),
            -float(row["reference_gross_per_trade_usdt"]),
            row["strategy_id"],
        )
    )
    chosen = eligible[0]["strategy_id"] if eligible else None
    payload = {
        "schema_version": "AI_BOTS_003K_SELECTION_V1",
        "generated_at_utc": _utc(int(datetime.now(tz=UTC).timestamp() * 1000)),
        "rule": {
            "min_closes": MIN_CLOSES,
            "min_improvement_usdt": MIN_IMPROVEMENT_USDT,
            "cost_floor_gross_per_trade_usdt": COST_FLOOR_USDT,
            "baseline": BASELINE,
            "baseline_expectancy_usdt": baseline["expectancy_usdt"],
            "source": "PRE_REGISTRATION.md section 4, frozen before the first run",
        },
        "candidates": rows,
        "selected": chosen,
        "status": "SELECTED" if chosen else "BLOCKED",
        "blocked_reason": None if chosen else "NO_VIABLE_CANDIDATE",
        "note": (
            "Selection uses the research window only. The OOS window is opened afterwards, "
            "once, for the baseline and the selected strategy."
            if chosen
            else "No candidate passed all three gates on the research window; the threshold "
            "is not relaxed to produce one."
        ),
    }
    (out / "SELECTION.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )

    table = ["# 003K — Selección (etapa A, solo research)", ""]
    table.append("| estrategia | cierres | bruto/op | coste/op | neto | expectativa | gates | elegible |")
    table.append("| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |")
    for row in rows:
        gates = ", ".join(f"{key}={'ok' if value else 'no'}" for key, value in row["gates"].items())
        table.append(
            f"| `{row['strategy_id']}` | {row['closes']} | {row['reference_gross_per_trade_usdt']} | "
            f"{row['cost_per_trade_usdt']} | {row['net_usdt']} | {row['expectancy_usdt']} | "
            f"{gates} | {'sí' if row['eligible'] else 'no'} |"
        )
    table += [
        "",
        f"**Seleccionada:** {('`' + chosen + '`') if chosen else '—'} · **Estado:** `{payload['status']}`",
        "",
        payload["note"],
    ]
    (out / "SELECTION.md").write_text("\n".join(table) + "\n", encoding="utf-8", newline="\n")
    print(f"[003k-select] status={payload['status']} selected={chosen}", flush=True)
    for row in rows:
        print(
            f"[003k-select]   {row['strategy_id']:<15} closes={row['closes']:<4} "
            f"ref/op={row['reference_gross_per_trade_usdt']} exp={row['expectancy_usdt']} "
            f"eligible={row['eligible']}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
