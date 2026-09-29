"""One-command operation, retention dry-run and the system daily report.

Three claims are under test here, all of them operational rather than
algorithmic:

* §5 — retention can be asked *what it would do* and answers without touching
  disk, so an operator can read the plan before anything is reclaimed;
* §15/§47 — the combined report folds the three planes and refuses to print a
  zero for a plane that produced nothing, because "no data" and "no losses" are
  different sentences;
* §49-§52 — one command starts PAPER + collector + maintenance, one command stops
  them, and the plan says which children are critical.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest

from trading_bot.research.forward.contract import (
    EventType,
    Market,
    RawEvent,
    SequenceRange,
    Transport,
)
from trading_bot.research.forward.retention import (
    RAW_ROOT,
    RetentionPolicy,
    apply_retention,
    plan_retention,
)
from trading_bot.research.forward.storage import SegmentWriter

_REPO_ROOT = Path(__file__).resolve().parents[3]
MINUTE_MS = 60_000
ROTATION = 900


def _load_script(name: str) -> Any:
    path = _REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def retention_driver() -> Any:
    return _load_script("forward_retention")


@pytest.fixture(scope="module")
def lab_launcher() -> Any:
    return _load_script("start_paper_lab")


@pytest.fixture(scope="module")
def system_report() -> Any:
    return _load_script("system_daily_report")


# --------------------------------------------------------------------- fixtures


def _trade(*, ts_ms: int, agg_id: int = 1) -> RawEvent:
    return RawEvent(
        event_type=EventType.AGG_TRADE,
        symbol="BTCUSDT",
        market=Market.SPOT,
        stream="btcusdt@aggTrade",
        transport=Transport.WS,
        run_id="run-lab-ops",
        exchange_event_id=str(agg_id),
        exchange_event_time=ts_ms,
        receive_time=ts_ms + 25,
        process_time=ts_ms + 26,
        sequence=SequenceRange(first=agg_id, last=agg_id),
        price="100.5",
        quantity="2",
        aggressor_side="buy",
    )


def _aligned_window_start(*, windows_ago: int = 0) -> int:
    """A real, rotation-aligned window start relative to now.

    Segments written into the *current* window can never be outside a hot window,
    so a test that wants a compactable window has to go back one rotation.
    """
    now_ms = int(time.time() * 1000)
    width = ROTATION * 1000
    return (now_ms // width) * width - windows_ago * width


def _capture(root: Path, *, window_start_ms: int, trades: int = 5) -> Path:
    writer = SegmentWriter(root, rotation_seconds=ROTATION, run_id="run-lab-ops")
    for index in range(trades):
        writer.write(_trade(ts_ms=window_start_ms + index * MINUTE_MS, agg_id=index + 1))
    writer.close()
    files = sorted((root / RAW_ROOT).rglob("*.jsonl.gz"))
    assert len(files) == 1, files
    return files[0]


def _tree_snapshot(root: Path) -> dict[str, int]:
    return {
        path.relative_to(root).as_posix(): path.stat().st_size
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _args(**overrides: Any) -> argparse.Namespace:
    base: dict[str, Any] = {
        "root": ".",
        "run_id": "run-lab-ops",
        "rotation_seconds": ROTATION,
        "raw_hot_hours": 1.0,
        "sealed_grace_seconds": 0,
        "reserve_mib": 384,
        "delete_when_free_below": 0,
        "loop": False,
        "dry_run": True,
        "interval": 600.0,
        "max_iterations": 1,
        "report": None,
    }
    return argparse.Namespace(**{**base, **overrides})


# ------------------------------------------------------- retention dry-run (§5)


def test_a_dry_run_reports_the_plan_and_changes_nothing(
    tmp_path: Path, retention_driver: Any
) -> None:
    bucket = _aligned_window_start()
    _capture(tmp_path, window_start_ms=bucket)
    before = _tree_snapshot(tmp_path)

    payload = retention_driver.dry_run_once(_args(), "run-lab-ops", tmp_path)

    assert payload["dry_run"] is True
    assert payload["dry_run_changed_nothing"] is True
    assert payload["would_retain_raw_segments"] == 1
    assert payload["would_compact_windows"] == 0  # still inside the hot window
    assert payload["would_delete_segments"] == 0
    assert payload["would_reclaim_bytes"] == 0
    assert _tree_snapshot(tmp_path) == before, "a dry run is not allowed to touch disk"


def test_a_compactable_window_is_reported_as_would_compact(
    tmp_path: Path, retention_driver: Any
) -> None:
    bucket = _aligned_window_start(windows_ago=1)
    _capture(tmp_path, window_start_ms=bucket)
    before = _tree_snapshot(tmp_path)

    payload = retention_driver.dry_run_once(
        _args(raw_hot_hours=0.0), "run-lab-ops", tmp_path
    )

    assert payload["would_compact_windows"] == 1
    assert payload["would_compact_segments"] == 1
    assert payload["would_compact_bytes"] > 0
    # Compaction has not happened, so nothing is deletable and nothing was freed.
    assert payload["would_delete_segments"] == 0
    assert payload["would_reclaim_bytes"] == 0
    assert _tree_snapshot(tmp_path) == before


def test_after_compaction_the_dry_run_says_what_would_be_reclaimed(
    tmp_path: Path, retention_driver: Any
) -> None:
    bucket = _aligned_window_start(windows_ago=1)
    _capture(tmp_path, window_start_ms=bucket)
    policy = RetentionPolicy(rotation_seconds=ROTATION, raw_hot_hours=0.0, sealed_grace_seconds=0)
    apply_retention(tmp_path, policy, "run-lab-ops", allow_delete=False)
    before = _tree_snapshot(tmp_path)

    payload = retention_driver.dry_run_once(_args(raw_hot_hours=0.0), "run-lab-ops", tmp_path)

    assert payload["would_delete_segments"] == 1
    assert payload["would_reclaim_bytes"] > 0
    assert payload["deletable"][0]["lineage_id"]
    assert payload["deletable"][0]["path"].endswith(".jsonl.gz")
    assert _tree_snapshot(tmp_path) == before, "the plan must not be the deed"


def test_deletion_is_disabled_unless_a_threshold_is_given(
    tmp_path: Path, retention_driver: Any
) -> None:
    bucket = _aligned_window_start()
    _capture(tmp_path, window_start_ms=bucket)
    payload = retention_driver.dry_run_once(_args(), "run-lab-ops", tmp_path)
    assert payload["delete_threshold_bytes"] == 0
    assert payload["deletion_would_be_enabled"] is False


# --------------------------------------------------- one-command start/stop (§50)


def _launcher_namespace(**overrides: Any) -> argparse.Namespace:
    """The launcher's arguments, built from the launcher's own parser.

    Taken from ``parse_args`` rather than hand-written, so a new option the
    launcher grows reaches this fixture automatically instead of making the test
    pass on a namespace the program can never actually receive.
    """
    args = launcher_defaults()
    values: dict[str, Any] = {
        **vars(args),
        "run_id": "lab-test",
        "dry_run": True,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


@lru_cache(maxsize=1)
def launcher_defaults() -> argparse.Namespace:
    """The parsed default namespace of the real launcher CLI."""
    return _load_script("start_paper_lab").parse_args([])


def test_the_launcher_plans_paper_and_collector_as_isolated_critical_children(
    lab_launcher: Any,
) -> None:
    namespace = _launcher_namespace()
    run_dir = Path("reports/paper-lab/lab-test")
    stop_files = lab_launcher.child_stop_files(namespace, "lab-test", run_dir)
    specs = lab_launcher.build_specs(namespace, "lab-test", run_dir, stop_files)
    by_name = {spec.name: spec for spec in specs}

    assert {"paper", "collector"} <= set(by_name)
    assert by_name["paper"].critical and by_name["collector"].critical
    assert not by_name["retention"].critical
    assert not by_name["strategy_lab"].critical
    # Isolation is structural: two commands, two processes, no shared state file.
    assert by_name["paper"].command != by_name["collector"].command
    assert "--continuous" in by_name["paper"].command
    assert "--mode" in by_name["collector"].command
    # The PAPER child is the PAPER entrypoint, so there is no live path to reach.
    assert "autonomous_paper.py" in " ".join(by_name["paper"].command)
    assert "--provider" in by_name["paper"].command


def test_every_child_that_must_finalise_is_stopped_by_a_file(lab_launcher: Any) -> None:
    """§51 — a supervisor's terminate() is a hard kill; the file is the ask."""
    namespace = _launcher_namespace()
    run_dir = Path("reports/paper-lab/lab-test")
    stop_files = lab_launcher.child_stop_files(namespace, "lab-test", run_dir)
    specs = lab_launcher.build_specs(namespace, "lab-test", run_dir, stop_files)
    by_name = {spec.name: spec for spec in specs}

    assert set(stop_files) == {"paper", "collector", "retention", "strategy_lab"}
    for name, spec in by_name.items():
        assert spec.stop_file == stop_files[name], name
    # Every distinct child gets its own file: one file cannot stop two children
    # and still tell the operator which one was asked first.
    assert len(set(stop_files.values())) == len(stop_files)
    # PAPER already watches STOP in its own run directory, and the collector's
    # file lives beside the resume state it writes.
    assert stop_files["paper"].name == "STOP"
    assert stop_files["collector"].suffix == ".stop"
    # The collector can only honour a stop file if it was told where it is.
    collector_command = by_name["collector"].command
    assert "--stop-file" in collector_command
    assert collector_command[collector_command.index("--stop-file") + 1] == str(
        stop_files["collector"]
    )


