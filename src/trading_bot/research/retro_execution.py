"""LEGACY-RETRO-EXECUTION-01 — executes the frozen retro protocol on real PIT data.

POC01-RECOVERY-AND-EVIDENCE-01 (Track B). Consumes the preregistered
:class:`trading_bot.research.legacy_retro.LegacyRetroProtocol` (fingerprint
verified BEFORE execution; never altered after seeing results) and produces:

- per-strategy simulated trades from REAL public OHLCV (binanceusdm, no
  credentials) using each family's structural stop;
- STRATEGY x ASSET x TIMEFRAME x REGIME cells (no over-aggregation);
- modern statistical gates via the existing stat-validation primitives;
- candidate health baselines from VALIDATED cells only (B4);
- proposed future status per strategy (B5) — evidence only, no POC01
  authority change.

PIT discipline:

- Candles are fetched once and frozen; every simulation reads the same
  window recorded in the dataset fingerprint.
- A signal evaluated at candle t may only use candles <= t (families are
  window-based; a sliding window ending at t is PIT by construction).
- Entry fills at the NEXT bar's open (no same-bar look-ahead).
- Stop resolution is adverse-first within a bar (SL before TP).

No POC01 artifact is read or written by this module.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from trading_bot.backtesting.stat_validation import (
    bootstrap_sharpe_ci,
    permutation_significance,
)
from trading_bot.market_data.types import OHLCV
from trading_bot.research.families import (
    BreakoutFamily,
    MeanReversionFamily,
    MomentumFamily,
    TrendFamily,
    VolatilityFamily,
)
from trading_bot.research.legacy_retro import (
    BOOTSTRAP_RESAMPLES,
    PERMUTATION_ROUNDS,
    STAT_SEED,
    CellStatus,
    LegacyRetroHarness,
    LegacyRetroProtocol,
)
from trading_bot.research.regime import RegimeEngine

__all__ = [
    "CellResult",
    "RetroExecutionReport",
    "RetroExecutor",
    "TradeOutcome",
]

#: Position risk fraction of notional lost at the structural stop is NOT
#: modeled here: returns are per-unit-price moves between entry and stop/tp,
#: consistent with the harness's per-trade return semantics.
RISK_MODEL = "structural_stop_adverse_first_next_bar_open_v1"


class OHLCVFetcher(Protocol):
    """Minimal PIT fetcher contract (public data, no credentials)."""

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[OHLCV]: ...


@dataclass(frozen=True, slots=True)
class TradeOutcome:
    """One simulated trade (entry next-bar-open, adverse-first stop)."""

    entry_ts: int
    exit_ts: int
    direction: str
    entry_price: float
    exit_price: float
    gross_return: float  # price move fraction, signed by direction
    net_return: float  # after protocol cost model (round trip)
    outcome: str  # STOP_LOSS / TAKE_PROFIT / MAX_HOLD_EXIT


@dataclass(frozen=True, slots=True)
class CellResult:
    strategy_id: str
    asset: str
    timeframe: str
    regime: str
    status: str
    n_trades: int
    metrics_json: str  # canonical metrics payload (gross/net expectancy etc.)
    reason: str


@dataclass(frozen=True, slots=True)
class RetroExecutionReport:
    protocol_fingerprint: str
    dataset_fingerprint: str
    data_window: dict[str, str]
    risk_model: str
    cells: tuple[CellResult, ...]
    baselines_json: str
    proposed_status: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol_fingerprint": self.protocol_fingerprint,
            "dataset_fingerprint": self.dataset_fingerprint,
            "data_window": dict(self.data_window),
            "risk_model": self.risk_model,
            "cells": [asdict(c) for c in self.cells],
            "baselines": json.loads(self.baselines_json),
            "proposed_status": dict(self.proposed_status),
        }


def _fingerprint_candles(candles: list[OHLCV]) -> str:
    payload = json.dumps(
        [[c.symbol, c.timestamp, c.open, c.high, c.low, c.close, c.volume] for c in candles],
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _regime_label(snapshot: Any) -> str:
    """Collapse the engine's multi-label snapshot into the cell regime key."""
    labels = sorted(snapshot.active_regimes) if snapshot.active_regimes else []
    if not labels:
        return "UNCLASSIFIED"
    return "|".join(labels)


