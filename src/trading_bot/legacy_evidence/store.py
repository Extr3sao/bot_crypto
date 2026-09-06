"""Legacy evidence records, store, and fail-closed eligibility policy.

Every legacy artifact becomes an immutable :class:`LegacyEvidenceRecord`
carrying the required provenance and eligibility contract:

- ``consumed_development_period`` is always True for the legacy window.
- ``eligible_for_context`` may be True (experts/critics may READ the memory).
- ``eligible_for_training`` / ``eligible_for_candidate_promotion`` /
  ``eligible_for_confirmation`` are hard-wired False (fail-closed).
- ``can_affect_execution`` is hard-wired False.

The store is the single authority for these flags: callers cannot construct
records with promotion flags enabled, and every helper that could be (mis)used
for promotion/confirmation re-checks the flags and raises
:class:`LegacyPromotionError` on violation (G6, G12, G13).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .ingest import LEGACY_PERIOD_END_EXCLUSIVE, LEGACY_PERIOD_START, SOURCE_SYSTEM

SCHEMA_VERSION = "legacy-evidence-v1"

#: Assets whose historical evidence is directly queryable by Asset Experts.
CORE_ASSETS: frozenset[str] = frozenset({"BTC", "ETH", "SOL"})

#: Legacy period is CONSUMED_DEVELOPMENT: no training/promotion/confirmation.
CONSUMED_DEVELOPMENT_PERIOD = True


class LegacyPromotionError(PermissionError):
    """Any attempt to use legacy evidence beyond context/critique."""


@dataclass(frozen=True, slots=True)
class LegacyEvidenceRecord:
    """Immutable provenance + economics record for one legacy artifact."""

    evidence_id: str
    source_system: str = SOURCE_SYSTEM
    source_version: str = ""
    source_sha256: str = ""
    period_start: datetime = LEGACY_PERIOD_START
    period_end: datetime = LEGACY_PERIOD_END_EXCLUSIVE
    symbol: str | None = None
    legacy_family: str | None = None
    canonical_strategy_hint: str | None = None
    regime: str | None = None
    sample_n: int | None = None
    gross_expectancy_r: float | None = None
    net_expectancy_r: float | None = None
    profit_factor: float | None = None
    gross_pnl: float | None = None
    fees: float | None = None
    net_pnl: float | None = None
    verdict: str = ""
    consumed_development_period: bool = CONSUMED_DEVELOPMENT_PERIOD
    eligible_for_context: bool = True
    eligible_for_training: bool = False
    eligible_for_candidate_promotion: bool = False
    eligible_for_confirmation: bool = False
    can_affect_execution: bool = False
    kind: str = "aggregate"
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "evidence_id": self.evidence_id,
            "source_system": self.source_system,
            "source_version": self.source_version,
            "source_sha256": self.source_sha256,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "symbol": self.symbol,
            "legacy_family": self.legacy_family,
            "canonical_strategy_hint": self.canonical_strategy_hint,
            "regime": self.regime,
            "sample_n": self.sample_n,
            "gross_expectancy_r": self.gross_expectancy_r,
            "net_expectancy_r": self.net_expectancy_r,
            "profit_factor": self.profit_factor,
            "gross_pnl": self.gross_pnl,
            "fees": self.fees,
            "net_pnl": self.net_pnl,
            "verdict": self.verdict,
            "consumed_development_period": self.consumed_development_period,
            "eligible_for_context": self.eligible_for_context,
            "eligible_for_training": self.eligible_for_training,
            "eligible_for_candidate_promotion": self.eligible_for_candidate_promotion,
            "eligible_for_confirmation": self.eligible_for_confirmation,
            "can_affect_execution": self.can_affect_execution,
            "kind": self.kind,
        }
        if self.payload:
            data["payload"] = self.payload
        return data

    def assert_usable_for_context(self) -> None:
        if not self.eligible_for_context:
            raise LegacyPromotionError(f"evidence {self.evidence_id} is not eligible for context")
        if self.consumed_development_period and (
            self.eligible_for_training
            or self.eligible_for_candidate_promotion
            or self.eligible_for_confirmation
            or self.can_affect_execution
        ):
            raise LegacyPromotionError(
                f"evidence {self.evidence_id} violates CONSUMED_DEVELOPMENT fail-closed flags"
            )


def _num(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _base_symbol(symbol: str) -> str:
    """BTCUSDT -> BTC (proper suffix removal, not rstrip-set)."""
    upper = symbol.upper()
    return upper[: -len("USDT")] if upper.endswith("USDT") else upper


class LegacyEvidenceStore:
    """Immutable catalog of legacy evidence records, built at ingest time."""

    def __init__(self, records: list[LegacyEvidenceRecord]) -> None:
        self._records: dict[str, LegacyEvidenceRecord] = {}
        for record in records:
            record.assert_usable_for_context()
            self._records[record.evidence_id] = record

    # -- catalog -----------------------------------------------------------

    def __len__(self) -> int:
        return len(self._records)

    def all_records(self) -> list[LegacyEvidenceRecord]:
        return sorted(self._records.values(), key=lambda r: r.evidence_id)

    def get(self, evidence_id: str) -> LegacyEvidenceRecord | None:
        return self._records.get(evidence_id)

    def by_symbol(self, symbol: str) -> list[LegacyEvidenceRecord]:
        """e.g. ``store.by_symbol("VET")`` returns per-asset legacy evidence."""
        wanted = _base_symbol(symbol)
        return [
            r
            for r in self.all_records()
            if r.symbol and _base_symbol(r.symbol) == wanted
        ]

    def by_family(self, legacy_family: str) -> list[LegacyEvidenceRecord]:
        wanted = legacy_family.upper()
        return [r for r in self.all_records() if (r.legacy_family or "").upper() == wanted]

    def core_asset_symbols(self) -> list[str]:
        return sorted(CORE_ASSETS)

    def catalogued_symbols(self) -> list[str]:
        """All legacy symbols (30 assets), catalogued without creating agents."""
        symbols = {
            _base_symbol(r.symbol)
            for r in self.all_records()
            if r.symbol and r.kind == "asset_aggregate"
        }
        return sorted(symbols)

    # -- fail-closed promotion guards (G6 / G12 / G13) ----------------------

    def attempt_candidate_promotion(self, evidence_id: str) -> None:
        """ALWAYS raises for legacy evidence: consumed-development history
        can never justify candidate promotion (e.g. VET/WIF by legacy PnL)."""
        record = self._records.get(evidence_id)
        if record is None:
            raise LegacyPromotionError(f"unknown evidence: {evidence_id}")
        raise LegacyPromotionError(
            f"REJECT: legacy evidence {evidence_id} is CONSUMED_DEVELOPMENT "
            "and can never promote a candidate"
        )

    def attempt_rule_adoption(self, evidence_id: str) -> None:
        """ALWAYS raises for legacy diagnostics: a failed pre-registered
        candidate (e.g. R31.9 VOL_GE_1) can never become a runtime rule."""
        record = self._records.get(evidence_id)
        if record is None:
            raise LegacyPromotionError(f"unknown evidence: {evidence_id}")
        if record.kind == "diagnostic" and record.verdict == "FAIL_NOT_PROMOTED":
            raise LegacyPromotionError(
                f"REJECT: legacy diagnostic {evidence_id} FAILED its pre-registered "
                "matched test and must never be converted into a rule"
            )
        raise LegacyPromotionError(
            f"REJECT: legacy evidence {evidence_id} is CONSUMED_DEVELOPMENT "
            "and can never become a runtime rule"
        )
