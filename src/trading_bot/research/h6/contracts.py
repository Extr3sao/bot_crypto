"""P7 — immutable H6 contracts.

These contracts carry only causal feature/signal evidence. No economic
outcome fields (PnL, Sharpe, expectancy, future return) are permitted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

DATASET_SHA256 = "16779b7d2eff0dc9e56015c444c2dbe7b67ef083e6cf1877a024a6de74098d99"
SPEC_SHA256 = "f514fecf42b52d2e1c2946cac9dee94b2570d485cb236b9a6c663f46f5bbf148"


class PriceDirection(StrEnum):
    UP = "UP"
    DOWN = "DOWN"
    NONE = "NONE"


class SignalDirection(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    NO_TRADE = "NO_TRADE"


@dataclass(frozen=True, slots=True)
class H6FeatureState:
    asset: str
    decision_time: datetime
    price_open: float
    price_close: float
    price_direction: PriceDirection
    oi_now: float
    oi_previous: float
    delta_oi: float
    rolling_median_delta_oi: float
    rolling_mad_delta_oi: float
    robust_z_oi: float
    decision_eligible: bool
    eligibility_reason: str
    dataset_sha256: str
    spec_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "decision_time": self.decision_time.isoformat(),
            "price_open": self.price_open,
            "price_close": self.price_close,
            "price_direction": self.price_direction.value,
            "oi_now": self.oi_now,
            "oi_previous": self.oi_previous,
            "delta_oi": self.delta_oi,
            "rolling_median_delta_oi": self.rolling_median_delta_oi,
            "rolling_mad_delta_oi": self.rolling_mad_delta_oi,
            "robust_z_oi": self.robust_z_oi,
            "decision_eligible": self.decision_eligible,
            "ineligibility_reason": self.eligibility_reason,
            "dataset_sha256": self.dataset_sha256,
            "spec_sha256": self.spec_sha256,
        }


@dataclass(frozen=True, slots=True)
class H6Signal:
    asset: str
    decision_time: datetime
    direction: SignalDirection
    entry_time: datetime | None
    exit_time: datetime | None
    robust_z_oi: float
    price_direction: PriceDirection
    evidence: str
    dataset_sha256: str
    spec_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "decision_time": self.decision_time.isoformat(),
            "direction": self.direction.value,
            "entry_time": self.entry_time.isoformat() if self.entry_time is not None else None,
            "exit_time": self.exit_time.isoformat() if self.exit_time is not None else None,
            "robust_z_oi": self.robust_z_oi,
            "price_direction": self.price_direction.value,
            "evidence": self.evidence,
            "dataset_sha256": self.dataset_sha256,
            "spec_sha256": self.spec_sha256,
        }
