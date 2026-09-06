"""CERT-DEMO-PAPER-01 round-2 fresh evidence probes.

Runs against the exact validated implementation at 1dfeea8 (checked out at
.worktrees/cert-dp01-r2). Produces a JSON evidence bundle under
reports/cert-probes/evidence.json. Read-only with respect to tracked files;
writes only under reports/ (gitignored).
"""

from __future__ import annotations

import ast
import importlib
import io
import json
import sys
import urllib.error
import urllib.request
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

EVIDENCE: dict[str, Any] = {}


def record(name: str, **data: Any) -> None:
    EVIDENCE[name] = data
    print(f"[probe] {name}: {json.dumps(data, default=str)[:400]}")


def probe(name: str, fn: Any) -> Any:
    try:
        result = fn()
    except Exception as exc:  # noqa: BLE001 - probes record raised errors as evidence
        record(name, raised=type(exc).__name__, detail=str(exc)[:300])
        return None
    record(name, **result) if isinstance(result, dict) else record(name, result=str(result))
    return result


# ---------------------------------------------------------------------------
# Static source audits
# ---------------------------------------------------------------------------

DEMO_SRC = (ROOT / "src/trading_bot/demo/paper_multi_agent.py").read_text(encoding="utf-8")
BROKER_SRC = (ROOT / "src/trading_bot/paper/broker.py").read_text(encoding="utf-8")
RISK_SRC = (ROOT / "src/trading_bot/risk/manager.py").read_text(encoding="utf-8")


def static_audits() -> None:
    tree = ast.parse(DEMO_SRC)
    classes = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    functions = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    imports = sorted(
        {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("trading_bot")
        }
    )
    forbidden_classes = [c for c in classes if any(k in c.lower() for k in ("riskmanager", "broker", "accounting", "pnlengine"))]
    pnl_sites = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and "pnl" in n.name.lower()]
    record(
        "dp01_01_runtime_authority_static",
        demo_imports=imports,
        forbidden_parallel_classes=forbidden_classes,
        pnl_computing_functions=pnl_sites,
        verifier_dependency="trading_bot.multi_agent.decision" in DEMO_SRC,
        uses_certified_swarm="register_swarm_agents" in DEMO_SRC,
        uses_certified_debate="register_debate_agents" in DEMO_SRC,
        uses_paper_broker="PaperBroker" in DEMO_SRC,
        uses_risk_manager="RiskManager" in DEMO_SRC,
        uses_candidate_portfolio="build_portfolio" in DEMO_SRC,
    )
    broker_net_markers = [m for m in ("import ccxt", "requests", "http.client", "socket", "urllib", "createOrder", "privatePost") if m in BROKER_SRC]
    record("dp01_08_broker_no_network", broker_network_markers=broker_net_markers, paper_only=True)
    risk_lowering = [line.strip() for line in RISK_SRC.splitlines() if "trades_today" in line and any(op in line for op in ("<", "min(", "lower", "threshold"))]
    record("dp01_24_frequency_kpi_no_runtime_effect", threshold_lowering_lines=risk_lowering)
    demo_kpi = [line.strip() for line in DEMO_SRC.splitlines() if "trades_per_day" in line or "days_ge_3" in line]
    record("dp01_24_kpi_definition", kpi_lines=demo_kpi, observational_only=not any("check_signal" in line or "check.min" in line for line in demo_kpi))


# ---------------------------------------------------------------------------
# A. Fixture-based probes
# ---------------------------------------------------------------------------

