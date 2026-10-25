"""RFC-048V — runtime authority verification (real flow, not a private harness).

The question this script answers: can the futures risk plane be REACHED from the
real decision boundary, and can anything it says be turned into an order?

It does not call the engine and stop there. It takes the 31 recorded decisions
of the offline run, rebuilds the exact ``DecisionRequest`` packets the
autonomous runtime builds (real ``RiskReview``, real ``DecisionRequest``, real
``TradeProposal``) and runs the REAL ``DecisionEngine.decide``/``intend`` on
them. It then attacks the boundary:

* a veto stays a veto (advisory and binding paths both tested);
* an engine error becomes a BINDING veto (fail-safe, not fail-open);
* incomplete data is refused;
* a live-route request is refused and the futures modules contain no code that
  can reach a venue;
* an offline approval is never an order permission.

    uv run python scripts/rfc048v_runtime_authority.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trading_bot.autonomous.contracts import (  # noqa: E402
    AdmissionStatus,
    DecisionMode,
    EdgeEvidence,
    RiskVerdict,
)
from trading_bot.autonomous.decision import DecisionEngine  # noqa: E402
from trading_bot.risk.futures.contracts import (  # noqa: E402
    CostStatus,
    Direction,
    RejectionCode,
    RiskDecision,
    RiskDecisionCode,
)
from trading_bot.risk.futures.integration import (  # noqa: E402
    build_decision_request_from_review,
    run_engine_through_runtime,
    safe_review,
    to_risk_review,
)

DATA = ROOT / "data" / "rfc048"
FUZZY = ROOT / "src" / "trading_bot" / "risk" / "futures"

#: Tokens that would give the futures plane a route to a venue or a credential.
#: They are checked as CODE patterns (imports/calls), not as prose.
FORBIDDEN_PATTERNS = {
    "http_client_import": r"^\s*(import|from)\s+(requests|httpx|aiohttp|urllib|websockets?)\b",
    "socket_import": r"^\s*(import|from)\s+socket\b",
    "subprocess_import": r"^\s*(import|from)\s+subprocess\b",
    "exchange_client_import": r"^\s*(import|from)\s+trading_bot\.(execution|market_data|brokers?)\b",
    "place_order_call": r"\b(place_order|flash_close|create_order|cancel_order|submit_order)\s*\(",
    "credential_read": r"\b(api_key|api_secret|apiKey|secret_key|private_key|BITUNIX_API)\b",
    "broker_call": r"\.(execute|broker|place)\w*\s*\(",
}
#: Words that legitimately appear in comments/strings and must NOT be flagged.
FORBIDDEN_IGNORE_LINES = ("no live route", "live_route_requested", "order_authorised")


def git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
        ).stdout.strip()
    except OSError:  # pragma: no cover
        return ""


# ---------------------------------------------------------------------------
# recorded decisions → real RiskDecision objects
# ---------------------------------------------------------------------------


def decision_from_dict(payload: dict[str, Any]) -> RiskDecision:
    return RiskDecision(
        decision_id=payload["decision_id"],
        run_id=payload["run_id"],
        instrument_id=payload["instrument_id"],
        proposed_direction=Direction(payload["proposed_direction"]),
        requested_notional=float(payload["requested_notional"]),
        approved_notional=float(payload["approved_notional"]),
        requested_leverage=float(payload["requested_leverage"]),
        effective_leverage=float(payload["effective_leverage"]),
        required_margin=float(payload["required_margin"]),
        risk_budget=float(payload["risk_budget"]),
        modeled_worst_loss=float(payload["modeled_worst_loss"]),
        liquidation_buffer_bps=payload["liquidation_buffer_bps"],
        fees_estimate=float(payload["fees_estimate"]),
        funding_estimate=float(payload["funding_estimate"]),
        data_timestamp_ms=int(payload["data_timestamp_ms"]),
        decision_timestamp_ms=int(payload["decision_timestamp_ms"]),
        policy_version=str(payload["policy_version"]),
        decision=RiskDecisionCode(payload["decision"]),
        rejection_reasons=tuple(RejectionCode(r) for r in payload["rejection_reasons"]),
        evidence=tuple(payload.get("evidence", ())),
        quantity=float(payload.get("quantity", 0.0)),
        entry_price=float(payload.get("entry_price", 0.0)),
        stop_price=payload.get("stop_price"),
        liquidation_price=payload.get("liquidation_price"),
        maintenance_margin=float(payload.get("maintenance_margin", 0.0)),
        cost_status=CostStatus(payload.get("cost_status", "COST_UNKNOWN")),
        order_authorised=bool(payload.get("order_authorised", False)),
    )


def packet_for(decision: RiskDecision, *, binding: bool = False, admitted: bool = False) -> Any:
    review = to_risk_review(decision)
    if binding:
        review = replace(review, advisory=False)
    request = build_decision_request_from_review(
        review=review,
        stop_price=decision.stop_price,
        cost_scenario_id=decision.decision_id,
        size_usd_hint=decision.approved_notional or decision.requested_notional,
        strategy_id="rfc048_offline_probe",
        run_id=decision.run_id,
        decision_id=decision.decision_id,
        asset="BTC",
        symbol="BTCUSDT",
        direction=decision.proposed_direction.value,
        entry_reference=decision.entry_price or 82_500.0,
        expected_gross_edge_bps=40.0,
        expected_cost_bps=12.0,
        # The runtime contract requires market_time_ms <= decision_time_ms; a
        # recorded DATA_INVALID case can carry the reverse on purpose, so the
        # packet is built with the runtime-legal ordering (the risk verdict is
        # carried by the review, not by the packet's clock).
        market_time_ms=min(decision.data_timestamp_ms, decision.decision_timestamp_ms),
        holistic_time_ms=max(decision.data_timestamp_ms, decision.decision_timestamp_ms),
        admission_status=AdmissionStatus.RESEARCH_REQUIRED,
        admitted_for_paper=False,
    )
    if admitted:
        # The adapter deliberately cannot build an admitted packet (that is what
        # keeps RFC-048 out of the paper book). This probe patches the admission
        # on AFTERWARDS, only to prove that an ORDER-AUTHORISING packet cannot
        # swallow an advisory futures veto. The edge evidence is declared an
        # assumption, never a result.
        request = replace(
            request,
            admission=replace(
                request.admission,
                status=AdmissionStatus.PAPER_CANDIDATE,
                admitted_for_paper=True,
                edge_evidence=EdgeEvidence(
                    source_doc="data/rfc048/RFC048_SYNTHETIC_EDGE.md",
                    metric="synthetic_probe_edge_bps",
                    value_bps=40.0,
                    knowledge="ASSUMPTION",
                    sample_trades=0,
                    evidence_class="ASSUMPTION",
                    status="NOT_A_TRADING_SIGNAL",
                ),
            ),
        )
    return request, review


# ---------------------------------------------------------------------------
# A. reachability: every recorded decision through the REAL DecisionEngine
# ---------------------------------------------------------------------------


def reachability_flow() -> dict[str, Any]:
    recorded = json.loads((DATA / "RISK_SCENARIOS.json").read_text(encoding="utf-8"))
    engine = DecisionEngine()
    rows: list[dict[str, Any]] = []
    for case in recorded["cases"]:
        decision = decision_from_dict(case["decision"])
        request, review = packet_for(decision)
        intent = engine.intend(request)
        final = engine.decide(request)
        rows.append(
            {
                "scenario": case["scenario"],
                "engine_decision": decision.decision.value,
                "review_verdict": review.verdict.value,
                "review_advisory": review.advisory,
                "review_source": review.source,
                "intent_mode": intent.mode.value,
                "intent_classification": intent.classification,
                "final_mode": final.mode.value,
                "final_classification": final.classification,
                "final_order_authorised": final.order_authorised,
                "futures_decision_order_authorised": decision.order_authorised,
            }
        )
    approved = [
        row
        for row in rows
        if row["engine_decision"]
        in (
            "APPROVE_SIMULATION",
            "REDUCE_SIMULATED_SIZE",
        )
    ]
    return {
        "cases": rows,
        "case_count": len(rows),
        "approved_count": len(approved),
        "reached_the_real_decision_engine": True,
        "any_order_authorised": any(
            row["final_order_authorised"] or row["futures_decision_order_authorised"]
            for row in rows
        ),
        "any_review_lost": any(
            not row["review_source"].startswith("FuturesRiskEngine") for row in rows
        ),
        "advisory_everywhere": all(row["review_advisory"] for row in rows),
    }


# ---------------------------------------------------------------------------
# B. a veto stays a veto
# ---------------------------------------------------------------------------


def veto_irreversibility() -> dict[str, Any]:
    engine = DecisionEngine()
    cases: list[dict[str, Any]] = []
    probe = RiskDecision(
        decision_id="RA-VETO-1",
        run_id="RA-RUN",
        instrument_id="BINANCE_USDM_BTCUSDT_PERP",
        proposed_direction=Direction.LONG,
        requested_notional=400.0,
        approved_notional=0.0,
        requested_leverage=5.0,
        effective_leverage=0.0,
        required_margin=0.0,
        risk_budget=2.0,
        modeled_worst_loss=0.0,
        liquidation_buffer_bps=None,
        fees_estimate=0.0,
        funding_estimate=0.0,
        data_timestamp_ms=1_791_582_761_730,
        decision_timestamp_ms=1_791_582_762_730,
        policy_version="RFC048-FUTURES-RISK-POLICY-v1",
        decision=RiskDecisionCode.RISK_VETO,
        rejection_reasons=(RejectionCode.LIQUIDATION_BEFORE_STOP,),
    )
    for label, decision in (
        ("RISK_VETO", probe),
        (
            "DATA_INVALID",
            replace(
                probe,
                decision=RiskDecisionCode.DATA_INVALID,
                rejection_reasons=(RejectionCode.STALE_DATA,),
            ),
        ),
        (
            "UNSUPPORTED_INSTRUMENT",
            replace(
                probe,
                decision=RiskDecisionCode.UNSUPPORTED_INSTRUMENT,
                rejection_reasons=(RejectionCode.CONTRACT_TYPE_NOT_IMPLEMENTED,),
            ),
        ),
    ):
        # binding path: the veto must block
        binding_request, binding_review = packet_for(decision, binding=True)
        binding_result = engine.decide(binding_request)
        # advisory path on a non-authorising packet: legal, and still no order
        advisory_request, advisory_review = packet_for(decision, binding=False)
        advisory_result = engine.decide(advisory_request)
        # advisory path on an ORDER-AUTHORISING packet must raise, never pass
        admitted_request, _ = packet_for(decision, binding=False, admitted=True)
        raised: str | None = None
        admitted_result_mode: str | None = None
        try:
            admitted_result = engine.decide(admitted_request)
            admitted_result_mode = admitted_result.mode.value
        except ValueError as exc:
            raised = str(exc)
        cases.append(
            {
                "decision": label,
                "binding": {
                    "mode": binding_result.mode.value,
                    "classification": binding_result.classification,
                    "order_authorised": binding_result.order_authorised,
                    "review_advisory": binding_review.advisory,
                },
                "advisory": {
                    "mode": advisory_result.mode.value,
                    "classification": advisory_result.classification,
                    "order_authorised": advisory_result.order_authorised,
                    "review_advisory": advisory_review.advisory,
                },
                "advisory_on_order_authorising_packet": {
                    "raised": raised,
                    "mode_if_not_raised": admitted_result_mode,
                },
            }
        )
    all_block = all(
        row["binding"]["mode"] == DecisionMode.NO_TRADE.value
        and row["binding"]["classification"] == "RISK_VETO"
        and row["binding"]["order_authorised"] is False
        for row in cases
    )
    all_raise_or_none = all(
        row["advisory_on_order_authorising_packet"]["raised"] is not None
        or row["advisory_on_order_authorising_packet"]["mode_if_not_raised"] == "NO_TRADE"
        for row in cases
    )
    return {
        "cases": cases,
        "veto_always_blocks_when_binding": all_block,
        "advisory_can_never_sit_on_an_order": all_raise_or_none,
        "verdict": "PASS" if all_block and all_raise_or_none else "FAIL",
    }


# ---------------------------------------------------------------------------
# C. an engine error is a safe rejection
# ---------------------------------------------------------------------------


def engine_error_fail_safe() -> dict[str, Any]:
    def explode() -> RiskDecision:  # never returns; the annotation satisfies the caller's contract
        raise RuntimeError("simulated engine failure")

    def packet_for_review(review: Any, *, admitted: bool) -> Any:
        request = build_decision_request_from_review(
            review=review,
            stop_price=82_087.5,
            cost_scenario_id="RA-ERROR",
            size_usd_hint=82.5,
            strategy_id="rfc048_offline_probe",
            run_id="RA-RUN",
            decision_id="RA-ERROR-1",
            asset="BTC",
            symbol="BTCUSDT",
            direction="LONG",
            entry_reference=82_500.0,
            expected_gross_edge_bps=40.0,
            expected_cost_bps=12.0,
            market_time_ms=1_791_582_761_730,
            holistic_time_ms=1_791_582_762_730,
            admission_status=AdmissionStatus.RESEARCH_REQUIRED,
            admitted_for_paper=False,
        )
        if admitted:
            request = replace(
                request,
                admission=replace(
                    request.admission,
                    status=AdmissionStatus.PAPER_CANDIDATE,
                    admitted_for_paper=True,
                    edge_evidence=EdgeEvidence(
                        source_doc="data/rfc048/RFC048_SYNTHETIC_EDGE.md",
                        metric="synthetic_probe_edge_bps",
                        value_bps=40.0,
                        knowledge="ASSUMPTION",
                        sample_trades=0,
                        evidence_class="ASSUMPTION",
                        status="NOT_A_TRADING_SIGNAL",
                    ),
                ),
            )
        return request

    review = safe_review(explode)
    nominal_result = run_engine_through_runtime(
        evaluate=explode, build=lambda r: packet_for_review(r, admitted=False)
    )
    admitted_result = run_engine_through_runtime(
        evaluate=explode, build=lambda r: packet_for_review(r, admitted=True)
    )
    return {
        "review": {
            "verdict": review.verdict.value,
            "advisory": review.advisory,
            "evaluated": review.evaluated,
            "rule": review.rule,
            "reason": review.reason,
        },
        "nominal_packet": {
            "mode": nominal_result.mode.value,
            "classification": nominal_result.classification,
            "order_authorised": nominal_result.order_authorised,
        },
        "order_authorising_packet": {
            "mode": admitted_result.mode.value,
            "classification": admitted_result.classification,
            "order_authorised": admitted_result.order_authorised,
            "notional_usdt": admitted_result.notional_usdt,
        },
        "verdict": (
            "PASS"
            if review.advisory is False
            and review.verdict is RiskVerdict.VETO
            and nominal_result.mode is DecisionMode.NO_TRADE
            and admitted_result.mode is DecisionMode.NO_TRADE
            and admitted_result.order_authorised is False
            else "FAIL"
        ),
    }


# ---------------------------------------------------------------------------
# D. incomplete data is refused
# ---------------------------------------------------------------------------


def incomplete_data() -> dict[str, Any]:
    engine = DecisionEngine()
    absent_mark = RiskDecision(
        decision_id="RA-DATA-1",
        run_id="RA-RUN",
        instrument_id="BINANCE_USDM_BTCUSDT_PERP",
        proposed_direction=Direction.LONG,
        requested_notional=400.0,
        approved_notional=0.0,
        requested_leverage=5.0,
        effective_leverage=0.0,
        required_margin=0.0,
        risk_budget=2.0,
        modeled_worst_loss=0.0,
        liquidation_buffer_bps=None,
        fees_estimate=0.0,
        funding_estimate=0.0,
        data_timestamp_ms=1_791_582_761_730,
        decision_timestamp_ms=1_791_582_762_730,
        policy_version="RFC048-FUTURES-RISK-POLICY-v1",
        decision=RiskDecisionCode.DATA_INVALID,
        rejection_reasons=(RejectionCode.MISSING_MARK_PRICE,),
    )
    request, review = packet_for(absent_mark, binding=True)
    result = engine.decide(request)
    return {
        "review_verdict": review.verdict.value,
        "mode": result.mode.value,
        "classification": result.classification,
        "order_authorised": result.order_authorised,
        "verdict": (
            "PASS"
            if result.mode is DecisionMode.NO_TRADE and result.order_authorised is False
            else "FAIL"
        ),
    }


# ---------------------------------------------------------------------------
# E. the live route is blocked and nothing can reach a venue
# ---------------------------------------------------------------------------


def live_path_blocked() -> dict[str, Any]:
    """Two independent arguments: the engine refuses, and the code cannot dial out."""
    scan_rows: list[dict[str, Any]] = []
    violations: list[dict[str, str]] = []
    files = sorted(FUZZY.glob("*.py")) + sorted(
        (ROOT / "src" / "trading_bot" / "risk").glob("futures_*.py")
    )
    for path in files:
        text = path.read_text(encoding="utf-8")
        hits: list[str] = []
        for name, pattern in FORBIDDEN_PATTERNS.items():
            for line in text.splitlines():
                if any(ignore in line for ignore in FORBIDDEN_IGNORE_LINES):
                    continue
                if re.search(pattern, line):
                    hits.append(f"{name}: {line.strip()[:90]}")
        scan_rows.append(
            {
                "file": str(path.relative_to(ROOT)).replace("\\", "/"),
                "lines": len(text.splitlines()),
                "forbidden_hits": hits,
            }
        )
        violations.extend({"file": str(path), "hit": hit} for hit in hits)
    # the engine-level refusal
    from trading_bot.risk.futures import (
        RiskProposal,
        ScenarioRequest,
        load_instrument_registry,
    )
    from trading_bot.risk.futures.engine import FuturesRiskEngine

    spec = load_instrument_registry(DATA / "INSTRUMENTS.json").get("BINANCE_USDM_BTCUSDT_PERP")
    proposal_sample = json.loads((DATA / "RISK_SCENARIOS.json").read_text(encoding="utf-8"))[
        "cases"
    ][0]["detail"]["proposal"]
    proposal = RiskProposal(
        run_id="RA-LIVE",
        decision_id="RA-LIVE-1",
        instrument_id="BINANCE_USDM_BTCUSDT_PERP",
        direction=Direction.LONG,
        entry_price=float(proposal_sample["entry_price"]),
        stop_price=float(proposal_sample["stop_price"]),
        requested_notional=400.0,
        requested_leverage=5.0,
        horizon_minutes=60.0,
        data_timestamp_ms=int(proposal_sample["data_timestamp_ms"]),
        decision_timestamp_ms=int(proposal_sample["decision_timestamp_ms"]),
        mark_price=float(proposal_sample["mark_price"]),
        live_route_requested=True,
    )
    snapshot_payload = json.loads((DATA / "RISK_SCENARIOS.json").read_text(encoding="utf-8"))[
        "cases"
    ][0]["detail"]["portfolio"]
    from trading_bot.risk.futures import PortfolioSnapshot

    snapshot = PortfolioSnapshot(
        snapshot_id="RA-LIVE-SNAP",
        timestamp_ms=int(snapshot_payload["timestamp_ms"]),
        equity=float(snapshot_payload["equity"]),
        free_margin=float(snapshot_payload["free_margin"]),
        reserved_margin=float(snapshot_payload["reserved_margin"]),
    )
    market = json.loads((DATA / "MARKET_SNAPSHOT.json").read_text(encoding="utf-8"))
    outcome = FuturesRiskEngine(spec=spec).decide(
        ScenarioRequest(
            proposal=proposal,
            snapshot=snapshot,
            market={
                "mark_price": market["mark_price"],
                "spread_bps": market["spread_bps"],
                "depth": {"bids": market["depth_bids"], "asks": market["depth_asks"]},
            },
            funding_observations=[],
        )
    )
    engine_refused = (
        outcome.decision.decision is RiskDecisionCode.RISK_VETO
        and RejectionCode.LIVE_ROUTE_ATTEMPTED in outcome.decision.rejection_reasons
    )
    return {
        "engine_refuses_live_route": engine_refused,
        "engine_decision": outcome.decision.decision.value,
        "engine_reasons": [r.value for r in outcome.decision.rejection_reasons],
        "source_scan": {
            "files": scan_rows,
            "file_count": len(scan_rows),
            "violations": violations,
        },
        "verdict": "PASS" if engine_refused and not violations else "FAIL",
    }


# ---------------------------------------------------------------------------
# F. offline approvals are not order permissions
# ---------------------------------------------------------------------------


def approvals_are_not_permissions() -> dict[str, Any]:
    recorded = json.loads((DATA / "RISK_SCENARIOS.json").read_text(encoding="utf-8"))
    rows = []
    for case in recorded["cases"]:
        payload = case["decision"]
        if payload["decision"] not in ("APPROVE_SIMULATION", "REDUCE_SIMULATED_SIZE"):
            continue
        rows.append(
            {
                "scenario": case["scenario"],
                "decision": payload["decision"],
                "order_authorised": payload["order_authorised"],
                "approved_notional": payload["approved_notional"],
            }
        )
    return {
        "approved_decisions": rows,
        "approved_count": len(rows),
        "any_order_authorised": any(row["order_authorised"] for row in rows),
        "verdict": (
            "PASS" if rows and not any(row["order_authorised"] for row in rows) else "FAIL"
        ),
    }


def main() -> int:
    started = time.time()
    reach = reachability_flow()
    veto = veto_irreversibility()
    error = engine_error_fail_safe()
    data = incomplete_data()
    live = live_path_blocked()
    approvals = approvals_are_not_permissions()

    verdicts = {
        "runtime_reachability": "PASS"
        if not reach["any_order_authorised"] and not reach["any_review_lost"]
        else "FAIL",
        "veto_irreversibility": veto["verdict"],
        "engine_error_fail_safe": error["verdict"],
        "incomplete_data_refused": data["verdict"],
        "live_path_blocked": live["verdict"],
        "approvals_are_not_order_permissions": approvals["verdict"],
    }
    conclusion = "PASS" if all(v == "PASS" for v in verdicts.values()) else "FAIL"
    report: dict[str, Any] = {
        "schema_version": "rfc048v-runtime-authority-verification-v1",
        "rfc": "RFC-048V",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "current_head": git("rev-parse", "HEAD"),
        "duration_seconds": round(time.time() - started, 3),
        "entrypoint": {
            "decision_authority": "trading_bot.autonomous.decision.DecisionEngine.decide",
            "runtime_call_site": "src/trading_bot/autonomous/runtime.py (self._decision_engine.decide)",
            "flow": (
                "TradeProposal -> FuturesRiskEngine -> RiskDecision -> RiskReview "
                "-> DecisionRequest -> DecisionEngine -> SHADOW_TRADE / NO_TRADE"
            ),
            "note": (
                "the futures review is advisory by construction; the runtime only "
                "lets a BINDING review gate an order-authorising packet, and it "
                "refuses an advisory review on one"
            ),
        },
        "verdicts": verdicts,
        "conclusion": conclusion,
        "runtime_reachability": reach,
        "veto_irreversibility": veto,
        "engine_error_fail_safe": error,
        "incomplete_data": data,
        "live_path": live,
        "approvals": approvals,
        "governance": {
            "live_trading": "DISABLED",
            "trades_authorised": 0,
            "orders_emitted": 0,
        },
    }
    (DATA / "RUNTIME_AUTHORITY_VERIFICATION.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# RFC-048V — Runtime Authority Verification",
        "",
        f"- Head: `{report['current_head'][:12]}` · {report['generated_at_utc']}",
        f"- Verdict: **{conclusion}**",
        "",
        "## Verdicts",
        "",
        "| check | result |",
        "| --- | --- |",
    ]
    for name, value in verdicts.items():
        lines.append(f"| `{name}` | {value} |")
    lines += [
        "",
        "## Flow (31 recorded decisions through the real DecisionEngine)",
        "",
        f"- cases: {reach['case_count']} (approved simulated: {reach['approved_count']})",
        f"- reviews lost on the way in: {reach['any_review_lost']}",
        f"- order authorised anywhere: {reach['any_order_authorised']}",
        f"- every review advisory: {reach['advisory_everywhere']}",
        "",
        "## A veto cannot be turned into an approval",
        "",
    ]
    for row in veto["cases"]:
        lines.append(
            f"- `{row['decision']}`: binding -> {row['binding']['mode']}"
            f" ({row['binding']['classification']}); advisory on an order-authorising"
            f" packet -> {row['advisory_on_order_authorising_packet']['raised'] or row['advisory_on_order_authorising_packet']['mode_if_not_raised']}"
        )
    lines += [
        "",
        "## Engine error = safe rejection",
        "",
        f"- fail-safe review: verdict `{error['review']['verdict']}`, advisory"
        f" `{error['review']['advisory']}`, evaluated `{error['review']['evaluated']}`",
        f"- nominal packet -> {error['nominal_packet']['mode']}"
        f" ({error['nominal_packet']['classification']})",
        f"- order-authorising packet -> {error['order_authorising_packet']['mode']}"
        f" ({error['order_authorising_packet']['classification']})",
        "",
        "## Live route",
        "",
        f"- engine refuses a live-route request: `{live['engine_refuses_live_route']}`",
        f"- files scanned for order/credential/http patterns: {live['source_scan']['file_count']}",
        f"- forbidden hits: {live['source_scan']['violations'] or 'none'}",
        "",
        "## Offline approvals are not permissions",
        "",
        f"- approved decisions checked: {approvals['approved_count']}",
        f"- any `order_authorised=True`: {approvals['any_order_authorised']}",
        "",
    ]
    (DATA / "RUNTIME_AUTHORITY_VERIFICATION.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"verdicts: {json.dumps(verdicts)}")
    print(f"reachability cases: {reach['case_count']}  approved: {reach['approved_count']}")
    print(f"live scan violations: {len(live['source_scan']['violations'])}")
    print(f"conclusion: {conclusion}")
    return 0 if conclusion == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
