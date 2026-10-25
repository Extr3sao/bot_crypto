"""EDGE-01 candidates — three deterministic rulesets, frozen before any result.

`FROZEN_PARAMS` is written down *before* the campaign runs and hashed into
``PARAMS_HASH`` so the report can prove the numbers were not adjusted after
seeing the outcome. Nothing here reads the future: every decision is taken at
the close of bar ``i`` using bars ``<= i``, and the simulator fills at the open
of ``i + 1``.

The three candidates share one contract:

* ``EDGE-INTRA-01``  — 15m breakout of a confirmed resistance with a 1h trend
  filter, a volume expansion filter and a measured-move objective.
  ``use_trend_filter=False`` is the pre-registered H1 ablation that isolates
  how much of the intraday funnel the 1h gate, not the breakout, decides;
* ``EDGE-INTRA-02``  — the SAME breakout, then a retest inside the broken level
  plus a confirmed bullish three-candle imbalance (FVG). ``require_fvg=False``
  is the pre-registered ablation that isolates what the FVG contributes;
* ``EDGE-TREND-01``  — 4h/1d trend following: EMA50 > EMA200, price above
  EMA200, breakout of the prior 20-bar extreme, 3xATR trailing stop, EMA50
  invalidation exit.

Every refusal is NAMED. "No trade" is a result: the report counts refusals per
reason so a candidate that never fires is explained rather than hidden.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from .costs import CostPlane
from .data import BAR_MS, OHLCVBar
from .features import (
    FVG,
    FeatureSeries,
    atr,
    build_feature_series,
    ema,
    last_closed_index,
    prior_extreme,
    trend_label,
)

__all__ = [
    "CANDIDATE_IDS",
    "FROZEN_PARAMS",
    "PARAMS_HASH",
    "CandidateSignal",
    "ContextSeries",
    "HtfState",
    "IntraBreakout",
    "IntraRetestFvg",
    "Refusal",
    "TrendFollow",
    "build_candidates",
    "build_context",
]

#: Parameters frozen before the campaign. Any change here changes PARAMS_HASH.
FROZEN_PARAMS: dict[str, dict[str, Any]] = {
    "edge_intra_01": {
        "resistance_lookback": 20,
        "atr_period": 14,
        "breakout_buffer_atr": 0.10,
        "volume_lookback": 20,
        "volume_mult": 1.20,
        "stop_atr_below_level": 0.50,
        "max_stop_atr": 2.50,
        "min_rr": 1.50,
        "cost_margin": 1.50,
        "trailing_atr": 2.00,
        "level_reset_atr": 1.00,
    },
    "edge_intra_02": {
        "resistance_lookback": 20,
        "atr_period": 14,
        "breakout_buffer_atr": 0.10,
        "volume_lookback": 20,
        "volume_mult": 1.20,
        "retest_window_bars": 8,
        "retest_tolerance_atr": 0.25,
        "stop_buffer_atr": 0.25,
        "max_stop_atr": 3.00,
        "min_rr": 1.50,
        "cost_margin": 1.50,
        "trailing_atr": 2.00,
        "require_fvg": True,
        "fvg_max_age_bars": 1,
        "level_reset_atr": 1.00,
    },
    "edge_trend_01": {
        "ema_fast": 50,
        "ema_slow": 200,
        "breakout_lookback": 20,
        "atr_period": 14,
        "trailing_atr": 3.00,
        "exit_ema": 50,
        "cost_margin": 1.50,
    },
}


def _params_hash() -> str:
    payload = json.dumps(FROZEN_PARAMS, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


PARAMS_HASH = _params_hash()

CANDIDATE_IDS: tuple[str, ...] = ("edge_intra_01", "edge_intra_02", "edge_trend_01")


@dataclass(frozen=True, slots=True)
class HtfState:
    """What the higher timeframe had CLOSED by the decision instant."""

    index: int
    close: float | None
    ema_fast: float | None
    ema_slow: float | None
    trend: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "close": self.close,
            "ema_fast": self.ema_fast,
            "ema_slow": self.ema_slow,
            "trend": self.trend,
        }


@dataclass(frozen=True, slots=True)
class ContextSeries:
    """A higher timeframe's closed bars plus its EMAs, read as-of a decision."""

    timeframe: str
    bars: tuple[OHLCVBar, ...]
    ema_fast: tuple[float | None, ...]
    ema_slow: tuple[float | None, ...]

    def state_at(self, decision_ts: int) -> HtfState:
        # The context bar's own duration is passed in: a 1h bar opened at T closes
        # at T + 1h and cannot be read at T + 15m (DEF-EDGE01-06).
        idx = last_closed_index(
            list(self.bars), decision_ts, span_ms=BAR_MS.get(self.timeframe, 0)
        )
        if idx < 0:
            return HtfState(-1, None, None, None, "UNKNOWN")
        return HtfState(
            index=idx,
            close=self.bars[idx].close,
            ema_fast=self.ema_fast[idx],
            ema_slow=self.ema_slow[idx],
            trend=trend_label(self.ema_fast[idx], self.ema_slow[idx]),
        )


