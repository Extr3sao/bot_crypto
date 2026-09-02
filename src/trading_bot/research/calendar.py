"""Calendar Completeness and Historical Confirmation for V0.2.3 §16-17, §24.

V0.2.3 §16: Complete calendar days (24h per day, no partial first/last).
V0.2.3 §17: DST handling with ZoneInfo.
V0.2.3 §24: Historical confirmation simulation (two disjoint windows).
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any
from zoneinfo import ZoneInfo

import structlog


@dataclass(frozen=True, slots=True)
class CalendarDay:
    """A single calendar day with completeness info."""

    date: str  # "YYYY-MM-DD"
    bar_count: int
    expected_bars: int  # 288 for 5m, 96 for 15m, etc.
    is_complete: bool
    is_evaluation: bool = True  # False for partial first/last days
    is_dst_transition: bool = False

    @property
    def completeness_pct(self) -> float:
        if self.expected_bars == 0:
            return 0.0
        return self.bar_count / self.expected_bars * 100

    @property
    def local_date(self) -> datetime.date:
        """Parse date string to datetime.date for comparison."""
        parts = self.date.split("-")
        return datetime.date(int(parts[0]), int(parts[1]), int(parts[2]))

    @property
    def candle_keys(self) -> int:
        """Number of candles observed for this day."""
        return self.bar_count


@dataclass(frozen=True, slots=True)
class CalendarAnalysis:
    """Calendar completeness analysis for a dataset."""

    total_days: int
    complete_days: int
    partial_days: int
    evaluation_days: int
    total_bars: int
    expected_bars_per_day: int
    days: list[CalendarDay] = field(default_factory=list)

    @property
    def completeness_pct(self) -> float:
        if self.total_days == 0:
            return 0.0
        return self.complete_days / self.total_days * 100

    @property
    def evaluation_bars(self) -> int:
        return sum(d.bar_count for d in self.days if d.is_evaluation)

    @property
    def days_by_date(self) -> list[CalendarDay]:
        """List of CalendarDay objects (iterable for filtering)."""
        return list(self.days)


class CalendarCompletenessChecker:
    """V0.2.3 §16-17: Calendar completeness and DST handling."""

    def __init__(self, timezone: str = "UTC") -> None:
        self._timezone = timezone
        self._log = structlog.get_logger("calendar_completeness")
        try:
            self._tz = ZoneInfo(timezone)
        except (KeyError, ValueError):
            self._tz = datetime.UTC

    def _bars_per_day(self, timeframe: str) -> int:
        """Expected bars per standard 24h day for a timeframe."""
        mapping = {
            "1m": 1440, "3m": 480, "5m": 288, "15m": 96,
            "30m": 48, "1h": 24, "4h": 6, "1d": 1,
        }
        return mapping.get(timeframe, 288)

    def _expected_bars_for_day(
        self, day_str: str, timeframe: str = "5m"
    ) -> int:
        """Compute expected bars for a specific calendar day, accounting for DST.

        For a timezone with DST:
        - Spring-forward day (23h): fewer bars than standard
        - Fall-back day (25h): more bars than standard
        - Standard day (24h): standard bar count
        """
        standard_per_day = self._bars_per_day(timeframe)
        try:
            parts = day_str.split("-")
            year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
            local_start = datetime.datetime(year, month, day, 0, 0, tzinfo=self._tz)
            local_end = datetime.datetime(year, month, day, 23, 59, 59, tzinfo=self._tz)
            # Convert to UTC to measure actual duration
            utc_start = local_start.astimezone(datetime.UTC)
            utc_end = local_end.astimezone(datetime.UTC)
            duration_hours = (utc_end - utc_start).total_seconds() / 3600.0
            # expected bars = duration_hours * bars_per_hour
            bars_per_hour = standard_per_day / 24.0
            expected = int(round(duration_hours * bars_per_hour))
            return max(1, expected)
        except (ValueError, KeyError):
            return standard_per_day

    def _is_dst_day(self, day_str: str) -> bool:
        """Check if a calendar day involves a DST transition."""
        try:
            parts = day_str.split("-")
            year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
            local_start = datetime.datetime(year, month, day, 0, 0, tzinfo=self._tz)
            local_end = datetime.datetime(year, month, day, 23, 59, 59, tzinfo=self._tz)
            utc_start = local_start.astimezone(datetime.UTC)
            utc_end = local_end.astimezone(datetime.UTC)
            duration_hours = (utc_end - utc_start).total_seconds() / 3600.0
            # DST day != 24h
            return abs(duration_hours - 24.0) > 0.5
        except (ValueError, KeyError):
            return False

    def is_dst_day(self, day_str: str) -> bool:
        """Public API: check if a calendar day involves a DST transition."""
        return self._is_dst_day(day_str)

    def analyze(
        self,
        bars: list[dict[str, Any]],
        timeframe: str = "5m",
    ) -> CalendarAnalysis:
        """Analyze calendar completeness of bars.

        V0.2.3 §16: Identify complete vs partial days.
        V0.2.3 §17: Handle DST transitions.
        """
        if not bars:
            return CalendarAnalysis(
                total_days=0, complete_days=0, partial_days=0,
                evaluation_days=0, total_bars=0, expected_bars_per_day=0,
            )

        expected_per_day = self._bars_per_day(timeframe)

        # Group bars by calendar day
        # Supports both dict bars (with 'timestamp') and OHLCV dataclass (with 'open_time')
        daily_counts: dict[str, list[int]] = {}
        for bar in bars:
            # Get timestamp: dict uses 'timestamp', OHLCV dataclass has 'timestamp' or 'open_time'
            if hasattr(bar, 'open_time'):
                ts = bar.open_time
            elif hasattr(bar, 'timestamp'):
                ts = bar.timestamp
            elif isinstance(bar, dict):
                ts = bar.get("timestamp", 0)
            else:
                continue
            try:
                dt = datetime.datetime.fromtimestamp(ts / 1000.0, tz=datetime.UTC)
                day_str = dt.strftime("%Y-%m-%d")
            except (OSError, ValueError):
                continue
            if day_str not in daily_counts:
                daily_counts[day_str] = []
            daily_counts[day_str].append(ts)

        sorted_days = sorted(daily_counts.keys())
        total_days = len(sorted_days)
        complete_days = 0
        partial_days = 0
        day_objects: list[CalendarDay] = []

        for i, day in enumerate(sorted_days):
            count = len(daily_counts[day])
            # Use DST-aware expected bars
            expected_for_day = self._expected_bars_for_day(day, timeframe)
            is_dst = self._is_dst_day(day)

            # First and last days are partial (not evaluation)
            is_first = i == 0
            is_last = i == len(sorted_days) - 1
            is_evaluation = not is_first and not is_last

            # DST transition days are always partial and excluded from evaluation
            if is_dst:
                is_complete = False
                is_evaluation = False
            else:
                is_complete = count >= expected_for_day * 0.95  # Allow 5% tolerance

            if is_complete:
                complete_days += 1
            else:
                partial_days += 1

            day_objects.append(CalendarDay(
                date=day,
                bar_count=count,
                expected_bars=expected_for_day,
                is_complete=is_complete,
                is_evaluation=is_evaluation,
                is_dst_transition=is_dst,
            ))

        evaluation_days = sum(1 for d in day_objects if d.is_evaluation)

        return CalendarAnalysis(
            total_days=total_days,
            complete_days=complete_days,
            partial_days=partial_days,
            evaluation_days=evaluation_days,
            total_bars=len(bars),
            expected_bars_per_day=expected_per_day,
            days=day_objects,
        )

    def get_evaluation_bars(
        self,
        bars: list[dict[str, Any]],
        timeframe: str = "5m",
    ) -> list[dict[str, Any]]:
        """Filter bars to only evaluation period (complete days, excluding first/last)."""
        analysis = self.analyze(bars, timeframe)

        # Get evaluation day strings
        eval_dates = {d.date for d in analysis.days if d.is_evaluation}

        return [
            bar for bar in bars
            if self._bar_date(bar) in eval_dates
        ]

    def _bar_date(self, bar) -> str:
        """Get calendar date string from bar timestamp."""
        if hasattr(bar, 'open_time'):
            ts = bar.open_time
        elif hasattr(bar, 'timestamp'):
            ts = bar.timestamp
        elif isinstance(bar, dict):
            ts = bar.get("timestamp", 0)
        else:
            return ""
        try:
            dt = datetime.datetime.fromtimestamp(ts / 1000.0, tz=datetime.UTC)
            return dt.strftime("%Y-%m-%d")
        except (OSError, ValueError):
            return ""


@dataclass(frozen=True, slots=True)
class HistoricalConfirmationWindows:
    """Two disjoint historical windows for confirmation simulation."""

    discovery_window_id: str
    confirmation_window_id: str
    discovery_start: int  # epoch ms
    discovery_end: int
    confirmation_start: int
    confirmation_end: int
    discovery_bars: int = 0
    confirmation_bars: int = 0
    labels: dict[str, str] = field(default_factory=dict)

    @property
    def are_disjoint(self) -> bool:
        return self.discovery_end <= self.confirmation_start


class HistoricalConfirmationSimulator:
    """V0.2.3 §24: Historical confirmation simulation.

    Uses two disjoint historical windows labeled honestly:
    - DEVELOPMENT_DISCOVERY_SIMULATION
    - DEVELOPMENT_CONFIRMATION_SIMULATION

    This validates the workflow but does NOT validate alpha prospectively.
    """

    def __init__(self) -> None:
        self._log = structlog.get_logger("historical_confirmation_sim")

    def split_windows(
        self,
        bars: list[dict[str, Any]],
        discovery_pct: float = 0.33,
        confirmation_pct: float = 0.33,
        gap_bars: int = 0,
    ) -> HistoricalConfirmationWindows:
        """Split a dataset into two disjoint windows for confirmation simulation.

        Args:
            bars: Full dataset sorted by timestamp
            discovery_pct: Fraction of bars for discovery
            confirmation_pct: Fraction of bars for confirmation
            gap_bars: Minimum gap between windows
        """
        if len(bars) < 10:
            raise ValueError("Need at least 10 bars for window splitting")

        n = len(bars)
        disc_end = int(n * discovery_pct)
        conf_start = disc_end + gap_bars
        conf_end = conf_start + int(n * confirmation_pct)

        if conf_end > n:
            conf_end = n

        return HistoricalConfirmationWindows(
            discovery_window_id="W-DISCOVERY-SIM",
            confirmation_window_id="W-CONFIRMATION-SIM",
            discovery_start=bars[0]["timestamp"],
            discovery_end=bars[disc_end - 1]["timestamp"] if disc_end > 0 else bars[0]["timestamp"],
            confirmation_start=bars[conf_start]["timestamp"] if conf_start < n else bars[-1]["timestamp"],
            confirmation_end=bars[conf_end - 1]["timestamp"] if conf_end > 0 else bars[-1]["timestamp"],
            discovery_bars=disc_end,
            confirmation_bars=conf_end - conf_start,
            labels={
                "discovery": "DEVELOPMENT_DISCOVERY_SIMULATION",
                "confirmation": "DEVELOPMENT_CONFIRMATION_SIMULATION",
            },
        )


__all__ = [
    "CalendarAnalysis",
    "CalendarCompletenessChecker",
    "CalendarDay",
    "HistoricalConfirmationSimulator",
    "HistoricalConfirmationWindows",
]
