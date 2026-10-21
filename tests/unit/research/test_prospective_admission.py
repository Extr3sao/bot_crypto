"""Prospective admission: the day is the unit, the lag is the evidence, the seal is the proof.

The tests are written against the failure this repository actually suffered, twice:

* ``DENSE_BUT_BACKFILLED`` — 229 days of bars that arrived after their close and were nonetheless
  counted as a 235-day corpus (``data/forward/edge04/coverage.json``);
* a count read from a derived file — ``coverage.json`` is regenerated on every tick, so it can
  never be evidence of what was true when it was quoted.

Every test builds its own two-bar-per-hour fixture in ``tmp_path``. Nothing here reads the real
store, so a future change to ``data/forward`` cannot silently change what these assert.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from trading_bot.research.prospective import (
    DENSE_BUT_BACKFILLED,
    INCOMPLETE,
    PENDING,
    AttestationLedger,
    ObservationBook,
    StoreError,
    accumulate,
    classify_day,
    expected_bars,
    independent_day_count,
    index_series,
    intersection_epoch,
    utc_date,
)
from trading_bot.research.prospective.admission import sealable_through
from trading_bot.research.prospective.ledger import LedgerConflict

HOUR = 3_600_000
DAY = "2026-10-15"
NOW = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)


def _write(
    path: Path,
    *,
    interval: str = "1h",
    day: str = DAY,
    count: int = 24,
    lag_ms: int = 60_000,
    skip: tuple[int, ...] = (),
    start_index: int = 0,
    append: bool = False,
) -> Path:
    span = HOUR if interval == "1h" else 900_000
    base = int(
        datetime.fromisoformat(f"{day}T00:00:00+00:00").timestamp() * 1000
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for index in range(count):
        if index in skip:
            continue
        ts = base + (start_index + index) * span
        lines.append(
            json.dumps(
                {
                    "ts": ts,
                    "interval": interval,
                    "closed": True,
                    "fetched_at_ms": ts + span + lag_ms,
                    "payload_sha256": f"{index:064x}",
                }
            )
        )
    payload = "\n".join(lines) + "\n"
    if append:
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
    else:
        path.write_text(payload, encoding="utf-8")
    return path


def _index(path: Path, asset: str, interval: str = "1h"):
    return index_series(path, asset, interval)


# --------------------------------------------------------------------------- #
# classification
# --------------------------------------------------------------------------- #
def test_observed_day_is_admissible(tmp_path: Path) -> None:
    index = _index(_write(tmp_path / "BTC.jsonl"), "BTC")
    day = classify_day(DAY, [index])
    assert day.classification == "PROSPECTIVELY_OBSERVED"
    assert day.admissible is True
    assert day.series[0].prospective == 24


def test_backfilled_day_is_dense_but_not_observed(tmp_path: Path) -> None:
    index = _index(_write(tmp_path / "BTC.jsonl", lag_ms=5 * 24 * HOUR), "BTC")
    day = classify_day(DAY, [index])
    assert day.classification == DENSE_BUT_BACKFILLED
    assert day.admissible is False
    # The point of the class: the bars are there, and that is exactly why a row count cannot see it.
    assert day.series[0].stored == 24
    assert day.series[0].prospective == 0


def test_missing_bars_are_incomplete_not_backfilled(tmp_path: Path) -> None:
    index = _index(_write(tmp_path / "BTC.jsonl", skip=(0, 1, 2, 3, 4, 5)), "BTC")
    day = classify_day(DAY, [index])
    assert day.classification == INCOMPLETE


def test_lag_boundary_is_inclusive(tmp_path: Path) -> None:
    at_bound = _index(_write(tmp_path / "a.jsonl", lag_ms=7_200_000), "BTC")
    over = _index(_write(tmp_path / "b.jsonl", lag_ms=7_200_001), "BTC")
    assert classify_day(DAY, [at_bound]).classification == "PROSPECTIVELY_OBSERVED"
    assert classify_day(DAY, [over]).classification == DENSE_BUT_BACKFILLED


def test_ninety_percent_coverage_is_the_threshold(tmp_path: Path) -> None:
    """22 of 24 is 0.9167 and passes; 21 of 24 is 0.875, which is not even dense."""
    passing = _index(_write(tmp_path / "a.jsonl", skip=(0, 1)), "BTC")
    failing = _index(_write(tmp_path / "b.jsonl", skip=(0, 1, 2)), "BTC")
    assert classify_day(DAY, [passing]).classification == "PROSPECTIVELY_OBSERVED"
    assert classify_day(DAY, [failing]).classification == INCOMPLETE


def test_a_missing_series_is_not_silently_skipped(tmp_path: Path) -> None:
    """One asset with no bar at all must make the day incomplete, not make the day smaller."""
    good = _index(_write(tmp_path / "BTC.jsonl"), "BTC")
    empty = _index(_write(tmp_path / "ETH.jsonl", day="2026-10-14"), "ETH")
    day = classify_day(DAY, [good, empty])
    assert day.classification == INCOMPLETE
    assert len(day.series) == 2
    assert day.series[1].stored == 0


def test_unclosed_bars_are_not_prospective(tmp_path: Path) -> None:
    path = tmp_path / "BTC.jsonl"
    _write(path, lag_ms=60_000)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    for row in rows:
        row["closed"] = False
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    assert classify_day(DAY, [_index(path, "BTC")]).classification == DENSE_BUT_BACKFILLED


def test_expected_bars_matches_the_calendar() -> None:
    assert expected_bars("1h") == 24
    assert expected_bars("15m") == 96
    with pytest.raises(ValueError):
        expected_bars("7h")


def test_a_naive_datetime_has_no_trusted_day() -> None:
    with pytest.raises(ValueError):
        utc_date(datetime(2026, 10, 1, 23, 30))
    assert intersection_epoch({"a": "2026-10-01"}) == "2026-10-01"


# --------------------------------------------------------------------------- #
# accumulation
# --------------------------------------------------------------------------- #
def test_today_is_pending_rather_than_counted(tmp_path: Path) -> None:
    """A day whose bars can still legitimately arrive is neither admitted nor rejected."""
    today = NOW.strftime("%Y-%m-%d")
    index = _index(_write(tmp_path / "BTC.jsonl", day=today, count=12), "BTC")
    result = accumulate(indexes=[index], epoch=today, now=NOW, target_days=1)
    assert result.pending == (today,)
    assert result.days == ()
    assert result.counts[PENDING] == 1
    assert result.admissible == 0


def test_accumulate_counts_only_admissible_days(tmp_path: Path) -> None:
    store = tmp_path / "BTC.jsonl"
    _write(store, day="2026-10-19")
    _write(store, day="2026-10-20", lag_ms=9 * HOUR, append=True)
    result = accumulate(
        indexes=[_index(store, "BTC")], epoch="2026-10-19", now=NOW, target_days=2
    )
    assert result.admissible_days == ("2026-10-19",)
    assert result.remaining == 1
    assert result.counts[DENSE_BUT_BACKFILLED] == 1


def test_projection_is_none_when_no_day_was_ever_admitted(tmp_path: Path) -> None:
    index = _index(_write(tmp_path / "a.jsonl", day="2026-10-20", lag_ms=48 * HOUR), "BTC")
    result = accumulate(indexes=[index], epoch="2026-10-20", now=NOW, target_days=90)
    assert result.projection()["projected_completion_utc"] is None
    assert result.projection()["rate_admissible_per_day"] == 0.0


def test_intersection_epoch_takes_the_latest_series_start() -> None:
    assert intersection_epoch({"1h:BTC": "2026-02-28", "15m:BTC": "2026-10-07"}) == "2026-10-07"


def test_sealable_through_leaves_room_for_the_longest_lag() -> None:
    cutoff = sealable_through(NOW, {"1h": 7_200_000})
    # 12:00 minus a 2 h lag minus a full day: yesterday's end is the last one fully settled.
    assert cutoff == (NOW - timedelta(hours=2) - timedelta(days=1)).date()
    assert cutoff < NOW.date()


# --------------------------------------------------------------------------- #
# the store refuses what it cannot read
# --------------------------------------------------------------------------- #
def test_corrupt_store_line_is_an_error_not_a_shorter_day(tmp_path: Path) -> None:
    path = _write(tmp_path / "BTC.jsonl", skip=(5,))
    lines = path.read_text(encoding="utf-8").splitlines()
    lines.insert(5, "{not json")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(StoreError):
        index_series(path, "BTC", "1h")


def test_a_series_that_lies_about_its_interval_is_refused(tmp_path: Path) -> None:
    path = _write(tmp_path / "BTC.jsonl")
    first = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    first["interval"] = "15m"
    path.write_text(json.dumps(first) + "\n", encoding="utf-8")
    with pytest.raises(StoreError):
        index_series(path, "BTC", "1h")


# --------------------------------------------------------------------------- #
# the ledger
# --------------------------------------------------------------------------- #
def _ledger_fixture(tmp_path: Path) -> tuple[AttestationLedger, list, list]:
    store = tmp_path / "store" / "BTC.jsonl"
    _write(store, day="2026-10-19")
    _write(store, day="2026-10-20", append=True)
    indexes = [_index(store, "BTC")]
    days = [
        classify_day("2026-10-19", indexes),
        classify_day("2026-10-20", indexes),
    ]
    return AttestationLedger(path=tmp_path / "state" / "attestations.jsonl"), indexes, days


def test_sealed_days_verify(tmp_path: Path) -> None:
    ledger, indexes, days = _ledger_fixture(tmp_path)
    sealed = ledger.seal(days, indexes, sealed_at_utc="2026-10-21T00:00:00Z")
    assert [row["day"] for row in sealed] == ["2026-10-19", "2026-10-20"]
    assert sealed[0]["prev_sha256"] == "0" * 64
    assert sealed[1]["prev_sha256"] == sealed[0]["sha256"]
    verification = ledger.verify(indexes)
    assert verification.ok is True
    assert verification.records == 2
    assert verification.admissible == ("2026-10-19", "2026-10-20")


def test_resealing_the_same_evidence_is_a_no_op(tmp_path: Path) -> None:
    ledger, indexes, days = _ledger_fixture(tmp_path)
    ledger.seal(days, indexes, sealed_at_utc="2026-10-21T00:00:00Z")
    assert ledger.seal(days, indexes, sealed_at_utc="2026-10-22T00:00:00Z") == []
    assert ledger.verify(indexes).records == 2


def test_rewriting_a_sealed_day_is_detected(tmp_path: Path) -> None:
    ledger, indexes, days = _ledger_fixture(tmp_path)
    ledger.seal(days, indexes, sealed_at_utc="2026-10-21T00:00:00Z")
    store = tmp_path / "store" / "BTC.jsonl"
    store.write_text(store.read_text(encoding="utf-8").replace("0000", "1111", 1), encoding="utf-8")
    verification = ledger.verify(indexes)
    assert verification.ok is False
    assert any(error.startswith("SERIES_REWRITTEN") for error in verification.errors)


def test_truncating_the_store_is_detected(tmp_path: Path) -> None:
    ledger, indexes, days = _ledger_fixture(tmp_path)
    ledger.seal(days, indexes, sealed_at_utc="2026-10-21T00:00:00Z")
    store = tmp_path / "store" / "BTC.jsonl"
    store.write_bytes(store.read_bytes()[:100])
    verification = ledger.verify(indexes)
    assert any(error.startswith("SERIES_TRUNCATED") for error in verification.errors)


def test_bars_appearing_after_a_sealed_empty_day_is_flagged(tmp_path: Path) -> None:
    """A day sealed as INCOMPLETE that later grows is drift, even if it looks like an improvement."""
    store = tmp_path / "store" / "BTC.jsonl"
    _write(store, day="2026-10-19")
    indexes = [_index(store, "BTC")]
    day = classify_day("2026-10-20", indexes)
    assert day.classification == INCOMPLETE
    ledger = AttestationLedger(path=tmp_path / "state" / "a.jsonl")
    ledger.seal([day], indexes, sealed_at_utc="2026-10-21T00:00:00Z")
    assert ledger.verify(indexes).ok is True

    _write(store, day="2026-10-20", append=True)
    verification = ledger.verify([_index(store, "BTC")])
    assert any(
        error.startswith("SERIES_GAINED_BARS_AFTER_SEAL") for error in verification.errors
    )


def test_a_contradictory_reseal_raises_instead_of_appending(tmp_path: Path) -> None:
    ledger, indexes, days = _ledger_fixture(tmp_path)
    ledger.seal(days, indexes, sealed_at_utc="2026-10-21T00:00:00Z")
    store = tmp_path / "store" / "BTC.jsonl"
    store.write_text(store.read_text(encoding="utf-8").replace("0000", "2222", 1), encoding="utf-8")
    with pytest.raises(LedgerConflict):
        ledger.seal(days, [_index(store, "BTC")], sealed_at_utc="2026-10-22T00:00:00Z")


def test_editing_a_record_breaks_its_hash_and_the_chain(tmp_path: Path) -> None:
    ledger, indexes, days = _ledger_fixture(tmp_path)
    ledger.seal(days, indexes, sealed_at_utc="2026-10-21T00:00:00Z")
    path = Path(ledger.path)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    # Editing the *first* record must break both its own hash and the next record's back-link.
    rows[0]["sealed_at_utc"] = "2030-01-01T00:00:00Z"
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    errors = ledger.verify(indexes).errors
    assert any(error.startswith("RECORD_HASH_MISMATCH") for error in errors)
    assert any(error.startswith("CHAIN_BROKEN") for error in errors)


def test_deleting_a_record_is_detected(tmp_path: Path) -> None:
    ledger, indexes, days = _ledger_fixture(tmp_path)
    ledger.seal(days, indexes, sealed_at_utc="2026-10-21T00:00:00Z")
    path = Path(ledger.path)
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text(lines[1] + "\n", encoding="utf-8")
    errors = ledger.verify(indexes).errors
    assert any(error.startswith("SEQ_GAP") for error in errors)
    assert any(error.startswith("CHAIN_BROKEN") for error in errors)


def test_verification_without_the_series_does_not_pass_silently(tmp_path: Path) -> None:
    ledger, indexes, days = _ledger_fixture(tmp_path)
    ledger.seal(days, indexes, sealed_at_utc="2026-10-21T00:00:00Z")
    verification = ledger.verify(indexes=None)
    assert verification.ok is False
    assert all(error.startswith("SERIES_NOT_SUPPLIED") for error in verification.errors)


# --------------------------------------------------------------------------- #
# independence
# --------------------------------------------------------------------------- #
def test_duplicate_experiments_do_not_multiply_observations() -> None:
    book = ObservationBook()
    for experiment in ("EXP-003J", "EXP-003K", "EXP-003N"):
        for day in ("2026-08-07", "2026-08-08"):
            book.use(experiment, day, "digest-a")
    assert book.independent_day_count() == 2
    assert book.inflation()["naive_observation_count"] == 6
    assert book.inflation()["overstated_by"] == 4
    assert len(book.duplicates()) == 2
    assert book.duplicates()[0].experiments == ("EXP-003J", "EXP-003K", "EXP-003N")


def test_fresh_days_exclude_what_a_neighbour_already_read() -> None:
    book = ObservationBook()
    book.use("EXP-003K", "2026-08-07", "digest-a")
    book.use("EXP-004A", "2026-08-07", "digest-a")
    book.use("EXP-004A", "2026-10-19", "digest-b")
    assert book.fresh_days_for("EXP-004A") == ("2026-10-19",)
    assert book.independent_day_count() == 2


def test_same_day_different_bytes_is_a_rewrite_signal() -> None:
    book = ObservationBook()
    book.use("EXP-A", "2026-08-07", "digest-a")
    book.use("EXP-B", "2026-08-07", "digest-b")
    duplicate = book.duplicates()[0]
    assert duplicate.same_bytes is False
    assert "rewrite" in duplicate.reading


def test_an_observation_without_provenance_cannot_be_counted() -> None:
    book = ObservationBook()
    with pytest.raises(ValueError):
        book.use("EXP-A", "2026-08-07", "")
    with pytest.raises(ValueError):
        independent_day_count([("EXP-A", "2026-08-07", "")])
