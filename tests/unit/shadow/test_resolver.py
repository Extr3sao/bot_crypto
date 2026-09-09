"""Shadow PIT resolver tests (§9 — POC02-OBSERVATION-AND-ALPHA-DIAGNOSIS-01)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import trading_bot.shadow.resolver as resolver_mod
from trading_bot.shadow.integration import ShadowCaptureHook
from trading_bot.shadow.resolver import resolve_pending_shadow_captures


def _capture_ctx(decision_id: str, decision_time: datetime, price: float = 100.0) -> dict:
    return {
        "decision_id": decision_id,
        "trace_id": f"trace-{decision_id}",
        "run_id": "run-1",
        "asset": "BTC/USDT:USDT",
        "direction": "LONG",
        "strategy_id": "momentum",
        "strategy_version": "1",
        "timeframe": "5m",
        "proposal_ref": f"proposal:{decision_id}",
        "decision_ref": f"decision:{decision_id}",
        "verifier_ref": f"verifier:{decision_id}",
        "decision_time": decision_time.isoformat(),
        "decision_price": price,
        "entry_reference": price,
        "stop_loss": price * 0.98,
        "take_profit": price * 1.04,
        "invalidation": "test",
        "regime_signature": "NEUTRAL|WEAK|NORMAL|RANGE|NORMAL|NORMAL",
        "strategy_health_state": "LEGACY_PAPER_BASELINE",
        "portfolio_context_ref": "ref",
        "correlation_state": "NORMAL",
        "risk_verdict": "REJECT",
        "risk_rejection_reason": "max_positions",
        "market_data_fingerprint": "fp",
        "cost_model_sha256": "cm",
    }


def _bars(decision_time: datetime, hours: float, hit_tp_at_hour: float | None = None):
    from trading_bot.market_data.types import OHLCV

    out = []
    t = decision_time + timedelta(minutes=5)
    end = decision_time + timedelta(hours=hours)
    while t <= end:
        high = 100.4
        low = 99.6
        if hit_tp_at_hour is not None and t >= decision_time + timedelta(hours=hit_tp_at_hour):
            high = 104.5  # take-profit at +4%
        out.append(
            OHLCV(
                symbol="BTC/USDT:USDT",
                timestamp=int(t.timestamp() * 1000),
                open=100.0,
                high=high,
                low=low,
                close=100.1,
                volume=1.0,
            )
        )
        t += timedelta(minutes=5)
    return out


def _write_capture(tmp_path: Path, decision_id: str, decision_time: datetime) -> None:
    hook = ShadowCaptureHook(
        captures_path=tmp_path / "shadow_captures.jsonl",
        outcomes_path=tmp_path / "shadow_outcomes.jsonl",
    )
    hook.on_risk_reject(_capture_ctx(decision_id, decision_time))


def test_resolve_pending_resolves_with_real_bars(tmp_path, monkeypatch) -> None:
    decision_time = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
    _write_capture(tmp_path, "d1", decision_time)
    bars = _bars(decision_time, hours=6, hit_tp_at_hour=2.0)
    monkeypatch.setattr(
        resolver_mod, "_fetch_public_bars_binanceusdm", lambda symbol, start_ms, end_ms: bars
    )
    summary = resolve_pending_shadow_captures(
        captures_path=tmp_path / "shadow_captures.jsonl",
        outcomes_path=tmp_path / "shadow_outcomes.jsonl",
        now=decision_time + timedelta(hours=10),
    )
    assert summary["resolved_now"] == 1
    assert summary["pending_after"] == 0
    # re-run: idempotent, nothing new resolved
    summary2 = resolve_pending_shadow_captures(
        captures_path=tmp_path / "shadow_captures.jsonl",
        outcomes_path=tmp_path / "shadow_outcomes.jsonl",
        now=decision_time + timedelta(hours=10),
    )
    assert summary2["resolved_now"] == 0
    assert summary2["already_resolved"] == 1


def test_resolve_keeps_pending_when_no_bars_available(tmp_path, monkeypatch) -> None:
    decision_time = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
    _write_capture(tmp_path, "d2", decision_time)
    monkeypatch.setattr(
        resolver_mod, "_fetch_public_bars_binanceusdm", lambda symbol, start_ms, end_ms: []
    )
    summary = resolve_pending_shadow_captures(
        captures_path=tmp_path / "shadow_captures.jsonl",
        outcomes_path=tmp_path / "shadow_outcomes.jsonl",
        now=decision_time + timedelta(hours=2),
    )
    assert summary["resolved_now"] == 0
    assert summary["skipped_insufficient_bars"] == 1
    # nothing synthesized: outcomes ledger absent/empty
    out_path = tmp_path / "shadow_outcomes.jsonl"
    assert not out_path.exists() or out_path.read_text(encoding="utf-8").strip() == ""


def test_resolve_provider_error_keeps_capture_pending(tmp_path, monkeypatch) -> None:
    decision_time = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
    _write_capture(tmp_path, "d3", decision_time)

    def _boom(symbol, start_ms, end_ms):
        raise RuntimeError("provider down")

    monkeypatch.setattr(resolver_mod, "_fetch_public_bars_binanceusdm", _boom)
    summary = resolve_pending_shadow_captures(
        captures_path=tmp_path / "shadow_captures.jsonl",
        outcomes_path=tmp_path / "shadow_outcomes.jsonl",
        now=decision_time + timedelta(hours=2),
    )
    assert summary["resolved_now"] == 0
    assert summary["errors"], "provider error must be surfaced, not swallowed"
