"""guards — the deterministic checks an LLM opinion must survive before it can trade.

The RFC is explicit that no trade may be produced by model text without schema, PIT and
the canonical RiskManager. Schema is ``contract.py`` and risk is ``RiskManager``; this
module is the middle layer that answers, mechanically:

* **PIT** — has every bar in the picture *closed* before the decision instant? A chart
  that contains a bar still forming at that instant is a look-ahead, and the position it
  produces would be unfalsifiable. The check needs the bar duration, because a bar's
  timestamp is its open (RFC-TAP-AI-BOTS-003).
* **Freshness** — is the image the one rendered for *this* decision bar? A cached or
  re-used snapshot makes the model answer an old market; the RFC calls it `STALE_CHART`
  and requires zero orders.
* **Asset** — is the chart the asset the decision is about? A BTC chart cannot authorise
  an ETH order (`ASSET_MISMATCH`).
* **Levels** — if the model names a price, is it inside the market it was shown? An
  invented level is a hallucination that would silently become a stop
  (`INVENTED_LEVEL`).
* **Costs** — is there a venue cost to charge? A zero-cost model is a missing input, so
  research runs must declare it as frictionless instead of pretending it is measured.

Each guard raises a typed error with a stable code, so the ledger can be counted by
cause and the report can say *why* a decision was refused instead of reporting a flat
`NO_TRADE` that hides the reason.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

#: A stated level may sit this far outside the window's extreme before it is a
#: hallucination rather than a typo in the last digits.
LEVEL_TOLERANCE = 0.005


class OpinionRejected(RuntimeError):
    """A model opinion rejected by a deterministic guard. Never traded."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def assert_causal(
    bars: Sequence[Any], decision_ts_ms: int, *, bar_interval_ms: int
) -> None:
    """Every bar in the picture must have **closed** at or before the decision instant.

    ``bar_interval_ms`` is required on purpose. A bar's ``ts_ms`` is its open, so the
    earlier version of this check compared opens against the decision instant and let a
    decision made at the close of the last bar pass as if it had been made one timeframe
    earlier — the bar it was reading had not closed yet at that instant. A caller that
    does not know the bar duration cannot answer this question, so it has to say so.
    """

    interval = int(bar_interval_ms)
    if interval <= 0:
        raise ValueError("bar_interval_ms must be positive")
    unclosed = [int(bar.ts_ms) for bar in bars if int(bar.ts_ms) + interval > int(decision_ts_ms)]
    if unclosed:
        raise OpinionRejected(
            "PIT_VIOLATION",
            f"{len(unclosed)} bar(s) had not closed at the decision instant "
            f"(first opens at {unclosed[0]}, closes at {unclosed[0] + interval} "
            f"> {int(decision_ts_ms)})",
        )


def assert_fresh(chart_last_ts_ms: int, decision_bar_ts_ms: int) -> None:
    """The image's last candle must be the decision bar itself."""
    if int(chart_last_ts_ms) != int(decision_bar_ts_ms):
        raise OpinionRejected(
            "STALE_CHART",
            f"image ends at {int(chart_last_ts_ms)} but the decision bar is "
            f"{int(decision_bar_ts_ms)}",
        )


def assert_asset(chart_symbol: str, context_symbol: str) -> None:
    if str(chart_symbol).strip().upper() != str(context_symbol).strip().upper():
        raise OpinionRejected(
            "ASSET_MISMATCH",
            f"chart is {chart_symbol!r} but the decision is about {context_symbol!r}",
        )


def assert_level_inside_market(level: float | None, bars: Sequence[Any]) -> None:
    """A cited price must exist in the market the model was shown."""
    if level is None:
        return
    if not bars:
        raise OpinionRejected("INVENTED_LEVEL", "no bars to validate the cited level against")
    highs = [float(bar.high) for bar in bars]
    lows = [float(bar.low) for bar in bars]
    high = max(highs) * (1.0 + LEVEL_TOLERANCE)
    low = min(lows) * (1.0 - LEVEL_TOLERANCE)
    if not (low <= float(level) <= high):
        raise OpinionRejected(
            "INVENTED_LEVEL",
            f"cited level {float(level):.8f} is outside the window's range "
            f"[{min(lows):.8f}, {max(highs):.8f}]",
        )


@dataclass(frozen=True, slots=True)
class CostCheck:
    """Whether the venue cost model is present and usable."""

    measured: bool
    reason: str
    total_bps: float


def check_costs(cost: Any, *, declared_frictionless: bool = False) -> CostCheck:
    """A zero-cost book must say so; silence is a missing input, not free trading."""
    if cost is None:
        raise OpinionRejected("COST_UNAVAILABLE", "no venue cost was supplied for this signal")
    total = (
        float(getattr(cost, "commission_bps", 0.0))
        + float(getattr(cost, "half_spread_bps", 0.0))
        + float(getattr(cost, "slippage_bps", 0.0))
    )
    if total <= 0.0 and not declared_frictionless:
        raise OpinionRejected(
            "COST_UNAVAILABLE",
            "the cost model prices the round trip at zero; declare the run frictionless "
            "explicitly instead of reporting it as measured",
        )
    return CostCheck(measured=total > 0.0, reason="OK" if total > 0.0 else "FRICTIONLESS_DECLARED", total_bps=total)


def is_weekend(ts_ms: int) -> bool:
    """UTC Saturday/Sunday. The policy flag decides what that means; this only reads it."""
    from datetime import UTC, datetime

    return datetime.fromtimestamp(int(ts_ms) / 1000.0, tz=UTC).weekday() >= 5


def assert_tradeable_window(ts_ms: int, *, weekend_trading: bool) -> None:
    if not weekend_trading and is_weekend(ts_ms):
        raise OpinionRejected(
            "WEEKEND_BLOCK", "policy sets weekend_trading=false; no discretionary entries"
        )
