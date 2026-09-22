#!/usr/bin/env python3
"""Independent MA-2 specialist swarm validator.

Verifies:
- proposal provenance
- evidence binding
- deduplication
- conflict detection
- ranking determinism
- execution capability = 0

Must be runnable from a clean checkout with no trading side-effects.
"""

from __future__ import annotations

import ast
import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# Ensure src is on the path for clean-checkout execution
_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root / "src"))

from trading_bot.market_data.types import OHLCV  # noqa: E402
from trading_bot.multi_agent import (  # noqa: E402
    AgentCapability,
    AgentRegistry,
    CapabilityRegistry,
    OpportunityBoard,
    TraceContext,
    register_swarm_agents,
)
from trading_bot.multi_agent.contracts import (  # noqa: E402
    AgentEvidence,
    TradeDirection,
    TradeProposal,
)
from trading_bot.multi_agent.specialists import MomentumExpert  # noqa: E402

REPORT_PATH = _root / "reports" / "multi_agent" / "ma2" / "VALIDATION_REPORT.json"

# Fixed validation clock — never uses datetime.now for decision logic
VALIDATION_CLOCK = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

PASS = "PASS"
FAIL = "FAIL"
results: dict[str, str] = {}
details: dict[str, Any] = {}


def _sha256_hex(payload: str = "") -> str:
    """Return a valid SHA-256 hex digest."""
    return hashlib.sha256(payload.encode()).hexdigest()


TRACE = TraceContext(
    run_id="ma2-validator",
    trace_id="ma2-validator-trace",
    correlation_id="ma2-validator-corr",
    causation_id="ma2-validator-cause",
)


def _ctx(asset: str = "SOL", returns: float = 0.06) -> Any:
    from trading_bot.research.asset_intelligence.models import AssetContext

    return AssetContext(
        asset=asset,
        timestamp=1_767_268_800_000,
        market_regime="TREND_UP",
        trend_state="up",
        volatility_state="normal",
        liquidity_state="deep",
        momentum_features={
            "returns": returns,
            "trend": {"direction": "up", "spread": 0.01},
            "rsi": 65.0,
        },
        volatility_features={"atr_norm": 0.01},
        volume_features={"surge": 1.2},
        data_quality={"bars_in_window": 120, "newest_bar_ts": 1_767_268_800_000},
        data_fingerprint="a" * 64,
        dataset_id="validator",
        agent_version="base-crypto-v1",
        regime_method_version="asset-agent-regime-v1",
        window_start_ts=1_767_268_800_000 - 119 * 300_000,
        window_end_ts=1_767_268_800_000,
        bar_count=120,
    )


def _candles_accelerating(asset: str = "SOL", count: int = 80) -> list[OHLCV]:
    start = 1_767_268_800_000 - (count - 1) * 300_000
    out: list[OHLCV] = []
    price = 100.0
    for i in range(count):
        ts = start + i * 300_000
        price *= 1.002
        out.append(
            OHLCV(f"{asset}/USDT", ts, price * 0.998, price * 1.002, price * 0.996, price, 100.0)
        )
    return out


def _check(name: str, passed: bool, detail: str = "") -> None:
    results[name] = PASS if passed else FAIL
    if detail:
        details[name] = detail
    symbol = "[OK]" if passed else "[!!]"
    print(f"  {symbol} MA2-{name}: {PASS if passed else FAIL}{f' ({detail})' if detail else ''}")


def _validate_execution_boundary() -> None:
    forbidden_prefixes = (
        "trading_bot.paper",
        "trading_bot.risk",
        "trading_bot.execution",
        "trading_bot.config",
    )
    target_files = [
        _root / "src" / "trading_bot" / "multi_agent" / "specialists.py",
        _root / "src" / "trading_bot" / "multi_agent" / "opportunity.py",
        _root / "src" / "trading_bot" / "multi_agent" / "swarm.py",
    ]
    import_violations: list[str] = []
    for path in target_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            mod = None
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mod = alias.name
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                mod = node.module
            if mod and any(mod.startswith(p) for p in forbidden_prefixes):
                import_violations.append(f"{path.name}:{mod}")
    _check(
        "no_execution_imports",
        len(import_violations) == 0,
        f"{len(import_violations)} violations" if import_violations else "clean",
    )