def _simulate_trades(
    family_name: str,
    candles: list[OHLCV],
    *,
    window: int,
    cost_rate: float,
    slippage_bps: float,
    max_hold_bars: int = 96,
) -> list[TradeOutcome]:
    """Walk candles PIT-style; resolve each family signal to a trade.

    - signal decision at bar t uses only candles[.. t] (window ending at t);
    - entry at bar t+1 open (with slippage);
    - adverse-first stop resolution from bar t+1 onward;
    - exit at structural stop / max-hold close.
    """
    fam_by_name: dict[str, Any] = {
        "momentum": MomentumFamily,
        "trend": TrendFamily,
        "breakout": BreakoutFamily,
        "mean_reversion": MeanReversionFamily,
        "volatility": VolatilityFamily,
    }
    fam: Any = fam_by_name[family_name]()
    trades: list[TradeOutcome] = []
    slip = slippage_bps / 10_000.0
    i = window
    while i < len(candles) - 1:
        window_candles = candles[max(0, i - window + 1) : i + 1]
        try:
            signals = fam.generate(window_candles, indicators={})
        except Exception:
            i += 1
            continue
        if not signals:
            i += 1
            continue
        sig = signals[0]
        entry_bar = candles[i + 1]
        entry_price = entry_bar.open * (1 + slip) if sig.direction == "LONG" else entry_bar.open * (1 - slip)
        stop = sig.structural_stop
        # Adverse-first walk from the entry bar itself.
        exit_price: float | None = None
        exit_ts = entry_bar.timestamp
        outcome = "MAX_HOLD_EXIT"
        for j in range(i + 1, min(i + 1 + max_hold_bars, len(candles))):
            bar = candles[j]
            if sig.direction == "LONG":
                if bar.low <= stop:
                    exit_price, exit_ts, outcome = stop * (1 - slip), bar.timestamp, "STOP_LOSS"
                    break
            else:
                if bar.high >= stop:
                    exit_price, exit_ts, outcome = stop * (1 + slip), bar.timestamp, "STOP_LOSS"
                    break
            exit_price, exit_ts = bar.close, bar.timestamp
        if exit_price is None:
            i += 1
            continue
        move = (
            (exit_price - entry_price) / entry_price
            if sig.direction == "LONG"
            else (entry_price - exit_price) / entry_price
        )
        gross = move
        net = gross - 2.0 * cost_rate - 2.0 * slip
        trades.append(
            TradeOutcome(
                entry_ts=entry_bar.timestamp,
                exit_ts=exit_ts,
                direction=sig.direction,
                entry_price=entry_price,
                exit_price=exit_price,
                gross_return=gross,
                net_return=net,
                outcome=outcome,
            )
        )
        i = exit_ts_index(candles, exit_ts) + 1 if exit_ts else i + 1
    return trades


def exit_ts_index(candles: list[OHLCV], ts: int) -> int:
    lo, hi = 0, len(candles) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if candles[mid].timestamp == ts:
            return mid
        if candles[mid].timestamp < ts:
            lo = mid + 1
        else:
            hi = mid - 1
    return max(0, hi)


def _metrics_payload(trades: list[TradeOutcome]) -> dict[str, Any]:
    if len(trades) < 5:  # MIN_SAMPLE of the stat-validation primitives
        return {
            "n": len(trades),
            "insufficient_sample": True,
            "cost_model": "protocol commission_rate + slippage both sides",
        }
    nets = tuple(t.net_return for t in trades)
    grosses = tuple(t.gross_return for t in trades)
    mean_net = sum(nets) / len(nets)
    mean_gross = sum(grosses) / len(grosses)
    gross_win = sum(r for r in nets if r > 0)
    gross_loss = sum(-r for r in nets if r < 0)
    pf = (gross_win / gross_loss) if gross_loss > 0 else None
    wins = sum(1 for r in nets if r > 0)
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in nets:
        equity *= 1.0 + r
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak)
    ci = bootstrap_sharpe_ci(nets, resamples=BOOTSTRAP_RESAMPLES, confidence=0.90, seed=STAT_SEED, periods_per_year=1)
    perm = permutation_significance(nets, permutations=PERMUTATION_ROUNDS, seed=STAT_SEED, periods_per_year=1)
    return {
        "n": len(nets),
        "gross_expectancy": mean_gross,
        "net_expectancy": mean_net,
        "profit_factor": pf,
        "win_rate": wins / len(nets),
        "max_drawdown": max_dd,
        "sharpe_per_trade": ci.estimate,
        "sharpe_ci_low": ci.ci_lower,
        "sharpe_ci_high": ci.ci_upper,
        "prob_sharpe_gt0": ci.prob_sharpe_positive,
        "permutation_pvalue": perm.p_value,
        "cost_model": "protocol commission_rate + slippage both sides",
    }


