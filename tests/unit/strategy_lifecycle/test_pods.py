"""StrategyPod tests: shadow isolation, no sizing/leverage, leak guard (§3/§12/§21)."""

from __future__ import annotations

import pytest

from trading_bot.strategy_lifecycle.contracts import (
    ContextKey,
    ExecutionMode,
    LifecycleState,
)
from trading_bot.strategy_lifecycle.pods import (
    ParallelShadowRuntime,
    PodSignal,
    ShadowLeakError,
    StrategyPod,
)

from ._helpers import descriptor

KEY = ContextKey("mom", "BTC", "5m", "TREND_UP")


def _pod(sid="mom", runtime=None) -> StrategyPod:
    rt = runtime or (lambda ctx, bars: PodSignal(direction="LONG", entry_reference=100.0, confidence=0.5))
    return StrategyPod(descriptor=descriptor(sid, state=LifecycleState.SHADOW), runtime=rt)


def test_pod_emits_a_shadow_signal() -> None:
    pod = _pod()
    result = pod.evaluate(None, [], KEY, timestamp_ms=1)
    assert result.is_shadow
    assert result.execution_mode is ExecutionMode.SHADOW
    assert result.emitted


def test_pod_that_returns_nothing_does_not_emit() -> None:
    pod = _pod(runtime=lambda ctx, bars: None)
    result = pod.evaluate(None, [], KEY, timestamp_ms=1)
    assert not result.emitted


def test_pod_runtime_error_is_a_non_emission_not_a_crash() -> None:
    def boom(ctx, bars):
        raise RuntimeError("bad input")

    result = _pod(runtime=boom).evaluate(None, [], KEY, timestamp_ms=1)
    assert not result.emitted
    assert any("runtime_error" in e for e in result.evidence)


def test_pod_runtime_must_return_a_pod_signal() -> None:
    with pytest.raises(TypeError):
        _pod(runtime=lambda ctx, bars: "BUY").evaluate(None, [], KEY, timestamp_ms=1)


def test_pod_may_not_set_leverage() -> None:
    with pytest.raises(ValueError):
        PodSignal(direction="LONG", entry_reference=100.0, confidence=0.5, advisory_metadata={"leverage": 5})


def test_pod_may_not_set_sizing() -> None:
    with pytest.raises(ValueError):
        PodSignal(direction="LONG", entry_reference=100.0, confidence=0.5, advisory_metadata={"notional_usdt": 500})


def test_pod_not_applicable_for_unsupported_asset() -> None:
    pod = _pod()
    other = ContextKey("mom", "DOGE", "5m", "TREND_UP")
    result = pod.evaluate(None, [], other, timestamp_ms=1)
    assert not result.emitted
    assert "NOT_APPLICABLE" in result.reason_codes


def test_parallel_runtime_evaluates_every_pod_in_order() -> None:
    runtime = ParallelShadowRuntime()
    runtime.add(_pod("zeta"))
    runtime.add(_pod("alpha"))
    results = runtime.evaluate_all(context=None, bars=[], context_key=KEY, timestamp_ms=1)
    assert [r.strategy_id for r in results] == ["alpha", "zeta"]


def test_shadow_result_cannot_reach_execution() -> None:
    runtime = ParallelShadowRuntime()
    runtime.add(_pod())
    out = runtime.evaluate_all(context=None, bars=[], context_key=KEY, timestamp_ms=1)
    with pytest.raises(ShadowLeakError):
        ParallelShadowRuntime.guard_not_executable(out)


def test_live_mode_is_refused_on_pod_result() -> None:
    from trading_bot.strategy_lifecycle.pods import PodResult

    with pytest.raises(ValueError):
        PodResult(
            strategy_id="mom",
            strategy_version="v1",
            context=KEY,
            execution_mode=ExecutionMode.LIVE,
            signal=None,
            timestamp_ms=1,
        )
