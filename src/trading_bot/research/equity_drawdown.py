"""Drawdown from a real equity curve — never from a peak-equity level.

WP-EDGE-017F/P0.3. The EDGE-017 report published ``drawdown_pct`` as
``risk_state_at_end.peak_equity``: a USDT balance (10 000.0), not a percentage,
and not a drawdown at all. A level cannot say how far the book fell from its own
high, so the number was unverifiable by construction.

This module measures the peak-to-trough fall of a *curve* and refuses to invent
one. When there are fewer than two finite points the answer is ``UNKNOWN`` with
the reason, because a percentage derived from a single mark is not evidence.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

__all__ = ["Drawdown", "max_drawdown"]

#: A flat curve has a 0% drawdown; fewer points than this cannot describe a fall.
MINIMUM_POINTS = 2


@dataclass(frozen=True, slots=True)
class Drawdown:
    """Peak-to-trough result, in percent and in USDT, with its own provenance."""

    status: str
    drawdown_pct: float | None
    drawdown_usdt: float | None
    peak_equity: float | None
    trough_equity: float | None
    peak_ts_ms: int | None
    trough_ts_ms: int | None
    points: int
    reason: str | None = None

    @property
    def measured(self) -> bool:
        return self.status == "MEASURED"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "drawdown_pct": None if self.drawdown_pct is None else round(self.drawdown_pct, 6),
            "drawdown_usdt": None if self.drawdown_usdt is None else round(self.drawdown_usdt, 6),
            "peak_equity": none_or_round(self.peak_equity),
            "trough_equity": none_or_round(self.trough_equity),
            "peak_ts_ms": self.peak_ts_ms,
            "trough_ts_ms": self.trough_ts_ms,
            "points": self.points,
            "reason": self.reason,
            "method": "max peak-to-trough of the mark-to-market net equity curve",
        }


def none_or_round(value: float | None) -> float | None:
    return None if value is None else round(float(value), 6)


def max_drawdown(
    points: Iterable[tuple[int, float]],
    *,
    minimum_points: int = MINIMUM_POINTS,
) -> Drawdown:
    """Largest peak-to-trough fall of ``(timestamp_ms, equity)`` points.

    Invalid marks are dropped, not interpolated: a non-finite equity is missing
    evidence, and inventing it would make the drawdown look better or worse than
    the book actually was. The percentage divides by the peak that preceded the
    trough, so a later, higher peak cannot dilute an earlier fall.
    """
    valid: list[tuple[int, float]] = []
    dropped = 0
    for ts_ms, equity in points:
        try:
            value = float(equity)
            stamp = int(ts_ms)
        except (TypeError, ValueError):
            dropped += 1
            continue
        if not math.isfinite(value):
            dropped += 1
            continue
        valid.append((stamp, value))

    if len(valid) < int(minimum_points):
        return Drawdown(
            status="UNKNOWN",
            drawdown_pct=None,
            drawdown_usdt=None,
            peak_equity=None,
            trough_equity=None,
            peak_ts_ms=None,
            trough_ts_ms=None,
            points=len(valid),
            reason=(
                f"{len(valid)} usable equity points < {int(minimum_points)} required"
                + (f" ({dropped} invalid dropped)" if dropped else "")
            ),
        )

    running_peak, running_peak_ts = valid[0][1], valid[0][0]
    worst = 0.0
    worst_peak = running_peak
    worst_peak_ts = running_peak_ts
    worst_trough = running_peak
    worst_trough_ts = running_peak_ts

    for ts_ms, equity in valid[1:]:
        if equity > running_peak:
            running_peak, running_peak_ts = equity, ts_ms
            continue
        fall = running_peak - equity
        if fall > worst:
            worst = fall
            worst_peak = running_peak
            worst_peak_ts = running_peak_ts
            worst_trough = equity
            worst_trough_ts = ts_ms

    if worst_peak <= 0:
        return Drawdown(
            status="UNKNOWN",
            drawdown_pct=None,
            drawdown_usdt=round(worst, 6),
            peak_equity=worst_peak,
            trough_equity=worst_trough,
            peak_ts_ms=worst_peak_ts,
            trough_ts_ms=worst_trough_ts,
            points=len(valid),
            reason="the peak equity is not positive, so a percentage is undefined",
        )

    return Drawdown(
        status="MEASURED",
        drawdown_pct=worst / worst_peak * 100.0,
        drawdown_usdt=worst,
        peak_equity=worst_peak,
        trough_equity=worst_trough,
        peak_ts_ms=worst_peak_ts,
        trough_ts_ms=worst_trough_ts,
        points=len(valid),
        reason=None,
    )
