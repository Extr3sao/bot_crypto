"""Counting observation days, not experiments.

Six experiments reading the same 46 days of BTC/ETH/SOL 1m bars have produced **one** period of
market history and six claims. That is what the ``EXP-003J`` / ``EXP-003K`` pair already taught
this repository the hard way: J's 505 closes are K's ``real`` arm, and counting them twice turns a
single negative result into two.

The unit of independent evidence is therefore a *day*, identified by its calendar date and by the
digest of the bytes it was measured from. An experiment adds observations only in proportion to
days it uses that no other experiment used. Nothing here can create evidence; it can only refrain
from inflating it.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "DuplicateUsage",
    "ObservationBook",
    "Usage",
    "experiments_sharing",
    "independent_day_count",
]


@dataclass(frozen=True, slots=True)
class Usage:
    """One experiment's claim on one day of one dataset."""

    experiment_id: str
    day: str
    evidence: str
    dataset: str = ""

    def key(self) -> tuple[str, str]:
        return (self.day, self.evidence)


@dataclass(frozen=True, slots=True)
class DuplicateUsage:
    """A day more than one experiment relied on."""

    day: str
    experiments: tuple[str, ...]
    evidence: str
    same_bytes: bool
    reading: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "day": self.day,
            "experiments": list(self.experiments),
            "evidence": self.evidence,
            "same_bytes": self.same_bytes,
            "reading": self.reading,
        }


@dataclass(slots=True)
class ObservationBook:
    """Accumulates who used which day, and answers with counts that cannot double-count."""

    _usages: list[Usage] = field(default_factory=list)

    def use(self, experiment_id: str, day: str, evidence: str, dataset: str = "") -> Usage:
        if not experiment_id:
            raise ValueError("experiment_id must be non-empty")
        if not day:
            raise ValueError("day must be non-empty")
        if not evidence:
            # An observation whose bytes are unnamed cannot be shown to be the same observation
            # as somebody else's, so it cannot be counted as independent.
            raise ValueError("evidence digest is required to count an observation")
        usage = Usage(experiment_id=experiment_id, day=day, evidence=evidence, dataset=dataset)
        self._usages.append(usage)
        return usage

    @property
    def usages(self) -> tuple[Usage, ...]:
        return tuple(self._usages)

    def experiments(self) -> tuple[str, ...]:
        return tuple(sorted({usage.experiment_id for usage in self._usages}))

    def days(self) -> tuple[str, ...]:
        return tuple(sorted({usage.day for usage in self._usages}))

    def independent_day_count(self) -> int:
        """Distinct (day, evidence) pairs — the number of independent observations."""
        return len({usage.key() for usage in self._usages})

    def duplicates(self) -> tuple[DuplicateUsage, ...]:
        """Days claimed by more than one experiment, with whether they read the same bytes."""
        buckets: dict[str, list[Usage]] = {}
        for usage in self._usages:
            buckets.setdefault(usage.day, []).append(usage)
        found: list[DuplicateUsage] = []
        for day, rows in sorted(buckets.items()):
            names = tuple(sorted({row.experiment_id for row in rows}))
            if len(names) < 2:
                continue
            digests = {row.evidence for row in rows}
            same_bytes = len(digests) == 1
            found.append(
                DuplicateUsage(
                    day=day,
                    experiments=names,
                    evidence=sorted(digests)[0],
                    same_bytes=same_bytes,
                    reading=(
                        "same bytes read by several experiments: one observation, counted once"
                        if same_bytes
                        else "the same day was read from DIFFERENT bytes, which is a rewrite signal"
                    ),
                )
            )
        return tuple(found)

    def fresh_days_for(self, experiment_id: str) -> tuple[str, ...]:
        """Days this experiment used that no *other* experiment used."""
        mine = {usage.day for usage in self._usages if usage.experiment_id == experiment_id}
        theirs = {
            usage.day for usage in self._usages if usage.experiment_id != experiment_id
        }
        return tuple(sorted(mine - theirs))

    def inflation(self) -> dict[str, Any]:
        """How much a naive sum over experiments would have overstated the evidence."""
        naive = len(self._usages)
        independent = self.independent_day_count()
        return {
            "naive_observation_count": naive,
            "independent_day_count": independent,
            "overstated_by": naive - independent,
            "overstatement_factor": round(naive / independent, 4) if independent else None,
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "experiments": list(self.experiments()),
            "days": list(self.days()),
            "usages": [
                {
                    "experiment_id": usage.experiment_id,
                    "day": usage.day,
                    "evidence": usage.evidence,
                    "dataset": usage.dataset,
                }
                for usage in self._usages
            ],
            "duplicates": [row.as_dict() for row in self.duplicates()],
            **self.inflation(),
        }


def independent_day_count(usages: Iterable[Usage | tuple[str, str, str]]) -> int:
    """Distinct (day, evidence) pairs across any mix of ``Usage`` rows and tuples."""
    keys: set[tuple[str, str]] = set()
    for row in usages:
        if isinstance(row, Usage):
            keys.add(row.key())
        else:
            _, day, evidence = row
            if not evidence:
                raise ValueError("evidence digest is required to count an observation")
            keys.add((day, evidence))
    return len(keys)


def experiments_sharing(usages: Sequence[Usage], day: str) -> tuple[str, ...]:
    """Which experiments touched one day, sorted and deduplicated."""
    return tuple(sorted({row.experiment_id for row in usages if row.day == day}))
