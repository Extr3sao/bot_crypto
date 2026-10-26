"""CAP-003 — deterministic decision outcome evaluator and comparison baselines.

CAP-002 sealed two real decisions and then had *nothing* that could say, by
itself, whether they were right.  This module is the missing judge.  It is fully
deterministic and it never asks the analyst anything:

* :class:`DecisionOutcome` is what the market actually did over the decision's
  own horizon, measured from the decision's own timestamp;
* :class:`DecisionPerformance` joins a sealed decision with that outcome and
  with the deterministic comparators that were computable *at seal time*.

Honesty rules baked in (each one is a way the measurement could otherwise lie):

* **No hindsight.**  ``build_window`` keeps only bars that had *fully closed* at
  the decision time for the entry, and it stops the outcome exactly at
  ``decision_time + horizon``.  Bars after the horizon are ignored, so a lucky
  move cannot leak into the label.
* **The horizon must have matured.**  Asking for an outcome before
  ``decision_time + horizon`` raises :class:`HorizonNotMaturedError`.  There is
  no partial or extrapolated outcome.
* **The evaluator never self-scores a thesis it cannot check.**  The V1 analyst
  emits a free-text invalidation, which is *not* machine-checkable.  The
  evaluator reports ``invalidation_hit = None`` with rule
  ``NOT_MACHINE_CHECKABLE_TEXT_INVALIDATION`` instead of inventing a threshold.
  A numeric ``invalidation_price`` (if a future frozen revision ever emits one)
  is honoured by a price-rule that is declared here, not chosen after the fact.
* **Everyone pays the same cost.**  The agent and every active comparator use
  one shared :class:`~trading_bot.research.agentic_baselines.CostModel`; a
  ``NO_TRADE`` sleeve trades nothing and therefore pays nothing.
* **Comparison labels are explicit.**  CAP-003's comparison set is the one the
  campaign asked for — A = the analyst itself, B = a frozen deterministic trend
  rule, C = buy-and-hold, D = random direction with the analyst's own
  distribution — and it is deliberately distinct from the CAP-001 evaluator
  labels.  ``D`` is a *distributional* comparator, so it is assigned at scoring
  time over the whole set (see :func:`matched_random_directions`) and is never
  written into an immutable per-decision evaluation.

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from typing import Any

from trading_bot.indicators.builtin import MacdIndicator, RsiIndicator
from trading_bot.market_data.types import OHLCV
from trading_bot.research import agentic_baselines as ab
from trading_bot.research import agentic_contracts as ac
from trading_bot.research.small_capital_v1 import SMA_WINDOW, sma

__all__ = [
    "AGENT_ID",
    "BASELINE_ID_BUY_AND_HOLD",
    "BASELINE_ID_DETERMINISTIC",
    "BASELINE_ID_RANDOM_MATCHED",
    "COMPARISON_BASELINE_IDS",
    "DETERMINISTIC_RULE_VERSION",
    "EVALUATOR_ID",
    "EVALUATOR_VERSION",
    "HORIZON_SECONDS",
    "INVALIDATION_NOT_MACHINE_CHECKABLE",
    "INVALIDATION_STRUCTURED_PRICE",
    "MACD_FAST",
    "MACD_SIGNAL_PERIOD",
    "MACD_SLOW",
    "OUTCOMES",
    "OUTCOME_FLAT",
    "OUTCOME_LOSS",
    "OUTCOME_NO_TRADE",
    "OUTCOME_WIN",
    "PROVIDER_SOURCE",
    "REASON_MACD_HISTORY_INSUFFICIENT",
    "REASON_RSI_EXTREME",
    "REASON_SIGNAL_MIXED",
    "RSI_HIGH",
    "RSI_LOW",
    "RSI_PERIOD",
    "RULE_INPUT_BARS_1D",
    "RULE_INPUT_BARS_4H",
    "BaselineComparison",
    "DecisionOutcome",
    "DecisionPerformance",
    "HorizonNotMaturedError",
    "OutcomeWindow",
    "RuleState",
    "analyst_confidence",
    "analyst_payload",
    "build_performance",
    "build_window",
    "deterministic_rule_state",
    "deterministic_trend_direction",
    "direction_distribution",
    "evaluate_decision",
    "horizon_seconds",
    "matched_random_directions",
    "outcome_payload_hash",
    "performance_payload_hash",
    "sleeve_outcome",
]

# --------------------------------------------------------------------------- #
# §1 — frozen identities
# --------------------------------------------------------------------------- #

EVALUATOR_ID = "DecisionOutcomeEvaluator"
EVALUATOR_VERSION = "DECISION_OUTCOME_EVALUATOR_V1"

#: CAP-003 comparison set.  A is the analyst under test; B/C/D are comparators.
AGENT_ID = "A_MARKET_ANALYST_V1"
BASELINE_ID_DETERMINISTIC = "B_DETERMINISTIC_TREND_RULE"
BASELINE_ID_BUY_AND_HOLD = "C_BUY_AND_HOLD"
BASELINE_ID_RANDOM_MATCHED = "D_RANDOM_MATCHED_DISTRIBUTION"

COMPARISON_BASELINE_IDS: tuple[str, ...] = (
    BASELINE_ID_DETERMINISTIC,
    BASELINE_ID_BUY_AND_HOLD,
    BASELINE_ID_RANDOM_MATCHED,
)

OUTCOME_WIN = "WIN"
OUTCOME_LOSS = "LOSS"
OUTCOME_FLAT = "FLAT"
OUTCOME_NO_TRADE = "NO_TRADE"
OUTCOMES: tuple[str, ...] = (OUTCOME_WIN, OUTCOME_LOSS, OUTCOME_FLAT, OUTCOME_NO_TRADE)

#: Horizon -> seconds.  Must stay aligned with the frozen analyst horizons.
HORIZON_SECONDS: dict[str, int] = {"4H": 14_400, "24H": 86_400, "72H": 259_200}

PROVIDER_SOURCE = "binance_public_ccxt"

# --------------------------------------------------------------------------- #
# §2 — the frozen deterministic comparator (comparison B)
# --------------------------------------------------------------------------- #

#: Frozen rule identity: ``SMA(200)`` trend + ``MACD(12,26,9)`` momentum + RSI
#: filter.  No window, threshold or parameter here is ever searched.
#:
#: ``V1_1`` is a *reproducibility* fix, not a semantic change: V1 fed the rule
#: whatever history the caller happened to download, and an EMA has infinite
#: memory, so a 500-bar fetch and a 494-bar fetch produced slightly different
#: MACD values for the same decision time.  The rule now reads a fixed-length
#: tail, so anyone holding the same bars re-derives the same direction.  It was
#: frozen before a single candidate had been evaluated (0 outcomes exist), so no
#: recorded comparison is invalidated by it.
DETERMINISTIC_RULE_VERSION = "DETERMINISTIC_TREND_RULE_V1_1"

#: Fixed input depth for the rule.  Long enough for MACD(12,26,9) to settle and
#: for SMA(200) to have history, short enough to be exactly re-derivable.
RULE_INPUT_BARS_4H = 400
RULE_INPUT_BARS_1D = 300
RSI_PERIOD = 14
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL_PERIOD = 9
RSI_LOW = 30.0
RSI_HIGH = 70.0

REASON_MACD_HISTORY_INSUFFICIENT = "INSUFFICIENT_MACD_HISTORY"
REASON_RSI_EXTREME = "RSI_EXTREME"
REASON_SIGNAL_MIXED = "SIGNAL_MIXED"

#: The V1 analyst emits a free-text invalidation; it cannot be machine-checked.
INVALIDATION_NOT_MACHINE_CHECKABLE = "NOT_MACHINE_CHECKABLE_TEXT_INVALIDATION"
INVALIDATION_STRUCTURED_PRICE = "STRUCTURED_PRICE_LEVEL"


class HorizonNotMaturedError(ValueError):
    """Raised when an outcome is requested before the horizon has closed."""


def horizon_seconds(horizon: str) -> int:
    try:
        return HORIZON_SECONDS[horizon]
    except KeyError as exc:
        raise ValueError(
            f"horizon must be one of {tuple(HORIZON_SECONDS)}, got {horizon!r}"
        ) from exc


def _open_time_seconds(row: OHLCV) -> int:
    return int(row.timestamp) // 1_000


def _ordered(rows: Sequence[OHLCV]) -> list[OHLCV]:
    return sorted(rows, key=lambda row: row.timestamp)


@dataclass(frozen=True, slots=True)
class RuleState:
    """Comparison B's signal plus the exact bars it was derived from.

    ``inputs_hash`` is the reproducibility anchor: two runs holding the same
    completed bars must produce the same direction *and* the same hash.
    """

    direction: str
    reason: str
    inputs_hash: str
    bars_4h: int
    bars_1d: int


def deterministic_rule_state(
    *,
    rows_4h: Sequence[OHLCV],
    daily_rows: Sequence[OHLCV],
    decision_time: int,
    bar_seconds: int = 14_400,
    daily_bar_seconds: int = 86_400,
) -> RuleState:
    """Comparison B — the frozen deterministic rule, causal and re-derivable.

    Only bars that had fully closed at ``decision_time`` can contribute, and the
    rule reads a fixed-length tail of them (``RULE_INPUT_BARS_4H`` /
    ``RULE_INPUT_BARS_1D``), so a wider download cannot change the answer.
    """
    daily_bars = [
        ab.DailyBar(open_time=_open_time_seconds(row), close=float(row.close))
        for row in _ordered(daily_rows)
    ]
    daily_closes = ab.completed_daily_closes(
        daily_bars, decision_time=decision_time, bar_seconds=daily_bar_seconds
    )[-RULE_INPUT_BARS_1D:]

    causal = [
        row for row in _ordered(rows_4h) if _open_time_seconds(row) + bar_seconds <= decision_time
    ][-RULE_INPUT_BARS_4H:]
    inputs_hash = ac.payload_digest(
        {
            "version": DETERMINISTIC_RULE_VERSION,
            "decision_time": decision_time,
            "bar_seconds": bar_seconds,
            "daily_bar_seconds": daily_bar_seconds,
            "bars_4h": [[_open_time_seconds(row), float(row.close)] for row in causal],
            "daily_closes": [[int(bar.open_time), float(bar.close)] for bar in daily_bars[-RULE_INPUT_BARS_1D:]],
        }
    )

    def state(direction: str, reason: str) -> RuleState:
        return RuleState(
            direction=direction,
            reason=reason,
            inputs_hash=inputs_hash,
            bars_4h=len(causal),
            bars_1d=len(daily_closes),
        )

    if len(daily_closes) < SMA_WINDOW:
        return state("NO_TRADE", ab.INSUFFICIENT_SMA200_HISTORY)
    average = sma([float(close) for close in daily_closes], SMA_WINDOW)[-1]
    if average is None:
        return state("NO_TRADE", ab.INSUFFICIENT_SMA200_HISTORY)
    trend_up = daily_closes[-1] > average

    if len(causal) < MACD_SLOW + MACD_SIGNAL_PERIOD - 1:
        return state("NO_TRADE", REASON_MACD_HISTORY_INSUFFICIENT)
    macd = MacdIndicator().compute(
        causal, {"fast": MACD_FAST, "slow": MACD_SLOW, "signal": MACD_SIGNAL_PERIOD}
    )
    rsi = RsiIndicator().compute(causal, {"period": RSI_PERIOD})
    if not RSI_LOW <= rsi <= RSI_HIGH:
        return state("NO_TRADE", REASON_RSI_EXTREME)

    momentum_up = macd["macd"] > macd["signal"]
    if trend_up and momentum_up:
        return state("LONG", "TREND_UP_MACD_LONG")
    if not trend_up and not momentum_up:
        return state("SHORT", "TREND_DOWN_MACD_SHORT")
    return state("NO_TRADE", REASON_SIGNAL_MIXED)


def deterministic_trend_direction(
    *,
    rows_4h: Sequence[OHLCV],
    daily_rows: Sequence[OHLCV],
    decision_time: int,
    bar_seconds: int = 14_400,
    daily_bar_seconds: int = 86_400,
) -> tuple[str, str]:
    """``(direction, reason)`` for comparison B (CAP-003 API, unchanged)."""
    rule = deterministic_rule_state(
        rows_4h=rows_4h,
        daily_rows=daily_rows,
        decision_time=decision_time,
        bar_seconds=bar_seconds,
        daily_bar_seconds=daily_bar_seconds,
    )
    return rule.direction, rule.reason


# --------------------------------------------------------------------------- #
# §3 — the causal outcome window
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class OutcomeWindow:
    """The exact, closed price path a decision is judged against."""

    decision_time: int
    horizon: str
    horizon_seconds: int
    entry_price: float
    entry_open_time: int
    entry_close_time: int
    exit_price: float
    exit_open_time: int
    exit_close_time: int
    bars_used: int
    path: tuple[float, ...]
    highs: tuple[float, ...]
    lows: tuple[float, ...]


def build_window(
    *,
    rows: Sequence[OHLCV],
    decision_time: int,
    horizon: str,
    bar_seconds: int = 14_400,
) -> OutcomeWindow:
    """Close the outcome window, or refuse because it has not matured yet.

    The entry is the close of the last bar that had fully closed at
    ``decision_time``; the exit is the close of the bar that closes exactly at
    ``decision_time + horizon``.  Nothing beyond the exit can influence the
    window.
    """
    seconds = horizon_seconds(horizon)
    ordered = _ordered(rows)
    completed = [row for row in ordered if _open_time_seconds(row) + bar_seconds <= decision_time]
    if not completed:
        raise HorizonNotMaturedError(f"no completed bar at decision_time={decision_time}")
    entry = completed[-1]
    entry_open = _open_time_seconds(entry)
    entry_close = entry_open + bar_seconds
    exit_close = decision_time + seconds

    exit_row = next(
        (row for row in ordered if _open_time_seconds(row) + bar_seconds == exit_close), None
    )
    if exit_row is None:
        raise HorizonNotMaturedError(
            f"horizon {horizon} not matured: no bar closes at {exit_close}"
        )

    entry_price = float(entry.close)
    exit_price = float(exit_row.close)
    if entry_price <= 0.0 or exit_price <= 0.0:
        raise ValueError("entry and exit prices must be positive")

    window_rows = [
        row
        for row in ordered
        if entry_open <= _open_time_seconds(row) <= _open_time_seconds(exit_row)
    ]
    return OutcomeWindow(
        decision_time=decision_time,
        horizon=horizon,
        horizon_seconds=seconds,
        entry_price=entry_price,
        entry_open_time=entry_open,
        entry_close_time=entry_close,
        exit_price=exit_price,
        exit_open_time=_open_time_seconds(exit_row),
        exit_close_time=exit_close,
        bars_used=len(window_rows),
        path=tuple(float(row.close) for row in window_rows),
        highs=tuple(float(row.high) for row in window_rows),
        lows=tuple(float(row.low) for row in window_rows),
    )


def _window_evidence(window: OutcomeWindow, *, source: str, bar_seconds: int) -> dict[str, Any]:
    return {
        "decision_time": window.decision_time,
        "horizon": window.horizon,
        "horizon_seconds": window.horizon_seconds,
        "bar_seconds": bar_seconds,
        "entry_open_time": window.entry_open_time,
        "entry_close_time": window.entry_close_time,
        "exit_open_time": window.exit_open_time,
        "exit_close_time": window.exit_close_time,
        "entry_price": window.entry_price,
        "exit_price": window.exit_price,
        "bars_used": window.bars_used,
        "path": list(window.path),
        "highs": list(window.highs),
        "lows": list(window.lows),
        "source": source,
    }


# --------------------------------------------------------------------------- #
# §4 — the outcome record
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class DecisionOutcome:
    """What the market did over one sealed decision's horizon.  Never a thesis."""

    decision_id: str
    decision_hash: str
    snapshot_hash: str
    asset: str
    decision_time: int
    horizon: str
    horizon_seconds: int
    evaluation_time: int
    observed_at: int
    decision: str
    confidence: float
    entry_price: float
    entry_close_time: int
    exit_price: float
    exit_close_time: int
    bars_used: int
    gross_return: float
    costs: float
    net_return: float
    mfe: float
    mae: float
    direction_correct: bool
    invalidation_hit: bool | None
    invalidation_rule: str
    outcome: str
    evidence_hash: str
    evaluator: str
    evaluator_version: str
    source: str
    outcome_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return dict(asdict(self))

    def hashable_dict(self) -> dict[str, Any]:
        return {key: value for key, value in self.to_dict().items() if key != "outcome_hash"}

    def hash(self) -> str:
        return outcome_payload_hash(self.hashable_dict())

    def with_hash(self) -> DecisionOutcome:
        return replace(self, outcome_hash=self.hash())

    def is_verified(self) -> bool:
        return bool(self.outcome_hash) and self.outcome_hash == self.hash()


