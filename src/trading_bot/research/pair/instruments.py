"""RFC-030 §7/§8 — the leg instrument contract and the no-substitution rule.

A frozen strategy that specifies a ``SPOT`` short may never silently become a
``PERPETUAL`` short (or vice versa). The two have different fees, funding, basis,
liquidity, counterparty mechanics and execution behaviour, so an instrument
change is a *different experiment* and requires a ``NEW_EXPERIMENT_ID`` unless the
frozen specification explicitly allows it.

Every instrument declares, at minimum: identity (asset/venue), type and side,
quote currency, contract/price/quantity increments, minimum notional, whether the
side is shortable and needs borrow, whether funding/basis apply, and — critically
— the **source** of both price data and cost data. An instrument whose cost source
is ``NONE`` cannot be economically executed; that is a declaration, not a failure.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

__all__ = [
    "EXP_ARP_023_LONG_INSTRUMENT",
    "EXP_ARP_023_SHORT_INSTRUMENT",
    "InstrumentSubstitutionError",
    "InstrumentType",
    "LegInstrumentContract",
    "Side",
    "require_same_instrument",
]


class InstrumentType(StrEnum):
    """Instrument classes with materially different economics (§7)."""

    SPOT = "SPOT"
    MARGIN_SPOT = "MARGIN_SPOT"
    PERPETUAL = "PERPETUAL"
    FUTURE = "FUTURE"


class Side(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"


class InstrumentSubstitutionError(Exception):
    """Raised when a frozen instrument is silently replaced by another (§8)."""


@dataclass(frozen=True, slots=True)
class LegInstrumentContract:
    """One leg's tradable instrument declaration (§7).

    ``cost_source == "NONE"`` means no authoritative cost series exists for this
    instrument; the leg is then *declared*, never assumed to be free.
    """

    instrument_id: str
    asset: str
    venue: str
    instrument_type: InstrumentType
    side: Side
    quote_currency: str
    contract_multiplier: float
    price_increment: float
    quantity_increment: float
    minimum_notional: float
    shortable: bool
    borrow_required: bool
    funding_applicable: bool
    basis_applicable: bool
    data_source: str
    cost_source: str

    def __post_init__(self) -> None:
        if self.contract_multiplier <= 0.0:
            raise ValueError("contract_multiplier must be > 0")
        if self.price_increment <= 0.0:
            raise ValueError("price_increment must be > 0")
        if self.quantity_increment <= 0.0:
            raise ValueError("quantity_increment must be > 0")
        if self.minimum_notional < 0.0:
            raise ValueError("minimum_notional must be >= 0")
        if (
            self.side is Side.SHORT
            and self.shortable
            and not self.borrow_required
            and self.instrument_type in (InstrumentType.SPOT, InstrumentType.MARGIN_SPOT)
        ):
            raise ValueError(
                "a shortable SPOT/MARGIN short must declare borrow_required=True; "
                "funding-only shorts are PERPETUAL/FUTURE, not shortable spot"
            )

    @property
    def has_authoritative_cost(self) -> bool:
        """True only when a real cost series exists for this instrument."""
        return self.cost_source not in ("", "NONE")

    def as_dict(self) -> dict[str, Any]:
        return {
            "instrument_id": self.instrument_id,
            "asset": self.asset,
            "venue": self.venue,
            "instrument_type": self.instrument_type.value,
            "side": self.side.value,
            "quote_currency": self.quote_currency,
            "contract_multiplier": self.contract_multiplier,
            "price_increment": self.price_increment,
            "quantity_increment": self.quantity_increment,
            "minimum_notional": self.minimum_notional,
            "shortable": self.shortable,
            "borrow_required": self.borrow_required,
            "funding_applicable": self.funding_applicable,
            "basis_applicable": self.basis_applicable,
            "data_source": self.data_source,
            "cost_source": self.cost_source,
        }


def require_same_instrument(
    frozen: LegInstrumentContract, candidate: LegInstrumentContract
) -> None:
    """Refuse an instrument substitution of a frozen leg (§8).

    Only the *asset* and *side* are allowed to differ between the two legs of a
    pair; the instrument class and venue must match the frozen declaration unless
    the frozen spec explicitly authorises otherwise (which would be a new spec).
    """
    if candidate.asset != frozen.asset:
        raise InstrumentSubstitutionError(
            f"asset changed: frozen {frozen.asset!r} -> candidate {candidate.asset!r}"
        )
    if candidate.side is not frozen.side:
        raise InstrumentSubstitutionError(
            f"side changed: frozen {frozen.side} -> candidate {candidate.side}"
        )
    if candidate.instrument_type is not frozen.instrument_type:
        raise InstrumentSubstitutionError(
            f"instrument type substitution is forbidden without NEW_EXPERIMENT_ID: "
            f"frozen {frozen.instrument_type} -> candidate {candidate.instrument_type}"
        )
    if candidate.venue != frozen.venue:
        raise InstrumentSubstitutionError(
            f"venue changed: frozen {frozen.venue!r} -> candidate {candidate.venue!r}"
        )


# ---------------------------------------------------------------------------
# EXP-ARP-023 frozen declarations (SPEC only — no execution)
# ---------------------------------------------------------------------------

#: The frozen long leg: native Binance 1d USDT spot, costed by COST_MODEL_V3.
EXP_ARP_023_LONG_INSTRUMENT = LegInstrumentContract(
    instrument_id="BINANCE-SPOT-USDT-LONG",
    asset="DYNAMIC_ASSET_UNIVERSE(ARP-006-UNIVERSE-v1)",
    venue="BINANCE",
    instrument_type=InstrumentType.SPOT,
    side=Side.LONG,
    quote_currency="USDT",
    contract_multiplier=1.0,
    price_increment=1e-8,
    quantity_increment=1e-8,
    minimum_notional=5.0,
    shortable=False,
    borrow_required=False,
    funding_applicable=False,
    basis_applicable=False,
    data_source="reports/alpha-diversified-v1/data (native 1d USDT bars)",
    cost_source="COST_MODEL_V3/BINANCE_SPOT_STANDARD_TAKER",
)

#: The frozen short leg. The SPEC requires a *spot* short, which needs borrow; no
#: borrow/funding/basis series exists in the corpus, so the cost source is NONE and
#: the leg is ``EXTERNAL_DATA_REQUIRED``. This declaration is intentionally NOT a
#: perpetual future — substituting one would be §8 instrument substitution.
EXP_ARP_023_SHORT_INSTRUMENT = LegInstrumentContract(
    instrument_id="BINANCE-MARGIN-SPOT-USDT-SHORT",
    asset="DYNAMIC_ASSET_UNIVERSE(ARP-006-UNIVERSE-v1)",
    venue="BINANCE",
    instrument_type=InstrumentType.MARGIN_SPOT,
    side=Side.SHORT,
    quote_currency="USDT",
    contract_multiplier=1.0,
    price_increment=1e-8,
    quantity_increment=1e-8,
    minimum_notional=5.0,
    shortable=True,
    borrow_required=True,
    funding_applicable=False,
    basis_applicable=False,
    data_source="reports/alpha-diversified-v1/data (native 1d USDT bars)",
    cost_source="NONE",
)