def test_a_restart_tells_the_collector_it_owns_the_root(
    tmp_path: Path, lab_launcher: Any
) -> None:
    """Without ``--resume`` the writer refuses its own past and the capture dies.

    Leg 2 of the first Stop/restart pair reused the run id without it and wrote
    198 unrecoverable gaps while every child exited 0 — a capture that stopped
    being able to write and never said so.
    """
    namespace = _launcher_namespace(forward_root=str(tmp_path / "forward"))
    run_dir = Path("reports/paper-lab/lab-test")
    stop_files = lab_launcher.child_stop_files(namespace, "lab-test", run_dir)
    first = {
        spec.name: spec
        for spec in lab_launcher.build_specs(namespace, "lab-test", run_dir, stop_files)
    }
    assert "--resume" not in first["collector"].command

    state = tmp_path / "forward" / "state"
    state.mkdir(parents=True)
    (state / "lab-test.json").write_text("{}", encoding="utf-8")

    again = {
        spec.name: spec
        for spec in lab_launcher.build_specs(namespace, "lab-test", run_dir, stop_files)
    }
    assert "--resume" in again["collector"].command
    # Only the collector owns capture state; PAPER resumes through its own store.
    assert "--resume" not in again["paper"].command
    assert "--resume" not in again["retention"].command