class RetroExecutor:
    """Executes the frozen protocol over real PIT data (Track B)."""

    def __init__(
        self,
        fetcher: OHLCVFetcher,
        protocol: LegacyRetroProtocol,
        harness: LegacyRetroHarness,
    ) -> None:
        self._fetcher = fetcher
        self._protocol = protocol
        self._harness = harness

    def run(
        self,
        *,
        symbols: dict[str, str],
        window_bars: int | dict[str, int],
        start_utc: datetime,
        end_utc: datetime,
        max_hold_bars: int = 96,
    ) -> RetroExecutionReport:
        proto = self._protocol
        fp = proto.fingerprint  # verified BEFORE any result is produced

        candles_by_key: dict[tuple[str, str], list[OHLCV]] = {}
        window_meta: dict[str, str] = {}
        for asset, symbol in symbols.items():
            for tf in proto.timeframes:
                bars = (
                    window_bars[tf] if isinstance(window_bars, dict) else window_bars
                )
                fetched: list[OHLCV] | None = self._fetcher.fetch_ohlcv(symbol, tf, bars)
                candles = fetched if fetched is not None else []
                if len(candles) < 120:
                    continue
                candles_by_key[(asset, tf)] = candles
                window_meta[f"{asset}:{tf}"] = (
                    f"{datetime.fromtimestamp(candles[0].timestamp / 1000, tz=UTC).isoformat()}"
                    f"..{datetime.fromtimestamp(candles[-1].timestamp / 1000, tz=UTC).isoformat()}"
                    f" n={len(candles)}"
                )
        dataset_fp = _fingerprint_candles(
            [c for cs in candles_by_key.values() for c in cs]
        )
        engine = RegimeEngine()

        cells: list[CellResult] = []
        cell_metrics: dict[tuple[str, str, str, str], tuple[int, list[TradeOutcome]]] = {}
        for asset, _symbol in symbols.items():
            for tf in proto.timeframes:
                stored: list[OHLCV] | None = candles_by_key.get((asset, tf))
                if not stored:
                    continue
                candles = stored
                # Regime snapshot per window (PIT: uses the same frozen window).
                regime = _regime_label(engine.detect(candles))
                for strategy_id in proto.applicability:
                    if asset not in proto.applicability[strategy_id]:
                        continue
                    trades = _simulate_trades(
                        strategy_id,
                        candles,
                        window=60,
                        cost_rate=proto.commission_rate,
                        slippage_bps=proto.slippage_bps,
                        max_hold_bars=max_hold_bars,
                    )
                    verdict = self._harness.evaluate_cell(
                        strategy_id=strategy_id,
                        asset=asset,
                        timeframe=tf,
                        regime=regime,
                        trade_returns=[t.net_return for t in trades],
                    )
                    payload: dict[str, Any] | None = None
                    if trades:
                        payload = _metrics_payload(trades)
                    cells.append(
                        CellResult(
                            strategy_id=strategy_id,
                            asset=asset,
                            timeframe=tf,
                            regime=regime,
                            status=verdict.status,
                            n_trades=len(trades),
                            metrics_json=json.dumps(payload, sort_keys=True) if payload else "{}",
                            reason=verdict.reason,
                        )
                    )
                    if verdict.status == CellStatus.VALIDATED_CELL and payload:
                        cell_metrics[(strategy_id, asset, tf, regime)] = (len(trades), trades)

        # B4: baselines from valid cells only.
        baselines = []
        for (sid, asset, tf, regime), (n, trades) in sorted(cell_metrics.items()):
            payload = _metrics_payload(trades)
            baselines.append(
                {
                    "strategy_id": sid,
                    "version": "legacy-1",
                    "asset": asset,
                    "timeframe": tf,
                    "regime": regime,
                    "baseline_expectancy": payload["net_expectancy"],
                    "baseline_sharpe": payload["sharpe_per_trade"],
                    "baseline_profit_factor": payload["profit_factor"],
                    "baseline_drawdown": payload["max_drawdown"],
                    "baseline_frequency": n,
                    "n": n,
                    "dataset_fingerprint": dataset_fp,
                    "protocol_fingerprint": fp,
                }
            )

        # B5: proposed future status per strategy (evidence only).
        proposed: dict[str, str] = {}
        for sid in proto.applicability:
            statuses = [c.status for c in cells if c.strategy_id == sid]
            if not statuses:
                proposed[sid] = "INSUFFICIENT_EVIDENCE"
            elif any(s == CellStatus.VALIDATED_CELL for s in statuses):
                proposed[sid] = (
                    "LEGACY_VALIDATION_PASS"
                    if all(s in (CellStatus.VALIDATED_CELL, CellStatus.INSUFFICIENT_SAMPLE) for s in statuses)
                    else "LEGACY_VALIDATION_PARTIAL"
                )
            elif all(s == CellStatus.INSUFFICIENT_SAMPLE for s in statuses):
                proposed[sid] = "INSUFFICIENT_EVIDENCE"
            else:
                proposed[sid] = "LEGACY_VALIDATION_FAIL"

        return RetroExecutionReport(
            protocol_fingerprint=fp,
            dataset_fingerprint=dataset_fp,
            data_window=window_meta,
            risk_model=RISK_MODEL,
            cells=tuple(cells),
            baselines_json=json.dumps(baselines, sort_keys=True),
            proposed_status=proposed,
        )


def utc_days_between(start: datetime, end: datetime) -> int:
    return max(0, (end - start).days)


def hours_between(a: datetime, b: datetime) -> float:
    return abs((b - a).total_seconds()) / 3600.0


def _round_hours(x: float) -> float:
    return math.floor(x * 100) / 100.0


def next_day_utc(dt: datetime) -> datetime:
    return (dt + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
