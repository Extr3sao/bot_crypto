"""Strategy Selector for V0.3 — manages confirmed strategies for paper trading.

V0.3 reads confirmed strategies from V0.2.x research pipeline
and validates they are ready for paper trading.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import structlog

StrategyStatus = Literal[
    "PENDING",  # Not yet validated
    "READY",  # Validated and ready for paper
    "ACTIVE",  # Currently trading
    "SUSPENDED",  # Temporarily disabled
    "DEPRECATED",  # No longer used
]


@dataclass(frozen=True, slots=True)
class StrategyConfig:
    """Configuration for a paper trading strategy."""

    strategy_id: str
    name: str
    version: str
    source_experiment_id: str  # V0.2.x experiment that confirmed this
    status: StrategyStatus = "PENDING"

    # Trading parameters
    symbols: list[str] = field(default_factory=list)
    timeframe: str = "5m"
    risk_per_trade_pct: float = 0.0025
    max_exposure_pct: float = 0.25
    max_positions: int = 1

    # Entry/Exit rules
    entry_rules: dict[str, Any] = field(default_factory=dict)
    exit_rules: dict[str, Any] = field(default_factory=dict)

    # Metadata
    created_at: float = field(default_factory=time.time)
    confirmed_at: float | None = None
    last_trade_at: float | None = None
    total_trades: int = 0
    total_pnl: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "name": self.name,
            "version": self.version,
            "source_experiment_id": self.source_experiment_id,
            "status": self.status,
            "symbols": self.symbols,
            "timeframe": self.timeframe,
            "risk_per_trade_pct": self.risk_per_trade_pct,
            "max_exposure_pct": self.max_exposure_pct,
            "max_positions": self.max_positions,
            "created_at": self.created_at,
            "confirmed_at": self.confirmed_at,
            "total_trades": self.total_trades,
            "total_pnl": self.total_pnl,
        }


class StrategySelector:
    """Manages strategies for paper trading.

    V0.3 reads confirmed strategies from V0.2.x research.
    """

    def __init__(self, config_dir: Path = Path("config/strategies")) -> None:
        self._config_dir = config_dir
        self._strategies: dict[str, StrategyConfig] = {}
        self._log = structlog.get_logger("strategy_selector")
        self._load_strategies()

    def _load_strategies(self) -> None:
        """Load strategy configurations from disk."""
        if not self._config_dir.exists():
            self._config_dir.mkdir(parents=True, exist_ok=True)
            return

        for path in self._config_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                config = StrategyConfig(**data)
                self._strategies[config.strategy_id] = config
            except Exception as e:
                self._log.warning("strategy.load_failed", path=str(path), error=str(e))

    def register_strategy(self, config: StrategyConfig) -> None:
        """Register a new strategy configuration."""
        self._strategies[config.strategy_id] = config
        self._save_strategy(config)
        self._log.info("strategy.registered", strategy_id=config.strategy_id)

    def activate_strategy(self, strategy_id: str) -> bool:
        """Activate a strategy for paper trading."""
        config = self._strategies.get(strategy_id)
        if config is None:
            return False

        if config.status not in ("READY", "SUSPENDED"):
            self._log.warning("strategy.cannot_activate", status=config.status)
            return False

        # Update status
        updated = StrategyConfig(
            strategy_id=config.strategy_id,
            name=config.name,
            version=config.version,
            source_experiment_id=config.source_experiment_id,
            status="ACTIVE",
            symbols=config.symbols,
            timeframe=config.timeframe,
            risk_per_trade_pct=config.risk_per_trade_pct,
            max_exposure_pct=config.max_exposure_pct,
            max_positions=config.max_positions,
            entry_rules=config.entry_rules,
            exit_rules=config.exit_rules,
            created_at=config.created_at,
            confirmed_at=config.confirmed_at,
            total_trades=config.total_trades,
            total_pnl=config.total_pnl,
        )

        self._strategies[strategy_id] = updated
        self._save_strategy(updated)
        self._log.info("strategy.activated", strategy_id=strategy_id)
        return True

    def deactivate_strategy(self, strategy_id: str) -> bool:
        """Deactivate a strategy."""
        config = self._strategies.get(strategy_id)
        if config is None:
            return False

        updated = StrategyConfig(
            strategy_id=config.strategy_id,
            name=config.name,
            version=config.version,
            source_experiment_id=config.source_experiment_id,
            status="SUSPENDED",
            symbols=config.symbols,
            timeframe=config.timeframe,
            risk_per_trade_pct=config.risk_per_trade_pct,
            max_exposure_pct=config.max_exposure_pct,
            max_positions=config.max_positions,
            entry_rules=config.entry_rules,
            exit_rules=config.exit_rules,
            created_at=config.created_at,
            confirmed_at=config.confirmed_at,
            total_trades=config.total_trades,
            total_pnl=config.total_pnl,
        )

        self._strategies[strategy_id] = updated
        self._save_strategy(updated)
        self._log.info("strategy.deactivated", strategy_id=strategy_id)
        return True

    def get_active_strategies(self) -> list[StrategyConfig]:
        """Get all active strategies."""
        return [s for s in self._strategies.values() if s.status == "ACTIVE"]

    def get_strategy(self, strategy_id: str) -> StrategyConfig | None:
        """Get a strategy by ID."""
        return self._strategies.get(strategy_id)

    def list_strategies(self) -> list[StrategyConfig]:
        """List all strategies."""
        return list(self._strategies.values())

    def update_trade_stats(self, strategy_id: str, pnl: float) -> None:
        """Update trade statistics for a strategy."""
        config = self._strategies.get(strategy_id)
        if config is None:
            return

        updated = StrategyConfig(
            strategy_id=config.strategy_id,
            name=config.name,
            version=config.version,
            source_experiment_id=config.source_experiment_id,
            status=config.status,
            symbols=config.symbols,
            timeframe=config.timeframe,
            risk_per_trade_pct=config.risk_per_trade_pct,
            max_exposure_pct=config.max_exposure_pct,
            max_positions=config.max_positions,
            entry_rules=config.entry_rules,
            exit_rules=config.exit_rules,
            created_at=config.created_at,
            confirmed_at=config.confirmed_at,
            last_trade_at=time.time(),
            total_trades=config.total_trades + 1,
            total_pnl=config.total_pnl + pnl,
        )

        self._strategies[strategy_id] = updated
        self._save_strategy(updated)

    def _save_strategy(self, config: StrategyConfig) -> None:
        """Save strategy configuration to disk."""
        path = self._config_dir / f"{config.strategy_id}.json"
        path.write_text(
            json.dumps(config.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )


__all__ = [
    "StrategyConfig",
    "StrategySelector",
    "StrategyStatus",
]
