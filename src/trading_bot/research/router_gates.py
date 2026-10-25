"""RouterGates — configurable gates for the StrategyRouter.

Freshness is the one gate that cannot have a single constant (§38, DEF-AUTO-3):
a 30-minute strategy whose context is 20 minutes old is *current*, and judging
it by a fixed 15-minute rule rejected every 30m candidate as
``stale_context`` — an effective ceiling of 5-15m on a system that claimed to
run 30m timeframes.

So staleness is derived from the timeframe the strategy actually runs on: a
context may lag up to ``freshness_grace_bars`` bars behind the decision
timestamp, which is the only rule that stays honest as the timeframe changes.
The legacy constant survives only as the fallback for a caller that never
declares a timeframe, and the autonomous runtime always declares one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

__all__ = [
    "DEFAULT_FRESHNESS_GRACE_BARS",
    "STALE_THRESHOLD_MS",
    "TIMEFRAME_MS",
    "RouterGates",
    "stale_threshold_for_timeframe",
    "timeframe_ms",
]

#: Legacy fixed threshold. Retained for callers that declare no timeframe; the
#: paper runtime always declares one, so this value never governs it (§38).
STALE_THRESHOLD_MS: Final[int] = 15 * 60 * 1000

MINUTE_MS: Final[int] = 60_000

#: Every timeframe the platform reasons about, in milliseconds.
TIMEFRAME_MS: Final[dict[str, int]] = {
    "1m": MINUTE_MS,
    "3m": 3 * MINUTE_MS,
    "5m": 5 * MINUTE_MS,
    "15m": 15 * MINUTE_MS,
    "30m": 30 * MINUTE_MS,
    "1h": 60 * MINUTE_MS,
    "2h": 120 * MINUTE_MS,
    "4h": 240 * MINUTE_MS,
    "1d": 1_440 * MINUTE_MS,
}

#: How many bars of lag a context may show before it is stale. 1.5 bars means
#: "the previous bar is still usable while the current one is forming", which is
#: true for every timeframe rather than only for the short ones.
DEFAULT_FRESHNESS_GRACE_BARS: Final[float] = 1.5


def timeframe_ms(timeframe: str) -> int | None:
    """Bar width in ms, or ``None`` when the timeframe is not recognised."""
    return TIMEFRAME_MS.get(timeframe.strip().lower())


def stale_threshold_for_timeframe(
    timeframe: str,
    *,
    grace_bars: float = DEFAULT_FRESHNESS_GRACE_BARS,
) -> int:
    """Staleness budget for one timeframe, in ms.

    Unknown timeframes raise rather than silently inheriting the legacy
    constant: a gate that cannot be reasoned about must not be reachable.
    """
    width = timeframe_ms(timeframe)
    if width is None:
        raise ValueError(
            f"unknown timeframe {timeframe!r}; known: {sorted(TIMEFRAME_MS)}"
        )
    if grace_bars <= 0:
        raise ValueError(f"grace_bars must be > 0, got {grace_bars}")
    return int(width * grace_bars)


@dataclass(frozen=True, slots=True)
class RouterGates:
    """Gates a strategy must pass before the router selects it.

    ``timeframe``/``freshness_ms`` exist so the freshness gate can be reasoned
    about per strategy. An explicit ``freshness_ms`` always wins; otherwise the
    timeframe decides; only a caller that declares neither falls back to the
    legacy constant.
    """

    require_confirmed: bool = True
    require_regime_match: bool = True
    min_data_quality: float = 0.5
    require_fresh_context: bool = True
    #: The timeframe the strategies under this router run on (§38).
    timeframe: str | None = None
    #: Explicit override, for callers that know their own budget.
    freshness_ms: int | None = None
    #: Bars of lag tolerated when the timeframe governs the budget.
    freshness_grace_bars: float = DEFAULT_FRESHNESS_GRACE_BARS

    def __post_init__(self) -> None:
        if self.timeframe is not None and timeframe_ms(self.timeframe) is None:
            raise ValueError(
                f"unknown timeframe {self.timeframe!r}; known: {sorted(TIMEFRAME_MS)}"
            )
        if self.freshness_ms is not None and self.freshness_ms <= 0:
            raise ValueError(f"freshness_ms must be > 0, got {self.freshness_ms}")
        if self.require_fresh_context and self.freshness_ms is not None and self.timeframe:
            raise ValueError(
                "declare either freshness_ms or timeframe, not both: a gate with two "
                "budgets cannot be audited"
            )

    def stale_after_ms(self) -> int:
        """The staleness budget this router actually applies."""
        if self.freshness_ms is not None:
            return self.freshness_ms
        if self.timeframe is not None:
            return stale_threshold_for_timeframe(
                self.timeframe, grace_bars=self.freshness_grace_bars
            )
        return STALE_THRESHOLD_MS

    @property
    def freshness_source(self) -> str:
        """Where the budget came from, so a trace can say why a context passed."""
        if self.freshness_ms is not None:
            return "explicit_ms"
        if self.timeframe is not None:
            return f"timeframe:{self.timeframe}"
        return "legacy_default"
