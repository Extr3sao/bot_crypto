"""WP-EDGE-015/P1-P2 — alpha families on the runtime's own data, priced per venue.

The mission of this work package is not to show that the engine runs; it is to
find out whether any *sufficiently different* hypothesis can clear its costs.
This module holds the part of that answer that must be frozen before data is
looked at: the families, their parameters, the cost model, and the thresholds
that would let a candidate be called adopted.

Three rules shape it.

1. **No renamed duplicates.** The families below are mechanically distinct —
   breakout with a volatility-regime filter, trend pullback, cross-sectional
   rotation, mean reversion conditioned on volatility *and* liquidity, and a
   maker-only hypothesis that is declared untestable rather than approximated.
   Each one is checked against the families the campaign already rejected
   (``breakout``, ``ema_crossover``, ``lead_lag``) in
   ``ALPHA_EXPERIMENT_MATRIX.csv``: a family that only re-parameterises a
   rejected one is marked ``DUPLICATE_OF_REJECTED`` instead of counted as new.
2. **Costs per venue and product, with the hypothesis labelled.** The cost model
   separates what is *known* (the published taker fee schedule), what is
   *estimated* (the audit's spread/slippage/impact at a 200 USDT stake), and what
   is a *hypothesis* of this work package (how those scale with the venue tier
   and the stake). Zero spread and zero slippage are never used to certify a
   candidate; the point of the earlier parity run was a *like-for-like engine
   comparison*, and that is not a licence to price a strategy at zero.
3. **Causal only.** Every indicator at bar *i* uses closes up to and including
   bar *i*; a decision taken on bar *i* fills at the open of bar *i+1*. Nothing
   peeks, and the fill rule is the same one the parity run fixed.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from itertools import pairwise
from statistics import median
from typing import Any

from .experiments import Bar, load_ohlcv
from .pit15 import run_family

__all__ = [
    "COST_MODEL_V15",
    "FAMILIES",
    "FROZEN_PROTOCOL",
    "ROTATION_UNIVERSE",
    "SINGLE_ASSET_FAMILIES",
    "Bar",
    "CostTerms",
    "bar_series",
    "cost_for",
    "evaluate_trades",
    "family_trades",
    "rotation_backtest",
    "round_trip_cost_bps",
    "split_index",
]

# --------------------------------------------------------------------------------------
# P2 — cost model
# --------------------------------------------------------------------------------------

#: Published taker fee, spot, VIP0, one side. KNOWN: it is on the venue's fee schedule.
FEE_BPS_PER_SIDE = 10.0

#: Anchor stake of the audit's estimated spread/slippage/impact components.
ANCHOR_STAKE_USDT = 200.0

#: One side of the quoted spread. TIER1 anchors on the recovery audit's estimated
#: 1.0 bps *round trip* for a top-two pair; the wider tiers are this work package's
#: hypothesis about thinner books, scaled by the inverse of the pair's typical depth.
HALF_SPREAD_BPS_BY_TIER: dict[str, float] = {
    "TIER1": 0.5,
    "MAJOR": 1.0,
    "ALT": 2.0,
}

#: Market-order slippage at the anchor stake, one side. TIER1 is the audit's
#: 2.2828 bps round trip halved; wider tiers carry the deeper-book penalty.
SLIPPAGE_BPS_PER_SIDE_BY_TIER: dict[str, float] = {
    "TIER1": 1.1414,
    "MAJOR": 1.6,
    "ALT": 2.4,
}

#: Impact at the anchor stake, one side; TIER1 is the audit's 0.0707 bps halved.
IMPACT_BPS_PER_SIDE_BY_TIER: dict[str, float] = {
    "TIER1": 0.0354,
    "MAJOR": 0.05,
    "ALT": 0.08,
}

SYMBOL_TIER: dict[str, str] = {
    "BTC/USDT": "TIER1",
    "BTCUSDT": "TIER1",
    "ETH/USDT": "TIER1",
    "ETHUSDT": "TIER1",
    "SOL/USDT": "MAJOR",
    "SOLUSDT": "MAJOR",
    "XRP/USDT": "MAJOR",
    "XRPUSDT": "MAJOR",
    "AAVE/USDT": "ALT",
    "AAVEUSDT": "ALT",
    "CRV/USDT": "ALT",
    "CRVUSDT": "ALT",
    "KSM/USDT": "ALT",
    "KSMUSDT": "ALT",
    "SNX/USDT": "ALT",
    "SNXUSDT": "ALT",
    "SUSHI/USDT": "ALT",
    "SUSHIUSDT": "ALT",
    "UNI/USDT": "ALT",
    "UNIUSDT": "ALT",
}


@dataclass(frozen=True)
class CostTerms:
    """One round trip's costs, one side at a time, with the provenance kept."""

    symbol: str
    venue: str
    tier: str
    stake_usdt: float
    fee_bps_per_side: float
    half_spread_bps: float
    slippage_bps_per_side: float
    impact_bps_per_side: float
    funding_bps_per_day: float
    knowledge: dict[str, str]

    @property
    def per_side_bps(self) -> float:
        return (
            self.fee_bps_per_side
            + self.half_spread_bps
            + self.slippage_bps_per_side
            + self.impact_bps_per_side
        )

    def round_trip_bps(self, multiplier: float = 1.0) -> float:
        """Both legs, with an adverse multiplier on everything but funding.

        The multiplier is how the brief's "adverse cost sensitivity" is
        implemented: 1.0 is the central model, 2.0 and 3.0 stress every traded
        component at once rather than one at a time, which is the pessimistic
        direction a candidate has to survive.
        """
        return 2.0 * self.per_side_bps * multiplier

    def to_row(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "venue": self.venue,
            "tier": self.tier,
            "stake_usdt": self.stake_usdt,
            "fee_bps_per_side": self.fee_bps_per_side,
            "half_spread_bps": self.half_spread_bps,
            "slippage_bps_per_side": self.slippage_bps_per_side,
            "impact_bps_per_side": self.impact_bps_per_side,
            "funding_bps_per_day": self.funding_bps_per_day,
            "per_side_bps": self.per_side_bps,
            "round_trip_bps": self.round_trip_bps(),
            "knowledge": self.knowledge,
        }


