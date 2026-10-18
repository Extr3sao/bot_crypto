"""PIT snapshot + event-driven AI gate — the causality and spend boundary."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trading_bot.market_data.market_events import EventGate, EventTriggerConfig, ResponseCache
from trading_bot.market_data.snapshot import (
    Quote,
    SnapshotUnavailable,
    build_market_snapshot,
    gate_snapshot,
    with_quote,
)
from trading_bot.market_data.timeframe_store import OHLCVTimeframeStore
from trading_bot.market_data.types import OHLCV
from trading_bot.storage.ohlcv_store import OHLCVStore

HOUR = 3_600_000
DAY = 24 * HOUR
START = ((1_700_000_000_000 // DAY) * DAY) + 2 * DAY  # aligned to a 4h and 1d boundary
SYMBOL = "BTC/USDT"


def seed(
    tmp_path: Path, *, bars_1h: int = 48, bars_4h: int = 12, bars_1d: int = 5
) -> OHLCVTimeframeStore:
    store = OHLCVTimeframeStore(OHLCVStore(f"sqlite:///{(tmp_path / 'ohlcv.sqlite').as_posix()}"))
    rows_1h: list[OHLCV] = []
    for index in range(bars_1h):
        base = 100.0 + index
        rows_1h.append(
            OHLCV(SYMBOL, START + index * HOUR, base, base + 1, base - 1, base + 0.5, 1.0)
        )
    rows_4h: list[OHLCV] = []
    for index in range(bars_4h):
        base = 100.0 + index * 2
        rows_4h.append(
            OHLCV(SYMBOL, START + index * 4 * HOUR, base, base + 2, base - 2, base + 1, 1.0)
        )
    rows_1d: list[OHLCV] = []
    for index in range(bars_1d):
        base = 100.0 + index * 5
        # Daily bars sit *before* START: at START + 46h only the bar opened at
        # START has closed (it closes at START + 24h), and a one-bar slice is
        # not a slice.
        rows_1d.append(
            OHLCV(
                SYMBOL,
                START - (bars_1d - 1 - index) * DAY,
                base,
                base + 5,
                base - 5,
                base + 2,
                1.0,
            )
        )
    store.upsert(rows_1h, symbol=SYMBOL, timeframe="1h")
    store.upsert(rows_4h, symbol=SYMBOL, timeframe="4h")
    store.upsert(rows_1d, symbol=SYMBOL, timeframe="1d")
    return store


def snapshot(store: OHLCVTimeframeStore, *, at: int, quote: Quote | None = None):
    return build_market_snapshot(
        store,
        symbol=SYMBOL,
        timeframes=["1h", "4h", "1d"],
        decision_ms=at,
        bars_per_timeframe=200,
        now_ms=at,
        quote=quote,
    )


def test_a_future_higher_timeframe_bar_is_never_part_of_the_snapshot(tmp_path):
    store = seed(tmp_path)
    at = START + 46 * HOUR  # 1h closed at 45; 4h closed at 44; 1d closed at 24 (yesterday)
    snap = snapshot(store, at=at)
    try:
        assert snap.slices["4h"].last_open_ms == START + 40 * HOUR
        assert snap.slices["1d"].last_open_ms == START
        assert snap.available_at_ms == START + 46 * HOUR
    finally:
        store.close()


def test_a_snapshot_built_at_a_later_decision_can_still_be_rejected_earlier(tmp_path):
    store = seed(tmp_path)
    at = START + 46 * HOUR
    snap = snapshot(store, at=at)
    try:
        early = gate_snapshot(snap, at_ms=START + 40 * HOUR)
        assert early.usable is False
        assert early.reason == "NOT_YET_AVAILABLE"
        assert early.retry_at_ms == START + 46 * HOUR
    finally:
        store.close()


def test_a_stale_snapshot_is_refused(tmp_path):
    store = seed(tmp_path)
    at = START + 46 * HOUR
    snap = snapshot(store, at=at)
    try:
        result = gate_snapshot(snap, at_ms=at + 6 * HOUR, max_age_ms=4 * HOUR)
        assert result.usable is False
        assert result.reason == "STALE_TIMEFRAME"
    finally:
        store.close()


def test_no_quote_means_no_executable_price(tmp_path):
    store = seed(tmp_path)
    at = START + 46 * HOUR
    snap = snapshot(store, at=at)
    try:
        result = gate_snapshot(snap, at_ms=at, require_quote=True)
        assert result.usable is False
        assert result.reason == "NO_EXECUTABLE_PRICE"

        quoted = with_quote(snap, Quote(bid=99.0, ask=101.0, observed_at_ms=at))
        assert gate_snapshot(quoted, at_ms=at, require_quote=True).usable is True
        assert quoted.executable_price(at + 61_000) is None
    finally:
        store.close()


def test_a_snapshot_without_closed_bars_fails_closed(tmp_path):
    store = seed(tmp_path, bars_1h=1, bars_4h=1, bars_1d=1)
    try:
        with pytest.raises(SnapshotUnavailable):
            snapshot(store, at=START)
    finally:
        store.close()


def test_snapshot_content_hash_changes_with_the_bars(tmp_path):
    store = seed(tmp_path)
    at = START + 46 * HOUR
    try:
        first = snapshot(store, at=at)
        same = snapshot(store, at=at)
        assert first.content_hash == same.content_hash
        store.upsert(
            [OHLCV(SYMBOL, at - 2 * HOUR, 1.0, 2.0, 0.5, 1.5, 3.0)],
            symbol=SYMBOL,
            timeframe="1h",
        )
        changed = snapshot(store, at=at)
        assert changed.content_hash != first.content_hash
    finally:
        store.close()


def _gate(tmp_path: Path, **overrides) -> EventGate:
    config = EventTriggerConfig(
        budget_usd=overrides.pop("budget_usd", 1.0),
        cost_per_attempt_usd=overrides.pop("cost_per_attempt_usd", 0.02),
        cooldown_ms=overrides.pop("cooldown_ms", 0),
        max_triggers_per_hour=overrides.pop("max_triggers_per_hour", 4),
        min_change_bps=overrides.pop("min_change_bps", 0.0),
        **overrides,
    )
    return EventGate(config, ledger_path=tmp_path / "triggers.jsonl")


def test_without_a_credential_the_gate_spends_nothing(tmp_path):
    store = seed(tmp_path)
    at = START + 46 * HOUR
    snap = snapshot(store, at=at)
    store.close()
    gate = _gate(tmp_path)
    decision = gate.evaluate(snap, at_ms=at, credentials_present=False)
    assert decision.should_analyze is False
    assert decision.reason == "MISSING_CREDENTIAL"
    assert decision.estimated_cost_usd == 0.0
    assert gate.spent_usd == 0.0


def test_zero_budget_is_enough_to_stop_every_call(tmp_path):
    store = seed(tmp_path)
    at = START + 46 * HOUR
    snap = snapshot(store, at=at)
    store.close()
    gate = _gate(tmp_path, budget_usd=0.0)
    decision = gate.evaluate(snap, at_ms=at, credentials_present=True)
    assert decision.reason == "BUDGET_EXHAUSTED"


def test_the_same_closed_bar_never_triggers_twice_even_after_a_restart(tmp_path):
    store = seed(tmp_path)
    at = START + 46 * HOUR
    snap = snapshot(store, at=at)
    store.close()
    gate = _gate(tmp_path)
    first = gate.evaluate(snap, at_ms=at, credentials_present=True)
    assert first.reason == "TRIGGERED"
    second = gate.evaluate(snap, at_ms=at + 60_000, credentials_present=True)
    assert second.reason == "DUPLICATE_EVENT"

    restarted = _gate(tmp_path)
    third = restarted.evaluate(snap, at_ms=at + 120_000, credentials_present=True)
    assert third.reason == "DUPLICATE_EVENT"
    assert restarted.spent_usd == pytest.approx(0.02)


def test_cooldown_bounds_the_spend(tmp_path):
    store = seed(tmp_path, bars_1h=48)
    gate = _gate(tmp_path, cooldown_ms=90 * 60 * 1_000, max_triggers_per_hour=10)
    fired = 0
    reasons: list[str] = []
    try:
        for step in range(6):
            at = START + (40 + step) * HOUR
            decision = gate.evaluate(snapshot(store, at=at), at_ms=at, credentials_present=True)
            reasons.append(decision.reason)
            fired += int(decision.should_analyze)
    finally:
        store.close()
    assert reasons.count("COOLDOWN") >= 1
    assert fired == 3, reasons


def test_hourly_cap_bounds_the_spend(tmp_path):
    store = seed(tmp_path, bars_1h=48)
    gate = _gate(tmp_path, cooldown_ms=0, max_triggers_per_hour=1)
    reasons: list[str] = []
    try:
        for step in range(4):
            at = START + (40 + step) * HOUR
            reasons.append(
                gate.evaluate(snapshot(store, at=at), at_ms=at, credentials_present=True).reason
            )
    finally:
        store.close()
    assert reasons[0] == "TRIGGERED"
    assert reasons[1] == "HOURLY_CAP"
    assert reasons.count("TRIGGERED") < len(reasons)


def test_a_material_change_threshold_can_suppress_a_new_bar(tmp_path):
    store = seed(tmp_path)
    at = START + 46 * HOUR
    snap = snapshot(store, at=at)
    store.close()
    gate = _gate(tmp_path, min_change_bps=10_000.0)
    decision = gate.evaluate(snap, at_ms=at, credentials_present=True, allow_new_candle=False)
    assert decision.reason == "NO_MATERIAL_CHANGE"


def test_the_trigger_ledger_is_append_only_and_explains_skips(tmp_path):
    store = seed(tmp_path)
    at = START + 46 * HOUR
    snap = snapshot(store, at=at)
    store.close()
    gate = _gate(tmp_path)
    gate.evaluate(snap, at_ms=at, credentials_present=False)
    gate.evaluate(snap, at_ms=at, credentials_present=True)
    rows = [
        json.loads(line)
        for line in (tmp_path / "triggers.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [row["reason"] for row in rows] == ["MISSING_CREDENTIAL", "TRIGGERED"]
    assert all("event_hash" in row for row in rows)


def test_cache_hits_are_fresh_only_for_the_same_inputs_and_ttl(tmp_path):
    cache = ResponseCache(tmp_path / "cache", ttl_ms=1_000)
    cache.put(
        snapshot_hash="hash-a",
        prompt_version="p1",
        model_version="m1",
        text="answer",
        at_ms=1_000,
    )
    assert cache.get(snapshot_hash="hash-a", prompt_version="p1", model_version="m1", at_ms=1_500)
    assert (
        cache.get(snapshot_hash="hash-b", prompt_version="p1", model_version="m1", at_ms=1_500)
        is None
    )
    assert (
        cache.get(snapshot_hash="hash-a", prompt_version="p2", model_version="m1", at_ms=1_500)
        is None
    )
    assert (
        cache.get(snapshot_hash="hash-a", prompt_version="p1", model_version="m1", at_ms=2_500)
        is None
    ), "an expired entry must not be reported as fresh"
