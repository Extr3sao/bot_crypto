"""execution — the price an opinion may be filled at, and for how long.

A decision is formed on a bar's **close**, which is the next bar's open. That instant is
when the opinion exists; the price it can be filled at is the first quote that exists at
or after the *answer* reached us, not the quote that was already there when the question
was asked.

This module answers two questions the lane used to answer implicitly and wrongly:

* **Which price?** Only a quote the replay actually has: a bar open. Asking for a price
  strictly inside a bar raises :class:`InsufficientResolution` instead of interpolating,
  because a four-number OHLC bar does not say whether the high or the low came first, and
  a fill invented from it is a fill at a price nobody could have taken. The consequence is
  declared rather than hidden: with a one-hour grid, a sub-bar latency costs one whole bar
  of delay.
* **For how long?** An opinion describes the state at its decision instant. Filling it
  two hours later is trading a stale view, so the quote must be within
  ``max_opinion_age_ms`` of the decision. That is the window in which a delay is *cost of
  execution* rather than a different trade.

The expiry is not a new rejection class: it is the same ``LATE_RESPONSE`` the Block A
guard reported, now with the age that caused it, because a late answer and an unexecutable
price were two names for one event.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Any, Protocol, runtime_checkable

#: The only price source this replay can prove it had. Named so a reader can audit it.
BAR_OPEN_SOURCE = "bar_open"


class InsufficientResolution(ValueError):
    """A price inside a bar is not knowable from OHLC. Refused, never interpolated."""


@dataclass(frozen=True, slots=True)
class Quote:
    """An executable price, with where and when it came from."""

    symbol: str
    ts_ms: int
    price: float
    #: ``bar_open`` today. A future feed with real ticks names itself here, so the
    #: ledger says which resolution produced the fill instead of assuming one.
    source: str = BAR_OPEN_SOURCE
    bar_open_ms: int = 0

    def __post_init__(self) -> None:
        if self.price <= 0:
            raise ValueError("a quote must have a positive price")
        if self.bar_open_ms == 0:
            object.__setattr__(self, "bar_open_ms", self.ts_ms)

    def to_row(self) -> dict[str, Any]:
        return {
            "quote_ts_ms": self.ts_ms,
            "quote_price": self.price,
            "quote_source": self.source,
            "quote_bar_open_ms": self.bar_open_ms,
        }


@dataclass(frozen=True, slots=True)
class CoverageProof:
    """Independent evidence that a missing bar is not a market outage.

    An OHLC series with a hole in it cannot say whether the venue was closed, whether the
    feed dropped, or whether nothing traded. A hole is therefore **not** permission to
    trade: the next timestamp is later than the gap, not proof that the gap was priced.
    This record is the only thing that turns a hole into an executable interval, and it
    comes from a *separate* source that names itself.
    """

    symbol: str
    missing_bar_open_ms: int
    source: str
    quotes: tuple[Quote, ...]
    venue_open: bool = False

    def covers(self, interval_ms: int) -> tuple[bool, str]:
        """Did this feed observe both halves of the interval, in order, by itself?"""

        if not self.venue_open:
            return False, "the feed reports the venue as closed during the hole"
        if not self.source or self.source == BAR_OPEN_SOURCE:
            return False, "the proof must name a source other than the replay's own bars"
        if len(self.quotes) < 2:
            return False, "a single observation is a point, not coverage"
        stamps = [int(quote.ts_ms) for quote in self.quotes]
        if stamps != sorted(stamps) or len(set(stamps)) != len(stamps):
            return False, "the observations are not strictly increasing"
        end = self.missing_bar_open_ms + int(interval_ms)
        if stamps[0] < self.missing_bar_open_ms or stamps[-1] >= end:
            return False, "the observations fall outside the missing bar"
        middle = self.missing_bar_open_ms + int(interval_ms) / 2.0
        if not (stamps[0] <= middle <= stamps[-1]):
            return False, "only one half of the interval was observed"
        return True, "both halves of the interval were observed by an independent feed"


@runtime_checkable
class QuoteFeed(Protocol):
    """A price source the lane did not build from the bars it is replaying."""

    name: str

    def prove_coverage(
        self, symbol: str, missing_bar_open_ms: int, interval_ms: int
    ) -> CoverageProof | None: ...


@dataclass(frozen=True, slots=True)
class FillDecision:
    """What the scheduler concluded about one quote for one order."""

    #: ``FILL`` (the quote exists at or after the answer and the opinion is still
    #: fresh), ``WAIT`` (this quote predates the answer: keep the order for the next
    #: one) or ``EXPIRED`` (the opinion is older than its declared window).
    status: str
    quote: Quote | None
    lag_ms: int
    age_ms: int
    detail: str = ""

    @property
    def fillable(self) -> bool:
        return self.status == "FILL"


def bar_quotes(symbol: str, bars: Sequence[Any]) -> list[Quote]:
    """One quote per bar, at its open: the resolution this data actually has."""

    return [
        Quote(symbol=symbol, ts_ms=int(bar.ts_ms), price=float(bar.open)) for bar in bars
    ]


def infer_interval_ms(bars: Sequence[Any]) -> int:
    """The smallest positive gap between consecutive bars, or 0 if there is only one.

    Inferred rather than configured so a caller cannot *ask* for an intrabar price with
    the resolution check switched off by omission.
    """

    stamps = sorted({int(bar.ts_ms) for bar in bars})
    gaps = [b - a for a, b in pairwise(stamps) if b > a]
    return min(gaps) if gaps else 0


def quote_at(
    symbol: str,
    bars: Sequence[Any],
    ts_ms: int,
    *,
    interval_ms: int | None = None,
) -> Quote | None:
    """The executable quote at ``ts_ms``, or ``None`` if there is no bar there.

    A timestamp that falls *strictly inside* a bar raises :class:`InsufficientResolution`:
    the caller is asking for a price the data cannot express, and the honest answer is a
    refusal rather than the bar's open or close dressed up as an intrabar price.
    """

    target = int(ts_ms)
    interval = int(interval_ms) if interval_ms is not None else infer_interval_ms(bars)
    for bar in bars:
        opened = int(bar.ts_ms)
        if opened == target:
            return Quote(symbol=symbol, ts_ms=opened, price=float(bar.open))
        if interval and opened < target < opened + interval:
            raise InsufficientResolution(
                f"{symbol} {target} falls inside the bar that opened at {opened} "
                f"({interval} ms). OHLC cannot say whether the high or the low came "
                "first, so no intrabar price is executable from this data."
            )
    return None


def schedule(
    quote: Quote,
    *,
    received_at_ms: int,
    decision_ts_ms: int,
    max_age_ms: int,
) -> FillDecision:
    """Can ``quote`` execute an opinion formed at ``decision_ts_ms`` answered at ``received_at_ms``?

    Three outcomes, in this order:

    1. the quote is older than the opinion's window → ``EXPIRED``. Waiting longer only
       makes it older, so the order is dropped instead of filled at a stale price;
    2. the quote predates the answer → ``WAIT``. The price existed before the question
       was answered, so it is not a price this answer could have taken;
    3. otherwise → ``FILL``, with the lag between the answer and the price actually paid.
    """

    age = int(quote.ts_ms) - int(decision_ts_ms)
    lag = int(quote.ts_ms) - int(received_at_ms)
    if int(max_age_ms) <= 0:
        # Zero used to mean "no expiry", which is a silent infinite window dressed up as
        # a default. The lane resolves "one bar" before calling, so a zero here is a bug
        # in the caller and must stop the run instead of trading a view forever.
        raise ValueError(
            "max_age_ms must be a positive, declared window; zero is not 'no expiry'"
        )
    if age > int(max_age_ms):
        return FillDecision(
            status="EXPIRED",
            quote=quote,
            lag_ms=lag,
            age_ms=age,
            detail=(
                f"the opinion is {age} ms old and its window is {int(max_age_ms)} ms; "
                "the quote is later than the view it would trade"
            ),
        )
    if lag < 0:
        return FillDecision(
            status="WAIT",
            quote=quote,
            lag_ms=lag,
            age_ms=age,
            detail=(
                f"the quote at {quote.ts_ms} predates the answer at {received_at_ms}; "
                "waiting for the next quote instead of filling before the answer existed"
            ),
        )
    return FillDecision(status="FILL", quote=quote, lag_ms=lag, age_ms=age)
