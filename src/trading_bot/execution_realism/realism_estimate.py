"""ExecutionRealismEstimate — diagnostic per-trade realism (§25).

Pure, deterministic, network-free. Unknown components remain explicit (None).
No fake values are produced. Confidence degrades with each unknown.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .cost_authority import Confidence


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


@dataclass(frozen=True, slots=True)
class ExecutionRealismEstimate:
    """One diagnostic per-trade cost breakdown (§25).

    All bps fields are round-trip unless stated. If a component is unknown,
    its field is None and ``missing_components`` lists its name. ``total_cost_bps``
    is None if any required component is unknown and no conservative bound is supplied.
    """

    asset: str
    direction: str  # long/short
    order_type: OrderType
    notional_usdt: float
    holding_period: str  # e.g. "1h" for H6, or "8h", etc.

    fee_cost_bps: float | None = None
    spread_cost_bps: float | None = None
    slippage_bps: float | None = None
    impact_bps: float | None = None
    funding_bps: float | None = None
    other_bps: float | None = None

    total_cost_bps: float | None = None
    confidence: Confidence = Confidence.UNKNOWN
    missing_components: tuple[str, ...] = ()
    limitations: str = ""
    source_refs: tuple[str, ...] = ()

    @staticmethod
    def build(
        *,
        asset: str,
        direction: str,
        order_type: OrderType | str,
        notional_usdt: float,
        holding_period: str,
        fee_cost_bps: float | None,
        spread_cost_bps: float | None,
        slippage_bps: float | None,
        impact_bps: float | None,
        funding_bps: float | None,
        other_bps: float | None = None,
        source_refs: tuple[str, ...] = (),
        limitations: str = "",
    ) -> ExecutionRealismEstimate:
        if isinstance(order_type, str):
            order_type = OrderType(order_type)
        if direction.lower() not in ("long", "short"):
            raise ValueError("direction must be long/short")

        components = {
            "fee": fee_cost_bps,
            "spread": spread_cost_bps,
            "slippage": slippage_bps,
            "impact": impact_bps,
            "funding": funding_bps,
        }
        missing: list[str] = [k for k, v in components.items() if v is None]
        # total is sum of known only if nothing missing (be conservative)
        total: float | None = None
        if not missing:
            vals = [v for v in components.values() if v is not None]
            # include other if known
            if other_bps is not None:
                vals.append(other_bps)
            total = sum(vals)  # type: ignore[arg-type]

        # confidence: HIGH only if no missing and all sources are official
        if missing:
            conf = Confidence.LOW if len(missing) <= 2 else Confidence.UNKNOWN
        else:
            conf = Confidence.MEDIUM  # without live depth proof, not HIGH
            if any("OFFICIAL_EXCHANGE" in s for s in source_refs):
                conf = Confidence.MEDIUM  # keep medium until full spread/latency proof

        return ExecutionRealismEstimate(
            asset=asset,
            direction=direction.lower(),
            order_type=order_type,
            notional_usdt=notional_usdt,
            holding_period=holding_period,
            fee_cost_bps=fee_cost_bps,
            spread_cost_bps=spread_cost_bps,
            slippage_bps=slippage_bps,
            impact_bps=impact_bps,
            funding_bps=funding_bps,
            other_bps=other_bps,
            total_cost_bps=total,
            confidence=conf,
            missing_components=tuple(missing),
            limitations=limitations,
            source_refs=source_refs,
        )

    def net_edge_bps(self, gross_edge_bps: float | None) -> float | None:
        """NET_EDGE = GROSS_EDGE - REALISTIC_COST (§30). None if cost unknown."""
        if self.total_cost_bps is None or gross_edge_bps is None:
            return None
        return gross_edge_bps - self.total_cost_bps
