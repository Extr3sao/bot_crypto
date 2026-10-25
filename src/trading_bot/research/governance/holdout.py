"""ARP-008 §6,§7 — the consumed-holdout registry and OOS firewall.

A *holdout* is a date range (over a set of assets, on a dataset with a known
hash) that may be read **at most once**. The registry records every holdout with
its accessors and its lifecycle state:

* ``UNTOUCHED`` — never read; the only state from which OOS may run;
* ``OPENED``    — first market-data access has happened; result not yet recorded;
* ``CONSUMED``  — the one-time test is over (pass, fail, invalid or crash).

``CONSUMED`` is absorbing: no transition ever returns a holdout to
``UNTOUCHED`` or ``OPENED``. The firewall helper :meth:`assert_untouched` must be
called *before* any OOS read; :meth:`mark_consumed` must be called in ``finally``
so a crash, an invalid result or a failed experiment still burns the holdout and
cannot be re-run.

Research-only: no runtime module imports it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from .hashing import canonical_hash

__all__ = [
    "Holdout",
    "HoldoutRegistry",
    "HoldoutReuseError",
    "HoldoutStatus",
    "utc_now_iso",
]


def utc_now_iso() -> str:
    """Current UTC timestamp in ISO-8601 (the registry's clock interface)."""
    return datetime.now(UTC).isoformat()


class HoldoutStatus(StrEnum):
    """Lifecycle of one holdout; ``CONSUMED`` is absorbing."""

    UNTOUCHED = "UNTOUCHED"
    OPENED = "OPENED"
    CONSUMED = "CONSUMED"


class HoldoutReuseError(RuntimeError):
    """Raised when a consumed/opened holdout is accessed or re-opened."""


@dataclass(frozen=True, slots=True)
class Holdout:
    """One frozen, at-most-once holdout."""

    holdout_id: str
    start: str
    end: str
    assets: tuple[str, ...]
    dataset_hash: str
    status: HoldoutStatus = HoldoutStatus.UNTOUCHED
    accessed_by: tuple[str, ...] = ()
    first_access_timestamp: str | None = None
    note: str = ""
    #: True when the range only becomes readable through forward collection
    #: (PAPER); it is still UNTOUCHED but is not yet statically available.
    forward_only: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.status, HoldoutStatus):
            object.__setattr__(self, "status", HoldoutStatus(self.status))
        if not isinstance(self.accessed_by, tuple):
            object.__setattr__(self, "accessed_by", tuple(self.accessed_by))

    def descriptor(self) -> dict[str, Any]:
        return {
            "holdout_id": self.holdout_id,
            "start": self.start,
            "end": self.end,
            "assets": list(self.assets),
            "dataset_hash": self.dataset_hash,
        }

    def descriptor_hash(self) -> str:
        return canonical_hash(self.descriptor())

    def to_dict(self) -> dict[str, Any]:
        return {
            "holdout_id": self.holdout_id,
            "start": self.start,
            "end": self.end,
            "assets": list(self.assets),
            "dataset_hash": self.dataset_hash,
            "status": self.status.value,
            "accessed_by": list(self.accessed_by),
            "first_access_timestamp": self.first_access_timestamp,
            "note": self.note,
            "forward_only": self.forward_only,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Holdout:
        return cls(
            holdout_id=str(data["holdout_id"]),
            start=str(data["start"]),
            end=str(data["end"]),
            assets=tuple(str(a) for a in data.get("assets", ())),
            dataset_hash=str(data.get("dataset_hash", "")),
            status=HoldoutStatus(str(data.get("status", "UNTOUCHED"))),
            accessed_by=tuple(str(a) for a in data.get("accessed_by", ())),
            first_access_timestamp=data.get("first_access_timestamp"),
            note=str(data.get("note", "")),
            forward_only=bool(data.get("forward_only", False)),
        )


class HoldoutRegistry:
    """Deterministic, persistable registry of holdouts and their accessors."""

    def __init__(self) -> None:
        self._holdouts: dict[str, Holdout] = {}

    # ------------------------------------------------------------------ read
    def get(self, holdout_id: str) -> Holdout:
        try:
            return self._holdouts[holdout_id]
        except KeyError as exc:
            raise KeyError(f"unknown holdout {holdout_id!r}") from exc

    def status(self, holdout_id: str) -> HoldoutStatus:
        return self.get(holdout_id).status

    def assert_untouched(self, holdout_id: str) -> Holdout:
        """OOS firewall: a holdout may only be read while ``UNTOUCHED``."""
        holdout = self.get(holdout_id)
        if holdout.status is not HoldoutStatus.UNTOUCHED:
            raise HoldoutReuseError(
                f"{holdout_id}: status is {holdout.status.value}, refusing OOS access "
                f"(accessed_by={list(holdout.accessed_by)})"
            )
        return holdout

    # ----------------------------------------------------------------- write
    def register(self, holdout: Holdout) -> str:
        """Register a holdout. Re-registering the same descriptor is idempotent."""
        existing = self._holdouts.get(holdout.holdout_id)
        if existing is not None:
            if existing.descriptor_hash() != holdout.descriptor_hash():
                raise HoldoutReuseError(
                    f"{holdout.holdout_id}: descriptor changed after registration"
                )
            return existing.descriptor_hash()
        self._holdouts[holdout.holdout_id] = holdout
        return holdout.descriptor_hash()

    def mark_opened(
        self, holdout_id: str, experiment_id: str, *, timestamp: str | None = None
    ) -> Holdout:
        """Record the first market-data access (before the result is known)."""
        holdout = self.get(holdout_id)
        if holdout.status is HoldoutStatus.CONSUMED:
            raise HoldoutReuseError(
                f"{holdout_id}: already CONSUMED; cannot re-open (NEW holdout required)"
            )
        accessed = holdout.accessed_by
        if experiment_id not in accessed:
            accessed = (*accessed, experiment_id)
        updated = replace(
            holdout,
            status=HoldoutStatus.OPENED,
            accessed_by=accessed,
            first_access_timestamp=holdout.first_access_timestamp
            or (timestamp or utc_now_iso()),
        )
        self._holdouts[holdout_id] = updated
        return updated

    def mark_consumed(
        self, holdout_id: str, experiment_id: str, *, timestamp: str | None = None
    ) -> Holdout:
        """Burn the holdout after the one-time test — success, failure or crash."""
        holdout = self.get(holdout_id)
        accessed = holdout.accessed_by
        if experiment_id and experiment_id not in accessed:
            accessed = (*accessed, experiment_id)
        updated = replace(
            holdout,
            status=HoldoutStatus.CONSUMED,
            accessed_by=accessed,
            first_access_timestamp=holdout.first_access_timestamp
            or (timestamp or utc_now_iso()),
        )
        self._holdouts[holdout_id] = updated
        return updated

    def consumed_ids(self) -> tuple[str, ...]:
        return tuple(
            h.holdout_id for h in self._holdouts.values() if h.status is HoldoutStatus.CONSUMED
        )

    # ------------------------------------------------------------ persistence
    def to_dict(self) -> dict[str, Any]:
        return {
            "holdouts": {h.holdout_id: h.to_dict() for h in self._holdouts.values()},
            "registry_hash": canonical_hash(
                {h.holdout_id: h.descriptor() for h in self._holdouts.values()}
            ),
        }

    def save(self, path: Path | str) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True), encoding="utf-8")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HoldoutRegistry:
        registry = cls()
        for entry in data.get("holdouts", {}).values():
            registry.register(Holdout.from_dict(entry))
        return registry

    @classmethod
    def load(cls, path: Path | str) -> HoldoutRegistry:
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
