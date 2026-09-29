"""§2-§4 — the capture exit contract, and the supervisor that reads it.

The defect these tests close: a capture whose writer had died recorded
``integrity.failures`` in its manifest, sealed what it could, and exited **0**.
An operator reading exit codes, and the supervisor that restarts on them, both
concluded the run had completed.

So the claims under test are:

* a terminal persistence failure is recorded as ``FAILED`` in the manifest **and**
  as a non-zero exit code, through one classifier rather than two opinions;
* a clean duration, an operator stop and a disk-guard stop are all exit 0, and
  they stay distinguishable in the manifest;
* the supervisor sees a non-zero collector exit as a crash (restart, backoff,
  eventually FAILED) and never as a completion;
* PAPER is not touched by a collector failure — the isolation is the point;
* a child that has to be killed at stop time is a failure, not a tidy stop.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from trading_bot.autonomous.supervisor import (
    ManagedProcess,
    ProcessState,
    Supervisor,
)
from trading_bot.research.forward.collector import CollectorConfig, ForwardCollector
from trading_bot.research.forward.contract import (
    EventType,
    Market,
    RawEvent,
    SequenceRange,
    Transport,
)
from trading_bot.research.forward.outcome import (
    EXIT_COMPLETE,
    EXIT_FAILED,
    FAILURE_BOOK,
    FAILURE_STORAGE,
    FAILURE_TIMESTAMP,
    CaptureOutcome,
    CaptureStatus,
    classify_capture,
    exit_code_for_status,
)
from trading_bot.research.forward.storage import (
    RunManifest,
    manifest_outcome,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_script(name: str) -> Any:
    path = _REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _manifest(**overrides: Any) -> RunManifest:
    base: dict[str, Any] = {
        "run_id": "exit-contract",
        "collector_version": "x",
        "contract_version": "FORWARD-DATA-CONTRACT-V1",
        "schema_version": "forward-event-v1",
        "provider": "binance-public",
        "market": "spot",
        "commit": "0" * 40,
        "symbols": ["BTCUSDT"],
        "markets": ["spot"],
        "started_at": "2026-09-29T00:00:00+00:00",
        "ended_at": "2026-09-29T00:10:00+00:00",
        "duration_seconds": 600.0,
        "rotation_seconds": 60,
        "continuity": "CONTINUOUS",
    }
    return RunManifest(**{**base, **overrides})


# ----------------------------------------------------------- the policy table (§2)


@pytest.mark.parametrize(
    ("stop_reason", "expected_status", "expected_code"),
    [
        ("duration reached", CaptureStatus.COMPLETE, EXIT_COMPLETE),
        ("stop file", CaptureStatus.CONTROLLED_STOP, EXIT_COMPLETE),
        ("signal", CaptureStatus.CONTROLLED_STOP, EXIT_COMPLETE),
        ("disk budget", CaptureStatus.CONTROLLED_STOP, EXIT_COMPLETE),
        ("disk guard", CaptureStatus.CONTROLLED_STOP, EXIT_COMPLETE),
    ],
)
def test_every_clean_exit_is_code_zero_and_still_distinguishable(
    stop_reason: str, expected_status: CaptureStatus, expected_code: int
) -> None:
    outcome = classify_capture(stop_reason=stop_reason)
    assert outcome.status is expected_status
    assert outcome.exit_code == expected_code
    # The reason survives: "it ran its two hours" and "someone stopped it" are
    # different findings even though both exit 0.
    assert outcome.stop_reason == stop_reason


@pytest.mark.parametrize(
    ("kwargs", "kind"),
    [
        ({"fatal_kind": FAILURE_STORAGE, "fatal_reason": "ENOSPC"}, FAILURE_STORAGE),
        ({"clock_violations": 3}, FAILURE_TIMESTAMP),
        ({"book_failed_streams": ("perp/BTCUSDT",)}, FAILURE_BOOK),
    ],
)
def test_a_terminal_failure_is_never_code_zero(kwargs: dict[str, Any], kind: str) -> None:
    outcome = classify_capture(stop_reason="storage failure", **kwargs)
    assert outcome.status is CaptureStatus.FAILED
    assert outcome.kind == kind
    assert outcome.exit_code == EXIT_FAILED
    assert outcome.exit_code != 0
    assert outcome.failed


def test_the_worst_failure_names_the_run() -> None:
    """A run that lost its writer and a book is reported as the writer failure."""
    outcome = classify_capture(
        stop_reason="storage failure",
        fatal_kind=FAILURE_STORAGE,
        fatal_reason="no space left on device",
        clock_violations=1,
        book_failed_streams=("perp/BTCUSDT",),
    )
    assert outcome.kind == FAILURE_STORAGE
    assert "no space left on device" in (outcome.reason or "")


def test_an_undeclared_stop_reason_is_not_promoted_to_complete() -> None:
    outcome = classify_capture(stop_reason="something nobody declared")
    assert outcome.status is CaptureStatus.CONTROLLED_STOP
    assert outcome.exit_code == EXIT_COMPLETE
    assert "unrecognised" in (outcome.reason or "")


def test_exit_codes_come_from_the_status_only() -> None:
    assert exit_code_for_status("COMPLETE") == 0
    assert exit_code_for_status("CONTROLLED_STOP") == 0
    assert exit_code_for_status("FAILED") == 2
    assert CaptureOutcome(status=CaptureStatus.FAILED, kind=FAILURE_STORAGE).exit_code == 2


# ------------------------------------------------- manifest is the same verdict (§2)


def test_the_manifest_carries_the_verdict_and_the_exit_code() -> None:
    failed = _manifest(
        status="FAILED",
        failure_kind=FAILURE_STORAGE,
        failure_reason="STORAGE_WRITE_FAILURE: OSError: ENOSPC",
        stop_reason="storage failure",
    )
    payload = failed.as_dict()
    assert payload["status"] == "FAILED"
    assert payload["exit_code"] == EXIT_FAILED
    assert failed.exit_code == EXIT_FAILED
    assert failed.outcome().kind == FAILURE_STORAGE

    clean = _manifest(stop_reason="duration reached")
    assert clean.as_dict()["status"] == "COMPLETE"
    assert clean.exit_code == EXIT_COMPLETE


def test_a_manifest_written_before_the_contract_still_reports_its_failure() -> None:
    """§52 — the verifier reads old artifacts through the same policy."""
    legacy = {
        "integrity": {"failures": "storage failure: no space left on device"},
        "stop_reason": "storage failure",
        "book_health": {},
    }
    outcome = manifest_outcome(legacy)
    assert outcome.status is CaptureStatus.FAILED
    assert outcome.exit_code == EXIT_FAILED

    legacy_clean = {"integrity": {"failures": None}, "stop_reason": "stop file"}
    assert manifest_outcome(legacy_clean).exit_code == EXIT_COMPLETE


# ------------------------------------------- the writer really fails and says so


class _FailingWriter:
    """A writer that refuses every append: the controlled write failure (§4)."""

    total_bytes = 0
    total_rows = 0

    def __init__(self, reason: str = "No space left on device") -> None:
        self.reason = reason
        self.attempts = 0

    def write(self, _event: RawEvent) -> str:
        self.attempts += 1
        raise OSError(self.reason)

    def rotate(self, _now_ms: int) -> None:
        raise OSError(self.reason)

    def close(self) -> None:
        return None

    def flush(self) -> None:
        return None

    def fingerprints(self) -> list[Any]:
        return []


def _collector(tmp_path: Path, **overrides: Any) -> ForwardCollector:
    options: dict[str, Any] = {
        "root": tmp_path,
        "symbols": ("BTCUSDT",),
        "markets": (Market.SPOT,),
        "keep_raw": False,
        "rotation_seconds": 60,
        "stale_after_ms": 10**15,
    }
    options.update(overrides)
    return ForwardCollector(CollectorConfig(**options))


def _trade(ts_ms: int = 1_800_000_000_000, agg_id: int = 1) -> RawEvent:
    return RawEvent(
        event_type=EventType.AGG_TRADE,
        symbol="BTCUSDT",
        market=Market.SPOT,
        stream="btcusdt@aggTrade",
        transport=Transport.WS,
        run_id="exit-contract",
        exchange_event_id=str(agg_id),
        exchange_event_time=ts_ms,
        receive_time=ts_ms + 25,
        process_time=ts_ms + 26,
        sequence=SequenceRange(first=agg_id, last=agg_id),
        price="100.5",
        quantity="2",
        aggressor_side="buy",
    )


def test_a_write_failure_is_recorded_as_terminal_and_stops_the_run(tmp_path: Path) -> None:
    collector = _collector(tmp_path / "capture")
    writer = _FailingWriter()
    collector.writer = writer  # type: ignore[assignment]

    collector._write(_trade())

    assert writer.attempts >= 1
    assert collector.write_failures == 1
    assert collector._fatal_kind == FAILURE_STORAGE
    assert "No space left on device" in (collector._fatal or "")
    # The run is asked to stop, so it finalises and writes a manifest instead of
    # becoming a process that died silently mid-append.
    assert collector.stop_reason == "storage failure"
    assert collector._evaluate_state(collector._started_ms + 1_000) == "FAILED"


def test_the_manifest_of_a_failed_capture_says_failed_and_the_process_must_fail(
    tmp_path: Path,
) -> None:
    root = tmp_path / "capture"
    collector = _collector(root)
    collector.writer = _FailingWriter()  # type: ignore[assignment]
    collector._write(_trade())
    collector.writer = _FailingWriter()  # type: ignore[assignment]

    manifest = collector.finalise()

    assert manifest.status == CaptureStatus.FAILED.value
    assert manifest.failure_kind == FAILURE_STORAGE
    assert manifest.exit_code == EXIT_FAILED
    # And it is on disk, because a verdict nobody can read is not a verdict.
    path = root / "manifest" / f"{collector.run_id}.json"
    assert path.exists()
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["status"] == "FAILED"
    assert stored["failure_kind"] == FAILURE_STORAGE
    assert stored["exit_code"] == EXIT_FAILED
    assert stored["integrity"]["write_failures"] == 1


def test_a_clean_capture_still_exits_zero(tmp_path: Path) -> None:
    """The contract must not turn healthy captures into failures."""
    collector = _collector(tmp_path / "capture")
    collector._write(_trade())
    collector.stop("stop file")
    manifest = collector.finalise()
    assert manifest.status == CaptureStatus.CONTROLLED_STOP.value
    assert manifest.exit_code == EXIT_COMPLETE


def test_the_min_free_guard_ends_cleanly_before_the_volume_fills(tmp_path: Path) -> None:
    """§20 — the last barrier: the guard stops, it does not fail."""
    collector = _collector(
        tmp_path / "capture",
        min_free_bytes=10**18,  # nothing is ever this free
        maintenance_seconds=0.01,
    )

    async def scenario() -> None:
        await collector._maintenance_loop()

    asyncio.run(scenario())
    assert collector.stopped_on_min_free is True
    assert collector.stop_reason == "disk guard"
    assert collector._fatal is None
    manifest = collector.finalise()
    assert manifest.status == CaptureStatus.CONTROLLED_STOP.value
    assert manifest.exit_code == EXIT_COMPLETE
    assert manifest.stopped_on_min_free is True


# ------------------------------------------------------------- the CLI exit codes


@pytest.fixture()
def collector_cli() -> Any:
    return _load_script("forward_collector")


def test_the_cli_exits_non_zero_when_the_manifest_records_a_failure(
    collector_cli: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _FakeCollector:
        run_id = "exit-contract"
        root = Path("unused")
        stop_reason = "storage failure"

        def __init__(self, _config: Any) -> None: ...

        async def run(self) -> RunManifest:
            return _manifest(
                status="FAILED",
                failure_kind=FAILURE_STORAGE,
                failure_reason="OSError: ENOSPC",
                stop_reason="storage failure",
            )

    monkeypatch.setattr(collector_cli, "ForwardCollector", _FakeCollector)
    code = collector_cli.main(["--mode", "run", "--symbols", "BTCUSDT"])
    assert code == EXIT_FAILED


def test_the_cli_exits_non_zero_when_no_manifest_can_be_written(
    collector_cli: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class _FakeCollector:
        run_id = "exit-contract"
        root = Path("unused")
        stop_reason = None

        def __init__(self, _config: Any) -> None: ...

        async def run(self) -> RunManifest:
            raise OSError("No space left on device")

    monkeypatch.setattr(collector_cli, "ForwardCollector", _FakeCollector)
    code = collector_cli.main(["--mode", "run", "--symbols", "BTCUSDT"])
    assert code == EXIT_FAILED
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["status"] == "FAILED"
    assert payload["failure_kind"] == "MANIFEST_FAILURE"
    assert payload["exit_code"] == EXIT_FAILED


def test_the_cli_exits_zero_for_a_controlled_stop(
    collector_cli: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _FakeCollector:
        run_id = "exit-contract"
        root = Path("unused")
        stop_reason = "stop file"

        def __init__(self, _config: Any) -> None: ...

        async def run(self) -> RunManifest:
            return _manifest(status="CONTROLLED_STOP", stop_reason="stop file")

    monkeypatch.setattr(collector_cli, "ForwardCollector", _FakeCollector)
    assert collector_cli.main(["--mode", "run", "--symbols", "BTCUSDT"]) == EXIT_COMPLETE


def test_the_data_root_flag_moves_everything_the_capture_writes(collector_cli: Any, tmp_path: Path) -> None:
    """§16 — a capture can be pointed at another volume without moving code."""
    args = collector_cli.build_parser().parse_args(
        ["--mode", "run", "--out", "reports/ignored", "--data-root", str(tmp_path / "elsewhere")]
    )
    config = collector_cli._config_from_args(args)
    assert config.root == tmp_path / "elsewhere"

    args = collector_cli.build_parser().parse_args(["--mode", "run", "--out", "reports/kept"])
    assert collector_cli._config_from_args(args).root == Path("reports/kept")


# ------------------------------------------------ the supervisor reads the verdict


def _spec(
    name: str,
    code: str,
    *,
    critical: bool = True,
    stop_file: Path | None = None,
    max_restarts: int = 3,
    restart_on_exit: bool = True,
) -> ManagedProcess:
    return ManagedProcess(
        name=name,
        command=[sys.executable, "-c", code],
        cwd=Path.cwd(),
        critical=critical,
        max_restarts=max_restarts,
        crash_loop_window_seconds=900.0,
        backoff_seconds=(0.05, 0.05, 0.05),
        restart_on_exit=restart_on_exit,
        stop_file=stop_file,
    )


#: The collector's own failure exit code, and a healthy long-lived PAPER loop.
FAILED_COLLECTOR = "raise SystemExit(2)"
PAPER_ALIVE = "import time; time.sleep(60)"


def test_a_non_zero_collector_exit_is_a_crash_and_paper_survives(tmp_path: Path) -> None:
    """§3/§26 — a failed capture is restarted, and never touches PAPER."""
    supervisor = Supervisor.build(
        tmp_path,
        [
            _spec("paper", PAPER_ALIVE),
            _spec("collector", FAILED_COLLECTOR, max_restarts=1),
        ],
        heartbeat_seconds=0.05,
    )
    try:
        supervisor.start_all()
        events: list[dict[str, Any]] = []
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline:
            events.extend(supervisor.poll_once())
            if supervisor.get("collector").state is ProcessState.FAILED:
                break
            time.sleep(0.05)

        exits = [event for event in events if event["event"] == "EXIT"]
        assert exits and exits[0]["process"] == "collector"
        assert exits[0]["outcome"] == "FAILED"
        assert exits[0]["exit_code"] == 2
        assert any(event["event"] == "RESTART_SCHEDULED" for event in events)
        assert supervisor.get("collector").state is ProcessState.FAILED
        # PAPER never noticed: separate process, separate failure domain.
        assert supervisor.get("paper").state is ProcessState.RUNNING
        status = supervisor.status()
        assert status["processes"]["paper"]["state"] == ProcessState.RUNNING.value
    finally:
        supervisor.stop_all()


def test_a_zero_exit_completion_is_not_reported_as_a_failure(tmp_path: Path) -> None:
    supervisor = Supervisor.build(
        tmp_path,
        [_spec("paper", "import sys; sys.exit(0)", restart_on_exit=False)],
        heartbeat_seconds=0.05,
    )
    supervisor.start_all()
    events: list[dict[str, Any]] = []
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline and not events:
        events.extend(supervisor.poll_once())
        time.sleep(0.05)
    assert events[0]["event"] == "EXIT"
    assert events[0]["outcome"] == "COMPLETED"
    assert supervisor.get("paper").state is ProcessState.STOPPED


# ------------------------------------------------------------ a stop is still a finding


def test_a_child_that_finalises_on_stop_is_reported_clean(tmp_path: Path) -> None:
    stop_file = tmp_path / "STOP"
    sealed = tmp_path / "sealed.txt"
    code = (
        "import pathlib, sys, time;"
        " stop = pathlib.Path(sys.argv[1]); out = pathlib.Path(sys.argv[2]);"
        "\nwhile not stop.exists():\n    time.sleep(0.05)\n"
        "out.write_text('sealed=1\\n', encoding='utf-8'); sys.exit(0)"
    )
    supervisor = Supervisor.build(
        tmp_path,
        [
            ManagedProcess(
                name="collector",
                command=[sys.executable, "-c", code, str(stop_file), str(sealed)],
                cwd=Path.cwd(),
                stop_file=stop_file,
            )
        ],
    )
    supervisor.start_all()
    status = supervisor.stop_all(grace_seconds=15.0)
    report = status["stop_report"]
    assert sealed.exists()
    assert report["verdict"] == "CLEAN"
    assert report["escalated"] == []
    assert report["failed_children"] == []
    assert report["exit_codes"]["collector"] == 0


def test_a_child_that_fails_while_being_stopped_is_reported_failed(tmp_path: Path) -> None:
    """A stop must not launder a failed child into a clean shutdown (§57)."""
    stop_file = tmp_path / "STOP"
    code = (
        "import pathlib, sys, time;"
        " stop = pathlib.Path(sys.argv[1]);"
        "\nwhile not stop.exists():\n    time.sleep(0.05)\n"
        "sys.exit(2)"
    )
    supervisor = Supervisor.build(
        tmp_path,
        [
            ManagedProcess(
                name="collector",
                command=[sys.executable, "-c", code, str(stop_file)],
                cwd=Path.cwd(),
                stop_file=stop_file,
            )
        ],
    )
    supervisor.start_all()
    status = supervisor.stop_all(grace_seconds=15.0)
    report = status["stop_report"]
    assert report["verdict"] == "FAILED"
    assert report["failed_children"] == ["collector"]
    assert report["exit_codes"]["collector"] == 2
    assert supervisor.get("collector").state is ProcessState.STOPPED


def test_a_child_that_ignores_the_stop_file_is_a_failure_not_a_tidy_stop(tmp_path: Path) -> None:
    stop_file = tmp_path / "STOP"
    supervisor = Supervisor.build(
        tmp_path,
        [
            ManagedProcess(
                name="collector",
                command=[sys.executable, "-c", "import time; time.sleep(60)"],
                cwd=Path.cwd(),
                stop_file=stop_file,
            )
        ],
    )
    supervisor.start_all()
    status = supervisor.stop_all(grace_seconds=0.5, timeout=5.0)
    report = status["stop_report"]
    assert report["escalated"] == ["collector"]
    assert report["verdict"] == "FAILED"
    runtime = supervisor.get("collector")
    assert runtime.state is ProcessState.FAILED
    assert runtime.forced_stop is True
    assert "did not finalise" in (runtime.failure_reason or "")