def build_context(bars: list[OHLCVBar], *, timeframe: str, fast: int, slow: int) -> ContextSeries:
    closes = [b.close for b in bars]
    return ContextSeries(
        timeframe=timeframe,
        bars=tuple(bars),
        ema_fast=tuple(ema(closes, fast)),
        ema_slow=tuple(ema(closes, slow)),
    )


@dataclass(frozen=True, slots=True)
class CandidateSignal:
    """A proposal the simulator may execute. Never carries a size (risk sizes it).

    ``entry_limit`` and ``limit_expiry_bars`` describe a *planned execution*, not a
    change of rules: when ``entry_limit`` is set the signal asks for a resting
    limit buy at that price, live for ``limit_expiry_bars`` bars of its own clock,
    and the simulator decides whether it ever fills. Both default to ``None``, so
    every pre-registered candidate keeps printing market intents and the frozen
    campaign is untouched; only the H6 retest variant sets them (see ``retest``).
    """

    candidate: str
    symbol: str
    bar_index: int
    decision_ts: int
    decision_timeframe: str
    entry_reference: float
    direction: str
    stop: float
    targets: tuple[float, ...]
    invalidations: tuple[str, ...]
    risk_reward: float
    expected_gross_bps: float
    expected_cost_bps: float
    expected_net_bps: float
    regime: str
    evidence: dict[str, Any] = field(default_factory=dict)
    trailing_atr: float | None = None
    trailing_atr_value: float | None = None
    exit_ema_period: int | None = None
    hard_invalidation: float | None = None
    entry_limit: float | None = None
    limit_expiry_bars: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate,
            "symbol": self.symbol,
            "bar_index": self.bar_index,
            "decision_ts": self.decision_ts,
            "decision_timeframe": self.decision_timeframe,
            "entry_reference": self.entry_reference,
            "direction": self.direction,
            "stop": self.stop,
            "targets": list(self.targets),
            "invalidations": list(self.invalidations),
            "risk_reward": round(self.risk_reward, 6),
            "expected_gross_bps": round(self.expected_gross_bps, 6),
            "expected_cost_bps": round(self.expected_cost_bps, 6),
            "expected_net_bps": round(self.expected_net_bps, 6),
            "regime": self.regime,
            "trailing_atr": self.trailing_atr,
            "exit_ema_period": self.exit_ema_period,
            "hard_invalidation": self.hard_invalidation,
            "entry_limit": self.entry_limit,
            "limit_expiry_bars": self.limit_expiry_bars,
            "evidence": self.evidence,
        }


@dataclass(frozen=True, slots=True)
class Refusal:
    """A setup that was considered and refused, with the reason spelled out."""

    candidate: str
    symbol: str
    bar_index: int
    decision_ts: int
    reason: str
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate,
            "symbol": self.symbol,
            "bar_index": self.bar_index,
            "decision_ts": self.decision_ts,
            "reason": self.reason,
            "detail": self.detail,
        }


