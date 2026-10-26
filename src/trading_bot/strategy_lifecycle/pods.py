"""StrategyPod + ParallelShadowRuntime (§3/§12/§21).

A StrategyPod is NOT an LLM trader. It wraps a deterministic runtime callable
and produces a signal. It has no execution path: the only thing it can return
is a :class:`PodResult` tagged with an execution mode, and SHADOW results are
structurally refused by the execution guard.

Parallel evaluation is the point: every relevant pod receives the SAME context
at the SAME timestamps with the SAME cost model, so a champion/challenger
comparison is honest. Shadow metrics are kept isolated and never mixed with
executed PAPER PnL.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from .contracts import (
    FORBIDDEN_EXECUTION_MODES,
    ContextKey,
    ExecutionMode,
    RationaleCode,
    StrategyDescriptor,
)

__all__ = [
    "FORBIDDEN_ADVISORY_KEYS",
    "ParallelShadowRuntime",
    "PodResult",
    "PodSignal",
    "ShadowLeakError",
    "StrategyPod",
]

PODS_VERSION: Final[str] = "strategy-pods-v1"

#: Keys a pod may NOT set on its own signal: only the RiskManager sizes a trade
#: and only the DecisionEngine decides to execute. A pod that tries anyway is
#: refused at construction (§21).
FORBIDDEN_ADVISORY_KEYS: Final[frozenset[str]] = frozenset(
    {
        "leverage",
        "size",
        "sizing",
        "position_size",
        "notional",
        "notional_usdt",
        "quantity",
        "risk",
        "risk_pct",
        "capital",
        "equity",
        "account",
        "margin",
    }
)


class ShadowLeakError(RuntimeError):
    """Raised when a SHADOW/RESEARCH result is offered to an execution sink."""


@dataclass(frozen=True, slots=True)
class PodSignal:
    """A deterministic signal. It carries NO sizing, leverage or risk field."""

    direction: str  # LONG / SHORT
    entry_reference: float
    confidence: float
    reasoning: tuple[str, ...] = ()
    advisory_metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.direction not in ("LONG", "SHORT"):
            raise ValueError(f"direction must be LONG/SHORT, got {self.direction!r}")
        if self.entry_reference <= 0:
            raise ValueError("entry_reference must be > 0")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")
        forbidden = sorted(set(self.advisory_metadata) & FORBIDDEN_ADVISORY_KEYS)
        if forbidden:
            raise ValueError(
                "a StrategyPod may not set sizing/leverage/risk fields "
                f"({forbidden}); these belong to the RiskManager alone (§21)"
            )

    @property
    def executable(self) -> bool:
        """A raw signal is never executable by itself — only via risk+decision."""
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "direction": self.direction,
            "entry_reference": self.entry_reference,
            "confidence": self.confidence,
            "reasoning": list(self.reasoning),
            "advisory_metadata": dict(self.advisory_metadata),
        }


@dataclass(frozen=True, slots=True)
class PodResult:
    """The output of one pod's evaluation. Always provenance-tagged."""

    strategy_id: str
    strategy_version: str
    context: ContextKey
    execution_mode: ExecutionMode
    signal: PodSignal | None
    timestamp_ms: int
    reason_codes: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    cost_bps: float = 0.0
    schema_version: str = PODS_VERSION

    def __post_init__(self) -> None:
        if self.execution_mode in FORBIDDEN_EXECUTION_MODES:
            raise ValueError(
                f"a pod result may not carry execution mode {self.execution_mode.value}"
            )

    @property
    def is_shadow(self) -> bool:
        return self.execution_mode is ExecutionMode.SHADOW

    @property
    def emitted(self) -> bool:
        return self.signal is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "context": self.context.to_dict(),
            "execution_mode": self.execution_mode.value,
            "signal": None if self.signal is None else self.signal.to_dict(),
            "timestamp_ms": self.timestamp_ms,
            "reason_codes": list(self.reason_codes),
            "evidence": list(self.evidence),
            "cost_bps": self.cost_bps,
            "schema_version": self.schema_version,
        }


#: A pod runtime is a pure function of (context, bars) → PodSignal | None.
PodRuntime = Callable[[Any, Sequence[Any]], "PodSignal | None"]


