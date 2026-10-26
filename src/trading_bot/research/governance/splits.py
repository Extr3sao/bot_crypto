"""ARP-008 §5 — immutable split definitions and their persisted hashes.

An experiment's DEV / VALIDATION / OOS boundaries are frozen at
pre-registration. Re-registering the *same* experiment id with a *different*
split is refused (:class:`SplitMutationError`); the caller must mint a
``NEW_EXPERIMENT_ID``. This makes "changing a split after pre-registration"
mechanically impossible instead of merely discouraged.

Research-only: no runtime module imports it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from .hashing import canonical_hash

__all__ = [
    "NEW_EXPERIMENT_REQUIRED",
    "ImmutableSplitRegistry",
    "SplitDefinition",
    "SplitMutationError",
]

#: the string a refusal returns, quoted by the SPEC so the remedy is explicit
NEW_EXPERIMENT_REQUIRED = "NEW_EXPERIMENT_ID"


class SplitMutationError(ValueError):
    """Raised when a pre-registered experiment's split is changed."""


def _parse(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValueError(f"split field {field!r} is not an ISO date: {value!r}") from exc


@dataclass(frozen=True, slots=True)
class SplitDefinition:
    """The six immutable boundaries of an experiment's data split (ISO dates).

    ``DEV`` / ``VALIDATION`` / ``OOS`` must be contiguous, non-empty and in
    strictly increasing order; an invalid definition is rejected at construction.
    """

    dev_start: str
    dev_end: str
    validation_start: str
    validation_end: str
    oos_start: str
    oos_end: str

    def __post_init__(self) -> None:
        bounds = (
            self.dev_start,
            self.dev_end,
            self.validation_start,
            self.validation_end,
            self.oos_start,
            self.oos_end,
        )
        names = self._field_names()
        dev_start, dev_end, val_start, val_end, oos_start, oos_end = (
            _parse(v, n) for v, n in zip(bounds, names, strict=True)
        )
        for name, a, b in (
            ("dev_start", dev_start, dev_end),
            ("validation_start", val_start, val_end),
            ("oos_start", oos_start, oos_end),
        ):
            if not a < b:
                raise ValueError(f"split window {name!r} must have start < end")
        # windows must be ordered and non-overlapping. A gap is permitted and is
        # meaningful: it is where an already-CONSUMED holdout lives, so the new
        # split must not silently re-absorb it.
        if dev_end > val_start or val_end > oos_start:
            raise ValueError("DEV/VALIDATION/OOS splits must be ordered and non-overlapping")

    @staticmethod
    def _field_names() -> tuple[str, ...]:
        return (
            "dev_start",
            "dev_end",
            "validation_start",
            "validation_end",
            "oos_start",
            "oos_end",
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "DEV_START": self.dev_start,
            "DEV_END": self.dev_end,
            "VALIDATION_START": self.validation_start,
            "VALIDATION_END": self.validation_end,
            "OOS_START": self.oos_start,
            "OOS_END": self.oos_end,
        }

    def split_hash(self) -> str:
        """Persisted hash of the frozen split definition."""
        return canonical_hash(self.to_dict())


class ImmutableSplitRegistry:
    """In-memory registry binding one experiment id to exactly one split.

    The registry is intentionally tiny and deterministic: it stores split
    definitions by experiment id and returns the persisted hash. It refuses a
    re-registration that differs from the frozen definition.
    """

    def __init__(self) -> None:
        self._splits: dict[str, SplitDefinition] = {}

    def register(self, experiment_id: str, split: SplitDefinition) -> str:
        """Freeze ``split`` for ``experiment_id``; return its hash.

        Re-registering the identical definition is idempotent. Any difference
        raises :class:`SplitMutationError` demanding a ``NEW_EXPERIMENT_ID``.
        """
        existing = self._splits.get(experiment_id)
        if existing is not None:
            if existing != split:
                raise SplitMutationError(
                    f"{experiment_id}: split definition changed after pre-registration "
                    f"({existing.split_hash()} != {split.split_hash()}) -> "
                    f"{NEW_EXPERIMENT_REQUIRED}"
                )
            return existing.split_hash()
        self._splits[experiment_id] = split
        return split.split_hash()

    def require(self, experiment_id: str, split: SplitDefinition) -> str:
        """Assert the frozen split matches ``split``; return its hash."""
        existing = self._splits.get(experiment_id)
        if existing is None:
            raise KeyError(f"{experiment_id}: no split registered")
        if existing != split:
            raise SplitMutationError(
                f"{experiment_id}: supplied split {split.split_hash()} does not match the "
                f"frozen split {existing.split_hash()} -> {NEW_EXPERIMENT_REQUIRED}"
            )
        return existing.split_hash()

    def frozen_hash(self, experiment_id: str) -> str:
        existing = self._splits.get(experiment_id)
        if existing is None:
            raise KeyError(f"{experiment_id}: no split registered")
        return existing.split_hash()

    def to_dict(self) -> dict[str, Any]:
        return {eid: s.to_dict() for eid, s in self._splits.items()}
