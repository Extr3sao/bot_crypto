"""Portable resource measurement for the collector (§42).

The collector must not be able to degrade the PAPER runtime by stealth, so its
CPU, memory, network and disk cost is measured and reported rather than assumed.
Only the standard library is used: adding a process-inspection dependency for a
research collector would be a poor trade.

Memory reporting is best effort and explicitly labelled as such — ``None`` means
"this platform did not tell us", never "zero".
"""

from __future__ import annotations

import ctypes
import importlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "ResourceSample",
    "ResourceSampler",
    "ResourceSummary",
    "percentile",
    "process_cpu_seconds",
    "process_memory_mb",
]


def process_cpu_seconds() -> float:
    """Total CPU seconds (user + system) consumed by this process."""
    return time.process_time()


def process_memory_mb() -> float | None:
    """Resident set size in MiB, or ``None`` when the platform withholds it."""
    # POSIX
    try:
        resource = importlib.import_module("resource")
        getrusage = getattr(resource, "getrusage", None)
        rusage_self = getattr(resource, "RUSAGE_SELF", None)
        if getrusage is None or rusage_self is None:
            raise AttributeError("resource module lacks getrusage/RUSAGE_SELF")
        usage = getrusage(rusage_self)
        maxrss = float(usage.ru_maxrss)
        # Linux reports KiB, macOS reports bytes.
        divisor = 1024.0 if maxrss > 1024 * 1024 * 10 else 1024.0 * 1024.0
        return maxrss / divisor
    except Exception:
        pass
    # Windows
    if hasattr(ctypes, "windll"):  # pragma: no cover - windows only
        try:

            class _ProcessMemoryCounters(ctypes.Structure):
                _fields_ = [
                    ("cb", ctypes.c_ulong),
                    ("PageFaultCount", ctypes.c_ulong),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            # Restypes must be declared explicitly: the default ``int`` return
            # type truncates the process HANDLE and the call silently fails.
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            kernel32.GetCurrentProcess.restype = ctypes.c_void_p
            getter = getattr(psapi, "GetProcessMemoryInfo", None)
            if getter is None:
                return None
            getter.restype = ctypes.c_int
            getter.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(_ProcessMemoryCounters),
                ctypes.c_uint,
            ]
            counters = _ProcessMemoryCounters()
            counters.cb = ctypes.sizeof(_ProcessMemoryCounters)
            handle = kernel32.GetCurrentProcess()
            if getter(handle, ctypes.byref(counters), counters.cb):
                return float(counters.WorkingSetSize) / (1024.0 * 1024.0)
        except Exception:
            return None
    return None


def percentile(values: list[float], fraction: float) -> float | None:
    """Nearest-rank percentile. Deterministic, no interpolation, no numpy."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = fraction * (len(ordered) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


@dataclass(frozen=True, slots=True)
class ResourceSample:
    wall_time: float
    cpu_seconds: float
    memory_mb: float | None
    disk_bytes: int
    network_bytes: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "wall_time": self.wall_time,
            "cpu_seconds": self.cpu_seconds,
            "memory_mb": self.memory_mb,
            "disk_bytes": self.disk_bytes,
            "network_bytes": self.network_bytes,
        }


@dataclass(frozen=True, slots=True)
class ResourceSummary:
    samples: int
    duration_seconds: float
    cpu_seconds: float
    cpu_utilisation: float
    memory_mb_max: float | None
    memory_mb_final: float | None
    disk_bytes: int
    disk_bytes_per_hour: float
    network_bytes: int
    network_bytes_per_hour: float
    memory_available: bool
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        payload = dict(self.detail)
        payload.update(
            {
                "samples": self.samples,
                "duration_seconds": round(self.duration_seconds, 3),
                "cpu_seconds": round(self.cpu_seconds, 3),
                "cpu_utilisation": round(self.cpu_utilisation, 6),
                "memory_mb_max": self.memory_mb_max,
                "memory_mb_final": self.memory_mb_final,
                "memory_available": self.memory_available,
                "disk_bytes": self.disk_bytes,
                "disk_bytes_per_hour": round(self.disk_bytes_per_hour, 2),
                "network_bytes": self.network_bytes,
                "network_bytes_per_hour": round(self.network_bytes_per_hour, 2),
            }
        )
        return payload


class ResourceSampler:
    """Accumulates samples and derives per-hour rates and peak usage."""

    def __init__(self) -> None:
        self._samples: list[ResourceSample] = []
        self._started_wall: float | None = None
        self._started_cpu: float | None = None

    def start(self) -> None:
        self._started_wall = time.time()
        self._started_cpu = process_cpu_seconds()

    def sample(self, disk_bytes: int, network_bytes: int) -> ResourceSample:
        entry = ResourceSample(
            wall_time=time.time(),
            cpu_seconds=process_cpu_seconds(),
            memory_mb=process_memory_mb(),
            disk_bytes=disk_bytes,
            network_bytes=network_bytes,
        )
        self._samples.append(entry)
        return entry

    @property
    def samples(self) -> list[ResourceSample]:
        return list(self._samples)

    def summary(self, disk_bytes: int, network_bytes: int) -> ResourceSummary:
        started_wall = self._started_wall if self._started_wall is not None else time.time()
        started_cpu = self._started_cpu if self._started_cpu is not None else process_cpu_seconds()
        duration = max(1e-9, time.time() - started_wall)
        cpu_used = max(0.0, process_cpu_seconds() - started_cpu)
        memories = [s.memory_mb for s in self._samples if s.memory_mb is not None]
        hours = duration / 3600.0
        return ResourceSummary(
            samples=len(self._samples),
            duration_seconds=duration,
            cpu_seconds=cpu_used,
            cpu_utilisation=cpu_used / duration,
            memory_mb_max=max(memories) if memories else None,
            memory_mb_final=memories[-1] if memories else None,
            disk_bytes=disk_bytes,
            disk_bytes_per_hour=disk_bytes / hours if hours > 0 else 0.0,
            network_bytes=network_bytes,
            network_bytes_per_hour=network_bytes / hours if hours > 0 else 0.0,
            memory_available=bool(memories),
            detail={
                "memory_measurement": (
                    "process working set / max RSS via stdlib"
                    if memories
                    else "UNAVAILABLE_ON_PLATFORM"
                ),
                "cpu_measurement": "time.process_time() delta over wall-clock delta",
                "disk_measurement": "sum of segment file sizes on disk, measured at sample time",
                "network_measurement": "sum of decoded WebSocket/HTTP payload bytes",
            },
        )


def directory_bytes(path: Path) -> int:
    """Total size of every file under ``path`` (0 when it does not exist)."""
    if not path.exists():
        return 0
    total = 0
    for entry in path.rglob("*"):
        try:
            if entry.is_file():
                total += entry.stat().st_size
        except OSError:  # pragma: no cover - racing deletion
            continue
    return total
