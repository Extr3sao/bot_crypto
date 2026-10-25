"""Disk budget planning for bounded capture windows (WP-9B).

The paper lab's first 24 h window stopped after 4.16 h because it was launched with a
collector valve of 800 MB while its own measured rate was 192 MB/h: 24 h needed 4.6 GB,
the valve could pay for 4.16 h, and the guard did exactly what it was told. Nothing in
the code was wrong and nothing in the run was unpredictable — the two facts were simply
never compared before the run started.

This module is that comparison, kept separate from the launcher so it can be reasoned
about and tested without starting a process:

* **the rate is a declared input with a named source** — measured from a sealed window,
  supplied by the operator, or a conservative declared fallback. It is never invented
  here, and the plan always says which one it used;
* **the requirement is at the stress rate by default** (the observed peak hour, not the
  mean), because a plan built on the mean under-provisions the next bad hour;
* **fail closed**: a window whose valve cannot pay for itself is ``INCOHERENT_BUDGET``
  and a window whose free space cannot pay for it at all is
  ``INSUFFICIENT_FREE_SPACE``. The first may be repaired by autoscaling the valve
  (recorded, not silent); the second may not be repaired by any flag this module knows,
  because disk size is not a preference.

Nothing here writes, deletes or measures a file: ``plan_window`` is pure, and
``free_bytes`` is a single ``statvfs``-equivalent call the caller makes explicitly.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Conservative rate used when nobody measured one: the highest hour actually observed
#: in this lane's captured windows (223.6 MB/h peak vs 192.3 MB/h mean). Declared here
#: with its provenance so a reader can disagree with the number rather than wonder where
#: it came from.
DECLARED_FALLBACK_BYTES_PER_HOUR = 240_000_000
DECLARED_FALLBACK_SOURCE = (
    "declared conservative fallback: the peak hour observed in the sealed window "
    "(223.6 MB/h) rounded up; not a measurement of the window about to run"
)

#: The peak-to-mean ratio the plan provisions for by default.
DEFAULT_STRESS_MULTIPLIER = 1.5

#: Free space the host must keep for itself and the other writers on this volume.
DEFAULT_RESERVE_BYTES = 2_000_000_000

STATE_COHERENT = "COHERENT"
STATE_TIGHT = "TIGHT"
STATE_INCOHERENT_BUDGET = "INCOHERENT_BUDGET"
STATE_INSUFFICIENT_FREE_SPACE = "INSUFFICIENT_FREE_SPACE"
STATE_UNBOUNDED = "UNBOUNDED"

#: States a launcher must refuse to start in (unless the plan was autoscaled, which can
#: only repair ``INCOHERENT_BUDGET``).
REFUSED_STATES = (STATE_INCOHERENT_BUDGET, STATE_INSUFFICIENT_FREE_SPACE)


def free_bytes(path: Path | str) -> int:
    """Free bytes on the volume ``path`` lives on. The only I/O in this module."""
    return int(shutil.disk_usage(str(path)).free)


@dataclass(frozen=True)
class DiskBudgetPlan:
    """What a window needs and whether it can be paid for."""

    hours: float
    rate_bytes_per_hour: float
    rate_source: str
    overhead_bytes_per_hour: float
    stress_multiplier: float
    required_bytes: int
    required_bytes_at_stress: int
    collector_max_bytes: int
    free_bytes: int
    reserve_bytes: int
    state: str
    autoscaled: bool = False
    reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return self.state not in REFUSED_STATES

    @property
    def effective_rate_bytes_per_hour(self) -> float:
        return self.rate_bytes_per_hour + self.overhead_bytes_per_hour

    @property
    def hours_affordable_by_valve(self) -> float:
        rate = self.effective_rate_bytes_per_hour
        return self.collector_max_bytes / rate if rate else 0.0

    @property
    def hours_affordable_by_disk(self) -> float:
        rate = self.effective_rate_bytes_per_hour
        return max(0, self.free_bytes - self.reserve_bytes) / rate if rate else 0.0

    @property
    def recommended_collector_max_bytes(self) -> int:
        """The valve that can pay for this window at the stress rate."""
        return round(self.required_bytes_at_stress)

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "hours": self.hours,
            "rate_bytes_per_hour": round(self.rate_bytes_per_hour, 3),
            "rate_source": self.rate_source,
            "overhead_bytes_per_hour": round(self.overhead_bytes_per_hour, 3),
            "effective_rate_bytes_per_hour": round(self.effective_rate_bytes_per_hour, 3),
            "stress_multiplier": self.stress_multiplier,
            "required_gb": round(self.required_bytes / 1e9, 3),
            "required_gb_at_stress": round(self.required_bytes_at_stress / 1e9, 3),
            "collector_max_bytes": self.collector_max_bytes,
            "collector_max_gb": round(self.collector_max_bytes / 1e9, 3),
            "free_bytes": self.free_bytes,
            "free_gb": round(self.free_bytes / 1e9, 3),
            "reserve_bytes": self.reserve_bytes,
            "hours_affordable_by_valve": round(self.hours_affordable_by_valve, 3),
            "hours_affordable_by_disk": round(self.hours_affordable_by_disk, 3),
            "recommended_collector_max_bytes": self.recommended_collector_max_bytes,
            "autoscaled": self.autoscaled,
            "ok": self.ok,
            "reasons": list(self.reasons),
        }


def plan_window(
    *,
    hours: float,
    collector_max_bytes: int,
    free: int,
    rate_bytes_per_hour: float | None = None,
    rate_source: str | None = None,
    overhead_bytes_per_hour: float = 0.0,
    stress_multiplier: float = DEFAULT_STRESS_MULTIPLIER,
    reserve_bytes: int = DEFAULT_RESERVE_BYTES,
    autoscale: bool = False,
) -> DiskBudgetPlan:
    """Decide whether a window of ``hours`` can be captured, and say why.

    ``hours <= 0`` means "until stopped": there is no requirement to compare against, so
    the plan is informational (``UNBOUNDED``) and publishes how many hours the valve and
    the free space each afford.
    """
    if rate_bytes_per_hour is None:
        rate_bytes_per_hour, rate_source = (
            DECLARED_FALLBACK_BYTES_PER_HOUR,
            (rate_source or DECLARED_FALLBACK_SOURCE),
        )
    rate = max(0.0, rate_bytes_per_hour) + max(0.0, overhead_bytes_per_hour)
    source = rate_source or "declared"

    if hours <= 0:
        plan = DiskBudgetPlan(
            hours=hours,
            rate_bytes_per_hour=rate_bytes_per_hour,
            rate_source=source,
            overhead_bytes_per_hour=overhead_bytes_per_hour,
            stress_multiplier=stress_multiplier,
            required_bytes=0,
            required_bytes_at_stress=0,
            collector_max_bytes=collector_max_bytes,
            free_bytes=free,
            reserve_bytes=reserve_bytes,
            state=STATE_UNBOUNDED,
            reasons=(
                "no window declared (until stopped): the valve affords "
                f"{collector_max_bytes / rate:.2f} h and the free space affords "
                f"{max(0, free - reserve_bytes) / rate:.2f} h at "
                f"{rate / 1e6:.2f} MB/h",
            ),
        )
        return plan

    required = round(rate * hours)
    required_stress = round(rate * stress_multiplier * hours)
    usable = free - reserve_bytes
    reasons: list[str] = []

    if required_stress > usable:
        reasons.append(
            f"free space cannot pay for the window: {required_stress / 1e9:.3f} GB needed at "
            f"{stress_multiplier}x, {max(0, usable) / 1e9:.3f} GB usable above the "
            f"{reserve_bytes / 1e9:.3f} GB reserve"
        )
        return DiskBudgetPlan(
            hours=hours,
            rate_bytes_per_hour=rate_bytes_per_hour,
            rate_source=source,
            overhead_bytes_per_hour=overhead_bytes_per_hour,
            stress_multiplier=stress_multiplier,
            required_bytes=required,
            required_bytes_at_stress=required_stress,
            collector_max_bytes=collector_max_bytes,
            free_bytes=free,
            reserve_bytes=reserve_bytes,
            state=STATE_INSUFFICIENT_FREE_SPACE,
            reasons=tuple(reasons),
        )

    if collector_max_bytes < required:
        if not autoscale:
            reasons.append(
                f"the collector valve cannot pay for the window: {collector_max_bytes / 1e9:.3f} GB "
                f"affords {collector_max_bytes / rate:.2f} h of the {hours:.2f} h declared, and "
                f"{required / 1e9:.3f} GB is needed at {rate / 1e6:.2f} MB/h "
                f"(this is the defect that stopped the first 24 h window)"
            )
            return DiskBudgetPlan(
                hours=hours,
                rate_bytes_per_hour=rate_bytes_per_hour,
                rate_source=source,
                overhead_bytes_per_hour=overhead_bytes_per_hour,
                stress_multiplier=stress_multiplier,
                required_bytes=required,
                required_bytes_at_stress=required_stress,
                collector_max_bytes=collector_max_bytes,
                free_bytes=free,
                reserve_bytes=reserve_bytes,
                state=STATE_INCOHERENT_BUDGET,
                reasons=tuple(reasons),
            )
        reasons.append(
            f"valve autoscaled from {collector_max_bytes} B to {required_stress} B so it can pay "
            f"for {hours:.2f} h at {stress_multiplier}x the measured rate (recorded, not silent)"
        )
        state = STATE_COHERENT
        return DiskBudgetPlan(
            hours=hours,
            rate_bytes_per_hour=rate_bytes_per_hour,
            rate_source=source,
            overhead_bytes_per_hour=overhead_bytes_per_hour,
            stress_multiplier=stress_multiplier,
            required_bytes=required,
            required_bytes_at_stress=required_stress,
            collector_max_bytes=required_stress,
            free_bytes=free,
            reserve_bytes=reserve_bytes,
            state=state,
            autoscaled=True,
            reasons=tuple(reasons),
        )

    if collector_max_bytes < required_stress:
        reasons.append(
            f"the valve pays for the mean hour but not the peak one: {collector_max_bytes / 1e9:.3f} GB "
            f"vs {required_stress / 1e9:.3f} GB at {stress_multiplier}x; the window runs, and the "
            f"recommended valve is {required_stress} B"
        )
        return DiskBudgetPlan(
            hours=hours,
            rate_bytes_per_hour=rate_bytes_per_hour,
            rate_source=source,
            overhead_bytes_per_hour=overhead_bytes_per_hour,
            stress_multiplier=stress_multiplier,
            required_bytes=required,
            required_bytes_at_stress=required_stress,
            collector_max_bytes=collector_max_bytes,
            free_bytes=free,
            reserve_bytes=reserve_bytes,
            state=STATE_TIGHT,
            reasons=tuple(reasons),
        )

    reasons.append(
        f"the valve pays for {hours:.2f} h at {stress_multiplier}x ({collector_max_bytes / 1e9:.3f} GB "
        f"available, {required_stress / 1e9:.3f} GB needed) and the host keeps "
        f"{(usable - required_stress) / 1e9:.3f} GB above the reserve"
    )
    return DiskBudgetPlan(
        hours=hours,
        rate_bytes_per_hour=rate_bytes_per_hour,
        rate_source=source,
        overhead_bytes_per_hour=overhead_bytes_per_hour,
        stress_multiplier=stress_multiplier,
        required_bytes=required,
        required_bytes_at_stress=required_stress,
        collector_max_bytes=collector_max_bytes,
        free_bytes=free,
        reserve_bytes=reserve_bytes,
        state=STATE_COHERENT,
        reasons=tuple(reasons),
    )
