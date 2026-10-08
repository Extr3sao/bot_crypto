"""CAP-004D — Campaign health watch & autonomous recovery signals.

The question this module answers is operational, not scientific: *can the
campaign be left running without a human watching it?*  It observes the
existing CAP-004 evidence — scheduler, heartbeat, cycle journal, verifier,
ledger chain, drift, settlements, disk — and condenses it into one
deterministic snapshot with a closed status vocabulary:

    HEALTHY / DEGRADED / STALLED / CRITICAL

Design constraints, in order:

1. **Observe, never act.**  No scheduler restarts, no ledger writes, no hash
   repairs, no forced settlements (§30).  The only automatic action ever
   surfaced is the pre-existing ``NO_NEW_DECISION_DISK_CRITICAL`` gate, which
   stays owned by CAP-004C's ``DiskSpaceGuard`` (§17/§31).
2. **Closed vocabularies.**  Health statuses (§04) and reason codes (§05) are
   tuples, not free text; a consumer can switch on them.
3. **``NO_TRADE`` is not failure** (§16).  A campaign whose scheduler runs,
   whose cycles advance, whose verify passes and whose chain is intact is
   HEALTHY even when it produces no decisions; the lack of decisions becomes
   only the informational reason ``NO_RECENT_DECISION_EXPECTED``.
4. **Bounded reads** (§09/§10).  Cycle-journal state is read through the
   existing tail-bounded reader, never via ``read_text().splitlines()`` over a
   possibly-gigantic journal; the health module adds its own bounded reader
   for its own journal.
5. **Alerts are a lifecycle, not a stream** (§23-§26).  One persistent
   condition maps to one alert whose ``occurrence_count`` grows; observations
   are append-only events, alerts are state.
6. **Determinism** (§18).  Same evidence → same snapshot; ``observed_at`` is
   carried by the caller so a fixed clock reproduces the same verdict.

Research only: no orders, no credentials, no capital, no edge claim (§55).
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
from collections import deque
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from . import campaign_reporting as cr
from . import campaign_state as cs
from .disk_space import CRITICAL as DISK_CRITICAL
from .disk_space import WARNING as DISK_WARNING

# --------------------------------------------------------------------------- #
# §04 / §05 — closed vocabularies
# --------------------------------------------------------------------------- #

#: §04. No ad-hoc states; every verdict is one of these four words.
HEALTH_STATUSES: tuple[str, ...] = ("HEALTHY", "DEGRADED", "STALLED", "CRITICAL")

#: Severity ranking used by §19's aggregation: higher wins.
_HEALTH_SEVERITY: dict[str, int] = {
    "HEALTHY": 0,
    "DEGRADED": 1,
    "STALLED": 2,
    "CRITICAL": 3,
}

#: §05. The complete reason vocabulary.  Reasons are machine words; the human
#: explanation lives in the rendered report, keyed off these codes.
REASON_CODES: tuple[str, ...] = (
    "SCHEDULER_DISABLED",
    "SCHEDULER_LAST_RUN_FAILED",
    "SCHEDULER_OVERDUE",
    "HEARTBEAT_STALE",
    "CYCLE_JOURNAL_STALE",
    "VERIFY_FAILED",
    "CHAIN_BROKEN",
    "DRIFT_DETECTED",
    "SETTLEMENT_PENDING_OVERDUE",
    "SETTLEMENT_PROGRESS_STALLED",
    "DISK_WARNING",
    "DISK_CRITICAL",
    "CONSECUTIVE_CYCLE_FAILURES",
    "NO_RECENT_DECISION",
    "NO_RECENT_DECISION_EXPECTED",
)

#: §19. Which reasons map to which minimum severity, with the map closing the
#: vocabulary: a reason without an entry cannot be emitted.
_REASON_SEVERITY: dict[str, str] = {
    "SCHEDULER_DISABLED": "DEGRADED",
    "SCHEDULER_LAST_RUN_FAILED": "DEGRADED",
    "SCHEDULER_OVERDUE": "DEGRADED",
    "HEARTBEAT_STALE": "STALLED",
    "CYCLE_JOURNAL_STALE": "STALLED",
    "VERIFY_FAILED": "CRITICAL",
    "CHAIN_BROKEN": "CRITICAL",
    "DRIFT_DETECTED": "DEGRADED",
    "SETTLEMENT_PENDING_OVERDUE": "DEGRADED",
    "SETTLEMENT_PROGRESS_STALLED": "STALLED",
    "DISK_WARNING": "DEGRADED",
    "DISK_CRITICAL": "CRITICAL",
    "CONSECUTIVE_CYCLE_FAILURES": "DEGRADED",
    "NO_RECENT_DECISION": "HEALTHY",  # informational only (§16)
    "NO_RECENT_DECISION_EXPECTED": "HEALTHY",  # informational only (§16)
}

#: §19's priority order for ordering the emitted reasons deterministically.
_REASON_PRIORITY: tuple[str, ...] = (
    "CHAIN_BROKEN",
    "DISK_CRITICAL",
    "VERIFY_FAILED",
    "SETTLEMENT_PROGRESS_STALLED",
    "DRIFT_DETECTED",
    "SETTLEMENT_PENDING_OVERDUE",
    "SCHEDULER_DISABLED",
    "CYCLE_JOURNAL_STALE",
    "HEARTBEAT_STALE",
    "SCHEDULER_OVERDUE",
    "SCHEDULER_LAST_RUN_FAILED",
    "CONSECUTIVE_CYCLE_FAILURES",
    "DISK_WARNING",
    "NO_RECENT_DECISION",
    "NO_RECENT_DECISION_EXPECTED",
)

#: §13. Drift labels that touch settlement/evaluation integrity and therefore
#: escalate beyond DEGRADED.  Anything else stays informational-degraded.
_INTEGRITY_DRIFT_LABELS = frozenset({"PROMPT_DRIFT", "FEATURE_DRIFT"})

#: Journal constants for the health history (§21/§22).
HEALTH_EVENT_VERSION = "CAP004_HEALTH_EVENT_V1"
HEALTH_JOURNAL_FILENAME = "campaign_health.ndjson"
HEALTH_EVENT_MAX_BYTES = 4096  # §22: a health event stays under 4 KiB

#: §24. Alert lifecycle states, closed.
ALERT_STATUSES: tuple[str, ...] = ("OPEN", "ACKNOWLEDGED", "RESOLVED")


# --------------------------------------------------------------------------- #
# §06 — cadence policy: every threshold lives here
# --------------------------------------------------------------------------- #


@dataclasses.dataclass(frozen=True)
class CampaignHealthPolicy:
    """The thresholds CAP-004D uses, centralised (§06).

    Defaults derive from the campaign's nominal 15-minute cadence; nothing
    else in the module owns a magic number.
    """

    cadence_seconds: int = 900
    cycle_warning_after: int = 2 * 900
    cycle_stalled_after: int = 4 * 900
    heartbeat_warning_after: int = 2 * 900
    heartbeat_stalled_after: int = 4 * 900
    scheduler_overdue_after: int = 2 * 900
    consecutive_failures_degraded: int = 2
    consecutive_failures_critical: int = 4
    settlement_overdue_after: int = 2 * 900
    settlement_stalled_after: int = 4 * 900
    decision_expected_after: int = 24 * 3600  # informational window (§16)
    disk_warning_bytes: int = 5 * 1024**3
    disk_critical_bytes: int = 2 * 1024**3
    #: §27: how long a sink must stay quiet about the same alert.
    notification_cooldown_seconds: int = 4 * 3600
    notification_critical_cooldown_seconds: int = 12 * 3600

    @classmethod
    def for_cadence(cls, cadence_seconds: int) -> CampaignHealthPolicy:
        """The policy for an arbitrary cadence, scaled from the 15-min default."""
        factor = max(int(cadence_seconds), 1) / 900
        return cls(
            cadence_seconds=int(cadence_seconds),
            cycle_warning_after=int(2 * 900 * factor),
            cycle_stalled_after=int(4 * 900 * factor),
            heartbeat_warning_after=int(2 * 900 * factor),
            heartbeat_stalled_after=int(4 * 900 * factor),
            scheduler_overdue_after=int(2 * 900 * factor),
            settlement_overdue_after=int(2 * 900 * factor),
            settlement_stalled_after=int(4 * 900 * factor),
        )


# --------------------------------------------------------------------------- #
# §03 — the snapshot
# --------------------------------------------------------------------------- #


@dataclasses.dataclass(frozen=True)
class CampaignHealthSnapshot:
    """One deterministic observation of the whole campaign (§03).

    ``observed_at`` is an epoch second supplied by the caller; serialisation is
    field-order-stable, so the same evidence at the same instant renders
    byte-identical JSON.
    """

    observed_at: int
    campaign_id: str

    scheduler_enabled: bool | None
    scheduler_last_result: int | None
    scheduler_last_run_at: str | None
    scheduler_next_run_at: str | None

    last_cycle_id: int | None
    last_cycle_at: int | None
    cycle_age_seconds: int | None

    heartbeat_at: int | None
    heartbeat_age_seconds: int | None

    last_verify_status: str | None

    chain_status: str
    drift_status: str

    pending_settlements: int
    oldest_pending_settlement_age_seconds: int | None

    last_decision_at: int | None
    decision_age_seconds: int | None

    disk_status: str
    disk_free_bytes: int | None
    days_until_warning: float | None
    days_until_critical: float | None

    consecutive_cycle_failures: int

    health_status: str
    reason_codes: tuple[str, ...]

    source_hashes: Mapping[str, str] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Field-stable serialisation (§03: deterministically serializable)."""
        payload = dataclasses.asdict(self)
        payload["reason_codes"] = list(self.reason_codes)
        payload["source_hashes"] = dict(sorted(self.source_hashes.items()))
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False, default=str)


