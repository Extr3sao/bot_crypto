"""quotes — a real 1-minute quote feed that can prove a hole was not an outage.

``vision.execution`` defines the contract (``QuoteFeed`` / ``CoverageProof``) and the
lane enforces it: a missing bar is not permission to trade, and the *only* way across it
is a price source that is independent of the bars being replayed. Until now that source
existed only as a test double that asserted coverage without reading any quote — a proof
of plumbing, not of market data.

This module supplies the missing half from public, credential-free Binance 1-minute
klines. Two claims are deliberately kept apart:

* **coverage** — every minute of the missing hour exists, in order, and comes from an
  archive that names itself. Anything less returns ``None``: the feed fails closed rather
  than awarding itself a proof it cannot support.
* **execution** — the first quote that exists *at or after* an instant. This is what a
  sub-bar feed could offer the lane; the lane still fills at bar opens, so the module
  exposes the quote without silently changing execution semantics. ``PROPOSED`` execution
  is therefore an audited counterfactual, not a runtime behaviour claim.

What the feed refuses to do:

* interpolate, carry forward or resample a minute it does not have;
* certify an interval that is not an exact multiple of one minute;
* accept an unsorted or duplicated series (that is a corrupt file, not a gap).
"""

from __future__ import annotations

import bisect
import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

from trading_bot.research.economic_recovery.experiments import Bar
from trading_bot.vision.execution import BAR_OPEN_SOURCE, CoverageProof, Quote, QuoteRange

MINUTE_MS = 60_000
#: The name a proof carries into the ledger. It is not ``bar_open``: the proof must come
#: from a source the replay did not build the bars it is replaying from.
FEED_NAME = "binance_spot_1m_klines"


class QuoteFeedIntegrityError(ValueError):
    """A series that cannot be trusted to answer one price per minute."""


