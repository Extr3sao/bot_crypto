"""WP-TDM-06 §D — profitability diagnosis on real public data.

Replays the authoritative PAPER runtime (``AutonomousPaperRuntime`` + the six
production ``AlphaFamilies`` + ``RiskManager`` + ``PaperBroker``) over freshly
fetched Binance 5m candles and measures, from the persisted traces alone:

* how often a signal becomes a proposal (frequency per day);
* gross / cost / net edge per proposal, and how many could ever pay the cost;
* the distribution of ``NO_TRADE`` reasons, split into infrastructure defects,
  signals without edge and legitimate risk blocks.

Nothing here changes the cost model, the risk limits or the admission ledger:
the counterfactuals are labelled and computed from the same measured numbers.

    PYTHONPATH=src python scripts/tdm06_profitability.py --days 3 \
        --assets BTC,ETH,SOL --out reports/trading-decision-monitor/WP-TDM-06/profitability.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

DATA_DIR = REPO_ROOT / ".tmp" / "tdm06-data"
BAR_MS = 5 * 60 * 1000


# ---------------------------------------------------------------------------
# market data (public REST, no credentials, no orders)
# ---------------------------------------------------------------------------


def fetch_bars(symbol: str, days: int, timeframe: str = "5m") -> tuple[list[list[float]], dict[str, Any]]:
    import ccxt

    exchange = ccxt.binance({"enableRateLimit": True, "timeout": 20_000})
    end = exchange.milliseconds()
    start = end - days * 24 * 60 * 60 * 1000
    rows: list[list[float]] = []
    cursor = start
    while True:
        batch = exchange.fetch_ohlcv(symbol, timeframe, since=cursor, limit=1000)
        if not batch:
            break
        rows.extend(batch)
        cursor = int(batch[-1][0]) + 1
        if len(batch) < 1000:
            break
        if cursor >= end:
            break
    seen: set[int] = set()
    deduped: list[list[float]] = []
    for row in sorted(rows, key=lambda r: int(r[0])):
        if int(row[0]) in seen:
            continue
        seen.add(int(row[0]))
        deduped.append(row)
    meta = {
        "symbol": symbol,
        "venue": "binance",
        "timeframe": timeframe,
        "bars": len(deduped),
        "first_bar_ms": int(deduped[0][0]) if deduped else None,
        "last_bar_ms": int(deduped[-1][0]) if deduped else None,
        "fetched_at_ms": end,
        "sha256": hashlib.sha256(json.dumps(deduped).encode("utf-8")).hexdigest(),
    }
    return deduped, meta


def to_ohlcv(symbol: str, rows: list[list[float]]) -> list[Any]:
    from trading_bot.market_data.types import OHLCV

    return [
        OHLCV(
            symbol=symbol,
            timestamp=int(r[0]),
            open=float(r[1]),
            high=float(r[2]),
            low=float(r[3]),
            close=float(r[4]),
            volume=float(r[5]),
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# statistics helpers
# ---------------------------------------------------------------------------


def dist(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"n": 0, "min": None, "p50": None, "p90": None, "max": None, "mean": None}
    ordered = sorted(values)
    index = min(len(ordered) - 1, round(0.9 * (len(ordered) - 1)))
    return {
        "n": len(ordered),
        "min": round(ordered[0], 4),
        "p50": round(statistics.median(ordered), 4),
        "p90": round(ordered[index], 4),
        "max": round(ordered[-1], 4),
        "mean": round(statistics.fmean(ordered), 4),
    }


#: Decision classifications the runtime emits, mapped to the cause they represent.
CLASSIFICATION_CAUSE = {
    "NO_GROSS_EDGE": "GROSS_EDGE_NEGATIVE",
    "COST_KILLED": "COST_ABOVE_GROSS",
    "NO_ALPHA": "NO_SIGNAL",
    "CONTEXT_ERROR": "CONTEXT_UNAVAILABLE",
    "RISK_VETO": "RISK_BLOCK",
    "VERIFIER_FAIL": "VERIFIER_BLOCK",
    "AGENT_VETO": "AGENT_BLOCK",
    "NO_TRADE": "NO_SIGNAL",
}


def classify_reason(trace: dict[str, Any]) -> str:
    """Bucket a decision by *why* it did not trade (never by what would help)."""
    if trace.get("errors"):
        return "INFRASTRUCTURE_ERROR"
    classification = str(trace.get("classification") or "")
    return CLASSIFICATION_CAUSE.get(classification) or classification or "UNCLASSIFIED"


# ---------------------------------------------------------------------------
# replay
# ---------------------------------------------------------------------------


def replay(assets: list[str], days: int, step: int) -> tuple[Path, dict[str, Any]]:
    from rfc010_baseline_replay import ReplayClock, build_runtime, timeline

    bars_raw: dict[str, list[list[float]]] = {}
    provenance: dict[str, Any] = {}
    for asset in assets:
        symbol = f"{asset}/USDT"
        rows, meta = fetch_bars(symbol, days)
        if not rows:
            raise RuntimeError(f"no candles returned for {symbol}")
        bars_raw[symbol] = rows
        provenance[symbol] = meta
        print(
            f"[data] {symbol}: {meta['bars']} bars "
            f"{datetime.fromtimestamp(meta['first_bar_ms'] / 1000, UTC).isoformat()} .. "
            f"{datetime.fromtimestamp(meta['last_bar_ms'] / 1000, UTC).isoformat()}"
        )

    bars_by_symbol = {symbol: to_ohlcv(symbol, rows) for symbol, rows in bars_raw.items()}
    instants = timeline(bars_by_symbol, step, BAR_MS)
    # A decision needs ``lookback_bars`` closed bars; replaying the first instants
    # would only manufacture CONTEXT_ERROR rows that say nothing about the strategy.
    warmup = 120
    instants = instants[warmup:]
    if not instants:
        raise RuntimeError("the window is shorter than the lookback; fetch more days")
    run_dir = REPO_ROOT / "reports" / "trading-decision-monitor" / "WP-TDM-06" / "replay-runs" / (
        "tdm06-replay-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    clock = ReplayClock(instants[0])
    runtime, registry = build_runtime(
        assets=assets,
        timeframe="5m",
        bars_by_symbol=bars_by_symbol,
        clock=clock,
        run_dir=run_dir,
        initial_equity=10_000.0,
        size_usd=1_000.0,
        lookback_bars=120,
        spread_bps=1.0,
    )

    import asyncio

    async def drive() -> tuple[list[Any], list[str]]:
        cycles: list[Any] = []
        errors: list[str] = []
        for index, instant in enumerate(instants, start=1):
            clock.now_ms = instant
            try:
                cycles.append(await runtime.run_cycle(cycle=index))
            except Exception as exc:  # a failed cycle is evidence, never silence
                errors.append(f"cycle {index}: {type(exc).__name__}: {exc}")
        return cycles, errors

    cycles, errors = asyncio.run(drive())
    summary = runtime.finalize_summary(
        run_id=run_dir.name, started_at_ms=instants[0], cycle_reports=cycles, errors=errors
    )
    from trading_bot.autonomous.reporting import write_run_report

    write_run_report(summary, run_dir)

    traces = [
        json.loads(line)
        for line in (run_dir / "traces.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    context = {
        "run_dir": str(run_dir),
        "run_id": run_dir.name,
        "instants": len(instants),
        "warmup_bars_skipped": warmup,
        "cycles_completed": len(cycles),
        "cycles_failed": len(errors),
        "errors": errors[:10],
        "totals": summary.totals(),
        "window_days": round((instants[-1] - instants[0]) / 86_400_000, 3),
        "provenance": provenance,
        "registry": registry.counts_by_status(),
        "paper_executable": list(registry.paper_candidates("5m")),
        "traces": traces,
        "executions": list(summary.executions),
        "chain": summary.chain,
        "replay": summary.replay,
    }
    return run_dir, context


# ---------------------------------------------------------------------------
# analysis
# ---------------------------------------------------------------------------


def analyse(context: dict[str, Any]) -> dict[str, Any]:
    traces: list[dict[str, Any]] = context["traces"]
    window_days = max(context["window_days"], 1e-9)

    reasons = Counter(classify_reason(t) for t in traces)
    kinds = Counter(str(t.get("no_trade_kind") or "NONE") for t in traces)
    per_asset = Counter(str(t.get("asset")) for t in traces)
    per_mode = Counter(str(t.get("mode")) for t in traces)

    gross: list[float] = []
    cost: list[float] = []
    net: list[float] = []
    per_strategy: dict[str, dict[str, Any]] = {}
    for trace in traces:
        proposal = trace.get("proposal") or {}
        if proposal:
            g = proposal.get("expected_gross_edge_bps")
            c = proposal.get("expected_cost_bps")
            n = proposal.get("expected_net_edge_bps")
            if isinstance(g, (int, float)):
                gross.append(float(g))
            if isinstance(c, (int, float)):
                cost.append(float(c))
            if isinstance(n, (int, float)):
                net.append(float(n))
        for considered in trace.get("strategies_considered") or []:
            sid = str(considered.get("strategy_id") or "UNKNOWN")
            row = per_strategy.setdefault(
                sid,
                {
                    "evaluated": 0,
                    "emitted_alpha": 0,
                    "proposals": 0,
                    "executed": 0,
                    "gross_bps": [],
                    "statuses": Counter(),
                },
            )
            row["evaluated"] += 1
            row["statuses"][str(considered.get("router_status") or "UNKNOWN")] += 1
            if considered.get("emitted_alpha"):
                row["emitted_alpha"] += 1
                value = considered.get("expected_gross_edge_bps")
                if isinstance(value, (int, float)):
                    row["gross_bps"].append(float(value))

    for trace in traces:
        proposal = trace.get("proposal") or {}
        sid = str(proposal.get("strategy_id") or "")
        if sid and sid in per_strategy:
            per_strategy[sid]["proposals"] += 1
            if trace.get("order_created"):
                per_strategy[sid]["executed"] += 1

    strategy_rows = {}
    for sid, row in sorted(per_strategy.items()):
        strategy_rows[sid] = {
            "evaluated": row["evaluated"],
            "emitted_alpha": row["emitted_alpha"],
            "proposals": row["proposals"],
            "executed": row["executed"],
            "gross_bps_when_emitted": dist(row["gross_bps"]),
            "router_status": dict(row["statuses"]),
        }

    # Forward-measured outcomes: the runtime resolves each hypothesis against the
    # bars that followed it, so these are realisations, not estimates.
    outcomes_path = Path(str(context.get("run_dir") or "")) / "outcomes.jsonl"
    outcome_rows: list[dict[str, Any]] = []
    if outcomes_path.exists():
        outcome_rows = [
            json.loads(line)
            for line in outcomes_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    def numbers(field: str) -> list[float]:
        return [float(r[field]) for r in outcome_rows if isinstance(r.get(field), (int, float))]

    net_by_strategy: dict[str, list[float]] = {}
    correct = 0
    for row in outcome_rows:
        value = row.get("net_hypothetical_bps")
        sid = str(row.get("strategy_id") or "UNKNOWN")
        if isinstance(value, (int, float)):
            net_by_strategy.setdefault(sid, []).append(float(value))
        if row.get("direction_correct") is True:
            correct += 1
    outcomes = {
        "resolved": len(outcome_rows),
        "note": (
            "Measured forward by the runtime's own OutcomeEvaluator over the bars that "
            "followed each decision (gross_return_bps / estimated_cost_bps / "
            "net_hypothetical_bps). Realisations, not estimates."
        ),
        "gross_return_bps": dist(numbers("gross_return_bps")),
        "estimated_cost_bps": dist(numbers("estimated_cost_bps")),
        "net_hypothetical_bps": dist(numbers("net_hypothetical_bps")),
        "net_by_strategy": {sid: dist(values) for sid, values in sorted(net_by_strategy.items())},
        "direction_correct": correct,
        "direction_correct_pct": round(100.0 * correct / len(outcome_rows), 2) if outcome_rows else None,
        "positive_realized_net": sum(1 for value in numbers("net_hypothetical_bps") if value > 0),
    }

    cost_reference = dist(cost)
    positive_net = [n for n in net if n > 0]
    counterfactual = {
        "note": (
            "COUNTERFACTUAL ONLY — computed from the same measured numbers and used to "
            "separate 'no gross edge' from 'cost barrier'. The cost model and the risk "
            "limits are NOT changed by this analysis."
        ),
        "proposals": len(net),
        "net_positive_with_model_cost": len(positive_net),
        "net_positive_with_fees_only_20bps": sum(1 for g in gross if g > 20.0),
        "net_positive_with_zero_cost": sum(1 for g in gross if g > 0.0),
    }

    defect_buckets = {"INFRASTRUCTURE_ERROR", "UNCLASSIFIED", "VERIFIER_BLOCK", "AGENT_BLOCK"}
    causes = {
        "infrastructure_defects": sum(v for k, v in reasons.items() if k in defect_buckets),
        "context_unavailable": reasons.get("CONTEXT_UNAVAILABLE", 0),
        "signals_without_edge": sum(
            v for k, v in reasons.items() if k in {"GROSS_EDGE_NEGATIVE", "COST_ABOVE_GROSS"}
        ),
        "legitimate_risk_blocks": reasons.get("RISK_BLOCK", 0),
        "no_signal": reasons.get("NO_SIGNAL", 0),
    }

    return {
        "decisions": len(traces),
        "decisions_per_day": round(len(traces) / window_days, 2),
        "per_asset": dict(per_asset),
        "per_mode": dict(per_mode),
        "executions": len(context["executions"]),
        "trades_per_day": round(len(context["executions"]) / window_days, 3),
        "reason_distribution": dict(reasons),
        "no_trade_kinds": dict(kinds),
        "proposal_gross_bps": dist(gross),
        "proposal_cost_bps": cost_reference,
        "proposal_net_bps": dist(net),
        "outcomes": outcomes,
        "cost_reference_bps": cost_reference.get("p50"),
        "per_strategy": strategy_rows,
        "counterfactual": counterfactual,
        "causes": causes,
        "chain_ok": bool((context.get("chain") or {}).get("ok")),
        "replay": context.get("replay"),
        "registry": context.get("registry"),
        "paper_executable": context.get("paper_executable"),
        "totals": context.get("totals"),
        "cycles": {
            "instants": context["instants"],
            "completed": context["cycles_completed"],
            "failed": context["cycles_failed"],
            "errors": context["errors"],
        },
        "window_days": round(window_days, 3),
        "warmup_bars_skipped": context.get("warmup_bars_skipped"),
        "provenance": context["provenance"],
        "run_dir": context["run_dir"],
    }


def render_markdown(payload: dict[str, Any]) -> str:
    a = payload["analysis"]
    lines = [
        "# WP-TDM-06 §D — Diagnóstico de rentabilidad",
        "",
        f"Run de replay: `{payload['run_id']}` · ventana {a['window_days']} días · "
        f"{a['decisions']} decisiones · {a['cycles']['failed']} ciclos fallidos",
        "",
        "## Embudo",
        "",
        "| métrica | valor |",
        "| --- | --- |",
        f"| decisiones/día | {a['decisions_per_day']} |",
        f"| propuestas | {a['proposal_net_bps']['n']} |",
        f"| ejecuciones PAPER | {a['executions']} |",
        f"| trades/día | {a['trades_per_day']} |",
        f"| cadena de trazas íntegra | {a['chain_ok']} |",
        "",
        "## Edge por propuesta (bps)",
        "",
        "| métrica | bruto | coste | neto |",
        "| --- | --- | --- | --- |",
    ]
    g, c, n = a["proposal_gross_bps"], a["proposal_cost_bps"], a["proposal_net_bps"]
    for key in ("n", "min", "p50", "p90", "max", "mean"):
        lines.append(f"| {key} | {g.get(key)} | {c.get(key)} | {n.get(key)} |")
    cf = a["counterfactual"]
    oc = a.get("outcomes") or {}
    if oc.get("resolved"):
        lines += [
            "",
            "## Resultado medido hacia delante (OutcomeEvaluator)",
            "",
            f"Resueltos: {oc['resolved']} · dirección correcta {oc['direction_correct']} "
            f"({oc.get('direction_correct_pct')}%) · neto hipotético > 0: "
            f"{oc['positive_realized_net']}",
            "",
            "| bps | p50 | media | min | max |",
            "| --- | --- | --- | --- | --- |",
        ]
        for name in ("gross_return_bps", "estimated_cost_bps", "net_hypothetical_bps"):
            row = oc.get(name) or {}
            lines.append(
                f"| {name} | {row.get('p50')} | {row.get('mean')} | {row.get('min')} | {row.get('max')} |"
            )
    lines += [
        "",
        "## Separación de causas",
        "",
        "| causa | decisiones |",
        "| --- | --- |",
    ]
    for key, value in a["causes"].items():
        lines.append(f"| {key} | {value} |")
    lines += [
        "",
        "Motivos observados: "
        + ", ".join(f"`{k}`={v}" for k, v in sorted(a["reason_distribution"].items())),
        "",
        "Contrafactual (no se cambia el modelo): "
        f"neto>0 con coste real = {cf['net_positive_with_model_cost']}, "
        f"neto>0 sólo con fees 20 bps = {cf['net_positive_with_fees_only_20bps']}, "
        f"neto>0 con coste cero = {cf['net_positive_with_zero_cost']} (de {cf['proposals']} propuestas).",
        "",
        "## Por estrategia",
        "",
        "| estrategia | evaluadas | señal | propuestas | ejecutadas | bruto p50 (bps) |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for sid, row in a["per_strategy"].items():
        lines.append(
            f"| {sid} | {row['evaluated']} | {row['emitted_alpha']} | {row['proposals']} | "
            f"{row['executed']} | {row['gross_bps_when_emitted'].get('p50')} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", default="BTC,ETH,SOL")
    parser.add_argument("--days", type=int, default=3)
    parser.add_argument("--step", type=int, default=1, help="evaluate every Nth sealed bar")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    assets = [a.strip().upper() for a in args.assets.split(",") if a.strip()]
    _run_dir, context = replay(assets, args.days, args.step)
    analysis = analyse(context)
    payload = {
        "schema": "wp-tdm-06-profitability-v1",
        "run_id": context["run_id"],
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "assets": assets,
        "days_requested": args.days,
        "step_bars": args.step,
        "analysis": analysis,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    out.with_suffix(".md").write_text(render_markdown(payload), encoding="utf-8")
    print(json.dumps({k: analysis[k] for k in ("decisions", "executions", "reason_distribution", "causes", "counterfactual")}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