Outcome = CandidateSignal | Refusal | None


class _Base:
    """Common bookkeeping: frozen params, warm-up counts, refusal helper."""

    id: str = ""
    timeframe: str = ""
    context_timeframe: str | None = None

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self.params: dict[str, Any] = dict(FROZEN_PARAMS[self.id] if params is None else params)
        self.bars_evaluated = 0
        self.warmup_bars = 0
        # Per-SERIES state, keyed by the identity of the bar list the caller
        # walked: one candidate object is reused across assets, and a breakout
        # pending on BTC must not expire because ETH walked a bar (nor may one
        # asset's features be read for another's prices).
        self._states: dict[int, dict[str, Any]] = {}

    def prepare(self, bars: list[OHLCVBar]) -> None:
        """Prime the per-series state for ``bars`` (idempotent)."""
        self._state(bars)

    def _state(self, bars: list[OHLCVBar]) -> dict[str, Any]:
        key = id(bars)
        state = self._states.get(key)
        if state is None:
            state = self._build_state(bars)
            self._states[key] = state
        return state

    def _build_state(self, bars: list[OHLCVBar]) -> dict[str, Any]:
        return {}

    def refuse(self, i: int, decision_ts: int, reason: str, **detail: Any) -> Refusal:
        return Refusal(self.id, "", i, decision_ts, reason, detail)

    # -- gates ------------------------------------------------------------ #
    def cost_gate(
        self,
        *,
        i: int,
        decision_ts: int,
        close: float,
        objective: float,
        stop_distance: float,
        plane: CostPlane,
        min_rr: float | None,
    ) -> tuple[dict[str, float] | None, Refusal | None]:
        """Cost-coverage gate plus, when the candidate HAS a fixed objective, an
        explicit reward/risk requirement; both name the failure.

        ``min_rr=None`` means the candidate exits on a trailing stop instead of a
        target (EDGE-TREND-01). Applying the R:R gate there would compare the
        modelled objective with the stop distance it is derived from — it can
        never be satisfied, and the candidate would be silently unable to trade
        (DEF-EDGE01-01). Such a candidate is judged by whether its modelled
        objective clears cost, which is the only thing its exit rule promises.

        Both numbers are returned even when a gate refuses, so the refusal can be
        read without re-deriving it.
        """
        if close <= 0 or stop_distance <= 0 or objective <= close:
            return None, self.refuse(i, decision_ts, "no_valid_target", objective=objective)
        gross_bps = (objective - close) / close * 10_000.0
        rr = (objective - close) / stop_distance
        cost_bps = plane.round_trip_bps
        numbers = {
            "expected_gross_bps": gross_bps,
            "expected_cost_bps": cost_bps,
            "expected_net_bps": gross_bps - cost_bps,
            "risk_reward": rr,
        }
        min_rr_effective = (
            None if min_rr is None else max(min_rr, float(self.params["cost_margin"]))
        )
        if min_rr_effective is not None and rr < min_rr_effective:
            return numbers, self.refuse(
                i,
                decision_ts,
                "rr_below_minimum",
                risk_reward=round(rr, 4),
                required_rr=min_rr_effective,
            )
        if gross_bps < cost_bps * float(self.params["cost_margin"]):
            return numbers, self.refuse(
                i,
                decision_ts,
                "reward_below_cost",
                expected_gross_bps=round(gross_bps, 4),
                cost_bps=round(cost_bps, 4),
                cost_margin=float(self.params["cost_margin"]),
            )
        return numbers, None

    def on_bar(
        self,
        bars: list[OHLCVBar],
        i: int,
        context: ContextSeries | None,
        plane: CostPlane,
    ) -> Outcome:  # pragma: no cover - interface definition
        raise NotImplementedError


