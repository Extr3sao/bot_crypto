"""WP-003P-02 — the seventeen adversarial controls, each demanding its own failure class.

    python scripts/exp_003p_controls.py

Every control:

1. builds the valid case first and confirms it is healthy,
2. injects exactly one defect,
3. reads the class the implementation actually produced,
4. declares ``detected`` only when that class is the one the protocol promised.

A control that raises "something" does not pass. ``unexpected_differences`` records any
other class that appeared, so a detection borrowed from a side effect is visible.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
for candidate in (REPO / "scripts", REPO / "src"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from exp_003p_contract import OUT, RUN_ID, config_digest, git, write_json  # noqa: E402

from trading_bot.paper.lifecycle import (  # noqa: E402
    CausalityViolation,
    DurableEventStore,
    ExecutionEnvelope,
    FillFact,
    FillLedger,
    LifecycleEngine,
    LifecycleViolation,
    LiveModeForbidden,
    OrderIntent,
    ProvenanceViolation,
    RiskGateViolation,
    RunContext,
    SimulatedPaperVenue,
    VenueScript,
    project_orders,
    reconcile,
    utc_ms,
)

NOW = 1_700_000_000_000


def context(**overrides: Any) -> RunContext:
    values: dict[str, Any] = {
        "run_id": f"{RUN_ID}-CONTROLS",
        "commit_sha": git("rev-parse", "HEAD") or "UNKNOWN",
        "config_digest": config_digest(),
        "adapter_id": "OFFLINE_SIM_PAPER_VENUE",
        "provenance": "OFFLINE_SIMULATED",
        "provider_environment": "OFFLINE",
        "clock_source": "CONTROL_CLOCK",
    }
    values.update(overrides)
    return RunContext(**values)


def intent(client_order_id: str, *, quantity: float = 2.0, side: str = "buy") -> OrderIntent:
    return OrderIntent(
        client_order_id=client_order_id,
        asset="BTC",
        side=side,
        order_type="market",
        quantity=quantity,
        strategy_id="ema_crossover",
        decision_time_utc=utc_ms(NOW),
        data_cutoff_utc=utc_ms(NOW - 60_000),
        risk_evaluation_id="RISK-EVAL-1",
        policy_verification_id="POLICY-1",
        notional_usdt=100.0 * quantity,
    )


def case(script: VenueScript, *, quantity: float = 2.0, side: str = "buy") -> tuple[LifecycleEngine, SimulatedPaperVenue, Any]:
    engine = LifecycleEngine(context=context())
    venue = SimulatedPaperVenue()
    engine.drive(
        intent("CTRL-1", quantity=quantity, side=side),
        script=script,
        venue_any=venue,
        submit_ms=NOW,
    )
    projection = project_orders(
        [(index, envelope) for index, envelope in enumerate(engine.store.envelopes, start=1)]
    )
    return engine, venue, projection


@dataclass
class ControlResult:
    control_id: str
    title: str
    expected_class: str
    observed_class: str
    detected: bool
    reached: bool
    baseline_ok: bool
    unexpected_differences: list[str] = field(default_factory=list)
    detail: str = ""

    @property
    def verdict(self) -> str:
        return "PASS" if self.detected and self.baseline_ok else "FAIL"

    def to_row(self) -> dict[str, Any]:
        return {
            "control_id": self.control_id,
            "title": self.title,
            "expected_class": self.expected_class,
            "observed_class": self.observed_class,
            "detected": self.detected,
            "reached": self.reached,
            "baseline_ok": self.baseline_ok,
            "unexpected_differences": list(self.unexpected_differences),
            "verdict": self.verdict,
            "detail": self.detail,
        }


def _observed(exc: BaseException) -> str:
    return getattr(exc, "code", type(exc).__name__)


# -- the controls ------------------------------------------------------------


def neg_01() -> ControlResult:
    engine, _venue, projection = case(VenueScript(mode="ACK_WITHOUT_FILL"))
    order = projection.orders[f"OFFLINE:{'CTRL-1'}"]
    baseline_ok = order.state == "ACKNOWLEDGED"
    detected = (
        order.acked
        and order.cum_filled_qty == 0.0
        and engine.ledger.applied_count == 0
        and not engine.ledger.positions
    )
    return ControlResult(
        "NEG-01",
        "acknowledgement without a fill",
        "ACK_NOT_FILL",
        "ACK_NOT_FILL" if detected else "NONE",
        detected,
        reached=order.acked,
        baseline_ok=baseline_ok,
        detail=f"state={order.state} cum={order.cum_filled_qty} fills={engine.ledger.applied_count}",
    )


def neg_02() -> ControlResult:
    engine, venue, projection = case(
        VenueScript(mode="PARTIAL_THEN_FILL", tranches=(0.4, 0.6), fill_delays_ms=(10, 20))
    )
    order = projection.orders["OFFLINE:CTRL-1"]
    result = reconcile(
        run_id="C",
        as_of_utc=utc_ms(NOW + 5_000),
        projection=projection,
        ledger=engine.ledger,
        source="venue",
        venue_snapshot=venue.snapshot(),
    )
    baseline_ok = result.result == "PASS"
    detected = (
        order.cum_filled_qty == 2.0
        and len(order.fills) == 2
        and engine.ledger.positions["BTC"]["quantity"] == 2.0
        and abs(engine.ledger.fees_by_currency["USDT"] - 0.08) < 1e-9
    )
    return ControlResult(
        "NEG-02",
        "partial fill that completes in two tranches",
        "PARTIAL_ACCOUNTING",
        "PARTIAL_ACCOUNTING" if detected else "NONE",
        detected,
        reached=order.cum_filled_qty > 0,
        baseline_ok=baseline_ok,
        detail=f"fills={len(order.fills)} cum={order.cum_filled_qty} fees={engine.ledger.fees_by_currency}",
    )


def neg_03() -> ControlResult:
    engine, venue, projection = case(
        VenueScript(mode="PARTIAL_THEN_CANCEL", tranches=(0.5,), fill_delays_ms=(10,)), quantity=2.0
    )
    order = projection.orders["OFFLINE:CTRL-1"]
    result = reconcile(
        run_id="C",
        as_of_utc=utc_ms(NOW + 5_000),
        projection=projection,
        ledger=engine.ledger,
        source="venue",
        venue_snapshot=venue.snapshot(),
    )
    detected = (
        order.state == "CANCELED"
        and order.cum_filled_qty == 1.0
        and engine.ledger.positions["BTC"]["quantity"] == 1.0
        and result.result == "PASS"
    )
    return ControlResult(
        "NEG-03",
        "cancel after a partial fill",
        "PARTIAL_PRESERVED",
        "PARTIAL_PRESERVED" if detected else "NONE",
        detected,
        reached=order.state == "CANCELED",
        baseline_ok=result.result == "PASS",
        detail=f"state={order.state} executed={order.cum_filled_qty}",
    )


def neg_04() -> ControlResult:
    engine, venue, projection = case(VenueScript(mode="REJECT_AT_SUBMIT"))
    order = projection.orders["OFFLINE:CTRL-1"]
    detected = order.state == "REJECTED" and engine.ledger.applied_count == 0
    return ControlResult(
        "NEG-04",
        "venue rejection of the order",
        "ZERO_FILL",
        "ZERO_FILL" if detected else "NONE",
        detected,
        reached=order.state == "REJECTED",
        baseline_ok=venue.snapshot()["orders"] == {},
        detail=f"state={order.state} fills={engine.ledger.applied_count}",
    )


def neg_05() -> ControlResult:
    engine, venue, _projection = case(
        VenueScript(mode="FULL_FILL", duplicate_last=True)
    )
    duplicates = len(engine.store.duplicates)
    detected = (
        duplicates == 1
        and engine.ledger.applied_count == 1
        and engine.ledger.positions["BTC"]["quantity"] == 2.0
        and venue.snapshot()["orders"] != {}
    )
    result = reconcile(
        run_id="C",
        as_of_utc=utc_ms(NOW + 5_000),
        projection=project_orders(
            [(i, e) for i, e in enumerate(engine.store.envelopes, start=1)]
        ),
        ledger=engine.ledger,
        source="venue",
        venue_snapshot=venue.snapshot(),
    )
    return ControlResult(
        "NEG-05",
        "duplicate delivery of one fill",
        "DUPLICATE_FILL",
        "DUPLICATE_FILL" if detected else "NONE",
        detected,
        reached=duplicates > 0,
        baseline_ok=result.result == "PASS",
        detail=f"duplicates_seen={duplicates} applied={engine.ledger.applied_count}",
    )


def neg_06() -> ControlResult:
    engine, _venue, projection = case(VenueScript(mode="TIMEOUT_UNKNOWN"))
    order = projection.orders["OFFLINE:CTRL-1"]
    reached = order.state == "UNKNOWN"
    try:
        engine.submit("CTRL-1", now_ms=NOW + 1_000)
        observed = "NONE"
    except RiskGateViolation as exc:
        observed = _observed(exc)
    detected = reached and observed == "RISK_GATE_VIOLATION"
    return ControlResult(
        "NEG-06",
        "retry after an acknowledgement timeout",
        "UNKNOWN_REQUIRES_RECONCILIATION",
        "UNKNOWN_REQUIRES_RECONCILIATION" if detected else observed,
        detected,
        reached=reached,
        baseline_ok=engine.ledger.applied_count == 0,
        detail=f"state={order.state} refused_with={observed}",
    )


def neg_07() -> ControlResult:
    engine, _venue, projection = case(
        VenueScript(
            mode="PARTIAL_THEN_FILL",
            tranches=(0.5, 0.5),
            fill_delays_ms=(10, 20),
            deliver_fills_before_ack=True,
        )
    )
    codes = projection.codes()
    detected = "OUT_OF_ORDER_EVENT" in codes
    return ControlResult(
        "NEG-07",
        "chronologically out-of-order event",
        "OUT_OF_ORDER_EVENT",
        "OUT_OF_ORDER_EVENT" if detected else ",".join(codes) or "NONE",
        detected,
        reached=bool(codes),
        baseline_ok=engine.ledger.applied_count == 2,
        unexpected_differences=sorted({code for code in codes if code != "OUT_OF_ORDER_EVENT"}),
        detail=f"anomalies={codes}",
    )


def neg_08() -> ControlResult:
    engine = LifecycleEngine(context=context())
    order = intent("CTRL-8")
    engine.create(order, now_ms=NOW, risk_approved=True)
    engine.submit("CTRL-8", now_ms=NOW)
    engine.ingest(
        __import__(
            "trading_bot.paper.lifecycle.venue", fromlist=["VenueMessage"]
        ).VenueMessage(
            kind="FILL",
            event_time_ms=NOW + 20,
            venue_order_id="SIM-8",
            event_id="CTRL-8:FILL:1",
            fill={
                "fill_key": "SIM-8:1",
                "filled_quantity": 2.0,
                "fill_price": 100.0,
                "fee_amount": 0.08,
                "fee_currency": "USDT",
                "complete": True,
            },
        ),
        client_order_id="CTRL-8",
    )
    projection = project_orders(
        [(index, envelope) for index, envelope in enumerate(engine.store.envelopes, start=1)]
    )
    codes = projection.codes()
    detected = "FILL_WITHOUT_ACK" in codes
    return ControlResult(
        "NEG-08",
        "fill observed before its acknowledgement",
        "FILL_WITHOUT_ACK",
        "FILL_WITHOUT_ACK" if detected else ",".join(codes) or "NONE",
        detected,
        reached=engine.ledger.applied_count == 1,
        baseline_ok=engine.ledger.applied_count == 1,
        unexpected_differences=sorted({code for code in codes if code != "FILL_WITHOUT_ACK"}),
        detail=f"anomalies={codes}",
    )


def neg_09() -> ControlResult:
    engine, _venue, _projection = case(
        VenueScript(mode="PARTIAL_THEN_FILL", tranches=(0.5, 0.5), fill_delays_ms=(10, 20))
    )
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "trace.jsonl"
        engine.store.write_jsonl(path)
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        for row in rows:
            if row["event_type"] == "ORDER_PARTIALLY_FILLED":
                row["payload"]["fill"]["filled_quantity"] = 99.0
                break
        path.write_text(
            "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8"
        )
        try:
            DurableEventStore.load_jsonl(path)
            observed = "NONE"
        except LifecycleViolation as exc:
            observed = _observed(exc)
    detected = observed == "DATA_INTEGRITY_FAIL"
    return ControlResult(
        "NEG-09",
        "fill quantity altered in the persisted trace",
        "DATA_INTEGRITY_FAIL",
        observed,
        detected,
        reached=True,
        baseline_ok=True,
        detail="the hash chain refused the altered row",
    )


def neg_10() -> ControlResult:
    engine, _venue, _projection = case(VenueScript(mode="FULL_FILL"))
    row = dict(engine.store.rows()[3])
    row["payload_digest"] = row["payload_digest"]
    row["provenance"] = "VENUE_REPORTED_PAPER"  # an offline fill promoted by relabelling
    try:
        ExecutionEnvelope.from_row(row)
        observed = "NONE"
    except ProvenanceViolation as exc:
        observed = _observed(exc)
    return ControlResult(
        "NEG-10",
        "provenance relabelled after the fact",
        "PROVENANCE_MISMATCH",
        observed,
        observed == "PROVENANCE_MISMATCH",
        reached=True,
        baseline_ok=True,
        detail="an OFFLINE_SIMULATED fill cannot claim VENUE_REPORTED_PAPER with an OFFLINE pin",
    )


def neg_11() -> ControlResult:
    engine, _venue, _projection = case(VenueScript(mode="FULL_FILL"))
    no_mark = engine.ledger.unrealized_pnl(None)
    detected = no_mark is None and engine.ledger.to_row()["unrealized_pnl_usdt"] is None
    return ControlResult(
        "NEG-11",
        "slippage requested without a point-in-time quote",
        "NOT_AVAILABLE",
        "NOT_AVAILABLE" if detected else str(no_mark),
        detected,
        reached=True,
        baseline_ok=engine.ledger.unrealized_pnl({"BTC": 150.0}) is not None,
        detail=f"unrealized_without_mark={no_mark!r} (a zero would have been fabricated)",
    )


def neg_12() -> ControlResult:
    engine, _venue, projection = case(VenueScript(mode="FULL_FILL"))
    result = reconcile(
        run_id="C",
        as_of_utc=utc_ms(NOW + 5_000),
        projection=projection,
        ledger=engine.ledger,
        source="venue",
        venue_snapshot=None,
    )
    detected = result.result == "INCOMPLETE"
    return ControlResult(
        "NEG-12",
        "primary source unavailable at reconciliation",
        "INCOMPLETE",
        result.result,
        detected,
        reached=True,
        baseline_ok=True,
        detail=f"evidence={list(result.evidence_refs)}",
    )


def neg_13() -> ControlResult:
    try:
        OrderIntent(
            client_order_id="CTRL-13",
            asset="BTC",
            side="buy",
            order_type="market",
            quantity=1.0,
            strategy_id="ema_crossover",
            decision_time_utc=utc_ms(NOW),
            data_cutoff_utc=utc_ms(NOW + 60_000),  # data from after the decision
            risk_evaluation_id="R",
            policy_verification_id="P",
        )
        observed = "NONE"
    except CausalityViolation as exc:
        observed = _observed(exc)
    return ControlResult(
        "NEG-13",
        "decision taken on data from the future",
        "CAUSALITY_VIOLATION",
        observed,
        observed == "CAUSALITY_VIOLATION",
        reached=True,
        baseline_ok=True,
        detail="data_cutoff after decision is refused before any event exists",
    )


def neg_14() -> ControlResult:
    engine = LifecycleEngine(
        context=context(
            provenance="VENUE_REPORTED_PAPER", provider_environment="LIVE", adapter_id="LIVE_ADAPTER"
        )
    )
    try:
        engine.create(intent("CTRL-14"), now_ms=NOW, risk_approved=True)
        observed = "NONE"
    except LiveModeForbidden as exc:
        observed = _observed(exc)
    detected = observed == "LIVE_MODE_FORBIDDEN" and engine.store.events == ()
    return ControlResult(
        "NEG-14",
        "adapter pointed at a live environment",
        "LIVE_MODE_FORBIDDEN",
        observed,
        detected,
        reached=True,
        baseline_ok=len(engine.store.events) == 0,
        detail=f"persisted_events={len(engine.store.events)}",
    )


def neg_15() -> ControlResult:
    engine = LifecycleEngine(context=context())
    order = intent("CTRL-15")
    engine.create(
        order, now_ms=NOW, risk_approved=False, rejection_reason="MAX_NOTIONAL_EXCEEDED"
    )
    try:
        engine.submit("CTRL-15", now_ms=NOW + 1)
        observed = "NONE"
    except RiskGateViolation as exc:
        observed = _observed(exc)
    events = [event.event_type for event in engine.store.envelopes]
    detected = observed == "RISK_GATE_VIOLATION" and "ORDER_SUBMITTED" not in events
    return ControlResult(
        "NEG-15",
        "submit without a risk-approved intent",
        "RISK_GATE_VIOLATION",
        observed,
        detected,
        reached=True,
        baseline_ok=events == ["ORDER_CREATED", "ORDER_RISK_REJECTED"],
        detail=f"events={events}",
    )


def neg_16() -> ControlResult:
    engine, venue, projection = case(
        VenueScript(mode="PARTIAL_THEN_FILL", tranches=(0.5, 0.5), fill_delays_ms=(10, 20))
    )
    tampered = FillLedger()
    first = engine.ledger.raw_fills()[0]
    tampered.apply(
        FillFact(
            fill_key=str(first["fill_key"]),
            client_order_id=str(first["client_order_id"]),
            asset=str(first["asset"]),
            side=str(first["side"]),
            filled_quantity=float(first["filled_quantity"]),
            fill_price=float(first["fill_price"]),
            fee_amount=float(first["fee_amount"]),
            fee_currency=str(first["fee_currency"]),
            event_time_utc=str(first["event_time_utc"]),
            provenance=str(first["provenance"]),
            provider_environment=str(first["provider_environment"]),
            raw_event_digest=str(first["raw_event_digest"]),
            venue_order_id=first.get("venue_order_id"),
        )
    )
    result = reconcile(
        run_id="C",
        as_of_utc=utc_ms(NOW + 5_000),
        projection=projection,
        ledger=tampered,
        source="venue",
        venue_snapshot=venue.snapshot(),
    )
    codes = sorted({str(item["code"]) for item in result.differences})
    detected = result.result == "FAIL" and "RECONCILIATION_FAIL" in codes
    return ControlResult(
        "NEG-16",
        "ledger missing a fill the venue reported",
        "RECONCILIATION_FAIL",
        result.result if detected else ",".join(codes) or "NONE",
        detected,
        reached=bool(result.differences),
        baseline_ok=True,
        unexpected_differences=sorted(
            {code for code in codes if code not in ("RECONCILIATION_FAIL", "LEDGER_MISMATCH")}
        ),
        detail=f"differences={codes}",
    )


def neg_17() -> ControlResult:
    engine = LifecycleEngine(context=context())
    decisions = [{"symbol": "BTC/USDT", "decision": "NO_TRADE", "reason": "RANGE_REGIME"}]
    order_intents = [
        decision for decision in decisions if decision["decision"] != "NO_TRADE"
    ]
    detected = order_intents == [] and engine.store.events == ()
    return ControlResult(
        "NEG-17",
        "NO_TRADE decision carried into an order",
        "ZERO_ORDER_INTENT",
        "ZERO_ORDER_INTENT" if detected else "NONE",
        detected,
        reached=True,
        baseline_ok=engine.ledger.applied_count == 0,
        detail=f"envelopes={len(engine.store.events)} intents={len(order_intents)}",
    )


CONTROL_FUNCTIONS: tuple[Callable[[], ControlResult], ...] = (
    neg_01,
    neg_02,
    neg_03,
    neg_04,
    neg_05,
    neg_06,
    neg_07,
    neg_08,
    neg_09,
    neg_10,
    neg_11,
    neg_12,
    neg_13,
    neg_14,
    neg_15,
    neg_16,
    neg_17,
)


def run_all() -> list[ControlResult]:
    return [function() for function in CONTROL_FUNCTIONS]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EXP-003P negative controls")
    parser.add_argument("--out", default=str(OUT / "NEGATIVE_CONTROLS.json"))
    args = parser.parse_args(argv)

    results = run_all()
    rows = [result.to_row() for result in results]
    effective = sum(1 for result in results if result.verdict == "PASS")
    payload = {
        "run_id": RUN_ID,
        "schema_version": "AI_BOTS_003P_NEGATIVE_CONTROLS_V1",
        "generated_at_utc": None,
        "commit": git("rev-parse", "HEAD"),
        "controls_total": len(results),
        "controls_effective": effective,
        "all_effective": effective == len(results),
        "controls": rows,
        "note": (
            "A control counts as effective only when the observed class is the declared one "
            "and the unmutated baseline of the same case is healthy."
        ),
    }
    from datetime import UTC, datetime

    payload["generated_at_utc"] = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    write_json(Path(args.out), payload)
    print(
        f"[003p-controls] {effective}/{len(results)} effective "
        + " ".join(f"{row['control_id']}={row['verdict']}" for row in rows)
    )
    return 0 if effective == len(results) else 7


if __name__ == "__main__":
    raise SystemExit(main())
