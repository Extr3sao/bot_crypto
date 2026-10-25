"""WP-EDGE-02 rules: the trend-robustness verdict, the uncertainty intervals, the audit.

These tests pin the four things WP-EDGE-02 rests on:

* the robustness verdict is a PURE function of the declared numbers, so a run cannot be
  promoted by the arithmetic going its way: a concentrated, interval-straddling reading
  lands on ``INSUFFICIENT_EVIDENCE``, a contradicted one on ``REJECT`` and only a clean
  one on ``ADMIT_PAPER``;
* the uncertainty intervals are the declared procedures — the Newey-West lag rule, the
  Student-t critical value and the seeded xorshift64* block bootstrap — and two runs of
  the same procedure with the same seed agree exactly;
* the H6 risk audit's refusal rules MEAN what the declared reasons say: a refusal is
  correct only when the stated limit really was breached in the captured state, and the
  runtime Risk Engine's own decision order is restated rather than assumed;
* DEF-EDGE02-01 stays fixed: the observing wrapper reads the live positions mapping, so
  an entry taken while the book is flat is still attributed its own size. The bug it
  replaces (``positions or {}`` on a falsy-but-live dict) is reproduced here on purpose,
  because the invariant that caught it is only worth having while the bug is impossible.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from trading_bot.research.edge01 import risk_audit as A
from trading_bot.research.edge01 import robustness as R
from trading_bot.research.edge01.simulator import PortfolioResult, RiskPolicy, _Gate

ROOT = Path(__file__).resolve().parents[3]
WP02 = ROOT / "reports" / "edge-recovery" / "WP-EDGE-02"


def policy(**overrides: Any) -> RiskPolicy:
    base = dict(
        risk_per_trade_pct=0.25,
        max_open_positions=3,
        max_total_exposure_pct=25.0,
        max_asset_exposure_pct=10.0,
        min_notional_usdt=20.0,
        max_notional_usdt=500.0,
        drawdown_halt_pct=5.0,
        max_consecutive_losses=3,
        consecutive_loss_cooldown_minutes=60.0,
        max_trades_per_day=20,
        start_equity=10_000.0,
    )
    base.update(overrides)
    return RiskPolicy(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# statistics
# --------------------------------------------------------------------------- #


def test_t_critical_matches_published_student_t_values() -> None:
    assert R._t_critical(51) == pytest.approx(2.00758, abs=1e-4)
    assert R._t_critical(30) == pytest.approx(2.04227, abs=1e-4)
    assert R._t_critical(100) == pytest.approx(1.98397, abs=1e-4)
    # the heavy tail is not guessed by the asymptotic formula: the declared table holds it
    assert R._t_critical(1) == pytest.approx(12.7062, abs=1e-4)
    assert R._t_critical(9) == pytest.approx(2.26216, abs=1e-4)
    assert R._t_critical(1) > R._t_critical(51) > R._t_critical(100)


def test_hac_lag_follows_the_declared_rule() -> None:
    assert R._hac_lag(52) == 3
    assert R._hac_lag(10) == 2
    assert R._hac_lag(1) == 0


def test_hac_interval_widens_with_positive_autocorrelation() -> None:
    rng = R.__dict__  # only to keep the module import local to this test file
    assert rng  # placeholder-free: the interval is exercised below
    alternating = [(-1.0) ** i for i in range(40)]
    trending = [float(i % 4) for i in range(40)]
    alternating_interval = R.hac_mean_interval(alternating)
    trending_interval = R.hac_mean_interval(trending)
    assert alternating_interval["lower"] is not None
    assert trending_interval["se"] > alternating_interval["se"]
    for interval in (alternating_interval, trending_interval):
        assert interval["lower"] <= interval["mean"] <= interval["upper"]


def test_hac_interval_is_centred_on_the_mean() -> None:
    values = [1.0, -2.0, 3.0, -1.0, 5.0, -0.5, 2.0, 4.0, -3.0, 1.5]
    interval = R.hac_mean_interval(values)
    assert interval["mean"] == pytest.approx(sum(values) / len(values))
    assert interval["lower"] < interval["mean"] < interval["upper"]
    assert interval["lag"] == R._hac_lag(len(values))


def test_block_bootstrap_is_deterministic_and_seed_sensitive() -> None:
    values = [3.0, -1.0, 4.0, -2.0, 1.0, 0.5, -0.25, 2.5]
    first = R.block_bootstrap_mean_interval(values, resamples=300)
    again = R.block_bootstrap_mean_interval(values, resamples=300)
    other = R.block_bootstrap_mean_interval(values, resamples=300, seed=7)
    assert first == again
    assert first["lower"] is not None and first["upper"] is not None
    assert (other["lower"], other["upper"]) != (first["lower"], first["upper"])


def test_leave_out_largest_removes_exactly_the_named_winners() -> None:
    nets = [10.0, 40.0, -5.0, 2.0]
    one = R.leave_out_largest(nets, 1)
    three = R.leave_out_largest(nets, 3)
    assert one["dropped_usdt"] == 40.0
    assert one["net_usdt"] == pytest.approx(7.0)
    assert one["trades"] == 3
    assert three["trades"] == 1
    assert three["net_usdt"] == pytest.approx(-5.0)


# --------------------------------------------------------------------------- #
# trend verdict
# --------------------------------------------------------------------------- #


def _trend_payload(
    *,
    trades: int = 52,
    net: float = 208.0056,
    share: float | None = 0.7987,
    leave_one: float = 41.87,
    leave_three: float = -221.33,
    hac: tuple[float, float] = (-9.27, 17.27),
    adverse: float | None = 146.89,
    positive_assets: int = 2,
    positive_periods: int = 2,
    drawdown: float = 2.567,
    hold_drawdown: float = 73.2,
) -> dict[str, Any]:
    assets = {
        f"A{index}": {"net_usdt": 10.0 if index < positive_assets else -10.0}
        for index in range(3)
    }
    periods = [
        {"period": f"P{index}", "net_usdt": 1.0 if index < positive_periods else -1.0}
        for index in range(3)
    ]
    sensitivity = {
        "leave_out": [
            {"k": 1, "net_usdt": leave_one, "net_removed_usdt": net - leave_one},
            {"k": 3, "net_usdt": leave_three, "net_removed_usdt": net - leave_three},
        ]
    }
    payload: dict[str, Any] = {
        "runs": {
            "OOS:BASE": {
                "combined": {
                    "trades": trades,
                    "net_usdt": net,
                    "largest_trade_share_of_net": share,
                    "max_drawdown_pct": drawdown,
                },
                "assets": assets,
                "periods": periods,
            },
            "OOS:ADVERSE": {"combined": {"net_usdt": adverse, "trades": trades}},
        },
        "sensitivity": {"OOS:BASE": sensitivity},
        "uncertainty": {
            "OOS:BASE": {
                "hac": {"lower": hac[0], "upper": hac[1], "lag": 3, "mean": net / trades},
                "bootstrap": {"lower": hac[0] - 2.0, "upper": hac[1] + 1.0},
            }
        },
        "risk_adjusted": {
            "OOS:BASE": {"deepest_buy_and_hold_drawdown_pct": hold_drawdown}
        },
        "wp_admission": {"verdict": "INSUFFICIENT_EVIDENCE"},
    }
    return payload


def test_trend_verdict_refuses_a_concentrated_reading() -> None:
    verdict = R.trend_robustness_verdict(_trend_payload())
    assert verdict["verdict"] == "INSUFFICIENT_EVIDENCE"
    assert verdict["decisive_failures"] == []
    assert "concentration_within_limit" in verdict["inconclusive_failures"]
    assert "the edge is not contradicted" in verdict["headline"]


def test_trend_verdict_rejects_when_the_single_winner_carries_the_book() -> None:
    verdict = R.trend_robustness_verdict(_trend_payload(leave_one=-5.0))
    assert verdict["verdict"] == "REJECT"
    assert "oos_net_positive_per_dropping_largest_winner" in verdict["decisive_failures"]


def test_trend_verdict_rejects_when_the_interval_says_no_positive_expectancy() -> None:
    verdict = R.trend_robustness_verdict(_trend_payload(hac=(-30.0, -1.5), leave_one=5.0))
    assert verdict["verdict"] == "REJECT"
    assert "hac_interval_upper_end_positive" in verdict["decisive_failures"]


def test_trend_verdict_admits_only_a_clean_reading() -> None:
    verdict = R.trend_robustness_verdict(_trend_payload(share=0.31, hac=(0.5, 7.5)))
    assert verdict["verdict"] == "ADMIT_PAPER"
    assert verdict["reasons"] == []
    assert all(check["result"] == "PASS" for check in verdict["checks"])


def test_trend_verdict_is_unpowered_below_the_trade_floor() -> None:
    verdict = R.trend_robustness_verdict(_trend_payload(trades=12, share=0.31, hac=(0.5, 7.5)))
    assert verdict["verdict"] == "INSUFFICIENT_EVIDENCE"
    assert "cannot support a conclusion" in verdict["headline"]


def test_trend_decision_keeps_the_wp_edge01_concentration_limit() -> None:
    assert (
        R.TREND_ROBUSTNESS_DECISION["concentration_criterion_pct_of_net"]
        == 0.50
    )
    assert (
        R.TREND_ROBUSTNESS_DECISION["concentration_criterion_unchanged_from"]
        == "WP-EDGE-01 OOS_TREND_DECISION.max_single_trade_share_of_net"
    )
    proposal = R.TREND_ROBUSTNESS_DECISION["proposal_not_applied"]
    assert "NOT applied" in proposal["status"]


# --------------------------------------------------------------------------- #
# risk refusal rules and the runtime comparison
# --------------------------------------------------------------------------- #


def test_drawdown_halt_refusal_needs_the_configured_threshold_breached() -> None:
    state = {"drawdown_pct": 5.0, "drawdown_halt_pct": 5.0}
    correct, detail = A.refusal_is_correct("risk_drawdown_halt", state)
    assert correct and "5.0" in detail
    below = {"drawdown_pct": 4.999999, "drawdown_halt_pct": 5.0}
    assert A.refusal_is_correct("risk_drawdown_halt", below)[0] is False


def test_cooldown_refusal_needs_the_instant_inside_the_window() -> None:
    assert A.refusal_is_correct(
        "risk_loss_cooldown", {"decision_ts": 1_000, "cooldown_until_ts": 2_000}
    )[0]
    assert not A.refusal_is_correct(
        "risk_loss_cooldown", {"decision_ts": 2_000, "cooldown_until_ts": 2_000}
    )[0]
    assert not A.refusal_is_correct(
        "risk_loss_cooldown", {"decision_ts": 3_000, "cooldown_until_ts": 2_000}
    )[0]


def test_every_declared_refusal_reason_has_a_rule() -> None:
    declared = set(A.RISK_AUDIT_DECISION["refusal_rules"])
    state = {
        "drawdown_pct": 9.0,
        "drawdown_halt_pct": 5.0,
        "decision_ts": 1,
        "cooldown_until_ts": 2,
        "open_positions_count": 3,
        "max_open_positions": 3,
        "trades_today": 20,
        "max_trades_per_day": 20,
        "open_notional": 2_500.0,
        "entry_notional": 10.0,
        "exposure_cap": 2_500.0,
        "min_notional_usdt": 20.0,
        "asset_held": True,
        "stop": 100.0,
        "entry_fill": 99.0,
        "entry_mid": -1.0,
    }
    for reason in declared:
        assert A.refusal_is_correct(reason, state)[0] is True, reason
    assert A.refusal_is_correct("risk_made_up", state)[0] is False


def test_runtime_decision_follows_the_risk_manager_order() -> None:
    state = {
        "trades_today": 20,
        "max_trades_per_day": 20,
        "open_positions_count": 1,
        "max_open_positions": 3,
        "decision_ts": 5_000,
        "cooldown_until_ts": 6_000,
        "drawdown_pct": 9.0,
        "drawdown_halt_pct": 5.0,
    }
    decision = A.expected_runtime_decision(state)
    assert decision["approved"] is False
    assert decision["blocked_by"] == "daily_trade_limit"  # first rule wins
    quiet = dict(state, trades_today=0, decision_ts=7_000)
    assert A.expected_runtime_decision(quiet)["blocked_by"] == "max_drawdown"
    assert "daily_drawdown" in decision["rules_not_modelled_by_the_research_budget"]


def test_risk_audit_verdict_reports_findings() -> None:
    clean = {
        "summary": {
            "refusals_incorrect": 0,
            "invariants_failed": 0,
            "runtime_disagreements": 0,
            "orders_refused_matches_captured_refusals": True,
            "primary_window": "DEV:BASE",
            "primary_arm": "plan_limit",
            "orders_placed": 686,
            "orders_filled": 372,
            "orders_refused": 183,
            "primary_refusals": 183,
            "primary_refusals_correct": 183,
            "refusal_reasons": {"risk_drawdown_halt": 148, "risk_loss_cooldown": 35},
        }
    }
    verdict = A.risk_audit_verdict(clean)
    assert verdict["verdict"] == "AUDIT_PASS"
    dirty = json.loads(json.dumps(clean))
    dirty["summary"]["refusals_incorrect"] = 1
    dirty["summary"]["orders_refused_matches_captured_refusals"] = False
    findings = A.risk_audit_verdict(dirty)
    assert findings["verdict"] == "AUDIT_FINDINGS"
    assert len(findings["findings"]) == 2


# --------------------------------------------------------------------------- #
# DEF-EDGE02-01: the observer must read the live positions mapping
# --------------------------------------------------------------------------- #


class _Signal:
    candidate = "edge_intra_01r"
    symbol = "ETH"
    stop = 95.0

    def __init__(self) -> None:
        self.entry_limit = 100.0


class _Position:
    entry_fill = 100.0
    notional = 250.0
    qty = 2.5
    stop_distance = 5.0
    planned_risk_usdt = 25.0


def _observe(monkeypatch: pytest.MonkeyPatch, positions: dict[str, Any], *, refuse: bool) -> dict[str, Any]:
    result = PortfolioResult()

    def fake_enter(*args: Any, **kwargs: Any) -> float:
        if refuse:
            result.refusals.append({"reason": "risk_drawdown_halt", "symbol": "ETH"})
            return 0.0
        positions["ETH"] = _Position()
        return -250.0

    monkeypatch.setitem(A._ORIGINALS, "enter", fake_enter)
    capture = A._Capture(key="DEV:BASE", arm="plan_limit", window="DEV", scenario="BASE")
    monkeypatch.setattr(A, "_CAPTURE", capture)
    gate = _Gate(peak_equity=9_000.0)
    A._observing_enter(
        signal=_Signal(),
        result=result,
        positions=positions,
        policy=policy(),
        gate=gate,
        mid=100.0,
        equity=8_000.0,  # the book is 11.11% below its peak, past the 5% halt
        ts=1_728_310_500_000,
    )
    assert capture.records, "the observer must always record the entry attempt"
    return capture.records[-1]


def test_observer_reads_a_live_but_empty_positions_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    """DEF-EDGE02-01: a falsy-but-live dict must not be replaced by a fresh one."""
    record = _observe(monkeypatch, {}, refuse=False)
    assert record["outcome"] == "filled_or_placed"
    assert record["asset_held"] is True
    assert record["entry_notional"] == 250.0
    assert record["entry_qty"] == 2.5
    assert record["entry_fill"] == 100.0


def test_observer_records_the_state_a_refusal_saw(monkeypatch: pytest.MonkeyPatch) -> None:
    record = _observe(monkeypatch, {}, refuse=True)
    assert record["outcome"] == "refused"
    assert record["reason"] == "risk_drawdown_halt"
    assert record["drawdown_pct"] == pytest.approx((9_000.0 - 8_000.0) / 9_000.0 * 100.0, abs=1e-6)
    assert A.refusal_is_correct("risk_drawdown_halt", record)[0] is True


def test_observer_is_installed_and_removed_without_leaving_a_trace() -> None:
    import trading_bot.research.edge01.simulator as S

    original = S._enter
    A.install_observer()
    try:
        assert S._enter is not original
        A.install_observer()  # idempotent
        assert S._enter is not original
    finally:
        A.remove_observer()
    assert S._enter is original
    assert A._ORIGINALS == {}


# --------------------------------------------------------------------------- #
# the published artefacts
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(
    not (WP02 / "h6-risk-audit" / "RISK_AUDIT.json").exists(),
    reason="the WP-EDGE-02 audit artefacts have not been generated",
)
def test_published_risk_audit_has_the_expected_shape() -> None:
    payload = json.loads(
        (WP02 / "h6-risk-audit" / "RISK_AUDIT.json").read_text(encoding="utf-8")
    )
    summary = payload["summary"]
    assert summary["orders_placed"] == 686
    assert summary["orders_filled"] == 372
    assert summary["orders_refused"] == 183
    assert summary["refusal_reasons"] == {
        "risk_drawdown_halt": 148,
        "risk_loss_cooldown": 35,
    }
    assert summary["primary_refusals_correct"] == 183
    assert summary["invariants_failed"] == 0
    assert payload["verdict"]["verdict"] == "AUDIT_PASS"
    assert payload["reproduction"]["all_equal"] is True


@pytest.mark.skipif(
    not (WP02 / "trend-robustness" / "ROBUSTNESS.json").exists(),
    reason="the WP-EDGE-02 robustness artefacts have not been generated",
)
def test_published_robustness_reproduces_and_refuses_to_promote() -> None:
    payload = json.loads(
        (WP02 / "trend-robustness" / "ROBUSTNESS.json").read_text(encoding="utf-8")
    )
    assert payload["reproduction"]["all_equal"] is True
    oos = payload["runs"]["OOS:BASE"]["combined"]
    assert oos["net_usdt"] == pytest.approx(208.0056, abs=1e-4)
    assert oos["trades"] == 52
    assert payload["runs"]["OOS:ADVERSE"]["combined"]["net_usdt"] == pytest.approx(
        146.8908, abs=1e-4
    )
    assert payload["sensitivity"]["OOS:BASE"]["leave_out"][0]["net_usdt"] == pytest.approx(
        41.874, abs=1e-2
    )
    assert payload["verdict"]["verdict"] == "INSUFFICIENT_EVIDENCE"
    assert payload["verdict"]["verdict"] != "ADMIT_PAPER"
    assert payload["corpus_coverage"]["additional_independent_periods_available"] is False