def test_the_stop_reason_is_read_from_the_evidence(
    tmp_path: Path, lab_launcher: Any
) -> None:
    """A duration-limited run stopped early must not be reported as completed."""
    stop_file = tmp_path / "STOP"
    # A signal beats everything: the handler knew why it stopped.
    assert lab_launcher.resolve_stop_reason(
        reason="signal 2", stop_file=stop_file, configured_duration_hours=2.0
    ) == "signal 2"
    # A STOP file on a 2 h run is a STOP file, not a reached duration.
    stop_file.write_text("stop\n", encoding="utf-8")
    assert lab_launcher.resolve_stop_reason(
        reason=None, stop_file=stop_file, configured_duration_hours=2.0
    ) == "STOP file"
    stop_file.unlink()
    assert lab_launcher.resolve_stop_reason(
        reason=None, stop_file=stop_file, configured_duration_hours=2.0
    ) == "duration reached"
    assert lab_launcher.resolve_stop_reason(
        reason=None, stop_file=stop_file, configured_duration_hours=0.0
    ) == "STOP file"


def test_one_command_writes_the_stop_file(
    tmp_path: Path, lab_launcher: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§51 — stopping is one command, and it is the same file the children watch."""
    from trading_bot.autonomous.paper_loop import STOP_FILE_NAME

    target = tmp_path / "lab-run"
    monkeypatch.setattr(
        sys, "argv", ["start_paper_lab.py", "--stop", str(target)]
    )
    assert lab_launcher.main() == 0
    stop_file = target / STOP_FILE_NAME
    assert stop_file.exists()
    assert "stop requested at" in stop_file.read_text(encoding="utf-8")


# ------------------------------------------------- system daily report (§15, §47)


def _paper_run_dir(root: Path, **overrides: Any) -> Path:
    run_dir = root / "run-1"
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "paper-daily-report-v1",
        "mode": "PAPER",
        "cycles": 7,
        "decisions": 21,
        "no_trade": 21,
        "no_trade_kinds": {"NO_STRATEGY_ADMITTED": 21},
        "shadow_trades": 0,
        "paper_trades": 0,
        "orders_created": 0,
        "risk_events": {},
        "runtime_failures": 0,
        "paper_candidates": [],
        "pnl": {"gross_bps_total": 0.0, "pending_outcomes": 0},
        "strategy_attribution": {},
        "errors": [],
        **overrides,
    }
    (run_dir / "PAPER_DAILY_REPORT.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    (run_dir / "heartbeat.json").write_text(
        json.dumps({"cycle": 7, "state_age_seconds": 12.0, "mode": "PAPER"}),
        encoding="utf-8",
    )
    return run_dir


def test_absent_planes_are_reported_as_absent_not_as_zero(
    tmp_path: Path, system_report: Any
) -> None:
    lab_dir = tmp_path / "lab"
    lab_dir.mkdir(parents=True, exist_ok=True)
    payload = system_report.build_report(
        argparse.Namespace(
            lab_run_dir=str(lab_dir),
            paper_run_dir=None,
            forward_root=str(tmp_path / "does-not-exist"),
            forward_run_id=None,
            lab_report=None,
            out=None,
        )
    )
    assert payload["planes_present"] == {
        "paper": False,
        "forward_data": False,
        "strategy_lab": False,
        "supervisor": False,
    }
    text = "\n".join(payload["honesty_notes"])
    assert "absence of evidence" in text
    markdown = system_report.render_system_markdown(payload)
    assert "n/a (no heartbeat)" in markdown


def test_paper_and_forward_and_lab_are_folded_into_one_report(
    tmp_path: Path, system_report: Any
) -> None:
    lab_dir = tmp_path / "lab"
    lab_dir.mkdir(parents=True, exist_ok=True)
    (lab_dir / "SYSTEM_HEARTBEAT.json").write_text(
        json.dumps(
            {
                "state": "HEALTHY",
                "disk_free_bytes": 1_000_000_000,
                "memory_mb": 123.5,
                "processes": {"paper": {"state": "RUNNING"}},
                "children": {},
            }
        ),
        encoding="utf-8",
    )
    (lab_dir / "LAB_RUN_REPORT.json").write_text(
        json.dumps(
            {
                "duration_seconds": 7200.0,
                "stop_reason": "STOP file",
                "final_state": "HEALTHY",
                "supervisor_events": [
                    {"event": "RESTARTED", "process": "collector"},
                    {"event": "EXIT", "process": "paper"},
                ],
            }
        ),
        encoding="utf-8",
    )
    paper_dir = _paper_run_dir(tmp_path / "paper")

    forward_root = tmp_path / "forward"
    (forward_root / "manifest").mkdir(parents=True, exist_ok=True)
    (forward_root / "state").mkdir(parents=True, exist_ok=True)
    (forward_root / "manifest" / "lab-1.json").write_text(
        json.dumps(
            {
                "run_id": "lab-1",
                "commit": "abc1234",
                "continuity": "INCOMPLETE_DATA",
                "duration_seconds": 7200.0,
                "rotation_seconds": 900,
                "fingerprints": [{"row_count": 400_000, "partial_tail": False}],
                "gaps": [
                    {"status": "RECOVERED_COMPLETE", "data_lost": False},
                    {"status": "UNRECOVERABLE", "data_lost": False},
                ],
                "reconnects": 3,
                "resnapshots": 5,
                "bytes_written": 500_000_000,
                "stopped_on_disk_budget": False,
                "integrity": {
                    "backfilled_events": 1234,
                    "backfill_gaps_closed": 2,
                    "backfill_failures": 0,
                    "connect_failures": 0,
                },
                "degradation_events": [{"kind": "DEGRADED"}],
                "resources": {"memory_mb_max": 210.0},
            }
        ),
        encoding="utf-8",
    )
    (forward_root / "state" / "lab-1.json").write_text(
        json.dumps({"run_id": "lab-1", "events": 400_000, "reconnects": 3, "gaps": 2}),
        encoding="utf-8",
    )

    lab_report = tmp_path / "lab" / "STRATEGY_LAB_REPORT.json"
    lab_report.write_text(
        json.dumps(
            {
                "schema_version": "strategy-lab-report-v1",
                "lifecycle": {
                    "REJECTED": 2,
                    "RESEARCH_REQUIRED": 1,
                    "PAPER_CANDIDATE": 0,
                    "PAPER_ACTIVE": 0,
                    "PAPER_RETIRED": 0,
                },
                "paper_executable": [],
                "all_checks_ok": True,
                "checks": {"ledger_sources": {"ok": True}},
                "mode": "READ_ONLY",
            }
        ),
        encoding="utf-8",
    )

    payload = system_report.build_report(
        argparse.Namespace(
            lab_run_dir=str(lab_dir),
            paper_run_dir=str(paper_dir),
            forward_root=str(forward_root),
            forward_run_id="lab-1",
            lab_report=str(lab_report),
            out=None,
        )
    )

    assert all(payload["planes_present"].values())
    assert payload["paper"]["cycles"] == 7
    assert payload["paper"]["no_trade"] == 21
    assert payload["paper"]["paper_trades"] == 0
    assert payload["forward_data"]["row_count"] == 400_000
    assert payload["forward_data"]["reconnects"] == 3
    assert payload["forward_data"]["unrecoverable_gaps"] == 1
    assert payload["forward_data"]["backfilled_events"] == 1234
    assert payload["strategy_lab"]["lifecycle"]["REJECTED"] == 2
    assert payload["operations"]["restarts"] == 1
    assert payload["operations"]["crash_loops"] == 0

    markdown = system_report.render_system_markdown(payload)
    assert "PAPER trades  : 0" in markdown
    assert "reconnects    : 3" in markdown
    assert "REJECTED=2" in markdown
    assert "0 experiments and 0 candidates" in "\n".join(payload["honesty_notes"]) or "NONE" in markdown


def test_the_system_report_writes_both_renditions(
    tmp_path: Path, system_report: Any
) -> None:
    lab_dir = tmp_path / "lab"
    lab_dir.mkdir(parents=True, exist_ok=True)
    stem = lab_dir / "SYSTEM_DAILY_REPORT"
    payload = system_report.build_report(
        argparse.Namespace(
            lab_run_dir=str(lab_dir),
            paper_run_dir=None,
            forward_root=str(tmp_path / "nope"),
            forward_run_id=None,
            lab_report=None,
            out=None,
        )
    )
    stem.with_suffix(".json").write_text(json.dumps(payload), encoding="utf-8")
    stem.with_suffix(".md").write_text(
        system_report.render_system_markdown(payload), encoding="utf-8"
    )
    assert json.loads(stem.with_suffix(".json").read_text(encoding="utf-8"))["schema_version"]
    assert stem.with_suffix(".md").read_text(encoding="utf-8").startswith("# SYSTEM DAILY REPORT")


def test_the_strategy_lab_reports_the_whole_status_histogram(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A lifecycle count of zero must not hide twenty-four non-executable strategies."""
    lab = _load_script("paper_lab_research")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "paper_lab_research.py",
            "--ledger",
            "config/strategy_admission.json",
            "--forward-root",
            "reports/microstructure-forward-lab",
            "--timeframe",
            "5m",
        ],
    )
    report = lab.build_report(lab.parse_args())
    assert report["strategies_total"] == 24
    assert report["strategies_not_paper_executable"] == 24
    assert report["paper_executable"] == []
    histogram = report["status_histogram"]
    assert histogram["NO_GROSS_EDGE"] == 17
    assert histogram["COST_KILLED"] == 7
    for admitted in ("PAPER_CANDIDATE", "PAPER_ACTIVE", "PAPER_RETIRED"):
        assert histogram[admitted] == 0


