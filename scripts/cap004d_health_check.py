#!/usr/bin/env python
"""CAP-004D — the campaign health check runner (§32).

One invocation:

1. gathers state from the EXISTING evidence (supervisor status, heartbeat,
   cycle journal, verifier report, ledger chain, drift, settlements, disk);
2. evaluates one deterministic snapshot;
3. persists it (CAMPAIGN_HEALTH.json + one compact journal event);
4. updates the alert lifecycle (open / dedup / resolve);
5. notifies via the configured sinks if the policy requires it;
6. prints a compact human summary;
7. exits with the §33 semantic code:

    0 = HEALTHY, 10 = DEGRADED, 20 = STALLED, 30 = CRITICAL, 40 = CHECK_FAILED

It is read-only with respect to the campaign: no scheduler restarts, no ledger
writes, no hash repairs (§30).  Designed to run unattended under Windows Task
Scheduler (§34): plain ``python scripts/cap004d_health_check.py``, no shell,
no interactivity, ASCII-safe output.

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
for candidate in (REPO / "src", REPO / "scripts"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from trading_bot.research import campaign_health as ch  # noqa: E402
from trading_bot.research import campaign_reporting as cr  # noqa: E402
from trading_bot.research import decision_ledger as dl  # noqa: E402
from trading_bot.research import disk_space as dsk  # noqa: E402

LEDGER_ROOT = REPO / "evidence" / "real_decisions"
CAMPAIGN_REPORT_ROOT = REPO / "reports" / "cap004"
SUPERVISOR_REPORT_ROOT = REPO / "reports" / "cap004b"
REPORT_ROOT = REPO / "reports" / "cap004d"
HEARTBEAT_IN_LEDGER = LEDGER_ROOT / "heartbeat.json"

EXIT_CODES: dict[str, int] = {"HEALTHY": 0, "DEGRADED": 10, "STALLED": 20, "CRITICAL": 30}
EXIT_CHECK_FAILED = 40


def now_seconds() -> int:
    return int(time.time())


def utc_iso(moment: int | None) -> str | None:
    if moment is None:
        return None
    return dt.datetime.fromtimestamp(int(moment), dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


# --------------------------------------------------------------------------- #
# evidence gathering — reads only what CAP-004 already produced (§07-§17)
# --------------------------------------------------------------------------- #


def gather_evidence(*, now: int, policy: ch.CampaignHealthPolicy,
                    skip_live_scheduler: bool) -> dict[str, Any]:
    """Collect decided evidence from the existing artifacts, bounded reads only."""
    supervisor_status = read_json(SUPERVISOR_REPORT_ROOT / "SUPERVISOR_STATUS.json")
    campaign_id = str(
        supervisor_status.get("campaign_id")
        or read_json(LEDGER_ROOT / "CAMPAIGN_MANIFEST.json").get("campaign_id")
        or "UNKNOWN"
    )

    heartbeat = cr.read_heartbeat(LEDGER_ROOT)
    if heartbeat is None:
        heartbeat = read_json(HEARTBEAT_IN_LEDGER)

    scheduler: dict[str, Any] | None = supervisor_status.get("scheduler")
    if scheduler and skip_live_scheduler:
        scheduler = dict(scheduler)
    elif not skip_live_scheduler:
        # §07: inspect the real registered task, best-effort, never raising.
        try:
            import cap004_supervisor as sup  # type: ignore[import-not-found]

            scheduler = sup.scheduler_status_safe()
        except Exception:
            scheduler = supervisor_status.get("scheduler")

    chain_status = str(supervisor_status.get("chain_status") or "UNKNOWN")
    drift_status = str(supervisor_status.get("drift_status") or "UNKNOWN")
    verifier = read_json(CAMPAIGN_REPORT_ROOT / "CAP004_VERIFICATION.json")

    ledger: dl.DecisionLedger | None = None
    if LEDGER_ROOT.is_dir():
        try:
            ledger = dl.DecisionLedger(LEDGER_ROOT)
            if chain_status == "UNKNOWN":
                chain_status = str(ledger.verify_chain().get("status") or "UNKNOWN")
        except Exception:
            chain_status = chain_status if chain_status != "UNKNOWN" else "UNKNOWN"

    settlements = ch.SettlementFacts(
        pending=list(ledger.pending_decisions()) if ledger is not None else [],
        last_settlement_progress_at=_last_outcome_time(ledger),
        now=now,
    )

    guard = dsk.DiskSpaceGuard(
        REPO,
        warning_bytes=policy.disk_warning_bytes,
        critical_bytes=policy.disk_critical_bytes,
    )
    try:
        guard_report = guard.report()
    except Exception:
        guard_report = {}

    last_decision_at = _last_decision_time(ledger)

    return {
        "campaign_id": campaign_id,
        "supervisor_status": supervisor_status,
        "scheduler": scheduler,
        "heartbeat": heartbeat,
        "verifier": verifier,
        "chain_status": chain_status,
        "drift_status": drift_status,
        "settlements": settlements,
        "guard_report": guard_report,
        "last_decision_at": last_decision_at,
    }


def _last_outcome_time(ledger: dl.DecisionLedger | None) -> int | None:
    if ledger is None:
        return None
    try:
        outcomes = ledger.outcomes()
    except Exception:
        return None
    times = [int(o.get("settled_at") or 0) for o in outcomes if o.get("settled_at")]
    return max(times) if times else None


def _last_decision_time(ledger: dl.DecisionLedger | None) -> int | None:
    if ledger is None:
        return None
    try:
        decisions = ledger.decisions()
    except Exception:
        return None
    times = [int(d.get("decision_time") or 0) for d in decisions if d.get("decision_time")]
    return max(times) if times else None


# --------------------------------------------------------------------------- #
# §20 — the human report
# --------------------------------------------------------------------------- #


def render_health_md(snapshot: ch.CampaignHealthSnapshot) -> str:
    s = snapshot
    lines = [
        "# CAP-004D CAMPAIGN HEALTH",
        "",
        f"- observed at: {utc_iso(s.observed_at)} ({s.observed_at})",
        f"- campaign: {s.campaign_id}",
        f"- **STATUS: {s.health_status}**",
        f"- reasons: {', '.join(s.reason_codes) if s.reason_codes else '(none)'}",
        "",
        "## Scheduler",
        "",
        f"- enabled: {_yes_no_unknown(s.scheduler_enabled)}",
        f"- last result: {s.scheduler_last_result}",
        f"- last run: {s.scheduler_last_run_at}",
        f"- next run: {s.scheduler_next_run_at}",
        "",
        "## Heartbeat",
        "",
        f"- last: {utc_iso(s.heartbeat_at)}",
        f"- age: {_human_age(s.heartbeat_age_seconds)}",
        "",
        "## Cycles",
        "",
        f"- last: {s.last_cycle_id}",
        f"- last at: {utc_iso(s.last_cycle_at)}",
        f"- age: {_human_age(s.cycle_age_seconds)}",
        f"- consecutive failures: {s.consecutive_cycle_failures}",
        "",
        "## Verify / chain / drift",
        "",
        f"- verify: {s.last_verify_status}",
        f"- chain: {s.chain_status}",
        f"- drift: {s.drift_status}",
        "",
        "## Settlements",
        "",
        f"- pending: {s.pending_settlements}",
        f"- oldest pending age: {_human_age(s.oldest_pending_settlement_age_seconds)}",
        "",
        "## Decisions",
        "",
        f"- last decision: {utc_iso(s.last_decision_at)}",
        f"- age: {_human_age(s.decision_age_seconds)}",
        "",
        "## Storage",
        "",
        f"- disk: {s.disk_status}",
        f"- free: {_human_bytes(s.disk_free_bytes)}",
        f"- warning forecast: {s.days_until_warning if s.days_until_warning is not None else 'n/a'} days",
        f"- critical forecast: {s.days_until_critical if s.days_until_critical is not None else 'n/a'} days",
        "",
        "## Alerts",
        "",
        _alerts_table(),
    ]
    return "\n".join(lines) + "\n"


def _alerts_table() -> str:
    alerts_path = REPORT_ROOT / "ALERTS.json"
    alerts = read_json(alerts_path).get("alerts", [])
    if not isinstance(alerts, list) or not alerts:
        return "No alerts recorded."
    rows = ["| alert | reason | severity | status | occurrences | first seen | last seen |",
            "| --- | --- | --- | --- | --- | --- | --- |"]
    for alert in alerts:
        rows.append(
            "| {alert_id} | {reason_code} | {severity} | {status} | {occurrence_count} | "
            "{first} | {last} |".format(
                first=utc_iso(int(alert.get("first_seen_at", 0))),
                last=utc_iso(int(alert.get("last_seen_at", 0))),
                **{k: alert.get(k) for k in
                   ("alert_id", "reason_code", "severity", "status", "occurrence_count")},
            )
        )
    return "\n".join(rows) + "\n"


def _yes_no_unknown(value: bool | None) -> str:
    return {True: "yes", False: "NO", None: "unknown"}[value]


def _human_age(seconds: int | None) -> str:
    if seconds is None:
        return "unknown"
    if seconds < 90:
        return f"{seconds}s"
    if seconds < 5400:
        return f"{round(seconds / 60)}m"
    if seconds < 172_800:
        return f"{round(seconds / 3600, 1)}h"
    return f"{round(seconds / 86_400, 1)}d"


def _human_bytes(size: int | None) -> str:
    if size is None:
        return "unknown"
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} PiB"


# --------------------------------------------------------------------------- #
# §32 — the run
# --------------------------------------------------------------------------- #


def run_health_check(*, now: int | None = None, policy: ch.CampaignHealthPolicy | None = None,
                     notify: bool = True, skip_live_scheduler: bool = False) -> dict[str, Any]:
    moment = now if now is not None else now_seconds()
    health_policy = policy or ch.CampaignHealthPolicy()

    evidence = gather_evidence(
        now=moment, policy=health_policy, skip_live_scheduler=skip_live_scheduler
    )
    evaluator = ch.CampaignHealthEvaluator(health_policy)
    snapshot = evaluator.evaluate(
        campaign_id=evidence["campaign_id"],
        observed_at=moment,
        scheduler=evidence["scheduler"],
        heartbeat=evidence["heartbeat"],
        cycle_journal=ch.cycle_journal_facts(CAMPAIGN_REPORT_ROOT, now=moment,
                                             policy=health_policy),
        verify_status=ch.last_verify_status(evidence["verifier"]),
        chain_status=evidence["chain_status"],
        drift_status=evidence["drift_status"],
        settlements=evidence["settlements"],
        disk=evidence["guard_report"],
        last_decision_at=evidence["last_decision_at"],
    )

    # §32.3 — persist snapshot + journal event
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    (REPORT_ROOT / "CAMPAIGN_HEALTH.json").write_text(
        json.dumps(snapshot.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (REPORT_ROOT / "CAMPAIGN_HEALTH.md").write_text(
        render_health_md(snapshot), encoding="utf-8"
    )
    event = ch.append_health_event(REPORT_ROOT, snapshot)

    # §32.4 — alert lifecycle
    store = ch.AlertStore(REPORT_ROOT / "ALERTS.jsonl")
    source_hash = ch.snapshot_source_hash(snapshot)
    newly_opened: list[ch.CampaignHealthAlert] = []
    observed_now: list[ch.CampaignHealthAlert] = []
    for reason in snapshot.reason_codes:
        if reason in ("NO_RECENT_DECISION", "NO_RECENT_DECISION_EXPECTED"):
            # §16: informational words never open alerts.
            continue
        severity = ch._REASON_SEVERITY[reason]
        alert, opened = store.observe(
            reason_code=reason,
            severity=severity,
            observed_at=moment,
            scope=snapshot.campaign_id,
            source_snapshot_hash=source_hash,
        )
        observed_now.append(alert)
        if opened:
            newly_opened.append(alert)
    resolved = store.resolve_missing(
        active_reasons={a.reason_code for a in observed_now}, observed_at=moment
    )
    store.save()
    # §57: the JSON view of the alert table, alongside the NDJSON source of truth.
    (REPORT_ROOT / "ALERTS.json").write_text(
        json.dumps(
            {"as_of": moment, "alerts": [a.to_dict() for a in store.all()]},
            indent=2, sort_keys=True, ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )

    # §32.5 — notifications per policy
    notified = 0
    if notify:
        notif = ch.NotificationPolicy(health_policy)
        sinks: list[ch.HealthNotificationSink] = [ch.ConsoleNotificationSink()]
        if moment == 0:  # pragma: no cover — file sink only for real runs
            pass
        file_sink = ch.FileNotificationSink(REPORT_ROOT / "notifications.ndjson")
        sinks.append(file_sink)
        for alert in observed_now:
            if notif.on_alert(alert, newly_opened=alert in newly_opened, sinks=sinks):
                notified += 1
        for alert in resolved:
            notif.on_resolved(alert, sinks=sinks)

    summary = {
        "observed_at": snapshot.observed_at,
        "observed_at_utc": utc_iso(snapshot.observed_at),
        "campaign_id": snapshot.campaign_id,
        "health_status": snapshot.health_status,
        "reason_codes": list(snapshot.reason_codes),
        "exit_code": EXIT_CODES.get(snapshot.health_status, EXIT_CHECK_FAILED),
        "event": event,
        "alerts_open": len(store.open_alerts()),
        "alerts_newly_opened": [a.alert_id for a in newly_opened],
        "alerts_resolved": [a.alert_id for a in resolved],
        "notifications_sent": notified,
    }
    return {"summary": summary, "snapshot": snapshot, "store": store}


def print_summary(summary: dict[str, Any]) -> None:
    """§32.6: compact ASCII summary — safe for any console / CI log."""
    print("CAP-004D CAMPAIGN HEALTH CHECK")
    print(f"  observed : {summary['observed_at_utc']}")
    print(f"  campaign : {summary['campaign_id']}")
    print(f"  status   : {summary['health_status']}")
    reasons = ",".join(summary["reason_codes"]) if summary["reason_codes"] else "(none)"
    print(f"  reasons  : {reasons}")
    print(f"  alerts   : {summary['alerts_open']} open "
          f"({len(summary['alerts_newly_opened'])} new, "
          f"{len(summary['alerts_resolved'])} resolved)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="CAP-004D campaign health check (observe-only watchdog)"
    )
    parser.add_argument("--json", action="store_true", help="print the full summary as JSON")
    parser.add_argument("--no-notify", action="store_true", help="skip notification sinks")
    parser.add_argument(
        "--no-live-scheduler",
        action="store_true",
        help="use the supervisor's cached scheduler snapshot instead of querying schtasks",
    )
    args = parser.parse_args(argv)
    try:
        result = run_health_check(
            notify=not args.no_notify, skip_live_scheduler=args.no_live_scheduler
        )
    except Exception as exc:
        print(f"CAP-004D CAMPAIGN HEALTH CHECK: CHECK_FAILED ({exc!r})")
        return EXIT_CHECK_FAILED
    summary = result["summary"]
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False, default=str))
    else:
        print_summary(summary)
    return int(summary["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
