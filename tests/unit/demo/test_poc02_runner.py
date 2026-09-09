"""POC02 runtime tests (Track A, POC02-LAUNCH-AND-DISCOVERY-BATCH-02)."""

from __future__ import annotations

from typing import Any

import pytest

import trading_bot.demo.poc02_runner as runner_mod
from trading_bot.demo.paper_multi_agent import DemoSafetyError, RiskCheck
from trading_bot.demo.poc02_runner import (
    POC02_CAMPAIGN_ID,
    POC02_MANIFEST_SHA256,
    PROVIDER_AUTHORITY,
    Poc02Bundle,
    evaluate_launch_gates,
)


def _bars(symbol: str, n: int = 60) -> list:
    from trading_bot.market_data.types import OHLCV

    out = []
    price = 100.0
    for i in range(n):
        price = price * (1.001 if i % 3 else 0.999)
        out.append(
            OHLCV(
                symbol=symbol,
                timestamp=1_700_000_000_000 + i * 300_000,
                open=price,
                high=price * 1.002,
                low=price * 0.998,
                close=price,
                volume=1_000.0,
            )
        )
    return out


def _bundle(tmp_path, monkeypatch) -> Poc02Bundle:
    monkeypatch.setattr(
        runner_mod, "_fetch_public_bars", lambda assets, limit=120: {a: _bars(f"{a}/USDT") for a in assets}
    )
    return Poc02Bundle(output_dir=tmp_path / "poc02", shadow_dir=tmp_path / "poc02" / "shadow")


# --------------------------------------------------------------------------
# Launch gates (preregistered, unchanged)
# --------------------------------------------------------------------------

def test_launch_gates_all_pass_with_committed_manifest_sha() -> None:
    g = evaluate_launch_gates(POC02_MANIFEST_SHA256)
    assert g["launch_authorized"] is True
    assert g["failed"] == 0
    assert g["total"] == 6


def test_launch_blocked_on_manifest_mismatch(tmp_path) -> None:
    g = evaluate_launch_gates("0" * 64)
    assert g["launch_authorized"] is False
    assert g["gates"]["manifest_committed"] is False
    with pytest.raises(DemoSafetyError):
        Poc02Bundle(
            output_dir=tmp_path / "x",
            shadow_dir=tmp_path / "x" / "s",
            manifest_sha256="0" * 64,
        )


def test_new_campaign_identity_and_provider_authority() -> None:
    assert POC02_CAMPAIGN_ID == "POC-02-paper-clean-01"
    assert POC02_CAMPAIGN_ID != "POC-01-paper-observation-01"
    assert PROVIDER_AUTHORITY["EXECUTION_MODE"] == "PAPER"
    assert PROVIDER_AUTHORITY["EXECUTION_VENUE_MODEL"] == "PaperBroker"
    assert "no credentials" in PROVIDER_AUTHORITY["MARKET_DATA_PROVIDER"]


# --------------------------------------------------------------------------
# Runtime cycle on synthetic bars
# --------------------------------------------------------------------------

def test_full_cycle_runs_paper_only(tmp_path, monkeypatch) -> None:
    bundle = _bundle(tmp_path, monkeypatch)
    summary = bundle.run_cycle(assets=("BTC",))
    state = summary["state"]
    assert state["mode"] == "PAPER"
    assert state["campaign_id"] == POC02_CAMPAIGN_ID
    assert state["live_calls"] == 0
    assert bundle.real_broker_calls == 0
    assert bundle.private_exchange_calls == 0
    assert summary["shadow_captures_total"] == len(bundle.shadow.captures)
    assert len(summary["bottlenecks"]) == 1


def test_cycle_telemetry_written_with_provider_authority(tmp_path, monkeypatch) -> None:
    import json

    bundle = _bundle(tmp_path, monkeypatch)
    summary = bundle.run_cycle(assets=("BTC",))
    path = tmp_path / "poc02" / f"POC02_TELEMETRY_{summary['run_id']}.json"
    assert path.exists()
    t = json.loads(path.read_text(encoding="utf-8"))
    assert t["provider_authority"] == PROVIDER_AUTHORITY
    assert t["campaign_id"] == POC02_CAMPAIGN_ID
    assert t["live_calls"] == 0
    assert t["shadow_paperbroker_calls"] == 0


def test_risk_reject_routes_to_shadow_capture(tmp_path, monkeypatch) -> None:
    bundle = _bundle(tmp_path, monkeypatch)

    def _reject(signal: Any) -> RiskCheck:
        return RiskCheck(approved=False, reason="Consecutive loss cooldown (3 losses)", blocked_by="consecutive_loss_cooldown")

    bundle.risk.check_signal = _reject  # type: ignore[method-assign]
    summary = bundle.run_cycle(assets=("BTC",))
    state = summary["state"]
    # either a verified candidate was rejected by risk, or no candidate existed
    if state["risk_rejects"] > 0:
        assert bundle.shadow.captures, "risk reject must produce a shadow capture"
        cap = bundle.shadow.captures[0]
        assert cap.risk_rejection_reason
        assert cap.strategy_health_state
        assert cap.regime_signature
        assert cap.market_data_fingerprint
    assert state["paper_trades"] == 0
    assert len(bundle.broker.positions) == 0


def test_shadow_never_calls_broker_or_risk(tmp_path, monkeypatch) -> None:
    bundle = _bundle(tmp_path, monkeypatch)
    calls = {"broker": 0, "risk": 0}
    orig_broker_exec = bundle.broker.execute_signal
    orig_risk_check = bundle.risk.check_signal

    def spy_broker(*a: Any, **k: Any) -> Any:
        calls["broker"] += 1
        return orig_broker_exec(*a, **k)

    def spy_risk(signal: Any) -> RiskCheck:
        calls["risk"] += 1
        return orig_risk_check(signal)

    bundle.broker.execute_signal = spy_broker  # type: ignore[method-assign]
    bundle.risk.check_signal = spy_risk  # type: ignore[method-assign]
    summary = bundle.run_cycle(assets=("BTC",))
    state = summary["state"]
    # every broker call maps to a state-accounted paper trade path,
    # and the shadow surfaces never invoke either
    assert bundle.shadow_paperbroker_calls == 0
    assert calls["risk"] == state["risk_calls"]
    assert calls["broker"] == state["broker_calls"]


def test_safety_assert_fails_on_live_call(tmp_path, monkeypatch) -> None:
    bundle = _bundle(tmp_path, monkeypatch)
    bundle.live_calls = 1
    with pytest.raises(DemoSafetyError):
        bundle.assert_safety()
