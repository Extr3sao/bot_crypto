"""Common types for quantitative research (FASE 2).

All types are frozen dataclasses with slots=True for:
- Immutability (no accidental mutation)
- Memory efficiency
- Safe propagation through pipelines

Design principles:
- P5: AlphaSignal carries family, direction, structural_stop, features
- P6: Structural risk separated (natural_stop, effective_stop, floor_bound)
- P7: Features != Rules (FeaturesBag is diagnostic data)
- P8: ExperimentRecord for reproducibility
- P11: DatasetWindow for consumed-periods tracking
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# ---------------------------------------------------------------------------
# Direction (P5: LONG and SHORT are NOT necessarily symmetric)
# ---------------------------------------------------------------------------

Direction = Literal["LONG", "SHORT"]


# ---------------------------------------------------------------------------
# FeaturesBag (P7: diagnostic features, not rules)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FeaturesBag:
    """Diagnostic features attached to an AlphaSignal.

    P7 contract:
    - Features are DESCRIPTIVE, not prescriptive.
    - A post-hoc descriptive difference is NOT an operational rule.
    - Features are stored for analysis, not used directly for entry/exit.
    """

    rsi: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    macd_histogram: float | None = None
    volume_ratio: float | None = None  # vs MA
    atr: float | None = None
    atr_pct: float | None = None
    ema_alignment: float | None = None  # fast - slow normalized
    ema_slope: float | None = None
    close_location: float | None = None  # (close - low) / (high - low)
    body_wick_ratio: float | None = None  # body / total range
    distance_to_ema: float | None = None  # distance to key EMA
    pullback_depth: float | None = None  # pullback % of recent move
    structural_stop_width: float | None = None  # entry - stop as %
    market_breadth: float | None = None  # advance/decline
    trend_regime: str | None = None  # BULL/BEAR/MIXED/etc
    custom: dict[str, float | str | bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for storage/analysis."""
        import dataclasses

        result: dict[str, Any] = {}
        for f in dataclasses.fields(self):
            v = getattr(self, f.name)
            if f.name == "custom":
                result.update(v)
            elif v is not None:
                result[f.name] = v
        return result


# ---------------------------------------------------------------------------
# AlphaSignal (P5: output of every AlphaFamily)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AlphaSignal:
    """Canonical signal emitted by an AlphaFamily.

    P5 contract:
    - Every alpha family produces AlphaSignals.
    - LONG and SHORT are NOT symmetric by definition.
    - Structural stop is explicit (P6).
    - Features are diagnostic, not rules (P7).
    """

    family: str  # alpha family name
    symbol: str
    timestamp: int  # epoch ms
    direction: Direction
    entry_reference: float  # reference entry price
    structural_stop: float  # natural structural stop price
    timeframe: str
    features: FeaturesBag = field(default_factory=FeaturesBag)
    metadata: dict[str, Any] = field(default_factory=dict)

    # P6: Structural risk fields
    effective_stop: float | None = None  # after floor/clamp
    minimum_stop_floor: float | None = None  # floor applied
    floor_bound: bool = False  # True if floor was applied

    def __post_init__(self) -> None:
        if self.direction not in ("LONG", "SHORT"):
            raise ValueError(f"direction must be LONG or SHORT, got {self.direction}")
        if self.entry_reference <= 0:
            raise ValueError(f"entry_reference must be > 0, got {self.entry_reference}")
        if self.structural_stop <= 0:
            raise ValueError(f"structural_stop must be > 0, got {self.structural_stop}")

    @property
    def risk_price(self) -> float:
        """Absolute risk per unit (entry - stop for LONG, stop - entry for SHORT)."""
        if self.direction == "LONG":
            return abs(self.entry_reference - self.structural_stop)
        return abs(self.structural_stop - self.entry_reference)

    @property
    def effective_stop_price(self) -> float:
        """The stop price that would actually be used (floor or natural)."""
        if self.effective_stop is not None:
            return self.effective_stop
        return self.structural_stop


# ---------------------------------------------------------------------------
# BlockedEvent (P4: pipeline classification)
# ---------------------------------------------------------------------------

BlockedReason = Literal[
    "MAX_OPEN",
    "MAX_DIRECTION",
    "DAILY_LOSS_LIMIT",
    "COOLDOWN",
    "POSITION_ALREADY_OPEN",
    "LOWER_PRIORITY",
    "RISK_INVALID",
    "KILL_SWITCH",
    "DAILY_TRADE_LIMIT",
    "CONSECUTIVE_LOSS_COOLDOWN",
    "MAX_DRAWDOWN",
    "SPREAD_EXCESSIVE",
    "VOLATILITY_EXTREME",
    "WEEKEND_BLOCKED",
    "STALE_DATA",
    "LOW_CONFIDENCE",
]


