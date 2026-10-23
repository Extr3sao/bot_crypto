"""ALPHA-003 — the frozen development experiment over the cross-asset frame.

This module is the honest half of the campaign.  The preregistration
(``alpha003.PREREGISTRATION``) says *what* the hypotheses are; this module says *how they
are measured*, and it is written so that the measurement cannot flatter the hypothesis:

* **The rule is applied, not re-derived.**  The traded directions come from
  ``alpha003.SIGNALS`` verbatim, evaluated on the derived feature row built by
  ``alpha003_features.cell_row``.  The ablation arms are separately written reductions of
  the same rule, and a test asserts that the ``FULL`` arm reproduces the frozen signal
  exactly, so a drifting ablation is a test failure rather than a finding.
* **A missing source is not a trade.**  A row where a required feature is absent is dropped
  for that arm and counted, never imputed.
* **The incremental delta is the question.**  Every hypothesis is measured against the
  *same hypothesis's own-history baseline arm*, because "the cross-asset rule made money"
  is not the question — "did the other asset's information add anything over what the
  target was already doing" is.  A cross-asset arm that works only because it replicates
  ordinary own-asset momentum is a failure of this campaign, and the arithmetic says so.
* **Multiplicity is frozen.**  Benjamini-Hochberg at q = 0.10 and Holm at alpha = 0.10 over
  every declared cell, plus a best-of-N circular-shift permutation null that shifts the
  cross-asset signal against the returns.  The corrections are named here, not chosen after
  seeing the numbers.
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
from trading_bot.research import alpha003 as a3
from trading_bot.research import alpha003_features as af

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
    "arm_direction",
    "calendar_boundaries",
    "cell_ids",
    "evaluate_directions",
    "in_window",
    "nontraded_flag",
    "parse_cell",
    "permutation_null",
    "preregistered_direction",
    "promotion_gate",
]

#: The design assumption used to derive the hurdle *before* any result is seen.
#: Identical to ALPHA-001's and ALPHA-002's: a conservative per-decision gross sigma, never
#: the realised dispersion (which would let the data set its own bar).
DESIGN_SIGMA_BPS = 400.0

#: Permutation draws for the selection null.
NULL_DRAWS = 1000
NULL_SEED = 20_261_011

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
    """A single calendar split shared by every asset, pair, lag and timeframe.

    Half-open intervals ``[lo, hi)``.  The holdout is the final slice and is never read by
    development.
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


# --------------------------------------------------------------------------- #
# §2 — the cell enumeration
# --------------------------------------------------------------------------- #


def cell_ids() -> list[str]:
    """Every declared cell, in a deterministic order shared by builder and verifier.

    ``A3-H01`` is enumerated over the declared pairs, the declared lags and the entry
    timeframes; ``A3-H02`` and ``A3-H03`` are per-target, having no pair or lag.  The list
    is closed: no cell outside it may be evaluated or reported.
    """
    cells: list[str] = []
    for timeframe in a3.ENTRY_TIMEFRAMES:
        for leader, target in a3.LEADER_TARGET_PAIRS:
            for lag in a3.LEAD_LAGS:
                cells.append(f"A3-H01|{leader}->{target}|L{lag}|{timeframe}")
    for hypothesis_id in ("A3-H02", "A3-H03"):
        for timeframe in a3.ENTRY_TIMEFRAMES:
            for target in a3.UNIVERSE:
                cells.append(f"{hypothesis_id}|{target}|{timeframe}")
    return cells


def parse_cell(cell_id: str) -> dict[str, Any]:
    """Inverse of :func:`cell_ids`, for a builder or verifier that is handed a cell."""
    parts = cell_id.split("|")
    hypothesis_id, timeframe = parts[0], parts[-1]
    if hypothesis_id == "A3-H01":
        if len(parts) != 4 or not parts[2].startswith("L"):
            raise ValueError(f"malformed A3-H01 cell: {cell_id}")
        leader, target = parts[1].split("->")
        lag = int(parts[2][1:])
        # An undeclared lag is not a cell: lag fishing is excluded by construction, not by
        # discipline, so a verifier handed such a cell fails loudly rather than evaluating it.
        if lag not in a3.LEAD_LAGS:
            raise ValueError(f"undeclared lag {lag} in cell {cell_id}")
        if (leader, target) not in a3.LEADER_TARGET_PAIRS:
            raise ValueError(f"undeclared pair {leader}->{target} in cell {cell_id}")
        return {
            "cell": cell_id,
            "hypothesis_id": hypothesis_id,
            "leader": leader,
            "target": target,
            "lag": lag,
            "timeframe": timeframe,
            "primary_arm": hypothesis_id,
        }
    if len(parts) != 3:
        raise ValueError(f"malformed cell: {cell_id}")
    if parts[1] not in a3.UNIVERSE:
        raise ValueError(f"undeclared target {parts[1]} in cell {cell_id}")
    return {
        "cell": cell_id,
        "hypothesis_id": hypothesis_id,
        "leader": None,
        "target": parts[1],
        "lag": None,
        "timeframe": timeframe,
        "primary_arm": hypothesis_id,
    }


