"""WP-051-02F — the runner's states, the temporal guard, the lock, and the verifier's refusals.

Three things are under test, and the third is the one that matters.

The **runner** has to name *why* nothing happened. ``NOT_DUE``, ``PENDING_DATA``,
``PENDING_FRESHNESS`` and ``BLOCKED_INTEGRITY`` are different facts about the world, and
a report that collapses them into one word is how a "capture" becomes a story. The
runner also has to be idempotent: a dataset that is already on disk is not captured
again, and a second attempt over it is a no-op rather than a second publication.

The **temporal guard** is the answer to ``DEF-02E-01``/``L-01``. The frozen extractor
marks a bar eligible when it was fetched at or after the declaration took effect and
opens inside the window; it never asks whether the bar claims to have been ingested
*after the capture was decided*. While phase 2 is frozen the extractor may not be
changed, so the only available correction is a refusal: detect the impossible row,
quarantine it, and leave the bytes on disk as the record of a quarantined attempt.

The **verifier** has to reject evidence that lies. Every case below is one a builder
could have produced by accident or by design — a claim of success with nothing behind
it, a capture decision in the future, a row the store never held, a row that was edited
on the way to publication, a gate that was quietly promoted — and each one has to come
back ``FAIL``.

Every fixture here is a fixture. The rows are synthetic, they live in ``tmp_path``, and
nothing in this file writes to ``data/exp004a``, to the forward store or to the freeze.

The tests are numbered after the fifteen minimum adversarial cases of RFC
``RFC-EXP004A-051-02F`` §9. The number in each docstring is the RFC's own.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

import exp004a_wp051_02f_runner as runner  # noqa: E402
import exp004a_wp051_02f_verify as verifier  # noqa: E402

WINDOW_START = "2026-10-22T00:00:00Z"
WINDOW_END = "2027-01-20T00:00:00Z"
EFFECTIVE = "2026-10-21T16:00:00Z"
DATASET_ID = "EXP-004A-1H-BTC"
ASSET = "BTC"
INTERVAL = "1h"
SPAN_MS = 3_600_000
LOCKED_GATES = {
    "C_016": "UNREACHABLE_UNDER_DECLARED_COST_MODEL",
    "PAPER_VALIDATION": "NOT_PASS",
    "CERTIFICATION": "BLOCKED",
    "PROMOTION": "NO_PROMOTION",
}


def _ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


class _NoSleep:
    """The ``time`` module with a no-op ``sleep``, so a retry test does not wait.

    ``dataclasses.replace(time, ...)`` is not an option: a module is not a dataclass.
    """

    def __init__(self, real: Any) -> None:
        self._real = real

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)

    def sleep(self, *args: Any, **kwargs: Any) -> None:
        return None


def _row(open_utc: str, fetched_utc: str, *, closed: bool = True, **extra: Any) -> dict[str, Any]:
    row = {
        "ts": _ms(open_utc),
        "interval": "1h",
        "closed": closed,
        "fetched_at_ms": _ms(fetched_utc),
        "open": 100.0,
        "close": 101.0,
    }
    row.update(extra)
    return row


def _slice(
    *,
    asset: str = ASSET,
    dataset_id: str = DATASET_ID,
    normalized: str | None = None,
) -> runner.Slice:
    return runner.Slice(
        spec=f"{INTERVAL}:{asset}",
        dataset_id=dataset_id,
        asset=asset,
        interval=INTERVAL,
        timeframe=INTERVAL,
        lag_bound_ms=7_200_000,
        coverage_required=0.9,
        generator_command=f"python scripts/exp004a_capture.py --slice {INTERVAL}:{asset}",
        normalized_file=normalized or f"data/exp004a/{dataset_id}.jsonl",
        raw_file=f"data/exp004a/{dataset_id}.raw.jsonl",
        source_path=Path(f"data/forward/edge03/{INTERVAL}/{asset}.jsonl"),
    )


def _declaration(
    *,
    start_utc: str = WINDOW_START,
    end_utc: str = WINDOW_END,
    effective_utc: str = EFFECTIVE,
    slices: tuple[runner.Slice, ...] | None = None,
) -> runner.Declaration:
    """A declaration object shaped like the real one, with a chosen window."""
    return runner.Declaration(
        document={
            "declaration_id": "fixture/v1",
            "capture_window": {},
            "generator": {
                "commit": verifier.GENERATOR_COMMIT,
                "blob_sha256": verifier.GENERATOR_SHA256,
            },
        },
        path=Path("config/preregistrations/EXP-004A.datasets.phase2.json"),
        sha256="0" * 64,
        blob_sha="1" * 40,
        commit="2" * 40,
        window_start_ms=_ms(start_utc),
        window_end_ms=_ms(end_utc),
        effective_from_ms=_ms(effective_utc),
        slices=slices if slices is not None else (_slice(),),
        deferred=("EXP-004A-ST6-TAPE: timeframe '4h slot, 3 rounds of 15s' is not a bar series",),
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows).encode("utf-8"))
    return path


# --------------------------------------------------------------------------- #
# the runner's vocabulary
# --------------------------------------------------------------------------- #


def test_window_state_names_the_three_periods() -> None:
    declaration = _declaration()
    assert runner.window_state(declaration, _ms("2026-10-21T23:59:59Z")) == "BEFORE_WINDOW"
    assert runner.window_state(declaration, _ms("2026-10-22T00:00:00Z")) == "OPEN"
    assert runner.window_state(declaration, _ms("2026-10-23T00:00:00Z")) == "OPEN"
    assert runner.window_state(declaration, _ms("2027-01-20T00:00:00Z")) == "AFTER_WINDOW"


def test_expected_last_closed_open_is_the_bar_that_has_already_closed() -> None:
    # At 20:26Z the 19:00Z bar has closed (it closes at 20:00Z) and the 20:00Z bar has not.
    assert runner.expected_last_closed_open(_ms("2026-10-21T20:26:00Z"), SPAN_MS) == _ms(
        "2026-10-21T19:00:00Z"
    )


def test_freshness_flags_a_store_that_lags_the_clock() -> None:
    state = runner.SeriesState(
        spec=f"{INTERVAL}:{ASSET}",
        asset=ASSET,
        interval=INTERVAL,
        path="data/forward/edge03/1h/BTC.jsonl",
        readable=True,
        rows=10,
        last_open_ms=_ms("2026-10-21T17:00:00Z"),
    )
    verdict = runner.freshness(state, _ms("2026-10-21T20:26:00Z"))
    assert verdict["ok"] is False
    assert "behind" in verdict["reason"]


def test_freshness_accepts_a_current_store() -> None:
    state = runner.SeriesState(
        spec=f"{INTERVAL}:{ASSET}",
        asset=ASSET,
        interval=INTERVAL,
        path="data/forward/edge03/1h/BTC.jsonl",
        readable=True,
        rows=10,
        last_open_ms=_ms("2026-10-21T19:00:00Z"),
    )
    assert runner.freshness(state, _ms("2026-10-21T20:26:00Z"))["ok"] is True


def test_an_unreadable_series_is_stale_rather_than_current() -> None:
    state = runner.SeriesState(
        spec=f"{INTERVAL}:{ASSET}",
        asset=ASSET,
        interval=INTERVAL,
        path="data/forward/edge03/1h/BTC.jsonl",
        readable=False,
        error="FileNotFoundError: nope",
    )
    assert runner.freshness(state, _ms("2026-10-21T20:26:00Z"))["ok"] is False


def test_the_runner_reads_its_window_from_the_declaration_and_copies_nothing() -> None:
    """The constants are the declaration's, not the runner's.

    A runner that hard-codes the window is a runner that keeps capturing after the
    preregistration moved, which is the same class of defect as the frozen extractor
    that this whole package exists to contain.
    """
    source = (REPO / "scripts" / "exp004a_wp051_02f_runner.py").read_text(encoding="utf-8")
    for literal in ("2026-10-22", "2027-01-20", "2026-10-21T16:00:00Z"):
        assert literal not in source, f"the runner hard-codes {literal}"
    declaration = runner.load_declaration(REPO)
    assert declaration.window_start_ms == _ms(WINDOW_START)
    assert declaration.window_end_ms == _ms(WINDOW_END)
    assert declaration.effective_from_ms == _ms(EFFECTIVE)
    assert [item.spec for item in declaration.slices] == ["1h:BTC", "1h:ETH", "1h:SOL"]
    assert any("ST6-TAPE" in item for item in declaration.deferred)


# --------------------------------------------------------------------------- #
# the temporal guard
# --------------------------------------------------------------------------- #


def _guard(tmp_path: Path, rows: list[dict[str, Any]], **kwargs: Any) -> runner.GuardVerdict:
    declaration = _declaration()
    slice_ = declaration.slices[0]
    dataset = tmp_path / "data" / "exp004a" / f"{DATASET_ID}.jsonl"
    _write_jsonl(dataset, rows)
    return runner.temporal_guard(
        tmp_path,
        slice_,
        declaration,
        decision_ms=kwargs.get("decision_ms", _ms("2026-10-22T03:00:00Z")),
        now_at_guard_ms=kwargs.get("now_at_guard_ms", _ms("2026-10-22T03:00:30Z")),
    )


def test_guard_accepts_admissible_rows(tmp_path: Path) -> None:
    verdict = _guard(
        tmp_path,
        [
            _row("2026-10-22T00:00:00Z", "2026-10-22T01:05:00Z"),
            _row("2026-10-22T01:00:00Z", "2026-10-22T02:05:00Z"),
        ],
    )
    assert verdict.verdict == "PASS"
    assert verdict.rows == 2
    assert verdict.violations == []


def test_guard_quarantines_an_ingest_after_the_capture_decision(tmp_path: Path) -> None:
    """The L-01 case: a bar that claims to have been ingested after the decision."""
    verdict = _guard(
        tmp_path,
        [_row("2026-10-22T00:00:00Z", "2026-10-22T03:30:00Z")],
        decision_ms=_ms("2026-10-22T03:00:00Z"),
    )
    assert verdict.verdict == "QUARANTINE"
    assert any(item["code"] == "INGEST_AFTER_DECISION" for item in verdict.violations)


def test_guard_quarantines_an_ingest_after_its_own_clock(tmp_path: Path) -> None:
    verdict = _guard(
        tmp_path,
        [_row("2026-10-22T00:00:00Z", "2026-10-22T00:45:00Z")],
        decision_ms=_ms("2026-10-22T09:00:00Z"),
        now_at_guard_ms=_ms("2026-10-22T00:30:00Z"),
    )
    assert verdict.verdict == "QUARANTINE"
    assert any(item["code"] == "INGEST_AFTER_NOW" for item in verdict.violations)


def test_guard_quarantines_an_ingest_before_the_declaration_took_effect(tmp_path: Path) -> None:
    verdict = _guard(
        tmp_path,
        [_row("2026-10-22T00:00:00Z", "2026-10-21T15:00:00Z")],
    )
    assert verdict.verdict == "QUARANTINE"
    assert any(item["code"] == "INGEST_BEFORE_EFFECTIVE" for item in verdict.violations)


def test_guard_quarantines_a_bar_outside_the_window(tmp_path: Path) -> None:
    verdict = _guard(
        tmp_path,
        [_row("2026-10-21T23:00:00Z", "2026-10-22T00:05:00Z")],
    )
    assert verdict.verdict == "QUARANTINE"
    assert any(item["code"] == "OUTSIDE_DECLARED_WINDOW" for item in verdict.violations)


def test_guard_quarantines_a_bar_that_closes_after_the_decision(tmp_path: Path) -> None:
    verdict = _guard(
        tmp_path,
        [_row("2026-10-22T01:30:00Z", "2026-10-22T02:00:00Z")],
        decision_ms=_ms("2026-10-22T01:00:00Z"),
    )
    assert verdict.verdict == "QUARANTINE"
    assert any(item["code"] == "CLOSE_AFTER_DECISION" for item in verdict.violations)


def test_guard_quarantines_a_bar_ingested_before_it_closed(tmp_path: Path) -> None:
    verdict = _guard(
        tmp_path,
        [_row("2026-10-22T00:00:00Z", "2026-10-22T00:30:00Z")],
    )
    assert verdict.verdict == "QUARANTINE"
    assert any(item["code"] == "NEGATIVE_LAG" for item in verdict.violations)


def test_guard_quarantines_repeated_and_disordered_opens(tmp_path: Path) -> None:
    verdict = _guard(
        tmp_path,
        [
            _row("2026-10-22T01:00:00Z", "2026-10-22T02:05:00Z"),
            _row("2026-10-22T00:00:00Z", "2026-10-22T00:05:00Z"),
            _row("2026-10-22T00:00:00Z", "2026-10-22T00:05:00Z"),
        ],
    )
    assert verdict.verdict == "QUARANTINE"
    codes = {item["code"] for item in verdict.violations}
    assert "DUPLICATE_BAR_OPEN" in codes
    assert "OUT_OF_ORDER" in codes


def test_guard_quarantines_a_row_that_is_not_json(tmp_path: Path) -> None:
    dataset = tmp_path / "data" / "exp004a" / f"{DATASET_ID}.jsonl"
    dataset.parent.mkdir(parents=True, exist_ok=True)
    dataset.write_bytes(b"{not json\n")
    verdict = runner.temporal_guard(
        tmp_path,
        _declaration().slices[0],
        _declaration(),
        decision_ms=_ms("2026-10-22T03:00:00Z"),
        now_at_guard_ms=_ms("2026-10-22T03:00:30Z"),
    )
    assert verdict.verdict == "QUARANTINE"
    assert any(item["code"] == "ROW_NOT_JSON" for item in verdict.violations)


def test_guard_reports_a_missing_dataset_as_not_published(tmp_path: Path) -> None:
    declaration = _declaration()
    verdict = runner.temporal_guard(
        tmp_path,
        declaration.slices[0],
        declaration,
        decision_ms=_ms("2026-10-22T03:00:00Z"),
        now_at_guard_ms=_ms("2026-10-22T03:00:30Z"),
    )
    assert verdict.verdict == "NOT_PUBLISHED"


def test_guard_never_writes_to_the_dataset_directory(tmp_path: Path) -> None:
    """RFC case 6: the guard rejects the row *without altering the file*."""
    rows = [_row("2026-10-22T00:00:00Z", "2026-10-22T01:05:00Z")]
    declaration = _declaration()
    dataset = tmp_path / "data" / "exp004a" / f"{DATASET_ID}.jsonl"
    _write_jsonl(dataset, rows)
    before = dataset.read_bytes()
    before_mtime = dataset.stat().st_mtime_ns
    directory = dataset.parent

    runner.temporal_guard(
        tmp_path,
        declaration.slices[0],
        declaration,
        decision_ms=_ms("2026-10-22T03:00:00Z"),
        now_at_guard_ms=_ms("2026-10-22T03:00:30Z"),
    )

    assert dataset.read_bytes() == before
    assert dataset.stat().st_mtime_ns == before_mtime
    assert sorted(path.name for path in directory.iterdir()) == [f"{DATASET_ID}.jsonl"]


# --------------------------------------------------------------------------- #
# the lock
# --------------------------------------------------------------------------- #


def test_the_lock_is_exclusive(tmp_path: Path) -> None:
    path = tmp_path / "runner.lock"
    with runner.Lock(path), pytest.raises(runner.LockHeld), runner.Lock(path):
        pass


def test_the_lock_is_released(tmp_path: Path) -> None:
    path = tmp_path / "runner.lock"
    with runner.Lock(path):
        pass
    assert not path.exists()


def test_an_abandoned_lock_is_taken_over_and_the_takeover_is_recorded(tmp_path: Path) -> None:
    path = tmp_path / "runner.lock"
    path.write_text(json.dumps({"pid": 999999, "acquired_at_utc": "2026-10-21T00:00:00Z"}))
    old = time.time() - runner.LOCK_STALE_SECONDS - 60
    os.utime(path, (old, old))

    with runner.Lock(path) as lock:
        assert lock.taken_over is not None
        assert lock.taken_over["previous"]["pid"] == 999999
    assert not path.exists()


# --------------------------------------------------------------------------- #
# the runner, end to end
# --------------------------------------------------------------------------- #


def _patch_runner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    rows: list[dict[str, Any]],
    slices: tuple[runner.Slice, ...] | None = None,
    preflight_status: str = "WINDOW_OPEN",
) -> runner.Declaration:
    """Make the runner hermetic: a fixture declaration, a fixture store, no network."""
    declaration = _declaration(slices=slices)
    store = tmp_path / "data" / "forward" / "edge03" / "1h" / "BTC.jsonl"
    _write_jsonl(store, rows)
    declaration = replace(
        declaration,
        slices=tuple(
            replace(item, source_path=store if item.asset == ASSET else item.source_path)
            for item in declaration.slices
        ),
    )
    monkeypatch.setattr(runner, "load_declaration", lambda repo: declaration)
    monkeypatch.setattr(
        runner,
        "observe",
        lambda repo, timeout, log_dir=None: {"command": "observer", "exit_code": 0},
    )
    monkeypatch.setattr(
        runner,
        "preflight",
        lambda repo, out_dir, timeout, log_dir=None: {
            "command": "preflight",
            "exit_code": 0,
            "preflight_status": preflight_status,
            "controls": 10,
            "failed_controls": []
            if preflight_status == "WINDOW_OPEN"
            else ["GENERATOR_BLOB_MISMATCH"],
            "out_dir": str(out_dir),
        },
    )
    monkeypatch.setattr(
        runner,
        "verify_02f",
        lambda repo, out_dir, timeout, report_name=runner.CLAIM_REPORT, log_dir=None: {
            "command": "verify02f",
            "exit_code": 0,
            "verifier_status": "PASS",
            "verifier_report": report_name,
        },
    )
    return declaration


def _fake_capture(
    rows: list[dict[str, Any]],
    *,
    exit_code: int = 0,
    publish: bool = True,
) -> Any:
    """A stand-in for the frozen extractor.

    It writes exactly what the extractor writes — the same rows the store holds — or
    refuses, so the runner's own reaction to each outcome can be observed.
    """

    def capture(repo: Path, slice_: runner.Slice, *, timeout: int, log_dir: Any = None) -> dict[str, Any]:
        target = repo / slice_.normalized_file
        if publish:
            _write_jsonl(target, rows)
        return {
            "command": slice_.generator_command,
            "exit_code": exit_code,
            "slice": slice_.spec,
            "dataset_id": slice_.dataset_id,
            "dataset_path": slice_.normalized_file,
            "dataset_exists": target.is_file(),
            "dataset_bytes": target.stat().st_size if target.is_file() else 0,
            "dataset_sha256": hashlib.sha256(target.read_bytes()).hexdigest()
            if target.is_file()
            else None,
            "manifest_exists": False,
            "exit_meaning": runner.CAPTURE_EXIT.get(exit_code, "UNKNOWN"),
        }

    return capture


def test_before_the_window_the_runner_says_not_due_and_publishes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """RFC case 1: the window is still closed."""
    _patch_runner(monkeypatch, tmp_path, rows=[_row("2026-10-21T19:00:00Z", "2026-10-21T20:00:00Z")])
    monkeypatch.setattr(runner, "now_ms", lambda: _ms("2026-10-21T20:00:00Z"))
    code, report = runner.run_once(
        tmp_path, tmp_path / "out", timeout=30, retries=0, skip_observation=True
    )
    assert code == runner.EXIT_PENDING
    assert report["state"] == runner.STATE_NOT_DUE
    assert report["capture_decision_at_utc"] is None
    assert report["independent_verification"] == "PASS"
    assert not (tmp_path / "data" / "exp004a").exists()


def test_inside_the_window_without_a_closed_bar_is_pending_data(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """RFC case 5: a bar that is open but has not closed yet is not data."""
    # A store that is current but whose last bar closes before the window opens: the
    # observer is alive, and there is still nothing to capture.
    _patch_runner(
        monkeypatch,
        tmp_path,
        rows=[_row("2026-10-21T23:00:00Z", "2026-10-22T00:02:00Z")],
    )
    monkeypatch.setattr(runner, "now_ms", lambda: _ms("2026-10-22T00:30:00Z"))
    code, report = runner.run_once(
        tmp_path, tmp_path / "out", timeout=30, retries=0, skip_observation=True
    )
    assert code == runner.EXIT_PENDING
    assert report["state"] == runner.STATE_PENDING_DATA
    assert not (tmp_path / "data" / "exp004a").exists()


def test_a_stale_store_is_pending_freshness_and_not_pending_data(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """RFC case 4: the observer is fresh, the store is behind (L-04)."""
    # A bar that opens inside the window but whose series lags the clock by a day.
    _patch_runner(
        monkeypatch,
        tmp_path,
        rows=[_row("2026-10-22T00:00:00Z", "2026-10-22T00:05:00Z")],
    )
    monkeypatch.setattr(runner, "now_ms", lambda: _ms("2026-10-23T12:00:00Z"))
    code, report = runner.run_once(
        tmp_path, tmp_path / "out", timeout=30, retries=0, skip_observation=True
    )
    assert code == runner.EXIT_PENDING
    assert report["state"] == runner.STATE_PENDING_FRESHNESS
    assert not (tmp_path / "data" / "exp004a").exists()


def test_a_capture_publishes_and_the_guard_admits_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """RFC case 2 with data: a closed bar inside the window is captured and admitted."""
    # The bar opens at 00:00 and closes at 01:00; it can only be in the store after that,
    # so the attempt happens at 01:30 and the ingest is at 01:05.
    rows = [_row("2026-10-22T00:00:00Z", "2026-10-22T01:05:00Z")]
    _patch_runner(monkeypatch, tmp_path, rows=rows)
    monkeypatch.setattr(runner, "now_ms", lambda: _ms("2026-10-22T01:30:00Z"))
    monkeypatch.setattr(runner, "capture", _fake_capture(rows))

    code, report = runner.run_once(
        tmp_path, tmp_path / "out", timeout=30, retries=0, skip_observation=True
    )
    assert code == runner.EXIT_OK
    assert report["state"] == runner.STATE_CAPTURED_VERIFIED
    assert report["temporal_guards"][0]["verdict"] == "PASS"
    assert report["independent_verification"] == "PASS"


def test_a_capture_with_an_impossible_ingest_is_quarantined_and_left_on_disk(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """RFC case 6: the L-01 bar is rejected and the file is left alone."""
    rows = [_row("2026-10-22T00:00:00Z", "2026-10-22T05:00:00Z")]
    _patch_runner(monkeypatch, tmp_path, rows=rows)
    monkeypatch.setattr(runner, "now_ms", lambda: _ms("2026-10-22T01:30:00Z"))
    monkeypatch.setattr(runner, "capture", _fake_capture(rows))

    code, report = runner.run_once(
        tmp_path, tmp_path / "out", timeout=30, retries=0, skip_observation=True
    )
    assert code == runner.EXIT_QUARANTINED
    assert report["state"] == runner.STATE_QUARANTINED
    assert (tmp_path / "data" / "exp004a" / f"{DATASET_ID}.jsonl").is_file()
    assert any(
        item["code"] == "INGEST_AFTER_DECISION"
        for item in report["temporal_guards"][0]["violations"]
    )


def test_a_dataset_that_is_already_published_is_not_captured_again(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """RFC case 11: the second attempt does not publish a second time."""
    rows = [_row("2026-10-22T00:00:00Z", "2026-10-22T01:05:00Z")]
    _patch_runner(monkeypatch, tmp_path, rows=rows)
    monkeypatch.setattr(runner, "now_ms", lambda: _ms("2026-10-22T01:30:00Z"))
    published = tmp_path / "data" / "exp004a" / f"{DATASET_ID}.jsonl"
    _write_jsonl(published, rows)

    def refuse(repo: Path, slice_: runner.Slice, *, timeout: int, log_dir: Any = None) -> dict[str, Any]:
        raise AssertionError("the extractor must not be invoked over a published dataset")

    monkeypatch.setattr(runner, "capture", refuse)
    code, report = runner.run_once(
        tmp_path, tmp_path / "out", timeout=30, retries=0, skip_observation=True
    )
    assert code == runner.EXIT_OK
    assert report["captures"][0]["exit_meaning"] == "ALREADY_PUBLISHED"


def test_a_partially_published_series_is_never_a_global_pass(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """RFC case 3: BTC is fine, ETH and SOL are not there. No global PASS."""
    rows = [_row("2026-10-22T00:00:00Z", "2026-10-22T01:05:00Z")]
    slices = (
        _slice(asset="BTC"),
        _slice(asset="ETH", dataset_id="EXP-004A-1H-ETH"),
        _slice(asset="SOL", dataset_id="EXP-004A-1H-SOL"),
    )
    _patch_runner(monkeypatch, tmp_path, rows=rows, slices=slices)
    monkeypatch.setattr(runner, "now_ms", lambda: _ms("2026-10-22T01:30:00Z"))

    def capture(repo: Path, slice_: runner.Slice, *, timeout: int, log_dir: Any = None) -> dict[str, Any]:
        if slice_.asset != "BTC":
            # No eligible bars for the other two series: exit 3, nothing written.
            return {
                "command": slice_.generator_command,
                "exit_code": 3,
                "slice": slice_.spec,
                "dataset_id": slice_.dataset_id,
                "dataset_path": slice_.normalized_file,
                "dataset_exists": False,
                "dataset_bytes": 0,
                "dataset_sha256": None,
                "manifest_exists": False,
                "exit_meaning": "NO_ELIGIBLE_BARS",
            }
        return _fake_capture(rows)(repo, slice_, timeout=timeout, log_dir=log_dir)

    monkeypatch.setattr(runner, "capture", capture)
    code, report = runner.run_once(
        tmp_path, tmp_path / "out", timeout=30, retries=0, skip_observation=True
    )
    assert code == runner.EXIT_FAILED
    assert report["state"] == runner.STATE_FAILED_OR_PENDING
    assert report["state"] != runner.STATE_CAPTURED_VERIFIED


def test_an_exit_zero_without_a_dataset_is_a_failure_not_a_capture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """RFC case 9: exit 0 with no output is the false success."""
    rows = [_row("2026-10-22T00:00:00Z", "2026-10-22T01:05:00Z")]
    _patch_runner(monkeypatch, tmp_path, rows=rows)
    monkeypatch.setattr(runner, "now_ms", lambda: _ms("2026-10-22T01:30:00Z"))
    monkeypatch.setattr(runner, "capture", _fake_capture(rows, exit_code=0, publish=False))

    code, report = runner.run_once(
        tmp_path, tmp_path / "out", timeout=30, retries=0, skip_observation=True
    )
    assert code == runner.EXIT_FAILED
    assert report["state"] == runner.STATE_FAILED_OR_PENDING
    assert report["captures"][0]["exit_meaning"] == "EXIT_WITHOUT_OUTPUT"
    assert runner.capture_ok(report["captures"][0]) is False


@pytest.mark.parametrize(
    ("exit_code", "meaning"),
    [
        (0, "OK"),
        (2, "CONTRACT_REFUSED"),
        (3, "NO_ELIGIBLE_BARS"),
        (4, "SOURCE_UNREADABLE"),
        (5, "NOT_ELIGIBLE"),
    ],
)
def test_the_extractors_exit_codes_are_read_as_the_contract_says(
    exit_code: int, meaning: str
) -> None:
    """RFC case 9: the contract's exit codes are named, not re-interpreted."""
    assert runner.CAPTURE_EXIT[exit_code] == meaning


