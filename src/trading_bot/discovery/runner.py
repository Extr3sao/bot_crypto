"""Discovery runner: evaluate symbol x family x regime x direction.

Reuses the existing canonical AlphaFamily universe and the existing
CommissionModel/SlippageModel cost semantics. PIT: every trade decision at
bar ``t`` uses only data up to ``t`` (signal generated at close of ``t``,
entry at the open of ``t+1`` plus slippage; stop/target checked from the
high/low of bars strictly after entry).

No parameter sweeps: each family runs its pre-registered, committed
parameter set (that IS the current strategy universe).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from trading_bot.market_data.types import OHLCV
from trading_bot.research.families import (
    BreakoutFamily,
    EmaCrossoverFamily,
    MeanReversionFamily,
    MomentumFamily,
    TrendFamily,
    VolatilityFamily,
)
from trading_bot.research.regime import RegimeEngine
from trading_bot.research.types import AlphaSignal

from .dataset import (
    FEE_RATE,
    SLIPPAGE_BPS,
    _ms,
)
from .split import SplitAccessor

FAMILIES: tuple[Any, ...] = (
    MomentumFamily,
    TrendFamily,
    BreakoutFamily,
    MeanReversionFamily,
    VolatilityFamily,
    EmaCrossoverFamily,
)

R_MULTIPLE_STOP = 2.0  # families emit structural stops; runner risk-units in R


@dataclass(frozen=True, slots=True)
class DiscoveryRun:
    family: str
    symbol: str
    regime: str
    direction: str
    trades: int
    wins: int
    losses: int
    win_rate: float
    gross_expectancy_r: float
    net_expectancy_r: float
    gross_pf: float
    net_pf: float
    gross_pnl_r: float
    fees_r: float
    slippage_r: float
    net_pnl_r: float
    max_drawdown_r: float
    trades_per_day: float
    stability_halves: dict[str, float]
    regime_concentration: float
    asset_concentration: float
    window: tuple[str, str]
    config_sha256: str

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "family": self.family,
            "symbol": self.symbol,
            "regime": self.regime,
            "direction": self.direction,
            "trades": self.trades,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": round(self.win_rate, 6),
            "gross_expectancy_r": round(self.gross_expectancy_r, 6),
            "net_expectancy_r": round(self.net_expectancy_r, 6),
            "gross_pf": round(self.gross_pf, 6),
            "net_pf": round(self.net_pf, 6),
            "gross_pnl_r": round(self.gross_pnl_r, 6),
            "fees_r": round(self.fees_r, 6),
            "slippage_r": round(self.slippage_r, 6),
            "net_pnl_r": round(self.net_pnl_r, 6),
            "max_drawdown_r": round(self.max_drawdown_r, 6),
            "trades_per_day": round(self.trades_per_day, 6),
            "stability_halves": {k: round(v, 6) for k, v in self.stability_halves.items()},
            "regime_concentration": round(self.regime_concentration, 6),
            "asset_concentration": round(self.asset_concentration, 6),
            "discovery_window": [self.window[0], self.window[1]],
            "config_sha256": self.config_sha256,
        }
        return data


@dataclass(frozen=True, slots=True)
class DiscoveryRunResult:
    runs: tuple[DiscoveryRun, ...]
    summary: dict[str, Any] = field(default_factory=dict)


def _family_instances() -> list[Any]:
    return [cls() for cls in FAMILIES]


def _regime_series(candles: list[OHLCV], *, stride: int = 12, lookback: int = 120) -> dict[int, str]:
    """Coarse regime label per sampled bar (trailing history only, PIT-safe).

    Regime is evaluated on a trailing window ending at the bar; sampled every
    ``stride`` bars and forward-filled for label lookup (a coarse context
    filter, never a signal input). ``stride`` is a fixed performance
    parameter of the harness, not a strategy parameter.
    """
    engine = RegimeEngine()
    labels: dict[int, str] = {}
    last_label = "MIXED"
    for index in range(len(candles)):
        if index % stride == 0 or index == len(candles) - 1:
            low = max(0, index - lookback)
            window = candles[low : index + 1]
            snapshot = engine.detect(window)
            last_label = str(snapshot.primary_regime or "MIXED")
        labels[candles[index].timestamp] = last_label
    return labels


def _risk_exit(
    stop_price: float,
    direction: str,
    bars: list[OHLCV],
) -> tuple[float, int, str] | None:
    """Walk bars forward; return (exit_price, bars_held, reason).

    Stop checks use bar high/low strictly AFTER the entry bar (PIT convention
    pinned by test_signal_uses_history_up_to_bar_entry_next_bar): adverse
    intra-entry-bar moves are never consulted for the entry decision. Cost
    modelling (slippage on entry, round-trip fees in R terms) is applied by
    the caller, which owns the entry price and stop distance.
    """
    for held, bar in enumerate(bars, start=1):
        if direction == "LONG":
            if bar.low <= stop_price:
                exit_price = min(stop_price, bar.open)  # conservative gap fill
                return exit_price, held, "stop"
        else:
            if bar.high >= stop_price:
                exit_price = max(stop_price, bar.open)
                return exit_price, held, "stop"
        # Time-stop: 36 bars (3h on 5m) — pre-registered, not tuned.
        if held >= 36:
            return bar.close, held, "time"
    return None


def _r_of(direction: str, entry: float, exit_price: float, stop_price: float) -> float:
    risk_per_unit = abs(entry - stop_price)
    if risk_per_unit <= 0:
        return 0.0
    raw = (exit_price - entry) if direction == "LONG" else (entry - exit_price)
    return raw / risk_per_unit


def evaluate_combo(
    accessor: SplitAccessor,
    *,
    family_name: str,
    symbol: str,
    regime_filter: str,
    direction_filter: str,
) -> DiscoveryRun:
    """Evaluate one (family, symbol, regime, direction) combination.

    Reads ONLY the discovery window through the accessor (locked windows
    raise). Costs: taker fee both sides + flat slippage on entry, expressed
    in R (risk units) using the family's structural stop.
    """

    candles = accessor.read(symbol, "discovery")
    if not candles:
        raise ValueError(f"no discovery candles for {symbol}")
    windows = accessor.windows

    instances = {inst.family_name: inst for inst in _family_instances()}
    family = instances.get(family_name)
    if family is None:
        raise ValueError(f"unknown family: {family_name}")

    regimes = _regime_series(candles)
    regime_at = regimes

    # Prefilter by regime: only bars whose trailing primary regime matches.
    if regime_filter != "ALL":
        allowed_ts = {ts for ts, label in regimes.items() if label == regime_filter}
    else:
        allowed_ts = {c.timestamp for c in candles}

    gross_rs: list[float] = []
    fee_rs: list[float] = []
    slip_rs: list[float] = []
    entry_ts: list[int] = []
    exit_reasons: list[str] = []
    half1_rs: list[float] = []
    half2_rs: list[float] = []
    discovery_mid_ms = _ms(windows.discovery_start) + (
        _ms(windows.discovery_end_exclusive) - _ms(windows.discovery_start)
    ) // 2

    max_signal_index = len(candles) - 2  # need t+1 for entry
    for index in range(1, max_signal_index):
        bar = candles[index]
        if bar.timestamp not in allowed_ts:
            continue
        history = candles[: index + 1]
        signals: list[AlphaSignal] = family.generate(history, {}, None)
        wanted = direction_filter.upper()
        signal = next(
            (s for s in signals if s.direction == wanted and s.timestamp == bar.timestamp),
            None,
        )
        if signal is None:
            continue
        entry_bar = candles[index + 1]
        stop = signal.structural_stop
        if stop is None or stop <= 0 or stop == entry_bar.open:
            continue
        outcome = _risk_exit(
            stop,
            wanted,
            candles[index + 2 :],
        )
        if outcome is None:
            continue
        exit_price, _held, reason = outcome
        slip = SLIPPAGE_BPS / 10_000.0
        eff_entry = entry_bar.open * (1 + slip) if wanted == "LONG" else entry_bar.open * (1 - slip)
        gross_r = _r_of(wanted, eff_entry, exit_price, stop)
        # Fees in R: round-trip notional cost relative to 1R risk.
        fee_r = (2 * FEE_RATE * eff_entry) / abs(eff_entry - stop)
        slip_r = abs(abs(eff_entry - entry_bar.open)) / abs(eff_entry - stop)
        gross_rs.append(gross_r)
        fee_rs.append(fee_r)
        slip_rs.append(slip_r)
        entry_ts.append(bar.timestamp)
        exit_reasons.append(reason)
        if bar.timestamp < discovery_mid_ms:
            half1_rs.append(gross_r - fee_r - slip_r)
        else:
            half2_rs.append(gross_r - fee_r - slip_r)

    net_rs = [g - f - s for g, f, s in zip(gross_rs, fee_rs, slip_rs, strict=True)]
    n = len(net_rs)
    days = max(
        (max(entry_ts) - min(entry_ts)) / 86_400_000, 1e-9
    ) if entry_ts else 0.0

    def _pf(values: list[float]) -> float:
        gains = sum(v for v in values if v > 0)
        losses = -sum(v for v in values if v < 0)
        if losses <= 0:
            return float("inf") if gains > 0 else 0.0
        return gains / losses

    def _mean(values: list[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for value in net_rs:
        equity += value
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

    regime_counts: dict[str, int] = {}
    for ts in entry_ts:
        label = regime_at.get(ts, "MIXED")
        regime_counts[label] = regime_counts.get(label, 0) + 1
    total_entries = max(len(entry_ts), 1)
    regime_concentration = (
        max(regime_counts.values()) / total_entries if regime_counts else 0.0
    )

    wins = sum(1 for v in net_rs if v > 0)
    losses = sum(1 for v in net_rs if v < 0)
    config_hash = json.dumps(
        {
            "family": family_name,
            "symbol": symbol,
            "regime": regime_filter,
            "direction": direction_filter,
            "fee_rate": FEE_RATE,
            "slippage_bps": SLIPPAGE_BPS,
            "time_stop_bars": 36,
            "params": "pre-registered committed family parameters",
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    import hashlib

    return DiscoveryRun(
        family=family_name,
        symbol=symbol,
        regime=regime_filter,
        direction=direction_filter,
        trades=n,
        wins=wins,
        losses=losses,
        win_rate=wins / n if n else 0.0,
        gross_expectancy_r=_mean(gross_rs),
        net_expectancy_r=_mean(net_rs),
        gross_pf=_pf(gross_rs),
        net_pf=_pf(net_rs),
        gross_pnl_r=sum(gross_rs),
        fees_r=sum(fee_rs),
        slippage_r=sum(slip_rs),
        net_pnl_r=sum(net_rs),
        max_drawdown_r=max_dd,
        trades_per_day=(n / days) if days else 0.0,
        stability_halves={
            "h1_net_exp_r": _mean(half1_rs),
            "h2_net_exp_r": _mean(half2_rs),
        },
        regime_concentration=regime_concentration,
        asset_concentration=1.0,  # one symbol per run by design
        window=(
            windows.discovery_start.isoformat(),
            windows.discovery_end_exclusive.isoformat(),
        ),
        config_sha256=hashlib.sha256(config_hash).hexdigest(),
    )


def run_discovery(
    accessor: SplitAccessor,
    *,
    symbols: tuple[str, ...],
    regime_filters: tuple[str, ...] = ("ALL",),
    directions: tuple[str, ...] = ("LONG", "SHORT"),
    min_trades: int = 30,
) -> DiscoveryRunResult:
    """Run the full pre-registered grid over the discovery slice only."""
    runs: list[DiscoveryRun] = []
    instances = _family_instances()
    for symbol in symbols:
        for inst in instances:
            for regime in regime_filters:
                for direction in directions:
                    runs.append(
                        evaluate_combo(
                            accessor,
                            family_name=inst.family_name,
                            symbol=symbol,
                            regime_filter=regime,
                            direction_filter=direction,
                        )
                    )
    evaluated = [r for r in runs if r.trades >= min_trades]
    summary = {
        "combos_attempted": len(runs),
        "combos_with_min_trades": len(evaluated),
        "min_trades_threshold": min_trades,
        "evaluated_at": datetime.now(tz=UTC).isoformat(),
    }
    return DiscoveryRunResult(runs=tuple(runs), summary=summary)