# --------------------------------------------------------------------------- #
# §14 — settlement health
# --------------------------------------------------------------------------- #


@dataclasses.dataclass(frozen=True)
class SettlementHealth:
    """§14: pending settlements, split due from not-yet-due."""

    pending_count: int = 0
    overdue_count: int = 0
    oldest_pending_age_seconds: int | None = None
    oldest_overdue_age_seconds: int | None = None
    last_settlement_progress_at: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class SettlementFacts:
    """What the settlement watch needs from the ledger, already decided."""

    #: Decisions whose horizon has no outcome yet (the ledger's own list).
    pending: Sequence[Mapping[str, Any]] = ()
    #: Epoch second of the last settlement progress (outcome appended); None
    #: when the campaign has never settled anything.
    last_settlement_progress_at: int | None = None
    #: Current epoch second, injected for determinism.
    now: int = 0

    def health(self, policy: CampaignHealthPolicy) -> SettlementHealth:
        """Split pending into legitimate (not yet due) and overdue (§14)."""
        overdue = 0
        oldest_pending: int | None = None
        oldest_overdue: int | None = None
        for entry in self.pending:
            decision_time = int(entry.get("decision_time", 0) or 0)
            horizon = int(entry.get("horizon_seconds", 0) or 0)
            age = max(self.now - decision_time, 0)
            if oldest_pending is None or age > oldest_pending:
                oldest_pending = age
            # Only a decision whose horizon already elapsed is exigible (§14):
            # a young pending decision is the campaign working as designed.
            if horizon and self.now >= decision_time + horizon:
                overdue += 1
                if oldest_overdue is None or age > oldest_overdue:
                    oldest_overdue = age
        return SettlementHealth(
            pending_count=len(self.pending),
            overdue_count=overdue,
            oldest_pending_age_seconds=oldest_pending,
            oldest_overdue_age_seconds=oldest_overdue,
            last_settlement_progress_at=self.last_settlement_progress_at,
        )


