"""Strategy lifecycle and registry contract tests (§17-§21, §36, §37, §41, §44, §46).

The lifecycle is a security property, not a naming convention: only a state
whose name is spent can trade, promotion needs a record, and LIVE is not a name
the vocabulary contains. These tests attack each of those in turn.
"""

from __future__ import annotations

import pytest

from trading_bot.autonomous.admission_ledger import AdmissionLedger
from trading_bot.autonomous.contracts import (
    PAPER_AUTHORISING_STATUSES,
    PAPER_PROMOTABLE_STATUSES,
    AdmissionEntry,
    AdmissionStatus,
    EdgeEvidence,
)
from trading_bot.autonomous.strategy_state import (
    AVAILABLE_PAPER_DATA,
    LIFECYCLE_STATES,
    LIVE_STATUS_NAMES,
    STATE_TRANSITIONS,
    PromotionRecord,
    StrategyRecord,
    StrategyRegistry,
    StrategyStateError,
    allowed_transitions,
    assert_transition,
    can_transition,
    is_paper_executable,
)

LEDGER: dict[str, object] = {
    "_schema_version": "strategy-admission-ledger-v1",
    "_sources": [
        {"path": "docs/STRATEGY_DISCOVERY_V3_RESULTS.json", "sha256": "a" * 64},
    ],
    "strategies": {
        "ema_crossover@5m": {
            "family": "ema_crossover",
            "status": "PAPER_CANDIDATE",
            "admitted_for_paper": True,
            "expected_gross_edge_bps": 7.5,
            "edge_evidence": {
                "source_doc": "docs/STRATEGY_DISCOVERY_V3_RESULTS.json",
                "metric": "family_5m.gross_bps_per_trade",
                "value_bps": 7.5,
                "knowledge": "ESTIMATED",
                "sample_trades": 100,
            },
            "source_doc": "docs/STRATEGY_DISCOVERY_V3_RESULTS.json",
            "rationale": "candidate",
            "timeframe": "5m",
            "known": True,
        },
        "breakout@5m": {
            "family": "breakout",
            "status": "NO_GROSS_EDGE",
            "admitted_for_paper": False,
            "expected_gross_edge_bps": -0.11,
            "edge_evidence": None,
            "source_doc": "docs/STRATEGY_DISCOVERY_V3_RESULTS.json",
            "rationale": "research classification NO_GROSS_EDGE",
            "timeframe": "5m",
            "known": True,
        },
        "microstructure_imbalance@5m": {
            "family": "order_book_imbalance",
            "status": "RESEARCH_REQUIRED",
            "admitted_for_paper": False,
            "expected_gross_edge_bps": None,
            "edge_evidence": None,
            "source_doc": "config/microstructure_preregistration.json",
            "rationale": "TECHNICALLY_READY_NEEDS_HISTORY",
            "timeframe": "5m",
            "known": True,
        },
    },
}


def _ledger(payload: dict[str, object] | None = None) -> AdmissionLedger:
    return AdmissionLedger.from_dict(payload or LEDGER, source_path="test://ledger")


def _registry() -> StrategyRegistry:
    return StrategyRegistry.from_ledger(_ledger(), assets=["BTC", "ETH", "SOL"])


# ------------------------------------------------------------------ vocabulary


def test_no_live_state_exists_in_the_vocabulary() -> None:
    """§46 — the runtime cannot name the state it must never reach."""
    names = {status.value.upper() for status in AdmissionStatus}
    assert not (names & LIVE_STATUS_NAMES)
    assert "CONFIRMED" not in names


def test_no_transition_leads_to_a_live_state() -> None:
    for targets in STATE_TRANSITIONS.values():
        for target in targets:
            assert target.value.upper() not in LIVE_STATUS_NAMES


def test_only_paper_candidate_may_be_promoted_to_active() -> None:
    assert frozenset({AdmissionStatus.PAPER_CANDIDATE}) == PAPER_PROMOTABLE_STATUSES
    assert AdmissionStatus.RESEARCH_REQUIRED not in PAPER_PROMOTABLE_STATUSES


def test_both_admitted_states_authorise_paper_and_nothing_else_does() -> None:
    assert (
        frozenset({AdmissionStatus.PAPER_CANDIDATE, AdmissionStatus.PAPER_ACTIVE})
        == PAPER_AUTHORISING_STATUSES
    )
    for status in AdmissionStatus:
        expected = status in PAPER_AUTHORISING_STATUSES
        assert is_paper_executable(status) is expected


