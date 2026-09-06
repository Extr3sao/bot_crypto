"""Discovery runner: evaluate symbol x family x regime x direction.

Reuses the existing canonical AlphaFamily universe and the existing
CommissionModel/SlippageModel cost semantics. PIT: every trade decision at
bar ``t`` uses only data up to ``t`` (signal generated at close of ``t``,
entry at the open of ``t+1`` plus slippage; stop/target checked from the
high/low of bars strictly after entry).

No parameter sweeps: each family runs its pre-registered, committed
parameter set (that IS the current strategy universe).

Edge-sanity semantics (R1): one position per combo at a time (signals while
a trade is open are skipped, so trades never overlap); slippage is applied
to entry AND exit; every trade is recorded in a TradeLedger so expectancy
can be recomputed independently; a trade that never exits inside the
window is excluded.
"""

from __future__ import annotations

import itertools
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
_DEFAULT_REGIME_LABELS = frozenset({"MIXED"})  # engine default bucket, not informative


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
    temporal_concentration: float = 0.0
    stability_thirds: dict[str, float] = field(default_factory=dict)

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
            "stability_thirds": {k: round(v, 6) for k, v in self.stability_thirds.items()},
            "regime_concentration": round(self.regime_concentration, 6),
            "asset_concentration": round(self.asset_concentration, 6),
            "temporal_concentration": round(self.temporal_concentration, 6),
            "discovery_window": [self.window[0], self.window[1]],
            "config_sha256": self.config_sha256,
        }
        return data


@dataclass(frozen=True, slots=True)
class TradeRecord:
    """One simulated trade with every ingredient of its R computation."""

    family: str
    symbol: str
    direction: str
    entry_signal_ts: int  # bar whose close generated the signal (PIT)
    entry_ts: int  # execution bar open (t+1)
    exit_ts: int
    held_bars: int
    entry_price: float  # raw execution price (entry bar open)
    eff_entry_price: float  # after entry slippage
    exit_price: float  # raw exit price
    eff_exit_price: float  # after exit slippage
    stop_price: float
    risk_per_unit: float  # |eff_entry - stop|, frozen at entry
    gross_r: float
    fee_r: float
    slippage_r: float
    net_r: float
    exit_reason: str
    regime_label: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "symbol": self.symbol,
            "direction": self.direction,
            "entry_signal_ts": self.entry_signal_ts,
            "entry_ts": self.entry_ts,
            "exit_ts": self.exit_ts,
            "held_bars": self.held_bars,
            "entry_price": self.entry_price,
            "eff_entry_price": self.eff_entry_price,
            "exit_price": self.exit_price,
            "eff_exit_price": self.eff_exit_price,
            "stop_price": self.stop_price,
            "risk_per_unit": self.risk_per_unit,
            "gross_r": round(self.gross_r, 9),
            "fee_r": round(self.fee_r, 9),
            "slippage_r": round(self.slippage_r, 9),
            "net_r": round(self.net_r, 9),
            "exit_reason": self.exit_reason,
            "regime_label": self.regime_label,
        }


@dataclass(frozen=True, slots=True)
class TradeLedger:
    """Full per-trade ledger of one combo (independent audit input)."""

    symbol: str
    family: str
    trades: tuple[TradeRecord, ...]

    def net_expectancy_r(self) -> float:
        return sum(t.net_r for t in self.trades) / len(self.trades) if self.trades else 0.0

    def has_overlap(self) -> bool:
        """True if any two trades overlap in time (impossible under the
        single-position policy; kept as an explicit audit check)."""
        ordered = sorted(self.trades, key=lambda t: t.entry_ts)
        return any(
            b.entry_ts <= a.exit_ts for a, b in itertools.pairwise(ordered)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "family": self.family,
            "trades": len(self.trades),
            "overlap": self.has_overlap(),
            "net_expectancy_r_recomputed": round(self.net_expectancy_r(), 9),
            "records": [t.to_dict() for t in self.trades],
        }


@dataclass(frozen=True, slots=True)
class DiscoveryRunResult:
    runs: tuple[DiscoveryRun, ...]
    summary: dict[str, Any] = field(default_factory=dict)
    ledgers: tuple[TradeLedger, ...] = ()


