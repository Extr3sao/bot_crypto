"""Champion/challenger selection (§11).

For one context (asset x timeframe x regime) there is one CHAMPION and any
number of CHALLENGERS. A challenger only becomes a ``PROMOTION_CANDIDATE`` after
it beats the champion over the required number of windows AND with enough
samples — one good short window never promotes. This module decides nothing
about PAPER: it produces a comparison that the lifecycle controller consumes.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final

from .contracts import ContextKey, RationaleCode

__all__ = [
    "CHAMPION_CHALLENGER_VERSION",
    "ChallengerEvaluation",
    "ChampionChallenger",
    "ComparisonOutcome",
    "ComparisonResult",
]

CHAMPION_CHALLENGER_VERSION: Final[str] = "champion-challenger-v1"


class ComparisonOutcome(StrEnum):
    CHAMPION_RETAINED = "CHAMPION_RETAINED"
    CHALLENGER_WINS = "CHALLENGER_WINS"
    PROMOTION_CANDIDATE = "PROMOTION_CANDIDATE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True, slots=True)
class ChallengerEvaluation:
    """One challenger's evidence against the champion."""

    strategy_id: str
    sample_count: int
    net_expectancy_bps: float
    profit_factor: float | None
    max_drawdown_bps: float
    #: Per-window net-bps sums, chronological. Wins are counted window by window.
    window_net_bps: tuple[float, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "sample_count": self.sample_count,
            "net_expectancy_bps": round(self.net_expectancy_bps, 8),
            "profit_factor": None if self.profit_factor is None else round(self.profit_factor, 8),
            "max_drawdown_bps": round(self.max_drawdown_bps, 8),
            "window_net_bps": [round(v, 8) for v in self.window_net_bps],
        }


@dataclass(frozen=True, slots=True)
class ComparisonResult:
    context: ContextKey
    champion_id: str | None
    outcome: ComparisonOutcome
    winner_id: str | None
    challengers: tuple[ChallengerEvaluation, ...]
    reason_codes: tuple[str, ...]
    evidence: tuple[str, ...]
    metrics: dict[str, dict[str, float]] = field(default_factory=dict)
    timestamp_ms: int = 0
    schema_version: str = CHAMPION_CHALLENGER_VERSION

    @property
    def promotes(self) -> bool:
        return self.outcome is ComparisonOutcome.PROMOTION_CANDIDATE

    def to_dict(self) -> dict[str, Any]:
        return {
            "context": self.context.to_dict(),
            "champion_id": self.champion_id,
            "outcome": self.outcome.value,
            "winner_id": self.winner_id,
            "challengers": [c.to_dict() for c in self.challengers],
            "reason_codes": list(self.reason_codes),
            "evidence": list(self.evidence),
            "metrics": self.metrics,
            "timestamp_ms": self.timestamp_ms,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class ChampionChallenger:
    """Deterministic champion/challenger comparison (§11)."""

    minimum_samples: int = 100
    minimum_challenger_edge_bps: float = 5.0
    minimum_profit_factor_advantage: float = 0.1
    #: Windows the challenger must win before it can be a promotion candidate.
    required_window_wins: int = 3
    #: Margin (bps) the challenger must clear on the champion to count a window.
    window_win_margin_bps: float = 0.0
    version: str = CHAMPION_CHALLENGER_VERSION

    def compare(
        self,
        *,
        context: ContextKey,
        champion: ChallengerEvaluation | None,
        challengers: Sequence[ChallengerEvaluation],
        timestamp_ms: int = 0,
    ) -> ComparisonResult:
        challengers = tuple(sorted(challengers, key=lambda c: c.strategy_id))
        if champion is None:
            return ComparisonResult(
                context=context,
                champion_id=None,
                outcome=ComparisonOutcome.INSUFFICIENT_EVIDENCE,
                winner_id=None,
                challengers=challengers,
                reason_codes=(RationaleCode.INSUFFICIENT_EVIDENCE.value,),
                evidence=("no champion registered for this context",),
                metrics=self._metrics(champion, challengers),
                timestamp_ms=timestamp_ms,
            )

        qualified: list[ChallengerEvaluation] = []
        evidence: list[str] = []
        for challenger in challengers:
            wins, total = self._window_wins(challenger, champion)
            edge = challenger.net_expectancy_bps - champion.net_expectancy_bps
            pf_adv = (challenger.profit_factor or 0.0) - (champion.profit_factor or 0.0)
            evidence.append(
                f"{challenger.strategy_id}: edge={edge:.2f}bps pf_adv={pf_adv:.2f} "
                f"wins={wins}/{total} samples={challenger.sample_count}"
            )
            if (
                challenger.sample_count >= self.minimum_samples
                and edge >= self.minimum_challenger_edge_bps
                and pf_adv >= self.minimum_profit_factor_advantage
                and wins >= self.required_window_wins
            ):
                qualified.append(challenger)

        if not qualified:
            return ComparisonResult(
                context=context,
                champion_id=champion.strategy_id,
                outcome=ComparisonOutcome.CHAMPION_RETAINED,
                winner_id=champion.strategy_id,
                challengers=challengers,
                reason_codes=(RationaleCode.CHAMPION_RETAINED.value,),
                evidence=tuple(evidence),
                metrics=self._metrics(champion, challengers),
                timestamp_ms=timestamp_ms,
            )

        best = sorted(
            qualified,
            key=lambda c: (-c.net_expectancy_bps, -(c.profit_factor or 0.0), c.strategy_id),
        )[0]
        evidence.append(
            f"{best.strategy_id} cleared all gates; becomes a PROMOTION_CANDIDATE "
            "(not an automatic promotion)"
        )
        return ComparisonResult(
            context=context,
            champion_id=champion.strategy_id,
            outcome=ComparisonOutcome.PROMOTION_CANDIDATE,
            winner_id=best.strategy_id,
            challengers=challengers,
            reason_codes=(RationaleCode.CHALLENGER_WIN.value,),
            evidence=tuple(evidence),
            metrics=self._metrics(champion, challengers),
            timestamp_ms=timestamp_ms,
        )

    # -- helpers -----------------------------------------------------------

    def _window_wins(
        self, challenger: ChallengerEvaluation, champion: ChallengerEvaluation
    ) -> tuple[int, int]:
        n = min(len(challenger.window_net_bps), len(champion.window_net_bps))
        if n == 0:
            return 0, 0
        wins = 0
        for i in range(n):
            if (
                challenger.window_net_bps[i]
                > champion.window_net_bps[i] + self.window_win_margin_bps
            ):
                wins += 1
        return wins, n

    @staticmethod
    def _metrics(
        champion: ChallengerEvaluation | None,
        challengers: Sequence[ChallengerEvaluation],
    ) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        if champion is not None:
            out[champion.strategy_id] = {
                "net_expectancy_bps": champion.net_expectancy_bps,
                "profit_factor": champion.profit_factor or 0.0,
                "sample_count": float(champion.sample_count),
            }
        for c in challengers:
            out[c.strategy_id] = {
                "net_expectancy_bps": c.net_expectancy_bps,
                "profit_factor": c.profit_factor or 0.0,
                "sample_count": float(c.sample_count),
            }
        return out
