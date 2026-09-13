"""V4 — feature-authority BOUNDARY between raw/normalised rows and the H6 engine.

V4 repair for V3-WL-003 (the whitelist was decorative: no runtime data path used it).

Division of labour:

* ``whitelist.H6FieldAccess`` is a *sanitizing read view*. It never stores forbidden
  values, but it also never fails closed: constructing one from a dirty row silently
  drops the dirty fields. That is correct for a read view and wrong for a boundary.
* ``feature_authority.admitted_observation`` (this module) is the **fail-closed**
  boundary. A row carrying a forbidden or unadmitted field is REJECTED outright,
  before any hourly aggregation, feature computation or signal candidate exists.

The H6 runtime therefore has exactly one way to turn a stored row into an observation,
and that way rejects unadmitted provider data instead of ignoring it.

Nothing here observes economics. No PnL, Sharpe, PF or expectancy is computed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Iterator, Mapping

from trading_bot.research.h6.whitelist import (
    FEATURE_INPUT_FIELDS,
    FORBIDDEN_H6_FIELDS,
    H6ForbiddenRowRejected,
    H6UnadmittedField,
    classify_keys,
)

REQUIRED_OBSERVATION_FIELDS = frozenset({"timestamp_ms", "sum_open_interest"})


@dataclass(frozen=True, slots=True)
class AdmittedOIObservation:
    """A validated, typed 5m OI snapshot.

    This is the ONLY observation shape the H6 engine consumes. It is immutable and
    every field is explicit, so a feature or signal can never be built from an
    unrestricted provider dictionary.
    """

    ts_ms: int
    sum_open_interest: float
    sum_open_interest_value: float | None
    unit_semantics: str | None
    source_file: str | None
    source_sha256: str | None

    def oi_time(self) -> datetime:
        return datetime.fromtimestamp(self.ts_ms / 1000, tz=timezone.utc)


class H6AuthorityBoundaryError(H6ForbiddenRowRejected):
    """Raised when the boundary cannot admit a row for a non-forbidden reason."""


def _as_float(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise H6AuthorityBoundaryError(f"{field} must be numeric, got bool")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError as exc:
            raise H6AuthorityBoundaryError(f"{field} is not numeric: {value!r}") from exc
    raise H6AuthorityBoundaryError(f"{field} is not numeric: {type(value).__name__}")


def classify_row(row: Mapping[str, Any]) -> dict[str, list[str]]:
    """Public helper: which keys are admitted / forbidden / unadmitted."""
    return classify_keys([k for k in row if isinstance(k, str)])


def admitted_observation(
    row: Mapping[str, Any],
    *,
    context: str = "h6.runtime",
    require_feature_inputs: bool = True,
) -> AdmittedOIObservation:
    """Validate one stored row and return a typed observation, or RAISE.

    Fail-closed rules (V4, per the whitelist V4 contract):

    1. any FORBIDDEN provider field  -> ``H6ForbiddenRowRejected``
    2. any unadmitted field          -> ``H6UnadmittedField``
    3. missing required field        -> ``H6AuthorityBoundaryError``

    A rejection happens before aggregation/feature/signal creation, so an injected
    forbidden column cannot influence any downstream number.
    """
    if not isinstance(row, Mapping):
        raise H6AuthorityBoundaryError(f"{context}: observation must be a mapping")

    forbidden = sorted(k for k in row if isinstance(k, str) and k in FORBIDDEN_H6_FIELDS)
    if forbidden:
        raise H6ForbiddenRowRejected(
            f"{context}: REFUSED row containing forbidden H6 field(s): {', '.join(forbidden)}"
        )

    unadmitted = sorted(
        k for k in row
        if isinstance(k, str) and k not in (FEATURE_INPUT_FIELDS | {
            "timestamp_ms", "unit_semantics", "source_file", "source_sha256"})
    )
    if unadmitted:
        raise H6UnadmittedField(
            f"{context}: REFUSED row containing unadmitted field(s): {', '.join(unadmitted)}"
        )

    missing = sorted(f for f in REQUIRED_OBSERVATION_FIELDS if f not in row)
    if missing:
        raise H6AuthorityBoundaryError(
            f"{context}: row missing required field(s): {', '.join(missing)}"
        )

    ts_raw = row["timestamp_ms"]
    if isinstance(ts_raw, bool) or not isinstance(ts_raw, int):
        if isinstance(ts_raw, str) and ts_raw.isdigit():
            ts_raw = int(ts_raw)
        else:
            raise H6AuthorityBoundaryError(f"{context}: timestamp_ms must be an int, got {ts_raw!r}")

    if require_feature_inputs and "sum_open_interest" not in row:
        raise H6AuthorityBoundaryError(f"{context}: missing sum_open_interest")

    return AdmittedOIObservation(
        ts_ms=int(ts_raw),
        sum_open_interest=_as_float(row["sum_open_interest"], "sum_open_interest"),
        sum_open_interest_value=(
            _as_float(row["sum_open_interest_value"], "sum_open_interest_value")
            if row.get("sum_open_interest_value") is not None else None
        ),
        unit_semantics=(str(row["unit_semantics"]) if row.get("unit_semantics") is not None else None),
        source_file=(str(row["source_file"]) if row.get("source_file") is not None else None),
        source_sha256=(str(row["source_sha256"]) if row.get("source_sha256") is not None else None),
    )


def admitted_observations(
    rows: Iterable[Mapping[str, Any]],
    *,
    context: str = "h6.runtime",
) -> list[AdmittedOIObservation]:
    """Boundary over a sequence; raises on the FIRST offending row."""
    return [admitted_observation(r, context=context) for r in rows]


def iter_stored_rows(path, *, context: str = "h6.runtime") -> Iterator[dict[str, Any]]:
    """Read a normalised .jsonl shard row by row (no interpretation)."""
    with open(path, "r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise H6AuthorityBoundaryError(
                    f"{context}: malformed JSON at {path}:{lineno}"
                ) from exc
