"""CAP-002 real pilot — focused tests for real context, the gate and the analyst.

No network: the provider rows are synthesised in-memory, but the code path under
test is exactly the real one (completed-bar filtering, adapter mapping, gate and
sealing). Synthetic rows here are test fixtures, never pilot evidence.

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import dataclasses

import pytest

from trading_bot.market_data.types import OHLCV
from trading_bot.research import agentic_contracts as ac
from trading_bot.research import market_analyst_v1 as mav
from trading_bot.research import real_market_context as rmc

DECISION_MS = 1_791_288_000_000
DECISION_TIME = DECISION_MS // 1_000
ASSET = "BINANCE:BTCUSDT"


def _rows(interval_key: str, count: int, *, decision_ms: int = DECISION_MS) -> list[OHLCV]:
    bar_ms = rmc.BAR_SECONDS[interval_key] * 1_000
    out: list[OHLCV] = []
    for index in range(count):
        open_ms = decision_ms - bar_ms * (count - index)
        close = 100.0 + index * 0.5
        out.append(
            OHLCV(
                symbol=rmc.provider_symbol(ASSET),
                timestamp=open_ms,
                open=close - 0.2,
                high=close + 0.3,
                low=close - 0.4,
                close=close,
                volume=10.0 + index,
            )
        )
    return out


def _all_rows(*, decision_ms: int = DECISION_MS) -> dict[str, list[OHLCV]]:
    return {
        "1h": _rows("1h", 500, decision_ms=decision_ms),
        "4h": _rows("4h", 300, decision_ms=decision_ms),
        "1D": _rows("1D", 250, decision_ms=decision_ms),
    }


# --------------------------------------------------------------------------- #
# causality
# --------------------------------------------------------------------------- #


def test_completed_rows_drops_live_and_future_bars() -> None:
    bar_ms = rmc.BAR_SECONDS["4h"] * 1_000
    rows = _rows("4h", 10)
    live = OHLCV(symbol="BTC/USDT", timestamp=DECISION_MS, open=1, high=1, low=1, close=1, volume=1)
    future = OHLCV(
        symbol="BTC/USDT", timestamp=DECISION_MS + bar_ms, open=1, high=1, low=1, close=1, volume=1
    )
    kept = rmc.completed_rows([*rows, live, future], decision_ms=DECISION_MS, interval_key="4h")
    assert len(kept) == 10
    assert kept[-1].timestamp == DECISION_MS - bar_ms


def test_last_completed_close_is_the_decision_boundary() -> None:
    rows = rmc.completed_rows(_rows("4h", 5), decision_ms=DECISION_MS, interval_key="4h")
    assert rmc.last_completed_close(rows, interval_key="4h") == DECISION_TIME


def test_contract_bars_map_on_the_adapter_shape() -> None:
    rows = rmc.completed_rows(_rows("1h", 3), decision_ms=DECISION_MS, interval_key="1h")
    bars = rmc.to_contract_bars(rows)
    assert set(bars[0]) == {"t", "o", "h", "l", "c", "v"}
    assert bars[0]["t"] == int(rows[0].timestamp) // 1_000
    assert bars[-1]["c"] == rows[-1].close


def test_daily_bars_feed_the_sma200_baseline() -> None:
    rows = rmc.completed_rows(_rows("1D", 250), decision_ms=DECISION_MS, interval_key="1D")
    bars = rmc.daily_bars(rows)
    assert len(bars) == 250
    assert bars[0].open_time == int(rows[0].timestamp) // 1_000


# --------------------------------------------------------------------------- #
# deterministic features
# --------------------------------------------------------------------------- #


def test_technicals_omit_fields_without_enough_history() -> None:
    short = rmc.technicals_from_rows(_rows("4h", 10))
    assert "RSI" not in short and "MACD" not in short and "EMA200" not in short
    full = rmc.technicals_from_rows(_rows("4h", 250))
    assert {"RSI", "MACD", "Momentum", "SMA50", "EMA200"}.issubset(full)


def test_regime_is_deterministic_and_repeatable() -> None:
    rows = _rows("4h", 60)
    assert rmc.deterministic_regime(rows) == rmc.deterministic_regime(rows)
    assert rmc.deterministic_regime(rows).startswith("trend_")


# --------------------------------------------------------------------------- #
# snapshot + gate
# --------------------------------------------------------------------------- #


def test_build_real_snapshot_artifact_is_causal_and_valid() -> None:
    artifact = rmc.build_real_snapshot_artifact(
        asset=ASSET, decision_time=DECISION_TIME, rows_by_interval=_all_rows()
    )
    assert artifact["source_type"] == rmc.REAL_SOURCE_TYPE
    assert artifact["synthetic"] is False
    assert artifact["validation_problems"] == []
    assert artifact["usable"] is True
    assert len(artifact["snapshot_hash"]) == 64
    assert len(artifact["raw_evidence_hash"]) == 64
    assert not artifact["snapshot"]["news"]
    assert not artifact["snapshot"]["macro_events"]


def test_gate_passes_on_a_real_like_snapshot() -> None:
    artifact = rmc.build_real_snapshot_artifact(
        asset=ASSET, decision_time=DECISION_TIME, rows_by_interval=_all_rows()
    )
    gate = rmc.evaluate_g_real_market_context(artifact, snapshot_at=DECISION_TIME)
    assert gate["status"] == "PASS"
    assert gate["failed"] == []
    assert gate["g_tv_context"] == ac.G_TV_CONTEXT == "NOT_VERIFIED"


def test_gate_fails_when_marked_synthetic() -> None:
    artifact = rmc.build_real_snapshot_artifact(
        asset=ASSET, decision_time=DECISION_TIME, rows_by_interval=_all_rows()
    )
    tampered = {**artifact, "synthetic": True}
    gate = rmc.evaluate_g_real_market_context(tampered, snapshot_at=DECISION_TIME)
    assert gate["status"] == "FAIL"
    assert "SYNTHETIC_CERTIFICATION_FALSE" in gate["failed"]


def test_gate_fails_without_enough_daily_history() -> None:
    rows = _all_rows()
    rows["1D"] = _rows("1D", 120)
    artifact = rmc.build_real_snapshot_artifact(
        asset=ASSET, decision_time=DECISION_TIME, rows_by_interval=rows
    )
    gate = rmc.evaluate_g_real_market_context(artifact, snapshot_at=DECISION_TIME)
    assert gate["status"] == "FAIL"
    assert "DAILY_HISTORY_FOR_SMA200" in gate["failed"]


def test_gate_fails_when_freshness_is_broken() -> None:
    artifact = rmc.build_real_snapshot_artifact(
        asset=ASSET, decision_time=DECISION_TIME, rows_by_interval=_all_rows()
    )
    gate = rmc.evaluate_g_real_market_context(artifact, snapshot_at=DECISION_TIME + 86_400)
    assert gate["status"] == "FAIL"
    assert "FRESHNESS" in gate["failed"]


def test_gate_fails_on_a_future_bar() -> None:
    rows = _all_rows()
    bar_ms = rmc.BAR_SECONDS["4h"] * 1_000
    rows["4h"] = [
        *rows["4h"],
        OHLCV(
            symbol="BTC/USDT",
            timestamp=DECISION_MS + bar_ms,
            open=1,
            high=1,
            low=1,
            close=1,
            volume=1,
        ),
    ]
    # The builder refuses to fetch a future bar into the snapshot; the gate check
    # is exercised directly on a deliberately poisoned artifact instead.
    artifact = rmc.build_real_snapshot_artifact(
        asset=ASSET, decision_time=DECISION_TIME, rows_by_interval=_all_rows()
    )
    artifact["raw_evidence"]["intervals"]["4h"]["bars"].append(
        {"t": (DECISION_MS + bar_ms) // 1_000, "o": 1, "h": 1, "l": 1, "c": 1, "v": 1}
    )
    gate = rmc.evaluate_g_real_market_context(artifact, snapshot_at=DECISION_TIME)
    assert gate["status"] == "FAIL"
    assert "COMPLETED_BAR_ENFORCEMENT" in gate["failed"]


# --------------------------------------------------------------------------- #
# analyst contract
# --------------------------------------------------------------------------- #


def _analyst(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "asset": ASSET,
        "decision": "LONG",
        "horizon": "24H",
        "thesis": "trend continuation",
        "evidence": ["1h/4h/1D up"],
        "counter_evidence": ["thin volume"],
        "invalidation": "4h close below SMA50",
        "confidence": 0.55,
        "expected_holding_period": "24H",
        "decision_time": DECISION_TIME,
        "no_trade_reason": "",
    }
    base.update(overrides)
    return base


def test_prompt_is_frozen_and_digest_is_stable() -> None:
    assert mav.PROMPT_VERSION == "MARKET_ANALYST_V1.0"
    assert mav.DEFAULT_BIAS == "NO_TRADE"
    assert mav.prompt_digest() == mav.prompt_digest()
    assert len(mav.prompt_digest()) == 64


def test_valid_analyst_answer_passes() -> None:
    assert mav.validate_analyst_output(_analyst()) == []


def test_no_trade_requires_a_reason() -> None:
    payload = _analyst(decision="NO_TRADE", evidence=[], no_trade_reason="")
    assert any("no_trade_reason" in problem for problem in mav.validate_analyst_output(payload))
    assert (
        mav.validate_analyst_output(
            _analyst(decision="NO_TRADE", evidence=[], no_trade_reason="no edge")
        )
        == []
    )


def test_analyst_horizon_and_decision_are_restricted() -> None:
    assert any(
        "horizon" in problem for problem in mav.validate_analyst_output(_analyst(horizon="1W"))
    )
    assert any(
        "decision" in problem for problem in mav.validate_analyst_output(_analyst(decision="MAYBE"))
    )


def test_analyst_confidence_is_bounded() -> None:
    assert any(
        "confidence" in problem for problem in mav.validate_analyst_output(_analyst(confidence=1.4))
    )
    assert any(
        "confidence" in problem
        for problem in mav.validate_analyst_output(_analyst(confidence="high"))
    )


def test_analyst_may_never_emit_sizing() -> None:
    problems = mav.validate_analyst_output(_analyst(leverage=8))
    assert any("never emit" in problem for problem in problems)
    with pytest.raises(ValueError, match="refusing to seal"):
        mav.seal_analyst_decision(
            _analyst(size=1.0), snapshot_hash="a" * 64, raw_data_hash="b" * 64
        )


def test_directional_answer_needs_evidence() -> None:
    assert any(
        "evidence" in problem for problem in mav.validate_analyst_output(_analyst(evidence=[]))
    )


def test_seal_is_verified_and_binds_the_snapshot() -> None:
    record = mav.seal_analyst_decision(_analyst(), snapshot_hash="a" * 64, raw_data_hash="b" * 64)
    assert record.is_verified() is True
    assert record.decision == "LONG"
    assert record.prompt_version == "MARKET_ANALYST_V1.0"
    assert record.evidence_snapshot_hash == "a" * 64
    assert record.timestamp == DECISION_TIME
    assert record.agent_output["raw_data_hash"] == "b" * 64


def test_seal_is_deterministic_and_separate_from_the_outcome() -> None:
    first = mav.seal_analyst_decision(_analyst(), snapshot_hash="a" * 64, raw_data_hash="b" * 64)
    second = mav.seal_analyst_decision(_analyst(), snapshot_hash="a" * 64, raw_data_hash="b" * 64)
    assert first.decision_hash == second.decision_hash
    # Adding a future outcome must not touch the seal.
    tampered = dataclasses.replace(first, timestamp=first.timestamp + 1)
    assert tampered.recomputed_hash() != first.decision_hash
