from __future__ import annotations

import pytest

from trading_bot.execution.intent import ExecutionReliabilityError
from trading_bot.strategies.health import (
    HealthIdentity,
    HealthThresholds,
    StrategyHealthSnapshot,
    StrategyHealthState,
    StrategyHealthTracker,
    StrategyHealthVerifier,
)


def _identity(**overrides: str) -> HealthIdentity:
    base = {
        "strategy_id": "momentum",
        "version": "v1",
        "asset": "SOL",
        "timeframe": "5m",
        "regime": "TREND_BULL",
        "observation_window": "2026-09-01/2026-09-08",
    }
    base.update(overrides)
    return HealthIdentity(**base)  # type: ignore[arg-type]


def _snapshot(
    *,
    sample_size: int = 40,
    expectancy: float = 0.4,
    sharpe: float = 1.2,
    pf: float = 1.6,
    win_rate: float = 0.55,
    drawdown: float = 0.05,
    cost_degradation: float = 1.0,
    identity: HealthIdentity | None = None,
) -> StrategyHealthSnapshot:
    return StrategyHealthSnapshot(
        identity=identity or _identity(),
        sample_size=sample_size,
        rolling_expectancy=expectancy,
        baseline_expectancy=0.5,
        rolling_sharpe=sharpe,
        baseline_sharpe=1.5,
        profit_factor=pf,
        win_rate=win_rate,
        drawdown=drawdown,
        slippage_adjusted_expectancy=expectancy - 0.05,
        trade_frequency=3.0,
        cost_degradation=cost_degradation,
    )


def test_insufficient_sample_is_not_degraded() -> None:
    tracker = StrategyHealthTracker()
    state, proposal = tracker.evaluate(_snapshot(sample_size=5), window_index=0)
    assert state is StrategyHealthState.INSUFFICIENT_EVIDENCE
    assert "sample_size" in proposal["reason"]


def test_single_bad_window_does_not_degrade_hysteresis() -> None:
    tracker = StrategyHealthTracker()
    bad = _snapshot(expectancy=-0.2, pf=0.5, win_rate=0.2)
    state1, p1 = tracker.evaluate(bad, window_index=0)
    assert state1 is StrategyHealthState.INSUFFICIENT_EVIDENCE  # first clean->monitoring? no: bad window
    assert p1["proposed_state"] == StrategyHealthState.INSUFFICIENT_EVIDENCE.value or state1 is not StrategyHealthState.DEGRADED
    # Second bad window in a row after a monitoring state would degrade, but
    # from INSUFFICIENT_EVIDENCE the first sufficient windows route to MONITORING
    # only when clean. With two consecutive bad windows the tracker proposes DEGRADED.
    state2, p2 = tracker.evaluate(bad, window_index=1)
    assert p2["proposed_state"] == StrategyHealthState.DEGRADED.value
    assert state2 is StrategyHealthState.DEGRADED


def test_degradation_requires_consecutive_windows() -> None:
    tracker = StrategyHealthTracker()
    tracker.evaluate(_snapshot(), window_index=0)  # clean -> MONITORING
    bad = _snapshot(expectancy=-0.2, pf=0.5, win_rate=0.2)
    tracker.evaluate(bad, window_index=1)  # 1st bad: streak=1, no flip
    assert tracker.cell_state(_identity()) is StrategyHealthState.MONITORING
    state, _ = tracker.evaluate(bad, window_index=2)  # 2nd bad: flip
    assert state is StrategyHealthState.DEGRADED


def test_recovery_requires_consecutive_clean_windows() -> None:
    tracker = StrategyHealthTracker()
    bad = _snapshot(expectancy=-0.2, pf=0.5, win_rate=0.2)
    tracker.evaluate(bad, window_index=0)
    tracker.evaluate(bad, window_index=1)  # DEGRADED
    good = _snapshot()
    tracker.evaluate(good, window_index=2)  # recovery streak 1
    assert tracker.cell_state(_identity()) is StrategyHealthState.DEGRADED
    state, _ = tracker.evaluate(good, window_index=3)  # recovery streak 2
    assert state is StrategyHealthState.MONITORING


def test_health_is_conditional_by_regime_partition() -> None:
    tracker = StrategyHealthTracker()
    bull = _identity(regime="TREND_BULL")
    rng = _identity(regime="RANGE")
    tracker.evaluate(_snapshot(identity=bull), window_index=0)
    tracker.evaluate(_snapshot(identity=rng, expectancy=-0.2, pf=0.5, win_rate=0.2), window_index=0)
    tracker.evaluate(_snapshot(identity=rng, expectancy=-0.2, pf=0.5, win_rate=0.2), window_index=1)
    assert tracker.cell_state(bull) is StrategyHealthState.MONITORING
    assert tracker.cell_state(rng) is StrategyHealthState.DEGRADED  # same strategy, different cell


