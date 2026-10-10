"""InstrumentSpec — the exact contract a futures position is priced against.

Every field is either read from the venue's own payload or explicitly declared
missing with ``None``/``[]``. An instrument whose contract type or position mode
has no verified model refuses to produce a spec, raising
``InstrumentNotSupported`` (RFC-048 §4: ``INSTRUMENT_NOT_SUPPORTED``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import Any

from .contracts import ContractType, InstrumentNotSupported, PositionMode, RejectionCode

__all__ = [
    "InstrumentRegistry",
    "InstrumentSpec",
    "MaintenanceBracket",
    "load_instrument_registry",
]

#: Contract types this RFC implements. Anything else is refused by name.
SUPPORTED_CONTRACT_TYPES: frozenset[ContractType] = frozenset({ContractType.LINEAR_PERPETUAL})
#: Position modes this RFC implements. Cross margin is NOT validated.
SUPPORTED_POSITION_MODES: frozenset[PositionMode] = frozenset({PositionMode.ISOLATED})


@dataclass(frozen=True, slots=True)
class MaintenanceBracket:
    """One row of the venue's maintenance-margin ladder.

    ``maintenance_margin = notional * rate - cum_maintenance_amount``; the
    continuity of the ladder across brackets is asserted by the registry, so a
    truncated or invented bracket table cannot be used silently.
    """

    bracket_seq: int
    notional_floor: float
    notional_cap: float
    maintenance_margin_rate: float
    cum_maintenance_amount: float
    max_open_pos_leverage: int
    min_open_pos_leverage: int

    def maintenance_margin(self, notional: float) -> float:
        return max(notional * self.maintenance_margin_rate - self.cum_maintenance_amount, 0.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "bracket_seq": self.bracket_seq,
            "notional_floor": self.notional_floor,
            "notional_cap": self.notional_cap,
            "maintenance_margin_rate": self.maintenance_margin_rate,
            "cum_maintenance_amount": self.cum_maintenance_amount,
            "max_open_pos_leverage": self.max_open_pos_leverage,
            "min_open_pos_leverage": self.min_open_pos_leverage,
        }


@dataclass(frozen=True, slots=True)
class InstrumentSpec:
    """Instrument contract (§4). Frozen: the runtime never mutates a contract."""

    instrument_id: str
    venue: str
    venue_symbol: str
    contract_type: ContractType
    collateral_asset: str
    settlement_asset: str
    base_asset: str
    quote_asset: str
    contract_multiplier: float
    quantity_step: float
    minimum_notional: float
    price_tick: float
    maintenance_margin_brackets: tuple[MaintenanceBracket, ...]
    quantity_min: float = 0.0
    quantity_max: float | None = None
    maximum_notional: float | None = None
    maker_bps: float | None = None
    taker_bps: float | None = None
    fee_source: str = ""
    fee_verified: bool = False
    funding_interval_ms: int | None = None
    liquidation_fee_rate: float | None = None
    supported_position_modes: tuple[PositionMode, ...] = (PositionMode.ISOLATED,)
    regulatory_eligibility_status: str = "PRODUCT_ELIGIBILITY_UNKNOWN"
    research_allowed: bool = True
    production_eligible: bool = False
    source_version: str = ""
    source_hash: str = ""
    #: sha256 of the raw venue payload the maintenance ladder came from, so a
    #: verifier can prove the ladder was not invented.
    source_hash_brackets: str = ""
    effective_timestamp_ms: int | None = None
    unsupported_reason: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    # -- capability questions ------------------------------------------------

    @property
    def is_linear(self) -> bool:
        return self.contract_type is ContractType.LINEAR_PERPETUAL

    @property
    def supports_isolated(self) -> bool:
        return PositionMode.ISOLATED in self.supported_position_modes

    @property
    def margin_ladder_complete(self) -> bool:
        """A ladder is usable only if it is non-empty, ordered and continuous."""
        if not self.maintenance_margin_brackets:
            return False
        brackets = self.maintenance_margin_brackets
        if brackets[0].notional_floor != 0.0:
            return False
        for lower, upper in pairwise(brackets):
            if upper.notional_floor != lower.notional_cap:
                return False
            if upper.bracket_seq != lower.bracket_seq + 1:
                return False
        return True

    def ensure_usable(self, position_mode: PositionMode = PositionMode.ISOLATED) -> None:
        """Refuse, by name, any contract this engine cannot model honestly."""
        if self.contract_type not in SUPPORTED_CONTRACT_TYPES:
            raise InstrumentNotSupported(
                self.instrument_id,
                f"contract type {self.contract_type.value} has no verified model"
                + (f" ({self.unsupported_reason})" if self.unsupported_reason else ""),
            )
        if position_mode not in SUPPORTED_POSITION_MODES:
            raise InstrumentNotSupported(
                self.instrument_id, f"position mode {position_mode.value} is not validated"
            )
        if position_mode not in self.supported_position_modes:
            raise InstrumentNotSupported(
                self.instrument_id,
                f"venue does not declare support for {position_mode.value}",
            )
        if self.contract_multiplier != 1.0:
            raise InstrumentNotSupported(
                self.instrument_id,
                f"contract multiplier {self.contract_multiplier} is not modelled (only 1.0)",
            )
        if not self.margin_ladder_complete:
            raise InstrumentNotSupported(
                self.instrument_id, "maintenance margin ladder is missing or discontinuous"
            )
        if self.quantity_step <= 0 or self.price_tick <= 0:
            raise InstrumentNotSupported(self.instrument_id, "step/tick not usable")

    def unsupported_reason_code(self) -> RejectionCode:
        if self.contract_type is not ContractType.LINEAR_PERPETUAL:
            return RejectionCode.CONTRACT_TYPE_NOT_IMPLEMENTED
        return RejectionCode.INSTRUMENT_NOT_SUPPORTED

    def bracket_for(self, notional: float) -> MaintenanceBracket:
        """The bracket whose notional window contains ``notional``."""
        if not self.maintenance_margin_brackets:
            raise InstrumentNotSupported(self.instrument_id, "no maintenance margin brackets")
        for bracket in self.maintenance_margin_brackets:
            if bracket.notional_floor <= notional <= bracket.notional_cap:
                return bracket
        return self.maintenance_margin_brackets[-1]

    def worst_bracket_for(self, a: float, b: float) -> MaintenanceBracket:
        """The most expensive bracket touched anywhere in ``[min(a,b), max(a,b)]``.

        A higher bracket always has a lower-or-equal leverage ceiling and a
        higher rate; taking the worst one keeps the margin requirement
        conservative when the notional can move between entry and stress.
        """
        low, high = (a, b) if a <= b else (b, a)
        touched = [
            bracket
            for bracket in self.maintenance_margin_brackets
            if bracket.notional_cap >= low and bracket.notional_floor <= high
        ]
        if not touched:
            return self.bracket_for(low)
        return max(touched, key=lambda br: br.maintenance_margin_rate)

    def leverage_ceiling_for(self, notional: float) -> int:
        """The venue's own max leverage for the bracket that notional lands in."""
        return self.bracket_for(notional).max_open_pos_leverage

    def round_quantity_down(self, quantity: float) -> float:
        """Never round up: rounding must never increase approved risk."""
        if self.quantity_step <= 0:
            return 0.0
        steps = int(quantity / self.quantity_step + 1e-9)
        return round(steps * self.quantity_step, 12)

    def to_dict(self) -> dict[str, Any]:
        return {
            "instrument_id": self.instrument_id,
            "venue": self.venue,
            "venue_symbol": self.venue_symbol,
            "contract_type": self.contract_type.value,
            "collateral_asset": self.collateral_asset,
            "settlement_asset": self.settlement_asset,
            "base_asset": self.base_asset,
            "quote_asset": self.quote_asset,
            "contract_multiplier": self.contract_multiplier,
            "quantity_step": self.quantity_step,
            "quantity_min": self.quantity_min,
            "quantity_max": self.quantity_max,
            "price_tick": self.price_tick,
            "minimum_notional": self.minimum_notional,
            "maximum_notional": self.maximum_notional,
            "maintenance_margin_brackets": [b.to_dict() for b in self.maintenance_margin_brackets],
            "maker_bps": self.maker_bps,
            "taker_bps": self.taker_bps,
            "fee_source": self.fee_source,
            "fee_verified": self.fee_verified,
            "funding_interval_ms": self.funding_interval_ms,
            "liquidation_fee_rate": self.liquidation_fee_rate,
            "supported_position_modes": [m.value for m in self.supported_position_modes],
            "regulatory_eligibility_status": self.regulatory_eligibility_status,
            "research_allowed": self.research_allowed,
            "production_eligible": self.production_eligible,
            "source_version": self.source_version,
            "source_hash": self.source_hash,
            "source_hash_brackets": self.source_hash_brackets,
            "effective_timestamp_ms": self.effective_timestamp_ms,
        }


