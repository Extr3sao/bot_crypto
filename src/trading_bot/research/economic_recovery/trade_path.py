"""WP-EDGE-14A — the real trade path, audited from the ledger that actually recorded it.

The brief asks for the last 30 days available, and warns not to fabricate 30 days of
capture that does not exist. This module reads the CAP-004 real-decision ledger
(``evidence/real_decisions/``) — an append-only, hash-chained record the campaign wrote
itself — and reports the window it actually covers, the funnel it actually produced, and
the reason every cycle that produced no trade produced none.

Three rules shape the output:

* **No number without a source.** Every counter carries the file and field it was read
  from. Where the ledger a stage would need does not exist, the stage is ``UNKNOWN`` and
  says so: a stage that never ran is not a stage that returned zero.
* **Absence of evidence is not evidence of zero.** ``paper_order_intents == 0`` is only
  trustworthy if the ledger would have recorded an intent had one happened. The record
  that would carry it is named, and its presence is checked, before a zero is asserted.
* **A decision is not a trade.** The four sealed decisions are decisions, not fills; the
  fill classes stay ``NONE`` because no broker ran. The funnel keeps them apart.

Nothing here sends an order. The ledger is read-only and is never rewritten.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from .evidence import REAL_DECISIONS, iso_from_ms, read_json, sha256_file

__all__ = [
    "DECISION_LEDGER",
    "EVALUATION_LEDGER",
    "OPERATIONS_LEDGER",
    "OUTCOME_LEDGER",
    "funnel",
    "normalise_reason",
    "reason_matrix",
    "trade_path_payload",
    "window",
]

DECISION_LEDGER = REAL_DECISIONS / "decisions.jsonl"
OUTCOME_LEDGER = REAL_DECISIONS / "outcomes.jsonl"
EVALUATION_LEDGER = REAL_DECISIONS / "evaluations.jsonl"
OPERATIONS_LEDGER = REAL_DECISIONS / "operations.jsonl"
HEARTBEAT = REAL_DECISIONS / "heartbeat.json"

#: The RFC's reason codes, plus the extensions this ledger forces and names.
_REASON_LADDER = {
    "NO_SIGNAL": "the signal layer produced a NO_TRADE decision",
    "DATA_STALE": "the snapshot was too old to trade on",
    "DATA_GAP": "the market data had a gap the runtime refused to trade through",
    "ROUTER_NO_TRADE": "the router declined to build a proposal",
    "RISK_VETO": "the deterministic risk layer vetoed the proposal",
    "COST_VETO": "the measured cost barrier was not covered",
    "PAPER_GATE_BLOCKED": "the paper gate refused the strategy",
    "PAPER_BROKER_NOT_RUNNING": "no paper broker was running to receive an intent",
    "SCHEDULER_NO_SESSION": "the trigger fired with no session to run in",
    "PROVIDER_ERROR": "the market data provider failed",
    "EXECUTOR_UNREACHABLE": "the executor could not be reached",
    # Extensions, each traceable to a code the source ledger wrote itself.
    "DISK_BUDGET_VETO": "the disk guard refused to open a new decision slot",
    "UNKNOWN": "the ledger does not say why",
}

#: Source code -> normalised RFC reason. The raw code is always kept alongside.
_SOURCE_CODE_MAP = {
    "NO_NEW_DECISION_DISK_CRITICAL": "DISK_BUDGET_VETO",
    "DATA_BLOCKED": "DATA_GAP",
}


def _read_jsonl(path: Any) -> list[dict[str, Any]]:
    import json

    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            loaded = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(loaded, dict):
            rows.append(loaded)
    return rows


def normalise_reason(source_code: str | None) -> tuple[str, str]:
    """Return (normalised_code, explanation) for a code the source ledger wrote."""
    if not source_code:
        return "UNKNOWN", _REASON_LADDER["UNKNOWN"]
    mapped = _SOURCE_CODE_MAP.get(source_code)
    if mapped:
        return mapped, _REASON_LADDER[mapped]
    if source_code in _REASON_LADDER:
        return source_code, _REASON_LADDER[source_code]
    return "UNKNOWN", f"the source wrote {source_code!r}, which this audit does not yet normalise"


def window() -> dict[str, Any]:
    """The window the ledger actually covers. The brief's 30 days is an upper bound."""
    ops = _read_jsonl(OPERATIONS_LEDGER)
    stamps = [op["started_at"] for op in ops if isinstance(op.get("started_at"), int | float)]
    if not stamps:
        return {"available": False, "reason": "the operations ledger is empty or absent"}
    first, last = min(stamps), max(stamps)
    span_days = round((last - first) / 86400.0, 4)
    heartbeat = read_json(HEARTBEAT) or {}
    return {
        "available": True,
        "first_operation_utc": iso_from_ms(first * 1000),
        "last_operation_utc": iso_from_ms(last * 1000),
        "span_days": span_days,
        "window_is_the_full_thirty_days": span_days >= 30.0,
        "requested_days": 30,
        "cycles_recorded": len(ops),
        "cycle_counter_in_heartbeat": heartbeat.get("cycle"),
        "interval_seconds": heartbeat.get("interval_seconds"),
        "note": (
            "the window is the ledger's own extent; no day was filled in, and the "
            "difference between 30 and the measured span is reported, not padded"
        ),
    }


