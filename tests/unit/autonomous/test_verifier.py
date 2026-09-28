"""IndependentVerifier — each check must be able to FAIL (no rubber stamp)."""

from __future__ import annotations

from typing import Any

from trading_bot.autonomous.contracts import AdmissionStatus, DecisionMode, TradeProposal
from trading_bot.autonomous.costs import CostEngine
from trading_bot.autonomous.verifier import IndependentVerifier, VerificationRequest

from .helpers import make_admitted_ledger, make_ledger
from .test_contracts import _cost, _proposal

BAR_MS = 5 * 60 * 1000
TS0 = 1_700_000_000_000


def _bars(n: int = 10) -> tuple[Any, ...]:
    from trading_bot.market_data.types import OHLCV

    return tuple(
        OHLCV(
            symbol="BTC/USDT",
            timestamp=TS0 + i * BAR_MS,
            open=100.0 + i,
            high=101.0 + i,
            low=99.0 + i,
            close=100.5 + i,
            volume=10.0,
        )
        for i in range(n)
    )


def _cost_inputs(**overrides: Any) -> dict[str, Any]:
    base = {
        "size_usd": 1_000.0,
        "horizon_minutes": 5.0,
        "spread_bps": 1.0,
        "liquidity_regime": "normal",
        "volatility_bps": 0.0,
        "entry_order_type": "market",
        "exit_order_type": "market",
    }
    base.update(overrides)
    return base


def _expected_cost(**overrides: Any) -> float:
    return CostEngine().evaluate(**_cost_inputs(**overrides)).round_trip_bps


def _request(**overrides: Any) -> VerificationRequest:
    ledger = overrides.pop("ledger", None) or make_ledger()
    decision_time = TS0 + 9 * BAR_MS
    cost_inputs = overrides.pop("cost_inputs", _cost_inputs())
    cost_bps = overrides.pop("cost_bps", _expected_cost())
    gross = overrides.pop("gross", 4.0)
    proposal = overrides.pop(
        "proposal",
        _proposal(
            market_time_ms=TS0 + 5 * BAR_MS,
            decision_time_ms=decision_time,
            entry_reference=100.5,
            expected_gross_edge_bps=gross,
            expected_cost_bps=cost_bps,
            expected_net_edge_bps=gross - cost_bps,
            cost=_cost_model(cost_bps),
            context_fingerprint="sha256:ctx",
        ),
    )
    base: dict[str, Any] = {
        "run_id": "run-1",
        "decision_id": "d-1",
        "asset": "BTC",
        "decision_time_ms": decision_time,
        "declared_mode": DecisionMode.SHADOW_TRADE,
        "raw_history": _bars(10),
        "used_bars": _bars(10),
        "window_end_ts": decision_time,
        "context_fingerprint": "sha256:ctx",
        "proposal": proposal,
        "cost_inputs": cost_inputs,
        "risk_reviewed": False,
        "orders_created": 0,
        "shadow_marked": True,
        "ledger": ledger,
    }
    base.update(overrides)
    return VerificationRequest(**{k: v for k, v in base.items() if k != "ledger"})


def _cost_model(cost_bps: float) -> Any:
    from dataclasses import replace

    return replace(
        _cost(),
        round_trip_bps=cost_bps,
        components=(
            {
                "name": "exchange_fee_entry",
                "value_bps": cost_bps / 2,
                "knowledge": "KNOWN",
                "source_id": "SRC-01",
                "note": "test",
            },
        ),
    )


def test_shadow_packet_passes_all_checks() -> None:
    verifier = IndependentVerifier(ledger=make_ledger())
    result = verifier.verify(_request())
    assert result.verdict.value == "PASS", result.failures
    assert result.passed


def test_future_bar_in_the_used_slice_fails() -> None:
    verifier = IndependentVerifier(ledger=make_ledger())
    bars = _bars(10)
    result = verifier.verify(_request(used_bars=(*bars, _extra_future_bar())))
    assert not result.passed
    assert "pit_slice_exact" in result.failures


def test_silently_dropped_bar_fails() -> None:
    verifier = IndependentVerifier(ledger=make_ledger())
    result = verifier.verify(_request(used_bars=_bars(9)))
    assert not result.passed
    assert "pit_slice_exact" in result.failures


