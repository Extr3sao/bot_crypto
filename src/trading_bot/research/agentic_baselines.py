"""CAP-002 — deterministic baseline outcome producer for the agentic pilot.

CAP-001 shipped the evaluator primitive
:func:`trading_bot.research.agentic_contracts.incremental_edge` but never shipped
the *baseline series* it compares against: ``BASELINES`` was only a tuple of
labels, and ``baseline_outcome`` had to be supplied by hand.  This module adds
that missing producer and a separate, future-only :class:`OutcomeRecord`, and
nothing else.  It is **not** a scorer, an evaluator, an agent or a strategy.

Honesty rules baked in here:

* **A_NO_TRADE_CASH** earns exactly ``0`` — no cash yield is invented;
* **B_BUY_AND_HOLD** uses the same asset, ``decision_time``, horizon and
  entry/exit semantics as the sealed decision, with realistic shared costs and
  no hindsight;
* **C_SIMPLE_TREND_SMA200** reuses the frozen RFC-039 rule
  :func:`trading_bot.research.small_capital_v1.sma` with ``window=SMA_WINDOW``
  (``close > SMA(200)`` -> ``LONG`` else ``CASH``).  No other window, no
  exponential smoothing and no parameter search exist in this file.  The signal
  is frozen from *completed*
  daily bars known at ``decision_time``; if there is not enough history the
  baseline is ``BASELINE_UNAVAILABLE`` instead of silently using a shorter mean;
* **D_PASSIVE_ASSET_BENCHMARK** is only produced from a *predeclared* canonical
  asset -> benchmark mapping.  No such mapping is declared in the frozen
  repository, so it is ``BASELINE_UNAVAILABLE`` with reason
  ``NO_PREDECLARED_CANONICAL_MAPPING``.  It is never invented and never chosen
  after seeing outcomes.  When a mapping maps the asset to itself it is
  economically the same exposure as buy-and-hold and is flagged
  ``economically_equivalent`` rather than reported as a fourth comparator;
* the **agent and every active baseline pay the same cost model** (one
  :class:`CostModel` is threaded through), and ``A_NO_TRADE_CASH`` pays none;
* the sealed :class:`~trading_bot.research.agentic_contracts.DecisionRecord` is
  **never mutated**: the future outcome lives in a separate
  :class:`OutcomeRecord` linked by ``decision_id`` + ``decision_hash``.

Costs are already embedded in each sleeve's ``net_return`` before it reaches
``incremental_edge``; the extra ``cost`` term of that primitive is therefore
``0.0`` so no cost is double counted.  The record carries every ``costs`` value
explicitly so a verifier can re-check that both sides paid.

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from trading_bot.research import agentic_contracts as ac
from trading_bot.research.small_capital_v1 import COST_BPS_PER_SIDE, SMA_WINDOW, sma

__all__ = [
    "BASELINE_IDS",
    "BASELINE_ID_BUY_AND_HOLD",
    "BASELINE_ID_NO_TRADE",
    "BASELINE_ID_PASSIVE",
    "BASELINE_ID_SIMPLE_TREND",
    "BASELINE_UNAVAILABLE",
    "CANONICAL_PASSIVE_BENCHMARK_MAPPING",
    "DEFAULT_COST_MODEL",
    "EVALUATOR_LABELS",
    "G_AGENTIC_EDGE",
    "BaselineOutcome",
    "CostModel",
    "DailyBar",
    "OutcomeRecord",
    "build_outcome_record",
    "buy_and_hold_baseline",
    "cash_baseline",
    "completed_daily_closes",
    "decision_id_for",
    "directional_gross_return",
    "excursion",
    "passive_benchmark_baseline",
    "passive_benchmark_equals_buy_and_hold",
    "simple_trend_baseline",
]

# --------------------------------------------------------------------------- #
# §1 — canonical baseline identities and the bridge to the frozen evaluator
# --------------------------------------------------------------------------- #

BASELINE_ID_NO_TRADE = "A_NO_TRADE_CASH"
BASELINE_ID_BUY_AND_HOLD = "B_BUY_AND_HOLD"
BASELINE_ID_SIMPLE_TREND = "C_SIMPLE_TREND_SMA200"
BASELINE_ID_PASSIVE = "D_PASSIVE_ASSET_BENCHMARK"

BASELINE_IDS: tuple[str, ...] = (
    BASELINE_ID_NO_TRADE,
    BASELINE_ID_BUY_AND_HOLD,
    BASELINE_ID_SIMPLE_TREND,
    BASELINE_ID_PASSIVE,
)

#: Returned whenever an honest baseline cannot be produced (never a guess).
BASELINE_UNAVAILABLE = "BASELINE_UNAVAILABLE"
NO_PREDECLARED_CANONICAL_MAPPING = "NO_PREDECLARED_CANONICAL_MAPPING"
INSUFFICIENT_SMA200_HISTORY = "INSUFFICIENT_SMA200_HISTORY"

#: CAP-002 canonical ids -> the labels ``agentic_contracts.incremental_edge``
#: already validates against.  The frozen evaluator is *not* touched.
EVALUATOR_LABELS: dict[str, str] = {
    BASELINE_ID_NO_TRADE: "A_NO_TRADE",
    BASELINE_ID_BUY_AND_HOLD: "B_BUY_AND_HOLD",
    BASELINE_ID_SIMPLE_TREND: "C_SIMPLE_TREND",
    BASELINE_ID_PASSIVE: "D_PASSIVE_PORTFOLIO",
}

#: The agentic-edge gate cannot pass without real sealed outcomes.
G_AGENTIC_EDGE = "NOT_TESTED"

#: No asset -> benchmark mapping has ever been predeclared in the frozen repo.
#: ``business_freeze.PRIMARY_PASSIVE_BENCHMARK`` is a required *slot*, never a
#: bound symbol, and its rules forbid choosing one after seeing results.
CANONICAL_PASSIVE_BENCHMARK_MAPPING: dict[str, str] = {}

# --------------------------------------------------------------------------- #
# §2 — shared, explicit cost model (agent and active baselines use the same one)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class CostModel:
    """Per-side cost in basis points, applied to traded notional.

    The round trip is charged once per active sleeve: a sleeve with exposure
    ``0`` (cash) pays nothing.
    """

    fee_bps_per_side: float
    spread_bps_per_side: float = 0.0
    slippage_bps_per_side: float = 0.0

    def __post_init__(self) -> None:
        for name, value in (
            ("fee_bps_per_side", self.fee_bps_per_side),
            ("spread_bps_per_side", self.spread_bps_per_side),
            ("slippage_bps_per_side", self.slippage_bps_per_side),
        ):
            if value < 0.0:
                raise ValueError(f"{name} must not be negative")

    @property
    def per_side_fraction(self) -> float:
        return (self.fee_bps_per_side + self.spread_bps_per_side + self.slippage_bps_per_side) / 10_000.0

    @property
    def round_trip_fraction(self) -> float:
        return 2.0 * self.per_side_fraction

    def cost_for(self, exposure: float) -> float:
        """Round-trip cost as a fraction of notional for a given exposure."""
        if exposure < 0.0:
            raise ValueError("exposure must not be negative")
        return self.round_trip_fraction * exposure

    def to_dict(self) -> dict[str, float]:
        return {
            "fee_bps_per_side": self.fee_bps_per_side,
            "spread_bps_per_side": self.spread_bps_per_side,
            "slippage_bps_per_side": self.slippage_bps_per_side,
            "round_trip_fraction": self.round_trip_fraction,
        }


#: Reuses the frozen RFC-039 per-side cost constant.  10 bps per side -> 20 bps
#: round trip.  Same model for the agent and every active baseline.
DEFAULT_COST_MODEL = CostModel(fee_bps_per_side=COST_BPS_PER_SIDE)


# --------------------------------------------------------------------------- #
# §3 — daily bars and the causal completed-bar filter
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class DailyBar:
    """One daily candle: ``open_time`` is the bar's opening unix second."""

    open_time: int
    close: float


