"""Lightweight in-memory metrics collector (Fase 8).

No external dependencies (no Prometheus, no database).
Collects counters, gauges, and histograms in memory.
Thread-safe not required (single-threaded trading loop).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MetricPoint:
    """A single metric data point."""

    name: str
    value: float
    timestamp: float = field(default_factory=time.time)
    tags: dict[str, str] = field(default_factory=dict)


class MetricsCollector:
    """In-memory metrics collector.

    Supports:
    - Counters (monotonic increment)
    - Gauges (set to value)
    - Histograms (record observations)
    - Snapshots (read current state)
    """

    def __init__(self) -> None:
        self._counters: dict[str, float] = {}
        self._gauges: dict[str, float] = {}
        self._histograms: dict[str, list[float]] = {}
        self._points: list[MetricPoint] = []

    def increment(self, name: str, value: float = 1.0, tags: dict[str, str] | None = None) -> None:
        """Increment a counter."""
        self._counters[name] = self._counters.get(name, 0.0) + value
        self._points.append(MetricPoint(name=name, value=self._counters[name], tags=tags or {}))

    def gauge(self, name: str, value: float, tags: dict[str, str] | None = None) -> None:
        """Set a gauge value."""
        self._gauges[name] = value
        self._points.append(MetricPoint(name=name, value=value, tags=tags or {}))

    def histogram(self, name: str, value: float, tags: dict[str, str] | None = None) -> None:
        """Record a histogram observation."""
        if name not in self._histograms:
            self._histograms[name] = []
        self._histograms[name].append(value)
        self._points.append(MetricPoint(name=name, value=value, tags=tags or {}))

    def counter(self, name: str) -> float:
        """Get current counter value."""
        return self._counters.get(name, 0.0)

    def gauge_value(self, name: str) -> float | None:
        """Get current gauge value."""
        return self._gauges.get(name)

    def histogram_stats(self, name: str) -> dict[str, float] | None:
        """Get histogram statistics."""
        values = self._histograms.get(name)
        if not values:
            return None
        sorted_vals = sorted(values)
        n = len(sorted_vals)
        return {
            "count": n,
            "sum": sum(sorted_vals),
            "min": sorted_vals[0],
            "max": sorted_vals[-1],
            "mean": sum(sorted_vals) / n,
            "p50": sorted_vals[n // 2],
            "p95": sorted_vals[int(n * 0.95)] if n >= 20 else sorted_vals[-1],
            "p99": sorted_vals[int(n * 0.99)] if n >= 100 else sorted_vals[-1],
        }

    def snapshot(self) -> dict[str, Any]:
        """Return a complete snapshot of all metrics."""
        return {
            "counters": dict(self._counters),
            "gauges": dict(self._gauges),
            "histograms": {name: self.histogram_stats(name) for name in self._histograms},
            "total_points": len(self._points),
        }

    def reset(self) -> None:
        """Reset all metrics."""
        self._counters.clear()
        self._gauges.clear()
        self._histograms.clear()
        self._points.clear()


__all__ = ["MetricPoint", "MetricsCollector"]
