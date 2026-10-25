"""WP-EDGE-08 — six proposed books, registered before they were measured, and the CURRENT arms.

Two tracks, kept apart on purpose:

* **QUALITY** — a daily clock, holds of days to weeks, few trades and a large objective per
  trade. ``FINDINGS.md`` of WP-EDGE-07 measured the cost barrier on the actual bars: a book at a
  daily clock has to capture 11-16 % of the open-to-open move to pay a 23.79 bps round trip,
  where an hourly book has to capture 58-86 %. The QUALITY books live where that arithmetic is
  survivable, and their problem is sample size, not cost.
* **ACTIVE** — a one-hour entry clock with multi-day holds, aiming at the mission's three trades
  a day *across* the universe (≈0.5 per asset per day on the six-symbol cross-section). A hold of
  one to three days is what makes three trades a day reachable at all: six assets re-entering
  every day or two is that many trades, and each one still has to clear the round trip.

Rules this module keeps, and they are the reason it can be trusted:

* **No size, no risk change.** A signal carries a stop, an objective and a direction;
  ``config/risk.yaml`` decides the quantity. No book may relax a limit, add a cooldown or touch
  the drawdown halt.
* **The cost gate is global and declared.** Every book goes through ``_Base.cost_gate`` with a
  registered ``cost_margin``, so a setup whose own objective cannot pay for the round trip is
  refused by the instrument, before anybody sees a result.
* **Registered parameters.** ``DECLARED_PARAMS`` is the machine-readable copy of
  ``PREREGISTRATION.json``, the hash of each book's parameters is published there, and
  ``scripts/edge08_verify.py`` recomputes every hash and fails if a parameter has moved.
* **No look-ahead.** Every feature is read at the closed bar ``i`` through the frozen
  ``features`` helpers; the simulator fills at the open of ``i + 1``.

All books are long only: this is spot, and a "fade" is the purchase of a stretched move.
"""

from __future__ import annotations

from typing import Any

from trading_bot.research.edge01.candidates import (
    CandidateSignal,
    ContextSeries,
    Outcome,
    _Base,
)
from trading_bot.research.edge01.costs import CostPlane
from trading_bot.research.edge01.data import BAR_MS, OHLCVBar
from trading_bot.research.edge01.features import atr, ema, prior_extreme, trend_label
from trading_bot.research.edge06.families import build_families
from trading_bot.research.edge07.active import build_active_books

__all__ = [
    "CURRENT_ARMS",
    "DECLARED_PARAMS",
    "PROPOSED_ARMS",
    "ActiveDayBreak",
    "ActiveMultiDayRange",
    "ActiveStretchRevert",
    "QualityBreakoutDaily",
    "QualityPullbackDaily",
    "QualityReversionDaily",
    "build_current",
    "build_proposed",
    "params_hash",
]

TIMEFRAME_QUALITY = "1d"
TIMEFRAME_ACTIVE = "1h"


def _rolling_mean(closes: list[float], i: int, period: int) -> float | None:
    """Mean of the last ``period`` closes ending at ``i`` (the band's own centre).

    Written here rather than imported because the frozen ``features`` module has no rolling-mean
    helper; the definition is named in the report so a reader can reproduce it.
    """
    if i + 1 < period:
        return None
    window = closes[i - period + 1 : i + 1]
    return sum(window) / period