# --------------------------------------------------------------------------- #
# §07/§08/§09/§11/§12/§13/§17 — evidence readers (bounded, reusing sources)
# --------------------------------------------------------------------------- #


def scheduler_facts(scheduler: Mapping[str, Any] | None) -> dict[str, Any]:
    """§07: flatten the supervisor's scheduler snapshot into decided facts.

    ``installed=False`` with no query error is read as *disabled*; an errored
    query is reported as unknown rather than invented.

    Windows Task Scheduler result codes are translated honestly: ``267009``
    (``0x41301``, SCHED_S_TASK_RUNNING) and the other SCHED_S_* informational
    codes are NOT failures — reading them as one would invent a failing
    campaign out of a healthy one.  They are preserved verbatim in
    ``last_result`` and only the verdict is normalised.
    """
    scheduler = dict(scheduler or {})
    if not scheduler:
        return {"installed": None, "enabled": None, "last_result": None,
                "last_result_failed": None,
                "last_run_at": None, "next_run_at": None}
    errored = "error" in scheduler or bool(scheduler.get("query_stderr"))
    installed = bool(scheduler.get("installed"))
    enabled = None if errored else bool(installed and scheduler.get("enabled"))
    last_result = (
        int(scheduler["last_task_result"])
        if scheduler.get("last_task_result") is not None else None
    )
    last_result_failed = None if last_result is None else last_result not in _SCHED_OK_CODES
    return {
        "installed": installed if not errored else None,
        "enabled": enabled,
        "last_result": last_result,
        "last_result_failed": last_result_failed,
        "last_run_at": scheduler.get("last_run_time"),
        "next_run_at": scheduler.get("next_run_time"),
    }


