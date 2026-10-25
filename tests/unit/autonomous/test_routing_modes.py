"""WP-STRAT-07 — lifecycle-aware routing modes in the PAPER runtime.

The dynamic plane used to be reachable only from scripts and tests. These tests
pin the three modes and the invariants the request requires:

* LEGACY is the default and changes nothing;
* SHADOW runs the lifecycle-aware selection next to the legacy one and records
  the same-context comparison WITHOUT affecting execution;
* LIFECYCLE lets the lifecycle-aware eligible set gate executable proposals
  (PAPER only), and only ``ACTIVE`` / explicitly authorised states route;
* a bridge failure fails CLOSED in LIFECYCLE mode.

Nothing here touches LIVE, capital or credentials.
"""

from __future__ import annotations

import asyncio
from typing import Any

from trading_bot.autonomous.admission_ledger import AdmissionLedger
from trading_bot.autonomous.contracts import DecisionMode
from trading_bot.strategy_lifecycle.portfolio import StrategyPortfolioManager
from trading_bot.strategy_lifecycle.runtime_bridge import (
    LifecycleRoutingAdapter,
    StrategyRoutingMode,
)

from .helpers import ledger_payload, make_admitted_ledger, make_ledger, make_runtime

SID = "ema_crossover@5m"


def _run(runtime: Any, **kwargs: Any) -> Any:
    return asyncio.run(runtime.run(**kwargs))


class _FakeEco:
    """Minimal ecosystem stand-in exposing ``lifecycle_map`` + ``version``."""

    version = "test-eco-v1"

    def __init__(self, mapping: dict[str, str]) -> None:
        self._mapping = mapping

    def lifecycle_map(self) -> dict[str, str]:
        return dict(self._mapping)


def test_legacy_mode_is_the_default_and_unchanged(tmp_path: Any) -> None:
    runtime, _scanner, _broker = make_runtime(
        run_dir=tmp_path, ledger=make_admitted_ledger(gross_bps=50.0)
    )
    assert runtime.routing_mode is StrategyRoutingMode.LEGACY
    summary = _run(runtime, cycles=1)
    assert summary.totals()["paper_trades"] == 1
    assert runtime.routing_comparisons == ()
    assert not (tmp_path / "routing_comparisons.jsonl").exists()


