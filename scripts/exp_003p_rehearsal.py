"""WP-003P-03 — the offline rehearsal, run on frozen bars with no network and no venue.

    python scripts/exp_003p_rehearsal.py --out reports/ai-bots/EXP-003P-PAPER-EXECUTION-001
    python scripts/exp_003p_rehearsal.py --out <dir> --checkout-check

Two phases, one trace convention:

* **runtime** — the real ``VisionLane`` (risk manager, cost schedule, exit policy) opens and
  closes book positions on frozen 1h bars. The attached ``PaperBrokerRecorder`` writes one
  envelope per broker boundary. Nothing here is a simulation of the runtime; it is the
  runtime.
* **scenario** — the same engine, store, ledger and reconciliation driven by a declared
  offline venue double, so partial fills, cancels, rejects and timeouts exist as observed
  events instead of document clauses.

Both are ``OFFLINE_SIMULATED``. Neither is paper trading, and the artifacts say so.
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
for candidate in (REPO / "scripts", REPO / "src"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from exp_003j_replay import load_series  # noqa: E402
from exp_003p_contract import (  # noqa: E402
    DATASET,
    OUT,
    RUN_ID,
    SCENARIO_FEE_BPS,
    SCENARIO_REFERENCE_PRICE,
    SCHEMA_TRACE,
    WINDOW,
    canonical_json,
    config_digest,
    git,
    parse_utc_ms,
    protocol_payload,
    read_json,
    sha256_file,
    write_json,
)

from trading_bot.config.settings import load_settings  # noqa: E402
from trading_bot.paper.lifecycle import (  # noqa: E402
    LifecycleEngine,
    OrderIntent,
    PaperBrokerRecorder,
    RunContext,
    SimulatedPaperVenue,
    VenueScript,
    project_orders,
    reconcile,
)
from trading_bot.vision.clock import timeframe_ms  # noqa: E402
from trading_bot.vision.lane import VisionLane  # noqa: E402
from trading_bot.vision.ledger import read_entries  # noqa: E402
from trading_bot.vision.settings import load_vision_config  # noqa: E402
from trading_bot.vision.signal_sources import (  # noqa: E402
    SIGNAL_SOURCE_STRATEGY,
    build_signal_provider,
)

HOLDOUT_START_UTC = "2026-08-06T00:00:00Z"
HOLDOUT_END_UTC = "2026-08-20T00:00:00Z"


def _parse_utc(text: str) -> int:
    return parse_utc_ms(text)


def _utc(ms: int) -> str:
    return datetime.fromtimestamp(int(ms) / 1000.0, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _context(adapter_id: str, clock_source: str) -> RunContext:
    return RunContext(
        run_id=RUN_ID,
        commit_sha=git("rev-parse", "HEAD") or "UNKNOWN",
        config_digest=config_digest(),
        adapter_id=adapter_id,
        provenance="OFFLINE_SIMULATED",
        provider_environment="OFFLINE",
        clock_source=clock_source,
    )


def _project(engine: LifecycleEngine) -> Any:
    return project_orders(
        [(index, envelope) for index, envelope in enumerate(engine.store.envelopes, start=1)]
    )


def _broker_provider_snapshot(broker: Any) -> dict[str, Any]:
    """The broker book expressed as a source snapshot, for reconciliation.

    Built from the book's own positions and closed trades — never from the lifecycle
    events — so comparing it with the ledger compares two independent derivations.
    """

    orders: dict[str, dict[str, float]] = {}
    for position in broker.positions.values():
        orders[str(position.entry_order_id)] = {
            "quantity": float(position.quantity),
            "notional": float(position.quantity) * float(position.entry_price),
            "fees_usdt": float(position.entry_commission),
        }
    for trade in broker.closed_trades:
        orders.setdefault(
            str(trade.entry_order_id),
            {
                "quantity": float(trade.quantity),
                "notional": float(trade.quantity) * float(trade.entry_price),
                "fees_usdt": float(trade.entry_commission),
            },
        )
        orders[str(trade.exit_order_id)] = {
            "quantity": float(trade.quantity),
            "notional": float(trade.quantity) * float(trade.exit_price),
            "fees_usdt": float(trade.exit_commission),
        }
    return {"adapter_id": "PAPER_BROKER_BOOK", "provider_environment": "OFFLINE", "orders": orders}


def _risk_counts(entries: list[dict[str, Any]]) -> dict[str, Any]:
    approved = 0
    blocked: dict[str, int] = {}
    for row in entries:
        entry = row.get("entry", {})
        if entry.get("kind") != "DECISION_OUTCOME":
            continue
        if entry.get("approved") is True and entry.get("executed") is True:
            approved += 1
        elif entry.get("approved") is False:
            key = str(entry.get("risk_blocked_by") or "risk_rejected")
            blocked[key] = blocked.get(key, 0) + 1
    return {"approved_and_executed": approved, "blocked": dict(sorted(blocked.items()))}


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def _assert_window_is_outside_holdout() -> None:
    start = _parse_utc(WINDOW["start_utc"])
    end = _parse_utc(WINDOW["end_utc"])
    holdout_start = _parse_utc(HOLDOUT_START_UTC)
    holdout_end = _parse_utc(HOLDOUT_END_UTC)
    if start < holdout_end and end > holdout_start:
        raise SystemExit("REFUSED: the rehearsal window intersects the closed holdout")


def _protocol() -> dict[str, Any]:
    path = OUT / "design" / "PROTOCOL.json"
    if not path.exists():
        raise SystemExit("REFUSED: no frozen protocol; write it before the first rehearsal")
    on_disk = read_json(path)
    if on_disk != protocol_payload():
        raise SystemExit(
            "REFUSED: PROTOCOL.json no longer matches the frozen contract "
            "(a protocol edited after the run is not a preregistration)"
        )
    return on_disk


def run_runtime_phase(out: Path, protocol: dict[str, Any]) -> dict[str, Any]:
    interval_ms = timeframe_ms(WINDOW["timeframe"])
    start_ms = _parse_utc(WINDOW["start_utc"])
    end_ms = _parse_utc(WINDOW["end_utc"])
    series, dataset_report = load_series(
        symbols=list(WINDOW["symbols"]),
        start_ms=start_ms,
        end_ms=end_ms,
        interval_ms=interval_ms,
        dataset_dir=DATASET,
    )
    settings = load_settings(config_dir=REPO / "config", env_file=None)
    vision = load_vision_config(env={})
    vision = replace(
        vision,
        lane=replace(
            vision.lane,
            timeframe=WINDOW["timeframe"],
            window_bars=int(WINDOW["window_bars"]),
            decision_every_bars=int(WINDOW["decision_every_bars"]),
            data_delay_ms=0,
        ),
    )
    engine = LifecycleEngine(
        context=_context("PAPER_BROKER_VISION_LANE", "VISION_LANE_BAR_CLOCK")
    )
    recorder = PaperBrokerRecorder(engine, book_id="paper-003p")
    trace_path = out / "runs" / "runtime" / "SIGNAL_TRACE.jsonl"
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    if trace_path.exists():
        trace_path.unlink()
    provider = build_signal_provider(
        SIGNAL_SOURCE_STRATEGY,
        series=series,
        timeframe=WINDOW["timeframe"],
        interval_ms=interval_ms,
        window_bars=int(WINDOW["window_bars"]),
        latency_ms=0,
        trace_path=trace_path,
        mode="PAPER",
        strategy_id=str(protocol["runtime"]["strategy_id"]),
    )
    ledger_path = out / "runs" / "runtime" / "lane_ledger.jsonl"
    if ledger_path.exists():
        ledger_path.unlink()
    lane = VisionLane(
        series={symbol: list(bars) for symbol, bars in series.items()},
        provider=provider,
        config=vision,
        risk_policy=settings.risk,
        ledger_path=ledger_path,
        equity=float(WINDOW["equity_usdt"]),
        book_id="paper-003p",
        decision_every_bars=int(WINDOW["decision_every_bars"]),
        max_calls=max(1_000, sum(len(bars) for bars in series.values())),
        cost_multiplier=1.0,
        lifecycle_recorder=recorder,
    )
    summary = lane.run()
    entries = read_entries(ledger_path)

    last_close = {
        symbol: float(bars[-1].close) for symbol, bars in series.items() if bars
    }
    # The mark is the final frozen close: a point-in-time price that exists in the data,
    # never a zero that would fabricate a loss.
    marks = {symbol.split("/")[0]: price for symbol, price in last_close.items()}
    broker_snapshot = lane.broker.accounting_snapshot(last_close)
    provider_snapshot = _broker_provider_snapshot(lane.broker)
    projection = _project(engine)
    reconciliation = reconcile(
        run_id=RUN_ID,
        as_of_utc=_utc(end_ms),
        projection=projection,
        ledger=engine.ledger,
        source="PAPER_BROKER_BOOK",
        venue_snapshot=provider_snapshot,
        broker_snapshot=broker_snapshot,
    )
    return {
        "engine": engine,
        "recorder": recorder,
        "summary": summary,
        "entries": entries,
        "projection": projection,
        "reconciliation": reconciliation,
        "dataset": dataset_report,
        "marks": marks,
        "broker_snapshot": broker_snapshot,
        "bars_per_symbol": {symbol: len(bars) for symbol, bars in series.items()},
        "lane_ledger_sha256": sha256_file(ledger_path) if ledger_path.exists() else None,
    }


def run_scenario_phase(protocol: dict[str, Any], out: Path) -> dict[str, Any]:
    engine = LifecycleEngine(
        context=_context("OFFLINE_SIM_PAPER_VENUE", "SCENARIO_CLOCK")
    )
    venue = SimulatedPaperVenue()
    submit_ms = _parse_utc(protocol["window"]["start_utc"])
    trace: list[dict[str, Any]] = []
    for index, row in enumerate(protocol["scenarios"]):
        price = SCENARIO_REFERENCE_PRICE * (1.0 + index * 1e-3)
        quantity = float(row["quantity"])
        client_order_id = f"SCN-{row['scenario_id']}"
        intent = OrderIntent(
            client_order_id=client_order_id,
            asset="BTC",
            side=str(row["side"]),
            order_type="market",
            quantity=quantity,
            strategy_id="scenario_harness",
            decision_time_utc=_utc(submit_ms),
            data_cutoff_utc=_utc(submit_ms - 3_600_000),
            notional_usdt=quantity * price,
            stop_loss_pct=1.0,
            take_profit_pct=2.0,
            risk_evaluation_id="SCENARIO_RISK_EVALUATION",
            policy_verification_id="SCENARIO_POLICY_VERIFICATION",
            decision_id=row["scenario_id"],
        )
        script = VenueScript(
            mode=str(row["mode"]),
            tranches=tuple(float(value) for value in row["tranches"]),
            fill_delays_ms=tuple(int(value) for value in row["fill_delays_ms"]),
            duplicate_last=bool(row["duplicate_last"]),
            deliver_fills_before_ack=bool(row["deliver_fills_before_ack"]),
            fee_bps=SCENARIO_FEE_BPS,
            price_ratio=1.0 + index * 1e-3,
        )
        engine.drive(intent, script=script, venue_any=venue, submit_ms=submit_ms + index * 60_000)
        trace.append(
            {
                "scenario_id": row["scenario_id"],
                "expected_terminal_state": row["expected_terminal_state"],
            }
        )
    projection = _project(engine)
    reconciliation = reconcile(
        run_id=RUN_ID,
        as_of_utc=_utc(submit_ms + 3_600_000),
        projection=projection,
        ledger=engine.ledger,
        source="OFFLINE_SIM_PAPER_VENUE",
        venue_snapshot=venue.snapshot(),
    )
    terminal = {
        key: order.state for key, order in sorted(projection.orders.items())
    }
    expectations = {
        f"OFFLINE:SCN-{row['scenario_id']}": row["expected_terminal_state"] for row in trace
    }
    mismatches = {
        key: {"expected": expectations[key], "observed": terminal.get(key)}
        for key in expectations
        if terminal.get(key) != expectations[key]
    }
    return {
        "engine": engine,
        "venue": venue,
        "projection": projection,
        "reconciliation": reconciliation,
        "terminal_states": terminal,
        "state_mismatches": mismatches,
        "trace": trace,
    }


def write_artifacts(out: Path, runtime: dict[str, Any], scenario: dict[str, Any]) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)

    runtime_engine: LifecycleEngine = runtime["engine"]
    scenario_engine: LifecycleEngine = scenario["engine"]
    runtime_engine.store.write_jsonl(out / "EXECUTION_TRACE.jsonl")
    scenario_engine.store.write_jsonl(out / "SCENARIO_TRACE.jsonl")

    lifecycle_rows: list[dict[str, Any]] = []
    for phase, engine in (("runtime", runtime_engine), ("scenario", scenario_engine)):
        projection = _project(engine)
        for order_key, order in sorted(projection.orders.items()):
            for fill in order.fills:
                lifecycle_rows.append(
                    {
                        "phase": phase,
                        "order_key": order_key,
                        "client_order_id": order.client_order_id,
                        "asset": order.asset,
                        "state": order.state,
                        "ordered_qty": order.ordered_qty,
                        "cum_filled_qty": round(order.cum_filled_qty, 12),
                        "event": "FILL",
                        "fill_qty": round(float(fill["filled_quantity"]), 12),
                        "fill_price": round(float(fill["fill_price"]), 10),
                        "fee_amount": round(float(fill["fee_amount"]), 10),
                        "fee_currency": fill["fee_currency"],
                        "event_time_utc": fill["filled_at_utc"],
                        "provenance": fill["provenance"],
                    }
                )
            if not order.fills:
                lifecycle_rows.append(
                    {
                        "phase": phase,
                        "order_key": order_key,
                        "client_order_id": order.client_order_id,
                        "asset": order.asset,
                        "state": order.state,
                        "ordered_qty": order.ordered_qty,
                        "cum_filled_qty": 0.0,
                        "event": "NO_FILL",
                        "fill_qty": 0.0,
                        "fill_price": "",
                        "fee_amount": 0.0,
                        "fee_currency": "",
                        "event_time_utc": order.last_event_utc,
                        "provenance": "OFFLINE_SIMULATED",
                    }
                )
    columns = [
        "phase",
        "order_key",
        "client_order_id",
        "asset",
        "state",
        "ordered_qty",
        "cum_filled_qty",
        "event",
        "fill_qty",
        "fill_price",
        "fee_amount",
        "fee_currency",
        "event_time_utc",
        "provenance",
    ]
    _write_csv(out / "ORDER_LIFECYCLE.csv", lifecycle_rows, columns)
    write_json(
        out / "ORDER_LIFECYCLE.json",
        {
            "schema_version": "AI_BOTS_003P_LIFECYCLE_V1",
            "rows": lifecycle_rows,
            "orders": {
                phase: _project(engine).to_row()
                for phase, engine in (("runtime", runtime_engine), ("scenario", scenario_engine))
            },
        },
    )

    reconciliation = {
        "schema_version": "AI_BOTS_003P_RECONCILIATION_V1",
        "run_id": RUN_ID,
        "runtime": runtime["reconciliation"].to_row(),
        "scenario": scenario["reconciliation"].to_row(),
        "result": (
            "PASS"
            if runtime["reconciliation"].result == "PASS"
            and scenario["reconciliation"].result == "PASS"
            else (
                "FAIL"
                if "FAIL" in (runtime["reconciliation"].result, scenario["reconciliation"].result)
                else "INCOMPLETE"
            )
        ),
        "paper_validation": "BLOCKED_NOT_CONFIGURED",
        "paper_validation_note": (
            "no authorised paper provider is configured; the offline book is not a venue"
        ),
    }
    write_json(out / "RECONCILIATION.json", reconciliation)

    return reconciliation, lifecycle_rows


def compute_metrics(
    runtime: dict[str, Any], scenario: dict[str, Any], lifecycle_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    counts: dict[str, dict[str, int]] = {}
    by_provenance: dict[str, int] = {}
    for phase, engine in (("runtime", runtime["engine"]), ("scenario", scenario["engine"])):
        tally = {name: 0 for name in (
            "ORDER_CREATED", "ORDER_RISK_REJECTED", "ORDER_SUBMITTED", "ORDER_ACKNOWLEDGED",
            "ORDER_PARTIALLY_FILLED", "ORDER_FILLED", "ORDER_CANCELED", "ORDER_REJECTED",
            "ORDER_EXPIRED", "ORDER_UNKNOWN", "ORDER_STATE_RESOLVED",
        )}
        for event in engine.store.envelopes:
            tally[event.event_type] += 1
            by_provenance[event.provenance] = by_provenance.get(event.provenance, 0) + 1
        counts[phase] = tally
        counts[phase]["DUPLICATE_DELIVERIES_REFUSED"] = len(engine.store.duplicates)

    latencies: dict[str, Any] = {"signal_to_intent": "NOT_AVAILABLE"}
    submit_ack: list[int] = []
    ack_fill: list[int] = []
    for engine in (runtime["engine"], scenario["engine"]):
        per_order: dict[str, dict[str, str]] = {}
        for event in engine.store.envelopes:
            per_order.setdefault(event.client_order_id, {})[event.event_type] = event.event_time_utc
        for stamps in per_order.values():
            submitted = stamps.get("ORDER_SUBMITTED")
            acked = stamps.get("ORDER_ACKNOWLEDGED")
            filled = stamps.get("ORDER_FILLED") or stamps.get("ORDER_PARTIALLY_FILLED")
            if submitted and acked:
                submit_ack.append(_parse_utc(acked) - _parse_utc(submitted))
            if acked and filled:
                ack_fill.append(_parse_utc(filled) - _parse_utc(acked))

    def summarise(values: list[int]) -> dict[str, Any]:
        if not values:
            return {"samples": 0, "p50": None, "max": None}
        ordered = sorted(values)
        return {
            "samples": len(ordered),
            "p50": ordered[len(ordered) // 2],
            "max": ordered[-1],
            "unit": "ms",
            "clock": "event_time_utc of the persisted envelopes",
        }

    latencies["submit_to_ack"] = summarise(submit_ack)
    latencies["ack_to_fill"] = summarise(ack_fill)

    summary = runtime["summary"]
    entries = runtime["entries"]
    risk = _risk_counts(entries)
    positions_open = len(runtime["broker_snapshot"]["open_positions"])
    return {
        "schema_version": "AI_BOTS_003P_METRICS_V1",
        "run_id": RUN_ID,
        "provenance_counts": dict(sorted(by_provenance.items())),
        "event_counts": counts,
        "orders": {
            phase: len(_project(engine).orders)
            for phase, engine in (("runtime", runtime["engine"]), ("scenario", scenario["engine"]))
        },
        "fills": {
            phase: sum(len(order.fills) for order in _project(engine).orders.values())
            for phase, engine in (("runtime", runtime["engine"]), ("scenario", scenario["engine"]))
        },
        "positions_open_at_end": positions_open,
        "lane_summary": {
            key: summary.get(key)
            for key in (
                "decision_points",
                "calls",
                "fills",
                "closed_trades",
                "net_realised_usdt",
                "costs_usdt",
                "execution_costs_realised_usdt",
                "final_equity_usdt",
                "stop_reason",
            )
        },
        "risk_gate": risk,
        "latencies": latencies,
        "costs": {
            "source": "ClosedTrade decomposition of the real paper broker",
            "execution_cost_realised_usdt": summary.get("execution_costs_realised_usdt"),
            "commissions_realised_usdt": summary.get("costs_usdt"),
            "cost_per_closed_trade_usdt": (
                None
                if not summary.get("closed_trades")
                else round(
                    float(summary.get("costs_usdt") or 0.0) / float(summary["closed_trades"]), 8
                )
            ),
        },
        "spread_and_slippage_vs_external_quote": "NOT_AVAILABLE",
        "unrealized_pnl": {
            "value": runtime["broker_snapshot"].get("unrealised_pnl"),
            "mark": "final frozen bar close per symbol",
            "mark_prices": runtime["marks"],
        },
        "live_orders": 0,
        "lifecycle_rows": len(lifecycle_rows),
        "paper_validation": "BLOCKED_NOT_CONFIGURED",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EXP-003P offline rehearsal")
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--checkout-check", action="store_true")
    args = parser.parse_args(argv)
    out = Path(args.out)

    _assert_window_is_outside_holdout()
    protocol = _protocol()

    runtime = run_runtime_phase(out, protocol)
    scenario = run_scenario_phase(protocol, out)
    reconciliation, lifecycle_rows = write_artifacts(out, runtime, scenario)
    metrics = compute_metrics(runtime, scenario, lifecycle_rows)
    write_json(out / "METRICS.json", metrics)

    digests = {
        "schema_version": "AI_BOTS_003P_DIGESTS_V1",
        "run_id": RUN_ID,
        "execution_trace_sha256": sha256_file(out / "EXECUTION_TRACE.jsonl"),
        "scenario_trace_sha256": sha256_file(out / "SCENARIO_TRACE.jsonl"),
        "lifecycle_csv_sha256": sha256_file(out / "ORDER_LIFECYCLE.csv"),
        "store_digest_runtime": runtime["engine"].store.digest(),
        "store_digest_scenario": scenario["engine"].store.digest(),
        "ledger_digest_runtime": runtime["engine"].ledger.digest(),
        "ledger_digest_scenario": scenario["engine"].ledger.digest(),
        "run_digest": "sha256:"
        + __import__("hashlib")
        .sha256(
            canonical_json(
                {
                    "execution_trace_sha256": sha256_file(out / "EXECUTION_TRACE.jsonl"),
                    "scenario_trace_sha256": sha256_file(out / "SCENARIO_TRACE.jsonl"),
                    "lifecycle_csv_sha256": sha256_file(out / "ORDER_LIFECYCLE.csv"),
                    "ledger_digest_runtime": runtime["engine"].ledger.digest(),
                    "ledger_digest_scenario": scenario["engine"].ledger.digest(),
                }
            ).encode("utf-8")
        )
        .hexdigest(),
        "protocol_sha256": sha256_file(OUT / "design" / "PROTOCOL.json"),
        "commit": git("rev-parse", "HEAD"),
        "config_digest": config_digest(),
        "checkout_check": bool(args.checkout_check),
    }
    write_json(out / "DIGESTS.json", digests)

    record = {
        "schema_version": SCHEMA_TRACE,
        "run_id": RUN_ID,
        "generated_at_utc": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit": git("rev-parse", "HEAD"),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "config_digest": config_digest(),
        "protocol_sha256": digests["protocol_sha256"],
        "window": WINDOW,
        "dataset": runtime["dataset"],
        "bars_per_symbol": runtime["bars_per_symbol"],
        "runtime": {
            "adapter_id": "PAPER_BROKER_VISION_LANE",
            "recorder": runtime["recorder"].introspection(),
            "events": len(runtime["engine"].store.envelopes),
            "duplicates_refused": len(runtime["engine"].store.duplicates),
            "anomalies": runtime["projection"].codes(),
            "reconciliation": runtime["reconciliation"].result,
            "lane_ledger_sha256": runtime["lane_ledger_sha256"],
        },
        "scenario": {
            "adapter_id": "OFFLINE_SIM_PAPER_VENUE",
            "events": len(scenario["engine"].store.envelopes),
            "duplicates_refused": len(scenario["engine"].store.duplicates),
            "anomalies": scenario["projection"].codes(),
            "reconciliation": scenario["reconciliation"].result,
            "terminal_states": scenario["terminal_states"],
            "state_mismatches": scenario["state_mismatches"],
        },
        "reconciliation": reconciliation["result"],
        "digests": digests,
        "live_orders": 0,
    }
    write_json(out / "REHEARSAL.json", record)

    print(
        "[003p-rehearsal] "
        f"runtime_events={len(runtime['engine'].store.envelopes)} "
        f"scenario_events={len(scenario['engine'].store.envelopes)} "
        f"runtime_recon={runtime['reconciliation'].result} "
        f"scenario_recon={scenario['reconciliation'].result} "
        f"anomalies={runtime['projection'].codes()}{scenario['projection'].codes()} "
        f"fills={metrics['fills']} run_digest={digests['run_digest'][:18]}…"
    )
    return 0 if reconciliation["result"] == "PASS" else 8


if __name__ == "__main__":
    raise SystemExit(main())
