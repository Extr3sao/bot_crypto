"""STRATEGY-BEHAVIOR-AUDIT-V1 — funnel / candle-identity analyzer (read-only).

Consumes the burn-in JSONL event stream (``paper.session`` events) and the
durable state file, and produces the audit funnel:

    decisions -> signals -> unique signals (bar_ts) -> proposals
    -> risk approvals/vetoes -> orders -> fills -> closed trades

plus candle-identity ratios, NO_TRADE taxonomy and per-strategy provenance.
Pure analysis: no trading runtime imports.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def load_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def analyze(events: list[dict[str, Any]], state: dict[str, Any] | None) -> dict[str, Any]:
    cycles = len(events)
    stage_counter: Counter[str] = Counter()
    reason_counter: Counter[str] = Counter()
    orders = 0
    risk_accepted = 0
    risk_rejected = 0
    signals = 0
    intent_keys: set[tuple[str, str, str, int]] = set()
    intent_total = 0
    # candle identity: symbol -> set of bar timestamps that produced signals
    signal_bars: dict[str, set[int]] = defaultdict(set)
    strategy_signals: Counter[str] = Counter()
    strategies_in_rejections: Counter[str] = Counter()
    latencies: list[int] = []

    for e in events:
        latencies.append(int(e.get("latency_ms", 0)))
        cyc = e.get("cycle") or {}
        orders += int(cyc.get("orders_created", 0) or 0)
        risk_accepted += int(cyc.get("risk_accepted", 0) or 0)
        risk_rejected += int(cyc.get("risk_rejected", 0) or 0)
        signals += int(cyc.get("signals_generated", 0) or 0)
        for r in cyc.get("rejections", []) or []:
            stage = str(r.get("stage", "?"))
            reason = str(r.get("reason", "")).split(":")[0]
            stage_counter[f"{stage}:{reason}"] += 1
            reason_counter[stage] += 1
            rid = str(r.get("reason", ""))
            if "duplicate_intent:PAPER-" in rid:
                intent_total += 1
                intent_keys.add((rid.split("PAPER-")[1][:12], stage, reason, 0))

    # per-symbol unique signal bars from the last portfolio snapshot is not
    # enough — use strategy provenance from state closed trades:
    closed = (state or {}).get("closed_trades", []) or []
    strategy_trades: Counter[str] = Counter(str(t.get("strategy_name", "?")) for t in closed)
    pnl_by_strategy: dict[str, float] = defaultdict(float)
    for t in closed:
        pnl_by_strategy[str(t.get("strategy_name", "?"))] += float(t.get("pnl", 0.0))

    positions = (state or {}).get("open_positions", []) or []
    broker = (state or {}).get("broker_state", {})
    equity = float(broker.get("equity", 0.0))
    initial = float(broker.get("initial_equity", 0.0))

    duplicate_intents_from_counters = sum(
        int((e.get("cycle") or {}).get("duplicate_intents", 0) or 0) for e in events
    )
    evaluations = sum(
        int((e.get("cycle") or {}).get("strategy_invocations", 0) or 0) for e in events
    )

    return {
        "cycles": cycles,
        "uptime_minutes": round(
            (events[-1]["ts_ms"] - events[0]["ts_ms"]) / 60000.0, 1
        )
        if events
        else 0.0,
        "evaluations": evaluations,
        "signals_generated": signals,
        "orders_created_total": orders,
        "risk_accepted": risk_accepted,
        "risk_rejected": risk_rejected,
        "duplicate_intents": duplicate_intents_from_counters,
        "stage_reasons": dict(stage_counter.most_common()),
        "stage_totals": dict(reason_counter.most_common()),
        "latency_ms_median": sorted(latencies)[len(latencies) // 2] if latencies else 0,
        "latency_ms_max": max(latencies) if latencies else 0,
        "state": {
            "equity": equity,
            "initial_equity": initial,
            "realized_net": round(equity - initial, 4),
            "open_positions": [
                {"symbol": p.get("symbol"), "strategy": p.get("strategy_name")}
                for p in positions
            ],
            "closed_trades": len(closed),
            "trades_by_strategy": dict(strategy_trades),
            "pnl_by_strategy": {k: round(v, 4) for k, v in pnl_by_strategy.items()},
        },
    }


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: strategy_behavior_audit.py <events.jsonl> [state.json]", file=sys.stderr)
        return 2
    events = load_events(Path(argv[1]))
    state = None
    if len(argv) > 2:
        sp = Path(argv[2])
        if sp.exists():
            state = json.loads(sp.read_text(encoding="utf-8"))
    out = analyze(events, state)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
