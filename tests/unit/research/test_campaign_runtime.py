"""CAP-004 — focused tests for the autonomous campaign runtime.

What is pinned here is the *supervision* surface: the campaign identity cannot
drift unnoticed, the decision slot is a fixed UTC grid taken from CAP-003, a
horizon is settled to the second or not at all, raw evidence is fingerprinted and
never silently re-fetched, NO_TRADE is a first-class decision whose counterfactual
is never called a profit, comparator D is reproducible, a checkpoint is written
once for its population, and two runners can never own the same campaign.

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import copy
import datetime as dt
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from trading_bot.market_data.types import OHLCV
from trading_bot.research import agentic_contracts as ac
from trading_bot.research import alpha_scorecard as asc
from trading_bot.research import analyst_provenance as ap
from trading_bot.research import campaign_lock as cl
from trading_bot.research import campaign_manifest as cm
from trading_bot.research import campaign_reporting as cr
from trading_bot.research import campaign_state as cs
from trading_bot.research import decision_ledger as dl
from trading_bot.research import decision_outcomes as do
from trading_bot.research import market_analyst_v1 as mav
from trading_bot.research import real_market_context as rmc

BAR = 14_400
DT = BAR * 118_055
HORIZON = "24H"
ROUND_TRIP = 0.002
CODE_COMMIT = "0" * 40

ANALYST_ANSWER: dict[str, Any] = {
    "asset": "BINANCE:BTCUSDT",
    "decision": "LONG",
    "horizon": HORIZON,
    "thesis": "test thesis",
    "evidence": ["test evidence"],
    "counter_evidence": [],
    "invalidation": "test invalidation",
    "confidence": 0.55,
    "expected_holding_period": "1 day",
    "decision_time": DT,
}


def _provenance(**overrides: str) -> dict[str, str]:
    base = ap.AnalystProvenance(
        analyst_id=mav.PROMPT_VERSION,
        prompt_version=mav.PROMPT_VERSION,
        prompt_digest=mav.prompt_digest(),
        model="freebuff-agent-in-context",
        provider="freebuff",
        temperature=ap.NOT_EXPOSED,
        schema_version=ap.SCHEMA_VERSION,
        feature_version=ap.FEATURE_VERSION,
        dataset="binance_public_ccxt",
    ).to_dict()
    base.update(overrides)
    return base


def _bar(open_time: int, close: float) -> OHLCV:
    return OHLCV(
        symbol="BTC/USDT",
        timestamp=open_time * 1_000,
        open=close,
        high=close * 1.001,
        low=close * 0.999,
        close=close,
        volume=1.0,
    )


def _rows() -> list[OHLCV]:
    rows: list[OHLCV] = []
    open_time = DT - 8 * BAR
    price = 100.0
    for _ in range(14):
        rows.append(_bar(open_time, price))
        open_time += BAR
        price += 1.0
    return rows


def _artifact(raw_evidence_hash: str | None = None) -> dict[str, Any]:
    snapshot = {
        "timestamp": DT,
        "asset": "BINANCE:BTCUSDT",
        "market_regime": "trend_up_low_volatility",
    }
    return {
        "asset": "BINANCE:BTCUSDT",
        "provider": rmc.PROVIDER,
        "source_type": rmc.REAL_SOURCE_TYPE,
        "snapshot": snapshot,
        "snapshot_hash": ac.payload_digest(snapshot),
        "raw_evidence_hash": raw_evidence_hash or "a" * 64,
        "technicals": {"RSI": 55.0},
        "derived": {"daily_bars_for_sma200": 220},
    }


def _record(direction: str = "LONG", *, snapshot_hash: str | None = None) -> ac.DecisionRecord:
    payload = dict(ANALYST_ANSWER)
    payload["decision"] = direction
    if direction == "NO_TRADE":
        payload["evidence"] = []
        payload["no_trade_reason"] = "no edge"
    return mav.seal_analyst_decision(
        payload,
        snapshot_hash=snapshot_hash or _artifact()["snapshot_hash"],
        raw_data_hash="b" * 64,
        critic_output={"note": "test"},
        provenance=_provenance(),
    )


def _entry(
    direction: str = "LONG",
    *,
    raw_evidence_path: str = "",
    artifact: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return dl.decision_entry(
        record=_record(direction),
        snapshot_artifact=artifact or _artifact(),
        provenance=_provenance(),
        raw_evidence_path=raw_evidence_path,
        recorded_at=DT,
    )


def _raw_payload(price: float = 100.0) -> dict[str, Any]:
    bars = [
        [DT - BAR, price, price, price, price, 1.0],
        [DT, price, price, price, price, 1.0],
    ]
    return {
        "provider": rmc.PROVIDER,
        "intervals": {
            "4h": {
                "bar_seconds": BAR,
                "first_open_time": DT - BAR,
                "last_open_time": DT,
                "bars": bars,
            }
        },
    }


def _perf(
    index: int,
    *,
    decision: str = "LONG",
    net_return: float = 0.01,
    confidence: float = 0.6,
) -> do.DecisionPerformance:
    entry = 100.0
    exit_price = entry * 1.01
    directional = decision != "NO_TRADE"
    gross = 0.0
    if decision == "LONG":
        gross = exit_price / entry - 1.0
    elif decision == "SHORT":
        gross = 1.0 - exit_price / entry
    return do.DecisionPerformance(
        decision_id=f"DEC-{index:016x}",
        decision_hash=f"{index:064x}",
        outcome_hash=f"{index + 1:064x}",
        asset="BINANCE:BTCUSDT" if index % 2 == 0 else "BINANCE:ETHUSDT",
        decision=decision,
        horizon=HORIZON,
        confidence=confidence,
        decision_time=DT,
        evaluation_time=DT + 86_400,
        entry_price=entry,
        exit_price=exit_price,
        gross_return=gross,
        costs=ROUND_TRIP if directional else 0.0,
        net_return=net_return,
        direction_correct=directional,
        outcome="WIN" if net_return > 0 else "LOSS",
        invalidation_hit=None,
        mfe=0.02 if directional else 0.0,
        mae=-0.01 if directional else 0.0,
        comparisons=(
            do.BaselineComparison(
                baseline_id=do.BASELINE_ID_DETERMINISTIC,
                direction="NO_TRADE" if index % 3 == 0 else "LONG",
                available=True,
                gross_return=0.005,
                costs=0.0 if index % 3 == 0 else ROUND_TRIP,
                net_return=0.0 if index % 3 == 0 else 0.005 - ROUND_TRIP,
                rule_version=do.DETERMINISTIC_RULE_VERSION,
            ),
            do.BaselineComparison(
                baseline_id=do.BASELINE_ID_BUY_AND_HOLD,
                direction="LONG",
                available=True,
                gross_return=gross,
                costs=ROUND_TRIP,
                net_return=gross - ROUND_TRIP,
                rule_version="BUY_AND_HOLD",
            ),
        ),
        cost_bps_per_side=10.0,
        round_trip_cost=ROUND_TRIP,
        source="TEST",
    ).with_hash()


# --------------------------------------------------------------------------- #
# §3 / §16 / §17 — campaign identity and drift
# --------------------------------------------------------------------------- #


def test_manifest_freezes_the_cap003_contract() -> None:
    manifest = cm.build_manifest(created_at=DT, code_commit=CODE_COMMIT)
    assert manifest["campaign_id"] == "CAP004-REAL-DECISIONS-V1"
    assert manifest["campaign_version"] == "1.0"
    assert manifest["horizon"] == "24H"
    assert manifest["assets"] == list(rmc.CAMPAIGN_ASSETS)
    assert manifest["prompt_version"] == mav.PROMPT_VERSION
    assert manifest["prompt_digest"] == mav.prompt_digest()
    assert manifest["schema_version"] == ap.SCHEMA_VERSION
    assert manifest["feature_version"] == ap.FEATURE_VERSION
    assert manifest["baselines"]["B"]["version"] == do.DETERMINISTIC_RULE_VERSION
    assert manifest["cost_model"]["round_trip_fraction"] == pytest.approx(ROUND_TRIP)
    assert manifest["min_evaluable_decisions"] == asc.MIN_EVALUABLE_DECISIONS == 100
    assert manifest["checkpoints"] == list(asc.CHECKPOINTS)
    assert manifest["code_commit"] == CODE_COMMIT
    # the freeze is carried in the identity, not merely referenced
    assert manifest["trades_authorized"] == 0 == ac.TRADES_AUTHORIZED
    assert manifest["alpha_claimed"] == ac.ALPHA_CLAIMED
    assert manifest["alpha_research_freeze"] == ac.ALPHA_RESEARCH_FREEZE
    assert manifest["runtime_promotion"] == "FORBIDDEN"


def test_manifest_round_trips_and_its_digest_is_stable(tmp_path: Path) -> None:
    manifest = cm.build_manifest(created_at=DT, code_commit=CODE_COMMIT)
    path = cm.write_manifest(tmp_path, manifest)
    assert path.name == cm.CAMPAIGN_MANIFEST_FILENAME
    loaded = cm.load_manifest(tmp_path)
    assert loaded == manifest
    assert cm.manifest_digest(loaded) == cm.manifest_digest(manifest)


def test_drift_is_clean_when_nothing_moved() -> None:
    manifest = cm.build_manifest(created_at=DT, code_commit=CODE_COMMIT)
    drift = cm.detect_drift(manifest)
    assert drift["status"] == "NO_DRIFT"
    assert drift["drifted"] == []


@pytest.mark.parametrize(
    ("mutate", "label"),
    [
        (lambda m: m.update(prompt_digest="0" * 64), "PROMPT_DRIFT"),
        (lambda m: m.update(prompt_version="MARKET_ANALYST_V9.9"), "PROMPT_DRIFT"),
        (lambda m: m.update(schema_version="TAMPERED"), "FEATURE_DRIFT"),
        (lambda m: m.update(feature_version="TAMPERED"), "FEATURE_DRIFT"),
        (lambda m: m["cost_model"].update(round_trip_fraction=0.25), "CAMPAIGN_CONFIGURATION_DRIFT"),
        (lambda m: m["baselines"]["B"].update(version="B_ROGUE"), "CAMPAIGN_CONFIGURATION_DRIFT"),
        (lambda m: m.update(horizon="4H"), "CAMPAIGN_CONFIGURATION_DRIFT"),
        (lambda m: m["cadence"].update(decision_slot_utc_hour=0), "CAMPAIGN_CONFIGURATION_DRIFT"),
    ],
)
def test_any_frozen_knob_move_blocks_the_campaign(mutate: Any, label: str) -> None:
    manifest = cm.build_manifest(created_at=DT, code_commit=CODE_COMMIT)
    mutate(manifest)
    drift = cm.detect_drift(manifest)
    assert drift["status"] == label
    assert drift["drifted"]
    # nothing here ever updates the manifest automatically
    assert drift["live"]["prompt_digest"] == mav.prompt_digest()


def test_model_drift_is_detected_and_splits_the_cohort() -> None:
    manifest = cm.build_manifest(created_at=DT, code_commit=CODE_COMMIT)
    entry = _entry()
    assert cm.detect_model_drift(manifest, [entry])["status"] == "NO_DRIFT"

    drifted = copy.deepcopy(entry)
    drifted["provenance"]["model"] = "some-other-model"
    result = cm.detect_model_drift(manifest, [drifted])
    assert result["status"] == cm.MODEL_DRIFT
    assert result["drifted"][0]["model"] == "some-other-model"
    assert result["expected_model"] == "freebuff-agent-in-context"


def test_cohort_of_adopts_the_legacy_pilot_without_rewriting_it() -> None:
    entry = _entry()
    assert cm.cohort_of(entry) == cm.COHORT_LEGACY_CAP003_PILOT

    campaign_entry = copy.deepcopy(entry)
    campaign_entry["provenance"]["campaign_id"] = cm.CAMPAIGN_ID
    assert cm.cohort_of(campaign_entry) == cm.CAMPAIGN_ID
    assert (
        cm.cohort_of(campaign_entry, expected_model="freebuff-agent-in-context")
        == cm.CAMPAIGN_ID
    )
    assert cm.MODEL_DRIFT in cm.cohort_of(campaign_entry, expected_model="a-different-model")


def test_campaign_provenance_requires_the_extended_fields() -> None:
    complete = cm.build_campaign_provenance(code_commit=CODE_COMMIT)
    assert cm.campaign_provenance_missing(complete) == []
    assert complete["campaign_id"] == cm.CAMPAIGN_ID
    assert complete["code_commit"] == CODE_COMMIT
    assert complete["temperature"] == ap.NOT_EXPOSED
    assert cm.campaign_provenance_missing({}) == list(cm.CAMPAIGN_PROVENANCE_FIELDS)
    assert cm.campaign_provenance_missing(complete | {"code_commit": ""}) == ["code_commit"]
    assert cm.campaign_provenance_missing(complete | {"campaign_id": "  "}) == ["campaign_id"]


# --------------------------------------------------------------------------- #
# §5 — the decision slot is a fixed grid, taken from CAP-003
# --------------------------------------------------------------------------- #


def test_the_decision_slot_is_the_cap003_1600_utc_grid() -> None:
    slot = cm.due_decision_slot(DT)
    assert cm.DECISION_SLOT_UTC_HOUR == 16
    # the due slot is a real 16:00 UTC boundary on the daily grid
    assert slot % 86_400 == cm.DECISION_SLOT_UTC_HOUR * 3_600
    assert cm.decision_slot_unix(dt.datetime.fromtimestamp(DT, dt.UTC).date()) == slot
    before = slot - 1
    assert cm.due_decision_slot(before) == slot - 86_400
    assert cm.next_decision_slot(before) == slot
    assert cm.next_decision_slot(slot) == slot + 86_400


def test_decision_key_is_deterministic_and_marks_the_consumed_slot() -> None:
    entry = _entry()
    key = cm.decision_key(
        asset=entry["asset"],
        decision_time=entry["decision_time"],
        horizon=entry["horizon"],
        analyst_version=entry["prompt_version"],
    )
    assert key == cm.decision_key(
        asset=entry["asset"],
        decision_time=entry["decision_time"],
        horizon=entry["horizon"],
        analyst_version=entry["prompt_version"],
    )
    assert key in cm.occupied_decision_keys([entry])
    # the same asset at a later slot is a different key
    later = cm.decision_key(
        asset=entry["asset"],
        decision_time=entry["decision_time"] + 86_400,
        horizon=entry["horizon"],
        analyst_version=entry["prompt_version"],
    )
    assert later != key
    assert later not in cm.occupied_decision_keys([entry])


# --------------------------------------------------------------------------- #
# §7 / §54 — maturity is enforced to the second
# --------------------------------------------------------------------------- #


def test_maturity_is_enforced_to_the_second() -> None:
    just_before = cs.maturity_state(decision_time=DT, horizon=HORIZON, now=DT + 86_400 - 1)
    assert just_before["maturity"] == cs.STATE_PENDING_MATURITY
    assert just_before["matured"] is False

    exact = cs.maturity_state(decision_time=DT, horizon=HORIZON, now=DT + 86_400)
    assert exact["maturity"] == "MATURED"
    assert exact["matured"] is True
    assert exact["overdue_seconds"] == 0

    after = cs.maturity_state(decision_time=DT, horizon=HORIZON, now=DT + 3 * 86_400)
    assert after["matured"] is True
    assert after["maturity_time"] == exact["maturity_time"]


def test_populations_stay_separate_and_a_matured_unsettled_degrades(tmp_path: Path) -> None:
    ledger = dl.DecisionLedger(tmp_path / "real_decisions")
    ledger.append_decision(_entry())
    early = cs.campaign_counters(ledger, now=DT)
    assert early["sealed_decisions"] == 1
    assert early["pending_decisions"] == 1
    assert early["matured_decisions"] == 0
    assert early["evaluated_decisions"] == 0
    assert cs.campaign_status_name(
        counters=early, chain_verified=True, drift={"status": "NO_DRIFT"}
    ) == "RUNNING"

    late = cs.campaign_counters(ledger, now=DT + 86_400)
    assert late["matured_decisions"] == 1
    assert late["matured_unsettled"] == 1
    assert cs.campaign_status_name(
        counters=late, chain_verified=True, drift={"status": "NO_DRIFT"}
    ) == "DEGRADED"


def test_campaign_status_vocabulary_never_promises_an_outcome() -> None:
    assert cs.FORBIDDEN_STATUS_WORDS == (
        "PROFITABLE",
        "EDGE_CONFIRMED",
        "STRATEGY_VALIDATED",
        "PAPER_READY",
        "LIVE_READY",
    )
    assert not set(cs.FORBIDDEN_STATUS_WORDS) & set(cs.CAMPAIGN_STATUSES)
    assert (
        cs.campaign_status_name(
            counters={"evaluated_decisions": 0}, chain_verified=False, drift={"status": "NO_DRIFT"}
        )
        == "INTEGRITY_FAILURE"
    )
    assert (
        cs.campaign_status_name(
            counters={"sealed_decisions": 1}, chain_verified=True, drift={"status": "PROMPT_DRIFT"}
        )
        == "BLOCKED"
    )
    assert (
        cs.campaign_status_name(
            counters={"sealed_decisions": 0},
            chain_verified=True,
            drift={"status": "NO_DRIFT"},
        )
        == "INITIALIZING"
    )
    assert (
        cs.campaign_status_name(
            counters={"sealed_decisions": 5, "evaluated_decisions": 100},
            chain_verified=True,
            drift={"status": "NO_DRIFT"},
        )
        == "COMPLETE_100"
    )


# --------------------------------------------------------------------------- #
# §13 / §57 — raw evidence is fingerprinted, never silently re-fetched
# --------------------------------------------------------------------------- #


def _raw_entry(tmp_path: Path, *, write: bool = True, mutate_price: bool = False) -> dict[str, Any]:
    payload = _raw_payload()
    digest = cs.canonical_content_digest(payload)
    artifact = _artifact(raw_evidence_hash=digest)
    entry = _entry(raw_evidence_path="raw_evidence/snapshot.json", artifact=artifact)
    if write:
        on_disk = _raw_payload(price=999.0) if mutate_price else payload
        target = tmp_path / entry["raw_evidence_path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(on_disk, sort_keys=True), encoding="utf-8")
    return entry


def test_raw_evidence_present_and_hash_matching_is_verified(tmp_path: Path) -> None:
    entry = _raw_entry(tmp_path)
    registered = cs.register_unregistered_raw_evidence(tmp_path, decisions=[entry], now=DT)
    assert registered[0]["status"] == "REGISTERED"
    status = cs.raw_evidence_status(tmp_path, decisions=[entry])
    assert status["per_snapshot"][entry["snapshot_hash"]]["status"] == "PRESENT_VERIFIED"
    assert status["status"] == "RAW_EVIDENCE_COMPLETE"
    assert cs.read_raw_evidence(tmp_path)[0]["snapshot_hash"] == entry["snapshot_hash"]


def test_raw_evidence_missing_is_reported_not_recreated(tmp_path: Path) -> None:
    entry = _raw_entry(tmp_path, write=False)
    assert not (tmp_path / entry["raw_evidence_path"]).is_file()
    registered = cs.register_unregistered_raw_evidence(tmp_path, decisions=[entry], now=DT)
    assert registered[0]["status"] == "RAW_EVIDENCE_MISSING"
    manifest = cs.read_raw_evidence(tmp_path)
    assert len(manifest) == 1
    # the expectation is remembered, but no bar is ever fabricated
    assert manifest[0]["intervals"] == []
    assert manifest[0]["raw_evidence_hash"] == entry["raw_evidence_hash"]
    status = cs.raw_evidence_status(tmp_path, decisions=[entry])
    assert status["per_snapshot"][entry["snapshot_hash"]]["status"] == "RAW_EVIDENCE_MISSING"


def test_raw_evidence_hash_mismatch_is_detected_on_a_changed_price(tmp_path: Path) -> None:
    entry = _raw_entry(tmp_path, mutate_price=True)
    cs.register_unregistered_raw_evidence(tmp_path, decisions=[entry], now=DT)
    status = cs.raw_evidence_status(tmp_path, decisions=[entry])
    record = status["per_snapshot"][entry["snapshot_hash"]]
    assert record["status"] == "RAW_EVIDENCE_HASH_MISMATCH"
    assert record["observed_sha256"] != record["expected_sha256"]


def test_unregistered_raw_evidence_is_reported(tmp_path: Path) -> None:
    entry = _entry()
    status = cs.raw_evidence_status(tmp_path, decisions=[entry])
    assert status["per_snapshot"][entry["snapshot_hash"]]["status"] == "RAW_EVIDENCE_UNREGISTERED"
    assert status["status"] in {"RAW_EVIDENCE_INCOMPLETE", "NO_DECISIONS"}


# --------------------------------------------------------------------------- #
# §20 / §21 / §22 / §58 — NO_TRADE is first class, its counterfactual is not PnL
# --------------------------------------------------------------------------- #


def test_no_trade_counterfactual_is_labelled_and_never_a_pnl() -> None:
    record = cs.no_trade_counterfactual(net_return=0.0, comparison_net_return=-0.03)
    assert record["label"] == "COUNTERFACTUAL"
    assert record["avoided_loss"] == pytest.approx(0.03)
    assert record["missed_gain"] == pytest.approx(0.0)
    assert record["delta_vs_counterfactual"] == pytest.approx(0.03)
    assert "pnl" not in json.dumps(record).lower()

    gain = cs.no_trade_counterfactual(net_return=0.0, comparison_net_return=0.02)
    assert gain["avoided_loss"] == pytest.approx(0.0)
    assert gain["missed_gain"] == pytest.approx(0.02)


def test_no_trade_selectivity_uses_no_trade_decisions() -> None:
    performances = [
        _perf(index, decision="NO_TRADE", net_return=0.0) for index in range(20)
    ] + [_perf(100 + index, decision="LONG", net_return=0.01) for index in range(20)]
    analysis = cs.no_trade_analysis(performances)
    assert analysis["status"] == "MEASURED"
    assert analysis["no_trade_count"] == 20
    assert analysis["directional_count"] == 20
    assert analysis["is_diagnostic_only"] is True
    assert len(analysis["counterfactuals"]) == 20
    assert all(item["label"] == "COUNTERFACTUAL" for item in analysis["counterfactuals"])
    assert analysis["bad_window_comparator"] == do.BASELINE_ID_BUY_AND_HOLD
    # the report never calls a counterfactual an executed profit
    assert "pnl" not in json.dumps(analysis).lower()


def test_selectivity_stays_insufficient_below_its_floor() -> None:
    performances = [_perf(index, decision="NO_TRADE", net_return=0.0) for index in range(3)]
    analysis = cs.no_trade_analysis(performances)
    assert analysis["status"] == "INSUFFICIENT_SAMPLE"
    assert analysis["no_trade_count"] == 3
    assert analysis["is_diagnostic_only"] is True


def test_no_trade_is_not_treated_as_missing_by_the_metrics() -> None:
    performances = [
        _perf(index, decision="NO_TRADE", net_return=0.0) for index in range(4)
    ] + [_perf(100 + index, decision="LONG", net_return=0.02) for index in range(4)]
    metrics = cs.campaign_metrics(performances)
    assert metrics["distribution"]["no_trade_count"] == 4
    assert metrics["distribution"]["no_trade_rate"] == pytest.approx(0.5)
    assert metrics["net"]["per_decision_sharpe"] is None
    assert metrics["net"]["sharpe_status"] == "NOT_COMPUTED_BELOW_SAMPLE_FLOOR"
    assert "INSUFFICIENT_SAMPLE" in metrics["sample_warnings"]


# --------------------------------------------------------------------------- #
# §19 / §59 — comparator D is reproducible
# --------------------------------------------------------------------------- #


def test_random_assignment_is_deterministic_for_the_same_decision_set() -> None:
    directions = ["LONG", "SHORT", "NO_TRADE", "LONG", "SHORT"]
    first = do.matched_random_directions(list(directions), seed=asc.RANDOM_BASELINE_SEED)
    second = do.matched_random_directions(list(directions), seed=asc.RANDOM_BASELINE_SEED)
    assert first == second
    assert sorted(first) == sorted(directions)  # an exact permutation, same mix
    other = do.matched_random_directions(list(directions), seed=asc.RANDOM_BASELINE_SEED + 1)
    assert other != first  # a different seed moves the assignment


def test_scorecard_records_the_assignment_digest_and_moves_with_the_set() -> None:
    performances = [_perf(index) for index in range(4)]
    first = asc.alpha_scorecard(performances)
    again = asc.alpha_scorecard(performances)
    assert first["comparators"][do.BASELINE_ID_RANDOM_MATCHED]["assignment_digest"] == (
        again["comparators"][do.BASELINE_ID_RANDOM_MATCHED]["assignment_digest"]
    )
    assert first["comparators"][do.BASELINE_ID_RANDOM_MATCHED]["seed"] == asc.RANDOM_BASELINE_SEED
    assert first["gate"]["conclusion"] == asc.CONCLUSION_INSUFFICIENT_SAMPLE

    grown = asc.alpha_scorecard([*performances, _perf(99)])
    assert grown["comparators"][do.BASELINE_ID_RANDOM_MATCHED]["assignment_digest"] != (
        first["comparators"][do.BASELINE_ID_RANDOM_MATCHED]["assignment_digest"]
    )


# --------------------------------------------------------------------------- #
# §24 / §46 — a checkpoint is written once for its population
# --------------------------------------------------------------------------- #


def _checkpoint_payload(checkpoint: int, performances: list[do.DecisionPerformance]) -> dict[str, Any]:
    return cr.build_checkpoint_payload(
        checkpoint=checkpoint,
        performances=performances,
        scorecard=asc.alpha_scorecard(performances),
        metrics=cs.campaign_metrics(performances),
        no_trade=cs.no_trade_analysis(performances),
        counters={"sealed_decisions": len(performances), "evaluated_decisions": len(performances)},
        drift={"status": "NO_DRIFT", "drifted": []},
        model_drift={"status": "NO_DRIFT"},
        now=DT,
    )


def test_checkpoint_is_written_once_and_refuses_another_population(tmp_path: Path) -> None:
    one = _checkpoint_payload(20, [_perf(index) for index in range(20)])
    assert one["edge_verdict"] == "NOT_PERMITTED_BELOW_SAMPLE_FLOOR"
    assert one["is_diagnostic_only"] is True
    first = cr.write_checkpoint(tmp_path, one)
    assert first["status"] == "CREATED"
    assert cr.checkpoint_md_path(tmp_path, 20).is_file()
    assert cr.checkpoint_json_path(tmp_path, 20).is_file()

    again = cr.write_checkpoint(tmp_path, _checkpoint_payload(20, [_perf(i) for i in range(20)]))
    assert again["status"] == "ALREADY_EXISTS"

    different = cr.write_checkpoint(tmp_path, _checkpoint_payload(20, [_perf(i) for i in range(21)]))
    assert different["status"] == "CHECKPOINT_CONFLICT"
    assert different["existing_decision_set_hash"] == first["decision_set_hash"]
    assert cr.read_checkpoint(tmp_path, 20)["n_evaluated"] == 20


# --------------------------------------------------------------------------- #
# §28 / §44 — observability carries no promotional vocabulary
# --------------------------------------------------------------------------- #


def test_status_and_heartbeat_render_without_a_promotional_word(tmp_path: Path) -> None:
    root = tmp_path / "real_decisions"
    ledger = dl.DecisionLedger(root)
    ledger.append_decision(_entry())
    manifest = cm.build_manifest(created_at=DT, code_commit=CODE_COMMIT)
    counters = cs.campaign_counters(ledger, now=DT)

    heartbeat = cr.heartbeat_payload(
        campaign_id=cm.CAMPAIGN_ID,
        campaign_version=cm.CAMPAIGN_VERSION,
        now=DT,
        process_status="RUNNING",
        counters=counters,
        cycle=1,
        interval_seconds=300,
        next_decision_slot=cm.next_decision_slot(DT),
        next_maturity=None,
    )
    cr.write_heartbeat(root, heartbeat)
    loaded = cr.read_heartbeat(root)
    assert loaded is not None
    assert loaded["campaign_id"] == cm.CAMPAIGN_ID
    assert loaded["pending_maturities"] == 1
    assert cr.heartbeat_age_seconds(loaded, now=DT + 5) == 5
    assert cr.heartbeat_age_seconds(None, now=DT) is None

    payload = cr.status_payload(
        manifest=manifest,
        counters=counters,
        scorecard=asc.alpha_scorecard([]),
        drift=cm.detect_drift(manifest),
        model_drift=cm.detect_model_drift(manifest, ledger.decisions()),
        raw_evidence=cs.raw_evidence_status(root, decisions=ledger.decisions()),
        chain=ledger.verify_chain(),
        status="RUNNING",
        now=DT,
        next_decision_slot=cm.next_decision_slot(DT),
        heartbeat=heartbeat,
    )
    blob = json.dumps(payload)
    assert "no_trade_count" in blob  # NO_TRADE is a reported population
    assert payload["direction_counts"]["long_count"] == 1
    rendered = cr.render_status_md(payload, metrics=cs.campaign_metrics([]))
    assert not any(word in rendered for word in cs.FORBIDDEN_STATUS_WORDS)
    assert not any(word in blob for word in cs.FORBIDDEN_STATUS_WORDS)


# --------------------------------------------------------------------------- #
# §31 / §32 / §33 — one runner per campaign, with offline recovery
# --------------------------------------------------------------------------- #


def test_a_second_instance_is_refused_while_the_lease_is_live(tmp_path: Path) -> None:
    lock = cl.CampaignLock(tmp_path, campaign_id=cm.CAMPAIGN_ID, stale_after_seconds=1_800)
    first = lock.acquire(now=DT)
    assert first["acquired"] is True
    assert first["status"] == "ACQUIRED"

    second = cl.CampaignLock(tmp_path, campaign_id=cm.CAMPAIGN_ID, stale_after_seconds=1_800)
    again = second.acquire(now=DT)
    assert again["acquired"] is False
    assert again["status"] == "ALREADY_RUNNING"
    assert again["holder"]["campaign_id"] == cm.CAMPAIGN_ID

    assert lock.renew(now=DT + 10)["status"] == "RENEWED"
    assert lock.release()["status"] == "RELEASED"
    assert cl.CampaignLock(tmp_path, campaign_id=cm.CAMPAIGN_ID).acquire(now=DT)["status"] == "ACQUIRED"


def test_a_stale_lease_is_reclaimed_after_a_crash(tmp_path: Path) -> None:
    lock = cl.CampaignLock(tmp_path, campaign_id=cm.CAMPAIGN_ID, stale_after_seconds=1_800)
    lock.path.write_text(
        json.dumps(
            {
                "lease_version": cl.LEASE_VERSION,
                "campaign_id": cm.CAMPAIGN_ID,
                "pid": 999_999,
                "renewed_at": DT - 10_000,
            }
        ),
        encoding="utf-8",
    )
    reclaimed = lock.acquire(now=DT)
    assert reclaimed["acquired"] is True
    assert reclaimed["status"] == "STALE_LEASE_RECLAIMED"


def test_stop_flag_is_raiseable_and_clearable(tmp_path: Path) -> None:
    lock = cl.CampaignLock(tmp_path, campaign_id=cm.CAMPAIGN_ID)
    assert lock.stop_requested() is False
    path = lock.request_stop(reason="operator")
    assert path.name == cl.STOP_FILENAME
    assert lock.stop_requested() is True
    lock.clear_stop()
    assert lock.stop_requested() is False


# --------------------------------------------------------------------------- #
# §32 / §33 — settlement waits for maturity, runs once, survives a restart
# --------------------------------------------------------------------------- #


def _load_runner() -> Any:
    path = Path(__file__).resolve().parents[3] / "scripts" / "cap004_campaign_runner.py"
    spec = importlib.util.spec_from_file_location("cap004_runner_probe", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _rows_by_asset() -> dict[str, dict[str, list[OHLCV]]]:
    return {"BINANCE:BTCUSDT": {"4h": _rows(), "1D": _rows()}}


def test_settle_waits_for_maturity_and_settles_exactly_once(tmp_path: Path) -> None:
    runner = _load_runner()
    ledger = dl.DecisionLedger(tmp_path / "real_decisions")
    ledger.append_decision(_entry())

    early = runner.settle_phase(ledger, rows_by_asset=_rows_by_asset(), now=DT + 86_400 - 1)
    assert early["settled"] == []
    assert len(early["pending"]) == 1
    assert early["pending"][0]["state"] == cs.STATE_PENDING_MATURITY
    assert ledger.outcomes() == []  # never settled a second before maturity

    # a restart after the horizon closed settles the matured decision
    matured = runner.settle_phase(ledger, rows_by_asset=_rows_by_asset(), now=DT + 86_400)
    assert len(matured["settled"]) == 1
    assert len(ledger.outcomes()) == 1
    assert len(ledger.evaluations()) == 1
    assert ledger.verify_chain()["status"] == "INTACT"

    # re-running much later never creates a second outcome
    again = runner.settle_phase(ledger, rows_by_asset=_rows_by_asset(), now=DT + 9 * 86_400)
    assert again["settled"] == []
    assert len(ledger.outcomes()) == 1
    assert len(ledger.evaluations()) == 1


def test_settle_blocks_a_matured_decision_when_its_rows_are_absent(tmp_path: Path) -> None:
    runner = _load_runner()
    ledger = dl.DecisionLedger(tmp_path / "real_decisions")
    ledger.append_decision(_entry())
    result = runner.settle_phase(ledger, rows_by_asset={}, now=DT + 86_400)
    assert result["settled"] == []
    assert result["blocked"][0]["code"] == "OUTCOME_BLOCKED_DATA"
    assert any(item["code"] == "OUTCOME_BLOCKED_DATA" for item in result["errors"])
    assert ledger.outcomes() == []  # no extrapolated or substituted candle
