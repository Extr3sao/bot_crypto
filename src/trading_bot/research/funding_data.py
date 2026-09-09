"""Funding-data authority — REAL funding history from public binanceusdm.

C6/DB2-07: the carry strategy requires REAL funding data.  Approximating
funding from OHLCV is PROHIBITED; if the data is unavailable the batch
reports ``INSUFFICIENT_DATA`` instead of substituting anything synthetic.

Provider: public binanceusdm (ccxt ``fetchFundingRateHistory``), no
credentials, no private methods.  Records: provider, symbol, funding
timestamp, observed interval, freshness, PIT provenance and a data
fingerprint (C2) so any cell result can be tied to the exact observations
used.

PIT invariant (C5/DB2-08): returned rates are keyed by their settlement
hour; a decision at time t may only use rates with funding_time <= t.
``restrict_to_window`` enforces the preregistered window end (no peeking
beyond the declared data boundary).
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any

from trading_bot.research.funding_units import (
    canon_funding_interval_s,
    canon_rate_per_period,
)

__all__ = ["FundingDataset", "fetch_funding_history"]

SECONDS_PER_YEAR = 365 * 24 * 3600


@dataclass(frozen=True, slots=True)
class FundingDataset:
    """Immutable, fingerprinted set of REAL funding observations."""

    provider: str                       # e.g. "binanceusdm-public-ccxt"
    symbol: str                         # e.g. "BTC/USDT:USDT"
    rates_by_ms: dict[int, float]       # settlement ms -> decimal per interval
    interval_s: int                     # observed settlement interval
    first_funding_ms: int | None
    last_funding_ms: int | None
    n_observations: int
    fetched_at_ms: int
    source_unit: str                    # provenance of raw unit normalization
    freshness_note: str
    window_start_ms: int | None = None  # preregistered window (PIT bound)
    window_end_ms: int | None = None

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(
            {
                "provider": self.provider,
                "symbol": self.symbol,
                "interval_s": self.interval_s,
                "n": self.n_observations,
                "first_ms": self.first_funding_ms,
                "last_ms": self.last_funding_ms,
                "rates": sorted(self.rates_by_ms.items()),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_meta(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "symbol": self.symbol,
            "interval_s": self.interval_s,
            "n_observations": self.n_observations,
            "first_funding_ms": self.first_funding_ms,
            "last_funding_ms": self.last_funding_ms,
            "fetched_at_ms": self.fetched_at_ms,
            "source_unit": self.source_unit,
            "freshness_note": self.freshness_note,
            "window_start_ms": self.window_start_ms,
            "window_end_ms": self.window_end_ms,
            "data_fingerprint": self.fingerprint,
        }

    def as_ms_map(self) -> dict[int, float]:
        """PIT map for the simulators: settlement ms -> decimal per interval."""
        return dict(self.rates_by_ms)


def fetch_funding_history(
    symbol: str,
    *,
    window_start_ms: int,
    window_end_ms: int,
    provider: str = "binanceusdm-public-ccxt",
    source_unit: str = "decimal_per_interval",
    funding_interval_s: int | str | None = None,
    max_lookback_ms: int = 30 * 24 * 3600 * 1000,
) -> FundingDataset:
    """Fetch REAL funding-rate history for ``symbol`` (public, no creds).

    Fails loudly on provider errors; the caller converts an empty or
    too-shallow history into INSUFFICIENT_DATA (never a synthetic
    substitute).
    """
    import ccxt  # deferred: research dependency (venv)

    start_ms = max(int(window_start_ms), int(window_end_ms) - max_lookback_ms)
    exchange = getattr(ccxt, "binanceusdm")({"enableRateLimit": True})
    try:
        rows: list[list[Any]] = []
        since = start_ms
        while since < window_end_ms:
            page = exchange.fetch_funding_rate_history(
                symbol, since=since, limit=1000)
            if not page:
                break
            rows.extend(page)
            last_t = int(page[-1]["timestamp"])
            if last_t <= since:
                break
            since = last_t + 1
        rates: dict[int, float] = {}
        intervals: list[int] = []
        first_ms = last_ms = None
        for row in rows:
            t = int(row["timestamp"])
            if t < start_ms or t > window_end_ms:
                continue  # PIT window clamp (prereg boundary)
            raw = float(row["fundingRate"])
            rate = canon_rate_per_period(raw, source_unit=source_unit)
            if t in rates and rates[t] != rate:
                raise ValueError(
                    f"CONFLICTING_FUNDING_OBSERVATIONS:{symbol}:{t}")
            rates[t] = rate
            if first_ms is None or t < first_ms:
                first_ms = t
            if last_ms is None or t > last_ms:
                last_ms = t
        ordered = sorted(rates)
        for a, b in zip(ordered, ordered[1:]):
            intervals.append((b - a) * 3_600_000)
        observed_interval = (
            canon_funding_interval_s(funding_interval_s)
            if funding_interval_s is not None
            else (min(set(intervals)) if intervals else 0)
        )
        span_days = (
            (last_ms - first_ms) / 86_400_000.0
            if first_ms is not None and last_ms is not None else 0.0
        )
        freshness = (
            f"span_days={span_days:.2f} "
            f"first={first_ms} last={last_ms} "
            f"(public endpoint depth-limited; recorded, not extended)"
        )
        return FundingDataset(
            provider=provider,
            symbol=symbol,
            rates_by_ms=rates,
            interval_s=observed_interval,
            first_funding_ms=first_ms,
            last_funding_ms=last_ms,
            n_observations=len(rates),
            fetched_at_ms=int(time.time() * 1000),
            source_unit=source_unit,
            freshness_note=freshness,
            window_start_ms=start_ms,
            window_end_ms=window_end_ms,
        )
    finally:
        close = getattr(exchange, "close", None)
        if callable(close):
            close()
