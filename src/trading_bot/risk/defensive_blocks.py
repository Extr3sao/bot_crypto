"""Defensive risk blocks — evaluated, not merely declared.

``config/risk.yaml`` has declared four hard blocks since the beginning: an
excessive spread, an extreme ATR, a high latency and weekend trading. WP-EDGE-016
audited the source and found that nothing in the runtime read any of them; the
research lane honoured the weekend flag by itself and the other three were
decoration. A block that no code evaluates is not a control.

This module is the missing evaluation, and it is **fail closed**:

* a condition that was not measured is a block (``*_UNKNOWN``), never a pass —
  the same rule ``tools/../exchange_connector.fetch_spread_bps`` already follows
  when the book is missing;
* the weekend rule is read from the calendar, not from the caller, so a caller
  cannot forget it;
* nothing here reads or writes policy. It receives ``DefensiveBlocks`` and
  returns a verdict with the numbers that produced it.

The caller (``PaperCycleEngine``) evaluates a verdict per symbol before
``RiskManager.check_signal`` and records the rejection with the block's name.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from trading_bot.config.risk import DefensiveBlocks

BLOCK_WEEKEND = "weekend_trading"
BLOCK_SPREAD = "excessive_spread_bps"
BLOCK_ATR = "extreme_atr_pct"
BLOCK_LATENCY = "high_latency_ms"
BLOCK_SPREAD_UNKNOWN = "spread_unknown"
BLOCK_ATR_UNKNOWN = "atr_unknown"
BLOCK_LATENCY_UNKNOWN = "latency_unknown"


@dataclass(frozen=True, slots=True)
class MarketConditions:
    """What a decision can actually know about the market it is about to trade.

    ``None`` means "not measured", which blocks. ``latency_ms`` is the age of the
    data being acted on — from the snapshot that produced the decision to the
    moment of the decision — because that delay is the one a paper runtime can
    observe honestly; venue round-trip time is not observable without an order.
    """

    at: datetime
    spread_bps: float | None = None
    atr_pct: float | None = None
    latency_ms: float | None = None


@dataclass(frozen=True, slots=True)
class BlockVerdict:
    """The verdict, the rule that produced it and the inputs it used."""

    blocked: bool
    blocked_by: str | None = None
    reason: str | None = None
    observed: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "blocked": self.blocked,
            "blocked_by": self.blocked_by,
            "reason": self.reason,
            "observed": dict(self.observed or {}),
        }


def evaluate_blocks(blocks: DefensiveBlocks, conditions: MarketConditions | None) -> BlockVerdict:
    """Evaluate all four declared blocks; the first one that fires wins.

    ``conditions is None`` means the caller could not gather market data at all,
    which blocks every trade rather than letting one through unevaluated.
    """
    if conditions is None:
        return BlockVerdict(
            blocked=True,
            blocked_by="market_conditions_unknown",
            reason="no market conditions supplied: the declared blocks cannot be evaluated",
            observed={},
        )

    at = conditions.at if conditions.at.tzinfo else conditions.at.replace(tzinfo=UTC)
    observed = {
        "at_utc": at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "weekday": at.weekday(),
        "spread_bps": conditions.spread_bps,
        "atr_pct": conditions.atr_pct,
        "latency_ms": conditions.latency_ms,
        "declared": {
            "weekend_trading": blocks.weekend_trading,
            "excessive_spread_bps": blocks.excessive_spread_bps,
            "extreme_atr_pct": blocks.extreme_atr_pct,
            "high_latency_ms": blocks.high_latency_ms,
        },
    }

    if at.weekday() >= 5 and not blocks.weekend_trading:
        return BlockVerdict(
            blocked=True,
            blocked_by=BLOCK_WEEKEND,
            reason=f"weekend ({at.strftime('%A')}) and blocks.weekend_trading=false",
            observed=observed,
        )

    if conditions.spread_bps is None:
        return BlockVerdict(
            blocked=True,
            blocked_by=BLOCK_SPREAD_UNKNOWN,
            reason="spread not measured: an unmeasured hostile condition is not a pass",
            observed=observed,
        )
    if conditions.spread_bps > blocks.excessive_spread_bps:
        return BlockVerdict(
            blocked=True,
            blocked_by=BLOCK_SPREAD,
            reason=(
                f"spread {conditions.spread_bps:.2f} bps > "
                f"{blocks.excessive_spread_bps} bps declared"
            ),
            observed=observed,
        )

    if conditions.atr_pct is None:
        return BlockVerdict(
            blocked=True,
            blocked_by=BLOCK_ATR_UNKNOWN,
            reason="ATR% not measured: an unmeasured hostile condition is not a pass",
            observed=observed,
        )
    if conditions.atr_pct > blocks.extreme_atr_pct:
        return BlockVerdict(
            blocked=True,
            blocked_by=BLOCK_ATR,
            reason=(f"ATR {conditions.atr_pct:.2f}% > {blocks.extreme_atr_pct}% declared"),
            observed=observed,
        )

    if conditions.latency_ms is None:
        return BlockVerdict(
            blocked=True,
            blocked_by=BLOCK_LATENCY_UNKNOWN,
            reason="latency not measured: an unmeasured hostile condition is not a pass",
            observed=observed,
        )
    if conditions.latency_ms > blocks.high_latency_ms:
        return BlockVerdict(
            blocked=True,
            blocked_by=BLOCK_LATENCY,
            reason=(
                f"data age {conditions.latency_ms:.0f} ms > {blocks.high_latency_ms} ms declared"
            ),
            observed=observed,
        )

    return BlockVerdict(blocked=False, observed=observed)


__all__ = [
    "BLOCK_ATR",
    "BLOCK_ATR_UNKNOWN",
    "BLOCK_LATENCY",
    "BLOCK_LATENCY_UNKNOWN",
    "BLOCK_SPREAD",
    "BLOCK_SPREAD_UNKNOWN",
    "BLOCK_WEEKEND",
    "BlockVerdict",
    "MarketConditions",
    "evaluate_blocks",
]