def params_hash(params: dict[str, Any]) -> str:
    """The published fingerprint of one book's parameters (sorted keys, compact separators)."""
    import hashlib
    import json

    return hashlib.sha256(
        json.dumps(params, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


#: The registration, in machine-readable form. Every value is a line of ``PREREGISTRATION.md``.
DECLARED_PARAMS: dict[str, dict[str, Any]] = {
    # -- QUALITY: the daily clock, where the barrier is 11-16 % of the move -------------- #
    "edge08_quality_breakout_daily": {
        "breakout_lookback": 20,
        "trend_ema": 200,
        "exit_ema": 100,
        "atr_period": 20,
        "stop_atr": 2.0,
        "target_atr": 6.0,
        "trail_atr": 4.0,
        "min_rr": 1.5,
        "cost_margin": 1.5,
    },
    "edge08_quality_pullback_daily": {
        "trend_fast": 50,
        "trend_slow": 200,
        "pullback_ema": 20,
        "exit_ema": 100,
        "atr_period": 20,
        "entry_distance_atr": 0.5,
        "stop_atr": 2.0,
        "target_atr": 3.0,
        "trail_atr": 2.5,
        "min_rr": 1.5,
        "cost_margin": 1.5,
    },
    "edge08_quality_reversion_daily": {
        "mean_period": 20,
        "stretch_atr": 3.0,
        "regime_ema_fast": 50,
        "regime_ema_slow": 200,
        "regime_max_gap_pct": 1.0,
        "atr_period": 20,
        "stop_atr": 2.0,
        "min_rr": 1.5,
        "cost_margin": 1.5,
    },
    # -- ACTIVE: one-hour entries, multi-day holds, aiming at 3 trades a day -------------- #
    "edge08_active_daybreak_1h": {
        "breakout_lookback": 24,
        "trend_ema": 200,
        "exit_ema": 50,
        "atr_period": 14,
        "thrust_atr": 0.5,
        "stop_atr": 2.0,
        "target_atr": 4.0,
        "trail_atr": 3.0,
        "min_rr": 1.25,
        "cost_margin": 1.5,
    },
    "edge08_active_stretch_revert_1h": {
        "mean_ema": 48,
        "atr_period": 14,
        "stretch_atr": 2.5,
        "down_bar_atr": 1.0,
        "stop_atr": 1.5,
        "min_rr": 1.0,
        "cost_margin": 1.5,
    },
    "edge08_active_multiday_range_1h": {
        "range_lookback": 72,
        "compression_atr": 6.0,
        "trend_ema": 200,
        "exit_ema": 50,
        "atr_period": 14,
        "stop_atr": 2.0,
        "target_atr": 5.0,
        "trail_atr": 3.0,
        "min_rr": 1.5,
        "cost_margin": 1.5,
    },
}


class QualityBreakoutDaily(_Base):
    """Q-1: Donchian breakout on a daily clock, filtered by the frozen 200-day EMA.

    The structure is the classic 20-day breakout with a stop two average true ranges wide and a
    six-range objective — a system whose priors are decades old and are therefore *not* chosen
    here. What this work package adds is the clock: on daily bars the round trip is a small
    fraction of a typical two-range objective, which is exactly what an hourly book cannot say.
    """

    id = "edge08_quality_breakout_daily"
    timeframe = TIMEFRAME_QUALITY
    context_timeframe = None

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(params if params is not None else dict(DECLARED_PARAMS[self.id]))

    def _build_state(self, bars: list[OHLCVBar]) -> dict[str, Any]:
        closes = [b.close for b in bars]
        return {
            "trend": ema(closes, int(self.params["trend_ema"])),
            "exit": ema(closes, int(self.params["exit_ema"])),
        }

    def on_bar(
        self, bars: list[OHLCVBar], i: int, context: ContextSeries | None, plane: CostPlane
    ) -> Outcome:
        p = self.params
        state = self._state(bars)
        close = bars[i].close
        decision_ts = bars[i].ts + BAR_MS[self.timeframe]
        trend = state["trend"][i]
        a = atr(bars, i, int(p["atr_period"]))
        level = prior_extreme(bars, i, int(p["breakout_lookback"]), want_high=True)
        if trend is None or a is None or level is None or a <= 0:
            self.warmup_bars += 1
            return None
        self.bars_evaluated += 1
        if close <= level:
            return None  # no breakout: nothing considered
        if close <= trend:
            return self.refuse(
                i,
                decision_ts,
                "trend_filter_fail",
                trend_ema=trend,
                trend=trend_label(close, trend),
            )
        stop = close - float(p["stop_atr"]) * a
        objective = close + float(p["target_atr"]) * a
        numbers, refusal = self.cost_gate(
            i=i,
            decision_ts=decision_ts,
            close=close,
            objective=objective,
            stop_distance=close - stop,
            plane=plane,
            min_rr=float(p["min_rr"]),
        )
        if refusal is not None:
            return refusal
        assert numbers is not None
        return CandidateSignal(
            candidate=self.id,
            symbol="",
            bar_index=i,
            decision_ts=decision_ts,
            decision_timeframe=self.timeframe,
            entry_reference=close,
            direction="LONG",
            stop=stop,
            targets=(objective,),
            invalidations=("close_below_exit_ema",),
            risk_reward=numbers["risk_reward"],
            expected_gross_bps=numbers["expected_gross_bps"],
            expected_cost_bps=numbers["expected_cost_bps"],
            expected_net_bps=numbers["expected_net_bps"],
            regime=trend_label(close, trend),
            evidence={
                "breakout_level": level,
                "trend_ema": trend,
                "atr": a,
                "stop_atr": float(p["stop_atr"]),
                "target_atr": float(p["target_atr"]),
            },
            trailing_atr=float(p["trail_atr"]),
            trailing_atr_value=a,
            exit_ema_period=int(p["exit_ema"]),
        )


class QualityPullbackDaily(_Base):
    """Q-2: buy a shallower price than the uptrend's own average, on a daily clock.

    The trend is established by two EMAs (50 above 200) and the entry is taken when the close has
    slipped at least half an average true range below the 20-day EMA — the entry is *cheaper* than
    the trend, not stronger than it, which is the opposite bet to Q-1 and the reason both are
    registered.
    """

    id = "edge08_quality_pullback_daily"
    timeframe = TIMEFRAME_QUALITY
    context_timeframe = None

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(params if params is not None else dict(DECLARED_PARAMS[self.id]))

    def _build_state(self, bars: list[OHLCVBar]) -> dict[str, Any]:
        closes = [b.close for b in bars]
        return {
            "fast": ema(closes, int(self.params["trend_fast"])),
            "slow": ema(closes, int(self.params["trend_slow"])),
            "pullback": ema(closes, int(self.params["pullback_ema"])),
            "exit": ema(closes, int(self.params["exit_ema"])),
        }

    def on_bar(
        self, bars: list[OHLCVBar], i: int, context: ContextSeries | None, plane: CostPlane
    ) -> Outcome:
        p = self.params
        state = self._state(bars)
        close = bars[i].close
        decision_ts = bars[i].ts + BAR_MS[self.timeframe]
        fast, slow, pullback = state["fast"][i], state["slow"][i], state["pullback"][i]
        a = atr(bars, i, int(p["atr_period"]))
        if fast is None or slow is None or pullback is None or a is None or a <= 0:
            self.warmup_bars += 1
            return None
        distance = pullback - close
        if distance < float(p["entry_distance_atr"]) * a:
            return None  # not pulled back: nothing considered, and nothing to count as a refusal
        self.bars_evaluated += 1
        if not (fast > slow):
            return self.refuse(
                i, decision_ts, "trend_filter_fail", trend_fast=fast, trend=trend_label(fast, slow)
            )
        stop = close - float(p["stop_atr"]) * a
        objective = close + float(p["target_atr"]) * a
        numbers, refusal = self.cost_gate(
            i=i,
            decision_ts=decision_ts,
            close=close,
            objective=objective,
            stop_distance=close - stop,
            plane=plane,
            min_rr=float(p["min_rr"]),
        )
        if refusal is not None:
            return refusal
        assert numbers is not None
        return CandidateSignal(
            candidate=self.id,
            symbol="",
            bar_index=i,
            decision_ts=decision_ts,
            decision_timeframe=self.timeframe,
            entry_reference=close,
            direction="LONG",
            stop=stop,
            targets=(objective,),
            invalidations=("close_below_exit_ema",),
            risk_reward=numbers["risk_reward"],
            expected_gross_bps=numbers["expected_gross_bps"],
            expected_cost_bps=numbers["expected_cost_bps"],
            expected_net_bps=numbers["expected_net_bps"],
            regime=trend_label(fast, slow),
            evidence={
                "pullback_ema": pullback,
                "distance_atr": distance / a,
                "atr": a,
                "stop_atr": float(p["stop_atr"]),
                "target_atr": float(p["target_atr"]),
            },
            trailing_atr=float(p["trail_atr"]),
            trailing_atr_value=a,
            exit_ema_period=int(p["exit_ema"]),
        )


class QualityReversionDaily(_Base):
    """Q-3: buy a three-range dislocation from the 20-day mean, in a range-bound tape.

    The regime filter is a *declared* one: the 50- and 200-day EMAs must be within one per cent of
    each other, so the book is not buying dips inside a downtrend. The objective is the 20-day
    mean itself and the entry is required to be at least three average true ranges below it, so the
    registered reward/risk is satisfiable by construction *and* the cost gate still decides, setup
    by setup, whether the trip to the mean is worth paying for.
    """

    id = "edge08_quality_reversion_daily"
    timeframe = TIMEFRAME_QUALITY
    context_timeframe = None

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(params if params is not None else dict(DECLARED_PARAMS[self.id]))

    def _build_state(self, bars: list[OHLCVBar]) -> dict[str, Any]:
        closes = [b.close for b in bars]
        return {
            "fast": ema(closes, int(self.params["regime_ema_fast"])),
            "slow": ema(closes, int(self.params["regime_ema_slow"])),
        }

    def on_bar(
        self, bars: list[OHLCVBar], i: int, context: ContextSeries | None, plane: CostPlane
    ) -> Outcome:
        p = self.params
        state = self._state(bars)
        close = bars[i].close
        decision_ts = bars[i].ts + BAR_MS[self.timeframe]
        fast, slow = state["fast"][i], state["slow"][i]
        mean = _rolling_mean([b.close for b in bars], i, int(p["mean_period"]))
        a = atr(bars, i, int(p["atr_period"]))
        if fast is None or slow is None or mean is None or a is None or a <= 0 or close <= 0:
            self.warmup_bars += 1
            return None
        stretch = (mean - close) / a
        if stretch < float(p["stretch_atr"]):
            return None  # not dislocated enough: nothing considered, nothing to count
        self.bars_evaluated += 1
        gap_pct = abs(fast - slow) / close * 100.0
        if gap_pct > float(p["regime_max_gap_pct"]):
            return self.refuse(
                i,
                decision_ts,
                "regime_filter_fail",
                regime_gap_pct=round(gap_pct, 4),
                stretch_atr=round(stretch, 4),
                trend=trend_label(fast, slow),
            )
        stop = close - float(p["stop_atr"]) * a
        # The target is the band's own centre: the trade is a bet on the mean, and the cost gate
        # is what refuses it when the mean sits too close to the entry to pay for the trip.
        numbers, refusal = self.cost_gate(
            i=i,
            decision_ts=decision_ts,
            close=close,
            objective=mean,
            stop_distance=close - stop,
            plane=plane,
            min_rr=float(p["min_rr"]),
        )
        if refusal is not None:
            return refusal
        assert numbers is not None
        return CandidateSignal(
            candidate=self.id,
            symbol="",
            bar_index=i,
            decision_ts=decision_ts,
            decision_timeframe=self.timeframe,
            entry_reference=close,
            direction="LONG",
            stop=stop,
            targets=(mean,),
            invalidations=(),
            risk_reward=numbers["risk_reward"],
            expected_gross_bps=numbers["expected_gross_bps"],
            expected_cost_bps=numbers["expected_cost_bps"],
            expected_net_bps=numbers["expected_net_bps"],
            regime="SIDEWAYS",
            evidence={
                "mean": mean,
                "stretch_atr": stretch,
                "atr": a,
                "stop_atr": float(p["stop_atr"]),
            },
        )


class ActiveDayBreak(_Base):
    """A-1: break the prior day's high on the hour, then hold for days.

    A 24-hour breakout above a 200-hour mean, with a thrust requirement (the bar itself must
    travel at least half an average true range) so that a drift through the level is not counted
    as momentum. The objective is four ranges against a two-range stop, and the trailing stop is
    what lets a runner live long enough for the hold to be measured in days rather than hours.
    """

    id = "edge08_active_daybreak_1h"
    timeframe = TIMEFRAME_ACTIVE
    context_timeframe = None

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(params if params is not None else dict(DECLARED_PARAMS[self.id]))

    def _build_state(self, bars: list[OHLCVBar]) -> dict[str, Any]:
        closes = [b.close for b in bars]
        return {
            "trend": ema(closes, int(self.params["trend_ema"])),
            "exit": ema(closes, int(self.params["exit_ema"])),
        }

    def on_bar(
        self, bars: list[OHLCVBar], i: int, context: ContextSeries | None, plane: CostPlane
    ) -> Outcome:
        p = self.params
        state = self._state(bars)
        bar = bars[i]
        close = bar.close
        decision_ts = bar.ts + BAR_MS[self.timeframe]
        trend = state["trend"][i]
        a = atr(bars, i, int(p["atr_period"]))
        level = prior_extreme(bars, i, int(p["breakout_lookback"]), want_high=True)
        if trend is None or a is None or level is None or a <= 0:
            self.warmup_bars += 1
            return None
        self.bars_evaluated += 1
        if close <= level:
            return None  # no breakout: nothing considered
        if close <= trend:
            return self.refuse(
                i,
                decision_ts,
                "trend_filter_fail",
                trend_ema=trend,
                trend=trend_label(close, trend),
            )
        thrust = (close - bar.open) / a
        if thrust < float(p["thrust_atr"]):
            return self.refuse(i, decision_ts, "thrust_filter_fail", thrust_atr=round(thrust, 4))
        stop = close - float(p["stop_atr"]) * a
        objective = close + float(p["target_atr"]) * a
        numbers, refusal = self.cost_gate(
            i=i,
            decision_ts=decision_ts,
            close=close,
            objective=objective,
            stop_distance=close - stop,
            plane=plane,
            min_rr=float(p["min_rr"]),
        )
        if refusal is not None:
            return refusal
        assert numbers is not None
        return CandidateSignal(
            candidate=self.id,
            symbol="",
            bar_index=i,
            decision_ts=decision_ts,
            decision_timeframe=self.timeframe,
            entry_reference=close,
            direction="LONG",
            stop=stop,
            targets=(objective,),
            invalidations=("close_below_exit_ema",),
            risk_reward=numbers["risk_reward"],
            expected_gross_bps=numbers["expected_gross_bps"],
            expected_cost_bps=numbers["expected_cost_bps"],
            expected_net_bps=numbers["expected_net_bps"],
            regime=trend_label(close, trend),
            evidence={
                "breakout_level": level,
                "trend_ema": trend,
                "atr": a,
                "thrust_atr": thrust,
                "hold": "days: a trailing stop plus a 50-hour EMA exit set the life of the trade",
            },
            trailing_atr=float(p["trail_atr"]),
            trailing_atr_value=a,
            exit_ema_period=int(p["exit_ema"]),
        )


class ActiveStretchRevert(_Base):
    """A-2: buy a two-and-a-half-range dislocation below the two-day mean, target the mean.

    The mirror image of A-1 on the same clock: it wants the hour to be *wrong*, not right. The
    objective is the mean itself, which on this clock is typically one to three ranges away —
    enough to clear the round trip, and the cost gate is what decides that setup by setup.
    """

    id = "edge08_active_stretch_revert_1h"
    timeframe = TIMEFRAME_ACTIVE
    context_timeframe = None

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(params if params is not None else dict(DECLARED_PARAMS[self.id]))

    def _build_state(self, bars: list[OHLCVBar]) -> dict[str, Any]:
        return {"mean": ema([b.close for b in bars], int(self.params["mean_ema"]))}

    def on_bar(
        self, bars: list[OHLCVBar], i: int, context: ContextSeries | None, plane: CostPlane
    ) -> Outcome:
        p = self.params
        state = self._state(bars)
        bar = bars[i]
        close = bar.close
        decision_ts = bar.ts + BAR_MS[self.timeframe]
        mean = state["mean"][i]
        a = atr(bars, i, int(p["atr_period"]))
        if mean is None or a is None or a <= 0:
            self.warmup_bars += 1
            return None
        self.bars_evaluated += 1
        if close >= mean:
            return None  # not stretched below the mean: nothing to refuse
        stretch = (mean - close) / a
        if stretch < float(p["stretch_atr"]):
            return self.refuse(i, decision_ts, "stretch_filter_fail", stretch_atr=round(stretch, 4))
        down = (bar.open - close) / a
        if down < float(p["down_bar_atr"]):
            return self.refuse(i, decision_ts, "down_bar_filter_fail", down_atr=round(down, 4))
        stop = close - float(p["stop_atr"]) * a
        numbers, refusal = self.cost_gate(
            i=i,
            decision_ts=decision_ts,
            close=close,
            objective=mean,
            stop_distance=close - stop,
            plane=plane,
            min_rr=float(p["min_rr"]),
        )
        if refusal is not None:
            return refusal
        assert numbers is not None
        return CandidateSignal(
            candidate=self.id,
            symbol="",
            bar_index=i,
            decision_ts=decision_ts,
            decision_timeframe=self.timeframe,
            entry_reference=close,
            direction="LONG",
            stop=stop,
            targets=(mean,),
            invalidations=(),
            risk_reward=numbers["risk_reward"],
            expected_gross_bps=numbers["expected_gross_bps"],
            expected_cost_bps=numbers["expected_cost_bps"],
            expected_net_bps=numbers["expected_net_bps"],
            regime=trend_label(close, mean),
            evidence={
                "mean": mean,
                "stretch_atr": stretch,
                "down_atr": down,
                "atr": a,
                "stop_atr": float(p["stop_atr"]),
            },
        )


class ActiveMultiDayRange(_Base):
    """A-3: break a three-day range that had compressed, on the hour.

    The setup asks for three things at once, which is what keeps it away from noise: the prior 72
    hours must have been *compressed* (their whole range at most six average true ranges), the
    close must break above that range, and it must be above the 200-hour mean. The hold is the
    same shape as A-1 — a wide objective and a trailing stop — so the frequency and the cost
    arithmetic of the two books can be compared directly.
    """

    id = "edge08_active_multiday_range_1h"
    timeframe = TIMEFRAME_ACTIVE
    context_timeframe = None

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(params if params is not None else dict(DECLARED_PARAMS[self.id]))

    def _build_state(self, bars: list[OHLCVBar]) -> dict[str, Any]:
        closes = [b.close for b in bars]
        return {
            "trend": ema(closes, int(self.params["trend_ema"])),
            "exit": ema(closes, int(self.params["exit_ema"])),
        }

    def on_bar(
        self, bars: list[OHLCVBar], i: int, context: ContextSeries | None, plane: CostPlane
    ) -> Outcome:
        p = self.params
        state = self._state(bars)
        close = bars[i].close
        decision_ts = bars[i].ts + BAR_MS[self.timeframe]
        lookback = int(p["range_lookback"])
        trend = state["trend"][i]
        a = atr(bars, i, int(p["atr_period"]))
        high = prior_extreme(bars, i, lookback, want_high=True)
        low = prior_extreme(bars, i, lookback, want_high=False)
        if trend is None or a is None or high is None or low is None or a <= 0:
            self.warmup_bars += 1
            return None
        self.bars_evaluated += 1
        if close <= high:
            return None  # no breakout: nothing considered
        compression = (high - low) / a
        if compression > float(p["compression_atr"]):
            return self.refuse(
                i, decision_ts, "range_not_compressed", range_atr=round(compression, 4)
            )
        if close <= trend:
            return self.refuse(
                i,
                decision_ts,
                "trend_filter_fail",
                trend_ema=trend,
                trend=trend_label(close, trend),
            )
        stop = close - float(p["stop_atr"]) * a
        objective = close + float(p["target_atr"]) * a
        numbers, refusal = self.cost_gate(
            i=i,
            decision_ts=decision_ts,
            close=close,
            objective=objective,
            stop_distance=close - stop,
            plane=plane,
            min_rr=float(p["min_rr"]),
        )
        if refusal is not None:
            return refusal
        assert numbers is not None
        return CandidateSignal(
            candidate=self.id,
            symbol="",
            bar_index=i,
            decision_ts=decision_ts,
            decision_timeframe=self.timeframe,
            entry_reference=close,
            direction="LONG",
            stop=stop,
            targets=(objective,),
            invalidations=("close_below_exit_ema",),
            risk_reward=numbers["risk_reward"],
            expected_gross_bps=numbers["expected_gross_bps"],
            expected_cost_bps=numbers["expected_cost_bps"],
            expected_net_bps=numbers["expected_net_bps"],
            regime=trend_label(close, trend),
            evidence={
                "range_high": high,
                "range_low": low,
                "range_atr": compression,
                "atr": a,
                "stop_atr": float(p["stop_atr"]),
                "target_atr": float(p["target_atr"]),
            },
            trailing_atr=float(p["trail_atr"]),
            trailing_atr_value=a,
            exit_ema_period=int(p["exit_ema"]),
        )


#: The six proposed books and the clock each one is walked on. ``split`` names the corpus the
#: screen reads (the frozen campaign's own split names), ``timeframe`` the bar size, and
#: ``horizon_minutes`` the holding horizon the cost plane is evaluated at — the same convention
#: the frozen campaign's ``CANDIDATE_SCOPES`` uses.
PROPOSED_ARMS: dict[str, dict[str, Any]] = {
    "edge08_quality_breakout_daily": {
        "track": "QUALITY",
        "split": "trend",
        "timeframe": "1d",
        "horizon_minutes": 4320.0,
        "answers": "Q-1: does the daily breakout pay its own round trip on a cross-section?",
    },
    "edge08_quality_pullback_daily": {
        "track": "QUALITY",
        "split": "trend",
        "timeframe": "1d",
        "horizon_minutes": 4320.0,
        "answers": "Q-2: is the cheaper entry into an uptrend the one that survives costs?",
    },
    "edge08_quality_reversion_daily": {
        "track": "QUALITY",
        "split": "trend",
        "timeframe": "1d",
        "horizon_minutes": 4320.0,
        "answers": "Q-3: does a band stretch inside a range regime pay after costs?",
    },
    "edge08_active_daybreak_1h": {
        "track": "ACTIVE",
        "split": "trend",
        "timeframe": "1h",
        "horizon_minutes": 1440.0,
        "answers": "A-1: can a day-high break held for days reach three trades a day and pay?",
    },
    "edge08_active_stretch_revert_1h": {
        "track": "ACTIVE",
        "split": "trend",
        "timeframe": "1h",
        "horizon_minutes": 1440.0,
        "answers": "A-2: is the dislocation the frequent side, and does it pay the round trip?",
    },
    "edge08_active_multiday_range_1h": {
        "track": "ACTIVE",
        "split": "trend",
        "timeframe": "1h",
        "horizon_minutes": 1440.0,
        "answers": "A-3: does a compressed three-day range pay when it breaks?",
    },
}

#: The CURRENT arms: books this project already registered and measured, carried here so the
#: cross-section reading has a baseline measured on the identical corpus, window, costs, risk
#: policy and simulator. They change no verdict — they are the comparison.
CURRENT_ARMS: dict[str, dict[str, Any]] = {
    "edge_trend_01_4h": {
        "track": "CURRENT",
        "source": "edge01.candidates",
        "timeframe": "4h",
        "horizon_minutes": 1440.0,
        "already": "the frozen WP-EDGE-01 ruleset: 4h trend with a 3xATR trailing exit",
    },
    "edge06_trend_fixed": {
        "track": "CURRENT",
        "source": "edge06.families",
        "timeframe": "4h",
        "horizon_minutes": 1440.0,
        "already": "WP-EDGE-06's fixed 3xATR target, REJECT on WP-EDGE-07's unread window",
    },
    "edge07_active_thrust": {
        "track": "CURRENT",
        "source": "edge07.active",
        "timeframe": "1h",
        "horizon_minutes": 1440.0,
        "already": "WP-EDGE-07's ACTIVE thrust book, REJECT_NO_GROSS_EDGE on the known universe",
    },
}


def build_proposed(universe: dict[str, list[OHLCVBar]]) -> dict[str, _Base]:
    """One instance per proposed book, constructed with the registered parameters."""
    del universe  # no proposed book needs the cross-sectional ranking; declared for symmetry
    return {
        "edge08_quality_breakout_daily": QualityBreakoutDaily(),
        "edge08_quality_pullback_daily": QualityPullbackDaily(),
        "edge08_quality_reversion_daily": QualityReversionDaily(),
        "edge08_active_daybreak_1h": ActiveDayBreak(),
        "edge08_active_stretch_revert_1h": ActiveStretchRevert(),
        "edge08_active_multiday_range_1h": ActiveMultiDayRange(),
    }


def build_current(universe: dict[str, list[OHLCVBar]]) -> dict[str, _Base]:
    """The frozen books, built by their own modules so no copy of them lives here."""
    families = build_families(universe)
    active = build_active_books()
    from trading_bot.research.edge01.candidates import build_candidates

    frozen = build_candidates()
    return {
        "edge_trend_01_4h": frozen["edge_trend_01_4h"],
        "edge06_trend_fixed": families["edge06_trend_fixed"],
        "edge07_active_thrust": active["edge07_active_thrust"],
    }
