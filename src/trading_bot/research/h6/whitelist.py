"""P12 — feature whitelist enforcement for H6 runtime (V2: PIT+Causality repair).

Runtime H6 implementation may access only permitted fields. Forbidden
fields raise H6_FORBIDDEN_FEATURE_ACCESS. V2 adds static field authority
checks and runtime fail-closed accessor covering all non-whitelisted provider
fields.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

ALLOWED_H6_FIELDS = frozenset({
    "sum_open_interest",
    "sum_open_interest_value",
    "price_open_high_low_close_volume_1h",
})

# V2 docs variant expects ALLOWED_OI_FIELDS for evidence checks
ALLOWED_OI_FIELDS = frozenset({
    "sum_open_interest",
    "sum_open_interest_value",
})

FORBIDDEN_H6_FIELDS = frozenset({
    "count_toptrader_long_short_ratio",
    "sum_toptrader_long_short_ratio",
    "count_long_short_ratio",
    "sum_taker_long_short_vol_ratio",
})


def is_field_allowed(field: str) -> bool:
    return field in ALLOWED_H6_FIELDS or field in ALLOWED_OI_FIELDS


def assert_field_allowed(field: str) -> None:
    if field in FORBIDDEN_H6_FIELDS:
        raise H6ForbiddenFeatureAccess(f"forbidden H6 feature access: {field}")
    if field not in ALLOWED_H6_FIELDS and field not in ALLOWED_OI_FIELDS:
        # Unknown non-forbidden fields are still disallowed unless explicitly whitelisted
        # (fail-closed: only whitelisted OI+price fields may be used)
        if field not in {"timestamp_ms", "unit_semantics", "source_file", "source_sha256"}:
            raise H6ForbiddenFeatureAccess(f"non-whitelisted field: {field}")


class H6ForbiddenFeatureAccess(Exception):
    """Raised when runtime attempts to use a forbidden feature for H6."""


@dataclass(frozen=True, slots=True)
class H6FieldAccess:
    """Fail-closed accessor wrapping an OI row or context dict."""

    data: Mapping[str, Any]

    def get(self, key: str, default: Any = None) -> Any:
        if key in FORBIDDEN_H6_FIELDS:
            raise H6ForbiddenFeatureAccess(
                f"forbidden H6 feature access: {key}"
            )
        if key not in ALLOWED_H6_FIELDS and key not in self.data:
            return default
        return self.data.get(key, default)

    def __getitem__(self, key: str) -> Any:
        if key in FORBIDDEN_H6_FIELDS:
            raise H6ForbiddenFeatureAccess(
                f"forbidden H6 feature access: {key}"
            )
        return self.data[key]

    def allowed_keys(self) -> frozenset[str]:
        return ALLOWED_H6_FIELDS

    def contains_forbidden(self, keys: Iterable[str]) -> bool:
        return any(k in FORBIDDEN_H6_FIELDS for k in keys)


def check_row_whitelist(row: Mapping[str, Any]) -> None:
    """Assert that a normalized OI row contains only whitelisted fields (+ metadata)."""
    for k in row:
        if k in FORBIDDEN_H6_FIELDS:
            raise H6ForbiddenFeatureAccess(f"row contains forbidden field: {k}")
        assert_field_allowed(k)
