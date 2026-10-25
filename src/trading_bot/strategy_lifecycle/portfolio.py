"""StrategyPortfolioManager — correlated exposure arbitration (§10).

Three strategies that all say "BUY BTC" are not three independent bets. This
manager looks at return correlation, position/asset/direction overlap and
concentration, and returns a :class:`PortfolioDecision` saying which proposals
survive. The RiskManager remains the final authority: this can only REDUCE,
never widen, what risk would allow.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

from .contracts import PortfolioDecision, RationaleCode

__all__ = [
    "PORTFOLIO_MANAGER_VERSION",
    "PortfolioProposal",
    "StrategyPortfolioManager",
    "pearson_correlation",
]

PORTFOLIO_MANAGER_VERSION: Final[str] = "strategy-portfolio-manager-v1"


@dataclass(frozen=True, slots=True)
class PortfolioProposal:
    """A strategy's proposal as seen by the portfolio manager."""

    strategy_id: str
    asset: str
    direction: str  # LONG / SHORT
    notional_usdt: float
    expected_net_edge_bps: float
    #: Net-return series for correlation (most recent last). Optional.
    net_return_series: tuple[float, ...] = ()
    regime: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "asset": self.asset,
            "direction": self.direction,
            "notional_usdt": round(self.notional_usdt, 8),
            "expected_net_edge_bps": round(self.expected_net_edge_bps, 8),
            "regime": self.regime,
        }


def pearson_correlation(a: Sequence[float], b: Sequence[float]) -> float | None:
    """Pearson correlation of two equal-length series, or ``None`` when undefined."""
    n = min(len(a), len(b))
    if n < 3:
        return None
    xa = list(a[-n:])
    xb = list(b[-n:])
    ma = sum(xa) / n
    mb = sum(xb) / n
    da = [v - ma for v in xa]
    db = [v - mb for v in xb]
    va = sum(v * v for v in da)
    vb = sum(v * v for v in db)
    if va <= 0 or vb <= 0:
        return None
    cov = sum(da[i] * db[i] for i in range(n))
    return float(cov / ((va**0.5) * (vb**0.5)))


@dataclass(frozen=True, slots=True)
class StrategyPortfolioManager:
    """Deterministic, correlation-aware proposal arbitration (§10)."""

    equity: float = 10_000.0
    max_asset_exposure_pct: float = 10.0
    max_total_exposure_pct: float = 25.0
    correlation_threshold: float = 0.7
    #: Same-direction proposals on one asset beyond this count are concentrated.
    max_same_direction_per_asset: int = 2
    version: str = PORTFOLIO_MANAGER_VERSION

    def arbitrate(
        self,
        proposals: Sequence[PortfolioProposal],
        *,
        timestamp_ms: int = 0,
    ) -> PortfolioDecision:
        accepted: list[PortfolioProposal] = []
        rejected: list[str] = []
        reasons: list[str] = []
        corr_flags: list[str] = []
        conc_flags: list[str] = []
        notes: list[str] = []

        # Deterministic order: best net edge first, then strategy id.
        ordered = sorted(
            proposals, key=lambda p: (-p.expected_net_edge_bps, p.strategy_id)
        )

        asset_budget = self.equity * (self.max_asset_exposure_pct / 100.0)
        total_budget = self.equity * (self.max_total_exposure_pct / 100.0)

        def asset_exposure(asset: str) -> float:
            return sum(p.notional_usdt for p in accepted if p.asset == asset)

        def total_exposure() -> float:
            return sum(p.notional_usdt for p in accepted)

        for proposal in ordered:
            # Total exposure
            if total_exposure() + proposal.notional_usdt > total_budget + 1e-6:
                rejected.append(proposal.strategy_id)
                reasons.append(RationaleCode.PORTFOLIO_CONFLICT.value)
                conc_flags.append(
                    f"total exposure would exceed {self.max_total_exposure_pct}% "
                    f"({total_exposure() + proposal.notional_usdt:.2f} > {total_budget:.2f})"
                )
                continue
            # Per-asset exposure
            if asset_exposure(proposal.asset) + proposal.notional_usdt > asset_budget + 1e-6:
                rejected.append(proposal.strategy_id)
                reasons.append(RationaleCode.CONCENTRATION_CONFLICT.value)
                conc_flags.append(
                    f"{proposal.asset} exposure would exceed "
                    f"{self.max_asset_exposure_pct}% ({asset_exposure(proposal.asset) + proposal.notional_usdt:.2f} > {asset_budget:.2f})"
                )
                continue
            # Same-direction concentration on one asset
            same_dir = [
                p
                for p in accepted
                if p.asset == proposal.asset and p.direction == proposal.direction
            ]
            if len(same_dir) >= self.max_same_direction_per_asset:
                rejected.append(proposal.strategy_id)
                reasons.append(RationaleCode.CONCENTRATION_CONFLICT.value)
                conc_flags.append(
                    f"{len(same_dir) + 1} same-direction {proposal.direction} "
                    f"proposals on {proposal.asset}"
                )
                continue
            # Return correlation with already-accepted proposals
            if self._correlated(proposal, accepted, corr_flags):
                rejected.append(proposal.strategy_id)
                reasons.append(RationaleCode.CORRELATION_CONFLICT.value)
                continue
            accepted.append(proposal)

        merged: dict[str, float] = {}
        for p in accepted:
            merged[p.asset] = merged.get(p.asset, 0.0) + p.notional_usdt

        if not reasons:
            reasons = [RationaleCode.SELECTED.value] if accepted else [RationaleCode.NOT_APPLICABLE.value]
        if not accepted:
            notes.append("no proposal survived portfolio arbitration; NO_TRADE is a valid outcome")

        return PortfolioDecision(
            accepted_proposals=tuple(p.strategy_id for p in accepted),
            rejected_proposals=tuple(rejected),
            merged_exposure=merged,
            correlation_flags=tuple(corr_flags),
            concentration_flags=tuple(conc_flags),
            reason_codes=tuple(sorted(set(reasons))),
            notes=tuple(notes),
            timestamp_ms=timestamp_ms,
        )

    def _correlated(
        self,
        proposal: PortfolioProposal,
        accepted: list[PortfolioProposal],
        flags: list[str],
    ) -> bool:
        for other in accepted:
            if other.asset != proposal.asset:
                continue
            if not proposal.net_return_series or not other.net_return_series:
                continue
            corr = pearson_correlation(proposal.net_return_series, other.net_return_series)
            if corr is not None and corr >= self.correlation_threshold:
                flags.append(
                    f"{proposal.strategy_id} vs {other.strategy_id} on {proposal.asset}: "
                    f"corr={corr:.2f}"
                )
                return True
        return False
