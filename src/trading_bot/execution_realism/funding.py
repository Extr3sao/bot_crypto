"""Funding cost — deterministic, network-free, §21/§20.

Funding on Binance USD-M: every 8h at 00:00, 08:00, 16:00 UTC. For a
position held across a funding timestamp, the cost is:

  funding_cost = notional * funding_rate * ( +1 if long pays, -1 if short receives )

Sign convention: funding_rate > 0 means longs pay shorts. So:
  long  funding_cost = +notional * rate   (cost, reduces PnL)
  short funding_cost = -notional * rate   (income, increases PnL)

All inputs are validated. No exchange calls. No H6 evaluation.
"""

from __future__ import annotations


def funding_cost_usdt(
    *,
    position_notional: float,
    direction: str,
    funding_rate: float,
    held_across_funding_event: bool,
) -> float:
    """Funding cost in USDT for one funding event.

    Returns 0.0 if not held across the event. Raises on bad inputs.
    """
    if position_notional < 0:
        raise ValueError("position_notional must be >= 0")
    if direction not in ("long", "short", "LONG", "SHORT"):
        raise ValueError("direction must be long/short")
    if not isinstance(held_across_funding_event, bool):
        raise ValueError("held_across_funding_event must be bool")

    if not held_across_funding_event:
        return 0.0
    if position_notional == 0:
        return 0.0

    d = direction.lower()
    if d == "long":
        return position_notional * funding_rate
    return -position_notional * funding_rate  # short


def funding_cost_bps(
    *,
    funding_rate: float,
    held_across_funding_event: bool,
) -> float:
    """Funding cost in bps of notional for one event (direction-agnostic magnitude).

    Returns the per-event funding rate in bps. Direction is applied by the caller
    via funding_cost_usdt if needed. Returns 0 if not held across event.
    """
    if not held_across_funding_event:
        return 0.0
    return funding_rate * 10_000.0


def funding_events_in_holding(
    *,
    entry_ms: int,
    exit_ms: int,
    funding_interval_ms: int = 8 * 3600 * 1000,
) -> int:
    """Count of funding events strictly inside (entry, exit] that would be charged.

    Binance funding timestamps are at 00:00, 08:00, 16:00 UTC. This helper counts
    how many 8h boundaries are crossed. For a 1h holding (H6), this is typically
    0 unless the bar straddles a funding time. No exchange data needed — pure
    arithmetic on UTC ms.
    """
    if entry_ms >= exit_ms:
        return 0
    # First funding at/after entry+1 (exclusive of entry instant)
    # Funding grid anchored at 00:00 UTC (epoch 0 is 1970-01-01T00:00:00Z).
    def next_funding_at(ms: int) -> int:
        # ceil to next 8h boundary strictly after ms
        rem = ms % funding_interval_ms
        if rem == 0:
            return ms + funding_interval_ms
        return ms + (funding_interval_ms - rem)

    count = 0
    t = next_funding_at(entry_ms)
    while t <= exit_ms:
        count += 1
        t += funding_interval_ms
    return count
