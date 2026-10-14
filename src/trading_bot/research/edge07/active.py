"""WP-EDGE-07 Track C — two ACTIVE multi-asset books, registered before they were measured.

The frozen low-frequency trend book keeps its own module and is untouched. This one is about the
mission's *frequency* question: a multi-asset book on BTC, ETH and SOL that aims at three or more
trades a day, where net expectancy comes before frequency and nothing is forced to make the
count.

Three rules, and they are the reason this file is short:

* **no size, no risk change** — a signal carries a stop and a target, ``config/risk.yaml``
  decides the quantity, and no candidate may relax a limit or add a cooldown;
* **the cost gate is global** — every candidate goes through ``_Base.cost_gate`` with a declared
  ``cost_margin``, so a setup whose own objective does not clear 1.25× the round-trip cost is
  refused *by the instrument*, before anybody looks at a result. At a one-hour horizon that cost
  is 23.79 bps per trade (``COST_MODEL_V3``, ``BINANCE_SPOT_STANDARD_TAKER``);
* **registered parameters** — ``DECLARED_PARAMS`` is the machine-readable copy of the two
  hypotheses, and it is what each candidate is constructed with, so the document and the run
  cannot drift apart.

Both books are long only, like every other lane in this project: this is spot, and a fade is a
purchase of a stretched move, not a short of a rally.
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
from trading_bot.research.edge01.data import OHLCVBar
from trading_bot.research.edge01.features import atr, ema, prior_extreme, trend_label

__all__ = [
    "DECLARED_PARAMS",
    "FREQUENCY_TARGET_PER_DAY",
    "TIMEFRAME",
    "ActiveStretchFade",
    "ActiveThrust",
    "build_active_books",
]

#: The mission's frequency aim, declared so a candidate that misses it is reported as missing it
#: rather than quietly passing a gate about money alone.
FREQUENCY_TARGET_PER_DAY = 3.0

TIMEFRAME = "1h"

#: The registration, in machine-readable form.
DECLARED_PARAMS: dict[str, dict[str, Any]] = {
    "edge07_active_thrust": {
        "ema_period": 48,
        "breakout_lookback": 12,
        "atr_period": 14,
        "thrust_atr": 0.5,
        "stop_atr": 1.0,
        "target_atr": 1.5,
        "min_rr": 1.5,
        "cost_margin": 1.25,
    },
    "edge07_active_fade": {
        "ema_period": 24,
        "atr_period": 14,
        "stretch_atr": 2.0,
        "down_bar_atr": 0.75,
        "stop_atr": 1.0,
        "min_rr": 0.5,
        "cost_margin": 1.25,
    },
}


class ActiveThrust(_Base):
    """A-1: half a day of range broken with a real thrust, above a two-day mean.

    The setup is deliberately cheap to hold for a few hours: a 12-bar (half-day) breakout, an
    EMA(48) (two-day) agreement filter, and a *thrust* requirement — the bar itself must travel
    at least half an ATR — so that a drift through the level does not count as momentum. The
    objective is 1.5 ATR against a 1 ATR stop, which is what the cost gate then checks against
    23.79 bps of round-trip cost.
    """

    id = "edge07_active_thrust"
    timeframe = TIMEFRAME
    context_timeframe = None

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(params if params is not None else dict(DECLARED_PARAMS[self.id]))

    def _build_state(self, bars: list[OHLCVBar]) -> dict[str, Any]:
        return {"ema": ema([b.close for b in bars], int(self.params["ema_period"]))}

    def on_bar(
        self, bars: list[OHLCVBar], i: int, context: ContextSeries | None, plane: CostPlane
    ) -> Outcome:
        p = self.params
        state = self._state(bars)
        mean = state["ema"][i]
        a = atr(bars, i, int(p["atr_period"]))
        level = prior_extreme(bars, i, int(p["breakout_lookback"]), want_high=True)
        if mean is None or a is None or level is None or a <= 0:
            self.warmup_bars += 1
            return None
        self.bars_evaluated += 1
        bar = bars[i]
        close = bar.close
        decision_ts = bar.ts + 3_600_000
        if close <= level:
            return None  # no breakout: nothing to refuse
        if close <= mean:
            return self.refuse(
                i, decision_ts, "trend_filter_fail", ema=mean, trend=trend_label(close, mean)
            )
        thrust = (close - bar.open) / a
        if thrust < float(p["thrust_atr"]):
            return self.refuse(
                i, decision_ts, "thrust_filter_fail", thrust_atr=round(thrust, 4)
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
            invalidations=(),
            risk_reward=numbers["risk_reward"],
            expected_gross_bps=numbers["expected_gross_bps"],
            expected_cost_bps=numbers["expected_cost_bps"],
            expected_net_bps=numbers["expected_net_bps"],
            regime=trend_label(close, mean),
            evidence={
                "ema": mean,
                "atr": a,
                "breakout_level": level,
                "thrust_atr": thrust,
                "target_atr": float(p["target_atr"]),
                "stop_atr": float(p["stop_atr"]),
            },
        )


class ActiveStretchFade(_Base):
    """A-2: buy a violent down bar that has stretched two ATRs below a one-day mean.

    The entry asks for two things that must both be true: the close is at least 2 ATR below the
    EMA(24), and the bar itself fell at least 0.75 ATR. The objective is the mean itself, which
    the cost gate then requires to be at least 1.25 ATR away — so the setup only trades when the
    stretch is wide enough that the mean is a target worth paying 23.79 bps to reach.
    """

    id = "edge07_active_fade"
    timeframe = TIMEFRAME
    context_timeframe = None

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(params if params is not None else dict(DECLARED_PARAMS[self.id]))

    def _build_state(self, bars: list[OHLCVBar]) -> dict[str, Any]:
        return {"ema": ema([b.close for b in bars], int(self.params["ema_period"]))}

    def on_bar(
        self, bars: list[OHLCVBar], i: int, context: ContextSeries | None, plane: CostPlane
    ) -> Outcome:
        p = self.params
        state = self._state(bars)
        mean = state["ema"][i]
        a = atr(bars, i, int(p["atr_period"]))
        if mean is None or a is None or a <= 0:
            self.warmup_bars += 1
            return None
        self.bars_evaluated += 1
        bar = bars[i]
        close = bar.close
        decision_ts = bar.ts + 3_600_000
        if close >= mean:
            return None  # not stretched below the mean: nothing to refuse
        if (mean - close) / a < float(p["stretch_atr"]):
            return self.refuse(
                i,
                decision_ts,
                "stretch_filter_fail",
                stretch_atr=round((mean - close) / a, 4),
            )
        down = (bar.open - close) / a
        if down < float(p["down_bar_atr"]):
            return self.refuse(i, decision_ts, "down_bar_filter_fail", down_atr=round(down, 4))
        stop = close - float(p["stop_atr"]) * a
        objective = mean
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
            invalidations=(),
            risk_reward=numbers["risk_reward"],
            expected_gross_bps=numbers["expected_gross_bps"],
            expected_cost_bps=numbers["expected_cost_bps"],
            expected_net_bps=numbers["expected_net_bps"],
            regime=trend_label(close, mean),
            evidence={
                "ema": mean,
                "atr": a,
                "stretch_atr": (mean - close) / a,
                "down_atr": down,
                "stop_atr": float(p["stop_atr"]),
            },
        )


def build_active_books() -> dict[str, _Base]:
    """One instance per registered candidate, constructed with the registered parameters."""
    return {
        "edge07_active_thrust": ActiveThrust(),
        "edge07_active_fade": ActiveStretchFade(),
    }
