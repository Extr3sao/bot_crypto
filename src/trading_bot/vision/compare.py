"""compare — did the model add money, on the same book, under the same rules?

The comparison is deliberately narrow, because a wide one would be dishonest:

* same bars, same capital, same cost schedule, same ``RiskManager`` policy — the caller
  is responsible for that, and the inputs record it so a mismatch is visible;
* one number decides the headline: net realised USDT. Drawdown and trade count are
  reported because a strategy that loses less by trading almost never has not added
  value, it has added cash drag, and the reader should see that;
* no significance claim. One path through one dataset is an anecdote with arithmetic,
  and the verdict says so in the same sentence as the number.

A missing drawdown is ``UNKNOWN``, never zero.
"""

from __future__ import annotations

import math
from typing import Any

#: Below this, a difference is bookkeeping noise rather than an edge.
NOISE_USDT = 0.01

#: Inputs that must be identical before the arithmetic says anything about the model.
#: When a run summary carries one of these, the comparator checks it itself instead of
#: trusting the caller to remember: a forgotten flag used to be enough to publish
#: ``VISION_ADDS_VALUE`` over two runs that were never comparable.
COMPARABLE_INPUTS: tuple[str, ...] = (
    "symbols",
    "window",
    "cadence_ms",
    "bar_step_ms",
    "initial_capital_usdt",
    "cost_model",
    "fee_bps",
    "slippage_bps",
    "risk_policy",
)


def _normalise(value: Any) -> Any:
    """A stable shape for equality: sorted lists, rounded floats, verbatim objects."""
    if isinstance(value, float):
        return round(value, 9)
    if isinstance(value, (list, tuple)):
        return sorted(str(item) for item in value)
    if isinstance(value, dict):
        return {str(key): _normalise(item) for key, item in sorted(value.items())}
    return value


def _derived_mismatches(
    vision: dict[str, Any], baseline: dict[str, Any]
) -> list[str]:
    """Inputs the summaries state themselves and that do not match (or cannot be shown to)."""
    mismatches: list[str] = []
    for key in COMPARABLE_INPUTS:
        in_vision = key in vision
        in_baseline = key in baseline
        if not in_vision and not in_baseline:
            continue
        if in_vision != in_baseline:
            # Declared on one side only: sameness cannot be established.
            mismatches.append(key)
        elif _normalise(vision[key]) != _normalise(baseline[key]):
            mismatches.append(key)
    return mismatches


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _safe_div(numerator: float, denominator: float) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def comparison(
    vision: dict[str, Any],
    baseline: dict[str, Any],
    *,
    same_inputs: dict[str, bool] | None = None,
    caveats: list[str] | None = None,
) -> dict[str, Any]:
    """Compare two run summaries. Inputs must already be normalised to the same keys."""
    vision_net = _finite(vision.get("net_realised_usdt"))
    baseline_net = _finite(baseline.get("net_realised_usdt"))
    vision_fills = _finite(vision.get("fills")) or 0.0
    baseline_fills = _finite(baseline.get("fills")) or 0.0

    if vision_net is None or baseline_net is None:
        return {
            "verdict": "UNKNOWN",
            "reason": "one of the runs has no measurable net result",
            "vision": vision,
            "baseline": baseline,
        }

    delta = vision_net - baseline_net
    if abs(delta) < NOISE_USDT:
        arithmetic_verdict = "NO_MEASURABLE_DIFFERENCE"
    elif delta > 0:
        arithmetic_verdict = "VISION_ADDS_VALUE"
    else:
        arithmetic_verdict = "VISION_DESTROYS_VALUE"

    # A loss that is "better" only because it traded less is reported as such.
    per_trade_vision = _safe_div(vision_net, vision_fills) if vision_fills else None
    per_trade_baseline = _safe_div(baseline_net, baseline_fills) if baseline_fills else None

    flags: dict[str, bool] = dict(same_inputs or {})
    mismatch = sorted(
        set(key for key, value in flags.items() if not value)
        | set(_derived_mismatches(vision, baseline))
    )
    # NOT_COMPARABLE is the verdict, not a footnote: if the inputs differ, the delta is
    # arithmetic about two different experiments and cannot name a winner. It is still
    # reported, under ``arithmetic``, so nobody has to recompute it by hand.
    comparable = not mismatch
    verdict = arithmetic_verdict if comparable else "NOT_COMPARABLE"

    return {
        "verdict": verdict,
        "comparison_valid": comparable,
        "arithmetic": {
            "would_be_verdict": arithmetic_verdict,
            "delta_net_usdt": round(delta, 6),
        },
        "delta_net_usdt": round(delta, 6),
        "relative_delta_pct": (
            None
            if _safe_div(baseline_net, abs(baseline_net)) is None
            else round(delta / abs(baseline_net) * 100.0, 4)
            if baseline_net != 0
            else None
        ),
        "vision": {
            "fills": int(vision_fills),
            "net_realised_usdt": round(vision_net, 6),
            "net_per_trade_usdt": None if per_trade_vision is None else round(per_trade_vision, 6),
            "drawdown_pct": vision.get("drawdown_pct", "UNKNOWN"),
            "final_equity_usdt": vision.get("final_equity_usdt"),
            "decisions": vision.get("decisions"),
            "estimated_spend_usd": vision.get("estimated_spend_usd"),
        },
        "baseline": {
            "fills": int(baseline_fills),
            "net_realised_usdt": round(baseline_net, 6),
            "net_per_trade_usdt": (
                None if per_trade_baseline is None else round(per_trade_baseline, 6)
            ),
            "drawdown_pct": baseline.get("drawdown_pct", "UNKNOWN"),
        },
        "inputs_match": not mismatch,
        "input_mismatches": mismatch,
        "caveats": [
            *(caveats or []),
            "one realisation on one dataset: this is arithmetic, not a significance test",
            "the model was charged the same venue cost schedule as the deterministic lane",
        ],
        "reading": _reading(verdict, delta, vision_fills, baseline_fills, mismatch),
    }


def _reading(
    verdict: str, delta: float, vision_fills: float, baseline_fills: float, mismatch: list[str]
) -> str:
    if mismatch:
        return (
            "NOT_A_COMPARISON: the runs differ in "
            + ", ".join(mismatch)
            + "; the arithmetic below is not evidence about the model"
        )
    if verdict == "VISION_ADDS_VALUE":
        return (
            f"the model finished {delta:+.2f} USDT better over the same window. "
            f"{int(vision_fills)} fills vs {int(baseline_fills)}. Treat as a hypothesis "
            "to test forward, not as an edge."
        )
    if verdict == "VISION_DESTROYS_VALUE":
        return (
            f"the model finished {delta:+.2f} USDT worse over the same window. "
            f"{int(vision_fills)} fills vs {int(baseline_fills)}. No restated edge."
        )
    if verdict == "NO_MEASURABLE_DIFFERENCE":
        return "the two books ended within bookkeeping noise of each other."
    return "no measurable net result on either side"