def outcome_payload_hash(payload: Mapping[str, Any]) -> str:
    """Digest of an outcome payload, ignoring its own hash field."""
    return ac.payload_digest({key: value for key, value in payload.items() if key != "outcome_hash"})


def analyst_payload(record: ac.DecisionRecord) -> Mapping[str, Any]:
    """The frozen analyst answer embedded in a sealed record (``{}`` if absent)."""
    agent = record.agent_output
    if isinstance(agent, Mapping):
        analyst = agent.get("analyst")
        if isinstance(analyst, Mapping):
            return analyst
    return {}


def analyst_confidence(record: ac.DecisionRecord) -> float:
    """Stated confidence in ``[0, 1]``; ``0.0`` when absent or out of range."""
    value = analyst_payload(record).get("confidence", 0.0)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    number = float(value)
    return number if 0.0 <= number <= 1.0 else 0.0


def _invalidation(
    *,
    decision: str,
    invalidation_price: float | None,
    highs: Sequence[float],
    lows: Sequence[float],
) -> tuple[bool | None, str]:
    """Structured price invalidation only; free text is never guessed."""
    if decision == "NO_TRADE":
        return None, INVALIDATION_NOT_MACHINE_CHECKABLE
    if invalidation_price is None:
        return None, INVALIDATION_NOT_MACHINE_CHECKABLE
    if invalidation_price <= 0.0:
        raise ValueError("invalidation_price must be positive when supplied")
    if decision == "LONG":
        return any(low <= invalidation_price for low in lows), INVALIDATION_STRUCTURED_PRICE
    if decision == "SHORT":
        return any(high >= invalidation_price for high in highs), INVALIDATION_STRUCTURED_PRICE
    raise ValueError(f"decision must be one of {ac.DIRECTIONS}, got {decision!r}")


