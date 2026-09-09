"""Shadow Campaign V2 runtime router (Track B, ALPHA-DISCOVERY-AND-SHADOW-V2-01).

Wires the next-campaign decision flow in ONE place so no runtime code path
can bypass capture:

    VERIFIED candidate
      -> RiskGateRouter.decide(...)
           verdict ACCEPT  -> route to PAPER (runtime executes as today)
           verdict REJECT  -> ShadowCaptureHook.on_risk_reject(...)
                              -> PIT resolution -> ShadowTrade

Strict isolation guarantees (SH-01..SH-04):

- the router NEVER calls PaperBroker, portfolio stores, RiskManager state
  or any accounting surface — on ACCEPT it simply returns the decision and
  the existing runtime path proceeds unchanged;
- on REJECT only the capture ledger + outcome ledger are written (separate
  files, separate accounting);
- the router is observational: it cannot mutate RiskManager, cannot relax
  any gate, cannot promote anything to PAPER.

Also provides :class:`ConditionedShadowMetrics` — per-reason counterfactual
metrics conditioned by strategy x asset x timeframe x regime x health x
correlation (B2/D1), and the shadow counters projection for Track G.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from trading_bot.shadow.integration import ShadowCaptureHook
from trading_bot.shadow.outcome import ShadowTrade

__all__ = [
    "ConditionedShadowMetrics",
    "RiskDecision",
    "RiskGateRouter",
    "ShadowCounters",
]


@dataclass(frozen=True, slots=True)
class RiskDecision:
    """Immutable outcome of one Risk gate evaluation."""

    decision_id: str
    verdict: str  # ACCEPT | REJECT
    reason: str | None  # required when REJECT
    capture_id: str | None = None  # set when REJECT (shadow capture id)

    def __post_init__(self) -> None:
        if self.verdict not in ("ACCEPT", "REJECT"):
            raise ValueError(f"invalid risk verdict: {self.verdict}")
        if self.verdict == "REJECT" and not self.reason:
            raise ValueError("REJECT decisions require a reason")
        if self.verdict == "ACCEPT" and self.capture_id is not None:
            raise ValueError("ACCEPT decisions never carry a shadow capture")


class RiskGateRouter:
    """Single routing point for verified candidates at the Risk gate.

    Wrap the REAL risk decision: the router never decides risk itself —
    ``verdict``/``reason`` must come from the campaign's RiskManager call.
    """

    def __init__(self, hook: ShadowCaptureHook) -> None:
        self._hook = hook

    def decide(
        self,
        *,
        verdict: str,
        reason: str | None,
        ctx: dict[str, Any],
    ) -> RiskDecision:
        """Route one verified candidate.

        ACCEPT: returns the decision; PAPER path is the runtime's existing
        behavior — the router performs no PaperBroker/portfolio calls.
        REJECT: persists one immutable shadow capture and returns the
        decision with its capture id.
        """
        v = str(verdict).upper()
        if v == "ACCEPT":
            return RiskDecision(decision_id=str(ctx["decision_id"]), verdict="ACCEPT", reason=None)
        if v != "REJECT":
            raise ValueError(f"invalid verdict: {verdict}")
        if not reason:
            raise ValueError("REJECT requires a risk rejection reason")
        ctx = dict(ctx)
        ctx["risk_verdict"] = "REJECT"
        ctx["risk_rejection_reason"] = str(reason)
        capture_id = self._hook.on_risk_reject(ctx)
        return RiskDecision(
            decision_id=str(ctx["decision_id"]),
            verdict="REJECT",
            reason=str(reason),
            capture_id=capture_id,
        )


class ConditionedShadowMetrics:
    """Counterfactual metrics conditioned by identity dimensions (B2/D1)."""

    def __init__(self, trades: Iterable[ShadowTrade]) -> None:
        self._trades: tuple[ShadowTrade, ...] = tuple(trades)

    def by_condition(
        self,
        *dimensions: str,
    ) -> dict[tuple[str, ...], dict[str, Any]]:
        """Group by named ShadowTrade fields, e.g. ``("risk_rejection_reason",
        "asset", "regime_signature")``. Unknown dimensions raise."""
        valid = set(ShadowTrade.__dataclass_fields__)
        for dim in dimensions:
            if dim not in valid:
                raise ValueError(f"unknown conditioning dimension: {dim}")
        groups: dict[tuple[str, ...], list[ShadowTrade]] = {}
        for t in self._trades:
            key = tuple(str(getattr(t, dim)) for dim in dimensions)
            groups.setdefault(key, []).append(t)
        out: dict[tuple[str, ...], dict[str, Any]] = {}
        for key, trades in groups.items():
            wins = sum(1 for t in trades if t.net_pnl > 0)
            losses = sum(1 for t in trades if t.net_pnl < 0)
            gross_win = sum(t.net_pnl for t in trades if t.net_pnl > 0)
            gross_loss = sum(-t.net_pnl for t in trades if t.net_pnl < 0)
            resolved = sum(1 for t in trades if t.exit_price is not None)
            equity = 0.0
            peak = 0.0
            max_dd = 0.0
            for t in trades:
                equity += t.net_pnl
                peak = max(peak, equity)
                max_dd = max(max_dd, peak - equity)
            out[key] = {
                "candidates": len(trades),
                "resolved": resolved,
                "wins": wins,
                "losses": losses,
                "expectancy_net": sum(t.net_pnl for t in trades) / len(trades),
                "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else None,
                "max_drawdown": max_dd,
                "r_multiples_mean": (
                    sum(t.r_multiple for t in trades if t.r_multiple is not None)
                    / max(resolved, 1)
                )
                if resolved
                else None,
            }
        return out


class ShadowCounters:
    """Read-only counters for the Track G projection."""

    def __init__(self, hook: ShadowCaptureHook) -> None:
        self._hook = hook

    def snapshot(self) -> dict[str, Any]:
        captures = self._hook.captures.captures
        trades = self._hook.outcomes.trades
        by_reason: dict[str, int] = {}
        for c in captures:
            by_reason[c.risk_rejection_reason] = (
                by_reason.get(c.risk_rejection_reason, 0) + 1
            )
        return {
            "captures_total": len(captures),
            "resolved_total": len(trades),
            "pending_total": len(captures) - len(trades),
            "captures_by_reason": by_reason,
            "paper_contamination": 0,  # structural: shadow writes no paper surface
        }
