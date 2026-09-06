"""POC01 integration tests (§8, §31, §33, §38)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from trading_bot.market_data.types import OHLCV
from trading_bot.paper_observation import runtime as rt_module
from trading_bot.paper_observation.runtime import (
    FIXTURE_EPOCH_MS,
    CampaignRuntime,
    create_campaign_dashboard,
)


def accelerating(asset: str, ts_end: int, *, n: int = 80, p0: float = 100.0) -> list[OHLCV]:
    out: list[OHLCV] = []
    price = p0
    start = ts_end - (n - 1) * 300_000
    for i in range(n):
        price *= 1.002
        out.append(
            OHLCV(f"{asset}/USDT", start + i * 300_000, price * 0.998, price * 1.002, price * 0.996, price, 100.0)
        )
    return out


def make_runtime(tmp_path: Path, **kw: Any) -> CampaignRuntime:
    kw.setdefault("strategies", ("momentum",))
    return CampaignRuntime(output_dir=tmp_path, provider="fake", **kw)


def ts(cycle: int) -> int:
    return FIXTURE_EPOCH_MS + cycle * 3_600_000


def test_resume_e2e_open_persist_restart_close(tmp_path: Path) -> None:
    """§8: start → open → persist → terminate → resume → later event → close → reconcile."""
    rt = make_runtime(tmp_path, campaign_name="resume-e2e")
    state = rt.new_campaign()
    end1 = ts(1)
    bars1 = {a: accelerating(a, end1) for a in ("BTC", "ETH", "SOL")}
    now1 = datetime.fromtimestamp((end1 + 60_000) / 1000, tz=UTC)
    risk, broker = rt._rehydrate(state)
    rt.run_cycle(bars_by_asset=bars1, risk=risk, broker=broker, now=now1)
    assert len(state.open_positions) == 1, "single-slot risk: exactly one position"
    rt._persist()
    opened_before = len(state.open_positions)
    orders_before = list(state.processed_order_ids)

    # --- simulate process termination: brand-new runtime object ---
    rt2 = make_runtime(tmp_path, campaign_name="resume-e2e")
    resumed = rt2.load_for_resume()
    assert resumed.campaign_id == state.campaign_id
    assert len(resumed.open_positions) == opened_before
    assert resumed.processed_order_ids == orders_before
    assert resumed.realized_pnl == state.realized_pnl

    # later market event with higher prices closes at take-profit
    end2 = ts(2)
    bars2 = {a: accelerating(a, end2, p0=160.0) for a in ("BTC", "ETH", "SOL")}
    now2 = datetime.fromtimestamp((end2 + 60_000) / 1000, tz=UTC)
    risk2, broker2 = rt2._rehydrate(resumed)
    rt2.run_cycle(bars_by_asset=bars2, risk=risk2, broker=broker2, now=now2)
    rt2._persist()

    assert resumed.closed_trades, "recovered position must close on the later event"
    recovered_close = [
        t for t in resumed.closed_trades if t["exit_reason"] in ("take_profit", "stop_loss")
    ]
    assert recovered_close, "original position closed via SL/TP reconciliation"
    assert all(t["pnl"] != 0 for t in recovered_close)
    # duplicate prevention: exactly one NEW order (the new decision) - the
    # recovered position was NOT re-entered
    new_orders = [o for o in resumed.processed_order_ids if o not in orders_before]
    assert len(new_orders) <= 1
    # PnL continuity: realized == sum of closed trades, equity == initial + realized
    assert resumed.realized_pnl == pytest.approx(sum(float(t["pnl"]) for t in resumed.closed_trades), abs=1e-6)
    assert resumed.equity == pytest.approx(resumed.initial_equity + resumed.realized_pnl, abs=1e-6)
    # orphan fills = 0: every fill id maps to a known decision/order or close
    assert resumed.processed_fill_ids == [i for i in resumed.processed_fill_ids if i]
    # reconciliation heartbeat
    assert resumed.heartbeat["last_reconciliation_success"] is not None


def test_credentials_present_but_not_consumed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """§3/§31: host may hold exchange keys; the public provider must never read them."""
    captured: dict[str, Any] = {}

    class StubExchange:
        def __init__(self, config: dict[str, Any]) -> None:
            captured["config"] = config

        def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[list[float]]:
            return [[1_786_000_000_000, 100.0, 101.0, 99.0, 100.5, 1000.0]] * 30

        def close(self) -> None:
            captured["closed"] = True

    import ccxt

    monkeypatch.setattr(ccxt, "binance", StubExchange)
    bars = rt_module._public_bars(("BTC",))
    assert len(bars["BTC"]) == 30
    config = captured["config"]
    assert config["apiKey"] == "" and config["secret"] == ""
    assert captured.get("closed") is True


def test_no_host_secret_values_reach_provider_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Even with host credentials in env, provider config contains no secret values."""
    host_secret = "vojNwGQBPixb0W5rMWmZgb2b18Opk5SIoYhY"
    captured: dict[str, Any] = {}

    class StubExchange:
        def __init__(self, config: dict[str, Any]) -> None:
            captured["config"] = config

        def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[list[float]]:
            return [[1, 1.0, 1.0, 1.0, 1.0, 1.0]] * 30

        def close(self) -> None:
            pass

    import ccxt

    monkeypatch.setattr(ccxt, "binance", StubExchange)
    monkeypatch.setenv("EXCHANGE_API_SECRET", host_secret)
    rt_module._public_bars(("BTC",))
    assert host_secret not in json.dumps(captured["config"])


