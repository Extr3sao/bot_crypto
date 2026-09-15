"""ARC-03 preregistration reference implementation (frozen signal -> trade emission).

This module is the **executable statement of the frozen ARC-03 contract**. It is a pure
function of (in-memory partition, in-memory funding series, frozen constants) and reads no
data root, no network and no clock. The independent verifier can therefore diff a future
executor against it without any economic input.

It is deliberately NOT an economic engine:

* it is exercised on SYNTHETIC fixtures only (``arc03_synthetic.py``);
* it computes no return on any real data;
* it emits the trade ledger shape (bars, prices, decision instants, funding legs) so the
  frozen semantics are testable, and it never inspects a realized outcome to make a decision.

Frozen semantics implemented (see ``docs/arc03-prereg-01/ARC03_SPEC_V1.json``):

* decision instant is the signal bar's ``close_time_ms``;
* entry is the OPEN of the first bar with ``open_time_ms > decision_time_ms``;
* exit is the OPEN of the bar at ``entry_open_time_ms + 12 * 300000``;
* NO_SIGNAL precedence is first-match-wins over the frozen seven-reason tuple;
* funding cashflow is the sum over certified settlements in ``(entry_time, exit_time]`` of
  ``-direction_sign * funding_rate`` and is NEVER a signal input.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from trading_bot.research.arc03.arc03_authority import (
    BAR_MS,
    HOLDING_BARS,
    HOLDING_MS,
    LONG,
    NO_SIGNAL,
    NO_SIGNAL_PRECEDENCE,
    SHORT,
    Kline5m,
    evaluate_bar,
)
from trading_bot.research.arc03.arc03_funding import FundingSeries, funding_cashflow_return


@dataclass(frozen=True)
class RefTrade:
    """One emitted ARC-03 trade (bars/prices/decision instants only)."""

    trade_id: str
    asset: str
    direction: str
    direction_sign: int
    signal_bar_open_time_ms: int
    decision_time_ms: int
    reference_observations_present: int
    volume: float
    reference_volume_max: float
    range: float
    reference_range_max: float
    body: float
    wick_fraction: float
    entry_bar_index: int
    entry_time_ms: int
    entry_price: float
    exit_bar_index: int
    exit_time_ms: int
    exit_price: float

    def gross_return(self) -> float:
        return self.direction_sign * (self.exit_price / self.entry_price - 1.0)


@dataclass(frozen=True)
class RefResult:
    trades: tuple[RefTrade, ...]
    funnel: dict[str, int]
    decisions_evaluated: int


def _funding_leg(
    series: FundingSeries | None, *, entry_time_ms: int, exit_time_ms: int, direction_sign: int
) -> tuple[float, int]:
    if series is None:
        return 0.0, 0
    return funding_cashflow_return(
        series, entry_time_ms=entry_time_ms, exit_time_ms=exit_time_ms, direction_sign=direction_sign
    )


def emit_trades(
    partitions: dict[str, Kline5m],
    *,
    start_ms: int,
    end_ms: int,
    funding: dict[str, FundingSeries] | None = None,
    asset_order: tuple[str, ...] | None = None,
) -> RefResult:
    """Emit the frozen ARC-03 trade set for the given in-memory partitions.

    Deterministic: assets are visited in the frozen order (BTCUSDT, ETHUSDT, SOLUSDT, filtered
    to the partitions supplied) and bars in ascending ``open_time_ms``. No randomness, no data
    root, no clock.
    """
    if asset_order is None:
        asset_order = tuple(a for a in ("BTCUSDT", "ETHUSDT", "SOLUSDT") if a in partitions)
    trades: list[RefTrade] = []
    funnel: dict[str, int] = {reason: 0 for reason in NO_SIGNAL_PRECEDENCE}
    decisions = 0

    for asset in asset_order:
        k = partitions[asset]
        next_free_index = 0
        for i in range(k.rows):
            bar_open = k.t[i]
            if bar_open > end_ms:
                break
            if bar_open < start_ms:
                funnel["OUTSIDE_COMMON_WINDOW"] += 1
                continue

            decisions += 1
            ev = evaluate_bar(k, i)
            if not ev["emitted"]:
                funnel[ev["reason"]] += 1
                continue

            if i < next_free_index:
                funnel["POSITION_ALREADY_OPEN"] += 1
                continue

            decision_time_ms = int(ev["decision_time_ms"])
            entry_i = k.first_index_strictly_after(decision_time_ms)
            if entry_i is None:
                funnel["INSUFFICIENT_FORWARD_PRICE_DATA"] += 1
                continue
            entry_time_ms = k.t[entry_i]
            if entry_time_ms > end_ms:
                funnel["INSUFFICIENT_FORWARD_PRICE_DATA"] += 1
                continue

            exit_time_ms = entry_time_ms + HOLDING_MS
            if exit_time_ms > end_ms:
                funnel["INSUFFICIENT_FORWARD_PRICE_DATA"] += 1
                continue
            exit_i = k.slot_index(exit_time_ms)
            if exit_i is None:
                funnel["INSUFFICIENT_FORWARD_PRICE_DATA"] += 1
                continue

            direction = ev["result"]
            direction_sign = 1 if direction == LONG else -1
            trades.append(
                RefTrade(
                    trade_id=f"{asset}-{i:08d}",
                    asset=asset,
                    direction=direction,
                    direction_sign=direction_sign,
                    signal_bar_open_time_ms=bar_open,
                    decision_time_ms=decision_time_ms,
                    reference_observations_present=int(ev["reference_observations_present"]),
                    volume=float(ev["volume"]),
                    reference_volume_max=float(ev["reference_volume_max"]),
                    range=float(ev["range"]),
                    reference_range_max=float(ev["reference_range_max"]),
                    body=float(ev["body"]),
                    wick_fraction=float(ev["wick_fraction"]),
                    entry_bar_index=entry_i,
                    entry_time_ms=entry_time_ms,
                    entry_price=k.o[entry_i],
                    exit_bar_index=exit_i,
                    exit_time_ms=exit_time_ms,
                    exit_price=k.o[exit_i],
                )
            )
            next_free_index = exit_i

    return RefResult(trades=tuple(trades), funnel=funnel, decisions_evaluated=decisions)


def trade_returns(
    trade: RefTrade,
    *,
    cost_bps: int,
    funding: FundingSeries | None = None,
) -> dict[str, Any]:
    """Frozen return decomposition for one trade. ``NET = GROSS + FUNDING - COST``."""
    gross = trade.gross_return()
    funding_leg, settlements = _funding_leg(
        funding,
        entry_time_ms=trade.entry_time_ms,
        exit_time_ms=trade.exit_time_ms,
        direction_sign=trade.direction_sign,
    )
    cost = cost_bps / 10_000.0
    return {
        "trade_id": trade.trade_id,
        "asset": trade.asset,
        "direction": trade.direction,
        "gross_price_return": gross,
        "funding_cashflow_return": funding_leg,
        "funding_settlements_applied": settlements,
        "cost_return": cost,
        "net_trade_return": gross + funding_leg - cost,
        "net_trade_return_ex_funding": gross - cost,
    }


def reference_holding_bars() -> int:
    """The frozen primary holding horizon (12 bars = 60 minutes)."""
    return HOLDING_BARS


__all__ = [
    "RefResult",
    "RefTrade",
    "emit_trades",
    "reference_holding_bars",
    "trade_returns",
]
