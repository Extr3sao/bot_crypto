"""Strategy Router (EPIC 3).

Resolves: AssetContext + Regime + AssetStrategyRegimeMap → Selected Strategy.

The router is a pure resolver:
- No side effects
- No market data access
- No execution access
- Deterministic: same inputs → same output

May return NO_TRADE if no strategy passes its gates. Never forces trades.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# The gate contract itself lives in ``router_gates``: one definition, so the
# freshness rule cannot drift between two copies. Re-exported here because this
# module is the public import site for ``RouterGates``.
from .router_gates import RouterGates

__all__ = [
    "PAPER_EXECUTABLE_STATUS_NAMES",
    "RouterDecision",
    "RouterGates",
    "StrategyRouter",
]

#: §17/§19 — the lifecycle states that authorise PAPER execution. Kept as a
#: local constant (rather than importing the autonomous package) so the research
#: router keeps its dependency direction: it may not import the runtime.
PAPER_EXECUTABLE_STATUS_NAMES: frozenset[str] = frozenset(
    {"PAPER_CANDIDATE", "PAPER_ACTIVE"}
)


@dataclass(frozen=True, slots=True)
class RouterDecision:
    """Output of the StrategyRouter for one asset at one timestamp."""

    asset: str
    timestamp: int

    # Selected strategy (None when NO_TRADE)
    strategy_id: str | None = None
    family: str | None = None
    direction: str | None = None  # "LONG" / "SHORT"

    # NO_TRADE reason (set when strategy_id is None)
    no_trade_reason: str | None = None

    # Routing trace (why this strategy / why not)
    trace: list[str] = field(default_factory=list)

    @property
    def is_no_trade(self) -> bool:
        return self.strategy_id is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "timestamp": self.timestamp,
            "strategy_id": self.strategy_id,
            "family": self.family,
            "direction": self.direction,
            "no_trade_reason": self.no_trade_reason,
            "trace": self.trace,
        }


class StrategyRouter:
    """Pure resolver: AssetContext + Regime + AssetStrategyRegimeMap → strategy.

    The map is a dict of: strategy_id → {families, regimes, direction, enabled}.
    The router consults the map, checks gates, and returns the best match.
    If nothing passes → NO_TRADE with reason. Never forces a trade.
    """

    def __init__(self, gates: RouterGates | None = None) -> None:
        self.gates = gates if gates is not None else RouterGates()

    def route(
        self,
        context: Any,  # AssetContext
        regime: str | None,
        strategy_map: dict[str, dict[str, Any]],
    ) -> RouterDecision:
        """Resolve the selected strategy for one asset at one timestamp.

        strategy_map entry format:
        {
            "strategy_id": {
                "family": "momentum",
                "regimes": ["TREND_UP", "TREND_DOWN"],
            "direction": "LONG",       # or "SHORT" or "BOTH"
            "enabled": True,
            "status": "PAPER_ACTIVE",  # the strategy's lifecycle state (§17)
            "priority": 0.5,           # optional tie-breaker
            },
            ...
        }
        """
        asset = getattr(context, "asset", "unknown")
        timestamp = getattr(context, "timestamp", 0)
        trace: list[str] = []

        if not strategy_map:
            return RouterDecision(
                asset=asset,
                timestamp=timestamp,
                no_trade_reason="empty_strategy_map",
                trace=["strategy map is empty"],
            )

        # Gate: context freshness
        if self.gates.require_fresh_context and self._is_stale(context):
            return RouterDecision(
                asset=asset,
                timestamp=timestamp,
                no_trade_reason="stale_context",
                trace=[f"context at {timestamp} is stale"],
            )
        trace.append("context_fresh")

        # Gate: data quality
        quality = self._data_quality(context)
        if quality < self.gates.min_data_quality:
            return RouterDecision(
                asset=asset,
                timestamp=timestamp,
                no_trade_reason="low_data_quality",
                trace=[f"data quality {quality:.2f} < {self.gates.min_data_quality:.2f}"],
            )
        trace.append(f"data_quality={quality:.2f}")

        # Current regime (from context or explicit override)
        current_regime = regime or getattr(context, "market_regime", None)
        if current_regime:
            trace.append(f"regime={current_regime}")

        # Iterate strategies, find best match
        best: tuple[str, dict[str, Any]] | None = None
        best_score: float = -1.0

        for sid, entry in strategy_map.items():
            # Gate: enabled
            if not entry.get("enabled", False):
                trace.append(f"{sid}: disabled")
                continue

            # Gate: research confirmation.
            #
            # DEF-AUTO-4: this used to compare against a literal "CONFIRMED",
            # which the legacy entrypoints stamped on every family whether or
            # not research had admitted it. The gate now accepts only the
            # lifecycle states that authorise PAPER execution, taken from the
            # contract, so a strategy can never be selected because somebody
            # wrote the right string in a map (§17, §19).
            if self.gates.require_confirmed:
                status = str(entry.get("status", "PENDING"))
                if status not in PAPER_EXECUTABLE_STATUS_NAMES:
                    trace.append(
                        f"{sid}: status={status}, need one of "
                        f"{sorted(PAPER_EXECUTABLE_STATUS_NAMES)}"
                    )
                    continue

            # Gate: regime match
            if self.gates.require_regime_match and current_regime:
                allowed = entry.get("regimes", [])
                if allowed and current_regime not in allowed:
                    trace.append(f"{sid}: regime {current_regime} not in {allowed}")
                    continue

            # Score: prefer strategies that list this regime explicitly
            score = 1.0
            if current_regime and current_regime in entry.get("regimes", []):
                score += 1.0
            if entry.get("priority"):
                score += float(entry["priority"])

            trace.append(f"{sid}: match score={score:.1f}")
            if score > best_score:
                best_score = score
                best = (sid, entry)

        if best is None:
            trace.append("no strategy passed all gates")
            return RouterDecision(
                asset=asset,
                timestamp=timestamp,
                no_trade_reason="no_strategy_passed_gates",
                trace=trace,
            )

        sid, entry = best
        direction = entry.get("direction", "BOTH")
        return RouterDecision(
            asset=asset,
            timestamp=timestamp,
            strategy_id=sid,
            family=entry.get("family"),
            direction=direction if direction in ("LONG", "SHORT") else None,
            trace=trace,
        )

    # -- helpers -----------------------------------------------------------

    def _is_stale(self, context: Any) -> bool:
        """Check context staleness via bar_count / window_end_ts.

        The budget comes from the gates, which derive it from the timeframe the
        strategies run on (§38, DEF-AUTO-3) instead of a fixed 15 minutes.
        """
        end_ts = getattr(context, "window_end_ts", 0)
        newest = getattr(context, "timestamp", 0)
        if not end_ts or not newest:
            return True
        # Stale if the context window ends too far behind the timestamp.
        return (newest - end_ts) > self.gates.stale_after_ms()

    def _data_quality(self, context: Any) -> float:
        """Derive a 0.0-1.0 quality score from AssetContext."""
        dq = getattr(context, "data_quality", None)
        if not dq:
            return 0.0
        bars = dq.get("bars_in_window", 0)
        # 120 bars = full window = 1.0; linear below that
        return float(min(1.0, bars / 120.0))
