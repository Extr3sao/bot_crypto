"""Carry-funding unit contract (Track C5) — resolves DEF-DISCOVERY-001.

POC02-LAUNCH-AND-DISCOVERY-BATCH-02. The Batch-01 carry spec was ambiguous
about funding-rate units and interval, producing 0 qualifying signals. This
module freezes the canonical unit contract BEFORE any Batch-02 execution:

- funding rates arrive as **decimal per period** (e.g. 0.0001 = 1 bp per
  funding interval) — binanceusdm's public API convention;
- the funding interval is **explicit per observation** (default 8h) and
  always taken from consecutive-observation spacing, never assumed;
- PnL accrual is ``notional * rate_decimal`` per period, signed LONG;
- SHORT carry is the negation (perp funding is long-pays-short when
  positive);
- annualization (when reported) is derived, never an input: multiplying
  per-period rates by ``periods_per_day`` from observed spacing.

PIT invariant (C6): every observation carries its exchange timestamp and
``observed_at``; using an observation in a decision requires
``observation.timestamp_ms <= decision_ms``. Violations raise.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

__all__ = [
    "FUNDING_UNIT_CONTRACT_V2",
    "FundingObservation",
    "FundingUnitContract",
    "accrue_long",
    "annualized_rate",
    "contract_fingerprint",
    "periods_per_day",
]


@dataclass(frozen=True, slots=True)
class FundingUnitContract:
    """Immutable unit contract for one experiment identity."""

    version: str
    rate_unit: str  # "decimal_per_period"
    default_interval_hours: float
    pnl_formula: str  # documentation of the signed PnL convention
    annualization: str  # derived-only rule
    data_source: str  # required real funding source (C6)

    def to_dict(self) -> dict[str, str]:
        return {
            "version": self.version,
            "rate_unit": self.rate_unit,
            "default_interval_hours": str(self.default_interval_hours),
            "pnl_formula": self.pnl_formula,
            "annualization": self.annualization,
            "data_source": self.data_source,
        }


FUNDING_UNIT_CONTRACT_V2 = FundingUnitContract(
    version="carry-unit-v2",
    rate_unit="decimal_per_period",
    default_interval_hours=8.0,
    pnl_formula="long_carry_pnl = notional * rate_decimal_per_period; short = -long",
    annualization="derived: rate_per_period * periods_per_day(observed spacing); never an input",
    data_source="binanceusdm fetch_funding_rate_history (public, PIT timestamps)",
)


@dataclass(frozen=True, slots=True)
class FundingObservation:
    """One real funding observation (C6 authority: never synthesized)."""

    timestamp_ms: int  # exchange funding timestamp (PIT)
    rate_decimal: float  # decimal per funding period (e.g. 0.0001 = 1bp)
    source: str  # e.g. "binanceusdm"
    interval_hours: float  # observed spacing to the next/previous observation

    def __post_init__(self) -> None:
        if self.timestamp_ms < 0:
            raise ValueError("funding timestamp_ms must be >= 0")
        if self.interval_hours <= 0:
            raise ValueError("funding interval_hours must be > 0")
        if abs(self.rate_decimal) >= 0.05:
            # >5% per period is not a real perp funding rate: unit misuse.
            raise ValueError(
                f"rate_decimal {self.rate_decimal} out of per-period range "
                "(bps-vs-decimal confusion? 1bp = 0.0001)"
            )


def periods_per_day(obs: FundingObservation) -> float:
    """Periods/day from the OBSERVED interval (never the default)."""
    return 24.0 / obs.interval_hours


def annualized_rate(obs: FundingObservation) -> float:
    """Derived annualization (approximation, reporting only)."""
    return obs.rate_decimal * periods_per_day(obs) * 365.0


def accrue_long(
    *,
    rate_decimal: float,
    notional: float,
) -> float:
    """Signed carry PnL for one period, LONG position.

    Positive funding: longs PAY shorts -> long carry is negative.
    SHORT positions negate this result.
    """
    return -notional * rate_decimal


def contract_fingerprint(contract: FundingUnitContract) -> str:
    canonical = json.dumps(contract.to_dict(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