def test_latency_percentiles_come_from_the_read_side_quality_report(
    tmp_path: Path, system_report: Any
) -> None:
    """The manifest is written by the capture process; the distribution is not.

    Rather than re-deriving a number the read side already publishes, the report
    prints ``None`` until the quality report exists.
    """
    forward_root = tmp_path / "forward"
    (forward_root / "manifest").mkdir(parents=True, exist_ok=True)
    (forward_root / "manifest" / "lab-1.json").write_text(
        json.dumps({"run_id": "lab-1", "fingerprints": [], "gaps": [], "integrity": {}}),
        encoding="utf-8",
    )
    without = system_report.collect_forward(forward_root, "lab-1")
    assert without["latency_p50_ms"] is None
    assert without["latency_source"] is None

    reports = forward_root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "FORWARD_DATA_QUALITY_REPORT.json").write_text(
        json.dumps({"event_latency_ms": {"p50_ms": 12, "p95_ms": 90, "p99_ms": 250}}),
        encoding="utf-8",
    )
    with_report = system_report.collect_forward(forward_root, "lab-1")
    assert (with_report["latency_p50_ms"], with_report["latency_p95_ms"]) == (12, 90)
    assert with_report["latency_source"].endswith("FORWARD_DATA_QUALITY_REPORT.json")


