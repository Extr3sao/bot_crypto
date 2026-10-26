"""ARP-009 EXP-ARP-021 — cross-sectional RISK-ADJUSTED relative strength.

New mechanism ``H-XSEC-RISKADJ-RELSTR-001`` (``PROJECT_DERIVED_VARIANT``). This is
the *portfolio* rotation pre-registered in
``docs/research/post_oos_recovery/experiments/EXP-ARP-021/`` and is deliberately
distinct from:

* ``EXP-ARP-008`` — single-asset time-series momentum (ranks nothing);
* ``EXP-ARP-016`` — raw trailing return, no volatility normalisation, no skip.

Frozen rule (never tuned on results):

1. ``score_i = (close_{t-skip} / close_{t-skip-formation} - 1) / realized_vol_i``
   with ``formation = lookback_days`` (90) and ``skip = skip_days`` (7);
   ``realized_vol_i`` is the population stdev of the last :data:`VOL_WINDOW` (30)
   daily log returns ending at ``t-skip``.
2. Eligible universe = PIT-safe :class:`DynamicAssetUniverse` snapshot; require
   at least ``min_members`` (5) *scored* names.
3. Long equal-weight the top decile (min ``min_members``, max ``max_names``).
4. Rebalance every ``rebalance_days`` (7) at the UTC close; act at the next open;
   only names whose membership changed are traded (turnover control). Held names
   keep their entry allocation — they are never re-weighted.
5. A held name force-exits after ``max_hold_days`` (30), **at the next open**
   (never at the signal bar's close — the EXP-ARP-008 defect is excluded).
6. Long-only; fixed total notional 500 USD spread equally; no compounding.

``risk_adjusted=False`` yields the *raw-return control* of §22 (identical
construction with ``score_i = formation_return``), used only to attribute whether
the volatility normalisation adds value; the control is never promotable.

Research-only, deterministic (no RNG, no wall-clock). No runtime module imports
it; it can neither size nor execute anything.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from trading_bot.research.alpha_expansion.strategies import Trade

from .data import MS_PER_DAY, DailyBar
from .universe import DynamicAssetUniverse, UniverseConfig

__all__ = [
    "RiskAdjConfig",
    "RiskAdjUniverseConfig",
    "compute_scores",
    "riskadj_config",
    "score_of",
    "select_top",
    "simulate_riskadj_xsec",
    "summarize_positions",
]

BPS = 10_000.0
VOL_WINDOW = 30

#: frozen EXP-ARP-021 universe rules (from the MANIFEST spec block).
FROZEN_MIN_MEMBERS = 5
FROZEN_MAX_NAMES = 20


@dataclass(frozen=True, slots=True)
class RiskAdjConfig:
    """Frozen parameters of the risk-adjusted rotation (single source of truth)."""

    lookback_days: int = 90
    skip_days: int = 7
    top_fraction: float = 0.1
    min_members: int = FROZEN_MIN_MEMBERS
    max_names: int = FROZEN_MAX_NAMES
    rebalance_days: int = 7
    max_hold_days: int = 30
    #: ``True`` = the frozen mechanism; ``False`` = the §22 raw-return control.
    risk_adjusted: bool = True
    vol_window: int = VOL_WINDOW


@dataclass(frozen=True, slots=True)
class RiskAdjUniverseConfig:
    """Alias-friendly view used by the ARP-009 driver/contract builder."""

    config: RiskAdjConfig


def riskadj_config(*, risk_adjusted: bool = True, **overrides: object) -> RiskAdjConfig:
    """Build the frozen config; ``overrides`` exist only for robustness/control."""
    base: dict[str, object] = dict(
        lookback_days=90,
        skip_days=7,
        top_fraction=0.1,
        min_members=FROZEN_MIN_MEMBERS,
        max_names=FROZEN_MAX_NAMES,
        rebalance_days=7,
        max_hold_days=30,
        risk_adjusted=risk_adjusted,
    )
    base.update(overrides)
    return RiskAdjConfig(**base)  # type: ignore[arg-type]


def score_of(
    index: Mapping[int, DailyBar], decision_day: int, config: RiskAdjConfig
) -> float | None:
    """The frozen PIT risk-adjusted score at ``decision_day`` (or ``None``).

    Reads *only* exact bars at ``t = decision_day, decision_day - skip, ...`` and
    the volatility window ending at ``t-skip``. A missing bar, a non-positive
    price or a zero-volatility window fails closed (``None``); no interpolation,
    no forward-fill, and a future bar is never referenced.
    """
    t_skip = decision_day - config.skip_days * MS_PER_DAY
    t_form = t_skip - config.lookback_days * MS_PER_DAY
    if t_form not in index or t_skip not in index:
        return None
    p_form = index[t_form].close
    p_skip = index[t_skip].close
    if p_form <= 0.0 or p_skip <= 0.0:
        return None
    formation_return = p_skip / p_form - 1.0
    if not config.risk_adjusted:
        return formation_return
    closes: list[float] = []
    for k in range(config.vol_window + 1):
        ts = t_skip - (config.vol_window - k) * MS_PER_DAY
        bar = index.get(ts)
        if bar is None or bar.close <= 0.0:
            return None
        closes.append(bar.close)
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    vol = statistics.pstdev(rets)
    if vol <= 1e-12:
        return None
    return formation_return / vol


def compute_scores(
    bars_by_symbol: Mapping[str, Sequence[DailyBar]],
    decision_day: int,
    config: RiskAdjConfig,
    *,
    symbols: Sequence[str] | None = None,
) -> dict[str, float]:
    """PIT-safe scores for every symbol with a valid score at ``decision_day``."""
    wanted = sorted(symbols) if symbols is not None else sorted(bars_by_symbol)
    out: dict[str, float] = {}
    for symbol in wanted:
        bars = bars_by_symbol.get(symbol)
        if not bars:
            continue
        index = {b.timestamp: b for b in bars}
        value = score_of(index, decision_day, config)
        if value is not None:
            out[symbol] = value
    return out


def select_top(scored: Mapping[str, float], config: RiskAdjConfig) -> list[str]:
    """Top-decile selection: deterministic rank ``(-score, symbol)``.

    ``n = clamp(ceil(top_fraction * N), min_members, max_names)``. Returns ``[]``
    when fewer than ``min_members`` names scored (fail closed, no guess).
    """
    n_scored = len(scored)
    if n_scored < config.min_members:
        return []
    target_n = math.ceil(config.top_fraction * n_scored)
    target_n = max(config.min_members, min(config.max_names, target_n))
    ranked = sorted(scored, key=lambda s: (-scored[s], s))
    return ranked[:target_n]


@dataclass
class _Holding:
    entry_price: float
    entry_ts: int
    alloc: float
    peak: float
    trough: float


@dataclass
class _Book:
    trades: list[Trade] = field(default_factory=list)


def summarize_positions(
    trades: Sequence[Trade], *, cost_bps_rt: float, total_notional: float = 500.0
) -> dict[str, object]:
    """Per-position metrics normalised by each trade's own notional (§11 shape).

    Each position carries ``notional = total_notional / n_selected``, so its return
    in bps equals the underlying asset return — the economically correct quantity
    to compare against ``COST_MODEL_V3`` (a position must out-earn its own
    round-trip cost). Portfolio totals are also reported in USD and bps-of-total.
    """
    n = len(trades)
    if n == 0:
        return {
            "trades": 0,
            "gross_usd": 0.0,
            "fees_usd": 0.0,
            "net_usd": 0.0,
            "expectancy_gross_bps": None,
            "expectancy_cost_bps": None,
            "expectancy_net_bps": None,
            "cost_bps_rt": round(cost_bps_rt, 4),
            "win_rate": None,
            "payoff": None,
            "profit_factor": None,
            "max_drawdown_bps": None,
            "sharpe_per_trade": None,
            "portfolio_net_bps": 0.0,
            "exit_mix": {},
            "concentration": {},
        }
    gross_bps = [
        (t.gross / t.notional * BPS) if t.notional else 0.0 for t in trades
    ]
    net_bps = [(t.net / t.notional * BPS) if t.notional else 0.0 for t in trades]
    nets = [t.net for t in trades]
    wins = [x for x in net_bps if x > 0]
    losses = [x for x in net_bps if x <= 0]
    # drawdown of the portfolio equity curve (non-compounding, USD -> bps of total)
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for x in nets:
        equity += x
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    sharpe = None
    if n >= 30:
        sd = statistics.pstdev(net_bps)
        if sd > 0:
            sharpe = round(statistics.fmean(net_bps) / sd, 4)
    pos = sorted((x for x in net_bps if x > 0), reverse=True)
    total_pos = sum(pos)
    k10 = max(1, n // 10)
    return {
        "trades": n,
        "gross_usd": round(sum(t.gross for t in trades), 2),
        "fees_usd": round(sum(t.fees for t in trades), 2),
        "net_usd": round(sum(nets), 2),
        "expectancy_gross_bps": round(statistics.fmean(gross_bps), 3),
        "expectancy_cost_bps": round(statistics.fmean([t.fees / t.notional * BPS for t in trades]), 3)
        if all(t.notional for t in trades)
        else round(cost_bps_rt, 3),
        "expectancy_net_bps": round(statistics.fmean(net_bps), 3),
        "cost_bps_rt": round(cost_bps_rt, 4),
        "win_rate": round(len(wins) / n, 4),
        "payoff": round(statistics.fmean(wins) / abs(statistics.fmean(losses)), 4)
        if wins and losses
        else None,
        "profit_factor": round(sum(wins) / abs(sum(losses)), 4) if losses else None,
        "max_drawdown_bps": round(worst / total_notional * BPS, 3),
        "sharpe_per_trade": sharpe,
        "portfolio_net_bps": round(sum(nets) / total_notional * BPS, 3),
        "exit_mix": {r: sum(1 for t in trades if t.reason == r) for r in sorted({t.reason for t in trades})},
        "concentration": {
            "positive_trades": len(pos),
            "total_positive_net_bps": round(total_pos, 3),
            "top1_share": round(pos[0] / total_pos, 4) if total_pos > 0 else None,
            "top5_share": round(sum(pos[:5]) / total_pos, 4) if total_pos > 0 else None,
            "top10pct_share": round(sum(pos[:k10]) / total_pos, 4) if total_pos > 0 else None,
        },
    }


def simulate_riskadj_xsec(
    bars_by_symbol: Mapping[str, Sequence[DailyBar]],
    listing_time: Mapping[str, int],
    data_fingerprint: str,
    *,
    config: RiskAdjConfig,
    cost_bps_rt: float,
    universe_config: UniverseConfig | None = None,
    notional: float = 500.0,
    subset: Sequence[str] | None = None,
) -> tuple[list[Trade], dict[str, dict[str, int]]]:
    """Run the frozen rotation. Returns ``(trades, census_by_decision)``.

    ``census_by_decision`` maps each rebalance decision timestamp to
    ``{"eligible": .., "scored": .., "selected": ..}`` for the §6 breadth audit.
    ``subset`` restricts the corpus (leave-one-asset-out) without changing params.
    """
    universe_config = universe_config or UniverseConfig()
    symbols = sorted(subset) if subset is not None else sorted(bars_by_symbol)
    corpus = {s: bars_by_symbol[s] for s in symbols}
    listing = {s: listing_time.get(s, 0) for s in symbols}
    uverse = DynamicAssetUniverse(corpus, listing, data_fingerprint, universe_config)
    index_by_sym: dict[str, dict[int, DailyBar]] = {
        s: {b.timestamp: b for b in bars} for s, bars in corpus.items()
    }
    calendar = sorted({ts for d in index_by_sym.values() for ts in d})
    if len(calendar) < 2:
        return [], {}

    per_alloc = notional / float(config.max_names)  # provisional; refined per rebalance
    book = _Book()
    holdings: dict[str, _Holding] = {}
    census: dict[str, dict[str, int]] = {}
    last_rebalance = -(10**9)

    def close(symbol: str, holding: _Holding, exit_price: float, exit_ts: int, reason: str) -> None:
        gross = holding.alloc * (exit_price / holding.entry_price - 1.0)
        fee = holding.alloc * cost_bps_rt / BPS
        book.trades.append(
            Trade(
                side="long",
                entry_ts=holding.entry_ts,
                exit_ts=exit_ts,
                entry=round(holding.entry_price, 6),
                exit=round(exit_price, 6),
                reason=reason,
                rule=f"riskadj_{symbol}",
                symbol=symbol,
                notional=round(holding.alloc, 6),
                gross=round(gross, 6),
                fees=round(fee, 6),
                net=round(gross - fee, 6),
                mfe_pct=round((holding.peak - holding.entry_price) / holding.entry_price * 100.0, 4),
                mae_pct=round((holding.entry_price - holding.trough) / holding.entry_price * 100.0, 4),
                duration_min=round((exit_ts - holding.entry_ts) / 60_000.0, 1),
            )
        )

    for i, day in enumerate(calendar):
        for symbol, holding in holdings.items():
            bar = index_by_sym[symbol].get(day)
            if bar is not None:
                holding.peak = max(holding.peak, bar.high)
                holding.trough = min(holding.trough, bar.low)

        if (i - last_rebalance) < config.rebalance_days:
            continue
        last_rebalance = i
        if i + 1 >= len(calendar):
            break
        fill_day = calendar[i + 1]

        snapshot = uverse.snapshot(day + MS_PER_DAY)
        scored = compute_scores(
            corpus, day, config, symbols=snapshot.eligible_assets
        )
        target = select_top(scored, config)
        census[str(day + MS_PER_DAY)] = {
            "eligible": len(snapshot.eligible_assets),
            "scored": len(scored),
            "selected": len(target),
        }
        if not target:
            continue

        alloc = notional / float(len(target))
        cap_excluded: set[str] = set()
        target_set = set(target)

        for symbol in list(holdings):
            holding = holdings[symbol]
            days_held = (day - holding.entry_ts) // MS_PER_DAY
            leaves = symbol not in target_set
            cap = days_held >= config.max_hold_days
            if not (leaves or cap):
                continue
            fill_bar = index_by_sym[symbol].get(fill_day)
            if fill_bar is None:
                continue  # cannot fill the rotation; stay put, no look-ahead
            close(
                symbol,
                holding,
                fill_bar.open,
                fill_day,
                "window_expiry" if cap else "rotate",
            )
            del holdings[symbol]
            if cap and symbol in target_set:
                cap_excluded.add(symbol)

        for symbol in target:
            if symbol in holdings or symbol in cap_excluded:
                continue
            fill_bar = index_by_sym[symbol].get(fill_day)
            if fill_bar is None:
                continue
            price = fill_bar.open
            if price <= 0.0:
                continue
            holdings[symbol] = _Holding(
                entry_price=price,
                entry_ts=fill_day,
                alloc=alloc,
                peak=price,
                trough=price,
            )

    if holdings and calendar:
        last_day = calendar[-1]
        for symbol, holding in list(holdings.items()):
            bar = index_by_sym[symbol].get(last_day)
            if bar is None:
                continue
            close(symbol, holding, bar.close, last_day, "end_of_sample")
            del holdings[symbol]

    _ = per_alloc  # retained for provenance/documentation only
    return book.trades, census
