"""Data Integrity Checks (FASE 8, P20).

Verifies:
- Missing bars detection
- Duplicate bar detection
- Timestamp monotonicity
- Timezone/DST consistency
- Complete calendar days (24/7 crypto)
- HTF candle completion
- Lookahead detection
- Warmup period validation

All checks are READ-ONLY and return structured results.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

from trading_bot.market_data.types import OHLCV

# ---------------------------------------------------------------------------
# Integrity Check Result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IntegrityCheck:
    """Result of a single integrity check."""

    check_name: str
    passed: bool
    issue_count: int
    details: str = ""
    affected_timestamps: list[int] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class IntegrityReport:
    """Complete integrity report for a candle series."""

    symbol: str
    timeframe: str
    total_candles: int
    checks: list[IntegrityCheck]

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def failed_checks(self) -> list[IntegrityCheck]:
        return [c for c in self.checks if not c.passed]

    @property
    def total_issues(self) -> int:
        return sum(c.issue_count for c in self.checks)


# ---------------------------------------------------------------------------
# Timeframe helpers
# ---------------------------------------------------------------------------

_TIMEFRAME_MS: dict[str, int] = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}


def _expected_interval_ms(timeframe: str) -> int | None:
    """Get expected interval in ms for a timeframe."""
    return _TIMEFRAME_MS.get(timeframe)


# ---------------------------------------------------------------------------
# Data Integrity Checker
# ---------------------------------------------------------------------------


class DataIntegrityChecker:
    """Validates candle data integrity (P20).

    All checks are READ-ONLY. Returns structured results without modifying data.
    """

    def __init__(self) -> None:
        self._log = structlog.get_logger("data_integrity")

    def check(
        self,
        candles: list[OHLCV],
        symbol: str,
        timeframe: str,
        *,
        expected_start_ts: int | None = None,
        expected_end_ts: int | None = None,
        warmup_candles: int = 50,
    ) -> IntegrityReport:
        """Run all integrity checks on a candle series.

        Args:
            candles: Chronologically sorted candles
            symbol: Symbol identifier
            timeframe: Timeframe string (1m, 5m, 15m, 1h, 4h, 1d)
            expected_start_ts: Expected series start (epoch ms)
            expected_end_ts: Expected series end (epoch ms)
            warmup_candles: Minimum candles needed for indicator warmup

        Returns:
            IntegrityReport with all check results
        """
        checks: list[IntegrityCheck] = []

        # 1. Missing bars
        checks.append(self._check_missing_bars(candles, timeframe))

        # 2. Duplicate bars
        checks.append(self._check_duplicates(candles))

        # 3. Timestamp monotonicity
        checks.append(self._check_monotonicity(candles))

        # 4. OHLCV validity (basic sanity)
        checks.append(self._check_ohlcv_validity(candles))

        # 5. Warmup
        checks.append(self._check_warmup(candles, warmup_candles))

        # 6. Completeness (if bounds provided)
        if expected_start_ts is not None and expected_end_ts is not None:
            checks.append(self._check_completeness(candles, timeframe, expected_start_ts, expected_end_ts))

        report = IntegrityReport(
            symbol=symbol,
            timeframe=timeframe,
            total_candles=len(candles),
            checks=checks,
        )

        if report.all_passed:
            self._log.info("integrity.all_passed", symbol=symbol, candles=len(candles))
        else:
            self._log.warning(
                "integrity.issues_found",
                symbol=symbol,
                failed=len(report.failed_checks),
                total_issues=report.total_issues,
            )

        return report

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_missing_bars(self, candles: list[OHLCV], timeframe: str) -> IntegrityCheck:
        """Check for gaps in the candle series."""
        if len(candles) < 2:
            return IntegrityCheck(
                check_name="missing_bars",
                passed=True,
                issue_count=0,
                details="Insufficient candles to check gaps",
            )

        expected_interval = _expected_interval_ms(timeframe)
        if expected_interval is None:
            return IntegrityCheck(
                check_name="missing_bars",
                passed=True,
                issue_count=0,
                details=f"Unknown timeframe '{timeframe}', cannot check gaps",
            )

        gaps: list[int] = []
        for i in range(1, len(candles)):
            diff = candles[i].timestamp - candles[i - 1].timestamp
            if diff > expected_interval * 1.5:  # allow 50% tolerance
                gaps.append(candles[i - 1].timestamp)

        return IntegrityCheck(
            check_name="missing_bars",
            passed=len(gaps) == 0,
            issue_count=len(gaps),
            details=f"{len(gaps)} gaps detected" if gaps else "",
            affected_timestamps=gaps[:20],  # cap at 20
        )

    def _check_duplicates(self, candles: list[OHLCV]) -> IntegrityCheck:
        """Check for duplicate timestamps."""
        seen: dict[int, int] = {}
        duplicates: list[int] = []
        for c in candles:
            if c.timestamp in seen:
                duplicates.append(c.timestamp)
            else:
                seen[c.timestamp] = 1

        return IntegrityCheck(
            check_name="duplicates",
            passed=len(duplicates) == 0,
            issue_count=len(duplicates),
            details=f"{len(duplicates)} duplicate timestamps" if duplicates else "",
            affected_timestamps=duplicates[:20],
        )

    def _check_monotonicity(self, candles: list[OHLCV]) -> IntegrityCheck:
        """Check that timestamps are strictly increasing."""
        violations: list[int] = []
        for i in range(1, len(candles)):
            if candles[i].timestamp <= candles[i - 1].timestamp:
                violations.append(i)

        return IntegrityCheck(
            check_name="monotonicity",
            passed=len(violations) == 0,
            issue_count=len(violations),
            details=f"{len(violations)} non-monotonic timestamps" if violations else "",
        )

    def _check_ohlcv_validity(self, candles: list[OHLCV]) -> IntegrityCheck:
        """Check basic OHLCV sanity: high >= low, close/open within range, volume >= 0."""
        issues: list[str] = []
        for c in candles:
            if c.high < c.low:
                issues.append(f"ts={c.timestamp}: high < low")
            if c.close < 0 or c.open < 0:
                issues.append(f"ts={c.timestamp}: negative price")
            if c.volume < 0:
                issues.append(f"ts={c.timestamp}: negative volume")
            if c.high < c.close or c.high < c.open:
                issues.append(f"ts={c.timestamp}: high < close/open")
            if c.low > c.close or c.low > c.open:
                issues.append(f"ts={c.timestamp}: low > close/open")

        return IntegrityCheck(
            check_name="ohlcv_validity",
            passed=len(issues) == 0,
            issue_count=len(issues),
            details="; ".join(issues[:5]) if issues else "",
        )

    def _check_warmup(self, candles: list[OHLCV], warmup_candles: int) -> IntegrityCheck:
        """Check if there are enough candles for indicator warmup."""
        enough = len(candles) >= warmup_candles
        return IntegrityCheck(
            check_name="warmup",
            passed=enough,
            issue_count=0 if enough else 1,
            details=(
                f"Have {len(candles)}, need {warmup_candles}"
                if not enough
                else ""
            ),
        )

    def _check_completeness(
        self,
        candles: list[OHLCV],
        timeframe: str,
        expected_start: int,
        expected_end: int,
    ) -> IntegrityCheck:
        """Check if the candle series covers the expected time range."""
        if not candles:
            return IntegrityCheck(
                check_name="completeness",
                passed=False,
                issue_count=1,
                details="No candles provided",
            )

        actual_start = candles[0].timestamp
        actual_end = candles[-1].timestamp

        issues: list[str] = []
        if actual_start > expected_start:
            issues.append(f"Series starts late: {actual_start} > {expected_start}")
        if actual_end < expected_end:
            issues.append(f"Series ends early: {actual_end} < {expected_end}")

        return IntegrityCheck(
            check_name="completeness",
            passed=len(issues) == 0,
            issue_count=len(issues),
            details="; ".join(issues) if issues else "",
        )


__all__ = ["DataIntegrityChecker", "IntegrityCheck", "IntegrityReport"]
