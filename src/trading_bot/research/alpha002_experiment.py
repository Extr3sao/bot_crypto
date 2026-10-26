"""ALPHA-002 — the frozen development experiment over the derivatives feature rows.

This module is the honest half of the campaign.  The preregistration
(``alpha002.PREREGISTRATION``) says *what* the hypotheses are; this module says
*how they are measured*, and it is written so that the measurement cannot flatter
the hypothesis:

* **The rule is applied, not re-derived.**  The traded directions come from
  ``alpha002.SIGNALS`` verbatim.  The ablations are separately written reductions
  of the same rule and a test asserts that the full ablation reproduces the frozen
  signal exactly, so a drifting ablation is a test failure rather than a finding.
* **A missing source is not a trade.**  A row where a required feature is absent is
  dropped for that signal and counted, never imputed.
* **Multiplicity is frozen.**  Benjamini-Hochberg at q = 0.10 and Holm at
  alpha = 0.10 across the three preregistered hypotheses, plus a best-of-three
  circular-shift permutation null.  The corrections are named here, not chosen
  after seeing the numbers.
* **Incremental value is the question.**  Every hypothesis is measured against the
  *same rule with the derivatives confirmation removed*, because "the strategy made
  money" is not the question — "did the participant data add anything" is.
* **NO_ALPHA is a result.**  Nothing in this module rewards a positive number.

Statistics are imported from ``alpha001``: one implementation, one behaviour.

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from trading_bot.research import alpha001 as a1
from trading_bot.research import alpha002
from trading_bot.research import alpha002_features as af

__all__ = [
    "ABLATIONS",
    "BASELINES",
    "BH_Q",
    "DESIGN_SIGMA_BPS",
    "DISCOVERY_FRACTION",
    "HOLDOUT_FRACTION",
    "HOLM_ALPHA",
    "NULL_DRAWS",
    "NULL_SEED",
    "STABILITY_WINDOWS",
    "VALIDATION_FRACTION",
    "ablation_direction",
    "calendar_boundaries",
    "evaluate_directions",
    "in_window",
    "nontraded_flag",
    "permutation_null",
    "preregistered_direction",
    "promotion_gate",
]

#: The design assumption used to derive the hurdle *before* any result is seen.
#: Identical to ALPHA-001's: a conservative per-decision gross sigma, never the
#: realised dispersion (which would let the data set its own bar).
DESIGN_SIGMA_BPS = 400.0

#: Permutation draws for the selection null.
NULL_DRAWS = 1000
NULL_SEED = 20_261_007

#: Multiplicity settings, frozen by the preregistration text.
BH_Q = 0.10
HOLM_ALPHA = 0.10

#: Split fractions, identical to the frozen preregistration.
DISCOVERY_FRACTION = 0.60
VALIDATION_FRACTION = 0.20
HOLDOUT_FRACTION = 0.20

STABILITY_WINDOWS = 4


# --------------------------------------------------------------------------- #
# §1 — splits
# --------------------------------------------------------------------------- #


def calendar_boundaries(
    start_ms: int,
    end_ms: int,
    *,
    discovery_fraction: float = DISCOVERY_FRACTION,
    validation_fraction: float = VALIDATION_FRACTION,
) -> dict[str, tuple[int, int]]:
    """A single calendar split shared by every asset and every timeframe.

    Half-open intervals ``[lo, hi)``.  The holdout is the final slice and is never
    read by development.
    """
    if end_ms <= start_ms:
        raise ValueError("end_ms must be > start_ms")
    span = end_ms - start_ms
    discovery_end = start_ms + round(span * discovery_fraction)
    validation_end = start_ms + round(span * (discovery_fraction + validation_fraction))
    return {
        "discovery": (start_ms, discovery_end),
        "validation": (discovery_end, validation_end),
        "holdout": (validation_end, end_ms + 1),
    }


def in_window(decision_ms: int, window: tuple[int, int]) -> bool:
    """Half-open membership test: ``window[0] <= decision_ms < window[1]``."""
    return window[0] <= decision_ms < window[1]


def _in_window(decision_ms: int, window: tuple[int, int]) -> bool:
    return window[0] <= decision_ms < window[1]


# --------------------------------------------------------------------------- #
# §2 — directions: the frozen rule, the non-traded arms, the ablations
# --------------------------------------------------------------------------- #


def _eligible(row: Mapping[str, Any], required: Sequence[str]) -> bool:
    return all(row.get(name) is not None for name in required)


def preregistered_direction(hypothesis_id: str, row: Mapping[str, Any]) -> int | None:
    """The frozen signal, or ``None`` when a required source is missing."""
    required = af.REQUIRED_FEATURES[hypothesis_id]
    if not _eligible(row, required):
        return None
    signal = alpha002.SIGNALS.get(hypothesis_id)
    if signal is None:
        raise KeyError(f"{hypothesis_id} is not a traded hypothesis")
    return int(signal(row))


def nontraded_flag(arm_id: str, row: Mapping[str, Any]) -> bool | None:
    """The declared comparator arms.  Reported, never traded."""
    required = af.REQUIRED_FEATURES[arm_id]
    if not _eligible(row, required):
        return None
    predicate = alpha002.NON_TRADED_ARMS[arm_id]
    return bool(predicate(row))


# -- ablations (attribution only; never used to promote a candidate) ---------- #

_T = alpha002.THRESHOLDS


def _h1_price_only(row: Mapping[str, Any]) -> int | None:
    if not _eligible(row, ("ret_z",)):
        return None
    return 1 if row["ret_z"] > _T["breakout_ret_z"] else 0


def _h1_price_oi(row: Mapping[str, Any]) -> int | None:
    if not _eligible(row, ("ret_z", "oi_chg")):
        return None
    if row["ret_z"] <= _T["breakout_ret_z"] or row["oi_chg"] <= _T["oi_expanding"]:
        return 0
    return 1


def _h1_price_taker(row: Mapping[str, Any]) -> int | None:
    if not _eligible(row, ("ret_z", "taker_imbalance")):
        return None
    if (
        row["ret_z"] <= _T["breakout_ret_z"]
        or row["taker_imbalance"] <= _T["taker_imbalance_confirm"]
    ):
        return 0
    return 1


def _h1_price_funding(row: Mapping[str, Any]) -> int | None:
    if not _eligible(row, ("ret_z", "funding")):
        return None
    if row["ret_z"] <= _T["breakout_ret_z"] or abs(row["funding"]) > _T["funding_extreme_abs"]:
        return 0
    return 1


def _h3_price_only(row: Mapping[str, Any]) -> int | None:
    if not _eligible(row, ("ret_z",)):
        return None
    if abs(row["ret_z"]) <= _T["breakout_ret_z"]:
        return 0
    return 1 if row["ret_z"] > 0 else -1


def _h3_price_oi(row: Mapping[str, Any]) -> int | None:
    if not _eligible(row, ("ret_z", "oi_chg")):
        return None
    if abs(row["ret_z"]) <= _T["breakout_ret_z"] or row["oi_chg"] <= _T["oi_expanding"]:
        return 0
    return 1 if row["ret_z"] > 0 else -1


def _h3_price_taker(row: Mapping[str, Any]) -> int | None:
    if not _eligible(row, ("ret_z", "taker_imbalance")):
        return None
    if abs(row["ret_z"]) <= _T["breakout_ret_z"]:
        return 0
    direction = 1 if row["ret_z"] > 0 else -1
    return direction if direction * row["taker_imbalance"] > _T["taker_imbalance_confirm"] else 0


def _h2_price_only(row: Mapping[str, Any]) -> int | None:
    if not _eligible(row, ("momentum_delta",)):
        return None
    return -1 if row["momentum_delta"] < _T["momentum_deteriorating"] else 0


def _h2_price_funding(row: Mapping[str, Any]) -> int | None:
    if not _eligible(row, ("momentum_delta", "funding")):
        return None
    if (
        row["momentum_delta"] >= _T["momentum_deteriorating"]
        or row["funding"] <= _T["funding_elevated"]
    ):
        return 0
    return -1


def _h2_price_positioning(row: Mapping[str, Any]) -> int | None:
    if not _eligible(row, ("momentum_delta", "ls_global_pctile", "ls_top_position_pctile")):
        return None
    crowding = max(row["ls_global_pctile"], row["ls_top_position_pctile"])
    if row["momentum_delta"] >= _T["momentum_deteriorating"] or crowding < _T["crowding_pctile"]:
        return 0
    return -1


#: ``hypothesis_id`` → ``{ablation label → direction builder}``.  ``FULL`` must
#: reproduce ``alpha002.SIGNALS`` exactly (a test enforces it).
ABLATIONS: dict[str, dict[str, Callable[[Mapping[str, Any]], int | None]]] = {
    "A2-H01": {
        "PRICE_ONLY": _h1_price_only,
        "PRICE+OI": _h1_price_oi,
        "PRICE+TAKER": _h1_price_taker,
        "PRICE+FUNDING": _h1_price_funding,
    },
    "A2-H03": {
        "PRICE_ONLY": _h3_price_only,
        "PRICE+OI": _h3_price_oi,
        "PRICE+TAKER": _h3_price_taker,
    },
    "A2-H02": {
        "PRICE_ONLY": _h2_price_only,
        "PRICE+FUNDING": _h2_price_funding,
        "PRICE+POSITIONING": _h2_price_positioning,
    },
}


def ablation_direction(hypothesis_id: str, label: str, row: Mapping[str, Any]) -> int | None:
    """Apply one ablation variant, or the frozen rule when ``label == 'FULL'``."""
    if label == "FULL":
        return preregistered_direction(hypothesis_id, row)
    return ABLATIONS[hypothesis_id][label](row)


# --------------------------------------------------------------------------- #
# §3 — baselines
# --------------------------------------------------------------------------- #


def _b0_unconditional(_row: Mapping[str, Any]) -> int:
    """B0 — always long.  The unconditional market return."""
    return 1


def _b3_momentum(_row: Mapping[str, Any]) -> int | None:
    """B3 — deterministic technical baseline: 1-bar momentum continuation."""
    if _row.get("ret_z") is None:
        return None
    if _row["ret_z"] == 0.0:
        return 0
    return 1 if _row["ret_z"] > 0 else -1


BASELINES: dict[str, Callable[[Mapping[str, Any]], int | None]] = {
    "B0_UNCONDITIONAL_LONG": _b0_unconditional,
    "B3_MOMENTUM_CONTINUATION": _b3_momentum,
}


# --------------------------------------------------------------------------- #
# §4 — the statistic on one arm
# --------------------------------------------------------------------------- #


def evaluate_directions(
    directions: Sequence[int | None],
    forward_returns: Sequence[float | None],
    *,
    hurdle_bps: float,
) -> dict[str, Any]:
    """The ALPHA-001 statistic applied to one arm.

    ``directions`` is the frozen signal per row (``None`` = not a decision, ``0`` =
    no trade).  ``forward_returns`` is the forward return as a *fraction* — the
    label — and is converted to basis points here, exactly once.  A contribution is
    ``direction * forward * 1e4``; its mean is the gross per-trade edge in bps.
    """
    pairs = [
        (int(direction), float(forward))
        for direction, forward in zip(directions, forward_returns, strict=True)
        if direction is not None and forward is not None
    ]
    evaluated = len(pairs)
    active = [(direction, forward) for direction, forward in pairs if direction != 0]
    contributions = [direction * forward * 1e4 for direction, forward in active]
    n = len(contributions)
    gross = a1.mean(contributions)
    sigma = a1.mean([(value - gross) ** 2 for value in contributions]) ** 0.5 if n else 0.0
    n_eff = a1.effective_sample_size(contributions) if n > 1 else float(n)
    se = sigma / math.sqrt(n_eff) if n_eff > 0 and sigma > 0 else float("inf")
    t_stat = gross / se if se not in (0.0, float("inf")) else 0.0
    p_raw = _one_sided_p(t_stat)
    ic = a1.spearman([d for d, _ in active], [f for _, f in active]) if len(active) >= 5 else 0.0
    power = a1.power_class(n_effective=n_eff, sigma_bps=sigma, hurdle_bps=hurdle_bps)
    concentration = a1.concentration([value for value in contributions if value != 0.0])
    stability = a1.stability_by_window(contributions, windows=STABILITY_WINDOWS)
    return {
        "n_evaluated": evaluated,
        "n": n,
        "n_effective": round(n_eff, 3),
        "gross_bps": round(gross, 6),
        "net_bps": round(gross - a1.COST_BPS_V3, 6),
        "sigma_bps": round(sigma, 6),
        "t_stat": round(t_stat, 6),
        "p_raw": round(p_raw, 8),
        "ic": round(ic, 6),
        "power_class": power["class"],
        "mde_bps": power["mde_bps"],
        "hurdle_bps": round(hurdle_bps, 6),
        "gross_above_hurdle": gross >= hurdle_bps,
        "distance_to_hurdle_bps": round(gross - hurdle_bps, 6),
        "concentration": concentration,
        "stability": stability,
        "contributions": contributions,
    }


def _one_sided_p(t_stat: float) -> float:
    if t_stat <= 0:
        return 1.0
    return max(0.0, min(1.0, 0.5 * math.erfc(t_stat / math.sqrt(2.0))))


def _circular_shift(values: Sequence[float], shift: int) -> list[float]:
    if not values:
        return []
    shift %= len(values)
    return list(values[shift:]) + list(values[:shift])


def permutation_null(
    arms: Mapping[str, tuple[Sequence[int | None], Sequence[float | None]]],
    *,
    draws: int = NULL_DRAWS,
    seed: int = NULL_SEED,
) -> dict[str, Any]:
    """Best-of-N selection null via circular shifts of the *directions*.

    Shifting the direction vector against the returns breaks the signal↔return
    alignment while preserving both marginals.  ``arms`` maps an arm label to its
    ``(directions, forwards_bps)``.
    """
    rng = random.Random(seed)
    observed: dict[str, float] = {}
    usable: dict[str, tuple[list[int], list[float]]] = {}
    for label, (directions, forward_returns) in arms.items():
        pairs = [
            (int(direction), float(forward))
            for direction, forward in zip(directions, forward_returns, strict=True)
            if direction is not None and forward is not None
        ]
        active = [(d, f) for d, f in pairs if d != 0]
        if len(active) < 20:
            continue
        observed[label] = a1.mean([d * f * 1e4 for d, f in active])
        usable[label] = ([d for d, _ in active], [f for _, f in active])
    if not usable:
        return {"draws": 0, "arms": []}
    null_best: list[float] = []
    for _ in range(draws):
        best = float("-inf")
        for directions, forwards in usable.values():
            shift = rng.randrange(1, len(directions))
            shifted = _circular_shift(directions, shift)
            best = max(best, a1.mean([d * f * 1e4 for d, f in zip(shifted, forwards, strict=True)]))
        null_best.append(best)
    best_label = max(observed, key=lambda label: observed[label])
    comparison: dict[str, Any] = dict(a1.best_of_n_null(observed[best_label], null_best))
    comparison["best_arm"] = best_label
    comparison["observed_best_bps"] = round(observed[best_label], 6)
    comparison["arms"] = sorted(usable)
    return comparison


# --------------------------------------------------------------------------- #
# §5 — the promotion gate
# --------------------------------------------------------------------------- #


def promotion_gate(
    *,
    summary: Mapping[str, Any],
    bh_pass: bool,
    holm_pass: bool,
    baseline_delta_bps: float,
    p_null_best_ge_observed: float,
) -> dict[str, Any]:
    """Every preregistered condition, evaluated explicitly and reported.

    A candidate reaches ``OOS_CANDIDATE`` only when every one of these holds.  A
    single failure is a REJECT, and an underpowered cell is INCONCLUSIVE rather
    than negative — the preregistration says so, and this returns it as such.
    """
    checks = {
        "raw_positive": summary["gross_bps"] > 0.0,
        "above_frozen_hurdle": bool(summary["gross_above_hurdle"]),
        "bh_fdr_pass": bool(bh_pass),
        "holm_pass": bool(holm_pass),
        "powered": summary["power_class"] == "POWERED",
        "concentration_robust": summary["concentration"]["classification"] == "ROBUST",
        "stability_consistent": bool(summary["stability"]["consistent"]),
        "beats_price_only_baseline": baseline_delta_bps > 0.0,
        "survives_selection_null": p_null_best_ge_observed < 0.05,
    }
    passed = all(checks.values())
    if passed:
        verdict = "OOS_CANDIDATE"
    elif summary["power_class"] == "UNDERPOWERED" or not checks["above_frozen_hurdle"]:
        # Not enough evidence to reject, or not enough effect to admit: the honest
        # word depends on which side of the hurdle the point estimate fell.
        verdict = "INCONCLUSIVE" if summary["power_class"] == "UNDERPOWERED" else "REJECT"
    else:
        verdict = "REJECT"
    return {"checks": checks, "passed": passed, "verdict": verdict}
