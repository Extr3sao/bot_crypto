"""Risk Manager — position sizing, kill switch, daily limits.

Fase 5: the single authority for trade sizing and risk checks.
No sizing is calculated outside this module.

Reglas duras:
- Ningún sizing se calcula fuera de este módulo.
- KillSwitch solo se desactiva manualmente.
- Toda decisión se registra en logs/risk-decisions.log.
- Tests con hypothesis para invariantes.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Literal

import structlog

from trading_bot.config.risk import Risk

if TYPE_CHECKING:
    from trading_bot.strategies.types import Signal

#: Where the protective distance came from. ``POLICY_DEFAULT`` means the strategy
#: declared none and the policy supplied one — a fact the ledger must publish, not a
#: silent substitution. There is deliberately no ``WIDENED`` member: no code path is
#: allowed to move the distance the strategy asked for.
StopSource = Literal["SIGNAL", "POLICY_DEFAULT"]

#: What the ``REJECT`` policy does with a stop shorter than the round-trip cost.
StopCostPolicy = Literal["OFF", "REPORT", "REJECT"]

#: Which clamp produced the notional. It is published because the money at risk is
#: ``notional × stop``, not the risk budget, and a reader must not confuse the two.
SizingBasis = Literal[
    "RISK_BUDGET",
    "MAX_ORDER_NOTIONAL_CLAMP",
    "EXPOSURE_CLAMP",
    "ASSET_EXPOSURE_CLAMP",
]


#: One week in milliseconds. The window is the UTC Monday-to-Monday week the
#: reports already use: it has no DST and no local-calendar ambiguity.
WEEK_MS = 7 * 24 * 3_600_000

#: 1969-12-29T00:00:00Z — the Monday before the epoch (1970-01-01 was a Thursday),
#: so ``(now - anchor) // WEEK_MS`` counts whole Monday-start weeks.
_MONDAY_ANCHOR_MS = -3 * 24 * 3_600_000


def week_start_ms_for(now_ms: int) -> int:
    """Epoch-ms of the UTC Monday 00:00 that opens the week containing ``now_ms``."""
    return _MONDAY_ANCHOR_MS + ((int(now_ms) - _MONDAY_ANCHOR_MS) // WEEK_MS) * WEEK_MS


def _attrs(obj: Any, names: tuple[str, ...]) -> dict[str, Any]:
    """Read named attributes off a position object (DEF-VERIFY-011 helper)."""
    out: dict[str, Any] = {}
    for name in names:
        try:
            out[name] = getattr(obj, name)
        except AttributeError:
            continue
    return out


@dataclass(frozen=True, slots=True)
class StopResolution:
    """The stop the book will actually hold, and how it got there (DEF-RUN-014).

    Four things that used to be one:

    * ``requested_stop_pct`` — the distance the *strategy* declared, i.e. its thesis'
      invalidation. ``None`` when the strategy declared none.
    * ``effective_stop_pct`` — the distance the book will hold. Equal to the requested
      one whenever there was one.
    * ``source``/``reason`` — who supplied it and why, so an override can never be made
      silently.
    * ``stop_distance_bps`` / ``round_trip_cost_bps`` / ``stop_clears_costs`` — whether
      the distance can pay for the round trip it has to survive, and therefore whether
      it is a loss limit at all.

    ``risk_at_stop_usdt`` is the money actually at risk after sizing: the risk budget is
    a *cap*, and the notional clamp (``max_order_notional_usdt``) is what usually binds.
    """

    requested_stop_pct: float | None
    effective_stop_pct: float
    source: StopSource
    reason: str
    requested_take_profit_pct: float | None
    effective_take_profit_pct: float
    take_profit_source: StopSource
    stop_distance_bps: float
    round_trip_cost_bps: float | None = None
    stop_clears_costs: bool | None = None
    #: ``None`` because the runtime has no instrument metadata; the ledger declares
    #: ``tick_size_check="NOT_AVAILABLE"`` rather than pretending it validated one.
    tick_size: float | None = None
    risk_at_stop_usdt: float = 0.0
    risk_budget_usdt: float = 0.0
    sizing_basis: SizingBasis = "RISK_BUDGET"
    notional_usdt: float = 0.0

    def to_row(self) -> dict[str, Any]:
        return {
            "requested_stop_loss_pct": self.requested_stop_pct,
            "effective_stop_loss_pct": self.effective_stop_pct,
            "stop_source": self.source,
            "stop_reason": self.reason,
            "requested_take_profit_pct": self.requested_take_profit_pct,
            "effective_take_profit_pct": self.effective_take_profit_pct,
            "take_profit_source": self.take_profit_source,
            "stop_distance_bps": round(self.stop_distance_bps, 6),
            "round_trip_cost_bps": (
                None if self.round_trip_cost_bps is None else round(self.round_trip_cost_bps, 6)
            ),
            "stop_clears_costs": self.stop_clears_costs,
            "tick_size": self.tick_size,
            "tick_size_check": "NOT_AVAILABLE" if self.tick_size is None else "CHECKED",
            "risk_at_stop_usdt": round(self.risk_at_stop_usdt, 8),
            "risk_budget_usdt": round(self.risk_budget_usdt, 8),
            "sizing_basis": self.sizing_basis,
            "notional_usdt": round(self.notional_usdt, 8),
        }


@dataclass(frozen=True, slots=True)
class PositionSize:
    """Computed position size for a signal."""

    symbol: str
    side: str
    notional_usdt: float
    quantity: float
    stop_loss_pct: float
    take_profit_pct: float
    risk_amount_usdt: float
    #: DEF-RUN-014: the rest of the stop contract. Defaulted so a caller that builds a
    #: ``PositionSize`` by hand keeps working, but every value is published by the
    #: manager and written to the ledger.
    requested_stop_loss_pct: float | None = None
    stop_source: StopSource = "POLICY_DEFAULT"
    stop_reason: str = ""
    risk_at_stop_usdt: float = 0.0
    sizing_basis: SizingBasis = "RISK_BUDGET"
    #: The whole contract, so a caller never has to re-derive where the stop came from.
    stop_resolution: StopResolution | None = None


@dataclass(frozen=True, slots=True)
class RiskCheck:
    """Result of evaluating a signal against risk policy."""

    approved: bool
    reason: str | None = None
    position_size: PositionSize | None = None
    blocked_by: str | None = None
    #: Present on a rejection caused by the stop itself (invalid, or inside its costs),
    #: and on every approval, so the caller never has to infer where the stop came from.
    stop_resolution: StopResolution | None = None


@dataclass
class RiskManager:
    """Stateful risk manager that tracks daily P&L, positions, and limits.

    One instance per trading session. Thread-safe not required (single-threaded
    trading loop).
    """

    risk: Risk
    equity: float
    open_positions: dict[str, Any] = field(default_factory=dict)
    daily_pnl: float = 0.0
    weekly_pnl: float = 0.0
    trades_today: int = 0
    consecutive_losses: int = 0
    peak_equity: float = 0.0
    #: Peak equity since the last ``reset_daily`` — the reference for the
    #: DAILY drawdown rule (``max_daily_drawdown_pct``). Distinct from the
    #: all-time ``peak_equity`` used by ``max_total_drawdown_pct``.
    day_peak_equity: float = 0.0
    #: Epoch-ms of the most recent losing trade, the anchor for the
    #: time-based consecutive-loss cooldown. 0 means "no loss recorded yet".
    _last_loss_ms: int = field(default=0)
    _kill_switch_active: bool = field(default=False)
    _log: Any = field(default=None, repr=False)
    #: Injectable clock (epoch seconds) so the runtime stays deterministic and
    #: the cooldown rule is testable without sleeping. Defaults to time.time.
    _clock: Callable[[], float] | None = field(default=None, repr=False)
    #: Epoch-ms of the UTC Monday 00:00 that anchors ``weekly_pnl``.
    weekly_start_ms: int = field(default=0)
    #: DEF-RUN-014: what one round trip in a symbol costs, in basis points, at a given
    #: notional. Injected rather than imported so this module keeps knowing nothing about
    #: venues. ``None`` means "not measured here".
    cost_bps_for: Callable[[str, float], float] | None = field(default=None, repr=False)
    #: ``OFF`` keeps the historical behaviour for every existing caller; ``REPORT``
    #: publishes ``stop_clears_costs`` and still trades; ``REJECT`` refuses a stop that
    #: is shorter than the round trip it has to pay for.
    stop_cost_policy: StopCostPolicy = "OFF"
    #: Why ``resolve_stop`` refused the distance, so ``check_signal`` can report it
    #: instead of a generic sizing failure.
    _last_stop_error: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        if self._log is None:
            self._log = structlog.get_logger("risk_manager")
        if self._clock is None:
            self._clock = time.time
        if self.weekly_start_ms <= 0:
            self.weekly_start_ms = week_start_ms_for(self._now_ms())
        self.peak_equity = max(self.peak_equity, self.equity)
        self.day_peak_equity = max(self.day_peak_equity, self.equity)

    # -- internal helpers --------------------------------------------------

    def _now_ms(self) -> int:
        """Epoch milliseconds from the (injectable) clock."""
        clock = self._clock or time.time
        return int(clock() * 1000)

    @staticmethod
    def _asset_of(symbol: str) -> str:
        """Base asset of a symbol: ``BTC/USDT`` -> ``BTC``; else the symbol."""
        if not symbol:
            return ""
        head = symbol.replace("-", "/").split("/", 1)[0]
        return head.strip().upper()

    def _position_notional(self, position: Any) -> float:
        if isinstance(position, dict):
            return float(position.get("notional_usdt", 0.0) or 0.0)
        return float(getattr(position, "notional_usdt", 0.0) or 0.0)

    def _position_asset(self, symbol: str, position: Any) -> str:
        if isinstance(position, dict):
            asset = position.get("asset")
            if asset:
                return str(asset).upper()
        else:
            asset = getattr(position, "asset", None)
            if asset:
                return str(asset).upper()
        return self._asset_of(symbol)

    def exposure_by_asset(self) -> dict[str, float]:
        """Current open notional per asset, in USDT (read-only)."""
        out: dict[str, float] = {}
        for symbol, position in self.open_positions.items():
            asset = self._position_asset(symbol, position)
            out[asset] = out.get(asset, 0.0) + self._position_notional(position)
        return out

    @property
    def kill_switch_active(self) -> bool:
        return self._kill_switch_active

    def activate_kill_switch(self, reason: str = "manual") -> None:
        """Activate kill switch. Cannot be undone programmatically."""
        self._kill_switch_active = True
        self._log.warning("risk.kill_switch_activated", reason=reason)

    def roll_week(self) -> bool:
        """Move the weekly window forward when the causal clock crosses Monday 00:00.

        The clock is the injectable one, so in the replay the window advances with
        the bars and not with the machine's wall clock. A clock that moves
        backwards never resets anything: the accumulator only ever belongs to the
        newest week the process has observed.

        Returns ``True`` only when a previously anchored window was replaced and
        its loss was therefore cleared.
        """
        start = week_start_ms_for(self._now_ms())
        if self.weekly_start_ms <= 0:
            self.weekly_start_ms = start
            return False
        if start <= self.weekly_start_ms:
            return False
        self.weekly_start_ms = start
        self.weekly_pnl = 0.0
        return True

    def check_signal(self, signal: Signal) -> RiskCheck:
        """Evaluate a signal against all risk constraints.

        Returns RiskCheck with approved=True + PositionSize if OK,
        or approved=False with reason if blocked.
        """
        # The weekly veto must lift at the boundary even before the first trade of
        # the new week, so the roll is evaluated on every decision.
        self.roll_week()

        # Kill switch
        if self._kill_switch_active or not self.risk.kill_switch_enabled:
            return RiskCheck(
                approved=False,
                reason="Kill switch active" if self._kill_switch_active else "Kill switch disabled",
                blocked_by="kill_switch",
            )

        # Daily trade limit
        if self.trades_today >= self.risk.max_trades_per_day:
            return RiskCheck(
                approved=False,
                reason=f"Daily trade limit reached ({self.risk.max_trades_per_day})",
                blocked_by="daily_trade_limit",
            )

        # Open positions limit
        if len(self.open_positions) >= self.risk.max_open_positions:
            return RiskCheck(
                approved=False,
                reason=f"Max open positions reached ({self.risk.max_open_positions})",
                blocked_by="max_positions",
            )

        # Consecutive losses cooldown (time-based).
        #
        # DEF-RISK-INERT-002: ``consecutive_loss_cooldown_minutes`` used to be
        # declared and validated but never read — the gate was a permanent block
        # that could never lift. It is now a real cooldown window measured from
        # the last losing trade: it blocks only while the window is open, and
        # ``0`` keeps the legacy permanent-block behaviour for callers that opt
        # into it.
        if self.consecutive_losses >= self.risk.max_consecutive_losses:
            cooldown_ms = int(self.risk.consecutive_loss_cooldown_minutes) * 60_000
            if cooldown_ms <= 0:
                return RiskCheck(
                    approved=False,
                    reason=f"Consecutive loss cooldown ({self.consecutive_losses} losses)",
                    blocked_by="consecutive_loss_cooldown",
                )
            elapsed_ms = self._now_ms() - self._last_loss_ms if self._last_loss_ms else cooldown_ms
            if elapsed_ms < cooldown_ms:
                remaining_min = (cooldown_ms - elapsed_ms) / 60_000.0
                return RiskCheck(
                    approved=False,
                    reason=(
                        f"Consecutive loss cooldown ({self.consecutive_losses} losses, "
                        f"{remaining_min:.1f} min remaining)"
                    ),
                    blocked_by="consecutive_loss_cooldown",
                )

        # Daily loss limit
        if self.daily_pnl < 0 and abs(self.daily_pnl) >= self.equity * (
            self.risk.max_daily_loss_pct / 100.0
        ):
            return RiskCheck(
                approved=False,
                reason=f"Daily loss limit reached ({self.risk.max_daily_loss_pct}%)",
                blocked_by="daily_loss_limit",
            )

        # Weekly loss limit (DEF-RISK-INERT-002: ``max_weekly_loss_pct`` was
        # declared but never enforced — weekly P&L was accumulated and never
        # compared against anything).
        if self.weekly_pnl < 0 and abs(self.weekly_pnl) >= self.equity * (
            self.risk.max_weekly_loss_pct / 100.0
        ):
            return RiskCheck(
                approved=False,
                reason=f"Weekly loss limit reached ({self.risk.max_weekly_loss_pct}%)",
                blocked_by="weekly_loss_limit",
            )

        # Daily drawdown (peak-to-trough SINCE the day's open). This is a
        # distinct rule from ``max_total_drawdown_pct``: a strategy that is up
        # over its lifetime can still give back too much in one day.
        day_drawdown_pct = (
            ((self.day_peak_equity - self.equity) / self.day_peak_equity * 100.0)
            if self.day_peak_equity > 0
            else 0.0
        )
        if day_drawdown_pct >= self.risk.max_daily_drawdown_pct:
            return RiskCheck(
                approved=False,
                reason=(
                    f"Daily drawdown reached ({day_drawdown_pct:.1f}% >= "
                    f"{self.risk.max_daily_drawdown_pct}%)"
                ),
                blocked_by="daily_drawdown",
            )

        # Max total drawdown
        drawdown_pct = (
            ((self.peak_equity - self.equity) / self.peak_equity * 100.0)
            if self.peak_equity > 0
            else 0.0
        )
        if drawdown_pct >= self.risk.max_total_drawdown_pct:
            return RiskCheck(
                approved=False,
                reason=f"Max drawdown reached ({drawdown_pct:.1f}% >= {self.risk.max_total_drawdown_pct}%)",
                blocked_by="max_drawdown",
            )

        # DEF-RUN-014: the stop is resolved (and validated) before anything is sized, so
        # an unusable distance is reported as exactly that instead of being folded into a
        # generic sizing failure.
        if self.resolve_stop(signal) is None:
            return RiskCheck(
                approved=False,
                reason=self._last_stop_error or "stop_loss_pct is not usable",
                blocked_by="invalid_stop",
            )

        # Position sizing
        position_size = self._compute_position_size(signal)
        if position_size is None:
            return RiskCheck(
                approved=False,
                reason="Position size below minimum or above maximum",
                blocked_by="position_sizing",
            )

        resolution = position_size.stop_resolution or self.resolve_stop(signal)
        if resolution is None:  # pragma: no cover - resolve_stop succeeded upstream
            return RiskCheck(
                approved=False, reason="stop_resolution_missing", blocked_by="position_sizing"
            )
        if not resolution.stop_clears_costs and self.stop_cost_policy == "REJECT":
            # A stop shorter than the round trip is not a loss limit: the position is
            # already past the level the moment the fill pays its friction.
            return RiskCheck(
                approved=False,
                reason=(
                    f"stop {resolution.stop_distance_bps:.2f} bps <= round-trip cost "
                    f"{resolution.round_trip_cost_bps:.2f} bps: the stop cannot pay for the "
                    "trip it has to survive"
                ),
                blocked_by="stop_inside_costs",
                stop_resolution=resolution,
            )

        self._log.info(
            "risk.signal_approved",
            symbol=signal.symbol,
            side=signal.side,
            notional=position_size.notional_usdt,
            confidence=signal.confidence,
            stop_source=resolution.source,
            stop_loss_pct=position_size.stop_loss_pct,
            risk_at_stop_usdt=resolution.risk_at_stop_usdt,
        )

        return RiskCheck(
            approved=True, position_size=position_size, stop_resolution=resolution
        )

    def resolve_stop(self, signal: Signal) -> StopResolution | None:
        """Resolve the protective distance, or ``None`` when it is not usable.

        Public so a verifier can replay the decision from the same inputs the manager
        used, and so the lane can record the resolution even on a rejection. The
        validation is deliberately narrow and deterministic — nothing here can widen a
        stop to make a trade fit:

        * a non-finite or non-positive distance is not a stop;
        * a distance of 100 % or more is the whole position, which is the absence of a
          stop expressed as a number;
        * a non-positive or >=100 % target is not a target.

        When the *strategy* supplies nothing, the policy default is used and labelled
        ``POLICY_DEFAULT``. That is the only fallback, and it is never silent.
        """
        requested_stop = signal.stop_loss_pct
        if requested_stop is None:
            effective_stop = float(self.risk.default_stop_loss_pct)
            source: StopSource = "POLICY_DEFAULT"
            reason = (
                "strategy declared no stop_loss_pct; policy default applied and labelled "
                f"({effective_stop}%)"
            )
            clean = effective_stop
        else:
            clean = float(requested_stop)
            if not math.isfinite(clean) or clean <= 0.0 or clean >= 100.0:
                self._last_stop_error = (
                    f"stop_loss_pct {requested_stop!r} is not a usable distance: it must be "
                    "finite, > 0 and < 100"
                )
                return None
            effective_stop = clean
            source = "SIGNAL"
            reason = "strategy stop honoured unchanged"

        requested_take_profit = signal.take_profit_pct
        if requested_take_profit is None:
            effective_take_profit = float(self.risk.default_take_profit_pct)
            take_profit_source: StopSource = "POLICY_DEFAULT"
        else:
            clean_take = float(requested_take_profit)
            if not math.isfinite(clean_take) or clean_take <= 0.0 or clean_take >= 100.0:
                self._last_stop_error = (
                    f"take_profit_pct {requested_take_profit!r} is not a usable distance: it "
                    "must be finite, > 0 and < 100"
                )
                return None
            effective_take_profit = clean_take
            take_profit_source = "SIGNAL"

        return StopResolution(
            requested_stop_pct=None if requested_stop is None else float(requested_stop),
            effective_stop_pct=effective_stop,
            source=source,
            reason=reason,
            requested_take_profit_pct=(
                None if requested_take_profit is None else float(requested_take_profit)
            ),
            effective_take_profit_pct=effective_take_profit,
            take_profit_source=take_profit_source,
            stop_distance_bps=effective_stop * 100.0,
        )

    def _stop_cost_row(
        self, signal: Signal, resolution: StopResolution, notional: float
    ) -> tuple[float | None, bool]:
        """Measure the round trip the stop has to pay for, when a model is injected."""
        if self.stop_cost_policy == "OFF" or self.cost_bps_for is None:
            return None, True
        try:
            cost = float(self.cost_bps_for(signal.symbol, notional))
        except Exception:  # an unmeasurable cost is not a measured zero
            return None, self.stop_cost_policy != "REJECT"
        if not math.isfinite(cost) or cost < 0.0:
            return None, self.stop_cost_policy != "REJECT"
        return cost, resolution.stop_distance_bps > cost

    def _compute_position_size(self, signal: Signal) -> PositionSize | None:
        """Compute position size respecting all limits."""
        if signal.price <= 0:
            return None
        resolution = self.resolve_stop(signal)
        if resolution is None:
            return None

        # Risk-based sizing
        risk_amount = self.equity * (self.risk.max_risk_per_trade_pct / 100.0)
        stop_loss_pct = resolution.effective_stop_pct
        take_profit_pct = resolution.effective_take_profit_pct

        # Notional = risk_amount / (stop_loss_pct / 100)
        notional = risk_amount / (stop_loss_pct / 100.0) if stop_loss_pct > 0 else risk_amount

        #: Which clamp ends up binding. It is the smallest of the ceilings, and it is
        #: published because "risk 0.25 % per trade" is a cap the notional limit routinely
        #: overrides: the money at risk is ``notional × stop``, not the budget.
        ceilings: list[tuple[SizingBasis, float]] = [
            ("RISK_BUDGET", notional),
            ("MAX_ORDER_NOTIONAL_CLAMP", float(self.risk.max_order_notional_usdt)),
        ]

        # Clamp to the venue/policy band first, then let the exposure clamps only reduce
        # it. Widening after an exposure clamp would trade past the cap it just enforced.
        notional = max(
            self.risk.min_order_notional_usdt, min(notional, self.risk.max_order_notional_usdt)
        )

        # Check total exposure — handle both dict and object positions
        current_exposure = 0.0
        for pos in self.open_positions.values():
            current_exposure += self._position_notional(pos)
        max_remaining = self.equity * (self.risk.max_total_exposure_pct / 100.0) - current_exposure
        ceilings.append(("EXPOSURE_CLAMP", max_remaining))
        if notional > max_remaining:
            notional = max_remaining

        # Per-asset exposure.
        #
        # DEF-RISK-EXPOSURE-001 (P0): ``max_asset_exposure_pct`` was declared and
        # range/cross-validated in ``config/risk.py`` but read by NOTHING — the
        # clamp above only bounded TOTAL exposure, so three correlated positions
        # on the same asset could each take the full total budget. The param is
        # now the binding constraint for its own asset, and it NEVER widens the
        # total-exposure clamp (it can only reduce the notional further).
        asset = self._asset_of(signal.symbol)
        asset_exposure = 0.0
        for symbol, pos in self.open_positions.items():
            if self._position_asset(symbol, pos) == asset:
                asset_exposure += self._position_notional(pos)
        asset_remaining = self.equity * (self.risk.max_asset_exposure_pct / 100.0) - asset_exposure
        ceilings.append(("ASSET_EXPOSURE_CLAMP", asset_remaining))
        if notional > asset_remaining:
            notional = asset_remaining

        basis: SizingBasis = min(ceilings, key=lambda item: item[1])[0]

        #: A residual exposure smaller than the venue minimum is a rejection, never a
        #: round-up: raising the size here would trade more than the policy allowed.
        if notional < self.risk.min_order_notional_usdt:
            return None

        quantity = notional / signal.price
        stop_cost_bps, clears = self._stop_cost_row(signal, resolution, notional)
        resolution = replace(
            resolution,
            round_trip_cost_bps=stop_cost_bps,
            stop_clears_costs=None if stop_cost_bps is None else clears,
            risk_at_stop_usdt=notional * stop_loss_pct / 100.0,
            risk_budget_usdt=risk_amount,
            sizing_basis=basis,
            notional_usdt=notional,
        )

        return PositionSize(
            symbol=signal.symbol,
            side=signal.side,
            notional_usdt=round(notional, 2),
            quantity=quantity,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            risk_amount_usdt=round(risk_amount, 2),
            requested_stop_loss_pct=resolution.requested_stop_pct,
            stop_source=resolution.source,
            stop_reason=resolution.reason,
            risk_at_stop_usdt=round(notional * stop_loss_pct / 100.0, 8),
            sizing_basis=basis,
            stop_resolution=resolution,
        )

    def mark_equity(self, equity: float) -> None:
        """Replace equity with the book's net mark-to-market, peaks included.

        WP-EDGE-017/P0.3. ``record_trade_result`` moves equity by realized PnL;
        this method lets the caller mark it to the broker's *net* equity, which
        also carries the unrealized leg and the commissions accrued on open
        positions. It **assigns** rather than adds, so calling it after a
        ``record_trade_result`` reconciles to the broker without double counting.

        Sizing, both drawdown rules and the daily/weekly loss thresholds all read
        ``equity`` and the peaks, so a caller that marks this way makes every one
        of those gates net-of-cost instead of gross.
        """
        self.equity = float(equity)
        self.peak_equity = max(self.peak_equity, self.equity)
        self.day_peak_equity = max(self.day_peak_equity, self.equity)

    def record_trade_result(self, pnl: float) -> None:
        """Record a completed trade's P&L.

        ``pnl`` must be the net figure the book realized (commissions and
        execution cost already deducted). A gross number here silently moves the
        daily loss, drawdown and sizing gates: see WP-EDGE-017/P0.3.
        """
        self.roll_week()
        self.trades_today += 1
        self.daily_pnl += pnl
        self.weekly_pnl += pnl
        self.equity += pnl
        self.peak_equity = max(self.peak_equity, self.equity)
        self.day_peak_equity = max(self.day_peak_equity, self.equity)

        if pnl < 0:
            self.consecutive_losses += 1
            # Anchor the time-based cooldown at the most recent loss.
            self._last_loss_ms = self._now_ms()
        else:
            self.consecutive_losses = 0

        self._log.info(
            "risk.trade_recorded",
            pnl=pnl,
            daily_pnl=self.daily_pnl,
            weekly_pnl=self.weekly_pnl,
            equity=self.equity,
            consecutive_losses=self.consecutive_losses,
        )

    def add_position(self, symbol: str, position: Any) -> None:
        """Register an open position."""
        self.open_positions[symbol] = position

    def remove_position(self, symbol: str) -> None:
        """Remove a closed position."""
        self.open_positions.pop(symbol, None)

    def reset_daily(self) -> None:
        """Reset daily counters (call at start of each trading day).

        ``weekly_pnl`` is not reset by the *daily* boundary itself, but the day
        boundary is where a week boundary is observed when no trade happens over
        the weekend: ``roll_week`` clears the weekly accumulator only when the
        clock has actually entered a new UTC week.
        """
        self.roll_week()
        self.daily_pnl = 0.0
        self.trades_today = 0
        self.consecutive_losses = 0
        self.day_peak_equity = self.equity

    def restore_state(
        self,
        *,
        daily_pnl: float,
        weekly_pnl: float,
        trades_today: int,
        consecutive_losses: int,
        peak_equity: float,
        open_positions: dict[str, Any],
        kill_switch_active: bool,
        day_peak_equity: float | None = None,
        last_loss_ms: int = 0,
        weekly_start_ms: int | None = None,
    ) -> None:
        """Restore counters from durable state (GAP-R1 hardening).

        MUST be called before the first ``check_signal`` after a restart so
        daily-loss/drawdown/cooldown limits see pre-restart exposure.
        Deterministic field assignment — no policy decisions here.
        """
        self.daily_pnl = float(daily_pnl)
        self.weekly_pnl = float(weekly_pnl)
        self.trades_today = int(trades_today)
        self.consecutive_losses = int(consecutive_losses)
        self.peak_equity = float(peak_equity)
        self.day_peak_equity = (
            float(day_peak_equity) if day_peak_equity is not None else float(peak_equity)
        )
        self.open_positions = dict(open_positions)
        self._last_loss_ms = int(last_loss_ms)
        self._kill_switch_active = bool(kill_switch_active)
        if weekly_start_ms is None:
            # Legacy snapshot without an anchor: keep the restored loss (never
            # forgive it silently) but anchor it now, so the next boundary clears
            # it and it cannot veto forever.
            self.weekly_start_ms = week_start_ms_for(self._now_ms())
        else:
            self.weekly_start_ms = int(weekly_start_ms)
            self.roll_week()

    def _position_to_row(self, symbol: str, position: Any) -> dict[str, Any]:
        """JSON-safe projection of one open position for the durable store.

        The engine only ever needs ``notional_usdt`` (for the exposure clamps)
        and ``asset`` (for the per-asset clamp); those are always emitted. Any
        other fields present on a dict/object are carried through when they are
        JSON scalars, so the snapshot is faithful without inventing a schema.
        """
        known = ("asset", "symbol", "side", "quantity", "entry_price")
        row: dict[str, Any] = {
            "symbol": symbol,
            "asset": self._position_asset(symbol, position),
            "notional_usdt": self._position_notional(position),
        }
        source = position if isinstance(position, dict) else _attrs(position, known)
        for name in known:
            value = source.get(name)
            if value is not None and isinstance(value, (str, int, float, bool)):
                row[name] = value
        return row

    def extract_state(self) -> dict[str, Any]:
        """JSON-safe counter snapshot for the durable store.

        DEF-VERIFY-011: ``open_positions`` used to be a hardcoded ``{}``, so a
        restore through ``restore_state`` always rebuilt an empty book and the
        max-open-positions gate plus both exposure clamps were blind until the
        next live re-sync. It now carries the real book as JSON-safe rows.
        """
        return {
            "daily_pnl": self.daily_pnl,
            "weekly_pnl": self.weekly_pnl,
            "weekly_start_ms": self.weekly_start_ms,
            "trades_today": self.trades_today,
            "consecutive_losses": self.consecutive_losses,
            "peak_equity": self.peak_equity,
            "day_peak_equity": self.day_peak_equity,
            "last_loss_ms": self._last_loss_ms,
            "open_positions": {
                symbol: self._position_to_row(symbol, position)
                for symbol, position in self.open_positions.items()
            },
            "kill_switch_active": self._kill_switch_active,
        }

    def sync_open_positions(self, positions: dict[str, Any]) -> None:
        """Adopt the live book so exposure gates see real positions.

        The PAPER runtime never called ``add_position`` (it reconciles directly
        with the broker), so ``open_positions`` stayed empty and both the
        ``max_open_positions`` gate and the exposure clamps were effectively
        inert. This is the one supported way to hand the engine the book; it
        copies, it does not mutate the caller's mapping.
        """
        self.open_positions = dict(positions)

    def snapshot(self) -> dict[str, Any]:
        """Read-only snapshot of risk state."""
        drawdown_pct = (
            ((self.peak_equity - self.equity) / self.peak_equity * 100.0)
            if self.peak_equity > 0
            else 0.0
        )
        day_drawdown_pct = (
            ((self.day_peak_equity - self.equity) / self.day_peak_equity * 100.0)
            if self.day_peak_equity > 0
            else 0.0
        )
        return {
            "equity": self.equity,
            "peak_equity": self.peak_equity,
            "day_peak_equity": self.day_peak_equity,
            "drawdown_pct": round(drawdown_pct, 2),
            "daily_drawdown_pct": round(day_drawdown_pct, 2),
            "daily_pnl": self.daily_pnl,
            "weekly_pnl": self.weekly_pnl,
            "trades_today": self.trades_today,
            "consecutive_losses": self.consecutive_losses,
            "open_positions": len(self.open_positions),
            "exposure_by_asset": self.exposure_by_asset(),
            "kill_switch_active": self._kill_switch_active,
        }


__all__ = ["PositionSize", "RiskCheck", "RiskManager"]
