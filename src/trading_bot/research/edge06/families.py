"""WP-EDGE-06 Track B — three families, registered before they were run.

Each class here is one hypothesis from ``HYPOTHESES.md``, with the parameters that file
declared and nothing else. They subclass the frozen ``_Base`` from ``edge01`` on purpose:
the entry gates, the cost gate, the refusal vocabulary and the simulator's treatment of
stops, targets, trailing exits and fills are the ones the frozen campaign already used, so
a difference between a family's result and a frozen book's result is a difference of
signals, not of accounting.

Three rules this module keeps:

* **No size.** A signal carries a stop, targets and a direction; ``config/risk.yaml`` decides
  the quantity. Nothing here reaches around the risk policy.
* **No look-ahead.** Every feature is read at the closed bar ``i`` through the frozen
  ``features`` helpers, which only expose closed bars; the simulator fills at the open of
  ``i+1``.
* **Declared parameters.** ``DECLARED_PARAMS`` is the machine-readable copy of what
  ``HYPOTHESES.md`` registered, and it is what the candidate is constructed with, so the
  document and the run cannot drift apart.
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

__all__ = [
    "DECLARED_PARAMS",
    "CrossSectionalMomentum",
    "FadeExtension",
    "TrendFixedTarget",
    "build_families",
    "family_books",
]

#: The registration, in machine-readable form. Every value is a line of ``HYPOTHESES.md``.
DECLARED_PARAMS: dict[str, dict[str, Any]] = {
    "edge06_xs_momentum": {
        "relative_strength_lookback": 30,
        "trend_ema": 200,
        "atr_period": 14,
        "stop_atr": 2.0,
        "exit_ema": 100,
        "cost_margin": 1.00,
    },
    "edge06_fade_extension": {
        "ema_period": 200,
        "atr_period": 14,
        "entry_distance_atr": 2.0,
        "stop_atr": 1.5,
        "min_rr": 1.50,
        "cost_margin": 1.50,
    },
    "edge06_trend_fixed": {
        "ema_fast": 50,
        "ema_slow": 200,
        "breakout_lookback": 20,
        "atr_period": 14,
        "stop_atr": 1.0,
        "target_atr": 3.0,
        "min_rr": 2.00,
        "cost_margin": 1.50,
    },
}


class CrossSectionalMomentum(_Base):
    """H-XS — only the strongest of the declared universe may be bought.

    The universe is injected rather than fetched: the simulator walks one asset at a time and
    the ranking has to be computed from the *same* bar objects it walks, which the caller
    already holds. A refusal is only recorded when a setup actually fired and another asset
    was stronger — that is the case worth counting, and counting the other three thousand
    bars would bury it.
    """

    id = "edge06_xs_momentum"
    timeframe = "4h"
    context_timeframe = None

    def __init__(self, universe: dict[str, list[OHLCVBar]], params: dict[str, Any] | None = None):
        super().__init__(params if params is not None else dict(DECLARED_PARAMS[self.id]))
        self.universe = universe
        self._asset_by_bars: dict[int, str] = {id(bars): asset for asset, bars in universe.items()}
        self._leaders: dict[str, dict[int, bool]] = {}

    def _build_state(self, bars: list[OHLCVBar]) -> dict[str, Any]:
        closes = [b.close for b in bars]
        return {
            "trend": ema(closes, int(self.params["trend_ema"])),
            "exit": ema(closes, int(self.params["exit_ema"])),
        }

    def _leader_map(self, asset: str) -> dict[int, bool]:
        """``timestamp -> is this asset the strongest of the universe``, computed once."""
        cached = self._leaders.get(asset)
        if cached is not None:
            return cached
        lookback = int(self.params["relative_strength_lookback"])
        strength: dict[str, dict[int, float | None]] = {}
        for name, bars in self.universe.items():
            closes = [b.close for b in bars]
            strength[name] = {
                bar.ts: (
                    closes[i] / closes[i - lookback] - 1.0
                    if i >= lookback and closes[i - lookback] > 0
                    else None
                )
                for i, bar in enumerate(bars)
            }
        leaders: dict[int, bool] = {}
        for bars in self.universe.values():
            for i, bar in enumerate(bars):
                values = {
                    name: table.get(bar.ts) for name, table in strength.items()
                }
                if any(value is None for value in values.values()):
                    leaders[bar.ts] = False
                    continue
                best = max(values.values())  # type: ignore[type-var]
                leaders[bar.ts] = bool(values.get(asset) == best)
        self._leaders[asset] = leaders
        return leaders

    def on_bar(
        self, bars: list[OHLCVBar], i: int, context: ContextSeries | None, plane: CostPlane
    ) -> Outcome:
        p = self.params
        state = self._state(bars)
        close = bars[i].close
        decision_ts = bars[i].ts + BAR_MS[self.timeframe]
        trend = state["trend"][i]
        a = atr(bars, i, int(p["atr_period"]))
        level = prior_extreme(bars, i, int(p["relative_strength_lookback"]), want_high=True)
        if trend is None or a is None or level is None:
            self.warmup_bars += 1
            return None
        self.bars_evaluated += 1
        if close <= level or close <= trend:
            return None  # no breakout of the strongest-of-three range: nothing considered
        asset = self._asset_by_bars.get(id(bars))
        if asset is None:
            return self.refuse(i, decision_ts, "asset_not_in_universe")
        if not self._leader_map(asset).get(bars[i].ts, False):
            return self.refuse(
                i,
                decision_ts,
                "not_the_relative_leader",
                relative_strength_lookback=int(p["relative_strength_lookback"]),
            )
        stop = close - float(p["stop_atr"]) * a
        numbers, refusal = self.cost_gate(
            i=i,
            decision_ts=decision_ts,
            close=close,
            objective=close + 3.0 * a,
            stop_distance=close - stop,
            plane=plane,
            min_rr=None,
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
            targets=(),
            invalidations=("close_below_exit_ema",),
            risk_reward=1.0,
            expected_gross_bps=numbers["expected_gross_bps"],
            expected_cost_bps=numbers["expected_cost_bps"],
            expected_net_bps=numbers["expected_net_bps"],
            # The label a reader can use: where the price is relative to the trend EMA it had
            # to clear. Labelling every entry with one constant would make the gate's
            # "at least one profitable regime" criterion satisfiable by construction.
            regime=trend_label(close, trend),
            evidence={
                "asset": asset,
                "relative_strength": "rank 1 of the declared universe",
                "breakout_level": level,
                "trend_ema": state["trend"][i],
                "atr": a,
            },
            trailing_atr=float(p["stop_atr"]),
            trailing_atr_value=a,
            exit_ema_period=int(p["exit_ema"]),
        )


class FadeExtension(_Base):
    """H-FADE — buy the stretch down to the mean, not the break up through it."""

    id = "edge06_fade_extension"
    timeframe = "4h"
    context_timeframe = None

    def _build_state(self, bars: list[OHLCVBar]) -> dict[str, Any]:
        return {"mean": ema([b.close for b in bars], int(self.params["ema_period"]))}

    def on_bar(
        self, bars: list[OHLCVBar], i: int, context: ContextSeries | None, plane: CostPlane
    ) -> Outcome:
        p = self.params
        state = self._state(bars)
        close = bars[i].close
        decision_ts = bars[i].ts + BAR_MS[self.timeframe]
        mean = state["mean"][i]
        a = atr(bars, i, int(p["atr_period"]))
        if mean is None or a is None:
            self.warmup_bars += 1
            return None
        self.bars_evaluated += 1
        distance = mean - close
        if distance < float(p["entry_distance_atr"]) * a:
            return None  # not stretched: nothing considered
        objective = mean
        stop = close - float(p["stop_atr"]) * a
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
                "mean": mean,
                "stretch_atr": distance / a,
                "atr": a,
                "entry_distance_atr": float(p["entry_distance_atr"]),
            },
        )


class TrendFixedTarget(_Base):
    """H-TARGET — the frozen trend entry with a fixed target instead of a trailing exit."""

    id = "edge06_trend_fixed"
    timeframe = "4h"
    context_timeframe = None

    def _build_state(self, bars: list[OHLCVBar]) -> dict[str, Any]:
        closes = [b.close for b in bars]
        return {
            "ema_fast": ema(closes, int(self.params["ema_fast"])),
            "ema_slow": ema(closes, int(self.params["ema_slow"])),
        }

    def on_bar(
        self, bars: list[OHLCVBar], i: int, context: ContextSeries | None, plane: CostPlane
    ) -> Outcome:
        p = self.params
        state = self._state(bars)
        close = bars[i].close
        decision_ts = bars[i].ts + BAR_MS[self.timeframe]
        fast, slow = state["ema_fast"][i], state["ema_slow"][i]
        a = atr(bars, i, int(p["atr_period"]))
        level = prior_extreme(bars, i, int(p["breakout_lookback"]), want_high=True)
        if fast is None or slow is None or a is None or level is None:
            self.warmup_bars += 1
            return None
        self.bars_evaluated += 1
        if close <= level:
            return None
        if not (fast > slow and close > slow):
            return self.refuse(
                i,
                decision_ts,
                "trend_filter_fail",
                ema_fast=fast,
                ema_slow=slow,
                trend=trend_label(fast, slow),
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
            regime=trend_label(fast, slow),
            evidence={
                "ema_fast": fast,
                "ema_slow": slow,
                "atr": a,
                "breakout_level": level,
                "target_atr": float(p["target_atr"]),
                "stop_atr": float(p["stop_atr"]),
            },
        )


#: The books that can be run, and the split each one is read on. Declared here so the runner
#: has no hidden defaults, and so a reader can see what "the same windows" means in one place.
FAMILY_BOOKS: dict[str, dict[str, Any]] = {
    "edge06_xs_momentum": {
        "split": "trend",
        "timeframe": "4h",
        "horizon_minutes": 1440.0,
        "needs_universe": True,
        "answers": "H-XS",
    },
    "edge06_fade_extension": {
        "split": "trend",
        "timeframe": "4h",
        "horizon_minutes": 1440.0,
        "needs_universe": False,
        "answers": "H-FADE",
    },
    "edge06_trend_fixed": {
        "split": "trend",
        "timeframe": "4h",
        "horizon_minutes": 1440.0,
        "needs_universe": False,
        "answers": "H-TARGET",
    },
}


def family_books() -> dict[str, dict[str, Any]]:
    return {name: dict(scope) for name, scope in FAMILY_BOOKS.items()}


def build_families(universe: dict[str, list[OHLCVBar]]) -> dict[str, _Base]:
    """One instance per registered book, constructed with the registered parameters."""
    return {
        "edge06_xs_momentum": CrossSectionalMomentum(
            universe=universe, params=dict(DECLARED_PARAMS["edge06_xs_momentum"])
        ),
        "edge06_fade_extension": FadeExtension(
            params=dict(DECLARED_PARAMS["edge06_fade_extension"])
        ),
        "edge06_trend_fixed": TrendFixedTarget(params=dict(DECLARED_PARAMS["edge06_trend_fixed"])),
    }
