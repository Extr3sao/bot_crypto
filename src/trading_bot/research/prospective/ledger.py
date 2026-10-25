"""Sealing day classifications so that a quoted count cannot be edited afterwards.

The problem this solves is not fraud in the abstract. It is that ``coverage.json`` is a *derived*
file: it is regenerated on every observer tick, so a number read from it last week is not
evidence of what was true last week. An attestation is.

Each attestation names an exact prefix of each series file — ``byte_end`` bytes, sha256 —
together with the classification computed from the bars inside that prefix. Appending tomorrow's
bars moves nothing; rewriting yesterday's bytes breaks the digest and :meth:`verify` says
``SERIES_REWRITTEN`` rather than quietly recomputing a new answer.

The chain is a plain previous-hash link, appended under an exclusive create. It is not a
blockchain and does not need to be: the threat is a report that drifts from its evidence, not a
miner.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .admission import ADMISSIBLE, DayAdmission
from .store import SeriesIndex, StoreError, prefix_digest

__all__ = [
    "ATT_LEDGER_VERSION",
    "AttestationLedger",
    "LedgerConflict",
    "LedgerVerification",
]

ATT_LEDGER_VERSION = "PROSPECTIVE_ATTESTATION_V1"

GENESIS = "0" * 64


class LedgerConflict(RuntimeError):
    """The ledger already says something different about this day; it is not rewritten."""


def _canonical(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _series_key(index: SeriesIndex) -> str:
    return f"{index.interval}:{index.asset}"


@dataclass(frozen=True, slots=True)
class LedgerVerification:
    """The answer to "is this count still backed by the bytes it was computed from?"."""

    ok: bool
    records: int
    series_checked: int
    admissible: tuple[str, ...]
    errors: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "records": self.records,
            "series_checked": self.series_checked,
            "admissible_days": list(self.admissible),
            "admissible": len(self.admissible),
            "errors": list(self.errors),
        }


@dataclass(slots=True)
class AttestationLedger:
    """An append-only attestation file, one JSON object per line."""

    path: Path
    version: str = ATT_LEDGER_VERSION

    # -- reading ---------------------------------------------------------- #
    def read(self) -> list[dict[str, Any]]:
        path = Path(self.path)
        if not path.exists():
            return []
        records: list[dict[str, Any]] = []
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as error:
                raise LedgerConflict(f"{path}:{number} is not JSON: {error}") from error
            if not isinstance(payload, dict):
                raise LedgerConflict(f"{path}:{number} is not an object")
            records.append(payload)
        return records

    def sealed_days(self) -> tuple[str, ...]:
        return tuple(str(record.get("day")) for record in self.read())

    # -- writing ---------------------------------------------------------- #
    def seal(
        self,
        admissions: Sequence[DayAdmission],
        indexes: Sequence[SeriesIndex],
        *,
        sealed_at_utc: str | None = None,
    ) -> list[dict[str, Any]]:
        """Append one attestation per settlement, refusing to contradict an earlier one.

        A day already in the ledger is compared field by field against a fresh computation.
        Agreement is a no-op; disagreement raises :class:`LedgerConflict` instead of appending
        a second, contradictory record for the same day.
        """
        if not indexes:
            raise ValueError("cannot seal against no series")
        by_key = {_series_key(index): index for index in indexes}
        last = self.read()
        existing = {str(record.get("day")): record for record in last}
        prev = str(last[-1]["sha256"]) if last else GENESIS
        seq = int(last[-1]["seq"]) + 1 if last else 1
        stamp = sealed_at_utc or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

        fresh: list[dict[str, Any]] = []
        for admission in sorted(admissions, key=lambda row: row.day):
            record = self._build(admission, seq + len(fresh), prev, stamp, by_key)
            prior = existing.get(admission.day)
            if prior is not None:
                if self._same_evidence(prior, record):
                    continue
                raise LedgerConflict(
                    f"{admission.day} is already attested as {prior.get('class')} over "
                    f"different bytes than the store now holds; refusing to append a second reading"
                )
            prev = str(record["sha256"])
            fresh.append(record)

        if not fresh:
            return []
        path = Path(self.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            for record in fresh:
                handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return fresh

    def _build(
        self,
        admission: DayAdmission,
        seq: int,
        prev: str,
        stamp: str,
        by_key: Mapping[str, SeriesIndex],
    ) -> dict[str, Any]:
        series: dict[str, Any] = {}
        for row in admission.series:
            key = f"{row.interval}:{row.asset}"
            index = by_key.get(key)
            if index is None:
                raise ValueError(f"day {admission.day} declares {key}, which was not indexed")
            byte_end = row.byte_end
            payload: dict[str, Any] = {
                "interval": row.interval,
                "asset": row.asset,
                "expected_bars": row.expected,
                "stored_bars": row.stored,
                "prospectively_observed_bars": row.prospective,
                "stored_coverage": row.stored_coverage,
                "prospective_coverage": row.prospective_coverage,
                "byte_end": byte_end or 0,
                # `None` is the honest value for a day with no bytes: it means the series held
                # nothing for that day, and verification re-checks that it still holds nothing.
                "sha256": prefix_digest(index.path, byte_end) if byte_end else None,
            }
            series[key] = payload
        body = {
            "version": self.version,
            "seq": seq,
            "day": admission.day,
            "class": admission.classification,
            "admissible": admission.classification in ADMISSIBLE,
            "coverage_required": admission.coverage_required,
            "lag_bounds_ms": dict(admission.lag_bounds),
            "series": series,
            "sealed_at_utc": stamp,
            "prev_sha256": prev,
        }
        return {**body, "sha256": _digest(body)}

    @staticmethod
    def _same_evidence(prior: Mapping[str, Any], fresh: Mapping[str, Any]) -> bool:
        keys = ("day", "class", "coverage_required", "lag_bounds_ms", "series")
        return all(prior.get(key) == fresh.get(key) for key in keys)

    # -- verifying -------------------------------------------------------- #
    def verify(self, indexes: Sequence[SeriesIndex] | None = None) -> LedgerVerification:
        """Recompute the chain and every series digest against the store as it is now."""
        records = self.read()
        by_key = {_series_key(index): index for index in (indexes or ())}
        errors: list[str] = []
        admissible: list[str] = []
        prev = GENESIS
        series_checked = 0
        for position, record in enumerate(records, start=1):
            day = str(record.get("day"))
            if int(record.get("seq", -1)) != position:
                errors.append(f"SEQ_GAP:{day}")
            if record.get("prev_sha256") != prev:
                errors.append(f"CHAIN_BROKEN:{day}")
            body = {key: value for key, value in record.items() if key != "sha256"}
            # The link is checked against the *recomputed* digest, not the stored one. Using the
            # stored value would let an edited record keep its successor's back-link intact, so the
            # chain would vouch for bytes it no longer describes.
            recomputed = _digest(body)
            if recomputed != record.get("sha256"):
                errors.append(f"RECORD_HASH_MISMATCH:{day}")
            prev = recomputed
            if record.get("admissible") is True:
                admissible.append(day)
            series = record.get("series")
            if not isinstance(series, Mapping):
                errors.append(f"SERIES_BLOCK_MISSING:{day}")
                continue
            for key, payload in series.items():
                if not isinstance(payload, Mapping):
                    errors.append(f"SERIES_BLOCK_INVALID:{day}:{key}")
                    continue
                series_checked += 1
                index = by_key.get(str(key))
                if index is None:
                    # Without the series we cannot re-derive the digest, and a verification that
                    # skips what it cannot check is a verification of nothing.
                    errors.append(f"SERIES_NOT_SUPPLIED:{day}:{key}")
                    continue
                errors.extend(_check_series(day, str(key), payload, index))
        return LedgerVerification(
            ok=not errors,
            records=len(records),
            series_checked=series_checked,
            admissible=tuple(admissible),
            errors=tuple(errors),
        )


def _check_series(
    day: str, key: str, payload: Mapping[str, Any], index: SeriesIndex
) -> list[str]:
    errors: list[str] = []
    recorded = payload.get("sha256")
    byte_end = int(payload.get("byte_end") or 0)
    if recorded is None:
        current = index.day_end(day)
        if current is not None:
            errors.append(f"SERIES_GAINED_BARS_AFTER_SEAL:{day}:{key}")
        return errors
    try:
        actual = prefix_digest(index.path, byte_end)
    except StoreError:
        return [f"SERIES_TRUNCATED:{day}:{key}"]
    if actual != recorded:
        errors.append(f"SERIES_REWRITTEN:{day}:{key}")
    if int(payload.get("stored_bars") or 0) != len(index.bars_on(day)):
        errors.append(f"SERIES_BAR_COUNT_DRIFT:{day}:{key}")
    return errors
