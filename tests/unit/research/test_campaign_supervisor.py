"""CAP-004B — focused tests for the persistent campaign supervisor.

The question this file pins down is operational, not scientific: *if the terminal
closes, does the campaign keep working correctly?*  So the tests exercise the
supervisor's own surface — the due-work gate, the lease, the operations hash
chain, the failure policy, the restart-recovery path and the scheduler task
definition — while reusing CAP-004 for the decision, outcome, baseline and score
semantics it must never reimplement.

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pytest

from trading_bot.market_data.types import OHLCV
from trading_bot.research import agentic_contracts as ac
from trading_bot.research import analyst_provenance as ap
from trading_bot.research import campaign_manifest as cm
from trading_bot.research import campaign_reporting as cr
from trading_bot.research import campaign_state as cs
from trading_bot.research import decision_ledger as dl
from trading_bot.research import market_analyst_v1 as mav
from trading_bot.research import real_market_context as rmc

BAR = 14_400
#: A decision instant exactly on the frozen 16:00 UTC slot grid.
DT = int(dt.datetime(2026, 10, 6, 16, 0, tzinfo=dt.UTC).timestamp())
HORIZON = "24H"
CODE_COMMIT = "0" * 40
TASK_NS = "{http://schemas.microsoft.com/windows/2004/02/mit/task}"

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


def _load_supervisor() -> Any:
    path = Path(__file__).resolve().parents[3] / "scripts" / "cap004_supervisor.py"
    spec = importlib.util.spec_from_file_location("cap004_supervisor_probe", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
        volume=10.0,
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


def _rows_by_asset() -> dict[str, dict[str, list[OHLCV]]]:
    return {"BINANCE:BTCUSDT": {"4h": _rows(), "1D": _rows()}}


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


def _record(direction: str = "LONG") -> ac.DecisionRecord:
    payload = dict(ANALYST_ANSWER)
    payload["decision"] = direction
    if direction == "NO_TRADE":
        payload["evidence"] = []
        payload["no_trade_reason"] = "no edge"
    return mav.seal_analyst_decision(
        payload,
        snapshot_hash=_artifact()["snapshot_hash"],
        raw_data_hash="b" * 64,
        critic_output={"note": "test"},
        provenance=_provenance(),
    )


def _entry(*, recorded_at: int = DT, artifact: dict[str, Any] | None = None) -> dict[str, Any]:
    return dl.decision_entry(
        record=_record(),
        snapshot_artifact=artifact or _artifact(),
        provenance=_provenance(),
        raw_evidence_path="",
        recorded_at=recorded_at,
    )


def _manifest(**overrides: Any) -> dict[str, Any]:
    manifest = cm.build_manifest(created_at=DT, code_commit=CODE_COMMIT)
    manifest.update(overrides)
    return manifest


def _prepare(tmp_path: Path, *, manifest: dict[str, Any] | None = None) -> dict[str, Path]:
    ledger_root = tmp_path / "real_decisions"
    ledger_root.mkdir(parents=True, exist_ok=True)
    cm.write_manifest(ledger_root, manifest or _manifest())
    return {
        "ledger_root": ledger_root,
        "report_root": tmp_path / "reports_cap004b",
        "ops_path": ledger_root / "operations.jsonl",
    }


def _utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> int:
    return int(dt.datetime(year, month, day, hour, minute, tzinfo=dt.UTC).timestamp())


def _fake_cycle(
    ledger_root: Path, *, rows: dict[str, dict[str, list[OHLCV]]] | None = None, calls: list[int] | None = None
) -> Any:
    """A cycle that runs the *real* CAP-004 settlement path, without the network."""

    def _run(*, modes: tuple[str, ...], now: int, cycle: int, store: dict[str, Any]) -> dict[str, Any]:
        supervisor = _load_supervisor()
        ledger = dl.DecisionLedger(ledger_root)
        settle = supervisor.campaign.settle_phase(ledger, rows_by_asset=rows or {}, now=now)
        counters = cs.campaign_counters(ledger, now=now)
        status = cs.campaign_status_name(
            counters=counters, chain_verified=True, drift={"status": "NO_DRIFT"}
        )
        if calls is not None:
            calls.append(now)
        return {
            "cycle": cycle,
            "modes": list(modes),
            "seal": {},
            "settle": settle,
            "counters": counters,
            "campaign_status": status,
            "errors": list(settle["errors"]),
            "verify": {"status": "PASS" if "verify" in modes else "SKIPPED"},
        }

    return _run


def _probe() -> dict[str, Any]:
    return {"scheduler_type": "windows_task_scheduler", "installed": False, "enabled": False}


# --------------------------------------------------------------------------- #
# §13 — the operations ledger
# --------------------------------------------------------------------------- #


def test_operations_entry_hash_is_stable_and_body_sensitive(tmp_path: Path) -> None:
    supervisor = _load_supervisor()
    kwargs: dict[str, Any] = {
        "campaign_id": cm.CAMPAIGN_ID,
        "ops_version": supervisor.OPS_VERSION,
        "started_at": DT,
        "ended_at": DT + 3,
        "host": "host",
        "pid": 1,
        "code_commit": CODE_COMMIT,
        "action": "RUN",
        "sealed": 1,
        "settled": 0,
        "evaluated": 0,
        "scored": True,
        "verification": "PASS",
        "exit_code": 0,
        "error_type": None,
        "error": None,
        "previous_hash": supervisor.GENESIS_HASH,
        "operation_id": "op-1",
    }
    first = supervisor.operation_entry(**kwargs)
    second = supervisor.operation_entry(**kwargs)
    assert first["event_hash"] == second["event_hash"]
    moved = supervisor.operation_entry(**{**kwargs, "sealed": 2})
    assert moved["event_hash"] != first["event_hash"]


def test_operations_ledger_chains_and_detects_tampering(tmp_path: Path) -> None:
    supervisor = _load_supervisor()
    ops = tmp_path / "operations.jsonl"
    previous = supervisor.GENESIS_HASH
    for index in range(3):
        record = supervisor.operation_entry(
            campaign_id=cm.CAMPAIGN_ID,
            ops_version=supervisor.OPS_VERSION,
            started_at=DT + index,
            ended_at=DT + index + 1,
            host="host",
            pid=100 + index,
            code_commit=CODE_COMMIT,
            action="RUN",
            sealed=0,
            settled=0,
            evaluated=0,
            scored=True,
            verification="PASS",
            exit_code=0,
            error_type=None,
            error=None,
            previous_hash=previous,
            operation_id=f"op-{index}",
        )
        supervisor.append_operation(ops, record)
        previous = record["event_hash"]

    entries = supervisor.read_operations(ops)
    assert len(entries) == 3
    assert entries[0]["previous_hash"] == supervisor.GENESIS_HASH
    assert supervisor.verify_operations_chain(entries)["status"] == "INTACT"
    assert supervisor.verify_operations_chain(entries)["head"] == entries[-1]["event_hash"]

    # tampering with the body without recomputing the hash must break the chain
    tampered = [dict(item) for item in entries]
    tampered[1]["action"] = "NOOP"
    assert supervisor.verify_operations_chain(tampered)["status"] == "BROKEN"
    assert supervisor.verify_operations_chain(tampered)["broken_index"] == 1


# --------------------------------------------------------------------------- #
# §7 / §8 — due work and phase selection
# --------------------------------------------------------------------------- #


def test_due_work_seals_inside_the_window_and_never_reports_a_phantom_settle(tmp_path: Path) -> None:
    supervisor = _load_supervisor()
    slot = _utc(2026, 10, 7, 16)
    paths = _prepare(tmp_path, manifest=_manifest(campaign_start=_utc(2026, 10, 7, 15)))
    ledger = dl.DecisionLedger(paths["ledger_root"])
    due = supervisor.due_work(ledger=ledger, manifest=_manifest(campaign_start=_utc(2026, 10, 7, 15)),
                              now=slot + 600, last_verify=slot)
    assert due["decision_slot"] == slot
    assert due["seal_due"] is True
    assert due["settle_due"] is False
    assert due["missed_due"] is False
    assert "seal" in supervisor.plan_modes(due)
    assert "settle" not in supervisor.plan_modes(due)


def test_due_work_is_a_noop_when_nothing_is_pending(tmp_path: Path) -> None:
    supervisor = _load_supervisor()
    manifest = _manifest(campaign_start=_utc(2026, 10, 8, 6))
    paths = _prepare(tmp_path, manifest=manifest)
    ledger = dl.DecisionLedger(paths["ledger_root"])
    now = _utc(2026, 10, 8, 6)
    due = supervisor.due_work(ledger=ledger, manifest=manifest, now=now, last_verify=now - 100)
    assert due["nothing_due"] is True
    assert due["missed_due"] is False
    assert supervisor.plan_modes(due) == ("score",)


def test_a_matured_pending_decision_makes_settlement_due(tmp_path: Path) -> None:
    supervisor = _load_supervisor()
    manifest = _manifest(campaign_start=_utc(2026, 10, 8, 15))
    paths = _prepare(tmp_path, manifest=manifest)
    ledger = dl.DecisionLedger(paths["ledger_root"])
    ledger.append_decision(_entry())
    now = DT + 86_400 + 3_600
    due = supervisor.due_work(ledger=ledger, manifest=manifest, now=now, last_verify=now)
    assert due["settle_due"] is True
    assert "settle" in supervisor.plan_modes(due)


def test_a_missed_slot_is_reported_and_never_backfilled(tmp_path: Path) -> None:
    supervisor = _load_supervisor()
    manifest = _manifest(campaign_start=_utc(2026, 10, 7, 15))
    paths = _prepare(tmp_path, manifest=manifest)
    ledger = dl.DecisionLedger(paths["ledger_root"])
    now = _utc(2026, 10, 9, 6)
    due = supervisor.due_work(ledger=ledger, manifest=manifest, now=now, last_verify=now)
    assert due["missed_due"] is True
    assert due["seal_due"] is False  # outside the seal window: no retroactive seal
    assert all(item["required_action"] == "NONE_NO_BACKFILL" for item in due["missed_slots"])
    assert "seal" in supervisor.plan_modes(due)  # so the miss is recorded by CAP-004
    assert "settle" not in supervisor.plan_modes(due)
    assert ledger.decisions() == []  # nothing was fabricated


# --------------------------------------------------------------------------- #
# §16 / §17 — failure policy
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "code",
    ["NETWORK", "TEMPORARY_PROVIDER_FAILURE", "DATA_NOT_READY", "TRANSIENT", "OUTCOME_BLOCKED_DATA"],
)
def test_retryable_failures_are_classified_retryable(code: str) -> None:
    assert _load_supervisor().classify_error(code) == "RETRYABLE"


@pytest.mark.parametrize(
    "code",
    [
        "CHAIN_FAILURE",
        "INTEGRITY_FAILURE",
        "RAW_HASH_MISMATCH",
        "PROMPT_DRIFT",
        "FEATURE_DRIFT",
        "CAMPAIGN_CONFIGURATION_DRIFT",
        "SCHEMA_DRIFT",
        "CONFIG_DRIFT",
    ],
)
def test_integrity_and_drift_failures_are_classified_blocking(code: str) -> None:
    assert _load_supervisor().classify_error(code) == "BLOCKING"


def test_an_unknown_failure_is_blocking_by_default() -> None:
    assert _load_supervisor().classify_error("SOMETHING_NEW") == "BLOCKING"


# --------------------------------------------------------------------------- #
# §14 / §15 — operational health, kept apart from campaign status
# --------------------------------------------------------------------------- #


def test_supervisor_health_is_operational_and_never_a_campaign_verdict() -> None:
    supervisor = _load_supervisor()
    interval = 900
    fresh = {"timestamp": DT}
    stale = {"timestamp": DT - 3 * interval}
    assert supervisor.supervisor_health(
        heartbeat=stale, now=DT, interval_seconds=interval, blocked=True,
        stop_requested=False, matured_unsettled=0,
    ) == "BLOCKED"
    assert supervisor.supervisor_health(
        heartbeat=stale, now=DT, interval_seconds=interval, blocked=False,
        stop_requested=True, matured_unsettled=0,
    ) == "STOPPED"
    assert supervisor.supervisor_health(
        heartbeat=fresh, now=DT, interval_seconds=interval, blocked=False,
        stop_requested=False, matured_unsettled=0,
    ) == "HEALTHY"
    assert supervisor.supervisor_health(
        heartbeat=stale, now=DT, interval_seconds=interval, blocked=False,
        stop_requested=False, matured_unsettled=0,
    ) == "DEGRADED"
    assert supervisor.supervisor_health(
        heartbeat=stale, now=DT, interval_seconds=interval, blocked=False,
        stop_requested=False, matured_unsettled=2,
    ) == "RECOVERING"
    assert supervisor.supervisor_health(
        heartbeat=None, now=DT, interval_seconds=interval, blocked=False,
        stop_requested=False, matured_unsettled=0,
    ) == "DEGRADED"
    # the supervisor has its own vocabulary; it is not the campaign's
    assert supervisor.SUPERVISOR_STATES != cs.CAMPAIGN_STATUSES
    for state in ("HEALTHY", "RECOVERING", "STOPPED"):
        assert state not in cs.CAMPAIGN_STATUSES


# --------------------------------------------------------------------------- #
# §10 / §18 — the supervised cycle, exactly-once and restart recovery
# --------------------------------------------------------------------------- #


def test_a_supervised_cycle_records_one_operations_event(tmp_path: Path) -> None:
    supervisor = _load_supervisor()
    paths = _prepare(tmp_path)
    result = supervisor.run_supervised_cycle(
        now=DT,
        ledger_root=paths["ledger_root"],
        report_root=paths["report_root"],
        ops_path=paths["ops_path"],
        cycle_fn=_fake_cycle(paths["ledger_root"]),
        scheduler_probe=_probe,
        code_commit=CODE_COMMIT,
        operation_id="op-cycle-1",
    )
    assert result["acquired"] is True
    assert result["action"] == "NOOP"
    assert result["exit_code"] == 0
    entries = supervisor.read_operations(paths["ops_path"])
    assert len(entries) == 1
    assert entries[0]["operation_id"] == "op-cycle-1"
    assert entries[0]["campaign_id"] == cm.CAMPAIGN_ID
    assert entries[0]["ops_version"] == supervisor.OPS_VERSION
    assert entries[0]["previous_hash"] == supervisor.GENESIS_HASH
    assert supervisor.verify_operations_chain(entries)["status"] == "INTACT"
    status = json.loads((paths["report_root"] / "SUPERVISOR_STATUS.json").read_text("utf-8"))
    assert status["campaign_version"] == cm.CAMPAIGN_VERSION
    assert status["experiment_version"] == cm.CAMPAIGN_VERSION
    assert status["scheduler"]["installed"] is False


def test_a_second_invocation_is_refused_while_the_lease_is_live(tmp_path: Path) -> None:
    supervisor = _load_supervisor()
    paths = _prepare(tmp_path)
    holder = supervisor.cl.CampaignLock(paths["ledger_root"], campaign_id=cm.CAMPAIGN_ID)
    holder.acquire(now=DT)
    calls: list[int] = []
    try:
        result = supervisor.run_supervised_cycle(
            now=DT + 10,
            ledger_root=paths["ledger_root"],
            report_root=paths["report_root"],
            ops_path=paths["ops_path"],
            cycle_fn=_fake_cycle(paths["ledger_root"], calls=calls),
            scheduler_probe=_probe,
            code_commit=CODE_COMMIT,
            operation_id="op-second",
        )
    finally:
        holder.release()
    assert result["acquired"] is False
    assert result["status"] == "ALREADY_RUNNING"
    assert result["exit_code"] == 0
    assert calls == []  # the cycle never ran
    entries = supervisor.read_operations(paths["ops_path"])
    assert entries[-1]["error_type"] == "ALREADY_RUNNING"


def test_restart_recovery_settles_a_matured_decision_exactly_once(tmp_path: Path) -> None:
    supervisor = _load_supervisor()
    manifest = _manifest(campaign_start=_utc(2026, 10, 7, 15))
    paths = _prepare(tmp_path, manifest=manifest)
    ledger = dl.DecisionLedger(paths["ledger_root"])
    ledger.append_decision(_entry())

    matured_at = DT + 86_400
    first = supervisor.run_supervised_cycle(
        now=matured_at,
        ledger_root=paths["ledger_root"],
        report_root=paths["report_root"],
        ops_path=paths["ops_path"],
        cycle_fn=_fake_cycle(paths["ledger_root"], rows=_rows_by_asset()),
        scheduler_probe=_probe,
        code_commit=CODE_COMMIT,
        operation_id="op-recover-1",
    )
    assert first["settled"] == 1
    assert first["evaluated"] == 1
    assert len(dl.DecisionLedger(paths["ledger_root"]).outcomes()) == 1

    # a long downtime, then the supervisor runs again: no second outcome
    second = supervisor.run_supervised_cycle(
        now=matured_at + 30 * 86_400,
        ledger_root=paths["ledger_root"],
        report_root=paths["report_root"],
        ops_path=paths["ops_path"],
        cycle_fn=_fake_cycle(paths["ledger_root"], rows=_rows_by_asset()),
        scheduler_probe=_probe,
        code_commit=CODE_COMMIT,
        operation_id="op-recover-2",
    )
    assert second["settled"] == 0
    after = dl.DecisionLedger(paths["ledger_root"])
    assert len(after.outcomes()) == 1
    assert len(after.evaluations()) == 1
    assert after.verify_chain()["status"] == "INTACT"


def test_a_sealed_decision_settles_on_recovery_but_its_old_slot_is_not_resealed(tmp_path: Path) -> None:
    supervisor = _load_supervisor()
    manifest = _manifest(campaign_start=_utc(2026, 10, 6, 15))
    paths = _prepare(tmp_path, manifest=manifest)
    ledger = dl.DecisionLedger(paths["ledger_root"])
    ledger.append_decision(_entry())

    now = DT + 30 * 86_400
    # the slot is long gone: it can never be sealed again
    missed = supervisor.campaign.missed_slots(ledger, manifest, now=now)
    assert missed, "an unsealed slot must be visible as missed"
    assert all(item["required_action"] == "NONE_NO_BACKFILL" for item in missed)

    # but the decision that was already sealed is settled on recovery
    result = supervisor.run_supervised_cycle(
        now=now,
        ledger_root=paths["ledger_root"],
        report_root=paths["report_root"],
        ops_path=paths["ops_path"],
        cycle_fn=_fake_cycle(paths["ledger_root"], rows=_rows_by_asset()),
        scheduler_probe=_probe,
        code_commit=CODE_COMMIT,
        operation_id="op-recovery",
    )
    assert result["settled"] == 1
    assert len(dl.DecisionLedger(paths["ledger_root"]).outcomes()) == 1


def test_late_market_data_is_retryable_and_never_a_block(tmp_path: Path) -> None:
    supervisor = _load_supervisor()
    manifest = _manifest(campaign_start=_utc(2026, 10, 6, 15))
    paths = _prepare(tmp_path, manifest=manifest)
    ledger = dl.DecisionLedger(paths["ledger_root"])
    ledger.append_decision(_entry())

    result = supervisor.run_supervised_cycle(
        now=DT + 86_400,
        ledger_root=paths["ledger_root"],
        report_root=paths["report_root"],
        ops_path=paths["ops_path"],
        cycle_fn=_fake_cycle(paths["ledger_root"], rows={}),  # no canonical candle yet
        scheduler_probe=_probe,
        code_commit=CODE_COMMIT,
        operation_id="op-late-data",
    )
    assert result["settled"] == 0
    assert result["exit_code"] == 1  # retryable, not blocked
    assert result["supervisor_state"] != "BLOCKED"
    assert result["errors"][0]["code"] == "OUTCOME_BLOCKED_DATA"
    assert dl.DecisionLedger(paths["ledger_root"]).outcomes() == []  # nothing substituted


def test_a_stop_request_is_graceful_and_leaves_the_ledger_untouched(tmp_path: Path) -> None:
    supervisor = _load_supervisor()
    manifest = _manifest(campaign_start=_utc(2026, 10, 6, 15))
    paths = _prepare(tmp_path, manifest=manifest)
    ledger = dl.DecisionLedger(paths["ledger_root"])
    ledger.append_decision(_entry())
    lock = supervisor.cl.CampaignLock(paths["ledger_root"], campaign_id=cm.CAMPAIGN_ID)
    lock.request_stop(reason="test")

    calls: list[int] = []
    result = supervisor.run_supervised_cycle(
        now=DT + 86_400,
        ledger_root=paths["ledger_root"],
        report_root=paths["report_root"],
        ops_path=paths["ops_path"],
        cycle_fn=_fake_cycle(paths["ledger_root"], rows=_rows_by_asset(), calls=calls),
        scheduler_probe=_probe,
        code_commit=CODE_COMMIT,
        operation_id="op-stop",
    )
    assert result["action"] == "STOPPED"
    assert result["exit_code"] == 0
    assert calls == []
    assert dl.DecisionLedger(paths["ledger_root"]).outcomes() == []
    assert supervisor.read_operations(paths["ops_path"])[-1]["action"] == "STOPPED"


def test_verification_runs_on_a_daily_cadence_not_on_every_cycle(tmp_path: Path) -> None:
    supervisor = _load_supervisor()
    manifest = _manifest(campaign_start=_utc(2026, 10, 8, 6))
    paths = _prepare(tmp_path, manifest=manifest)
    now = _utc(2026, 10, 8, 6)
    first = supervisor.run_supervised_cycle(
        now=now,
        ledger_root=paths["ledger_root"],
        report_root=paths["report_root"],
        ops_path=paths["ops_path"],
        cycle_fn=_fake_cycle(paths["ledger_root"]),
        scheduler_probe=_probe,
        code_commit=CODE_COMMIT,
        operation_id="op-verify-1",
    )
    assert first["modes"] == ["score", "verify"]  # first run verifies
    assert first["verification"] == "PASS"
    second = supervisor.run_supervised_cycle(
        now=now + 60,
        ledger_root=paths["ledger_root"],
        report_root=paths["report_root"],
        ops_path=paths["ops_path"],
        cycle_fn=_fake_cycle(paths["ledger_root"]),
        scheduler_probe=_probe,
        code_commit=CODE_COMMIT,
        operation_id="op-verify-2",
    )
    assert second["modes"] == ["score"]  # only fifteen minutes later: no heavy re-verify
    assert second["verification"] == "SKIPPED"


def test_a_stale_heartbeat_degrades_the_supervisor_without_breaking_the_chain(tmp_path: Path) -> None:
    supervisor = _load_supervisor()
    paths = _prepare(tmp_path)
    stale_stamp = DT - 10 * supervisor.DEFAULT_INTERVAL_SECONDS
    cr.write_heartbeat(
        paths["ledger_root"],
        cr.heartbeat_payload(
            campaign_id=cm.CAMPAIGN_ID,
            campaign_version=cm.CAMPAIGN_VERSION,
            now=stale_stamp,
            process_status="RUNNING",
            counters={},
            cycle=1,
            interval_seconds=supervisor.DEFAULT_INTERVAL_SECONDS,
            next_decision_slot=DT,
            next_maturity=None,
        ),
    )
    result = supervisor.run_supervised_cycle(
        now=DT,
        ledger_root=paths["ledger_root"],
        report_root=paths["report_root"],
        ops_path=paths["ops_path"],
        cycle_fn=_fake_cycle(paths["ledger_root"]),
        scheduler_probe=_probe,
        code_commit=CODE_COMMIT,
        operation_id="op-stale",
    )
    assert result["supervisor_state"] == "DEGRADED"
    assert result["exit_code"] == 0
    assert result["operations_chain"]["status"] == "INTACT"
    # the supervisor never rewrites the campaign heartbeat with its own vocabulary
    assert cr.read_heartbeat(paths["ledger_root"])["timestamp"] == stale_stamp


# --------------------------------------------------------------------------- #
# §4 / §16 — preflight blocks
# --------------------------------------------------------------------------- #


def test_prompt_drift_blocks_preflight(tmp_path: Path) -> None:
    supervisor = _load_supervisor()
    drifted = _manifest()
    drifted["prompt_digest"] = "0" * 64
    paths = _prepare(tmp_path, manifest=drifted)
    pre = supervisor.preflight(ledger_root=paths["ledger_root"], manifest=drifted)
    assert pre["status"] == "BLOCKED"
    assert pre["code"] == "PROMPT_DRIFT"

    result = supervisor.run_supervised_cycle(
        now=DT,
        ledger_root=paths["ledger_root"],
        report_root=paths["report_root"],
        ops_path=paths["ops_path"],
        cycle_fn=_fake_cycle(paths["ledger_root"], calls=[]),
        scheduler_probe=_probe,
        code_commit=CODE_COMMIT,
        operation_id="op-drift",
    )
    assert result["supervisor_state"] == "BLOCKED"
    assert result["action"] == "PREFLIGHT_BLOCKED"
    assert result["exit_code"] == 3


def test_the_first_settlement_artifact_stays_pending_until_a_real_settlement(tmp_path: Path) -> None:
    supervisor = _load_supervisor()
    paths = _prepare(tmp_path)
    result = supervisor.write_first_settlement(
        ledger_root=paths["ledger_root"], report_root=paths["report_root"], now=DT
    )
    assert result["status"] == "PENDING"
    assert not (paths["report_root"] / "FIRST_REAL_SETTLEMENT.json").exists()


def test_the_first_settlement_artifact_is_written_once_without_claiming_an_edge(tmp_path: Path) -> None:
    supervisor = _load_supervisor()
    paths = _prepare(tmp_path)
    ledger = dl.DecisionLedger(paths["ledger_root"])
    entry = _entry()
    ledger.append_decision(entry)
    settle = supervisor.campaign.settle_phase(
        ledger, rows_by_asset=_rows_by_asset(), now=DT + 86_400
    )
    assert len(settle["settled"]) == 1
    first = supervisor.write_first_settlement(
        ledger_root=paths["ledger_root"], report_root=paths["report_root"], now=DT + 86_400
    )
    assert first["status"] == "WRITTEN"
    payload = json.loads((paths["report_root"] / "FIRST_REAL_SETTLEMENT.json").read_text("utf-8"))
    assert payload["n_settled"] == 1
    assert payload["trades_authorized"] == 0
    assert payload["alpha_claimed"] == "NONE"
    assert "INSUFFICIENT_SAMPLE" in payload["sample_note"]
    assert payload["settlements"][0]["decision_id"] == entry["decision_id"]
    assert (paths["report_root"] / "FIRST_REAL_SETTLEMENT.md").is_file()
    again = supervisor.write_first_settlement(
        ledger_root=paths["ledger_root"], report_root=paths["report_root"], now=DT + 90_000
    )
    assert again["status"] == "ALREADY_EXISTS"


def test_a_missing_manifest_blocks_preflight(tmp_path: Path) -> None:
    supervisor = _load_supervisor()
    root = tmp_path / "empty"
    root.mkdir()
    pre = supervisor.preflight(ledger_root=root, manifest=None)
    assert pre["status"] == "BLOCKED"
    assert pre["code"] == "CAMPAIGN_NOT_INITIALIZED"


def test_raw_evidence_hash_mismatch_blocks_preflight(tmp_path: Path) -> None:
    supervisor = _load_supervisor()
    paths = _prepare(tmp_path)
    ledger = dl.DecisionLedger(paths["ledger_root"])
    entry = _entry()
    ledger.append_decision(entry)
    raw_dir = paths["ledger_root"] / "raw_evidence"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "snap.json").write_text(json.dumps({"provider": "x", "intervals": {}}), "utf-8")
    manifest_line = {
        "snapshot_hash": entry["snapshot_hash"],
        "raw_evidence_hash": "c" * 64,  # deliberately wrong
        "local_path": "raw_evidence/snap.json",
    }
    (paths["ledger_root"] / "RAW_EVIDENCE_MANIFEST.jsonl").write_text(
        json.dumps(manifest_line) + "\n", "utf-8"
    )
    pre = supervisor.preflight(
        ledger_root=paths["ledger_root"], manifest=cm.load_manifest(paths["ledger_root"])
    )
    assert pre["status"] == "BLOCKED"
    assert pre["code"] == "RAW_HASH_MISMATCH"


def test_a_broken_ledger_chain_blocks_preflight(tmp_path: Path) -> None:
    supervisor = _load_supervisor()
    paths = _prepare(tmp_path)
    ledger = dl.DecisionLedger(paths["ledger_root"])
    ledger.append_decision(_entry())
    decisions_path = paths["ledger_root"] / "decisions.jsonl"
    lines = decisions_path.read_text("utf-8").splitlines()
    record = json.loads(lines[0])
    record["snapshot"]["timestamp"] = DT + 1  # snapshot no longer matches its hash
    decisions_path.write_text(json.dumps(record) + "\n", "utf-8")
    pre = supervisor.preflight(
        ledger_root=paths["ledger_root"], manifest=cm.load_manifest(paths["ledger_root"])
    )
    assert pre["status"] == "BLOCKED"
    assert pre["code"] == "CHAIN_FAILURE"


# --------------------------------------------------------------------------- #
# §9 / §19 / §20 — the OS scheduler task definition
# --------------------------------------------------------------------------- #


def test_the_task_definition_is_stable_and_carries_the_safety_settings() -> None:
    supervisor = _load_supervisor()
    kwargs = {
        "start_boundary": "2026-10-06T22:00:00",
        "interval_minutes": 15,
        "user_id": "DESKTOP\\user",
        "command": "python.exe",
        "arguments": '"supervisor.py" run',
        "working_dir": "C:\\repo",
        "author": "DESKTOP\\user",
    }
    xml = supervisor.build_task_xml(**kwargs)
    assert xml == supervisor.build_task_xml(**kwargs)  # idempotent definition
    root = ET.fromstring(xml)
    settings = root.find(f"{TASK_NS}Settings")
    assert settings is not None
    assert settings.find(f"{TASK_NS}MultipleInstancesPolicy").text == "IgnoreNew"
    assert settings.find(f"{TASK_NS}StartWhenAvailable").text == "true"
    assert settings.find(f"{TASK_NS}Enabled").text == "true"
    repetition = root.find(f".//{TASK_NS}Repetition/{TASK_NS}Interval")
    assert repetition is not None and repetition.text == "PT15M"
    principal = root.find(f".//{TASK_NS}Principal/{TASK_NS}RunLevel")
    assert principal is not None and principal.text == "LeastPrivilege"
    exec_node = root.find(f".//{TASK_NS}Actions/{TASK_NS}Exec")
    assert exec_node is not None
    assert exec_node.find(f"{TASK_NS}Command").text == "python.exe"
    assert exec_node.find(f"{TASK_NS}Arguments").text == '"supervisor.py" run'
    assert exec_node.find(f"{TASK_NS}WorkingDirectory").text == "C:\\repo"


def test_the_registered_command_points_at_this_supervisor() -> None:
    supervisor = _load_supervisor()
    assert supervisor.task_command() == supervisor.python_executable()
    assert str(supervisor.SCRIPT) in supervisor.task_arguments()
    assert supervisor.task_arguments().endswith("run")
    assert supervisor.task_working_directory() == str(supervisor.REPO)


def test_install_is_idempotent_through_the_scheduler_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    supervisor = _load_supervisor()
    state = {"installed": False, "calls": []}

    def fake_status(**kwargs: Any) -> dict[str, Any]:
        return {
            "scheduler_type": "windows_task_scheduler",
            "task_name": kwargs.get("task_name", supervisor.TASK_NAME),
            "installed": state["installed"],
            "enabled": state["installed"],
        }

    def fake_schtasks(args: Any, timeout: int = 60) -> dict[str, Any]:
        state["calls"].append(list(args))
        if any(str(item) == "/create" for item in args):
            state["installed"] = True
        return {"ok": True, "returncode": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(supervisor, "scheduler_status", fake_status)
    monkeypatch.setattr(supervisor, "_schtasks", fake_schtasks)
    monkeypatch.setattr(supervisor, "current_user_id", lambda: "HOST\\user")
    monkeypatch.setattr(supervisor, "task_command", lambda: "python.exe")
    monkeypatch.setattr(supervisor, "task_arguments", lambda: '"supervisor.py" run')
    monkeypatch.setattr(supervisor, "task_working_directory", lambda: str(tmp_path))

    ops = tmp_path / "operations.jsonl"
    first = supervisor.install_scheduler(
        interval_minutes=15, journal_path=tmp_path / "reports", ops_path=ops, operation_id="op-i1"
    )
    assert first["status"] == "INSTALLED"
    second = supervisor.install_scheduler(
        interval_minutes=15, journal_path=tmp_path / "reports", ops_path=ops, operation_id="op-i2"
    )
    assert second["status"] == "UPDATED"
    creates = [call for call in state["calls"] if any(str(item) == "/create" for item in call)]
    assert len(creates) == 2  # re-registered, not duplicated
    assert supervisor.verify_operations_chain(supervisor.read_operations(ops))["status"] == "INTACT"
