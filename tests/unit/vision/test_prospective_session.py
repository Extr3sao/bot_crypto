"""INTEGRATION/RUNTIME — a paper session on a live-shaped feed, without a venue call."""

from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path

import pytest

from trading_bot.config.settings import load_settings
from trading_bot.market_data.minute_collector import (
    MINUTE_MS,
    KlinePage,
    MinuteCollector,
    SourceUnavailable,
)
from trading_bot.vision.ledger import read_entries, verify_chain
from trading_bot.vision.prospective import (
    LiveModeRefused,
    ProspectiveConfig,
    ProspectiveSession,
    compare_prefix,
)
from trading_bot.vision.settings import load_vision_config

REPO = Path(__file__).resolve().parents[3]
T0 = 1_700_000_000_000 - (1_700_000_000_000 % (5 * MINUTE_MS))
FIVE = 5 * MINUTE_MS
SYMBOLS = ("BTCUSDT", "ETHUSDT")


class FakeClock:
    def __init__(self, now_ms: int) -> None:
        self.now = int(now_ms)

    def __call__(self) -> int:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += int(float(seconds) * 1000)


def _kline(open_ms: int, price: float) -> list[float]:
    high = price * 1.0008
    low = price * 0.9992
    return [open_ms, price, high, low, price * 1.0001, 5.0]