# --------------------------------------------------------------------------- #
# §3 — directions: the frozen rule, the baselines, the ablations
# --------------------------------------------------------------------------- #


def _eligible(features: Mapping[str, float | None], required: Sequence[str]) -> bool:
    return all(features.get(name) is not None for name in required)


def arm_direction(arm_id: str, features: Mapping[str, float | None]) -> int | None:
    """Apply one declared arm to a derived feature row, or ``None`` when it cannot fire.

    ``arm_id`` is either a traded hypothesis (``alpha003.SIGNALS``) or a declared baseline.
    A row missing a required feature is not a decision for that arm.
    """
    required = af.REQUIRED_FEATURES[arm_id]
    if not _eligible(features, required):
        return None
    signal = a3.SIGNALS.get(arm_id)
    if signal is not None:
        return int(signal(_values(features)))
    baseline = BASELINES.get(arm_id)
    if baseline is not None:
        return baseline(_values(features))
    raise KeyError(f"{arm_id} is neither a traded hypothesis nor a declared baseline")


def _as_float(value: float | None) -> float:
    return 0.0 if value is None else float(value)


def _values(features: Mapping[str, float | None]) -> dict[str, float]:
    """The narrow, fully-populated view an executable arm is allowed to read.

    A required feature is guaranteed present before an arm runs, so the ``0.0`` fallback
    only ever applies to a feature the arm does not use.
    """
    return {name: _as_float(features.get(name)) for name in af.FEATURE_NAMES}


def preregistered_direction(hypothesis_id: str, features: Mapping[str, float | None]) -> int | None:
    """The frozen signal for a traded hypothesis, or ``None`` when a source is missing."""
    return arm_direction(hypothesis_id, features)


def nontraded_flag(arm_id: str, features: Mapping[str, float | None]) -> bool | None:
    """The declared comparator arms.  Reported, never traded."""
    required = af.REQUIRED_FEATURES[arm_id]
    if not _eligible(features, required):
        return None
    predicate = a3.NON_TRADED_ARMS[arm_id]
    return bool(predicate(_values(features)))


# -- baselines --------------------------------------------------------------- #


def _b0_unconditional(_features: Mapping[str, float]) -> int:
    """A3-B0 — always long.  The unconditional return of the target."""
    return 1


def _b1_own_same_lag(features: Mapping[str, float]) -> int | None:
    """A3-B1 (H1) — the target's own move at the hypothesis's own horizon."""
    value = features["target_ret_z"]
    if abs(value) <= a3.THRESHOLDS["leader_ret_z"]:
        return 0
    return 1 if value > 0 else -1


def _b1_own_r(features: Mapping[str, float]) -> int | None:
    """A3-B1 (H2/H3) — the target's own R-bar momentum, with no cross-asset term."""
    value = features["target_mom_z"]
    if abs(value) <= a3.THRESHOLDS["relative_strength_z"]:
        return 0
    return 1 if value > 0 else -1


def _b3_market_direction(features: Mapping[str, float]) -> int | None:
    """A3-B3 — trade the target on the common market factor, using no pair at all."""
    value = features["market_ret_z"]
    if abs(value) <= a3.THRESHOLDS["leader_ret_z"]:
        return 0
    return 1 if value > 0 else -1


def _b4_leader_only(features: Mapping[str, float]) -> int | None:
    """A3-B4 — the directional twin of the declared non-traded contrast ``A3-NT-01``.

    The frozen H1 rule with the target-lag condition removed: trade the leader's direction
    whenever the leader moved.  The contrast arm itself is a boolean *subset* and cannot be
    traded; this is the same idea expressed as a direction, so the ablation table can answer
    "is the target condition doing any work at all".
    """
    value = features["leader_ret_z"]
    if abs(value) <= a3.THRESHOLDS["leader_ret_z"]:
        return 0
    return 1 if value > 0 else -1