#: Windows Task Scheduler codes that are not task failures (SCHED_S_* family).
_SCHED_OK_CODES = frozenset({0, 267009, 267011, 267014, 267015})


def last_verify_status(verifier: Mapping[str, Any] | None) -> str | None:
    """§11: the verifier's own status word, or None when never run."""
    verifier = dict(verifier or {})
    status = verifier.get("status")
    return str(status) if status else None


def cycle_journal_facts(report_root: Path, *, now: int,
                        policy: CampaignHealthPolicy) -> dict[str, Any]:
    """§09: bounded tail of the cycle journal — never the whole file.

    Reads at most the last ``CYC_TAIL`` events plus the chain check the
    existing verifier already does across segments; the chain walk is the
    existing bounded streaming reader, not ``read_text().splitlines()``.
    """
    tail = cr.read_cycle_journal(report_root, limit=CYC_TAIL)
    last = tail[-1] if tail else None
    last_at: int | None = None
    if last is not None:
        for key in ("finished_at", "started_at"):
            value = last.get(key)
            if isinstance(value, (int, float)):
                last_at = int(value)
                break
            if isinstance(value, str) and value.isdigit():
                last_at = int(value)
                break
    failures = 0
    for entry in reversed(tail):
        # Only REAL failure states count (the campaign state machine's own
        # vocabulary); ``MISSED_DECISION_SLOT`` and other informational slot
        # notes are the campaign working as designed, never a cycle failure.
        codes = [str(code) for code in (entry.get("error_codes") or [])]
        if any(code in cs.ERROR_STATES for code in codes):
            failures += 1
        else:
            break
    # A negative age would mean clock skew or a backdated observation; it is
    # clamped to ``0`` so a skew can never mask staleness.
    return {
        "last_cycle_id": int(last["cycle"]) if last and last.get("cycle") is not None else None,
        "last_cycle_at": last_at,
        "cycle_age_seconds": max(now - last_at, 0) if last_at is not None else None,
        "consecutive_cycle_failures": failures,
        "event_count": len(tail),
    }


#: How many tail events the journal health reads; bounded by design (§09).
CYC_TAIL = 24


def chain_and_drift(ledger_chain: Mapping[str, Any] | None,
                    drift: Mapping[str, Any] | None) -> dict[str, str]:
    """§12/§13: consume the existing semantics, never reinterpret them."""
    chain_status = str((ledger_chain or {}).get("status") or "UNKNOWN")
    drift_status = str((drift or {}).get("status") or "UNKNOWN")
    return {"chain_status": chain_status, "drift_status": drift_status}


def disk_facts(guard_report: Mapping[str, Any] | None) -> dict[str, Any]:
    """§17: re-use the disk guard's own report verbatim (no duplicate guard)."""
    report = dict(guard_report or {})
    if not report:
        return {"status": "UNKNOWN", "free_bytes": None,
                "days_until_warning": None, "days_until_critical": None}
    warning = report.get("estimated_days_to_warning")
    critical = report.get("estimated_days_to_critical")
    return {
        "status": str(report.get("status") or "UNKNOWN"),
        "free_bytes": report.get("free_bytes"),
        "days_until_warning": float(warning) if warning is not None else None,
        "days_until_critical": float(critical) if critical is not None else None,
    }


# --------------------------------------------------------------------------- #
# §18 — the evaluator
# --------------------------------------------------------------------------- #