class IntraBreakout(_Base):
    """EDGE-INTRA-01 — breakout of the prior 20-bar extreme, 15m with 1h filter."""

    id = "edge_intra_01"
    timeframe = "15m"
    context_timeframe = "1h"

    @property
    def use_trend_filter(self) -> bool:
        """``False`` only in the H1 ablation: the frozen ruleset minus the 1h gate.

        The key is absent from ``FROZEN_PARAMS['edge_intra_01']``, so the pre-
        registered run and ``PARAMS_HASH`` are unchanged; only the derived
        ablation passes it explicitly.
        """
        return bool(self.params.get("use_trend_filter", True))

    def _build_state(self, bars: list[OHLCVBar]) -> dict[str, Any]:
        p = self.params
        return {
            "feat": build_feature_series(
                bars,
                lookback=int(p["resistance_lookback"]),
                atr_period=int(p["atr_period"]),
                volume_lookback=int(p["volume_lookback"]),
            ),
            "level_traded": None,
        }

    def _features(self, bars: list[OHLCVBar]) -> FeatureSeries:
        feat = self._state(bars).get("feat")
        assert isinstance(feat, FeatureSeries)  # built by _build_state, keyed by the bar list
        return feat

    def on_bar(
        self, bars: list[OHLCVBar], i: int, context: ContextSeries | None, plane: CostPlane
    ) -> Outcome:
        p = self.params
        state = self._state(bars)
        feat = self._features(bars)
        level_traded = state["level_traded"]
        level = feat.resistance[i]
        a = feat.atr[i]
        if level is None or a is None:
            self.warmup_bars += 1
            return None
        self.bars_evaluated += 1
        bar = bars[i]
        close = bar.close
        decision_ts = bar.ts + BAR_MS[self.timeframe]
        if close <= level + float(p["breakout_buffer_atr"]) * a:
            return None  # no setup at all: an uneventful bar, not a refusal

        if level_traded is not None and abs(level - level_traded) <= float(
            p["level_reset_atr"]
        ) * a:
            return self.refuse(i, decision_ts, "level_already_traded", level=level)

        avg_volume = feat.volume_avg[i]
        if (
            avg_volume is not None
            and avg_volume > 0
            and bar.volume < float(p["volume_mult"]) * avg_volume
        ):
            return self.refuse(
                i,
                decision_ts,
                "volume_filter_fail",
                volume=bar.volume,
                avg_volume=avg_volume,
            )

        # The 1h trend filter. The pre-registered H1 ablation
        # (``use_trend_filter=False``) removes ONLY this refusal: the higher
        # timeframe is still read so the regime LABEL stays comparable between
        # the two runs, and a context that is genuinely unavailable is still
        # refused rather than skipped.
        htf, htf_refusal = _htf_uptrend(context, decision_ts)
        if htf_refusal is not None:
            reason, detail = htf_refusal
            filtered = reason == "trend_filter_fail" and not self.use_trend_filter
            if not filtered:
                return self.refuse(i, decision_ts, reason, **detail)
        if htf is None:
            return self.refuse(i, decision_ts, "htf_unavailable", {})

        stop = level - float(p["stop_atr_below_level"]) * a
        if stop >= close:
            stop = close - 1.0 * a
        stop_distance = close - stop
        if stop_distance <= 0:
            return self.refuse(i, decision_ts, "stop_invalid", stop=stop)
        if stop_distance > float(p["max_stop_atr"]) * a:
            return self.refuse(
                i, decision_ts, "stop_too_wide", stop_distance=stop_distance, atr=a
            )

        range_low = feat.support[i]
        if range_low is None or level <= range_low:
            return self.refuse(i, decision_ts, "no_valid_target", level=level)
        objective = level + (level - range_low)

        numbers, refusal = self.cost_gate(
            i=i,
            decision_ts=decision_ts,
            close=close,
            objective=objective,
            stop_distance=stop_distance,
            plane=plane,
            min_rr=float(p["min_rr"]),
        )
        if refusal is not None:
            return refusal
        assert numbers is not None

        state["level_traded"] = level
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
            invalidations=("close_below_broken_level",),
            risk_reward=numbers["risk_reward"],
            expected_gross_bps=numbers["expected_gross_bps"],
            expected_cost_bps=numbers["expected_cost_bps"],
            expected_net_bps=numbers["expected_net_bps"],
            regime=htf.trend,
            evidence={
                "resistance": level,
                "atr": a,
                "range_low": range_low,
                "htf": None if htf is None else htf.to_dict(),
                "volume": bar.volume,
            },
            trailing_atr=float(p["trailing_atr"]),
            trailing_atr_value=a,
            hard_invalidation=level,
        )