@dataclass(slots=True)
class StrategyPod:
    """Descriptor + deterministic runtime. Never executes, never sizes."""

    descriptor: StrategyDescriptor
    runtime: PodRuntime

    def __post_init__(self) -> None:
        if not self.descriptor.deterministic:
            raise ValueError(
                f"{self.descriptor.strategy_id}: only deterministic runtimes get a pod"
            )
        if not callable(self.runtime):
            raise TypeError("a pod runtime must be callable")

    @property
    def strategy_id(self) -> str:
        return self.descriptor.strategy_id

    def applies_to(self, context_key: ContextKey) -> bool:
        return self.descriptor.supports(
            context_key.asset, context_key.timeframe, context_key.regime
        )

    def evaluate(
        self,
        context: Any,
        bars: Sequence[Any],
        context_key: ContextKey,
        *,
        timestamp_ms: int,
        execution_mode: ExecutionMode = ExecutionMode.SHADOW,
    ) -> PodResult:
        """Run the runtime once. A raising runtime is a NON-emission, not a crash."""
        if not self.applies_to(context_key):
            return PodResult(
                strategy_id=self.strategy_id,
                strategy_version=self.descriptor.strategy_version,
                context=context_key,
                execution_mode=execution_mode,
                signal=None,
                timestamp_ms=timestamp_ms,
                reason_codes=(RationaleCode.NOT_APPLICABLE.value,),
                evidence=("descriptor does not support this asset/timeframe/regime",),
            )
        try:
            signal = self.runtime(context, bars)
        except Exception as exc:  # a broken pod emits nothing; it never executes
            return PodResult(
                strategy_id=self.strategy_id,
                strategy_version=self.descriptor.strategy_version,
                context=context_key,
                execution_mode=execution_mode,
                signal=None,
                timestamp_ms=timestamp_ms,
                reason_codes=(RationaleCode.REJECTED.value,),
                evidence=(f"runtime_error:{type(exc).__name__}:{exc}",),
            )
        if signal is None:
            return PodResult(
                strategy_id=self.strategy_id,
                strategy_version=self.descriptor.strategy_version,
                context=context_key,
                execution_mode=execution_mode,
                signal=None,
                timestamp_ms=timestamp_ms,
                reason_codes=(RationaleCode.NOT_APPLICABLE.value,),
                evidence=("no signal",),
            )
        if not isinstance(signal, PodSignal):
            raise TypeError(
                f"{self.strategy_id}: pod runtime returned {type(signal).__name__}, "
                "expected PodSignal"
            )
        return PodResult(
            strategy_id=self.strategy_id,
            strategy_version=self.descriptor.strategy_version,
            context=context_key,
            execution_mode=execution_mode,
            signal=signal,
            timestamp_ms=timestamp_ms,
            reason_codes=(RationaleCode.SELECTED.value,),
            evidence=signal.reasoning,
        )


@dataclass(slots=True)
class ParallelShadowRuntime:
    """Evaluate many pods against one shared context, in isolation (§12)."""

    pods: dict[str, StrategyPod] = field(default_factory=dict, repr=False)

    def add(self, pod: StrategyPod) -> None:
        self.pods[pod.strategy_id] = pod

    def remove(self, strategy_id: str) -> None:
        self.pods.pop(strategy_id, None)

    def evaluate_all(
        self,
        *,
        context: Any,
        bars: Sequence[Any],
        context_key: ContextKey,
        timestamp_ms: int,
    ) -> list[PodResult]:
        """Run every pod over the same context. Order is by strategy_id."""
        out: list[PodResult] = []
        for sid in sorted(self.pods):
            out.append(
                self.pods[sid].evaluate(
                    context,
                    bars,
                    context_key,
                    timestamp_ms=timestamp_ms,
                    execution_mode=ExecutionMode.SHADOW,
                )
            )
        return out

    @staticmethod
    def guard_not_executable(results: Iterable[PodResult]) -> None:
        """Refuse to let a SHADOW/RESEARCH result feed an execution sink.

        This is the structural barrier that makes "shadow leaked into execution"
        a detectable failure rather than a silent one (§12/§29).
        """
        for result in results:
            if result.execution_mode is not ExecutionMode.PAPER:
                raise ShadowLeakError(
                    f"{result.strategy_id}: {result.execution_mode.value} result offered to "
                    "execution; only PAPER results may reach the broker"
                )