def _outcome_label(decision: str, net_return: float) -> str:
    if decision == "NO_TRADE":
        return OUTCOME_NO_TRADE
    if net_return > 0.0:
        return OUTCOME_WIN
    if net_return < 0.0:
        return OUTCOME_LOSS
    return OUTCOME_FLAT


def sleeve_outcome(
    *, direction: str, entry_price: float, exit_price: float, cost_model: ab.CostModel
) -> tuple[float, float, float]:
    """``(gross, costs, net)`` for one sleeve; cash trades nothing and pays nothing."""
    gross = ab.directional_gross_return(
        direction=direction, entry_price=entry_price, exit_price=exit_price
    )
    costs = 0.0 if direction == "NO_TRADE" else cost_model.cost_for(1.0)
    return gross, costs, gross - costs


def evaluate_decision(
    *,
    record: ac.DecisionRecord,
    asset: str,
    horizon: str,
    rows: Sequence[OHLCV],
    bar_seconds: int = 14_400,
    cost_model: ab.CostModel = ab.DEFAULT_COST_MODEL,
    invalidation_price: float | None = None,
    source: str = PROVIDER_SOURCE,
) -> DecisionOutcome:
    """Judge one sealed decision against real market data.  Deterministic.

    Raises :class:`HorizonNotMaturedError` before the horizon closes, so a
    premature "outcome" can never enter the ledger.
    """
    if not record.is_verified():
        raise ValueError("refusing to evaluate an unsealed or tampered decision record")
    seconds = horizon_seconds(horizon)
    window = build_window(
        rows=rows, decision_time=record.timestamp, horizon=horizon, bar_seconds=bar_seconds
    )
    gross, costs, net = sleeve_outcome(
        direction=record.decision,
        entry_price=window.entry_price,
        exit_price=window.exit_price,
        cost_model=cost_model,
    )
    mfe, mae = ab.excursion(
        direction=record.decision,
        entry_price=window.entry_price,
        path=(*window.highs, *window.lows),
    )
    directional = record.decision in ("LONG", "SHORT")
    invalidation_hit, invalidation_rule = _invalidation(
        decision=record.decision,
        invalidation_price=invalidation_price,
        highs=window.highs,
        lows=window.lows,
    )
    return DecisionOutcome(
        decision_id=ab.decision_id_for(record),
        decision_hash=record.decision_hash,
        snapshot_hash=record.evidence_snapshot_hash,
        asset=asset,
        decision_time=record.timestamp,
        horizon=horizon,
        horizon_seconds=seconds,
        evaluation_time=record.timestamp + seconds,
        observed_at=window.exit_close_time,
        decision=record.decision,
        confidence=analyst_confidence(record),
        entry_price=window.entry_price,
        entry_close_time=window.entry_close_time,
        exit_price=window.exit_price,
        exit_close_time=window.exit_close_time,
        bars_used=window.bars_used,
        gross_return=gross,
        costs=costs,
        net_return=net,
        mfe=mfe,
        mae=mae,
        direction_correct=bool(gross > 0.0) if directional else False,
        invalidation_hit=invalidation_hit,
        invalidation_rule=invalidation_rule,
        outcome=_outcome_label(record.decision, net),
        evidence_hash=ac.payload_digest(_window_evidence(window, source=source, bar_seconds=bar_seconds)),
        evaluator=EVALUATOR_ID,
        evaluator_version=EVALUATOR_VERSION,
        source=source,
    ).with_hash()