def validate() -> bool:
    print("\n=== MA-2 Independent Validator ===\n")

    # --- 1. Proposal provenance ---
    expert = MomentumExpert()
    sol_ctx = _ctx()
    sol_candles = _candles_accelerating("SOL")
    evaluation = expert.evaluate(sol_ctx, sol_candles, trace=TRACE)

    has_proposals = len(evaluation.proposals) > 0
    _check(
        "proposal_provenance",
        has_proposals,
        f"{len(evaluation.proposals)} proposals from {evaluation.agent_id}",
    )

    if has_proposals:
        for p in evaluation.proposals:
            assert p.run_id == TRACE.run_id
            assert p.trace_id == TRACE.trace_id

    # --- 2. Evidence binding ---
    all_evidence_bound = (
        all(len(p.evidence_refs) > 0 for p in evaluation.proposals)
        if evaluation.proposals
        else False
    )
    _check("evidence_binding", all_evidence_bound, "all proposals have evidence refs")

    evidence_by_id = {e.evidence_id: e for e in evaluation.evidence}
    evidence_matches = (
        all(ref in evidence_by_id for p in evaluation.proposals for ref in p.evidence_refs)
        if evaluation.proposals
        else False
    )
    _check("evidence_matching", evidence_matches, "all refs resolve to registered evidence")

    # --- 3. Deduplication ---
    board = OpportunityBoard(run_id=TRACE.run_id, now=VALIDATION_CLOCK)
    for e in evaluation.evidence:
        board.add_evidence(e)

    if evaluation.proposals:
        p = evaluation.proposals[0]
        board.add(p, source_agent_id=evaluation.agent_id, source_agent_version="1.0.0")
        dup = p.model_copy(update={"proposal_id": p.proposal_id + "-dup"})
        board.add(dup, source_agent_id=evaluation.agent_id, source_agent_version="1.0.0")
        dedup_ok = len(board.snapshot().opportunities) == 1
        _check("deduplication", dedup_ok, "semantically identical proposals collapsed to 1")
    else:
        _check("deduplication", False, "no proposals to test dedup")

    # --- 4. Conflict detection ---
    board2 = OpportunityBoard(run_id=TRACE.run_id, now=VALIDATION_CLOCK)
    ts = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    for ref_id in ("ev-long", "ev-short"):
        ev = AgentEvidence(
            schema_version="ma-2-v1",
            evidence_id=ref_id,
            run_id=TRACE.run_id,
            producer_agent_id="test",
            evidence_type="strategy_signal",
            source_ref="test",
            claim_refs=(),
            observed_at=ts,
            available_at=ts,
            content_hash=_sha256_hex(ref_id),
            metadata=(),
            trace=TRACE,
        )
        board2.add_evidence(ev)

    long_p = TradeProposal(
        schema_version="ma-2-v1",
        proposal_id="p-long",
        run_id=TRACE.run_id,
        trace_id=TRACE.trace_id,
        asset="SOL",
        direction=TradeDirection.LONG,
        strategy="momentum",
        timeframe="5m",
        regime="TREND_UP",
        evidence_refs=("ev-long",),
        invalidation="stop",
        confidence=0.8,
        data_time=ts,
        created_at=ts,
        expires_at=ts + timedelta(minutes=15),
        trace=TRACE,
    )
    short_p = TradeProposal(
        schema_version="ma-2-v1",
        proposal_id="p-short",
        run_id=TRACE.run_id,
        trace_id=TRACE.trace_id,
        asset="SOL",
        direction=TradeDirection.SHORT,
        strategy="mean_reversion",
        timeframe="5m",
        regime="TREND_UP",
        evidence_refs=("ev-short",),
        invalidation="stop",
        confidence=0.7,
        data_time=ts,
        created_at=ts,
        expires_at=ts + timedelta(minutes=15),
        trace=TRACE,
    )
    board2.add(long_p, source_agent_id="test", source_agent_version="1.0.0")
    board2.add(short_p, source_agent_id="test", source_agent_version="1.0.0")
    snap = board2.snapshot()
    has_conflict = len(snap.conflicts) == 1 and snap.conflicts[0].asset == "SOL"
    _check("conflict_detection", has_conflict, f"{len(snap.conflicts)} conflict(s) detected")

    ranked = board2.rank()
    conflicted_items = [r for r in ranked if r.conflict_status == "CONFLICTED"]
    _check(
        "conflict_marking",
        len(conflicted_items) == 2,
        f"{len(conflicted_items)} conflicted rankings",
    )

    # --- 5. Ranking determinism ---
    ranked_1 = board2.rank()
    ranked_2 = board2.rank()
    _check("ranking_determinism", ranked_1 == ranked_2)

    # --- 6. Execution capability = 0 ---
    registry = AgentRegistry()
    cap_reg = CapabilityRegistry()
    manifests = register_swarm_agents(registry, cap_reg)
    all_caps_ok = True
    for manifest in manifests:
        perms = cap_reg.permissions_for(manifest.agent_id, manifest.agent_version)
        for forbidden_cap in (
            AgentCapability.EXECUTE,
            AgentCapability.PRODUCTION_ACTION,
            AgentCapability.RISK_OVERRIDE,
            AgentCapability.DIRECT_BROKER_ACCESS,
        ):
            if forbidden_cap in perms:
                all_caps_ok = False
                details[f"capability_violation_{manifest.agent_id}"] = forbidden_cap.value
    _check(
        "execution_capability_zero",
        all_caps_ok,
        f"{len(manifests)} agents verified, no forbidden capabilities",
    )

    # --- 7. Stale/expiry enforcement ---
    board3 = OpportunityBoard(run_id=TRACE.run_id, now=VALIDATION_CLOCK)
    if evaluation.proposals:
        p = evaluation.proposals[0]
        board3.add_evidence(evaluation.evidence[0])
        board3.add(p, source_agent_id=evaluation.agent_id, source_agent_version="1.0.0")
        expired = board3.expire_stale(now=p.expires_at + timedelta(hours=1))
        expired_ok = p.proposal_id in expired and len(board3.rank()) == 0
        _check("stale_expiry", expired_ok, "expired proposal excluded from ranking")
    else:
        _check("stale_expiry", False, "no proposals to test expiry")

    # --- 8. No execution imports ---
    _validate_execution_boundary()

    # --- Summary ---
    total = len(results)
    passed_count = sum(1 for v in results.values() if v == PASS)
    failed = total - passed_count
    print(f"\n{'=' * 40}")
    print(f"Result: {passed_count}/{total} PASS, {failed} FAIL")
    print(f"{'=' * 40}\n")

    # Write report
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "validator": "ma2-specialist-swarm",
        "total": total,
        "passed": passed_count,
        "failed": failed,
        "results": results,
        "details": details,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"Report written to {REPORT_PATH}")

    return failed == 0


if __name__ == "__main__":
    success = validate()
    sys.exit(0 if success else 1)
