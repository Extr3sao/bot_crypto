"""Measure the monitor's real cost (RFC §6 performance targets).

Produces ``performance.json`` with:

* cold/warm projection time for a run of N decisions;
* HTTP p50/p95 for the decision list and for a drilldown;
* **event visibility latency**: how long after a decision is appended to
  ``traces.jsonl`` the API can serve it (this is the number the RFC's ≤2 s p95
  target refers to for a local PAPER runtime).

Everything is measured against real files and a real loopback HTTP server; no
figure here is estimated.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import statistics
import sys
import threading
import time
import tracemalloc
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.autonomous.contracts import (  # noqa: E402
    AdmissionStatus,
    CostBreakdown,
    DecisionMode,
    DecisionTrace,
    EdgeEvidence,
    NoTradeKind,
    TradeProposal,
)
from trading_bot.autonomous.trace import DecisionTraceStore  # noqa: E402
from trading_bot.monitor.api import MonitorConfig, build_server  # noqa: E402
from trading_bot.monitor.candles import Bar, StaticCandleSource  # noqa: E402
from trading_bot.monitor.projector import load_run, project_run  # noqa: E402

TS0 = 1_792_826_135_240
BAR_MS = 300_000


def _proposal(decision_id: str, symbol: str, ts: int) -> dict:
    gross, cost = 4.0, 22.8
    return TradeProposal(
        run_id="perf",
        decision_id=decision_id,
        asset=symbol.split("/")[0],
        symbol=symbol,
        strategy_id="ema_crossover@5m",
        strategy_version="v1",
        family="ema_crossover",
        direction="LONG",
        timeframe="5m",
        market_time_ms=ts,
        decision_time_ms=ts,
        entry_reference=100.0,
        structural_stop=99.0,
        horizon_minutes=5.0,
        expected_gross_edge_bps=gross,
        expected_cost_bps=cost,
        expected_net_edge_bps=round(gross - cost, 10),
        cost=CostBreakdown(
            scenario_id="perf",
            cost_model_version="COST_MODEL_V3",
            size_usd=500.0,
            horizon_minutes=5.0,
            spread_bps=1.0,
            spread_knowledge="OBSERVED",
            fee_bps=10.0,
            slippage_bps=5.0,
            impact_bps=1.0,
            funding_bps=0.0,
            round_trip_bps=cost,
            components=(),
            created_at_ms=TS0,
        ),
        edge_evidence=EdgeEvidence(
            source_doc="docs/perf.json",
            metric="gross_bps",
            value_bps=gross,
            knowledge="ESTIMATED",
            sample_trades=1000,
            period="perf",
            timeframe="5m",
            status="COST_KILLED",
        ),
        admission_status=AdmissionStatus.COST_KILLED,
        regime="LOW_VOLATILITY",
        confidence=0.4,
        evidence=("perf:fixture",),
    ).to_dict()


def _trace(index: int, assets: list[str]) -> DecisionTrace:
    asset = assets[index % len(assets)]
    symbol = f"{asset}/USDT"
    ts = TS0 + (index // len(assets)) * BAR_MS
    decision_id = f"perf-session-{asset}-{index:06d}"
    return DecisionTrace(
        run_id="perf",
        decision_id=decision_id,
        asset=asset,
        symbol=symbol,
        market_time_ms=ts,
        decision_time_ms=ts,
        mode=DecisionMode.NO_TRADE,
        reason="gross_edge_not_positive:-18.8000bps",
        classification="NO_GROSS_EDGE",
        regime="LOW_VOLATILITY",
        strategies_considered=(
            {
                "strategy_id": "ema_crossover@5m",
                "admission_status": "COST_KILLED",
                "admitted_for_paper": False,
                "emitted_alpha": index % 3 != 0,
                "expected_gross_edge_bps": 4.0,
                "lifecycle_verdict": None,
                "router_reason": None,
                "router_status": "SELECTED",
                "selected": True,
            },
        ),
        market_context={"last_price": 100.0, "market_time_ms": ts, "router_trace": []},
        asset_context={"asset": asset},
        proposal=_proposal(decision_id, symbol, ts),
        agent_messages=(),
        evidence=("perf:fixture",),
        counter_evidence=(),
        verification={"verdict": "PASS", "checks": [], "failures": []},
        risk={
            "verdict": "PASS",
            "reason": "risk_approved",
            "risk_evaluated": True,
            "advisory": True,
            "risk_rule": "all_limits_pass",
            "notional_usdt": 500.0,
        },
        shadow=None,
        cost_model_version="COST_MODEL_V3",
        order_created=False,
        orders_created=0,
        no_trade_kind=NoTradeKind.NO_TRADE_STRATEGIC.value,
        errors=(),
        created_at_ms=ts + 4_000,
    )


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((pct / 100.0) * (len(ordered) - 1))))
    return ordered[index]


def _get(url: str) -> tuple[int, float]:
    start = time.perf_counter()
    with urllib.request.urlopen(url, timeout=30) as response:
        response.read()
        return response.status, (time.perf_counter() - start) * 1000.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decisions", type=int, default=2000)
    parser.add_argument("--requests", type=int, default=60)
    parser.add_argument("--assets", default="BTC,ETH,SOL")
    parser.add_argument("--out", default="reports/trading-decision-monitor/WP-TDM-05/performance.json")
    parser.add_argument("--run-root", default=".tmp/tdm-perf/runs")
    args = parser.parse_args()

    assets = [a.strip().upper() for a in args.assets.split(",") if a.strip()]
    # the directory name is also the run id the API resolves
    run_dir = (REPO_ROOT / args.run_root / "perf").resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    trace_path = run_dir / "traces.jsonl"
    if trace_path.exists():
        trace_path.unlink()

    store = DecisionTraceStore(run_dir)
    write_start = time.perf_counter()
    for index in range(args.decisions):
        store.append(_trace(index, assets))
    write_ms = (time.perf_counter() - write_start) * 1000.0

    cold_start = time.perf_counter()
    artifacts = load_run(run_dir)
    projection = project_run(artifacts)
    cold_ms = (time.perf_counter() - cold_start) * 1000.0

    # memory of one full projection, measured with tracemalloc (portable, no psutil)
    tracemalloc.start()
    baseline_memory = tracemalloc.get_traced_memory()[0]
    memory_projection = project_run(load_run(run_dir))
    peak_memory = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    projection_rss_bytes = max(peak_memory - baseline_memory, 0)
    del memory_projection

    warm_times = []
    for _ in range(5):
        start = time.perf_counter()
        project_run(load_run(run_dir))
        warm_times.append((time.perf_counter() - start) * 1000.0)

    (run_dir / "RUN_REPORT.json").write_text(
        json.dumps(
            {
                "run_id": "perf",
                "environment": "ccxt:binance",
                "mode": "paper",
                "commit": "perf",
                "timeframe": "5m",
                "executions": [],
            }
        ),
        encoding="utf-8",
    )

    bars = {
        f"{asset}/USDT": [
            Bar(
                time_ms=TS0 - (60 - i) * BAR_MS,
                open=100.0 + i * 0.1,
                high=100.5 + i * 0.1,
                low=99.5 + i * 0.1,
                close=100.2 + i * 0.1,
                volume=10.0,
                timeframe="5m",
                symbol=f"{asset}/USDT",
                venue="BINANCE",
                is_closed=True,
                source="performance-fixture",
                ingested_at="2026-10-24T00:00:00.000Z",
            )
            for i in range(60)
        ]
        for asset in assets
    }
    config = MonitorConfig(runs_root=run_dir.parent, candle_source=StaticCandleSource(bars))
    server, _app = build_server(config, port=0)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    try:
        list_times, detail_times = [], []
        for _ in range(args.requests):
            status, elapsed = _get(f"{base}/api/monitor/decisions?run_id=perf&limit=500")
            assert status == 200
            list_times.append(elapsed)
            status, elapsed = _get(
                f"{base}/api/monitor/decisions/perf-session-{assets[0]}-000000?run_id=perf"
            )
            assert status == 200
            detail_times.append(elapsed)

        # event visibility: append one decision, poll until the API serves it
        visibility = []
        for extra in range(5):
            decision = dataclasses.replace(
                _trace(args.decisions + extra, assets), decision_id=f"live-{extra}"
            )
            store.append(decision)
            start = time.perf_counter()
            while True:
                status, _body = _get(f"{base}/api/monitor/decisions/live-{extra}?run_id=perf")
                if status == 200:
                    visibility.append((time.perf_counter() - start) * 1000.0)
                    break
                if (time.perf_counter() - start) > 10:
                    visibility.append(10_000.0)
                    break
                time.sleep(0.02)
    finally:
        server.shutdown()
        server.server_close()

    payload = {
        "schema": "tdm-performance-v1",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "dataset": {
            "decisions": args.decisions,
            "assets": assets,
            "events_projected": len(projection.events),
            "trace_bytes": trace_path.stat().st_size,
        },
        "projection": {
            "cold_ms": round(cold_ms, 1),
            "warm_ms_median": round(statistics.median(warm_times), 1),
            "write_all_ms": round(write_ms, 1),
            "events_per_second": round(len(projection.events) / max(cold_ms / 1000.0, 1e-9), 1),
            "peak_python_heap_bytes": projection_rss_bytes,
            "bytes_per_event": round(
                projection_rss_bytes / max(len(projection.events), 1), 1
            ),
        },
        "api": {
            "decision_list_ms": {
                "p50": round(_percentile(list_times, 50), 1),
                "p95": round(_percentile(list_times, 95), 1),
                "max": round(max(list_times), 1),
                "requests": len(list_times),
            },
            "drilldown_ms": {
                "p50": round(_percentile(detail_times, 50), 1),
                "p95": round(_percentile(detail_times, 95), 1),
                "max": round(max(detail_times), 1),
                "requests": len(detail_times),
            },
            "event_visibility_ms": {
                "samples": [round(v, 1) for v in visibility],
                "p95": round(_percentile(visibility, 95), 1),
            },
        },
        "targets": {
            "event_visible_p95_ms": 2000,
            "load_2000_markers_without_blocking": "measured via projection cold/warm",
        },
        "notes": [
            "Static candle source: this measures the monitor, not the venue.",
            "Polling interval in the visibility probe is 20 ms, so the floor is ~20 ms.",
        ],
    }
    out = REPO_ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["projection"], indent=1))
    print(json.dumps(payload["api"], indent=1))
    print(f"[tdm-perf] wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
