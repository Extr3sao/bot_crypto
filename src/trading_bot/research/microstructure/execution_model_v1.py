"""EXECUTION_MODEL_V1 — taker vs maker execution semantics (research-only).

§PHASE 3. The point of this module is to stop the analysis from pretending that

    market order  ==  limit order  ==  free fill.

A *taker* intent is (nearly) deterministic: given the observed spread and a
size/liquidity regime, the order crosses and pays fee + half-spread + slippage.
A *maker* intent is a *distribution*: it may fill, partially fill, or never
fill; if it fills it may be adversely selected. Modelling a maker strategy with
the taker number is the single most common way a backtest lies to itself, so
the two live in different classes and the maker side refuses to emit a single
scalar without an explicit fill model.

Evidence discipline: every parameter here is ``ASSUMED`` unless a caller passes
a measured ``FillEvidence``. A synthetic scenario is allowed but must be
labelled ``SYNTHETIC_STRESS_TEST`` and can never be the basis of admission.

RESEARCH_ONLY. Not wired to any runtime path (§44).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

__all__ = [
    "EXECUTION_MODEL_VERSION",
    "ExecutionModelStatus",
    "ExecutionOutcome",
    "FillEvidence",
    "MakerExecutionModel",
    "SyntheticMakerScenario",
    "TakerExecutionModel",
]

EXECUTION_MODEL_VERSION = "EXECUTION_MODEL_V1"

ExecutionModelStatus = Literal[
    "EVIDENCE_BACKED",
    "EXECUTION_MODEL_REQUIRED",
    "SYNTHETIC_STRESS_TEST",
]

_T123 = 1.0 / 3.0


def _nn(value: float, name: str) -> None:
    if value < 0.0:
        raise ValueError(f"{name} must be >= 0, got {value}")


def _prob(value: float, name: str) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be in [0, 1], got {value}")


# ---------------------------------------------------------------------------
# Taker
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TakerExecutionModel:
    """Deterministic crossing model.

    ``slippage_bps`` is the expected adverse move *beyond* the quoted top of
    book; it is separate from the half-spread, which is the price of crossing
    at all. ``participation_rate`` caps how much of the visible size a single
    order may take before it walks the book; when the requested size exceeds
    the cap the model reports an extra ``book_walk_bps`` term.
    """

    base_slippage_bps: float = 1.0
    half_spread_bps: float = 0.5
    participation_rate: float = 0.10
    books_per_level_bps: float = 0.5

    def __post_init__(self) -> None:
        _nn(self.base_slippage_bps, "base_slippage_bps")
        _nn(self.half_spread_bps, "half_spread_bps")
        if not 0.0 < self.participation_rate <= 1.0:
            raise ValueError("participation_rate must be in (0, 1]")
        _nn(self.books_per_level_bps, "books_per_level_bps")

    def book_walk_bps(self, size_usd: float, visible_notional_usd: float) -> float:
        """Extra cost from walking past the top of book."""
        _nn(size_usd, "size_usd")
        if visible_notional_usd <= 0.0:
            raise ValueError("visible_notional_usd must be > 0")
        capacity = visible_notional_usd * self.participation_rate
        if size_usd <= capacity:
            return 0.0
        levels = math.ceil(size_usd / capacity) - 1
        return levels * self.books_per_level_bps

    def round_trip_cost_bps(
        self,
        fee_bps_per_side: float,
        size_usd: float = 1_000.0,
        visible_notional_usd: float = 50_000.0,
    ) -> float:
        _nn(fee_bps_per_side, "fee_bps_per_side")
        walk = self.book_walk_bps(size_usd, visible_notional_usd)
        per_side = fee_bps_per_side + self.half_spread_bps + self.base_slippage_bps + walk
        return 2.0 * per_side

    def as_dict(self) -> dict[str, float | str]:
        return {
            "model": EXECUTION_MODEL_VERSION,
            "kind": "TAKER",
            "base_slippage_bps": self.base_slippage_bps,
            "half_spread_bps": self.half_spread_bps,
            "participation_rate": self.participation_rate,
            "books_per_level_bps": self.books_per_level_bps,
            "status": "EVIDENCE_BACKED",
        }


# ---------------------------------------------------------------------------
# Maker
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FillEvidence:
    """Measured fill statistics. Only a forward collector can produce this.

    All fields are optional: an empty ``FillEvidence`` means "no evidence", and
    the maker model will report ``EXECUTION_MODEL_REQUIRED`` instead of a
    number.
    """

    n_orders: int = 0
    fill_rate: float | None = None
    partial_fill_rate: float | None = None
    median_time_to_fill_ms: int | None = None
    adverse_move_after_fill_bps: float | None = None
    source: str = ""

    @property
    def is_usable(self) -> bool:
        return (
            self.n_orders > 0
            and self.fill_rate is not None
            and self.adverse_move_after_fill_bps is not None
        )

    def __post_init__(self) -> None:
        if self.n_orders < 0:
            raise ValueError("n_orders must be >= 0")
        if self.fill_rate is not None:
            _prob(self.fill_rate, "fill_rate")
        if self.partial_fill_rate is not None:
            _prob(self.partial_fill_rate, "partial_fill_rate")
        if self.median_time_to_fill_ms is not None and self.median_time_to_fill_ms < 0:
            raise ValueError("median_time_to_fill_ms must be >= 0")


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    """Distributional result of a maker intent."""

    prob_filled: float
    prob_partial: float
    prob_missed: float
    expected_effective_cost_bps: float | None
    expected_slippage_bps: float | None
    adverse_selection_bps: float | None
    status: ExecutionModelStatus
    notes: str = ""

    def __post_init__(self) -> None:
        for name in ("prob_filled", "prob_partial", "prob_missed"):
            _prob(getattr(self, name), name)
        total = self.prob_filled + self.prob_partial + self.prob_missed
        if not 0.99 <= total <= 1.01:
            raise ValueError(f"fill probabilities must sum to 1, got {total}")

    def as_dict(self) -> dict[str, object]:
        return {
            "prob_filled": round(self.prob_filled, 4),
            "prob_partial": round(self.prob_partial, 4),
            "prob_missed": round(self.prob_missed, 4),
            "expected_effective_cost_bps": (
                None
                if self.expected_effective_cost_bps is None
                else round(self.expected_effective_cost_bps, 4)
            ),
            "expected_slippage_bps": (
                None if self.expected_slippage_bps is None else round(self.expected_slippage_bps, 4)
            ),
            "adverse_selection_bps": (
                None if self.adverse_selection_bps is None else round(self.adverse_selection_bps, 4)
            ),
            "status": self.status,
            "notes": self.notes,
        }


@dataclass(frozen=True, slots=True)
class SyntheticMakerScenario:
    """A labelled synthetic maker scenario.

    Anything produced through this class is ``SYNTHETIC_STRESS_TEST`` and is
    explicitly barred from admission. It exists to bound a cost envelope, not
    to demonstrate an edge.
    """

    fill_prob: float
    partial_prob: float
    missed_opportunity_cost_bps: float
    adverse_selection_bps: float
    label: str = "SYNTHETIC_STRESS_TEST"

    def __post_init__(self) -> None:
        _prob(self.fill_prob, "fill_prob")
        _prob(self.partial_prob, "partial_prob")
        _nn(self.missed_opportunity_cost_bps, "missed_opportunity_cost_bps")
        _nn(self.adverse_selection_bps, "adverse_selection_bps")
        if self.label != "SYNTHETIC_STRESS_TEST":
            raise ValueError("synthetic scenarios must be labelled SYNTHETIC_STRESS_TEST")


@dataclass(frozen=True, slots=True)
class MakerExecutionModel:
    """Maker cost as a function of fill evidence, never a free lunch.

    effective cost (bps) =
        fee + spread_earned_credit? NO.
        fee
      + adverse_selection_after_fill * p_filled
      + missed_opportunity * p_missed
      + requote/queue penalty * (attempts)

    We deliberately do NOT credit the maker with capturing the spread: a
    passive order that fills is, by construction, one that was hit, and the
    empirical adverse move after such a fill is the real counterpart. Crediting
    spread capture without modelling adverse selection is how a maker backtest
    manufactures an edge out of nothing.
    """

    maker_fee_bps: float
    maker_rebate_bps: float = 0.0
    requote_penalty_bps: float = 0.1
    nominal_fill_prob: float = 0.5

    def __post_init__(self) -> None:
        _nn(self.maker_fee_bps, "maker_fee_bps")
        _nn(self.requote_penalty_bps, "requote_penalty_bps")
        _prob(self.nominal_fill_prob, "nominal_fill_prob")
        if self.maker_rebate_bps > 0.0:
            raise ValueError(
                "maker rebates are not modelled as a baseline (§7); "
                "a published 0% maker fee is expressed as maker_fee_bps=0"
            )

    def evaluate(self, evidence: FillEvidence) -> ExecutionOutcome:
        if not evidence.is_usable:
            return ExecutionOutcome(
                prob_filled=0.0,
                prob_partial=0.0,
                prob_missed=1.0,
                expected_effective_cost_bps=None,
                expected_slippage_bps=None,
                adverse_selection_bps=None,
                status="EXECUTION_MODEL_REQUIRED",
                notes=(
                    "no usable fill evidence (needs a forward collection of "
                    "fill_rate + adverse_move_after_fill_bps)"
                ),
            )
        assert evidence.fill_rate is not None
        assert evidence.adverse_move_after_fill_bps is not None
        assert evidence.partial_fill_rate is not None or evidence.partial_fill_rate is None

        p_full = evidence.fill_rate
        p_part = (evidence.partial_fill_rate or 0.0) * (1.0 - p_full)
        p_miss = max(0.0, 1.0 - p_full - p_part)
        adverse = evidence.adverse_move_after_fill_bps
        missed = adverse  # proxy: a missed fill forgoes a move of the same scale
        eff = (
            self.maker_fee_bps
            + adverse * (p_full + _T123 * p_part)
            + missed * p_miss
            + self.requote_penalty_bps
        )
        return ExecutionOutcome(
            prob_filled=p_full,
            prob_partial=p_part,
            prob_missed=p_miss,
            expected_effective_cost_bps=eff,
            expected_slippage_bps=adverse,
            adverse_selection_bps=adverse,
            status="EVIDENCE_BACKED",
            notes=f"evidence from {evidence.source or 'unspecified'} (n={evidence.n_orders})",
        )

    def evaluate_synthetic(self, scenario: SyntheticMakerScenario) -> ExecutionOutcome:
        p_full = scenario.fill_prob
        p_part = scenario.partial_prob * (1.0 - p_full)
        p_miss = max(0.0, 1.0 - p_full - p_part)
        eff = (
            self.maker_fee_bps
            + scenario.adverse_selection_bps * (p_full + _T123 * p_part)
            + scenario.missed_opportunity_cost_bps * p_miss
            + self.requote_penalty_bps
        )
        return ExecutionOutcome(
            prob_filled=p_full,
            prob_partial=p_part,
            prob_missed=p_miss,
            expected_effective_cost_bps=eff,
            expected_slippage_bps=scenario.adverse_selection_bps,
            adverse_selection_bps=scenario.adverse_selection_bps,
            status="SYNTHETIC_STRESS_TEST",
            notes="not admissible evidence; bounds a cost envelope only",
        )

    def as_dict(self) -> dict[str, float | str]:
        return {
            "model": EXECUTION_MODEL_VERSION,
            "kind": "MAKER",
            "maker_fee_bps": self.maker_fee_bps,
            "maker_rebate_bps": self.maker_rebate_bps,
            "requote_penalty_bps": self.requote_penalty_bps,
            "nominal_fill_prob": self.nominal_fill_prob,
            "status": "EXECUTION_MODEL_REQUIRED",
        }
