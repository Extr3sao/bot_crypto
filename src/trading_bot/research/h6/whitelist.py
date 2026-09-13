"""P12 / V4 — feature authority enforcement for the H6 runtime.

V4 ROOT-CAUSE REPAIR (V3-WL-001 / V3-WL-002).

V3 stored the *entire* inbound mapping on the accessor and tried to hide forbidden
entries behind ``__getattr__``. That failed: ``H6FieldAccess`` was a dataclass with
``slots=True``, so ``data`` was a real slot and the ``__getattr__`` guard for the name
``"data"`` was dead code. One attribute access reached every forbidden provider field,
and ``repr`` / ``copy`` / ``pickle`` carried the forbidden values along.

V4 inverts the design:

    THE ACCESSOR NEVER STORES FORBIDDEN VALUES.

Construction validates inbound keys and builds an immutable internal mapping that
contains **only** admitted fields. Consequently there is nothing forbidden to recover
— not through ``.data``, not through ``object.__getattribute__``, not through ``vars``,
``__dict__``, ``dataclasses.asdict``, ``repr``, ``str``, ``copy``, ``deepcopy``,
``pickle`` or JSON serialization. Sanitized immutable state beats cosmetic blocking.

Two distinct controls exist and both are required:

1. ``H6FieldAccess`` (this module) — a *sanitizing* read view. It never raises at
   construction, and it can never yield a non-admitted value.
2. ``feature_authority.admitted_observation`` — the *fail-closed* data-path boundary.
   A row carrying a forbidden or unadmitted field is REJECTED before any feature or
   signal can be created.

Frozen field authority is declared in ``H6_FEATURE_AUTHORITY_WHITELIST``.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Any, Iterable, Iterator, Mapping

# --------------------------------------------------------------------------- sets

# Feature fields admitted to the H6 feature engine.
ALLOWED_H6_FIELDS = frozenset(
    {
        "sum_open_interest",
        "sum_open_interest_value",
        "price_open_high_low_close_volume_1h",
    }
)

# V2 docs variant expects ALLOWED_OI_FIELDS for evidence checks.
ALLOWED_OI_FIELDS = frozenset(
    {
        "sum_open_interest",
        "sum_open_interest_value",
    }
)

# Provider columns that must never reach an H6 feature or signal.
FORBIDDEN_H6_FIELDS = frozenset(
    {
        "count_toptrader_long_short_ratio",
        "sum_toptrader_long_short_ratio",
        "count_long_short_ratio",
        "sum_taker_long_short_vol_ratio",
    }
)

# Metadata allowed for PIT / provenance bookkeeping but never as a feature.
ALLOWED_METADATA_FIELDS = frozenset(
    {
        "timestamp_ms",
        "unit_semantics",
        "source_file",
        "source_sha256",
    }
)

# Unified admitted set: only these names may be stored or yielded by the accessor.
ALLOWED_ALL_FIELDS = ALLOWED_H6_FIELDS | ALLOWED_OI_FIELDS | ALLOWED_METADATA_FIELDS
_ADMITTED_FIELDS: frozenset[str] = ALLOWED_ALL_FIELDS

# Feature-only subset (what the feature engine is allowed to consume as inputs).
FEATURE_INPUT_FIELDS: frozenset[str] = ALLOWED_H6_FIELDS | ALLOWED_OI_FIELDS


# --------------------------------------------------------------------------- errors


class H6ForbiddenFeatureAccess(Exception):
    """Raised when runtime attempts to use a forbidden feature for H6."""


class H6UnadmittedField(H6ForbiddenFeatureAccess):
    """Raised when a field is not in the admitted set (FIELD_NOT_ADMITTED)."""


class H6ForbiddenRowRejected(H6ForbiddenFeatureAccess):
    """Raised at the data-path boundary when a row carries forbidden fields.

    This is the fail-closed rejection that MUST happen before any aggregation,
    feature computation or signal candidate is produced.
    """


# --------------------------------------------------------------------------- helpers


def is_field_allowed(field: str) -> bool:
    """True only for names in the admitted set."""
    return field in _ADMITTED_FIELDS


def is_field_forbidden(field: str) -> bool:
    """True only for provider fields that must never be used."""
    return field in FORBIDDEN_H6_FIELDS


def classify_keys(keys: Iterable[str]) -> dict[str, list[str]]:
    """Split keys into admitted / forbidden / unadmitted buckets."""
    admitted: list[str] = []
    forbidden: list[str] = []
    unadmitted: list[str] = []
    for k in keys:
        if k in FORBIDDEN_H6_FIELDS:
            forbidden.append(k)
        elif k in _ADMITTED_FIELDS:
            admitted.append(k)
        else:
            unadmitted.append(k)
    return {"admitted": sorted(admitted), "forbidden": sorted(forbidden), "unadmitted": sorted(unadmitted)}


def assert_field_allowed(field: str) -> None:
    """Raise unless ``field`` is admitted.

    Forbidden fields raise with the explicit forbidden marker; everything else
    non-admitted raises FIELD_NOT_ADMITTED. Both are fail-closed.
    """
    if field in FORBIDDEN_H6_FIELDS:
        raise H6ForbiddenFeatureAccess(f"forbidden H6 feature access: {field}")
    if field not in _ADMITTED_FIELDS:
        raise H6UnadmittedField(f"FIELD_NOT_ADMITTED: {field}")


def check_row_whitelist(row: Mapping[str, Any], *, reject_unadmitted: bool = True) -> None:
    """Fail closed if a row carries a forbidden field (or, by default, any unadmitted field).

    Used by the data-path boundary. Raises ``H6ForbiddenRowRejected`` for forbidden
    fields and ``H6UnadmittedField`` for non-admitted names.
    """
    forbidden = [k for k in row if k in FORBIDDEN_H6_FIELDS]
    if forbidden:
        raise H6ForbiddenRowRejected(
            "row contains forbidden field(s): %s" % ", ".join(sorted(forbidden))
        )
    if reject_unadmitted:
        unadmitted = [k for k in row if k not in _ADMITTED_FIELDS]
        if unadmitted:
            raise H6UnadmittedField(
                "row contains unadmitted field(s): %s" % ", ".join(sorted(unadmitted))
            )


def sanitize_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Return a new dict containing ONLY admitted keys.

    Forbidden values are dropped, never copied. This is the single sanitization
    primitive; the accessor is built on it.
    """
    out: dict[str, Any] = {}
    for k, v in row.items():
        if isinstance(k, str) and k in _ADMITTED_FIELDS:
            out[k] = v
    return out


