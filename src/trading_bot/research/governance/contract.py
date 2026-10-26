"""ARP-008 §4 — the deterministic pre-execution :class:`ExperimentContractValidator`.

Before any DEV execution the five frozen views of an experiment must agree:

* **SPEC**                 — the pre-registered spec fields;
* **MANIFEST**             — the pre-registered manifest fields;
* **IMPLEMENTATION**       — the actual code/config the runner would use;
* **SPLITS**               — the six DEV/VALIDATION/OOS boundaries;
* **COST_MODEL**           — the round-trip cost basis.

Each view is supplied as a flat mapping of *normalised* frozen fields (see
``FROZEN_FIELDS``). Any field declared by two or more views whose canonical
values differ marks the experiment ``EXPERIMENT_INVALID`` and refuses DEV
execution. The validator is pure and deterministic: the same contract yields the
same mismatches in the same order on every machine.

Research-only: no runtime module imports it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .hashing import canonical_hash, canonical_json

__all__ = [
    "EXPERIMENT_INVALID",
    "FROZEN_FIELDS",
    "SOURCE_ORDER",
    "ContractMismatch",
    "ContractValidationResult",
    "ExperimentContract",
    "ExperimentContractValidator",
    "ExperimentInvalidError",
    "contract_hash",
]

#: the status a failed contract takes; DEV must not run
EXPERIMENT_INVALID = "EXPERIMENT_INVALID"
CONTRACT_PASS = "PASS"

#: canonical view ordering — fixes mismatch ordering for determinism
SOURCE_ORDER: tuple[str, ...] = (
    "SPEC",
    "MANIFEST",
    "IMPLEMENTATION",
    "SPLITS",
    "COST_MODEL",
)

#: every field the validator compares. A view only declares the subset it owns;
#: the validator compares the union of whatever two or more views declare.
FROZEN_FIELDS: tuple[str, ...] = (
    "experiment_id",
    "strategy_id",
    "timeframe",
    "assets",
    "lookback_days",
    "max_hold_days",
    "entry_rule",
    "exit_rule",
    "dataset_fingerprint",
    "cost_round_trip_bps",
    "cost_model_version",
    "cost_scenario",
    "split_contract",
    "DEV_START",
    "DEV_END",
    "VALIDATION_START",
    "VALIDATION_END",
    "OOS_START",
    "OOS_END",
)


class ExperimentInvalidError(RuntimeError):
    """Raised when a frozen field differs across contract views (STOP)."""

    def __init__(self, result: ContractValidationResult) -> None:
        self.result = result
        detail = "; ".join(
            f"{m.field}: {m.source_a}={m.value_a!r} != {m.source_b}={m.value_b!r}"
            for m in result.mismatches
        )
        super().__init__(f"{result.experiment_id}: {EXPERIMENT_INVALID} ({detail})")


@dataclass(frozen=True, slots=True)
class ContractMismatch:
    """One disagreement between two contract views on a frozen field."""

    field: str
    source_a: str
    value_a: Any
    source_b: str
    value_b: Any

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "source_a": self.source_a,
            "value_a": self.value_a,
            "source_b": self.source_b,
            "value_b": self.value_b,
        }


@dataclass(frozen=True, slots=True)
class ExperimentContract:
    """Five normalised frozen views of one experiment."""

    experiment_id: str
    spec: Mapping[str, Any]
    manifest: Mapping[str, Any]
    implementation_config: Mapping[str, Any]
    split_definition: Mapping[str, Any]
    cost_model: Mapping[str, Any]

    def views(self) -> dict[str, Mapping[str, Any]]:
        return {
            "SPEC": self.spec,
            "MANIFEST": self.manifest,
            "IMPLEMENTATION": self.implementation_config,
            "SPLITS": self.split_definition,
            "COST_MODEL": self.cost_model,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "views": {name: dict(view) for name, view in self.views().items()},
        }


def contract_hash(contract: ExperimentContract) -> str:
    """Deterministic hash of a whole contract (all five views)."""
    return canonical_hash(contract.to_dict())


@dataclass(frozen=True, slots=True)
class ContractValidationResult:
    """Outcome of :meth:`ExperimentContractValidator.validate`."""

    experiment_id: str
    status: str
    mismatches: tuple[ContractMismatch, ...]
    compared_fields: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return self.status == CONTRACT_PASS

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "status": self.status,
            "valid": self.valid,
            "compared_fields": list(self.compared_fields),
            "mismatches": [m.to_dict() for m in self.mismatches],
        }


class ExperimentContractValidator:
    """Compares the frozen views and fails closed on any difference."""

    def __init__(self, fields: Iterable[str] = FROZEN_FIELDS) -> None:
        self._fields: tuple[str, ...] = tuple(fields)

    def _declared(self, view: Mapping[str, Any], field: str) -> tuple[bool, Any]:
        if field in view and view[field] is not None:
            return True, view[field]
        return False, None

    def validate(self, contract: ExperimentContract) -> ContractValidationResult:
        views = contract.views()
        mismatches: list[ContractMismatch] = []
        compared: list[str] = []
        for field in self._fields:
            declared: list[tuple[str, Any]] = []
            for name in SOURCE_ORDER:
                present, value = self._declared(views[name], field)
                if present:
                    declared.append((name, value))
            if len(declared) < 2:
                continue
            compared.append(field)
            base_name, base_value = declared[0]
            base_json = canonical_json(base_value)
            for other_name, other_value in declared[1:]:
                if canonical_json(other_value) != base_json:
                    mismatches.append(
                        ContractMismatch(
                            field=field,
                            source_a=base_name,
                            value_a=base_value,
                            source_b=other_name,
                            value_b=other_value,
                        )
                    )
        status = CONTRACT_PASS if not mismatches else EXPERIMENT_INVALID
        return ContractValidationResult(
            experiment_id=contract.experiment_id,
            status=status,
            mismatches=tuple(mismatches),
            compared_fields=tuple(compared),
        )

    def validate_or_raise(self, contract: ExperimentContract) -> ContractValidationResult:
        """Validate and, on any mismatch, raise — no DEV execution may follow."""
        result = self.validate(contract)
        if not result.valid:
            raise ExperimentInvalidError(result)
        return result

    def assert_dev_allowed(self, contract: ExperimentContract) -> ContractValidationResult:
        """Alias for the pre-DEV gate: PASS or STOP with ``EXPERIMENT_INVALID``."""
        return self.validate_or_raise(contract)
