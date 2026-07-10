"""Domain types for the TSK-860 trade intelligence journal."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

TradeDirection = Literal["LONG", "SHORT"]
TradeCaseStatus = Literal[
    "pending_order",
    "order_rejected",
    "open",
    "closed",
]
ZoneKind = Literal[
    "support",
    "resistance",
    "order_block",
    "accumulation",
    "distribution",
    "range_high",
    "range_low",
]
SnapshotProvider = Literal["tradingview", "local_renderer"]
SnapshotStatus = Literal["ok", "fallback", "failed", "deferred"]
WinLoss = Literal["win", "loss", "breakeven"]


@dataclass(frozen=True, slots=True)
class TechnicalZone:
    zone_id: str
    symbol: str
    timeframe: str
    kind: ZoneKind
    low: float
    high: float
    strength: float
    detected_at: int
    source: str
    evidence: dict[str, float | str | bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.low > self.high:
            raise ValueError("technical zone low must be <= high")
        if not 0.0 <= self.strength <= 1.0:
            raise ValueError("technical zone strength must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class EntryThesis:
    trade_case_id: str
    signal_id: str
    symbol: str
    direction: TradeDirection
    entry_price: float
    tp_price: float
    sl_price: float
    timeframe: str
    entry_reason: str
    criteria_met: tuple[str, ...]
    criteria_failed: tuple[str, ...]
    indicators: dict[str, float | str | bool]
    zones: tuple[TechnicalZone, ...]
    confidence_score: float
    created_at: int

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence_score <= 1.0:
            raise ValueError("entry thesis confidence_score must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class ChartSnapshot:
    snapshot_id: str
    trade_case_id: str
    provider: SnapshotProvider
    path: str
    status: SnapshotStatus
    captured_at: int | None
    overlays: dict[str, object]


@dataclass(frozen=True, slots=True)
class TradeOutcome:
    trade_case_id: str
    position_id: str
    exit_reason: str
    pnl_net: float
    r_multiple: float
    mfe: float
    mae: float
    win_loss: WinLoss
    closed_at: int
    post_trade_diagnosis: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TradeCase:
    trade_case_id: str
    signal_id: str
    symbol: str
    direction: TradeDirection
    status: TradeCaseStatus
    created_at: int
    order_id: str | None = None
    position_id: str | None = None
    entry_thesis: EntryThesis | None = None
    chart_snapshot: ChartSnapshot | None = None
    outcome: TradeOutcome | None = None


__all__ = [
    "ChartSnapshot",
    "EntryThesis",
    "SnapshotProvider",
    "SnapshotStatus",
    "TechnicalZone",
    "TradeCase",
    "TradeCaseStatus",
    "TradeDirection",
    "TradeOutcome",
    "WinLoss",
    "ZoneKind",
]