# --------------------------------------------------------------------------- accessor


class H6FieldAccess:
    """Fail-closed, sanitizing read view over an OI row or context mapping.

    Invariants
    ----------
    * ``_admitted`` (the only stored state) contains admitted keys exclusively.
    * No forbidden value is ever retained, so no access path can recover one.
    * ``[]`` / ``get`` / ``in`` / ``getattr`` on a non-admitted name raise.
    * ``keys`` / ``values`` / ``items`` / iteration / ``len`` yield admitted data only.
    * ``repr`` / ``str`` render **key names only** — never any value — so logs and
      evidence dumps cannot carry an unadmitted provider value.
    * ``copy`` / ``deepcopy`` / ``pickle`` reproduce sanitized state only.
    """

    __slots__ = ("_admitted",)

    def __init__(self, row: Mapping[str, Any] | None = None) -> None:
        if row is None:
            row = {}
        if not isinstance(row, Mapping):
            raise TypeError("H6FieldAccess requires a mapping, got %r" % type(row).__name__)
        # Sanitize FIRST, then freeze. Forbidden values never enter the object.
        object.__setattr__(self, "_admitted", MappingProxyType(sanitize_row(row)))

    # -- internal -----------------------------------------------------------

    def _safe_admitted(self) -> Mapping[str, Any]:
        try:
            return object.__getattribute__(self, "_admitted")
        except AttributeError:  # pragma: no cover - defensive
            return MappingProxyType({})

    def _require_allowed(self, key: str) -> None:
        if key not in _ADMITTED_FIELDS:
            if key in FORBIDDEN_H6_FIELDS:
                raise H6ForbiddenFeatureAccess(f"forbidden H6 feature access: {key}")
            raise H6UnadmittedField(f"FIELD_NOT_ADMITTED: {key}")

    # -- mapping protocol ---------------------------------------------------

    def __getitem__(self, key: str) -> Any:
        self._require_allowed(key)
        return self._safe_admitted()[key]

    def get(self, key: str, default: Any = None) -> Any:
        self._require_allowed(key)
        return self._safe_admitted().get(key, default)

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str):
            return False
        if key not in _ADMITTED_FIELDS:
            raise H6ForbiddenFeatureAccess(f"FIELD_NOT_ADMITTED __contains__: {key}")
        return key in self._safe_admitted()

    def __iter__(self) -> Iterator[str]:
        return iter(self._safe_admitted())

    def __len__(self) -> int:
        return len(self._safe_admitted())

    def keys(self) -> list[str]:
        return list(self._safe_admitted().keys())

    def values(self) -> list[Any]:
        adm = self._safe_admitted()
        return [adm[k] for k in adm]

    def items(self) -> list[tuple[str, Any]]:
        adm = self._safe_admitted()
        return [(k, adm[k]) for k in adm]

    def to_dict(self) -> dict[str, Any]:
        """Explicit, admitted-only export."""
        return dict(self._safe_admitted())

    def allowed_keys(self) -> frozenset[str]:
        return _ADMITTED_FIELDS

    def present_keys(self) -> list[str]:
        return list(self._safe_admitted().keys())

    def contains_forbidden(self, keys: Iterable[str]) -> bool:
        return any(k in FORBIDDEN_H6_FIELDS for k in keys)

    # -- attribute access ---------------------------------------------------

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        adm = self._safe_admitted()
        if name in _ADMITTED_FIELDS:
            if name not in adm:
                raise AttributeError(f"admitted field {name!r} is not present in this row")
            return adm[name]
        if name in FORBIDDEN_H6_FIELDS:
            raise H6ForbiddenFeatureAccess(f"forbidden H6 feature access: {name}")
        raise H6UnadmittedField(f"FIELD_NOT_ADMITTED attribute: {name}")

    # -- immutability -------------------------------------------------------

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("H6FieldAccess is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("H6FieldAccess is immutable")

    # -- safe representations ----------------------------------------------

    def __repr__(self) -> str:
        # Keys only. Never render a value: values are an evidence-leak surface.
        keys = ",".join(sorted(self._safe_admitted().keys()))
        return f"H6FieldAccess(admitted=[{keys}])"

    __str__ = __repr__

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, H6FieldAccess):
            return NotImplemented
        return self._safe_admitted() == other._safe_admitted()

    def __hash__(self) -> int:
        adm = self._safe_admitted()
        try:
            return hash(tuple(sorted(adm.items(), key=lambda kv: kv[0])))
        except TypeError:
            return hash(tuple(sorted(adm.keys())))

    # -- copy / pickle safety ----------------------------------------------

    def __copy__(self) -> "H6FieldAccess":
        return H6FieldAccess(self.to_dict())

    def __deepcopy__(self, memo: dict) -> "H6FieldAccess":
        import copy as _copy

        return H6FieldAccess(_copy.deepcopy(self.to_dict(), memo))

    def __reduce__(self):
        # Rebuilds sanitized state only; nothing forbidden was ever stored.
        return (H6FieldAccess, (self.to_dict(),))

    def __getstate__(self) -> dict:
        return {"admitted": self.to_dict()}

    def __setstate__(self, state: Mapping[str, Any]) -> None:
        object.__setattr__(self, "_admitted", MappingProxyType(sanitize_row(state.get("admitted", {}))))


# --------------------------------------------------------------------------- declaration

# Frozen declaration of what the module enforces. Consumed by tests and by the
# feature-authority boundary; not a substitute for the runtime checks above.
H6_FEATURE_AUTHORITY_WHITELIST = {
    "ALLOWED_FEATURE_FIELDS": sorted(ALLOWED_H6_FIELDS),
    "ALLOWED_OI_FIELDS": sorted(ALLOWED_OI_FIELDS),
    "ALLOWED_METADATA_FIELDS": sorted(ALLOWED_METADATA_FIELDS),
    "FORBIDDEN_FIELDS": sorted(FORBIDDEN_H6_FIELDS),
    "enforcement": {
        "accessor": "H6FieldAccess (sanitizing, forbidden values never stored)",
        "boundary": "feature_authority.admitted_observation (fail-closed row rejection)",
        "bypass_paths_allowed": 0,
        "forbidden_values_stored": 0,
        "exception": "H6ForbiddenFeatureAccess",
    },
}
