"""POC02 daily coverage authority tests (DAILY COVERAGE AUTHORITY RECONCILIATION).

Covers §11–§14 and §17:

- OPEN day + successful cycle + valid receipt contributes 0 to the
  coverage numerator (§11 OPEN_DAY_COVERAGE_CONTRIBUTION = 0)
- UTC boundary with an injected clock: 23:59:59 cannot finalize D,
  00:00:00 D+1 can (§12; no local-time dependence)
- closed VALID day counted; closed INVALID day not counted; zero
  denominator -> NOT_YET_MEASURABLE (never 1.0) (§3/§4)
- 5 successful cycles same day: one bucket, one coverage entry, 5
  receipts (amendment chain), 0 contribution before close, 1 after a
  valid close (§13)
- retry/failure/restart: one authoritative daily outcome, no duplicate
  coverage, double finalization impossible (§8/§14)
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from trading_bot.paper.day_state import (
    INVALID,
    OPEN,
    PENDING_VALIDATION,
    VALID,
    DayStateAuthority,
)


def _mk(tmp_path: Path, clock) -> DayStateAuthority:
    return DayStateAuthority(tmp_path, clock=clock)


def _write_bucket(path: Path, day: str, *, cycles: int, minutes: int) -> None:
    rows = {}
    p = path / "POC02_COVERAGE_DAILY.jsonl"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                rows[r["utc_day"]] = r
    rows[day] = {
        "utc_day": day,
        "expected_minutes": 1440,
        "expected_cycles": 288,
        "observed_cycles": cycles,
        "observed_minutes": minutes,
        "coverage_ratio": round(minutes / 1440, 6),
        "day_validity": "PENDING",
        "provider_consecutive_failures": 0,
        "provider_data_gap": False,
    }
    p.write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows.values()),
        encoding="utf-8",
    )


def _write_receipts(path: Path, day: str, n: int) -> None:
    rdir = path / "receipts"
    rdir.mkdir(parents=True, exist_ok=True)
    for i in range(1, n + 1):
        payload = {
            "receipt_id": f"RECEIPT_{day}_{i:03d}",
            "is_amendment": i > 1,
            "utc_day": day,
            "receipt_sha256": f"hash-{day}-{i}",
        }
        (rdir / f"RECEIPT_{day}_{i:03d}.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )


# --------------------------------------------------------------------------
# §11 — OPEN day contributes ZERO
# --------------------------------------------------------------------------

def test_open_day_coverage_contribution_is_zero(tmp_path: Path) -> None:
    clock = lambda: datetime(2026, 9, 9, 16, 45, tzinfo=UTC)  # noqa: E731
    auth = _mk(tmp_path, clock)
    _write_bucket(tmp_path, "2026-09-09", cycles=5, minutes=200)
    _write_receipts(tmp_path, "2026-09-09", 5)
    st = auth.day_state("2026-09-09")
    assert st.day_validity == OPEN
    assert st.day_bucket_exists and st.day_has_valid_evidence
    # §11: open day + successful cycles + valid receipt -> numerator 0
    cov = auth.campaign_coverage(
        window_start="2026-09-09T00:00:00+00:00",
        window_end="2026-09-30T00:00:00+00:00",
    )
    assert cov["VALID_CLOSED_DAYS"] == 0
    assert cov["CLOSED_ELIGIBLE_DAYS"] == 0
    assert cov["CAMPAIGN_COVERAGE"] == "NOT_YET_MEASURABLE"
    assert cov["OPEN_ELIGIBLE_DAY"] == ["2026-09-09"]


# --------------------------------------------------------------------------
# §12 — UTC boundary (injected clock, no local time)
# --------------------------------------------------------------------------

def test_utc_boundary_235959_cannot_finalize_000000_can(tmp_path: Path) -> None:
    auth = _mk(tmp_path, lambda: datetime(2026, 9, 9, 23, 59, 59, tzinfo=UTC))
    _write_bucket(tmp_path, "2026-09-09", cycles=3, minutes=60)
    early = auth.finalize_day("2026-09-09")
    assert early["DAY_NOT_CLOSED"] is True
    assert early["finalized"] is False
    # one microsecond later (UTC midnight) the day is closed
    auth._clock = lambda: datetime(2026, 9, 10, 0, 0, 0, tzinfo=UTC)
    late = auth.finalize_day("2026-09-09")
    assert late["DAY_NOT_CLOSED"] is False
    assert late["finalized"] is True
    assert late["FINALIZATION_COUNT_PER_DAY"] == 1


def test_boundary_is_pure_utc_not_local(tmp_path: Path) -> None:
    # a clock far ahead in the same UTC day still cannot finalize
    auth = _mk(tmp_path, lambda: datetime(2026, 9, 9, 23, 59, 59, tzinfo=UTC))
    _write_bucket(tmp_path, "2026-09-09", cycles=1, minutes=1)
    assert auth.finalize_day("2026-09-09")["DAY_NOT_CLOSED"] is True
    # and a UTC-equal instant from a different tz construction is identical
    auth._clock = lambda: datetime.fromisoformat(
        "2026-09-10T00:00:00+00:00"
    )
    assert auth.finalize_day("2026-09-09")["finalized"] is True


# --------------------------------------------------------------------------
# §3/§4 — valid closed counted, invalid closed not, zero denominator
# --------------------------------------------------------------------------

def test_closed_valid_day_counts_and_invalid_does_not(tmp_path: Path) -> None:
    auth = _mk(tmp_path, lambda: datetime(2026, 9, 11, tzinfo=UTC))
    _write_bucket(tmp_path, "2026-09-09", cycles=10, minutes=200)
    _write_receipts(tmp_path, "2026-09-09", 1)
    _write_bucket(tmp_path, "2026-09-10", cycles=0, minutes=0)
    assert auth.finalize_day("2026-09-09")["validity"] == VALID
    res = auth.finalize_day("2026-09-10")
    assert res["validity"] == INVALID
    assert "NO_OBSERVATION" in res["reason_codes"]
    cov = auth.campaign_coverage(
        window_start="2026-09-09T00:00:00+00:00",
        window_end="2026-09-30T00:00:00+00:00",
    )
    assert cov["CLOSED_ELIGIBLE_DAYS"] == 2
    assert cov["VALID_CLOSED_DAYS"] == 1
    assert cov["INVALID_CLOSED_DAYS"] == 1
    assert cov["CAMPAIGN_COVERAGE"] == 0.5
    # invalid day contributes zero to the numerator
    st_invalid = auth.day_state("2026-09-10")
    assert st_invalid.day_counts_for_coverage is False
    st_valid = auth.day_state("2026-09-09")
    assert st_valid.day_counts_for_coverage is True


def test_zero_denominator_is_not_yet_measurable_not_one(tmp_path: Path) -> None:
    auth = _mk(tmp_path, lambda: datetime(2026, 9, 9, 12, tzinfo=UTC))
    cov = auth.campaign_coverage(
        window_start="2026-09-09T00:00:00+00:00",
        window_end="2026-09-30T00:00:00+00:00",
    )
    assert cov["CAMPAIGN_COVERAGE"] == "NOT_YET_MEASURABLE"
    assert cov["CAMPAIGN_COVERAGE"] != 1.0


def test_pending_validation_day_not_counted_until_finalized(tmp_path: Path) -> None:
    auth = _mk(tmp_path, lambda: datetime(2026, 9, 10, 12, tzinfo=UTC))
    _write_bucket(tmp_path, "2026-09-09", cycles=5, minutes=100)
    _write_receipts(tmp_path, "2026-09-09", 1)
    st = auth.day_state("2026-09-09")
    assert st.day_validity == PENDING_VALIDATION
    cov = auth.campaign_coverage(
        window_start="2026-09-09T00:00:00+00:00",
        window_end="2026-09-30T00:00:00+00:00",
    )
    # closed but not finalized: in the denominator, not the numerator
    assert cov["CLOSED_ELIGIBLE_DAYS"] == 1
    assert cov["VALID_CLOSED_DAYS"] == 0
    assert cov["CAMPAIGN_COVERAGE"] == 0.0
    auth.finalize_day("2026-09-09")
    cov2 = auth.campaign_coverage(
        window_start="2026-09-09T00:00:00+00:00",
        window_end="2026-09-30T00:00:00+00:00",
    )
    assert cov2["VALID_CLOSED_DAYS"] == 1
    assert cov2["CAMPAIGN_COVERAGE"] == 1.0


# --------------------------------------------------------------------------
# §13 — multiple cycles same day
# --------------------------------------------------------------------------

def test_five_cycles_same_day_single_bucket(tmp_path: Path) -> None:
    auth = _mk(tmp_path, lambda: datetime(2026, 9, 9, 18, tzinfo=UTC))
    # 5 successful cycles append to ONE bucket (amendments, not duplicates)
    for i in range(1, 6):
        rows = auth._load_coverage_rows()
        row = rows.get(
            "2026-09-09",
            {"utc_day": "2026-09-09", "observed_cycles": 0, "observed_minutes": 0},
        )
        row["observed_cycles"] = i
        row["observed_minutes"] = i
        rows["2026-09-09"] = row
        auth._coverage_path.write_text(
            "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows.values()),
            encoding="utf-8",
        )
        _write_receipts(tmp_path, "2026-09-09", i)
    st = auth.day_state("2026-09-09")
    assert st.day_bucket_exists
    assert st.cycles == 5
    assert auth._receipt_count("2026-09-09") == 5
    assert auth._load_coverage_rows()["2026-09-09"]["observed_cycles"] == 5
    chain = auth.amendment_chain("2026-09-09")
    assert chain["receipt_count"] == 5
    assert chain["canonical_latest"] == "RECEIPT_2026-09-09_005.json"
    assert [c["is_amendment"] for c in chain["chain"]] == [
        False, True, True, True, True,
    ]
    # before close: contribution 0
    cov0 = auth.campaign_coverage(
        window_start="2026-09-09T00:00:00+00:00",
        window_end="2026-09-30T00:00:00+00:00",
    )
    assert cov0["CAMPAIGN_COVERAGE"] == "NOT_YET_MEASURABLE"
    # after a valid close: contribution 1
    auth._clock = lambda: datetime(2026, 9, 10, 0, 0, 1, tzinfo=UTC)
    assert auth.finalize_day("2026-09-09")["validity"] == VALID
    cov1 = auth.campaign_coverage(
        window_start="2026-09-09T00:00:00+00:00",
        window_end="2026-09-30T00:00:00+00:00",
    )
    assert cov1["VALID_CLOSED_DAYS"] == 1
    assert cov1["CAMPAIGN_COVERAGE"] == 1.0


# --------------------------------------------------------------------------
# §8/§14 — double finalization, retry/restart
# --------------------------------------------------------------------------

def test_double_finalization_is_idempotent(tmp_path: Path) -> None:
    auth = _mk(tmp_path, lambda: datetime(2026, 9, 10, 1, tzinfo=UTC))
    _write_bucket(tmp_path, "2026-09-09", cycles=4, minutes=90)
    _write_receipts(tmp_path, "2026-09-09", 1)
    first = auth.finalize_day("2026-09-09")
    assert first["finalized"] and not first.get("already_finalized")
    second = auth.finalize_day("2026-09-09")
    third = auth.finalize_day("2026-09-09")
    assert second["already_finalized"] and third["already_finalized"]
    assert second["FINALIZATION_COUNT_PER_DAY"] == 1
    assert third["FINALIZATION_COUNT_PER_DAY"] == 1
    fin = auth._load_finalizations()
    assert fin["2026-09-09"]["finalization_count"] == 1
    # validity unchanged by the re-calls
    assert second["validity"] == first["validity"] == VALID


def test_retry_after_failed_first_cycle_single_authoritative_outcome(
    tmp_path: Path,
) -> None:
    # failed first cycle: no bucket; successful retry creates exactly one
    auth = _mk(tmp_path, lambda: datetime(2026, 9, 9, 20, tzinfo=UTC))
    assert auth.day_state("2026-09-09").day_bucket_exists is False
    _write_bucket(tmp_path, "2026-09-09", cycles=2, minutes=40)  # retry
    _write_receipts(tmp_path, "2026-09-09", 2)  # original + amendment
    st = auth.day_state("2026-09-09")
    assert st.day_bucket_exists and st.cycles == 2
    chain = auth.amendment_chain("2026-09-09")
    assert chain["receipt_count"] == 2
    # process restart: a NEW authority instance sees the same state
    auth2 = _mk(tmp_path, lambda: datetime(2026, 9, 10, 2, tzinfo=UTC))
    res = auth2.finalize_day("2026-09-09")
    assert res["finalized"] and res["validity"] == VALID
    # restart again: still one finalization
    auth3 = _mk(tmp_path, lambda: datetime(2026, 9, 10, 3, tzinfo=UTC))
    again = auth3.finalize_day("2026-09-09")
    assert again["already_finalized"]
    assert again["FINALIZATION_COUNT_PER_DAY"] == 1
    cov = auth3.campaign_coverage(
        window_start="2026-09-09T00:00:00+00:00",
        window_end="2026-09-30T00:00:00+00:00",
    )
    assert cov["VALID_CLOSED_DAYS"] == 1  # no duplicate coverage


def test_partial_artifacts_are_invalid_not_valid(tmp_path: Path) -> None:
    # cycles recorded but no receipts -> NO_VALID_EVIDENCE -> INVALID
    auth = _mk(tmp_path, lambda: datetime(2026, 9, 10, 1, tzinfo=UTC))
    _write_bucket(tmp_path, "2026-09-09", cycles=3, minutes=60)
    res = auth.finalize_day("2026-09-09")
    assert res["validity"] == INVALID
    assert "NO_VALID_EVIDENCE" in res["reason_codes"]


# --------------------------------------------------------------------------
# §5 — provisional metrics never feed authority
# --------------------------------------------------------------------------

def test_provisional_metrics_labeled_and_separate(tmp_path: Path) -> None:
    auth = _mk(tmp_path, lambda: datetime(2026, 9, 9, 18, tzinfo=UTC))
    _write_bucket(tmp_path, "2026-09-09", cycles=7, minutes=5)
    p = auth.provisional_metrics(current_day="2026-09-09")
    assert p["PROVISIONAL_OBSERVED_BUCKETS"] == 1
    assert p["CURRENT_DAY_CYCLES"] == 7
    assert "coverage >= 0.80" in p["never_feeds"]
    assert "PROVISIONAL" in p["label"]
    # authority still refuses to count the open day
    cov = auth.campaign_coverage(
        window_start="2026-09-09T00:00:00+00:00",
        window_end="2026-09-30T00:00:00+00:00",
    )
    assert cov["CAMPAIGN_COVERAGE"] == "NOT_YET_MEASURABLE"


# --------------------------------------------------------------------------
# §9 — amendment chain integrity
# --------------------------------------------------------------------------

def test_amendment_chain_links_hashes(tmp_path: Path) -> None:
    auth = _mk(tmp_path, lambda: datetime(2026, 9, 9, 19, tzinfo=UTC))
    _write_receipts(tmp_path, "2026-09-09", 3)
    chain = auth.amendment_chain("2026-09-09")
    assert chain["chain"][0]["previous_hash"] is None
    assert chain["chain"][1]["previous_hash"] == "hash-2026-09-09-1"
    assert chain["chain"][2]["previous_hash"] == "hash-2026-09-09-2"
    assert chain["historical_retained"] is True
