"""P8 — H6 feature engine implementing frozen spec semantics.

No future data is used. All OI observations must satisfy
`oi_time <= decision_time`. OI completeness requires exactly 12
distinct 5m snapshots in the completed decision hour. Rolling state
is computed strictly from completed hourly changes strictly before
the decision time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Sequence

from trading_bot.research.h6.contracts import (
    H6FeatureState,
    H6Signal,
    PriceDirection,
    SignalDirection,
)

# V4 repair (V3-AUTH-001): no hash literals here. Both values come from the single
# versioned runtime authority binding and resolve to UNBOUND while unbound.
def _spec_sha256() -> str:
    from trading_bot.research.h6 import runtime_authority as _ra

    return _ra.spec_sha256_or_unbound()


def _dataset_sha256() -> str:
    from trading_bot.research.h6 import runtime_authority as _ra

    return _ra.dataset_sha256_or_unbound()


def __getattr__(name: str):  # PEP 562 back-compat for attribute-style access
    if name == "SPEC_SHA256":
        return _spec_sha256()
    if name == "DATASET_SHA256":
        return _dataset_sha256()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


@dataclass(frozen=True, slots=True)
class ObservedOI:
    """One 5m OI snapshot for a single asset."""

    oi_time: datetime
    sum_open_interest: float
    sum_open_interest_value: float


@dataclass(frozen=True, slots=True)
class CompletedHourPrice:
    """Completed 1h price context for one asset."""

    bucket_close_time: datetime
    open: float
    close: float


@dataclass(frozen=True, slots=True)
class CompletedHourOI:
    """Completed hourly OI aggregate derived from 5m snapshots."""

    hour_close_time: datetime
    oi_last_snapshot: float
    snapshot_count: int


class H6FeatureEngine:
    """Frozen H6 causal feature computation.

    Public API is intentionally small and symbol-aware in case a symbol
    parameter is needed by the importer; the engine itself remains pure
    and stateless beyond its constructor.
    """

    def __init__(self, *, symbol: str | None = None) -> None:
        self._symbol = symbol

    def compute_feature_state(
        self,
        asset: str,
        decision_time: datetime,
        price: CompletedHourPrice,
        current_hour_oi: CompletedHourOI,
        previous_hour_oi: CompletedHourOI | None,
        completed_hour_changes_before: Sequence[tuple[datetime, float]],
    ) -> H6FeatureState:
        if current_hour_oi.snapshot_count != 12:
            return self._ineligible(
                asset,
                decision_time,
                price,
                "CURRENT_HOUR_OI_COMPLETENESS != 12",
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
            )

        if previous_hour_oi is None:
            return self._ineligible(
                asset,
                decision_time,
                price,
                "previous_hour_oi missing",
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
            )

        if previous_hour_oi.snapshot_count != 12:
            return self._ineligible(
                asset,
                decision_time,
                price,
                "PREVIOUS_HOUR_OI_COMPLETENESS != 12",
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
            )

        delta_oi = current_hour_oi.oi_last_snapshot - previous_hour_oi.oi_last_snapshot

        median, mad = _robust_median_and_mad(completed_hour_changes_before)

        if mad == 0.0 or len(completed_hour_changes_before) < 336:
            return self._ineligible(
                asset,
                decision_time,
                price,
                "insufficient_history_or_mad_zero",
                current_hour_oi.oi_last_snapshot,
                previous_hour_oi.oi_last_snapshot,
                delta_oi,
                median,
                mad,
                float("nan"),
            )

        robust_z = (delta_oi - median) / (1.4826 * mad)

        return H6FeatureState(
            asset=asset,
            decision_time=decision_time,
            price_open=price.open,
            price_close=price.close,
            price_direction=_price_direction(price.open, price.close),
            oi_now=current_hour_oi.oi_last_snapshot,
            oi_previous=previous_hour_oi.oi_last_snapshot,
            delta_oi=delta_oi,
            rolling_median_delta_oi=median,
            rolling_mad_delta_oi=mad,
            robust_z_oi=robust_z,
            decision_eligible=True,
            eligibility_reason="eligible",
            dataset_sha256=_dataset_sha256(),
            spec_sha256=_spec_sha256(),
        )

    def _ineligible(
        self,
        asset: str,
        decision_time: datetime,
        price: CompletedHourPrice,
        reason: str,
        oi_now: float,
        oi_previous: float,
        delta_oi: float,
        median: float,
        mad: float,
        robust_z: float,
    ) -> H6FeatureState:
        return H6FeatureState(
            asset=asset,
            decision_time=decision_time,
            price_open=price.open,
            price_close=price.close,
            price_direction=_price_direction(price.open, price.close),
            oi_now=oi_now,
            oi_previous=oi_previous,
            delta_oi=delta_oi,
            rolling_median_delta_oi=median,
            rolling_mad_delta_oi=mad,
            robust_z_oi=robust_z,
            decision_eligible=False,
            eligibility_reason=reason,
            dataset_sha256=_dataset_sha256(),
            spec_sha256=_spec_sha256(),
        )


def _price_direction(open: float, close: float) -> PriceDirection:
    if close > open:
        return PriceDirection.UP
    if close < open:
        return PriceDirection.DOWN
    return PriceDirection.NONE


def _robust_median_and_mad(
    values: Sequence[tuple[datetime, float]],
) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    xs = sorted(v for _t, v in values)
    n = len(xs)
    median = (xs[(n - 1) // 2] + xs[n // 2]) / 2.0
    abs_devs = sorted(abs(v - median) for v in xs)
    mad = (abs_devs[(n - 1) // 2] + abs_devs[n // 2]) / 2.0
    return median, mad


def compute_signal(feature: H6FeatureState) -> H6Signal:
    # EXT-CONS-004 / OI_SIGN_RULE (H6 V2): qualifying expansion requires BOTH delta_oi > 0 AND z >= 1.0.
    # A contraction with z >= 1 due to negative median/MAD must NOT qualify.
    if not feature.decision_eligible:
        return H6Signal(
            asset=feature.asset,
            decision_time=feature.decision_time,
            direction=SignalDirection.NO_TRADE,
            entry_time=None,
            exit_time=None,
            robust_z_oi=feature.robust_z_oi,
            price_direction=feature.price_direction,
            evidence=feature.eligibility_reason,
            dataset_sha256=_dataset_sha256(),
            spec_sha256=_spec_sha256(),
        )

    if feature.price_direction == PriceDirection.NONE:
        return H6Signal(
            asset=feature.asset,
            decision_time=feature.decision_time,
            direction=SignalDirection.NO_TRADE,
            entry_time=None,
            exit_time=None,
            robust_z_oi=feature.robust_z_oi,
            price_direction=feature.price_direction,
            evidence="price flat => NO_TRADE",
            dataset_sha256=_dataset_sha256(),
            spec_sha256=_spec_sha256(),
        )

    if feature.robust_z_oi < 1.0:
        return H6Signal(
            asset=feature.asset,
            decision_time=feature.decision_time,
            direction=SignalDirection.NO_TRADE,
            entry_time=None,
            exit_time=None,
            robust_z_oi=feature.robust_z_oi,
            price_direction=feature.price_direction,
            evidence="z_oi < 1.0 => NO_TRADE",
            dataset_sha256=_dataset_sha256(),
            spec_sha256=_spec_sha256(),
        )

    if feature.delta_oi <= 0:
        return H6Signal(
            asset=feature.asset,
            decision_time=feature.decision_time,
            direction=SignalDirection.NO_TRADE,
            entry_time=None,
            exit_time=None,
            robust_z_oi=feature.robust_z_oi,
            price_direction=feature.price_direction,
            evidence=f"delta_oi={feature.delta_oi} <=0 => NO_TRADE (raw-sign rule; contraction never qualifies even if z>=1)",
            dataset_sha256=_dataset_sha256(),
            spec_sha256=_spec_sha256(),
        )

    if feature.price_direction == PriceDirection.UP:
        direction = SignalDirection.LONG
        evidence = "UP + z_oi >= 1.0 => LONG"
    else:
        direction = SignalDirection.SHORT
        evidence = "DOWN + z_oi >= 1.0 => SHORT"

    decision_dt = feature.decision_time
    entry_time = decision_dt + timedelta(hours=1)
    exit_time = entry_time + timedelta(hours=1)

    return H6Signal(
        asset=feature.asset,
        decision_time=feature.decision_time,
        direction=direction,
        entry_time=entry_time,
        exit_time=exit_time,
        robust_z_oi=feature.robust_z_oi,
        price_direction=feature.price_direction,
        evidence=evidence,
        dataset_sha256=_dataset_sha256(),
        spec_sha256=_spec_sha256(),
    )