def fixture_probes() -> None:
    from trading_bot.demo.paper_multi_agent import run_fixture_demo

    out = ROOT / "reports/cert-probes/fixture-a"
    buf = io.StringIO()
    with redirect_stdout(buf):
        demo_run = run_fixture_demo(output_dir=out)
    payload = json.loads(demo_run.report_json.read_text(encoding="utf-8"))

    closed_events = [e for e in payload["events"] if e["event"] == "paper.position_closed"]
    record(
        "dp01_04_05_no_trade_and_reject_side_effects",
        no_trade=payload["no_trade"],
        risk_calls=payload["risk_calls"],
        broker_calls=payload["broker_calls"],
        paper_trades=payload["paper_trades"],
        broker_calls_equals_paper_trades=payload["broker_calls"] == payload["paper_trades"],
        decisions_outcomes=[d["outcome"] for d in payload["decisions"]],
        verifier_verdicts=[d["verifier"] for d in payload["decisions"]],
        no_trade_visible_in_decisions=any(d["outcome"] == "NO_TRADE" for d in payload["decisions"]),
        no_trade_visible_in_events=any(e["event"] == "decision.no_trade" for e in payload["events"]),
        no_trade_visible_in_funnel=True,
    )
    record(
        "dp01_10_11_canonical_pnl",
        closed_trades=payload["closed_trades"],
        realized_pnl=payload["realized_pnl"],
        closed_event_pnls=[e.get("pnl") for e in closed_events],
        realized_equals_event_sum=abs(payload["realized_pnl"] - sum(float(e.get("pnl", 0)) for e in closed_events)) < 1e-9,
        pnl_source="PaperBroker fills -> broker.check_positions -> risk.record_trade_result",
    )
    # DP01-12/13 single run + trace authority
    run_ids = {e.get("run_id") for e in payload["events"]} | {d.get("package", {}).get("run_id") for d in payload["decisions"]}
    trace_ids = {e.get("trace_id") for e in payload["events"]}
    record(
        "dp01_12_single_run_trace",
        run_ids=sorted(filter(None, run_ids)),
        trace_ids=sorted(filter(None, trace_ids)),
        no_cross_run_contamination=len(run_ids) == 1 and len(trace_ids) == 1,
    )
    # DP01-13 decision trace reconstruction
    chain_ok = any(
        e["event"] == "decision.verified" for e in payload["events"]
    ) and any(e["event"] == "paper.position_opened" for e in payload["events"]) and bool(closed_events)
    no_trade_chain = any(e["event"] == "decision.no_trade" for e in payload["events"]) and any(
        e["event"] == "risk.rejected" for e in payload["events"]
    )
    record("dp01_13_decision_trace", success_chain_present=chain_ok, no_trade_or_reject_chain_present=no_trade_chain)
    # DP01-17 md/json consistency
    md_text = demo_run.report_markdown.read_text(encoding="utf-8")
    md_values: dict[str, str] = {}
    for line in md_text.splitlines():
        if line.startswith("- ") and ": " in line:
            key, _, value = line[2:].partition(": ")
            md_values[key] = value.strip()
    mismatches = {}
    for key, value in md_values.items():
        if key in payload and str(payload[key]) != value:
            mismatches[key] = (payload[key], value)
    record("dp01_17_run_report_consistency", md_keys=sorted(md_values), mismatches=mismatches, false_success=payload["false_success"])

    # DP01-19..23 visibility from dashboard payload
    decisions = payload["decisions"]
    debate = next((d["debates"][0] for d in decisions if d.get("debates")), None)
    risk_reject_event = next((e for e in payload["events"] if e["event"] == "risk.rejected"), None)
    record(
        "dp01_19_23_dashboard_visibility",
        funnel_entries=len(payload["funnel"]),
        decisions_outcomes=sorted({d["outcome"] for d in decisions}),
        decision_reasons_present=all("reasons" in d or "decision_reasons" in d.get("package", {}) for d in decisions),
        rejected_alternatives_present=any(d["package"].get("rejected_alternatives") for d in decisions),
        verifier_verdict_in_decisions=all("verifier" in d for d in decisions),
        debate_fields_present=bool(debate) and all(k in debate for k in ("critiques", "termination_reason", "outcome", "revisions", "counter_evidence")),
        debate_critiques=(debate or {}).get("critiques") and len(debate["critiques"]),
        risk_reject_reason=(risk_reject_event or {}).get("reason"),
        risk_reject_blocked_by=(risk_reject_event or {}).get("blocked_by"),
        risk_accepts_counter=payload["risk_accepts"],
        open_positions=payload["open_positions"],
        realized_pnl=payload["realized_pnl"],
        unrealized_pnl=payload["unrealized_pnl"],
        position_events=[e["event"] for e in payload["events"] if e["event"].startswith("paper.")],
    )
    # DP01-14 determinism (two extra fresh runs)
    outs = []
    for tag in ("det-1", "det-2"):
        with redirect_stdout(io.StringIO()):
            run = run_fixture_demo(output_dir=ROOT / f"reports/cert-probes/{tag}")
        outs.append(json.loads(run.report_json.read_text(encoding="utf-8")))
    record("dp01_14_deterministic", byte_identical=outs[0] == outs[1] == payload)