def test_an_unreadable_source_is_retried_a_bounded_number_of_times(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """RFC case 9 and AC-05: retries are finite and audited."""
    rows = [_row("2026-10-22T00:00:00Z", "2026-10-22T01:05:00Z")]
    _patch_runner(monkeypatch, tmp_path, rows=rows)
    monkeypatch.setattr(runner, "now_ms", lambda: _ms("2026-10-22T01:30:00Z"))
    monkeypatch.setattr(runner, "time", _NoSleep(time))
    calls: list[int] = []

    def capture(repo: Path, slice_: runner.Slice, *, timeout: int, log_dir: Any = None) -> dict[str, Any]:
        calls.append(slice_.spec)
        return {
            "command": slice_.generator_command,
            "exit_code": 4,
            "slice": slice_.spec,
            "dataset_id": slice_.dataset_id,
            "dataset_path": slice_.normalized_file,
            "dataset_exists": False,
            "dataset_bytes": 0,
            "dataset_sha256": None,
            "manifest_exists": False,
            "exit_meaning": "SOURCE_UNREADABLE",
        }

    monkeypatch.setattr(runner, "capture", capture)
    code, report = runner.run_once(
        tmp_path, tmp_path / "out", timeout=30, retries=2, skip_observation=True
    )
    # one attempt plus two retries
    assert len(calls) == 3
    assert code == runner.EXIT_FAILED
    assert report["state"] == runner.STATE_FAILED_OR_PENDING


def test_a_broken_freeze_blocks_before_the_extractor_is_invoked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """RFC case 8: a declaration or generator whose hash does not match blocks."""
    rows = [_row("2026-10-22T00:00:00Z", "2026-10-22T01:05:00Z")]
    _patch_runner(monkeypatch, tmp_path, rows=rows, preflight_status="BLOCKED")
    monkeypatch.setattr(runner, "now_ms", lambda: _ms("2026-10-22T01:30:00Z"))

    def refuse(repo: Path, slice_: runner.Slice, *, timeout: int, log_dir: Any = None) -> dict[str, Any]:
        raise AssertionError("the extractor must not run while the freeze does not bind")

    monkeypatch.setattr(runner, "capture", refuse)
    code, report = runner.run_once(
        tmp_path, tmp_path / "out", timeout=30, retries=0, skip_observation=True
    )
    assert code == runner.EXIT_BLOCKED
    assert report["state"] == runner.STATE_BLOCKED_INTEGRITY
    assert not (tmp_path / "data" / "exp004a").exists()


def test_a_preflight_status_the_runner_does_not_know_blocks_the_capture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The runner reads the 02E contract's own vocabulary; it does not invent one.

    ``PASS`` is what a reader expects a passing preflight to say, and the 02E program
    never says it for a window that is open: it says ``WINDOW_OPEN``. A runner that
    accepts ``PASS`` would be accepting a status the contract does not define, so the
    unknown status has to block instead of being translated into consent.
    """
    rows = [_row("2026-10-22T00:00:00Z", "2026-10-22T01:05:00Z")]
    declaration = _patch_runner(monkeypatch, tmp_path, rows=rows, preflight_status="PASS")
    monkeypatch.setattr(runner, "now_ms", lambda: _ms("2026-10-22T01:30:00Z"))

    def refuse(repo: Path, slice_: runner.Slice, *, timeout: int, log_dir: Any = None) -> dict[str, Any]:
        raise AssertionError("an unrecognised preflight status is not an authorisation")

    monkeypatch.setattr(runner, "capture", refuse)
    code, report = runner.run_once(
        tmp_path, tmp_path / "out", timeout=30, retries=0, skip_observation=True
    )
    assert runner.PREFLIGHT_ACCEPTED == ("WINDOW_OPEN", "READY_FOR_WINDOW")
    assert code == runner.EXIT_BLOCKED
    assert report["state"] == runner.STATE_BLOCKED_INTEGRITY
    assert not (tmp_path / "data" / "exp004a").exists()
    assert declaration is not None


def test_the_claim_is_on_disk_before_the_verifier_reads_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The verifier is handed a file, so the file has to exist first."""
    rows = [_row("2026-10-22T00:00:00Z", "2026-10-22T01:05:00Z")]
    _patch_runner(monkeypatch, tmp_path, rows=rows)
    monkeypatch.setattr(runner, "now_ms", lambda: _ms("2026-10-22T01:30:00Z"))
    monkeypatch.setattr(runner, "capture", _fake_capture(rows))
    seen: dict[str, Any] = {}

    def spy_verifier(
        repo: Path, out_dir: Path, *, timeout: int, report_name: str, log_dir: Any = None
    ) -> dict[str, Any]:
        seen["report_name"] = report_name
        seen["existed"] = (out_dir / report_name).is_file()
        seen["state"] = json.loads((out_dir / report_name).read_text(encoding="utf-8"))["state"]
        return {"command": "verify02f", "exit_code": 0, "verifier_status": "PASS"}

    monkeypatch.setattr(runner, "verify_02f", spy_verifier)
    code, report = runner.run_once(
        tmp_path, tmp_path / "out", timeout=30, retries=0, skip_observation=True
    )
    assert code == runner.EXIT_OK
    assert seen["report_name"] == runner.CLAIM_REPORT
    assert seen["existed"] is True
    assert seen["state"] == runner.STATE_INDEPENDENT_VERIFY
    run_dir = tmp_path / "out" / runner.EVIDENCE_DIR / str(report["run_id"])
    assert report["verified_claim"]["sha256"] == hashlib.sha256(
        (run_dir / runner.CLAIM_REPORT).read_bytes()
    ).hexdigest()


def test_every_attempt_gets_its_own_directory_and_its_own_verdict(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Two attempts never share a directory, and a seal is never overwritten."""
    rows = [_row("2026-10-22T00:00:00Z", "2026-10-22T01:05:00Z")]
    _patch_runner(monkeypatch, tmp_path, rows=rows)
    monkeypatch.setattr(runner, "now_ms", lambda: _ms("2026-10-22T01:30:00Z"))
    monkeypatch.setattr(runner, "capture", _fake_capture(rows))
    out = tmp_path / "out"

    first_code, first = runner.run_once(
        tmp_path, out, timeout=30, retries=0, skip_observation=True
    )
    second_code, second = runner.run_once(
        tmp_path, out, timeout=30, retries=0, skip_observation=True
    )
    assert first_code == second_code == runner.EXIT_OK
    assert first["run_id"] != second["run_id"]
    runs = sorted(p.name for p in (out / runner.EVIDENCE_DIR).iterdir() if p.is_dir())
    assert len(runs) == 2
    for run in runs:
        assert (out / runner.EVIDENCE_DIR / run / runner.RUN_REPORT).is_file()
        assert (out / runner.EVIDENCE_DIR / run / runner.CLAIM_REPORT).is_file()
    pointer = json.loads((out / runner.LATEST_RUN).read_text(encoding="utf-8"))
    assert pointer["run_id"] == second["run_id"]


def test_resume_reconciles_without_publishing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rows = [_row("2026-10-22T00:00:00Z", "2026-10-22T01:05:00Z")]
    _patch_runner(monkeypatch, tmp_path, rows=rows)
    monkeypatch.setattr(runner, "now_ms", lambda: _ms("2026-10-22T01:30:00Z"))
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    (out / runner.LATEST_RUN).write_text(
        json.dumps({"state": "PENDING_DATA", "started_at_utc": "2026-10-21T20:00:00Z"}),
        encoding="utf-8",
    )
    resume = runner.run_resume(tmp_path, out)
    assert resume["previous_state"] == "PENDING_DATA"
    assert resume["published_count"] == 0
    assert not (tmp_path / "data" / "exp004a").exists()


def test_resume_finds_the_attempts_a_previous_crash_left_behind(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """RFC case 11: a crash between the capture and the seal is reconciled."""
    rows = [_row("2026-10-22T00:00:00Z", "2026-10-22T01:05:00Z")]
    _patch_runner(monkeypatch, tmp_path, rows=rows)
    monkeypatch.setattr(runner, "now_ms", lambda: _ms("2026-10-22T01:30:00Z"))
    monkeypatch.setattr(runner, "capture", _fake_capture(rows))
    out = tmp_path / "out"
    runner.run_once(tmp_path, out, timeout=30, retries=0, skip_observation=True)

    # The crash: the run directory survives with its claim but without its report.
    run_dir = next((out / runner.EVIDENCE_DIR).iterdir())
    (run_dir / runner.RUN_REPORT).unlink()

    resume = runner.run_resume(tmp_path, out)
    assert resume["attempt_count"] == 1
    assert resume["published_count"] == 1
    # A second attempt over the published dataset is a no-op, not a second publication.
    code, report = runner.run_once(
        tmp_path, out, timeout=30, retries=0, skip_observation=True
    )
    assert code == runner.EXIT_OK
    assert report["captures"][0]["exit_meaning"] == "ALREADY_PUBLISHED"


def test_a_second_runner_does_not_run_while_the_lock_is_held(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """RFC case 10: two simultaneous runs are one run, not two."""
    rows = [_row("2026-10-22T00:00:00Z", "2026-10-22T01:05:00Z")]
    _patch_runner(monkeypatch, tmp_path, rows=rows)
    monkeypatch.setattr(runner, "now_ms", lambda: _ms("2026-10-22T01:30:00Z"))
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    (out / runner.LOCK_NAME).write_text(
        json.dumps({"pid": 4242, "acquired_at_utc": "2026-10-22T01:29:00Z"}),
        encoding="utf-8",
    )
    code = runner.main(["--once", "--repo", str(tmp_path), "--out-dir", str(out)])
    assert code == runner.EXIT_ALREADY_RUNNING
    assert not (tmp_path / "data" / "exp004a").exists()


def test_two_attempts_never_share_a_run_id() -> None:
    first = runner.new_run_id(_ms("2026-10-22T01:30:00Z"))
    second = runner.new_run_id(_ms("2026-10-22T01:30:00Z"))
    assert first != second
    assert first.startswith("20261022T013000Z-")


def test_check_writes_nothing_at_all(tmp_path: Path) -> None:
    """RFC case 14: the diagnostic mode does not touch the sealed artefacts."""
    before = sorted(path.name for path in tmp_path.iterdir())
    runner.run_check(REPO)
    assert sorted(path.name for path in tmp_path.iterdir()) == before


# --------------------------------------------------------------------------- #
# the gates, the freeze and the seals
# --------------------------------------------------------------------------- #


def test_the_report_keeps_the_gates_where_they_were(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """RFC case 15 and AC-09/AC-10: no gate moves and C-013 is not promoted."""
    rows = [_row("2026-10-22T00:00:00Z", "2026-10-22T01:05:00Z")]
    _patch_runner(monkeypatch, tmp_path, rows=rows)
    monkeypatch.setattr(runner, "now_ms", lambda: _ms("2026-10-22T01:30:00Z"))
    monkeypatch.setattr(runner, "capture", _fake_capture(rows))
    code, report = runner.run_once(
        tmp_path, tmp_path / "out", timeout=30, retries=0, skip_observation=True
    )
    assert code == runner.EXIT_OK
    for name, value in LOCKED_GATES.items():
        assert report["gates"][name] == value
    assert report["gates"]["C_013"] == "TIME_PROOF_WEAK"
    assert report["economic_executions"] == 0


def test_the_runner_and_the_verifier_cannot_place_an_order() -> None:
    """RFC case 15: zero order requests, zero paper orders, by construction."""
    forbidden = (
        "place_order",
        "create_order",
        "submit_order",
        "paper_order",
        "broker",
        "trading_bot.paper",
        "trading_bot.execution",
    )
    for name in ("exp004a_wp051_02f_runner.py", "exp004a_wp051_02f_verify.py"):
        source = (REPO / "scripts" / name).read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in source, f"{name} mentions {token}"


def test_the_report_separates_the_two_hash_magnitudes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """RFC case 13: a SHA-256 of the checkout and a Git blob id are not the same thing."""
    rows = [_row("2026-10-22T00:00:00Z", "2026-10-22T01:05:00Z")]
    _patch_runner(monkeypatch, tmp_path, rows=rows)
    # The report hashes the generator's bytes in *its* checkout, so the fixture repository
    # has to hold a byte-identical copy of the frozen extractor.
    target = tmp_path / runner.GENERATOR
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(REPO / runner.GENERATOR, target)
    monkeypatch.setattr(runner, "now_ms", lambda: _ms("2026-10-22T01:30:00Z"))
    monkeypatch.setattr(runner, "capture", _fake_capture(rows))
    code, report = runner.run_once(
        tmp_path, tmp_path / "out", timeout=30, retries=0, skip_observation=True
    )
    assert code == runner.EXIT_OK
    declaration = report["declaration"]
    assert "worktree_sha256" in declaration
    assert "git_blob_sha" in declaration
    assert "hash_note" in declaration
    generator = report["generator"]
    assert generator["frozen_blob_sha256"] == verifier.GENERATOR_SHA256
    assert generator["worktree_sha256"] == verifier.GENERATOR_SHA256
    assert generator["frozen_commit"] == verifier.GENERATOR_COMMIT


def test_a_git_blob_id_is_not_a_sha256_of_the_checkout() -> None:
    """RFC case 13, measured rather than asserted: the two ids are different objects."""
    blob = runner.git_blob_sha(REPO, runner.GENERATOR)
    assert blob is not None, "the generator must be committed for the freeze to be checkable"
    assert len(blob) == 40
    assert len(verifier.GENERATOR_SHA256) == 64
    assert blob != verifier.GENERATOR_SHA256
    assert runner.sha256_file(REPO / runner.GENERATOR) == verifier.GENERATOR_SHA256


def test_the_sealed_02d_and_02e_artefacts_are_not_touched_by_a_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """RFC case 14: the frozen packages are read, never written."""
    frozen: dict[str, str] = {}
    for package in ("wp051_02d", "wp051_02e"):
        root = REPO / "docs" / "agentic" / "exp004a" / package
        for path in sorted(root.rglob("*")):
            if path.is_file():
                frozen[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    assert frozen, "the frozen packages must exist for this control to mean anything"

    rows = [_row("2026-10-22T00:00:00Z", "2026-10-22T01:05:00Z")]
    _patch_runner(monkeypatch, tmp_path, rows=rows)
    monkeypatch.setattr(runner, "now_ms", lambda: _ms("2026-10-22T01:30:00Z"))
    monkeypatch.setattr(runner, "capture", _fake_capture(rows))
    runner.run_once(tmp_path, tmp_path / "out", timeout=30, retries=0, skip_observation=True)

    for path, digest in frozen.items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest, path


def test_the_preflight_is_asked_to_write_into_this_package_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """RFC case 14: the same program, a different output directory."""
    seen: dict[str, Any] = {}

    def fake_run_command(repo: Path, argv: list[str], **kwargs: Any) -> dict[str, Any]:
        seen["argv"] = argv
        return {"command": " ".join(argv), "exit_code": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(runner, "run_command", fake_run_command)
    runner.preflight(tmp_path, tmp_path / "out" / "reused_preflight", timeout=30)
    argv = seen["argv"]
    assert "--out-dir" in argv
    out_dir = Path(argv[argv.index("--out-dir") + 1])
    assert "wp051_02e" not in out_dir.as_posix()
    assert out_dir.as_posix().endswith("reused_preflight")


def test_the_seal_names_the_published_datasets_and_not_only_the_paper(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC-07: the artefacts the attempt produced are sealed with the same semantics.

    A manifest that listed only the package's own files would seal the description of a
    capture and not the capture. Each dataset is recorded with the digest the claim made
    beside the digest measured on disk, so a disagreement is visible rather than averaged.
    """
    rows = [_row("2026-10-22T00:00:00Z", "2026-10-22T01:05:00Z")]
    _patch_runner(monkeypatch, tmp_path, rows=rows)
    monkeypatch.setattr(runner, "now_ms", lambda: _ms("2026-10-22T01:30:00Z"))
    monkeypatch.setattr(runner, "capture", _fake_capture(rows))
    out = tmp_path / "out"
    code, report = runner.run_once(
        tmp_path, out, timeout=30, retries=0, skip_observation=True
    )
    assert code == runner.EXIT_OK
    seal_code, sealed = runner.seal(tmp_path, out, report["run_id"])
    assert seal_code == runner.EXIT_OK, sealed
    manifest = json.loads((out / runner.EVIDENCE_MANIFEST).read_text(encoding="utf-8"))
    datasets = [entry for entry in manifest["entries"] if entry.get("role") == "dataset"]
    assert len(datasets) == 1
    entry = datasets[0]
    assert entry["path"] == f"data/exp004a/{DATASET_ID}.jsonl"
    assert entry["present"] is True
    assert entry["matches_claim"] is True
    assert entry["sha256"] == entry["claimed_sha256"]
    assert "git_blob_sha" not in entry
    assert "never presented as the same one" in manifest["hash_semantics"]


def test_the_seal_promotes_one_run_and_refuses_to_overwrite_another(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rows = [_row("2026-10-22T00:00:00Z", "2026-10-22T01:05:00Z")]
    _patch_runner(monkeypatch, tmp_path, rows=rows)
    monkeypatch.setattr(runner, "now_ms", lambda: _ms("2026-10-22T01:30:00Z"))
    monkeypatch.setattr(runner, "capture", _fake_capture(rows))
    out = tmp_path / "out"
    runner.run_once(tmp_path, out, timeout=30, retries=0, skip_observation=True)
    runner.run_once(tmp_path, out, timeout=30, retries=0, skip_observation=True)

    code, payload = runner.seal(tmp_path, out, None)
    assert code == runner.EXIT_OK
    assert payload["ok"] is True
    assert (out / runner.RUN_REPORT).is_file()
    assert (out / runner.RUN_REPORT_MD).is_file()
    assert (out / runner.EVIDENCE_MANIFEST).is_file()
    manifest = json.loads((out / runner.EVIDENCE_MANIFEST).read_text(encoding="utf-8"))
    assert manifest["entry_count"] > 0
    assert all("sha256" in entry for entry in manifest["entries"])

    # A second seal of a different run is refused: a package whose evidence changes
    # underneath the reader is worse than a package with no seal.
    code, payload = runner.seal(tmp_path, out, sorted(p.name for p in (out / runner.EVIDENCE_DIR).iterdir())[0])
    assert code == runner.EXIT_BLOCKED
    assert payload["ok"] is False


# --------------------------------------------------------------------------- #
# the verifier's refusals
# --------------------------------------------------------------------------- #


def _package(
    tmp_path: Path,
    *,
    published: list[dict[str, Any]] | None,
    source: list[dict[str, Any]],
    decision_utc: str = "2026-10-22T01:00:00Z",
    state: str = "CAPTURED_VERIFIED",
    gates: dict[str, Any] | None = None,
    at_utc: str = "2026-10-22T01:00:30Z",
    captures: list[dict[str, Any]] | None = None,
    declared_row_count: int = 1,
) -> tuple[Path, Path, Path, int]:
    """A run report, a dataset and a source series that agree with each other."""
    run_dir = tmp_path / "run"
    dataset_dir = tmp_path / "datasets"
    run_dir.mkdir(parents=True, exist_ok=True)
    dataset_dir.mkdir(parents=True, exist_ok=True)
    source_path = tmp_path / "forward" / "1h" / "BTC.jsonl"
    _write_jsonl(source_path, source)

    dataset_path = dataset_dir / f"{DATASET_ID}.jsonl"
    if published is not None:
        _write_jsonl(dataset_path, published)
    report = {
        "state": state,
        "capture_decision_at_utc": decision_utc,
        "datasets": [
            {
                "dataset_id": DATASET_ID,
                "slice": f"{INTERVAL}:{ASSET}",
                "dataset_path": f"datasets/{DATASET_ID}.jsonl",
                "exists": published is not None,
                "bytes": dataset_path.stat().st_size if published is not None else 0,
                "sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest()
                if published is not None
                else None,
                "published_rows": len(published) if published is not None else 0,
                "declared_row_count": declared_row_count,
                "declared_coverage_required": 0.9,
                "fraction_of_declared": (
                    round(len(published) / declared_row_count, 6)
                    if published is not None and declared_row_count > 0
                    else None
                ),
                "coverage_status": (
                    "NOT_PUBLISHED"
                    if not published
                    else (
                        "AT_LEAST_DECLARED"
                        if declared_row_count > 0
                        and len(published) / declared_row_count >= 0.9
                        else "BELOW_DECLARED"
                    )
                ),
            }
        ],
        "store": [
            {
                "spec": f"{INTERVAL}:{ASSET}",
                "asset": ASSET,
                "interval": INTERVAL,
                "path": "forward/1h/BTC.jsonl",
                "rows": len(source),
            }
        ],
        "captures": captures
        if captures is not None
        else [
            {
                "slice": f"{INTERVAL}:{ASSET}",
                "dataset_id": DATASET_ID,
                "exit_code": 0,
                "dataset_path": f"datasets/{DATASET_ID}.jsonl",
            }
        ],
        "temporal_guards": [],
        "gates": gates
        if gates is not None
        else {
            "C_004": "PASS",
            "C_013": "TIME_PROOF_WEAK",
            "C_016": "UNREACHABLE_UNDER_DECLARED_COST_MODEL",
            "PAPER_VALIDATION": "NOT_PASS",
            "CERTIFICATION": "BLOCKED",
            "PROMOTION": "NO_PROMOTION",
        },
    }
    (run_dir / runner.RUN_REPORT).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return run_dir, dataset_dir, tmp_path, _ms(at_utc)


def _verdict(checks: list[verifier.Check], check_id: str) -> str:
    for item in checks:
        if item.check_id == check_id:
            return item.status
    raise AssertionError(f"no check named {check_id}")


def test_coverage_is_named_rather_than_averaged() -> None:
    """14 rows of a 2160-row declaration is not 90 % of anything.

    The frozen extractor does not enforce ``coverage_required`` and writes a dataset once, so
    a capture taken before the declared period elapses freezes a short file. The runner may
    not call that complete, and the verifier recomputes it from the bytes.
    """
    assert runner.coverage_status(1944, 2160, 0.9) == "AT_LEAST_DECLARED"
    assert runner.coverage_status(14, 2160, 0.9) == "BELOW_DECLARED"
    assert runner.coverage_status(0, 2160, 0.9) == "NOT_PUBLISHED"
    assert runner.coverage_status(5, 0, 0.9) == "DECLARED_COUNT_UNKNOWN"


def test_a_short_dataset_is_claimed_as_short(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rows = [_row("2026-10-22T00:00:00Z", "2026-10-22T01:05:00Z")]
    declaration = _patch_runner(monkeypatch, tmp_path, rows=rows)
    declaration = replace(
        declaration,
        slices=tuple(replace(item, declared_row_count=2160) for item in declaration.slices),
    )
    monkeypatch.setattr(runner, "load_declaration", lambda repo: declaration)
    monkeypatch.setattr(runner, "now_ms", lambda: _ms("2026-10-22T01:30:00Z"))
    monkeypatch.setattr(runner, "capture", _fake_capture(rows))
    code, report = runner.run_once(
        tmp_path, tmp_path / "out", timeout=30, retries=0, skip_observation=True
    )
    assert code == runner.EXIT_OK
    dataset = report["datasets"][0]
    assert dataset["published_rows"] == 1
    assert dataset["declared_row_count"] == 2160
    assert dataset["coverage_status"] == "BELOW_DECLARED"
    assert any("cannot be extended" in note for note in report["notes"])


def test_the_verifier_rejects_a_claim_that_rounds_a_shortfall_away(tmp_path: Path) -> None:
    rows = [_row("2026-10-22T00:00:00Z", "2026-10-22T00:05:00Z")]
    run_dir, dataset_dir, source_root, at_ms = _package(
        tmp_path, published=rows, source=rows, declared_row_count=2160
    )
    report_path = run_dir / runner.RUN_REPORT
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["datasets"][0]["coverage_status"] = "AT_LEAST_DECLARED"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    checks, status = verifier.verify(
        run_dir,
        REPO,
        dataset_dir=dataset_dir,
        source_root=source_root,
        at_ms=at_ms,
        skip_sealed_reverification=True,
    )
    assert status == "FAIL"
    assert _verdict(checks, "COVERAGE_DECLARED_VS_PUBLISHED") == "FAIL"


def test_the_verifier_blocks_when_there_is_no_claim_to_test(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    checks, status = verifier.verify(
        run_dir, REPO, dataset_dir=tmp_path, skip_sealed_reverification=True
    )
    assert status == "BLOCKED"
    assert _verdict(checks, "RUN_REPORT_PRESENT") == "BLOCKED"


def test_the_verifier_accepts_an_admissible_package(tmp_path: Path) -> None:
    rows = [_row("2026-10-22T00:00:00Z", "2026-10-22T00:05:00Z")]
    run_dir, dataset_dir, source_root, at_ms = _package(tmp_path, published=rows, source=rows)
    checks, status = verifier.verify(
        run_dir,
        REPO,
        dataset_dir=dataset_dir,
        source_root=source_root,
        at_ms=at_ms,
        skip_sealed_reverification=True,
    )
    assert status == "PASS", [item.as_dict() for item in checks if item.status != "PASS"]


def test_the_verifier_rejects_a_capture_decision_in_the_future(tmp_path: Path) -> None:
    rows = [_row("2026-10-22T00:00:00Z", "2026-10-22T00:05:00Z")]
    run_dir, dataset_dir, source_root, at_ms = _package(
        tmp_path,
        published=rows,
        source=rows,
        decision_utc="2026-10-25T00:00:00Z",
        at_utc="2026-10-22T01:00:30Z",
    )
    checks, status = verifier.verify(
        run_dir,
        REPO,
        dataset_dir=dataset_dir,
        source_root=source_root,
        at_ms=at_ms,
        skip_sealed_reverification=True,
    )
    assert status == "FAIL"
    assert _verdict(checks, "DECISION_INSTANT_NOT_IN_FUTURE") == "FAIL"


def test_the_verifier_rejects_a_row_ingested_after_the_decision(tmp_path: Path) -> None:
    published = [_row("2026-10-22T00:00:00Z", "2026-10-22T03:00:00Z")]
    source = [_row("2026-10-22T00:00:00Z", "2026-10-22T03:00:00Z")]
    run_dir, dataset_dir, source_root, at_ms = _package(
        tmp_path,
        published=published,
        source=source,
        decision_utc="2026-10-22T01:00:00Z",
        at_utc="2026-10-22T04:00:00Z",
    )
    checks, status = verifier.verify(
        run_dir,
        REPO,
        dataset_dir=dataset_dir,
        source_root=source_root,
        at_ms=at_ms,
        skip_sealed_reverification=True,
    )
    assert status == "FAIL"
    assert _verdict(checks, "ROWS_ADMISSIBLE") == "FAIL"


def test_the_verifier_rejects_a_row_the_store_never_held(tmp_path: Path) -> None:
    published = [_row("2026-10-22T00:00:00Z", "2026-10-22T00:05:00Z")]
    source = [_row("2026-10-22T01:00:00Z", "2026-10-22T01:05:00Z")]
    run_dir, dataset_dir, source_root, at_ms = _package(
        tmp_path, published=published, source=source
    )
    checks, status = verifier.verify(
        run_dir,
        REPO,
        dataset_dir=dataset_dir,
        source_root=source_root,
        at_ms=at_ms,
        skip_sealed_reverification=True,
    )
    assert status == "FAIL"
    assert _verdict(checks, "SOURCE_COMPARED") == "FAIL"


def test_the_verifier_rejects_a_row_that_was_edited_on_the_way_out(tmp_path: Path) -> None:
    published = [_row("2026-10-22T00:00:00Z", "2026-10-22T00:05:00Z", close=999.0)]
    source = [_row("2026-10-22T00:00:00Z", "2026-10-22T00:05:00Z", close=101.0)]
    run_dir, dataset_dir, source_root, at_ms = _package(
        tmp_path, published=published, source=source
    )
    checks, status = verifier.verify(
        run_dir,
        REPO,
        dataset_dir=dataset_dir,
        source_root=source_root,
        at_ms=at_ms,
        skip_sealed_reverification=True,
    )
    assert status == "FAIL"
    assert _verdict(checks, "SOURCE_COMPARED") == "FAIL"


def test_the_verifier_rejects_a_promoted_gate(tmp_path: Path) -> None:
    rows = [_row("2026-10-22T00:00:00Z", "2026-10-22T00:05:00Z")]
    gates = {
        "C_004": "PASS",
        "C_013": "TIME_PROOF_WEAK",
        "C_016": "UNREACHABLE_UNDER_DECLARED_COST_MODEL",
        "PAPER_VALIDATION": "PASS",
        "CERTIFICATION": "BLOCKED",
        "PROMOTION": "NO_PROMOTION",
    }
    run_dir, dataset_dir, source_root, at_ms = _package(
        tmp_path, published=rows, source=rows, gates=gates
    )
    checks, status = verifier.verify(
        run_dir,
        REPO,
        dataset_dir=dataset_dir,
        source_root=source_root,
        at_ms=at_ms,
        skip_sealed_reverification=True,
    )
    assert status == "FAIL"
    assert _verdict(checks, "GATE_PAPER_VALIDATION") == "FAIL"


def test_the_verifier_refuses_to_promote_the_time_proof(tmp_path: Path) -> None:
    """RFC case 7: a stored hour is not a comparable timestamp source for C-013."""
    rows = [_row("2026-10-22T00:00:00Z", "2026-10-22T00:05:00Z")]
    gates = {
        "C_004": "PASS",
        "C_013": "PASS",
        "C_016": "UNREACHABLE_UNDER_DECLARED_COST_MODEL",
        "PAPER_VALIDATION": "NOT_PASS",
        "CERTIFICATION": "BLOCKED",
        "PROMOTION": "NO_PROMOTION",
    }
    run_dir, dataset_dir, source_root, at_ms = _package(
        tmp_path, published=rows, source=rows, gates=gates
    )
    checks, status = verifier.verify(
        run_dir,
        REPO,
        dataset_dir=dataset_dir,
        source_root=source_root,
        at_ms=at_ms,
        skip_sealed_reverification=True,
    )
    assert status == "FAIL"
    assert _verdict(checks, "GATE_C_013") == "FAIL"


def test_a_crlf_checkout_is_not_reported_as_freeze_drift(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """RFC case 13: the two hash magnitudes are compared with the right semantics.

    A working tree that checks the generator out with CRLF has different bytes and the
    same Git object. The runner hashes those bytes for the record and must not turn the
    difference into a drift verdict: the freeze is compared on Git objects by the
    preflight, and this file only reports what it measured.
    """
    rows = [_row("2026-10-22T00:00:00Z", "2026-10-22T01:05:00Z")]
    _patch_runner(monkeypatch, tmp_path, rows=rows)
    target = tmp_path / runner.GENERATOR
    target.parent.mkdir(parents=True, exist_ok=True)
    lf = (REPO / runner.GENERATOR).read_bytes()
    crlf = lf.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    target.write_bytes(crlf)
    assert hashlib.sha256(crlf).hexdigest() != verifier.GENERATOR_SHA256
    monkeypatch.setattr(runner, "now_ms", lambda: _ms("2026-10-22T01:30:00Z"))
    monkeypatch.setattr(runner, "capture", _fake_capture(rows))

    code, report = runner.run_once(
        tmp_path, tmp_path / "out", timeout=30, retries=0, skip_observation=True
    )
    assert code == runner.EXIT_OK
    generator = report["generator"]
    assert generator["worktree_sha256"] == hashlib.sha256(crlf).hexdigest()
    assert generator["worktree_sha256"] != generator["frozen_blob_sha256"]
    assert "CRLF" in report["declaration"]["hash_note"]
    assert report["state"] == runner.STATE_CAPTURED_VERIFIED


def test_the_verifier_rejects_a_claim_of_success_with_nothing_behind_it(tmp_path: Path) -> None:
    run_dir, dataset_dir, source_root, at_ms = _package(
        tmp_path, published=None, source=[], state="CAPTURED_VERIFIED"
    )
    checks, status = verifier.verify(
        run_dir,
        REPO,
        dataset_dir=dataset_dir,
        source_root=source_root,
        at_ms=at_ms,
        skip_sealed_reverification=True,
    )
    assert status == "FAIL"
    assert _verdict(checks, "NO_FALSE_SUCCESS") == "FAIL"


def test_the_verifier_rejects_an_exit_zero_without_a_dataset(tmp_path: Path) -> None:
    """RFC case 9: the report says 0, the disk says nothing is there."""
    rows = [_row("2026-10-22T00:00:00Z", "2026-10-22T00:05:00Z")]
    run_dir, dataset_dir, source_root, at_ms = _package(
        tmp_path,
        published=None,
        source=rows,
        state="CAPTURED_VERIFIED",
        captures=[
            {
                "slice": f"{INTERVAL}:{ASSET}",
                "dataset_id": DATASET_ID,
                "exit_code": 0,
                "dataset_path": f"datasets/{DATASET_ID}.jsonl",
            }
        ],
    )
    checks, status = verifier.verify(
        run_dir,
        REPO,
        dataset_dir=dataset_dir,
        source_root=source_root,
        at_ms=at_ms,
        skip_sealed_reverification=True,
    )
    assert status == "FAIL"
    assert _verdict(checks, "CAPTURE_OUTPUT_PRESENT") == "FAIL"


def test_the_verifier_rejects_a_dataset_whose_digest_does_not_match_the_claim(
    tmp_path: Path,
) -> None:
    rows = [_row("2026-10-22T00:00:00Z", "2026-10-22T00:05:00Z")]
    run_dir, dataset_dir, source_root, at_ms = _package(
        tmp_path, published=rows, source=rows
    )
    report_path = run_dir / runner.RUN_REPORT
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["datasets"][0]["sha256"] = "0" * 64
    report_path.write_text(json.dumps(report), encoding="utf-8")
    checks, status = verifier.verify(
        run_dir,
        REPO,
        dataset_dir=dataset_dir,
        source_root=source_root,
        at_ms=at_ms,
        skip_sealed_reverification=True,
    )
    assert status == "FAIL"
    assert _verdict(checks, "DATASET_PRESENT") == "FAIL"


def test_the_verifier_refuses_a_tampered_generator(tmp_path: Path) -> None:
    """RFC case 8: the freeze must be the objects the preregistration named."""
    fake_repo = tmp_path / "repo"
    (fake_repo / "scripts").mkdir(parents=True)
    (fake_repo / "config" / "preregistrations").mkdir(parents=True)
    (fake_repo / "scripts" / "exp004a_capture.py").write_text("# tampered\n", encoding="utf-8")
    (fake_repo / "config" / "preregistrations" / "EXP-004A.datasets.phase2.json").write_text(
        json.dumps({"supersedes": {"sha256": verifier.PHASE1_SHA256}}), encoding="utf-8"
    )
    checks = verifier.check_freeze(fake_repo)
    assert _verdict(checks, "GENERATOR_WORKTREE_UNCHANGED") == "FAIL"
    assert _verdict(checks, "GENERATOR_BLOB") == "FAIL"


def test_the_sealed_02e_bytes_are_checked_against_their_own_manifest(tmp_path: Path) -> None:
    """RFC case 14: the frozen package is judged by bytes, not by re-running its clock."""
    package = tmp_path / "docs" / "agentic" / "exp004a" / "wp051_02e"
    package.mkdir(parents=True)
    artefact = package / "RUN_REPORT.json"
    artefact.write_text('{"state": "PENDING_WINDOW"}\n', encoding="utf-8")
    manifest = {
        "entries": [
            {
                "path": "docs/agentic/exp004a/wp051_02e/RUN_REPORT.json",
                "sha256": hashlib.sha256(artefact.read_bytes()).hexdigest(),
            }
        ]
    }
    (package / "EVIDENCE_MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")

    assert verifier.sealed_02e_integrity(tmp_path).status == "PASS"
    artefact.write_text('{"state": "CAPTURED_VERIFIED"}\n', encoding="utf-8")
    drifted = verifier.sealed_02e_integrity(tmp_path)
    assert drifted.status == "FAIL"
    assert drifted.evidence["drifted"] == ["docs/agentic/exp004a/wp051_02e/RUN_REPORT.json"]
    artefact.unlink()
    assert verifier.sealed_02e_integrity(tmp_path).status == "FAIL"


def test_a_sealed_02e_verdict_that_expired_with_the_clock_is_not_a_regression() -> None:
    """The 02E controls that assert a closed window cannot pass twice.

    Re-running 02E after the window opens is not the same question as whether 02E's
    bytes are still the ones it sealed. The first is answered by naming the expired
    controls; the second by hashing the manifest, which the test above does.
    """
    verdict, detail = verifier.classify_sealed_02e(2, "FAIL", ["V-TEMP-01", "V-TEMP-02"])
    assert verdict == "PASS"
    assert "V-TEMP-01" in detail and "not a re-certification" in detail


@pytest.mark.parametrize(
    ("exit_code", "failed"),
    [
        (2, ["V-TEMP-01", "V-ART-01"]),
        (2, ["V-UNKNOWN-99"]),
        (2, []),
        (1, []),
    ],
)
def test_a_sealed_02e_verdict_that_regressed_or_was_not_understood_fails(
    exit_code: int, failed: list[str]
) -> None:
    verdict, _ = verifier.classify_sealed_02e(exit_code, "FAIL", failed)
    assert verdict == "FAIL"


def test_the_verifier_does_not_import_the_runner_or_the_package_it_verifies() -> None:
    import ast

    tree = ast.parse(
        (REPO / "scripts" / "exp004a_wp051_02f_verify.py").read_text(encoding="utf-8")
    )
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert not [name for name in imported if "trading_bot" in name]
    assert not [name for name in imported if "exp004a_wp051_02f_runner" in name]


def test_the_verifier_can_be_run_as_its_own_process(tmp_path: Path) -> None:
    """RFC case 12: the independent verifier is re-run over the published bytes."""
    rows = [_row("2026-10-22T00:00:00Z", "2026-10-22T00:05:00Z")]
    run_dir, dataset_dir, source_root, _at_ms = _package(tmp_path, published=rows, source=rows)
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/exp004a_wp051_02f_verify.py",
            "--run-dir",
            str(run_dir),
            "--repo",
            str(REPO),
            "--dataset-dir",
            str(dataset_dir),
            "--source-root",
            str(source_root),
            "--out",
            str(tmp_path / "verification.json"),
            "--skip-sealed-reverification",
        ],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == verifier.EXIT_PASS, completed.stdout + completed.stderr
    payload = json.loads((tmp_path / "verification.json").read_text(encoding="utf-8"))
    assert payload["status"] == "PASS"
    assert payload["temporal_proof"] == "TIME_PROOF_WEAK"
    assert payload["economic_executions"] == 0
