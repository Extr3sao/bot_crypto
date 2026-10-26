"""Evaluation cadence for the PAPER loop — WP-STRAT-09.

Why this module exists
----------------------
The router's freshness gate (``RouterGates.stale_after_ms``) measures how far a
context lags the decision. ``pit.py`` defines a bar's availability as its
**close** (``timestamp + interval``), but ``AssetContext.window_end_ts`` carries
the newest bar's **open**. So the gate's measured age is
``decision - bar_open``, which already contains one whole bar of
"currently forming" time on top of the true availability age.

For a 5m timeframe the 1.5-bar budget is 450 s, so the *effective* window after
a bar seals in which ``decision - bar_open <= 450 s`` holds is only
``450 s - 300 s = 150 s``. A free-running 60 s loop lands inside that window on
about half of its cycles and is rejected ``stale_context`` on the rest — measured
at 50 % over 336 evaluations in the WP-STRAT-08 SHADOW campaign
(``DEF-FRESH-BUDGET-001``).

The honest fix is **cadence, never the budget**: wake at
``bar_close + settlement`` so the decision sits just after a seal, where
``decision - bar_open = interval + settlement < grace_bars * interval``. The
freshness budget is untouched — this module never imports, recomputes or widens
``stale_after_ms``. It only guarantees the loop is *phase-aligned* to the sealed
bar the gate already expects.

``validate_settlement`` derives its ceiling from
``DEFAULT_FRESHNESS_GRACE_BARS`` (``interval * (grace - 1)``) instead of
hard-coding "150 s", so if the gate's grace is ever changed by an independent
process, the cadence constraint follows it rather than silently disagreeing
(TEST_TARGET == RUNTIME_TARGET).
"""

from __future__ import annotations

from typing import Final

from trading_bot.research.router_gates import DEFAULT_FRESHNESS_GRACE_BARS

__all__ = [
    "CADENCE_BAR_CLOSE",
    "CADENCE_INTERVAL",
    "bar_close_ms",
    "max_settlement_ms",
    "next_bar_close_ms",
    "seconds_until_next_evaluation",
    "validate_settlement",
]

#: Legacy cadence: sleep a fixed number of seconds between cycles (unchanged).
CADENCE_INTERVAL: Final[str] = "interval"
#: Bar-close cadence: wake at each sealed bar's close plus a settlement delay.
CADENCE_BAR_CLOSE: Final[str] = "bar-close"


def _require_interval(interval_ms: int) -> int:
    if interval_ms <= 0:
        raise ValueError(f"interval_ms must be > 0, got {interval_ms}")
    return interval_ms


def bar_close_ms(now_ms: int, interval_ms: int) -> int:
    """The close of the most recent bar at or before ``now_ms``.

    Bar opens sit on the ``interval_ms`` grid, so bar ``k`` closes at
    ``(k + 1) * interval_ms``; the latest such close not in the future is the
    grid point at or below ``now_ms``.
    """
    return (now_ms // _require_interval(interval_ms)) * interval_ms


def next_bar_close_ms(now_ms: int, interval_ms: int) -> int:
    """The first bar close strictly after ``now_ms``."""
    return (now_ms // _require_interval(interval_ms) + 1) * interval_ms


def max_settlement_ms(interval_ms: int, *, grace_bars: float = DEFAULT_FRESHNESS_GRACE_BARS) -> int:
    """Largest settlement delay that still lands inside the freshness budget.

    A decision at ``bar_close + settlement`` sees a newest sealed bar whose
    open is ``interval + settlement`` behind, which must stay below
    ``grace_bars * interval``. Hence ``settlement < interval * (grace - 1)``.
    """
    _require_interval(interval_ms)
    if grace_bars <= 1.0:
        raise ValueError(f"grace_bars must be > 1.0 for a bar-close cadence, got {grace_bars}")
    return int(interval_ms * (grace_bars - 1.0))


def validate_settlement(
    interval_ms: int,
    settlement_seconds: float,
    *,
    grace_bars: float = DEFAULT_FRESHNESS_GRACE_BARS,
) -> float:
    """Return the settlement in ms, or raise if it would outrun the budget."""
    if settlement_seconds < 0:
        raise ValueError(f"settlement_seconds must be >= 0, got {settlement_seconds}")
    ceiling = max_settlement_ms(interval_ms, grace_bars=grace_bars)
    settlement_ms = int(settlement_seconds * 1000)
    if settlement_ms >= ceiling:
        raise ValueError(
            f"settlement {settlement_ms} ms >= budget ceiling {ceiling} ms "
            f"({interval_ms} ms bar, grace {grace_bars}); the cycle would land "
            "outside the freshness window — lower the delay, do not widen the gate"
        )
    return settlement_ms


def seconds_until_next_evaluation(
    now_ms: int,
    interval_ms: int,
    settlement_seconds: float,
) -> float:
    """Seconds to sleep so the next cycle runs at ``next_close + settlement``.

    Never negative; a caller that is already past the target wakes immediately.
    """
    target = next_bar_close_ms(now_ms, interval_ms) + int(settlement_seconds * 1000)
    return max(0.0, (target - now_ms) / 1000.0)