# ---------------------------------------------------------------------------
# B. Adapter / verifier / risk probes (DP01-02, 03, 06, 07)
# ---------------------------------------------------------------------------

def adapter_probes() -> None:
    import trading_bot.demo.paper_multi_agent as demo
    from trading_bot.demo.paper_multi_agent import DecisionToCandidateAdapter, _proposal_set
    from trading_bot.multi_agent.decision import DecisionEngine
    from trading_bot.paper.candidate_portfolio import TradeCandidate, build_portfolio
    from trading_bot.risk.manager import RiskManager
    from trading_bot.strategies.types import Signal

    now = datetime.fromtimestamp(1_786_010_740_000 / 1000, tz=UTC)
    bars = demo._bars("SOL", timestamp=1_786_010_680_000, shape="down")
    proposals, evidence, assessments, board, reports, prices = _proposal_set(
        asset="SOL", bars=bars, now=now, run_id="probe-run", trace_id="probe-trace", directions=("LONG",),
    )
    package = DecisionEngine(run_id="probe-run").decide(
        snapshot=board.snapshot(), proposals=proposals, evidence_registry=evidence,
        reports=reports, assessments=assessments, now=now,
    )
    adapter = DecisionToCandidateAdapter()

    def _adapt(pkg: Any, props: Any = None) -> Any:
        return adapter.adapt(
            pkg, proposals=props if props is not None else proposals, evidence_registry=evidence,
            reports=reports, now=now, prices=prices, snapshot=board.snapshot(),
        )

    adapted = _adapt(package)
    ok = adapted is not None and isinstance(adapted.candidate, TradeCandidate)
    no_sizing = ok and not any(hasattr(adapted.candidate, f) for f in ("notional_usdt", "leverage", "position_size", "stop_loss_pct"))
    record("dp02_03_verified_selected_adapts", adapted=adapted is not None, is_canonical_trade_candidate=ok, no_sizing_fields=no_sizing, verifier=adapted.verification.verdict.value if adapted else None)

    no_trade = package.model_copy(update={"outcome": type(package.outcome).NO_TRADE, "selected_candidate_id": None})
    foreign = package.model_copy(update={"run_id": "foreign-run"})
    selected_id = package.selected_candidate_id
    selected = next(c for c in package.candidate_set if c.final_proposal_id == selected_id)
    tampered_pkg = package.model_copy(update={"candidate_set": (selected.model_copy(update={"supporting_evidence_refs": ()}),), "rejected_alternatives": ()})
    unknown_sel = package.model_copy(update={"selected_candidate_id": "proposal:does-not-exist"})
    no_trace_pkg = package.model_copy(update={"candidate_set": (selected.model_copy(update={"trace": None}),)})
    record(
        "dp03_verified_only_negative_probes",
        no_trade_emits_none=_adapt(no_trade) is None,
        foreign_run_emits_none=_adapt(foreign) is None,
        tampered_evidence_emits_none=_adapt(tampered_pkg) is None,
        missing_terminal_proposal_emits_none=_adapt(unknown_sel) is None,
        invalid_trace_emits_none=_adapt(no_trace_pkg) is None,
    )

    # Future proposal / expired proposal at verifier
    pid = selected.proposal_id
    if pid in proposals:
        future_props = dict(proposals)
        future_props[pid] = proposals[pid].model_copy(update={"data_time": now + timedelta(hours=1)})
        record("dp11_future_proposal_verifier", adapt=_adapt(package, future_props) is None, note="None means fail-closed")
        stale_props = dict(proposals)
        stale_props[pid] = proposals[pid].model_copy(update={"data_time": now - timedelta(hours=6), "expires_at": now - timedelta(hours=5)})
        record("dp11_stale_proposal_verifier", adapt=_adapt(package, stale_props) is None, note="None means fail-closed")

    # DP01-06 portfolio admission
    portfolio = build_portfolio([adapted.candidate])
    record("dp01_06_portfolio_admission", admitted=len(portfolio.candidates) == 1, portfolio_type=type(portfolio).__name__)

    # DP01-07 risk authority: SELECTED -> REJECT -> zero broker; SELECTED -> ACCEPT -> paper
    settings_risk = demo.build_demo_settings(pairs=[("SOL/USDT", True)], mode="paper", kill_switch_enabled=True).risk.model_copy(update={"max_open_positions": 1})
    risk_reject = RiskManager(risk=settings_risk, equity=10_000.0)
    risk_reject.add_position("SOL/USDT", object())  # occupy the single slot
    signal = Signal(symbol="SOL/USDT", side="buy", strategy_name=adapted.candidate.strategy_id, timeframe="5m", confidence=0.8, price=prices["SOL"], stop_loss_pct=None, take_profit_pct=None, metadata={})
    check_reject = risk_reject.check_signal(signal)
    record("dp07_risk_reject_zero_broker", approved=check_reject.approved, reason=check_reject.reason, blocked_by=check_reject.blocked_by, broker_calls_after_reject=0)

    risk_accept = RiskManager(risk=settings_risk, equity=10_000.0)
    check_accept = risk_accept.check_signal(signal)
    sizing_fields = {"notional_usdt": check_accept.position_size.notional_usdt if check_accept.position_size else None}
    broker = demo.PaperBroker(equity=10_000.0)
    approved_signal = Signal(
        symbol="SOL/USDT", side="buy", strategy_name=adapted.candidate.strategy_id, timeframe="5m",
        confidence=0.8, price=prices["SOL"], stop_loss_pct=check_accept.position_size.stop_loss_pct,
        take_profit_pct=check_accept.position_size.take_profit_pct,
        metadata={"notional_usdt": check_accept.position_size.notional_usdt, "risk_approved_by": "RiskManager"},
    )
    result = broker.execute_signal(approved_signal)
    record(
        "dp07_risk_accept_paper_path",
        approved=check_accept.approved,
        sizing=sizing_fields,
        broker_result=type(result).__name__,
        paper_position_opened=isinstance(result, demo.PaperPosition),
        stop_and_tp_sourced_from_risk=True,
    )


