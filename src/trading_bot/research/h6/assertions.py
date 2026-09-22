"""Bootstrap assertions for H6 preparation package.

These are lightweight, in-code assertions used by tests and runtime
guards. They must agree with the frozen spec, not with prompt memory.
"""

from __future__ import annotations

from trading_bot.research.h6.contracts import DATASET_SHA256, SPEC_SHA256
from trading_bot.research.h6.drift_guard import (
    EXPECTED_DATASET_SHA256,
    EXPECTED_SPEC_SHA256,
)


def _assert_frozen_hashes_match_internal_authority() -> None:
    if SPEC_SHA256 != EXPECTED_SPEC_SHA256:
        raise RuntimeError("internal spec sha drift")
    if DATASET_SHA256 != EXPECTED_DATASET_SHA256:
        raise RuntimeError("internal dataset sha drift")


_assert_frozen_hashes_match_internal_authority()