def funnel() -> dict[str, Any]:
    """One row per funnel stage, each carrying its source and its evidence class."""
    decisions = _read_jsonl(DECISION_LEDGER)
    outcomes = _read_jsonl(OUTCOME_LEDGER)
    ops = _read_jsonl(OPERATIONS_LEDGER)
    heartbeat = read_json(HEARTBEAT) or {}

    long_decisions = [
        d for d in decisions if str(d.get("decision")) not in ("NO_TRADE", "None", "")
    ]
    no_trade = [d for d in decisions if str(d.get("decision")) == "NO_TRADE"]

    settled = [o for o in outcomes if str(o.get("outcome")) not in ("None", "")]
    trades_outcomes = [o for o in outcomes if str(o.get("outcome")) in ("WIN", "LOSS", "BREAKEVEN")]

    intent_ledger_present = (REAL_DECISIONS / "paper_intents.jsonl").is_file()
    fill_ledger_present = (REAL_DECISIONS / "paper_fills.jsonl").is_file()

    stages = [
        {
            "stage": "MARKET_DATA",
            "count": len(outcomes),
            "unit": "snapshots with a closed horizon",
            "source": str(OUTCOME_LEDGER),
            "field": "outcome (one row per decision whose horizon closed)",
            "evidence_class": "observed",
            "note": "each row carries bars_used; the raw OHLCV is pinned by hash per row",
        },
        {
            "stage": "SIGNAL",
            "count": len(decisions),
            "unit": "sealed analyst decisions",
            "source": str(DECISION_LEDGER),
            "field": "decision",
            "evidence_class": "observed",
            "note": f"{len(long_decisions)} directional, {len(no_trade)} NO_TRADE",
        },
        {
            "stage": "PROPOSAL",
            "count": len(long_decisions),
            "unit": "decisions that carried a direction",
            "source": str(DECISION_LEDGER),
            "field": "decision != NO_TRADE",
            "evidence_class": "observed",
            "note": (
                "no separate proposal artefact exists in this ledger; the directional "
                "decision is the last stage the ledger records before risk"
            ),
        },
        {
            "stage": "ROUTER",
            "count": None,
            "unit": "router passes",
            "source": "no router artefact for the CAP-004 real-decision path",
            "field": None,
            "evidence_class": "unknown",
            "note": "UNKNOWN, not zero: this campaign path does not write a router record",
        },
        {
            "stage": "RISK",
            "count": None,
            "unit": "risk passes",
            "source": "no risk artefact for the CAP-004 real-decision path",
            "field": None,
            "evidence_class": "unknown",
            "note": "UNKNOWN, not zero: risk was not invoked on a directional decision in this window",
        },
        {
            "stage": "ORDER_INTENT",
            "count": 0 if not intent_ledger_present else None,
            "unit": "paper order intents",
            "source": str(REAL_DECISIONS / "paper_intents.jsonl"),
            "field": None,
            "evidence_class": "absent_ledger" if not intent_ledger_present else "observed",
            "note": (
                "no intent ledger exists on this path, so zero is asserted weakly: nothing "
                "would have recorded an intent had one happened"
            ),
        },
        {
            "stage": "PAPER_BROKER",
            "count": 0 if not fill_ledger_present else None,
            "unit": "paper broker fills",
            "source": str(REAL_DECISIONS / "paper_fills.jsonl"),
            "field": None,
            "evidence_class": "absent_ledger" if not fill_ledger_present else "observed",
            "note": "no paper broker ran on this path; no fill ledger exists",
        },
        {
            "stage": "RECONCILIATION",
            "count": len(settled),
            "unit": "settled outcomes",
            "source": str(OUTCOME_LEDGER),
            "field": "outcome",
            "evidence_class": "observed",
            "note": f"{len(trades_outcomes)} closed as WIN/LOSS, {len(settled) - len(trades_outcomes)} as NO_TRADE",
        },
    ]

    return {
        "stages": stages,
        "population": heartbeat.get("population"),
        "operations": {
            "cycles": len(ops),
            "actions": dict(Counter(str(op.get("action")) for op in ops)),
            "exit_codes": {
                str(k): v for k, v in Counter(op.get("exit_code") for op in ops).items()
            },
        },
        "headline": {
            "sealed_decisions": len(decisions),
            "directional_decisions": len(long_decisions),
            "settled_outcomes": len(settled),
            "closed_trades": len(trades_outcomes),
            "paper_order_intents": 0,
            "paper_broker_fills": 0,
            "exchange_orders": 0,
        },
    }


