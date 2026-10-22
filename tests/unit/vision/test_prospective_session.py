"""INTEGRATION/RUNTIME — a paper session on a live-shaped feed, without a venue call."""

from __future__ import annotations

import json
import math
import subprocess
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
    RuntimeNotProvable,
    SessionAborted,
    SessionIdentityMismatch,
    compare_prefix,
)
from trading_bot.vision.provenance import SESSION_PATHS
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
    signal_source: str = "legacy_parity",
    window_bars: int = 20,
    decision_every_bars: int = 1,
    root: Path = REPO,
    resume: bool = False,
    out: Path | None = None,
    clock_start_ms: int | None = None,
) -> tuple[ProspectiveSession, FakeClock, SyntheticVenue]:
    clock = FakeClock(clock_start_ms if clock_start_ms is not None else T0 + 300 * MINUTE_MS)
    venue = SyntheticVenue(clock)
    out = out if out is not None else tmp_path / "session"
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
        lane=replace(
            vision.lane,
            timeframe="5m",
            window_bars=window_bars,
            decision_every_bars=decision_every_bars,
        ),
    )
    settings = load_settings(config_dir=REPO / "config", env_file=None)
    session = ProspectiveSession(
        config=ProspectiveConfig(
            symbols=SYMBOLS,
            timeframe="5m",
            window_bars=window_bars,
            decision_every_bars=decision_every_bars,
            duration_s=duration_s,
            poll_interval_s=15.0,
            settle_ms=0,
            latency_ms=latency_ms,
            warmup_minutes=240,
            max_cycles=max_cycles,
            signal_source=signal_source,
        ),
        out_dir=out,
        vision_config=vision,
        risk_policy=settings.risk,
        root=root,
        collector=collector,
        clock=clock,
        sleeper=clock.sleep,
        resume=resume,
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


# ---------------------------------------------------------------------------
# 003J — the signal source is a configurable, opt-in part of the true session
# ---------------------------------------------------------------------------


def test_the_default_source_is_the_legacy_script(tmp_path: Path) -> None:
    session, _clock, _venue = build_session(tmp_path)
    summary = session.run()
    assert summary["signal_source"] == "legacy_parity"
    assert summary["provider"] == "paper-script"
    start = json.loads((tmp_path / "session" / "SESSION_START.json").read_text(encoding="utf-8"))
    assert start["signal_source"] == "legacy_parity"
    assert start["strategy_id"] is None
    cycles = [
        row["entry"]
        for row in read_entries(tmp_path / "session" / "STREAM.jsonl")
        if row["entry"]["kind"] == "CYCLE"
    ]
    decisions = [
        row["entry"]
        for row in read_entries(tmp_path / "session" / cycles[-1]["ledger"]["path"])
        if row["entry"]["kind"] == "DECISION"
    ]
    providers = {row["provider"]["provider"] for row in decisions if "provider" in row}
    assert providers == {"paper-script"}
    # The scripted rotation is untouched: two of every four answers are directional.
    actions = [row["decision"]["action"] for row in decisions if row.get("decision")]
    assert "LONG" in actions and "SHORT" in actions


def test_the_experimental_source_runs_through_the_same_session(tmp_path: Path) -> None:
    session, _clock, _venue = build_session(
        tmp_path, signal_source="strategy_experimental", window_bars=24
    )
    summary = session.run()

    assert summary["signal_source"] == "strategy_experimental"
    assert summary["provider"] == "strategy-signal"
    assert summary["live_orders"] == 0
    assert summary["cycles_executed"] >= 2
    assert (tmp_path / "session" / "cycles" / "cycle-0001" / "SIGNAL_TRACE.jsonl").exists()

    trace: list[dict[str, object]] = []
    for path in sorted((tmp_path / "session" / "cycles").glob("*/SIGNAL_TRACE.jsonl")):
        trace.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
    assert trace
    assert {row["action"] for row in trace} <= {"LONG", "SHORT", "NO_TRADE"}
    assert all(row["strategy_id"] == "ema_crossover" for row in trace)
    assert all(row["quality_status"] in {"PASS", "REJECT"} for row in trace)
    assert all(
        row["max_input_data_time_ms"] is None
        or int(row["max_input_data_time_ms"]) <= int(row["decision_time_ms"])
        for row in trace
    )
    # The decisions the lane recorded name the provider that formed them.
    last = [
        row["entry"]
        for row in read_entries(
            tmp_path / "session" / "STREAM.jsonl"
        )
        if row["entry"]["kind"] == "CYCLE"
    ][-1]
    entries = read_entries(tmp_path / "session" / last["ledger"]["path"])
    providers = {
        row["entry"]["provider"]["provider"]
        for row in entries
        if row["entry"]["kind"] == "DECISION" and "provider" in row["entry"]
    }
    assert providers == {"strategy-signal"}


def test_a_late_answer_fills_once_the_cadence_leaves_it_a_bar(tmp_path: Path) -> None:
    """DEF-003J-08, pinned: the answer arrives after the next open, so it needs a bar.

    With a decision every bar, the newer opinion is formed at the very close that the
    older order needed as its next open, and the order is superseded before that open is
    processed. Every second bar leaves the open free, and the same lane fills it — with
    the quote stamped at or after the answer, never before it.
    """

    session, _clock, _venue = build_session(
        tmp_path, latency_ms=30_000, max_cycles=4, decision_every_bars=2
    )
    summary = session.run()
    assert summary["live_orders"] == 0
    assert summary["fills"] >= 1

    fills: list[dict[str, object]] = []
    for path in sorted((tmp_path / "session" / "cycles").glob("*/ledger.jsonl")):
        fills.extend(
            row["entry"]
            for row in read_entries(path)
            if row["entry"]["kind"] == "FILL"
        )
    assert fills
    for fill in fills:
        assert int(fill["quote_ts_ms"]) >= int(fill["received_at_ms"])
        assert int(fill["opinion_age_ms"]) >= 0


def test_an_unknown_signal_source_is_refused_by_the_config() -> None:
    with pytest.raises(ValueError, match="unknown signal source"):
        ProspectiveConfig(signal_source="parity_fallback")


def test_the_experimental_source_refuses_a_window_the_family_cannot_read() -> None:
    with pytest.raises(ValueError, match="window_bars"):
        ProspectiveConfig(signal_source="strategy_experimental", window_bars=20)


# ---------------------------------------------------------------------------
# RFC-DEF-RUN-019 / WP-04 — a live session has to say which bytes decided
# ---------------------------------------------------------------------------

LATER_MS = T0 + 305 * MINUTE_MS


def git_run(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    )
    return completed.stdout.strip()


def fake_runtime_root(tmp_path: Path, *, commit: bool = True) -> Path:
    """A repository holding every runtime path, so a session can be pinned against it.

    The files are placeholders: ``capture_session`` hashes bytes and asks Git, it never
    imports what it is hashing. That keeps the fail-closed tests independent of the code
    under test.
    """

    root = tmp_path / "fake-root"
    for relative in SESSION_PATHS:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"# {relative}\n", encoding="utf-8", newline="\n")
    if not commit:
        return root
    git_run(root, "init", "-q")
    git_run(root, "add", "-A")
    git_run(
        root,
        "-c",
        "user.email=agent@example.invalid",
        "-c",
        "user.name=agent",
        "commit",
        "-q",
        "-m",
        "runtime",
    )
    return root