def test_quarantine_requires_governance_and_recovery_requires_research() -> None:
    tracker = StrategyHealthTracker()
    bad = _snapshot(expectancy=-0.2, pf=0.5, win_rate=0.2)
    tracker.evaluate(bad, window_index=0)
    tracker.evaluate(bad, window_index=1)  # DEGRADED
    proposal = tracker.propose_quarantine(_identity(), reason="governance decision", window_index=2)
    assert proposal["proposed_state"] == StrategyHealthState.QUARANTINED.value
    # No self-recovery: organic windows on a QUARANTINED cell are no-ops that
    # can never lift the state; only revalidation recovery can.
    state, noop = tracker.evaluate(_snapshot(), window_index=3)
    assert state is StrategyHealthState.QUARANTINED
    assert "revalidation required" in noop["reason"]
    recovery = tracker.propose_revalidation_recovery(_identity(), research_artifact="RSCH-001", window_index=4)
    assert recovery["proposed_state"] == StrategyHealthState.MONITORING.value
    assert "RSCH-001" in recovery["reason"]


def test_recovered_strategy_does_not_auto_promote_to_healthy() -> None:
    tracker = StrategyHealthTracker()
    bad = _snapshot(expectancy=-0.2, pf=0.5, win_rate=0.2)
    tracker.evaluate(bad, window_index=0)
    tracker.evaluate(bad, window_index=1)
    tracker.propose_quarantine(_identity(), reason="governance", window_index=2)
    tracker.propose_revalidation_recovery(_identity(), research_artifact="RSCH-001", window_index=3)
    # Even with great metrics, MONITORING is the ceiling after recovery.
    state, _ = tracker.evaluate(_snapshot(), window_index=4)
    assert state is StrategyHealthState.MONITORING


def test_retired_is_terminal() -> None:
    tracker = StrategyHealthTracker()
    tracker.propose_retirement(_identity(), reason="governance", window_index=0)
    assert tracker.cell_state(_identity()) is StrategyHealthState.RETIRED
    with pytest.raises(ExecutionReliabilityError):
        tracker.evaluate(_snapshot(), window_index=1)


def test_verifier_rejects_inadequate_sample_for_critical_transition() -> None:
    tracker = StrategyHealthTracker()
    verifier = StrategyHealthVerifier()
    small = _snapshot(sample_size=5)
    tracker.evaluate(small, window_index=0)
    # Attempt a forged DEGRADED proposal with inadequate sample.
    forged = {
        "cell": small.identity.key(),
        "proposed_state": StrategyHealthState.DEGRADED.value,
        "reason": "degraded signals for 2 consecutive windows",
        "window_index": "1",
    }
    ok, failures = verifier.verify_transition(
        small,
        forged,
        expected_window_index=1,
        baseline_binding="baseline-v1",
        regime_binding="TREND_BULL",
        prior_state=StrategyHealthState.MONITORING,
    )
    assert not ok
    assert "sample_inadequate_for_critical_transition" in failures


def test_verifier_checks_window_regime_and_hysteresis() -> None:
    verifier = StrategyHealthVerifier()
    snap = _snapshot()
    proposal = {
        "cell": snap.identity.key(),
        "proposed_state": StrategyHealthState.DEGRADED.value,
        "reason": "bad window",  # no 'consecutive' -> hysteresis failure
        "window_index": "0",
    }
    ok, failures = verifier.verify_transition(
        snap,
        proposal,
        expected_window_index=0,
        baseline_binding="baseline-v1",
        regime_binding="TREND_BULL",
    )
    assert not ok
    assert "hysteresis_not_cited" in failures
    # Wrong regime binding.
    ok2, failures2 = verifier.verify_transition(
        snap,
        proposal,
        expected_window_index=0,
        baseline_binding="baseline-v1",
        regime_binding="RANGE",
    )
    assert not ok2
    assert "regime_binding_mismatch" in failures2
    # Wrong window index.
    ok3, failures3 = verifier.verify_transition(
        snap,
        proposal,
        expected_window_index=5,
        baseline_binding="baseline-v1",
        regime_binding="TREND_BULL",
    )
    assert not ok3
    assert "window_identity_mismatch" in failures3


def test_verifier_accepts_valid_transition() -> None:
    tracker = StrategyHealthTracker()
    verifier = StrategyHealthVerifier()
    tracker.evaluate(_snapshot(), window_index=0)  # MONITORING
    bad = _snapshot(expectancy=-0.2, pf=0.5, win_rate=0.2)
    tracker.evaluate(bad, window_index=1)
    _, proposal = tracker.evaluate(bad, window_index=2)  # DEGRADED proposal
    ok, failures = verifier.verify_transition(
        _snapshot(expectancy=-0.2, pf=0.5, win_rate=0.2),
        proposal,
        expected_window_index=2,
        baseline_binding="baseline-v1",
        regime_binding="TREND_BULL",
        prior_state=StrategyHealthState.MONITORING,
    )
    assert ok, failures


def test_health_thresholds_configurable() -> None:
    tracker = StrategyHealthTracker(HealthThresholds(min_sample_size=2, degraded_consecutive_windows=1))
    state, _ = tracker.evaluate(_snapshot(sample_size=2), window_index=0)
    assert state is StrategyHealthState.MONITORING


def test_snapshot_to_dict_roundtrip_keys() -> None:
    snap = _snapshot()
    payload = snap.to_dict()
    assert payload["identity"] == _identity().key()
    assert payload["sample_size"] == 40
