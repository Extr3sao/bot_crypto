"""LLM Safety Guard (P25).

Enforces the boundary between what an LLM may and may not do.
P25 contract:
- LLM MAY: summarize results, document, propose FUTURE hypotheses,
  generate code for a campaign that hasn't seen its data yet.
- LLM MUST NOT: change an experiment after seeing results,
  modify gates during a run, pick thresholds post-hoc,
  declare consumed data as fresh, approve a candidate bypassing Python.

Python is the final authority of the research protocol.

Provides:
- Operation authorization (allowed/denied)
- Audit trail of LLM requests
- Concrete constraint checks
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal

import structlog

# ---------------------------------------------------------------------------
# Operation Types
# ---------------------------------------------------------------------------

LLMOperation = Literal[
    # ALLOWED operations
    "summarize_results",
    "document_findings",
    "propose_future_hypothesis",
    "generate_future_code",
    "describe_metrics",
    "explain_architecture",
    # DENIED operations
    "modify_experiment_after_results",
    "modify_gates_during_run",
    "pick_thresholds_posthoc",
    "declare_consumed_as_fresh",
    "approve_candidate_bypassing_python",
    "change_preregistered_config",
    "modify_code_hash",
]

# Operations that the LLM is allowed to perform
ALLOWED_OPERATIONS: set[LLMOperation] = {
    "summarize_results",
    "document_findings",
    "propose_future_hypothesis",
    "generate_future_code",
    "describe_metrics",
    "explain_architecture",
}

# Operations that the LLM is NEVER allowed to perform
DENIED_OPERATIONS: set[LLMOperation] = {
    "modify_experiment_after_results",
    "modify_gates_during_run",
    "pick_thresholds_posthoc",
    "declare_consumed_as_fresh",
    "approve_candidate_bypassing_python",
    "change_preregistered_config",
    "modify_code_hash",
}


# ---------------------------------------------------------------------------
# Authorization Result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LLMAuthorization:
    """Result of an LLM safety check."""

    operation: LLMOperation
    allowed: bool
    reason: str
    checked_at: int

    @property
    def is_denied(self) -> bool:
        return not self.allowed


# ---------------------------------------------------------------------------
# Safety Guard
# ---------------------------------------------------------------------------


@dataclass
class LLMRequestLog:
    """Log entry for an LLM request."""

    operation: LLMOperation
    allowed: bool
    reason: str
    timestamp: int
    context: dict[str, Any] = field(default_factory=dict)


class LLMSafetyGuard:
    """Enforces LLM safety constraints (P25).

    Every LLM operation must be checked against this guard BEFORE execution.
    Python is the final authority — the guard never overrides a DENIED decision.

    P25 invariants:
    - LLM cannot modify experiments after seeing results.
    - LLM cannot modify gates during a run.
    - LLM cannot pick thresholds post-hoc.
    - LLM cannot declare consumed data as fresh.
    - LLM cannot approve candidates bypassing Python.
    """

    def __init__(self) -> None:
        self._log = structlog.get_logger("llm_safety")
        self._request_log: list[LLMRequestLog] = []

    def check(
        self, operation: LLMOperation, context: dict[str, Any] | None = None
    ) -> LLMAuthorization:
        """Check if an LLM operation is authorized.

        Args:
            operation: The operation the LLM wants to perform
            context: Optional context for the check

        Returns:
            LLMAuthorization with allowed/denied status
        """
        now = int(time.time() * 1000)

        if operation in DENIED_OPERATIONS:
            auth = LLMAuthorization(
                operation=operation,
                allowed=False,
                reason=f"P25: LLM is NEVER allowed to {operation}",
                checked_at=now,
            )
        elif operation in ALLOWED_OPERATIONS:
            auth = LLMAuthorization(
                operation=operation,
                allowed=True,
                reason="P25: operation is in allowed set",
                checked_at=now,
            )
        else:
            # Unknown operation — deny by default (fail-closed)
            auth = LLMAuthorization(
                operation=operation,
                allowed=False,
                reason=f"P25: unknown operation '{operation}' — deny by default",
                checked_at=now,
            )

        # Log the request
        self._request_log.append(
            LLMRequestLog(
                operation=operation,
                allowed=auth.allowed,
                reason=auth.reason,
                timestamp=now,
                context=context or {},
            )
        )

        if auth.allowed:
            self._log.info("llm_safety.allowed", operation=operation)
        else:
            self._log.warning("llm_safety.denied", operation=operation, reason=auth.reason)

        return auth

    def assert_allowed(
        self, operation: LLMOperation, context: dict[str, Any] | None = None
    ) -> None:
        """Check and raise if operation is not allowed.

        Use this for hard enforcement.
        """
        auth = self.check(operation, context)
        if not auth.allowed:
            raise PermissionError(f"LLM operation denied: {auth.reason}")

    @property
    def request_log(self) -> list[LLMRequestLog]:
        """All logged requests (for auditing)."""
        return list(self._request_log)

    @property
    def denied_count(self) -> int:
        return sum(1 for r in self._request_log if not r.allowed)

    @property
    def allowed_count(self) -> int:
        return sum(1 for r in self._request_log if r.allowed)

    def reset_log(self) -> None:
        """Reset the request log."""
        self._request_log.clear()


__all__ = [
    "ALLOWED_OPERATIONS",
    "DENIED_OPERATIONS",
    "LLMAuthorization",
    "LLMOperation",
    "LLMSafetyGuard",
]
