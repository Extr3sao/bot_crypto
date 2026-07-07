"""Types for paper-trading session orchestration (TSK-105)."""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from trading_bot.scanner import CounterSnapshot, MarketSnapshot


@dataclass(frozen=True, slots=True)
class PaperFill:
    fill_id: str
    symbol: str
    side: Literal["buy", "sell"]
    qty: float
    fill_price: float
    reference_price: float
    commission: float
    slippage_bps: float
    notional_usdt: float
    timestamp: int
    reason: str


@dataclass(frozen=True, slots=True)
class PaperPosition:
    symbol: str
    qty: float
    entry_price: float
    entry_commission: float
    opened_at_ms: int
    last_price: float
    marked_at_ms: int
    notional_usdt: float
    unrealized_pnl: float
    sessions_held: int


@dataclass(frozen=True, slots=True)
class PaperClosedTrade:
    trade_id: str
    symbol: str
    qty: float
    entry_price: float
    exit_price: float
    opened_at_ms: int
    closed_at_ms: int
    realized_pnl: float
    realized_pnl_pct: float
    total_commission: float
    sessions_held: int
    entry_fill_id: str
    exit_fill_id: str


@dataclass(frozen=True, slots=True)
class PaperExecutionSummary:
    fills: list[PaperFill] = field(default_factory=list)
    open_positions: list[PaperPosition] = field(default_factory=list)
    closed_trades: list[PaperClosedTrade] = field(default_factory=list)
    fills_opened: int = 0
    fills_closed: int = 0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    ending_cash: float = 0.0
    ending_equity: float = 0.0
    win_rate_closed: float = 0.0


@dataclass(frozen=True, slots=True)
class PaperSessionMetrics:
    total_snapshots: int
    active_snapshots: int
    inactive_snapshots: int
    scanner_errors: int
    active_ratio: float
    inactive_ratio: float
    avg_active_rank_score: float
    median_spread_bps_active: float
    fills_opened: int = 0
    fills_closed: int = 0
    closed_trades: int = 0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    ending_cash: float = 0.0
    ending_equity: float = 0.0
    win_rate_closed: float = 0.0


@dataclass(frozen=True, slots=True)
class PaperSessionResult:
    session_id: str
    started_at: datetime.datetime
    ended_at: datetime.datetime
    duration_ms: int
    snapshots: list[MarketSnapshot]
    counters: CounterSnapshot
    metrics: PaperSessionMetrics
    execution_summary: PaperExecutionSummary | None = None
    report_markdown_path: Path | None = None
    report_json_path: Path | None = None


@dataclass(frozen=True, slots=True)
class PaperBacktestExpectation:
    expected_active_snapshots: int
    expected_median_spread_bps: float
    expected_realized_pnl: float | None = None
    min_active_ratio: float = 0.30
    min_win_rate_closed: float = 0.30
    max_scanner_errors: int = 3


@dataclass(frozen=True, slots=True)
class PaperSessionAlert:
    code: str
    message: str


__all__ = [
    "PaperBacktestExpectation",
    "PaperClosedTrade",
    "PaperExecutionSummary",
    "PaperFill",
    "PaperPosition",
    "PaperSessionAlert",
    "PaperSessionMetrics",
    "PaperSessionResult",
]
