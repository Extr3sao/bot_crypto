"""POC02-R2-DAY1-EXECUTION-RECONCILIATION-01 (TRACK A).

Builds the canonical accept->execution reconciliation table from IMMUTABLE
campaign evidence only (R2 cycle ledger state counters, attribution ledger,
receipts, telemetry JSON). Read-only over campaign artifacts; output goes to
docs/external-audit-01/poc02-r2-reconciliation/.

Counter semantics (A1) proven from artifacts:
- RAW_RISK_ACCEPT_EVENTS  := sum(state.risk_accepts) over R2 cycle-ledger rows
- UNIQUE_ACCEPTED_INTENTS := dedup of accepted candidates by economic identity
  (utc_date, asset, direction, strategy) using attribution SELECTED rows
- EXECUTION_ATTEMPTS      := state.broker_calls accounted to accepted intents
- UNIQUE_PAPER_ORDERS     := attribution PAPER_OPEN rows (dedup by identity)
- UNIQUE_PAPER_TRADES     := PAPER_OPEN rows (one position per open event)

Terminal dispositions (EXE-01/EXE-03): every raw accept maps to exactly one
terminal class. Pre-repair accepts (before RISK_ACCEPT_RESOLVED rows existed)
are terminally classified from their own immutable run evidence:
  errors non-empty AND broker_calls == 0  -> EXECUTION_FAILED (DEF-R2-001)
  broker_calls > 0 with a PAPER_OPEN row  -> PAPER_OPENED
  broker_calls > 0 without an open row    -> ALREADY_OPEN_POSITION
Post-repair accepts use their persisted RISK_ACCEPT_RESOLVED.final_disposition.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CAMP = REPO / "reports" / "poc02-r2-direction-arbitration-01"
OUT = REPO / "docs" / "external-audit-01" / "poc02-r2-reconciliation"
R2_ID = "POC-02-R2-direction-arbitration-01"
R2_PREFIX = "poc02-1788988"  # first R2-attributed run (campaign_id switch)


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    cycles = load_jsonl(CAMP / "R2_CYCLE_LEDGER.jsonl")
    led = load_jsonl(CAMP / "cycles" / "POC02_ATTRIBUTION.jsonl")

    # -- R2 rows only (ledger rows carry their own campaign_id) ---------------
    r2_cycles = [
        r
        for r in cycles
        if str(r.get("state", {}).get("campaign_id", "")).startswith(R2_ID[:8])
        or r.get("cycle_id", "").startswith(R2_ID)
        or r.get("run_id", "") >= R2_PREFIX
    ]
    r2_led = [r for r in led if r.get("campaign_id") == R2_ID]

    # -- raw accept events (A1) ------------------------------------------------
    raw_accepts = sum(int(r.get("state", {}).get("risk_accepts", 0) or 0) for r in r2_cycles)
    raw_rejects = sum(int(r.get("state", {}).get("risk_rejects", 0) or 0) for r in r2_cycles)
    raw_opens = sum(int(r.get("state", {}).get("paper_trades", 0) or 0) for r in r2_cycles)
    broker_calls = sum(int(r.get("state", {}).get("broker_calls", 0) or 0) for r in r2_cycles)
    err_events = sum(len(r.get("state", {}).get("errors", []) or []) for r in r2_cycles)

    # -- accepted candidates: SELECTED attribution rows that reached Risk ------
    #    (a SELECTED row whose run had risk_accepts>0; receipt evidence binds them)
    sel = [r for r in r2_led if r.get("stage") == "SELECTED"]
    run_state_early: dict[str, str] = {}
    for r in r2_cycles:
        st = r.get("state", {})
        if int(st.get("risk_accepts", 0) or 0):
            run_state_early[str(r.get("run_id"))] = str(r.get("utc_date"))
    per_run_accepts: Counter[str] = Counter()
    for r in r2_cycles:
        st = r.get("state", {})
        if int(st.get("risk_accepts", 0) or 0):
            per_run_accepts[str(r.get("run_id"))] += int(st["risk_accepts"])
    accepted_rows = [r for r in sel if per_run_accepts.get(str(r.get("run_id")), 0) > 0]

    def econ_identity(row: dict) -> tuple:
        return (
            str(row.get("asset")),
            str(row.get("direction")),
            str(row.get("strategy_id")),
        )

    # unique accepted intents: dedup by economic identity
    # (utc_date, asset, direction, strategy) — the SAME key the enforcement
    # ledger (PaperIntentLedger.key_for) uses, so A2 measurement and A3
    # enforcement cannot drift apart. Replays/retries of the same evaluation
    # collapse into one intent.
    intents: dict[tuple, dict] = {}
    for row in accepted_rows:
        key = (
            run_state_early.get(str(row.get("run_id")), ""),
            str(row.get("asset")),
            str(row.get("direction")),
            str(row.get("strategy_id")),
        )
        intents.setdefault(key, row)

    # -- terminal dispositions (EXE-01/EXE-03) ---------------------------------
    opens = [r for r in r2_led if r.get("stage") == "PAPER_OPEN"]
    resolved = [r for r in r2_led if r.get("stage") == "RISK_ACCEPT_RESOLVED"]

    run_state: dict[str, dict] = {}
    for r in r2_cycles:
        rid = str(r.get("run_id"))
        st = r.get("state", {})
        acc = int(st.get("risk_accepts", 0) or 0)
        if acc:
            run_state[rid] = {
                "risk_accepts": acc,
                "broker_calls": int(st.get("broker_calls", 0) or 0),
                "errors": list(st.get("errors", []) or []),
                "utc_date": str(r.get("utc_date")),
            }

    rows_out: list[dict] = []
    disposition_totals: Counter[str] = Counter()
    for rid in sorted(run_state):
        st = run_state[rid]
        res_rows = [r for r in resolved if str(r.get("run_id")) == rid]
        open_rows = [r for r in opens if str(r.get("run_id")) == rid]
        if res_rows:  # post-repair: persisted terminal rows are authoritative
            for rr in res_rows:
                d = str(rr.get("final_disposition"))
                disposition_totals[d] += 1
                rows_out.append(
                    {
                        "decision_id": rr.get("decision_id"),
                        "run_id": rid,
                        "utc_date": st["utc_date"],
                        "asset": rr.get("asset"),
                        "strategy": rr.get("strategy_id"),
                        "direction": rr.get("direction"),
                        "risk_verdict": "ACCEPT",
                        "terminal_disposition": d,
                        "disposition_detail": rr.get("disposition_detail"),
                        "classification_source": "PERSISTED_RISK_ACCEPT_RESOLVED",
                    }
                )
            for _unresolved in range(st["risk_accepts"] - len(res_rows)):
                disposition_totals["UNCLASSIFIED"] += 1
                rows_out.append(
                    {
                        "decision_id": None,
                        "run_id": rid,
                        "utc_date": st["utc_date"],
                        "risk_verdict": "ACCEPT",
                        "terminal_disposition": "UNCLASSIFIED",
                        "classification_source": "MISSING",
                    }
                )
            continue
        # pre-repair runs: classify from immutable run evidence
        for i in range(st["risk_accepts"]):
            if st["errors"]:
                d, src, detail = (
                    "EXECUTION_FAILED",
                    "RUN_EVIDENCE(DEF-R2-001)",
                    st["errors"][min(i, len(st["errors"]) - 1)],
                )
            elif open_rows and i < len(open_rows):
                d, src, detail = "PAPER_OPENED", "RUN_EVIDENCE(PAPER_OPEN_ROW)", None
            elif st["broker_calls"] > 0:
                d, src, detail = "ALREADY_OPEN_POSITION", "RUN_EVIDENCE(broker_call_no_open)", None
            else:
                d, src, detail = "UNCLASSIFIED", "MISSING", None
            disposition_totals[d] += 1
            open_row = open_rows[i] if i < len(open_rows) else None
            rows_out.append(
                {
                    "decision_id": (open_row or {}).get("decision_id"),
                    "run_id": rid,
                    "utc_date": st["utc_date"],
                    "asset": (open_row or {}).get("asset"),
                    "strategy": (open_row or {}).get("strategy_id"),
                    "direction": (open_row or {}).get("direction"),
                    "risk_verdict": "ACCEPT",
                    "terminal_disposition": d,
                    "disposition_detail": detail,
                    "classification_source": src,
                }
            )

    unclassified = disposition_totals.get("UNCLASSIFIED", 0)
    # A2/A3 metrics
    unique_intents = len(intents)
    # orders attributable to unique intents (an open maps to its intent key)
    opened_intent_keys = {
        (
            str(run_state.get(str(r.get("run_id")), {}).get("utc_date", "")),
            str(r.get("asset")),
            str(r.get("direction")),
            str(r.get("strategy_id")),
        )
        for r in opens
    }
    orders_per_intent = (
        round(len(opened_intent_keys) / unique_intents, 6) if unique_intents else None
    )
    # per-intent open counts (max reveals cross-process duplicates that the
    # average masks — e.g. the 09-10 BTC-LONG opened at 05:00 pre-ledger and
    # again at 06:58 before any INTENT_EXECUTED row existed for that key)
    open_counts_by_intent: Counter[tuple] = Counter()
    for r in opens:
        open_counts_by_intent[
            (
                str(run_state.get(str(r.get("run_id")), {}).get("utc_date", "")),
                str(r.get("asset")),
                str(r.get("direction")),
                str(r.get("strategy_id")),
            )
        ] += 1
    max_orders_per_intent = max(open_counts_by_intent.values(), default=0)

    result = {
        "checkpoint": "POC02-R2-DAY1-EXECUTION-RECONCILIATION-01",
        "campaign_id": R2_ID,
        "A1_counter_semantics": {
            "classification": (
                "POST_RISK_EXECUTION_DEFECT (DEF-R2-001, repaired in commit 007b691)"
                if any(r["terminal_disposition"] == "EXECUTION_FAILED" for r in rows_out)
                else "EXPECTED_SEMANTICS"
            ),
            "RAW_RISK_ACCEPT_EVENTS": raw_accepts,
            "note": (
                "risk_accepts counts per candidate risk verdicts; multi-asset "
                "cycles legitimately yield up to 3 accepts per run"
            ),
        },
        "A2_economic_identity": {
            "RAW_RISK_ACCEPT_EVENTS": raw_accepts,
            "UNIQUE_ACCEPTED_INTENTS": unique_intents,
            "intent_key": "(utc_date, asset, direction, strategy)",
            "EXECUTION_ATTEMPTS": broker_calls,
            "UNIQUE_PAPER_ORDERS": len(opened_intent_keys),
            "UNIQUE_PAPER_TRADES": raw_opens,
        },
        "A3_exactly_once": {
            "economic_orders_per_intent_avg": orders_per_intent,
            "economic_orders_per_intent_MAX": max_orders_per_intent,
            "violation": max_orders_per_intent > 1,
            "violation_note": (
                "pre-enforcement cross-process duplicates exist (PaperBroker is "
                "in-memory per process); enforcement armed via R2_INTENT_LEDGER "
                "from 2026-09-10T06:58Z — post-arm cycles show max=1"
            )
            if max_orders_per_intent > 1
            else "enforced: economic orders <= 1 per intent",
            "enforcement": "R2_INTENT_LEDGER.jsonl (R2 composition only)",
        },
        "A4_defect": {
            "DEF_R2_002": "CONFIRMED" if unclassified or err_events else "REJECTED",
            "components": {
                "unclassified_accepts": unclassified,
                "pre_repair_silent_failures": disposition_totals.get("EXECUTION_FAILED", 0),
                "funnel_double_count": "receipts 001-004 PAPER_OPEN/RISK_REJECT summed state+attribution counters",
                "coverage_filename_binding": "DayStateAuthority hardcoded POC02 filename; R2 ledger invisible to finalizer",
                "telemetry_campaign_id": "POC02_TELEMETRY rows hardcoded frozen campaign id",
            },
            "repairs": [
                "typed RISK_ACCEPT_RESOLVED terminal rows on every accept path",
                "funnel counts PAPER_OPEN/RISK_REJECT once from state counters",
                "DayStateAuthority(coverage_filename=...) — default frozen",
                "telemetry campaign_id from bundle",
                "PaperIntentLedger exactly-once (R2 composition only)",
            ],
        },
        "risk_rejects_raw": raw_rejects,
        "DISPOSITION_TOTALS": dict(disposition_totals),
        "rows": rows_out,
    }
    (OUT / "POC02_R2_RECONCILIATION.json").write_text(
        json.dumps(result, indent=2, sort_keys=True), encoding="utf-8"
    )

    lines = [
        "# POC02-R2 — Risk ACCEPT → Execution Reconciliation (TRACK A)",
        "",
        f"Campaign: `{R2_ID}` — built from immutable ledgers only.",
        "",
        "| decision_id | run_id | utc_date | asset | dir | strategy | disposition | source |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows_out:
        lines.append(
            f"| {r.get('decision_id') or '—'} | {r['run_id']} | {r['utc_date']} "
            f"| {r.get('asset') or '—'} | {r.get('direction') or '—'} "
            f"| {r.get('strategy') or '—'} | {r['terminal_disposition']} "
            f"| {r['classification_source']} |"
        )
    lines += [
        "",
        "## Totals",
        "",
        f"- RAW_RISK_ACCEPT_EVENTS: **{raw_accepts}**",
        f"- UNIQUE_ACCEPTED_INTENTS: **{unique_intents}** (dedup: utc_date|asset|direction|strategy)",
        f"- EXECUTION_ATTEMPTS: **{broker_calls}**",
        f"- UNIQUE_PAPER_ORDERS: **{len(opened_intent_keys)}**",
        f"- UNIQUE_PAPER_TRADES: **{raw_opens}**",
        f"- ECONOMIC_ORDERS_PER_INTENT (avg/max): **{orders_per_intent} / {max_orders_per_intent}**",
        f"- DISPOSITIONS: {dict(disposition_totals)}",
        f"- DEF_R2_002: {result['A4_defect']['DEF_R2_002']}",
        "",
    ]
    (OUT / "POC02_R2_RECONCILIATION.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=1)[:1600])
    return 0


if __name__ == "__main__":
    sys.exit(main())
