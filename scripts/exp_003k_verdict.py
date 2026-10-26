"""exp_003k_verdict — Stage B: one read of the holdout, and the verdict the rule gives.

    ./.venv/Scripts/python.exe scripts/exp_003k_verdict.py

It reads the two OOS runs (baseline and the strategy Stage A selected), rebuilds every
number from the ledgers, and applies the five conditions ``PRE_REGISTRATION.md`` §4 fixed
before the holdout was opened:

1. positive net expectancy;
2. bootstrap 95 % interval of the per-trade mean with a **lower bound above zero**
   (10 000 rounds, seed ``20261020``);
3. positive expectancy in **both halves** of the holdout, split by close time;
4. reference gross per trade above the 1.29 USDT cost floor;
5. OOS expectancy above the baseline's on the same window.

Anything less is ``REJECT``; fewer than 30 closes is ``INSUFFICIENT_SAMPLE``. The script
cannot return ``EVIDENCE_OF_EDGE`` on a subset of the conditions, and it does not tune
anything: it reports the number it found.

It also writes the CURRENT vs CANDIDATE comparison on both windows, because a candidate
that only wins on the holdout is a coincidence, not an edge.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics as stats
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "ai-bots" / "EXP-003K-CANDIDATE-001"
BOOTSTRAP_ROUNDS = 10_000
BOOTSTRAP_SEED = 20261020
COST_FLOOR_USDT = 1.29
MIN_CLOSES = 30
BASELINE = "ema_crossover"


def _utc(ms: int) -> str:
    return datetime.fromtimestamp(int(ms) / 1000.0, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _entries(strategy_id: str, partition: str) -> list[dict[str, Any]]:
    path = OUT / "runs" / strategy_id / "real" / partition / "ledger.jsonl"
    return [
        json.loads(line)["entry"]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _round(value: float | None, digits: int = 6) -> float | None:
    return None if value is None else round(float(value), digits)


def _bootstrap(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "mean": None, "ci95": None, "rounds": BOOTSTRAP_ROUNDS, "seed": BOOTSTRAP_SEED}
    rng = random.Random(BOOTSTRAP_SEED)
    n = len(values)
    means = sorted(stats.fmean(rng.choices(values, k=n)) for _ in range(BOOTSTRAP_ROUNDS))
    return {
        "n": n,
        "mean": _round(stats.fmean(values)),
        "ci95": [_round(means[int(0.025 * BOOTSTRAP_ROUNDS)]), _round(means[int(0.975 * BOOTSTRAP_ROUNDS) - 1])],
        "rounds": BOOTSTRAP_ROUNDS,
        "seed": BOOTSTRAP_SEED,
    }


def _metrics(strategy_id: str, partition: str) -> dict[str, Any]:
    entries = _entries(strategy_id, partition)
    closes = [row for row in entries if row.get("kind") == "CLOSE"]
    decisions = [row for row in entries if row.get("kind") == "DECISION"]
    ordered = sorted(closes, key=lambda row: int(row["ts_ms"]))
    nets = [float(row["pnl_net_usdt"]) for row in ordered]
    half = len(ordered) // 2
    reference = sum(float(row["reference_gross_pnl_usdt"]) for row in ordered)
    execution = sum(float(row["execution_cost_usdt"]) for row in ordered)
    commissions = sum(float(row["commissions_usdt"]) for row in ordered)
    net = sum(nets)
    by_asset: dict[str, dict[str, Any]] = {}
    for row in ordered:
        symbol = str(row["symbol"])
        block = by_asset.setdefault(symbol, {"closes": 0, "net_usdt": 0.0, "wins": 0})
        block["closes"] += 1
        block["net_usdt"] += float(row["pnl_net_usdt"])
        block["wins"] += 1 if float(row["pnl_net_usdt"]) > 0 else 0
    for block in by_asset.values():
        block["net_usdt"] = _round(block["net_usdt"])
        block["win_rate_pct"] = _round(100.0 * block["wins"] / block["closes"], 4)
        block.pop("wins")
    reasons: dict[str, int] = {}
    for row in ordered:
        reasons[str(row.get("exit_reason"))] = reasons.get(str(row.get("exit_reason")), 0) + 1
    durations = [(int(row["ts_ms"]) - int(row["entry_quote_ts_ms"])) / 60_000.0 for row in ordered]
    summary = json.loads(
        (OUT / "runs" / strategy_id / "real" / partition / "SUMMARY.json").read_text(encoding="utf-8")
    )
    return {
        "strategy_id": strategy_id,
        "partition": partition,
        "decisions": len(decisions),
        "directional": sum(1 for row in decisions if row.get("intent") not in (None, "NONE")),
        "fills": sum(1 for row in entries if row.get("kind") == "FILL"),
        "closes": len(ordered),
        "open_at_end": len(summary.get("open_positions_at_end") or {}),
        "exit_reasons": reasons,
        "reference_gross_usdt": _round(reference),
        "execution_cost_usdt": _round(execution),
        "commissions_usdt": _round(commissions),
        "net_usdt": _round(net),
        "expectancy_usdt": _round(net / len(ordered)) if ordered else None,
        "reference_gross_per_trade_usdt": _round(reference / len(ordered)) if ordered else None,
        "cost_per_trade_usdt": _round((execution + commissions) / len(ordered)) if ordered else None,
        "win_rate_pct": _round(100.0 * sum(1 for value in nets if value > 0) / len(ordered), 4)
        if ordered
        else None,
        "mean_holding_minutes": _round(stats.fmean(durations), 4) if durations else None,
        "median_holding_minutes": _round(stats.median(durations), 4) if durations else None,
        "bootstrap": _bootstrap(nets),
        "first_half_expectancy_usdt": _round(stats.fmean(nets[:half])) if half else None,
        "second_half_expectancy_usdt": _round(stats.fmean(nets[half:])) if half else None,
        "first_close_utc": _utc(int(ordered[0]["ts_ms"])) if ordered else None,
        "last_close_utc": _utc(int(ordered[-1]["ts_ms"])) if ordered else None,
        "drawdown_pct": summary.get("drawdown_pct"),
        "by_asset": by_asset,
        "ledger": f"runs/{strategy_id}/real/{partition}/ledger.jsonl",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)
    out = Path(args.out)

    selection_path = out / "SELECTION.json"
    if not selection_path.exists():
        print("[003k-verdict] BLOCKED — no SELECTION.json: Stage A has not been decided", file=sys.stderr)
        return 2
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    candidate_id = selection.get("selected")
    if not candidate_id:
        payload = {
            "schema_version": "AI_BOTS_003K_VERDICT_V1",
            "generated_at_utc": _utc(int(datetime.now(tz=UTC).timestamp() * 1000)),
            "candidate": None,
            "baseline": BASELINE,
            "status": "BLOCKED",
            "blocked_reason": selection.get("blocked_reason") or "NO_VIABLE_CANDIDATE",
            "conditions": None,
            "note": (
                "Stage A produced no admissible candidate, so the holdout was not opened for a "
                "second strategy. Reporting a verdict would require inventing one."
            ),
        }
        (out / "VERDICT.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
        )
        (out / "VERDICT.md").write_text(
            "# 003K — Veredicto\n\n`BLOCKED / NO_VIABLE_CANDIDATE`: ninguna familia superó las "
            "tres puertas de la etapa A. El OOS no se abrió para una segunda estrategia.\n",
            encoding="utf-8",
            newline="\n",
        )
        print("[003k-verdict] BLOCKED — no candidate to confirm", flush=True)
        return 0

    research = {sid: _metrics(sid, "research") for sid in (BASELINE, candidate_id)}
    oos = {sid: _metrics(sid, "oos") for sid in (BASELINE, candidate_id)}
    candidate = oos[candidate_id]
    baseline = oos[BASELINE]
    ci = candidate["bootstrap"]["ci95"] or [None, None]
    conditions = {
        "positive_expectancy": (candidate["expectancy_usdt"] or 0.0) > 0,
        "ci_lower_above_zero": ci[0] is not None and ci[0] > 0,
        "positive_in_both_halves": (candidate["first_half_expectancy_usdt"] or 0.0) > 0
        and (candidate["second_half_expectancy_usdt"] or 0.0) > 0,
        "gross_above_cost_floor": (candidate["reference_gross_per_trade_usdt"] or 0.0) > COST_FLOOR_USDT,
        "beats_baseline": (candidate["expectancy_usdt"] or 0.0) > (baseline["expectancy_usdt"] or 0.0),
    }
    if candidate["closes"] < MIN_CLOSES:
        status = "INSUFFICIENT_SAMPLE"
    elif all(conditions.values()):
        status = "EVIDENCE_OF_EDGE"
    else:
        status = "REJECT"
    payload = {
        "schema_version": "AI_BOTS_003K_VERDICT_V1",
        "generated_at_utc": _utc(int(datetime.now(tz=UTC).timestamp() * 1000)),
        "candidate": candidate_id,
        "baseline": BASELINE,
        "status": status,
        "rule": {
            "min_closes": MIN_CLOSES,
            "cost_floor_gross_per_trade_usdt": COST_FLOOR_USDT,
            "bootstrap_rounds": BOOTSTRAP_ROUNDS,
            "bootstrap_seed": BOOTSTRAP_SEED,
            "source": "PRE_REGISTRATION.md section 4 (Stage B), frozen before the holdout",
        },
        "conditions": conditions,
        "failed_conditions": [key for key, ok in conditions.items() if not ok],
        "research": research,
        "oos": oos,
        "note": (
            "A positive status here is permission for a confirmation experiment on new data, "
            "not a certification and not authorisation for live trading."
            if status == "EVIDENCE_OF_EDGE"
            else "The candidate did not clear every pre-registered condition; nothing is promoted."
        ),
    }
    (out / "VERDICT.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )

    lines = [
        "# 003K — CURRENT vs CANDIDATE",
        "",
        "Todas las cifras salen de los ledgers; ningún número se copia de un resumen.",
        "",
        "| ventana | estrategia | cierres | bruto/op | coste/op | neto | expectativa | IC95% | acierto % |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |",
    ]
    for partition, block in (("research", research), ("oos", oos)):
        for strategy_id, metrics in block.items():
            ci_values = metrics["bootstrap"]["ci95"] or ["n/a", "n/a"]
            lines.append(
                f"| {partition} | `{strategy_id}` | {metrics['closes']} | "
                f"{metrics['reference_gross_per_trade_usdt']} | {metrics['cost_per_trade_usdt']} | "
                f"{metrics['net_usdt']} | {metrics['expectancy_usdt']} | "
                f"[{ci_values[0]}, {ci_values[1]}] | {metrics['win_rate_pct']} |"
            )
    lines += [
        "",
        f"## Veredicto: `{status}`",
        "",
        "| condición pre-registrada | resultado |",
        "| --- | --- |",
    ]
    for key, ok in conditions.items():
        lines.append(f"| {key} | {'cumple' if ok else 'NO cumple'} |")
    lines += [
        "",
        f"Mitades del OOS: {candidate['first_half_expectancy_usdt']} / "
        f"{candidate['second_half_expectancy_usdt']} USDT por operación.",
        "",
        f"Salidas: {candidate['exit_reasons']} · posiciones abiertas al cierre: {candidate['open_at_end']}.",
        "",
        payload["note"],
    ]
    (out / "COMPARISON.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    (out / "VERDICT.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(
        f"[003k-verdict] {candidate_id}: status={status} oos_exp={candidate['expectancy_usdt']} "
        f"ci={candidate['bootstrap']['ci95']} failed={payload['failed_conditions']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
