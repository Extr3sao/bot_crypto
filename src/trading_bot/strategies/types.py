"""Strategy types — Signal, Side, StrategyConfig.

Fase 4 domain types. No I/O, no exchange, no execution coupling.
Frozen dataclasses for safe propagation through the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Side = Literal["buy", "sell"]
StrategyState = Literal["disabled", "research", "paper", "live_candidate", "live"]


@dataclass(frozen=True, slots=True)
class Signal:
    """Canonical signal emitted by a strategy.

    Everything downstream (risk manager, execution) consumes this.
    The signal does NOT carry position sizing — that's the risk
    manager's responsibility.
    """

    symbol: str
    side: Side
    strategy_name: str
    timeframe: str
    confidence: float  # 0.0 - 1.0
    price: float  # reference price at signal time
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0, 1], got {self.confidence}")


@dataclass(frozen=True, slots=True)
class StrategyConfig:
    """Runtime configuration for a strategy (resolved from YAML)."""

    name: str
    state: StrategyState
    enabled: bool
    description: str
    timeframes: list[str]
    indicator_names: list[str]
    entry_rules: dict[str, Any]
    exit_rules: dict[str, Any]
    filters: dict[str, Any]

    @property
    def is_active(self) -> bool:
        """True if strategy can produce signals in its current state."""
        return self.enabled and self.state in ("research", "paper", "live_candidate", "live")

    @property
    def is_paper(self) -> bool:
        return self.state == "paper"


__all__ = ["Side", "Signal", "StrategyConfig", "StrategyState"]
