"""MARKET_ANALYST_V1.0 — frozen analyst contract for the CAP-002 real pilot.

The analyst is the LLM client (ChatGPT / Codex / this agent).  The repository is
the deterministic shell: it hands the analyst a real :class:`MarketSnapshot`,
validates the analyst's structured answer against a **frozen** schema, and seals
it as a :class:`~trading_bot.research.agentic_contracts.DecisionRecord` *before*
any outcome exists.

What is frozen (never tuned during the pilot):

* the prompt (see :data:`SYSTEM_PROMPT` and the tracked
  ``docs/research/MARKET_ANALYST_V1.md``),
* the output schema (:data:`ANALYST_OUTPUT_FIELDS`),
* the allowed directions (:data:`ALLOWED_DECISIONS`) and horizons
  (:data:`HORIZONS`).

What the analyst may **never** emit: position size, leverage, capital
allocation, risk overrides or execution instructions.  ``NO_TRADE`` is a valid
and expected answer, and the prompt never encourages activity.

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from trading_bot.research import agentic_contracts as ac

__all__ = [
    "ALLOWED_DECISIONS",
    "ANALYST_OUTPUT_FIELDS",
    "DEFAULT_BIAS",
    "HORIZONS",
    "PROMPT_VERSION",
    "SYSTEM_PROMPT",
    "AnalystDecision",
    "prompt_digest",
    "seal_analyst_decision",
    "validate_analyst_output",
]

PROMPT_VERSION = "MARKET_ANALYST_V1.0"
DEFAULT_BIAS = "NO_TRADE"
ALLOWED_DECISIONS: tuple[str, ...] = ("LONG", "SHORT", "NO_TRADE")
HORIZONS: tuple[str, ...] = ("4H", "24H", "72H")

ANALYST_OUTPUT_FIELDS: tuple[str, ...] = (
    "asset",
    "decision",
    "horizon",
    "thesis",
    "evidence",
    "counter_evidence",
    "invalidation",
    "confidence",
    "expected_holding_period",
    "decision_time",
    "no_trade_reason",
)

SYSTEM_PROMPT = """You are MARKET_ANALYST_V1.0, a frozen market analyst for a research pilot.

You receive ONE real, timestamped MarketSnapshot for ONE asset: price structure across
1h/4h/1D, a few deterministic technicals computed from completed bars only, and nothing
else. There is NO news, NO macro, NO sentiment and NO external rating in this experiment.

Answer with a single structured decision. You MUST answer, explicitly, in the fields below:

- WHY TRADE?      -> thesis
- WHY NOT TRADE?  -> no_trade_reason   (required when decision = NO_TRADE)
- WHAT INVALIDATES THE THESIS? -> invalidation
- WHAT EVIDENCE CONTRADICTS IT? -> counter_evidence

Rules:
1. Default to NO_TRADE. Do not look for reasons to be active. The prior is inaction.
2. A LONG or SHORT requires at least one concrete piece of evidence and an invalidation.
3. Allowed decisions: LONG, SHORT, NO_TRADE. Choose exactly one.
4. Allowed horizons: 4H, 24H, 72H. Choose exactly one.
5. confidence is a number in [0, 1] and must reflect genuine uncertainty.
6. Everything you use must already be visible in the snapshot. Never assume data you were
   not given. If the snapshot is thin or ambiguous, the correct answer is NO_TRADE.
7. You may NEVER output position size, leverage, capital allocation, risk limits or any
   execution instruction. Those belong to the deterministic risk gate, not to you.

Output exactly these fields:
asset, decision, horizon, thesis, evidence[], counter_evidence[], invalidation,
confidence, expected_holding_period, decision_time, no_trade_reason.
"""


def prompt_digest() -> str:
    return hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class AnalystDecision:
    asset: str
    decision: str
    horizon: str
    thesis: str
    evidence: tuple[str, ...]
    counter_evidence: tuple[str, ...]
    invalidation: str
    confidence: float
    expected_holding_period: str
    decision_time: int
    no_trade_reason: str = ""
    model_id: str = ""
    model_configuration: str = ""

    def to_dict(self) -> dict[str, Any]:
        return dict(asdict(self))


def _as_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value if str(item).strip())
    return ()


def validate_analyst_output(payload: Mapping[str, Any]) -> list[str]:
    """Return the schema violations (empty list == a valid, sealable answer)."""
    problems: list[str] = []
    missing = [field for field in ANALYST_OUTPUT_FIELDS if field not in payload and field != "no_trade_reason"]
    if missing:
        problems.append(f"missing fields: {missing}")

    decision = payload.get("decision")
    if decision not in ALLOWED_DECISIONS:
        problems.append(f"decision must be one of {ALLOWED_DECISIONS}, got {decision!r}")
    horizon = payload.get("horizon")
    if horizon not in HORIZONS:
        problems.append(f"horizon must be one of {HORIZONS}, got {horizon!r}")

    confidence = payload.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        problems.append("confidence must be a number")
    elif not 0.0 <= float(confidence) <= 1.0:
        problems.append("confidence must be within [0, 1]")

    if not str(payload.get("asset", "")).strip():
        problems.append("asset must not be empty")
    if not str(payload.get("thesis", "")).strip():
        problems.append("thesis must not be empty")
    if not str(payload.get("invalidation", "")).strip():
        problems.append("invalidation must not be empty")
    if not str(payload.get("expected_holding_period", "")).strip():
        problems.append("expected_holding_period must not be empty")

    decision_time = payload.get("decision_time")
    if not isinstance(decision_time, int) or isinstance(decision_time, bool) or decision_time <= 0:
        problems.append("decision_time must be a positive unix second value")

    if decision == "NO_TRADE":
        if not str(payload.get("no_trade_reason", "")).strip():
            problems.append("NO_TRADE requires an explicit no_trade_reason")
    else:
        if not _as_tuple(payload.get("evidence")):
            problems.append("a LONG/SHORT answer requires evidence")

    forbidden = ac.forbidden_proposal_keys(payload)
    if forbidden:
        problems.append(f"the analyst must never emit {forbidden}")
    return problems


def seal_analyst_decision(
    payload: Mapping[str, Any],
    *,
    snapshot_hash: str,
    raw_data_hash: str,
    critic_output: Any = None,
) -> ac.DecisionRecord:
    """Seal a validated analyst answer *before* the outcome exists.

    Refuses to seal anything that violates the frozen schema or smuggles sizing.
    """
    problems = validate_analyst_output(payload)
    if problems:
        raise ValueError(f"refusing to seal an invalid analyst answer: {problems}")
    agent_output = {
        "analyst": dict(payload),
        "prompt_version": PROMPT_VERSION,
        "prompt_digest": prompt_digest(),
        "snapshot_hash": snapshot_hash,
        "raw_data_hash": raw_data_hash,
        "model_id": str(payload.get("model_id", "")),
        "model_configuration": str(payload.get("model_configuration", "")),
    }
    return ac.seal_decision_record(
        timestamp=int(payload["decision_time"]),
        prompt_version=PROMPT_VERSION,
        evidence_snapshot_hash=snapshot_hash,
        agent_output=agent_output,
        critic_output=critic_output,
        decision=str(payload["decision"]),
    )


def decisions_from_records(records: Sequence[ac.DecisionRecord]) -> list[str]:
    return [record.decision for record in records]
