"""Legacy memory lookups for Strategy Experts, Critics and Debate.

Read-only: these helpers expose what legacy history says about a hypothesis,
family or asset so critics can flag already-tested hypotheses, rejected
variants, cost problems and post-hoc attempts. Nothing here mutates scores.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .store import LegacyEvidenceRecord, LegacyEvidenceStore


@dataclass(frozen=True, slots=True)
class LegacyCritiqueHints:
    """What legacy history contributes to a critique (observation only)."""

    hypothesis_already_tested: bool
    tested_evidence_ids: tuple[str, ...]
    rejected_variants: tuple[str, ...]
    cost_problem: bool
    post_hoc_attempt: bool
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "hypothesis_already_tested": self.hypothesis_already_tested,
            "tested_evidence_ids": list(self.tested_evidence_ids),
            "rejected_variants": list(self.rejected_variants),
            "cost_problem": self.cost_problem,
            "post_hoc_attempt": self.post_hoc_attempt,
            "summary": self.summary,
        }


class LegacyHypothesisIndex:
    """Queryable legacy memory by asset / family / hypothesis keyword."""

    def __init__(self, store: LegacyEvidenceStore) -> None:
        self._store = store

    @property
    def store(self) -> LegacyEvidenceStore:
        return self._store

    # -- queries for experts (G8) ------------------------------------------

    def for_asset(self, symbol: str) -> list[LegacyEvidenceRecord]:
        return self._store.by_symbol(symbol)

    def for_family(self, legacy_family: str) -> list[LegacyEvidenceRecord]:
        return self._store.by_family(legacy_family)

    # -- queries for critics (G9) -------------------------------------------

    def campaign_verdicts(self) -> dict[str, str]:
        return {
            r.evidence_id: r.verdict
            for r in self._store.all_records()
            if r.kind == "campaign"
        }

    def rejected_campaigns(self) -> list[LegacyEvidenceRecord]:
        return [
            r
            for r in self._store.all_records()
            if r.kind == "campaign"
            and ("STOP" in r.verdict or "REJECT" in r.verdict or r.verdict == "FAIL_NOT_PROMOTED")
        ]

    def hypotheses_matching(self, *keywords: str) -> list[LegacyEvidenceRecord]:
        """Search verdicts/payloads for preregistered hypothesis records."""
        wanted = [k.lower() for k in keywords if k]
        matches: list[LegacyEvidenceRecord] = []
        for record in self._store.all_records():
            haystack = json_dumps(record).lower()
            if all(k in haystack for k in wanted):
                matches.append(record)
        return matches

    def critique_hints(
        self, *, symbol: str | None = None, legacy_family: str | None = None
    ) -> LegacyCritiqueHints:
        """Detect repeated legacy hypotheses / rejected variants / cost issues."""
        records: list[LegacyEvidenceRecord] = []
        if symbol:
            records += self.for_asset(symbol)
        if legacy_family:
            records += self.for_family(legacy_family)
        tested_ids = tuple(sorted({r.evidence_id for r in records}))
        rejected = tuple(
            sorted(
                r.evidence_id
                for r in self.rejected_campaigns()
            )
        )
        net_negative = [
            r
            for r in records
            if r.net_pnl is not None and r.net_pnl < 0 and (r.fees or 0) > 0
        ]
        cost_problem = bool(net_negative)
        # Post-hoc: the R31.9 diagnostic explicitly forbids inverting the
        # pre-registered candidate (VOL_GE_1 FAIL must never be promoted).
        post_hoc = any(r.kind == "diagnostic" and r.verdict == "FAIL_NOT_PROMOTED" for r in records)
        summary = (
            f"legacy records={len(records)} tested={len(tested_ids)} "
            f"rejected_campaigns={len(rejected)} net_negative_with_fees={len(net_negative)}"
        )
        return LegacyCritiqueHints(
            hypothesis_already_tested=bool(records),
            tested_evidence_ids=tested_ids,
            rejected_variants=rejected,
            cost_problem=cost_problem,
            post_hoc_attempt=post_hoc,
            summary=summary,
        )


def json_dumps(record: LegacyEvidenceRecord) -> str:
    import json

    return json.dumps(record.to_dict(), sort_keys=True, default=str)