def _family_instances() -> list[Any]:
    return [cls() for cls in FAMILIES]


def _regime_series(candles: list[OHLCV], *, stride: int = 12, lookback: int = 120) -> dict[int, str]:
    """Coarse regime label per sampled bar (trailing history only, PIT-safe).

    Regime is evaluated on a trailing window ending at the bar; sampled every
    ``stride`` bars and forward-filled for label lookup (a coarse context
    filter, never a signal input). ``stride`` is a fixed performance
    parameter of the harness, not a strategy parameter.

    Note (R1 audit): the canonical engine labels most real-market bars
    "MIXED"; concentration metrics exclude the default bucket (see
    ``_DEFAULT_REGIME_LABELS``) so the regime gate measures niche dependence,
    not label prevalence.
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


def evaluate_combo_with_ledger(
    accessor: SplitAccessor,
    *,
    family_name: str,
    symbol: str,
    regime_filter: str,
    direction_filter: str,
) -> tuple[DiscoveryRun, TradeLedger]:
    """Evaluate one (family, symbol, regime, direction) combination.

    Reads ONLY the discovery window through the accessor (locked windows
    raise). Costs: taker fee per side (entry + exit) and slippage on entry
    AND exit, expressed in R (risk units) using the family's structural
    stop. Single-position policy: no overlapping trades; a trade that never
    exits inside the window is excluded. Returns the metrics plus the full
    TradeLedger for independent recomputation.
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

    half1_rs: list[float] = []
    half2_rs: list[float] = []
    trades: list[TradeRecord] = []
    discovery_mid_ms = _ms(windows.discovery_start) + (
        _ms(windows.discovery_end_exclusive) - _ms(windows.discovery_start)
    ) // 2

    # -- trade simulation under the single-position policy -------------------
    # Overlap/capital semantics (edge-sanity audit, R1): one position at a
    # time. While a trade is open, further signals of this combo are skipped;
    # a new trade may enter only after the previous one has closed. One
    # signal produces at most one trade (structural duplicate prevention).
    max_signal_index = len(candles) - 2  # need t+1 for entry
    position_open_until = -1  # exclusive index bound while a position is open
    wanted = direction_filter.upper()
    for index in range(1, max_signal_index):
        if index < position_open_until:
            continue  # single-position policy: no overlapping trades
        bar = candles[index]
        if bar.timestamp not in allowed_ts:
            continue
        history = candles[: index + 1]
        signals: list[AlphaSignal] = family.generate(history, {}, None)
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
            continue  # trade never closed inside the window: excluded
        exit_price, held, reason = outcome
        exit_ts = candles[index + held + 1].timestamp
        slip = SLIPPAGE_BPS / 10_000.0
        eff_entry = entry_bar.open * (1 + slip) if wanted == "LONG" else entry_bar.open * (1 - slip)
        eff_exit = exit_price * (1 - slip) if wanted == "LONG" else exit_price * (1 + slip)
        risk_per_unit = abs(eff_entry - stop)  # initial risk, frozen at entry
        if risk_per_unit <= 0:
            continue
        gross_r = _r_of(wanted, eff_entry, eff_exit, stop)
        # Fees in R: entry-side + exit-side notional cost relative to 1R risk.
        fee_r = (2 * FEE_RATE * eff_entry) / risk_per_unit
        slip_r = abs(abs(eff_entry - entry_bar.open)) / risk_per_unit
        net_r = gross_r - fee_r - slip_r
        position_open_until = index + held + 2  # reopen on the bar AFTER the exit bar
        trades.append(
            TradeRecord(
                family=family_name,
                symbol=symbol,
                direction=wanted,
                entry_signal_ts=bar.timestamp,
                entry_ts=entry_bar.timestamp,
                exit_ts=exit_ts,
                held_bars=held,
                entry_price=entry_bar.open,
                eff_entry_price=eff_entry,
                exit_price=exit_price,
                eff_exit_price=eff_exit,
                stop_price=stop,
                risk_per_unit=risk_per_unit,
                gross_r=gross_r,
                fee_r=fee_r,
                slippage_r=slip_r,
                net_r=net_r,
                exit_reason=reason,
                regime_label=regime_at.get(bar.timestamp, "MIXED"),
            )
        )
        if bar.timestamp < discovery_mid_ms:
            half1_rs.append(net_r)
        else:
            half2_rs.append(net_r)

    gross_rs = [t.gross_r for t in trades]
    fee_rs = [t.fee_r for t in trades]
    slip_rs = [t.slippage_r for t in trades]
    entry_ts = [t.entry_signal_ts for t in trades]

    net_rs = [t.net_r for t in trades]
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
    # Regime concentration must measure dependence on NARROW (informative)
    # regimes. The canonical engine labels most bars "MIXED" on real data, so
    # counting the default label would degenerate every ALL-filter run to
    # ~1.0 (measurement artifact, not edge information — R1 audit finding).
    # Concentration is therefore the max share over informative labels only;
    # an all-MIXED run has 0.0 (edge spread across the generic regime).
    informative_shares = [
        v / total_entries
        for label, v in regime_counts.items()
        if label not in _DEFAULT_REGIME_LABELS
    ]
    regime_concentration = max(informative_shares, default=0.0)

    # Audit metrics (R1): multi-subperiod stability (thirds) + temporal
    # concentration (largest gap between consecutive trade entries relative
    # to the traded span, including the edges of the discovery window).
    stability_thirds: dict[str, float] = {}
    temporal_concentration = 0.0
    if trades:
        lo = min(t.entry_signal_ts for t in trades)
        hi = max(t.entry_signal_ts for t in trades)
        third = max((hi - lo) / 3, 1)
        bounds = ((lo, lo + third), (lo + third, lo + 2 * third), (lo + 2 * third, hi + 1))
        for name, (lo_b, hi_b) in zip(("t1", "t2", "t3"), bounds, strict=True):
            vals = [t.net_r for t in trades if lo_b <= t.entry_signal_ts < hi_b]
            stability_thirds[f"{name}_net_exp_r"] = _mean(vals)
        ordered_ts = sorted(t.entry_signal_ts for t in trades)
        span = max(hi - lo, 1)
        edge_gaps = [
            (ordered_ts[0] - _ms(windows.discovery_start)) / span,
            (_ms(windows.discovery_end_exclusive) - ordered_ts[-1]) / span,
        ]
        inner_gaps = [(b - a) / span for a, b in itertools.pairwise(ordered_ts)]
        temporal_concentration = max([*edge_gaps, *inner_gaps])

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
        temporal_concentration=temporal_concentration,
        window=(
            windows.discovery_start.isoformat(),
            windows.discovery_end_exclusive.isoformat(),
        ),
        config_sha256=hashlib.sha256(config_hash).hexdigest(),
        stability_thirds=stability_thirds,
    ), TradeLedger(symbol=symbol, family=family_name, trades=tuple(trades))


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
    ledgers: list[TradeLedger] = []
    instances = _family_instances()
    for symbol in symbols:
        for inst in instances:
            for regime in regime_filters:
                for direction in directions:
                    run, ledger = evaluate_combo_with_ledger(
                        accessor,
                        family_name=inst.family_name,
                        symbol=symbol,
                        regime_filter=regime,
                        direction_filter=direction,
                    )
                    runs.append(run)
                    ledgers.append(ledger)
    evaluated = [r for r in runs if r.trades >= min_trades]
    summary = {
        "combos_attempted": len(runs),
        "combos_with_min_trades": len(evaluated),
        "min_trades_threshold": min_trades,
        "evaluated_at": datetime.now(tz=UTC).isoformat(),
    }
    return DiscoveryRunResult(runs=tuple(runs), summary=summary, ledgers=tuple(ledgers))


def evaluate_combo(
    accessor: SplitAccessor,
    *,
    family_name: str,
    symbol: str,
    regime_filter: str,
    direction_filter: str,
) -> DiscoveryRun:
    """Metrics-only convenience wrapper (the ledger is discarded)."""
    run, _ledger = evaluate_combo_with_ledger(
        accessor,
        family_name=family_name,
        symbol=symbol,
        regime_filter=regime_filter,
        direction_filter=direction_filter,
    )
    return run