# ------------------------------------------------------------------ graph edges


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (AdmissionStatus.RESEARCH_REQUIRED, AdmissionStatus.PAPER_CANDIDATE),
        (AdmissionStatus.PAPER_CANDIDATE, AdmissionStatus.PAPER_ACTIVE),
        (AdmissionStatus.PAPER_ACTIVE, AdmissionStatus.PAPER_RETIRED),
        (AdmissionStatus.PAPER_RETIRED, AdmissionStatus.RESEARCH_REQUIRED),
        (AdmissionStatus.REJECTED, AdmissionStatus.RESEARCH_REQUIRED),
    ],
)
def test_authorised_edges(source: AdmissionStatus, target: AdmissionStatus) -> None:
    assert can_transition(source, target)


@pytest.mark.parametrize(
    ("source", "target"),
    [
        # Research cannot jump into PAPER; it has to become a candidate first.
        (AdmissionStatus.RESEARCH_REQUIRED, AdmissionStatus.PAPER_ACTIVE),
        # A retired or rejected strategy cannot activate directly.
        (AdmissionStatus.PAPER_RETIRED, AdmissionStatus.PAPER_ACTIVE),
        (AdmissionStatus.REJECTED, AdmissionStatus.PAPER_ACTIVE),
        (AdmissionStatus.REJECTED, AdmissionStatus.PAPER_CANDIDATE),
        # Losing PAPER is not a promotion and is not a re-admission.
        (AdmissionStatus.PAPER_ACTIVE, AdmissionStatus.PAPER_CANDIDATE),
        (AdmissionStatus.COST_KILLED, AdmissionStatus.PAPER_ACTIVE),
    ],
)
def test_forbidden_edges(source: AdmissionStatus, target: AdmissionStatus) -> None:
    assert not can_transition(source, target)
    with pytest.raises(StrategyStateError):
        assert_transition("s@5m", source, target)


def test_every_lifecycle_state_is_reachable_from_research() -> None:
    """The graph is closed and total: every state has declared neighbours."""
    for status in LIFECYCLE_STATES:
        assert allowed_transitions(status), f"{status.value} has no authorised transition"


# ------------------------------------------------------------------- promotion


def _promotion(**changes: object) -> PromotionRecord:
    base = {
        "promotion_id": "promo-1",
        "strategy_id": "ema_crossover@5m",
        "from_status": AdmissionStatus.PAPER_CANDIDATE,
        "to_status": AdmissionStatus.PAPER_ACTIVE,
        "evidence": ("docs/STRATEGY_DISCOVERY_V3_RESULTS.json#abc",),
        "commit": "abc1234",
        "dataset": "W1-W7 2026-03-01..2026-09-24",
        "decision": "admitted",
    }
    return PromotionRecord(**{**base, **changes})  # type: ignore[arg-type]


def test_promotion_needs_a_record() -> None:
    with pytest.raises(StrategyStateError, match="PromotionRecord"):
        assert_transition(
            "ema_crossover@5m", AdmissionStatus.PAPER_CANDIDATE, AdmissionStatus.PAPER_ACTIVE
        )


def test_promotion_record_must_match_the_strategy() -> None:
    with pytest.raises(StrategyStateError, match="belongs to"):
        assert_transition(
            "other@5m",
            AdmissionStatus.PAPER_CANDIDATE,
            AdmissionStatus.PAPER_ACTIVE,
            promotion=_promotion(),
        )


def test_a_valid_promotion_is_authorised() -> None:
    assert_transition(
        "ema_crossover@5m",
        AdmissionStatus.PAPER_CANDIDATE,
        AdmissionStatus.PAPER_ACTIVE,
        promotion=_promotion(),
    )


@pytest.mark.parametrize("field", ["evidence", "commit", "dataset"])
def test_a_promotion_without_its_evidence_is_refused(field: str) -> None:
    empty = () if field == "evidence" else ""
    with pytest.raises(ValueError, match=field):
        _promotion(**{field: empty})


def test_promotion_from_a_non_promotable_state_is_refused() -> None:
    with pytest.raises(ValueError, match="promotion must start from"):
        _promotion(from_status=AdmissionStatus.RESEARCH_REQUIRED)


# --------------------------------------------------------------------- registry


def test_registry_reports_the_real_lifecycle_states() -> None:
    registry = _registry()
    counts = registry.counts_by_status()
    assert counts["PAPER_CANDIDATE"] == 1
    assert counts["NO_GROSS_EDGE"] == 1
    assert counts["RESEARCH_REQUIRED"] == 1
    assert counts["PAPER_ACTIVE"] == 0


