"""Shadow-only provenance attachment at the OpportunityBoard/MetaRanker edge.

The linker produces an immutable, side-effect-free annotation for a ranked
opportunity. Nothing in this module reads or writes ranking state, and no
decision/execution component consumes it (G7/G10 rely on this isolation).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .store import LegacyEvidenceRecord

if TYPE_CHECKING:
    from .store import LegacyEvidenceStore


@dataclass(frozen=True, slots=True)
class LegacyShadowLink:
    """Immutable provenance annotation: NEVER consumed by scoring/execution."""

    proposal_id: str
    legacy_evidence_ids: tuple[str, ...]
    legacy_family: str | None
    verdicts: tuple[str, ...]
    consumed_development_period: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "legacy_evidence_ids": list(self.legacy_evidence_ids),
            "legacy_family": self.legacy_family,
            "verdicts": list(self.verdicts),
            "consumed_development_period": self.consumed_development_period,
            "shadow_only": True,
        }


class ShadowEvidenceLinker:
    """Builds shadow links between current proposals and legacy evidence.

    Usage is restricted to observability: experts/critics may CALL this to
    attach historical context to reports; MetaRanker scoring and PaperBroker
    execution never receive the linker's output.
    """

    def __init__(self, store: LegacyEvidenceStore) -> None:
        self._store = store

    def link(
        self,
        proposal_id: str,
        *,
        symbol: str | None = None,
        legacy_family: str | None = None,
    ) -> LegacyShadowLink:
        matched: list[LegacyEvidenceRecord] = []
        if symbol is not None:
            matched += self._store.by_symbol(symbol)
        if legacy_family is not None:
            matched += self._store.by_family(legacy_family)
        ordered = sorted(matched, key=lambda r: r.evidence_id)
        return LegacyShadowLink(
            proposal_id=proposal_id,
            legacy_evidence_ids=tuple(r.evidence_id for r in ordered),
            legacy_family=legacy_family,
            verdicts=tuple(r.verdict for r in ordered),
        )