def _series_digest(bars: Sequence[Bar]) -> str:
    payload = json.dumps(
        [[int(bar.ts_ms), bar.open, bar.high, bar.low, bar.close, bar.volume] for bar in bars],
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class MinuteSeries:
    """One symbol's minutes, with the archive they came from.

    Validated on construction. A gap is allowed (the archive may genuinely miss a
    minute); a duplicate, a non-increasing stamp or a non-positive open is not, because
    those make "one quote per minute" meaningless rather than merely incomplete.
    """

    symbol: str
    bars: tuple[Bar, ...]
    source: str = FEED_NAME

    def __post_init__(self) -> None:
        if not self.bars:
            raise QuoteFeedIntegrityError(f"{self.symbol}: the series is empty")
        previous = 0
        for bar in self.bars:
            stamp = int(bar.ts_ms)
            if stamp <= previous:
                raise QuoteFeedIntegrityError(
                    f"{self.symbol}: minute {stamp} does not follow {previous}; "
                    "an unsorted or duplicated series is corrupt, not sparse"
                )
            previous = stamp
            if not (bar.open > 0 and bar.high > 0 and bar.low > 0 and bar.close > 0):
                raise QuoteFeedIntegrityError(
                    f"{self.symbol}: minute {stamp} has a non-positive price, which is a "
                    "missing observation rather than a quote"
                )
            if bar.high < max(bar.open, bar.close) or bar.low > min(bar.open, bar.close):
                raise QuoteFeedIntegrityError(
                    f"{self.symbol}: minute {stamp} has OHLC outside its own high/low"
                )

    @classmethod
    def from_rows(cls, symbol: str, rows: Iterable[Sequence[float]]) -> MinuteSeries:
        """Build from ``[ts_ms, open, high, low, close, volume]`` rows."""

        bars = tuple(
            Bar(
                ts_ms=int(row[0]),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
            )
            for row in rows
        )
        return cls(symbol=symbol, bars=bars)

    @property
    def stamps(self) -> list[int]:
        return [int(bar.ts_ms) for bar in self.bars]

    @property
    def digest(self) -> str:
        return _series_digest(self.bars)

    def quote_at(self, index: int) -> Quote:
        bar = self.bars[index]
        opened = int(bar.ts_ms)
        return Quote(symbol=self.symbol, ts_ms=opened, price=float(bar.open), source=self.source)


class MinuteBarQuoteFeed:
    """A ``QuoteFeed`` over real 1-minute opens, keyed by display symbol."""

    name = FEED_NAME

    def __init__(self, series: Mapping[str, MinuteSeries]) -> None:
        if not series:
            raise QuoteFeedIntegrityError("a feed with no series cannot prove anything")
        self._series = dict(series)
        self._stamps = {symbol: item.stamps for symbol, item in self._series.items()}

    # -- construction --------------------------------------------------------

    @classmethod
    def from_directory(
        cls,
        directory: Path | str,
        *,
        aliases: Mapping[str, str] | None = None,
        symbols: Sequence[str] | None = None,
    ) -> MinuteBarQuoteFeed:
        """Load ``<FILE_SYMBOL>_1m_*.json`` files, mapping them to display symbols.

        ``aliases`` maps the archive's symbol (``UNIUSDT``) to the lane's symbol
        (``UNI/USDT``); without one the file symbol is used unchanged.
        """

        root = Path(directory)
        mapping = dict(aliases or {})
        wanted = set(symbols) if symbols is not None else None
        series: dict[str, MinuteSeries] = {}
        for path in sorted(root.glob("*_1m_*.json")):
            file_symbol = path.name.split("_1m_", 1)[0]
            display = mapping.get(file_symbol, file_symbol)
            if wanted is not None and display not in wanted and file_symbol not in wanted:
                continue
            rows = json.loads(path.read_text(encoding="utf-8"))
            series[display] = MinuteSeries.from_rows(display, rows)
        if not series:
            raise QuoteFeedIntegrityError(f"{root}: no 1-minute series found")
        return cls(series)

    # -- inspection ----------------------------------------------------------

    def has(self, symbol: str) -> bool:
        return symbol in self._series

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(sorted(self._series))

    def series(self, symbol: str) -> MinuteSeries:
        try:
            return self._series[symbol]
        except KeyError:
            raise KeyError(
                f"{symbol} is not in this feed (has {', '.join(self.symbols)}); a feed that "
                "silently answers for another symbol would prove the wrong thing"
            ) from None

    def quotes_between(self, symbol: str, start_ms: int, end_ms: int) -> tuple[Quote, ...]:
        """Every 1-minute open in ``[start_ms, end_ms)``, in order."""

        series = self.series(symbol)
        stamps = self._stamps[symbol]
        left = bisect.bisect_left(stamps, int(start_ms))
        right = bisect.bisect_left(stamps, int(end_ms))
        return tuple(series.quote_at(index) for index in range(left, right))

    # -- the contract the lane enforces --------------------------------------

    def explain_coverage(
        self, symbol: str, missing_bar_open_ms: int, interval_ms: int
    ) -> tuple[bool, str]:
        """Why a hole is (or is not) provable, without dressing the answer up as a proof."""

        if not self.has(symbol):
            return False, f"{symbol} is absent from {self.name}"
        interval = int(interval_ms)
        if interval <= 0 or interval % MINUTE_MS:
            return (
                False,
                f"{interval} ms is not a whole number of minutes; this feed cannot prove it",
            )
        expected = interval // MINUTE_MS
        stamps = self._stamps[symbol]
        left = bisect.bisect_left(stamps, int(missing_bar_open_ms))
        observed = [
            stamps[index]
            for index in range(left, len(stamps))
            if stamps[index] < int(missing_bar_open_ms) + interval
        ]
        if len(observed) != expected:
            missing = expected - len(observed)
            return (
                False,
                f"{len(observed)}/{expected} minutes observed inside the hole "
                f"({missing} missing); a partial minute grid is not continuity",
            )
        step_ok = all(b - a == MINUTE_MS for a, b in pairwise(observed))
        if not step_ok:
            return False, "the observed minutes are not consecutive"
        return True, f"all {expected} minutes of the hole were observed by {self.name}"

    def prove_coverage(
        self, symbol: str, missing_bar_open_ms: int, interval_ms: int
    ) -> CoverageProof | None:
        """A proof the lane accepts, or ``None`` when this feed cannot support one."""

        covered, _ = self.explain_coverage(symbol, missing_bar_open_ms, interval_ms)
        if not covered:
            return None
        proof = CoverageProof(
            symbol=symbol,
            missing_bar_open_ms=int(missing_bar_open_ms),
            source=self.name,
            quotes=self.quotes_between(
                symbol, int(missing_bar_open_ms), int(missing_bar_open_ms) + int(interval_ms)
            ),
            venue_open=True,
        )
        # Ask the contract, not the constructor: a proof this module built must still
        # satisfy the same ``covers`` rule the lane applies.
        accepted, _ = proof.covers(int(interval_ms))
        return proof if accepted else None

    # -- execution quality ---------------------------------------------------

    def first_quote_at_or_after(
        self, symbol: str, ts_ms: int, *, horizon_ms: int
    ) -> Quote | None:
        """The first 1-minute open at or after ``ts_ms``, if within ``horizon_ms``.

        Never returns a quote older than the instant asked for: that would be a price the
        event could not have taken, which is exactly the defect the bar grid already
        carries.
        """

        if int(horizon_ms) <= 0:
            raise ValueError("horizon_ms must be positive; zero is not 'any horizon'")
        series = self.series(symbol)
        stamps = self._stamps[symbol]
        index = bisect.bisect_left(stamps, int(ts_ms))
        if index >= len(stamps):
            return None
        quote = series.quote_at(index)
        if int(quote.ts_ms) - int(ts_ms) > int(horizon_ms):
            return None
        if quote.source == BAR_OPEN_SOURCE:  # pragma: no cover - guarded by construction
            return None
        return quote

    # -- the range a stop may see --------------------------------------------

    def range_between(self, symbol: str, after_ms: int, until_ms: int) -> QuoteRange | None:
        """High/low/last of the minutes **strictly after** ``after_ms``, before ``until_ms``.

        The minute that contains ``after_ms`` is excluded: a 1-minute OHLC does not say
        whether its high or low came before or after the instant inside it, so using it
        would be look-ahead. ``None`` means no minute is left to observe, which the lane
        records as "no observable range" instead of inventing one.
        """

        series = self.series(symbol)
        stamps = self._stamps[symbol]
        left = bisect.bisect_right(stamps, int(after_ms))
        right = bisect.bisect_left(stamps, int(until_ms))
        rows = series.bars[left:right]
        if not rows:
            return None
        return QuoteRange(
            symbol=symbol,
            after_ms=int(after_ms),
            until_ms=int(until_ms),
            minutes=len(rows),
            high=max(float(bar.high) for bar in rows),
            low=min(float(bar.low) for bar in rows),
            last=float(rows[-1].close),
            source=self.name,
        )

    # -- provenance ----------------------------------------------------------

    def as_public_dict(self) -> dict[str, Any]:
        return {
            "feed": self.name,
            "symbols": {
                symbol: {
                    "minutes": len(series.bars),
                    "first_minute_ms": int(series.bars[0].ts_ms),
                    "last_minute_ms": int(series.bars[-1].ts_ms),
                    "series_sha256": series.digest,
                }
                for symbol, series in sorted(self._series.items())
            },
        }