class IntraRetestFvg(_Base):
    """EDGE-INTRA-02 — the same breakout, then a retest plus a confirmed FVG.

    ``require_fvg=False`` runs the pre-registered ablation: identical ruleset,
    identical data and costs, only the imbalance requirement removed.
    """

    id = "edge_intra_02"
    timeframe = "15m"
    context_timeframe = "1h"

    def _build_state(self, bars: list[OHLCVBar]) -> dict[str, Any]:
        p = self.params
        return {
            "feat": build_feature_series(
                bars,
                lookback=int(p["resistance_lookback"]),
                atr_period=int(p["atr_period"]),
                volume_lookback=int(p["volume_lookback"]),
                with_swings=True,
            ),
            "pending": None,
            "level_traded": None,
        }

    def _features(self, bars: list[OHLCVBar]) -> FeatureSeries:
        feat = self._state(bars).get("feat")
        assert isinstance(feat, FeatureSeries)  # built by _build_state, keyed by the bar list
        return feat

    def on_bar(
        self, bars: list[OHLCVBar], i: int, context: ContextSeries | None, plane: CostPlane
    ) -> Outcome:
        p = self.params
        state = self._state(bars)
        feat = self._features(bars)
        a = feat.atr[i]
        level = feat.resistance[i]
        if a is None or level is None:
            self.warmup_bars += 1
            return None
        self.bars_evaluated += 1
        bar = bars[i]
        decision_ts = bar.ts + BAR_MS[self.timeframe]

        pending_state = state["pending"]
        if pending_state is not None and i - int(pending_state["index"]) > int(
            p["retest_window_bars"]
        ):
            state["pending"] = None
            state["level_traded"] = float(pending_state["level"])
            return self.refuse(
                i,
                decision_ts,
                "no_retest_confirmed",
                level=pending_state["level"],
                window_bars=int(p["retest_window_bars"]),
            )

        if state["pending"] is None:
            return self._start_opportunity(bars, i, context, a, level, decision_ts)
        return self._try_retest(bars, i, context, plane, a, decision_ts)

    # -- phase 1: the breakout that opens the opportunity ------------------ #
    def _start_opportunity(
        self,
        bars: list[OHLCVBar],
        i: int,
        context: ContextSeries | None,
        a: float,
        level: float,
        decision_ts: int,
    ) -> Outcome:
        p = self.params
        bar = bars[i]
        if bar.close <= level + float(p["breakout_buffer_atr"]) * a:
            return None
        level_traded = self._state(bars)["level_traded"]
        if level_traded is not None and abs(level - level_traded) <= float(
            p["level_reset_atr"]
        ) * a:
            return self.refuse(i, decision_ts, "level_already_traded", level=level)
        avg_volume = self._features(bars).volume_avg[i]
        if (
            avg_volume is not None
            and avg_volume > 0
            and bar.volume < float(p["volume_mult"]) * avg_volume
        ):
            return self.refuse(
                i,
                decision_ts,
                "volume_filter_fail",
                volume=bar.volume,
                avg_volume=avg_volume,
            )
        htf, htf_refusal = _htf_uptrend(context, decision_ts)
        if htf_refusal is not None:
            return self.refuse(i, decision_ts, htf_refusal[0], **htf_refusal[1])
        self._state(bars)["pending"] = {
            "level": level,
            "index": i,
            "ts": decision_ts,
            "range_low": self._features(bars).support[i],
            "htf": None if htf is None else htf.to_dict(),
        }
        return None

    # -- phase 2: the retest inside the window ----------------------------- #
    def _try_retest(
        self,
        bars: list[OHLCVBar],
        i: int,
        context: ContextSeries | None,
        plane: CostPlane,
        a: float,
        decision_ts: int,
    ) -> Outcome:
        p = self.params
        state = self._state(bars)
        pending = state["pending"]
        assert pending is not None
        bar = bars[i]
        close = bar.close
        target_level = float(pending["level"])
        if bar.low > target_level + float(p["retest_tolerance_atr"]) * a:
            return None  # price never came back to the zone
        if close <= target_level:
            return self.refuse(
                i, decision_ts, "retest_not_confirmed", level=target_level, close=close
            )

        htf, htf_refusal = _htf_uptrend(context, decision_ts)
        if htf_refusal is not None:
            return self.refuse(i, decision_ts, htf_refusal[0], **htf_refusal[1])

        fvg: FVG | None = None
        if bool(p["require_fvg"]):
            candidate_fvg = self._features(bars).fvg[i]
            if candidate_fvg is None:
                return self.refuse(i, decision_ts, "no_confirmed_fvg", level=target_level)
            if i - candidate_fvg.formed_index > int(p["fvg_max_age_bars"]):
                return self.refuse(
                    i,
                    decision_ts,
                    "fvg_not_temporally_related",
                    formed_index=candidate_fvg.formed_index,
                    index=i,
                )
            if close <= candidate_fvg.bottom:
                return self.refuse(
                    i,
                    decision_ts,
                    "fvg_invalidated",
                    fvg_bottom=candidate_fvg.bottom,
                    close=close,
                )
            fvg = candidate_fvg

        stop_low = bar.low if fvg is None else min(bar.low, fvg.bottom)
        stop = stop_low - float(p["stop_buffer_atr"]) * a
        stop_distance = close - stop
        if stop_distance <= 0:
            return self.refuse(i, decision_ts, "stop_invalid", stop=stop)
        if stop_distance > float(p["max_stop_atr"]) * a:
            return self.refuse(
                i, decision_ts, "stop_too_wide", stop_distance=stop_distance, atr=a
            )

        floor = max(close + stop_distance, target_level)
        objective: float | None = None
        for _idx, swing_high in reversed(self._features(bars).confirmed_swings_before(i)):
            if swing_high > floor:
                objective = swing_high
                break
        if objective is None:
            range_low = pending.get("range_low")
            if range_low is None or target_level <= range_low:
                return self.refuse(i, decision_ts, "no_valid_target", level=target_level)
            objective = target_level + (target_level - range_low)

        numbers, refusal = self.cost_gate(
            i=i,
            decision_ts=decision_ts,
            close=close,
            objective=objective,
            stop_distance=stop_distance,
            plane=plane,
            min_rr=float(p["min_rr"]),
        )
        if refusal is not None:
            return refusal
        assert numbers is not None

        breakout_index = int(pending["index"])
        state["pending"] = None
        state["level_traded"] = target_level
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
            invalidations=("close_below_retest_level", "fvg_bottom_lost"),
            risk_reward=numbers["risk_reward"],
            expected_gross_bps=numbers["expected_gross_bps"],
            expected_cost_bps=numbers["expected_cost_bps"],
            expected_net_bps=numbers["expected_net_bps"],
            regime=htf.trend if htf is not None else "UNKNOWN",
            evidence={
                "level": target_level,
                "atr": a,
                "fvg": None if fvg is None else {"bottom": fvg.bottom, "top": fvg.top},
                "require_fvg": bool(p["require_fvg"]),
                "breakout_index": breakout_index,
                "bars_since_breakout": i - breakout_index,
                "htf": None if htf is None else htf.to_dict(),
            },
            trailing_atr=float(p["trailing_atr"]),
            trailing_atr_value=a,
            hard_invalidation=target_level,
        )


