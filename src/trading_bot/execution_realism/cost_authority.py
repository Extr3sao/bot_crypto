"""ExecutionCostAuthority — research/diagnostic cost authority contract.

EXECUTION-REALISM-AND-COST-AUTHORITY-01 §24, §22, §23, §37.

This module defines pure, deterministic, network-free contracts:

  ExchangeExecutionProfile  — exchange-specific fee tier (portable, vendor side)
  CostComponent             — fee/spread/slippage/impact/funding slice with confidence
  CostScenario              — IDEALIZED/BASE/STRESSED/SEVERE bundle (generic, not H6-fitted)
  ExecutionCostAuthority    — research diagnostic authority (one per asset+profile+validity window)

All bps values are round-trip unless stated. ``total_cost_bps`` fields are
TOTAL modeled round-trip friction — consistent with H6_SPEC_V2's phrasing.

Portability: generic cost mechanics live here; exchange-specific numbers live
in ExchangeExecutionProfile. No Binance hardcoding in the generic path.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CostScenarioKind(str, Enum):
    IDEALIZED = "IDEALIZED"  # fees only
    BASE = "BASE"  # fees + median observed friction
    STRESSED = "STRESSED"  # fees + P90 friction
    SEVERE = "SEVERE"  # fees + P99 / conservative upper bound
    UNKNOWN = "UNKNOWN"  # insufficient evidence — do not fabricate


class Confidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ExchangeExecutionProfile:
    """Exchange-specific fee tier (portable, §37).

    No execution semantics live here — just the vendor's fee schedule.
    One profile per (provider, market, vip tier, date range).
    """

    provider: str  # e.g. "binance"
    market: str  # e.g. "usdm" (USD-M futures), "spot", "coinm"
    maker_fee_bps: float
    taker_fee_bps: float
    fee_currency: str = "USDT"
    fee_base: str = "notional"  # fees computed on notional
    vip_tier: str = "VIP0"
    bnb_discount_applied: bool = False
    effective_from: str = ""  # ISO date or empty if unknown
    source_refs: tuple[str, ...] = ()
    notes: str = ""

    def round_trip_bps(self, *, maker_maker: bool = False) -> float:
        """Round-trip bps for a given fill assumption.

        maker_maker=True: both legs are maker (2*maker). Otherwise taker+taker
        (the conservative default for market orders).
        """
        if maker_maker:
            return 2.0 * self.maker_fee_bps
        return 2.0 * self.taker_fee_bps

    def fingerprint(self) -> str:
        payload = json.dumps(
            {
                "provider": self.provider,
                "market": self.market,
                "maker_bps": self.maker_fee_bps,
                "taker_bps": self.taker_fee_bps,
                "vip": self.vip_tier,
                "bnb": self.bnb_discount_applied,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class CostComponent:
    """One slice of TOTAL_COST = fees+spread+slippage+impact+funding+other (§22)."""

    name: str  # e.g. "exchange_fees", "spread", "slippage", "market_impact", "funding"
    bps: float | None  # None => UNKNOWN / not empirically estimated
    confidence: Confidence = Confidence.UNKNOWN
    source: str = ""  # SOURCE_ID from source registry or "assumption:..."
    limitations: str = ""  # scope / conditions

    def is_known(self) -> bool:
        return self.bps is not None


@dataclass(frozen=True, slots=True)
class CostScenario:
    """Generic scenario bundle (§23). Not fitted to any strategy."""

    kind: CostScenarioKind
    label: str
    components: tuple[CostComponent, ...] = ()
    total_cost_bps: float | None = None  # if None, derived as sum of known components
    confidence: Confidence = Confidence.UNKNOWN
    limitations: str = ""

    def derived_total(self) -> float | None:
        known = [c.bps for c in self.components if c.bps is not None]
        unknown = any(c.bps is None for c in self.components)
        if unknown and self.total_cost_bps is None:
            return None  # not fully known
        if self.total_cost_bps is not None:
            return self.total_cost_bps
        return sum(known) if known else None


# Canonical binance USD-M VIP0 profiles (authoritative, 2026-09-12)
# Source: Binance official fee pages (see SOURCE_REGISTRY); archived findings:
#   USP-M regular/VIP0: maker 2 bps (0.02%), taker 5 bps (0.05%) without BNB;
#   with 10% BNB discount: maker 1.8 bps, taker 4.5 bps.
#   COIN-M same 2/5 (regular). Mixed reports of 0.04% taker for some pages
#   are captured as UNKNOWN variant below; canonical remains 5 bps taker.
BINANCE_USDM_VIP0 = ExchangeExecutionProfile(
    provider="binance",
    market="usdm",
    maker_fee_bps=2.0,
    taker_fee_bps=5.0,
    vip_tier="VIP0",
    bnb_discount_applied=False,
    effective_from="2024-01-01",
    source_refs=("OFFICIAL_EXCHANGE_DOC:binance.com/fee/futureFee",),
    notes="Canonical VIP0 USD-M: 2bps maker / 5bps taker (regular user).",
)

BINANCE_USDM_VIP0_BNB = ExchangeExecutionProfile(
    provider="binance",
    market="usdm",
    maker_fee_bps=1.8,
    taker_fee_bps=4.5,
    vip_tier="VIP0",
    bnb_discount_applied=True,
    effective_from="2024-01-01",
    source_refs=("OFFICIAL_EXCHANGE_DOC:binance.com/fee/futureFee",),
    notes="VIP0 with 10% BNB discount applied.",
)


@dataclass(frozen=True, slots=True)
class ExecutionCostAuthority:
    """Research/diagnostic authority (§24). One per asset+profile+validity window.

    Not wired into production trading. Diagnostic only.
    """

    authority_id: str
    provider: str
    market: str
    asset: str  # e.g. "BTCUSDT"
    profile: ExchangeExecutionProfile
    valid_from: str  # ISO date
    valid_to: str  # ISO date or "present"
    scenarios: tuple[CostScenario, ...] = ()
    source_refs: tuple[str, ...] = ()
    confidence: Confidence = Confidence.MEDIUM
    limitations: str = ""

    def scenario(self, kind: CostScenarioKind) -> CostScenario | None:
        for s in self.scenarios:
            if s.kind == kind:
                return s
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_id": self.authority_id,
            "provider": self.provider,
            "market": self.market,
            "asset": self.asset,
            "profile": {
                "provider": self.profile.provider,
                "market": self.profile.market,
                "maker_bps": self.profile.maker_fee_bps,
                "taker_bps": self.profile.taker_fee_bps,
                "vip": self.profile.vip_tier,
                "bnb_discount": self.profile.bnb_discount_applied,
                "fingerprint": self.profile.fingerprint(),
            },
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "scenarios": [
                {
                    "kind": s.kind.value,
                    "label": s.label,
                    "total_bps": s.derived_total(),
                    "confidence": s.confidence.value,
                    "components": [
                        {
                            "name": c.name,
                            "bps": c.bps,
                            "confidence": c.confidence.value,
                            "source": c.source,
                        }
                        for c in s.components
                    ],
                }
                for s in self.scenarios
            ],
            "confidence": self.confidence.value,
            "limitations": self.limitations,
        }

    def fingerprint(self) -> str:
        return hashlib.sha256(
            json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