class SyntheticVenue:
    """A venue with a clock, not a page script: it answers any minute range."""

    name = "synthetic_venue"

    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.first_open_ms = T0
        self.freeze_minutes = False
        self.frozen_last: int | None = None
        self.failures = 0
        self.fetches = 0

    def price(self, symbol: str, open_ms: int) -> float:
        index = (open_ms - self.first_open_ms) // MINUTE_MS
        base = 30_000.0 if symbol == "BTCUSDT" else 2_000.0
        drift = 25.0 if symbol == "BTCUSDT" else 2.0
        return base + drift * math.sin(index / 9.0) + 3.0 * math.sin(index / 2.3)

    def last_closed_open(self) -> int:
        if self.freeze_minutes:
            if self.frozen_last is None:
                self.frozen_last = (self.clock() // MINUTE_MS) * MINUTE_MS - MINUTE_MS
            return self.frozen_last
        return (self.clock() // MINUTE_MS) * MINUTE_MS - MINUTE_MS

    def server_time(self) -> int:
        if self.failures:
            self.failures -= 1
            raise SourceUnavailable("NETWORK", "scripted outage")
        return self.clock()

    def fetch(
        self,
        symbol: str,
        *,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 500,
    ) -> KlinePage:
        self.fetches += 1
        if self.failures:
            self.failures -= 1
            raise SourceUnavailable("NETWORK", "scripted outage")
        last = self.last_closed_open()
        stamps = list(range(self.first_open_ms, last + 1, MINUTE_MS))
        if start_ms is not None:
            stamps = [stamp for stamp in stamps if stamp >= int(start_ms)]
            stamps = stamps[: max(1, limit)]
        else:
            stamps = stamps[-max(1, limit) :]
        return KlinePage(
            symbol=symbol,
            rows=tuple(tuple(_kline(stamp, self.price(symbol, stamp))) for stamp in stamps),
            server_time_ms=self.clock(),
            received_at_ms=self.clock(),
        )


def build_session(
    tmp_path: Path,
    *,
    duration_s: int = 1_500,
    max_cycles: int = 3,
    latency_ms: int = 30_000,
    freeze_after_bootstrap: bool = False,
) -> tuple[ProspectiveSession, FakeClock, SyntheticVenue]:
    clock = FakeClock(T0 + 300 * MINUTE_MS)
    venue = SyntheticVenue(clock)
    out = tmp_path / "session"
    out.mkdir(parents=True, exist_ok=True)
    collector = MinuteCollector(
        source=venue,
        root=out / "market-1m",
        symbols=SYMBOLS,
        local_clock=clock,
        settle_ms=0,
    ).open()
    vision = load_vision_config(env={})
    vision = replace(
        vision,
        lane=replace(vision.lane, timeframe="5m", window_bars=20, decision_every_bars=1),
    )
    settings = load_settings(config_dir=REPO / "config", env_file=None)
    session = ProspectiveSession(
        config=ProspectiveConfig(
            symbols=SYMBOLS,
            timeframe="5m",
            window_bars=20,
            decision_every_bars=1,
            duration_s=duration_s,
            poll_interval_s=15.0,
            settle_ms=0,
            latency_ms=latency_ms,
            warmup_minutes=240,
            max_cycles=max_cycles,
        ),
        out_dir=out,
        vision_config=vision,
        risk_policy=settings.risk,
        root=REPO,
        collector=collector,
        clock=clock,
        sleeper=clock.sleep,
    )
    if freeze_after_bootstrap:
        # Freeze once the warm-up has been read, so the session starts healthy and then
        # watches the feed stop delivering minutes.
        original_bootstrap = collector.bootstrap

        def bootstrap_then_freeze(*args, **kwargs):
            result = original_bootstrap(*args, **kwargs)
            venue.freeze_minutes = True
            return result

        collector.bootstrap = bootstrap_then_freeze  # type: ignore[method-assign]
    return session, clock, venue


def test_a_session_executes_only_after_its_data_closed(tmp_path: Path) -> None:
    session, clock, _venue = build_session(tmp_path)
    summary = session.run()

    assert summary["mode"] == "PAPER"
    assert summary["live_orders"] == 0
    assert summary["cycles_executed"] >= 2
    rows = read_entries(tmp_path / "session" / "STREAM.jsonl")
    kinds = [row["entry"]["kind"] for row in rows]
    assert kinds[0] == "SESSION_START"
    assert kinds[-1] == "SESSION_END"
    cycles = [row["entry"] for row in rows if row["entry"]["kind"] == "CYCLE"]
    assert cycles
    for row in cycles:
        assert row["status"] == "EXECUTED"
        assert row["mode"] == "PAPER"
        assert row["live_orders"] == 0
        assert row["data_time_ms"] <= row["decision_time_ms"]
        assert row["decision_bar_open_ms"] + FIVE == row["data_time_ms"]
        assert row["ledger"]["prefix"]["ok"] is True
        assert row["subbar_entries"] is True
    # The last cycle must describe the data that existed when it ran, not the future.
    assert cycles[-1]["data_time_ms"] <= clock()


def test_decisions_begin_when_the_session_begins_not_in_the_warmup(
    tmp_path: Path,
) -> None:
    session, _clock, _venue = build_session(tmp_path)
    started = session._started_at_ms
    session.run()
    last = read_entries(tmp_path / "session" / "STREAM.jsonl")[-2]["entry"]
    assert last["kind"] == "CYCLE"
    ledger = tmp_path / "session" / last["ledger"]["path"]
    entries = read_entries(ledger)
    decisions = [row["entry"] for row in entries if row["entry"]["kind"] == "DECISION"]
    assert decisions
    assert all(int(row["ts_ms"]) >= int(started) for row in decisions)
    assert verify_chain(ledger)["ok"] is True


def test_a_fill_never_pays_a_price_from_before_its_answer(tmp_path: Path) -> None:
    session, _clock, _venue = build_session(tmp_path)
    session.run()
    rows = read_entries(tmp_path / "session" / "STREAM.jsonl")
    last = [row["entry"] for row in rows if row["entry"]["kind"] == "CYCLE"][-1]
    entries = read_entries(tmp_path / "session" / last["ledger"]["path"])
    fills = [row["entry"] for row in entries if row["entry"]["kind"] == "FILL"]
    assert fills, "the session must produce at least one simulated fill"
    for fill in fills:
        assert int(fill["quote_ts_ms"]) >= int(fill["received_at_ms"])
        assert fill["entry_quote_source"] != "bar_open"
        assert int(fill["entry_bar_range_from_ms"]) == int(fill["quote_ts_ms"])
    summary = json.loads((tmp_path / "session" / "SUMMARY.json").read_text(encoding="utf-8"))
    assert summary["subbar_entries"] is True


def test_a_stalled_feed_produces_blocked_rows_and_no_further_cycle(
    tmp_path: Path,
) -> None:
    session, clock, venue = build_session(tmp_path, duration_s=1_800, max_cycles=5)
    original_progress = session.progress

    def progress(message: str) -> None:
        original_progress(message)
        if message.startswith("cycle 1"):
            # The feed keeps its clock but stops delivering new minutes: freeze the last
            # delivered minute *before* advancing the venue clock.
            venue.frozen_last = venue.last_closed_open()
            venue.freeze_minutes = True
            clock.now += 20 * MINUTE_MS

    session.progress = progress
    summary = session.run()
    assert summary["cycles_executed"] == 1
    rows = read_entries(tmp_path / "session" / "STREAM.jsonl")
    blocked = [row["entry"] for row in rows if row["entry"]["kind"] == "BLOCKED"]
    assert blocked
    assert blocked[0]["reason"] == "DATA_NOT_TRADEABLE"
    assert "STALE" in json.dumps(blocked[0]["detail"])
    assert venue.freeze_minutes is True


def test_live_mode_is_refused_before_any_object_is_built(tmp_path: Path) -> None:
    with pytest.raises(LiveModeRefused, match="PAPER only"):
        ProspectiveConfig(mode="LIVE")
    session, _clock, _venue = build_session(tmp_path)
    # Defence in depth: even a config mutated after construction cannot start a run.
    object.__setattr__(session.config, "mode", "LIVE")
    with pytest.raises(LiveModeRefused):
        session.run()


def test_prefix_comparison_detects_a_rewritten_decision() -> None:
    previous = [
        {"seq": 1, "entry": {"kind": "RUN", "dataset": 48}, "sha256": "x"},
        {"seq": 2, "entry": {"kind": "DECISION", "action": "LONG"}, "sha256": "y"},
        {
            "seq": 3,
            "entry": {"kind": "GUARD_REJECT", "phase": "RUN_END"},
            "sha256": "z",
        },
        {"seq": 4, "entry": {"kind": "RUN_END", "net": -1.0}, "sha256": "w"},
    ]
    current = [
        # The dataset legitimately grew, so the header is allowed to differ.
        {"seq": 1, "entry": {"kind": "RUN", "dataset": 49}, "sha256": "x"},
        {"seq": 2, "entry": {"kind": "DECISION", "action": "LONG"}, "sha256": "y"},
        {"seq": 3, "entry": {"kind": "FILL", "price": 100.0}, "sha256": "f"},
        {"seq": 4, "entry": {"kind": "RUN_END", "net": 1.0}, "sha256": "v"},
    ]
    assert compare_prefix(previous, current)["ok"] is True
    current[1]["entry"] = {"kind": "DECISION", "action": "SHORT"}
    result = compare_prefix(previous, current)
    assert result["ok"] is False
    assert result["reason"] == "PREFIX_DIVERGENCE"
    assert result["first_mismatch_seq"] == 2