class InstrumentRegistry:
    """Read-only registry of declared instruments."""

    def __init__(self, instruments: dict[str, InstrumentSpec]) -> None:
        self._instruments = dict(instruments)

    def get(self, instrument_id: str) -> InstrumentSpec:
        try:
            return self._instruments[instrument_id]
        except KeyError as exc:  # pragma: no cover - a test pins the message
            raise KeyError(f"unknown instrument {instrument_id!r}") from exc

    def ids(self) -> list[str]:
        return sorted(self._instruments)

    def supported_ids(self) -> list[str]:
        out: list[str] = []
        for key, spec in self._instruments.items():
            try:
                spec.ensure_usable()
            except InstrumentNotSupported:
                continue
            out.append(key)
        return sorted(out)

    def __len__(self) -> int:
        return len(self._instruments)


def _brackets(payload: list[dict[str, Any]]) -> tuple[MaintenanceBracket, ...]:
    return tuple(
        MaintenanceBracket(
            bracket_seq=int(row["bracket_seq"]),
            notional_floor=float(row["notional_floor"]),
            notional_cap=float(row["notional_cap"]),
            maintenance_margin_rate=float(row["maintenance_margin_rate"]),
            cum_maintenance_amount=float(row["cum_maintenance_amount"]),
            max_open_pos_leverage=int(row["max_open_pos_leverage"]),
            min_open_pos_leverage=int(row["min_open_pos_leverage"]),
        )
        for row in payload
    )


