"""Canonical funding-unit contract — DEF-DISCOVERY-001 repair (C5/DB2-06).

DEF-DISCOVERY-001: the batch-01 ``carry_funding`` spec was unit-ambiguous
(funding-window semantics produced zero qualifying signals) and the repair
MUST NOT modify the old spec in place.  Batch-02 evaluates
``carry_funding_v2`` under THIS contract, frozen and fingerprinted before
any batch-02 execution.

Canonical units (the one true representation everywhere in batch-02):

- funding rate  = DECIMAL FRACTION PER FUNDING INTERVAL
                  (e.g. 0.0001 == 0.01% == 1 basis point per interval)
- funding interval = SECONDS between settlements for the symbol, taken
                  from the data source, NEVER assumed (8h = 28800 s is the
                  binanceusdm default but symbols may differ)
- annualization = per_interval_decimal * (SECONDS_PER_YEAR / interval_s)
                  with SECONDS_PER_YEAR = 365*24*3600 (crypto convention)
- funding PnL   = LONG PAYS positive funding:  pnl = -notional * rate
                  SHORT RECEIVES positive funding: pnl = +notional * rate
                  (negative rates flip signs automatically; zero is zero)

PIT invariant (C6/DB2-08): a funding rate settling at time T is first
observable at T; a decision at time t may only use rates with
funding_time <= t.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

__all__ = [
    "FundingUnitContract",
    "canon_funding_interval_s",
    "canon_rate_per_period",
    "annualized_rate",
    "funding_pnl",
    "contract_fingerprint",
]

CONTRACT_ID = "FUNDING-UNITS-CANONICAL-V1"
SECONDS_PER_YEAR = 365 * 24 * 3600

_VALID_SOURCE_UNITS = frozenset(
    {
        "decimal_per_interval",
        "percent_per_interval",
        "bps_per_interval",
    }
)


@dataclass(frozen=True, slots=True)
class FundingUnitContract:
    """Machine-readable freeze of the canonical funding-unit semantics."""

    CONTRACT_ID: str = CONTRACT_ID
    canonical_rate_unit: str = "decimal_fraction_per_interval"
    canonical_interval_unit: str = "seconds"
    seconds_per_year: int = SECONDS_PER_YEAR
    long_positive_funding: str = "PAYS (pnl = -notional * rate)"
    short_positive_funding: str = "RECEIVES (pnl = +notional * rate)"
    pit_invariant: str = "decision t may use rates with funding_time <= t"
    assumption_policy: str = (
        "interval taken from the data source per symbol; never assumed; "
        "missing interval fails closed (no silent 8h default)"
    )
    notes: str = (
        "batch-01 carry_funding spec (unit-ambiguous, DEF-DISCOVERY-001) is "
        "preserved unmodified in git history; carry_funding_v2 is a NEW "
        "fingerprinted spec evaluated under this contract"
    )

    @property
    def fingerprint(self) -> str:
        return contract_fingerprint(self)


def canon_rate_per_period(raw: float, *, source_unit: str) -> float:
    """Normalize a raw funding rate to DECIMAL FRACTION PER INTERVAL.

    - decimal_per_interval: returned as-is (e.g. 0.0001)
    - percent_per_interval: /100 (e.g. 0.01 % -> 0.0001)
    - bps_per_interval: /10_000 (e.g. 1.0 bp -> 0.0001)
    Unknown units fail closed (no guessing).
    """
    if source_unit not in _VALID_SOURCE_UNITS:
        raise ValueError(
            f"UNKNOWN_FUNDING_SOURCE_UNIT:{source_unit}")
    v = float(raw)
    if v != v or v in (float("inf"), float("-inf")):
        raise ValueError("NON_FINITE_FUNDING_RATE")
    if source_unit == "percent_per_interval":
        return v / 100.0
    if source_unit == "bps_per_interval":
        return v / 10_000.0
    return v


def canon_funding_interval_s(raw: int | str | None, *,
                             default_s: int | None = None) -> int:
    """Normalize the funding interval to seconds.

    ``raw`` may be seconds (int) or an ISO-like "8h"/"4h"/"1h" duration.
    ``None`` resolves only when an explicit ``default_s`` is passed by the
    CALLER'S DECLARED policy — the contract itself never assumes 8h.
    """
    if raw is None:
        if default_s is None:
            raise ValueError("FUNDING_INTERVAL_REQUIRED")
        raw = default_s
    if isinstance(raw, str):
        s = raw.strip().lower()
        if s.endswith("h"):
            seconds = int(float(s[:-1]) * 3600)
        elif s.endswith("m"):
            seconds = int(float(s[:-1]) * 60)
        else:
            seconds = int(float(s))
    else:
        seconds = int(raw)
    if seconds <= 0:
        raise ValueError(f"INVALID_FUNDING_INTERVAL:{seconds}")
    return seconds


def annualized_rate(per_interval_decimal: float, interval_s: int) -> float:
    """Annualize a per-interval decimal rate (APR, simple, frozen 365d)."""
    if interval_s <= 0:
        raise ValueError(f"INVALID_FUNDING_INTERVAL:{interval_s}")
    return float(per_interval_decimal) * (SECONDS_PER_YEAR / interval_s)


def funding_pnl(position_side: str, notional: float,
                rate_per_interval: float) -> float:
    """Signed funding PnL for one settlement, in quote currency.

    LONG pays positive funding; SHORT receives it.  Negative rates flip
    the signs automatically.  ``notional`` must be >= 0; the side must be
    exactly "LONG" or "SHORT" — no normalization, no synonyms, no lowercase
    acceptance (fail closed; callers pass the canonical side).
    """
    if position_side not in ("LONG", "SHORT"):
        raise ValueError(f"INVALID_POSITION_SIDE:{position_side}")
    if notional < 0:
        raise ValueError("NEGATIVE_NOTIONAL")
    r = float(rate_per_interval)
    if r != r or r in (float("inf"), float("-inf")):
        raise ValueError("NON_FINITE_FUNDING_RATE")
    if position_side == "LONG":
        return -float(notional) * r
    return float(notional) * r


def contract_fingerprint(contract: FundingUnitContract | None = None) -> str:
    """Deterministic SHA-256 of the canonical contract (C2/DB2-02)."""
    c = contract or FundingUnitContract()
    payload = json.dumps(
        {
            "contract_id": c.CONTRACT_ID,
            "canonical_rate_unit": c.canonical_rate_unit,
            "canonical_interval_unit": c.canonical_interval_unit,
            "seconds_per_year": c.seconds_per_year,
            "long_positive_funding": c.long_positive_funding,
            "short_positive_funding": c.short_positive_funding,
            "pit_invariant": c.pit_invariant,
            "assumption_policy": c.assumption_policy,
            "notes": c.notes,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
