"""Builders for monitor tests: real ``DecisionTrace`` records, real JSONL files.

The monitor is only allowed to read runtime artifacts, so the tests must produce
the *same* artifacts the runtime produces — hash-chained rows written by
``DecisionTraceStore`` — instead of hand-written JSON that could drift from the
real contract.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from trading_bot.autonomous.contracts import (
    AdmissionStatus,
    CostBreakdown,
    DecisionMode,
    DecisionTrace,
    EdgeEvidence,
    NoTradeKind,
    TradeProposal,
)
from trading_bot.autonomous.trace import DecisionTraceStore

TS0 = 1_792_826_135_240  # the baseline run's market time (2026-10-24T07:15:35Z)
BAR_MS = 5 * 60 * 1000


def considered(
    strategy_id: str = "ema_crossover@5m",
    *,
    emitted: bool = True,
    selected: bool = True,
    gross_bps: float = 8.0,
    admission_status: str = "COST_KILLED",
    router_status: str = "SELECTED",
) -> dict[str, Any]:
    return {
        "strategy_id": strategy_id,
        "admission_status": admission_status,
        "admitted_for_paper": False,
        "emitted_alpha": emitted,
        "expected_gross_edge_bps": gross_bps,
        "lifecycle_verdict": None,
        "router_reason": None if selected else "no_alpha_in_direction:ANY",
        "router_status": router_status,
        "selected": selected,
    }


def proposal(
    *,
    strategy_id: str = "ema_crossover@5m",
    direction: str = "LONG",
    gross_bps: float = 8.0,
    cost_bps: float = 22.8,
    net_bps: float | None = None,
    entry: float = 100.0,
    timeframe: str = "5m",
    confidence: float = 0.42,
    decision_time_ms: int = TS0,
) -> dict[str, Any]:
    """A *real* ``TradeProposal`` serialised the way the runtime serialises it.

    Built from the dataclass (never hand-written JSON) so the trace round-trips:
    a hand-rolled dict would silently break ``DecisionTraceStore.replay`` and the
    test would be validating a shape the runtime never produces.
    """
    net = round(gross_bps - cost_bps, 10) if net_bps is None else net_bps
    return TradeProposal(
        run_id="run-a",
        decision_id="dec",
        asset="BTC",
        symbol="BTC/USDT",
        strategy_id=strategy_id,
        strategy_version="v1",
        family=strategy_id.split("@")[0],
        direction=direction,
        timeframe=timeframe,
        market_time_ms=decision_time_ms,
        decision_time_ms=decision_time_ms,
        entry_reference=entry,
        structural_stop=round(entry * 0.99, 8),
        horizon_minutes=5.0,
        expected_gross_edge_bps=gross_bps,
        expected_cost_bps=cost_bps,
        expected_net_edge_bps=net,
        cost=CostBreakdown(
            scenario_id="unit-test",
            cost_model_version="COST_MODEL_V3",
            size_usd=500.0,
            horizon_minutes=5.0,
            spread_bps=1.0,
            spread_knowledge="OBSERVED",
            fee_bps=10.0,
            slippage_bps=5.0,
            impact_bps=1.0,
            funding_bps=0.0,
            round_trip_bps=cost_bps,
            components=(),
            created_at_ms=TS0,
        ),
        edge_evidence=EdgeEvidence(
            source_doc="docs/STRATEGY_DISCOVERY_V3_RESULTS.json",
            metric="family_5m_diagnostic_zero_cost.gross_bps_per_trade",
            value_bps=gross_bps,
            knowledge="ESTIMATED",
            sample_trades=1500,
            note="unit-test evidence",
            period="unit-test-window",
            timeframe=timeframe,
            status="COST_KILLED",
        ),
        admission_status=AdmissionStatus.COST_KILLED,
        regime="LOW_VOLATILITY",
        confidence=confidence,
        evidence=("admission_ledger:config/strategy_admission.json",),
        counter_evidence=("spread:2.0bps[OBSERVED]",),
        context_fingerprint="sha256:abc123",
    ).to_dict()


def risk(
    verdict: str = "PASS",
    *,
    evaluated: bool = True,
    advisory: bool = True,
    rule: str = "all_limits_pass",
    reason: str = "risk_approved",
    notional: float | None = 500.0,
) -> dict[str, Any]:
    return {
        "verdict": verdict,
        "reason": reason,
        "notional_usdt": notional,
        "source": "RiskManager.check_signal",
        "advisory": advisory,
        "binding": not advisory,
        "risk_evaluated": evaluated,
        "state": "APPROVED" if verdict == "PASS" else "VETOED",
        # real traces name these ``risk_rule`` / ``risk_reason`` / ``risk_result``
        "risk_rule": rule,
        "risk_reason": reason,
        "risk_result": "APPROVED" if verdict == "PASS" else "VETOED",
        "risk_inputs": {"kill_switch_enabled": True, "equity": 10_000.0},
    }


def verification(verdict: str = "PASS", failures: tuple[str, ...] = ()) -> dict[str, Any]:
    return {
        "decision_id": "dec",
        "verdict": verdict,
        "checks": [
            {
                "name": "pit_slice_exact",
                "passed": verdict == "PASS",
                "detail": "119 bars, all <= decision_ts",
            }
        ],
        "failures": list(failures),
        "verifier_version": "independent-verifier-v1",
    }


def make_trace(
    decision_id: str = "dec-1",
    *,
    run_id: str = "run-a",
    symbol: str = "BTC/USDT",
    asset: str = "BTC",
    mode: DecisionMode = DecisionMode.NO_TRADE,
    classification: str = "NO_GROSS_EDGE",
    reason: str = "gross_edge_not_positive:-4.5600bps",
    no_trade_kind: str | None = NoTradeKind.NO_TRADE_STRATEGIC.value,
    proposal_payload: dict[str, Any] | None = None,
    risk_payload: dict[str, Any] | None = None,
    verification_payload: dict[str, Any] | None = None,
    order_created: bool = False,
    errors: tuple[str, ...] = (),
    market_time_ms: int = TS0,
    decision_time_ms: int = TS0,
    created_at_ms: int | None = None,
    strategies: tuple[dict[str, Any], ...] | None = None,
    shadow: dict[str, Any] | None = None,
    venue_price: float = 100.5,
) -> DecisionTrace:
    strategies = strategies or (considered(),)
    if mode is DecisionMode.SHADOW_TRADE and shadow is None:
        shadow = {
            "run_id": run_id,
            "decision_id": decision_id,
            "timestamp_ms": decision_time_ms,
            "asset": asset,
            "strategy_id": "ema_crossover@5m",
            "direction": "LONG",
            "hypothetical_entry": 100.0,
            "expected_edge_bps": 8.0,
            "expected_cost_bps": 22.8,
            "expected_net_edge_bps": -14.8,
            "rejection_reason": "admission=COST_KILLED",
        }
    if no_trade_kind is not None and mode is not DecisionMode.NO_TRADE:
        no_trade_kind = None
    return DecisionTrace(
        run_id=run_id,
        decision_id=decision_id,
        asset=asset,
        symbol=symbol,
        market_time_ms=market_time_ms,
        decision_time_ms=decision_time_ms,
        mode=mode,
        reason=reason,
        classification=classification,
        regime="LOW_VOLATILITY",
        strategies_considered=strategies,
        market_context={
            "last_price": venue_price,
            "market_time_ms": market_time_ms,
            "router_trace": ["context_fresh", "regime=LOW_VOLATILITY"],
        },
        asset_context={"asset": asset},
        proposal=proposal_payload,
        agent_messages=(),
        evidence=("cost_model:COST_MODEL_V3:BINANCE_SPOT_STANDARD_TAKER",),
        counter_evidence=(),
        verification=verification_payload or verification(),
        risk=risk_payload or risk(),
        shadow=shadow,
        cost_model_version="COST_MODEL_V3",
        order_created=order_created,
        orders_created=1 if order_created else 0,
        no_trade_kind=no_trade_kind,
        errors=errors,
        created_at_ms=created_at_ms if created_at_ms is not None else decision_time_ms + 4_000,
    )


def write_run(
    tmp_path: Path,
    traces: list[DecisionTrace],
    *,
    run_id: str = "run-a",
    executions: list[dict[str, Any]] | None = None,
    environment: str = "ccxt:binance",
    timeframe: str = "5m",
    commit: str = "deadbeef",
    heartbeat: bool = True,
) -> Path:
    """Write a realistic run directory (chain sealed by the real store)."""
    run_dir = tmp_path / run_id
    store = DecisionTraceStore(run_dir)
    for trace in traces:
        store.append(trace)
    if executions is not None:
        report = {
            "run_id": run_id,
            "environment": environment,
            "mode": "paper",
            "commit": commit,
            "timeframe": timeframe,
            "executions": executions,
        }
        (run_dir / "RUN_REPORT.json").write_text(json.dumps(report), encoding="utf-8")
        (run_dir / "PAPER_RUN.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "provider": environment.split(":")[0],
                    "mode": "paper",
                    "timeframe": timeframe,
                    "commit": commit,
                }
            ),
            encoding="utf-8",
        )
    if heartbeat:
        (run_dir / "heartbeat.json").write_text(
            json.dumps(
                {
                    "schema_version": "paper-heartbeat-v1",
                    "run_id": run_id,
                    "mode": "PAPER",
                    "cycle": 1,
                    "timestamp_ms": TS0 + 5_000,
                    "decisions": len(traces),
                    "errors": [],
                }
            ),
            encoding="utf-8",
        )
    return run_dir


def execution(decision_id: str, *, symbol: str = "BTC/USDT", notional: float = 500.0) -> dict[str, Any]:
    return {
        "run_id": "run-a",
        "decision_id": decision_id,
        "asset": symbol.split("/")[0],
        "symbol": symbol,
        "strategy_id": "ema_crossover@5m",
        "mode": "TRADE_PAPER",
        "notional_usdt": notional,
        "cloid": f"PAPER-AUTO-abcdef123456-ema_crossover@5m-{decision_id[-6:]}",
    }