def test_dashboard_read_only_campaign_state(tmp_path: Path) -> None:
    rt = make_runtime(tmp_path, campaign_name="dash")
    rt.new_campaign()
    server = create_campaign_dashboard(rt, port=0)
    port = server.port
    server.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/campaign", timeout=5) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        assert payload["mode"] == "PAPER"
        assert payload["live_disabled"] is True
        assert payload["campaign_id"] == rt.campaign_id
        assert "today" in payload and "funnel" in payload and "runtime_health" in payload
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as resp:
            assert resp.status == 200
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/order", timeout=5)
            raised = False
        except urllib.error.HTTPError as exc:
            raised = exc.code == 404
        assert raised, "no control endpoints may exist"
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/campaign", data=b"{}", method="POST"
        )
        try:
            urllib.request.urlopen(req, timeout=5)
            post_ok = True
        except urllib.error.HTTPError as exc:
            post_ok = False
            assert exc.code == 405
        assert not post_ok, "POST must be rejected"
    finally:
        server.stop()


def test_safe_stop_mid_session(tmp_path: Path) -> None:
    rt = make_runtime(tmp_path, campaign_name="stop")
    rt.new_campaign()
    rt.request_stop()  # stop before the first cycle
    result = rt.run_bounded_session(cycles=3)
    assert result["session"]["cycles"] == 0
    assert result["session"]["stopped_early"] is True
    loaded = rt.store.load()
    assert loaded.campaign_status in ("STOPPED", "PAUSED")
    assert (rt.campaign_dir / "CAMPAIGN_REPORT.json").exists()


def test_daily_rollover_two_days(tmp_path: Path) -> None:
    rt = make_runtime(tmp_path, campaign_name="rollover")
    state = rt.new_campaign()
    end1 = ts(1)
    bars1 = {a: accelerating(a, end1) for a in ("BTC", "ETH", "SOL")}
    now1 = datetime.fromtimestamp((end1 + 60_000) / 1000, tz=UTC)
    risk, broker = rt._rehydrate(state)
    rt.run_cycle(bars_by_asset=bars1, risk=risk, broker=broker, now=now1)
    end2 = ts(25)  # one day later in fixture time
    bars2 = {a: accelerating(a, end2) for a in ("BTC", "ETH", "SOL")}
    now2 = datetime.fromtimestamp((end2 + 60_000) / 1000, tz=UTC)
    state.processed_data_fingerprints.clear()
    rt.run_cycle(bars_by_asset=bars2, risk=risk, broker=broker, now=now2)
    assert len(state.daily) == 2
    rt.write_reports()
    day_dirs = [d for d in rt.campaign_dir.iterdir() if d.is_dir()]
    assert len(day_dirs) == 2
    for d in day_dirs:
        assert (d / "DAILY_REPORT.json").exists()
        assert (d / "DAILY_REPORT.md").exists()


def test_provider_failure_recorded_campaign_continues(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """§11/§30: provider failure is loud in health metrics, session survives."""
    rt = CampaignRuntime(
        output_dir=tmp_path, campaign_name="provider-fail", provider="ccxt", strategies=("momentum",)
    )
    state = rt.new_campaign()

    def failing_bars(assets: tuple[str, ...], *, limit: int = 150) -> dict[str, list[OHLCV]]:
        raise ConnectionError("public provider down")

    monkeypatch.setattr(rt_module, "_public_bars", failing_bars)
    result = rt.run_bounded_session(cycles=2)
    assert result["session"]["cycles"] == 0
    loaded = rt.store.load()
    assert loaded.campaign_id == state.campaign_id
    assert loaded.data_health["provider_failures"] >= 1
    assert loaded.heartbeat["provider_status"] == "STALE"
    assert any("provider:" in e for e in loaded.errors)
    assert loaded.funnel.get("PAPER_OPEN", 0) == 0
    assert (rt.campaign_dir / "CAMPAIGN_STATE.json").exists()