def cost_for(
    symbol: str, *, stake_usdt: float = ANCHOR_STAKE_USDT, venue: str = "BINANCE_SPOT"
) -> CostTerms:
    """Price a round trip in ``symbol`` at ``stake_usdt`` on ``venue``.

    Slippage grows with the square root of size (the usual square-root law) and
    impact grows linearly: a 4x stake is 2x the slippage and 4x the impact. Both
    scale with the pair's tier, and the whole thing is *declared* as a mixture of
    published fact and hypothesis rather than presented as a measurement.
    """
    tier = SYMBOL_TIER.get(symbol.upper(), "ALT")
    scale = max(stake_usdt, 1.0) / ANCHOR_STAKE_USDT
    sqrt_scale = math.sqrt(scale)
    return CostTerms(
        symbol=symbol,
        venue=venue,
        tier=tier,
        stake_usdt=stake_usdt,
        fee_bps_per_side=FEE_BPS_PER_SIDE,
        half_spread_bps=HALF_SPREAD_BPS_BY_TIER[tier],
        slippage_bps_per_side=SLIPPAGE_BPS_PER_SIDE_BY_TIER[tier] * sqrt_scale,
        impact_bps_per_side=IMPACT_BPS_PER_SIDE_BY_TIER[tier] * scale,
        funding_bps_per_day=0.0,  # spot: no funding leg, and none is invented
        knowledge={
            "fee": "KNOWN: venue taker fee schedule, VIP0, one side",
            "half_spread": "ESTIMATED: recovery audit spread, split and widened by tier",
            "slippage": "HYPOTHESIS: sqrt(size) scaling of the audit's estimate, by tier",
            "impact": "HYPOTHESIS: linear size scaling of the audit's estimate, by tier",
            "funding": "NOT_APPLICABLE: spot venue has no funding leg",
        },
    )


def round_trip_cost_bps(
    symbol: str, *, stake_usdt: float = ANCHOR_STAKE_USDT, multiplier: float = 1.0
) -> float:
    return cost_for(symbol, stake_usdt=stake_usdt).round_trip_bps(multiplier)


#: The three sensitivity levels every experiment is reported at.
COST_MULTIPLIERS: tuple[float, ...] = (1.0, 2.0, 3.0)

COST_MODEL_V15: dict[str, Any] = {
    "schema_version": "EDGE15_COST_MODEL_V1",
    "venue": "BINANCE_SPOT",
    "anchor_stake_usdt": ANCHOR_STAKE_USDT,
    "fee_bps_per_side": FEE_BPS_PER_SIDE,
    "half_spread_bps_by_tier": HALF_SPREAD_BPS_BY_TIER,
    "slippage_bps_per_side_by_tier": SLIPPAGE_BPS_PER_SIDE_BY_TIER,
    "impact_bps_per_side_by_tier": IMPACT_BPS_PER_SIDE_BY_TIER,
    "scaling": {"slippage": "sqrt(stake/anchor)", "impact": "stake/anchor"},
    "sensitivity_multipliers": list(COST_MULTIPLIERS),
    "not_used": (
        "zero spread and zero slippage: those were declared parity inputs for comparing two "
        "engines, and they are not a price at which a strategy may be certified"
    ),
    "examples": [
        cost_for(symbol).to_row() for symbol in ("BTC/USDT", "ETH/USDT", "SOL/USDT", "UNI/USDT")
    ],
}


# --------------------------------------------------------------------------------------
# indicators (causal: value at index i uses bars[i] and earlier only)
# --------------------------------------------------------------------------------------


