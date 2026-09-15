"""In-memory synthetic fixtures for the ARC-03 prereg unit tests.

No data root, no network, no clock. Every fixture is deterministic so the frozen contract
can be tested without ever touching real (economic) data.
"""

from __future__ import annotations

from trading_bot.research.arc03.arc03_authority import BAR_MS, DAY_MS, Kline5m
from trading_bot.research.arc03.arc03_funding import FundingSeries

#: A stable synthetic start instant (a 5m boundary), far from any real authority window.
T0_MS = 1_600_000_200_000 - (1_600_000_200_000 % BAR_MS)


def build_partition(
    symbol: str,
    *,
    bars: int,
    start_ms: int = T0_MS,
    volume: float = 100.0,
    open_price: float = 100.0,
    high_offset: float | None = None,
    low_offset: float | None = None,
) -> dict:
    """Build a flat synthetic partition as a raw dict of arrays.

    ``high_offset``/``low_offset`` default to a constant 1.0/1.0 band around the open.
    """
    hi = 1.0 if high_offset is None else high_offset
    lo = 1.0 if low_offset is None else low_offset
    t = [start_ms + i * BAR_MS for i in range(bars)]
    rows = {
        "symbol": symbol,
        "t": t,
        "ct": [x + BAR_MS - 1 for x in t],
        "o": [open_price] * bars,
        "h": [open_price + hi] * bars,
        "l": [open_price - lo] * bars,
        "c": [open_price] * bars,
        "v": [volume] * bars,
        "qv": [volume * open_price] * bars,
        "n": [10] * bars,
        "tb": [volume / 2] * bars,
        "tq": [volume * open_price / 2] * bars,
    }
    return rows


def to_kline5m(rows: dict, *, sha256: str = "0" * 64, path: str = "synthetic") -> Kline5m:
    t = tuple(int(x) for x in rows["t"])
    return Kline5m(
        symbol=rows["symbol"],
        t=t,
        ct=tuple(int(x) for x in rows["ct"]),
        o=tuple(float(x) for x in rows["o"]),
        h=tuple(float(x) for x in rows["h"]),
        l=tuple(float(x) for x in rows["l"]),
        c=tuple(float(x) for x in rows["c"]),
        v=tuple(float(x) for x in rows["v"]),
        qv=tuple(float(x) for x in rows["qv"]),
        n=tuple(int(x) for x in rows["n"]),
        tb=tuple(float(x) for x in rows["tb"]),
        tq=tuple(float(x) for x in rows["tq"]),
        sha256=sha256,
        path=path,
        rows=len(t),
        index={x: i for i, x in enumerate(t)},
    )


def _index_of(rows: dict, open_time_ms: int) -> int:
    return rows["t"].index(open_time_ms)


def reference_slot_offsets(days: int = 30) -> list[int]:
    return [DAY_MS * j for j in range(1, days + 1)]


def make_up_push_exhaustion(
    rows: dict,
    *,
    signal_index: int,
    ref_volume: float = 100.0,
    ref_range: float = 2.0,
) -> dict:
    """Turn bar ``signal_index`` into a SHORT signal: participation record + excursion
    record + up-push rejection (close back below the high by more than half the range).

    The 30 same-slot references are set to ``ref_volume`` / ``ref_range`` so the record
    conditions hold by construction.
    """
    bar_open = rows["t"][signal_index]
    for off in reference_slot_offsets():
        j = _index_of(rows, bar_open - off)
        rows["v"][j] = ref_volume
        rows["h"][j] = rows["o"][j] + ref_range / 2.0
        rows["l"][j] = rows["o"][j] - ref_range / 2.0
        rows["c"][j] = rows["o"][j]

    o = 100.0
    hi = o + 3.0          # range = 4.0 > ref_range
    lo = o - 1.0
    c = o + 1.0           # body > 0, (hi - c) = 2.0 > range/2 = 2.0? no: 2.0 > 2.0 is False
    c = o + 0.9           # body > 0, (hi - c) = 2.1 > 2.0 -> exhaustion holds
    rows["o"][signal_index] = o
    rows["h"][signal_index] = hi
    rows["l"][signal_index] = lo
    rows["c"][signal_index] = c
    rows["v"][signal_index] = ref_volume * 5.0   # participation record
    return rows


def make_down_push_exhaustion(
    rows: dict,
    *,
    signal_index: int,
    ref_volume: float = 100.0,
    ref_range: float = 2.0,
) -> dict:
    """Turn bar ``signal_index`` into a LONG signal (down-push rejected)."""
    bar_open = rows["t"][signal_index]
    for off in reference_slot_offsets():
        j = _index_of(rows, bar_open - off)
        rows["v"][j] = ref_volume
        rows["h"][j] = rows["o"][j] + ref_range / 2.0
        rows["l"][j] = rows["o"][j] - ref_range / 2.0
        rows["c"][j] = rows["o"][j]

    o = 100.0
    hi = o + 1.0
    lo = o - 3.0          # range = 4.0
    c = o - 0.9           # body < 0, (c - lo) = 2.1 > 2.0 -> exhaustion holds
    rows["o"][signal_index] = o
    rows["h"][signal_index] = hi
    rows["l"][signal_index] = lo
    rows["c"][signal_index] = c
    rows["v"][signal_index] = ref_volume * 5.0
    return rows


def set_prices(rows: dict, *, index: int, open_price: float) -> dict:
    rows["o"][index] = open_price
    return rows


def make_funding(
    symbol: str,
    *,
    settlements_ms: list[int],
    rates: list[float],
    interval_hours: int = 8,
) -> FundingSeries:
    if len(settlements_ms) != len(rates):
        raise ValueError("settlements and rates must be the same length")
    return FundingSeries(
        symbol=symbol,
        funding_time_ms=tuple(int(x) for x in settlements_ms),
        funding_rate=tuple(float(x) for x in rates),
        interval_hours=tuple([interval_hours] * len(settlements_ms)),
        sha256="f" * 64,
        path="synthetic",
        rows=len(settlements_ms),
        matches_arc01_authority=True,
    )


__all__ = [
    "T0_MS",
    "build_partition",
    "make_down_push_exhaustion",
    "make_funding",
    "make_up_push_exhaustion",
    "reference_slot_offsets",
    "set_prices",
    "to_kline5m",
]