@dataclass(frozen=True, slots=True)
class BlockedEvent:
    """Record of a signal that was blocked by the admission controller.

    P4 contract: every BLOCKED signal must save its reason.
    """

    signal_family: str
    symbol: str
    timestamp: int
    direction: Direction
    reason: BlockedReason
    details: str = ""


# ---------------------------------------------------------------------------
# PerformanceMetrics (P2: costs first, gross vs net)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PerformanceMetrics:
    """Complete performance metrics with gross/net distinction.

    P2 contract:
    - Every evaluation includes gross_pnl, commission, slippage, net_pnl.
    - economic_margin_r = gross_exp_r - execution_cost_r.
    - cost_to_edge_ratio = execution_cost_r / abs(gross_exp_r).
    """

    # Trade counts
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0

    # Gross metrics
    gross_pnl: float = 0.0
    gross_win_sum: float = 0.0
    gross_loss_sum: float = 0.0

    # Cost components
    total_commission: float = 0.0
    total_slippage: float = 0.0
    total_funding: float = 0.0

    # Net metrics
    net_pnl: float = 0.0
    net_win_sum: float = 0.0
    net_loss_sum: float = 0.0

    # Risk metrics
    risk_per_trade: float = 0.0  # total risk deployed
    max_drawdown: float = 0.0

    # R-multiples
    gross_exp_r: float = 0.0  # gross_pnl / risk_per_trade
    fee_exp_r: float = 0.0  # (commission + slippage + funding) / risk_per_trade
    net_exp_r: float = 0.0  # net_pnl / risk_per_trade

    # Profit factors
    gross_pf: float = 0.0  # gross_win_sum / abs(gross_loss_sum)
    net_pf: float = 0.0  # net_win_sum / abs(net_loss_sum)

    # Economic quality
    economic_margin_r: float = 0.0  # gross_exp_r - fee_exp_r
    cost_to_edge_ratio: float = 0.0  # fee_exp_r / abs(gross_exp_r) when valid

    # Turnover
    trades_per_day: float = 0.0
    turnover: float = 0.0  # total notional traded
    fees_per_trade: float = 0.0
    fees_per_day: float = 0.0
    pnl_per_trade: float = 0.0
    pnl_per_unit_turnover: float = 0.0

    # Daily coverage
    coverage_days_pct: float = 0.0  # % of days with >= 1 trade
    zero_trade_days: int = 0
    worst_day_trades: int = 0

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.winning_trades / self.total_trades

    @property
    def execution_cost(self) -> float:
        return self.total_commission + self.total_slippage + self.total_funding

    def compute_derived(self) -> PerformanceMetrics:
        """Compute derived metrics from raw components.

        Returns a NEW instance with derived fields populated.
        """
        # R-multiples
        gross_exp_r = self.gross_pnl / self.risk_per_trade if self.risk_per_trade > 0 else 0.0
        fee_exp_r = self.execution_cost / self.risk_per_trade if self.risk_per_trade > 0 else 0.0
        net_exp_r = self.net_pnl / self.risk_per_trade if self.risk_per_trade > 0 else 0.0

        # Profit factors
        gross_pf = (
            self.gross_win_sum / abs(self.gross_loss_sum)
            if self.gross_loss_sum != 0
            else (float("inf") if self.gross_win_sum > 0 else 0.0)
        )
        net_pf = (
            self.net_win_sum / abs(self.net_loss_sum)
            if self.net_loss_sum != 0
            else (float("inf") if self.net_win_sum > 0 else 0.0)
        )

        # Economic quality
        economic_margin_r = gross_exp_r - fee_exp_r
        cost_to_edge = (
            fee_exp_r / abs(gross_exp_r)
            if gross_exp_r != 0
            else float("inf")
            if fee_exp_r > 0
            else 0.0
        )

        # Turnover
        trades_per_day = self.trades_per_day
        fees_per_trade = self.execution_cost / self.total_trades if self.total_trades > 0 else 0.0
        fees_per_day = self.fees_per_day
        pnl_per_trade = self.net_pnl / self.total_trades if self.total_trades > 0 else 0.0
        pnl_per_unit = self.net_pnl / self.turnover if self.turnover > 0 else 0.0

        return PerformanceMetrics(
            total_trades=self.total_trades,
            winning_trades=self.winning_trades,
            losing_trades=self.losing_trades,
            gross_pnl=self.gross_pnl,
            gross_win_sum=self.gross_win_sum,
            gross_loss_sum=self.gross_loss_sum,
            total_commission=self.total_commission,
            total_slippage=self.total_slippage,
            total_funding=self.total_funding,
            net_pnl=self.net_pnl,
            net_win_sum=self.net_win_sum,
            net_loss_sum=self.net_loss_sum,
            risk_per_trade=self.risk_per_trade,
            max_drawdown=self.max_drawdown,
            gross_exp_r=gross_exp_r,
            fee_exp_r=fee_exp_r,
            net_exp_r=net_exp_r,
            gross_pf=gross_pf,
            net_pf=net_pf,
            economic_margin_r=economic_margin_r,
            cost_to_edge_ratio=cost_to_edge,
            trades_per_day=trades_per_day,
            turnover=self.turnover,
            fees_per_trade=fees_per_trade,
            fees_per_day=fees_per_day,
            pnl_per_trade=pnl_per_trade,
            pnl_per_unit_turnover=pnl_per_unit,
            coverage_days_pct=self.coverage_days_pct,
            zero_trade_days=self.zero_trade_days,
            worst_day_trades=self.worst_day_trades,
        )