def _sma(values: Sequence[float], span: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    running = 0.0
    for index, value in enumerate(values):
        running += value
        if index >= span:
            running -= values[index - span]
        if index >= span - 1:
            out[index] = running / span
    return out


def _stdev(values: Sequence[float], span: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    for index in range(span - 1, len(values)):
        window = values[index - span + 1 : index + 1]
        mean = sum(window) / span
        variance = sum((v - mean) ** 2 for v in window) / span
        out[index] = math.sqrt(variance)
    return out


def _ema(values: Sequence[float], span: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) < span:
        return out
    k = 2.0 / (span + 1.0)
    previous = sum(values[:span]) / span
    out[span - 1] = previous
    for index in range(span, len(values)):
        previous = values[index] * k + previous * (1.0 - k)
        out[index] = previous
    return out


def _atr(bars: Sequence[Bar], span: int) -> list[float | None]:
    true_ranges: list[float] = []
    for index, bar in enumerate(bars):
        if index == 0:
            true_ranges.append(bar.high - bar.low)
            continue
        previous_close = bars[index - 1].close
        true_ranges.append(
            max(
                bar.high - bar.low,
                abs(bar.high - previous_close),
                abs(bar.low - previous_close),
            )
        )
    return _ema(true_ranges, span)


def _rolling_max(values: Sequence[float], span: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    for index in range(span - 1, len(values)):
        out[index] = max(values[index - span + 1 : index + 1])
    return out


def _rolling_min(values: Sequence[float], span: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    for index in range(span - 1, len(values)):
        out[index] = min(values[index - span + 1 : index + 1])
    return out


def _percentile_rank(
    values: Sequence[float | None], window: int, *, buckets: int = 50
) -> list[float | None]:
    """Where today's value sits inside the trailing ``window`` of known values.

    Causal by construction: the count that produces the rank is updated *after*
    the current point is added, so it describes the window that ends at the
    current bar and never one that starts after it. Bucket bounds are fixed from
    the first full window (a past window for every later point) and values
    outside them are clamped, which trades 2%-resolution accuracy for a linear
    pass over a five-year series.
    """
    out: list[float | None] = [None] * len(values)
    points = [(index, value) for index, value in enumerate(values) if value is not None]
    if len(points) < window or window <= 1:
        return out
    low = min(value for _index, value in points[:window])
    high = max(value for _index, value in points[:window])
    if high <= low:
        return out
    width = (high - low) / buckets
    counts = [0] * buckets
    recent: list[int] = []
    for index, value in points:
        bucket = min(buckets - 1, max(0, int((value - low) / width)))
        counts[bucket] += 1
        recent.append(bucket)
        if len(recent) > window:
            counts[recent.pop(0)] -= 1
        if len(recent) == window:
            below = sum(counts[:bucket]) + 0.5 * counts[bucket]
            out[index] = below / window
    return out


# --------------------------------------------------------------------------------------
# P1 — the families
# --------------------------------------------------------------------------------------


def _real(values: Sequence[float | None]) -> list[float]:
    """An optional series as floats, with NaN standing for "not yet defined".

    NaN is the right sentinel here instead of a branch: every comparison with it
    is False, so a gate whose input has not warmed up simply does not fire, and
    the arithmetic stays type-safe without a special case per indicator.
    """
    return [value if value is not None else math.nan for value in values]


@dataclass(frozen=True)
class Family:
    """A hypothesis, its frozen parameters and what it must beat to be adopted."""

    name: str
    hypothesis: str
    parameters: dict[str, Any]
    status: str = "TESTED"
    differs_from: tuple[str, ...] = ()
    untestable_reason: str = ""
    required_evidence: str = ""


FAMILIES: tuple[Family, ...] = (
    Family(
        name="vol_regime_breakout",
        hypothesis=(
            "H: a close above the 168h high is informative only when realised volatility is "
            "in its upper-middle range — dead markets produce false breakouts and panic "
            "regimes produce reversals — so the Donchian entry is gated on the ATR percentile "
            "and on price being above the long trend."
        ),
        parameters={
            "channel_hours": 168,
            "atr_hours": 24,
            "percentile_window_hours": 720,
            "atr_percentile_min": 0.5,
            "atr_percentile_max": 0.95,
            "trail_atr_multiple": 3.0,
            "regime_ema_hours": 200,
        },
        differs_from=("breakout@5m", "ema_crossover@5m"),
    ),
    Family(
        name="trend_pullback",
        hypothesis=(
            "H: in an established uptrend, a first close back below a fast mean is a "
            "continuation entry rather than a reversal, provided the trend filter and the "
            "recovery above the fast mean are both required before entry."
        ),
        parameters={
            "trend_ema_hours": 200,
            "trend_slope_hours": 24,
            "fast_ema_hours": 20,
            "slow_ema_hours": 50,
            "atr_hours": 24,
            "stop_atr_multiple": 3.0,
        },
        differs_from=("ema_crossover@5m",),
    ),
    Family(
        name="cross_sectional_rotation",
        hypothesis=(
            "H: the relative ordering of 72h returns across a fixed liquid universe carries "
            "information that a single-asset trend rule cannot see, so holding the top-k "
            "names while the absolute trend filter is up beats holding any one of them."
        ),
        parameters={
            "lookback_hours": 72,
            "rebalance_hours": 24,
            "top_k": 2,
            "regime_ema_hours": 200,
            "universe": ["AAVEUSDT", "CRVUSDT", "KSMUSDT", "SNXUSDT", "SUSHIUSDT", "UNIUSDT"],
        },
        differs_from=("lead_lag",),
    ),
    Family(
        name="mean_reversion_vol_liq",
        hypothesis=(
            "H: a two-sigma stretch below a 48h mean reverts only when volatility is low and "
            "the bar is liquid; without those two conditions the same stretch is the start of "
            "a trend and the strategy is on the wrong side of it."
        ),
        parameters={
            "mean_hours": 48,
            "z_entry": -2.0,
            "z_exit": 0.0,
            "atr_hours": 24,
            "atr_percentile_max": 0.5,
            "percentile_window_hours": 720,
            "volume_median_hours": 168,
            "volume_multiple_min": 1.2,
            "max_hold_hours": 48,
            "atr_stop_multiple": 4.0,
        },
        differs_from=("breakout@5m", "ema_crossover@5m", "lead_lag"),
    ),
    Family(
        name="maker_only_spread_capture",
        hypothesis=(
            "H: a passive order inside the spread can be filled favourably often enough to "
            "beat the taker round trip. It is listed because the brief asks for it and it is "
            "NOT tested, because measuring it needs a fill model this repository does not "
            "have."
        ),
        parameters={"quote_offset_bps": 1.0, "inventory_hours": 4},
        status="DEFER_NO_FILL_MODEL",
        untestable_reason=(
            "no verifiable queue-position or fill-probability model exists in the tree, and "
            "without one a maker backtest reports fills it could not have obtained"
        ),
        required_evidence=(
            "a recorded order-book or trade-print source at sub-second resolution plus a "
            "queue model validated against real fills; then, and only then, a maker backtest"
        ),
    ),
)

FAMILY_BY_NAME: dict[str, Family] = {family.name: family for family in FAMILIES}

#: The universe the rotation family runs on. Fixed here so the freeze has it.
ROTATION_UNIVERSE: tuple[str, ...] = tuple(
    FAMILY_BY_NAME["cross_sectional_rotation"].parameters["universe"]
)


def bar_series(path: Any, *, limit: int | None = None) -> list[Bar]:
    bars = load_ohlcv(path)
    return bars[-limit:] if limit else bars


# --- A1: volatility-regime breakout ---------------------------------------------------


def _vol_regime_breakout(bars: Sequence[Bar], params: dict[str, Any]) -> list[dict[str, Any]]:
    """WP-EDGE-016: evaluated through the point-in-time machine (see ``pit15``).

    The WP-EDGE-015 version of this function filled every exit at the open of the
    bar whose close triggered it — a price that had already happened before the
    information existed. The rule itself is unchanged; only the fill instant moved
    to the next executable bar.
    """
    return run_family("vol_regime_breakout", bars, params)


def _vol_regime_breakout_pre_pit(
    bars: Sequence[Bar], params: dict[str, Any]
) -> list[dict[str, Any]]:
    """The pre-repair rule, kept only so the defect stays reproducible in tests."""
    closes = [b.close for b in bars]
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    channel = int(params["channel_hours"])
    # The channel is read at ``previous - 1``, i.e. over the bars *before* the bar
    # being tested: a close cannot exceed the high of its own bar, so a channel
    # that includes it can never be broken (the first version of this family
    # produced exactly zero trades for that reason).
    upper = _real(_rolling_max(highs, channel))
    lower = _real(_rolling_min(lows, channel))
    atr = _real(_atr(bars, int(params["atr_hours"])))
    atr_rank = _real(
        _percentile_rank(
            _atr(bars, int(params["atr_hours"])), int(params["percentile_window_hours"])
        )
    )
    regime = _real(_ema(closes, int(params["regime_ema_hours"])))
    rank_min = float(params["atr_percentile_min"])
    rank_max = float(params["atr_percentile_max"])
    trail = float(params["trail_atr_multiple"])
    trades: list[dict[str, Any]] = []
    entry: int | None = None
    peak = 0.0
    for index in range(1, len(bars)):
        previous = index - 1
        prior = previous - 1
        if entry is None:
            if (
                prior >= 0
                and closes[previous] > upper[prior]
                and rank_min <= atr_rank[previous] <= rank_max
                and closes[previous] > regime[previous]
            ):
                entry = index
                peak = bars[index].close
            continue
        peak = max(peak, bars[index].close)
        stopped = bars[index].close < peak - trail * atr[previous]
        broke_channel = prior >= 0 and closes[previous] < lower[prior]
        if stopped or broke_channel:
            trades.append(_round_trip(bars, entry, index, params))
            entry = None
    if entry is not None:
        trades.append(_round_trip(bars, entry, len(bars) - 1, params))
    return trades


# --- A2: trend pullback --------------------------------------------------------------


def _trend_pullback(bars: Sequence[Bar], params: dict[str, Any]) -> list[dict[str, Any]]:
    """WP-EDGE-016: the same rule, with exits filled at the next executable bar."""
    return run_family("trend_pullback", bars, params)


def _trend_pullback_pre_pit(bars: Sequence[Bar], params: dict[str, Any]) -> list[dict[str, Any]]:
    """The pre-repair rule, kept only so the defect stays reproducible in tests."""
    closes = [b.close for b in bars]
    trend = _real(_ema(closes, int(params["trend_ema_hours"])))
    fast = _real(_ema(closes, int(params["fast_ema_hours"])))
    slow = _real(_ema(closes, int(params["slow_ema_hours"])))
    atr = _real(_atr(bars, int(params["atr_hours"])))
    slope = int(params["trend_slope_hours"])
    trades: list[dict[str, Any]] = []
    entry: int | None = None
    armed = False
    for index in range(1, len(bars)):
        previous = index - 1
        trend_ok = (
            previous >= slope
            and trend[previous] > trend[previous - slope]
            and closes[previous] > trend[previous]
            and fast[previous] > slow[previous]
        )
        if entry is None:
            if not trend_ok:
                armed = False
                continue
            if closes[previous] < fast[previous]:
                armed = True  # pullback begun
                continue
            if armed and closes[previous] > fast[previous]:
                entry = index
                armed = False
            continue
        stop = closes[index] < bars[entry].open - float(params["stop_atr_multiple"]) * atr[previous]
        trend_broken = closes[previous] < slow[previous]
        if stop or trend_broken:
            trades.append(_round_trip(bars, entry, index, params))
            entry = None
    if entry is not None:
        trades.append(_round_trip(bars, entry, len(bars) - 1, params))
    return trades


# --- A4: mean reversion conditioned on volatility and liquidity -------------------------


def _mean_reversion_vol_liq(bars: Sequence[Bar], params: dict[str, Any]) -> list[dict[str, Any]]:
    """WP-EDGE-016: the same rule, with exits filled at the next executable bar."""
    return run_family("mean_reversion_vol_liq", bars, params)


def _mean_reversion_vol_liq_pre_pit(
    bars: Sequence[Bar], params: dict[str, Any]
) -> list[dict[str, Any]]:
    """The pre-repair rule, kept only so the defect stays reproducible in tests."""
    closes = [b.close for b in bars]
    volumes = [b.volume for b in bars]
    mean = _real(_sma(closes, int(params["mean_hours"])))
    deviation = _real(_stdev(closes, int(params["mean_hours"])))
    atr = _real(_atr(bars, int(params["atr_hours"])))
    atr_rank = _real(
        _percentile_rank(
            _atr(bars, int(params["atr_hours"])), int(params["percentile_window_hours"])
        )
    )
    volume_median = _real(
        [
            median(volumes[max(0, index - int(params["volume_median_hours"]) + 1) : index + 1])
            if index > 0
            else None
            for index in range(len(volumes))
        ]
    )
    trades: list[dict[str, Any]] = []
    entry: int | None = None
    for index in range(1, len(bars)):
        previous = index - 1
        z = float("nan")
        if deviation[previous] > 0:
            z = (closes[previous] - mean[previous]) / deviation[previous]
        if entry is None:
            if (
                z <= float(params["z_entry"])
                and atr_rank[previous] <= float(params["atr_percentile_max"])
                and volumes[previous]
                > float(params["volume_multiple_min"]) * volume_median[previous]
            ):
                entry = index
            continue
        held = index - entry
        exit_now = held >= int(params["max_hold_hours"])
        if not exit_now and deviation[previous] > 0:
            z_now = (closes[previous] - mean[previous]) / deviation[previous]
            exit_now = z_now >= float(params["z_exit"])
        if not exit_now:
            exit_now = (
                closes[index] < bars[entry].open - float(params["atr_stop_multiple"]) * atr[entry]
            )
        if exit_now:
            trades.append(_round_trip(bars, entry, index, params))
            entry = None
    if entry is not None:
        trades.append(_round_trip(bars, entry, len(bars) - 1, params))
    return trades


def _round_trip(
    bars: Sequence[Bar], entry: int, exit_index: int, params: dict[str, Any]
) -> dict[str, Any]:
    """Entry at the open of ``entry``, exit at the open of ``exit_index`` (causal)."""
    del params
    entry_price = bars[entry].open
    exit_price = bars[exit_index].open if exit_index > entry else bars[exit_index].close
    return {
        "entry_ts_ms": bars[entry].ts_ms,
        "exit_ts_ms": bars[exit_index].ts_ms,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "gross_bps": (exit_price / entry_price - 1.0) * 10_000.0,
        "bars_held": exit_index - entry,
        "direction": "long",
    }


# --- A3: cross-sectional rotation ------------------------------------------------------


def rotation_backtest(
    series: dict[str, list[Bar]],
    params: dict[str, Any],
    *,
    cost_multiplier: float = 1.0,
    stake_usdt: float = ANCHOR_STAKE_USDT,
) -> dict[str, Any]:
    """Long the top-k trailing performers while the absolute trend filter is up.

    One account, equal weight across the ``top_k`` names, rebalanced every
    ``rebalance_hours``. A name leaving the set is sold at the next bar's open
    and pays its own round trip; the sleeve keeps 1/k of the book so the
    comparison with the single-asset families stays a per-notional one.
    """
    lookback = int(params["lookback_hours"])
    rebalance = int(params["rebalance_hours"])
    top_k = int(params["top_k"])
    regime_span = int(params["regime_ema_hours"])
    universe = [s for s in params["universe"] if s in series]

    closes: dict[str, dict[int, float]] = {
        symbol: {bar.ts_ms: bar.close for bar in series[symbol]} for symbol in universe
    }
    opens: dict[str, dict[int, float]] = {
        symbol: {bar.ts_ms: bar.open for bar in series[symbol]} for symbol in universe
    }
    regime: dict[str, dict[int, float | None]] = {}
    for symbol in universe:
        bars = series[symbol]
        series_ema = _ema([bar.close for bar in bars], regime_span)
        regime[symbol] = {bar.ts_ms: series_ema[index] for index, bar in enumerate(bars)}

    timestamps = sorted({ts for symbol in universe for ts in closes[symbol]})
    position_of = {ts: index for index, ts in enumerate(timestamps)}
    hour_ms = 3_600_000
    sleeve = 1.0 / top_k
    held: dict[str, float] = {}  # symbol -> entry price
    cash = 1.0
    equity_curve: list[tuple[int, float]] = []
    events: list[dict[str, Any]] = []
    last_rebalance_ts: int | None = None
    lag = rebalance * hour_ms

    def next_ts(ts: int) -> int:
        index = position_of.get(ts, 0)
        return timestamps[index + 1] if index + 1 < len(timestamps) else ts

    for ts in timestamps:
        marks: dict[str, float] = {s: closes[s][ts] for s in universe if ts in closes[s]}
        # mark the book on every bar: valuation only, no decision
        marked = cash + sum(
            (marks.get(symbol, entry) / entry - 1.0) * sleeve for symbol, entry in held.items()
        )
        equity_curve.append((ts, marked))
        if last_rebalance_ts is not None and ts - last_rebalance_ts < lag:
            continue
        last_rebalance_ts = ts
        scored: list[tuple[float, str]] = []
        for symbol in universe:
            past = closes[symbol].get(ts - lookback * hour_ms)
            now = marks.get(symbol)
            ema_now = regime[symbol].get(ts)
            if past and now and ema_now is not None and now > ema_now:
                scored.append((now / past - 1.0, symbol))
        scored.sort(reverse=True)
        target = {symbol for _score, symbol in scored[:top_k]}
        for symbol in sorted(set(held) - target):
            exit_ts = next_ts(ts)
            exit_price = opens[symbol].get(exit_ts)
            if exit_price is None:
                continue
            entry_price = held.pop(symbol)
            gross = (exit_price / entry_price - 1.0) * 10_000.0
            cost = round_trip_cost_bps(symbol, stake_usdt=stake_usdt, multiplier=cost_multiplier)
            cash += sleeve * (gross - cost) / 10_000.0
            events.append(
                {
                    "action": "SELL",
                    "symbol": symbol,
                    "ts_ms": exit_ts,
                    "entry_ts_ms": None,
                    "price": exit_price,
                    "entry_price": entry_price,
                    "gross_bps": gross,
                    "cost_bps": cost,
                    "net_bps": gross - cost,
                    "sleeve": sleeve,
                }
            )
        for symbol in sorted(target - set(held)):
            entry_ts = next_ts(ts)
            open_price = opens[symbol].get(entry_ts)
            if open_price is None:
                continue
            entry_price = open_price
            held[symbol] = entry_price
            events.append(
                {
                    "action": "BUY",
                    "symbol": symbol,
                    "ts_ms": entry_ts,
                    "price": entry_price,
                    "sleeve": sleeve,
                }
            )

    trades = _rotation_round_trips(events)
    return {
        "family": "cross_sectional_rotation",
        "events": events,
        "trades": trades,
        "equity_curve": equity_curve,
        "rebalances": sum(1 for e in events if e["action"] == "BUY"),
        "universe": universe,
    }


def _rotation_round_trips(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pair each BUY with its SELL so the family reports in the same shape."""
    open_entries: dict[str, dict[str, Any]] = {}
    trades: list[dict[str, Any]] = []
    for event in events:
        if event["action"] == "BUY":
            open_entries[event["symbol"]] = event
            continue
        opening = open_entries.pop(event["symbol"], None)
        trades.append(
            {
                "symbol": event["symbol"],
                "entry_ts_ms": opening["ts_ms"] if opening else event["ts_ms"],
                "exit_ts_ms": event["ts_ms"],
                "entry_price": opening["price"] if opening else event["price"],
                "exit_price": event["price"],
                "gross_bps": float(event["gross_bps"]),
                "net_bps": float(event["net_bps"]),
                "cost_bps": float(event["cost_bps"]),
                "sleeve": float(event["sleeve"]),
                "bars_held": 0,
                "direction": "long",
            }
        )
    return trades


def evaluate_portfolio(
    equity_curve: Sequence[tuple[int, float]],
    trades: Sequence[dict[str, Any]],
    *,
    window_days: float,
) -> dict[str, Any]:
    """The rotation family's metrics, read off its own equity path."""
    if not equity_curve:
        return {}
    start_ts, end_ts = equity_curve[0][0], equity_curve[-1][0]
    values = [value for _ts, value in equity_curve]
    peak = values[0]
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            worst = max(worst, (peak - value) / peak)
    daily: list[float] = []
    day_of = {}
    for ts, value in equity_curve:
        day_of[ts // 86_400_000] = value
    days_sorted = sorted(day_of)
    for previous, current in pairwise(days_sorted):
        if day_of[previous] > 0:
            daily.append((day_of[current] / day_of[previous] - 1.0) * 10_000.0)
    sharpe = 0.0
    if len(daily) > 1:
        mean = sum(daily) / len(daily)
        variance = sum((v - mean) ** 2 for v in daily) / len(daily)
        stdev = math.sqrt(variance)
        if stdev > 0:
            sharpe = (mean / stdev) * math.sqrt(365.0)
    net = [float(t["net_bps"]) for t in trades]
    gains = sum(v for v in net if v > 0)
    losses = -sum(v for v in net if v <= 0)
    traded_days = len({int(t["exit_ts_ms"]) // 86_400_000 for t in trades})
    rebalance_days = len({int(t["entry_ts_ms"]) // 86_400_000 for t in trades})
    final = values[-1]
    return {
        "symbol": "PORTFOLIO",
        "trades": len(trades),
        "trades_per_day": len(trades) / window_days if window_days else 0.0,
        "days_without_trades": max(int(window_days) - rebalance_days, 0),
        "window_days": window_days,
        "window_start_ms": start_ts,
        "window_end_ms": end_ts,
        "gross_bps_total": sum(float(t["gross_bps"]) for t in trades),
        "gross_bps_per_trade": (sum(float(t["gross_bps"]) for t in trades) / len(trades))
        if trades
        else 0.0,
        "net_bps_total": sum(net) / max(1, len({t["sleeve"] for t in trades})) if trades else 0.0,
        "net_bps_total_portfolio": (final - 1.0) * 10_000.0,
        "expectancy_bps_per_trade": (sum(net) / len(net)) if net else 0.0,
        "cost_bps_per_trade": (sum(float(t.get("cost_bps", 0.0)) for t in trades) / len(trades))
        if trades
        else 0.0,
        "fees_and_costs_bps_paid": sum(float(t.get("cost_bps", 0.0)) for t in trades),
        "win_rate": (sum(1 for v in net if v > 0) / len(net)) if net else 0.0,
        "profit_factor": (gains / losses) if losses > 0 else (None if not net else float("inf")),
        "equity_multiple": final,
        "max_drawdown_bps": worst * 10_000.0,
        "sharpe_daily_annualised": sharpe,
        "traded_days": traded_days,
    }


# --------------------------------------------------------------------------------------
# evaluation
# --------------------------------------------------------------------------------------


def split_index(bars: Sequence[Bar], fraction: float) -> int:
    return max(1, min(len(bars) - 1, int(len(bars) * fraction)))


def family_trades(
    family: Family, bars: Sequence[Bar], params: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Run one tested family over one symbol's bars."""
    active = {**family.parameters, **(params or {})}
    if family.name == "vol_regime_breakout":
        return _vol_regime_breakout(bars, active)
    if family.name == "trend_pullback":
        return _trend_pullback(bars, active)
    if family.name == "mean_reversion_vol_liq":
        return _mean_reversion_vol_liq(bars, active)
    raise ValueError(f"family {family.name!r} has no single-asset implementation")


def _daily_curve(trades: Iterable[dict[str, Any]], window_days: float) -> tuple[list[float], float]:
    """Daily net bps, oldest first, from the trades' own days."""
    by_day: dict[int, float] = {}
    for trade in trades:
        day = int(float(trade["exit_ts_ms"]) // 86_400_000)
        by_day[day] = by_day.get(day, 0.0) + float(trade["net_bps"])
    if not by_day:
        return [], window_days
    first, last = min(by_day), max(by_day)
    days = max(last - first + 1, 1)
    return [by_day.get(day, 0.0) for day in range(first, last + 1)], float(days)


def evaluate_trades(
    trades: Sequence[dict[str, Any]],
    *,
    symbol: str,
    window_days: float,
    window_start_ms: int,
    window_end_ms: int,
    stake_usdt: float = ANCHOR_STAKE_USDT,
    cost_multiplier: float = 1.0,
    already_net: bool = False,
) -> dict[str, Any]:
    """Every metric the brief asks for, from the trades' own rows.

    ``already_net`` is for the rotation family, which charges each rebalance as
    it happens; everything else enters gross and is priced here, so the cost
    multiplier can be varied without re-running the rule.
    """
    rows = [dict(t) for t in trades]
    cost_1x = round_trip_cost_bps(symbol, stake_usdt=stake_usdt, multiplier=1.0)
    cost_at = round_trip_cost_bps(symbol, stake_usdt=stake_usdt, multiplier=cost_multiplier)
    for row in rows:
        gross = float(row["gross_bps"])
        row["cost_bps"] = cost_at
        row["net_bps"] = float(row["net_bps"]) if already_net else gross - cost_at
        for multiplier in COST_MULTIPLIERS:
            row[f"net_bps_{multiplier:g}x"] = gross - round_trip_cost_bps(
                symbol, stake_usdt=stake_usdt, multiplier=multiplier
            )

    net_sum = sum(float(r["net_bps"]) for r in rows)
    gross_sum = sum(float(r["gross_bps"]) for r in rows)
    wins = [r for r in rows if float(r["net_bps"]) > 0]
    losses = [r for r in rows if float(r["net_bps"]) <= 0]
    gains = sum(float(r["net_bps"]) for r in wins)
    drawdowns = -sum(float(r["net_bps"]) for r in losses)

    curve, days = _daily_curve(rows, window_days)
    equity = 1.0
    peak = 1.0
    worst = 0.0
    for value in [float(r["net_bps"]) for r in rows]:
        equity *= 1.0 + value / 10_000.0
        peak = max(peak, equity)
        worst = max(worst, (peak - equity) / peak)
    sharpe = 0.0
    if len(curve) > 1:
        mean = sum(curve) / len(curve)
        variance = sum((v - mean) ** 2 for v in curve) / len(curve)
        stdev = math.sqrt(variance)
        if stdev > 0:
            sharpe = (mean / stdev) * math.sqrt(365.0)

    traded_days = len({int(float(r["exit_ts_ms"]) // 86_400_000) for r in rows})
    # Concentration: a mean carried by a handful of trades is a lottery, not an
    # edge, and a mean alone cannot show the difference. These three numbers can.
    ordered_gross = sorted((float(r["gross_bps"]) for r in rows), reverse=True)
    top5 = sum(ordered_gross[:5])
    median_net = median([float(r["net_bps"]) for r in rows]) if rows else 0.0
    return {
        "symbol": symbol,
        "trades": len(rows),
        "median_net_bps_per_trade": median_net,
        "top5_share_of_gross": (top5 / gross_sum) if gross_sum > 0 else None,
        "best_trade_bps": ordered_gross[0] if ordered_gross else 0.0,
        "worst_trade_bps": ordered_gross[-1] if ordered_gross else 0.0,
        "trades_losing_money_per_trade": (
            sum(1 for r in rows if float(r["net_bps"]) <= 0) / len(rows) if rows else 0.0
        ),
        "trades_per_day": len(rows) / days if days else 0.0,
        "days_without_trades": max(int(days) - traded_days, 0),
        "window_days": days,
        "window_start_ms": window_start_ms,
        "window_end_ms": window_end_ms,
        "gross_bps_total": gross_sum,
        "gross_bps_per_trade": gross_sum / len(rows) if rows else 0.0,
        "net_bps_total": net_sum,
        "expectancy_bps_per_trade": net_sum / len(rows) if rows else 0.0,
        "cost_bps_per_trade": cost_at,
        "cost_1x_bps_per_trade": cost_1x,
        "fees_and_costs_bps_paid": cost_at * len(rows),
        "win_rate": len(wins) / len(rows) if rows else 0.0,
        "profit_factor": (gains / drawdowns)
        if drawdowns > 0
        else (None if not rows else float("inf")),
        "equity_multiple": equity,
        "max_drawdown_bps": worst * 10_000.0,
        "sharpe_daily_annualised": sharpe,
        "net_bps_total_1x": sum(float(r["net_bps_1x"]) for r in rows),
        "net_bps_total_2x": sum(float(r["net_bps_2x"]) for r in rows),
        "net_bps_total_3x": sum(float(r["net_bps_3x"]) for r in rows),
        "expectancy_bps_per_trade_2x": (
            sum(float(r["net_bps_2x"]) for r in rows) / len(rows) if rows else 0.0
        ),
        "expectancy_bps_per_trade_3x": (
            sum(float(r["net_bps_3x"]) for r in rows) / len(rows) if rows else 0.0
        ),
    }


# --------------------------------------------------------------------------------------
# the protocol, frozen before capture
# --------------------------------------------------------------------------------------

#: Thresholds frozen before the prospective data exists. A candidate that has not
#: reached the trade count cannot accept or reject anything.
ACCEPTANCE_THRESHOLDS: dict[str, Any] = {
    "min_closed_trades_per_strategy": 200,
    "net_expectancy_bps_per_trade_min": 0.0,
    "profit_factor_min": 1.2,
    "max_drawdown_bps_max": 2000.0,
    "must_stay_positive_at_cost_multiplier": 2.0,
    "max_data_points_used_for_selection": 1,
}

FROZEN_PROTOCOL: dict[str, Any] = {
    "schema_version": "EDGE15_ALPHA_PROTOCOL_V1",
    "work_package": "WP-EDGE-015/P1-P3",
    "families": [
        {
            "name": family.name,
            "status": family.status,
            "hypothesis": family.hypothesis,
            "parameters": family.parameters,
            "differs_from": list(family.differs_from),
            "untestable_reason": family.untestable_reason,
            "required_evidence": family.required_evidence,
        }
        for family in FAMILIES
    ],
    "costs": COST_MODEL_V15,
    "acceptance_thresholds": ACCEPTANCE_THRESHOLDS,
    "selection_rule": (
        "parameters are fixed here and are not searched on the evaluation segment; a family "
        "is ADOPTed only if it clears every threshold on data it did not select on, and this "
        "project has no such data until the prospective slice accrues"
    ),
    "comparator_CURRENT": (
        "the runtime as it stands: no strategy admitted, no trades, flat equity — a candidate "
        "must beat zero, not merely exist"
    ),
    "expected_outcome_if_the_evidence_says_so": (
        "NO_ECONOMIC_EDGE_FOUND, with the research lane kept and the next hypothesis named"
    ),
}

#: Families that are only declared, never executed — reported as such everywhere.
UNTESTED_FAMILIES: tuple[str, ...] = tuple(
    family.name for family in FAMILIES if family.status != "TESTED"
)

#: The single-asset families, in the order the matrix reports them.
TESTED_FAMILIES: tuple[Family, ...] = tuple(f for f in FAMILIES if f.status == "TESTED")

#: The subset that runs one symbol at a time, i.e. everything but the portfolio one.
SINGLE_ASSET_FAMILIES: tuple[Family, ...] = tuple(
    f for f in TESTED_FAMILIES if f.name != "cross_sectional_rotation"
)


def family_runner(name: str) -> Callable[[Sequence[Bar], dict[str, Any]], list[dict[str, Any]]]:
    return {
        "vol_regime_breakout": _vol_regime_breakout,
        "trend_pullback": _trend_pullback,
        "mean_reversion_vol_liq": _mean_reversion_vol_liq,
    }[name]


#: The pre-repair runners, for the reconciliation script and its tests only.
PRE_PIT_RUNNERS: dict[str, Callable[[Sequence[Bar], dict[str, Any]], list[dict[str, Any]]]] = {
    "vol_regime_breakout": _vol_regime_breakout_pre_pit,
    "trend_pullback": _trend_pullback_pre_pit,
    "mean_reversion_vol_liq": _mean_reversion_vol_liq_pre_pit,
}

__all_pit__ = ["PIT_CONTRACT", "audit_trade", "PRE_PIT_RUNNERS", "run_family"]
