"""RFC-022 Sprint 002 - hypothesis registry (data form).

The prose form is reports/edge-discovery/sprint002/HYPOTHESIS_REGISTRY.md.
This module is the machine-readable authority used by the pipeline to emit
HYPOTHESIS_REGISTRY.json and to bind every experiment to a hypothesis_id.
"""

from __future__ import annotations

from typing import Any

HYPOTHESIS_META: dict[str, dict[str, Any]] = {
    "H-P0-01": {
        "family": "compression_breakout",
        "tier": "P0",
        "description": "ATR/range compression percentile then structural range breakout continues.",
        "economic_mechanism": (
            "Volatility clusters; compressed ranges concentrate stop orders and resting "
            "liquidity just outside the range, so the first break consumes liquidity and "
            "extends mechanically."
        ),
        "why_edge_may_exist": (
            "Breaks out of statistically unusual compression are informed positioning, not noise."
        ),
        "why_move_can_exceed_cost": (
            "Range-expansion excursion is a multiple of the compression width, itself a large "
            "fraction of ATR."
        ),
        "expected_regime": "LOW_VOLATILITY -> HIGH_VOLATILITY",
        "entry_concept": (
            "rank_atr[120] <= 0.20 and close > max(high[i-40..i-1]) (LONG; mirror SHORT)"
        ),
        "exit_concept": "ATR target / ATR stop / time stop",
        "invalidation": "Re-entry into the pre-break range, or time stop",
        "assets": ["BTC", "ETH", "SOL"],
        "timeframes": ["15m", "30m", "1h", "2h"],
        "required_data": "OHLCV only",
        "known_failure_modes": ["false breakouts", "single rank threshold", "low event count"],
    },
    "H-P0-02": {
        "family": "squeeze_magnitude",
        "tier": "P0",
        "description": (
            "Bollinger-inside-Keltner squeeze duration/tightness predicts release magnitude; "
            "ATR-scaled exit."
        ),
        "economic_mechanism": (
            "Vol clustering; squeeze quality (duration + tightness) measures accumulated "
            "compression."
        ),
        "why_edge_may_exist": (
            "Sprint 001 volatility@30m traded the release with a flat 0.75% TP and a 1% default "
            "stop, truncating the tail; the signal may carry information while the exit destroys it."
        ),
        "why_move_can_exceed_cost": (
            "A long squeeze release impulse scales with accumulated compression; a 2-3x ATR target "
            "is materially larger than 0.75% fixed."
        ),
        "expected_regime": "LOW_VOLATILITY releasing into HIGH_VOLATILITY",
        "entry_concept": (
            "BB(20,2.0) inside KC(20,1.5xATR10) >= 6 bars, BB width rank <= 0.25, close outside BB"
        ),
        "exit_concept": "ATR target / ATR stop / time stop",
        "invalidation": "Stop at k_s x ATR, or time stop",
        "assets": ["BTC", "ETH", "SOL"],
        "timeframes": ["15m", "30m", "1h"],
        "required_data": "OHLCV only",
        "known_failure_modes": [
            "Keltner multiplier sensitivity",
            "single-bar release spikes",
            "low event count",
        ],
    },
    "H-P0-03": {
        "family": "vol_contraction_expansion",
        "tier": "P0",
        "description": "Realised-vol expansion onset in the direction of the established EMA trend.",
        "economic_mechanism": (
            "Volatility is persistent; the direction of an expansion is set by the prevailing trend."
        ),
        "why_edge_may_exist": (
            "Separates compression (do not trade) from expansion onset (trade); Sprint 001 "
            "required no trend agreement."
        ),
        "why_move_can_exceed_cost": (
            "Trend + expanding vol is the regime with the largest favourable excursion per unit time."
        ),
        "expected_regime": "Trend + volatility expansion",
        "entry_concept": "rank_rv[120] <= 0.20 and rv20 rising and ema9 > ema21 (LONG; mirror SHORT)",
        "exit_concept": "ATR target / ATR stop / time stop",
        "invalidation": "EMA trend flips against the position, stop, or time stop",
        "assets": ["BTC", "ETH", "SOL"],
        "timeframes": ["30m", "1h", "2h"],
        "required_data": "OHLCV only",
        "known_failure_modes": ["late trend filter", "one-bar expansion artefact"],
    },
    "H-P1-01": {
        "family": "pullback_continuation",
        "tier": "P1",
        "description": "Established trend, controlled retracement to the fast EMA, then momentum reclaim.",
        "economic_mechanism": (
            "Trends are not monotonic; pullbacks re-accumulate resting liquidity and improve the "
            "entry price."
        ),
        "why_edge_may_exist": (
            "Low frequency, better entry, wide ATR exit -> larger favourable excursion per trade."
        ),
        "why_move_can_exceed_cost": (
            "Entry near the pullback extreme shrinks the move needed to pay 23.79 bps while the "
            "remaining trend runway is unchanged."
        ),
        "expected_regime": "TREND_UP / TREND_DOWN",
        "entry_concept": (
            "ema21 > ema50 and ema9 > ema21, low touched ema21 within 5 bars, close back above "
            "ema9, rsi14 < 60 (LONG; mirror SHORT)"
        ),
        "exit_concept": "ATR target / ATR stop / time stop",
        "invalidation": "Close back below ema21, or time stop",
        "assets": ["BTC", "ETH", "SOL"],
        "timeframes": ["15m", "30m", "1h", "2h"],
        "required_data": "OHLCV only",
        "known_failure_modes": ["pullback becomes reversal", "many events in chop"],
    },
    "H-P1-02": {
        "family": "breakout_retest",
        "tier": "P1",
        "description": "Structural level break, then a retest that holds, then continuation.",
        "economic_mechanism": (
            "A broken level that holds is evidence the break was absorbed by real flow rather "
            "than a liquidity sweep."
        ),
        "why_edge_may_exist": (
            "Fewer trades, higher hit rate, larger average winner, less whipsaw than a naive "
            "breakout."
        ),
        "why_move_can_exceed_cost": (
            "Entering at the retest shrinks the distance to target and tightens invalidation, "
            "improving cost/edge structurally."
        ),
        "expected_regime": "Breakout / trend initiation",
        "entry_concept": (
            "Level = max(high[i-60..i-21]); break, then a bar within 10 that touches level and "
            "closes on the break side"
        ),
        "exit_concept": "ATR target / ATR stop / time stop",
        "invalidation": "Close back through the level against the position",
        "assets": ["BTC", "ETH", "SOL"],
        "timeframes": ["30m", "1h", "2h"],
        "required_data": "OHLCV only",
        "known_failure_modes": ["retest never occurs", "level-definition sensitivity"],
    },
    "H-P1-03": {
        "family": "regime_momentum",
        "tier": "P1",
        "description": "Momentum only when the volatility/volume regime supports continuation.",
        "economic_mechanism": (
            "Continuation needs liquidity to keep arriving in the same direction; volume "
            "expansion is the observable proxy."
        ),
        "why_edge_may_exist": (
            "Conditioning on an ONLINE regime removes the chop trades that killed generic momentum."
        ),
        "why_move_can_exceed_cost": (
            "Conditioning raises average excursion per trade by excluding low-amplitude regimes."
        ),
        "expected_regime": "TREND + volume expansion",
        "entry_concept": "ret[20] > 0 and vol_rank[120] >= 0.70 and close > ema21 (LONG; mirror SHORT)",
        "exit_concept": "ATR target / ATR stop / time stop",
        "invalidation": "Stop or time stop",
        "assets": ["BTC", "ETH", "SOL"],
        "timeframes": ["30m", "1h", "2h"],
        "required_data": "OHLCV only",
        "known_failure_modes": ["noisy volume proxy", "regime label lag"],
    },
    "H-P1-04": {
        "family": "vol_shock_followthrough",
        "tier": "P1",
        "description": "After a volatility shock, test continuation AND reversion symmetrically.",
        "economic_mechanism": (
            "A shock is an information event; continuation implies under-reaction, reversion "
            "implies absorbed overreaction."
        ),
        "why_edge_may_exist": "Shocks are exactly when a move is large enough to clear 23.79 bps.",
        "why_move_can_exceed_cost": (
            "The shock itself is a large move; the question is whether the next leg is tradable."
        ),
        "expected_regime": "HIGH_VOLATILITY",
        "entry_concept": (
            "rank_atr[240] >= 0.90 and atr_pct >= 2x mean(atr_pct[i-20..i-1]); direction = "
            "+/- sign(ret1)"
        ),
        "exit_concept": "ATR target / ATR stop / time stop",
        "invalidation": "Stop or time stop",
        "assets": ["BTC", "ETH", "SOL"],
        "timeframes": ["30m", "1h"],
        "required_data": "OHLCV only",
        "known_failure_modes": ["both directions fail", "threshold sensitivity"],
    },
    "H-P1-05": {
        "family": "cross_sectional_rs",
        "tier": "P1",
        "description": "Long the strongest major, short the weakest, costed per leg.",
        "economic_mechanism": (
            "Relative-strength persistence: idiosyncratic flow rotates into the strongest name "
            "and out of the weakest."
        ),
        "why_edge_may_exist": (
            "The strongest-minus-weakest spread is less beta-driven than a single-asset position."
        ),
        "why_move_can_exceed_cost": (
            "Pair spread can exceed single-asset drift, but both legs pay 23.79 bps so the pair "
            "barrier is 47.58 bps."
        ),
        "expected_regime": "Any; stronger in rotation regimes",
        "entry_concept": "Rank trailing ret[40]; LONG rank-1, SHORT rank-3",
        "exit_concept": "Time stop (rebalance horizon); pair closed together",
        "invalidation": "Time stop",
        "assets": ["BTC", "ETH", "SOL"],
        "timeframes": ["1h", "2h"],
        "required_data": "Synchronised OHLCV across the three assets",
        "known_failure_modes": [
            "short leg not executable in the frozen spot runtime (RFC-030 SHORT_DATA_BLOCKED)",
            "double cost",
        ],
    },
    "H-P1-06": {
        "family": "lead_lag",
        "tier": "P1",
        "description": "BTC(t) move is followed by ETH/SOL at t+delta for predefined delta.",
        "economic_mechanism": (
            "BTC is the price-discovery venue for the complex; thinner majors adjust with a lag."
        ),
        "why_edge_may_exist": "Cross-asset information diffusion is not instantaneous.",
        "why_move_can_exceed_cost": (
            "The lagged move must exceed 23.79 bps, plausible after a strong BTC bar at 15m/30m."
        ),
        "expected_regime": "Any; stronger in high-activity regimes",
        "entry_concept": "sign(ret1_BTC[t]) -> enter ETH/SOL at t+delta, delta in {1, 3} bars",
        "exit_concept": "ATR target / ATR stop / time stop",
        "invalidation": "Stop or time stop",
        "assets": ["ETH", "SOL"],
        "timeframes": ["15m", "30m"],
        "required_data": "Synchronised OHLCV; only bars <= t for the BTC signal",
        "known_failure_modes": [
            "synchronous beta artefact; REJECT if it vanishes in VALIDATION",
            "forbidden: BTC(t+1) -> ETH(t)",
        ],
        "tests_required": ["LEAD_LAG_PIT", "LEAD_LAG_FUTURE_POINTS"],
    },
    "H-P2-01": {
        "family": "funding_carry",
        "tier": "P2",
        "description": "Funding extremes, funding mean reversion, spot-perp basis convergence, carry.",
        "economic_mechanism": (
            "Perpetual funding pays the side crowded against the basis; extremes precede basis "
            "mean reversion."
        ),
        "why_edge_may_exist": "Perp crowding is observable through funding.",
        "why_move_can_exceed_cost": (
            "Funding is a cash flow; basis convergence is a single move."
        ),
        "expected_regime": "Any",
        "entry_concept": "NOT DEFINED - data unavailable",
        "exit_concept": "NOT DEFINED",
        "invalidation": "N/A",
        "assets": [],
        "timeframes": [],
        "required_data": (
            "Timestamped, historical, PIT-safe funding/basis series covering 2026-03..2026-09"
        ),
        "known_failure_modes": [
            "DATA_BLOCKED: only a 2026-10-01 forward capture exists, outside W1-W7"
        ],
        "status": "DATA_BLOCKED",
    },
    "H-P2-02": {
        "family": "volume_expansion",
        "tier": "P2",
        "description": "Abnormal volume accompanies price breakouts; orthogonal to price-only signals.",
        "economic_mechanism": (
            "Volume is the footprint of participation; a breakout on abnormal volume is more "
            "likely backed by real flow."
        ),
        "why_edge_may_exist": (
            "Volume is a different information set than price geometry and should raise breakout "
            "hit rate."
        ),
        "why_move_can_exceed_cost": (
            "Filtering to high-participation events selects bars with larger excursions."
        ),
        "expected_regime": "HIGH_VOLATILITY / HIGH_PARTICIPATION",
        "entry_concept": "vol_rank[120] >= 0.90 and ret1 > 0 (LONG; mirror SHORT)",
        "exit_concept": "ATR target / ATR stop / time stop",
        "invalidation": "Stop or time stop",
        "assets": ["BTC", "ETH", "SOL"],
        "timeframes": ["30m", "1h"],
        "required_data": "OHLCV only (volume included)",
        "known_failure_modes": ["noisy exchange-specific volume", "correlated with the shock event"],
    },
    "H-P2-03": {
        "family": "session_conditioning",
        "tier": "P2",
        "description": (
            "Session rule fixed BEFORE the test: US session (13:00-21:00 UTC) continuation signals.",
        ),
        "economic_mechanism": (
            "Liquidity and information arrival are not uniform across the day; the US session "
            "carries the deepest flow."
        ),
        "why_edge_may_exist": (
            "Session-conditioned execution avoids thin, mean-reverting hours."
        ),
        "why_move_can_exceed_cost": (
            "Larger intraday amplitude during the US session relative to cost."
        ),
        "expected_regime": "Any (session orthogonal to trend)",
        "entry_concept": "13 <= utc_hour < 21 and ret[5] > 0 (LONG; mirror SHORT)",
        "exit_concept": "ATR target / ATR stop / time stop",
        "invalidation": "Stop or time stop",
        "assets": ["BTC", "ETH", "SOL"],
        "timeframes": ["30m", "1h"],
        "required_data": "OHLCV with UTC timestamps",
        "known_failure_modes": [
            "thin per-session sample",
            "hour-selection risk controlled by fixing the rule first",
        ],
    },
}

# Sprint 001 families must NOT be re-tuned through micro parameter changes (S2).
NON_RETUNABLE_SPRINT001_FAMILIES = (
    "breakout",
    "ema_crossover",
    "mean_reversion",
    "momentum",
    "trend",
    "volatility",
)

__all__ = ["HYPOTHESIS_META", "NON_RETUNABLE_SPRINT001_FAMILIES"]