# --------------------------------------------------------------------------- #
# §5 — decision performance (sealed decision + outcome + seal-time comparators)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class BaselineComparison:
    baseline_id: str
    direction: str
    available: bool
    gross_return: float
    costs: float
    net_return: float
    rule_version: str = ""
    reason: str = ""
    rule_input_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return dict(asdict(self))


@dataclass(frozen=True, slots=True)
class DecisionPerformance:
    """``DecisionRecord + DecisionOutcome`` plus every seal-time comparator."""

    decision_id: str
    decision_hash: str
    outcome_hash: str
    asset: str
    decision: str
    horizon: str
    confidence: float
    decision_time: int
    evaluation_time: int
    entry_price: float
    exit_price: float
    gross_return: float
    costs: float
    net_return: float
    direction_correct: bool
    outcome: str
    invalidation_hit: bool | None
    mfe: float
    mae: float
    comparisons: tuple[BaselineComparison, ...]
    cost_bps_per_side: float
    round_trip_cost: float
    source: str
    evaluation_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return dict(asdict(self))

    def hashable_dict(self) -> dict[str, Any]:
        return {key: value for key, value in self.to_dict().items() if key != "evaluation_hash"}

    def hash(self) -> str:
        return performance_payload_hash(self.hashable_dict())

    def with_hash(self) -> DecisionPerformance:
        return replace(self, evaluation_hash=self.hash())

    def is_verified(self) -> bool:
        return bool(self.evaluation_hash) and self.evaluation_hash == self.hash()

    def comparison(self, baseline_id: str) -> BaselineComparison | None:
        for item in self.comparisons:
            if item.baseline_id == baseline_id:
                return item
        return None

    def edge_vs(self, baseline_id: str) -> float | None:
        """Net-of-cost incremental edge against one available comparator."""
        item = self.comparison(baseline_id)
        if item is None or not item.available:
            return None
        return self.net_return - item.net_return


