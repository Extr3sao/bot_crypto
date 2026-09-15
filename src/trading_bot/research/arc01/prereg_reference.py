"""ARC-01 preregistration reference functions — pure, deterministic, data-free.

This module encodes ONLY the frozen ARC-01 decision rules
(docs/arc01-prereg-01/ARC01_SPEC_V1.json) as pure functions over caller-supplied
observations. It performs NO I/O, loads NO dataset, computes NO performance
statistic, and therefore cannot observe economic performance.

Its purpose is pre-freeze verification: it gives the prereg validator something
executable to falsify (PIT future-mutation invariance, past-eligible mutation
detectability, MAD-zero behaviour, inclusive threshold boundaries, NO_SIGNAL
precedence). The later authorized discovery run MUST use these definitions
unchanged.

Frozen constants are read from the spec by tests/verify_arc01_prereg.py; they are
duplicated here as module constants for import-time clarity only.
"""

from __future__ import annotations

import hashlib
from statistics import median

# ---- frozen constants (ARC01_SPEC_V1.json) ----
FUNDING_LOOKBACK_DAYS = 60
FUNDING_LOOKBACK_MS = FUNDING_LOOKBACK_DAYS * 86_400_000
FUNDING_MIN_OBSERVATIONS = 90
MAD_SCALE = 1.4826
FUNDING_Z_POSITIVE_THRESHOLD = 2.0
FUNDING_Z_NEGATIVE_THRESHOLD = -2.0
OI_LOOKBACK_MS = 86_400_000
OI_MAX_STALENESS_MS = 600_000
HOLDING_MS = 72 * 3_600_000
NULL_SEED = 20260915

COMMON_WINDOW_START_MS = 1_638_316_800_000
COMMON_WINDOW_END_MS = 1_789_081_200_000

# Frozen NO_SIGNAL precedence (first satisfied reason wins).
NO_SIGNAL_PRECEDENCE = (
    "OUTSIDE_COMMON_WINDOW",
    "INSUFFICIENT_FUNDING_HISTORY",
    "SCALE_NONPOSITIVE",
    "FUNDING_NOT_EXTREME",
    "OI_MISSING_OR_STALE",
    "OI_REFERENCE_MISSING_OR_STALE",
    "OI_REFERENCE_INVALID",
    "OI_NOT_EXPANDING",
    "POSITION_ALREADY_OPEN",
    "INSUFFICIENT_FORWARD_PRICE_DATA",
)

LONG = "LONG"
SHORT = "SHORT"
NO_SIGNAL = "NO_SIGNAL"


def _median(values: list[float]) -> float:
    return float(median(values))


def _mad(values: list[float], center: float) -> float:
    return _median([abs(v - center) for v in values])


def _stdev(values: list[float]) -> float:
    """Sample standard deviation (ddof=1); 0.0 for fewer than 2 points.

    A fully degenerate window (every observation identical) returns exactly 0.0 even
    though naive summation can leave a ~1e-19 residue: the frozen MAD==0 fallback must
    be float-independent, otherwise a pinned funding regime would silently produce a
    spurious scale instead of failing closed with SCALE_NONPOSITIVE.
    """
    n = len(values)
    if n < 2:
        return 0.0
    if min(values) == max(values):
        return 0.0
    mu = sum(values) / n
    variance = sum((v - mu) ** 2 for v in values) / (n - 1)
    if variance <= 0.0:
        return 0.0
    return float(variance ** 0.5)


def funding_window(
    funding_observations: list[tuple[int, float]],
    decision_time_ms: int,
) -> list[tuple[int, float]]:
    """Frozen trailing funding window: CLOSED [T - 60d, T] on funding_time_ms.

    `funding_observations` is a caller-supplied list of (funding_time_ms, rate).
    Strictly causal: observations after T are excluded.
    """
    lo = decision_time_ms - FUNDING_LOOKBACK_MS
    return [
        (int(t), float(r))
        for (t, r) in funding_observations
        if lo <= int(t) <= decision_time_ms
    ]