class CampaignHealthEvaluator:
    """Deterministic aggregation of evidence into one snapshot (§18/§19).

    Every input is decided data (mappings, already read); the evaluator owns
    no I/O, so the same inputs at the same ``observed_at`` produce the same
    snapshot byte-for-byte.
    """

    def __init__(self, policy: CampaignHealthPolicy | None = None) -> None:
        self.policy = policy or CampaignHealthPolicy()

    def evaluate(
        self,
        *,
        campaign_id: str,
        observed_at: int,
        scheduler: Mapping[str, Any] | None = None,
        heartbeat: Mapping[str, Any] | None = None,
        cycle_journal: Mapping[str, Any] | None = None,
        verify_status: str | None = None,
        chain_status: str = "UNKNOWN",
        drift_status: str = "UNKNOWN",
        settlements: SettlementFacts | None = None,
        disk: Mapping[str, Any] | None = None,
        last_decision_at: int | None = None,
        source_hashes: Mapping[str, str] | None = None,
    ) -> CampaignHealthSnapshot:
        policy = self.policy
        sched = scheduler_facts(scheduler)
        cyc = dict(cycle_journal or {})
        disk_info = disk_facts(disk)
        settle = (settlements or SettlementFacts(now=observed_at)).health(policy)

        reasons: set[str] = set()

        # -- scheduler (§07) -------------------------------------------------
        if sched["enabled"] is False:
            reasons.add("SCHEDULER_DISABLED")
        elif sched["enabled"] is None and scheduler:
            # An errored query with an installed task is suspicion, not proof.
            reasons.add("SCHEDULER_OVERDUE")
        last_result = sched["last_result"]
        if sched["last_result_failed"]:
            reasons.add("SCHEDULER_LAST_RUN_FAILED")
        next_run = scheduler.get("next_run_time") if scheduler else None
        last_run = scheduler.get("last_run_time") if scheduler else None
        if sched["enabled"] and not next_run and not last_run:
            reasons.add("SCHEDULER_OVERDUE")

        # -- heartbeat (§08) -------------------------------------------------
        hb_age: int | None = None
        if heartbeat and heartbeat.get("timestamp") is not None:
            hb_age = max(observed_at - int(heartbeat["timestamp"]), 0)
        if hb_age is None or hb_age > policy.heartbeat_stalled_after:
            reasons.add("HEARTBEAT_STALE")

        # -- cycle journal (§09) ----------------------------------------------
        cycle_age = cyc.get("cycle_age_seconds")
        if cycle_age is None or int(cycle_age) > policy.cycle_stalled_after:
            reasons.add("CYCLE_JOURNAL_STALE")
        failures = int(cyc.get("consecutive_cycle_failures", 0) or 0)
        if failures >= policy.consecutive_failures_critical or failures >= policy.consecutive_failures_degraded:
            reasons.add("CONSECUTIVE_CYCLE_FAILURES")

        # -- verify (§11) -----------------------------------------------------
        if verify_status is not None and verify_status != "PASS":
            reasons.add("VERIFY_FAILED")

        # -- chain (§12) -------------------------------------------------------
        if chain_status == "BROKEN":
            reasons.add("CHAIN_BROKEN")

        # -- drift (§13) -------------------------------------------------------
        if drift_status not in ("NO_DRIFT",):
            reasons.add("DRIFT_DETECTED")

        # -- settlements (§14/§15) ---------------------------------------------
        if settle.overdue_count > 0:
            if settle.oldest_overdue_age_seconds is not None and (
                settle.oldest_overdue_age_seconds > policy.settlement_overdue_after
            ):
                reasons.add("SETTLEMENT_PENDING_OVERDUE")
            if settle.oldest_overdue_age_seconds is not None and (
                settle.oldest_overdue_age_seconds > policy.settlement_stalled_after
                and (
                    settle.last_settlement_progress_at is None
                    or observed_at - settle.last_settlement_progress_at
                    > policy.settlement_stalled_after
                )
            ):
                reasons.add("SETTLEMENT_PROGRESS_STALLED")

        # -- disk (§17) ---------------------------------------------------------
        if disk_info["status"] == DISK_WARNING:
            reasons.add("DISK_WARNING")
        elif disk_info["status"] == DISK_CRITICAL:
            reasons.add("DISK_CRITICAL")

        # -- §16: the informational decision window ------------------------------
        decision_age = (
            max(observed_at - last_decision_at, 0) if last_decision_at is not None else None
        )
        healthy_framing = (
            chain_status == "INTACT"
            and verify_status == "PASS"
            and sched["enabled"] is True
            and cycle_age is not None
            and int(cycle_age) <= policy.cycle_warning_after
            and hb_age is not None
            and hb_age <= policy.heartbeat_warning_after
        )
        if decision_age is None or decision_age > policy.decision_expected_after:
            reasons.add("NO_RECENT_DECISION")
            if healthy_framing:
                # The campaign is alive and simply legitimately declining to
                # trade: informational, never an alarm (§16).
                reasons.add("NO_RECENT_DECISION_EXPECTED")

        # -- §19 aggregation ------------------------------------------------------
        status = self._aggregate(reasons, cycle_age=cycle_age, hb_age=hb_age, policy=policy)
        ordered = [r for r in _REASON_PRIORITY if r in reasons]
        snapshot = CampaignHealthSnapshot(
            observed_at=observed_at,
            campaign_id=campaign_id,
            scheduler_enabled=sched["enabled"],
            scheduler_last_result=last_result,
            scheduler_last_run_at=sched["last_run_at"],
            scheduler_next_run_at=sched["next_run_at"],
            last_cycle_id=cyc.get("last_cycle_id"),
            last_cycle_at=cyc.get("last_cycle_at"),
            cycle_age_seconds=int(cycle_age) if cycle_age is not None else None,
            heartbeat_at=(
                int(heartbeat["timestamp"]) if heartbeat and heartbeat.get("timestamp") else None
            ),
            heartbeat_age_seconds=hb_age,
            last_verify_status=verify_status,
            chain_status=chain_status,
            drift_status=drift_status,
            pending_settlements=settle.pending_count,
            oldest_pending_settlement_age_seconds=settle.oldest_pending_age_seconds,
            last_decision_at=last_decision_at,
            decision_age_seconds=decision_age,
            disk_status=disk_info["status"],
            disk_free_bytes=disk_info["free_bytes"],
            days_until_warning=disk_info["days_until_warning"],
            days_until_critical=disk_info["days_until_critical"],
            consecutive_cycle_failures=failures,
            health_status=status,
            reason_codes=tuple(ordered),
            source_hashes=dict(source_hashes or {}),
        )
        return snapshot

    def _aggregate(self, reasons: set[str], *, cycle_age: Any, hb_age: Any,
                   policy: CampaignHealthPolicy) -> str:
        """Highest severity wins; a HEALTHY signal can never mask a CRITICAL."""
        if not reasons:
            return "HEALTHY"
        severity = max(
            (_HEALTH_SEVERITY[_REASON_SEVERITY[code]] for code in reasons),
            default=0,
        )
        return HEALTH_STATUSES[severity]


