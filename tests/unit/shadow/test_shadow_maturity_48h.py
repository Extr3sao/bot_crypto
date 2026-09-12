"""Shadow 48h maturity authority tests — EXT-SHADOW-002."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


def test_shadow_maturity_is_48h_after_capture() -> None:
    authority = Path("docs/external-audit-01/oi-full-history-03/SHADOW_MATURITY_AUTHORITY_V2.json")
    assert authority.exists(), authority
    j = json.loads(authority.read_text(encoding="utf-8"))
    for cap in j["captures"]:
        cap_t = datetime.fromisoformat(cap["capture_time"])
        mat_t = datetime.fromisoformat(cap["maturity_time"])
        delta = mat_t - cap_t
        assert delta == timedelta(hours=48), f"{cap['capture_id']} maturity {cap['maturity_time']} not +48h from {cap['capture_time']}"
        # Old claimed should be 0h
        assert cap["historical_maturity_claim"] is not None


def test_resolution_only_when_mature() -> None:
    from pathlib import Path as P

    authority = json.loads(P("docs/external-audit-01/oi-full-history-03/SHADOW_MATURITY_AUTHORITY_V2.json").read_text(encoding="utf-8"))
    # Before each correct maturity, no resolution should exist; after 2026-09-12T12:00 some are still immature
    earliest = datetime.fromisoformat(authority["earliest_correct_maturity"].replace("Z", "+00:00"))
    latest = datetime.fromisoformat(authority["latest_correct_maturity"].replace("Z", "+00:00"))
    assert earliest == datetime(2026, 9, 11, 21, 15, tzinfo=timezone.utc)
    assert latest == datetime(2026, 9, 12, 11, 25, tzinfo=timezone.utc)


def test_invalidation_record_marks_11_invalid() -> None:
    rec = json.loads(Path("docs/external-audit-01/oi-full-history-03/SHADOW_V2_INVALIDATION_RECORD.json").read_text(encoding="utf-8"))
    assert rec["verdict"] == "INVALIDATED"
    assert rec["previous_claim"]["total_captures"] == 11
    assert rec["evidence"]["delta_hours_claimed"] == 0
    assert rec["evidence"]["correct_horizon_hours"] == 48


def test_h6_shadow_isolation() -> None:
    rec = json.loads(Path("docs/external-audit-01/oi-full-history-03/H6_SHADOW_ISOLATION_REPORT.json").read_text(encoding="utf-8"))
    assert rec["verdict"] == "PASS"