def funding_extreme(
    funding_observations: list[tuple[int, float]],
    decision_time_ms: int,
) -> dict[str, object]:
    """Frozen FUNDING_EXTREME_ROBUST_Z transform.

    Returns a dict with status in {OK, INSUFFICIENT_FUNDING_HISTORY,
    SCALE_NONPOSITIVE, NO_CURRENT_OBSERVATION} plus the estimator internals.
    """
    window = funding_window(funding_observations, decision_time_ms)
    rates = [r for _, r in window]
    current = [r for (t, r) in window if t == decision_time_ms]
    out: dict[str, object] = {
        "window_start_ms": decision_time_ms - FUNDING_LOOKBACK_MS,
        "window_end_ms": decision_time_ms,
        "observations": len(rates),
        "scale_estimator": "1.4826*MAD",
        "mad_fallback_used": False,
        "z": None,
    }
    if not current:
        out["status"] = "NO_CURRENT_OBSERVATION"
        return out
    out["current_rate"] = current[-1]
    if len(rates) < FUNDING_MIN_OBSERVATIONS:
        out["status"] = "INSUFFICIENT_FUNDING_HISTORY"
        return out
    center = _median(rates)
    mad = _mad(rates, center)
    if mad == 0.0:
        scale = _stdev(rates)
        out["mad_fallback_used"] = True
        out["scale_estimator"] = "SAMPLE_STDEV(ddof=1) [MAD==0 fallback]"
    else:
        scale = MAD_SCALE * mad
    out["median"] = center
    out["mad"] = mad
    out["scale"] = scale
    if scale <= 0.0:
        out["status"] = "SCALE_NONPOSITIVE"
        return out
    out["z"] = (float(current[-1]) - center) / scale
    out["status"] = "OK"
    return out


def oi_change_24h(
    oi_now: tuple[int, float] | None,
    oi_ref: tuple[int, float] | None,
    decision_time_ms: int,
) -> dict[str, object]:
    """Frozen OI_CROWDING_EXPANSION_24H transform. Inputs are (timestamp_ms, sum_open_interest)."""
    out: dict[str, object] = {"oi_change_24h": None, "status": "OK"}
    if oi_now is None:
        out["status"] = "OI_MISSING_OR_STALE"
        return out
    now_ts, now_val = int(oi_now[0]), float(oi_now[1])
    if decision_time_ms - now_ts > OI_MAX_STALENESS_MS or now_ts > decision_time_ms:
        out["status"] = "OI_MISSING_OR_STALE"
        return out
    reference_instant = decision_time_ms - OI_LOOKBACK_MS
    if oi_ref is None:
        out["status"] = "OI_REFERENCE_MISSING_OR_STALE"
        return out
    ref_ts, ref_val = int(oi_ref[0]), float(oi_ref[1])
    if reference_instant - ref_ts > OI_MAX_STALENESS_MS or ref_ts > reference_instant:
        out["status"] = "OI_REFERENCE_MISSING_OR_STALE"
        return out
    if ref_val <= 0.0:
        out["status"] = "OI_REFERENCE_INVALID"
        return out
    out["oi_now"] = now_val
    out["oi_ref"] = ref_val
    out["oi_now_time_ms"] = now_ts
    out["oi_ref_time_ms"] = ref_ts
    out["oi_change_24h"] = (now_val / ref_val) - 1.0
    return out


def decide_direction(z_funding: float | None) -> str | None:
    """Frozen INCLUSIVE direction rules: z >= +2.0 -> SHORT, z <= -2.0 -> LONG, else None."""
    if z_funding is None:
        return None
    z = float(z_funding)
    if z >= FUNDING_Z_POSITIVE_THRESHOLD:
        return SHORT
    if z <= FUNDING_Z_NEGATIVE_THRESHOLD:
        return LONG
    return None