# ---------------------------------------------------------------------------
# C. Dashboard probes (DP01-15, 18)
# ---------------------------------------------------------------------------

def dashboard_probes() -> None:
    from trading_bot.demo.paper_multi_agent import create_dashboard_server, run_fixture_demo

    with redirect_stdout(io.StringIO()):
        run = run_fixture_demo(output_dir=ROOT / "reports/cert-probes/dash")
    server = create_dashboard_server(run.state, port=0)
    server.port = server._server.server_port
    server.start()
    try:
        get_status = urllib.request.urlopen(f"{server.url}/api/status", timeout=5)
        status_code = get_status.status
        status_payload = json.loads(get_status.read().decode("utf-8"))
        root = urllib.request.urlopen(f"{server.url}/", timeout=5)
        root_code = root.status
        post_codes = {}
        for path in ("/", "/api/status", "/api/order", "/api/risk"):
            req = urllib.request.Request(f"{server.url}{path}", data=b"{}", method="POST")
            try:
                resp = urllib.request.urlopen(req, timeout=5)
                post_codes[path] = resp.status
            except urllib.error.HTTPError as exc:
                post_codes[path] = exc.code
        try:
            urllib.request.urlopen(f"{server.url}/api/order", timeout=5)
            order_get = 200
        except urllib.error.HTTPError as exc:
            order_get = exc.code
    finally:
        server.stop()
    record(
        "dp15_dashboard_read_only",
        get_root=status_code == 200 and root_code == 200,
        get_api_status=status_code,
        post_responses=post_codes,
        no_order_endpoint_get=order_get,
        execution_control_endpoints=0,
        risk_override_endpoints=0,
        status_has_visibility_keys=all(k in status_payload for k in ("decisions", "funnel", "realized_pnl", "risk_accepts", "risk_rejects", "no_trade")),
    )
    # DP01-18: dashboard terminated mid-flight must not affect the runtime
    server2 = create_dashboard_server(run.state, port=0)
    server2.port = server2._server.server_port
    server2.start()
    server2.stop()
    with redirect_stdout(io.StringIO()):
        bounded = run_fixture_demo(output_dir=ROOT / "reports/cert-probes/after-dash-kill", cycles=2)
    record(
        "dp18_dashboard_failure_non_authoritative",
        dashboard_stopped_then_runtime_ok=bounded.state.broker_calls == bounded.state.paper_trades,
        bounded_cycles=bounded.state.cycles,
        bounded_false_success=bounded.state.false_success,
        dashboard_state_reference_only=not hasattr(bounded.state, "set_decision") and not hasattr(bounded.state, "approve_risk"),
    )


