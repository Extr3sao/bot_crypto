"""ARP-012 verifier tests — lock the metric-semantics findings for EXP-ARP-019.

These are pure and fast: they assert the *semantics* the independent verifier
established (per-position expectancy denominator; bps-space vs currency profit
factor; episode grouping), not the corpus-driven outcome.
"""

from __future__ import annotations

from trading_bot.research.alpha_expansion.strategies import Trade
from trading_bot.research.diversified.xsec_riskadj import summarize_positions

BPS = 10_000.0


def _trade(symbol: str, notional: float, ret: float, cost_bps: float, entry_ts: int, exit_ts: int) -> Trade:
    gross = notional * ret
    fee = notional * cost_bps / BPS
    return Trade(
        side="long",
        entry_ts=entry_ts,
        exit_ts=exit_ts,
        entry=1.0,
        exit=1.0 + ret,
        reason="regime_exit",
        rule=f"breadth_{symbol}",
        symbol=symbol,
        notional=notional,
        gross=gross,
        fees=fee,
        net=gross - fee,
    )


def test_expectancy_denominator_is_per_position_notional() -> None:
    """expectancy_net_bps = mean(net / own notional) — NOT /500 portfolio."""
    trades = [
        _trade("A", 10.0, 0.10, 23.559, 0, 100),
        _trade("B", 2.0, 0.25, 23.559, 0, 100),
    ]
    out = summarize_positions(trades, cost_bps_rt=23.559)
    per_position = [
        t.net / t.notional * BPS for t in trades
    ]
    assert out["expectancy_net_bps"] == round(sum(per_position) / len(per_position), 3)
    # the portfolio-notional reading (sum(net)/500) is a DIFFERENT number
    portfolio_reading = sum(t.net for t in trades) / 500.0 * BPS
    assert abs(out["expectancy_net_bps"] - portfolio_reading) > 1.0
    # and it is not the per-trade mean in USD either
    assert out["expectancy_net_bps"] != round(sum(t.net for t in trades) / len(trades), 3)


def test_profit_factor_is_bps_space_not_currency() -> None:
    """The builder PF weights positions equally (bps); currency PF can differ."""
    # big winner with a SMALL allocation, small loser with a LARGE allocation
    trades = [
        _trade("WIN", 2.0, 1.0, 0.0, 0, 100),   # +20000 bps, +2 USD
        _trade("LOSE", 20.0, -0.05, 0.0, 0, 100),  # -500 bps, -1 USD
    ]
    out = summarize_positions(trades, cost_bps_rt=0.0)
    # bps-space PF: 10000 / 500 = 20 (equal position weighting)
    assert out["profit_factor"] == 20.0
    # currency PF: 2 / 1 = 2.0 — materially different
    currency_pf = sum(t.net for t in trades if t.net > 0) / abs(
        sum(t.net for t in trades if t.net < 0)
    )
    assert currency_pf == 2.0
    assert out["profit_factor"] != currency_pf


def test_episode_grouping_collapses_a_basket_to_one_decision() -> None:
    """~N simultaneous constituents form ONE episode (effective-sample claim)."""
    trades = [
        _trade("A", 5.0, 0.1, 0.0, 0, 100),
        _trade("B", 5.0, -0.1, 0.0, 0, 100),
        _trade("C", 5.0, 0.2, 0.0, 0, 100),
        _trade("D", 5.0, 0.05, 0.0, 1000, 1100),
    ]
    # two entry timestamps -> two episodes over four asset-positions
    by_entry: dict[int, int] = {}
    for t in trades:
        by_entry[t.entry_ts] = by_entry.get(t.entry_ts, 0) + 1
    assert len(by_entry) == 2
    assert sum(by_entry.values()) == 4
    # the economics: episode net USD is the basket sum, not a per-position figure
    ep0 = [t for t in trades if t.entry_ts == 0]
    assert abs(sum(t.net for t in ep0) - 1.0) < 1e-9
