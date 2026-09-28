"""Strategy admission ledger — the ONLY source of "may this run PAPER?" (§3).

The runtime never decides by itself that a strategy is good enough to trade
paper money. It reads a committed ledger produced from research artifacts,
and it fails closed:

* unknown strategy        → ``UNKNOWN``      → not admitted, no edge evidence
* missing gross-edge data → not admitted
* ``PAPER_CANDIDATE`` without evidence → rejected at load time

The ledger is data, not code: it is generated from committed research
results (``docs/STRATEGY_DISCOVERY_V3_RESULTS.json``,
``docs/STRATEGY_ADMISSION_MATRIX.json``) by
``scripts/build_strategy_admission.py`` so every number keeps a provenance
chain (CLAIM → SOURCE → EVIDENCE → DECISION).

Costs are recomputed every cycle with COST_MODEL_V3; the ledger only supplies
the *expected gross edge* measured in research, never a cost assumption.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .contracts import (
    PAPER_AUTHORISING_STATUSES,
    SHADOW_ELIGIBLE_STATUSES,
    AdmissionEntry,
    AdmissionStatus,
)

__all__ = [
    "DEFAULT_ADMISSION_LEDGER_PATH",
    "PAPER_AUTHORISING_STATUSES",
    "SHADOW_ELIGIBLE_STATUSES",
    "AdmissionLedger",
    "default_ledger_path",
]

DEFAULT_ADMISSION_LEDGER_PATH = "config/strategy_admission.json"


def default_ledger_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else Path.cwd()
    return root / DEFAULT_ADMISSION_LEDGER_PATH


class AdmissionLedger:
    """Immutable, fail-closed view over the committed admission ledger."""

    def __init__(self, entries: dict[str, AdmissionEntry], *, source_path: str = "") -> None:
        self._entries = dict(entries)
        self._source_path = source_path

    # -- construction -------------------------------------------------------

    @classmethod
    def from_dict(cls, payload: dict[str, Any], *, source_path: str = "") -> AdmissionLedger:
        raw = payload.get("strategies", payload)
        if not isinstance(raw, dict):
            raise ValueError("admission ledger must map strategy_id -> entry")
        entries: dict[str, AdmissionEntry] = {}
        for strategy_id, item in raw.items():
            if strategy_id.startswith("_"):
                continue  # provenance keys
            entries[strategy_id] = AdmissionEntry.from_dict({**item, "strategy_id": strategy_id})
        return cls(entries, source_path=source_path)

    @classmethod
    def load(cls, path: Path | str) -> AdmissionLedger:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(
                f"admission ledger not found at {p}; the runtime refuses to guess "
                "which strategies are admitted (fail closed, §3)"
            )
        payload = json.loads(p.read_text(encoding="utf-8"))
        return cls.from_dict(payload, source_path=p.as_posix())

    # -- queries ------------------------------------------------------------

    @property
    def source_path(self) -> str:
        return self._source_path

    def strategy_ids(self) -> list[str]:
        return sorted(self._entries)

    def entry(self, strategy_id: str) -> AdmissionEntry:
        """Ledger entry, or a fail-closed UNKNOWN entry (never raises)."""
        found = self._entries.get(strategy_id)
        if found is not None:
            return found
        return AdmissionEntry(
            strategy_id=strategy_id,
            family=strategy_id,
            status=AdmissionStatus.UNKNOWN,
            admitted_for_paper=False,
            expected_gross_edge_bps=None,
            edge_evidence=None,
            source_doc=self._source_path or "(no ledger)",
            rationale="strategy absent from the admission ledger (fail closed)",
            known=False,
        )

    def status_for(self, strategy_id: str) -> AdmissionStatus:
        return self.entry(strategy_id).status

    def is_paper_admitted(self, strategy_id: str) -> bool:
        """The single authority for "may this strategy touch PAPER?"."""
        return self.entry(strategy_id).admitted_for_paper

    def expected_gross_edge_bps(self, strategy_id: str) -> float | None:
        return self.entry(strategy_id).expected_gross_edge_bps

    def paper_candidates(self) -> list[str]:
        return sorted(sid for sid, e in self._entries.items() if e.admitted_for_paper)

    def entries_for_timeframe(self, timeframe: str) -> dict[str, AdmissionEntry]:
        """Entries whose research evidence was measured on this timeframe.

        A timeframe with no measured evidence yields no candidates at all: the
        runtime cannot invent an expected edge for a horizon nobody studied.
        """
        return {
            sid: entry
            for sid, entry in self._entries.items()
            if entry.timeframe == timeframe
        }

    def key_for(self, family: str, timeframe: str) -> str:
        """Ledger key convention: ``<family>@<timeframe>``."""
        return f"{family}@{timeframe}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "_source_path": self._source_path,
            "strategies": {sid: e.to_dict() for sid, e in sorted(self._entries.items())},
        }
