"""WP-EDGE-05 — the reconciliation's own regressions.

The reconciliation exists because a killed process can leave bars in the store that no run row
claims, and because "the store moved and nothing says it moved" has to be distinguishable from a
real defect. So the tests that matter are the ones about *naming*:

* a clean lane reconciles clean, and every stored bar is attributed to a ledger row and, through
  the instant, to a tick;
* a tick that appended bars and died before recording itself is named, with its bars, as a closed
  episode once a later tick found them already above its high-water mark;
* a bar whose ingest row was never written, a claim the store does not hold, a bar claimed twice,
  a chain that jumps and two ticks that read the same store and decided differently are each
  named — and each is an *open* defect;
* a ledger that has been front-truncated does not invent an epoch for the bars below it;
* the second ingest pass at one instant must append nothing, re-derived from the ledger;
* the reconciliation is a reading: identical for a pinned instant, and it writes nothing into the
  lane's tree.

The lane fixture is the watchdog's own: one synthetic lane, advanced tick by tick, where any single
point of persistence can be interrupted.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from trading_bot.research.edge05 import reconcile as REC  # noqa: E402


def _lane_fixture():
    """The watchdog suite's lane, loaded by path so both suites drive the same instrument.

    Imported under its own module name on purpose: a second name for the same file would make the
    two suites disagree about which module object they are asserting against.
    """
    path = Path(__file__).with_name("test_edge05_watchdog.py")
    spec = importlib.util.spec_from_file_location("edge05_lane_fixture", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


FIX = _lane_fixture()
Lane = FIX.Lane
T0 = FIX.T0
QUARTER = FIX.QUARTER
HOUR = FIX.HOUR
INSTANT = T0 + 40 * QUARTER


def reconciler(tmp_path: Path, lane: Any, **kwargs: Any) -> REC.Reconciler:
    return REC.Reconciler(
        repo_root=tmp_path,
        lane_state_root=lane.state,
        store_root=lane.store,
        state_root=tmp_path / "watch",
        series=lane.series,
        **kwargs,
    )


def states(report: dict[str, Any]) -> list[str]:
    return [str(item["state"]) for item in report["defects"]]


def healthy(tmp_path: Path, *, ticks: int = 6) -> Any:
    lane = Lane(tmp_path)
    for index in range(ticks):
        lane.tick(T0 + index * QUARTER)
    return lane


# --------------------------------------------------------------------------- the happy path
def test_a_clean_lane_reconciles_with_every_bar_attributed(tmp_path):
    lane = healthy(tmp_path)
    report = reconciler(tmp_path, lane).reconcile(now_ms=INSTANT)
    assert report["status"] == "CLEAN"
    assert report["defects"] == []
    assert report["reconstruction"]["every_stored_bar_has_an_author_or_a_name"] is True
    assert report["reconstruction"]["bars_removed"] == 0
    assert report["lane_writes"] == 0
    assert report["market_requests"] == 0
    assert report["promotion"] == "NONE"
    assert report["attempts"]["without_a_run"] == 0
    for name, body in report["chains"].items():
        assert body["chain_holds"] is True, name
        assert body["unattributed_bars"] == 0
        assert body["stored_bars"] == (
            body["pre_epoch_bars"] + body["post_epoch_attributed"] + body["unattributed_bars"]
        )
    # the pipeline's own restart proof, re-derived from the ledger by another process
    assert report["restart_proof"]["instants_with_two_passes"] == 6
    assert report["restart_proof"]["broken"] == []


# --------------------------------------------------------------------------- the killed tick
def test_a_tick_that_appended_bars_and_never_recorded_itself_is_named_with_its_bars(tmp_path):
    lane = healthy(tmp_path, ticks=4)
    # the crash: the store and the ledger are written, the run row never is
    crashed = lane.tick(T0 + 4 * QUARTER, run=False)
    assert crashed["new_bars"] > 0
    # the next trigger finds the bars already above its high-water mark and appends none of them;
    # it is a repeat inside the slot the dead tick drained, so it leaves the seal alone
    later = lane.tick(T0 + 4 * QUARTER + 30_000, seal=False, slot_sealed=False)
    assert later["new_bars"] == 0

    report = reconciler(tmp_path, lane).reconcile(now_ms=INSTANT)
    attempts = report["attempts"]["without_a_run_detail"]
    assert len(attempts) == 1
    attempt = attempts[0]
    assert attempt["attempt_at_utc"] == FIX.stamp_ms(T0 + 4 * QUARTER)
    assert attempt["bars_appended"] == crashed["new_bars"]
    assert attempt["next_run_id"] == later["run_id"]
    assert attempt["match_granularity"] is None
    assert len(attempt["bars"]) == crashed["new_bars"]
    for bar in attempt["bars"]:
        assert bar["series"] in {f"{tf}:{sym}" for tf, sym in lane.series}
    assert "covered exactly once" in attempt["recovery"]
    # a closed episode, not an open defect: the bars are all in the store
    assert attempt["episode"] == "CLOSED"
    assert attempt["interval_covered"] is True
    assert attempt["bars_present_in_store"] == attempt["bars_appended"]
    # the seal the dead tick wrote is the second half of the same episode, not a second fault
    assert len(attempt["seals_of_this_attempt"]) == 1
    assert report["seals"]["of_an_unrecorded_run"][0]["belongs_to_attempt"] == attempt["attempt_at_utc"]
    assert report["status"] == "HISTORICAL_ONLY"
    assert report["open_defects"] == []
    assert report["defect_counts"][REC.UNATTRIBUTED_ATTEMPT] == 1
    assert report["reconstruction"]["every_stored_bar_has_an_author_or_a_name"] is True


def test_an_attempt_whose_bars_never_reached_the_store_stays_open(tmp_path):
    lane = healthy(tmp_path, ticks=4)
    lane.tick(T0 + 4 * QUARTER, store=False, run=False)
    lane.tick(T0 + 5 * QUARTER)
    report = reconciler(tmp_path, lane).reconcile(now_ms=INSTANT)
    assert report["status"] == "OPEN_DEFECTS"
    attempt = report["attempts"]["without_a_run_detail"][0]
    assert attempt["interval_covered"] is False
    assert attempt["episode"] == "OPEN"
    assert attempt["bars_present_in_store"] < attempt["bars_appended"]
    assert any(
        item["state"] == REC.CLAIMED_BUT_ABSENT for item in report["open_defects"]
    ), "a claimed bar the store does not hold is its own finding"


def test_a_bar_whose_ingest_row_was_never_written_is_still_named(tmp_path):
    lane = healthy(tmp_path, ticks=4)
    lane.tick(T0 + 4 * QUARTER, ledger=False)
    report = reconciler(tmp_path, lane).reconcile(now_ms=INSTANT)
    unattributed = [item for item in report["defects"] if item["state"] == REC.UNATTRIBUTED_BAR]
    assert unattributed, "a stored bar with no claiming row must be named"
    bar = unattributed[0]
    assert bar["fetched_at_utc"] == FIX.stamp_ms(T0 + 4 * QUARTER)
    assert bar["removed"] is False
    assert bar["attempt"] is not None, "the attempt is reconstructed from the bar's own fetch instant"
    assert report["status"] == "OPEN_DEFECTS"
    assert report["reconstruction"]["every_stored_bar_has_an_author_or_a_name"] is True


def test_a_claim_the_store_does_not_hold_is_named(tmp_path):
    lane = healthy(tmp_path, ticks=4)
    lane.tick(T0 + 4 * QUARTER, store=False)
    report = reconciler(tmp_path, lane).reconcile(now_ms=INSTANT)
    absent = [item for item in report["defects"] if item["state"] == REC.CLAIMED_BUT_ABSENT]
    assert absent
    assert absent[0]["claim"]["run_at_ms"] == T0 + 4 * QUARTER
    assert report["status"] == "OPEN_DEFECTS"


def test_a_bar_claimed_twice_is_a_duplicate_write(tmp_path):
    lane = healthy(tmp_path, ticks=4)
    lane.tick(T0 + 4 * QUARTER)
    # A second ledger row claims a bar that the first one already claimed.
    rows, _ = REC._lane_read_jsonl(lane.ledger_path)  # noqa: SLF001 - the fixture's own file
    first = next(row for row in rows if row.get("appended"))
    extra = dict(first)
    extra["run_at_ms"] = int(first["run_at_ms"]) + 1_000
    FIX._append_jsonl(lane.ledger_path, extra)
    report = reconciler(tmp_path, lane).reconcile(now_ms=INSTANT)
    doubles = [item for item in report["defects"] if item["state"] == REC.DOUBLE_CLAIM]
    assert doubles
    assert doubles[0]["bar_ts"] == int(first["high_water_ts"]) + FIX.span_of(first["timeframe"])
    assert report["status"] == "OPEN_DEFECTS"


def test_a_chain_that_jumps_names_both_sides_of_the_arithmetic(tmp_path):
    lane = healthy(tmp_path, ticks=6)
    rows, _ = REC._lane_read_jsonl(lane.ledger_path)  # noqa: SLF001
    # The last row of one series, so the jump is measured against the chain's own end.
    last_row = [row for row in rows if row.get("appended")][-1]
    series = f"{last_row['timeframe']}:{last_row['symbol']}"
    jumped = dict(
        [row for row in rows if f"{row['timeframe']}:{row['symbol']}" == series][-1]
    )
    span = FIX.span_of(str(jumped["timeframe"]))
    jumped["high_water_ts"] = int(jumped["high_water_ts"]) + 3 * span
    jumped["appended"] = 0
    jumped["run_at_ms"] = int(jumped["run_at_ms"]) + 1_000
    FIX._append_jsonl(lane.ledger_path, jumped)
    report = reconciler(tmp_path, lane).reconcile(now_ms=INSTANT)
    breaks = [item for item in report["defects"] if item["state"] == REC.CHAIN_BROKEN]
    assert breaks
    assert breaks[0]["series"] == series
    assert breaks[0]["gap_bars"] == 3
    assert breaks[0]["expected_high_water_utc"] != breaks[0]["observed_high_water_utc"]
    assert report["chains"][series]["chain_holds"] is False
    assert report["status"] == "OPEN_DEFECTS"


def test_two_ticks_that_read_the_same_store_must_have_decided_the_same(tmp_path):
    lane = healthy(tmp_path, ticks=4)
    lane.tick(T0 + 4 * QUARTER, append=0)
    lane.decisions_digest = "e" * 64
    lane.tick(T0 + 5 * QUARTER, append=0)
    report = reconciler(tmp_path, lane).reconcile(now_ms=INSTANT)
    divergences = [item for item in report["defects"] if item["state"] == REC.DECISION_DIVERGENCE]
    assert divergences
    assert divergences[0]["store_bars"] == lane.runs[-2]["store"]["total_bars"]
    assert divergences[0]["previous_decisions_digest"] != divergences[0]["current_decisions_digest"]
    assert report["status"] == "OPEN_DEFECTS"


def test_the_second_pass_of_an_instant_must_append_nothing(tmp_path):
    lane = healthy(tmp_path, ticks=4)
    lane.tick(T0 + 4 * QUARTER, append_on_second_pass=1)
    report = reconciler(tmp_path, lane).reconcile(now_ms=INSTANT)
    broken = [item for item in report["defects"] if item["state"] == REC.RESTART_PROOF_BROKEN]
    assert broken
    assert broken[0]["appended_on_the_second_pass"] == 1
    assert report["status"] == "OPEN_DEFECTS"


def test_a_seal_without_its_run_and_a_consuming_run_without_its_seal_are_both_named(tmp_path):
    lane = healthy(tmp_path, ticks=3)
    # (a) a run the seal names, removed from the run log *and* from the ledger, as a log that was
    # front-truncated before both would leave it
    rows, _ = REC._lane_read_jsonl(lane.runs_path)  # noqa: SLF001
    instant = REC.parse_instant_ms(rows[0]["market_instant_utc"])
    ledger, _ = REC._lane_read_jsonl(lane.ledger_path)  # noqa: SLF001
    lane.ledger_path.write_text(
        "".join(
            json.dumps(row, sort_keys=True) + "\n"
            for row in ledger
            if int(row["run_at_ms"]) // 1000 != int(instant) // 1000
        ),
        encoding="utf-8",
    )
    lane.runs_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows[1:]), encoding="utf-8"
    )
    report = reconciler(tmp_path, lane).reconcile(now_ms=INSTANT)
    orphaned = [item for item in report["defects"] if item["state"] == REC.SEAL_ORPHANED]
    assert len(orphaned) == 1
    assert orphaned[0]["run_id"] == rows[0]["run_id"]
    assert REC.SEAL_ORPHANED in report["defect_counts"]
    # (b) a consuming tick that sealed nothing
    lane2 = Lane(tmp_path / "second")
    for index in range(3):
        lane2.tick(T0 + index * QUARTER, seal=index != 2)
    report2 = reconciler(tmp_path, lane2).reconcile(now_ms=INSTANT)
    missing = [item for item in report2["defects"] if item["state"] == REC.SEAL_MISSING]
    assert len(missing) == 1
    assert missing[0]["run_id"].endswith("00Z")


def test_a_front_truncated_ledger_does_not_invent_an_epoch(tmp_path):
    lane = healthy(tmp_path, ticks=6)
    rows, _ = REC._lane_read_jsonl(lane.ledger_path)  # noqa: SLF001
    # one whole tick: the ledger holds two passes per series, so six rows would keep the second
    # pass of three series and nothing else
    kept = rows[-12:]
    lane.ledger_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in kept), encoding="utf-8"
    )
    report = reconciler(tmp_path, lane, ledger_kept=12).reconcile(now_ms=INSTANT)
    assert report["inputs"]["ledger_truncated"] is True
    for name, body in report["chains"].items():
        first_for_series = next(
            row for row in kept if f"{row['timeframe']}:{row['symbol']}" == name
        )
        assert body["epoch_utc"] == FIX.stamp_ms(int(first_for_series["high_water_ts"]))
        # the bars older than the epoch are counted as pre-epoch, never as unattributed: a
        # truncated ledger is a statement about the ledger, not an accusation against the store
        assert body["pre_epoch_bars"] > 0
        assert body["unattributed_bars"] == 0
    assert all(body["chain_holds"] for body in report["chains"].values())
    # The declared count is what makes the epoch checkable: if the ledger's own "how many bars
    # existed before me" disagrees with the store, that is named rather than smoothed over.
    first = dict(kept[0])
    first["stored_before"] = int(first["stored_before"]) + 1
    lane.ledger_path.write_text(
        "".join(
            json.dumps(row, sort_keys=True) + "\n" for row in [first, *kept[1:]]
        ),
        encoding="utf-8",
    )
    second = reconciler(tmp_path, lane, ledger_kept=12).reconcile(now_ms=INSTANT)
    mismatches = [
        item
        for item in second["defects"]
        if item["state"] == REC.CHAIN_BROKEN and item.get("kind") == "EPOCH_MISMATCH"
    ]
    assert mismatches
    assert mismatches[0]["stored_at_or_below_the_epoch"] != mismatches[0]["stored_before_the_chain_started"]


# --------------------------------------------------------------------------- restraint
def test_reconciliation_is_a_reading_and_is_identical_for_a_pinned_instant(tmp_path):
    lane = healthy(tmp_path, ticks=4)
    lane.tick(T0 + 4 * QUARTER, run=False)
    seen = reconciler(tmp_path, lane)
    lane_before = {
        p.relative_to(lane.state).as_posix(): p.read_bytes()
        for p in lane.state.rglob("*")
        if p.is_file()
    }
    store_before = {
        p.relative_to(lane.store).as_posix(): p.read_bytes()
        for p in lane.store.rglob("*")
        if p.is_file()
    }
    first = seen.reconcile(now_ms=INSTANT)
    second = seen.reconcile(now_ms=INSTANT)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    written = seen.write(first)
    assert set(written) == {"reconciliation", "attribution", "markers", "markdown"}
    assert seen.report_path.is_file()
    markers = seen.markers_path.read_text(encoding="utf-8")
    # writing the same reading twice cannot append a second copy of it
    seen.write(second)
    assert seen.markers_path.read_text(encoding="utf-8") == markers
    assert not seen.markers_path.with_suffix(".previous.jsonl").exists()
    assert json.loads(seen.report_path.read_text(encoding="utf-8"))["status"] == first["status"]
    assert (
        Path(first["inputs"]["runs_path"]).read_bytes()
        == (lane.state / "runs.jsonl").read_bytes()
    )
    assert {
        p.relative_to(lane.state).as_posix(): p.read_bytes()
        for p in lane.state.rglob("*")
        if p.is_file()
    } == lane_before, "the lane's own state root must be untouched by a reconciliation"
    assert {
        p.relative_to(lane.store).as_posix(): p.read_bytes()
        for p in lane.store.rglob("*")
        if p.is_file()
    } == store_before


def test_the_rendered_report_states_the_findings_it_found(tmp_path):
    lane = healthy(tmp_path, ticks=4)
    lane.tick(T0 + 4 * QUARTER, run=False)
    lane.tick(T0 + 5 * QUARTER)
    seen = reconciler(tmp_path, lane)
    report = seen.reconcile(now_ms=INSTANT)
    text = seen.render(report)
    assert "reconciliation of the forward lane" in text
    assert report["status"] in text
    for attempt in report["attempts"]["without_a_run_detail"]:
        for bar in attempt["bars"]:
            assert bar["bar_utc"] in text
    assert "no promotion" in text


@pytest.mark.parametrize("interruption", ["store", "ledger", "run", "seal"])
def test_every_point_of_persistence_can_be_interrupted_and_is_named(tmp_path, interruption: str):
    """A tick writes four things. Dropping any one of them must leave a *named* state."""
    lane = healthy(tmp_path, ticks=3)
    options = {interruption: False}
    lane.tick(T0 + 3 * QUARTER, **options)
    lane.tick(T0 + 4 * QUARTER)
    report = reconciler(tmp_path, lane).reconcile(now_ms=INSTANT)
    named = set(states(report))
    expected = {
        # the ledger was written and the bars never were
        "store": {REC.CLAIMED_BUT_ABSENT},
        # the bars were written and the ledger row never was
        "ledger": {REC.UNATTRIBUTED_BAR},
        # the tick never recorded itself: the bars are attributed, the attempt is not
        "run": {REC.UNATTRIBUTED_ATTEMPT},
        # the tick consumed a slot and left no seal
        "seal": {REC.SEAL_MISSING},
    }[interruption]
    assert expected <= named, f"{interruption}: {sorted(named)}"
    assert report["status"] == "OPEN_DEFECTS" or (
        interruption == "run" and report["status"] == "HISTORICAL_ONLY"
    )
