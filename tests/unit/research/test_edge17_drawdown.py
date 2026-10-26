"""WP-EDGE-017F/P0.3 — drawdown must come from a curve, not from a peak level.

The EDGE-017 report published ``drawdown_pct = risk_state_at_end.peak_equity``,
i.e. 10 000.0: a balance, not a percentage. These tests pin the replacement and,
critically, the ``UNKNOWN`` branch: one mark cannot describe a fall, so the
report must say so instead of deriving a number from it.
"""

from __future__ import annotations

import pytest

from trading_bot.research.equity_drawdown import max_drawdown

#: 1 000 ms steps are enough; only the order and the values matter here.
T = 1_791_000_000_000


def _curve(*values: float) -> list[tuple[int, float]]:
    return [(T + index * 1_000, value) for index, value in enumerate(values)]


def test_a_single_peak_to_trough_is_measured_in_percent_and_usdt() -> None:
    result = max_drawdown(_curve(10_000.0, 11_000.0, 9_000.0, 10_500.0))

    assert result.status == "MEASURED"
    assert result.drawdown_pct == pytest.approx((11_000.0 - 9_000.0) / 11_000.0 * 100.0)
    assert result.drawdown_usdt == pytest.approx(2_000.0)
    assert result.peak_equity == pytest.approx(11_000.0)
    assert result.trough_equity == pytest.approx(9_000.0)
    assert result.peak_ts_ms == T + 1_000
    assert result.trough_ts_ms == T + 2_000
    assert result.points == 4


def test_the_worst_fall_is_taken_even_if_a_later_peak_is_higher() -> None:
    # first fall: 10 000 -> 8 000 (20%); second: 12 000 -> 11 000 (8.3%)
    result = max_drawdown(_curve(10_000.0, 8_000.0, 12_000.0, 11_000.0))

    assert result.drawdown_pct == pytest.approx(20.0)
    assert result.peak_ts_ms == T
    assert result.trough_ts_ms == T + 1_000


def test_a_flat_or_rising_curve_has_zero_drawdown() -> None:
    flat = max_drawdown(_curve(10_000.0, 10_000.0, 10_000.0))
    rising = max_drawdown(_curve(10_000.0, 10_500.0, 11_000.0))

    assert flat.status == rising.status == "MEASURED"
    assert flat.drawdown_pct == pytest.approx(0.0)
    assert rising.drawdown_pct == pytest.approx(0.0)
    assert flat.drawdown_usdt == pytest.approx(0.0)


def test_a_wipeout_is_one_hundred_percent_not_a_balance() -> None:
    # the trough is 0, so the fall from the 10 000 peak is the whole peak
    result = max_drawdown(_curve(10_000.0, 4_000.0, 0.0))

    assert result.drawdown_pct == pytest.approx(100.0)
    assert result.drawdown_usdt == pytest.approx(10_000.0)
    assert result.peak_ts_ms == T
    assert result.trough_ts_ms == T + 2_000


def test_a_peak_level_published_as_a_percentage_is_impossible() -> None:
    """Regression: a USDT level masquerading as ``drawdown_pct``.

    A curve whose peak is 10 000 cannot produce a percentage above 100, and a
    book that never fell must produce 0 — the old code returned 10 000.0 for both.
    """
    never_fell = max_drawdown(_curve(10_000.0, 10_000.0, 9_761.0, 9_761.0))

    assert never_fell.drawdown_pct is not None
    assert 0.0 <= never_fell.drawdown_pct <= 100.0
    assert never_fell.drawdown_pct == pytest.approx(2.39)
    assert never_fell.drawdown_pct != pytest.approx(10_000.0)


@pytest.mark.parametrize(
    ("points", "reason_fragment"),
    [
        ([], "0 usable"),
        (_curve(10_000.0), "1 usable"),
        ([(T, float("nan")), (T + 1_000, 10_000.0)], "1 usable"),
        ([(T, 10_000.0), (T + 1_000, float("inf"))], "1 usable"),
    ],
)
def test_insufficient_evidence_is_unknown_never_a_number(
    points: list[tuple[int, float]], reason_fragment: str
) -> None:
    result = max_drawdown(points)

    assert result.status == "UNKNOWN"
    assert result.drawdown_pct is None
    assert result.drawdown_usdt is None
    assert result.reason is not None and reason_fragment in result.reason


def test_a_negative_peak_is_unknown_because_the_percentage_is_undefined() -> None:
    result = max_drawdown(_curve(-1_000.0, -2_000.0))

    assert result.status == "UNKNOWN"
    assert result.reason is not None and "not positive" in result.reason


def test_unparsable_points_are_dropped_and_counted() -> None:
    result = max_drawdown(
        [  # type: ignore[list-item]
            (T, 10_000.0),
            ("not-a-timestamp", 9_000.0),
            (T + 1_000, 9_500.0),
        ]
    )

    assert result.status == "MEASURED"
    assert result.points == 2
    assert result.drawdown_pct == pytest.approx(5.0)


def test_the_serialised_contract_carries_the_method_and_no_invented_numbers() -> None:
    measured = max_drawdown(_curve(10_000.0, 9_000.0)).to_dict()
    unknown = max_drawdown(_curve(10_000.0)).to_dict()

    assert measured["status"] == "MEASURED"
    assert measured["method"] == "max peak-to-trough of the mark-to-market net equity curve"
    assert unknown == {
        **unknown,
        "status": "UNKNOWN",
        "drawdown_pct": None,
        "drawdown_usdt": None,
    }
    assert unknown["reason"]