def spec_from_dict(row: dict[str, Any]) -> InstrumentSpec:
    """Build a spec from a derived fixture. Never fabricates a missing field."""
    fee = row.get("fee_schedule") or {}
    funding = row.get("funding_schedule") or {}
    modes: list[PositionMode] = []
    for raw_mode in row.get("supported_position_modes", []):
        try:
            modes.append(PositionMode(raw_mode))
        except ValueError:
            continue
    return InstrumentSpec(
        instrument_id=str(row["instrument_id"]),
        venue=str(row["venue"]),
        venue_symbol=str(row["venue_symbol"]),
        contract_type=ContractType(row["contract_type"]),
        collateral_asset=str(row["collateral_asset"]),
        settlement_asset=str(row["settlement_asset"]),
        base_asset=str(row["base_asset"]),
        quote_asset=str(row["quote_asset"]),
        contract_multiplier=float(row.get("contract_multiplier") or 0.0),
        quantity_step=float(row.get("quantity_step") or 0.0),
        quantity_min=float(row.get("quantity_min") or 0.0),
        quantity_max=(
            float(row["quantity_max"]) if row.get("quantity_max") is not None else None
        ),
        price_tick=float(row.get("price_tick") or 0.0),
        minimum_notional=float(row.get("minimum_notional") or 0.0),
        maximum_notional=(
            float(row["maximum_notional"]) if row.get("maximum_notional") is not None else None
        ),
        maintenance_margin_brackets=_brackets(row.get("maintenance_margin_brackets") or []),
        maker_bps=float(fee["maker_bps"]) if fee.get("maker_bps") is not None else None,
        taker_bps=float(fee["taker_bps"]) if fee.get("taker_bps") is not None else None,
        fee_source=str(fee.get("source", "")),
        fee_verified=bool(fee.get("verified_against_account", False)),
        funding_interval_ms=(
            int(funding["interval_ms"]) if funding.get("interval_ms") is not None else None
        ),
        liquidation_fee_rate=(
            float(row["liquidation_fee_rate"])
            if row.get("liquidation_fee_rate") is not None
            else None
        ),
        supported_position_modes=tuple(modes),
        regulatory_eligibility_status=str(
            row.get("regulatory_eligibility_status", "PRODUCT_ELIGIBILITY_UNKNOWN")
        ),
        research_allowed=bool(row.get("research_allowed", True)),
        production_eligible=bool(row.get("production_eligible", False)),
        source_version=str(row.get("source_version", "")),
        source_hash=str(row.get("source_hash", "")),
        source_hash_brackets=str(row.get("source_hash_brackets", "")),
        effective_timestamp_ms=(
            int(row["effective_timestamp_ms"])
            if row.get("effective_timestamp_ms") is not None
            else None
        ),
        unsupported_reason=str(row.get("unsupported_reason", "")),
        raw=dict(row),
    )


def load_instrument_registry(path: Path) -> InstrumentRegistry:
    """Load ``data/rfc048/INSTRUMENTS.json`` (or any file of the same shape)."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    instruments = {
        row["instrument_id"]: spec_from_dict(row) for row in payload["instruments"]
    }
    return InstrumentRegistry(instruments)