def stream_rows(out: Path) -> list[dict[str, object]]:
    return [row["entry"] for row in read_entries(out / "STREAM.jsonl")]


def test_the_session_records_its_identity_before_the_first_decision(tmp_path: Path) -> None:
    root = fake_runtime_root(tmp_path)
    session, _clock, _venue = build_session(tmp_path, max_cycles=2, root=root)
    summary = session.run()

    out = tmp_path / "session"
    entries = stream_rows(out)
    kinds = [entry["kind"] for entry in entries]
    assert kinds.index("SESSION_PROVENANCE") < kinds.index("CYCLE")
    block = entries[kinds.index("SESSION_PROVENANCE")]
    assert block["code"]["commit"] == git_run(root, "rev-parse", "HEAD")
    assert block["mode"] == "PAPER" and block["live_enabled"] is False
    assert block["provider"]["data"]["name"] == "synthetic_venue"
    assert block["config"]["payload"]["window_bars"] == 20
    assert len(block["runtime"]["sha256"]) == len(SESSION_PATHS)
    assert block["unavailable_reasons"] == []

    cycles = [entry for entry in entries if entry["kind"] == "CYCLE"]
    assert cycles
    assert {entry["provenance"]["pinned_identity"] for entry in cycles} == {
        block["pinned_identity"]
    }
    assert {entry["provenance"]["runtime_digest"] for entry in cycles} == {
        block["runtime"]["digest"]
    }
    assert summary["provenance"]["session_id"] == block["session_id"]
    assert summary["provenance"]["pinned_identity"] == block["pinned_identity"]
    assert (out / "SESSION_PROVENANCE.json").is_file()
    assert (out / "provenance" / f"session-{block['session_id']}.json").is_file()


