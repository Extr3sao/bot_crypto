"""CAP-003 — ALPHA_SCORECARD: does the analyst beat its comparators, or not?

Two decisions prove nothing.  This module aggregates a whole campaign of
evaluated decisions into one honest answer, and it is deliberately hard to
mistake for a profitability claim:

* it reports the analyst's own expectancy, hit rate, profit factor, drawdown and
  confidence calibration;
* it reports the *incremental* edge against comparison B (frozen deterministic
  rule), C (buy-and-hold) and D (random direction with the analyst's own
  distribution);
* it refuses to conclude anything below a declared sample floor.  Under 100
  evaluable decisions the verdict is a sample-size verdict, never an edge
  verdict;
* it always carries ``alpha_claimed = False`` and
  ``profitability_status = NOT_DEMONSTRATED``.  A positive preliminary edge is
  a reason to run out-of-sample work, never a business result.

``NO_TRADE`` is a real decision and counts toward the sample, exactly as the
campaign contract requires.  It is excluded only from direction-based metrics
(hit rate, calibration), where it is meaningless.

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from trading_bot.research import agentic_baselines as ab
from trading_bot.research import agentic_contracts as ac
from trading_bot.research import decision_outcomes as do

__all__ = [
    "ALPHA_SCORECARD_ID",
    "CHECKPOINTS",
    "CONCLUSION_EDGE_NON_POSITIVE",
    "CONCLUSION_EDGE_POSITIVE_PRELIMINARY",
    "CONCLUSION_INSUFFICIENT_SAMPLE",
    "CONCLUSION_NOT_MEASURABLE",
    "G_AGENTIC_EDGE",
    "MIN_EVALUABLE_DECISIONS",
    "MIN_PRELIMINARY_DECISIONS",
    "RANDOM_BASELINE_SEED",
    "alpha_scorecard",
]

ALPHA_SCORECARD_ID = "ALPHA_SCORECARD"
G_AGENTIC_EDGE = "G_AGENTIC_EDGE"

#: The campaign contract: 100-300 evaluable decisions, scored at checkpoints.
MIN_EVALUABLE_DECISIONS = 100
MIN_PRELIMINARY_DECISIONS = 20
CHECKPOINTS: tuple[int, ...] = (20, 50, 100)

#: Frozen seed for comparator D, so a given evaluated set always yields the same
#: random assignment.
RANDOM_BASELINE_SEED = 20_261_003

CONCLUSION_NOT_MEASURABLE = "EDGE_NOT_MEASURABLE_NO_EVALUABLE_DECISIONS"
CONCLUSION_INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE_NO_EDGE_VERDICT"
CONCLUSION_EDGE_NON_POSITIVE = "EDGE_NON_POSITIVE"
CONCLUSION_EDGE_POSITIVE_PRELIMINARY = "EDGE_POSITIVE_PRELIMINARY_ONLY"

GATE_STATUSES = {
    CONCLUSION_NOT_MEASURABLE: "NOT_TESTED",
    CONCLUSION_INSUFFICIENT_SAMPLE: "INSUFFICIENT_SAMPLE",
    CONCLUSION_EDGE_NON_POSITIVE: "NON_POSITIVE",
    CONCLUSION_EDGE_POSITIVE_PRELIMINARY: "PRELIMINARY_POSITIVE",
}


def _mean(values: Sequence[float]) -> float | None:
    return ac.expectancy(values) if values else None


def _checkpoint_reached(count: int) -> int:
    reached = [point for point in CHECKPOINTS if count >= point]
    return max(reached) if reached else 0


def _next_checkpoint(count: int) -> int | None:
    remaining = [point for point in CHECKPOINTS if count < point]
    return min(remaining) if remaining else None


def _equity_curve(performances: Sequence[do.DecisionPerformance]) -> list[float]:
    ordered = sorted(performances, key=lambda item: (item.evaluation_time, item.decision_id))
    equity = [1.0]
    for item in ordered:
        equity.append(equity[-1] * (1.0 + item.net_return))
    return equity


def _comparator_stats(
    performances: Sequence[do.DecisionPerformance], baseline_id: str
) -> dict[str, Any]:
    values: list[float] = []
    for item in performances:
        comparison = item.comparison(baseline_id)
        if comparison is None or not comparison.available:
            continue
        values.append(comparison.net_return)
    return {
        "baseline_id": baseline_id,
        "n": len(values),
        "net_returns": values,
        "mean_net_return": _mean(values),
    }


def _random_comparator(
    performances: Sequence[do.DecisionPerformance], *, seed: int
) -> dict[str, Any]:
    directions = [item.decision for item in performances]
    assigned = do.matched_random_directions(directions, seed=seed)
    values: list[float] = []
    for item, direction in zip(performances, assigned, strict=True):
        _gross, _costs, net = do.sleeve_outcome(
            direction=direction,
            entry_price=item.entry_price,
            exit_price=item.exit_price,
            cost_model=ab.CostModel(fee_bps_per_side=item.cost_bps_per_side),
        )
        values.append(net)
    return {
        "baseline_id": do.BASELINE_ID_RANDOM_MATCHED,
        "n": len(values),
        "seed": seed,
        "assignment": list(assigned),
        "assignment_digest": ac.payload_digest(list(assigned)),
        "distribution": do.direction_distribution(assigned),
        "net_returns": values,
        "mean_net_return": _mean(values),
    }


def _edge(agent_mean: float | None, comparator_mean: float | None) -> float | None:
    if agent_mean is None or comparator_mean is None:
        return None
    return agent_mean - comparator_mean


def alpha_scorecard(
    performances: Sequence[do.DecisionPerformance], *, random_seed: int = RANDOM_BASELINE_SEED
) -> dict[str, Any]:
    """Aggregate the evaluated campaign into a single, honest verdict."""
    n = len(performances)
    net_returns = [item.net_return for item in performances]
    directional = [item for item in performances if item.decision != "NO_TRADE"]
    directional_returns = [item.net_return for item in directional]

    agent_mean = _mean(net_returns)
    hit_rate = ac.hit_rate(directional_returns) if directional_returns else None
    profit_factor = ac.profit_factor(net_returns) if net_returns else None
    drawdown = ac.max_drawdown(_equity_curve(performances)) if performances else None
    calibration = (
        ac.brier_score([(item.confidence, item.direction_correct) for item in directional])
        if directional
        else None
    )

    b_stats = _comparator_stats(performances, do.BASELINE_ID_DETERMINISTIC)
    c_stats = _comparator_stats(performances, do.BASELINE_ID_BUY_AND_HOLD)
    d_stats = _random_comparator(performances, seed=random_seed) if performances else None

    edges = {
        do.BASELINE_ID_DETERMINISTIC: _edge(agent_mean, b_stats["mean_net_return"]),
        do.BASELINE_ID_BUY_AND_HOLD: _edge(agent_mean, c_stats["mean_net_return"]),
    }
    if d_stats is not None:
        edges[do.BASELINE_ID_RANDOM_MATCHED] = _edge(agent_mean, d_stats["mean_net_return"])

    if n == 0:
        conclusion = CONCLUSION_NOT_MEASURABLE
    elif n < MIN_EVALUABLE_DECISIONS:
        conclusion = CONCLUSION_INSUFFICIENT_SAMPLE
    else:
        computed = [value for value in edges.values() if value is not None]
        positive = bool(computed) and all(value > 0.0 for value in computed)
        conclusion = (
            CONCLUSION_EDGE_POSITIVE_PRELIMINARY if positive else CONCLUSION_EDGE_NON_POSITIVE
        )

    no_trade = [item for item in performances if item.decision == "NO_TRADE"]
    no_trade_counterfactual = [
        value
        for value in (item.comparison(do.BASELINE_ID_BUY_AND_HOLD) for item in no_trade)
        if value is not None and value.available
    ]

    per_asset: dict[str, dict[str, Any]] = {}
    for item in performances:
        bucket = per_asset.setdefault(item.asset, {"n": 0, "net_returns": []})
        bucket["n"] += 1
        bucket["net_returns"].append(item.net_return)
    for bucket in per_asset.values():
        bucket["mean_net_return"] = _mean(bucket["net_returns"])

    per_horizon: dict[str, dict[str, Any]] = {}
    for item in performances:
        bucket = per_horizon.setdefault(item.horizon, {"n": 0, "net_returns": []})
        bucket["n"] += 1
        bucket["net_returns"].append(item.net_return)
    for bucket in per_horizon.values():
        bucket["mean_net_return"] = _mean(bucket["net_returns"])

    return {
        "scorecard": ALPHA_SCORECARD_ID,
        "campaign": "CAP-003 REAL DECISION OUTCOME & ALPHA EVALUATION",
        "n_decisions_evaluated": n,
        "n_directional": len(directional),
        "n_no_trade": len(no_trade),
        "action_rate": (len(directional) / n) if n else None,
        "horizons": do.HORIZON_SECONDS,
        "agent": {
            "id": do.AGENT_ID,
            "mean_net_return": agent_mean,
            "hit_rate_directional": hit_rate,
            "profit_factor": profit_factor,
            "max_drawdown": drawdown,
            "brier_score_directional": calibration,
            "net_returns": net_returns,
        },
        "comparators": {
            do.BASELINE_ID_DETERMINISTIC: b_stats,
            do.BASELINE_ID_BUY_AND_HOLD: c_stats,
            do.BASELINE_ID_RANDOM_MATCHED: d_stats,
        },
        "incremental_edges": edges,
        "direction_distribution": do.direction_distribution(
            [item.decision for item in performances]
        )
        if performances
        else {direction: 0 for direction in ac.DIRECTIONS},
        "no_trade": {
            "n": len(no_trade),
            "mean_buy_and_hold_net_return_in_those_windows": _mean(
                [value.net_return for value in no_trade_counterfactual]
            ),
        },
        "per_asset": per_asset,
        "per_horizon": per_horizon,
        "sample": {
            "min_evaluable_decisions": MIN_EVALUABLE_DECISIONS,
            "min_preliminary_decisions": MIN_PRELIMINARY_DECISIONS,
            "checkpoints": list(CHECKPOINTS),
            "checkpoint_reached": _checkpoint_reached(n),
            "next_checkpoint": _next_checkpoint(n),
        },
        "gate": {
            "name": G_AGENTIC_EDGE,
            "status": GATE_STATUSES[conclusion],
            "conclusion": conclusion,
        },
        "alpha_claimed": False,
        "kpi_agentic_decision_edge": ac.KPI_VALUES["AGENTIC_DECISION_EDGE"],
        "profitability_status": "NOT_DEMONSTRATED",
        "business_evidence": False,
        "next_step": (
            "accumulate evaluated decisions to the declared sample floor with the frozen "
            "analyst; only then run out-of-sample and robustness work"
            if conclusion != CONCLUSION_EDGE_POSITIVE_PRELIMINARY
            else "preliminary positive edge: run out-of-sample and robustness work before any claim"
        ),
    }
