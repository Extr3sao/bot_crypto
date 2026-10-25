"""CAP-001 — unit tests for the deterministic TradingView MCP adapter.

The fixture is explicitly synthetic; the shapes mimic the documented MCP
responses so the mapping logic can be tested without credentials.

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from trading_bot.research import agentic_contracts as ac
from trading_bot.research import tradingview_mcp_adapter as tva

REPO = Path(__file__).resolve().parents[3]
FIXTURE = REPO / "tests" / "fixtures" / "tradingview_mcp_sample.json"
BUNDLE: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))


def _snapshot() -> ac.MarketSnapshot:
    return tva.build_snapshot(
        asset=BUNDLE["asset"],
        snapshot_at=int(BUNDLE["snapshot_at"]),
        ohlcv_by_interval=BUNDLE["ohlcv"],
        technicals_payload=BUNDLE["technicals_rating"],
        news_payload=BUNDLE["news"],
        macro_payload=BUNDLE["economic_calendar"],
        market_regime=BUNDLE["market_regime"],
        reference_symbol=BUNDLE["reference_symbol"],
        relative_strength_value=float(BUNDLE["relative_strength"]),
        source_timestamps=BUNDLE["source_timestamps"],
    )


# --------------------------------------------------------------------------- #
# fixture hygiene
# --------------------------------------------------------------------------- #


def test_fixture_declares_itself_synthetic() -> None:
    assert BUNDLE["_synthetic"] is True
    assert "SYNTHETIC_FIXTURE" in BUNDLE["_note"]


# --------------------------------------------------------------------------- #
# bars
# --------------------------------------------------------------------------- #


def test_extract_bars_reads_the_documented_shape() -> None:
    bars = tva.extract_bars(BUNDLE["ohlcv"]["4h"])
    assert len(bars) == 18
    assert set(bars[0]) >= {"t", "o", "h", "l", "c", "v"}


def test_extract_bars_accepts_a_bare_list() -> None:
    assert len(tva.extract_bars([{"t": 1, "c": 2.0}])) == 1


def test_extract_bars_refuses_to_invent_structure() -> None:
    with pytest.raises(ValueError, match="no bars array"):
        tva.extract_bars({"symbol": "X"})
    with pytest.raises(ValueError, match="non-empty"):
        tva.extract_bars({"bars": []})
    with pytest.raises(ValueError, match="must be a mapping or a bar list"):
        tva.extract_bars("nope")
    with pytest.raises(ValueError, match="numeric close"):
        tva.extract_bars({"bars": [{"t": 1, "o": 1.0}]})


def test_extract_bars_enforces_the_documented_cap() -> None:
    oversized = [{"t": index, "c": 1.0} for index in range(ac.MCP_MAX_OHLCV_BARS + 1)]
    with pytest.raises(ValueError, match="above the documented"):
        tva.extract_bars({"bars": oversized})


def test_closes_and_volumes_skip_non_numeric_entries() -> None:
    bars = [{"c": 1.0, "v": 2.0}, {"c": "bad", "v": 3.0}, {"c": 4.0}]
    assert tva.closes(bars) == (1.0, 4.0)
    assert tva.volumes(bars) == (2.0, 3.0)


def test_bar_timestamps_returns_ints() -> None:
    stamps = tva.bar_timestamps(tva.extract_bars(BUNDLE["ohlcv"]["1h"]))
    assert len(stamps) == 24
    assert all(isinstance(stamp, int) for stamp in stamps)


# --------------------------------------------------------------------------- #
# trend + blocks
# --------------------------------------------------------------------------- #


def test_trend_of_labels_rising_falling_and_flat() -> None:
    rising = [{"c": float(index)} for index in range(1, 25)]
    falling = [{"c": float(index)} for index in range(24, 0, -1)]
    flat = [{"c": 100.0} for _ in range(24)]
    assert tva.trend_of(rising) == "up"
    assert tva.trend_of(falling) == "down"
    assert tva.trend_of(flat) == "range"
    assert tva.trend_of([{"c": 1.0}]) == "unknown"


def test_price_state_uses_the_last_close() -> None:
    payload = BUNDLE["ohlcv"]["1D"]
    state = tva.price_state_from_ohlcv("BINANCE:BTCUSDT", "1D", payload)
    assert state.last == payload["bars"][-1]["c"]
    assert state.bar_count == len(payload["bars"])
    assert state.bar_interval == "1D"
    assert state.change_pct > 0.0


def test_volume_state_compares_to_the_trailing_average() -> None:
    state = tva.volume_state_from_ohlcv(BUNDLE["ohlcv"]["4h"])
    assert state.last > 0.0
    assert state.relative > 0.0
    assert tva.volume_state_from_ohlcv({"bars": [{"c": 1.0, "v": 5.0}]}) == ac.VolumeState(
        last=5.0, relative=0.0
    )


def test_multi_timeframe_is_composed_in_contract_order() -> None:
    states = tva.multi_timeframe_states(BUNDLE["ohlcv"], BUNDLE["asset"])
    assert [state.interval for state in states] == list(tva.TIMEFRAME_ORDER)
    assert all(state.trend in ("up", "down", "range", "unknown") for state in states)


def test_multi_timeframe_appends_unknown_intervals_sorted() -> None:
    states = tva.multi_timeframe_states(
        {"1D": BUNDLE["ohlcv"]["1D"], "2h": BUNDLE["ohlcv"]["4h"], "1h": BUNDLE["ohlcv"]["1h"]},
        BUNDLE["asset"],
    )
    assert [state.interval for state in states] == ["1h", "1D", "2h"]


# --------------------------------------------------------------------------- #
# technicals
# --------------------------------------------------------------------------- #


def test_technical_state_reads_the_documented_fields() -> None:
    state = tva.technical_state_from_rating(BUNDLE["technicals_rating"])
    assert state.rsi == pytest.approx(61.2)
    assert state.adx == pytest.approx(28.4)
    assert state.recommendation == "BUY"


def test_missing_technical_fields_become_none_never_zero() -> None:
    state = tva.technical_state_from_rating({"symbol": "X"})
    assert state.rsi is None
    assert state.macd is None
    assert state.sma50 is None
    assert state.recommendation == ""


def test_technical_values_may_arrive_as_strings() -> None:
    state = tva.technical_state_from_rating({"RSI": "55.5", "ADX": "not-a-number"})
    assert state.rsi == pytest.approx(55.5)
    assert state.adx is None


# --------------------------------------------------------------------------- #
# news + macro
# --------------------------------------------------------------------------- #


def test_news_items_are_mapped() -> None:
    items = tva.news_items(BUNDLE["news"])
    assert len(items) == 2
    assert items[0].urgency == 1
    assert items[0].published > 0


def test_news_entries_without_title_or_date_are_dropped() -> None:
    payload = {
        "items": [{"title": "ok", "published": 1}, {"title": "", "published": 2}, {"published": 3}]
    }
    assert len(tva.news_items(payload)) == 1
    assert tva.news_items("nonsense") == ()
    assert tva.news_items(None) == ()


def test_macro_events_are_mapped_and_normalised() -> None:
    events = tva.macro_events(BUNDLE["economic_calendar"])
    assert [event.importance for event in events] == [1, 0]
    assert events[0].name == "US CPI YoY"


def test_macro_importance_outside_the_domain_is_normalised_to_unknown() -> None:
    payload = {"events": [{"name": "x", "when": 1, "importance": 9}]}
    assert tva.macro_events(payload)[0].importance == -1


def test_macro_events_drop_entries_without_name_or_date() -> None:
    payload = {"events": [{"name": "ok", "when": 1}, {"name": "", "when": 2}, {"name": "no-date"}]}
    assert len(tva.macro_events(payload)) == 1


# --------------------------------------------------------------------------- #
# tool gate
# --------------------------------------------------------------------------- #


def test_read_only_tools_are_accepted() -> None:
    assert tva.assert_read_only_tools(BUNDLE["tools_used"]) == tuple(BUNDLE["tools_used"])


def test_write_tools_are_rejected() -> None:
    with pytest.raises(ValueError, match="write MCP tool"):
        tva.assert_read_only_tools(["get_ohlcv", "create_alert"])


def test_unknown_tools_are_rejected() -> None:
    with pytest.raises(ValueError, match="unknown MCP tool"):
        tva.assert_read_only_tools(["get_ohlcv", "teleport_me"])


def test_spike_uses_only_read_only_tools() -> None:
    assert not set(BUNDLE["tools_used"]) & set(ac.WRITE_MCP_TOOLS)


# --------------------------------------------------------------------------- #
# freshness
# --------------------------------------------------------------------------- #


def test_freshness_is_fresh_for_the_fixture() -> None:
    freshness = tva.data_freshness(
        snapshot_at=int(BUNDLE["snapshot_at"]), source_timestamps=BUNDLE["source_timestamps"]
    )
    assert freshness.level == "FRESH"
    assert freshness.degraded is False
    assert freshness.age_seconds == 1800


def test_freshness_is_stale_for_an_old_feed() -> None:
    freshness = tva.data_freshness(snapshot_at=2_000_000, source_timestamps=[1_000_000])
    assert freshness.level == "STALE"
    assert freshness.degraded is True


def test_freshness_without_sources_is_unknown_and_degraded() -> None:
    freshness = tva.data_freshness(snapshot_at=2_000_000, source_timestamps=[])
    assert freshness.level == "UNKNOWN"
    assert freshness.degraded is True
    assert freshness.age_seconds == -1


def test_degraded_flag_propagates() -> None:
    freshness = tva.data_freshness(
        snapshot_at=int(BUNDLE["snapshot_at"]),
        source_timestamps=BUNDLE["source_timestamps"],
        degraded=True,
    )
    assert freshness.degraded is True


# --------------------------------------------------------------------------- #
# full snapshot
# --------------------------------------------------------------------------- #


def test_snapshot_built_from_the_fixture_is_contract_valid() -> None:
    snapshot = _snapshot()
    assert ac.validate_snapshot(snapshot) == []
    assert ac.snapshot_is_usable(snapshot) is True


def test_snapshot_carries_every_contract_field() -> None:
    payload = _snapshot().to_dict()
    assert set(payload) == set(ac.MARKET_SNAPSHOT_FIELDS)
    assert set(payload["data_freshness"]) == {
        "snapshot_at",
        "newest_source_at",
        "oldest_source_at",
        "age_seconds",
        "level",
        "degraded",
    }


def test_snapshot_evidence_comes_from_read_only_mcp_tools() -> None:
    snapshot = _snapshot()
    assert snapshot.evidence
    for item in snapshot.evidence:
        assert item.kind in ac.EVIDENCE_KINDS
        assert item.source.startswith("tradingview_mcp.")
        assert item.source.split(".", 1)[1] in ac.READ_ONLY_MCP_TOOLS


def test_snapshot_needs_at_least_one_interval() -> None:
    with pytest.raises(ValueError, match="at least one OHLCV interval"):
        tva.build_snapshot(
            asset="X",
            snapshot_at=1,
            ohlcv_by_interval={},
            technicals_payload={},
            news_payload={},
            macro_payload={},
            market_regime="range",
            reference_symbol="SP:SPX",
            relative_strength_value=None,
            source_timestamps=[],
        )


def test_snapshot_is_deterministic() -> None:
    assert ac.payload_digest(_snapshot().to_dict()) == ac.payload_digest(_snapshot().to_dict())
