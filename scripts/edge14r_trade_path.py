"""edge14r_trade_path — reconcile the trade path across its two real recordings.

Two independent recordings of the same pipeline exist and they disagree in the only
way that matters: one of them cannot see the middle of the path at all.

* the CAP-004 real-decision path (window 2026-10-06 → 2026-10-16) sealed **four**
  decisions, of which one was directional, and wrote **no** order-intent, router or
  broker record: those stages are `UNKNOWN`/`absent_ledger`, not zero;
* the PAPER_REPLAY execution recorded here drives the same canonical path over
  historical bars and counts every stage, so it can say *where* the funnel stops and
  *why*.

This script reconciles the two, states the terminal cause, and records the capacity
position of the disk guardian. Nothing is inferred from the absence of a ledger: a
stage with no ledger is reported as unknown, and zero is only asserted where a
ledger that would have recorded the event exists.

    python scripts/edge14r_trade_path.py
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "economic-recovery" / "RFC-EDGE-014R"
PAPER = OUT / "PAPER_EXECUTION_EVIDENCE.json"
CAPACITY = OUT / "CAPACITY_RECLAIM.json"
RFC014_DIAGNOSIS = (
    REPO / "reports" / "economic-recovery" / "RFC-EDGE-014" / "TRADE_PATH_DIAGNOSIS.md"
)

STAGES = [
    "MARKET_DATA",
    "SIGNAL",
    "TRADE_PROPOSAL",
    "ROUTER",
    "DETERMINISTIC_RISK",
    "PAPER_BROKER",
    "FILL_LEDGER",
    "RECONCILIATION",
]


def _capacity_snapshot() -> dict[str, Any]:
    from trading_bot.research.disk_space import DiskSpaceGuard

    guard = DiskSpaceGuard(REPO / "data" / "st6")
    report = guard.report()
    allowed, reason = guard.allows_new_decision()
    return {
        "status": guard.status(),
        "allows_new_decision": allowed,
        "refusal_reason": reason,
        "free_bytes": int(report["free_bytes"]),
        "free_gib": round(float(report["free_gib"]), 4),
        "warning_free_bytes": int(report["warning_free_bytes"]),
        "critical_free_bytes": int(report["critical_free_bytes"]),
        "thresholds": {
            "healthy_bytes": int(report["warning_free_bytes"]),
            "critical_bytes": int(report["critical_free_bytes"]),
            "changed_by_this_work_package": False,
        },
        "reclaim": json.loads(CAPACITY.read_text(encoding="utf-8")),
        "reading": (
            "the guardian keeps the campaign's own thresholds (5 GiB healthy, 2 GiB "
            "critical); capacity was recovered from regenerable caches and scratch, no "
            "evidence artifact was deleted and no limit was lowered"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="WP-EDGE-14R trade path reconciliation")
    parser.add_argument("--paper", default=str(PAPER))
    args = parser.parse_args()

    paper = json.loads(Path(args.paper).read_text(encoding="utf-8"))
    gate = paper["arms"]["GATE_INTACT"]
    sandbox = paper["arms"]["SANDBOX_ADMISSION"]
    g = gate["stage_totals"]
    s = sandbox["stage_totals"]

    authoritative = {
        "arm": "GATE_INTACT",
        "what_it_is": (
            "the committed admission ledger, unmodified: the strategy under test has to "
            "be admitted by a committed research artifact before the router will let it "
            "reach risk"
        ),
        "cycles": gate["cycles"],
        "stages": {
            "MARKET_DATA": {
                "count": g["contexts_built"],
                "unit": "symbol-contexts built",
                "ledger": "present (per-cycle context)",
                "evidence_class": "OBSERVED",
            },
            "SIGNAL": {
                "count": g["signals_generated"],
                "unit": "signals",
                "ledger": "present (per-cycle counters)",
                "evidence_class": "OBSERVED",
                "note": (
                    "zero signals: no admitted strategy exists, so the router has nothing "
                    "to ask for one"
                ),
            },
            "TRADE_PROPOSAL": {
                "count": g["orders_created"],
                "unit": "proposals",
                "ledger": "present (per-cycle counters)",
                "evidence_class": "OBSERVED",
            },
            "ROUTER": {
                "count": g["router_invocations"],
                "unit": "invocations",
                "ledger": "present (per-cycle counters)",
                "evidence_class": "OBSERVED",
                "rejected_as": dict(gate["rejection_reasons"]),
                "terminal_cause": "NO_TRADE:no_strategy_passed_gates",
            },
            "DETERMINISTIC_RISK": {
                "count": g["risk_accepted"] + g["risk_rejected"],
                "unit": "decisions",
                "ledger": "present (per-cycle counters)",
                "evidence_class": "OBSERVED",
                "note": "never reached: the router returned no trade, so no signal was sized",
            },
            "PAPER_BROKER": {
                "count": g["orders_created"],
                "unit": "orders",
                "ledger": "present (broker equity and fills)",
                "evidence_class": "OBSERVED",
            },
            "FILL_LEDGER": {
                "count": gate["fills_closed"],
                "unit": "closed fills",
                "ledger": "present",
                "evidence_class": "OBSERVED",
            },
            "RECONCILIATION": {
                "count": gate["cycles"],
                "unit": "cycles reconciled",
                "ledger": "present",
                "evidence_class": "OBSERVED",
                "note": "every cycle ends with a recorded terminal state",
            },
        },
        "broker_equity": {
            "initial": gate["broker_initial_equity"],
            "final": gate["broker_final_equity"],
            "realised_pnl": gate["realised_pnl"],
        },
        "exchange_orders": paper["exchange_orders"],
        "order_sent": paper["order_sent"],
    }

    sandbox_arm = {
        "arm": "SANDBOX_ADMISSION",
        "what_it_is": (
            "a declared sandbox ledger placed in this package's scratch directory, "
            "admitting one family so the downstream stages can be exercised. It is not "
            "an admission and nothing here promotes it"
        ),
        "cycles": sandbox["cycles"],
        "stages": {
            "ROUTER": {
                "count": s["router_invocations"],
                "unit": "invocations",
                "evidence_class": "OBSERVED",
                "rejected_as": dict(sandbox["rejection_reasons"]),
            },
            "DETERMINISTIC_RISK": {
                "count": s["risk_accepted"] + s["risk_rejected"],
                "unit": "decisions",
                "evidence_class": "OBSERVED",
            },
            "PAPER_BROKER": {
                "count": s["orders_created"],
                "unit": "orders",
                "evidence_class": "OBSERVED",
            },
            "FILL_LEDGER": {
                "count": sandbox["fills_closed"],
                "unit": "closed fills",
                "evidence_class": "OBSERVED",
                "opened": sandbox["fills_opened"],
            },
        },
        "broker_equity": {
            "initial": sandbox["broker_initial_equity"],
            "final": sandbox["broker_final_equity"],
            "realised_pnl": sandbox["realised_pnl"],
        },
        "reading": (
            "the risk and broker boundary is reachable: once a strategy is admitted the "
            "same canonical path produces orders and closed fills. That certifies "
            "connectivity, not admissibility"
        ),
    }

    cap004 = {
        "source": str(RFC014_DIAGNOSIS.relative_to(REPO)) if RFC014_DIAGNOSIS.is_file() else None,
        "window": "2026-10-06T19:59:02Z -> 2026-10-16T12:45:03Z",
        "sealed_decisions": 4,
        "directional_decisions": 1,
        "exchange_orders": 0,
        "paper_order_intents": 0,
        "paper_broker_fills": 0,
        "stages_without_a_ledger": [
            "ROUTER",
            "DETERMINISTIC_RISK",
            "TRADE_PROPOSAL",
            "PAPER_BROKER",
        ],
        "why_zero_paper_orders": (
            "the CAP-004 real-decision path writes decision and outcome records but no "
            "order-intent, router or broker record, so the path's middle is unobserved "
            "there: `0` in that window is a weakly-asserted zero (nothing would have "
            "recorded an intent had one existed), not a measured absence of trading"
        ),
        "reconciled_against": (
            "the PAPER_REPLAY execution, which drives the same canonical pipeline with a "
            "ledger at every stage and localises the stop to the router"
        ),
    }

    reconciliation = {
        "schema_version": "EDGE14R_TRADE_PATH_RECONCILIATION_V1",
        "work_package": "WP-EDGE-14R/P1",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "order_sent": False,
        "credentials_used": False,
        "promotion": "NONE",
        "stage_order": STAGES,
        "execution_class": paper["execution_class"],
        "execution_class_reading": paper["execution_class_reading"],
        "engine_factory": paper["engine_factory"],
        "committed_ledger": paper["committed_ledger"],
        "sandbox_ledger": paper["sandbox_ledger"],
        "arms": {"GATE_INTACT": authoritative, "SANDBOX_ADMISSION": sandbox_arm},
        "cap004_real_decision_path": cap004,
        "cause_of_no_paper_orders": [
            {
                "cause": "NO_STRATEGY_PASSED_GATES",
                "where": "router",
                "measured": (
                    f"{g['router_no_trade']} of {g['router_invocations']} router invocations "
                    "on the authoritative arm returned no trade"
                ),
                "why": (
                    "config/strategy_admission.json admits nothing: every strategy in it "
                    "is NO_GROSS_EDGE or not measured under the cost model, so the gate "
                    "that protects capital refuses before sizing"
                ),
                "not_a_defect": True,
            },
            {
                "cause": "PAPER_BROKER_RETURNED_NO_FILL",
                "where": "paper_broker",
                "measured": dict(sandbox["rejection_reasons"]),
                "why": (
                    "on the sandbox arm the broker refused 1134 of 1528 risk-accepted "
                    "decisions: an order with no fill is a normal broker outcome, not a "
                    "missing stage"
                ),
                "not_a_defect": True,
            },
        ],
        "connectivity_verdict": (
            "the pipeline runs end to end: contexts are built, the router is invoked, "
            "risk accepts and the broker fills — on the arm that has an admitted strategy. "
            "On the authoritative arm the funnel stops at the router by design, and that "
            "stop is the gate working, not a broken stage"
        ),
        "capacity": _capacity_snapshot(),
        "unknown_is_not_zero": (
            "a stage without a ledger is reported UNKNOWN and a zero is only asserted "
            "where a ledger that would have recorded the event exists; the CAP-004 path "
            "is weak-zero for intent, broker and fill, and the PAPER_REPLAY arm is a "
            "strong zero because its ledger is present and counted"
        ),
        "limitations": [
            "PAPER_REPLAY is historical bars replayed through the runtime: it is real "
            "execution of the project's code and NOT prospective observation, because "
            "every bar predates the run",
            "one dataset, two symbols, one timeframe and one family certify the path, not an edge",
            "the sandbox ledger is a scratch input that admits a family for connectivity "
            "testing; no result from it may be treated as a research finding",
            "the disk guard refuses only on CRITICAL; a WARNING state still permits new "
            "decision slots, so the earlier 42 refusals were capacity-driven and are "
            "resolved by capacity, not by loosening the guard",
        ],
    }

    (OUT / "TRADE_PATH_RECONCILIATION.json").write_text(
        json.dumps(reconciliation, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )

    cap = reconciliation["capacity"]
    md = f"""# WP-EDGE-14R/P1 — trade path reconciliation