def completed_daily_closes(
    bars: Sequence[DailyBar], *, decision_time: int, bar_seconds: int = 86_400
) -> tuple[float, ...]:
    """Closes of daily bars that had *fully closed* at ``decision_time``.

    A bar is completed once ``open_time + bar_seconds <= decision_time``.  An
    in-progress (intraday) candle is therefore excluded, and a bar opening in
    the future can never contribute.  Bars must be strictly ascending.
    """
    if bar_seconds <= 0:
        raise ValueError("bar_seconds must be > 0")
    closes: list[float] = []
    previous: int | None = None
    for bar in bars:
        if bar.close <= 0.0 or not math.isfinite(bar.close):
            raise ValueError("every daily bar needs a positive finite close")
        if previous is not None and bar.open_time <= previous:
            raise ValueError("daily bars must be strictly ascending by open_time")
        previous = bar.open_time
        if bar.open_time + bar_seconds <= decision_time:
            closes.append(bar.close)
    return tuple(closes)


# --------------------------------------------------------------------------- #
# §4 — baseline outcomes
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class BaselineOutcome:
    baseline_id: str
    evaluator_label: str
    available: bool
    exposure: float
    gross_return: float
    cost: float
    net_return: float
    reason: str = ""
    economically_equivalent: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _unavailable(baseline_id: str, reason: str) -> BaselineOutcome:
    return BaselineOutcome(
        baseline_id=baseline_id,
        evaluator_label=EVALUATOR_LABELS[baseline_id],
        available=False,
        exposure=0.0,
        gross_return=0.0,
        cost=0.0,
        net_return=0.0,
        reason=reason,
    )


