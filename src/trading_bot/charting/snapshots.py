"""Shared chart snapshot contracts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from trading_bot.market_data.types import OHLCV
from trading_bot.trade_journal.types import TechnicalZone


@dataclass(frozen=True, slots=True)
class ChartSnapshotRequest:
    trade_case_id: str
    symbol: str
    direction: str
    entry_price: float
    tp_price: float
    sl_price: float
    candles: tuple[OHLCV, ...]
    zones: tuple[TechnicalZone, ...]
    output_dir: Path
    captured_at: int


__all__ = ["ChartSnapshotRequest"]

