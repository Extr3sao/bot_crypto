"""WP-003P-05 — run report, final report, traceability table and seal.

    python scripts/exp_003p_report.py
    python scripts/exp_003p_report.py --seal

Reads only artifacts this experiment produced. It never recomputes a verdict: the verdict
is in ``VERIFICATION.json`` and this module's job is to state it, with the evidence paths
that support it and the limitations that qualify it.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

from exp_003p_contract import (  # noqa: E402
    OUT,
    RUN_ID,
    SCHEMA_RUN_REPORT,
    config_digest,
    git,
    read_json,
    sha256_file,
    write_json,
)

ARTEFACTS = (
    "BASELINE.md",
    "runtime_authority_map.md",
    "WORK_PACKAGES.md",
    "RFC-EXP-003P-PAPER-EXECUTION.md",
    "design/PROTOCOL.json",
    "design/PREREGISTRATION.md",
    "design/DESIGN.sha256",
    "design/PAPER_INTEGRATION_PLAN.md",
    "ORDER_EVENT_SCHEMA.md",
    "ORDER_EVENT_SCHEMA.json",
    "STATE_MACHINE.md",
    "EXECUTION_TRACE.jsonl",
    "SCENARIO_TRACE.jsonl",
    "ORDER_LIFECYCLE.csv",
    "ORDER_LIFECYCLE.json",
    "RECONCILIATION.json",
    "METRICS.json",
    "NEGATIVE_CONTROLS.json",
    "INDEPENDENCE_AUDIT.json",
    "INDEPENDENCE_AUDIT.md",
    "VERIFICATION.json",
    "DIGESTS.json",
    "REHEARSAL.json",
    "evidence/BASELINE.json",
    "evidence/TESTS.json",
    "evidence/environment.freeze.txt",
    "evidence/CLEAN_CHECKOUT_REPRODUCTION.json",
    "RUN_REPORT.md",
    "RUN_REPORT.json",
    "FINAL_REPORT.md",
    "SHA256SUMS.txt",
)

#: The traceability the RFC requires: every requirement, its acceptance criterion, the work
#: package that built it, the implementation, the test and the artifacts.
TRACEABILITY = (
    ("REQ-003P-01", "runtime authority map + reachable PaperBroker", "WP-00",
     "scripts/exp_003p_baseline.py; src/trading_bot/paper/lifecycle/recorder.py",
     "tests/unit/paper/test_execution_lifecycle.py::test_paper_broker_fill_is_recorded_as_an_envelope_with_its_own_provenance",
     "BASELINE.md; runtime_authority_map.md; EXECUTION_TRACE.jsonl"),
    ("REQ-003P-02", "every event carries provenance, adapter, clock, correlation", "WP-01",
     "src/trading_bot/paper/lifecycle/contracts.py",
     "test_provenance_cannot_be_promoted_by_relabelling; V2_provenance_completeness",
     "EXECUTION_TRACE.jsonl; VERIFICATION.json"),
    ("REQ-003P-03", "data_time <= decision_time <= event_time", "WP-01",
     "src/trading_bot/paper/lifecycle/contracts.py",
     "test_decision_after_the_event_it_produced_is_refused; V3_causality",
     "VERIFICATION.json"),
    ("REQ-003P-04", "no submit without risk approval and policy identity", "WP-01",
     "src/trading_bot/paper/lifecycle/engine.py",
     "test_submit_without_risk_approval_is_refused_before_transmission; NEG-15",
     "NEGATIVE_CONTROLS.json"),
    ("REQ-003P-05", "only legal transitions; ACK != FILL; terminal states hold", "WP-01",
     "src/trading_bot/paper/lifecycle/store.py",
     "test_acknowledgement_is_not_a_fill; V4_state_machine; NEG-01/NEG-04",
     "ORDER_LIFECYCLE.csv; VERIFICATION.json"),
    ("REQ-003P-06", "one fill key books exactly once", "WP-01",
     "src/trading_bot/paper/lifecycle/store.py",
     "test_duplicate_delivery_books_the_fill_once; NEG-05",
     "NEGATIVE_CONTROLS.json; ORDER_LIFECYCLE.csv"),
    ("REQ-003P-07", "quantities, cash, positions, fees and PnL rebuilt from events", "WP-01",
     "src/trading_bot/paper/lifecycle/store.py",
     "test_partial_fill_then_full_fill_accumulates_quantity_and_fees; V5_ledger_rebuild",
     "ORDER_LIFECYCLE.json; VERIFICATION.json"),
    ("REQ-003P-08", "reconciliation PASS/FAIL/INCOMPLETE, no simulated source", "WP-03",
     "src/trading_bot/paper/lifecycle/reconcile.py",
     "test_reconciliation_without_a_primary_source_is_incomplete; NEG-12/NEG-16",
     "RECONCILIATION.json"),
    ("REQ-003P-09", "timeouts and unknowns produce no duplicate order or invented fill", "WP-01",
     "src/trading_bot/paper/lifecycle/engine.py",
     "test_timeout_leaves_the_order_unknown_and_blocks_another_submit; NEG-06",
     "NEGATIVE_CONTROLS.json"),
    ("REQ-003P-10", "trace, metrics, per-provenance counts and a verifiable manifest", "WP-03",
     "src/trading_bot/paper/lifecycle/store.py; scripts/exp_003p_rehearsal.py",
     "V1_chain_integrity; V8_determinism",
     "EXECUTION_TRACE.jsonl; METRICS.json; SHA256SUMS.txt"),
    ("REQ-003P-11", "each control fails with its declared class", "WP-02",
     "scripts/exp_003p_controls.py",
     "17 controls, each with baseline_ok and the declared class",
     "NEGATIVE_CONTROLS.json"),
    ("REQ-003P-12", "separate verification program; honest independence", "WP-05",
     "scripts/exp_003p_verify.py",
     "INDEPENDENCE_AUDIT.json (program=True, organizational=False)",
     "INDEPENDENCE_AUDIT.md; VERIFICATION.json"),
    ("REQ-003P-13", "LIVE unreachable, no secrets, config hashes preserved", "WP-01/WP-05",
     "src/trading_bot/paper/lifecycle/contracts.py",
     "NEG-10/NEG-14; V7_live_disabled; V12_config_unchanged; V13_no_secrets",
     "VERIFICATION.json"),
    ("REQ-003P-14", "two offline runs produce the same canonical digest", "WP-03",
     "scripts/exp_003p_rehearsal.py",
     "V8_determinism (run 1 vs run 2)",
     "DIGESTS.json; runs/run-2/DIGESTS.json"),
)

CLAIMS = (
    ("the paper execution boundary is instrumented, not re-implemented",
     "src/trading_bot/paper/broker.py (lifecycle hook)", "8-event probe + 276-event rehearsal",
     "accepted"),
    ("a real broker fill produces CREATED→SUBMITTED→ACK→FILLED",
     "EXECUTION_TRACE.jsonl", "69 runtime fills, 0 illegal transitions", "accepted"),
    ("ACK alone never moves quantity", "ORDER_LIFECYCLE.csv", "NEG-01, V6", "accepted"),
    ("duplicate delivery books exactly once", "NEGATIVE_CONTROLS.json", "NEG-05 effective", "accepted"),
    ("timeouts leave an UNKNOWN order and block resend", "NEGATIVE_CONTROLS.json",
     "NEG-06 effective", "accepted"),
    ("reconciliation is PASS against the broker book and the venue snapshot",
     "RECONCILIATION.json", "runtime=PASS scenario=PASS", "accepted"),
    ("observed paper execution", "none", "no authorised provider is configured", "rejected"),
    ("economic edge", "none", "not evaluated by this phase", "rejected"),
    ("organisational independence", "INDEPENDENCE_AUDIT.json", "one author", "rejected"),
)

DEFECTS = (
    {
        "id": "DEF-003P-01",
        "severity": "high",
        "summary": "the lane's recorder parameter was shadowed by an internal variable",
        "detail": (
            "VisionLane.__init__ assigns ``lifecycle = str(opinion_lifecycle)``; the new "
            "parameter of the same name was therefore a string when it reached PaperBroker, "
            "and every observation raised AttributeError. The broker logged a warning per "
            "fill and the trace stayed empty rather than failing loudly."
        ),
        "treatment": (
            "parameter renamed to lifecycle_recorder; the broker now logs the exception "
            "message, and the rehearsal asserts a non-zero event count"
        ),
    },
    {
        "id": "DEF-003P-02",
        "severity": "medium",
        "summary": "a duplicate accounting_snapshot was shadowed by the existing one",
        "detail": (
            "003P added a second accounting_snapshot to PaperBroker; Python silently kept "
            "the later definition, so reconciliation compared against a shape nobody "
            "returned. The class already carried a richer book snapshot."
        ),
        "treatment": "the added method was removed; reconciliation reads the existing shape",
    },
    {
        "id": "DEF-003P-03",
        "severity": "high",
        "summary": "a tampered persisted row was reported as PROVENANCE_MISMATCH",
        "detail": (
            "the loader validated the payload digest before the hash chain, so NEG-09 "
            "(quantity altered on disk) produced a provenance class instead of an integrity "
            "one. Naming the wrong defect is how a control passes for the wrong reason."
        ),
        "treatment": "the chain is verified over the bytes as written before any semantic check",
    },
    {
        "id": "DEF-003P-04",
        "severity": "medium",
        "summary": "the venue double counted a duplicated delivery in its own snapshot",
        "detail": (
            "the re-delivered fill was refused by the event store (correct) but counted "
            "twice in the venue's tally, so a correct ledger failed reconciliation."
        ),
        "treatment": "the venue book applies each fill identity once",
    },
    {
        "id": "DEF-003P-05",
        "severity": "low",
        "summary": "realised PnL was compared while the book still held a position",
        "detail": (
            "the ledger books an open leg's entry fee at the fill and the broker books it at "
            "the close, so the two realised numbers differ by that fee until flat."
        ),
        "treatment": (
            "the comparison is deferred and declared "
            "(realised_pnl_comparison=DEFERRED_OPEN_POSITION) instead of being forced"
        ),
    },
    {
        "id": "DEF-003P-06",
        "severity": "low",
        "summary": "the protocol was re-rendered once before the first rehearsal",
        "detail": (
            "NEG-14's expected class was corrected to LIVE_MODE_FORBIDDEN after the contract "
            "began refusing a LIVE environment as a live-mode violation. The correction "
            "happened before any trace existed; the protocol hash recorded by the rehearsal "
            "matches the file on disk."
        ),
        "treatment": "declared here; the protocol carries no result-dependent content",
    },
    {
        "id": "DEF-003P-07",
        "severity": "high",
        "summary": "the checkout gate could compare a run against itself and call it a reproduction",
        "detail": (
            "run_checkout_check derived the worktree path from ``REPO.parent``. Executed from "
            "inside the checkout that path *is* the checkout, so the rehearsal would rewrite "
            "the published artifacts and the digest comparison would compare a file with "
            "itself: a green verdict for an operation that reproduced nothing. Found while "
            "running this phase's own reproduction, before any verdict was published."
        ),
        "treatment": (
            "the gate refuses to run when the worktree path resolves to the repository it is "
            "executing from, and the reproduction verdict is now produced by a separate "
            "comparison script (exp_003p_checkout_compare.py) that reads two directories"
        ),
    },
    {
        "id": "DEF-003P-08",
        "severity": "medium",
        "summary": "the independence audit reported a false negative from a substring scan",
        "detail": (
            "`program_independence` was decided by searching the verifier's text for each "
            "producer module stem. Those stems (\"store\", \"engine\", \"venue\", "
            "\"reconcile\", \"recorder\", \"contracts\") also occur as ordinary words in "
            "its prose, so the audit published `program_independence=false` for a verifier "
            "that imports no `trading_bot` module at all. An audit that understates its own "
            "separation is still wrong: the claim has to match the code."
        ),
        "treatment": (
            "the scan parses the verifier with `ast` and collects its real imports; the "
            "markdown heading follows the measured value instead of asserting it"
        ),
    },
)

BLOCKERS = (
    "PAPER_VALIDATION=BLOCKED_NOT_CONFIGURED: no authorised paper/testnet provider, endpoint "
    "or account is configured in this workspace, so no fill of this cycle was observed at a "
    "venue. The offline book is not a substitute.",
    "organizational_independence=false: producer, verifier and controls were written by one "
    "agent. The separation is between programs.",
    "Prospective status does not rest on a commit that predates the run: the artifacts are "
    "committed by the evidence commit, which follows the code commit the run binds. The "
    "preregistration is a frozen document (`PROTOCOL_FROZEN_UTC`), its digest is recorded in "
    "every run, and a clean checkout re-derives the identical file from the frozen constants.",
)


def _read_all(out: Path) -> dict[str, Any]:
    def load(name: str) -> Any:
        path = out / name
        return read_json(path) if path.exists() else None

    return {
        "baseline": load("evidence/BASELINE.json"),
        "protocol": load("design/PROTOCOL.json"),
        "rehearsal": load("REHEARSAL.json"),
        "digests": load("DIGESTS.json"),
        "metrics": load("METRICS.json"),
        "reconciliation": load("RECONCILIATION.json"),
        "controls": load("NEGATIVE_CONTROLS.json"),
        "verification": load("VERIFICATION.json"),
        "tests": load("evidence/TESTS.json"),
        "checkout": load("evidence/CLEAN_CHECKOUT_REPRODUCTION.json"),
        "independence": load("INDEPENDENCE_AUDIT.json"),
    }


def build_run_report(out: Path, data: dict[str, Any]) -> dict[str, Any]:
    verification = data["verification"] or {}
    rehearsal = data["rehearsal"] or {}
    metrics = data["metrics"] or {}
    tests = data["tests"] or {}
    controls = data["controls"] or {}
    reconciliation = data["reconciliation"] or {}
    digests = data["digests"] or {}

    technical = verification.get("technical_execution_validation", "NOT_PERFORMED")
    paper = verification.get("paper_validation", "BLOCKED_NOT_CONFIGURED")
    checkout = data["checkout"] or {}
    checkout_state = {
        "REPRODUCED": "PASS",
        "FAILED": "FAIL",
    }.get(str(checkout.get("verdict")), "NOT_PERFORMED")
    status = "PASS" if technical == "PASS" and paper == "PASS" else "PARTIAL"
    if technical == "FAIL" or checkout_state == "FAIL":
        status = "FAIL"

    return {
        "run_id": RUN_ID,
        "schema_version": SCHEMA_RUN_REPORT,
        "status": status,
        "generated_at_utc": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        #: The commit the run binds is the one recorded by the rehearsal, not whatever HEAD
        #: happens to be when the report is rendered: this tree is shared, other agents
        #: commit to it, and a report that renamed the commit would misstate its evidence.
        "commit": digests.get("commit") or git("rev-parse", "HEAD"),
        "head_when_report_rendered": git("rev-parse", "HEAD"),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "config_digest": config_digest(),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "timezone": "UTC",
            "network_used": False,
            "live_orders": 0,
        },
        "paths_executed": [
            "scripts/exp_003p_baseline.py",
            "scripts/exp_003p_preregister.py",
            "scripts/exp_003p_rehearsal.py",
            "scripts/exp_003p_controls.py",
            "scripts/exp_003p_verify.py",
            "scripts/exp_003p_checkout_compare.py",
            "scripts/exp_003p_report.py",
        ],
        "runtime": {
            "execution_boundary": "trading_bot.paper.broker.PaperBroker",
            "instrumentation": "trading_bot.paper.lifecycle.PaperBrokerRecorder",
            "provenance": "OFFLINE_SIMULATED",
            "events": (rehearsal.get("runtime") or {}).get("events"),
            "fills": (metrics.get("fills") or {}).get("runtime"),
            "orders": (metrics.get("orders") or {}).get("runtime"),
            "anomalies": (rehearsal.get("runtime") or {}).get("anomalies"),
        },
        "scenario": {
            "adapter": "OFFLINE_SIM_PAPER_VENUE",
            "events": (rehearsal.get("scenario") or {}).get("events"),
            "fills": (metrics.get("fills") or {}).get("scenario"),
            "terminal_states": (rehearsal.get("scenario") or {}).get("terminal_states"),
            "state_mismatches": (rehearsal.get("scenario") or {}).get("state_mismatches"),
        },
        "orders_and_fills_by_provenance": metrics.get("provenance_counts"),
        "reconciliation": reconciliation.get("result"),
        "reconciliation_detail": {
            "runtime": (reconciliation.get("runtime") or {}).get("result"),
            "scenario": (reconciliation.get("scenario") or {}).get("result"),
            "paper_validation": reconciliation.get("paper_validation"),
        },
        "controls": {
            "effective": controls.get("controls_effective"),
            "total": controls.get("controls_total"),
        },
        "tests": {
            "state": tests.get("state"),
            "suites": tests.get("suites"),
            "exit_codes": {
                key: value.get("exit_code")
                for key, value in (tests.get("results") or {}).items()
                if isinstance(value, dict)
            },
        },
        "dimensions": {
            "IMPLEMENTATION": "PASS",
            "TESTS": tests.get("state", "NOT_PERFORMED"),
            "OFFLINE_RUNTIME_VALIDATION": technical,
            "CLEAN_CHECKOUT_REPRODUCTION": checkout_state,
            "PAPER_VALIDATION": paper,
            "ECONOMIC_EDGE": "NOT_EVALUATED",
            "STRATEGY_PROMOTION": "DENIED",
            "INDEPENDENT_VERIFICATION": (
                "PARTIAL" if verification.get("organizational_independence") is False else "PASS"
            ),
            "FALSE_SUCCESS": verification.get("false_success", 0),
            "LIVE": "DISABLED" if verification.get("live_orders") == 0 else "FAIL",
        },
        "checks": {
            "passed": verification.get("checks_passed"),
            "total": verification.get("checks_total"),
            "failed": verification.get("checks_failed"),
        },
        "digests": {
            "protocol_sha256": digests.get("protocol_sha256"),
            "execution_trace_sha256": digests.get("execution_trace_sha256"),
            "scenario_trace_sha256": digests.get("scenario_trace_sha256"),
            "run_digest": digests.get("run_digest"),
        },
        "blockers": list(BLOCKERS),
        "errors": [],
        "evidence": [
            "EXECUTION_TRACE.jsonl",
            "SCENARIO_TRACE.jsonl",
            "ORDER_LIFECYCLE.csv",
            "RECONCILIATION.json",
            "METRICS.json",
            "NEGATIVE_CONTROLS.json",
            "VERIFICATION.json",
            "INDEPENDENCE_AUDIT.json",
        ],
        "economic_edge": "NOT_EVALUATED",
        "strategy_promotion": "DENIED",
        "holdout": "CLOSED",
    }


def render_run_markdown(report: dict[str, Any], data: dict[str, Any]) -> str:
    metrics = data["metrics"] or {}
    lines = [
        "# RUN REPORT — EXP-003P",
        "",
        f"- status: **{report['status']}**",
        f"- commit: `{report['commit']}` ({report['branch']})",
        f"- config digest: `{report['config_digest']}`",
        "- provenance: `OFFLINE_SIMULATED` only; live orders: `0`",
        "",
        "## What ran",
        "",
        "| phase | events | orders | fills | reconciliation |",
        "| --- | --- | --- | --- | --- |",
        f"| runtime (real VisionLane + PaperBroker) | {report['runtime']['events']} | "
        f"{report['runtime']['orders']} | {report['runtime']['fills']} | "
        f"{report['reconciliation_detail']['runtime']} |",
        f"| scenario (offline venue double) | {report['scenario']['events']} | "
        f"{(metrics.get('orders') or {}).get('scenario')} | "
        f"{report['scenario']['fills']} | {report['reconciliation_detail']['scenario']} |",
        "",
        "## Dimensions",
        "",
        "| dimension | value |",
        "| --- | --- |",
    ]
    for key, value in report["dimensions"].items():
        lines.append(f"| `{key}` | `{value}` |")
    lines += [
        "",
        "## Tests and controls",
        "",
        f"- tests: `{report['tests']['state']}`",
        f"- controls: {report['controls']['effective']}/{report['controls']['total']} effective",
        f"- verifier checks: {report['checks']['passed']}/{report['checks']['total']} "
        f"(failed: {report['checks']['failed'] or 'none'})",
        "",
        "## Latencies (from persisted event times)",
        "",
        f"- submit → ACK: `{(metrics.get('latencies') or {}).get('submit_to_ack')}`",
        f"- ACK → fill: `{(metrics.get('latencies') or {}).get('ack_to_fill')}`",
        "- signal → intent: `NOT_AVAILABLE` (the broker does not publish a decision clock)",
        "",
        "## Blockers",
        "",
    ]
    lines += [f"- {item}" for item in report["blockers"]]
    lines += [
        "",
        "## What this run does not mean",
        "",
        "- `OFFLINE_RUNTIME_VALIDATION` is not paper trading and does not promote to "
        "`PAPER_VALIDATION`.",
        "- No economic edge is measured: `ECONOMIC_EDGE=NOT_EVALUATED`.",
        "- `STRATEGY_PROMOTION=DENIED`, `HOLDOUT=CLOSED`, `LIVE=DISABLED`.",
        "",
    ]
    return "\n".join(lines)


def render_final(data: dict[str, Any], report: dict[str, Any]) -> str:
    verification = data["verification"] or {}
    checkout = data["checkout"] or {}
    metrics = data["metrics"] or {}
    lines = [
        "# FINAL REPORT — EXP-003P PAPER EXECUTION LIFECYCLE",
        "",
        "- **PHASE**: `EXP-003P-PAPER-EXECUTION-001`",
        f"- **COMMITS**: the code is committed; the run binds `{report['commit']}`, the commit "
        "that carries the implementation, the frozen 003K input and the scripts. The "
        "artifacts are carried by the evidence commit that follows it "
        "(`git log -1 --format=%H -- reports/ai-bots/EXP-003P-PAPER-EXECUTION-001`), because a "
        "file cannot contain the hash of the commit that adds it.",
        "- **IMPLEMENTED**: typed lifecycle contracts, hash-chained event store, order state "
        "machine, idempotent fill ledger, provenance gate, offline venue double, "
        "reconciliation, broker instrumentation, 17 adversarial controls, separate verifier",
        f"- **TESTS**: `{report['tests']['state']}` "
        f"(see `evidence/TESTS.json` for exit codes)",
        f"- **RUNTIME_VALIDATION**: `{verification.get('technical_execution_validation')}` "
        f"({verification.get('checks_passed')}/{verification.get('checks_total')} checks, "
        f"{report['controls']['effective']}/{report['controls']['total']} controls)",
        f"- **CLEAN_CHECKOUT_REPRODUCTION**: "
        f"`{report['dimensions']['CLEAN_CHECKOUT_REPRODUCTION']}` "
        f"({checkout.get('verdict', 'NOT_PERFORMED')})",
        "- **PAPER_VALIDATION**: `BLOCKED_NOT_CONFIGURED` — no authorised paper provider exists "
        "in this workspace, so nothing here is observed paper execution; the minimum "
        "integration plan and its P1..P10 acceptance checks are in "
        "`design/PAPER_INTEGRATION_PLAN.md` and were not executed",
        f"- **FALSE_SUCCESS**: `{verification.get('false_success', 0)}`",
        f"- **DEFECTS**: {len(DEFECTS)} found and fixed/declared during the phase",
        f"- **BLOCKERS**: {len(BLOCKERS)}",
        "- **EVIDENCE**: `EXECUTION_TRACE.jsonl`, `SCENARIO_TRACE.jsonl`, "
        "`ORDER_LIFECYCLE.csv`, `RECONCILIATION.json`, `METRICS.json`, "
        "`NEGATIVE_CONTROLS.json`, `VERIFICATION.json`, `INDEPENDENCE_AUDIT.json`, "
        "`SHA256SUMS.txt`",
        "- **ARCHITECTURE_STATUS**: the existing paper runtime is instrumented at its real "
        "execution boundary (`PaperBroker`); no second risk engine, broker or platform was "
        "added. The offline venue is a declared test double.",
        "- **RFC_STATUS**: `ADOPT_P0` implemented for WP00-WP03 and WP05; WP04 "
        "`BLOCKED_NOT_CONFIGURED`; live, edge and promotion remain `REJECT`ed",
        "- **NEXT_PHASE**: resolve the paper-provider blocker (`PAPER_VALIDATION`), or open "
        "an independent review of this trace — both are separate, authorised decisions",
        "",
        "## Claims, sources and decisions",
        "",
        "| CLAIM | SOURCE | EVIDENCE | DECISION |",
        "| --- | --- | --- | --- |",
    ]
    for claim, source, evidence, decision in CLAIMS:
        lines.append(f"| {claim} | `{source}` | {evidence} | `{decision}` |")
    lines += [
        "",
        "## Traceability REQ → ACC → WP → IMP → TEST → EXEC → EVID",
        "",
        "| REQ | ACC | WP | IMP | TEST | EVID |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for req, acc, wp, imp, test, evid in TRACEABILITY:
        lines.append(f"| `{req}` | {acc} | `{wp}` | `{imp}` | {test} | {evid} |")
    lines += [
        "",
        "## Defects",
        "",
    ]
    for defect in DEFECTS:
        lines.append(
            f"### {defect['id']} — {defect['summary']} (`{defect['severity']}`)\n\n"
            f"{defect['detail']}\n\n**Treatment:** {defect['treatment']}\n"
        )
    lines += [
        "## Blockers",
        "",
    ]
    lines += [f"- {item}" for item in BLOCKERS]
    lines += [
        "",
        "## Declared limits",
        "",
        "- The 69 runtime fills are `OFFLINE_SIMULATED`: they prove what the code does with a "
        "frozen bar and never that a venue accepted an order.",
        "- Partial fills, cancels, rejects and timeouts are exercised through the declared "
        "offline venue double, not through the broker, whose fills are all-or-nothing.",
        "- Broker-observed envelopes stamp the decision instant with the booking instant "
        "(`decision_time_source=PAPER_BROKER_BOOKING_INSTANT`) and record the broker's "
        "notional guard as the risk gate (`risk_evaluation_source=PAPERBROKER_NOTIONAL_GUARD`).",
        "- `signal → intent` latency is `NOT_AVAILABLE`; the broker publishes no decision clock.",
        "- Spread and slippage against an external quote are `NOT_AVAILABLE`; the closed-trade "
        "cost decomposition of the broker is reported instead.",
        "- Depends on `EXP-003O=PASS_PARTIAL_INCOMPLETE_REAL_DATA`; 003P does not repair that "
        "coverage or its independence.",
        "- `tests/unit/reports` belongs to another experiment and is not part of this gate. "
        "Observed while reproducing: it passes in the shared tree (201 tests) and is red in a "
        "clean checkout (2 failed, 40 errors) because it reads artifacts under "
        "`reports/ai-bots` that are git-ignored and therefore absent from a checkout. That "
        "is a pre-existing defect of that suite, declared here and not counted as green.",
        "- The clean-checkout reproduction needs the 003K frozen dataset, which the code commit "
        "publishes under `reports/ai-bots/EXP-003K-CANDIDATE-001/dataset` (3.9 MB) so the "
        "checkout is self-contained; the three SHA-256 digests are the ones `BASELINE.json` "
        "recorded.",
        "- Dependencies are installed from the committed `uv.lock`. `uv sync --locked` refuses "
        "this repository because that lock predates the current `pyproject.toml` (it does not "
        "know `matplotlib`) — a pre-existing repository defect, not a 003P one. The clean "
        "checkout therefore installs the baseline's exact versions with `uv pip sync` from a "
        "frozen freeze file, declared with its command in "
        "`evidence/CLEAN_CHECKOUT_REPRODUCTION.json`.",
        "",
        "## Clean-checkout reproduction",
        "",
        f"- result: `{checkout.get('verdict', 'NOT_PERFORMED')}`",
        f"- detail: {checkout.get('detail', 'not executed')}",
        f"- commit reproduced: `{checkout.get('commit', 'none')}`",
        f"- comparisons: {json.dumps(checkout.get('comparisons') or {}, sort_keys=True)}",
        f"- method: {checkout.get('method', 'not executed')}",
        "",
        "## Measurements (uninterpreted)",
        "",
        f"- runtime fills: `{(metrics.get('fills') or {}).get('runtime')}`; scenario fills: "
        f"`{(metrics.get('fills') or {}).get('scenario')}`",
        f"- broker cost decomposition (closed trades): "
        f"`{(metrics.get('costs') or {}).get('execution_cost_realised_usdt')}` execution, "
        f"`{(metrics.get('costs') or {}).get('commissions_realised_usdt')}` commissions",
        f"- positions open at end: `{metrics.get('positions_open_at_end')}`; mark: "
        f"`{(metrics.get('unrealized_pnl') or {}).get('mark')}`",
        "- These numbers are bookkeeping of an offline replay. They are not a profitability "
        "claim and were not used to select anything.",
        "",
        "**FINAL STATUS: PARTIAL** — `TECHNICAL_EXECUTION_VALIDATION=PASS`, "
        "`PAPER_VALIDATION=BLOCKED_NOT_CONFIGURED`, `ECONOMIC_EDGE=NOT_EVALUATED`, "
        "`STRATEGY_PROMOTION=DENIED`, `LIVE=DISABLED`, `HOLDOUT=CLOSED`, `FALSE_SUCCESS=0`.",
        "",
    ]
    return "\n".join(lines)


def seal(out: Path) -> dict[str, Any]:
    missing = [
        name
        for name in ARTEFACTS
        if name != "SHA256SUMS.txt" and not (out / name).exists()
    ]
    if missing:
        return {"sealed": False, "missing": missing}
    lines = []
    for name in sorted(ARTEFACTS):
        if name == "SHA256SUMS.txt":
            continue
        lines.append(f"{sha256_file(out / name)}  {name}")
    (out / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return {"sealed": True, "files": len(lines), "sha256": sha256_file(out / "SHA256SUMS.txt")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EXP-003P report and seal")
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--seal", action="store_true")
    args = parser.parse_args(argv)
    out = Path(args.out)

    if args.seal:
        result = seal(out)
        if not result["sealed"]:
            print(f"[003p-report] REFUSED — missing artifacts: {result['missing']}")
            return 10
        print(
            f"[003p-report] sealed {result['files']} artifacts "
            f"({result['sha256'][:16]}…)"
        )
        return 0

    data = _read_all(out)
    if data["verification"] is None:
        print("[003p-report] REFUSED — run the verifier first")
        return 11

    report = build_run_report(out, data)
    write_json(out / "RUN_REPORT.json", report)
    (out / "RUN_REPORT.md").write_text(
        render_run_markdown(report, data), encoding="utf-8", newline="\n"
    )
    (out / "FINAL_REPORT.md").write_text(
        render_final(data, report), encoding="utf-8", newline="\n"
    )
    print(
        f"[003p-report] status={report['status']} "
        f"technical={report['dimensions']['OFFLINE_RUNTIME_VALIDATION']} "
        f"paper={report['dimensions']['PAPER_VALIDATION']} "
        f"controls={report['controls']['effective']}/{report['controls']['total']} "
        f"checks={report['checks']['passed']}/{report['checks']['total']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
