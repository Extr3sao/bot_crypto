"""Point-in-time admission ledger (RFC-021 §5-§8)."""

from __future__ import annotations

import pytest

from trading_bot.autonomous.admission_ledger import AdmissionLedger
from trading_bot.autonomous.contracts import AdmissionStatus
from trading_bot.autonomous.pit_ledger import PitAdmissionLedger

BASE = {
    "strategies": {
        "momentum@5m": {
            "family": "momentum",
            "status": "NO_GROSS_EDGE",
            "admitted_for_paper": False,
            "expected_gross_edge_bps": -1.88,
            "source_doc": "docs/STRATEGY_DISCOVERY_V3_RESULTS.json",
            "rationale": "research classification",
            "timeframe": "5m",
            "known": True,
        }
    }
}


def _base() -> AdmissionLedger:
    return AdmissionLedger.from_dict(BASE)


def test_edge_is_as_of_and_excludes_future_outcomes() -> None:
    # exits at 100..400; at 300 only exits 100 and 200 are observable
    outcomes = {"momentum@5m": [(100, 10.0), (200, 20.0), (300, 999.0), (400, -100.0)]}
    ledger = PitAdmissionLedger(_base(), outcomes, min_sample=2)
    ledger.advance_to(300)
    # strict: exit_ts < 300 -> the (300, 999) outcome is NOT observable
    assert ledger.expected_gross_edge_bps("momentum@5m") == 15.0


def test_insufficient_history_is_fail_closed() -> None:
    outcomes = {"momentum@5m": [(100, 10.0)]}
    ledger = PitAdmissionLedger(_base(), outcomes, min_sample=30)
    ledger.advance_to(500)
    entry = ledger.entry("momentum@5m")
    assert entry.expected_gross_edge_bps is None
    assert entry.status is AdmissionStatus.RESEARCH_REQUIRED
    assert "INSUFFICIENT_LEDGER_HISTORY" in entry.rationale


def test_never_auto_promotes_to_paper() -> None:
    outcomes = {"momentum@5m": [(i * 100, 50.0) for i in range(1, 100)]}
    ledger = PitAdmissionLedger(_base(), outcomes, min_sample=10)
    ledger.advance_to(10_000)
    # strongly positive as-of edge, yet still not admitted for paper
    assert ledger.expected_gross_edge_bps("momentum@5m") == 50.0
    assert ledger.is_paper_admitted("momentum@5m") is False
    assert ledger.paper_candidates() == []


def test_time_cannot_move_backwards() -> None:
    ledger = PitAdmissionLedger(_base(), {}, min_sample=1)
    ledger.advance_to(1_000)
    with pytest.raises(ValueError):
        ledger.advance_to(500)
    assert ledger.as_of_ms == 1_000


def test_future_poisoning_leaves_past_edge_unchanged() -> None:
    outcomes = {"momentum@5m": [(i * 100, float(i)) for i in range(1, 50)]}
    poisoned = {
        "momentum@5m": [(ts, -999.0 if ts > 3_000 else g) for ts, g in outcomes["momentum@5m"]]
    }
    a = PitAdmissionLedger(_base(), outcomes, min_sample=5)
    b = PitAdmissionLedger(_base(), poisoned, min_sample=5)
    for t in (1_000, 2_000, 3_000):
        a.advance_to(t)
        b.advance_to(t)
        assert a.expected_gross_edge_bps("momentum@5m") == b.expected_gross_edge_bps("momentum@5m")
