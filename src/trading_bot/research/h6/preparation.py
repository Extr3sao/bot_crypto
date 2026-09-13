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
    frozen_rolling_window,
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


def _oldest_hour_close(observations: Sequence[AdmittedOIObservation]) -> datetime | None:
    """Close time of the hour containing the OLDEST observation handed over."""
    if not observations:
        return None
    oldest = min(o.oi_time() for o in observations)
    return oldest.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)


def completed_hours_ending_at(
    observations: Sequence[AdmittedOIObservation],
    *,
    first_hour_close: datetime,
    last_hour_close: datetime,
) -> list[CompletedHourOI]:
    """Half-open completed-hour aggregates across a range of hour-close times.

    The observations are first restricted to the union of the queried hour windows,
    ``[first_hour_close - 1h, last_hour_close)``.  No snapshot outside that union can
    belong to any queried window, so the restriction is semantics-preserving; it keeps
    the cost proportional to the WINDOW rather than to however much history the caller
    passes.
    """
    if last_hour_close < first_hour_close:
        return []
    union_start = first_hour_close - timedelta(hours=1)
    kept = [o for o in observations if union_start <= o.oi_time() < last_hour_close]
    snaps = to_observed_oi(kept)
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
    # Only the two hours a decision actually consumes are converted; a caller may hand
    # over the whole causal store, so this must not materialise every snapshot.
    recent = [o for o in observations if o.oi_time() >= decision_time - timedelta(hours=2)]
    snaps = to_observed_oi(recent)
    current = build_completed_hour_oi(snaps, hour_close_time=decision_time)
    previous = build_completed_hour_oi(snaps, hour_close_time=decision_time - timedelta(hours=1))

    # The frozen window bounds the number of hourly CHANGES (each change pairs two
    # consecutive completed hours), so the hour range spans length_hours + 1 closes.  It
    # is additionally clipped to the history that actually exists: materialising the full
    # window over a shorter history would fabricate zero-level "completed" hours, which
    # are not observations at all.  The engine then applies the frozen window to the
    # series it receives, so a caller passing everything still gets the frozen window.
    window_hours, _min_observations = frozen_rolling_window()
    window_start = decision_time - timedelta(hours=window_hours + 1)
    oldest_close = _oldest_hour_close(observations)
    first_hour_close = max(window_start, oldest_close) if oldest_close is not None else window_start
    hours = completed_hours_ending_at(
        observations,
        first_hour_close=first_hour_close,
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

    ``data_root`` may be the documented data root (``<repo>/data``, i.e. the value of
    ``TRADING_AGENTIC_DATA_ROOT``), the repo root, or the store directory itself; the
    store is resolved explicitly and an unresolvable or empty target RAISES. The causal
    reader silently returns nothing for a directory that does not contain the shards, so
    without this check a wrong ``data_root`` produced a plausible-looking NO_TRADE
    decision from zero observations instead of failing loudly.

    Uses the frozen causal reader (``oi_dataset_v2.oi_state_at_ms``) and then the
    fail-closed boundary. The verifier-visible path is identical to
    ``prepare_decision``, so TEST_TARGET == RUNTIME_TARGET holds by construction.
    """
    from trading_bot.research.oi_dataset_v2 import oi_state_at_ms, resolve_oi_v2_data_dir_from

    store = resolve_oi_v2_data_dir_from(Path(data_root))
    sym_dir = store / symbol
    if not any(sym_dir.glob(f"{symbol}-oi-5m-*.jsonl")):
        raise FileNotFoundError(
            f"no H6 OI shards for {symbol} under {store} (resolved from {data_root!s}); "
            "refusing to return a decision built from an empty store"
        )
    rows = oi_state_at_ms(_ms(decision_time), symbol, store)
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