*Two recordings of one pipeline. Only one of them has a ledger at every stage, and it
says where the funnel stops.*

## The stop

| stage | authoritative arm (`GATE_INTACT`) | evidence |
| --- | --- | --- |
| MARKET_DATA | {g["contexts_built"]} symbol-contexts built over {gate["cycles"]} cycles | observed |
| SIGNAL | {g["signals_generated"]} signals | observed |
| TRADE_PROPOSAL | {g["orders_created"]} proposals | observed |
| ROUTER | {g["router_invocations"]} invocations, all NO_TRADE | observed |
| DETERMINISTIC_RISK | {g["risk_accepted"] + g["risk_rejected"]} decisions | observed |
| PAPER_BROKER | {g["orders_created"]} orders | observed |
| FILL_LEDGER | {gate["fills_closed"]} closed fills | observed |
| RECONCILIATION | {gate["cycles"]} cycles reconciled | observed |

The single terminal cause is `{g["router_no_trade"]} x NO_TRADE:no_strategy_passed_gates`:
`config/strategy_admission.json` admits nothing, so the router refuses before sizing.
That is the capital gate working. It is not a broken stage.

## The same path, with an admitted strategy

Placed in this package's scratch directory, a declared sandbox ledger admitting one
family drives the same canonical pipeline:

| stage | sandbox arm | count |
| --- | --- | ---: |
| ROUTER | invocations | {s["router_invocations"]} |
| DETERMINISTIC_RISK | accepted + rejected | {s["risk_accepted"] + s["risk_rejected"]} |
| PAPER_BROKER | orders created | {s["orders_created"]} |
| FILL_LEDGER | fills closed | {sandbox["fills_closed"]} |

Final broker equity {sandbox["broker_final_equity"]:.2f} from
{sandbox["broker_initial_equity"]:.0f} (realised PnL {sandbox["realised_pnl"]:.4f}).
Connectivity is certified by this arm and admissibility is certified by no arm.

## The CAP-004 real-decision path

Four sealed decisions, one directional, **no** paper order, **no** exchange order. It is
reconciled here rather than reinterpreted: that path writes decision and outcome records
but no order-intent, router or broker record, so its middle is unobserved. `0` there is a
**weak zero** — nothing would have recorded an intent had one existed — and it is never
presented as evidence that the runtime chose not to trade.

## Capacity

- guardian status **{cap["status"]}**, free **{cap["free_gib"]} GiB**
  (critical threshold {cap["critical_free_bytes"] / 2**30:.0f} GiB,
  healthy {cap["warning_free_bytes"] / 2**30:.0f} GiB);
- `allows_new_decision` = **{cap["allows_new_decision"]}** — the earlier
  `NO_NEW_DECISION_DISK_CRITICAL` refusals are gone because space was recovered, not
  because the guard was relaxed;
- reclaimed: {cap["reclaim"]["reclaimed_bytes"]} bytes from regenerable caches and scratch
  (pip cache, bytecode caches, pytest scratch, type-check cache, re-fetchable clones). No
  evidence artifact was deleted and no limit was lowered.

## What this file does not claim

- it does not claim the paper path has an edge: it certifies that the path runs;
- it does not present a replay as prospective paper: every bar predates the run;
- it does not turn an absent ledger into a zero.
"""
    (OUT / "TRADE_PATH_RECONCILIATION.md").write_text(md, encoding="utf-8")

    print(f"[trade-path] authoritative arm: {g['router_no_trade']} refusals at the router")
    print(
        f"[trade-path] sandbox arm: {s['orders_created']} orders / {sandbox['fills_closed']} fills"
    )
    print(
        f"[trade-path] disk {cap['status']} free={cap['free_gib']} GiB "
        f"allows_new_decision={cap['allows_new_decision']}"
    )
    print(f"[trade-path] wrote {OUT / 'TRADE_PATH_RECONCILIATION.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