def performance_payload_hash(payload: Mapping[str, Any]) -> str:
    """Digest of a performance payload, ignoring its own hash field."""
    return ac.payload_digest(
        {key: value for key, value in payload.items() if key != "evaluation_hash"}
    )


def _comparison(
    baseline_id: str,
    *,
    direction: str,
    entry_price: float,
    exit_price: float,
    cost_model: ab.CostModel,
    rule_version: str = "",
    reason: str = "",
    rule_input_hash: str = "",
) -> BaselineComparison:
    gross, costs, net = sleeve_outcome(
        direction=direction, entry_price=entry_price, exit_price=exit_price, cost_model=cost_model
    )
    return BaselineComparison(
        baseline_id=baseline_id,
        direction=direction,
        available=True,
        gross_return=gross,
        costs=costs,
        net_return=net,
        rule_version=rule_version,
        reason=reason,
        rule_input_hash=rule_input_hash,
    )


def build_performance(
    *,
    record: ac.DecisionRecord,
    outcome: DecisionOutcome,
    rows_4h: Sequence[OHLCV],
    daily_rows: Sequence[OHLCV] = (),
    bar_seconds: int = 14_400,
    daily_bar_seconds: int = 86_400,
    cost_model: ab.CostModel = ab.DEFAULT_COST_MODEL,
) -> DecisionPerformance:
    """Join a sealed decision with its outcome and the seal-time comparators.

    Comparators produced here are B (frozen deterministic rule) and C
    (buy-and-hold).  D is assigned by the scorecard over the whole evaluated
    set, because "the same distribution as the analyst" is a statement about the
    set, not about one decision.
    """
    if not outcome.is_verified():
        raise ValueError("refusing to score an unverified outcome")
    if outcome.decision_hash != record.decision_hash:
        raise ValueError("outcome does not belong to this decision record")

    rule = deterministic_rule_state(
        rows_4h=rows_4h,
        daily_rows=daily_rows,
        decision_time=record.timestamp,
        bar_seconds=bar_seconds,
        daily_bar_seconds=daily_bar_seconds,
    )
    comparisons = (
        _comparison(
            BASELINE_ID_DETERMINISTIC,
            direction=rule.direction,
            entry_price=outcome.entry_price,
            exit_price=outcome.exit_price,
            cost_model=cost_model,
            rule_version=DETERMINISTIC_RULE_VERSION,
            reason=rule.reason,
            rule_input_hash=rule.inputs_hash,
        ),
        _comparison(
            BASELINE_ID_BUY_AND_HOLD,
            direction="LONG",
            entry_price=outcome.entry_price,
            exit_price=outcome.exit_price,
            cost_model=cost_model,
            rule_version="BUY_AND_HOLD",
            reason="ALWAYS_LONG",
        ),
    )
    return DecisionPerformance(
        decision_id=outcome.decision_id,
        decision_hash=record.decision_hash,
        outcome_hash=outcome.outcome_hash,
        asset=outcome.asset,
        decision=outcome.decision,
        horizon=outcome.horizon,
        confidence=outcome.confidence,
        decision_time=outcome.decision_time,
        evaluation_time=outcome.evaluation_time,
        entry_price=outcome.entry_price,
        exit_price=outcome.exit_price,
        gross_return=outcome.gross_return,
        costs=outcome.costs,
        net_return=outcome.net_return,
        direction_correct=outcome.direction_correct,
        outcome=outcome.outcome,
        invalidation_hit=outcome.invalidation_hit,
        mfe=outcome.mfe,
        mae=outcome.mae,
        comparisons=comparisons,
        cost_bps_per_side=cost_model.fee_bps_per_side
        + cost_model.spread_bps_per_side
        + cost_model.slippage_bps_per_side,
        round_trip_cost=cost_model.round_trip_fraction,
        source=outcome.source,
    ).with_hash()


# --------------------------------------------------------------------------- #
# §6 — comparator D: random direction with the analyst's own distribution
# --------------------------------------------------------------------------- #


def direction_distribution(directions: Sequence[str]) -> dict[str, int]:
    """Count of ``LONG`` / ``SHORT`` / ``NO_TRADE`` in the evaluated set."""
    counts = {direction: 0 for direction in ac.DIRECTIONS}
    for direction in directions:
        if direction not in counts:
            raise ValueError(f"direction must be one of {ac.DIRECTIONS}, got {direction!r}")
        counts[direction] += 1
    return counts


def matched_random_directions(directions: Sequence[str], *, seed: int) -> tuple[str, ...]:
    """An exact permutation of the analyst's directions, deterministically.

    Using a permutation (not a fresh sample) matches the *realized* mix exactly,
    so comparator D isolates timing/selection skill instead of exposure mix, and
    adds no sampling noise.  The seed is frozen by the caller, so the assignment
    is reproducible for a given evaluated set.
    """
    assigned = list(directions)
    random.Random(seed).shuffle(assigned)
    return tuple(assigned)