def test_a_dirty_runtime_refuses_before_the_venue_is_called(tmp_path: Path) -> None:
    root = fake_runtime_root(tmp_path)
    (root / "src/trading_bot/risk/manager.py").write_text(
        "# edited while a session could have started\n", encoding="utf-8", newline="\n"
    )
    session, _clock, venue = build_session(tmp_path, root=root)

    with pytest.raises(RuntimeNotProvable) as excinfo:
        session.run()

    assert excinfo.value.reasons == ["RUNTIME_PATHS_DIRTY"]
    assert venue.fetches == 0, "a refused session must not have read the feed"
    assert not (tmp_path / "session" / "STREAM.jsonl").exists()


def test_a_root_without_git_refuses_to_start(tmp_path: Path) -> None:
    root = fake_runtime_root(tmp_path, commit=False)
    session, _clock, venue = build_session(tmp_path, root=root)

    with pytest.raises(RuntimeNotProvable) as excinfo:
        session.run()

    assert "NOT_A_REPOSITORY" in excinfo.value.reasons
    assert venue.fetches == 0


def test_a_shared_checkout_with_unrelated_edits_runs_and_discloses_them(tmp_path: Path) -> None:
    root = fake_runtime_root(tmp_path)
    (root / "notes-from-another-agent.md").write_text("in progress\n", encoding="utf-8")
    session, _clock, _venue = build_session(tmp_path, max_cycles=1, root=root)

    summary = session.run()

    assert summary["cycles_executed"] == 1
    block = json.loads((tmp_path / "session" / "SESSION_PROVENANCE.json").read_text("utf-8"))
    worktree = block["code"]["worktree"]
    assert worktree["runtime_dirty"] == []
    assert worktree["fully_clean"] is False
    assert worktree["dirty_outside_runtime_total"] == 1
    assert block["unavailable_reasons"] == []


def test_a_runtime_change_mid_session_stops_the_next_decision(tmp_path: Path) -> None:
    root = fake_runtime_root(tmp_path)
    session, clock, _venue = build_session(
        tmp_path, max_cycles=5, duration_s=3_600, root=root
    )
    untouched = session.progress

    def progress(message: str) -> None:
        untouched(message)
        if message.startswith("cycle 1"):
            (root / "src/trading_bot/vision/lane.py").write_text(
                "# changed under the running session\n", encoding="utf-8", newline="\n"
            )
            clock.now += 10 * MINUTE_MS

    session.progress = progress
    summary = session.run()

    assert summary["cycles_executed"] == 1
    assert summary["runtime_stable"] is False
    assert summary["runtime_drift"] == ["src/trading_bot/vision/lane.py"]
    entries = stream_rows(tmp_path / "session")
    drift = [e for e in entries if e.get("reason") == "RUNTIME_DRIFT"]
    assert len(drift) == 1
    assert drift[0]["detail"]["changed_paths"] == ["src/trading_bot/vision/lane.py"]
    assert "RUNTIME_DRIFT" in summary["blocked_reasons"]
    kinds = [e["kind"] for e in entries]
    assert kinds.index("BLOCKED") < kinds.index("SESSION_END")


