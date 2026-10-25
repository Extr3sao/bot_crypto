"""Point-in-time microstructure data types (§18-19).

Every record carries three distinct clocks:
  * ``event_time``   — when the event happened at the exchange.
  * ``available_at`` — earliest wall-clock at which the datum was knowable
                       to a consumer (usually the close of the aggregation
                       window, NOT the open).
  * ``receive_time`` — when our collector observed it (forward collection).

The decision clock must satisfy ``available_at <= decision_time``. Features
are computed only from records whose ``available_at`` is not after the bar
they are attached to.
"""

from __future__ import annotations

from dataclasses import dataclass


def _require_non_negative(value: float, name: str) -> None:
    if value < 0.0:
        raise ValueError(f"{name} must be >= 0, got {value}")


@dataclass(frozen=True, slots=True)
class MicroBar:
    """One kline interval enriched with aggressor-flow fields.

    The extra fields (``trades``, ``taker_buy_base``, ``taker_buy_quote``)
    come from Binance klines (columns 8-10). ``available_at`` is the interval
    close + 1 ms, so the bar is usable only on the next decision.
    """

    event_time: int  # open time, ms epoch
    available_at: int  # close time + 1, ms epoch
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float
    trades: int
    taker_buy_base: float
    taker_buy_quote: float

    def __post_init__(self) -> None:
        if self.high < self.low:
            raise ValueError(f"high < low at {self.event_time}")
        if self.close <= 0.0 or self.open <= 0.0:
            raise ValueError(f"non-positive price at {self.event_time}")
        for name in ("volume", "quote_volume", "taker_buy_base", "taker_buy_quote"):
            _require_non_negative(getattr(self, name), name)
        if self.trades < 0:
            raise ValueError(f"trades must be >= 0, got {self.trades}")
        if self.taker_buy_base > self.volume + 1e-9:
            raise ValueError(
                f"taker_buy_base ({self.taker_buy_base}) > volume ({self.volume}) "
                f"at {self.event_time} — inconsistent kline"
            )
        if self.available_at <= self.event_time:
            raise ValueError(
                f"available_at ({self.available_at}) must be after event_time "
                f"({self.event_time})"
            )


@dataclass(frozen=True, slots=True)
class FundingPoint:
    """One realised funding payment (perpetual)."""

    symbol: str
    event_time: int  # fundingTime, ms epoch
    available_at: int
    funding_rate: float
    mark_price: float

    def __post_init__(self) -> None:
        if self.mark_price <= 0.0:
            raise ValueError("mark_price must be > 0")
        if self.available_at < self.event_time:
            raise ValueError("available_at must be >= event_time")


@dataclass(frozen=True, slots=True)
class PremiumPoint:
    """Premium-index sample (futures premium vs spot index)."""

    symbol: str
    event_time: int
    available_at: int
    premium: float  # (mark - index) / index, as fraction

    def __post_init__(self) -> None:
        if self.available_at < self.event_time:
            raise ValueError("available_at must be >= event_time")


@dataclass(frozen=True, slots=True)
class OpenInterestPoint:
    """Open-interest histogram sample (30-day retention on Binance)."""

    symbol: str
    event_time: int
    available_at: int
    sum_open_interest: float
    sum_open_interest_value: float

    def __post_init__(self) -> None:
        if self.sum_open_interest < 0.0 or self.sum_open_interest_value < 0.0:
            raise ValueError("open interest must be >= 0")
        if self.available_at < self.event_time:
            raise ValueError("available_at must be >= event_time")


@dataclass(frozen=True, slots=True)
class BasisPoint:
    """Spot/perpetual basis sample."""

    symbol: str
    event_time: int
    available_at: int
    index_price: float
    futures_price: float
    basis: float
    basis_rate: float

    def __post_init__(self) -> None:
        if self.index_price <= 0.0 or self.futures_price <= 0.0:
            raise ValueError("prices must be > 0")
        if self.available_at < self.event_time:
            raise ValueError("available_at must be >= event_time")


__all__ = [
    "BasisPoint",
    "FundingPoint",
    "MicroBar",
    "OpenInterestPoint",
    "PremiumPoint",
]
