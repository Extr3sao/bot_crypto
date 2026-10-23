"""ARP-008 §1,§8 — terminal experiment states and the no-resume guard.

Once an experiment reaches a terminal state it is *finished*: it may not be
edited, resumed or silently re-run. Any material change (data window, exit,
parameter, asset set, regime filter, adding shorts, dropping an asset) is a new
hypothesis that requires a new ``experiment_id`` under a new pre-registration.

Research-only: no runtime module imports it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from .hashing import canonical_hash

__all__ = [
    "NEW_HYPOTHESIS_REQUIRED",
    "TerminalExperimentMutationError",
    "TerminalExperimentRecord",
    "TerminalExperimentRegistry",
    "TerminalState",
]

#: what a refused edit must be re-expressed as
NEW_HYPOTHESIS_REQUIRED = "NEW_HYPOTHESIS + NEW_EXPERIMENT_ID"


class TerminalState(StrEnum):
    """The only states from which research on a configuration ends."""

    REJECT_NO_EDGE = "REJECT_NO_EDGE"
    REJECT_COSTS = "REJECT_COSTS"
    REJECT_VALIDATION = "REJECT_VALIDATION"
    REJECT_FRAGILE = "REJECT_FRAGILE"
    OOS_FAIL = "OOS_FAIL"
    OOS_INVALID = "OOS_INVALID"


class TerminalExperimentMutationError(RuntimeError):
    """Raised when a terminal experiment is edited or resumed."""


@dataclass(frozen=True, slots=True)
class TerminalExperimentRecord:
    """Immutable terminal record for one experiment."""

    experiment_id: str
    strategy_id: str
    terminal_state: TerminalState
    reason: str
    execution_sha: str
    manifest_hash: str
    spec_hash: str
    dataset_hash: str
    metrics: dict[str, Any] = field(default_factory=dict)
    #: the (start, end) of a holdout this experiment consumed, if any
    oos_window: tuple[str, str] | None = None
    #: additional reproducible hashes (dev/validation/robustness result hashes)
    evidence_hashes: dict[str, str] = field(default_factory=dict)

    @property
    def terminal(self) -> bool:
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "strategy_id": self.strategy_id,
            "status": self.terminal_state.value,
            "terminal": True,
            "reason": self.reason,
            "execution_sha": self.execution_sha,
            "manifest_hash": self.manifest_hash,
            "spec_hash": self.spec_hash,
            "dataset_hash": self.dataset_hash,
            "metrics": self.metrics,
            "oos_window": list(self.oos_window) if self.oos_window else None,
            "evidence_hashes": self.evidence_hashes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TerminalExperimentRecord:
        window = data.get("oos_window")
        return cls(
            experiment_id=str(data["experiment_id"]),
            strategy_id=str(data.get("strategy_id", "")),
            terminal_state=TerminalState(str(data["status"])),
            reason=str(data.get("reason", "")),
            execution_sha=str(data.get("execution_sha", "")),
            manifest_hash=str(data.get("manifest_hash", "")),
            spec_hash=str(data.get("spec_hash", "")),
            dataset_hash=str(data.get("dataset_hash", "")),
            metrics=dict(data.get("metrics", {})),
            oos_window=(str(window[0]), str(window[1])) if window else None,
            evidence_hashes=dict(data.get("evidence_hashes", {})),
        )

    def record_hash(self) -> str:
        return canonical_hash(self.to_dict())


class TerminalExperimentRegistry:
    """Stores terminal records and refuses to edit or resume them."""

    def __init__(self) -> None:
        self._records: dict[str, TerminalExperimentRecord] = {}

    def record(self, record: TerminalExperimentRecord) -> str:
        """Persist a terminal record; return its hash.

        Re-recording the identical record is idempotent. A differing record for
        the same experiment id is a mutation and is refused.
        """
        existing = self._records.get(record.experiment_id)
        if existing is not None:
            if existing.record_hash() != record.record_hash():
                raise TerminalExperimentMutationError(
                    f"{record.experiment_id}: terminal record cannot be edited -> "
                    f"{NEW_HYPOTHESIS_REQUIRED}"
                )
            return existing.record_hash()
        self._records[record.experiment_id] = record
        return record.record_hash()

    def is_terminal(self, experiment_id: str) -> bool:
        return experiment_id in self._records

    def get(self, experiment_id: str) -> TerminalExperimentRecord:
        try:
            return self._records[experiment_id]
        except KeyError as exc:
            raise KeyError(f"{experiment_id}: not a terminal experiment") from exc

    def assert_not_terminal(self, experiment_id: str) -> None:
        """Refuse to (re)run or edit an experiment that is already terminal."""
        if experiment_id in self._records:
            record = self._records[experiment_id]
            raise TerminalExperimentMutationError(
                f"{experiment_id}: already terminal ({record.terminal_state.value}); "
                f"cannot be resumed or edited -> {NEW_HYPOTHESIS_REQUIRED}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiments": {eid: r.to_dict() for eid, r in self._records.items()},
            "registry_hash": canonical_hash({eid: r.to_dict() for eid, r in self._records.items()}),
        }

    def save(self, path: Path | str) -> None:
        Path(path).write_text(self._json(), encoding="utf-8")

    def _json(self) -> str:
        import json

        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TerminalExperimentRegistry:
        registry = cls()
        for entry in data.get("experiments", {}).values():
            registry.record(TerminalExperimentRecord.from_dict(entry))
        return registry
