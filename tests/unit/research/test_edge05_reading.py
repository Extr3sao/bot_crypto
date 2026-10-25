"""WP-EDGE-05R — the reading snapshot, held to the promise the reports make.

The promise is narrow and checkable: every figure says when it was read and which artefact it came
from, and a snapshot edited after it was taken cannot be rendered. These tests are about that
promise rather than about the collection itself, because a report that is *usually* consistent is
the defect this work package exists to remove.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from trading_bot.research.edge05 import reading as R

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_script(name: str) -> Any:
    path = REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def report_script() -> Any:
    return _load_script("edge05r_report")


def _lane(root: Path, *, rows: int = 2, blocked: bool = False) -> Path:
    """A minimal lane state root: a run log and nothing else, which is all a reading needs."""
    lane = root / "lane"
    lane.mkdir(parents=True, exist_ok=True)
    for index in range(rows):
        if blocked:
            row = {
                "run_id": "FWD-EDGE04-9",
                "outcome": "DISK_BUDGET_EXCEEDED",
                "new_bars": 0,
                "market_requests": 0,
                "exit_code": 5,
                "started_at_utc": "2026-10-13T22:00:00Z",
                "finished_at_utc": "2026-10-13T22:00:30Z",
                "disk": {"free_bytes": 1_700_000_000, "status": "CRITICAL"},
            }
        else:
            row = {
                "run_id": f"FWD-EDGE04-{index}",
                "outcome": "OBSERVED" if index % 2 == 0 else "NO_NEW_DATA",
                "new_bars": 6,
                "market_requests": 7,
                "exit_code": 0,
                "slot_key": f"2026-10-13T{10 + index:02d}:00:00Z",
                "started_at_utc": f"2026-10-13T{10 + index:02d}:00:00Z",
                "finished_at_utc": f"2026-10-13T{10 + index:02d}:00:30Z",
                "disk": {"free_bytes": 2_400_000_000, "status": "WARNING"},
                "order_sent": False,
                "promotion": "NONE",
            }
        with (lane / "runs.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    return lane


def _read(root: Path, **kwargs: Any) -> Any:
    return R.collect(
        repo_root=root,
        lane_state_root=kwargs.get("lane") or _lane(root),
        watch_state_root=root / "watch",
        store_root=root / "store",
    )


def test_every_figure_says_when_it_was_read_and_where_it_came_from(tmp_path):
    """A number without its instant is a number that will be quoted at the wrong one."""
    snapshot = _read(tmp_path)
    assert snapshot.figures, "a reading with no figures is not a reading"
    for item in snapshot.figures:
        assert item.run_id == snapshot.run_id, f"{item.name} is not tagged with this reading"
        assert item.as_of_utc == snapshot.as_of_utc, f"{item.name} carries another instant"
        assert item.measurement_scope, f"{item.name} does not say what it counts"
        assert item.source_artifact, f"{item.name} does not say where it came from"
        if item.source_digest:
            assert len(item.source_digest) == 64, f"{item.name} cites a digest that is not one"
        else:
            # No digest is allowed for exactly one reason: the artefact was not there to read.
            assert not Path(item.source_artifact).is_file(), (
                f"{item.name} cites a present artefact but carries no digest of it"
            )


def test_the_snapshot_verifies_itself_and_notices_an_edit(tmp_path):
    """The digest is the immutability: change one figure and the snapshot stops being usable."""
    snapshot = _read(tmp_path)
    ok, why = snapshot.verified()
    assert ok, why

    edited = json.loads(json.dumps(snapshot.as_dict()))  # a round trip, as a reader would
    edited["figures"][0]["value"] = "a number nobody measured"
    ok, why = R.ReadingSnapshot.from_dict(edited).verified()
    assert not ok
    assert "edited after it was taken" in why


def test_the_digest_survives_a_round_trip_through_the_written_file(tmp_path):
    """What is written is what is verified: the JSON on disk is the snapshot, not a copy of it."""
    snapshot = _read(tmp_path)
    path = tmp_path / "READING_SNAPSHOT.json"
    path.write_text(json.dumps(snapshot.as_dict(), indent=2, sort_keys=True), encoding="utf-8")
    reloaded = R.ReadingSnapshot.from_dict(json.loads(path.read_text(encoding="utf-8")))
    assert reloaded.digest == snapshot.digest
    assert reloaded.verified() == (True, "the digest matches the contents")
    assert [item.as_dict() for item in reloaded.figures] == [
        item.as_dict() for item in snapshot.figures
    ]


def test_the_report_refuses_a_snapshot_that_was_edited(tmp_path, report_script, capsys):
    """Not a warning: the generator writes nothing and exits non-zero."""
    snapshot = _read(tmp_path)
    path = tmp_path / "READING_SNAPSHOT.json"
    payload = snapshot.as_dict()
    payload["figures"][0]["value"] = 99
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    with pytest.raises(SystemExit) as raised:
        report_script.load_snapshot(path)
    assert "refusing to render" in str(raised.value), raised.value
    assert capsys.readouterr().out == ""


def test_every_acceptance_row_cites_figures_that_are_in_the_snapshot(tmp_path, report_script):
    """A row may not point at evidence that does not exist — that is how a PASS stops meaning one."""
    snapshot = _read(tmp_path)
    wrapped = report_script.Snapshot(snapshot)
    rows = report_script.matrix(wrapped)
    assert len(rows) == 15, f"the matrix declares {len(rows)} rows"
    known = set(wrapped.figures)
    for row in rows:
        assert row["verdict"] in {"PASS", "FAIL", "BLOCKED", "NOT_TESTED"}, row["id"]
        assert row["evidence"], f"{row['id']} cites no evidence at all"
        assert row["note"], f"{row['id']} states no reason"
        for item in row["evidence"]:
            if item["figure"] not in known:
                # A row may name the figure it *would* have cited — that is how NOT_TESTED stays
                # legible — but it may not claim a result on evidence that is not there.
                assert row["verdict"] != "PASS", (
                    f"{row['id']} claims PASS citing {item['figure']}, which is absent"
                )
                assert item["value"] is None and item["source_digest"] == ""
                continue
            assert item["as_of_utc"] == snapshot.as_of_utc, f"{row['id']} cites another instant"
            assert item["source_artifact"], f"{row['id']} cites a figure with no artefact"
        if row["verdict"] == "PASS":
            assert any(item["value"] is not None for item in row["evidence"]), (
                f"{row['id']} claims PASS with nothing measured behind it"
            )


def test_a_blocked_ingest_cannot_be_reported_as_a_closed_work_package(tmp_path, report_script):
    """`No declarar PASS si la ingesta continúa bloqueada`, as a rule rather than as a note."""
    lane = _lane(tmp_path, blocked=True)
    snapshot = _read(tmp_path, lane=lane)
    wrapped = report_script.Snapshot(snapshot)
    state, why = report_script.ingest_state(wrapped)
    assert state == "INGEST_BLOCKED", why
    assert "cannot observe" in why

    passing = [{"id": "ACC-01", "verdict": "PASS"}]
    verdict, verdict_why = report_script.work_package_verdict(passing, state)
    assert verdict == "NOT_CLOSED_INGEST_BLOCKED"
    assert "no closure" in verdict_why

    # A demonstrated failure outranks the ingest reason, and still is not a closure.
    assert report_script.work_package_verdict(
        passing + [{"id": "ACC-04", "verdict": "FAIL"}], state
    )[0] == "NOT_CLOSED"
    assert report_script.work_package_verdict(passing, "INGESTING")[0] == "CLOSED"


def test_a_lane_row_claiming_an_order_is_counted_and_never_silently_ignored(tmp_path):
    """ACC-13 is checked by reading the log, so the check has to be able to fail."""
    lane = _lane(tmp_path)
    good = _read(tmp_path, lane=lane)
    assert good.value("lane_rows_claiming_an_order") == 0

    with (lane / "runs.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps({"run_id": "FWD-EDGE04-X", "outcome": "OBSERVED", "order_sent": True}) + "\n"
        )
    bad = _read(tmp_path, lane=lane)
    assert bad.value("lane_rows_claiming_an_order") == 1
