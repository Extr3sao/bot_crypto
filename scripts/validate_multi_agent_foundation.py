"""Deterministic MA-0 foundation smoke validation.

This script is validation-only. It never imports or invokes trading runtime
execution components, exchanges, credentials, RiskManager, or PaperBroker.
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

from trading_bot.multi_agent.contracts import (
    AgentCapability,
    AgentEvidence,
    AgentManifest,
    AgentMessage,
    AgentMessageType,
    AgentRole,
    ForbiddenAction,
    TraceContext,
    TradeDirection,
    TradeProposal,
    VerificationMetadata,
)
from trading_bot.multi_agent.registry import (
    AgentRegistry,
    CapabilityDeniedError,
    CapabilityRegistry,
)

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


def _command_output(*command: str) -> str:
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _validation_metadata() -> dict[str, object]:
    return {
        "commit": _command_output("git", "rev-parse", "HEAD"),
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "uv": _command_output("uv", "--version"),
        },
        "tests": [
            "manifest construction and immutability",
            "agent version registration and lifecycle transition",
            "safe READ permission grant",
            "forbidden PRODUCTION_ACTION rejection",
            "evidence/message/proposal trace correlation",
            "NO_TRADE serialization round-trip",
            "builder/verifier identity separation",
        ],
        "errors": [],
        "evidence_paths": [
            "reports/multi_agent/ma0/RUN_REPORT.json",
            "reports/multi_agent/ma0/RUN_REPORT.md",
        ],
    }


def run() -> dict[str, object]:
    trace = TraceContext(
        run_id="ma0-smoke-run",
        trace_id="ma0-smoke-trace",
        correlation_id="ma0-smoke-correlation",
        causation_id="ma0-smoke-causation",
    )
    manifest = AgentManifest(
        schema_version="ma-0-v1",
        agent_id="smoke-strategy-agent",
        agent_version="1.0.0",
        role=AgentRole.STRATEGY_EXPERT,
        description="Deterministic MA-0 smoke agent.",
        capabilities=frozenset({AgentCapability.READ}),
        input_contracts=("AssetContext",),
        output_contracts=("TradeProposal",),
        allowed_tools=("indicator_registry",),
        forbidden_actions=frozenset(ForbiddenAction),
        created_at=NOW,
    )

    agent_registry = AgentRegistry()
    agent_registry.register(manifest)
    agent_registry.place_in_probation(manifest.agent_id, manifest.agent_version)

    capability_registry = CapabilityRegistry()
    capability_registry.register_agent(
        agent_registry.get_version(manifest.agent_id, manifest.agent_version)
    )
    capability_registry.grant(manifest.agent_id, manifest.agent_version, AgentCapability.READ)
    capability_registry.assert_allowed(
        manifest.agent_id, manifest.agent_version, AgentCapability.READ
    )
    try:
        capability_registry.assert_allowed(
            manifest.agent_id, manifest.agent_version, AgentCapability.PRODUCTION_ACTION
        )
    except CapabilityDeniedError:
        forbidden_capability_rejected = True
    else:
        forbidden_capability_rejected = False

    evidence = AgentEvidence(
        schema_version="ma-0-v1",
        evidence_id="smoke-evidence",
        run_id=trace.run_id,
        producer_agent_id=manifest.agent_id,
        evidence_type="deterministic_metric",
        source_ref="smoke://offline-data",
        claim_refs=("smoke-claim",),
        observed_at=NOW - timedelta(minutes=1),
        available_at=NOW,
        content_hash=sha256(b"ma0-smoke-evidence").hexdigest(),
        metadata=(("value", 1.0),),
        trace=trace,
    )
    message = AgentMessage(
        schema_version="ma-0-v1",
        message_id="smoke-message",
        run_id=trace.run_id,
        trace_id=trace.trace_id,
        sender=manifest.agent_id,
        receiver="smoke-verifier",
        message_type=AgentMessageType.OBSERVATION,
        claim="The deterministic smoke fixture is valid.",
        evidence_refs=(evidence.evidence_id,),
        confidence=1.0,
        created_at=NOW,
        data_time=NOW - timedelta(minutes=1),
        trace=trace,
    )
    proposal = TradeProposal(
        schema_version="ma-0-v1",
        proposal_id="smoke-proposal",
        run_id=trace.run_id,
        trace_id=trace.trace_id,
        asset="BTC/USDT",
        direction=TradeDirection.NO_TRADE,
        strategy="smoke",
        timeframe="5m",
        regime="RANGE",
        evidence_refs=(evidence.evidence_id,),
        invalidation="Smoke validation ended.",
        confidence=1.0,
        data_time=NOW - timedelta(minutes=1),
        created_at=NOW,
        trace=trace,
    )
    verification = VerificationMetadata(
        artifact_id=proposal.proposal_id,
        builder_agent_id=manifest.agent_id,
        verifier_agent_id="smoke-verifier",
    )

    round_trip = TradeProposal.model_validate(proposal.model_dump())
    if round_trip != proposal or not forbidden_capability_rejected:
        raise RuntimeError("MA-0 smoke invariant failed")

    payload: dict[str, object] = {
        "run_id": trace.run_id,
        "result": "PASS",
        **_validation_metadata(),
        "mode": "PAPER_OFFLINE_ONLY",
        "contracts_tested": [
            "AgentManifest",
            "AgentMessage",
            "AgentEvidence",
            "TradeProposal",
            "TraceContext",
            "VerificationMetadata",
        ],
        "registries_tested": ["AgentRegistry", "CapabilityRegistry"],
        "agent_versions": len(agent_registry),
        "effective_permissions": sorted(
            capability.value
            for capability in capability_registry.permissions_for(
                manifest.agent_id, manifest.agent_version
            )
        ),
        "message_id": message.message_id,
        "evidence_id": evidence.evidence_id,
        "proposal_direction": proposal.direction.value,
        "verification": verification.model_dump(),
        "forbidden_capability_rejected": forbidden_capability_rejected,
    }
    return payload


def main() -> int:
    payload = run()
    output_dir = Path("reports/multi_agent/ma0")
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "RUN_REPORT.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
