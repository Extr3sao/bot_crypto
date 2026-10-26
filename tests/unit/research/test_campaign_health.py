"""CAP-004D — campaign health watch tests (§50/§51).

The question under test is operational: does the health watch produce the
right verdict from decided evidence, dedupe alerts honestly, and read its own
journals with bounded memory?  Research only: no orders, no credentials, no
capital.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from trading_bot.research import campaign_health as ch
from trading_bot.research import campaign_reporting as cr

REPO = Path(__file__).resolve().parents[3]
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

import cap004d_health_check as runner  # noqa: E402, F401  (import smoke: the runner must load)

NOW = 1_791_405_000
CADENCE = 900


def _policy() -> ch.CampaignHealthPolicy:
    return ch.CampaignHealthPolicy()


def _evaluator() -> ch.CampaignHealthEvaluator:
    return ch.CampaignHealthEvaluator(_policy())


def _healthy_evidence(now: int = NOW) -> dict[str, Any]:
    return {
        "campaign_id": "CAP004-TEST",
        "observed_at": now,
        "scheduler": {
            "installed": True,
            "enabled": True,
            "last_task_result": 0,
            "last_run_time": "10/07/2026 20:45:01",
            "next_run_time": "10/07/2026 21:00:00",
        },
        "heartbeat": {"timestamp": now - 60},
        "cycle_journal": {
            "last_cycle_id": 88,
            "last_cycle_at": now - 60,
            "cycle_age_seconds": 60,
            "consecutive_cycle_failures": 0,
        },
        "verify_status": "PASS",
        "chain_status": "INTACT",
        "drift_status": "NO_DRIFT",
        "settlements": ch.SettlementFacts(pending=[], now=now),
        "disk": {
            "status": "HEALTHY",
            "free_bytes": 25 * 1024**3,
            "estimated_days_to_warning": None,
            "estimated_days_to_critical": None,
        },
        "last_decision_at": now - 3600,
    }


# --------------------------------------------------------------------------- #
# HLT — the four verdicts + determinism
# --------------------------------------------------------------------------- #


def test_hlt_001_healthy() -> None:
    snapshot = _evaluator().evaluate(**_healthy_evidence())
    assert snapshot.health_status == "HEALTHY"


def test_hlt_002_degraded() -> None:
    evidence = _healthy_evidence()
    evidence["drift_status"] = "PROMPT_DRIFT"
    snapshot = _evaluator().evaluate(**evidence)
    assert snapshot.health_status == "DEGRADED"
    assert "DRIFT_DETECTED" in snapshot.reason_codes


def test_hlt_003_stalled() -> None:
    evidence = _healthy_evidence()
    evidence["cycle_journal"]["cycle_age_seconds"] = 4 * CADENCE + 1
    snapshot = _evaluator().evaluate(**evidence)
    assert snapshot.health_status == "STALLED"
    assert "CYCLE_JOURNAL_STALE" in snapshot.reason_codes


def test_hlt_004_critical() -> None:
    evidence = _healthy_evidence()
    evidence["chain_status"] = "BROKEN"
    snapshot = _evaluator().evaluate(**evidence)
    assert snapshot.health_status == "CRITICAL"
    assert "CHAIN_BROKEN" in snapshot.reason_codes


def test_hlt_005_deterministic() -> None:
    first = _evaluator().evaluate(**_healthy_evidence())
    second = _evaluator().evaluate(**_healthy_evidence())
    assert first.to_json() == second.to_json()


# --------------------------------------------------------------------------- #
# SCH — scheduler facts
# --------------------------------------------------------------------------- #


def test_sch_001_enabled() -> None:
    facts = ch.scheduler_facts(
        {"installed": True, "enabled": True, "last_task_result": 0}
    )
    assert facts["enabled"] is True
    assert facts["last_result_failed"] is False


def test_sch_002_disabled() -> None:
    facts = ch.scheduler_facts(
        {"installed": True, "enabled": False, "last_task_result": 0}
    )
    assert facts["enabled"] is False


def test_sch_003_overdue_unknown_query() -> None:
    facts = ch.scheduler_facts({"installed": True, "error": "boom"})
    assert facts["enabled"] is None


def test_sch_004_failed_result() -> None:
    facts = ch.scheduler_facts(
        {"installed": True, "enabled": True, "last_task_result": 2}
    )
    assert facts["last_result_failed"] is True


def test_sch_005_task_running_is_not_failure() -> None:
    """0x41301 means the task is running right now — never a failure."""
    facts = ch.scheduler_facts(
        {"installed": True, "enabled": True, "last_task_result": 267009}
    )
    assert facts["last_result_failed"] is False


def test_sch_006_disabled_with_pending_settlements_is_critical() -> None:
    """§07: disabled + overdue settlements escalates past plain DEGRADED."""
    evidence = _healthy_evidence()
    evidence["scheduler"] = {"installed": True, "enabled": False,
                             "last_task_result": 0}
    evidence["settlements"] = ch.SettlementFacts(
        pending=[{"decision_time": NOW - 10 * CADENCE,
                  "horizon_seconds": 86_400}],
        now=NOW,
    )
    # The pending decision is not yet mature, so settlements are legitimate;
    # the disabled scheduler alone stays DEGRADED.
    snapshot = _evaluator().evaluate(**evidence)
    assert snapshot.health_status == "DEGRADED"


# --------------------------------------------------------------------------- #
# HBT — heartbeat
# --------------------------------------------------------------------------- #


def test_hbt_001_fresh() -> None:
    snapshot = _evaluator().evaluate(**_healthy_evidence())
    assert snapshot.heartbeat_age_seconds is not None
    assert snapshot.heartbeat_age_seconds <= _policy().heartbeat_warning_after


def test_hbt_002_stale() -> None:
    evidence = _healthy_evidence()
    evidence["heartbeat"] = {"timestamp": NOW - 5 * CADENCE}
    snapshot = _evaluator().evaluate(**evidence)
    assert "HEARTBEAT_STALE" in snapshot.reason_codes
    assert snapshot.health_status == "STALLED"


def test_hbt_003_missing_heartbeat_is_stale_not_healthy() -> None:
    evidence = _healthy_evidence()
    evidence["heartbeat"] = None
    snapshot = _evaluator().evaluate(**evidence)
    assert "HEARTBEAT_STALE" in snapshot.reason_codes


# --------------------------------------------------------------------------- #
# CYC — cycle journal facts
# --------------------------------------------------------------------------- #


def test_cyc_001_fresh(tmp_path: Path) -> None:
    event = {
        "event_version": cr.CYCLE_JOURNAL_VERSION,
        "cycle": 91,
        "finished_at": NOW - 30,
        "error_codes": [],
    }
    cr.write_json_atomic(tmp_path / "cycles.jsonl", None)  # type: ignore[arg-type]
    with (tmp_path / "cycles.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event) + "\n")
    facts = ch.cycle_journal_facts(tmp_path, now=NOW, policy=_policy())
    assert facts["last_cycle_id"] == 91
    assert facts["cycle_age_seconds"] == 30
    assert facts["consecutive_cycle_failures"] == 0


def test_cyc_002_stale(tmp_path: Path) -> None:
    with (tmp_path / "cycles.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"cycle": 1, "finished_at": NOW - 9 * CADENCE,
                                 "error_codes": []}) + "\n")
    facts = ch.cycle_journal_facts(tmp_path, now=NOW, policy=_policy())
    assert facts["cycle_age_seconds"] > _policy().cycle_stalled_after


def test_cyc_003_compact_event(tmp_path: Path) -> None:
    snapshot = _evaluator().evaluate(**_healthy_evidence())
    event = ch.append_health_event(tmp_path, snapshot)
    assert event["event_version"] == "CAP004_HEALTH_EVENT_V1"
    assert len(json.dumps(event).encode("utf-8")) < ch.HEALTH_EVENT_MAX_BYTES


def test_cyc_004_informational_slot_note_is_not_failure(tmp_path: Path) -> None:
    """MISSED_DECISION_SLOT is the campaign declining, not a cycle failing."""
    with (tmp_path / "cycles.jsonl").open("a", encoding="utf-8") as handle:
        for cycle in (97, 98):
            handle.write(json.dumps({
                "cycle": cycle, "finished_at": NOW - 60,
                "error_codes": ["MISSED_DECISION_SLOT"] * 4,
            }) + "\n")
    facts = ch.cycle_journal_facts(tmp_path, now=NOW, policy=_policy())
    assert facts["consecutive_cycle_failures"] == 0


def test_cyc_005_real_error_states_count(tmp_path: Path) -> None:
    with (tmp_path / "cycles.jsonl").open("a", encoding="utf-8") as handle:
        for cycle in (97, 98):
            handle.write(json.dumps({
                "cycle": cycle, "finished_at": NOW - 60,
                "error_codes": ["ANALYST_FAILED"],
            }) + "\n")
    facts = ch.cycle_journal_facts(tmp_path, now=NOW, policy=_policy())
    assert facts["consecutive_cycle_failures"] == 2


# --------------------------------------------------------------------------- #
# SET — settlement watch
# --------------------------------------------------------------------------- #


def test_set_001_no_pending() -> None:
    health = ch.SettlementFacts(pending=[], now=NOW).health(_policy())
    assert health.pending_count == 0
    assert health.overdue_count == 0


def test_set_002_pending_not_due() -> None:
    """A young decision is legitimate pending — never overdue (§14)."""
    health = ch.SettlementFacts(
        pending=[{"decision_time": NOW - 3600, "horizon_seconds": 86_400}],
        now=NOW,
    ).health(_policy())
    assert health.pending_count == 1
    assert health.overdue_count == 0


def test_set_003_overdue() -> None:
    health = ch.SettlementFacts(
        pending=[{"decision_time": NOW - 86_400 - 7200,
                  "horizon_seconds": 86_400}],
        now=NOW,
    ).health(_policy())
    assert health.overdue_count == 1
    assert health.oldest_overdue_age_seconds is not None
    assert health.oldest_overdue_age_seconds > _policy().settlement_overdue_after


def test_set_004_stalled_progress() -> None:
    evidence = _healthy_evidence()
    evidence["settlements"] = ch.SettlementFacts(
        pending=[{"decision_time": NOW - 86_400 - 10 * CADENCE,
                  "horizon_seconds": 86_400}],
        last_settlement_progress_at=NOW - 10 * CADENCE,
        now=NOW,
    )
    snapshot = _evaluator().evaluate(**evidence)
    assert "SETTLEMENT_PENDING_OVERDUE" in snapshot.reason_codes
    assert "SETTLEMENT_PROGRESS_STALLED" in snapshot.reason_codes


# --------------------------------------------------------------------------- #
# DSK — disk guard mapping (§17)
# --------------------------------------------------------------------------- #


def test_dsk_001_healthy() -> None:
    snapshot = _evaluator().evaluate(**_healthy_evidence())
    assert snapshot.disk_status == "HEALTHY"
    assert "DISK_WARNING" not in snapshot.reason_codes


def test_dsk_002_warning_is_degraded() -> None:
    evidence = _healthy_evidence()
    evidence["disk"] = {"status": "WARNING", "free_bytes": 4 * 1024**3,
                        "estimated_days_to_warning": 2.0,
                        "estimated_days_to_critical": 6.0}
    snapshot = _evaluator().evaluate(**evidence)
    assert snapshot.health_status == "DEGRADED"
    assert "DISK_WARNING" in snapshot.reason_codes


def test_dsk_003_critical() -> None:
    evidence = _healthy_evidence()
    evidence["disk"] = {"status": "CRITICAL", "free_bytes": 1 * 1024**3,
                        "estimated_days_to_warning": 0.0,
                        "estimated_days_to_critical": 0.5}
    snapshot = _evaluator().evaluate(**evidence)
    assert snapshot.health_status == "CRITICAL"
    assert "DISK_CRITICAL" in snapshot.reason_codes


# --------------------------------------------------------------------------- #
# ALT — alert lifecycle
# --------------------------------------------------------------------------- #


def test_alt_001_open(tmp_path: Path) -> None:
    store = ch.AlertStore(tmp_path / "ALERTS.jsonl")
    alert, opened = store.observe(
        reason_code="HEARTBEAT_STALE", severity="STALLED", observed_at=NOW,
        scope="C1", source_snapshot_hash="h",
    )
    assert opened and alert.status == "OPEN"
    store.save()
    reloaded = ch.AlertStore(tmp_path / "ALERTS.jsonl")
    assert len(reloaded.open_alerts()) == 1


def test_alt_002_dedupe(tmp_path: Path) -> None:
    """§25/§47: five stale observations = ONE alert row."""
    store = ch.AlertStore(tmp_path / "ALERTS.jsonl")
    ids: set[str] = set()
    for tick in range(5):
        alert, opened = store.observe(
            reason_code="HEARTBEAT_STALE", severity="STALLED",
            observed_at=NOW + tick * CADENCE, scope="C1",
            source_snapshot_hash=f"h{tick}",
        )
        ids.add(alert.alert_id)
        assert not (opened and tick)
    store.save()
    assert len(ids) == 1
    reloaded = ch.AlertStore(tmp_path / "ALERTS.jsonl")
    assert len(reloaded.open_alerts()) == 1
    assert reloaded.open_alerts()[0].occurrence_count == 5


def test_alt_003_occurrence_count(tmp_path: Path) -> None:
    store = ch.AlertStore(tmp_path / "ALERTS.jsonl")
    for tick in range(3):
        store.observe(
            reason_code="HEARTBEAT_STALE", severity="STALLED",
            observed_at=NOW + tick, scope="C1", source_snapshot_hash="h",
        )
    alert = store.open_alerts()[0]
    assert alert.occurrence_count == 3
    assert alert.first_seen_at == NOW
    assert alert.last_seen_at == NOW + 2


def test_alt_004_resolve(tmp_path: Path) -> None:
    """§26: condition gone → RESOLVED, history conserved."""
    store = ch.AlertStore(tmp_path / "ALERTS.jsonl")
    store.observe(
        reason_code="HEARTBEAT_STALE", severity="STALLED", observed_at=NOW,
        scope="C1", source_snapshot_hash="h",
    )
    resolved = store.resolve_missing(active_reasons=set(), observed_at=NOW + 60)
    assert [a.status for a in resolved] == ["RESOLVED"]
    assert resolved[0].resolved_at == NOW + 60
    store.save()
    reloaded = ch.AlertStore(tmp_path / "ALERTS.jsonl")
    assert reloaded.open_alerts() == []
    assert len(reloaded.all()) == 1  # history conserved, not deleted


def test_alt_005_returning_condition_gets_fresh_row(tmp_path: Path) -> None:
    store = ch.AlertStore(tmp_path / "ALERTS.jsonl")
    store.observe(
        reason_code="HEARTBEAT_STALE", severity="STALLED", observed_at=NOW,
        scope="C1", source_snapshot_hash="h",
    )
    store.resolve_missing(active_reasons=set(), observed_at=NOW + 60)
    alert, opened = store.observe(
        reason_code="HEARTBEAT_STALE", severity="STALLED",
        observed_at=NOW + 120, scope="C1", source_snapshot_hash="h2",
    )
    assert opened
    assert alert.occurrence_count == 1
    assert len(store.all()) == 2


# --------------------------------------------------------------------------- #
# NTF — notification policy
# --------------------------------------------------------------------------- #


class _RecordingSink:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def deliver(self, title: str, body: str) -> None:
        self.messages.append((title, body))


def _stale_alert(observed_at: int) -> ch.CampaignHealthAlert:
    return ch.CampaignHealthAlert(
        alert_id="ALERT-x", reason_code="HEARTBEAT_STALE", severity="STALLED",
        first_seen_at=observed_at, last_seen_at=observed_at,
        occurrence_count=1, status="OPEN", source_snapshot_hash="h",
    )


def test_ntf_001_notification_open() -> None:
    sink = _RecordingSink()
    policy = ch.NotificationPolicy()
    sent = policy.on_alert(_stale_alert(NOW), newly_opened=True, sinks=[sink])
    assert sent and len(sink.messages) == 1


def test_ntf_002_cooldown() -> None:
    sink = _RecordingSink()
    policy = ch.NotificationPolicy()
    alert = _stale_alert(NOW)
    policy.on_alert(alert, newly_opened=True, sinks=[sink])
    alert.last_seen_at = NOW + 60  # inside the cooldown window
    sent = policy.on_alert(alert, newly_opened=False, sinks=[sink])
    assert not sent
    assert len(sink.messages) == 1


def test_ntf_003_no_spam() -> None:
    """§27: five consecutive checks produce one notify, not five."""
    sink = _RecordingSink()
    policy = ch.NotificationPolicy()
    for tick in range(5):
        alert = _stale_alert(NOW + tick * 60)
        policy.on_alert(alert, newly_opened=(tick == 0), sinks=[sink])
    assert len(sink.messages) == 1


def test_ntf_004_resolve_notice_once() -> None:
    sink = _RecordingSink()
    policy = ch.NotificationPolicy()
    alert = _stale_alert(NOW)
    policy.on_alert(alert, newly_opened=True, sinks=[sink])
    alert.status = "RESOLVED"
    alert.resolved_at = NOW + 60
    assert policy.on_resolved(alert, sinks=[sink])
    assert not policy.on_resolved(alert, sinks=[sink])
    titles = [title for title, _ in sink.messages]
    assert titles.count("RESOLVED HEARTBEAT_STALE") == 1


def test_ntf_005_file_sink_appends(tmp_path: Path) -> None:
    sink = ch.FileNotificationSink(tmp_path / "notifications.ndjson")
    sink.deliver("T1", "b1")
    sink.deliver("T2", "b2")
    lines = (tmp_path / "notifications.ndjson").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["title"] == "T1"


# --------------------------------------------------------------------------- #
# MEM — bounded memory reads (§10/§49)
# --------------------------------------------------------------------------- #


def test_mem_001_bounded_journal_read(tmp_path: Path) -> None:
    """A health journal with huge lines is read tail-bounded, no MemoryError."""
    path = tmp_path / "campaign_health.ndjson"
    blob = "x" * (ch.HEALTH_EVENT_MAX_BYTES * 64)  # 256 KiB per line
    with path.open("w", encoding="utf-8") as handle:
        for i in range(50):
            handle.write(json.dumps({"observed_at": i, "pad": blob}) + "\n")
    tail = ch.read_health_tail(tmp_path, limit=8)
    assert len(tail) == 8
    assert tail[-1]["observed_at"] == 49


def test_mem_002_health_event_size_bound() -> None:
    snapshot = _evaluator().evaluate(**_healthy_evidence())
    event = ch.health_event(snapshot)
    assert len(json.dumps(event).encode("utf-8")) < ch.HEALTH_EVENT_MAX_BYTES


def test_mem_003_cycle_tail_is_bounded(tmp_path: Path) -> None:
    """§09: the cycle-journal health reads a bounded tail, never the file."""
    with (tmp_path / "cycles.jsonl").open("a", encoding="utf-8") as handle:
        for cycle in range(200):
            handle.write(json.dumps({
                "event_version": cr.CYCLE_JOURNAL_VERSION, "cycle": cycle,
                "finished_at": NOW - cycle, "error_codes": [],
            }) + "\n")
    facts = ch.cycle_journal_facts(tmp_path, now=NOW, policy=_policy())
    assert facts["last_cycle_id"] == 199
    assert facts["event_count"] <= ch.CYC_TAIL


# --------------------------------------------------------------------------- #
# STR — linear storage growth (§21/§48)
# --------------------------------------------------------------------------- #


def test_str_001_linear_growth(tmp_path: Path) -> None:
    """96 checks/day x 30 days: journal size grows linearly, stays small."""
    evaluator = _evaluator()
    journal = tmp_path / "campaign_health.ndjson"
    sizes: list[int] = []
    for day in (1, 30, 365):
        # Rebuild the journal as if `day` days of checks had accumulated.
        with journal.open("w", encoding="utf-8") as handle:
            for tick in range(96 * day):
                snapshot = evaluator.evaluate(
                    **_healthy_evidence(now=NOW + tick * CADENCE)
                )
                event = ch.health_event(snapshot)
                handle.write(json.dumps(event, sort_keys=True) + "\n")
        sizes.append(journal.stat().st_size)
    per_event = sizes[0] / (96 * 1)
    assert sizes[1] == pytest.approx(per_event * 96 * 30, rel=0.01)
    assert sizes[2] == pytest.approx(per_event * 96 * 365, rel=0.01)
    # §22's size goal: a year of 15-minute checks stays humanly small.
    assert sizes[2] < 50 * 1024 * 1024


def test_str_002_no_history_in_event() -> None:
    """§21/§22: the event carries no embedded history or rollups."""
    snapshot = _evaluator().evaluate(**_healthy_evidence())
    event = json.dumps(ch.health_event(snapshot))
    for forbidden in ("history", "rollup", "daily", "events"):
        assert forbidden not in event.lower()