class TrendFollow(_Base):
    """EDGE-TREND-01 — 4h/1d trend following, long only, spot."""

    id = "edge_trend_01"
    timeframe = "4h"
    context_timeframe = None

    def __init__(self, profile: str = "4h", params: dict[str, Any] | None = None) -> None:
        super().__init__(params)
        self.profile = profile
        self.timeframe = profile

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
        fast = state["ema_fast"][i]
        slow = state["ema_slow"][i]
        a = atr(bars, i, int(p["atr_period"]))
        level = prior_extreme(bars, i, int(p["breakout_lookback"]), want_high=True)
        if fast is None or slow is None or a is None or level is None:
            self.warmup_bars += 1
            return None
        self.bars_evaluated += 1
        bar = bars[i]
        close = bar.close
        decision_ts = bar.ts + BAR_MS[self.timeframe]
        if close <= level:
            return None  # no breakout: nothing to refuse

        # Optional entry gate: H4's frozen ablation adds a minimum ATR/close and
        # nothing else (see ENTRY_VOLATILITY_FILTER in campaign.py). Default is
        # None, so the frozen candidate's params — and its params_hash — do not
        # move when the gate is unused.
        min_atr_pct = p.get("min_atr_pct")
        atr_pct = a / close * 100.0
        if min_atr_pct is not None and atr_pct < float(min_atr_pct):
            return self.refuse(
                i,
                decision_ts,
                "volatility_filter_fail",
                atr_pct=atr_pct,
                min_atr_pct=float(min_atr_pct),
            )
        if not (fast > slow and close > slow):
            return self.refuse(
                i,
                decision_ts,
                "trend_filter_fail",
                ema_fast=fast,
                ema_slow=slow,
                trend=trend_label(fast, slow),
            )

        stop = close - float(p["trailing_atr"]) * a
        stop_distance = close - stop
        objective = close + float(p["trailing_atr"]) * a
        # A trailing exit has no fixed target: the cost gate is applied to the
        # modelled objective (one trailing distance) and the R:R gate is not
        # applied at all (min_rr=None) — see DEF-EDGE01-01 in cost_gate.
        numbers, refusal = self.cost_gate(
            i=i,
            decision_ts=decision_ts,
            close=close,
            objective=objective,
            stop_distance=stop_distance,
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
            regime=trend_label(fast, slow),
            evidence={
                "ema_fast": fast,
                "ema_slow": slow,
                "atr": a,
                "atr_pct": atr_pct,
                "breakout_level": level,
                "profile": self.profile,
            },
            trailing_atr=float(p["trailing_atr"]),
            trailing_atr_value=a,
            exit_ema_period=int(p["exit_ema"]),
        )


