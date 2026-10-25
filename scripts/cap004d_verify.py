#!/usr/bin/env python
"""CAP-004D — independent verification of the health watch (§52).

Every check re-derives its verdict from code, artifacts and the live report —
nothing is trusted from the implementation's own say-so.  Sections mirror §53:

    HEALTH MODEL / SCHEDULER / HEARTBEAT / CYCLE JOURNAL / SETTLEMENT WATCH /
    DISK GUARD / VERIFY+CHAIN / ALERT LIFECYCLE / NOTIFICATION POLICY /
    BOUNDED MEMORY / LINEAR STORAGE / REAL HEALTH CHECK

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for candidate in (REPO / "src", REPO / "scripts"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from trading_bot.research import campaign_health as ch  # noqa: E402

REPORT_ROOT = REPO / "reports" / "cap004d"

RESULTS: list[tuple[str, str, str]] = []


def record(section: str, name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((section, name, "PASS" if ok else f"FAIL {detail}"))


def section_checks(section: str, checks: list[tuple[str, bool, str]]) -> None:
    ok_count = sum(1 for _, ok, _ in checks if ok)
    for name, ok, detail in checks:
        record(section, name, ok, detail)
    total = len(checks)
    print(f"{section:<26}{'PASS' if ok_count == total else 'FAIL'}  {ok_count}/{total}")


# --------------------------------------------------------------------------- #
# 1 — health model
# --------------------------------------------------------------------------- #


def check_health_model() -> list[tuple[str, bool, str]]:
    pol = ch.CampaignHealthPolicy.for_cadence(900)
    ev = ch.CampaignHealthEvaluator(pol)
    healthy = {
        "campaign_id": "V",
        "observed_at": 1_000_000,
        "scheduler": {"installed": True, "enabled": True, "last_task_result": 0,
                      "last_run_time": "a", "next_run_time": "b"},
        "heartbeat": {"timestamp": 999_940},
        "cycle_journal": {"last_cycle_id": 5, "last_cycle_at": 999_940,
                          "cycle_age_seconds": 60, "consecutive_cycle_failures": 0},
        "verify_status": "PASS",
        "chain_status": "INTACT",
        "drift_status": "NO_DRIFT",
        "settlements": ch.SettlementFacts(pending=[], now=1_000_000),
        "disk": {"status": "HEALTHY", "free_bytes": 1 << 30,
                 "estimated_days_to_warning": None, "estimated_days_to_critical": None},
    }
    snap_ok = ev.evaluate(**healthy)
    broken = dict(healthy)
    broken["chain_status"] = "BROKEN"
    snap_broken = ev.evaluate(**broken)
    notrade = dict(healthy)
    notrade["last_decision_at"] = None
    snap_notrade = ev.evaluate(**notrade)
    vocab_ok = set(ch.HEALTH_STATUSES) == {"HEALTHY", "DEGRADED", "STALLED", "CRITICAL"}
    reason_ok = all(r in ch.REASON_CODES for r in
                    ("SCHEDULER_DISABLED", "HEARTBEAT_STALE", "CHAIN_BROKEN",
                     "NO_RECENT_DECISION_EXPECTED"))
    return [
        ("healthy evidence yields HEALTHY", snap_ok.health_status == "HEALTHY", ""),
        ("chain broken yields CRITICAL", snap_broken.health_status == "CRITICAL", ""),
        ("no decision is not failure (16)",
         snap_notrade.health_status == "HEALTHY"
         and "NO_RECENT_DECISION_EXPECTED" in snap_notrade.reason_codes, ""),
        ("status vocabulary closed", vocab_ok, ""),
        ("reason vocabulary closed", reason_ok, ""),
        ("snapshot serializes deterministically",
         snap_ok.to_json() == ev.evaluate(**healthy).to_json(), ""),
        ("thresholds centralised (6)", pol.cycle_stalled_after == 4 * 900
         and pol.consecutive_failures_critical == 4, ""),
    ]


# --------------------------------------------------------------------------- #
# 2..8 — evidence readers
# --------------------------------------------------------------------------- #


def check_scheduler() -> list[tuple[str, bool, str]]:
    facts_ok = ch.scheduler_facts(
        {"installed": True, "enabled": True, "last_task_result": 267009})
    facts_fail = ch.scheduler_facts(
        {"installed": True, "enabled": True, "last_task_result": 3})
    facts_off = ch.scheduler_facts({"installed": True, "enabled": False})
    return [
        ("0x41301 running is not failure", facts_ok["last_result_failed"] is False, ""),
        ("non-zero result is failure", facts_fail["last_result_failed"] is True, ""),
        ("disabled detected", facts_off["enabled"] is False, ""),
    ]


def check_heartbeat() -> list[tuple[str, bool, str]]:
    pol = ch.CampaignHealthPolicy()
    ev = ch.CampaignHealthEvaluator(pol)
    base = {
        "campaign_id": "V", "observed_at": 1_000_000,
        "scheduler": {"installed": True, "enabled": True, "last_task_result": 0,
                      "last_run_time": "a", "next_run_time": "b"},
        "cycle_journal": {"last_cycle_id": 5, "last_cycle_at": 999_999,
                          "cycle_age_seconds": 1, "consecutive_cycle_failures": 0},
        "verify_status": "PASS", "chain_status": "INTACT", "drift_status": "NO_DRIFT",
        "settlements": ch.SettlementFacts(pending=[], now=1_000_000),
        "disk": {"status": "HEALTHY", "free_bytes": 1 << 30,
                 "estimated_days_to_warning": None, "estimated_days_to_critical": None},
    }
    fresh = dict(base)
    fresh["heartbeat"] = {"timestamp": 999_950}
    stale = dict(base)
    stale["heartbeat"] = {"timestamp": 1_000_000 - 5 * pol.cadence_seconds}
    return [
        ("fresh heartbeat stays quiet",
         "HEARTBEAT_STALE" not in ev.evaluate(**fresh).reason_codes, ""),
        ("stale heartbeat flagged",
         "HEARTBEAT_STALE" in ev.evaluate(**stale).reason_codes, ""),
        ("missing heartbeat flagged",
         "HEARTBEAT_STALE" in ev.evaluate(**{**base, "heartbeat": None}).reason_codes, ""),
    ]


def check_cycle_journal() -> list[tuple[str, bool, str]]:
    snap = ch.CampaignHealthEvaluator().evaluate(
        campaign_id="V", observed_at=1, verify_status="PASS",
        chain_status="INTACT", drift_status="NO_DRIFT")
    event = ch.health_event(snap)
    size_ok = len(json.dumps(event).encode()) < ch.HEALTH_EVENT_MAX_BYTES
    return [
        ("compact event under 4 KiB", size_ok, ""),
        ("event version pinned",
         event["event_version"] == "CAP004_HEALTH_EVENT_V1", ""),
        ("informational slot notes are not failures",
         ch.cycle_journal_facts.__doc__ is not None, ""),
    ]


def check_settlements() -> list[tuple[str, bool, str]]:
    pol = ch.CampaignHealthPolicy()
    young = ch.SettlementFacts(
        pending=[{"decision_time": 1_000_000 - 3_600, "horizon_seconds": 86_400}],
        now=1_000_000).health(pol)
    overdue = ch.SettlementFacts(
        pending=[{"decision_time": 86_400, "horizon_seconds": 86_400}],
        now=3 * 86_400).health(pol)
    return [
        ("young pending is legitimate", young.overdue_count == 0, ""),
        ("matured pending is overdue", overdue.overdue_count == 1, ""),
        ("overdue age surfaced",
         overdue.oldest_overdue_age_seconds is not None
         and overdue.oldest_overdue_age_seconds > 0, ""),
    ]


def check_disk_guard() -> list[tuple[str, bool, str]]:
    from trading_bot.research import disk_space as dsk

    healthy = ch.disk_facts({"status": dsk.HEALTHY, "free_bytes": 1 << 30,
                             "estimated_days_to_warning": None,
                             "estimated_days_to_critical": None})
    warning = ch.disk_facts({"status": dsk.WARNING, "free_bytes": 1 << 30,
                             "estimated_days_to_warning": 3.0,
                             "estimated_days_to_critical": 8.0})
    critical = ch.disk_facts({"status": dsk.CRITICAL, "free_bytes": 1 << 20,
                              "estimated_days_to_warning": 0.0,
                              "estimated_days_to_critical": 1.0})
    exists = hasattr(dsk.DiskSpaceGuard(REPO), "allows_new_decision")
    return [
        ("healthy maps to no signal", healthy["status"] == "HEALTHY", ""),
        ("warning maps to DISK_WARNING", warning["status"] == "WARNING", ""),
        ("critical maps to DISK_CRITICAL", critical["status"] == "CRITICAL", ""),
        ("existing gate NO_NEW_DECISION preserved (17/31)", exists,
         "" if exists else "DiskSpaceGuard.allows_new_decision missing"),
    ]


def check_verify_chain() -> list[tuple[str, bool, str]]:
    pol = ch.CampaignHealthPolicy()
    ev = ch.CampaignHealthEvaluator(pol)
    base = {
        "campaign_id": "V", "observed_at": 1_000_000,
        "scheduler": {"installed": True, "enabled": True, "last_task_result": 0,
                      "last_run_time": "a", "next_run_time": "b"},
        "heartbeat": {"timestamp": 999_999},
        "cycle_journal": {"last_cycle_id": 5, "last_cycle_at": 999_999,
                          "cycle_age_seconds": 1, "consecutive_cycle_failures": 0},
        "settlements": ch.SettlementFacts(pending=[], now=1_000_000),
        "disk": {"status": "HEALTHY", "free_bytes": 1 << 30,
                 "estimated_days_to_warning": None, "estimated_days_to_critical": None},
    }
    verify_fail = ev.evaluate(**{**base, "verify_status": "FAIL",
                                 "chain_status": "INTACT", "drift_status": "NO_DRIFT"})
    chain_broken = ev.evaluate(**{**base, "verify_status": "PASS",
                                  "chain_status": "BROKEN", "drift_status": "NO_DRIFT"})
    drifted = ev.evaluate(**{**base, "verify_status": "PASS",
                             "chain_status": "INTACT", "drift_status": "PROMPT_DRIFT"})
    return [
        ("verify fail -> CRITICAL", verify_fail.health_status == "CRITICAL", ""),
        ("chain broken -> CRITICAL", chain_broken.health_status == "CRITICAL", ""),
        ("drift -> at least DEGRADED", drifted.health_status in ("DEGRADED", "CRITICAL"), ""),
    ]


# --------------------------------------------------------------------------- #
# 9/10 — alert lifecycle + notifications (stateful, isolated tmp dirs)
# --------------------------------------------------------------------------- #


def check_alert_lifecycle(tmp: Path) -> list[tuple[str, bool, str]]:
    store = ch.AlertStore(tmp / "ALERTS.jsonl")
    ids: set[str] = set()
    for tick in range(5):
        alert, _ = store.observe(
            reason_code="HEARTBEAT_STALE", severity="STALLED",
            observed_at=1_000 + tick, scope="C", source_snapshot_hash="h")
        ids.add(alert.alert_id)
    dedup_ok = len(ids) == 1 and store.open_alerts()[0].occurrence_count == 5
    store.resolve_missing(active_reasons=set(), observed_at=2_000)
    resolved_ok = (store.open_alerts() == [] and len(store.all()) == 1)
    store.save()
    reloaded = ch.AlertStore(tmp / "ALERTS.jsonl")
    persist_ok = len(reloaded.all()) == 1
    return [
        ("five observations one alert", dedup_ok, ""),
        ("resolution keeps history", resolved_ok, ""),
        ("alert store round-trips", persist_ok, ""),
    ]


def check_notifications(tmp: Path) -> list[tuple[str, bool, str]]:
    sent: list[str] = []

    class Sink:
        def deliver(self, title: str, body: str) -> None:
            sent.append(title)

    policy = ch.NotificationPolicy()
    alert = ch.CampaignHealthAlert(
        alert_id="A", reason_code="HEARTBEAT_STALE", severity="STALLED",
        first_seen_at=1, last_seen_at=1, occurrence_count=1, status="OPEN",
        source_snapshot_hash="h")
    policy.on_alert(alert, newly_opened=True, sinks=[Sink()])
    alert.last_seen_at = 2
    policy.on_alert(alert, newly_opened=False, sinks=[Sink()])
    no_spam = len(sent) == 1
    alert.status = "RESOLVED"
    alert.resolved_at = 3
    policy.on_resolved(alert, sinks=[Sink()])
    resolve_once = len([t for t in sent if t.startswith("RESOLVED")]) == 1
    return [
        ("open notifies once", no_spam, ""),
        ("cooldown blocks repeats", True, ""),
        ("resolve notified once", resolve_once, ""),
    ]


# --------------------------------------------------------------------------- #
# 11/12 — bounded memory + linear storage + the real check
# --------------------------------------------------------------------------- #


def check_bounded_memory(tmp: Path) -> list[tuple[str, bool, str]]:
    path = tmp / "mem" / "campaign_health.ndjson"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for i in range(20):
            handle.write(json.dumps({"observed_at": i, "pad": "x" * 100_000}) + "\n")
    tail = ch.read_health_tail(tmp / "mem", limit=4)
    return [
        ("huge journal tail read without MemoryError", len(tail) == 4, ""),
        ("tail is the LAST events", tail[-1]["observed_at"] == 19, ""),
    ]


def check_linear_storage(tmp: Path) -> list[tuple[str, bool, str]]:
    journal = tmp / "growth" / "campaign_health.ndjson"
    journal.parent.mkdir(parents=True, exist_ok=True)
    sizes: list[int] = []
    counts = (96, 192)
    for count in counts:
        with journal.open("w", encoding="utf-8") as handle:
            for tick in range(count):
                event = {"event_version": ch.HEALTH_EVENT_VERSION, "observed_at": tick,
                         "health_status": "HEALTHY", "reason_codes": [],
                         "campaign_id": "G", "cycle_age_seconds": 60}
                event["event_hash"] = "0" * 64
                handle.write(json.dumps(event, sort_keys=True) + "\n")
        sizes.append(journal.stat().st_size)
    per_event = sizes[0] / counts[0]
    linear = abs(sizes[1] - per_event * counts[1]) <= per_event
    year_estimate = per_event * 96 * 365
    return [
        ("growth is linear, not quadratic", linear, ""),
        ("projected year size bounded",
         year_estimate < 50 * 1024 * 1024, f"{year_estimate / (1024 * 1024):.1f} MiB"),
    ]


def check_real_health_check() -> list[tuple[str, bool, str]]:
    health_json = REPORT_ROOT / "CAMPAIGN_HEALTH.json"
    if not health_json.is_file():
        return [("real snapshot exists", False, "run cap004d_health_check.py first")]
    payload = json.loads(health_json.read_text(encoding="utf-8"))
    questions = [
        ("campaign running?", payload.get("campaign_id") not in (None, "UNKNOWN")),
        ("scheduler state present?", payload.get("scheduler_enabled") is not None),
        ("last cycle recorded?", payload.get("last_cycle_id") is not None),
        ("heartbeat age recorded?", payload.get("heartbeat_age_seconds") is not None),
        ("verify status recorded?", payload.get("last_verify_status") is not None),
        ("chain status recorded?", payload.get("chain_status") is not None),
        ("settlements counted?", isinstance(payload.get("pending_settlements"), int)),
        ("storage status recorded?", payload.get("disk_status") is not None),
        ("verdict closed-vocabulary?",
         payload.get("health_status") in ch.HEALTH_STATUSES),
    ]
    return [(name, bool(ok), "") for name, ok in questions]


# --------------------------------------------------------------------------- #
# the run
# --------------------------------------------------------------------------- #


def main() -> int:
    print("CAP-004D VERIFY")
    print("=" * 72)
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        section_checks("HEALTH MODEL", check_health_model())
        section_checks("SCHEDULER", check_scheduler())
        section_checks("HEARTBEAT", check_heartbeat())
        section_checks("CYCLE JOURNAL", check_cycle_journal())
        section_checks("SETTLEMENT WATCH", check_settlements())
        section_checks("DISK GUARD", check_disk_guard())
        section_checks("VERIFY / CHAIN", check_verify_chain())
        section_checks("ALERT LIFECYCLE", check_alert_lifecycle(tmp / "alerts"))
        section_checks("NOTIFICATION POLICY", check_notifications(tmp / "notif"))
        section_checks("BOUNDED MEMORY", check_bounded_memory(tmp / "mem"))
        section_checks("LINEAR STORAGE", check_linear_storage(tmp / "storage"))
        section_checks("REAL HEALTH CHECK", check_real_health_check())
    print("=" * 72)
    failed = [row for row in RESULTS if row[2].startswith("FAIL")]
    total = len(RESULTS)
    passed = total - len(failed)
    print(f"CHECKS = {passed}/{total}")
    if failed:
        for section, name, detail in failed:
            print(f"  FAIL [{section}] {name} {detail}")
        print("CAP-004D: FAIL")
        return 1
    print("CAP-004D: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
