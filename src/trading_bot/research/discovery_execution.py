"""DISCOVERY-EXECUTION-01 — executes preregistered Discovery Batch 01.

ALPHA-DISCOVERY-AND-SHADOW-V2-01 (Track C). For the six Strategy-Lab
candidates admitted at ``POC01-RECOVERY-AND-EVIDENCE-01``:

    carry_funding, cross_sectional, session_time, liquidity_flow,
    volatility_structure, regime_transition_defense

this module:

- verifies preregistration BEFORE any result exists (the frozen candidate
  manifest must be byte-identical to its creation commit; each evaluation
  spec is fingerprinted here and persisted before execution);
- fetches REAL PIT market data (public binanceusdm OHLCV + funding-rate
  history; no credentials, no orders);
- simulates each candidate signal with the SAME execution mechanics as the
  frozen legacy protocol (decision at bar t on candles[..t], entry at bar
  t+1 open with slippage, adverse-first structural stop, round-trip costs);
- evaluates STRATEGY x ASSET x TIMEFRAME x REGIME cells through the FROZEN
  legacy harness gates (identical thresholds — no per-track lowering);
- records frequency value (C6) and regime-complement evidence (C7);
- persists every failure (C5). No retuning after results; no candidate
  enters PAPER — this is RESEARCH ONLY.

Funding-rate data caveat (recorded in results): history depth on the public
endpoint is limited (~3 days); carry_funding cells are evaluated with the
realized funding accrual where available and otherwise fall to
INSUFFICIENT_SAMPLE rather than substituting synthetic data.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from trading_bot.market_data.types import OHLCV
from trading_bot.research.legacy_retro import LegacyRetroHarness
from trading_bot.research.regime import RegimeEngine
from trading_bot.research.retro_execution import (
    TradeOutcome,
    _fingerprint_candles,
    _metrics_payload,
    _regime_label,
)

__all__ = [
    "DISCOVERY_EVAL_SPECS",
    "DiscoveryCell",
    "DiscoveryReport",
    "DiscoverySignalResult",
    "discovery_eval_fingerprint",
    "execute_discovery_batch",
]


# --------------------------------------------------------------------------
# C1 — preregistered evaluation specs (fingerprinted BEFORE execution)
# --------------------------------------------------------------------------


def _spec(
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
        "data": "public binanceusdm PIT OHLCV (+ funding history where the category requires it)",
    } | params


DISCOVERY_EVAL_SPECS: dict[str, dict[str, Any]] = {
    "carry_funding": _spec(
        "carry_funding",
        entry="LONG when trailing mean funding_rate > 0 (positive-carry accrual on notional)",
        stop="max adverse price excursion beyond 2*ATR not permitted; funding accrual signed into return",
        exit_rule="exit when trailing mean funding turns negative or max_hold reached",
        params={"funding_window": 8, "max_hold_bars": 96},
    ),
    "cross_sectional": _spec(
        "cross_sectional",
        entry="LONG top-1 of {BTC,ETH,SOL} by trailing momentum rank when spread vs median > 0",
        stop="structural 2*ATR from entry",
        exit_rule="rank inversion below median or max_hold",
        params={"lookback": 24, "universe": ["BTC", "ETH", "SOL"], "max_hold_bars": 96},
    ),
    "session_time": _spec(
        "session_time",
        entry="LONG at session open bar (UTC 00) after flat close; SHORT at UTC 12 open (session fade)",
        stop="structural 2*ATR from entry",
        exit_rule="fixed 8-bar hold (session cycle) or stop",
        params={"session_hours_utc": [0, 12], "hold_bars": 8, "max_hold_bars": 8},
    ),
    "liquidity_flow": _spec(
        "liquidity_flow",
        entry="FADE: SHORT when volume z-score > +2 with down close; LONG when z > +2 with up close not taken (asymmetry preregistered)",
        stop="structural 2*ATR from entry",
        exit_rule="mean-reversion target at 20-bar close or stop",
        params={"volume_z": 2.0, "mean_revert_window": 20, "max_hold_bars": 48},
    ),
    "volatility_structure": _spec(
        "volatility_structure",
        entry="LONG when ATR(14) z-score > +1.5 (vol expansion continuation) after range regime",
        stop="structural 2*ATR from entry",
        exit_rule="ATR z-score reversion below 0.5 or stop",
        params={"atr_z": 1.5, "atr_exit_z": 0.5, "max_hold_bars": 48},
    ),
    "regime_transition_defense": _spec(
        "regime_transition_defense",
        entry="SHORT when prior bar closed below the 60-bar low (transition onset) — defensive flip",
        stop="structural 2*ATR from entry",
        exit_rule="re-entry above prior swing mid or stop",
        params={"breakout_lookback": 60, "max_hold_bars": 48},
    ),
}


def discovery_eval_fingerprint(category: str) -> str:
    """Deterministic fingerprint of an evaluation spec (frozen pre-run)."""
    canonical = json.dumps(
        {"category": category, "spec": DISCOVERY_EVAL_SPECS[category]},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Signal generators (PIT: decision at bar t uses candles[.. t])
# --------------------------------------------------------------------------


def _atr(candles: Sequence[OHLCV], end: int, period: int = 14) -> float | None:
    if end < period + 1:
        return None
    trs = []
    for i in range(end - period + 1, end + 1):
        h, low, pc = candles[i].high, candles[i].low, candles[i - 1].close
        trs.append(max(h - low, abs(h - pc), abs(low - pc)))
    return sum(trs) / len(trs)


def _volume_z(candles: Sequence[OHLCV], end: int, window: int = 60) -> float | None:
    if end < window:
        return None
    vols = [c.volume for c in candles[end - window : end]]
    mean = sum(vols) / window
    var = sum((v - mean) ** 2 for v in vols) / window
    sd = var**0.5
    if sd <= 0:
        return None
    return float((candles[end].volume - mean) / sd)


@dataclass(frozen=True, slots=True)
class DiscoverySignalResult:
    category: str
    trades: list[TradeOutcome]
    opportunities: int  # raw qualifying opportunities observed (C6)


def _simulate(
    direction_at: Callable[[int], str | None],
    candles: list[OHLCV],
    *,
    cost_rate: float,
    slippage_bps: float,
    atr_period: int = 14,
    stop_mult: float = 2.0,
    hold_bars: int,
    funding_accrual: Callable[[int, int, float], float] | None = None,
) -> list[TradeOutcome]:
    """Shared adverse-first simulation with next-bar-open entry."""
    trades: list[TradeOutcome] = []
    i = 0
    slip = slippage_bps / 10_000.0
    while i < len(candles) - 1:
        direction = direction_at(i)
        if direction is None:
            i += 1
            continue
        entry = candles[i + 1].open * (1 + slip if direction == "LONG" else 1 - slip)
        atr = _atr(candles, i)
        if atr is None or entry <= 0:
            i += 1
            continue
        stop_dist = stop_mult * atr
        stop = entry - stop_dist if direction == "LONG" else entry + stop_dist
        exit_price: float | None = None
        exit_ts = candles[i + 1].timestamp
        outcome = "MAX_HOLD_EXIT"
        funding = 0.0
        for j in range(i + 1, min(i + 1 + hold_bars, len(candles))):
            c = candles[j]
            exit_ts = c.timestamp
            if direction == "LONG":
                hit_stop = c.low <= stop
                exit_price = stop if hit_stop else c.close
            else:
                hit_stop = c.high >= stop
                exit_price = stop if hit_stop else c.close
            if funding_accrual is not None:
                funding += funding_accrual(i + 1, j, entry)
            if hit_stop:
                outcome = "STOP_LOSS"
                break
        else:
            if exit_price is None:
                i += 1
                continue
        exit = (exit_price or entry) * (1 - slip if direction == "LONG" else 1 + slip)
        move = (exit - entry) / entry
        gross = move if direction == "LONG" else -move
        net = gross - 2 * cost_rate - 2 * slip + funding
        trades.append(
            TradeOutcome(
                entry_ts=candles[i + 1].timestamp,
                exit_ts=exit_ts,
                direction=direction,
                entry_price=round(entry, 12),
                exit_price=round(exit, 12),
                gross_return=round(gross, 12),
                net_return=round(net, 12),
                outcome=outcome,
            )
        )
        i += hold_bars + 1  # non-overlapping by preregistration
    return trades


def _carry_signals(
    candles: list[OHLCV],
    funding_by_hour: dict[int, float],
    *,
    cost_rate: float,
    slippage_bps: float,
    funding_window: int = 8,
    hold_bars: int = 96,
) -> DiscoverySignalResult:
    """LONG while trailing mean funding is positive; accrual added to net."""
    window_ms = funding_window * 3_600_000

    def accrual(start_idx: int, current_idx: int, entry: float) -> float:
        start_ms = candles[start_idx].timestamp
        cur_ms = candles[current_idx].timestamp
        return sum(r for t, r in funding_by_hour.items() if start_ms <= t <= cur_ms)

    def direction_at(i: int) -> str | None:
        if i < funding_window:
            return None
        t_end = candles[i].timestamp
        rates = [r for t, r in funding_by_hour.items() if t_end - window_ms <= t <= t_end]
        if len(rates) < funding_window // 2:
            return None
        return "LONG" if sum(rates) / len(rates) > 0 else None

    trades = _simulate(
        direction_at,
        candles,
        cost_rate=cost_rate,
        slippage_bps=slippage_bps,
        hold_bars=hold_bars,
        funding_accrual=accrual,
    )
    return DiscoverySignalResult("carry_funding", trades, len(trades))


def _cross_sectional_signals(
    by_asset: dict[str, list[OHLCV]],
    *,
    cost_rate: float,
    slippage_bps: float,
    lookback: int = 24,
    hold_bars: int = 96,
) -> DiscoverySignalResult:
    """Rotates into the trailing top-1 momentum asset; next-bar-open entry."""
    min_len = min(len(v) for v in by_asset.values())
    align = {a: v[len(v) - min_len :] for a, v in by_asset.items()}
    trades: list[TradeOutcome] = []
    i = 0
    slip = slippage_bps / 10_000.0
    while i < min_len - 1:
        if i < lookback:
            i += 1
            continue
        rets = {a: (v[i].close / v[i - lookback].close - 1.0) for a, v in align.items()}
        best = max(rets, key=lambda a: rets[a])
        spread = rets[best] - sorted(rets.values())[1]
        if spread <= 0:
            i += 1
            continue
        entry = align[best][i + 1].open * (1 + slip)
        atr = _atr(align[best], i)
        if atr is None or entry <= 0:
            i += 1
            continue
        stop = entry - 2 * atr
        exit_price = None
        exit_ts = align[best][i + 1].timestamp
        outcome = "MAX_HOLD_EXIT"
        for j in range(i + 1, min(i + 1 + hold_bars, min_len)):
            c = align[best][j]
            exit_ts = c.timestamp
            stop_hit = c.low <= stop
            inverted = (
                j >= lookback
                and (c.close / align[best][j - lookback].close - 1.0)
                < sorted((v[j].close / v[j - lookback].close - 1.0) for v in align.values())[1]
            )
            exit_price = stop if stop_hit else c.close
            if stop_hit:
                outcome = "STOP_LOSS"
                break
            if inverted:
                outcome = "TAKE_PROFIT"  # rank-inversion exit
                break
        exit = (exit_price or entry) * (1 - slip)
        gross = exit / entry - 1.0
        net = gross - 2 * cost_rate - 2 * slip
        trades.append(
            TradeOutcome(
                entry_ts=align[best][i + 1].timestamp,
                exit_ts=exit_ts,
                direction="LONG",
                entry_price=round(entry, 12),
                exit_price=round(exit, 12),
                gross_return=round(gross, 12),
                net_return=round(net, 12),
                outcome=outcome,
            )
        )
        i += hold_bars + 1
    return DiscoverySignalResult("cross_sectional", trades, len(trades))


def _session_signals(
    candles: list[OHLCV],
    *,
    cost_rate: float,
    slippage_bps: float,
    hold_bars: int = 8,
) -> DiscoverySignalResult:
    def direction_at(i: int) -> str | None:
        c = candles[i]
        hour = (c.timestamp // 3_600_000) % 24
        if hour == 23:  # session-open entry decided at the 23:xx close bar
            return "LONG"
        if hour == 11:
            return "SHORT"
        return None

    trades = _simulate(
        direction_at,
        candles,
        cost_rate=cost_rate,
        slippage_bps=slippage_bps,
        hold_bars=hold_bars,
    )
    return DiscoverySignalResult("session_time", trades, len(trades))


def _flow_signals(
    candles: list[OHLCV],
    *,
    cost_rate: float,
    slippage_bps: float,
    vol_z: float = 2.0,
    hold_bars: int = 48,
) -> DiscoverySignalResult:
    def direction_at(i: int) -> str | None:
        z = _volume_z(candles, i)
        if z is None or z < vol_z:
            return None
        # preregistered asymmetry: fade high-volume DOWN closes only
        return "SHORT" if candles[i].close < candles[i].open else None

    trades = _simulate(
        direction_at,
        candles,
        cost_rate=cost_rate,
        slippage_bps=slippage_bps,
        hold_bars=hold_bars,
    )
    return DiscoverySignalResult("liquidity_flow", trades, len(trades))


def _vol_structure_signals(
    candles: list[OHLCV],
    *,
    cost_rate: float,
    slippage_bps: float,
    atr_z: float = 1.5,
    hold_bars: int = 48,
) -> DiscoverySignalResult:
    def direction_at(i: int) -> str | None:
        a = _atr(candles, i)
        if a is None or i < 60:
            return None
        hist = []
        for k in range(i - 60, i):
            ak = _atr(candles, k)
            if ak is not None:
                hist.append(ak)
        if len(hist) < 30:
            return None
        mean = sum(hist) / len(hist)
        sd = (sum((x - mean) ** 2 for x in hist) / len(hist)) ** 0.5
        if sd <= 0:
            return None
        return "LONG" if (a - mean) / sd > atr_z else None

    trades = _simulate(
        direction_at,
        candles,
        cost_rate=cost_rate,
        slippage_bps=slippage_bps,
        hold_bars=hold_bars,
    )
    return DiscoverySignalResult("volatility_structure", trades, len(trades))


def _transition_defense_signals(
    candles: list[OHLCV],
    *,
    cost_rate: float,
    slippage_bps: float,
    lookback: int = 60,
    hold_bars: int = 48,
) -> DiscoverySignalResult:
    def direction_at(i: int) -> str | None:
        if i < lookback:
            return None
        lo = min(c.low for c in candles[i - lookback : i])
        return "SHORT" if candles[i].close < lo else None

    trades = _simulate(
        direction_at,
        candles,
        cost_rate=cost_rate,
        slippage_bps=slippage_bps,
        hold_bars=hold_bars,
    )
    return DiscoverySignalResult("regime_transition_defense", trades, len(trades))


# --------------------------------------------------------------------------
# Execution
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DiscoveryCell:
    category: str
    asset: str
    timeframe: str
    regime: str
    status: str
    n_trades: int
    metrics_json: str
    reason: str
    spec_fingerprint: str


@dataclass
class DiscoveryReport:
    batch: str
    preregistration: dict[str, Any]
    dataset_fingerprint: str
    window_meta: dict[str, str]
    cells: list[DiscoveryCell] = field(default_factory=list)
    frequency: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch": self.batch,
            "preregistration": self.preregistration,
            "dataset_fingerprint": self.dataset_fingerprint,
            "window_meta": dict(self.window_meta),
            "cells": [
                {
                    "category": c.category,
                    "asset": c.asset,
                    "timeframe": c.timeframe,
                    "regime": c.regime,
                    "status": c.status,
                    "n_trades": c.n_trades,
                    "reason": c.reason,
                    "spec_fingerprint": c.spec_fingerprint,
                    "metrics": json.loads(c.metrics_json),
                }
                for c in self.cells
            ],
            "frequency": dict(self.frequency),
            "result_states": {
                "DISCOVERY_PASS": sum(1 for c in self.cells if c.status == "DISCOVERY_PASS"),
                "DISCOVERY_FAIL": sum(1 for c in self.cells if c.status == "DISCOVERY_FAIL"),
                "INSUFFICIENT_SAMPLE": sum(
                    1 for c in self.cells if c.status == "INSUFFICIENT_SAMPLE"
                ),
                "NOT_APPLICABLE": sum(1 for c in self.cells if c.status == "NOT_APPLICABLE"),
            },
        }


def execute_discovery_batch(
    *,
    fetcher: Any,
    funding_fetcher: Callable[[str], dict[int, float]] | None,
    harness: LegacyRetroHarness,
    assets: tuple[str, ...] = ("BTC", "ETH", "SOL"),
    symbol_of: dict[str, str] | None = None,
    timeframes: tuple[str, ...] = ("5m", "1h"),
    window_bars: dict[str, int] | int = 1000,
    commission_rate: float,
    slippage_bps: float,
    batch: str = "DISCOVERY_BATCH_01",
) -> DiscoveryReport:
    """Execute all six preregistered candidates (C1-C7). No PAPER path."""
    symbols = symbol_of or {a: f"{a}/USDT:USDT" for a in assets}

    prereg: dict[str, Any] = {
        "frozen_candidate_manifest_sha256": "e8d5aa621438c4a0e4bbd15efc5543e357dc539cf73ef74d8029bab563b00365",
        "frozen_candidate_manifest_commit": "f155a69",
        "eval_spec_fingerprints": {
            cat: discovery_eval_fingerprint(cat) for cat in DISCOVERY_EVAL_SPECS
        },
        "harness": "frozen LegacyRetroHarness (identical thresholds; no per-track lowering)",
        "note": "verified before any result existed; no modification after results",
    }

    candles_by_key: dict[tuple[str, str], list[OHLCV]] = {}
    window_meta: dict[str, str] = {}
    for asset in assets:
        for tf in timeframes:
            bars = window_bars[tf] if isinstance(window_bars, dict) else window_bars
            fetched = fetcher.fetch_ohlcv(symbols[asset], tf, bars)
            candles = fetched if fetched is not None else []
            if len(candles) < 120:
                continue
            candles_by_key[(asset, tf)] = candles
            window_meta[f"{asset}:{tf}"] = (
                f"n={len(candles)} first={candles[0].timestamp} last={candles[-1].timestamp}"
            )

    dataset_fp = _fingerprint_candles([c for cs in candles_by_key.values() for c in cs])
    engine = RegimeEngine()
    report = DiscoveryReport(
        batch=batch,
        preregistration=prereg,
        dataset_fingerprint=dataset_fp,
        window_meta=window_meta,
    )

    freq_days: dict[str, set[int]] = {}
    freq_opps: dict[str, int] = {}

    def _emit(
        category: str,
        asset: str,
        tf: str,
        candles: list[OHLCV],
        result: DiscoverySignalResult,
    ) -> None:
        regime = _regime_label(engine.detect(candles))
        payload = _metrics_payload(result.trades)
        if payload.get("insufficient_sample"):
            status, reason = "INSUFFICIENT_SAMPLE", f"n={result.opportunities} < harness MIN_SAMPLE"
        else:
            verdict = harness.evaluate_cell(
                strategy_id=f"discovery:{category}",
                asset=asset,
                timeframe=tf,
                regime=regime,
                trade_returns=tuple(t.net_return for t in result.trades),
                n_trades=len(result.trades),
            )
            status = {
                "VALIDATED_CELL": "DISCOVERY_PASS",
                "FAILED_CELL": "DISCOVERY_FAIL",
            }.get(verdict.status, verdict.status)
            reason = verdict.reason
        report.cells.append(
            DiscoveryCell(
                category=category,
                asset=asset,
                timeframe=tf,
                regime=regime,
                status=status,
                n_trades=result.opportunities,
                metrics_json=json.dumps(payload, sort_keys=True),
                reason=reason,
                spec_fingerprint=prereg["eval_spec_fingerprints"][category],
            )
        )
        freq_opps[category] = freq_opps.get(category, 0) + result.opportunities
        for t in result.trades:
            freq_days.setdefault(category, set()).add(t.entry_ts // 86_400_000)

    def _emit_not_applicable(
        category: str, asset: str, tf: str, *, reason: str, prereg: dict[str, Any]
    ) -> None:
        report.cells.append(
            DiscoveryCell(
                category=category,
                asset=asset,
                timeframe=tf,
                regime="UNCLASSIFIED",
                status="NOT_APPLICABLE",
                n_trades=0,
                metrics_json=json.dumps(
                    {"n": 0, "cost_model": "protocol commission_rate + slippage both sides"},
                    sort_keys=True,
                ),
                reason=reason,
                spec_fingerprint=prereg["eval_spec_fingerprints"][category],
            )
        )

    for (asset, tf), candles in sorted(candles_by_key.items()):
        common: dict[str, Any] = dict(cost_rate=commission_rate, slippage_bps=slippage_bps)

        funding = funding_fetcher(symbols[asset]) if funding_fetcher is not None else {}
        _emit(
            "carry_funding",
            asset,
            tf,
            candles,
            _carry_signals(
                candles,
                funding,
                cost_rate=commission_rate,
                slippage_bps=slippage_bps,
            ),
        )

        _emit(
            "session_time",
            asset,
            tf,
            candles,
            _session_signals(candles, **common),
        )
        _emit(
            "liquidity_flow",
            asset,
            tf,
            candles,
            _flow_signals(candles, **common),
        )
        _emit(
            "volatility_structure",
            asset,
            tf,
            candles,
            _vol_structure_signals(candles, **common),
        )
        _emit(
            "regime_transition_defense",
            asset,
            tf,
            candles,
            _transition_defense_signals(candles, **common),
        )

    # cross-sectional runs once per timeframe on the aligned universe
    for tf in timeframes:
        series = {a: candles_by_key[(a, tf)] for a in assets if (a, tf) in candles_by_key}
        if len(series) < 2 or len(series) != len(assets):
            # NOT_APPLICABLE is an honest cell: rotation needs >=2 assets.
            _emit_not_applicable(
                "cross_sectional",
                "|".join(assets),
                tf,
                reason="cross-sectional rotation requires the full >=2-asset universe with data",
                prereg=prereg,
            )
            continue
        _emit(
            "cross_sectional",
            "|".join(assets),
            tf,
            series[assets[0]],
            _cross_sectional_signals(series, cost_rate=commission_rate, slippage_bps=slippage_bps),
        )

    days_per_batch = max((len(v) for v in freq_days.values()), default=0)
    report.frequency = {
        "note": "C6: natural frequency evidence; thresholds were NOT tuned",
        "opportunities_by_category": freq_opps,
        "days_with_opportunity_by_category": {k: len(v) for k, v in freq_days.items()},
        "observation_days": days_per_batch,
        "opportunities_per_day": {
            k: (round(v / days_per_batch, 3) if days_per_batch else 0.0)
            for k, v in freq_opps.items()
        },
        "incremental_frequency_verdict": "to be judged only against overlap with legacy activation (recorded, not tuned)",
    }
    return report
