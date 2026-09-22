"""Bottleneck model tests (Track F, POC02-LAUNCH-AND-DISCOVERY-BATCH-02)."""

from __future__ import annotations

import pytest

from trading_bot.paper.bottleneck import (
    BottleneckState,
    BottleneckWindow,
    classify_window,
    regime_bottleneck_table,
)


def test_phase_b_no_signal() -> None:
    w = classify_window(
        window_id="2026-09-08",
        activity={"market_scans": 1, "trade_proposals": 0},
        regime="RANGE",
    )
    assert w.bottleneck == BottleneckState.NO_SIGNAL
    assert "PHASE B" in w.reason
    assert w.counts["scans"] == 1


def test_phase_a_risk_cooldown() -> None:
    w = classify_window(
        window_id="w2",
        activity={
            "market_scans": 10,
            "trade_proposals": 5,
            "selected_decisions": 2,
            "risk_rejects": 2,
            "risk_rejects_by_reason": {"CONSECUTIVE_LOSS_COOLDOWN": 2},
        },
    )
    assert w.bottleneck == BottleneckState.RISK_COOLDOWN


def test_phase_a_risk_positions() -> None:
    w = classify_window(
        window_id="w3",
        activity={
            "market_scans": 10,
            "trade_proposals": 5,
            "selected_decisions": 3,
            "risk_rejects": 1,
            "risk_rejects_by_reason": {"MAX_POSITIONS": 1},
        },
    )
    assert w.bottleneck == BottleneckState.RISK_POSITIONS


def test_agent_filter() -> None:
    w = classify_window(
        window_id="w4",
        activity={"market_scans": 3, "trade_proposals": 4, "selected_decisions": 0},
    )
    assert w.bottleneck == BottleneckState.AGENT_FILTER


def test_verifier_filter() -> None:
    w = classify_window(
        window_id="w5",
        activity={
            "market_scans": 3,
            "trade_proposals": 2,
            "selected_decisions": 1,
            "verifier_rejects": 1,
        },
    )
    assert w.bottleneck == BottleneckState.VERIFIER_FILTER


def test_execution_and_none() -> None:
    w_exec = classify_window(
        window_id="w6",
        activity={
            "market_scans": 3,
            "trade_proposals": 2,
            "selected_decisions": 1,
            "risk_accepts": 1,
            "broker_errors": 1,
        },
    )
    assert w_exec.bottleneck == BottleneckState.EXECUTION

    w_none = classify_window(
        window_id="w7",
        activity={
            "market_scans": 3,
            "trade_proposals": 2,
            "selected_decisions": 1,
            "risk_accepts": 1,
            "executed_paper_trades": 1,
        },
    )
    assert w_none.bottleneck == BottleneckState.NONE


def test_unobserved_window_is_not_mislabeled() -> None:
    w = classify_window(window_id="w8", activity={"market_scans": 0})
    assert w.bottleneck == BottleneckState.NONE
    assert "not observed" in w.reason


def test_regime_table_concentration() -> None:
    windows = [
        classify_window(window_id="a", activity={"market_scans": 1}, regime="RANGE"),
        classify_window(window_id="b", activity={"market_scans": 1}, regime="RANGE"),
        classify_window(
            window_id="c",
            activity={
                "market_scans": 1,
                "trade_proposals": 1,
                "selected_decisions": 1,
                "risk_rejects": 1,
                "risk_rejects_by_reason": {"MAX_POSITIONS": 1},
            },
            regime="FUSED",
        ),
    ]
    table = regime_bottleneck_table(windows)
    assert table["RANGE"][BottleneckState.NO_SIGNAL] == 2
    assert table["FUSED"][BottleneckState.RISK_POSITIONS] == 1


def test_window_is_pure_data() -> None:
    w = classify_window(window_id="x", activity={"market_scans": 1})
    assert isinstance(w, BottleneckWindow)
    d = w.to_dict()
    assert d["bottleneck"] == BottleneckState.NO_SIGNAL
    # observational: no gate/block hooks exist on the dataclass
    assert not any(callable(getattr(w, name, None)) for name in ("gate", "block", "route"))


def test_activity_with_zero_scans_and_proposals_neither_nor() -> None:
    w = classify_window(window_id="y", activity={})
    assert w.bottleneck == BottleneckState.NONE


@pytest.mark.parametrize(
    ("activity", "expected"),
    [
        (
            {
                "market_scans": 1,
                "trade_proposals": 1,
                "selected_decisions": 1,
                "risk_accepts": 1,
                "executed_paper_trades": 1,
            },
            BottleneckState.NONE,
        ),
        ({"market_scans": 1, "trade_proposals": 0}, BottleneckState.NO_SIGNAL),
        (
            {"market_scans": 1, "trade_proposals": 1, "selected_decisions": 0},
            BottleneckState.AGENT_FILTER,
        ),
        (
            {
                "market_scans": 1,
                "trade_proposals": 1,
                "selected_decisions": 1,
                "verifier_rejects": 1,
            },
            BottleneckState.VERIFIER_FILTER,
        ),
        # POC02-OBSERVATION taxonomy §5: rejections without a persisted
        # reason split are OTHER_RISK — labeling them RISK_COOLDOWN without
        # evidence was an inference, now forbidden.
        (
            {"market_scans": 1, "trade_proposals": 1, "selected_decisions": 1, "risk_rejects": 1},
            BottleneckState.OTHER_RISK,
        ),
        (
            {
                "market_scans": 1,
                "trade_proposals": 1,
                "selected_decisions": 1,
                "risk_rejects": 2,
                "risk_rejects_by_reason": {"CONSECUTIVE_LOSS_COOLDOWN": 2},
            },
            BottleneckState.RISK_COOLDOWN,
        ),
        (
            {
                "market_scans": 1,
                "trade_proposals": 1,
                "selected_decisions": 1,
                "risk_rejects": 2,
                "risk_rejects_by_reason": {"MAX_POSITIONS": 1, "MAX_TOTAL_EXPOSURE": 1},
            },
            BottleneckState.RISK_POSITIONS,
        ),
        (
            {
                "market_scans": 1,
                "trade_proposals": 1,
                "selected_decisions": 1,
                "risk_rejects": 1,
                "risk_rejects_by_reason": {"OTHER": 1},
            },
            BottleneckState.OTHER_RISK,
        ),
        (
            {
                "market_scans": 1,
                "trade_proposals": 1,
                "selected_decisions": 1,
                "risk_rejects": 3,
                "risk_rejects_by_reason": {
                    "CONSECUTIVE_LOSS_COOLDOWN": 1,
                    "MAX_POSITIONS": 1,
                    "OTHER": 1,
                },
            },
            BottleneckState.OTHER_RISK,
        ),
    ],
)
def test_classification_matrix(activity: dict, expected: str) -> None:
    assert classify_window(window_id="z", activity=activity).bottleneck == expected


def test_other_risk_is_in_canonical_taxonomy() -> None:
    assert "OTHER_RISK" in BottleneckState.ALL