def test_a_resume_continues_the_chain_after_proving_the_identity(tmp_path: Path) -> None:
    root = fake_runtime_root(tmp_path)
    out = tmp_path / "session"
    first, _clock, _venue = build_session(tmp_path, max_cycles=1, root=root)
    first_summary = first.run()

    second, _clock2, _venue2 = build_session(
        tmp_path, max_cycles=1, root=root, resume=True, out=out, clock_start_ms=LATER_MS
    )
    second_summary = second.run()

    assert second_summary["provenance"]["resumed"] is True
    assert second_summary["provenance"]["session_id"] != first_summary["provenance"]["session_id"]
    assert second_summary["provenance"]["chain"][0]["session_id"] == (
        first_summary["provenance"]["session_id"]
    )
    assert second_summary["provenance"]["pinned_identity"] == (
        first_summary["provenance"]["pinned_identity"]
    )
    entries = stream_rows(out)
    starts = [entry for entry in entries if entry["kind"] == "SESSION_START"]
    assert len(starts) == 2
    assert [entry["cycle"] for entry in entries if entry["kind"] == "CYCLE"] == [1, 2]
    assert all(
        entry["status"] == "EXECUTED" for entry in entries if entry["kind"] == "CYCLE"
    )
    assert [item["session_id"] for item in second_summary["provenance"]["chain"]] == [
        first_summary["provenance"]["session_id"]
    ]


def test_a_resume_refuses_when_the_code_moved(tmp_path: Path) -> None:
    root = fake_runtime_root(tmp_path)
    out = tmp_path / "session"
    build_session(tmp_path, max_cycles=1, root=root)[0].run()

    target = root / "src/trading_bot/risk/manager.py"
    target.write_text("# a new decision rule\n", encoding="utf-8", newline="\n")
    git_run(root, "add", "-A")
    git_run(
        root,
        "-c",
        "user.email=agent@example.invalid",
        "-c",
        "user.name=agent",
        "commit",
        "-q",
        "-m",
        "change the rule",
    )

    session, _clock, _venue = build_session(
        tmp_path, root=root, resume=True, out=out, clock_start_ms=LATER_MS
    )
    with pytest.raises(SessionIdentityMismatch) as excinfo:
        session.run()

    assert "COMMIT_CHANGED" in excinfo.value.reasons
    assert "RUNTIME_DRIFT" in excinfo.value.reasons
    assert excinfo.value.detail["changed_runtime_paths"] == [
        "src/trading_bot/risk/manager.py"
    ]


def test_a_resume_refuses_a_different_configuration(tmp_path: Path) -> None:
    root = fake_runtime_root(tmp_path)
    out = tmp_path / "session"
    build_session(tmp_path, max_cycles=1, root=root)[0].run()

    session, _clock, _venue = build_session(
        tmp_path,
        max_cycles=1,
        window_bars=24,
        root=root,
        resume=True,
        out=out,
        clock_start_ms=LATER_MS,
    )
    with pytest.raises(SessionIdentityMismatch) as excinfo:
        session.run()

    assert excinfo.value.reasons == ["CONFIG_CHANGED"]


def test_a_resume_without_a_pinned_session_is_refused(tmp_path: Path) -> None:
    root = fake_runtime_root(tmp_path)
    session, _clock, venue = build_session(tmp_path, root=root, resume=True)

    with pytest.raises(SessionAborted, match="RESUME_WITHOUT_PROVENANCE"):
        session.run()

    assert venue.fetches == 0
