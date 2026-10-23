"""CODEX — a killed session must be resumable without deleting files by hand.

Measured on the host: ``Stop-Process -Force`` in the middle of a live 3-symbol session
left ``STREAM.jsonl.lock`` and one ``<SYMBOL>.jsonl.lock`` per symbol behind. The next
run did not resume and did not refuse with a code: it died with a traceback out of
``MinuteStore.open`` (exit 1), which is neither a decision nor evidence. A loop that can
only be restarted by hand is not a sustained loop.

The policy under test is narrow on purpose: reclaim **only** a lock that carries an
integer pid and whose process is provably gone. A lock held by a live process, or one
whose owner cannot be read, is refused with a name — deleting an unattributable lock could
corrupt a writer that is still running.

The venue here is deliberately a second, simpler fake than the one in
``test_prospective_session``: this file is about scaffolding, and sharing the model would
make a fixture bug look like a session bug.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from trading_bot.config.settings import load_settings
from trading_bot.market_data.minute_collector import MINUTE_MS, KlinePage
from trading_bot.ops import windowless
from trading_bot.vision import prospective
from trading_bot.vision.ledger import read_entries, verify_chain
from trading_bot.vision.prospective import (
    RUNTIME_PATHS,
    ProspectiveConfig,
    ProspectiveSession,
    SessionAborted,
    reclaim_stale_lock,
)
from trading_bot.vision.provenance import SESSION_PATHS
from trading_bot.vision.settings import load_vision_config

REPO = Path(__file__).resolve().parents[3]
T0 = 1_700_000_000_000 - (1_700_000_000_000 % (5 * MINUTE_MS))
SYMBOLS = ("BTCUSDT", "ETHUSDT")


class _Clock:
    def __init__(self, now_ms: int) -> None:
        self.now = int(now_ms)

    def __call__(self) -> int:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += int(float(seconds) * 1000)


class _Venue:
    """Minute bars that exist for every closed minute, priced by index and not by luck."""

    name = "lock_recovery_venue"

    def __init__(self, clock: _Clock) -> None:
        self.clock = clock
        self.first_open_ms = T0

    def _price(self, symbol: str, open_ms: int) -> float:
        index = (open_ms - self.first_open_ms) // MINUTE_MS
        base = 1000.0 if symbol == "BTCUSDT" else 100.0
        return base * (1.0 + 0.0002 * index)

    def server_time(self) -> int:
        return self.clock()

    def fetch(
        self,
        symbol: str,
        *,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 500,
    ) -> KlinePage:
        last = (self.clock() // MINUTE_MS) * MINUTE_MS - MINUTE_MS
        stamps = list(range(self.first_open_ms, last + 1, MINUTE_MS))
        if start_ms is not None:
            stamps = [stamp for stamp in stamps if stamp >= int(start_ms)][: max(1, limit)]
        else:
            stamps = stamps[-max(1, limit) :]
        rows = []
        for stamp in stamps:
            price = self._price(symbol, stamp)
            rows.append((stamp, price, price * 1.0008, price * 0.9992, price * 1.0001, 5.0))
        return KlinePage(
            symbol=symbol,
            rows=tuple(rows),
            server_time_ms=self.clock(),
            received_at_ms=self.clock(),
        )


def _dead_pid() -> int:
    """A pid that existed and no longer does: spawned, reaped, then asked again."""

    #: ``windowless.spawn`` is this repository's only launcher: a child that can draw a
    #: console is an ops defect the audit flags.
    proc = windowless.spawn([sys.executable, "-c", "pass"], cwd=str(REPO))
    proc.wait()
    return int(proc.pid)


def _lock(path: Path, pid: int | str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(pid), encoding="utf-8")
    return path


def _dead_pid_or_skip() -> int:
    pid = _dead_pid()
    if prospective._pid_alive(pid):  # pragma: no cover - pid reuse on a busy host
        pytest.skip("the reaped pid was reused before it could be probed")
    return pid


def test_a_lock_whose_owner_is_gone_is_reclaimed_with_its_pid_recorded(tmp_path: Path) -> None:
    pid = _dead_pid_or_skip()
    path = _lock(tmp_path / "STREAM.jsonl.lock", pid)

    record = reclaim_stale_lock(path)

    assert record is not None
    assert record["lock"] == "STREAM.jsonl.lock"
    assert record["pid"] == pid
    assert record["reason"] == "OWNER_PROCESS_DEAD"
    #: The fence is part of the evidence: the reclaimed lock was taken over once, so a stale
    #: writer (`ops.single_writer`) fails its next ``assert_held`` instead of writing on.
    assert record["fence"] >= 1
    assert not path.exists()


def test_a_lock_held_by_a_live_process_is_refused_and_left_alone(tmp_path: Path) -> None:
    live = _lock(tmp_path / "ETHUSDT.jsonl.lock", os.getpid())

    with pytest.raises(SessionAborted) as excinfo:
        reclaim_stale_lock(live)
    assert "RUNTIME_LOCK_HELD" in str(excinfo.value)
    assert live.exists()


def test_a_lock_without_an_owner_is_refused_rather_than_deleted(tmp_path: Path) -> None:
    path = _lock(tmp_path / "SOLUSDT.jsonl.lock", "not-a-pid")

    with pytest.raises(SessionAborted) as excinfo:
        reclaim_stale_lock(path)
    assert "RUNTIME_LOCK_UNATTRIBUTED" in str(excinfo.value)
    assert path.exists(), "a lock we cannot attribute is never removed"


def test_no_lock_is_not_an_error(tmp_path: Path) -> None:
    assert reclaim_stale_lock(tmp_path / "absent.lock") is None


def _fake_root(tmp_path: Path) -> Path:
    """A committed repository holding every runtime path.

    The session refuses to start when the runtime cannot be identified, and this file's
    own edits make the real checkout dirty by construction. Pinning the session against
    placeholder bytes keeps the test about locks instead of about the working tree.
    """

    root = tmp_path / "fake-root"
    for relative in sorted(set(SESSION_PATHS) | set(RUNTIME_PATHS)):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"# {relative}\n", encoding="utf-8", newline="\n")
    for argv in (
        ("init", "-q"),
        ("add", "-A"),
        (
            "-c",
            "user.email=agent@example.invalid",
            "-c",
            "user.name=agent",
            "commit",
            "-q",
            "-m",
            "runtime",
        ),
    ):
        subprocess.run(
            ["git", "-C", str(root), *argv],
            check=True,
            capture_output=True,
            text=True,
        )
    return root


def _build(tmp_path: Path, *, out: Path, clock: _Clock, root: Path, max_cycles: int = 2):
    vision = load_vision_config(env={})
    vision = replace(
        vision,
        lane=replace(vision.lane, timeframe="5m", window_bars=20, decision_every_bars=1),
    )
    settings = load_settings(config_dir=REPO / "config", env_file=None)
    return ProspectiveSession(
        config=ProspectiveConfig(
            symbols=SYMBOLS,
            timeframe="5m",
            window_bars=20,
            duration_s=1_500,
            poll_interval_s=15.0,
            settle_ms=0,
            latency_ms=30_000,
            warmup_minutes=240,
            max_cycles=max_cycles,
        ),
        out_dir=out,
        vision_config=vision,
        risk_policy=settings.risk,
        root=root,
        #: the production path: the session builds and opens its own collector, which is
        #: exactly where a stale lock used to kill the process with a traceback.
        collector=None,
        clock=clock,
        sleeper=lambda seconds: clock.sleep(seconds),
    )


def test_a_crashed_session_resumes_by_reclaiming_its_locks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "session"
    pid = _dead_pid_or_skip()
    expected = ["STREAM.jsonl.lock", *(f"{symbol}.jsonl.lock" for symbol in SYMBOLS)]
    _lock(out / "STREAM.jsonl.lock", pid)
    for symbol in SYMBOLS:
        _lock(out / "market-1m" / f"{symbol}.jsonl.lock", pid)

    clock = _Clock(T0 + 300 * MINUTE_MS)
    venue = _Venue(clock)
    monkeypatch.setattr(prospective, "_default_source", lambda: venue)

    summary = _build(tmp_path, out=out, clock=clock, root=_fake_root(tmp_path), max_cycles=2).run()

    assert summary["cycles_executed"] >= 1
    assert summary["mode"] == "PAPER"
    assert summary["live_orders"] == 0
    assert summary["runtime_stable"] is True
    rows = [row["entry"] for row in read_entries(out / "STREAM.jsonl")]
    reclaimed = [row for row in rows if row["kind"] == "LOCK_RECLAIMED"]
    assert len(reclaimed) == 1
    assert {item["lock"] for item in reclaimed[0]["locks"]} == set(expected)
    assert all(item["reason"] == "OWNER_PROCESS_DEAD" for item in reclaimed[0]["locks"])
    kinds = [row["kind"] for row in rows]
    assert kinds.index("SESSION_PROVENANCE") < kinds.index("LOCK_RECLAIMED")
    assert kinds.index("LOCK_RECLAIMED") < kinds.index("CYCLE")
    assert verify_chain(out / "STREAM.jsonl")["ok"] is True
    written = json.loads((out / "LOCKS_RECLAIMED.json").read_text(encoding="utf-8"))
    assert {item["pid"] for item in written["locks"]} == {pid}
    assert "ORDER" not in {row["kind"] for row in rows}
