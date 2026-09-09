"""DISCOVERY-BATCH-02 — preregistered evaluation specs (frozen BEFORE execution).

POC02-LAUNCH-AND-DISCOVERY-BATCH-02 (Tracks C/D/E).  This module is the
batch-02 analogue of ``discovery_execution.DISCOVERY_EVAL_SPECS``: every
economic semantic below is frozen here, fingerprinted, and committed BEFORE
any batch-02 result exists.  No threshold was chosen after observing
batch-01 outcomes (DB2-03 — no retuning of leads).

Batch-02 candidates (exactly three, per protocol):

- ``volatility_structure_v2``: SAME hypothesis/params/costs/regime method
  as batch-01 ``volatility_structure`` (DEEPER WINDOW ONLY — Track C3).
  Validated against the batch-01 spec fingerprint; any drift is a hard
  error (DB2-03).
- ``cross_sectional_v2``: SAME hypothesis as batch-01 ``cross_sectional``
  (DEEPER WINDOW ONLY — Track C4).  PIT safety requirements are part of
  the spec (no future universe membership/rank).
- ``carry_funding_v2``: NEW evaluation spec with canonical funding-unit
  contract (C5 — DEF-DISCOVERY-001 repair).  The batch-01 ``carry_funding``
  spec is NOT modified: the repair is a new fingerprinted version
  (DB2-06).  See ``trading_bot.research.funding_units``.

Costs, regime engine, simulation mechanics and harness gates are the FROZEN
canonical legacy protocol values (commission_rate 0.0004, slippage 2.0 bps
both sides, MIN_SAMPLE 15, max_pvalue 0.05) — identical thresholds, no
per-track lowering.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

from trading_bot.research.discovery_execution import (
    DISCOVERY_EVAL_SPECS as BATCH01_EVAL_SPECS,
)
from trading_bot.research.discovery_execution import (
    DiscoverySignalResult,
    _atr,
    _simulate,
)
from trading_bot.research.funding_units import (
    CONTRACT_ID,
    canon_funding_interval_s,
    canon_rate_per_period,
)
from trading_bot.market_data.types import OHLCV
from trading_bot.research.retro_execution import TradeOutcome

__all__ = [
    "BATCH02_EVAL_SPECS",
    "COST_RATE",
    "SLIPPAGE_BPS",
    "batch02_eval_fingerprint",
    "verify_batch01_spec_unchanged",
    "carry_funding_v2_signals",
    "volatility_structure_v2_signals",
    "cross_sectional_v2_signals",
]

# --------------------------------------------------------------------------
# Frozen canonical protocol values (identical to batch-01 execution)
# --------------------------------------------------------------------------
COST_RATE = 0.0004          # commission per side (4 bps)
SLIPPAGE_BPS = 2.0          # slippage per side (bps)
MIN_SAMPLE = 15             # harness MIN_SAMPLE (binding constraint in batch-01)

# Deeper preregistered window (C2): 1h candles, ~2 years back from launch.
DEEPER_1H_BARS = 17520
DEEPER_5M_BARS = 1500       # higher-resolution cells stay bounded (prereg)


# --------------------------------------------------------------------------
# C1/DB2-03 — batch-02 specs; lead specs must equal batch-01 semantics
# --------------------------------------------------------------------------
def _spec2(
    category: str,
    entry: str,
    stop: str,
    exit_rule: str,
    *,
    params: dict[str, Any],
) -> dict[str, Any]:
    return {
        "category": category,
        "entry_rule": entry,
        "stop_rule": stop,
        "exit_rule": exit_rule,
        "sizing_rule": "unit fraction (evaluation; sizing is not part of research)",
        "cost_model": "protocol commission_rate + slippage both sides (identical to frozen legacy protocol)",
        "direction_policy": "structural (long or short per signal)",
        "min_sample": "harness MIN_SAMPLE",
        "data": "public binanceusdm PIT OHLCV (+ REAL funding history for carry_funding_v2)",
    } | params


def _batch01(category: str) -> dict[str, Any]:
    return BATCH01_EVAL_SPECS[category]


#: batch-01 stores params FLAT on the spec dict; these are the mirrored
#: parameter keys per category (economic semantics, verified in
#: ``verify_batch01_spec_unchanged``).
BATCH01_PARAM_KEYS: dict[str, tuple[str, ...]] = {
    "volatility_structure": ("atr_z", "atr_exit_z", "max_hold_bars"),
    "cross_sectional": ("lookback", "universe", "max_hold_bars"),
    "carry_funding": ("funding_window", "max_hold_bars"),
}


def _batch01_params(category: str) -> dict[str, Any]:
    return {k: _batch01(category)[k] for k in BATCH01_PARAM_KEYS[category]}


BATCH02_EVAL_SPECS: dict[str, dict[str, Any]] = {
    # ------------------------------------------------------------------
    # C3 — volatility_structure_v2: deeper window of the SAME hypothesis.
    # Every economic semantic mirrors batch-01 ``volatility_structure``;
    # only the data window differs (deeper), which is window, not spec.
    # ------------------------------------------------------------------
    "volatility_structure_v2": _spec2(
        "volatility_structure_v2",
        entry=_batch01("volatility_structure")["entry_rule"],
        stop=_batch01("volatility_structure")["stop_rule"],
        exit_rule=_batch01("volatility_structure")["exit_rule"],
        params=_batch01_params("volatility_structure"),
    ),
    # ------------------------------------------------------------------
    # C4 — cross_sectional_v2: deeper window of the SAME hypothesis; PIT
    # safety made explicit (no future universe membership or future rank).
    # ------------------------------------------------------------------
    "cross_sectional_v2": _spec2(
        "cross_sectional_v2",
        entry=_batch01("cross_sectional")["entry_rule"],
        stop=_batch01("cross_sectional")["stop_rule"],
        exit_rule=_batch01("cross_sectional")["exit_rule"],
        params={
            **_batch01_params("cross_sectional"),
            "pit_universe_policy": (
                "universe membership frozen at decision time; ranking uses "
                "only candles[..t]; no future data"
            ),
        },
    ),
    # ------------------------------------------------------------------
    # C5 — carry_funding_v2: NEW spec under the canonical funding-unit
    # contract (DEF-DISCOVERY-001 repair; old spec untouched).
    # ------------------------------------------------------------------
    "carry_funding_v2": _spec2(
        "carry_funding_v2",
        entry=(
            "TRUE CARRY: SHORT when trailing mean funding_rate > 0 in "
            "DECIMAL per interval (SHORT receives positive funding); LONG "
            "when trailing mean < 0 (LONG receives negative funding); flat "
            "otherwise.  DEF-DISCOVERY-001 repair: batch-01 said 'LONG when "
            "funding positive (positive-carry accrual)' — wrong-signed perp "
            "mechanics (LONG PAYS positive funding); corrected here BEFORE "
            "any batch-02 result existed"
        ),
        stop=_batch01("carry_funding")["stop_rule"],
        exit_rule=(
            "exit when trailing mean funding (decimal, per interval) turns "
            "against the position or max_hold reached"
        ),
        params={
            **_batch01_params("carry_funding"),
            "funding_unit_contract": CONTRACT_ID,
            "funding_units": "decimal_fraction_per_interval (e.g. 0.0001 = 1 bp per interval)",
            "funding_interval_s": 28800,
            "funding_window_intervals": 8,
            "funding_key_unit": "epoch_milliseconds (DEF-DISCOVERY-001 repair: batch-01 compared hour-keyed entries against millisecond window bounds)",
            "short_carry_sign": "SHORT positions receive the opposite sign of funding",
        },
    ),
}


def verify_batch01_spec_unchanged() -> dict[str, str]:
    """Prove batch-02 lead specs did not drift from batch-01 (DB2-03).

    Returns {batch02_category: batch01_category} for the mirrored pairs and
    raises when any economic semantic differs.
    """
    mirrored: dict[str, str] = {}
    pairs = {
        "volatility_structure_v2": "volatility_structure",
        "cross_sectional_v2": "cross_sectional",
    }
    for v2, v1 in pairs.items():
        spec_v2 = BATCH02_EVAL_SPECS[v2]
        spec_v1 = _batch01(v1)
        for field in ("entry_rule", "stop_rule", "exit_rule"):
            if spec_v2[field] != spec_v1[field]:
                raise AssertionError(
                    f"RETUNE DETECTED: {v2}.{field} differs from batch-01")
        for k, v in _batch01_params(v1).items():
            if spec_v2.get(k) != v:
                raise AssertionError(
                    f"RETUNE DETECTED: {v2}.{k} differs from batch-01")
        mirrored[v2] = v1
    return mirrored


def batch02_eval_fingerprint(category: str) -> str:
    """Deterministic fingerprint of a batch-02 evaluation spec (C2)."""
    canonical = json.dumps(
        {
            "category": category,
            "spec": BATCH02_EVAL_SPECS[category],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Signal generators — SAME mechanics as batch-01 (_simulate), deeper window
# --------------------------------------------------------------------------
def volatility_structure_v2_signals(
    candles: list[OHLCV],
    *,
    cost_rate: float = COST_RATE,
    slippage_bps: float = SLIPPAGE_BPS,
    atr_z: float = 1.5,
    atr_exit_z: float = 0.5,
    max_hold_bars: int = 48,
    lookback: int = 96,
) -> DiscoverySignalResult:
    """Mirror of batch-01 ``volatility_structure`` signal (v1 source of
    truth: ``discovery_execution._vol_structure_signals``)."""

    def atr_z_at(i: int) -> float | None:
        end = i - 1
        if end < 14:
            return None
        trs = []
        for k in range(end - 14 + 1, end + 1):
            h, low, pc = candles[k].high, candles[k].low, candles[k - 1].close
            trs.append(max(h - low, abs(h - pc), abs(low - pc)))
        mean = sum(trs) / 14
        var = sum((t - mean) ** 2 for t in trs) / 14
        sd = var ** 0.5
        if sd <= 0:
            return None
        return float((trs[-1] - mean) / sd)

    def z_mean_at(i: int) -> float | None:
        zs = [atr_z_at(k) for k in range(max(0, i - lookback), i)]
        zs = [z for z in zs if z is not None]
        if len(zs) < lookback // 2:
            return None
        return sum(zs) / len(zs)

    def direction_at(i: int) -> str | None:
        zm = z_mean_at(i)
        if zm is None or zm <= atr_z:
            return None
        return "LONG"

    def exit_at(i: int) -> bool:
        zm = z_mean_at(i)
        return zm is not None and zm < atr_exit_z

    trades = _simulate_long_only(
        direction_at,
        candles,
        cost_rate=cost_rate,
        slippage_bps=slippage_bps,
        hold_bars=max_hold_bars,
        exit_early=exit_at,
    )
    return DiscoverySignalResult("volatility_structure_v2", trades, len(trades))


def cross_sectional_v2_signals(
    by_asset: dict[str, list[OHLCV]],
    *,
    cost_rate: float = COST_RATE,
    slippage_bps: float = SLIPPAGE_BPS,
    lookback: int = 24,
    max_hold_bars: int = 96,
) -> DiscoverySignalResult:
    """Mirror of batch-01 ``cross_sectional`` (top-1 momentum rotation) —
    PIT-safe by construction: ranking at bar t uses only closes <= t."""

    def _top1(i: int) -> str | None:
        rets = {
            a: (v[i].close / v[i - lookback].close - 1.0)
            for a, v in by_asset.items()
            if len(v) > lookback
        }
        if not rets:
            return None
        ranked = sorted(rets.items(), key=lambda kv: (-kv[1], kv[0]))
        top_a, top_r = ranked[0]
        others = sorted(r for _, r in ranked[1:])
        med = others[len(others) // 2]
        return top_a if top_r > med else None

    def direction_at(i: int) -> str | None:
        if i < lookback:
            return None
        return _top1(i)

    def asset_at(i: int) -> str | None:
        if i < lookback:
            return None
        return _top1(i)

    trades = _simulate_top1_rotation(
        asset_at,
        by_asset,
        cost_rate=cost_rate,
        slippage_bps=slippage_bps,
        hold_bars=max_hold_bars,
    )
    return DiscoverySignalResult("cross_sectional_v2", trades, len(trades))


def carry_funding_v2_signals(
    candles: list[OHLCV],
    funding_by_ms: dict[int, float],
    *,
    cost_rate: float = COST_RATE,
    slippage_bps: float = SLIPPAGE_BPS,
    funding_window_intervals: int = 8,
    funding_interval_s: int = 28800,
    hold_bars: int = 96,
) -> DiscoverySignalResult:
    """carry_funding_v2 under the canonical funding-unit contract (C5).

    ``funding_by_ms`` maps SETTLEMENT TIME (epoch ms) -> DECIMAL funding
    rate per funding interval (as produced by
    ``funding_data.fetch_funding_history`` / ``canon_rate_per_period``).
    ``funding_window_intervals`` counts settlements, not hours.  The
    decision rule is symmetric: trailing mean > 0 → LONG, < 0 → SHORT.

    DEF-DISCOVERY-001 repair note: batch-01 compared hour-keyed funding
    entries against millisecond window bounds, so ``rates`` was always
    empty on real data (0 qualifying signals).  This spec keys by ms and
    normalizes the window to ``intervals * interval_s`` milliseconds.
    """
    window_ms = funding_window_intervals * funding_interval_s * 1000
    min_obs = funding_window_intervals // 2

    def accrual(start_idx: int, current_idx: int, entry: float) -> float:
        """INCREMENTAL accrual for bar ``current_idx``.

        ``_simulate`` sums this callback once per held bar, so the callback
        must return only the settlements in (prev_bar, cur_bar] (the entry
        bar includes settlements at exactly its timestamp).  Returning a
        cumulative sum here would double-count every settlement once per
        remaining held bar (a latent batch-01 mechanics defect this spec
        repairs — settlements must count exactly once per trade span).
        """
        cur_ms = candles[current_idx].timestamp
        if current_idx > start_idx:
            prev_ms = candles[current_idx - 1].timestamp
            lo, hi = prev_ms + 1, cur_ms
        else:
            lo, hi = candles[start_idx].timestamp, cur_ms
        # Canonical contract (funding_units.funding_pnl): LONG PAYS positive
        # funding (pnl = -N*r) => accrual sign -1; SHORT receives => +1.
        # Negative rates flip the signs automatically.
        sign = -1.0 if held_direction[0] == "LONG" else 1.0
        return sum(
            sign * r for t, r in funding_by_ms.items() if lo <= t <= hi
        )

    held_direction = ["LONG"]

    def direction_at(i: int) -> str | None:
        t_end = candles[i].timestamp
        rates = [
            r for t, r in funding_by_ms.items()
            if t_end - window_ms <= t <= t_end
        ]
        if len(rates) < min_obs:
            return None
        mean = sum(rates) / len(rates)
        if mean > 0:
            # positive funding: SHORT receives it (true carry)
            held_direction[0] = "SHORT"
            return "SHORT"
        if mean < 0:
            # negative funding: LONG receives it (true carry)
            held_direction[0] = "LONG"
            return "LONG"
        return None

    trades = _simulate(
        direction_at,
        candles,
        cost_rate=cost_rate,
        slippage_bps=slippage_bps,
        hold_bars=hold_bars,
        funding_accrual=accrual,
    )
    return DiscoverySignalResult("carry_funding_v2", trades, len(trades))


# --------------------------------------------------------------------------
# Long-only / rotation variants of the frozen _simulate mechanics
# (mechanics identical: next-bar-open entry with slippage, adverse-first
# structural 2*ATR stop, round-trip costs, non-overlapping holds)
# --------------------------------------------------------------------------
def _simulate_long_only(
    direction_at: Callable[[int], str | None],
    candles: list[OHLCV],
    *,
    cost_rate: float,
    slippage_bps: float,
    hold_bars: int,
    exit_early: Callable[[int], bool] | None = None,
) -> list[TradeOutcome]:
    """_simulate restricted to LONG (vol-structure continuation hypothesis),
    with the preregistered z-reversion early exit."""
    trades: list[TradeOutcome] = []
    i = 0
    slip = slippage_bps / 10_000.0
    while i < len(candles) - 1:
        if direction_at(i) is None:
            i += 1
            continue
        entry = candles[i + 1].open * (1 + slip)
        atr = _atr(candles, i)
        if atr is None or entry <= 0:
            i += 1
            continue
        stop = entry - 2.0 * atr
        exit_price: float | None = None
        exit_ts = candles[i + 1].timestamp
        outcome = "MAX_HOLD_EXIT"
        for j in range(i + 1, min(i + 1 + hold_bars, len(candles))):
            c = candles[j]
            exit_ts = c.timestamp
            hit_stop = c.low <= stop
            exit_price = stop if hit_stop else c.close
            if hit_stop:
                outcome = "STOP_LOSS"
                break
            if exit_early is not None and exit_early(j):
                outcome = "SIGNAL_EXIT"
                break
        else:
            if exit_price is None:
                i += 1
                continue
        exit = (exit_price or entry) * (1 - slip)
        gross = (exit - entry) / entry
        net = gross - 2 * cost_rate - 2 * slip
        trades.append(
            TradeOutcome(
                entry_ts=candles[i + 1].timestamp,
                exit_ts=exit_ts,
                direction="LONG",
                entry_price=round(entry, 12),
                exit_price=round(exit, 12),
                gross_return=round(gross, 12),
                net_return=round(net, 12),
                outcome=outcome,
            )
        )
        i += hold_bars + 1  # non-overlapping by preregistration
    return trades


def _simulate_top1_rotation(
    asset_at: Callable[[int], str | None],
    by_asset: dict[str, list[OHLCV]],
    *,
    cost_rate: float,
    slippage_bps: float,
    hold_bars: int,
) -> list[TradeOutcome]:
    """Top-1 rotation over aligned asset candles; next-bar-open entry on the
    selected asset; adverse-first structural stop; non-overlapping holds.
    Ranking is PIT (uses only bars <= decision bar)."""
    min_len = min(len(v) for v in by_asset.values())
    align = {a: v[len(v) - min_len:] for a, v in by_asset.items()}
    trades: list[TradeOutcome] = []
    i = 0
    slip = slippage_bps / 10_000.0
    while i < min_len - 1:
        if i < 1:
            i += 1
            continue
        picked = asset_at(i)
        if picked is None:
            i += 1
            continue
        candles = align[picked]
        entry = candles[i + 1].open * (1 + slip)
        atr = _atr(candles, i)
        if atr is None or entry <= 0:
            i += 1
            continue
        stop = entry - 2.0 * atr
        exit_price: float | None = None
        exit_ts = candles[i + 1].timestamp
        outcome = "MAX_HOLD_EXIT"
        for j in range(i + 1, min(i + 1 + hold_bars, len(candles))):
            c = candles[j]
            exit_ts = c.timestamp
            hit_stop = c.low <= stop
            exit_price = stop if hit_stop else c.close
            if hit_stop:
                outcome = "STOP_LOSS"
                break
            if j + 1 < len(candles) and asset_at(j) != picked:
                outcome = "SIGNAL_EXIT"
                break
        else:
            if exit_price is None:
                i += 1
                continue
        exit = (exit_price or entry) * (1 - slip)
        gross = (exit - entry) / entry
        net = gross - 2 * cost_rate - 2 * slip
        trades.append(
            TradeOutcome(
                entry_ts=candles[i + 1].timestamp,
                exit_ts=exit_ts,
                direction="LONG",
                entry_price=round(entry, 12),
                exit_price=round(exit, 12),
                gross_return=round(gross, 12),
                net_return=round(net, 12),
                outcome=outcome,
            )
        )
        i += hold_bars + 1  # non-overlapping by preregistration
    return trades


# Funding interval helpers re-exported for the batch driver (C5 tests bind
# 8h vs other intervals; see funding_units for the canonical contract).
__all__ += ["canon_funding_interval_s", "canon_rate_per_period"]
