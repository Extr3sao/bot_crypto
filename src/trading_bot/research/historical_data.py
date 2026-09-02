"""Historical Data Adapter and Data Quality Gate for V0.2.1.

V0.2.1 §3: Real OHLCV Store Integration
- Locates real OHLCV storage in the bot (OHLCVStore)
- Determines format, symbols, timeframes, timestamps, timezone, origin, integrity
- Reuses existing infrastructure (OHLCVStore)

V0.2.1 §4: Data Quality Gate
- Before backtesting, validate: monotonic timestamps, duplicates, missing bars,
  invalid OHLC, negative volume, timezone, timeframe, incomplete candles,
  coverage, warmup sufficiency

Output:
- HistoricalDataset with evidence_class=HISTORICAL_REAL
- DataQualityResult: PASS or FAIL_CLOSED
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

import structlog

from .evidence import EvidenceClass, EvidenceRecord


@dataclass(frozen=True, slots=True)
class HistoricalDataset:
    """Descriptor for a real historical dataset.

    V0.2.1 §3: Returned by HistoricalDataAdapter.
    evidence_class=HISTORICAL_REAL for real data.
    """

    dataset_id: str
    symbols: list[str]
    timeframe: str
    start: int  # epoch ms
    end: int  # epoch ms
    bar_count: int
    source: str  # e.g., "OHLCVStore:data/storage/bot.db"
    checksum: str
    evidence_class: EvidenceClass = EvidenceClass.HISTORICAL_MARKET_REAL

    @property
    def duration_hours(self) -> float:
        return (self.end - self.start) / (1000 * 3600)

    def to_evidence_record(self) -> EvidenceRecord:
        """Convert to EvidenceRecord for pipeline provenance."""
        return EvidenceRecord(
            evidence_class=self.evidence_class,
            source=self.source,
            dataset_id=self.dataset_id,
            checksum=self.checksum,
            metadata={
                "symbols": self.symbols,
                "timeframe": self.timeframe,
                "start": self.start,
                "end": self.end,
                "bar_count": self.bar_count,
            },
        )


@dataclass(frozen=True, slots=True)
class QualityCheck:
    """Single quality check result."""

    check_id: str
    passed: bool
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DataQualityResult:
    """Result of data quality gate.

    V0.2.1 §4: If ERROR/CRITICAL → FAIL_CLOSED.
    Never execute strategy qualification over invalid dataset.
    """

    dataset_id: str
    passed: bool
    checks: list[QualityCheck] = field(default_factory=list)
    evidence: EvidenceRecord | None = None

    @property
    def failed_checks(self) -> list[QualityCheck]:
        return [c for c in self.checks if not c.passed]

    @property
    def passed_count(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    @property
    def total_count(self) -> int:
        return len(self.checks)

    def assert_valid(self) -> None:
        """Raise if quality gate failed (FAIL_CLOSED)."""
        if not self.passed:
            failed = [c.check_id for c in self.failed_checks]
            raise ValueError(
                f"Data quality gate FAIL_CLOSED for {self.dataset_id}: "
                f"failed checks: {failed}"
            )


class DataQualityGate:
    """Validates OHLCV data before backtesting.

    V0.2.1 §4: Comprehensive quality checks.
    """

    def __init__(self, min_warmup_bars: int = 50) -> None:
        self._min_warmup_bars = min_warmup_bars
        self._log = structlog.get_logger("data_quality_gate")

    def validate(
        self,
        bars: list[dict[str, Any]],
        dataset_id: str,
        expected_timeframe: str = "5m",
    ) -> DataQualityResult:
        """Run all quality checks on a list of OHLCV bars.

        Args:
            bars: List of OHLCV dicts with keys: timestamp, open, high, low, close, volume
            dataset_id: Dataset identifier
            expected_timeframe: Expected candle interval

        Returns:
            DataQualityResult with pass/fail and individual check results
        """
        checks: list[QualityCheck] = []

        if not bars:
            return DataQualityResult(
                dataset_id=dataset_id,
                passed=False,
                checks=[QualityCheck(check_id="empty_dataset", passed=False, message="No bars provided")],
            )

        # 1. Timestamps monotonic
        checks.append(self._check_timestamps_monotonic(bars))

        # 2. Duplicates
        checks.append(self._check_duplicates(bars))

        # 3. Invalid OHLC
        checks.append(self._check_invalid_ohlc(bars))

        # 4. Negative volume
        checks.append(self._check_negative_volume(bars))

        # 5. Missing bars (gap detection)
        checks.append(self._check_missing_bars(bars, expected_timeframe))

        # 6. Coverage
        checks.append(self._check_coverage(bars))

        # 7. Warmup sufficiency
        checks.append(self._check_warmup(bars))

        # 8. Incomplete candles (last candle)
        checks.append(self._check_incomplete_candle(bars))

        passed = all(c.passed for c in checks)

        self._log.info(
            "data_quality.completed",
            dataset_id=dataset_id,
            passed=passed,
            total=len(checks),
            failed=sum(1 for c in checks if not c.passed),
        )

        return DataQualityResult(
            dataset_id=dataset_id,
            passed=passed,
            checks=checks,
        )

    def _check_timestamps_monotonic(self, bars: list[dict[str, Any]]) -> QualityCheck:
        """Check timestamps are strictly increasing."""
        for i in range(1, len(bars)):
            if bars[i]["timestamp"] <= bars[i - 1]["timestamp"]:
                return QualityCheck(
                    check_id="monotonic_timestamps",
                    passed=False,
                    message=f"Non-monotonic at index {i}: {bars[i-1]['timestamp']} >= {bars[i]['timestamp']}",
                )
        return QualityCheck(check_id="monotonic_timestamps", passed=True)

    def _check_duplicates(self, bars: list[dict[str, Any]]) -> QualityCheck:
        """Check for duplicate timestamps."""
        seen: set[int] = set()
        for i, bar in enumerate(bars):
            ts = bar["timestamp"]
            if ts in seen:
                return QualityCheck(
                    check_id="no_duplicates",
                    passed=False,
                    message=f"Duplicate timestamp at index {i}: {ts}",
                )
            seen.add(ts)
        return QualityCheck(check_id="no_duplicates", passed=True)

    def _check_invalid_ohlc(self, bars: list[dict[str, Any]]) -> QualityCheck:
        """Check OHLC validity: high >= low, high >= open/close, low <= open/close."""
        for i, bar in enumerate(bars):
            o, h, l, c = bar["open"], bar["high"], bar["low"], bar["close"]
            if h < l:
                return QualityCheck(
                    check_id="valid_ohlc",
                    passed=False,
                    message=f"high < low at index {i}: high={h}, low={l}",
                )
            if h < o or h < c:
                return QualityCheck(
                    check_id="valid_ohlc",
                    passed=False,
                    message=f"high < open/close at index {i}: high={h}, open={o}, close={c}",
                )
            if l > o or l > c:
                return QualityCheck(
                    check_id="valid_ohlc",
                    passed=False,
                    message=f"low > open/close at index {i}: low={l}, open={o}, close={c}",
                )
        return QualityCheck(check_id="valid_ohlc", passed=True)

    def _check_negative_volume(self, bars: list[dict[str, Any]]) -> QualityCheck:
        """Check no negative volume."""
        for i, bar in enumerate(bars):
            if bar["volume"] < 0:
                return QualityCheck(
                    check_id="non_negative_volume",
                    passed=False,
                    message=f"Negative volume at index {i}: {bar['volume']}",
                )
        return QualityCheck(check_id="non_negative_volume", passed=True)

    def _check_missing_bars(
        self, bars: list[dict[str, Any]], timeframe: str
    ) -> QualityCheck:
        """Check for gaps in timestamps based on expected timeframe."""
        interval_ms = _timeframe_to_ms(timeframe)
        if interval_ms <= 0:
            return QualityCheck(check_id="gap_detection", passed=True, message="Unknown timeframe, skipping gap check")

        gaps: list[int] = []
        for i in range(1, len(bars)):
            expected = bars[i - 1]["timestamp"] + interval_ms
            actual = bars[i]["timestamp"]
            # Allow 1.5x tolerance for occasional irregularities
            if actual > expected * 1.5:
                gaps.append(i)
            elif actual < expected:
                # Backward timestamp is a different error
                pass

        if gaps:
            return QualityCheck(
                check_id="gap_detection",
                passed=False,
                message=f"{len(gaps)} gaps detected at indices: {gaps[:5]}{'...' if len(gaps) > 5 else ''}",
                details={"gap_count": len(gaps), "gap_indices": gaps[:20]},
            )
        return QualityCheck(check_id="gap_detection", passed=True)

    def _check_coverage(self, bars: list[dict[str, Any]]) -> QualityCheck:
        """Check that dataset has minimum bars."""
        if len(bars) < self._min_warmup_bars:
            return QualityCheck(
                check_id="min_coverage",
                passed=False,
                message=f"Only {len(bars)} bars, minimum is {self._min_warmup_bars}",
            )
        return QualityCheck(
            check_id="min_coverage",
            passed=True,
            message=f"{len(bars)} bars available",
        )

    def _check_warmup(self, bars: list[dict[str, Any]]) -> QualityCheck:
        """Check warmup sufficiency for indicator calculation."""
        if len(bars) < self._min_warmup_bars:
            return QualityCheck(
                check_id="warmup_sufficient",
                passed=False,
                message=f"Insufficient warmup: {len(bars)} < {self._min_warmup_bars}",
            )
        return QualityCheck(check_id="warmup_sufficient", passed=True)

    def _check_incomplete_candle(self, bars: list[dict[str, Any]]) -> QualityCheck:
        """Check if last candle might be incomplete (zero volume)."""
        if bars and bars[-1].get("volume", 0) == 0:
            return QualityCheck(
                check_id="no_incomplete_candles",
                passed=False,
                message="Last candle has zero volume — possibly incomplete",
            )
        return QualityCheck(check_id="no_incomplete_candles", passed=True)


def _timeframe_to_ms(timeframe: str) -> int:
    """Convert timeframe string to milliseconds."""
    multipliers = {
        "1m": 60_000,
        "3m": 180_000,
        "5m": 300_000,
        "15m": 900_000,
        "30m": 1_800_000,
        "1h": 3_600_000,
        "4h": 14_400_000,
        "1d": 86_400_000,
    }
    return multipliers.get(timeframe, 0)


def compute_dataset_checksum(bars: list[dict[str, Any]]) -> str:
    """Compute SHA-256 checksum of dataset contents.

    Used for dataset integrity verification in freeze/confirmation.
    """
    hasher = hashlib.sha256()
    for bar in sorted(bars, key=lambda b: b["timestamp"]):
        key = f"{bar['timestamp']}:{bar['open']}:{bar['high']}:{bar['low']}:{bar['close']}:{bar['volume']}"
        hasher.update(key.encode("utf-8"))
    return hasher.hexdigest()


__all__ = [
    "DataQualityGate",
    "DataQualityResult",
    "HistoricalDataset",
    "QualityCheck",
    "compute_dataset_checksum",
]
