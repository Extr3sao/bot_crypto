"""WP-EDGE-017/P0.1 — the capture contract, reproduced as tests before the fix.

Each test below is one of the failures the issue names: a second capture that
destroyed the first, a truncated retry mistaken for the end of history, a
coverage count that could not exceed one bar per symbol, duplicates "checked"
against a dict's own keys, and a still-forming hour admitted as evidence.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from trading_bot.research.oos_capture import (
    PERIOD_MS_1H,
    CaptureIntegrityError,
    closed_only,
    coverage_ladder,
    expected_closed_opens,
    is_closed,
    merge_slice,
    next_since_ms,
    paginate,
    read_slice,
    row_from_ccxt,
    slice_sha256,
    write_slice_atomic,
)

#: aligned to an hourly boundary so "expected opens" and the fixture agree
START = 497_777 * PERIOD_MS_1H


def _bars(count: int, *, start: int = START) -> list[list[float]]:
    return [
        [start + index * PERIOD_MS_1H, 100.0 + index, 101.0 + index, 99.0 + index, 100.5, 7.0]
        for index in range(count)
    ]


def _rows(symbol: str, bars: list[list[float]]) -> list[dict[str, object]]:
    return [row_from_ccxt(symbol, bar) for bar in bars]


# -- 1. repeated capture must not destroy what an earlier one wrote ----------------------


def test_repeated_capture_keeps_every_row_and_is_byte_identical(tmp_path: Path) -> None:
    slice_path = tmp_path / "slice.jsonl"
    first = _rows("BTC/USDT", _bars(3))
    write_slice_atomic(slice_path, first)

    # a second capture whose page no longer reaches the oldest bar (the venue
    # trimmed history, or the page simply started later)
    second = _rows("BTC/USDT", _bars(4))[2:]
    merged = merge_slice(read_slice(slice_path), second)
    write_slice_atomic(slice_path, merged.rows)

    assert [row["timestamp"] for row in read_slice(slice_path)] == [
        START,
        START + PERIOD_MS_1H,
        START + 2 * PERIOD_MS_1H,
        START + 3 * PERIOD_MS_1H,
    ]
    assert merged.added == 1
    assert merged.duplicates_identical == 1

    # idempotence is a digest, not a promise: a third identical capture lands on
    # exactly the same bytes
    before = slice_sha256(read_slice(slice_path))
    third = merge_slice(read_slice(slice_path), second)
    write_slice_atomic(slice_path, third.rows)
    assert slice_sha256(read_slice(slice_path)) == before
    assert third.added == 0


def test_resume_starts_after_the_newest_held_bar(tmp_path: Path) -> None:
    rows = _rows("BTC/USDT", _bars(5))
    assert next_since_ms(rows, "BTC/USDT", floor_ms=START) == START + 5 * PERIOD_MS_1H
    # a cold slice starts at the floor, never at zero
    assert next_since_ms([], "BTC/USDT", floor_ms=START) == START


# -- 2. a truncated retry must not be believed ------------------------------------------


def test_pagination_recovers_history_beyond_one_page() -> None:
    bars = _bars(2_500)
    calls: list[int] = []

    def fetch_page(since: int, limit: int) -> list[list[float]]:
        calls.append(since)
        return [bar for bar in bars if bar[0] >= since][:limit]

    result = paginate(fetch_page, since_ms=START, end_ms=START + 2_500 * PERIOD_MS_1H)

    assert len(result.rows) == 2_500
    assert result.rows[0][0] == START
    assert result.rows[-1][0] == START + 2_499 * PERIOD_MS_1H
    assert result.pages > 1
    assert result.truncated is False
    assert result.retried_short_pages >= 1


def test_truncated_page_is_confirmed_with_one_more_request() -> None:
    bars = _bars(400)
    calls = {"n": 0}

    def fetch_page(since: int, limit: int) -> list[list[float]]:
        calls["n"] += 1
        available = [bar for bar in bars if bar[0] >= since]
        # the first call is silently truncated by the venue/network
        return available[:50] if calls["n"] == 1 else available[:limit]

    result = paginate(fetch_page, since_ms=START, end_ms=START + 400 * PERIOD_MS_1H)

    assert len(result.rows) == 400, "a truncated page must not be read as the end of history"
    assert result.retried_short_pages >= 1
    assert calls["n"] >= 2


def test_a_page_that_does_not_advance_raises_instead_of_spinning() -> None:
    stuck = [[START - PERIOD_MS_1H, 1, 1, 1, 1, 1]]

    with pytest.raises(RuntimeError, match="did not advance"):
        paginate(lambda since, limit: stuck, since_ms=START, end_ms=START + 10 * PERIOD_MS_1H)


def test_page_limit_reports_truncation_rather_than_claiming_completeness() -> None:
    bars = _bars(50)

    def fetch_page(since: int, limit: int) -> list[list[float]]:
        return [bar for bar in bars if bar[0] >= since][:limit]

    result = paginate(
        fetch_page,
        since_ms=START,
        end_ms=START + 50 * PERIOD_MS_1H,
        page_limit=10,
        max_pages=2,
    )
    assert result.truncated is True
    assert result.stop_reason == "PAGE_LIMIT_REACHED"


# -- 3. coverage must count every hour, not one per symbol ------------------------------


def test_coverage_counts_every_captured_hour_per_symbol() -> None:
    expected = expected_closed_opens(START - PERIOD_MS_1H // 2, START + 4 * PERIOD_MS_1H)
    assert len(expected) == 4

    slice_rows = [
        *_rows("BTC/USDT", _bars(4)),
        *_rows("ETH/USDT", _bars(4)),
        *_rows("SOL/USDT", _bars(4)),
    ]
    ladder, totals = coverage_ladder(
        symbols=("BTC/USDT", "ETH/USDT", "SOL/USDT"),
        expected_opens=expected,
        slice_rows=slice_rows,
    )

    assert len(ladder) == 12
    assert totals["observed_symbol_bars"] == 12
    assert totals["expected_symbol_bars"] == 12
    assert totals["per_symbol"]["BTC/USDT"]["observed"] == 4
    assert totals["identity_holds"] is True


def test_a_missing_hour_is_missing_and_never_a_quiet_market() -> None:
    expected = expected_closed_opens(START - PERIOD_MS_1H // 2, START + 4 * PERIOD_MS_1H)
    # BTC has all four hours, ETH the first two, SOL none
    slice_rows = [*_rows("BTC/USDT", _bars(4)), *_rows("ETH/USDT", _bars(2))]
    ladder, totals = coverage_ladder(
        symbols=("BTC/USDT", "ETH/USDT", "SOL/USDT"),
        expected_opens=expected,
        slice_rows=slice_rows,
    )

    missing = [row for row in ladder if row["missing"]]
    assert len(missing) == 6
    assert all(row["classified"] == "MISSING_NO_COLLECTOR" for row in missing)
    assert totals["per_symbol"]["SOL/USDT"] == {
        "expected": 4,
        "observed": 0,
        "evaluated": 0,
        "missing": 4,
    }


def test_duplicate_rows_in_the_slice_are_counted_not_hidden() -> None:
    expected = expected_closed_opens(START - PERIOD_MS_1H // 2, START + 2 * PERIOD_MS_1H)
    rows = _rows("BTC/USDT", _bars(2))
    _, totals = coverage_ladder(
        symbols=("BTC/USDT",),
        expected_opens=expected,
        slice_rows=[*rows, *rows],
    )
    assert totals["duplicate_slice_rows"] == 2
    assert totals["observed_symbol_bars"] == 2


# -- 4. duplicate keys with different values are a conflict, not a silent drop ----------


def test_duplicate_key_with_a_different_value_is_recorded_as_a_conflict() -> None:
    original = _rows("BTC/USDT", _bars(1))[0]
    tampered = dict(original)
    tampered["close"] = float(original["close"]) + 5.0

    merged = merge_slice([original], [tampered])

    assert merged.added == 0
    assert merged.duplicates_identical == 0
    assert len(merged.conflicts) == 1
    assert merged.conflicts[0]["kept"]["close"] == original["close"]
    assert merged.rows[0]["close"] == original["close"], "the first captured value is immutable"


def test_an_identical_duplicate_is_counted_and_collapsed() -> None:
    row = _rows("BTC/USDT", _bars(1))[0]
    merged = merge_slice([row], [dict(row), dict(row)])
    assert merged.added == 0
    assert merged.duplicates_identical == 2
    assert merged.rows == [row]


# -- 5. the still-forming hour is not evidence -----------------------------------------


def test_partial_current_hour_bar_is_excluded() -> None:
    now = START + 2 * PERIOD_MS_1H + 1_800_000  # halfway through the third hour
    assert is_closed(START, now) is True
    assert is_closed(START + PERIOD_MS_1H, now) is True
    assert is_closed(START + 2 * PERIOD_MS_1H, now) is False

    kept = closed_only(_rows("BTC/USDT", _bars(3)), now_ms=now)
    assert [row["timestamp"] for row in kept] == [START, START + PERIOD_MS_1H]


# -- 6. atomicity -----------------------------------------------------------------------


def test_a_failed_replace_leaves_the_previous_slice_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    slice_path = tmp_path / "slice.jsonl"
    write_slice_atomic(slice_path, _rows("BTC/USDT", _bars(2)))
    before = slice_path.read_bytes()

    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        write_slice_atomic(slice_path, _rows("BTC/USDT", _bars(5)))

    assert slice_path.read_bytes() == before, "a failed write must not truncate the slice"
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]


def test_a_corrupt_slice_raises_instead_of_reading_as_empty(tmp_path: Path) -> None:
    slice_path = tmp_path / "slice.jsonl"
    slice_path.write_text('{"symbol": "BTC/USDT"}\n', encoding="utf-8")
    with pytest.raises(CaptureIntegrityError):
        read_slice(slice_path)


def test_rows_round_trip_through_disk_as_canonical_json(tmp_path: Path) -> None:
    slice_path = tmp_path / "slice.jsonl"
    written = write_slice_atomic(slice_path, _rows("BTC/USDT", _bars(2)))
    lines = slice_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["symbol"] == "BTC/USDT"
    assert written["sha256"] == slice_sha256(read_slice(slice_path))