def test_understated_cost_fails_recomputation() -> None:
    verifier = IndependentVerifier(ledger=make_ledger())
    cheap = _expected_cost() - 5.0
    proposal = _proposal(
        market_time_ms=TS0 + 5 * BAR_MS,
        decision_time_ms=TS0 + 9 * BAR_MS,
        entry_reference=100.5,
        expected_gross_edge_bps=4.0,
        expected_cost_bps=cheap,
        expected_net_edge_bps=4.0 - cheap,
        cost=_cost_model(cheap),
        context_fingerprint="sha256:ctx",
    )
    result = verifier.verify(_request(proposal=proposal, cost_bps=cheap))
    assert not result.passed
    assert "cost_model_applied" in result.failures


def test_admission_mismatch_fails() -> None:
    verifier = IndependentVerifier(ledger=make_admitted_ledger())
    # Proposal claims a status the ledger does not back.
    proposal = _proposal(
        market_time_ms=TS0 + 5 * BAR_MS,
        decision_time_ms=TS0 + 9 * BAR_MS,
        entry_reference=100.5,
        expected_gross_edge_bps=4.0,
        expected_cost_bps=_expected_cost(),
        expected_net_edge_bps=4.0 - _expected_cost(),
        cost=_cost_model(_expected_cost()),
        context_fingerprint="sha256:ctx",
        admission_status=AdmissionStatus.COST_KILLED,
    )
    result = verifier.verify(_request(ledger=make_admitted_ledger(), proposal=proposal))
    assert not result.passed
    assert "admission_recomputed" in result.failures


def test_paper_mode_without_admission_fails() -> None:
    verifier = IndependentVerifier(ledger=make_ledger())
    result = verifier.verify(
        _request(declared_mode=DecisionMode.TRADE_PAPER, risk_reviewed=True)
    )
    assert not result.passed
    assert "admission_recomputed" in result.failures


def test_paper_mode_without_risk_review_fails() -> None:
    verifier = IndependentVerifier(ledger=make_admitted_ledger())
    proposal = _proposal(
        market_time_ms=TS0 + 5 * BAR_MS,
        decision_time_ms=TS0 + 9 * BAR_MS,
        entry_reference=100.5,
        expected_gross_edge_bps=30.0,
        expected_cost_bps=_expected_cost(),
        expected_net_edge_bps=30.0 - _expected_cost(),
        cost=_cost_model(_expected_cost()),
        context_fingerprint="sha256:ctx",
        admission_status=AdmissionStatus.PAPER_CANDIDATE,
    )
    result = verifier.verify(
        _request(
            ledger=make_admitted_ledger(),
            proposal=proposal,
            declared_mode=DecisionMode.TRADE_PAPER,
            risk_reviewed=False,
        )
    )
    assert not result.passed
    assert "paper_requires_proposal" in result.failures


def test_shadow_with_an_order_fails() -> None:
    verifier = IndependentVerifier(ledger=make_ledger())
    result = verifier.verify(_request(orders_created=1))
    assert not result.passed
    assert "shadow_purity" in result.failures


def test_missing_cost_inputs_fails_closed() -> None:
    verifier = IndependentVerifier(ledger=make_ledger())
    result = verifier.verify(_request(cost_inputs={}))
    assert not result.passed
    assert "cost_model_applied" in result.failures


def test_missing_context_fingerprint_fails() -> None:
    verifier = IndependentVerifier(ledger=make_ledger())
    result = verifier.verify(_request(context_fingerprint=""))
    assert not result.passed
    assert "context_fingerprint" in result.failures


def _extra_future_bar() -> Any:
    from trading_bot.market_data.types import OHLCV

    return OHLCV(
        symbol="BTC/USDT",
        timestamp=TS0 + 20 * BAR_MS,
        open=1.0,
        high=1.0,
        low=1.0,
        close=1.0,
        volume=1.0,
    )


def test_proposal_round_trip_used_by_verifier_is_the_same_object() -> None:
    proposal = _proposal()
    assert isinstance(TradeProposal.from_dict(proposal.to_dict()), TradeProposal)
