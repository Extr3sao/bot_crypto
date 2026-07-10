"""Post-trade evaluator for TSK-860."""

from __future__ import annotations

from dataclasses import dataclass

import typing

from trading_bot.market_data.types import OHLCV
from trading_bot.trade_journal.types import EntryThesis, TradeOutcome, WinLoss


@dataclass(frozen=True, slots=True)
class TradeEvaluationInput:
    thesis: EntryThesis
    position_id: str
    exit_price: float
    exit_reason: str
    qty: float
    fees: float
    candles_after_entry: tuple[OHLCV, ...]
    closed_at: int


def evaluate_trade_outcome(payload: TradeEvaluationInput) -> TradeOutcome:
    if payload.qty <= 0:
        raise ValueError("qty must be > 0")
    if payload.exit_price <= 0:
        raise ValueError("exit_price must be > 0")

    direction = payload.thesis.direction
    entry = payload.thesis.entry_price
    risk_per_unit = abs(entry - payload.thesis.sl_price)
    if risk_per_unit <= 0:
        raise ValueError("entry and SL must not be equal")

    if direction == "LONG":
        pnl_gross = (payload.exit_price - entry) * payload.qty
        mfe = (
            max((candle.high - entry) for candle in payload.candles_after_entry)
            if payload.candles_after_entry
            else 0.0
        )
        mae = (
            max((entry - candle.low) for candle in payload.candles_after_entry)
            if payload.candles_after_entry
            else 0.0
        )
    else:
        pnl_gross = (entry - payload.exit_price) * payload.qty
        mfe = (
            max((entry - candle.low) for candle in payload.candles_after_entry)
            if payload.candles_after_entry
            else 0.0
        )
        mae = (
            max((candle.high - entry) for candle in payload.candles_after_entry)
            if payload.candles_after_entry
            else 0.0
        )

    pnl_net = pnl_gross - payload.fees
    r_multiple = pnl_net / (risk_per_unit * payload.qty)
    win_loss = "win" if pnl_net > 0 else "loss" if pnl_net < 0 else "breakeven"
    diagnosis = _diagnose(payload.thesis, payload.exit_reason, win_loss, mfe, mae, risk_per_unit)

    return TradeOutcome(
        trade_case_id=payload.thesis.trade_case_id,
        position_id=payload.position_id,
        exit_reason=payload.exit_reason,
        pnl_net=round(pnl_net, 10),
        r_multiple=round(r_multiple, 6),
        mfe=round(mfe, 10),
        mae=round(mae, 10),
        win_loss=typing.cast(WinLoss, win_loss),
        closed_at=payload.closed_at,
        post_trade_diagnosis=diagnosis,
    )


def _diagnose(
    thesis: EntryThesis,
    exit_reason: str,
    win_loss: str,
    mfe: float,
    mae: float,
    risk_per_unit: float,
) -> tuple[str, ...]:
    tags: list[str] = []
    if win_loss == "win":
        if thesis.direction == "LONG" and any(
            tag in thesis.criteria_met
            for tag in ("near_support", "near_range_low", "near_accumulation")
        ):
            tags.append("support_respected")
        if thesis.direction == "SHORT" and any(
            tag in thesis.criteria_met
            for tag in ("near_resistance", "near_range_high", "near_distribution")
        ):
            tags.append("resistance_rejected")
    else:
        if any("against" in tag for tag in thesis.criteria_failed):
            tags.append("structure_invalidated")
        if mae > risk_per_unit * 0.9:
            tags.append("sl_pressure_high")

    if exit_reason == "take_profit":
        tags.append("tp_reached")
    elif exit_reason == "stop_loss":
        tags.append("sl_reached")
    elif exit_reason == "manual":
        tags.append("manual_close")

    if mfe < risk_per_unit * 0.25:
        tags.append("low_favorable_excursion")
    return tuple(dict.fromkeys(tags))


__all__ = ["TradeEvaluationInput", "evaluate_trade_outcome"]