def test_the_reported_plan_is_the_plan_the_real_pass_executes(
    tmp_path: Path, retention_driver: Any
) -> None:
    """A dry run is only useful if it is the same decision the real pass makes."""
    bucket = _aligned_window_start(windows_ago=1)
    _capture(tmp_path, window_start_ms=bucket)
    policy = RetentionPolicy(rotation_seconds=ROTATION, raw_hot_hours=0.0, sealed_grace_seconds=0)
    planned = plan_retention(tmp_path, policy, "run-lab-ops")

    dry = retention_driver.dry_run_once(_args(raw_hot_hours=0.0), "run-lab-ops", tmp_path)
    assert dry["would_compact_windows"] == len(planned.compactable)
    assert dry["would_retain_raw_segments"] == len(planned.retained_raw)

    real = retention_driver.run_once(_args(raw_hot_hours=0.0, dry_run=False), "run-lab-ops", tmp_path)
    assert len(real["result"]["compacted_windows"]) == len(planned.compactable)
    assert real["deleted"] == 0, "deletion is demand driven and was not demanded"


def test_a_missing_root_is_not_an_error(retention_driver: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["forward_retention.py", "--root", "reports/definitely-not-a-real-root"],
    )
    assert retention_driver.main() == 0


def test_retention_waits_for_a_capture_that_starts_late(
    tmp_path: Path, retention_driver: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A long-lived compaction worker must outlive its capture's first write.

    The collector creates its root after the retention child starts, so exiting
    on the first empty pass would silently drop compaction for the whole run.
    """
    root = tmp_path / "forward-lab"
    waits = {"n": 0}

    def fake_sleep(_seconds: float) -> None:
        waits["n"] += 1
        (root / "state").mkdir(parents=True, exist_ok=True)
        (root / "state" / "late-run.json").write_text(
            json.dumps({"run_id": "late-run", "events": 1}), encoding="utf-8"
        )

    monkeypatch.setattr(retention_driver.time, "sleep", fake_sleep)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "forward_retention.py",
            "--root",
            str(root),
            "--loop",
            "--interval",
            "1",
            "--max-iterations",
            "1",
            "--dry-run",
            "--report",
            str(tmp_path / "RETENTION_REPORT.json"),
        ],
    )
    assert retention_driver.main() == 0
    # The count is not the claim: the worker now waits in short slices so it can
    # notice a stop file, and this fake sleep returns instantly while the real
    # clock barely moves, so one wait is many slices. The claim is that it waited
    # instead of exiting on an empty pass — and then used the capture it found.
    assert waits["n"] >= 1, "it should wait before the capture appeared"
    report = json.loads((tmp_path / "RETENTION_REPORT.json").read_text(encoding="utf-8"))
    assert report["run_id"] == "late-run"
    assert report["dry_run"] is True
