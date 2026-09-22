"""Execution Assumptions Audit for V0.2.1 §15.

Documents exactly: entry timing, exit timing, commission, slippage,
funding, same-bar SL/TP policy, stop-first policy, quantity sizing,
min notional, risk per trade, max exposure, max positions, cooldown,
timezone.

No hidden assumptions permitted.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .evidence import EvidenceClass, EvidenceRecord

try:
    from trading_agent.core.models_v02 import sha256_hex
except ImportError:
    import hashlib

    def sha256_hex(data: str) -> str:
        return hashlib.sha256(data.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ExecutionAssumptions:
    """Complete execution assumptions for a backtest/research run.

    V0.2.1 §15: No hidden assumptions. All documented and hashed.
    """

    # Entry/Exit timing
    entry_timing: str = "close_of_signal_bar"  # or "next_bar_open"
    exit_timing: str = "close_of_exit_bar"

    # Costs
    commission_rate: float = 0.001  # 0.1% per side
    commission_model: str = "flat_pct"
    slippage_bps: float = 5.0
    slippage_model: str = "flat_bps"
    funding_enabled: bool = False
    funding_rate: float = 0.0

    # Same-bar behavior
    same_bar_sl_tp: str = "close_only"  # or "intra_bar"
    stop_first_policy: bool = True  # stops checked before targets

    # Position sizing
    quantity_sizing: str = "fixed_risk_pct"
    risk_per_trade_pct: float = 0.0025  # 0.25% of equity
    min_order_notional_usdt: float = 20.0
    max_order_notional_usdt: float = 500.0

    # Exposure limits
    max_exposure_pct: float = 0.25  # 25% of equity
    max_positions: int = 1
    max_positions_per_symbol: int = 1

    # Cooldown
    cooldown_bars: int = 0
    max_trades_per_day: int = 20
    max_consecutive_losses: int = 3
    consecutive_loss_cooldown_bars: int = 12  # 1h at 5m

    # Timezone
    timezone: str = "UTC"

    # Universe
    symbols: list[str] = field(default_factory=list)
    timeframe: str = "5m"

    @property
    def hash(self) -> str:
        """Compute deterministic hash of all assumptions."""
        data = json.dumps(asdict(self), sort_keys=True, default=str)
        return str(sha256_hex(data))

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON output."""
        d = asdict(self)
        d["hash"] = self.hash
        return d

    def to_evidence(self) -> EvidenceRecord:
        """Create evidence record."""
        return EvidenceRecord(
            evidence_class=EvidenceClass.SYNTHETIC,
            source="ExecutionAssumptions:config",
            metadata={"hash": self.hash},
        )


def write_execution_assumptions(
    assumptions: ExecutionAssumptions,
    output_path: Path,
) -> Path:
    """Write execution assumptions to JSON file.

    V0.2.1 §15: research/EXECUTION_ASSUMPTIONS.json
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(assumptions.to_dict(), indent=2, default=str),
        encoding="utf-8",
    )
    return output_path


def load_execution_assumptions(path: Path) -> ExecutionAssumptions:
    """Load execution assumptions from JSON file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    data.pop("hash", None)  # Remove computed field
    return ExecutionAssumptions(**data)


__all__ = [
    "ExecutionAssumptions",
    "load_execution_assumptions",
    "write_execution_assumptions",
]