# ---------------------------------------------------------------------------
# ExperimentRecord (P8: experiment registry)
# ---------------------------------------------------------------------------

ExperimentStatus = Literal[
    "PREREGISTERED",
    "RUNNING",
    "REJECTED",
    "CANDIDATE",
    "CONFIRMING",
    "CONFIRMED",
    "INVALIDATED",
]


@dataclass(frozen=True, slots=True)
class ExperimentRecord:
    """A registered experiment (P8).

    P8 contract:
    - Each experiment has a unique ID.
    - Code, config, and data are hashed for reproducibility.
    - Status lifecycle is explicit.
    - A consumed period cannot be re-labeled as FRESH.
    """

    experiment_id: str
    strategy_version: str
    hypothesis: str
    rules: dict[str, Any]
    parameters: dict[str, Any]
    dataset_start: int  # epoch ms
    dataset_end: int  # epoch ms
    created_at: int  # epoch ms
    code_hash: str  # SHA256 of strategy code
    config_hash: str  # SHA256 of config
    data_hash: str  # hash or identifier of dataset
    status: ExperimentStatus = "PREREGISTERED"
    executed_at: int | None = None
    results: PerformanceMetrics | None = None
    decision: str = ""  # human/LLM decision note
    parent_experiment: str | None = None  # for discovery -> confirmation chain

    def __post_init__(self) -> None:
        if not self.experiment_id:
            raise ValueError("experiment_id cannot be empty")
        if not self.code_hash:
            raise ValueError("code_hash cannot be empty (P9: preregistration)")


# ---------------------------------------------------------------------------
# DatasetWindow (P11: disjoint windows, consumed-data ledger)
# ---------------------------------------------------------------------------

WindowStatus = Literal["FRESH", "CONSUMED", "RESERVED"]


@dataclass(frozen=True, slots=True)
class DatasetWindow:
    """A discrete data window for discovery/confirmation (P11).

    P11 contract:
    - Never reuse data.
    - Discovery and confirmation must use disjoint windows.
    - Once consumed, a window cannot be re-labeled FRESH.
    """

    window_id: str
    symbol: str
    timeframe: str
    start_ts: int  # epoch ms
    end_ts: int  # epoch ms
    candle_count: int
    status: WindowStatus = "FRESH"
    consumed_by_experiment: str | None = None  # experiment_id
    consumed_at: int | None = None  # epoch ms

    @property
    def duration_hours(self) -> float:
        return (self.end_ts - self.start_ts) / (1000 * 3600)

    def overlaps(self, other: DatasetWindow) -> bool:
        """Check if two windows overlap in time."""
        if self.symbol != other.symbol:
            return False
        return self.start_ts < other.end_ts and other.start_ts < self.end_ts


# ---------------------------------------------------------------------------
# CampaignRecord (P24: autonomous campaign controller)
# ---------------------------------------------------------------------------

CampaignStatus = Literal[
    "WAITING_FOR_DATA",
    "DISCOVERY_READY",
    "RUNNING_DISCOVERY",
    "CANDIDATE_FOUND",
    "WAITING_CONFIRMATION",
    "RUNNING_CONFIRMATION",
    "CONFIRMED",
    "CAMPAIGN_REJECTED",
    "QUEUE_EXHAUSTED",
    "STOP_NO_EDGE",
]


@dataclass(frozen=True, slots=True)
class CampaignRecord:
    """A research campaign tracking discovery/confirmation cycle (P24)."""

    campaign_id: str
    family: str  # alpha family being tested
    created_at: int  # epoch ms
    status: CampaignStatus = "WAITING_FOR_DATA"
    discovery_experiment_id: str | None = None
    confirmation_experiment_id: str | None = None
    discovery_window_id: str | None = None
    confirmation_window_id: str | None = None
    hypothesis: str = ""
    candidate_metrics: PerformanceMetrics | None = None
    confirmed_metrics: PerformanceMetrics | None = None
    completed_at: int | None = None


__all__ = [
    "AlphaSignal",
    "BlockedEvent",
    "BlockedReason",
    "CampaignRecord",
    "CampaignStatus",
    "DatasetWindow",
    "Direction",
    "ExperimentRecord",
    "ExperimentStatus",
    "FeaturesBag",
    "PerformanceMetrics",
    "WindowStatus",
]
