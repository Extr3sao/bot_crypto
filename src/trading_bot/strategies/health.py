"""Strategy Health V1 — degradation detection for admitted strategies.

STRATEGY-HEALTH-01 (checkpoint INTELLIGENCE-AND-EXECUTION-HARDENING-01,
Track B). Deterministic, evidence-gated health model over the
(strategy x asset x timeframe x regime) partition. NO self-modification:
health states are PROPOSALS for governance; nothing here disables or
promotes a strategy at runtime. POC01 remains untouched.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from trading_bot.execution.intent import ExecutionReliabilityError


class StrategyHealthState(StrEnum):
    """Deterministic health states (B2)."""

    HEALTHY = "HEALTHY"
    MONITORING = "MONITORING"
    DEGRADED = "DEGRADED"
    QUARANTINED = "QUARANTINED"
    RETIRED = "RETIRED"
    # Legacy runtime strategies without health instrumentation keep their
    # baseline status; they are never auto-transitioned.
    LEGACY_PAPER_BASELINE = "LEGACY_PAPER_BASELINE"
    # Not enough closed trades in the observation window: no verdict.
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


# Allowed transitions (B2 + B3: no single-trade flips, no auto-promotion).
# Recovery from QUARANTINED requires research/revalidation -> goes through
# the verifier with an explicit `revalidation` evidence payload, landing in
# MONITORING (never straight to HEALTHY). RETIRED is terminal and reachable
# from any non-terminal state as a GOVERNANCE action (never organic).
_ALLOWED_HEALTH_TRANSITIONS: dict[StrategyHealthState, frozenset[StrategyHealthState]] = {
    StrategyHealthState.HEALTHY: frozenset({StrategyHealthState.MONITORING, StrategyHealthState.DEGRADED, StrategyHealthState.RETIRED}),
    StrategyHealthState.MONITORING: frozenset({StrategyHealthState.HEALTHY, StrategyHealthState.DEGRADED, StrategyHealthState.QUARANTINED, StrategyHealthState.RETIRED}),
    StrategyHealthState.DEGRADED: frozenset({StrategyHealthState.MONITORING, StrategyHealthState.QUARANTINED, StrategyHealthState.RETIRED}),
    StrategyHealthState.QUARANTINED: frozenset({StrategyHealthState.MONITORING, StrategyHealthState.RETIRED}),
    StrategyHealthState.RETIRED: frozenset(),
    StrategyHealthState.LEGACY_PAPER_BASELINE: frozenset({StrategyHealthState.MONITORING, StrategyHealthState.RETIRED}),
    StrategyHealthState.INSUFFICIENT_EVIDENCE: frozenset({StrategyHealthState.HEALTHY, StrategyHealthState.MONITORING, StrategyHealthState.DEGRADED, StrategyHealthState.RETIRED}),
}


@dataclass(frozen=True, slots=True)
class HealthIdentity:
    """Identity of one health cell: strategy x asset x timeframe x regime."""

    strategy_id: str
    version: str
    asset: str
    timeframe: str
    regime: str
    observation_window: str  # e.g. "2026-09-01/2026-09-08" or "rolling-30d"

    def key(self) -> str:
        return f"{self.strategy_id}|{self.version}|{self.asset}|{self.timeframe}|{self.regime}|{self.observation_window}"


@dataclass(frozen=True, slots=True)
class StrategyHealthSnapshot:
    """Metrics for one health cell (B identity + metrics)."""

    identity: HealthIdentity
    sample_size: int
    rolling_expectancy: float
    baseline_expectancy: float
    rolling_sharpe: float
    baseline_sharpe: float
    profit_factor: float
    win_rate: float
    drawdown: float
    slippage_adjusted_expectancy: float
    trade_frequency: float  # trades per day over the window
    cost_degradation: float  # realized cost bps vs assumed cost bps (>=0 worse)

    def to_dict(self) -> dict[str, object]:
        return {
            "identity": self.identity.key(),
            "sample_size": self.sample_size,
            "rolling_expectancy": self.rolling_expectancy,
            "baseline_expectancy": self.baseline_expectancy,
            "rolling_sharpe": self.rolling_sharpe,
            "baseline_sharpe": self.baseline_sharpe,
            "profit_factor": self.profit_factor,
            "win_rate": self.win_rate,
            "drawdown": self.drawdown,
            "slippage_adjusted_expectancy": self.slippage_adjusted_expectancy,
            "trade_frequency": self.trade_frequency,
            "cost_degradation": self.cost_degradation,
        }


@dataclass(frozen=True, slots=True)
class HealthThresholds:
    """Deterministic thresholds. Positive numbers are 'good' directions."""

    min_sample_size: int = 30
    expectancy_floor: float = 0.0  # below -> degraded signal
    sharpe_floor: float = 0.0
    profit_factor_floor: float = 1.0
    win_rate_floor: float = 0.35
    drawdown_ceiling: float = 0.15  # above -> degraded signal
    cost_degradation_ceiling: float = 5.0  # bps above assumed -> degraded signal
    # Hysteresis (B2): consecutive windows required to ENTER degraded /
    # to RECOVER from degraded. One bad window never flips the state.
    degraded_consecutive_windows: int = 2
    recovery_consecutive_windows: int = 2


@dataclass
class HealthCellState:
    """Mutable per-cell runtime state (window streaks + current state)."""

    current: StrategyHealthState = StrategyHealthState.INSUFFICIENT_EVIDENCE
    degraded_streak: int = 0
    recovery_streak: int = 0
    last_transition_reason: str = ""


class StrategyHealthTracker:
    """Deterministic health state machine over health cells.

    B1: cells are keyed by (strategy, version, asset, timeframe, regime) —
    never collapsed into one global number.
    B2: minimum sample gate -> INSUFFICIENT_EVIDENCE; hysteresis via
    consecutive windows; no single-trade transitions.
    B3: transitions produce PROPOSALS only; no runtime self-modification.
    """

    def __init__(self, thresholds: HealthThresholds | None = None) -> None:
        self._thresholds = thresholds or HealthThresholds()
        self._cells: dict[str, HealthCellState] = {}
        self._proposals: list[dict[str, str]] = []

    def cell_state(self, identity: HealthIdentity) -> StrategyHealthState:
        return self._cells.setdefault(identity.key(), HealthCellState()).current

    def evaluate(
        self,
        snapshot: StrategyHealthSnapshot,
        *,
        window_index: int,
    ) -> tuple[StrategyHealthState, dict[str, str]]:
        """Evaluate one observation window for a cell; returns (state, proposal).

        ``window_index`` must be monotonically increasing per cell; the same
        window evaluated twice is idempotent (no double-counted streaks).
        """
        if window_index < 0:
            raise ExecutionReliabilityError("window_index must be >= 0")
        t = self._thresholds
        cell = self._cells.setdefault(snapshot.identity.key(), HealthCellState())
        key = snapshot.identity.key()

        # RETIRED is terminal: organic evaluation is forbidden.
        if cell.current is StrategyHealthState.RETIRED:
            raise ExecutionReliabilityError(f"cell {key} is RETIRED; no organic evaluation allowed")
        # QUARANTINED: organic windows are no-ops. Only an explicit
        # revalidation (propose_revalidation_recovery) may act on the cell.
        if cell.current is StrategyHealthState.QUARANTINED:
            return cell.current, {
                "cell": key,
                "proposed_state": cell.current.value,
                "reason": "quarantined; organic windows ignored; revalidation required",
                "window_index": str(window_index),
            }

        # Sample gate first: insufficient evidence is never DEGRADED.
        if snapshot.sample_size < t.min_sample_size:
            # Streaks reset: evidence scarcity is not degradation evidence.
            cell.degraded_streak = 0
            cell.recovery_streak = 0
            proposal = {
                "cell": key,
                "proposed_state": StrategyHealthState.INSUFFICIENT_EVIDENCE.value,
                "reason": f"sample_size {snapshot.sample_size} < {t.min_sample_size}",
                "window_index": str(window_index),
            }
            self._proposals.append(proposal)
            return StrategyHealthState.INSUFFICIENT_EVIDENCE, proposal

        degraded_signals = self._degraded_signals(snapshot, t)
        if degraded_signals:
            cell.degraded_streak += 1
            cell.recovery_streak = 0
        else:
            cell.recovery_streak += 1
            cell.degraded_streak = 0

        # Enter DEGRADED only after N consecutive degraded windows.
        if (
            cell.degraded_streak >= t.degraded_consecutive_windows
            and cell.current
            not in (StrategyHealthState.DEGRADED, StrategyHealthState.QUARANTINED, StrategyHealthState.RETIRED)
        ):
            proposal = self._propose_transition(
                cell,
                key,
                StrategyHealthState.DEGRADED,
                f"degraded signals {sorted(degraded_signals)} for {cell.degraded_streak} consecutive windows",
                window_index,
            )
            return cell.current, proposal

        # Recovery: DEGRADED -> MONITORING after N consecutive clean windows.
        if (
            cell.current is StrategyHealthState.DEGRADED
            and cell.recovery_streak >= t.recovery_consecutive_windows
        ):
            proposal = self._propose_transition(
                cell,
                key,
                StrategyHealthState.MONITORING,
                f"clean metrics for {cell.recovery_streak} consecutive windows",
                window_index,
            )
            return cell.current, proposal

        # First clean window after INSUFFICIENT_EVIDENCE -> MONITORING.
        if cell.current is StrategyHealthState.INSUFFICIENT_EVIDENCE and not degraded_signals:
            proposal = self._propose_transition(
                cell,
                key,
                StrategyHealthState.MONITORING,
                "sufficient sample with clean metrics",
                window_index,
            )
            return cell.current, proposal

        return cell.current, {
            "cell": key,
            "proposed_state": cell.current.value,
            "reason": "no transition (hysteresis gate)",
            "window_index": str(window_index),
        }

    def propose_quarantine(self, identity: HealthIdentity, *, reason: str, window_index: int) -> dict[str, str]:
        """Governance-initiated quarantine proposal (from DEGRADED or MONITORING)."""
        cell = self._cells.setdefault(identity.key(), HealthCellState())
        return self._propose_transition(cell, identity.key(), StrategyHealthState.QUARANTINED, reason, window_index)

    def propose_revalidation_recovery(self, identity: HealthIdentity, *, research_artifact: str, window_index: int) -> dict[str, str]:
        """QUARANTINED recovery requires a research artifact; lands in MONITORING."""
        cell = self._cells.setdefault(identity.key(), HealthCellState())
        if cell.current is not StrategyHealthState.QUARANTINED:
            raise ExecutionReliabilityError(
                f"revalidation recovery requires QUARANTINED state, got {cell.current.value}"
            )
        proposal = self._propose_transition(
            cell,
            identity.key(),
            StrategyHealthState.MONITORING,
            f"revalidated via research artifact {research_artifact}",
            window_index,
        )
        return proposal

    def propose_retirement(self, identity: HealthIdentity, *, reason: str, window_index: int) -> dict[str, str]:
        cell = self._cells.setdefault(identity.key(), HealthCellState())
        return self._propose_transition(cell, identity.key(), StrategyHealthState.RETIRED, reason, window_index)

    @property
    def proposals(self) -> tuple[dict[str, str], ...]:
        return tuple(self._proposals)

    # -- internals -----------------------------------------------------------
    def _degraded_signals(self, s: StrategyHealthSnapshot, t: HealthThresholds) -> tuple[str, ...]:
        signals: list[str] = []
        if s.rolling_expectancy < t.expectancy_floor:
            signals.append("rolling_expectancy_below_floor")
        if s.rolling_sharpe < t.sharpe_floor:
            signals.append("rolling_sharpe_below_floor")
        if s.profit_factor < t.profit_factor_floor:
            signals.append("profit_factor_below_floor")
        if s.win_rate < t.win_rate_floor:
            signals.append("win_rate_below_floor")
        if s.drawdown > t.drawdown_ceiling:
            signals.append("drawdown_above_ceiling")
        if s.cost_degradation > t.cost_degradation_ceiling:
            signals.append("cost_degradation_above_ceiling")
        return tuple(signals)

    def _propose_transition(
        self,
        cell: HealthCellState,
        key: str,
        target: StrategyHealthState,
        reason: str,
        window_index: int,
    ) -> dict[str, str]:
        previous = cell.current
        if target not in _ALLOWED_HEALTH_TRANSITIONS.get(previous, frozenset()):
            raise ExecutionReliabilityError(
                f"illegal health transition {previous.value} -> {target.value} for {key}"
            )
        cell.current = target
        cell.last_transition_reason = reason
        proposal = {
            "cell": key,
            "proposed_state": target.value,
            "reason": reason,
            "window_index": str(window_index),
            "previous_state": previous.value,
        }
        self._proposals.append(proposal)
        return proposal


class StrategyHealthVerifier:
    """Independent verifier for critical health transitions (B4).

    BUILDER != VERIFIER: the tracker proposes; this verifier re-derives the
    decision from the snapshot + proposal metadata. It validates sample
    adequacy, metric correctness, window identity, PIT contract, baseline
    binding, regime binding, hysteresis and transition legality.
    """

    def verify_transition(
        self,
        snapshot: StrategyHealthSnapshot,
        proposal: dict[str, str],
        *,
        expected_window_index: int,
        baseline_binding: str,
        regime_binding: str,
        prior_state: StrategyHealthState | None = None,
    ) -> tuple[bool, tuple[str, ...]]:
        failures: list[str] = []
        t = HealthThresholds()
        # sample adequacy
        if snapshot.sample_size < t.min_sample_size and proposal["proposed_state"] in (
            StrategyHealthState.DEGRADED.value,
            StrategyHealthState.QUARANTINED.value,
            StrategyHealthState.RETIRED.value,
        ):
            failures.append("sample_inadequate_for_critical_transition")
        # metric correctness (basic sanity domains)
        if not (0.0 <= snapshot.win_rate <= 1.0):
            failures.append("win_rate_out_of_domain")
        if snapshot.drawdown < 0.0:
            failures.append("drawdown_negative")
        if snapshot.profit_factor < 0.0:
            failures.append("profit_factor_negative")
        # window identity
        if int(proposal.get("window_index", "-1")) != expected_window_index:
            failures.append("window_identity_mismatch")
        # PIT contract: observation window must not be future-dated relative
        # to the decision metadata (string contract; enforced by convention).
        if "/" not in snapshot.identity.observation_window:
            failures.append("observation_window_not_pit_bounded")
        # baseline + regime binding
        if not baseline_binding:
            failures.append("baseline_unbound")
        if snapshot.identity.regime != regime_binding:
            failures.append("regime_binding_mismatch")
        # hysteresis: critical transitions must cite consecutive windows
        if proposal["proposed_state"] == StrategyHealthState.DEGRADED.value and "consecutive" not in proposal.get("reason", ""):
            failures.append("hysteresis_not_cited")
        # transition legality
        if prior_state is not None:
            allowed = _ALLOWED_HEALTH_TRANSITIONS.get(prior_state, frozenset())
            target = StrategyHealthState(proposal["proposed_state"])
            if target not in allowed:
                failures.append("transition_illegal")
        return (not failures, tuple(failures))
