from __future__ import annotations

import pytest

from trading_bot.feedback import TradeEvaluationInput, evaluate_trade_outcome
from trading_bot.market_data.types import OHLCV
from trading_bot.trade_journal.types import EntryThesis


def _candle(ts: int, open_: float, high: float, low: float, close: float) -> OHLCV:
    return OHLCV("BTC/USDT", ts, open_, high, low, close, 100)


def _thesis(direction: str, *, failed: tuple[str, ...] = ()) -> EntryThesis:
    return EntryThesis(
        trade_case_id="case-1",
        signal_id="signal-1",
        symbol="BTC/USDT",
        direction=direction,  # type: ignore[arg-type]
        entry_price=100,
        tp_price=104 if direction == "LONG" else 96,
        sl_price=98 if direction == "LONG" else 102,
        timeframe="1m",
        entry_reason="test",
        criteria_met=("near_support",) if direction == "LONG" else ("near_resistance",),
        criteria_failed=failed,
        indicators={},
        zones=(),
        confidence_score=0.7,
        created_at=1,
    )


def test_evaluate_long_take_profit_tags_support_respected() -> None:
    outcome = evaluate_trade_outcome(
        TradeEvaluationInput(
            thesis=_thesis("LONG"),
            position_id="pos-1",
            exit_price=104,
            exit_reason="take_profit",
            qty=1,
            fees=0.1,
            candles_after_entry=(
                _candle(2, 100, 102, 99, 101),
                _candle(3, 101, 104, 100, 104),
            ),
            closed_at=4,
        )
    )

    assert outcome.win_loss == "win"
    assert outcome.r_multiple == pytest.approx(1.95)
    assert "support_respected" in outcome.post_trade_diagnosis
    assert "tp_reached" in outcome.post_trade_diagnosis


def test_evaluate_short_stop_loss_tags_structure_invalidated() -> None:
    outcome = evaluate_trade_outcome(
        TradeEvaluationInput(
            thesis=_thesis("SHORT", failed=("near_support_against_short",)),
            position_id="pos-1",
            exit_price=102,
            exit_reason="stop_loss",
            qty=1,
            fees=0.0,
            candles_after_entry=(
                _candle(2, 100, 101, 99, 100),
                _candle(3, 100, 102.2, 99.5, 102),
            ),
            closed_at=4,
        )
    )

    assert outcome.win_loss == "loss"
    assert outcome.r_multiple == pytest.approx(-1.0)
    assert "structure_invalidated" in outcome.post_trade_diagnosis
    assert "sl_reached" in outcome.post_trade_diagnosis


def test_evaluate_rejects_invalid_qty() -> None:
    with pytest.raises(ValueError, match="qty must be > 0"):
        evaluate_trade_outcome(
            TradeEvaluationInput(
                thesis=_thesis("LONG"),
                position_id="pos-1",
                exit_price=104,
                exit_reason="take_profit",
                qty=0,
                fees=0,
                candles_after_entry=(),
                closed_at=4,
            )
        )

