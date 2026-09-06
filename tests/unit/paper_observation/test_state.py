"""Unit tests for POC01 durable campaign state (§38: state schema, atomic write, corrupted state)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trading_bot.paper_observation.state import (
    SCHEMA_VERSION,
    CampaignStateStore,
    CorruptedStateError,
    DurableCampaignState,
    daily_report_payload,
    performance_metrics,
)


def test_state_schema_roundtrip(tmp_path: Path) -> None:
    state = DurableCampaignState(
        campaign_id="poc01-test-20260101-001",
        campaign_start="2026-01-01T00:00:00+00:00",
        implementation_commit="deadbeef1234",
        provider="ccxt",
        assets=("BTC", "ETH", "SOL"),
        run_id="poc01-test-20260101-001-run1",
        trace_id="trace-poc01-test",
    )
    state.mark_decision("decision-1")
    state.mark_order("decision-1:open")
    state.mark_fill("decision-1:open")
    store = CampaignStateStore(tmp_path)
    store.save(state)
    loaded = store.load()
    assert loaded.schema_version == SCHEMA_VERSION
    assert loaded.campaign_id == state.campaign_id
    assert loaded.assets == ("BTC", "ETH", "SOL")
    assert loaded.last_processed_decision_ids == ["decision-1"]
    assert loaded.processed_order_ids == ["decision-1:open"]
    assert loaded.processed_fill_ids == ["decision-1:open"]
    # no duplicate marks
    state.mark_decision("decision-1")
    assert state.last_processed_decision_ids == ["decision-1"]


def test_atomic_write_leaves_no_tmp_and_valid_json(tmp_path: Path) -> None:
    store = CampaignStateStore(tmp_path)
    state = DurableCampaignState(campaign_id="poc01-atomic-001")
    store.save(state)
    assert not list(tmp_path.glob("*.tmp"))
    payload = json.loads((tmp_path / "CAMPAIGN_STATE.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == SCHEMA_VERSION


def test_save_overwrites_previous_state_atomically(tmp_path: Path) -> None:
    store = CampaignStateStore(tmp_path)
    first = DurableCampaignState(campaign_id="poc01-x", realized_pnl=1.0)
    store.save(first)
    second = DurableCampaignState(campaign_id="poc01-x", realized_pnl=42.5)
    store.save(second)
    assert store.load().realized_pnl == 42.5
    assert not list(tmp_path.glob("*.tmp"))


def test_corrupted_state_raises(tmp_path: Path) -> None:
    store = CampaignStateStore(tmp_path)
    store.path.write_text("{not json", encoding="utf-8")
    with pytest.raises(CorruptedStateError):
        store.load()


def test_unknown_schema_version_rejected(tmp_path: Path) -> None:
    store = CampaignStateStore(tmp_path)
    store.path.write_text(json.dumps({"schema_version": "poc01-state-v999"}), encoding="utf-8")
    with pytest.raises(CorruptedStateError):
        store.load()


def test_load_missing_state_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        CampaignStateStore(tmp_path).load()


def test_performance_metrics_canonical_numbers() -> None:
    trades = [
        {"pnl": 100.0, "fees": 1.0, "closed_at_ms": 1_000},
        {"pnl": -40.0, "fees": 1.0, "closed_at_ms": 2_000},
        {"pnl": 60.0, "fees": 1.0, "closed_at_ms": 3_000},
    ]
    metrics = performance_metrics(
        initial_equity=10_000.0,
        equity=10_120.0,
        closed_trades=trades,
        realized_pnl=120.0,
        unrealized_pnl=5.0,
        fees=3.0,
    )
    assert metrics["trades"] == 3
    assert metrics["wins"] == 2
    assert metrics["losses"] == 1
    assert metrics["net_pnl"] == 120.0
    assert metrics["win_rate"] == pytest.approx(2 / 3)
    assert metrics["profit_factor"] == pytest.approx(160.0 / 40.0)
    assert metrics["expectancy"] == pytest.approx(120.0 / 3)
    assert metrics["sample_status"] == "INSUFFICIENT_SAMPLE"  # 3 < 30


def test_daily_report_payload_frequency_kpi() -> None:
    payload = daily_report_payload(
        campaign_id="poc01-x",
        day="2026-01-01",
        day_entry={"trades": 3, "valid": True},
    )
    assert payload["trades_per_day"] == 3
    assert payload["day_ge_3"] == 1
    low = daily_report_payload(campaign_id="poc01-x", day="2026-01-02", day_entry={"trades": 2})
    assert low["day_ge_3"] == 0