def evaluate_decision(
    *,
    decision_time_ms: int,
    funding_observations: list[tuple[int, float]],
    oi_now: tuple[int, float] | None,
    oi_ref: tuple[int, float] | None,
    position_open: bool = False,
    exit_bar_open_time_ms: int | None = None,
    entry_bar_open_time_ms: int | None = None,
    common_window_start_ms: int = COMMON_WINDOW_START_MS,
    common_window_end_ms: int = COMMON_WINDOW_END_MS,
) -> dict[str, object]:
    """Frozen decision evaluation with the exact frozen NO_SIGNAL precedence.

    Emits a trade only when the SHORT_RULE or LONG_RULE holds and no reason applies.
    """
    reasons: set[str] = set()

    decision_in_window = common_window_start_ms <= decision_time_ms <= common_window_end_ms
    if not decision_in_window:
        reasons.add("OUTSIDE_COMMON_WINDOW")

    funding = funding_extreme(funding_observations, decision_time_ms)
    if funding["status"] == "INSUFFICIENT_FUNDING_HISTORY":
        reasons.add("INSUFFICIENT_FUNDING_HISTORY")
    if funding["status"] == "SCALE_NONPOSITIVE":
        reasons.add("SCALE_NONPOSITIVE")

    z = funding["z"]
    direction = decide_direction(z)  # type: ignore[arg-type]
    if direction is None:
        reasons.add("FUNDING_NOT_EXTREME")

    oi = oi_change_24h(oi_now, oi_ref, decision_time_ms)
    oi_status = str(oi["status"])
    if oi_status != "OK":
        reasons.add(oi_status)
    else:
        change = float(oi["oi_change_24h"])  # type: ignore[arg-type]
        if not change > 0.0:
            reasons.add("OI_NOT_EXPANDING")

    if position_open:
        reasons.add("POSITION_ALREADY_OPEN")

    if (
        exit_bar_open_time_ms is not None
        and exit_bar_open_time_ms > common_window_end_ms
    ):
        reasons.add("INSUFFICIENT_FORWARD_PRICE_DATA")
    if entry_bar_open_time_ms is not None and entry_bar_open_time_ms <= decision_time_ms:
        raise ValueError("entry anchor must be strictly after decision_time (PIT violation)")

    first_reason = next((r for r in NO_SIGNAL_PRECEDENCE if r in reasons), None)
    emitted = first_reason is None
    return {
        "decision_time_ms": decision_time_ms,
        "result": direction if emitted else NO_SIGNAL,
        "emitted": emitted,
        "reason": first_reason,
        "all_reasons": sorted(reasons),
        "z_funding": z,
        "funding_status": funding["status"],
        "oi_status": oi_status,
        "oi_change_24h": oi["oi_change_24h"],
        "funding_transform": funding,
    }


def funding_cashflow_return(direction_sign: int, settlement_rates: list[float]) -> float:
    """Frozen cashflow rule: sum of (-direction_sign * funding_rate) over settlements in (entry, exit]."""
    if direction_sign not in (-1, 1):
        raise ValueError("direction_sign must be +1 or -1")
    return float(sum(-direction_sign * float(r) for r in settlement_rates))


def null_direction(asset: str, decision_time_ms: int, seed: int = NULL_SEED) -> str:
    """Frozen NULL_CONTROL direction: deterministic SHA256 parity of (seed, asset, decision_time_ms)."""
    digest = hashlib.sha256(f"{seed}:{asset}:{decision_time_ms}".encode("utf-8")).digest()
    return LONG if digest[0] % 2 == 0 else SHORT


def exit_bar_open_time_ms(entry_bar_open_time_ms: int) -> int:
    return int(entry_bar_open_time_ms) + HOLDING_MS


__all__ = [
    "COMMON_WINDOW_END_MS",
    "COMMON_WINDOW_START_MS",
    "FUNDING_LOOKBACK_MS",
    "FUNDING_MIN_OBSERVATIONS",
    "FUNDING_Z_NEGATIVE_THRESHOLD",
    "FUNDING_Z_POSITIVE_THRESHOLD",
    "HOLDING_MS",
    "LONG",
    "MAD_SCALE",
    "NO_SIGNAL",
    "NO_SIGNAL_PRECEDENCE",
    "NULL_SEED",
    "OI_LOOKBACK_MS",
    "OI_MAX_STALENESS_MS",
    "SHORT",
    "decide_direction",
    "evaluate_decision",
    "exit_bar_open_time_ms",
    "funding_cashflow_return",
    "funding_extreme",
    "funding_window",
    "null_direction",
    "oi_change_24h",
]
