"""G-7: eligibility comes from the committed ledger, never from a fixture."""

from __future__ import annotations

from pathlib import Path

from trading_bot.market_data.real_data_validation import timeframe_ms
from trading_bot.market_data.types import OHLCV
from trading_bot.paper.eligibility import evaluate_eligibility

REPO = Path(__file__).resolve().parents[3]
BASE = 1_792_900_000_000
TF = "5m"


def _bars(count: int = 130) -> list[OHLCV]:
    return [
        OHLCV(
            symbol="BTC/USDT",
            timestamp=BASE + index * timeframe_ms(TF),
            open=100.0 + index,
            high=101.0 + index,
            low=99.0 + index,
            close=100.5 + index,
            volume=10.0,
        )
        for index in range(count)
    ]


def test_committed_ledger_has_no_paper_eligible_strategy_in_5m() -> None:
    bars = _bars()
    decision = bars[-1].timestamp + timeframe_ms(TF)
    report = evaluate_eligibility(
        ledger_path=REPO / "config" / "strategy_admission.json",
        assets=["BTC"],
        timeframe=TF,
        bars_by_symbol={"BTC/USDT": bars},
        decision_time_ms=decision,
    )

    assert report.selected == ()
    assert not report.context_errors
    assert len(report.rows) == 6
    assert report.counts == {"NOT_APPLICABLE": 6}
    assert all(row["selected"] is False for row in report.rows)
    assert all(row["admitted_for_paper"] is False for row in report.rows)
    assert all(row["validation_status"] in {"NO_GROSS_EDGE", "COST_KILLED"} for row in report.rows)
    assert all(row["eligibility_reason"] for row in report.rows)


def test_ledger_statuses_are_reported_with_expected_gross_edge() -> None:
    bars = _bars()
    decision = bars[-1].timestamp + timeframe_ms(TF)
    report = evaluate_eligibility(
        ledger_path=REPO / "config" / "strategy_admission.json",
        assets=["BTC"],
        timeframe=TF,
        bars_by_symbol={"BTC/USDT": bars},
        decision_time_ms=decision,
    )
    by_id = {row["strategy_id"]: row for row in report.rows}
    assert by_id["mean_reversion@5m"]["validation_status"] == "COST_KILLED"
    assert by_id["mean_reversion@5m"]["expected_gross_edge_bps"] == 1.49
    assert by_id["ema_crossover@5m"]["validation_status"] == "NO_GROSS_EDGE"
