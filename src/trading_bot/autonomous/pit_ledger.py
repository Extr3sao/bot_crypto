"""Point-in-time admission ledger — value-as-known-then (RFC-021 §5-§8).

The frozen ``AdmissionLedger`` reports a strategy's measured gross edge over the
WHOLE research window (``W1-W7``). Replaying a decision inside that window then
reads a prior calibrated on its own future — the RFC-020 P1 finding.

``PitAdmissionLedger`` fixes that without touching the runtime: it wraps the
frozen ledger's structure and recomputes each strategy's expected gross edge
from PER-TRADE outcomes, using ONLY trades that were already observable at the
decision instant:

    outcome available at ``exit_ts`` (§8: ledger_available_time >= outcome_time)
    → a decision at ``T`` may only use trades with ``exit_ts < T``

Below a minimum sample the edge is ``None`` and the status degrades to
``RESEARCH_REQUIRED`` with an explicit ``INSUFFICIENT_LEDGER_HISTORY`` rationale —
never a global average, never a future value, never a silent fallback (§7).

It is a drop-in for the ``AdmissionLedger`` duck-type the runtime consumes: the
caller advances ``as_of_ms`` once per decision (walk-forward, §6) and every read
reflects the past only.
"""

from __future__ import annotations

import bisect
from dataclasses import replace

from .admission_ledger import AdmissionLedger
from .contracts import AdmissionEntry, AdmissionStatus, EdgeEvidence

__all__ = ["DEFAULT_MIN_SAMPLE", "INSUFFICIENT_REASON", "PitAdmissionLedger"]

#: Minimum observable outcomes before a strategy has an expected edge at all.
DEFAULT_MIN_SAMPLE = 30

INSUFFICIENT_REASON = "INSUFFICIENT_LEDGER_HISTORY"


class PitAdmissionLedger:
    """`AdmissionLedger` view whose expected edge is as-of ``as_of_ms``.

    ``outcomes`` maps ``strategy_id`` → a list of ``(exit_ts_ms, gross_bps)``
    observations, ascending by ``exit_ts_ms``. Only observations strictly before
    ``as_of_ms`` are ever used.
    """

    def __init__(
        self,
        base: AdmissionLedger,
        outcomes: dict[str, list[tuple[int, float]]],
        *,
        min_sample: int = DEFAULT_MIN_SAMPLE,
    ) -> None:
        self._base = base
        self._outcomes = {
            sid: sorted(rows, key=lambda row: row[0]) for sid, rows in outcomes.items()
        }
        self._min_sample = int(min_sample)
        self._as_of_ms = 0
        # per-strategy (sorted exit stamps, cumulative gross sums) for O(log n) reads
        self._stamps: dict[str, list[int]] = {
            sid: [ts for ts, _ in rows] for sid, rows in self._outcomes.items()
        }
        self._cumsum: dict[str, list[float]] = {}
        for sid, rows in self._outcomes.items():
            run = 0.0
            sums: list[float] = []
            for _, gross in rows:
                run += gross
                sums.append(run)
            self._cumsum[sid] = sums

    # -- walk-forward driver -----------------------------------------------

    @property
    def as_of_ms(self) -> int:
        return self._as_of_ms

    def advance_to(self, as_of_ms: int) -> None:
        """Move the ledger clock forward (never backwards within a run)."""
        if as_of_ms < self._as_of_ms:
            raise ValueError("PIT ledger time must not move backwards")
        self._as_of_ms = int(as_of_ms)

    # -- edge resolution ---------------------------------------------------

    def observables(self, strategy_id: str) -> tuple[int, float] | None:
        """(sample_count, mean_gross_bps) of outcomes with exit_ts < as_of_ms."""
        stamps = self._stamps.get(strategy_id)
        if not stamps:
            return None
        cutoff = bisect.bisect_left(stamps, self._as_of_ms)  # strictly before
        if cutoff <= 0:
            return None
        total = self._cumsum[strategy_id][cutoff - 1]
        return cutoff, total / cutoff

    def _resolved(self, strategy_id: str) -> tuple[float | None, int]:
        obs = self.observables(strategy_id)
        if obs is None or obs[0] < self._min_sample:
            return None, 0 if obs is None else obs[0]
        return obs[1], obs[0]

    # -- AdmissionLedger duck-type -----------------------------------------

    @property
    def source_path(self) -> str:
        return self._base.source_path

    @property
    def sources(self) -> tuple[dict[str, str], ...]:
        return self._base.sources

    @property
    def schema_version(self) -> str:
        return self._base.schema_version

    def strategy_ids(self) -> list[str]:
        return self._base.strategy_ids()

    def entries(self) -> dict[str, AdmissionEntry]:
        return {sid: self.entry(sid) for sid in self._base.strategy_ids()}

    def entries_for_timeframe(self, timeframe: str) -> dict[str, AdmissionEntry]:
        return {
            sid: self.entry(sid)
            for sid in self._base.strategy_ids()
            if self._base.entry(sid).timeframe == timeframe
        }

    def entry(self, strategy_id: str) -> AdmissionEntry:
        base_entry = self._base.entry(strategy_id)
        gross, sample = self._resolved(strategy_id)
        if gross is None:
            status = (
                AdmissionStatus.UNKNOWN
                if not base_entry.known
                else AdmissionStatus.RESEARCH_REQUIRED
            )
            return replace(
                base_entry,
                status=status,
                admitted_for_paper=False,
                expected_gross_edge_bps=None,
                edge_evidence=None,
                rationale=(
                    f"{INSUFFICIENT_REASON}: {sample} observable outcomes "
                    f"< min {self._min_sample} before decision time"
                ),
            )
        status = (
            AdmissionStatus.RESEARCH_CANDIDATE
            if gross > 0
            else AdmissionStatus.NO_GROSS_EDGE
        )
        evidence = EdgeEvidence(
            source_doc="reports/strategy-baseline/TRADES_*.csv (as-of)",
            metric="family_gross_bps_per_trade_as_of",
            value_bps=round(gross, 6),
            knowledge="HISTORICAL_AS_OF",
            sample_trades=sample,
        )
        return replace(
            base_entry,
            status=status,
            admitted_for_paper=False,
            expected_gross_edge_bps=round(gross, 6),
            edge_evidence=evidence,
            rationale=(
                f"as-of {self._as_of_ms}: {sample} outcomes, mean gross "
                f"{gross:.4f} bps/trade (never admitted for paper here)"
            ),
        )

    def status_for(self, strategy_id: str) -> AdmissionStatus:
        return self.entry(strategy_id).status

    def is_paper_admitted(self, strategy_id: str) -> bool:
        return False  # a PIT ledger never auto-promotes; promotion is a separate gate

    def expected_gross_edge_bps(self, strategy_id: str) -> float | None:
        return self.entry(strategy_id).expected_gross_edge_bps

    def paper_candidates(self) -> list[str]:
        return []

    def key_for(self, family: str, timeframe: str) -> str:
        return f"{family}@{timeframe}"

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": "strategy-admission-ledger-pit-v1",
            "as_of_ms": self._as_of_ms,
            "min_sample": self._min_sample,
            "base_source_path": self._base.source_path,
            "strategies": {sid: e.to_dict() for sid, e in sorted(self.entries().items())},
        }

