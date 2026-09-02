"""Strategy Experiment Sandbox for V0.2.1 §24.

V0.2.1 §24: Create real separation between:
- LIVE_STRATEGIES
- PAPER_STRATEGIES
- RESEARCH_STRATEGIES

V0.2.1 can ONLY write to RESEARCH_STRATEGIES.
Permission test must deny writes to live/paper.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import structlog

StrategyZone = Literal["LIVE", "PAPER", "RESEARCH"]


@dataclass(frozen=True, slots=True)
class ZonePermission:
    """Permission result for a strategy zone write."""

    zone: StrategyZone
    allowed: bool
    reason: str = ""


class StrategySandbox:
    """Enforces zone separation for strategy code.

    V0.2.1 §24:
    - LIVE_STRATEGIES: strategies/live/
    - PAPER_STRATEGIES: strategies/paper/
    - RESEARCH_STRATEGIES: strategies/research/ or research/generated/

    V0.2.1 only writes to RESEARCH_STRATEGIES.
    """

    ZONE_PATHS: dict[StrategyZone, Path] = {
        "LIVE": Path("strategies/live"),
        "PAPER": Path("strategies/paper"),
        "RESEARCH": Path("strategies/research"),
    }

    def __init__(self, allowed_zones: list[StrategyZone] | None = None) -> None:
        self._allowed_zones = allowed_zones or ["RESEARCH"]
        self._log = structlog.get_logger("strategy_sandbox")

    def check_write_permission(self, zone: StrategyZone) -> ZonePermission:
        """Check if writing to a zone is permitted."""
        allowed = zone in self._allowed_zones
        if not allowed:
            self._log.warning(
                "sandbox.write_denied",
                zone=zone,
                allowed=self._allowed_zones,
            )
        return ZonePermission(
            zone=zone,
            allowed=allowed,
            reason="" if allowed else f"Zone {zone} not in allowed zones: {self._allowed_zones}",
        )

    def get_zone_path(self, zone: StrategyZone) -> Path:
        """Get the filesystem path for a zone."""
        return self.ZONE_PATHS[zone]

    def ensure_research_dir(self) -> Path:
        """Ensure research directory exists."""
        path = self.ZONE_PATHS["RESEARCH"]
        path.mkdir(parents=True, exist_ok=True)
        return path

    def validate_no_live_write(self, file_path: Path) -> bool:
        """Validate that a file path is not in live/paper zones."""
        path_str = str(file_path).replace("\\", "/")
        for zone in ["LIVE", "PAPER"]:
            zone_str = str(self.ZONE_PATHS[zone]).replace("\\", "/")
            if zone_str in path_str:
                self._log.error(
                    "sandbox.live_write_attempt",
                    path=str(file_path),
                    zone=zone,
                )
                return False
        return True


__all__ = [
    "StrategySandbox",
    "StrategyZone",
    "ZonePermission",
]
