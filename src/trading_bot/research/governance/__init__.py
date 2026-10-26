"""ARP-008 POST-OOS RECOVERY — experiment contract governance (research-only).

This package hardens the experiment lifecycle that EXP-ARP-008 violated. It is
deliberately isolated: no runtime module imports it, and it can neither size,
risk-check, execute nor promote anything. It provides:

* :mod:`contract` — :class:`ExperimentContractValidator`, the deterministic
  pre-execution comparison of SPEC / MANIFEST / IMPLEMENTATION / SPLITS /
  COST_MODEL that fails closed with ``EXPERIMENT_INVALID``;
* :mod:`splits`   — :class:`SplitDefinition` and :class:`ImmutableSplitRegistry`,
  which make a post-registration split change require a ``NEW_EXPERIMENT_ID``;
* :mod:`holdout`  — :class:`HoldoutRegistry`, the consumed-holdout ledger with
  ``UNTOUCHED`` / ``OPENED`` / ``CONSUMED`` (CONSUMED is absorbing);
* :mod:`terminal` — :class:`TerminalState` and
  :class:`TerminalExperimentRegistry`, which refuse to edit or resume a finished
  experiment (``NEW_HYPOTHESIS + NEW_EXPERIMENT_ID``);
* :mod:`hashing`  — canonical JSON hashing shared by all of the above.
"""

from __future__ import annotations

from .contract import (
    EXPERIMENT_INVALID,
    ExperimentContract,
    ExperimentContractValidator,
    ExperimentInvalidError,
    contract_hash,
)
from .hashing import canonical_hash, canonical_json
from .holdout import (
    Holdout,
    HoldoutRegistry,
    HoldoutReuseError,
    HoldoutStatus,
)
from .splits import (
    NEW_EXPERIMENT_REQUIRED,
    ImmutableSplitRegistry,
    SplitDefinition,
    SplitMutationError,
)
from .terminal import (
    NEW_HYPOTHESIS_REQUIRED,
    TerminalExperimentMutationError,
    TerminalExperimentRecord,
    TerminalExperimentRegistry,
    TerminalState,
)

__all__ = [
    "EXPERIMENT_INVALID",
    "NEW_EXPERIMENT_REQUIRED",
    "NEW_HYPOTHESIS_REQUIRED",
    "ExperimentContract",
    "ExperimentContractValidator",
    "ExperimentInvalidError",
    "Holdout",
    "HoldoutRegistry",
    "HoldoutReuseError",
    "HoldoutStatus",
    "ImmutableSplitRegistry",
    "SplitDefinition",
    "SplitMutationError",
    "TerminalExperimentMutationError",
    "TerminalExperimentRecord",
    "TerminalExperimentRegistry",
    "TerminalState",
    "canonical_hash",
    "canonical_json",
    "contract_hash",
]
