"""Feed dead-man guard — block new entries when market data goes stale.

EXECUTION-RELIABILITY-01 (checkpoint EXTERNAL-AUDIT-RECONCILIATION-01,
directive 10). Execution-layer guard only: no strategy logic changes. When
required market data becomes stale the guard blocks new entries, prevents
stale pricing from reaching execution, and emits an explicit state/evidence
record. Resting-order cancellation policy is explicit and deterministic
(BLOCK_ONLY by default; CANCEL_RESTING is available where applicable).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class FeedGuardAction(Enum):
    """Deterministic action when feed freshness is evaluated."""

    ALLOW = "allow"
    BLOCK_NEW_ENTRIES = "block_new_entries"
    BLOCK_AND_CANCEL_RESTING = "block_and_cancel_resting"


@dataclass(frozen=True, slots=True)
class FeedFreshness:
    """Freshness observation for one required feed."""

    feed_id: str
    last_update_ts: float
    observed_at_ts: float
    max_staleness_seconds: float

    @property
    def staleness_seconds(self) -> float:
        return self.observed_at_ts - self.last_update_ts

    @property
    def is_stale(self) -> bool:
        return self.staleness_seconds > self.max_staleness_seconds


@dataclass(frozen=True, slots=True)
class FeedGuardVerdict:
    """Explicit state + evidence for a feed guard evaluation."""

    action: FeedGuardAction
    stale_feeds: tuple[str, ...]
    evidence: dict[str, Any]


@dataclass
class FeedDeadManGuard:
    """Dead-man switch over required market data feeds.

    ``required_feeds`` are the feeds execution depends on for NEW entries.
    If any required feed is stale, new entries are blocked; if configured,
    resting orders are cancelled deterministically after a hard staleness
    threshold (``cancel_after_multiplier`` x the feed's max staleness).
    """

    cancel_resting_on_stale: bool = False
    cancel_after_multiplier: float = 3.0
    _events: list[FeedGuardVerdict] = field(default_factory=list)

    def evaluate(
        self,
        freshness: tuple[FeedFreshness, ...],
    ) -> FeedGuardVerdict:
        """Evaluate all required feeds; deterministic on the observation set."""
        stale = tuple(f.feed_id for f in freshness if f.is_stale)
        if not stale:
            verdict = FeedGuardVerdict(
                action=FeedGuardAction.ALLOW,
                stale_feeds=(),
                evidence={
                    "feeds": {
                        f.feed_id: {
                            "staleness_seconds": round(f.staleness_seconds, 6),
                            "max_staleness_seconds": f.max_staleness_seconds,
                            "stale": False,
                        }
                        for f in freshness
                    }
                },
            )
        else:
            hard_stale = tuple(
                f.feed_id
                for f in freshness
                if f.is_stale
                and f.staleness_seconds > f.max_staleness_seconds * self.cancel_after_multiplier
            )
            if self.cancel_resting_on_stale and hard_stale:
                action = FeedGuardAction.BLOCK_AND_CANCEL_RESTING
            else:
                action = FeedGuardAction.BLOCK_NEW_ENTRIES
            verdict = FeedGuardVerdict(
                action=action,
                stale_feeds=stale,
                evidence={
                    "feeds": {
                        f.feed_id: {
                            "staleness_seconds": round(f.staleness_seconds, 6),
                            "max_staleness_seconds": f.max_staleness_seconds,
                            "stale": f.feed_id in stale,
                            "hard_stale": f.feed_id in hard_stale,
                        }
                        for f in freshness
                    },
                    "cancel_after_multiplier": self.cancel_after_multiplier,
                },
            )
        self._events.append(verdict)
        return verdict

    def allow_new_entries(self, verdict: FeedGuardVerdict) -> bool:
        return verdict.action is FeedGuardAction.ALLOW

    @property
    def events(self) -> tuple[FeedGuardVerdict, ...]:
        return tuple(self._events)
