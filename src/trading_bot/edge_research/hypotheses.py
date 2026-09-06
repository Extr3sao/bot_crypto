"""EDGE-RESEARCH-002 — orthogonal edge hypotheses (pre-registered).

Six structurally distinct hypotheses (A-F), each registered BEFORE any run
with an exact config, economic rationale, pre-registered acceptance rule and
a content hash. One execution per configuration; post-hoc variants require a
new HYPOTHESIS_ID. No parameter sweeps exist in this package.

Conditioning (higher-timeframe context, volatility buckets, sessions) is
applied exclusively through pre-registered bar filters passed to the
certified R1 simulation (``evaluate_combo_with_ledger``): gates change WHEN
a signal may be traded, never prices, stops, costs or exits.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from trading_bot.market_data.types import OHLCV

FRESH_START_UTC_MS = 1787097600000  # 2026-08-19T00:00:00Z


def _config_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class Hypothesis:
    """A pre-registered hypothesis: config fixed before execution."""

    hypothesis_id: str
    economic_rationale: str
    exact_config: dict[str, Any]
    acceptance_rule: dict[str, Any]
    bar_filter: Callable[[int], bool] | None = None
    family_names: tuple[str, ...] | None = None  # None = committed universe
    config_sha256: str = ""

    def __post_init__(self) -> None:
        if not self.config_sha256:
            object.__setattr__(
                self,
                "config_sha256",
                _config_hash(
                    {
                        "hypothesis_id": self.hypothesis_id,
                        "exact_config": self.exact_config,
                        "acceptance_rule": self.acceptance_rule,
                        "family_names": self.family_names,
                        "filter": getattr(self.bar_filter, "__name__", None),
                    }
                ),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "economic_rationale": self.economic_rationale,
            "exact_config": self.exact_config,
            "pre_registered_acceptance": self.acceptance_rule,
            "config_sha256": self.config_sha256,
            "registered_before_execution": True,
        }


# ---------------------------------------------------------------------------
# PIT-safe higher-timeframe context (H-A)
# ---------------------------------------------------------------------------


def _bucket_bounds(ts: int, factor: int) -> tuple[int, int]:
    """(open_ts, close_ts) of the bucket containing 5m timestamp ``ts``."""
    span = factor * 300_000
    offset = (ts - FRESH_START_UTC_MS) // span
    open_ts = FRESH_START_UTC_MS + offset * span
    return open_ts, open_ts + span - 1


def _bucket_closes(
    candles: list[OHLCV], factor: int
) -> tuple[list[tuple[int, int]], dict[int, float]]:
    """Ascending (open_ts, close_ts) buckets + open_ts -> bucket close price.

    The close price of a bucket is the last 5m close inside it (buckets are
    built from the full series, but consumers only read buckets whose close
    time is already in the past, so this is PIT-safe).
    """
    buckets: list[tuple[int, int]] = []
    closes: dict[int, float] = {}
    for candle in candles:
        open_ts, close_ts = _bucket_bounds(candle.timestamp, factor)
        if not buckets or buckets[-1][0] != open_ts:
            buckets.append((open_ts, close_ts))
        closes[open_ts] = candle.close  # last write wins = bucket close
    return buckets, closes


def htf_trend_labeler(
    candles: list[OHLCV], *, fast_factor: int, slow_factor: int
) -> Callable[[int], bool]:
    """Return a PIT-safe bar filter: trade only with the HTF direction.

    Labels are derived from CLOSED 5m history only: the 15m/1h bucket that is
    still forming at signal time is never consulted (its close is in the
    future). Direction = bucket-close-to-bucket-close return on BOTH
    horizons.
    """
    fast_buckets, fast_close = _bucket_closes(candles, fast_factor)
    slow_buckets, slow_close = _bucket_closes(candles, slow_factor)

    def _last_two_closed(
        buckets: list[tuple[int, int]], ts: int
    ) -> tuple[int, int] | None:
        closed = [open_ts for open_ts, close_ts in buckets if close_ts <= ts]
        if len(closed) < 2:
            return None
        return closed[-2], closed[-1]

    def filter_fn(ts: int) -> bool:
        fast_pair = _last_two_closed(fast_buckets, ts)
        slow_pair = _last_two_closed(slow_buckets, ts)
        if fast_pair is None or slow_pair is None:
            return False
        f_prev, f_last = fast_pair
        s_prev, s_last = slow_pair
        return (
            fast_close[f_last] > fast_close[f_prev]
            and slow_close[s_last] > slow_close[s_prev]
        )

    return filter_fn


def htf_pullback_labeler(
    candles: list[OHLCV], *, factor: int, want: str
) -> Callable[[int], bool]:
    """H-D gate: last CLOSED ``factor``-bar bucket return has sign ``want``.

    For LONG entries the gate demands a downward 15m bucket (pullback);
    for SHORT entries an upward one. PIT: only fully closed buckets.
    """
    buckets, closes = _bucket_closes(candles, factor)

    def filter_fn(ts: int) -> bool:
        closed = [open_ts for open_ts, close_ts in buckets if close_ts <= ts]
        if len(closed) < 2:
            return False
        prev_ts, last_ts = closed[-2], closed[-1]
        went_down = closes[last_ts] < closes[prev_ts]
        return went_down if want == "down" else not went_down

    return filter_fn


# ---------------------------------------------------------------------------
# H-B: volatility buckets (ex-ante terciles over the discovery window)
# ---------------------------------------------------------------------------


def atr_labeler(
    candles: list[OHLCV], *, period: int, low_q: float, high_q: float
) -> Callable[[int], bool]:
    """Trade only in the pre-registered mid volatility bucket.

    ATR% is computed on closed bars up to each timestamp (PIT). Bucket
    boundaries are quantiles of the ATR% distribution over the DISCOVERY
    window — fixed ex-ante as buckets, not optimized thresholds.
    """
    # ATR% series per bar (uses bar data up to and including itself, which is
    # then consumed as a gate on that same bar's signal -> entry is t+1, so
    # no lookahead: the ATR value exists before the entry price).
    trs: list[float] = []
    atr_pct_at: dict[int, float] = {}
    prev_close: float | None = None
    for candle in candles:
        tr = (
            candle.high - candle.low
            if prev_close is None
            else max(
                candle.high - candle.low,
                abs(candle.high - prev_close),
                abs(candle.low - prev_close),
            )
        )
        trs.append(tr)
        window = trs[-period:]
        atr = sum(window) / len(window)
        atr_pct_at[candle.timestamp] = atr / candle.close
        prev_close = candle.close

    ordered = sorted(atr_pct_at.values())
    n = len(ordered)
    low_cut = ordered[int(low_q * n)]
    high_cut = ordered[int(high_q * n)]

    def filter_fn(ts: int) -> bool:
        v = atr_pct_at.get(ts)
        return v is not None and low_cut <= v <= high_cut

    return filter_fn


# ---------------------------------------------------------------------------
# H-E: cross-sectional relative strength (PIT ranks over the fixed trio)
# ---------------------------------------------------------------------------


def cross_sectional_rs_labeler(
    closes_by_symbol: dict[str, dict[int, float]], *, target: str, lookback_bars: int
) -> Callable[[int], bool]:
    """Trade ``target`` only when its lookback return ranks 1st of the trio.

    All inputs are closes at or before ``ts`` (PIT). Symbols missing data at
    a required timestamp disqualify the bar (fail-closed).
    """
    step = 300_000

    def filter_fn(ts: int) -> bool:
        past = ts - lookback_bars * step
        returns: dict[str, float] = {}
        for symbol, closes in closes_by_symbol.items():
            now_px = closes.get(ts)
            past_px = closes.get(past)
            if now_px is None or past_px is None or past_px <= 0:
                return False  # fail-closed on missing alignment
            returns[symbol] = now_px / past_px - 1.0
        if target not in returns or len(returns) < 3:
            return False
        return returns[target] == max(returns.values())

    return filter_fn


# ---------------------------------------------------------------------------
# H-F: session structure (ex-ante UTC definitions)
# ---------------------------------------------------------------------------


def session_labeler(*, start_hour_utc: int, end_hour_utc: int) -> Callable[[int], bool]:
    """Trade only inside the pre-registered UTC session window."""

    def filter_fn(ts: int) -> bool:
        hour = (ts // 3_600_000) % 24
        if start_hour_utc <= end_hour_utc:
            return start_hour_utc <= hour < end_hour_utc
        return hour >= start_hour_utc or hour < end_hour_utc

    return filter_fn


# ---------------------------------------------------------------------------
# Registry (fixed before any execution)
# ---------------------------------------------------------------------------

ACCEPTANCE_RULE = {
    "min_trades": 30,
    "min_net_expectancy_r": 0.05,
    "min_net_pf": 1.15,
    "max_regime_concentration": 0.90,
    "max_temporal_concentration": 0.50,
    "min_positive_thirds": 2,
    "min_stability_halves_positive": True,
    "require_both_halves_nonempty": True,
    "note": "identical to pre-registered R1 v2 criteria; no threshold was tuned",
}


def preregistered_hypotheses() -> tuple[Hypothesis, ...]:
    """The six sanctioned hypotheses, in registration order."""
    return (
        Hypothesis(
            hypothesis_id="H-A-MTF-CONTEXT",
            economic_rationale=(
                "5m execution filtered by 15m+1h trend alignment: higher "
                "timeframes carry the persistent directional drift that 5m "
                "noise obscures; trading only with both horizons rising "
                "conditions entries on the slower structure"
            ),
            exact_config={
                "execution_timeframe": "5m",
                "context_timeframes": ["15m", "1h"],
                "context_rule": "last two CLOSED bucket closes rising on BOTH horizons",
                "resampling": "closed-bucket only; forming bucket never consulted",
            },
            acceptance_rule=ACCEPTANCE_RULE,
            bar_filter=None,  # bound per-symbol at run time (labeler needs candles)
            family_names=None,
        ),
        Hypothesis(
            hypothesis_id="H-B-VOL-MID-BUCKET",
            economic_rationale=(
                "Extreme volatility degrades stop quality (gap risk, slippage) "
                "and dead volatility starves breakouts; the ex-ante mid ATR% "
                "tercile isolates tradeable conditions without tuning"
            ),
            exact_config={
                "atr_period_bars": 288,  # 24h of 5m bars
                "bucket": "mid tercile [q33, q66] of discovery-window ATR%",
                "quantiles": [0.33, 0.66],
            },
            acceptance_rule=ACCEPTANCE_RULE,
            bar_filter=None,
            family_names=None,
        ),
        Hypothesis(
            hypothesis_id="H-C-MEAN-REVERSION-FADE",
            economic_rationale=(
                "Short-horizon continuation strategies (momentum/trend/"
                "breakout) crowd the same signal; fading extreme 5m moves "
                "toward a mean is a structurally different return source"
            ),
            exact_config={
                "families": ["mean_reversion"],
                "directions": ["LONG", "SHORT"],
                "note": "committed MeanReversion family, unmodified parameters",
            },
            acceptance_rule=ACCEPTANCE_RULE,
            bar_filter=None,
            family_names=("mean_reversion",),
        ),
        Hypothesis(
            hypothesis_id="H-D-TREND-PULLBACK",
            economic_rationale=(
                "Breakout entry chases extended prices (poor location, stop "
                "distance); entering with the trend AFTER a pullback improves "
                "location and asymmetry without new parameters"
            ),
            exact_config={
                "families": ["trend"],
                "directions": ["LONG", "SHORT"],
                "pullback_gate": "15m bucket close below its previous value (LONG side counters chase)",
                "note": "committed Trend family; pullback expressed as a context gate",
            },
            acceptance_rule=ACCEPTANCE_RULE,
            bar_filter=None,
            family_names=("trend",),
        ),
        Hypothesis(
            hypothesis_id="H-E-CROSS-SECTIONAL-RS",
            economic_rationale=(
                "Relative strength among BTC/ETH/SOL rotates capital toward "
                "the structurally stronger asset; ranks use closed bars only "
                "(PIT), computed per bar across the fixed trio"
            ),
            exact_config={
                "universe": ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"],
                "rs_lookback_bars": 288,
                "rule": "trade symbol only if its 24h close-to-close return ranks 1st of 3",
                "directions": ["LONG"],
            },
            acceptance_rule=ACCEPTANCE_RULE,
            bar_filter=None,
            family_names=("momentum", "trend", "breakout", "ema_crossover"),
        ),
        Hypothesis(
            hypothesis_id="H-F-US-SESSION",
            economic_rationale=(
                "Crypto liquidity concentrates in the US session overlay; "
                "session conditioning is a structural time-of-day hypothesis "
                "with ex-ante boundaries (no window search)"
            ),
            exact_config={
                "session_utc": [13, 21],  # 13:00-21:00 UTC, ex-ante
                "families": None,  # committed universe
                "directions": ["LONG", "SHORT"],
            },
            acceptance_rule=ACCEPTANCE_RULE,
            bar_filter=session_labeler(start_hour_utc=13, end_hour_utc=21),
            family_names=None,
        ),
    )


def register_payload() -> dict[str, Any]:
    """Frozen registration artifact (committed BEFORE execution evidence)."""
    return {
        "schema_version": "edge-research-002-hypotheses-v1",
        "count": 6,
        "hypotheses": [h.to_dict() for h in preregistered_hypotheses()],
    }