def cash_baseline() -> BaselineOutcome:
    """A — hold cash: zero exposure, zero gross, zero cost, zero net.

    No cash yield is invented (RFC-039 fixes a 0% cash return).
    """
    return BaselineOutcome(
        baseline_id=BASELINE_ID_NO_TRADE,
        evaluator_label=EVALUATOR_LABELS[BASELINE_ID_NO_TRADE],
        available=True,
        exposure=0.0,
        gross_return=0.0,
        cost=0.0,
        net_return=0.0,
    )


def _long_only_net(*, entry_price: float, exit_price: float, cost_model: CostModel) -> tuple[float, float, float]:
    if entry_price <= 0.0 or exit_price <= 0.0:
        raise ValueError("entry and exit prices must be positive")
    gross = exit_price / entry_price - 1.0
    cost = cost_model.cost_for(1.0)
    return gross, cost, gross - cost


def buy_and_hold_baseline(
    *, entry_price: float, exit_price: float, cost_model: CostModel
) -> BaselineOutcome:
    """B — long the same asset over the exact same window as the decision."""
    gross, cost, net = _long_only_net(entry_price=entry_price, exit_price=exit_price, cost_model=cost_model)
    return BaselineOutcome(
        baseline_id=BASELINE_ID_BUY_AND_HOLD,
        evaluator_label=EVALUATOR_LABELS[BASELINE_ID_BUY_AND_HOLD],
        available=True,
        exposure=1.0,
        gross_return=gross,
        cost=cost,
        net_return=net,
    )


def simple_trend_baseline(
    *,
    daily_bars: Sequence[DailyBar],
    decision_time: int,
    entry_price: float,
    exit_price: float,
    cost_model: CostModel,
    bar_seconds: int = 86_400,
) -> BaselineOutcome:
    """C — the frozen RFC-039 rule ``close > SMA(200)`` -> LONG else CASH.

    The signal is frozen from completed daily bars known at ``decision_time``.
    With fewer than ``SMA_WINDOW`` completed observations (or any ``None`` SMA)
    the baseline is ``BASELINE_UNAVAILABLE`` — never a shorter average.
    """
    closes = completed_daily_closes(daily_bars, decision_time=decision_time, bar_seconds=bar_seconds)
    if len(closes) < SMA_WINDOW:
        return _unavailable(BASELINE_ID_SIMPLE_TREND, INSUFFICIENT_SMA200_HISTORY)
    values: list[float | None] = [float(close) for close in closes]
    average = sma(values, SMA_WINDOW)[-1]
    if average is None:
        return _unavailable(BASELINE_ID_SIMPLE_TREND, INSUFFICIENT_SMA200_HISTORY)
    if closes[-1] <= average:
        return BaselineOutcome(
            baseline_id=BASELINE_ID_SIMPLE_TREND,
            evaluator_label=EVALUATOR_LABELS[BASELINE_ID_SIMPLE_TREND],
            available=True,
            exposure=0.0,
            gross_return=0.0,
            cost=0.0,
            net_return=0.0,
            reason="SIGNAL_CASH",
        )
    gross, cost, net = _long_only_net(entry_price=entry_price, exit_price=exit_price, cost_model=cost_model)
    return BaselineOutcome(
        baseline_id=BASELINE_ID_SIMPLE_TREND,
        evaluator_label=EVALUATOR_LABELS[BASELINE_ID_SIMPLE_TREND],
        available=True,
        exposure=1.0,
        gross_return=gross,
        cost=cost,
        net_return=net,
        reason="SIGNAL_LONG",
    )


