"""Canonical data contracts for admitted research data families (DATA-ONLY checkpoint).

ALPHA-DATA-ADMISSION-01 Track D2 / E1. Frozen schema version: 1.0.0.

Direction semantics (official Binance USD-M aggTrades schema, field 7
``is_buyer_maker`` / archive column ``is_buyer_maker``):

- ``buyer_is_maker == true``  -> the buyer is the MAKER, so the aggressive
  (taker) side is the SELLER  -> ``taker_side = TAKER_SELL``
- ``buyer_is_maker == false`` -> the buyer is the TAKER (aggressor)  ->
  ``taker_side = TAKER_BUY``

Source of authority: binance/binance-public-data README (USD-M Futures
aggTrades), identical to ``/fapi/v1/aggTrades``.

Open interest units (official Binance futures metrics archive, columns
``sum_open_interest`` / ``sum_open_interest_value``):

- ``open_interest_contracts`` <- ``sum_open_interest``: base-asset contracts
  (for USD-M: measured in the BASE asset, e.g. BTC)
- ``open_interest_value``     <- ``sum_open_interest_value``: USDT notional

``openInterest``/``sumOpenInterest`` from the REST openInterestHist endpoint
map to the same two concepts respectively; units are NEVER mixed: contracts
stay contracts, value stays USDT notional.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

SCHEMA_VERSION = "1.0.0"

# Open-interest native cadence (official Binance USD-M daily metrics archive).
# DEF-DATA-OI-001 reconciliation: initially mis-declared as 15m; ground truth
# measured from raw provider files is 5m (288 unique timestamps per complete
# UTC day, inter-arrival deltas uniformly 300s).
OPEN_INTEREST_NATIVE_PERIOD = "5m"
OPEN_INTEREST_EXPECTED_INTERVAL_MS = 300_000
OPEN_INTEREST_ROWS_PER_COMPLETE_UTC_DAY = 288


class TakerSide(str, Enum):
    """Aggressive side derived EXPLICITLY from is_buyer_maker (no inference)."""

    TAKER_BUY = "TAKER_BUY"
    TAKER_SELL = "TAKER_SELL"


@dataclass(frozen=True, slots=True)
class TradeFlowRecord:
    """Canonical aggregate-trade record (Binance USD-M futures)."""

    exchange: str
    market: str
    symbol: str
    agg_trade_id: int
    price: float
    quantity: float
    first_trade_id: int
    last_trade_id: int
    trade_time_ms: int
    buyer_is_maker: bool
    taker_side: TakerSide
    source_file: str
    source_sha256: str


@dataclass(frozen=True, slots=True)
class OpenInterestRecord:
    """Canonical open-interest observation (Binance USD-M futures metrics)."""

    exchange: str
    market: str
    symbol: str
    timestamp_ms: int
    open_interest_contracts: float
    open_interest_value: float
    period: str
    source: str
    source_file: str
    source_sha256: str


def taker_side_from_buyer_is_maker(buyer_is_maker: bool) -> TakerSide:
    """Map the official flag to the aggressive side (documented, no inference)."""
    return TakerSide.TAKER_SELL if buyer_is_maker else TakerSide.TAKER_BUY


def validate_trade_flow_record(rec: TradeFlowRecord) -> list[str]:
    """Structural invariants from Track D2. Returns list of violation strings."""
    errors: list[str] = []
    if rec.price <= 0:
        errors.append("price_not_positive")
    if rec.quantity <= 0:
        errors.append("quantity_not_positive")
    if rec.first_trade_id > rec.last_trade_id:
        errors.append("first_trade_id_gt_last_trade_id")
    if rec.trade_time_ms < 0:
        errors.append("negative_trade_time")
    return errors


def validate_open_interest_record(rec: OpenInterestRecord) -> list[str]:
    """Structural invariants from Track E1. Returns list of violation strings."""
    errors: list[str] = []
    if rec.open_interest_contracts < 0:
        errors.append("negative_open_interest_contracts")
    if rec.open_interest_value < 0:
        errors.append("negative_open_interest_value")
    if rec.timestamp_ms < 0:
        errors.append("negative_timestamp")
    return errors