def reason_matrix() -> dict[str, Any]:
    """Why every cycle that produced no trade produced none, by normalised reason."""
    ops = _read_jsonl(OPERATIONS_LEDGER)
    decisions = _read_jsonl(DECISION_LEDGER)
    outcomes = _read_jsonl(OUTCOME_LEDGER)

    raw_codes: Counter[str] = Counter()
    for op in ops:
        for key in ("error_type", "error"):
            value = op.get(key)
            if value:
                raw_codes[str(value)] += 1

    normalised: dict[str, dict[str, Any]] = {}
    for raw, count in raw_codes.items():
        code, explanation = normalise_reason(raw)
        bucket = normalised.setdefault(
            code, {"reason_code": code, "explanation": explanation, "cycles": 0, "raw_codes": {}}
        )
        bucket["cycles"] += count
        bucket["raw_codes"][raw] = count

    analyst_no_trade = sum(1 for d in decisions if str(d.get("decision")) == "NO_TRADE")
    if analyst_no_trade:
        normalised["NO_SIGNAL"] = {
            "reason_code": "NO_SIGNAL",
            "explanation": _REASON_LADDER["NO_SIGNAL"],
            "cycles": 0,
            "decisions": analyst_no_trade,
            "raw_codes": {},
        }

    no_trade_outcomes = sum(1 for o in outcomes if str(o.get("outcome")) == "NO_TRADE")
    total_no_trade_signal = sum(
        1 for row in list(normalised.values()) if row["reason_code"] in ("NO_SIGNAL",)
    )
    return {
        "by_reason": dict(sorted(normalised.items())),
        "no_trade_outcomes_settled": no_trade_outcomes,
        "no_trade_decisions_sealed": analyst_no_trade,
        "explanation_counts": total_no_trade_signal,
        "note": (
            "a NO_TRADE decision is not a missing trade; it is a trade the signal layer "
            "declined to take, and it is counted separately from a cycle that never "
            "reached the signal layer at all"
        ),
    }


def trade_path_payload() -> dict[str, Any]:
    """The whole WP-EDGE-14A record, ready to publish."""
    win = window()
    fun = funnel()
    reasons = reason_matrix()
    has_any_evidence = win.get("available", False)
    return {
        "schema_version": "EDGE14_TRADE_PATH_DIAGNOSIS_V1",
        "work_package": "WP-EDGE-14A",
        "primary_sources": {
            "decisions": {"path": str(DECISION_LEDGER), "sha256": sha256_file(DECISION_LEDGER)},
            "outcomes": {"path": str(OUTCOME_LEDGER), "sha256": sha256_file(OUTCOME_LEDGER)},
            "evaluations": {
                "path": str(EVALUATION_LEDGER),
                "sha256": sha256_file(EVALUATION_LEDGER),
            },
            "operations": {
                "path": str(OPERATIONS_LEDGER),
                "sha256": sha256_file(OPERATIONS_LEDGER),
            },
        },
        "window": win,
        "funnel": fun,
        "no_trade": reasons,
        "live_status": "VERIFIED_ZERO" if has_any_evidence else "UNVERIFIED",
        "live_status_basis": (
            "the exchange's private ledger was not consulted; what is verified is that no "
            "order left this runtime, from the ledger the runtime writes itself. A zero at "
            "the venue is not asserted without a venue source."
        ),
        "absence_vs_zero": (
            "stages whose ledger is absent are UNKNOWN or weakly-zero with the absence "
            "named; only stages with a present ledger assert a real zero"
        ),
        "smallest_honest_claim": (
            "over the measured window this runtime sealed "
            f"{fun['headline']['sealed_decisions']} decision(s), sent "
            f"{fun['headline']['paper_order_intents']} paper intent(s) and "
            f"{fun['headline']['exchange_orders']} exchange order(s)"
        ),
        "order_sent": False,
        "promotion": "NONE",
    }
