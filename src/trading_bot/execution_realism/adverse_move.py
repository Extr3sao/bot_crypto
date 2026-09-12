"""Latency adverse-move offline diagnostic contract §19.

This contract measures price after decision at fixed horizons ONLY where
data granularity supports it. No sub-second results are fabricated from
5m/1h candles. Coverage must be stated explicitly.

The contract is offline and deterministic, operating over an in-memory
tick/aggTrades series. No network I/O.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AdverseMoveHorizons:
    """Price after decision at fixed horizons (bps vs decision price)."""

    h_50ms_bps: float | None = None
    h_100ms_bps: float | None = None
    h_250ms_bps: float | None = None
    h_500ms_bps: float | None = None
    h_1s_bps: float | None = None
    h_5s_bps: float | None = None
    coverage: str = ""  # e.g. "aggTrades 2024-06-05 00:00Z..23:59Z"
    limitations: str = ""


def adverse_move_bps(
    *,
    decision_price: float,
    price_after: float | None,
) -> float | None:
    """Signed adverse move in bps (positive = favorable for long if after>decision).

    For a pure adverse-move diagnostic we return raw movement bps; caller
    applies direction sign (long adverse is price_after < decision_price).
    Returns None if price_after unavailable (insufficient granularity).
    """
    if price_after is None or decision_price <= 0:
        return None
    return (price_after - decision_price) / decision_price * 10_000.0


def adverse_move_for_direction(
    *,
    raw_move_bps: float | None,
    direction: str,
) -> float | None:
    """Convert raw move bps to adverse move for a direction.

    Long: adverse when price falls (negative raw move).
    Short: adverse when price rises (positive raw move).
    Returns positive bps when adverse (cost), negative when favorable.
    """
    if raw_move_bps is None:
        return None
    d = direction.lower()
    if d == "long":
        return -raw_move_bps  # adverse = -raw (fall is adverse)
    if d == "short":
        return raw_move_bps  # adverse = +raw (rise is adverse)
    raise ValueError("direction must be long/short")
