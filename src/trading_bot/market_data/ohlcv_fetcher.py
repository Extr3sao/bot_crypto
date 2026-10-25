from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Optional, Sequence

try:  # pragma: no cover - runtime-only path
    import structlog
except Exception:  # pragma: no cover - local runbook path
    structlog = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

__all__ = ["OHLCVFetcher"]


@dataclass
class Bar:
    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float


class OHLCVFetcher:
    def fetch(self, symbols: Sequence[str], timeframe: str, since: int, until: int) -> Dict[str, Sequence[Bar]]:
        return {}