def passive_benchmark_equals_buy_and_hold(*, asset: str, mapping: Mapping[str, str] | None) -> bool:
    """True when the predeclared benchmark for ``asset`` *is* the asset itself."""
    if not mapping:
        return False
    target = mapping.get(asset)
    return target is not None and target.strip() == asset.strip()


def passive_benchmark_baseline(
    *,
    asset: str,
    entry_price: float | None,
    exit_price: float | None,
    cost_model: CostModel,
    mapping: Mapping[str, str] | None = None,
) -> BaselineOutcome:
    """D — passive benchmark only when a canonical mapping was predeclared.

    With no predeclared mapping (the frozen repository declares none) the
    baseline is ``BASELINE_UNAVAILABLE`` / ``NO_PREDECLARED_CANONICAL_MAPPING``.
    """
    resolved = CANONICAL_PASSIVE_BENCHMARK_MAPPING if mapping is None else mapping
    if not resolved or asset not in resolved:
        return _unavailable(BASELINE_ID_PASSIVE, NO_PREDECLARED_CANONICAL_MAPPING)
    if entry_price is None or exit_price is None:
        return _unavailable(BASELINE_ID_PASSIVE, "BENCHMARK_PRICES_MISSING")
    gross, cost, net = _long_only_net(entry_price=entry_price, exit_price=exit_price, cost_model=cost_model)
    return BaselineOutcome(
        baseline_id=BASELINE_ID_PASSIVE,
        evaluator_label=EVALUATOR_LABELS[BASELINE_ID_PASSIVE],
        available=True,
        exposure=1.0,
        gross_return=gross,
        cost=cost,
        net_return=net,
        reason=f"BENCHMARK={resolved[asset]}",
        economically_equivalent=passive_benchmark_equals_buy_and_hold(asset=asset, mapping=resolved),
    )


# --------------------------------------------------------------------------- #
# §5 — the agent's own outcome and its excursions
# --------------------------------------------------------------------------- #


def directional_gross_return(*, direction: str, entry_price: float, exit_price: float) -> float:
    if direction not in ac.DIRECTIONS:
        raise ValueError(f"direction must be one of {ac.DIRECTIONS}, got {direction!r}")
    if entry_price <= 0.0 or exit_price <= 0.0:
        raise ValueError("entry and exit prices must be positive")
    move = exit_price / entry_price - 1.0
    if direction == "LONG":
        return move
    if direction == "SHORT":
        return -move
    return 0.0


def excursion(*, direction: str, entry_price: float, path: Sequence[float]) -> tuple[float, float]:
    """``(MFE, MAE)`` as signed fractions of entry, respecting direction."""
    if direction not in ac.DIRECTIONS:
        raise ValueError(f"direction must be one of {ac.DIRECTIONS}, got {direction!r}")
    if entry_price <= 0.0:
        raise ValueError("entry_price must be positive")
    if direction == "NO_TRADE":
        return 0.0, 0.0
    prices = [entry_price, *(float(point) for point in path)]
    moves = [price / entry_price - 1.0 for price in prices]
    if direction == "SHORT":
        moves = [-move for move in moves]
    return max(moves), min(moves)


# --------------------------------------------------------------------------- #
# §6 — the separate outcome artifact (never mutates the sealed decision)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class OutcomeRecord:
    """Future-only record; links back to the seal by id + hash, adds nothing."""

    decision_id: str
    decision_hash: str
    asset: str
    evaluation_time: int
    entry_reference: float
    exit_reference: float
    gross_return: float
    costs: float
    net_return: float
    mfe: float
    mae: float
    baseline_outcomes: tuple[BaselineOutcome, ...]
    incremental_edges: tuple[dict[str, Any], ...]
    source: str
    llm_invoked: bool
    real_market_data: bool
    agent_decision_real: bool
    counts_toward_pilot: bool

    def to_dict(self) -> dict[str, Any]:
        return dict(asdict(self))

    def edge_by_id(self, baseline_id: str) -> dict[str, Any] | None:
        for edge in self.incremental_edges:
            if edge["baseline_id"] == baseline_id:
                return edge
        return None