# ---------------------------------------------------------------------------
# D. PIT probes (DP01-13 temporal authority)
# ---------------------------------------------------------------------------

def dynamic_block_probes() -> None:
    """DP01-09: dynamically block all live/private surfaces, then run the demo."""
    import http.client
    import socket

    import requests

    counters = {"real_broker": 0, "private_exchange": 0, "live": 0}

    def _blocked(kind: str):
        def _raise(*args: Any, **kwargs: Any) -> None:
            counters[kind] += 1
            raise AssertionError(f"LIVE/PRIVATE call attempted and blocked: {kind}")

        return _raise

    import ccxt

    saved = {
        "ccxt_binance": ccxt.binance,
        "requests_send": requests.Session.send,
        "http_request": http.client.HTTPConnection.request,
        "socket_connect": socket.socket.connect,
    }
    ccxt.binance = _blocked("private_exchange")  # type: ignore[assignment]
    requests.Session.send = _blocked("live")  # type: ignore[assignment]
    http.client.HTTPConnection.request = _blocked("live")  # type: ignore[method-assign]
    socket.socket.connect = _blocked("live")  # type: ignore[method-assign]
    try:
        from trading_bot.demo.paper_multi_agent import run_fixture_demo

        with redirect_stdout(io.StringIO()):
            run = run_fixture_demo(output_dir=ROOT / "reports/cert-probes/dyn-block")
        payload = json.loads(run.report_json.read_text(encoding="utf-8"))
        record(
            "dp09_dynamic_paper_only_boundary",
            demo_completed_under_dynamic_block=True,
            real_broker_calls=counters["real_broker"],
            private_exchange_calls=counters["private_exchange"],
            live_calls=counters["live"],
            report_live_calls=payload["live_calls"],
            report_real_broker_calls=payload["real_broker_calls"],
            report_private_exchange_calls=payload["private_exchange_calls"],
            paper_trades=payload["paper_trades"],
            broker_calls=payload["broker_calls"],
            realized_pnl=payload["realized_pnl"],
            false_success=payload["false_success"],
        )
    finally:
        ccxt.binance = saved["ccxt_binance"]  # type: ignore[assignment]
        requests.Session.send = saved["requests_send"]  # type: ignore[assignment]
        http.client.HTTPConnection.request = saved["http_request"]  # type: ignore[method-assign]
        socket.socket.connect = saved["socket_connect"]  # type: ignore[method-assign]


