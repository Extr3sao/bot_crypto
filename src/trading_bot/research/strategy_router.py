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
    "RoutedStrategy",
    "RouterDecision",
    "RouterGates",
    "RouterSelection",
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


#: Machine-readable routing verdicts. ``SELECTED`` is the only one that lets
#: a strategy reach the next stage; every other value is an explicit refusal.
ROUTER_VERDICTS: frozenset[str] = frozenset(
    {
        "SELECTED",
        "REJECTED",
        "NOT_APPLICABLE",
        "PAUSED",
        "DEGRADED",
        "THROTTLED",
        "INSUFFICIENT_EVIDENCE",
        "REGIME_MISMATCH",
        "RISK_CONFLICT",
        "PORTFOLIO_CONFLICT",
    }
)


@dataclass(frozen=True, slots=True)
class RoutedStrategy:
    """One strategy's routing verdict, always with a reason."""

    strategy_id: str
    verdict: str
    reason: str = ""
    family: str | None = None
    direction: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "verdict": self.verdict,
            "reason": self.reason,
            "family": self.family,
            "direction": self.direction,
        }


@dataclass(frozen=True, slots=True)
class RouterSelection:
    """Result of :meth:`StrategyRouter.select_eligible_strategies`.

    Unlike :meth:`route`, this returns EVERY eligible strategy plus the verdict
    for every non-eligible one — no candidate is silently dropped, and the
    system can hold more than one ACTIVE strategy at a time (§10/§13).
    """

    asset: str
    timestamp: int
    selected: tuple[str, ...] = ()
    routed: tuple[RoutedStrategy, ...] = ()
    trace: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.selected

    def by_verdict(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for item in self.routed:
            out.setdefault(item.verdict, []).append(item.strategy_id)
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "timestamp": self.timestamp,
            "selected": list(self.selected),
            "routed": [r.to_dict() for r in self.routed],
            "trace": list(self.trace),
        }