def test_shadow_records_a_comparison_and_does_not_change_execution(tmp_path: Any) -> None:
    runtime, _scanner, _broker = make_runtime(
        run_dir=tmp_path,
        ledger=make_admitted_ledger(gross_bps=50.0),  # PAPER_CANDIDATE
        routing_mode="SHADOW",
    )
    summary = _run(runtime, cycles=1)
    # execution is the UNCHANGED legacy result
    assert summary.totals()["paper_trades"] == 1
    comparisons = runtime.routing_comparisons
    assert len(comparisons) == 1
    comparison = comparisons[0]
    assert comparison.asset == "BTC"
    assert comparison.timeframe == "5m"
    # PAPER_CANDIDATE maps to SHADOW -> lifecycle abstains while legacy trades
    assert comparison.legacy_selected == (SID,)
    assert comparison.lifecycle_selected == ()
    assert any(d.startswith("LEGACY_ONLY:") for d in comparison.differences)
    # the comparison is written as evidence
    rows = (tmp_path / "routing_comparisons.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(rows) == 1


def test_lifecycle_mode_with_paper_active_trades_and_agrees(tmp_path: Any) -> None:
    ledger = make_ledger(status="PAPER_ACTIVE", admitted=True, gross_bps=50.0)
    runtime, _scanner, _broker = make_runtime(
        run_dir=tmp_path, ledger=ledger, routing_mode="LIFECYCLE"
    )
    summary = _run(runtime, cycles=1)
    assert summary.totals()["paper_trades"] == 1
    comparison = runtime.routing_comparisons[0]
    assert comparison.lifecycle_selected == (SID,)
    assert comparison.differences == ("AGREE",)
    # §11 provenance: strategy_version is family@timeframe, never the timeframe
    trace = runtime.trace_store.read()[0]
    assert trace.proposal is not None
    assert trace.proposal["strategy_version"] == SID
    # §14/§15: the comparison is stamped with the SAME decision time as the
    # trace, so registry/health/regime were read on one coherent snapshot.
    assert comparison.decision_time_ms == trace.decision_time_ms


def test_lifecycle_mode_blocks_a_non_active_strategy(tmp_path: Any) -> None:
    runtime, _scanner, _broker = make_runtime(
        run_dir=tmp_path,
        ledger=make_admitted_ledger(gross_bps=50.0),  # PAPER_CANDIDATE -> SHADOW
        routing_mode="LIFECYCLE",
    )
    summary = _run(runtime, cycles=1)
    assert summary.totals()["paper_trades"] == 0
    row = summary.cycle_reports[0].assets[0]
    assert row.mode is DecisionMode.NO_TRADE
    comparison = runtime.routing_comparisons[0]
    assert comparison.lifecycle_selected == ()
    assert SID in comparison.lifecycle_rejected
    # the refusal is named on the persisted trace row, never silently dropped
    trace = runtime.trace_store.read()[0]
    assert any(
        str(considered.get("router_reason", "")).startswith("lifecycle_excluded:")
        for considered in trace.strategies_considered
    )


def test_lifecycle_override_can_pause_an_otherwise_active_strategy(tmp_path: Any) -> None:
    ledger = make_ledger(status="PAPER_ACTIVE", admitted=True, gross_bps=50.0)
    runtime, _scanner, _broker = make_runtime(
        run_dir=tmp_path,
        ledger=ledger,
        routing_mode="LIFECYCLE",
        lifecycle_ecosystem=_FakeEco({SID: "PAUSED"}),
    )
    summary = _run(runtime, cycles=1)
    assert summary.totals()["paper_trades"] == 0
    assert runtime.routing_comparisons[0].lifecycle_rejected[SID] == "PAUSED"


def _two_active_strategies() -> AdmissionLedger:
    a = ledger_payload(
        strategy_id="a@5m",
        family="ema_crossover",
        status="PAPER_ACTIVE",
        admitted=True,
        gross_bps=40.0,
    )
    b = ledger_payload(
        strategy_id="b@5m",
        family="ema_crossover",
        status="PAPER_ACTIVE",
        admitted=True,
        gross_bps=30.0,
    )
    payload = {"_period": "unit-test-window", "strategies": {**a["strategies"], **b["strategies"]}}
    return AdmissionLedger.from_dict(payload, source_path="test-ledger.json")


def test_lifecycle_mode_arbitrates_portfolio_conflicts(tmp_path: Any) -> None:
    # §12 — two same-direction candidates on one asset; the portfolio manager
    # may only REDUCE. With a cap of 1 same-direction per asset the second is
    # dropped before the winner is chosen, and the refusal is recorded.
    runtime, _scanner, _broker = make_runtime(
        run_dir=tmp_path, ledger=_two_active_strategies(), routing_mode="LIFECYCLE"
    )
    runtime._portfolio = StrategyPortfolioManager(
        equity=10_000.0,
        max_asset_exposure_pct=10.0,
        max_total_exposure_pct=25.0,
        max_same_direction_per_asset=1,
    )
    summary = _run(runtime, cycles=1)
    assert summary.totals()["paper_trades"] == 1
    comparison = runtime.routing_comparisons[0]
    assert len(comparison.portfolio_rejected) == 1
    assert set(comparison.portfolio_rejected.values()) == {"PORTFOLIO_CONFLICT"}


def test_lifecycle_bridge_failure_fails_closed(tmp_path: Any, monkeypatch: Any) -> None:
    ledger = make_ledger(status="PAPER_ACTIVE", admitted=True, gross_bps=50.0)
    runtime, _scanner, _broker = make_runtime(
        run_dir=tmp_path, ledger=ledger, routing_mode="LIFECYCLE"
    )

    def _boom(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("bridge boom")

    monkeypatch.setattr(LifecycleRoutingAdapter, "select", _boom)
    summary = _run(runtime, cycles=1)
    assert summary.totals()["paper_trades"] == 0  # fail CLOSED, never open