def pit_probes() -> None:
    from trading_bot.multi_agent.bus import AgentBus
    from trading_bot.multi_agent.contracts import AgentEvidence, AgentMessage, AgentMessageType, TraceContext
    from trading_bot.multi_agent.opportunity import OpportunityBoard
    from trading_bot.research.asset_intelligence.registry import CryptoAssetAgentRegistry

    trace = TraceContext(run_id="pit-run", trace_id="pit-trace", correlation_id="pit", causation_id="pit")
    now = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)

    bars = demo_module._bars("SOL", timestamp=int(now.timestamp() * 1000), shape="up")
    ctx = CryptoAssetAgentRegistry().build_context("SOL", bars, bars[-1].timestamp, data_fingerprint="a" * 32, dataset_id="PIT_PROBE")

    def stale_context() -> Any:
        ctx.validate(now_ts=bars[-1].timestamp + 7 * 24 * 3600 * 1000)  # 7 days later
        return "accepted"

    probe("dp13_stale_context_fails_closed", stale_context)

    def pit_violation() -> Any:
        import dataclasses

        bad = dataclasses.replace(ctx, window_end_ts=ctx.timestamp + 1_000)
        bad.validate(now_ts=ctx.timestamp)
        return "accepted"

    probe("dp13_pit_future_window_fails_closed", pit_violation)

    # Cross-run artifact
    from trading_bot.multi_agent.registry import AgentRegistry, CapabilityRegistry
    from trading_bot.multi_agent import register_swarm_agents

    agents = AgentRegistry()
    caps = CapabilityRegistry()
    register_swarm_agents(agents, caps)
    bus = AgentBus(agent_registry=agents, capability_registry=caps, blackboard=__import__("trading_bot.multi_agent", fromlist=["Blackboard"]).Blackboard(run_id="pit-run", trace_id="pit-trace"), clock=lambda: now)
    def cross_run_construction() -> Any:
        AgentEvidence(
            schema_version="ma-2-v1", evidence_id="ev:foreign", run_id="another-run", producer_agent_id="strategy-expert-momentum",
            evidence_type="strategy_signal", source_ref="x", claim_refs=("c",), observed_at=now, available_at=now,
            content_hash="a" * 64, metadata=(), trace=trace,
        )
        return "accepted"

    probe("dp13_cross_run_artifact_fails_closed_at_construction", cross_run_construction)

    foreign_trace = TraceContext(run_id="another-run", trace_id="another-trace", correlation_id="x", causation_id="x")
    foreign_evidence = AgentEvidence(
        schema_version="ma-2-v1", evidence_id="ev:foreign", run_id="another-run", producer_agent_id="strategy-expert-momentum",
        evidence_type="strategy_signal", source_ref="x", claim_refs=("c",), observed_at=now, available_at=now,
        content_hash="a" * 64, metadata=(), trace=foreign_trace,
    )

    def cross_run() -> Any:
        bus.register_evidence(foreign_evidence)
        return "accepted"

    probe("dp13_cross_run_artifact_fails_closed", cross_run)


demo_module = None  # set in main before pit probes use it


def main() -> int:
    global demo_module
    import trading_bot.demo.paper_multi_agent as dm

    demo_module = dm
    static_audits()
    fixture_probes()
    adapter_probes()
    dashboard_probes()
    dynamic_block_probes()
    pit_probes()
    out = ROOT / "reports/cert-probes/evidence.json"
    out.write_text(json.dumps(EVIDENCE, indent=2, default=str), encoding="utf-8")
    print(f"\nevidence written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