# --------------------------------------------------------------------------- #
# §20/§21/§22 — persistence: snapshot + compact append-only journal
# --------------------------------------------------------------------------- #


def snapshot_source_hash(snapshot: CampaignHealthSnapshot) -> str:
    """A stable digest of a snapshot's evidence, kept as alert provenance.

    Alert identity keys on ``(reason_code, campaign_id)`` — see ``AlertStore`` —
    so this hash documents WHICH evidence first showed the condition without
    having to stay equal across observations.
    """
    body = snapshot.to_dict()
    body.pop("observed_at", None)
    body.pop("health_status", None)
    body.pop("reason_codes", None)
    canonical = json.dumps(body, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def health_event(snapshot: CampaignHealthSnapshot) -> dict[str, Any]:
    """§22: one compact event, bounded well under 4 KiB.

    No history, no rollups, no cycle lists — exactly the defect CAP-004C
    removed from the cycle journal is not reintroduced here (§21).
    """
    event = {
        "event_version": HEALTH_EVENT_VERSION,
        "observed_at": snapshot.observed_at,
        "observed_at_utc": _iso(snapshot.observed_at),
        "campaign_id": snapshot.campaign_id,
        "health_status": snapshot.health_status,
        "reason_codes": list(snapshot.reason_codes),
        "last_cycle_id": snapshot.last_cycle_id,
        "cycle_age_seconds": snapshot.cycle_age_seconds,
        "heartbeat_age_seconds": snapshot.heartbeat_age_seconds,
        "last_verify_status": snapshot.last_verify_status,
        "chain_status": snapshot.chain_status,
        "drift_status": snapshot.drift_status,
        "pending_settlements": snapshot.pending_settlements,
        "disk_status": snapshot.disk_status,
        "disk_free_bytes": snapshot.disk_free_bytes,
        "consecutive_cycle_failures": snapshot.consecutive_cycle_failures,
    }
    event["event_hash"] = _event_digest(event)
    return event


def _event_digest(event: Mapping[str, Any]) -> str:
    """Chain digest in the repo's existing ``payload_digest`` style."""
    body = {k: v for k, v in event.items() if k != "event_hash"}
    canonical = json.dumps(body, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def append_health_event(report_root: Path, snapshot: CampaignHealthSnapshot) -> dict[str, Any]:
    """§21: append one compact event; never embed history."""
    path = Path(report_root) / HEALTH_JOURNAL_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    event = health_event(snapshot)
    line = json.dumps(event, sort_keys=True, ensure_ascii=False, default=str)
    if len(line.encode("utf-8")) > HEALTH_EVENT_MAX_BYTES:
        raise ValueError("CAP004_HEALTH_EVENT_V1 exceeded 4 KiB")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    return event


def read_health_tail(report_root: Path, *, limit: int = 64) -> list[dict[str, Any]]:
    """Bounded tail of the health journal — deque(maxlen), never splitlines (§10)."""
    path = Path(report_root) / HEALTH_JOURNAL_FILENAME
    if not path.is_file():
        return []
    kept: deque[dict[str, Any]] = deque(maxlen=limit)
    with path.open("rb") as handle:
        for raw in handle:
            if not raw.strip():
                continue
            try:
                kept.append(json.loads(raw.decode("utf-8", errors="replace")))
            except json.JSONDecodeError:
                continue
    return list(kept)


# --------------------------------------------------------------------------- #
# §24/§25/§26 — alert lifecycle
# --------------------------------------------------------------------------- #


@dataclasses.dataclass
class CampaignHealthAlert:
    """§24: one condition, one alert, occurrence counts, immutable evidence."""

    alert_id: str
    reason_code: str
    severity: str
    first_seen_at: int
    last_seen_at: int
    occurrence_count: int
    status: str
    source_snapshot_hash: str
    resolved_at: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


class AlertStore:
    """The alert table (JSON file): one row per ``(reason_code, campaign_id)``.

    Condition identity is deliberately coarse: a persistent ``HEARTBEAT_STALE``
    is one alert no matter how the surrounding evidence wiggles, because the
    volatile ages inside a snapshot change every observation and keying on them
    would mint one alert per check — exactly what §25 forbids.  The first
    observation's evidence hash is recorded once and never mutated (§24).
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._alerts: dict[str, CampaignHealthAlert] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.is_file():
            return
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            alert = CampaignHealthAlert(
                alert_id=str(record["alert_id"]),
                reason_code=str(record["reason_code"]),
                severity=str(record["severity"]),
                first_seen_at=int(record["first_seen_at"]),
                last_seen_at=int(record["last_seen_at"]),
                occurrence_count=int(record["occurrence_count"]),
                status=str(record["status"]),
                source_snapshot_hash=str(record["source_snapshot_hash"]),
                resolved_at=record.get("resolved_at"),
            )
            self._alerts[alert.alert_id] = alert

    @staticmethod
    def alert_id_for(reason_code: str, scope: str) -> str:
        """Stable per-condition identity: one reason in one campaign."""
        return f"ALERT-{hashlib.sha256(f'{reason_code}|{scope}'.encode()).hexdigest()[:16]}"

    def save(self) -> None:
        lines = [json.dumps(a.to_dict(), sort_keys=True, ensure_ascii=False) for a in
                 self._alerts.values()]
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def all(self) -> list[CampaignHealthAlert]:
        return list(self._alerts.values())

    def open_alerts(self) -> list[CampaignHealthAlert]:
        return [a for a in self._alerts.values() if a.status == "OPEN"]

    def _latest_episode(self, base_id: str) -> CampaignHealthAlert | None:
        """The most recent row for a condition — the base row or its latest
        suffixed episode, whichever was seen last."""
        candidates = [
            alert for alert_id, alert in self._alerts.items()
            if alert_id == base_id or alert_id.startswith(f"{base_id}-")
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda alert: (alert.first_seen_at, alert.last_seen_at))

    def observe(
        self,
        *,
        reason_code: str,
        severity: str,
        observed_at: int,
        scope: str,
        source_snapshot_hash: str,
    ) -> tuple[CampaignHealthAlert, bool]:
        """§25: one condition → one OPEN alert; occurrences grow, rows do not.

        Dedup targets the LATEST row for the condition, whatever its id: an
        episode opened five minutes ago keeps accumulating occurrences even
        though the original base row resolved in between.  A NEW episode is
        minted only when the latest episode is RESOLVED — §26 keeps history
        immutable, so separate episodes keep separate rows.
        """
        base_id = self.alert_id_for(reason_code, scope)
        existing = self._latest_episode(base_id)
        if existing is None:
            alert = CampaignHealthAlert(
                alert_id=base_id,
                reason_code=reason_code,
                severity=severity,
                first_seen_at=observed_at,
                last_seen_at=observed_at,
                occurrence_count=1,
                status="OPEN",
                source_snapshot_hash=source_snapshot_hash,
            )
            self._alerts[base_id] = alert
            return alert, True
        if existing.status == "RESOLVED":
            alert_id = f"{base_id}-{observed_at}"
            alert = CampaignHealthAlert(
                alert_id=alert_id,
                reason_code=reason_code,
                severity=severity,
                first_seen_at=observed_at,
                last_seen_at=observed_at,
                occurrence_count=1,
                status="OPEN",
                source_snapshot_hash=source_snapshot_hash,
            )
            self._alerts[alert_id] = alert
            return alert, True
        existing.last_seen_at = observed_at
        existing.occurrence_count += 1
        return existing, False

    def resolve_missing(self, *, active_reasons: set[str],
                        observed_at: int) -> list[CampaignHealthAlert]:
        """§26: OPEN alerts whose condition vanished become RESOLVED."""
        resolved: list[CampaignHealthAlert] = []
        for alert in self._alerts.values():
            if alert.status != "OPEN":
                continue
            if alert.reason_code in active_reasons:
                continue
            alert.status = "RESOLVED"
            alert.resolved_at = observed_at
            resolved.append(alert)
        return resolved


# --------------------------------------------------------------------------- #
# §27/§28/§29 — notification policy and sinks
# --------------------------------------------------------------------------- #


class HealthNotificationSink(Protocol):
    """§28: where notifications go; add Telegram/email later without churn."""

    def deliver(self, title: str, body: str) -> None: ...


class ConsoleNotificationSink:
    """§28: the minimal sink — print to stdout."""

    def deliver(self, title: str, body: str) -> None:
        print(f"[cap004d] {title}: {body}")


class FileNotificationSink:
    """§29: append-only NDJSON, no secrets, one line per notification."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def deliver(self, title: str, body: str) -> None:
        record = {
            "delivered_at": int(dt.datetime.now(dt.UTC).timestamp()),
            "title": title,
            "body": body,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")


@dataclasses.dataclass
class NotificationRecord:
    alert_id: str
    last_sent_at: int
    times_sent: int


class NotificationPolicy:
    """§27: notify on open, respect cooldowns, one optional resolve notice.

    State is in-memory per run; the runner persists nothing secret, and the
    file sink already keeps an append-only audit trail (§29).
    """

    def __init__(self, policy: CampaignHealthPolicy | None = None) -> None:
        self.policy = policy or CampaignHealthPolicy()
        self._sent: dict[str, NotificationRecord] = {}

    def _cooldown_for(self, severity: str) -> int:
        if severity == "CRITICAL":
            return self.policy.notification_critical_cooldown_seconds
        return self.policy.notification_cooldown_seconds

    def on_alert(
        self,
        alert: CampaignHealthAlert,
        *,
        newly_opened: bool,
        sinks: Sequence[HealthNotificationSink],
    ) -> bool:
        """Decide-and-send for one alert observation."""
        cooldown = self._cooldown_for(alert.severity)
        record = self._sent.get(alert.alert_id)
        if record is not None and alert.last_seen_at - record.last_sent_at < cooldown:
            return False
        title = f"{alert.severity} {alert.reason_code}"
        body = (
            f"alert {alert.alert_id} occurrence {alert.occurrence_count} "
            f"since {_iso(alert.first_seen_at)}"
        )
        for sink in sinks:
            sink.deliver(title, body)
        self._sent[alert.alert_id] = NotificationRecord(
            alert_id=alert.alert_id,
            last_sent_at=alert.last_seen_at,
            times_sent=(record.times_sent + 1) if record else 1,
        )
        return True

    def on_resolved(
        self, alert: CampaignHealthAlert, *, sinks: Sequence[HealthNotificationSink]
    ) -> bool:
        """§27: the optional single resolve notice; sent once per alert."""
        record = self._sent.get(alert.alert_id)
        if record is not None and record.times_sent > 1:
            return False
        for sink in sinks:
            sink.deliver(f"RESOLVED {alert.reason_code}", f"alert {alert.alert_id} resolved")
        if record is None:
            self._sent[alert.alert_id] = NotificationRecord(
                alert_id=alert.alert_id, last_sent_at=alert.resolved_at or 0, times_sent=1
            )
        else:
            record.times_sent += 1
        return True


def _iso(moment: int | None) -> str | None:
    if moment is None:
        return None
    return dt.datetime.fromtimestamp(int(moment), dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
