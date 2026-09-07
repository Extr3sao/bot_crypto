"""ADMISSION-FOUNDATION-01 — Confirmation Protocol V2 (§8/§9, ADM-08/09/10).

An immutable, pre-committed confirmation manifest. The governance repair for
BLOCKED_CONFIRMATION_AUTHORITY: the manifest MUST be committed before the
confirmation market data becomes eligible:

    manifest_commit_time < confirmation_window_start < execution_time

Reusing discovery data, consuming a locked window, or executing against a
consumed/mismatched manifest fails closed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .registry import canonical_hash

SCHEMA_VERSION = "confirmation-manifest-v2"
PROTOCOL_VERSION = "CONFIRMATION-PROTOCOL-V2"


class ConfirmationAuthorityError(PermissionError):
    """Raised on any future-window/consumption/fingerprint violation."""


@dataclass(frozen=True, slots=True)
class ConfirmationManifest:
    """Immutable pre-registration of a confirmation experiment (§8)."""

    confirmation_id: str
    strategy_ids: tuple[str, ...]
    created_at: str
    commit: str                      # git commit that carries this manifest
    protocol_version: str
    window_start: str                # UTC ISO
    window_end: str                  # UTC ISO
    expected_bars: int
    assets: tuple[str, ...]
    timeframes: tuple[str, ...]
    data_source: str
    acceptance_criteria: dict[str, Any]
    cost_model_sha256: str
    candidate_config_sha256: tuple[str, ...]
    window_status: str = "COMMITTED"
    consumed: bool = False
    notes: str = ""
    manifest_sha256: str = field(default="")

    def __post_init__(self) -> None:
        if not self.manifest_sha256:
            object.__setattr__(self, "manifest_sha256", canonical_hash(self._identity()))

    def _identity(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "confirmation_id": self.confirmation_id,
            "strategy_ids": list(self.strategy_ids),
            "created_at": self.created_at,
            "commit": self.commit,
            "protocol_version": self.protocol_version,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "expected_bars": self.expected_bars,
            "assets": list(self.assets),
            "timeframes": list(self.timeframes),
            "data_source": self.data_source,
            "acceptance_criteria": self.acceptance_criteria,
            "cost_model_sha256": self.cost_model_sha256,
            "candidate_config_sha256": list(self.candidate_config_sha256),
            "window_status": self.window_status,
            "notes": self.notes,
        }

    def verify_future_ordering(
        self,
        *,
        manifest_commit_time: str,
        execution_time: str | None = None,
    ) -> None:
        """Prove manifest_commit_time < window_start (< execution_time). (§9)"""
        commit_t = datetime.fromisoformat(manifest_commit_time)
        start_t = datetime.fromisoformat(self.window_start)
        end_t = datetime.fromisoformat(self.window_end)
        if commit_t.tzinfo is None or start_t.tzinfo is None:
            raise ConfirmationAuthorityError("timestamps must be timezone-aware")
        if commit_t >= start_t:
            raise ConfirmationAuthorityError(
                f"manifest committed {commit_t.isoformat()} NOT BEFORE window start {start_t.isoformat()}"
            )
        if start_t >= end_t:
            raise ConfirmationAuthorityError("window_start must precede window_end")
        if execution_time is not None:
            exec_t = datetime.fromisoformat(execution_time)
            if exec_t <= start_t:
                raise ConfirmationAuthorityError(
                    "execution_time must be AFTER confirmation_window_start (future data only)"
                )

    def verify_configs(self, candidate_config_sha256: tuple[str, ...]) -> None:
        """Config hash mismatch fails closed (frozen candidates only)."""
        if tuple(sorted(candidate_config_sha256)) != tuple(sorted(self.candidate_config_sha256)):
            raise ConfirmationAuthorityError(
                "candidate config hash mismatch vs frozen manifest"
            )

    def verify_data_fingerprint(self, data_sha256: str) -> None:
        """The confirmation dataset must carry the manifest's cost/cost-model
        binding and be fetched ONLY from the window at execution time; the
        data fingerprint itself is recorded at execution and compared against
        the manifest's window-derived expectation by the caller. Here we bind
        the fingerprint into the consumption record."""
        if not data_sha256:
            raise ConfirmationAuthorityError("empty data fingerprint")

    def consume(self, *, data_sha256: str, executed_at: str) -> dict[str, Any]:
        """Single-use consumption guard (ADM-10): a consumed manifest can
        never authorize a second execution."""
        if self.consumed:
            raise ConfirmationAuthorityError(
                f"confirmation manifest {self.confirmation_id} already CONSUMED"
            )
        self.verify_future_ordering(
            manifest_commit_time=self.created_at, execution_time=executed_at
        )
        self.verify_data_fingerprint(data_sha256)
        return {
            "confirmation_id": self.confirmation_id,
            "consumed_at": executed_at,
            "data_sha256": data_sha256,
            "window": [self.window_start, self.window_end],
            "single_use": True,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._identity(),
            "consumed": self.consumed,
            "manifest_sha256": self.manifest_sha256,
        }


class ConfirmationRegistry:
    """Tracks confirmation consumption. The manifest itself is immutable
    (frozen), so the single-use guard lives here: a confirmation_id may be
    consumed exactly once, ever (ADM-10)."""

    def __init__(self) -> None:
        self._consumed: dict[str, dict[str, Any]] = {}

    def consume(
        self, manifest: ConfirmationManifest, *, data_sha256: str, executed_at: str
    ) -> dict[str, Any]:
        if manifest.confirmation_id in self._consumed:
            raise ConfirmationAuthorityError(
                f"confirmation manifest {manifest.confirmation_id} already CONSUMED"
            )
        receipt = manifest.consume(
            data_sha256=data_sha256, executed_at=executed_at
        )
        self._consumed[manifest.confirmation_id] = receipt
        return receipt

    def is_consumed(self, confirmation_id: str) -> bool:
        return confirmation_id in self._consumed


def load_manifest(path: str) -> ConfirmationManifest:
    """Load a manifest from a committed JSON file, re-verifying its hash."""
    import json
    import pathlib

    payload = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    m = ConfirmationManifest(
        confirmation_id=payload["confirmation_id"],
        strategy_ids=tuple(payload["strategy_ids"]),
        created_at=payload["created_at"],
        commit=payload["commit"],
        protocol_version=payload["protocol_version"],
        window_start=payload["window_start"],
        window_end=payload["window_end"],
        expected_bars=payload["expected_bars"],
        assets=tuple(payload["assets"]),
        timeframes=tuple(payload["timeframes"]),
        data_source=payload["data_source"],
        acceptance_criteria=payload["acceptance_criteria"],
        cost_model_sha256=payload["cost_model_sha256"],
        candidate_config_sha256=tuple(payload["candidate_config_sha256"]),
        window_status=payload.get("window_status", "COMMITTED"),
        consumed=payload.get("consumed", False),
        notes=payload.get("notes", ""),
    )
    if m.manifest_sha256 != payload.get("manifest_sha256"):
        raise ConfirmationAuthorityError("manifest hash mismatch (tampered file)")
    return m