def _htf_uptrend(
    context: ContextSeries | None, decision_ts: int
) -> tuple[HtfState | None, tuple[str, dict[str, Any]] | None]:
    """The 1h trend filter: only the last CLOSED 1h bar may authorise a long."""
    if context is None:
        return None, None
    state = context.state_at(decision_ts)
    if state.index < 0 or state.ema_slow is None or state.close is None:
        return None, ("context_not_available", {"decision_ts": decision_ts})
    if not (state.close > state.ema_slow and state.trend != "DOWN"):
        # The state is returned alongside the refusal so the ablation that drops
        # this gate can still label the resulting trade with the same regime.
        return state, (
            "trend_filter_fail",
            {"htf_close": state.close, "htf_ema_slow": state.ema_slow, "trend": state.trend},
        )
    return state, None


def build_candidates() -> dict[str, _Base]:
    """The pre-registered candidates plus the two pre-registered ablations.

    Both ablations are derived by override, never by editing ``FROZEN_PARAMS``:
    the frozen hash of the pre-registered rulesets stays the one written down
    before the campaign ran.
    """
    return {
        "edge_intra_01": IntraBreakout(),
        "edge_intra_01_no_trend": IntraBreakout(
            {**FROZEN_PARAMS["edge_intra_01"], "use_trend_filter": False}
        ),
        "edge_intra_02": IntraRetestFvg(),
        "edge_intra_02_no_fvg": IntraRetestFvg(
            {**FROZEN_PARAMS["edge_intra_02"], "require_fvg": False}
        ),
        "edge_trend_01_4h": TrendFollow("4h"),
        "edge_trend_01_1d": TrendFollow("1d"),
    }