def decision_id_for(record: ac.DecisionRecord) -> str:
    """Deterministic id derived from the seal — the record itself is untouched."""
    if not record.decision_hash:
        raise ValueError("cannot derive a decision_id from an unsealed record")
    return "DEC-" + record.decision_hash[:16]


def _edge_payload(edge: ac.IncrementalEdge, baseline_id: str) -> dict[str, Any]:
    return {
        "baseline_id": baseline_id,
        "evaluator_label": edge.baseline,
        "agent_outcome": edge.agent_outcome,
        "baseline_outcome": edge.baseline_outcome,
        "cost": edge.cost,
        "edge": edge.edge,
        "positive": edge.positive,
    }


def build_outcome_record(
    *,
    record: ac.DecisionRecord,
    asset: str,
    evaluation_time: int,
    entry_reference: float,
    exit_reference: float,
    cost_model: CostModel = DEFAULT_COST_MODEL,
    path: Sequence[float] = (),
    daily_bars: Sequence[DailyBar] = (),
    bar_seconds: int = 86_400,
    baseline_mapping: Mapping[str, str] | None = None,
    benchmark_entry_price: float | None = None,
    benchmark_exit_price: float | None = None,
    source: str = "SYNTHETIC_FIXTURE",
    llm_invoked: bool = False,
    real_market_data: bool = False,
    agent_decision_real: bool = False,
    counts_toward_pilot: bool = False,
) -> OutcomeRecord:
    """Assemble the future outcome for a *sealed* decision.

    ``decision_time`` is ``record.timestamp`` (the seal's own time), so the
    trend signal is frozen from bars known at the decision, not after it.  The
    record is read, never written.
    """
    if not record.is_verified():
        raise ValueError("refusing to score an unsealed or tampered decision record")
    direction = record.decision
    gross = directional_gross_return(
        direction=direction, entry_price=entry_reference, exit_price=exit_reference
    )
    cost = 0.0 if direction == "NO_TRADE" else cost_model.cost_for(1.0)
    net = gross - cost
    mfe, mae = excursion(direction=direction, entry_price=entry_reference, path=path)

    baselines: list[BaselineOutcome] = [
        cash_baseline(),
        buy_and_hold_baseline(
            entry_price=entry_reference, exit_price=exit_reference, cost_model=cost_model
        ),
        simple_trend_baseline(
            daily_bars=daily_bars,
            decision_time=record.timestamp,
            entry_price=entry_reference,
            exit_price=exit_reference,
            cost_model=cost_model,
            bar_seconds=bar_seconds,
        ),
        passive_benchmark_baseline(
            asset=asset,
            entry_price=benchmark_entry_price,
            exit_price=benchmark_exit_price,
            cost_model=cost_model,
            mapping=baseline_mapping,
        ),
    ]

    edges: list[dict[str, Any]] = []
    for baseline in baselines:
        if not baseline.available:
            continue
        edge = ac.incremental_edge(
            agent_outcome=net,
            baseline_outcome=baseline.net_return,
            cost=0.0,
            baseline=baseline.evaluator_label,
        )
        edges.append(_edge_payload(edge, baseline.baseline_id))

    return OutcomeRecord(
        decision_id=decision_id_for(record),
        decision_hash=record.decision_hash,
        asset=asset,
        evaluation_time=evaluation_time,
        entry_reference=entry_reference,
        exit_reference=exit_reference,
        gross_return=gross,
        costs=cost,
        net_return=net,
        mfe=mfe,
        mae=mae,
        baseline_outcomes=tuple(baselines),
        incremental_edges=tuple(edges),
        source=source,
        llm_invoked=llm_invoked,
        real_market_data=real_market_data,
        agent_decision_real=agent_decision_real,
        counts_toward_pilot=counts_toward_pilot,
    )
