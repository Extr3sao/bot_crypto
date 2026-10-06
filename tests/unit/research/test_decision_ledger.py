"""CAP-003 — focused tests for the append-only real decision ledger.

What is pinned here is the integrity surface: a decision without complete
provenance cannot enter the campaign, hashes are re-derived on the way in, a
duplicate or a tampered line is refused/detected, an outcome must point at a
decision already in the ledger, comparator D is never baked into an immutable
evaluation, and ``replay`` reconstructs exactly what the analyst saw.

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from trading_bot.market_data.types import OHLCV
from trading_bot.research import agentic_contracts as ac
from trading_bot.research import alpha_scorecard as asc
from trading_bot.research import analyst_provenance as ap
from trading_bot.research import decision_ledger as dl
from trading_bot.research import decision_outcomes as do
from trading_bot.research import market_analyst_v1 as mav

BAR = 14_400
DT = BAR * 118_055
HORIZON = "24H"

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


def _artifact() -> dict[str, Any]:
    snapshot = {
        "timestamp": DT,
        "asset": "BINANCE:BTCUSDT",
        "market_regime": "trend_up_low_volatility",
    }
    return {
        "asset": "BINANCE:BTCUSDT",
        "provider": "binance_public_ccxt",
        "source_type": "REAL_MARKET_DATA",
        "snapshot": snapshot,
        "snapshot_hash": ac.payload_digest(snapshot),
        "raw_evidence_hash": "a" * 64,
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


def _entry(direction: str = "LONG") -> dict[str, Any]:
    return dl.decision_entry(
        record=_record(direction),
        snapshot_artifact=_artifact(),
        provenance=_provenance(),
        recorded_at=DT,
    )


# --------------------------------------------------------------------------- #
# provenance
# --------------------------------------------------------------------------- #


def test_provenance_requires_every_declared_field() -> None:
    assert ap.provenance_missing(_provenance()) == []
    assert ap.provenance_missing({}) == list(ap.PROVENANCE_FIELDS)
    assert ap.provenance_missing(_provenance(temperature="")) == ["temperature"]
    assert ap.provenance_missing(_provenance(model="  ")) == ["model"]


def test_provenance_digest_is_stable_and_sensitive() -> None:
    record = _provenance()
    assert ap.provenance_digest(record) == ap.provenance_digest(dict(record))
    assert ap.provenance_digest(record) != ap.provenance_digest(_provenance(model="other"))


def test_unexposed_sampling_parameters_are_declared_not_invented() -> None:
    assert ap.NOT_EXPOSED == "NOT_EXPOSED"
    assert _provenance()["temperature"] == ap.NOT_EXPOSED


def test_sealing_refuses_incomplete_provenance() -> None:
    with pytest.raises(ValueError, match="incomplete provenance"):
        mav.seal_analyst_decision(
            dict(ANALYST_ANSWER),
            snapshot_hash="c" * 64,
            raw_data_hash="d" * 64,
            provenance=_provenance(provider=""),
        )


def test_sealing_without_provenance_stays_backwards_compatible() -> None:
    payload = dict(ANALYST_ANSWER)
    payload["decision"] = "NO_TRADE"
    payload["evidence"] = []
    payload["no_trade_reason"] = "no edge"
    record = mav.seal_analyst_decision(payload, snapshot_hash="c" * 64, raw_data_hash="d" * 64)
    assert record.is_verified()
    assert "provenance" not in record.agent_output


# --------------------------------------------------------------------------- #
# building an entry
# --------------------------------------------------------------------------- #


def test_decision_entry_embeds_snapshot_and_provenance() -> None:
    artifact = _artifact()
    entry = _entry()
    assert entry["ledger_version"] == dl.LEDGER_VERSION
    assert entry["decision_id"] == "DEC-" + entry["decision_hash"][:16]
    assert entry["snapshot"] == artifact["snapshot"]
    assert entry["snapshot_hash"] == artifact["snapshot_hash"]
    assert entry["horizon"] == HORIZON
    assert entry["horizon_seconds"] == 86_400
    assert entry["provenance_digest"] == ap.provenance_digest(_provenance())
    assert entry["recorded_at"] == DT
    assert dl.record_from_entry(entry).is_verified()


def test_decision_entry_refuses_incomplete_provenance() -> None:
    with pytest.raises(dl.LedgerError, match="provenance"):
        dl.decision_entry(
            record=_record(), snapshot_artifact=_artifact(), provenance=_provenance(dataset="")
        )


def test_decision_entry_refuses_a_snapshot_that_does_not_redigest() -> None:
    artifact = _artifact()
    artifact["snapshot"] = {"timestamp": DT, "tampered": True}
    with pytest.raises(dl.LedgerError, match="re-digest"):
        dl.decision_entry(record=_record(), snapshot_artifact=artifact, provenance=_provenance())


def test_decision_entry_refuses_a_record_sealed_against_another_snapshot() -> None:
    with pytest.raises(dl.LedgerError, match="not sealed against"):
        dl.decision_entry(
            record=_record(snapshot_hash="f" * 64),
            snapshot_artifact=_artifact(),
            provenance=_provenance(),
        )


def test_decision_entry_refuses_a_tampered_record() -> None:
    tampered = dataclasses.replace(_record("LONG"), decision="SHORT")
    with pytest.raises(dl.LedgerError, match="unsealed or tampered"):
        dl.decision_entry(record=tampered, snapshot_artifact=_artifact(), provenance=_provenance())


def test_decision_entry_refuses_a_foreign_horizon() -> None:
    payload = dict(ANALYST_ANSWER)
    payload["horizon"] = "1H"  # never sealable by the frozen analyst, so seal directly
    record = ac.seal_decision_record(
        timestamp=DT,
        prompt_version=mav.PROMPT_VERSION,
        evidence_snapshot_hash=_artifact()["snapshot_hash"],
        agent_output={"analyst": payload},
        critic_output=None,
        decision="LONG",
    )
    with pytest.raises(dl.LedgerError, match="unknown horizon"):
        dl.decision_entry(record=record, snapshot_artifact=_artifact(), provenance=_provenance())


def test_decision_entry_refuses_a_foreign_decision_time() -> None:
    payload = dict(ANALYST_ANSWER)
    payload["decision_time"] = DT + BAR
    record = ac.seal_decision_record(
        timestamp=DT,
        prompt_version=mav.PROMPT_VERSION,
        evidence_snapshot_hash=_artifact()["snapshot_hash"],
        agent_output={"analyst": payload},
        critic_output=None,
        decision="LONG",
    )
    with pytest.raises(dl.LedgerError, match="decision_time does not match"):
        dl.decision_entry(record=record, snapshot_artifact=_artifact(), provenance=_provenance())


# --------------------------------------------------------------------------- #
# the store
# --------------------------------------------------------------------------- #


def test_ledger_starts_empty_and_appends(tmp_path: Path) -> None:
    ledger = dl.DecisionLedger(tmp_path / "real_decisions")
    assert ledger.decisions() == []
    assert ledger.outcomes() == []
    assert ledger.evaluations() == []
    assert ledger.verify_chain()["status"] == "INTACT"
    assert ledger.replay("DEC-nothing")["found"] is False

    entry = _entry()
    assert ledger.append_decision(entry) == entry["decision_id"]
    assert ledger.has_decision(entry["decision_hash"])
    assert len(ledger.decisions()) == 1


def test_duplicate_decisions_are_refused(tmp_path: Path) -> None:
    ledger = dl.DecisionLedger(tmp_path)
    entry = _entry()
    ledger.append_decision(entry)
    with pytest.raises(dl.LedgerError, match="already in the ledger"):
        ledger.append_decision(entry)
    assert len(ledger.decisions()) == 1


def test_append_revalidates_the_sealed_hash(tmp_path: Path) -> None:
    ledger = dl.DecisionLedger(tmp_path)
    forged = _entry()
    forged["decision_hash"] = "0" * 64
    forged["decision_id"] = "DEC-" + "0" * 16
    with pytest.raises(dl.LedgerError, match="does not recompute"):
        ledger.append_decision(forged)
    wrong_id = _entry()
    wrong_id["decision_id"] = "DEC-" + "9" * 16
    with pytest.raises(dl.LedgerError, match="decision_id must be"):
        ledger.append_decision(wrong_id)
    assert ledger.decisions() == []


def test_append_refuses_an_entry_without_provenance(tmp_path: Path) -> None:
    ledger = dl.DecisionLedger(tmp_path)
    entry = _entry()
    entry["provenance"] = _provenance(temperature="")
    with pytest.raises(dl.LedgerError, match="incomplete provenance"):
        ledger.append_decision(entry)


def test_outcome_and_evaluation_require_their_parents(tmp_path: Path) -> None:
    ledger = dl.DecisionLedger(tmp_path)
    record = _record()
    outcome = do.evaluate_decision(
        record=record, asset="BINANCE:BTCUSDT", horizon=HORIZON, rows=_rows()
    )
    performance = do.build_performance(record=record, outcome=outcome, rows_4h=_rows())

    with pytest.raises(dl.LedgerError, match="not in the ledger"):
        ledger.append_outcome(outcome)
    with pytest.raises(dl.LedgerError, match="not in the ledger"):
        ledger.append_evaluation(performance)

    ledger.append_decision(_entry())
    ledger.append_outcome(outcome)
    ledger.append_evaluation(performance)
    with pytest.raises(dl.LedgerError, match="already has an outcome"):
        ledger.append_outcome(outcome)
    with pytest.raises(dl.LedgerError, match="already has an evaluation"):
        ledger.append_evaluation(performance)
    assert len(ledger.outcomes()) == 1
    assert len(ledger.evaluations()) == 1


def test_full_cycle_chain_is_intact_and_replayable(tmp_path: Path) -> None:
    ledger = dl.DecisionLedger(tmp_path)
    record = _record("SHORT")
    entry = dl.decision_entry(
        record=record, snapshot_artifact=_artifact(), provenance=_provenance(), recorded_at=DT
    )
    ledger.append_decision(entry)
    outcome = do.evaluate_decision(
        record=record, asset="BINANCE:BTCUSDT", horizon=HORIZON, rows=_rows()
    )
    ledger.append_outcome(outcome)
    performance = do.build_performance(record=record, outcome=outcome, rows_4h=_rows())
    ledger.append_evaluation(performance)

    chain = ledger.verify_chain()
    assert chain["status"] == "INTACT"
    assert (chain["n_decisions"], chain["n_outcomes"], chain["n_evaluations"]) == (1, 1, 1)
    assert chain["dup_decision_hashes"] == []

    replay = ledger.replay(outcome.decision_id)
    assert replay["found"] is True
    assert replay["settled"] is True
    assert replay["reconstructed_input"] == _artifact()["snapshot"]
    assert replay["chain"]["snapshot_hash"] == _artifact()["snapshot_hash"]
    assert replay["chain"]["outcomes"][0]["outcome_hash"] == outcome.outcome_hash
    assert replay["chain"]["evaluations"][0]["evaluation_hash"] == performance.evaluation_hash
    assert replay["checks"]["decision_record_verified"] is True
    assert replay["checks"]["snapshot_digest_matches"] is True
    assert replay["checks"]["provenance_complete"] is True
    assert replay["checks"]["raw_evidence_present"] is False
    assert replay["checks"]["raw_evidence_hash_matches"] is None


def test_ledger_preserves_append_order_and_pending(tmp_path: Path) -> None:
    ledger = dl.DecisionLedger(tmp_path)
    first = _entry("LONG")
    second = _entry("NO_TRADE")
    ledger.append_decision(first)
    ledger.append_decision(second)
    assert [e["decision_id"] for e in ledger.decisions()] == [
        first["decision_id"],
        second["decision_id"],
    ]
    assert len(ledger.pending_decisions()) == 2


def test_tampering_with_a_written_line_is_detected(tmp_path: Path) -> None:
    ledger = dl.DecisionLedger(tmp_path)
    entry = _entry()
    ledger.append_decision(entry)
    tampered = dict(entry)
    tampered["decision"] = "SHORT"  # the sealed hash no longer recomputes
    (tmp_path / dl.DECISIONS_FILENAME).write_text(
        json.dumps(tampered, sort_keys=True) + "\n", encoding="utf-8"
    )
    chain = ledger.verify_chain()
    assert chain["status"] == "BROKEN"
    assert {item["problem"] for item in chain["broken"]} == {"hash"}


def test_tampering_with_an_outcome_line_is_detected(tmp_path: Path) -> None:
    ledger = dl.DecisionLedger(tmp_path)
    record = _record()
    ledger.append_decision(
        dl.decision_entry(
            record=record, snapshot_artifact=_artifact(), provenance=_provenance(), recorded_at=DT
        )
    )
    outcome = do.evaluate_decision(
        record=record, asset="BINANCE:BTCUSDT", horizon=HORIZON, rows=_rows()
    )
    ledger.append_outcome(outcome)
    tampered = outcome.to_dict()
    tampered["net_return"] = 0.123456
    (tmp_path / dl.OUTCOMES_FILENAME).write_text(
        json.dumps(tampered, sort_keys=True) + "\n", encoding="utf-8"
    )
    chain = ledger.verify_chain()
    assert chain["status"] == "BROKEN"
    problems = {item["problem"] for item in chain["broken"]}
    assert "hash" in problems
    assert "arithmetic" in problems


def test_replay_marks_a_missing_raw_evidence_file(tmp_path: Path) -> None:
    ledger = dl.DecisionLedger(tmp_path)
    artifact = _artifact()
    raw_rel = f"{dl.RAW_EVIDENCE_DIRNAME}/snapshot.json"
    entry = dl.decision_entry(
        record=_record(),
        snapshot_artifact=artifact,
        provenance=_provenance(),
        raw_evidence_path=raw_rel,
        recorded_at=DT,
    )
    ledger.append_decision(entry)
    assert ledger.replay(entry["decision_id"])["checks"]["raw_evidence_present"] is False

    raw_file = ledger.root / raw_rel
    raw_file.parent.mkdir(parents=True, exist_ok=True)
    raw_file.write_text("{}\n", encoding="utf-8")
    replay = ledger.replay(entry["decision_id"])
    assert replay["checks"]["raw_evidence_present"] is True
    assert replay["checks"]["raw_evidence_hash_matches"] is False


def test_rebuilt_evaluations_feed_the_scorecard(tmp_path: Path) -> None:
    ledger = dl.DecisionLedger(tmp_path)
    for direction in ("LONG", "NO_TRADE"):
        record = _record(direction)
        ledger.append_decision(
            dl.decision_entry(
                record=record,
                snapshot_artifact=_artifact(),
                provenance=_provenance(),
                recorded_at=DT,
            )
        )
        outcome = do.evaluate_decision(
            record=record, asset="BINANCE:BTCUSDT", horizon=HORIZON, rows=_rows()
        )
        ledger.append_outcome(outcome)
        ledger.append_evaluation(
            do.build_performance(record=record, outcome=outcome, rows_4h=_rows())
        )

    rebuilt = ledger.rebuilt_evaluations()
    assert len(rebuilt) == 2
    assert all(item.is_verified() for item in rebuilt)
    assert all(item.comparisons for item in rebuilt)
    scorecard = asc.alpha_scorecard(rebuilt)
    assert scorecard["n_decisions_evaluated"] == 2
    assert scorecard["n_no_trade"] == 1
    assert scorecard["gate"]["conclusion"] == asc.CONCLUSION_INSUFFICIENT_SAMPLE
    assert scorecard["comparators"][do.BASELINE_ID_RANDOM_MATCHED]["distribution"] == {
        "LONG": 1,
        "SHORT": 0,
        "NO_TRADE": 1,
    }