class StrategyRouter:
    """Pure resolver: AssetContext + Regime + AssetStrategyRegimeMap → strategy.

    The map is a dict of: strategy_id → {families, regimes, direction, enabled}.
    The router consults the map, checks gates, and returns the best match.
    If nothing passes → NO_TRADE with reason. Never forces a trade.

    ``select_eligible_strategies`` is the dynamic-ecosystem entry point: it
    returns the full eligible set with lifecycle/health/portfolio verdicts
    instead of collapsing everything to one winner.
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

    def select_eligible_strategies(
        self,
        context: Any,
        regime: str | None,
        strategy_map: dict[str, dict[str, Any]],
        *,
        lifecycle: dict[str, str] | None = None,
        health: dict[str, str] | None = None,
        performance: dict[str, float] | None = None,
        min_expectancy_bps: float | None = None,
        risk_blocked: frozenset[str] | set[str] = frozenset(),
        portfolio_rejected: frozenset[str] | set[str] = frozenset(),
    ) -> RouterSelection:
        """Return the whole eligible set with per-strategy verdicts (§13).

        This is deliberately NOT ``best_strategy()``. Multiple strategies may be
        eligible at once; the caller (portfolio manager) arbitrates overlap. The
        router only decides *eligibility* and explains every refusal with a
        machine-readable verdict — a candidate is never silently dropped.

        ``lifecycle`` is a ``strategy_id -> dynamic lifecycle state`` map (e.g.
        ``ACTIVE``/``DEGRADED``/``PAUSED``/``SHADOW``). When absent, the router
        falls back to the legacy ``status`` field so existing callers keep
        working unchanged.
        """
        asset = getattr(context, "asset", "unknown")
        timestamp = getattr(context, "timestamp", 0)
        trace: list[str] = []
        routed: list[RoutedStrategy] = []
        selected: list[str] = []

        if not strategy_map:
            return RouterSelection(
                asset=asset, timestamp=timestamp, trace=("strategy map is empty",)
            )
        if self.gates.require_fresh_context and self._is_stale(context):
            return RouterSelection(
                asset=asset,
                timestamp=timestamp,
                trace=(f"context at {timestamp} is stale",),
            )
        trace.append("context_fresh")
        quality = self._data_quality(context)
        if quality < self.gates.min_data_quality:
            return RouterSelection(
                asset=asset,
                timestamp=timestamp,
                trace=(f"data quality {quality:.2f} < {self.gates.min_data_quality:.2f}",),
            )
        trace.append(f"data_quality={quality:.2f}")
        current_regime = regime or getattr(context, "market_regime", None)
        if current_regime:
            trace.append(f"regime={current_regime}")

        for sid in sorted(strategy_map):
            entry = strategy_map[sid]
            family = entry.get("family")
            direction = entry.get("direction")
            verdict, reason = self._verdict_for(
                sid,
                entry,
                current_regime,
                lifecycle=lifecycle,
                health=health,
                performance=performance,
                min_expectancy_bps=min_expectancy_bps,
                risk_blocked=risk_blocked,
                portfolio_rejected=portfolio_rejected,
            )
            routed.append(
                RoutedStrategy(
                    strategy_id=sid,
                    verdict=verdict,
                    reason=reason,
                    family=family,
                    direction=direction if direction in ("LONG", "SHORT") else None,
                )
            )
            trace.append(f"{sid}: {verdict}" + (f" ({reason})" if reason else ""))
            if verdict == "SELECTED":
                selected.append(sid)

        return RouterSelection(
            asset=asset,
            timestamp=timestamp,
            selected=tuple(selected),
            routed=tuple(routed),
            trace=tuple(trace),
        )

    def _verdict_for(
        self,
        sid: str,
        entry: dict[str, Any],
        current_regime: str | None,
        *,
        lifecycle: dict[str, str] | None,
        health: dict[str, str] | None,
        performance: dict[str, float] | None,
        min_expectancy_bps: float | None,
        risk_blocked: set[str] | frozenset[str],
        portfolio_rejected: set[str] | frozenset[str],
    ) -> tuple[str, str]:
        if not entry.get("enabled", False):
            return "REJECTED", "disabled"
        if sid in risk_blocked:
            return "RISK_CONFLICT", "risk engine blocked this strategy"
        if sid in portfolio_rejected:
            return "PORTFOLIO_CONFLICT", "rejected by portfolio arbitration"

        state = None
        if lifecycle is not None and sid in lifecycle:
            state = str(lifecycle[sid]).upper()
        if state is not None:
            if state == "ACTIVE":
                pass
            elif state == "ELIGIBLE":
                return "INSUFFICIENT_EVIDENCE", "eligible but not yet active"
            elif state == "DEGRADED":
                return "DEGRADED", "strategy is degraded"
            elif state == "THROTTLED":
                return "THROTTLED", "strategy is throttled"
            elif state == "PAUSED":
                return "PAUSED", "strategy is paused"
            elif state == "RETIRED":
                return "REJECTED", "strategy is retired"
            else:  # DISCOVERED / CANDIDATE / VALIDATING / PAPER / SHADOW
                return "NOT_APPLICABLE", f"lifecycle state {state} does not route"
        elif self.gates.require_confirmed:
            status = str(entry.get("status", "PENDING"))
            if status not in PAPER_EXECUTABLE_STATUS_NAMES:
                return (
                    "NOT_APPLICABLE",
                    f"status={status}, need one of {sorted(PAPER_EXECUTABLE_STATUS_NAMES)}",
                )

        if self.gates.require_regime_match and current_regime:
            allowed = entry.get("regimes", [])
            if allowed and current_regime not in allowed:
                return "REGIME_MISMATCH", f"regime {current_regime} not in {allowed}"

        if health is not None and sid in health:
            hs = str(health[sid]).upper()
            if hs in ("DEGRADED", "CRITICAL"):
                return "DEGRADED", f"health={hs}"
            if hs == "INSUFFICIENT_DATA":
                return "INSUFFICIENT_EVIDENCE", "health insufficient data"
        if min_expectancy_bps is not None and performance is not None:
            exp = performance.get(sid)
            if exp is None or exp < min_expectancy_bps:
                return "INSUFFICIENT_EVIDENCE", f"net expectancy {exp} < {min_expectancy_bps}"
        return "SELECTED", ""

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
