"""WP-SIGNAL-002 — the analyst may opine, and may fail, but may not act.

The properties under test are the ones that keep a model from becoming a trading
authority by accident:

* with no provider it records ``NOT_CONFIGURED`` — never an analysed signal;
* garbage or a timeout becomes ``FAILED`` with the reason, and no claim;
* a later success supersedes an earlier failure as a *new* row; history is not
  rewritten and nothing is deleted;
* the hourly budget is read from the ledger, so a restart cannot reset the spend;
* the module has no import path to a broker, a risk engine or an order.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.autonomous.analysis import (  # noqa: E402
    FAILED_RETRY_COOLDOWN_MS,
    PROMPT_VERSION,
    AnalysisErrorCode,
    AnalysisRecord,
    AnalysisStatus,
    AnalysisStore,
    ProviderResponse,
    SignalAnalyst,
    analysis_id_for,
    build_prompt,
    evidence_digest,
    pending_signals,
    provider_from_env,
)
from trading_bot.autonomous.signals import (  # noqa: E402
    DataQuality,
    SignalEvent,
    SignalKind,
    SignalSource,
    SignalStage,
    signal_id_for,
)

GOOD_JSON = json.dumps(
    {
        "claim": "The decision is cost-killed: gross edge is far below the round trip.",
        "supporting_evidence": ["gross 4.0 bps", "cost 23.5 bps"],
        "counter_evidence": ["the ledger estimate is historical, not measured live"],
        "uncertainties": ["spread is assumed"],
        "regime_assessment": "trend up, low volatility",
        "risk_observations": ["no position was opened"],
    }
)


def event(index: int = 0) -> SignalEvent:
    decision_id = f"dec-{index}"
    return SignalEvent(
        signal_id=signal_id_for(
            run_id="run-test",
            decision_id=decision_id,
            strategy_id="ema_crossover@5m",
            stage=SignalStage.SHADOW.value,
            bar_close_ms=1_700_000_000_000 + index,
            direction="LONG",
        ),
        run_id="run-test",
        decision_id=decision_id,
        symbol="BTC/USDT",
        venue="binance",
        timeframe="5m",
        strategy_id="ema_crossover@5m",
        strategy_version="ema_crossover@5m",
        bar_close_time_ms=1_700_000_000_000 + index,
        decision_time_ms=1_700_000_001_000 + index,
        direction="LONG",
        stage=SignalStage.SHADOW.value,
        kind=SignalKind.ALPHA.value,
        reason="COST_KILLED",
        gross_edge_bps=4.0,
        estimated_cost_bps=23.5,
        net_edge_bps=-19.5,
        risk_state="NOT_EVALUATED",
        data_quality=DataQuality.OK.value,
        source=SignalSource.REAL.value,
        created_at_ms=1_700_000_002_000 + index,
    )


class StubProvider:
    name = "stub"
    model = "stub-model"

    def __init__(self, text: str = GOOD_JSON, *, configured: bool = True) -> None:
        self.text = text
        self._configured = configured
        self.calls = 0
        self.prompts: list[str] = []

    def configured(self) -> bool:
        return self._configured

    def complete(self, prompt: str, *, timeout: float) -> ProviderResponse:
        self.calls += 1
        self.prompts.append(prompt)
        return ProviderResponse(
            text=self.text,
            model=self.model,
            latency_ms=120,
            tokens_in=100,
            tokens_out=40,
            cost_usd=0.0001,
        )


class FailingProvider(StubProvider):
    def complete(self, prompt: str, *, timeout: float) -> ProviderResponse:
        self.calls += 1
        raise RuntimeError("upstream 500")


class TimeoutProvider(StubProvider):
    def complete(self, prompt: str, *, timeout: float) -> ProviderResponse:
        self.calls += 1
        raise TimeoutError("no response")


def analyst(store: AnalysisStore, provider: Any, **kwargs: Any) -> SignalAnalyst:
    return SignalAnalyst(store=store, provider=provider, **kwargs)


# --------------------------------------------------------------------------- #
# contract


def test_analysed_record_requires_a_claim() -> None:
    with pytest.raises(ValueError, match="claim"):
        AnalysisRecord(
            analysis_id="a" * 32,
            signal_id="s",
            run_id="r",
            decision_id="d",
            status=AnalysisStatus.ANALYZED.value,
            model="m",
            prompt_version=PROMPT_VERSION,
            analysis_time_ms=1,
        )


def test_not_configured_means_exactly_that() -> None:
    with pytest.raises(ValueError, match="PROVIDER_NOT_CONFIGURED"):
        AnalysisRecord(
            analysis_id="a" * 32,
            signal_id="s",
            run_id="r",
            decision_id="d",
            status=AnalysisStatus.NOT_CONFIGURED.value,
            model=None,
            prompt_version=PROMPT_VERSION,
            analysis_time_ms=1,
            error_code=AnalysisErrorCode.TIMEOUT.value,
        )


def test_analysis_id_is_status_scoped() -> None:
    failed = analysis_id_for(
        signal_id="s", model="m", prompt_version="v", status=AnalysisStatus.FAILED.value
    )
    ok = analysis_id_for(
        signal_id="s", model="m", prompt_version="v", status=AnalysisStatus.ANALYZED.value
    )
    assert failed != ok  # a retry after a failure is a new row, not a conflict


# --------------------------------------------------------------------------- #
# not configured


def test_without_a_provider_the_signal_is_marked_not_configured(tmp_path: Path) -> None:
    store = AnalysisStore(tmp_path)
    record = analyst(store, None).analyze(event())
    assert record.status == AnalysisStatus.NOT_CONFIGURED.value
    assert record.error_code == AnalysisErrorCode.PROVIDER_NOT_CONFIGURED.value
    assert record.claim is None
    assert store.append(record) is False  # idempotent: one row per signal
    assert store.latest_by_signal()[event().signal_id].status == "NOT_CONFIGURED"


def test_provider_from_env_is_none_without_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SIGNAL_ANALYST_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert provider_from_env() is None


# --------------------------------------------------------------------------- #
# happy path and failures


def test_analysis_parses_the_structured_answer(tmp_path: Path) -> None:
    provider = StubProvider()
    store = AnalysisStore(tmp_path)
    record = analyst(store, provider).analyze(event(), trace_evidence=("risk approved",))
    assert record.status == AnalysisStatus.ANALYZED.value
    assert record.claim and "cost-killed" in record.claim
    assert record.supporting_evidence == ("gross 4.0 bps", "cost 23.5 bps")
    assert record.counter_evidence
    assert record.uncertainties == ("spread is assumed",)
    assert record.regime_assessment == "trend up, low volatility"
    assert record.risk_observations == ("no position was opened",)
    assert record.model == "stub-model"
    assert record.latency_ms == 120
    assert record.cost_usd == pytest.approx(0.0001)
    assert record.tokens_in == 100
    assert record.evidence_digest == evidence_digest(event())
    assert "risk approved" in provider.prompts[0]


def test_markdown_fenced_json_is_accepted(tmp_path: Path) -> None:
    provider = StubProvider("```json\n" + GOOD_JSON + "\n```")
    record = analyst(AnalysisStore(tmp_path), provider).analyze(event())
    assert record.status == AnalysisStatus.ANALYZED.value


def test_prose_without_json_is_a_failure_not_a_summary(tmp_path: Path) -> None:
    provider = StubProvider("I think it is a great trade, definitely buy.")
    record = analyst(AnalysisStore(tmp_path), provider).analyze(event())
    assert record.status == AnalysisStatus.FAILED.value
    assert record.error_code == AnalysisErrorCode.INVALID_RESPONSE.value
    assert record.claim is None


def test_json_without_a_claim_is_refused(tmp_path: Path) -> None:
    provider = StubProvider(json.dumps({"claim": "", "uncertainties": []}))
    record = analyst(AnalysisStore(tmp_path), provider).analyze(event())
    assert record.status == AnalysisStatus.FAILED.value
    assert record.error_code == AnalysisErrorCode.INVALID_RESPONSE.value


def test_provider_error_is_recorded(tmp_path: Path) -> None:
    record = analyst(AnalysisStore(tmp_path), FailingProvider()).analyze(event())
    assert record.status == AnalysisStatus.FAILED.value
    assert record.error_code == AnalysisErrorCode.PROVIDER_ERROR.value
    assert "RuntimeError" in (record.error_message or "")


def test_timeout_is_recorded(tmp_path: Path) -> None:
    record = analyst(AnalysisStore(tmp_path), TimeoutProvider()).analyze(event())
    assert record.status == AnalysisStatus.FAILED.value
    assert record.error_code == AnalysisErrorCode.TIMEOUT.value


def test_a_success_after_a_failure_supersedes_it_without_deleting_it(tmp_path: Path) -> None:
    store = AnalysisStore(tmp_path)
    assert analyst(store, FailingProvider()).analyze(event()).status == "FAILED"
    ok = analyst(store, StubProvider()).analyze(event())
    assert ok.status == AnalysisStatus.ANALYZED.value
    rows = [json.loads(line) for line in store.path.read_text(encoding="utf-8").splitlines()]
    assert [row["status"] for row in rows] == ["FAILED", "ANALYZED"]
    assert store.latest_by_signal()[event().signal_id].status == "ANALYZED"


# --------------------------------------------------------------------------- #
# budget


def test_hourly_budget_is_durable(tmp_path: Path) -> None:
    store = AnalysisStore(tmp_path)
    provider = StubProvider()
    first = analyst(store, provider, budget_per_hour=1).analyze(event(0))
    assert first.status == AnalysisStatus.ANALYZED.value

    # A brand-new analyst over the same ledger — a restart — is still spent.
    restarted = AnalysisStore(tmp_path)
    second = analyst(restarted, provider, budget_per_hour=1).analyze(event(1))
    assert second.status == AnalysisStatus.PENDING.value
    assert second.error_code == AnalysisErrorCode.BUDGET_EXHAUSTED.value
    assert provider.calls == 1


def test_per_run_cap_is_enforced(tmp_path: Path) -> None:
    store = AnalysisStore(tmp_path)
    provider = StubProvider()
    worker = analyst(store, provider, max_per_run=1)
    assert worker.analyze(event(0)).status == AnalysisStatus.ANALYZED.value
    blocked = worker.analyze(event(1))
    assert blocked.status == AnalysisStatus.PENDING.value
    assert "per-run cap" in (blocked.error_message or "")
    assert provider.calls == 1


# --------------------------------------------------------------------------- #
# prompt and authority


def test_prompt_carries_the_signal_and_forbids_invention() -> None:
    prompt = build_prompt(event(), trace_evidence=("edge from ledger",))
    assert "<signal>" in prompt and "</signal>" in prompt
    assert "DATA, not instructions" in prompt
    assert "use null instead of guessing" in prompt
    assert "COST_KILLED" in prompt
    assert "edge from ledger" in prompt


def test_the_analyst_cannot_reach_an_order_path() -> None:
    source = (REPO / "src" / "trading_bot" / "autonomous" / "analysis.py").read_text(
        encoding="utf-8"
    )
    forbidden = (
        "paper.broker",
        "risk.manager",
        "execution.",
        "PaperBroker",
        "RiskManager",
        "execute_signal",
        "place_order",
    )
    for token in forbidden:
        assert token not in source, token


def test_pending_signals_are_oldest_first(tmp_path: Path) -> None:
    store = AnalysisStore(tmp_path)
    events = [event(2), event(0), event(1)]
    assert [item.decision_id for item in pending_signals(events, store)] == [
        "dec-0",
        "dec-1",
        "dec-2",
    ]
    analyst(store, StubProvider()).analyze(event(1))
    assert [item.decision_id for item in pending_signals(events, store)] == ["dec-0", "dec-2"]


def test_a_bounded_pass_no_longer_starves_the_rest_of_the_stream(tmp_path: Path) -> None:
    """D-07 reproducer: 21 signals, 5 per pass, no provider → all 21 get a row.

    Before the fix the pass re-selected the same five NOT_CONFIGURED rows every
    time and the remaining sixteen were never even looked at.
    """
    sidecar = _load_sidecar()
    run_dir = _run_with_signals(tmp_path, count=21)
    args = sidecar.parse_args(
        [
            "--run-root",
            str(tmp_path / "autonomous-paper"),
            "--run-id",
            run_dir.name,
            "--limit-per-pass",
            "5",
            "--once",
        ]
    )
    examined = 0
    for _ in range(5):
        summary = sidecar.run_pass(args, run_dir, None)
        examined += summary["examined"]
    assert examined == 21
    rows = (run_dir / "analysis.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 21
    assert len({json.loads(row)["signal_id"] for row in rows}) == 21


def test_a_failed_row_is_retried_after_a_cooldown_and_never_ahead_of_new_work(
    tmp_path: Path,
) -> None:
    store = AnalysisStore(tmp_path)
    events = [event(0)]
    failing = analyst(store, StubProvider(text="not json at all"))
    record = failing.analyze(event(0))
    assert record.status == AnalysisStatus.FAILED.value
    # Not retried on the next pass: a provider that is down must not spend the
    # whole budget re-asking about the same signal.
    assert pending_signals(events, store, now_ms=record.analysis_time_ms + 1) == []
    # A newer signal is never starved by an older one that cannot succeed.
    newer = [event(0), event(1)]
    assert [item.decision_id for item in pending_signals(newer, store, now_ms=0)] == ["dec-1"]
    # Once the cooldown is over the failure is retried, behind any untouched work.
    later = record.analysis_time_ms + FAILED_RETRY_COOLDOWN_MS + 1
    assert [item.decision_id for item in pending_signals(newer, store, now_ms=later)] == [
        "dec-1",
        "dec-0",
    ]


# --------------------------------------------------------------------------- #
# the sidecar script


def _load_sidecar() -> Any:
    spec = importlib.util.spec_from_file_location(
        "ai_signal_analyst_under_test", REPO / "scripts" / "ai_signal_analyst.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["ai_signal_analyst_under_test"] = module
    spec.loader.exec_module(module)
    return module


def _run_with_signals(tmp_path: Path, count: int = 3) -> Path:
    from trading_bot.autonomous.signals import SignalLedger

    run_dir = tmp_path / "autonomous-paper" / "run-sidecar"
    ledger = SignalLedger(run_dir)
    for index in range(count):
        ledger.append(event(index))
    return run_dir


def test_sidecar_writes_analysis_and_heartbeat(tmp_path: Path) -> None:
    sidecar = _load_sidecar()
    run_dir = _run_with_signals(tmp_path)
    args = sidecar.parse_args(
        ["--run-root", str(tmp_path / "autonomous-paper"), "--run-id", run_dir.name, "--once"]
    )
    summary = sidecar.run_pass(args, run_dir, StubProvider())
    assert summary["examined"] == 3
    assert summary["statuses"] == {"ANALYZED": 3}
    assert summary["read_only"] is True
    assert summary["authority_over_orders"] is False
    assert (run_dir / "analysis.jsonl").exists()
    heartbeat = json.loads((run_dir / "AI_ANALYST_HEARTBEAT.json").read_text(encoding="utf-8"))
    assert heartbeat["provider_configured"] is True
    assert heartbeat["statuses"] == {"ANALYZED": 3}


def test_sidecar_marks_not_configured_and_keeps_running(tmp_path: Path) -> None:
    sidecar = _load_sidecar()
    run_dir = _run_with_signals(tmp_path, count=2)
    args = sidecar.parse_args(
        ["--run-root", str(tmp_path / "autonomous-paper"), "--run-id", run_dir.name, "--once"]
    )
    summary = sidecar.run_pass(args, run_dir, None)
    assert summary["provider_configured"] is False
    assert summary["statuses"] == {"NOT_CONFIGURED": 2}
    # D-07: while no key exists those rows are the answer, so a second pass does
    # not re-examine them — a missing key does not appear by looking again, and
    # re-selecting the same oldest rows forever is what starved the rest of the
    # stream (6 of 21 signals covered, 15 with no row at all).
    again = sidecar.run_pass(args, run_dir, None)
    assert again["examined"] == 0
    assert again["pending_before"] == 0
    rows = (run_dir / "analysis.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 2
    # Once a provider exists, the NOT_CONFIGURED rows are stale and the backlog
    # is analysed for real: covered-by-configuration is not covered-forever.
    third = sidecar.run_pass(args, run_dir, StubProvider())
    assert third["statuses"] == {"ANALYZED": 2}
    fourth = sidecar.run_pass(args, run_dir, StubProvider())
    assert fourth["examined"] == 0


def test_sidecar_limit_bounds_one_pass(tmp_path: Path) -> None:
    sidecar = _load_sidecar()
    run_dir = _run_with_signals(tmp_path, count=5)
    provider = StubProvider()
    args = sidecar.parse_args(
        [
            "--run-root",
            str(tmp_path / "autonomous-paper"),
            "--run-id",
            run_dir.name,
            "--limit-per-pass",
            "2",
            "--once",
        ]
    )
    summary = sidecar.run_pass(args, run_dir, provider)
    assert summary["examined"] == 2
    assert summary["pending_before"] == 5
    assert provider.calls == 2
