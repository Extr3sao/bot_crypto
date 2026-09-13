"""V4 — the ACTUAL H6 runtime data path (V4 repair for V3-WL-003).

Traced path this module implements:

    stored normalised OI row
        -> feature_authority.admitted_observation   (FAIL-CLOSED boundary)
        -> causal selection (only ts <= decision_time)
        -> half-open completed-hour aggregation     ([T-1h, T), exactly 12 by contract)
        -> H6FeatureEngine.compute_feature_state
        -> compute_signal                           (signal candidate)

The feature engine never receives an unrestricted dictionary: it receives
``CompletedHourOI`` / ``CompletedHourPrice`` / typed change tuples built only from
``AdmittedOIObservation`` values. Injecting a forbidden or unadmitted field anywhere on
this path raises BEFORE any aggregate, feature or signal exists.

This module is the RUNTIME TARGET that tests must exercise (TEST_TARGET == RUNTIME_TARGET).

No economics.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from trading_bot.research.h6.eligibility import build_completed_hour_oi, completed_hour_changes_before
from trading_bot.research.h6.feature_authority import AdmittedOIObservation, admitted_observation
from trading_bot.research.h6.feature_engine import (
    CompletedHourOI,
    CompletedHourPrice,
    H6FeatureEngine,
    H6FeatureState,
    H6Signal,
    ObservedOI,
    compute_signal,
)

HOUR_MS = 3_600_000


@dataclass(frozen=True, slots=True)
class PreparedDecision:
    """Everything the H6 runtime can legally know at decision time."""

    symbol: str
    decision_time: datetime
    decision_time_ms: int
    observations_admitted: int
    current_hour_oi: CompletedHourOI
    previous_hour_oi: CompletedHourOI | None
    rolling_changes: int
    feature_state: H6FeatureState
    signal: H6Signal
    authority_boundary: str = "feature_authority.admitted_observation"


def _ms(decision_time: datetime) -> int:
    return int(decision_time.timestamp() * 1000)


def admitted_causal_observations(
    rows: Iterable[Mapping[str, Any]],
    *,
    decision_time: datetime,
    context: str = "h6.preparation",
) -> list[AdmittedOIObservation]:
    """Boundary + causal filter. Rejects dirty rows before looking at time."""
    cutoff = _ms(decision_time)
    admitted: list[AdmittedOIObservation] = []
    for row in rows:
        obs = admitted_observation(row, context=context)  # fail closed
        if obs.ts_ms <= cutoff:
            admitted.append(obs)
    admitted.sort(key=lambda o: o.ts_ms)
    return admitted


def to_observed_oi(observations: Sequence[AdmittedOIObservation]) -> list[ObservedOI]:
    """Typed conversion; the only bridge from stored rows to the feature engine."""
    return [
        ObservedOI(
            oi_time=o.oi_time(),
            sum_open_interest=o.sum_open_interest,
            sum_open_interest_value=o.sum_open_interest_value or 0.0,
        )
        for o in observations
    ]


def completed_hours_ending_at(
    observations: Sequence[AdmittedOIObservation],
    *,
    first_hour_close: datetime,
    last_hour_close: datetime,
) -> list[CompletedHourOI]:
    """Half-open completed-hour aggregates across a range of hour-close times."""
    snaps = to_observed_oi(observations)
    hours: list[CompletedHourOI] = []
    close = first_hour_close
    while close <= last_hour_close:
        hours.append(build_completed_hour_oi(snaps, hour_close_time=close))
        close = close + timedelta(hours=1)
    return hours


def build_feature_state(
    observations: Sequence[AdmittedOIObservation],
    *,
    symbol: str,
    decision_time: datetime,
    price: CompletedHourPrice,
    engine: H6FeatureEngine | None = None,
) -> tuple[H6FeatureState, CompletedHourOI, CompletedHourOI | None, int]:
    """Aggregate and compute the frozen feature state from admitted observations only."""
    snaps = to_observed_oi(observations)
    current = build_completed_hour_oi(snaps, hour_close_time=decision_time)
    previous = build_completed_hour_oi(snaps, hour_close_time=decision_time - timedelta(hours=1))

    hours = completed_hours_ending_at(
        observations,
        first_hour_close=decision_time - timedelta(hours=len(observations) // 12 + 2),
        last_hour_close=decision_time,
    )
    changes = completed_hour_changes_before(hours, strictly_before_decision_time=decision_time)

    engine = engine or H6FeatureEngine(symbol=symbol)
    feature = engine.compute_feature_state(
        symbol, decision_time, price, current, previous, changes
    )
    return feature, current, previous, len(changes)


def prepare_decision(
    rows: Iterable[Mapping[str, Any]],
    *,
    symbol: str,
    decision_time: datetime,
    price: CompletedHourPrice,
    engine: H6FeatureEngine | None = None,
    context: str = "h6.preparation",
) -> PreparedDecision:
    """THE RUNTIME ENTRY POINT. Boundary first, then causal filter, then features.

    Raises (fail-closed, before any feature/signal exists) if any row carries a
    forbidden or unadmitted field.
    """
    admitted = admitted_causal_observations(rows, decision_time=decision_time, context=context)
    feature, current, previous, n_changes = build_feature_state(
        admitted, symbol=symbol, decision_time=decision_time, price=price, engine=engine
    )
    return PreparedDecision(
        symbol=symbol,
        decision_time=decision_time,
        decision_time_ms=_ms(decision_time),
        observations_admitted=len(admitted),
        current_hour_oi=current,
        previous_hour_oi=previous,
        rolling_changes=n_changes,
        feature_state=feature,
        signal=compute_signal(feature),
    )


def prepare_decision_from_data_root(
    *,
    data_root: Path,
    symbol: str,
    decision_time: datetime,
    price: CompletedHourPrice,
    engine: H6FeatureEngine | None = None,
) -> PreparedDecision:
    """Runtime entry point reading the authoritative normalised OI store.

    Uses the frozen causal reader (``oi_dataset_v2.oi_state_at_ms``) and then the
    fail-closed boundary. The verifier-visible path is identical to
    ``prepare_decision``, so TEST_TARGET == RUNTIME_TARGET holds by construction.
    """
    from trading_bot.research.oi_dataset_v2 import oi_state_at_ms

    rows = oi_state_at_ms(_ms(decision_time), symbol, data_root)
    return prepare_decision(
        rows,
        symbol=symbol,
        decision_time=decision_time,
        price=price,
        engine=engine,
        context=f"h6.preparation[{symbol}]",
    )


__all__ = [
    "PreparedDecision",
    "admitted_causal_observations",
    "build_feature_state",
    "completed_hours_ending_at",
    "prepare_decision",
    "prepare_decision_from_data_root",
    "to_observed_oi",
]
