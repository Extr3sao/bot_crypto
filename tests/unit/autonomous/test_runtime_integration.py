"""Runtime integration + adversarial false-success matrix.

Every test here is a negative claim turned into an executable check: the
runtime must NOT be able to declare success (or place an order) when a
precondition is missing.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from trading_bot.autonomous.contracts import DecisionMode, VerifierVerdict
from trading_bot.autonomous.costs import COST_MODEL_VERSION
from trading_bot.market_data.types import OHLCV

from .helpers import (
    BAR_MS,
    TS0,
    BoomFamily,
    BoomReader,
    FakeSnapshot,
    SilentFamily,
    StaticFamily,
    bars,
    ledger_payload,
    make_admitted_ledger,
    make_ledger,
    make_runtime,
)


def _run(runtime: Any, **kwargs: Any) -> Any:
    return asyncio.run(runtime.run(**kwargs))


def test_shadow_decision_is_persisted_and_touches_nothing(tmp_path: Path) -> None:
    runtime, _scanner, broker = make_runtime(run_dir=tmp_path, ledger=make_ledger(gross_bps=4.0))
    summary = _run(runtime, cycles=1)
    totals = summary.totals()
    assert totals["asset_cycle_evaluations"] == 1
    assert totals["shadow_trades"] == 1
    assert totals["orders_created"] == 0
    assert totals["traces_persisted"] == 1
    assert broker.positions == {}  # SHADOW never touches the portfolio
    row = summary.cycle_reports[0].assets[0]
    assert row.mode is DecisionMode.SHADOW_TRADE
    assert row.classification == "COST_KILLED"
    assert row.expected_gross_edge_bps == 4.0
    assert row.expected_net_edge_bps < 0
    assert row.verifier_verdict == VerifierVerdict.PASS.value
    assert runtime.trace_store.verify_chain().ok


def test_cost_model_is_applied_with_observed_spread(tmp_path: Path) -> None:
    runtime, _scanner, _broker = make_runtime(run_dir=tmp_path, ledger=make_ledger(gross_bps=4.0))
    _run(runtime, cycles=1)
    trace = runtime.trace_store.read()[0]
    assert trace.cost_model_version == COST_MODEL_VERSION
    proposal = trace.proposal
    assert proposal is not None
    cost = proposal["cost"]
    assert cost["spread_knowledge"] == "OBSERVED"
    assert cost["spread_bps"] == pytest.approx(1.0)
    assert cost["fee_bps"] == pytest.approx(20.0)  # 10 bps x 2 legs
    assert cost["round_trip_bps"] > cost["fee_bps"]  # spread + slippage + impact
    assert any(c["knowledge"] == "ASSUMED" for c in cost["components"]) is False
    assert {c["knowledge"] for c in cost["components"]} <= {"KNOWN", "OBSERVED", "ESTIMATED"}


def test_unadmitted_but_profitable_strategy_never_trades_paper(tmp_path: Path) -> None:
    class SpyBroker:
        def __init__(self) -> None:
            self.calls = 0
            self.positions: dict[str, Any] = {}
            self.equity = 10_000.0

        def execute_signal(self, signal: Any) -> Any:
            self.calls += 1
            return object()

        def reconcile_session(self, session_id: str, snapshots: Any, risk: Any) -> Any:
            class _Summary:
                def __init__(self) -> None:
                    self.new_closed_trades: list[Any] = []
                    self.fills_opened = 0
                    self.fills_closed = 0

            return _Summary()

    broker = SpyBroker()
    runtime, _scanner, _ = make_runtime(
        run_dir=tmp_path,
        ledger=make_ledger(gross_bps=50.0),  # net edge strongly positive
        broker=broker,
    )
    summary = _run(runtime, cycles=1)
    row = summary.cycle_reports[0].assets[0]
    assert row.mode is DecisionMode.SHADOW_TRADE
    assert row.classification == "NOT_ADMITTED"
    assert broker.calls == 0
    assert summary.totals()["orders_created"] == 0


def test_admitted_candidate_places_exactly_one_paper_order(tmp_path: Path) -> None:
    runtime, _scanner, broker = make_runtime(
        run_dir=tmp_path, ledger=make_admitted_ledger(gross_bps=50.0)
    )
    summary = _run(runtime, cycles=1)
    row = summary.cycle_reports[0].assets[0]
    assert row.mode is DecisionMode.TRADE_PAPER
    assert row.order_created is True
    assert row.risk_verdict == "PASS"
    assert summary.totals()["paper_trades"] == 1
    assert summary.executions[0]["mode"] == "TRADE_PAPER"
    # Reconciliation may already have closed the position in the same cycle
    # (stop-loss), so the evidence of execution is the broker's own ledger.
    broker_state = broker.extract_state()
    assert broker_state["fills_opened"] >= 1
    assert broker_state["equity"] != broker_state["initial_equity"]


def test_report_rejects_true_without_a_real_paper_trade(tmp_path: Path) -> None:
    """FALSE_SUCCESS: a no-trade run must never look like an execution."""
    runtime, _scanner, broker = make_runtime(
        run_dir=tmp_path,
        ledger=make_ledger(gross_bps=-4.56),
        families={"ema_crossover": StaticFamily()},
    )
    summary = _run(runtime, cycles=1)
    assert summary.totals()["paper_trades"] == 0
    assert summary.totals()["orders_created"] == 0
    assert summary.executions == []
    assert broker.positions == {}


def test_negative_gross_edge_is_no_trade_with_full_trace(tmp_path: Path) -> None:
    runtime, _scanner, _broker = make_runtime(
        run_dir=tmp_path, ledger=make_ledger(gross_bps=-4.56)
    )
    summary = _run(runtime, cycles=1)
    row = summary.cycle_reports[0].assets[0]
    assert row.mode is DecisionMode.NO_TRADE
    assert row.classification == "NO_GROSS_EDGE"
    trace = runtime.trace_store.read()[0]
    assert trace.proposal is not None
    assert trace.evidence  # economics are recorded even when rejected


def test_silent_family_yields_no_alpha_and_a_persisted_trace(tmp_path: Path) -> None:
    runtime, _scanner, _broker = make_runtime(
        run_dir=tmp_path,
        ledger=make_ledger(gross_bps=4.0),
        families={"ema_crossover": SilentFamily("ema_crossover")},
    )
    summary = _run(runtime, cycles=1)
    row = summary.cycle_reports[0].assets[0]
    assert row.classification == "NO_ALPHA"
    assert row.trace_persisted is True
    trace = runtime.trace_store.read()[0]
    assert trace.strategies_considered[0]["emitted_alpha"] is False


def test_strategy_exception_fails_closed(tmp_path: Path) -> None:
    runtime, _scanner, broker = make_runtime(
        run_dir=tmp_path, ledger=make_ledger(gross_bps=4.0), families={"ema_crossover": BoomFamily()}
    )
    summary = _run(runtime, cycles=1)
    row = summary.cycle_reports[0].assets[0]
    assert row.mode is DecisionMode.NO_TRADE
    assert row.classification == "NO_ALPHA"
    assert any("strategy_error" in e for e in summary.errors)
    assert broker.positions == {}


def test_provider_outage_is_visible_and_creates_no_order(tmp_path: Path) -> None:
    runtime, _scanner, broker = make_runtime(
        run_dir=tmp_path, ledger=make_ledger(gross_bps=4.0), reader=BoomReader()
    )
    summary = _run(runtime, cycles=1)
    assert any("history_error" in e for e in summary.errors)
    assert summary.totals()["orders_created"] == 0
    row = summary.cycle_reports[0].assets[0]
    assert row.mode is DecisionMode.NO_TRADE
    assert row.classification == "CONTEXT_ERROR"
    assert broker.positions == {}


def test_missing_snapshot_is_no_market_data(tmp_path: Path) -> None:
    runtime, _scanner, _broker = make_runtime(
        run_dir=tmp_path,
        ledger=make_ledger(gross_bps=4.0),
        assets=("BTC", "ETH"),
        snapshots=[FakeSnapshot(symbol="BTC/USDT", timestamp=TS0)],
    )
    summary = _run(runtime, cycles=1)
    rows = {r.asset: r for r in summary.cycle_reports[0].assets}
    assert rows["ETH"].classification == "NO_MARKET_DATA"
    assert rows["ETH"].mode is DecisionMode.NO_TRADE


def test_verifier_failure_blocks_an_admitted_candidate(tmp_path: Path) -> None:
    from trading_bot.autonomous.contracts import VerificationResult

    class FailingVerifier:
        version = "failing-verifier"

        def verify(self, request: Any) -> VerificationResult:
            return VerificationResult(
                decision_id=request.decision_id,
                verdict=VerifierVerdict.FAIL,
                failures=("injected_failure",),
                verifier_version=self.version,
            )

    runtime, _scanner, broker = make_runtime(
        run_dir=tmp_path, ledger=make_admitted_ledger(gross_bps=50.0)
    )
    runtime._verifier = FailingVerifier()  # type: ignore[assignment]
    summary = _run(runtime, cycles=1)
    row = summary.cycle_reports[0].assets[0]
    assert row.mode is DecisionMode.NO_TRADE
    assert row.classification == "VERIFIER_FAIL"
    assert broker.positions == {}
    assert summary.totals()["orders_created"] == 0


def test_risk_veto_blocks_an_admitted_candidate(tmp_path: Path) -> None:
    runtime, _scanner, broker = make_runtime(
        run_dir=tmp_path, ledger=make_admitted_ledger(gross_bps=50.0)
    )
    runtime._risk.activate_kill_switch("test")
    summary = _run(runtime, cycles=1)
    row = summary.cycle_reports[0].assets[0]
    assert row.mode is DecisionMode.NO_TRADE
    assert row.classification == "RISK_VETO"
    assert row.risk_verdict == "VETO"
    assert broker.positions == {}


def test_cost_model_absence_is_detectable_in_the_trace(tmp_path: Path) -> None:
    """A trace must always name the cost model version actually applied."""
    runtime, _scanner, _broker = make_runtime(run_dir=tmp_path, ledger=make_ledger(gross_bps=4.0))
    _run(runtime, cycles=1)
    for trace in runtime.trace_store.read():
        assert trace.cost_model_version == COST_MODEL_VERSION
        assert trace.verification["verdict"] in {"PASS", "FAIL", "NOT_RUN"}


def test_every_decision_carries_verification_and_risk(tmp_path: Path) -> None:
    runtime, _scanner, _broker = make_runtime(run_dir=tmp_path, ledger=make_ledger(gross_bps=4.0))
    _run(runtime, cycles=1)
    trace = runtime.trace_store.read()[0]
    assert trace.verification["verifier_version"]
    assert trace.risk["source"]
    assert trace.agent_messages  # reviews recorded, not summarised away


def test_timeframe_without_research_evidence_produces_no_candidates(tmp_path: Path) -> None:
    runtime, _scanner, _broker = make_runtime(
        run_dir=tmp_path,
        ledger=make_ledger(gross_bps=4.0, timeframe="30m"),
        timeframe="5m",
    )
    summary = _run(runtime, cycles=1)
    row = summary.cycle_reports[0].assets[0]
    assert row.mode is DecisionMode.NO_TRADE
    assert row.classification == "NO_ALPHA"
    assert row.strategies_considered == ()


def test_decision_time_is_safe_but_outcome_is_pending_for_a_fresh_bar(tmp_path: Path) -> None:
    runtime, _scanner, _broker = make_runtime(run_dir=tmp_path, ledger=make_ledger(gross_bps=4.0))
    summary = _run(runtime, cycles=1)
    trace = runtime.trace_store.read()[0]
    assert trace.decision_time_ms >= trace.market_time_ms
    assert summary.totals()["outcomes_pending"] == 1
    assert runtime.trace_store.read_outcomes() == []


# -- multi-cycle: DECISION → OUTCOME → PERFORMANCE ---------------------------


class _EvolvingState:
    """Shared state: each cycle appends one more closed bar."""

    def __init__(self, n: int = 130) -> None:
        self.history: dict[str, list[OHLCV]] = {"BTC/USDT": bars("BTC/USDT", n)}

    def advance(self) -> None:
        series = self.history["BTC/USDT"]
        last = series[-1]
        price = last.close + 1.0
        series.append(
            OHLCV(
                symbol=last.symbol,
                timestamp=last.timestamp + BAR_MS,
                open=price,
                high=price + 1.0,
                low=price - 1.0,
                close=price + 0.5,
                volume=1_000.0,
            )
        )

    def last_ts(self) -> int:
        return self.history["BTC/USDT"][-1].timestamp


class _EvolvingScanner:
    def __init__(self, state: _EvolvingState) -> None:
        self._state = state
        self.counters: Any = None

    async def run(self) -> list[FakeSnapshot]:
        return [
            FakeSnapshot(symbol="BTC/USDT", timestamp=self._state.last_ts()),
        ]


class _EvolvingReader:
    def __init__(self, state: _EvolvingState) -> None:
        self._state = state

    async def get_ohlcv(
        self, symbol: str, *, as_of_timestamp_ms: int, lookback_bars: int
    ) -> list[OHLCV]:
        window = [b for b in self._state.history.get(symbol, []) if b.timestamp <= as_of_timestamp_ms]
        return window[-lookback_bars:]


def test_multi_cycle_resolves_outcome_and_updates_performance(tmp_path: Path) -> None:
    from trading_bot.autonomous.runtime import AutonomousPaperRuntime
    from trading_bot.config.runtime import TradingMode
    from trading_bot.paper.broker import PaperBroker

    state = _EvolvingState(n=130)
    ledger = make_ledger(gross_bps=4.0)

    class _Settings:
        class runtime:
            mode = TradingMode.PAPER
            exchange_id = "fake"

        class risk:
            kill_switch_enabled = True

    runtime = AutonomousPaperRuntime(
        settings=_Settings(),
        scanner_factory=lambda: _EvolvingScanner(state),
        history_reader=_EvolvingReader(state),
        broker=PaperBroker(equity=10_000.0),
        risk_manager=__import__(
            "tests.unit.autonomous.helpers", fromlist=["risk_manager"]
        ).risk_manager(),
        families={"ema_crossover": StaticFamily()},
        strategy_map={
            "ema_crossover@5m": {
                "family": "ema_crossover",
                "regimes": [],
                "direction": "BOTH",
                "enabled": True,
                "status": "RESEARCH_ONLY",
                "priority": 0.0,
            }
        },
        ledger=ledger,
        run_dir=tmp_path,
        assets=("BTC",),
        timeframe="5m",
        horizon_minutes=5.0,
    )

    def _two_cycles() -> Any:
        async def _go() -> Any:
            first = await runtime.run_cycle(cycle=1)
            state.advance()
            second = await runtime.run_cycle(cycle=2)
            return first, second

        return asyncio.run(_go())

    first, second = _two_cycles()
    assert first.assets[0].mode is DecisionMode.SHADOW_TRADE
    assert first.outcomes_resolved == 0
    assert first.outcomes_pending == 1
    assert second.assets[0].mode is DecisionMode.SHADOW_TRADE
    assert second.outcomes_resolved == 1
    assert second.performance_updates == 1

    outcomes = runtime.trace_store.read_outcomes()
    assert len(outcomes) == 1
    assert outcomes[0].outcome_time_ms > outcomes[0].decision_time_ms
    assert outcomes[0].mode is DecisionMode.SHADOW_TRADE

    cells = runtime.performance_store.all_cells()
    assert len(cells) == 1
    assert cells[0].sample_size == 1
    assert cells[0].shadow_sample_size == 1
    assert cells[0].paper_sample_size == 0

    replay = runtime.trace_store.replay(outcomes[0].decision_id)
    assert replay.ok
    assert replay.outcome is not None


def test_ledger_payload_defaults_are_fail_closed() -> None:
    payload = ledger_payload(gross_bps=4.0)
    assert payload["strategies"]["ema_crossover@5m"]["admitted_for_paper"] is False