def test_registry_records_carry_the_registry_contract() -> None:
    record = _registry().record("ema_crossover@5m")
    assert record is not None
    payload = record.to_dict()
    for field in (
        "strategy_id",
        "version",
        "family",
        "assets",
        "timeframes",
        "required_data",
        "required_features",
        "admission_status",
        "evidence_ids",
    ):
        assert field in payload, field
    assert payload["assets"] == ["BTC", "ETH", "SOL"]
    assert payload["timeframes"] == ["5m"]
    assert payload["required_data"] == ["ohlcv"]
    assert any("STRATEGY_DISCOVERY_V3_RESULTS.json" in e for e in payload["evidence_ids"])


def test_strategy_map_uses_lifecycle_states_not_a_confirmed_constant() -> None:
    strategy_map = _registry().strategy_map("5m")
    assert strategy_map["ema_crossover@5m"]["status"] == "PAPER_CANDIDATE"
    assert strategy_map["breakout@5m"]["status"] == "NO_GROSS_EDGE"
    assert "CONFIRMED" not in {entry["status"] for entry in strategy_map.values()}
    assert "RESEARCH_ONLY" not in {entry["status"] for entry in strategy_map.values()}


def test_only_the_admitted_strategy_is_paper_executable() -> None:
    registry = _registry()
    assert registry.paper_candidates("5m") == ["ema_crossover@5m"]
    refusals = {row["strategy_id"]: row["reason"] for row in registry.refusals("5m")}
    assert "NO_GROSS_EDGE" in refusals["breakout@5m"]
    assert "RESEARCH_REQUIRED" in refusals["microstructure_imbalance@5m"]


def test_a_timeframe_nobody_researched_has_no_candidates() -> None:
    registry = _registry()
    assert registry.paper_candidates("30m") == []
    assert registry.strategy_map("30m") == {}


def test_a_strategy_needing_data_the_runtime_lacks_cannot_be_candidate() -> None:
    """§37 — required_data is enforced, not decorative."""
    record = StrategyRecord(
        strategy_id="m03@5m",
        version="order_book_imbalance@5m",
        family="order_book_imbalance",
        assets=("BTC",),
        timeframes=("5m",),
        required_data=("order_book",),
        required_features=("book_imbalance",),
        admission_status=AdmissionStatus.PAPER_CANDIDATE,
        evidence_ids=("docs/x.json",),
        expected_gross_edge_bps=5.0,
        admitted_for_paper=True,
    )
    ready, reason = record.data_readiness(AVAILABLE_PAPER_DATA)
    assert not ready and "order_book" in reason
    executable, why = record.paper_executable(AVAILABLE_PAPER_DATA)
    assert not executable and "missing required data" in why

    with pytest.raises(StrategyStateError, match="requires data it cannot get"):
        StrategyRegistry(records={"m03@5m": record}, source="test").assert_consistent()


def test_an_active_strategy_must_be_admitted() -> None:
    with pytest.raises(ValueError, match="PAPER_ACTIVE requires admitted_for_paper"):
        AdmissionEntry(
            strategy_id="x@5m",
            family="x",
            status=AdmissionStatus.PAPER_ACTIVE,
            admitted_for_paper=False,
            expected_gross_edge_bps=1.0,
            edge_evidence=None,
            source_doc="docs/x.json",
            rationale="",
        )


def test_a_retired_strategy_cannot_be_admitted() -> None:
    with pytest.raises(ValueError, match="admitted_for_paper requires one of"):
        AdmissionEntry(
            strategy_id="x@5m",
            family="x",
            status=AdmissionStatus.PAPER_RETIRED,
            admitted_for_paper=True,
            expected_gross_edge_bps=1.0,
            edge_evidence=EdgeEvidence(
                source_doc="docs/x.json",
                metric="m",
                value_bps=1.0,
                knowledge="ESTIMATED",
                sample_trades=1,
            ),
            source_doc="docs/x.json",
            rationale="",
        )


def test_registry_describe_names_the_lifecycle_and_the_refusals() -> None:
    lines = _registry().describe("5m")
    text = "\n".join(lines)
    assert "PAPER_CANDIDATE=1" in text
    assert "paper-executable on 5m: ['ema_crossover@5m']" in text
    assert "refused breakout@5m" in text


def test_the_committed_ledger_produces_zero_paper_candidates() -> None:
    """§18 — the shipped state admits nobody, and says so."""
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[3]
    ledger = AdmissionLedger.load(repo_root / "config" / "strategy_admission.json")
    registry = StrategyRegistry.from_ledger(ledger, assets=["BTC", "ETH", "SOL"])
    assert registry.paper_candidates("5m") == []
    assert registry.counts_by_status()["PAPER_ACTIVE"] == 0
    assert all(
        record.admission_status not in PAPER_AUTHORISING_STATUSES
        for record in registry.records.values()
    )
