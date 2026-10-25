"""ARP-010 EXP-ARP-022 — intermarket risk-appetite rotation.

New mechanism ``H-INTERMARKET-RISKAPP-001`` (``PROJECT_DERIVED_VARIANT``), the
rotation pre-registered in
``docs/research/post_oos_recovery/experiments/EXP-ARP-022/``.

Frozen rule (never tuned on results):

1. ``risk_on = ETHBTC_close_t > SMA50(ETHBTC)_t`` on closed bars only, where the
   ratio is ``ETHUSDT.close / BTCUSDT.close`` (a *cross-market* ratio, not a
   per-asset trend).
2. ``risk_on`` -> hold an equal-weight top-20 liquid non-BTC alt basket;
   otherwise hold ``BTCUSDT``.
3. Rebalance weekly at the UTC close; act at the **next open**; trade only when
   the regime flips or the basket membership changes.
4. One leg at a time; fixed total notional 500 USD; no compounding; one
   round-trip cost per rotation.

Data authority (§3/§4): the only inputs are ``ETHUSDT`` and ``BTCUSDT`` daily
bars already present in the ARP-006 corpus. No external macro series is
substituted; if the frozen inputs were absent the correct outcome is
``DATA_BLOCKED`` (see the driver). The ratio is an *intermarket* variable only in
the crypto-internal sense (ETH vs BTC) — stated explicitly in the evidence.

PIT contract: the SMA and the basket membership read closed bars at or before the
decision close; the fill is the next open. ``SURVIVORSHIP_DATA_LIMITATION`` binds
the cross-sectional basket.

Research-only, deterministic (no RNG, no wall-clock).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from trading_bot.research.alpha_expansion.strategies import Trade

from .data import MS_PER_DAY, DailyBar
from .universe import DynamicAssetUniverse, UniverseConfig

__all__ = [
    "IntermarketConfig",
    "IntermarketError",
    "StateRecord",
    "intermarket_config",
    "risk_on_state",
    "simulate_intermarket_rotation",
]

BPS = 10_000.0
BTC = "BTCUSDT"
ETH = "ETHUSDT"


class IntermarketError(Exception):
    """Raised when the frozen intermarket inputs are unavailable."""


@dataclass(frozen=True, slots=True)
class IntermarketConfig:
    """Frozen parameters of the intermarket rotation."""

    lookback_days: int = 50
    alt_basket_size: int = 20
    min_members: int = 5
    rebalance_days: int = 7
    max_hold_days: int = 7
    entry_delay_days: int = 0


@dataclass(frozen=True, slots=True)
class StateRecord:
    """Replayable attribution for one weekly decision (§12)."""

    decision_ts: int
    ratio: float
    sma: float
    risk_on: bool
    leg: str
    eligible_alts: int
    basket: tuple[str, ...]
    action: str

    def to_dict(self) -> dict[str, object]:
        return {
            "decision_ts": self.decision_ts,
            "ratio": round(self.ratio, 8),
            "sma": round(self.sma, 8),
            "risk_on": self.risk_on,
            "leg": self.leg,
            "eligible_alts": self.eligible_alts,
            "basket": list(self.basket),
            "action": self.action,
        }


def intermarket_config(**overrides: object) -> IntermarketConfig:
    """Build the frozen config; ``overrides`` exist only for robustness."""
    base: dict[str, object] = {
        "lookback_days": 50,
        "alt_basket_size": 20,
        "min_members": 5,
        "rebalance_days": 7,
        "max_hold_days": 7,
    }
    base.update(overrides)
    return IntermarketConfig(**base)  # type: ignore[arg-type]


def risk_on_state(
    ratio_series: Sequence[float], lookback_days: int
) -> bool | None:
    """``True`` when the latest ratio exceeds the mean of the trailing window.

    ``ratio_series`` must be ordered oldest -> newest and end at the decision bar.
    Returns ``None`` when fewer than ``lookback_days`` observations exist
    (fail closed — no signal). Reads only the supplied (closed) values.
    """
    if len(ratio_series) < lookback_days:
        return None
    window = ratio_series[-lookback_days:]
    sma = sum(window) / len(window)
    return ratio_series[-1] > sma


@dataclass
class _Holding:
    entry_price: float
    entry_ts: int
    alloc: float
    peak: float
    trough: float


def _exact_ratio(
    btc: Mapping[int, DailyBar], eth: Mapping[int, DailyBar], day: int, lookback: int
) -> list[float] | None:
    """Contiguous closed-bar ratio window ending at ``day`` (or ``None``)."""
    out: list[float] = []
    for k in range(lookback):
        ts = day - (lookback - 1 - k) * MS_PER_DAY
        b = btc.get(ts)
        e = eth.get(ts)
        if b is None or e is None or b.close <= 0.0 or e.close <= 0.0:
            return None
        out.append(e.close / b.close)
    return out


def simulate_intermarket_rotation(
    bars_by_symbol: Mapping[str, Sequence[DailyBar]],
    listing_time: Mapping[str, int],
    data_fingerprint: str,
    *,
    config: IntermarketConfig,
    cost_bps_rt: float,
    universe_config: UniverseConfig | None = None,
    notional: float = 500.0,
    subset: Sequence[str] | None = None,
    force_leg: str | None = None,
) -> tuple[list[Trade], list[StateRecord], dict[str, object]]:
    """Run the frozen rotation. Returns ``(trades, states, audit)``.

    Raises :class:`IntermarketError` when the frozen inputs (``BTCUSDT`` /
    ``ETHUSDT``) are absent — the caller must then record ``DATA_BLOCKED`` rather
    than substitute a proxy.
    """
    universe_config = universe_config or UniverseConfig()
    symbols = sorted(subset) if subset is not None else sorted(bars_by_symbol)
    corpus = {s: bars_by_symbol[s] for s in symbols}
    if BTC not in corpus or ETH not in corpus:
        raise IntermarketError(f"frozen inputs missing: require {BTC} and {ETH}")
    listing = {s: listing_time.get(s, 0) for s in symbols}
    uverse = DynamicAssetUniverse(corpus, listing, data_fingerprint, universe_config)
    index_by_sym: dict[str, dict[int, DailyBar]] = {
        s: {b.timestamp: b for b in bars} for s, bars in corpus.items()
    }
    btc = index_by_sym[BTC]
    eth = index_by_sym[ETH]
    calendar = sorted({ts for d in index_by_sym.values() for ts in d})
    if len(calendar) < 2:
        return [], [], {"decisions": 0}

    trades: list[Trade] = []
    states: list[StateRecord] = []
    holdings: dict[str, _Holding] = {}
    current_leg = "NONE"
    last_rebalance = -(10**9)
    no_signal_days = 0

    def close(symbol: str, h: _Holding, exit_price: float, exit_ts: int, reason: str) -> None:
        gross = h.alloc * (exit_price / h.entry_price - 1.0)
        fee = h.alloc * cost_bps_rt / BPS
        trades.append(
            Trade(
                side="long",
                entry_ts=h.entry_ts,
                exit_ts=exit_ts,
                entry=round(h.entry_price, 6),
                exit=round(exit_price, 6),
                reason=reason,
                rule=f"intermarket_{symbol}",
                symbol=symbol,
                notional=round(h.alloc, 6),
                gross=round(gross, 6),
                fees=round(fee, 6),
                net=round(gross - fee, 6),
                mfe_pct=round((h.peak - h.entry_price) / h.entry_price * 100.0, 4),
                mae_pct=round((h.entry_price - h.trough) / h.entry_price * 100.0, 4),
                duration_min=round((exit_ts - h.entry_ts) / 60_000.0, 1),
            )
        )

    def open_leg(targets: Mapping[str, float], fill_day: int, reason: str) -> None:
        for symbol, alloc in targets.items():
            bar = index_by_sym[symbol].get(fill_day)
            if bar is None or bar.open <= 0.0:
                continue
            holdings[symbol] = _Holding(bar.open, fill_day, alloc, bar.open, bar.open)

    for i, day in enumerate(calendar):
        for symbol, h in holdings.items():
            bar = index_by_sym[symbol].get(day)
            if bar is not None:
                h.peak = max(h.peak, bar.high)
                h.trough = min(h.trough, bar.low)

        if (i - last_rebalance) < config.rebalance_days:
            continue
        last_rebalance = i
        fill_i = i + 1 + config.entry_delay_days
        if fill_i >= len(calendar):
            break
        fill_day = calendar[fill_i]

        ratios = _exact_ratio(btc, eth, day, config.lookback_days)
        if ratios is None:
            no_signal_days += 1
            continue
        sma = sum(ratios) / len(ratios)
        state = risk_on_state(ratios, config.lookback_days)
        if state is None:
            no_signal_days += 1
            continue
        risk_on = state
        if force_leg == "ALT":
            risk_on = True
        elif force_leg == "BTC":
            risk_on = False

        if risk_on:
            snapshot = uverse.snapshot(day + MS_PER_DAY)
            alt_eligible = [s for s in snapshot.eligible_assets if s != BTC]
            ranked = sorted(
                alt_eligible,
                key=lambda s: (-snapshot.liquidity_metric.get(s, 0.0), s),
            )
            basket = tuple(ranked[: config.alt_basket_size])
            if len(basket) < config.min_members:
                no_signal_days += 1
                states.append(
                    StateRecord(day, ratios[-1], sma, True, "NO_SIGNAL",
                                len(alt_eligible), basket, "no_signal")
                )
                continue
            target_leg = "ALT"
            targets = {s: notional / len(basket) for s in basket}
        else:
            target_leg = "BTC"
            basket = (BTC,)
            targets = {BTC: notional}

        action = "hold"
        if current_leg == "NONE":
            open_leg(targets, fill_day, "entry")
            current_leg = target_leg
            action = "open"
        elif target_leg != current_leg:
            for symbol, h in list(holdings.items()):
                bar = index_by_sym[symbol].get(fill_day)
                if bar is None:
                    continue
                close(symbol, h, bar.open, fill_day, "rotate")
                del holdings[symbol]
            open_leg(targets, fill_day, "entry")
            current_leg = target_leg
            action = "rotate"
        elif target_leg == "ALT":
            for symbol, h in list(holdings.items()):
                if symbol in targets:
                    continue
                bar = index_by_sym[symbol].get(fill_day)
                if bar is None:
                    continue
                close(symbol, h, bar.open, fill_day, "membership")
                del holdings[symbol]
            new_names = {s: a for s, a in targets.items() if s not in holdings}
            if new_names:
                open_leg(new_names, fill_day, "membership")
                action = "membership"

        states.append(
            StateRecord(day, ratios[-1], sma, risk_on, target_leg,
                        len(basket), basket, action)
        )

    if holdings and calendar:
        last_day = calendar[-1]
        for symbol, h in list(holdings.items()):
            bar = index_by_sym[symbol].get(last_day)
            if bar is None:
                continue
            close(symbol, h, bar.close, last_day, "end_of_sample")
            del holdings[symbol]

    audit: dict[str, object] = {
        "decisions": len(states),
        "no_signal_days": no_signal_days,
        "risk_on_days": sum(1 for s in states if s.risk_on and s.leg != "NO_SIGNAL"),
        "risk_off_days": sum(1 for s in states if not s.risk_on),
    }
    return trades, states, audit