BASELINES: dict[str, Callable[[Mapping[str, float]], int | None]] = {
    "A3-B0_UNCONDITIONAL_LONG": _b0_unconditional,
    "A3-B1_OWN_MOMENTUM_SAME_LAG": _b1_own_same_lag,
    "A3-B1_OWN_MOMENTUM_R": _b1_own_r,
    "A3-B3_MARKET_DIRECTION": _b3_market_direction,
    "A3-B4_LEADER_ONLY": _b4_leader_only,
}

#: ``hypothesis_id`` → the arms reported beside the frozen rule.  ``FULL`` must reproduce
#: ``alpha003.SIGNALS`` exactly (a test enforces it).  The arm named by the hypothesis's
#: declared ``baseline_arm`` is the one the incremental delta is measured against.
#: Every entry must be a *directional* arm (a traded hypothesis or a declared baseline); a
#: boolean subset arm is reported in the non-traded table instead, and a test enforces it.
ABLATIONS: dict[str, tuple[str, ...]] = {
    "A3-H01": ("FULL", "A3-B1_OWN_MOMENTUM_SAME_LAG", "A3-B4_LEADER_ONLY"),
    "A3-H02": ("FULL", "A3-B1_OWN_MOMENTUM_R", "A3-B3_MARKET_DIRECTION"),
    "A3-H03": ("FULL", "A3-B1_OWN_MOMENTUM_R", "A3-B3_MARKET_DIRECTION"),
}

#: The arm each hypothesis's incremental delta is measured against, frozen here from the
#: registry's ``baseline_arm`` so the arithmetic cannot pick its own comparator.
INCREMENTAL_BASELINE: dict[str, str] = {
    "A3-H01": "A3-B1_OWN_MOMENTUM_SAME_LAG",
    "A3-H02": "A3-B1_OWN_MOMENTUM_R",
    "A3-H03": "A3-B1_OWN_MOMENTUM_R",
}


def ablation_direction(
    hypothesis_id: str, label: str, features: Mapping[str, float | None]
) -> int | None:
    """Apply one ablation variant, or the frozen rule when ``label == 'FULL'``."""
    if label == "FULL":
        return preregistered_direction(hypothesis_id, features)
    return arm_direction(label, features)


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

    ``directions`` is the frozen signal per row (``None`` = not a decision, ``0`` = no
    trade).  ``forward_returns`` is the forward return as a *fraction* — the label — and is
    converted to basis points here, exactly once.  A contribution is
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

    Shifting the direction vector against the returns breaks the cross-asset signal's
    alignment with the target's forward return while preserving both marginals: an
    equally-sized random signal of the same shape must not reproduce the apparent result.
    ``arms`` maps a cell label to its ``(directions, forwards)``.
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
    incremental_delta_bps: float,
    bh_pass: bool,
    holm_pass: bool,
    p_null_best_ge_observed: float,
) -> dict[str, Any]:
    """Every preregistered condition, evaluated explicitly and reported.

    A cell reaches ``VALIDATION_CANDIDATE`` only when every one of these holds — including,
    first among equals, that the cross-asset arm beat its own-history baseline.  A single
    failure is a REJECT, and an underpowered cell is INCONCLUSIVE rather than negative: the
    preregistration says so, and this returns it as such.
    """
    checks = {
        "raw_positive": summary["gross_bps"] > 0.0,
        "incremental_positive": incremental_delta_bps > 0.0,
        "above_frozen_hurdle": bool(summary["gross_above_hurdle"]),
        "bh_fdr_pass": bool(bh_pass),
        "holm_pass": bool(holm_pass),
        "powered": summary["power_class"] == "POWERED",
        "concentration_robust": summary["concentration"]["classification"] == "ROBUST",
        "stability_consistent": bool(summary["stability"]["consistent"]),
        "survives_selection_null": p_null_best_ge_observed < 0.05,
    }
    passed = all(checks.values())
    if passed:
        verdict = "VALIDATION_CANDIDATE"
    elif summary["power_class"] == "UNDERPOWERED" or incremental_delta_bps <= 0.0:
        # Not enough evidence to reject (or the extra information subtracted value): the
        # honest word depends on whether the cell could have said anything at all.
        verdict = "INCONCLUSIVE" if summary["power_class"] == "UNDERPOWERED" else "REJECT"
    else:
        verdict = "REJECT"
    return {"checks": checks, "passed": passed, "verdict": verdict}
