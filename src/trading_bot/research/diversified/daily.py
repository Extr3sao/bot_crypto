"""ARP-006 DIVERSIFIED ALPHA SEARCH §10-§13 — the two ready daily experiments.

* ``EXP-ARP-006`` — ``STRAT-CAND-016-VARIANT-B`` liquidity-reversal
  (:class:`Exp006LiquidityReversal`), arm ``PROJECT_DERIVED_VARIANT`` (NOT
  source-faithful).
* ``EXP-ARP-008`` — ``H-DAILY-TSMOM-001`` daily time-series momentum
  (:func:`simulate_exp008`), a NEW project hypothesis.

Frozen parameters only — they are copied verbatim from the pre-registered SPECs in
``docs/research/alpha_recovery_v1_2/experiments/`` and never re-tuned. The MATERIAL
DIFFERENCE authorised by ARP-006 is the *data*: the ARP-005 expanded multi-regime
corpus and the standard DEV/VALIDATION/OOS_LOCK splits replace the original
W1..W7 short window. Parameters, entry, exit and asset selection are unchanged.

PIT contract: a signal produced on the *closed* daily bar ``i`` is filled at
``open[i + 1]``; ``data_time <= decision_time <= fill_time``. One position at a time
per symbol; fixed notional (500 USD); no compounding; a single round-trip cost.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from trading_bot.market_data.types import OHLCV
from trading_bot.research.alpha_recovery.daily import DailySetup, simulate_daily
from trading_bot.research.alpha_recovery.series import atr_series
from trading_bot.research.alpha_recovery.simulate import Trade

from .data import DailyBar

__all__ = [
    "EXP006_DECISION_TIME_NOTE",
    "Exp006Config",
    "Exp006LiquidityReversal",
    "Exp008Config",
    "TaggedTrade",
    "simulate_exp006",
    "simulate_exp008",
    "tag_trades",
]

BPS = 10_000.0

#: identity note persisted into the experiment reports
EXP006_DECISION_TIME_NOTE = (
    "signal on a closed 1d bar i; fill at open[i+1]; one position per symbol"
)


@dataclass(frozen=True, slots=True)
class Exp006Config:
    """EXP-ARP-006 frozen parameters (copied from the SPEC; never tuned)."""

    atr_period: int = 14
    void_min_days: int = 3
    void_min_atr: float = 2.0
    retest_lookback_days: int = 10
    stop_atr: float = 1.5
    target_atr: float = 3.0
    max_hold_days: int = 5


class Exp006LiquidityReversal:
    """Fade a fast one-sided daily move back into its void-origin band (§10).

    A *void* is ``>= 3`` consecutive daily closes strictly monotone in one direction
    whose total displacement is ``>= 2.0 x ATR(14)`` (ATR at the void's last day).
    The *origin band* is ``[min(open_first, close_last), max(open_first, close_last)]``
    over the void. The first bar within ``10`` days of the void end whose high
    (down-void) or low (up-void) re-enters the band signals entry at the *next*
    open, opposite the void.
    """

    def __init__(self, config: Exp006Config | None = None) -> None:
        self.config = config or Exp006Config()
        self.warmup = self.config.atr_period + self.config.void_min_days + 2
        self._signals: dict[int, DailySetup] = {}

    def prepare(self, bars: Sequence[OHLCV]) -> None:
        cfg = self.config
        n = len(bars)
        atr = atr_series(
            [b.high for b in bars],
            [b.low for b in bars],
            [b.close for b in bars],
            cfg.atr_period,
        )
        signals: dict[int, DailySetup] = {}
        for e in range(1, n):
            a = atr[e]
            if a is None or a <= 0:
                continue
            if bars[e].close == bars[e - 1].close:
                continue
            down = bars[e].close < bars[e - 1].close
            s = e
            while s > 0 and (
                (bars[s].close < bars[s - 1].close) if down else (bars[s].close > bars[s - 1].close)
            ):
                s -= 1
            length = e - s + 1
            if length < cfg.void_min_days:
                continue
            displacement = abs(bars[e].close - bars[s].close)
            if displacement < cfg.void_min_atr * a:
                continue
            band_low = min(bars[s].open, bars[e].close)
            band_high = max(bars[s].open, bars[e].close)
            for k in range(e + 1, min(e + cfg.retest_lookback_days, n - 1) + 1):
                if k in signals:
                    continue
                if down and bars[k].high >= band_low:
                    signals[k] = DailySetup(
                        side="long",
                        rule="exp006_void_retest_long",
                        max_hold_days=cfg.max_hold_days,
                        atr=a,
                        stop_atr_mult=cfg.stop_atr,
                        target_atr_mult=cfg.target_atr,
                    )
                    break
                if not down and bars[k].low <= band_high:
                    signals[k] = DailySetup(
                        side="short",
                        rule="exp006_void_retest_short",
                        max_hold_days=cfg.max_hold_days,
                        atr=a,
                        stop_atr_mult=cfg.stop_atr,
                        target_atr_mult=cfg.target_atr,
                    )
                    break
        self._signals = signals

    def entry(self, i: int) -> DailySetup | None:
        return self._signals.get(i)


@dataclass(frozen=True, slots=True)
class TaggedTrade:
    """A daily :class:`Trade` bound to its symbol, so multi-asset analytics work."""

    symbol: str
    trade: Trade

    @property
    def net(self) -> float:
        return self.trade.net

    @property
    def gross(self) -> float:
        return self.trade.gross

    @property
    def fees(self) -> float:
        return self.trade.fees

    @property
    def mfe_pct(self) -> float:
        return self.trade.mfe_pct

    @property
    def mae_pct(self) -> float:
        return self.trade.mae_pct

    @property
    def duration_min(self) -> float:
        return self.trade.duration_min

    @property
    def reason(self) -> str:
        return self.trade.reason

    @property
    def entry_ts(self) -> int:
        return self.trade.entry_ts

    @property
    def exit_ts(self) -> int:
        return self.trade.exit_ts

    def as_dict(self) -> dict[str, Any]:
        d = self.trade.as_dict()
        d["symbol"] = self.symbol
        return d


def tag_trades(by_symbol: Mapping[str, Sequence[Trade]]) -> list[TaggedTrade]:
    """Bind each trade to its symbol for cross-asset aggregation."""
    return [TaggedTrade(symbol=s, trade=t) for s, trades in by_symbol.items() for t in trades]


def to_ohlcv(bars: Sequence[DailyBar]) -> list[OHLCV]:
    return [
        OHLCV(
            symbol=b.symbol,
            timestamp=b.timestamp,
            open=b.open,
            high=b.high,
            low=b.low,
            close=b.close,
            volume=b.volume,
        )
        for b in bars
    ]


def simulate_exp006(
    bars_by_symbol: Mapping[str, Sequence[DailyBar]],
    *,
    cost_bps_rt: float,
    notional: float = 500.0,
    entry_delay_days: int = 0,
    config: Exp006Config | None = None,
) -> dict[str, list[Trade]]:
    """Run EXP-ARP-006 per symbol, returning ``symbol -> [Trade]``."""
    out: dict[str, list[Trade]] = {}
    for symbol, bars in bars_by_symbol.items():
        if not bars:
            out[symbol] = []
            continue
        strategy = Exp006LiquidityReversal(config)
        result = simulate_daily(
            strategy,
            to_ohlcv(bars),
            cost_bps_rt=cost_bps_rt,
            notional=notional,
            entry_delay_days=entry_delay_days,
        )
        out[symbol] = result.trades
    return out


# --------------------------------------------------------------------- EXP-ARP-008


@dataclass(frozen=True, slots=True)
class Exp008Config:
    """EXP-ARP-008 frozen parameters (copied from the SPEC; never tuned)."""

    lookback_days: int = 30
    max_hold_days: int = 20


def simulate_exp008(
    bars_by_symbol: Mapping[str, Sequence[DailyBar]],
    *,
    cost_bps_rt: float,
    notional: float = 500.0,
    entry_delay_days: int = 0,
    config: Exp008Config | None = None,
) -> dict[str, list[Trade]]:
    """Long-only daily time-series momentum, flat on signal flip (next open).

    Long while ``close_t > close_{t-lookback}``; enter/exit at the *next* open; no
    stop; ``max_hold_days`` safety exit at a close. Deterministic, PIT-safe.
    """
    cfg = config or Exp008Config()
    fee_usd = notional * cost_bps_rt / BPS
    out: dict[str, list[Trade]] = {}
    for symbol, bars in bars_by_symbol.items():
        out[symbol] = _run_exp008_one(
            bars,
            lookback=cfg.lookback_days,
            max_hold=cfg.max_hold_days,
            fee_usd=fee_usd,
            notional=notional,
            entry_delay_days=entry_delay_days,
            symbol=symbol,
        )
    return out


def _run_exp008_one(
    bars: Sequence[DailyBar],
    *,
    lookback: int,
    max_hold: int,
    fee_usd: float,
    notional: float,
    entry_delay_days: int,
    symbol: str,
) -> list[Trade]:
    n = len(bars)
    trades: list[Trade] = []
    if n <= lookback + 1:
        return trades
    closes = [b.close for b in bars]

    def signal(i: int) -> bool:
        return i >= lookback and closes[i] > closes[i - lookback]

    open_entry: float | None = None
    entry_index = 0
    peak = 0.0
    trough = 0.0
    pending_entry = False
    pending_due = 0
    pending_exit = False

    def close(pos_entry: float, price: float, ts: int, reason: str) -> None:
        gross = notional * (price / pos_entry - 1.0)
        trades.append(
            Trade(
                side="long",
                entry_ts=int(bars[entry_index].timestamp),
                exit_ts=ts,
                duration_min=round((ts - bars[entry_index].timestamp) / 60_000.0, 1),
                entry=round(pos_entry, 6),
                exit=round(price, 6),
                reason=reason,
                mfe_pct=round((peak - pos_entry) / pos_entry * 100.0, 4),
                mae_pct=round((pos_entry - trough) / pos_entry * 100.0, 4),
                notional=round(notional, 2),
                gross=round(gross, 4),
                fees=round(fee_usd, 4),
                net=round(gross - fee_usd, 4),
                rule=f"exp008_tsmom_{symbol}",
            )
        )

    for i in range(n):
        bar = bars[i]
        if open_entry is not None and pending_exit:
            close(open_entry, bar.open, int(bar.timestamp), "signal_flip")
            open_entry = None
            pending_exit = False
        if open_entry is None and pending_entry and i >= pending_due:
            open_entry = bar.open
            entry_index = i
            peak = trough = bar.open
            pending_entry = False
        if open_entry is not None:
            peak = max(peak, bar.high)
            trough = min(trough, bar.low)
            if i - entry_index >= max_hold:
                close(open_entry, bar.close, int(bar.timestamp), "window_expiry")
                open_entry = None
                pending_exit = False
        if i >= n - 1:
            break
        if open_entry is None and not pending_entry and signal(i):
            due = i + 1 + entry_delay_days
            if due <= n - 1:
                pending_entry = True
                pending_due = due
        elif open_entry is not None and not pending_exit and not signal(i):
            pending_exit = True

    if open_entry is not None:
        last = bars[-1]
        close(open_entry, last.close, int(last.timestamp), "window_expiry")
    return trades
