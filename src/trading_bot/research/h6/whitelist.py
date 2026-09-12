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

# Metadata fields allowed for PIT/row bookkeeping but not features
_ALLOWED_METADATA_FIELDS = frozenset({
    "timestamp_ms",
    "unit_semantics",
    "source_file",
    "source_sha256",
})

# Unified fail-closed whitelist: only these may be accessed via H6FieldAccess
_ALLOWED_ALL_FIELDS = ALLOWED_H6_FIELDS | ALLOWED_OI_FIELDS | _ALLOWED_METADATA_FIELDS


def is_field_allowed(field: str) -> bool:
    return field in _ALLOWED_ALL_FIELDS


def assert_field_allowed(field: str) -> None:
    if field in FORBIDDEN_H6_FIELDS:
        raise H6ForbiddenFeatureAccess(f"forbidden H6 feature access: {field}")
    if field not in _ALLOWED_ALL_FIELDS:
        raise H6ForbiddenFeatureAccess(f"non-whitelisted field: {field}")


class H6ForbiddenFeatureAccess(Exception):
    """Raised when runtime attempts to use a forbidden feature for H6."""


@dataclass(frozen=True, slots=True)
class H6FieldAccess:
    """Fail-closed accessor wrapping an OI row or context dict.

    Invariant: ONLY explicitly admitted field names can be accessed.
    Both obj["field"] and obj.get("field") enforce authority.
    Unknown field -> H6ForbiddenFeatureAccess (FIELD_NOT_ADMITTED).
    Known allowed but missing -> standard missing behavior (get returns default, [] raises KeyError).
    All iteration / membership / key views are filtered to admitted fields only,
    so forbidden payload never leaks via keys()/values()/items()/in/iter/dict().
    """

    data: Mapping[str, Any]

    def _require_allowed(self, key: str) -> None:
        if key not in _ALLOWED_ALL_FIELDS:
            if key in FORBIDDEN_H6_FIELDS:
                raise H6ForbiddenFeatureAccess(f"forbidden H6 feature access: {key}")
            raise H6ForbiddenFeatureAccess(f"FIELD_NOT_ADMITTED: {key}")

    def get(self, key: str, default: Any = None) -> Any:
        self._require_allowed(key)
        return self.data.get(key, default)

    def __getitem__(self, key: str) -> Any:
        self._require_allowed(key)
        return self.data[key]

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str):
            return False
        if key not in _ALLOWED_ALL_FIELDS:
            raise H6ForbiddenFeatureAccess(f"FIELD_NOT_ADMITTED __contains__: {key}")
        return key in self.data

    def __iter__(self):  # type: ignore[override]
        for k in self.data:
            if k in _ALLOWED_ALL_FIELDS:
                yield k

    def __len__(self) -> int:
        return sum(1 for k in self.data if k in _ALLOWED_ALL_FIELDS)

    def keys(self):  # type: ignore[override]
        return [k for k in self.data.keys() if k in _ALLOWED_ALL_FIELDS]

    def values(self):
        return [self.data[k] for k in self.data.keys() if k in _ALLOWED_ALL_FIELDS]

    def items(self):
        return [(k, self.data[k]) for k in self.data.keys() if k in _ALLOWED_ALL_FIELDS]

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        if name in ("data", "allowed_keys", "contains_forbidden", "get", "keys", "values", "items"):
            raise AttributeError(name)
        if name not in _ALLOWED_ALL_FIELDS:
            raise H6ForbiddenFeatureAccess(f"FIELD_NOT_ADMITTED attribute: {name}")
        if name not in self.data:
            raise AttributeError(f"allowed field {name} not present in row")
        return self.data[name]

    def allowed_keys(self) -> frozenset[str]:
        return _ALLOWED_ALL_FIELDS

    def contains_forbidden(self, keys: Iterable[str]) -> bool:
        return any(k in FORBIDDEN_H6_FIELDS for k in keys)


def check_row_whitelist(row: Mapping[str, Any]) -> None:
    """Assert that a normalized OI row contains only whitelisted fields (+ metadata)."""
    for k in row:
        if k in FORBIDDEN_H6_FIELDS:
            raise H6ForbiddenFeatureAccess(f"row contains forbidden field: {k}")
        assert_field_allowed(k)
