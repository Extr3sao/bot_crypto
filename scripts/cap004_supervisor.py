"""CAP-004B — the persistent campaign supervisor.

CAP-004 already knows *how* to seal, settle, evaluate, score and verify.  What it
does not have is a persistent, restart-safe way to be *kept running*: until now
``CAMPAIGN_STATUS = RUNNING`` described a logical state, not a live process.  This
supervisor closes that gap without touching the experiment.

It is the single entry point the operating system calls on a schedule:

    OS scheduler -> cap004_supervisor.py run -> (lease) -> due work
                 -> CAP-004 cycle -> CAP-004 verification -> heartbeat
                 -> operations event -> exit

Design rules that make it safe to run every fifteen minutes forever:

* **It reuses CAP-004, it does not reimplement it.**  Decision, outcome, baseline,
  score and verification logic stay in their own modules; this file only decides
  *whether* there is due work and records what happened.
* **Exactly-once is CAP-004's job and stays that way.**  A lease makes two
  simultaneous invocations impossible (the second reports ``ALREADY_RUNNING``),
  and a due-work gate means ninety-six scheduler runs a day still produce at most
  one decision per asset per day.
* **Nothing the supervisor writes can corrupt the campaign.**  Integrity or drift
  failures put the supervisor in ``BLOCKED`` and it refuses to touch the ledger.
* **Operational state is separate from the campaign.**  A supervisor heartbeat and
  a campaign heartbeat are different instruments: the campaign verifier keeps
  treating an old heartbeat as a diagnostic (CAP-004 ``bf83b7f``); the supervisor
  treats staleness as an operational fact and degrades.  Neither vocabulary leaks
  into the other.
* **Downtime is normal, not damage.**  A decision sealed before the machine slept
  is settled on recovery; a decision slot that closed while the machine was off is
  ``MISSED_DECISION_SLOT`` and is never backfilled with future market data.

Every invocation appends one hashed event to ``evidence/real_decisions/operations.jsonl``
so the operational history is auditable independently of the scientific ledger.

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import logging
import logging.handlers
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
SCRIPT = Path(__file__).resolve()
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import cap004_campaign_runner as campaign  # noqa: E402

from trading_bot.research import alpha_scorecard as asc  # noqa: E402
from trading_bot.research import campaign_lock as cl  # noqa: E402
from trading_bot.research import campaign_manifest as cm  # noqa: E402
from trading_bot.research import campaign_reporting as cr  # noqa: E402
from trading_bot.research import campaign_state as cs  # noqa: E402
from trading_bot.research import decision_ledger as dl  # noqa: E402
from trading_bot.research import disk_space as dsk  # noqa: E402
from trading_bot.research import market_analyst_v1 as mav  # noqa: E402
from trading_bot.research import real_market_context as rmc  # noqa: E402

# --------------------------------------------------------------------------- #
# §0 — identity
# --------------------------------------------------------------------------- #

SUPERVISOR_NAME = "cap004-supervisor"
SUPERVISOR_VERSION = "CAP004B-1"

#: Operational version, deliberately kept apart from ``campaign_version``: an ops
#: change must never alter the scientific cohort identity (CAP-004B §11).
OPS_VERSION = "CAP004B-1"

LEDGER_ROOT = REPO / "evidence" / "real_decisions"
CAMPAIGN_REPORT_ROOT = REPO / "reports" / "cap004"
REPORT_ROOT = REPO / "reports" / "cap004b"
OPS_LEDGER = LEDGER_ROOT / "operations.jsonl"
SUPERVISOR_STATUS_FILENAME = "SUPERVISOR_STATUS.json"
PROBE_TASK_NAME = "TradingAgentic-CAP004-NetProbe"
PROBE_REPORT_FILENAME = "MARKET_DATA_PROBE.json"
FIRST_SETTLEMENT_JSON = "FIRST_REAL_SETTLEMENT.json"
FIRST_SETTLEMENT_MD = "FIRST_REAL_SETTLEMENT.md"
LOG_DIR = REPO / "logs"
LOG_FILENAME = "cap004_supervisor.log"

TASK_NAME = "TradingAgentic-CAP004-Campaign"
TASK_DESCRIPTION = (
    "Trading Agentic Portable — CAP-004B persistent campaign supervisor. "
    "Runs one due-work cycle of the frozen CAP-004 experiment and never trades."
)

DEFAULT_INTERVAL_SECONDS = 900
SCHEDULER_STALE_FACTOR = 2
DAILY_VERIFY_SECONDS = 86_400
OPS_LOG_MAX_BYTES = 1_000_000
OPS_LOG_BACKUPS = 5

GENESIS_HASH = "0" * 64

#: The supervisor's own vocabulary, never mixed with ``CAMPAIGN_STATUSES``.
SUPERVISOR_STATES: tuple[str, ...] = ("HEALTHY", "DEGRADED", "RECOVERING", "BLOCKED", "STOPPED")

OPERATION_ACTIONS: tuple[str, ...] = (
    "RUN",
    "NOOP",
    "PREFLIGHT_BLOCKED",
    "STOPPED",
    "INSTALL",
    "UNINSTALL",
    "START",
    "STOP",
    "RUN_NOW",
    "VERIFY",
    "STATUS",
)

#: Failures the supervisor may retry on its own; everything else is a stop sign.
RETRYABLE_CODES: frozenset[str] = frozenset(
    {
        "NETWORK",
        "TEMPORARY_PROVIDER_FAILURE",
        "DATA_NOT_READY",
        "TRANSIENT",
        "DATA_BLOCKED",
        "OUTCOME_BLOCKED_DATA",
    }
)

#: Failures that must never be auto-repaired: repairing them would mean editing
#: frozen evidence or the frozen experiment.
BLOCKING_CODES: frozenset[str] = frozenset(
    {
        "CHAIN_FAILURE",
        "INTEGRITY_FAILURE",
        "RAW_HASH_MISMATCH",
        "RAW_EVIDENCE_HASH_MISMATCH",
        "PROMPT_DRIFT",
        "FEATURE_DRIFT",
        "CAMPAIGN_CONFIGURATION_DRIFT",
        "CONFIG_DRIFT",
        "SCHEMA_DRIFT",
        "MODEL_DRIFT",
    }
)

VERIFIERS: dict[str, Path] = {
    "cap003": REPO / "scripts" / "cap003_verify.py",
    "cap004": REPO / "scripts" / "cap004_verify.py",
    "cap004b": REPO / "scripts" / "cap004b_verify.py",
}


# --------------------------------------------------------------------------- #
# §1 — small helpers
# --------------------------------------------------------------------------- #


def now_seconds() -> int:
    return int(time.time())


def utc_iso(moment: int | None) -> str | None:
    if moment is None:
        return None
    return dt.datetime.fromtimestamp(int(moment), dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical_json(payload: Any) -> str:
    """The one canonicalisation both the supervisor and its verifier agree on."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def digest_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_event_hash(record: Mapping[str, Any]) -> str:
    """SHA-256 over the event body, excluding its own ``event_hash``."""
    body = {key: value for key, value in record.items() if key != "event_hash"}
    return digest_text(canonical_json(body))


def git_commit() -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=False
    )
    return proc.stdout.strip()


def hostname() -> str:
    return socket.gethostname()


# --------------------------------------------------------------------------- #
# §2 — the operations ledger (append-only, hash-chained)
# --------------------------------------------------------------------------- #


def read_operations(path: Path) -> list[dict[str, Any]]:
    if not Path(path).is_file():
        return []
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def last_event_hash(entries: Sequence[Mapping[str, Any]]) -> str:
    return str(entries[-1]["event_hash"]) if entries else GENESIS_HASH


def last_verification_time(entries: Sequence[Mapping[str, Any]]) -> int | None:
    """When the last CAP-004 verification passed, read from the ops ledger.

    The campaign heartbeat is written *before* the verify phase, so in one-shot
    (scheduled) mode it can never carry the current verify result; the operations
    ledger is the authority for the supervisor's own verification cadence.
    """
    # ``started_at`` shares the cycle clock (``ended_at`` is wall-clock completion),
    # so the daily cadence is measured on the same timeline the gate is evaluated on.
    stamps = [
        int(entry.get("started_at", 0)) for entry in entries if str(entry.get("verification")) == "PASS"
    ]
    return max(stamps) if stamps else None


def operation_entry(
    *,
    campaign_id: str,
    ops_version: str,
    started_at: int,
    ended_at: int,
    host: str,
    pid: int,
    code_commit: str,
    action: str,
    sealed: int,
    settled: int,
    evaluated: int,
    scored: bool,
    verification: str,
    exit_code: int,
    error_type: str | None,
    error: str | None,
    previous_hash: str,
    operation_id: str | None = None,
    disk: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """One operational event, chained to the previous one by hash.

    ``disk`` records the storage state measured before this invocation.  It is
    operational metadata about the HOST, never an input to any decision, and it is
    part of the hashed body so a later edit of it breaks the chain.
    """
    record: dict[str, Any] = {
        "operation_id": operation_id or uuid.uuid4().hex,
        "campaign_id": campaign_id,
        "ops_version": ops_version,
        "started_at": int(started_at),
        "started_at_utc": utc_iso(started_at),
        "ended_at": int(ended_at),
        "ended_at_utc": utc_iso(ended_at),
        "hostname": host,
        "pid": int(pid),
        "code_commit": code_commit,
        "action": action,
        "sealed": int(sealed),
        "settled": int(settled),
        "evaluated": int(evaluated),
        "scored": bool(scored),
        "verification": verification,
        "exit_code": int(exit_code),
        "error_type": error_type,
        "error": error,
        "previous_hash": previous_hash,
    }
    if disk is not None:
        record["disk_free_bytes"] = disk.get("free_bytes")
        record["disk_status"] = disk.get("status")
    record["event_hash"] = compute_event_hash(record)
    return record


def append_operation(path: Path, record: Mapping[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(canonical_json(dict(record)) + "\n")


def verify_operations_chain(entries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Re-derive the whole chain from disk.  A tampered event breaks it."""
    previous = GENESIS_HASH
    for index, entry in enumerate(entries):
        if str(entry.get("previous_hash")) != previous:
            return {
                "status": "BROKEN",
                "broken_index": index,
                "reason": "previous_hash does not match the prior event_hash",
            }
        expected = compute_event_hash(entry)
        if str(entry.get("event_hash")) != expected:
            return {
                "status": "BROKEN",
                "broken_index": index,
                "reason": "event_hash does not re-derive from the event body",
            }
        previous = str(entry["event_hash"])
    return {
        "status": "INTACT",
        "events": len(entries),
        "head": previous,
    }


# --------------------------------------------------------------------------- #
# §3 — due work
# --------------------------------------------------------------------------- #


def _slot_keys(slot: int) -> list[str]:
    return [
        cm.decision_key(
            asset=asset,
            decision_time=slot,
            horizon=cm.HORIZON,
            analyst_version=mav.PROMPT_VERSION,
        )
        for asset in cm.CAMPAIGN_ASSETS
    ]


def due_work(
    *,
    ledger: dl.DecisionLedger,
    manifest: Mapping[str, Any],
    now: int,
    last_verify: int | None,
) -> dict[str, Any]:
    """What, if anything, this run must actually do.  NOOP is a valid answer."""
    decisions = ledger.decisions()
    occupied = cm.occupied_decision_keys(decisions)
    slot = cm.due_decision_slot(now)
    delay = int(now) - slot
    within_window = delay <= cm.SEAL_WINDOW_SECONDS
    unsealed = [key for key in _slot_keys(slot) if key not in occupied]
    seal_due = within_window and bool(unsealed)
    missed = campaign.missed_slots(ledger, dict(manifest), now=now)
    settle_due = any(
        cs.maturity_state(
            decision_time=int(item["decision_time"]), horizon=str(item["horizon"]), now=now
        )["matured"]
        for item in ledger.pending_decisions()
    )
    verify_due = last_verify is None or (int(now) - int(last_verify)) >= DAILY_VERIFY_SECONDS
    return {
        "decision_slot": slot,
        "decision_slot_utc": utc_iso(slot),
        "within_seal_window": within_window,
        "unsealed_slot_keys": unsealed,
        "seal_due": seal_due,
        "missed_slots": missed,
        "missed_due": bool(missed),
        "settle_due": settle_due,
        "verify_due": verify_due,
        "nothing_due": not (seal_due or missed or settle_due),
    }


def plan_modes(due: Mapping[str, Any]) -> tuple[str, ...]:
    """Select the CAP-004 phases this run needs, in the canonical order."""
    modes: list[str] = []
    if due.get("seal_due") or due.get("missed_due"):
        modes.append("seal")
    if due.get("settle_due"):
        modes.append("settle")
    modes.append("score")
    if due.get("seal_due") or due.get("settle_due") or due.get("verify_due"):
        modes.append("verify")
    return tuple(modes)


# --------------------------------------------------------------------------- #
# §4 — preflight and failure policy
# --------------------------------------------------------------------------- #


def classify_error(code: str) -> str:
    """``RETRYABLE`` or ``BLOCKING`` — never a guess the caller has to make."""
    if code in BLOCKING_CODES:
        return "BLOCKING"
    if code in RETRYABLE_CODES:
        return "RETRYABLE"
    return "BLOCKING"


def preflight(*, ledger_root: Path, manifest: Mapping[str, Any] | None) -> dict[str, Any]:
    """Cheap, in-process integrity gate.  Heavy verifiers run on a daily cadence."""
    if manifest is None:
        return {"status": "BLOCKED", "code": "CAMPAIGN_NOT_INITIALIZED", "retryable": False}
    ledger = dl.DecisionLedger(ledger_root)
    chain = ledger.verify_chain()
    if chain["status"] != "INTACT":
        return {
            "status": "BLOCKED",
            "code": "CHAIN_FAILURE",
            "retryable": False,
            "broken": chain.get("broken"),
        }
    drift = cm.detect_drift(manifest)
    if drift["status"] != "NO_DRIFT":
        return {
            "status": "BLOCKED",
            "code": str(drift["status"]),
            "retryable": False,
            "drifted": drift.get("drifted"),
        }
    raw = cs.raw_evidence_status(ledger_root, decisions=ledger.decisions())
    counts = raw.get("counts") or {}
    if int(counts.get("RAW_EVIDENCE_HASH_MISMATCH", 0)) > 0:
        return {
            "status": "BLOCKED",
            "code": "RAW_HASH_MISMATCH",
            "retryable": False,
            "raw_evidence": raw,
        }
    return {"status": "OK", "chain": chain, "drift": drift, "raw_evidence": raw}


# --------------------------------------------------------------------------- #
# §5 — operational health (strictly separate from campaign status)
# --------------------------------------------------------------------------- #


def supervisor_health(
    *,
    heartbeat: Mapping[str, Any] | None,
    now: int,
    interval_seconds: int,
    blocked: bool,
    stop_requested: bool,
    matured_unsettled: int,
) -> str:
    """The supervisor's own freshness verdict, never a campaign verdict."""
    if blocked:
        return "BLOCKED"
    if stop_requested:
        return "STOPPED"
    age = cr.heartbeat_age_seconds(heartbeat, now=now)
    if age is None:
        return "DEGRADED"
    if age <= max(interval_seconds, 1) * SCHEDULER_STALE_FACTOR:
        return "HEALTHY"
    if int(matured_unsettled) > 0:
        return "RECOVERING"
    return "DEGRADED"


def heartbeat_fresh(
    *, heartbeat: Mapping[str, Any] | None, now: int, interval_seconds: int
) -> bool:
    age = cr.heartbeat_age_seconds(heartbeat, now=now)
    return age is not None and age <= max(interval_seconds, 1) * SCHEDULER_STALE_FACTOR


# --------------------------------------------------------------------------- #
# §6 — logging (operational logs never live under reports/)
# --------------------------------------------------------------------------- #


def configure_logging(log_dir: Path = LOG_DIR, *, capture_stdout: bool = True) -> logging.Logger:
    logger = logging.getLogger(SUPERVISOR_NAME)
    logger.setLevel(logging.INFO)
    if not any(isinstance(handler, logging.handlers.RotatingFileHandler) for handler in logger.handlers):
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            Path(log_dir) / LOG_FILENAME,
            maxBytes=OPS_LOG_MAX_BYTES,
            backupCount=OPS_LOG_BACKUPS,
            encoding="utf-8",
        )
        file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(file_handler)
    if capture_stdout and not any(
        type(handler) is logging.StreamHandler for handler in logger.handlers
    ):
        stream = logging.StreamHandler(sys.stdout)
        stream.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(stream)
    logger.propagate = False
    return logger


# --------------------------------------------------------------------------- #
# §7 — the supervised cycle
# --------------------------------------------------------------------------- #


def _load_manifest(ledger_root: Path) -> dict[str, Any] | None:
    return cm.load_manifest(ledger_root)


def _seed_store(heartbeat: Mapping[str, Any] | None, *, interval_seconds: int) -> dict[str, Any]:
    """Carry the success timestamps across one-shot invocations."""
    previous = heartbeat or {}
    return {
        "interval_seconds": int(interval_seconds),
        "cycle": int(previous.get("cycle") or 0) + 1,
        "last_seal": previous.get("last_successful_seal"),
        "last_settle": previous.get("last_successful_settle"),
        "last_score": previous.get("last_successful_score"),
        "last_verify": previous.get("last_successful_verify"),
    }


def run_supervised_cycle(
    *,
    now: int,
    ledger_root: Path = LEDGER_ROOT,
    report_root: Path = REPORT_ROOT,
    ops_path: Path = OPS_LEDGER,
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
    cycle_fn: Callable[..., dict[str, Any]] | None = None,
    scheduler_probe: Callable[[], Mapping[str, Any]] | None = None,
    code_commit: str | None = None,
    operation_id: str | None = None,
) -> dict[str, Any]:
    """One supervised invocation: lease, preflight, due work, cycle, evidence.

    ``cycle_fn`` is injectable so the tests can exercise the whole orchestration
    without a network call; production always defaults to ``campaign.run_cycle``.
    """
    started_at = int(now)
    commit = code_commit if code_commit is not None else git_commit()
    ops_entries = read_operations(ops_path)
    heartbeat = cr.read_heartbeat(ledger_root)
    # CAP-004C §19/§17: free space is measured BEFORE the cycle and recorded with
    # it.  CRITICAL refuses NEW decisions; it never blocks the settlement or the
    # evaluation of decisions that are already sealed, which is preservation work.
    guard = dsk.DiskSpaceGuard(report_root)
    new_decision_allowed, disk_gate_code = guard.allows_new_decision()
    # The forecast comes from the same measured series the cycle uses, and never
    # across a certified migration boundary (§21/§22).
    discontinuity = campaign.storage_discontinuities(report_root)
    disk = guard.report(
        samples=campaign.growth_samples(campaign.load_storage_samples(report_root)),
        after=discontinuity,
    )
    disk["migration_discontinuity"] = discontinuity
    disk["new_decision_allowed"] = new_decision_allowed
    disk["gate_code"] = disk_gate_code
    lock = cl.CampaignLock(
        ledger_root,
        campaign_id=cm.CAMPAIGN_ID,
        stale_after_seconds=max(interval_seconds * 4, cl.DEFAULT_STALE_AFTER_SECONDS),
    )

    acquisition = lock.acquire(now=started_at)
    if not acquisition["acquired"]:
        result = _record_operation(
            ops_path=ops_path,
            ops_entries=ops_entries,
            campaign_id=cm.CAMPAIGN_ID,
            started_at=started_at,
            ended_at=now_seconds(),
            commit=commit,
            action="NOOP",
            sealed=0,
            settled=0,
            evaluated=0,
            scored=False,
            verification="SKIPPED",
            exit_code=0,
            error_type="ALREADY_RUNNING",
            error="another supervisor instance holds the lease",
            operation_id=operation_id,
            disk=disk,
        )
        result.update({"acquired": False, "status": "ALREADY_RUNNING", "holder": acquisition.get("holder")})
        return result

    stop_requested = lock.stop_requested()
    manifest = _load_manifest(ledger_root)
    pre = preflight(ledger_root=ledger_root, manifest=manifest)
    blocked = pre["status"] == "BLOCKED"

    due: dict[str, Any] = {}
    modes: tuple[str, ...] = ()
    cycle_result: dict[str, Any] | None = None
    error_type: str | None = None
    error: str | None = None
    verification = "SKIPPED"
    sealed = settled = evaluated = 0
    scored = False
    action = "NOOP"
    exit_code = 0

    try:
        if blocked:
            action = "PREFLIGHT_BLOCKED"
            error_type = str(pre["code"])
            error = f"preflight refused to run: {pre['code']}"
            exit_code = 3
        elif stop_requested:
            action = "STOPPED"
            error_type = "STOP_REQUESTED"
            error = "graceful STOP requested; no work performed"
            exit_code = 0
        else:
            ledger = dl.DecisionLedger(ledger_root)
            assert manifest is not None  # preflight guarantees a manifest when not blocked
            due = due_work(
                ledger=ledger,
                manifest=manifest,
                now=started_at,
                last_verify=last_verification_time(ops_entries),
            )
            modes = plan_modes(due)
            store = _seed_store(heartbeat, interval_seconds=interval_seconds)
            runner = cycle_fn or campaign.run_cycle
            cycle_result = runner(modes=modes, now=started_at, cycle=int(store["cycle"]), store=store)
            seal = cycle_result.get("seal") or {}
            settle = cycle_result.get("settle") or {}
            sealed = len(seal.get("sealed") or [])
            settled = len(settle.get("settled") or [])
            evaluated = int((cycle_result.get("counters") or {}).get("evaluated_decisions", 0))
            scored = "score" in modes
            verification = str((cycle_result.get("verify") or {}).get("status", "SKIPPED"))
            action = "RUN" if (sealed or settled) else "NOOP"
            failures = [item for item in cycle_result.get("errors") or []]
            blocking = [
                item for item in failures if classify_error(str(item.get("code", ""))) == "BLOCKING"
            ]
            if blocking:
                error_type = str(blocking[0].get("code"))
                error = str(blocking[0].get("detail", ""))
                exit_code = 3
            elif failures:
                error_type = str(failures[0].get("code"))
                error = str(failures[0].get("detail", ""))
                exit_code = 1
    finally:
        lock.release()

    ended_at = now_seconds()
    entry = _record_operation(
        ops_path=ops_path,
        ops_entries=ops_entries,
        campaign_id=cm.CAMPAIGN_ID,
        started_at=started_at,
        ended_at=ended_at,
        commit=commit,
        action=action,
        sealed=sealed,
        settled=settled,
        evaluated=evaluated,
        scored=scored,
        verification=verification,
        exit_code=exit_code,
        error_type=error_type,
        error=error,
        operation_id=operation_id,
        disk=disk,
    )

    first_settlement = write_first_settlement(
        ledger_root=ledger_root, report_root=report_root, now=ended_at
    )

    heartbeat_after = cr.read_heartbeat(ledger_root)
    counters_after: dict[str, Any] = dict((cycle_result or {}).get("counters") or {})
    if not counters_after:
        try:
            counters_after = cs.campaign_counters(dl.DecisionLedger(ledger_root), now=ended_at)
        except Exception:  # pragma: no cover - a broken ledger must still yield a status file
            counters_after = {}
    if cycle_result is not None:
        campaign_status = str(cycle_result.get("campaign_status") or "RUNNING")
    else:
        campaign_status = "BLOCKED" if blocked else "RUNNING"
    health = supervisor_health(
        heartbeat=heartbeat_after,
        now=ended_at,
        interval_seconds=interval_seconds,
        blocked=blocked,
        stop_requested=stop_requested,
        matured_unsettled=int(counters_after.get("matured_unsettled", 0) or 0),
    )

    status_payload = _supervisor_status_payload(
        now=ended_at,
        health=health,
        campaign_status=campaign_status,
        counters=counters_after,
        due=due,
        modes=modes,
        pre=pre,
        heartbeat=heartbeat_after,
        interval_seconds=interval_seconds,
        operations=verify_operations_chain(read_operations(ops_path)),
        last_verification=last_verification_time(read_operations(ops_path)),
        task_state=(scheduler_probe or scheduler_status_safe)(),
        errors=[] if not error else [{"code": error_type, "detail": error}],
        last_run=ended_at,
        last_success=entry["ended_at"] if exit_code == 0 else _as_int((heartbeat or {}).get("last_successful_score")),
        disk=disk,
    )
    cr.write_json_atomic(Path(report_root) / SUPERVISOR_STATUS_FILENAME, status_payload)

    return {
        "acquired": True,
        "supervisor_state": health,
        "campaign_status": campaign_status,
        "action": action,
        "modes": list(modes),
        "due_work": due,
        "sealed": sealed,
        "settled": settled,
        "evaluated": evaluated,
        "verification": verification,
        "exit_code": exit_code,
        "operation": entry,
        "operations_chain": status_payload["operations"],
        "first_settlement": first_settlement,
        "cycle": cycle_result,
        "errors": status_payload["errors"],
    }


def first_settlement_payload(*, ledger_root: Path, now: int) -> dict[str, Any]:
    """The first real settlement artifact (CAP-004B §27)."""
    ledger = dl.DecisionLedger(ledger_root)
    outcomes = ledger.outcomes()
    achievements = {f"{item['decision_id']}|{item['horizon']}": item for item in ledger.evaluations()}
    decisions = {str(item["decision_id"]): item for item in ledger.decisions()}
    performances = ledger.rebuilt_evaluations()
    entries: list[dict[str, Any]] = []
    for outcome in outcomes:
        key = f"{outcome['decision_id']}|{outcome['horizon']}"
        evaluation = achievements.get(key) or {}
        decision = decisions.get(str(outcome["decision_id"])) or {}
        decision_time = _as_int(decision.get("decision_time"))
        entries.append(
            {
                "decision_id": outcome["decision_id"],
                "asset": outcome.get("asset"),
                "horizon": outcome.get("horizon"),
                "decision_time": decision_time,
                "decision_time_utc": utc_iso(decision_time),
                "maturity_time": outcome.get("maturity_time") or outcome.get("exit_close_time"),
                "settlement_time": outcome.get("recorded_at"),
                "snapshot_hash": decision.get("snapshot_hash"),
                "raw_evidence_hash": decision.get("raw_evidence_hash"),
                "outcome_hash": outcome.get("outcome_hash"),
                "evaluation_hash": evaluation.get("evaluation_hash"),
                "analyst_decision": decision.get("decision"),
                "outcome": outcome.get("outcome"),
                "net_return": outcome.get("net_return"),
                "comparisons": outcome.get("comparisons"),
            }
        )
    return {
        "campaign_id": cm.CAMPAIGN_ID,
        "campaign_version": cm.CAMPAIGN_VERSION,
        "ops_version": OPS_VERSION,
        "created_at": int(now),
        "created_at_utc": utc_iso(now),
        "n_settled": len(outcomes),
        "settlements": entries,
        "agent_vs_baselines": asc.alpha_scorecard(performances),
        "net_performance": cs.campaign_metrics(performances),
        "no_trade_counterfactuals": cs.no_trade_analysis(performances),
        "sample_note": (
            "INSUFFICIENT_SAMPLE: this is an early settlement record, not an edge verdict; "
            f"the primary metric stays blocked below {asc.MIN_EVALUABLE_DECISIONS} evaluated decisions"
        ),
        "trades_authorized": 0,
        "alpha_claimed": "NONE",
    }


def write_first_settlement(
    *, ledger_root: Path = LEDGER_ROOT, report_root: Path = REPORT_ROOT, now: int | None = None
) -> dict[str, Any]:
    """Write the first-settlement artifact exactly once, and only once real."""
    moment = now_seconds() if now is None else int(now)
    ledger = dl.DecisionLedger(ledger_root)
    if not ledger.outcomes():
        return {"status": "PENDING", "reason": "no outcomes settled yet"}
    json_path = Path(report_root) / FIRST_SETTLEMENT_JSON
    if json_path.is_file():
        return {"status": "ALREADY_EXISTS", "path": str(json_path)}
    payload = first_settlement_payload(ledger_root=ledger_root, now=moment)
    cr.write_json_atomic(json_path, payload)
    lines = [
        "# FIRST REAL SETTLEMENT",
        "",
        f"- settled decisions: {payload['n_settled']}",
        f"- created: {payload['created_at_utc']}",
        f"- trades authorized: {payload['trades_authorized']}",
        f"- alpha claimed: {payload['alpha_claimed']}",
        "",
        payload["sample_note"],
        "",
        "| decision_id | asset | horizon | analyst | outcome | net | outcome_hash |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in payload["settlements"]:
        lines.append(
            f"| {item['decision_id']} | {item['asset']} | {item['horizon']} | "
            f"{item['analyst_decision']} | {item['outcome']} | {item['net_return']} | "
            f"{item['outcome_hash']} |"
        )
    lines.append("")
    (Path(report_root) / FIRST_SETTLEMENT_MD).write_text("\n".join(lines), encoding="utf-8")
    return {"status": "WRITTEN", "path": str(json_path), "n_settled": payload["n_settled"]}


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _record_operation(
    *,
    ops_path: Path,
    ops_entries: Sequence[Mapping[str, Any]],
    campaign_id: str,
    started_at: int,
    ended_at: int,
    commit: str,
    action: str,
    sealed: int,
    settled: int,
    evaluated: int,
    scored: bool,
    verification: str,
    exit_code: int,
    error_type: str | None,
    error: str | None,
    operation_id: str | None,
    disk: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    entry = operation_entry(
        campaign_id=campaign_id,
        ops_version=OPS_VERSION,
        started_at=started_at,
        ended_at=ended_at,
        host=hostname(),
        pid=os.getpid(),
        code_commit=commit,
        action=action,
        sealed=sealed,
        settled=settled,
        evaluated=evaluated,
        scored=scored,
        verification=verification,
        exit_code=exit_code,
        error_type=error_type,
        error=error,
        previous_hash=last_event_hash(ops_entries),
        operation_id=operation_id,
        disk=disk,
    )
    append_operation(ops_path, entry)
    return entry


def _supervisor_status_payload(
    *,
    now: int,
    health: str,
    campaign_status: str,
    counters: Mapping[str, Any],
    due: Mapping[str, Any],
    modes: Sequence[str],
    pre: Mapping[str, Any],
    heartbeat: Mapping[str, Any] | None,
    interval_seconds: int,
    operations: Mapping[str, Any],
    last_verification: int | None,
    task_state: Mapping[str, Any],
    errors: Sequence[Mapping[str, Any]],
    last_run: int | None,
    last_success: int | None,
    disk: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    maturity_times = [
        int(item["maturity_time"])
        for item in counters.get("decision_states") or []
        if item.get("maturity") != "MATURED"
    ]
    return {
        "supervisor_name": SUPERVISOR_NAME,
        "supervisor_version": SUPERVISOR_VERSION,
        "ops_version": OPS_VERSION,
        "campaign_id": cm.CAMPAIGN_ID,
        "campaign_version": cm.CAMPAIGN_VERSION,
        "experiment_version": cm.CAMPAIGN_VERSION,
        "timestamp": int(now),
        "timestamp_utc": utc_iso(now),
        "supervisor_state": health,
        "campaign_status": campaign_status,
        "steps": {"preflight": pre.get("status"), "modes": list(modes)},
        "due_work": dict(due),
        "interval_seconds": int(interval_seconds),
        "last_run": last_run,
        "last_run_utc": utc_iso(last_run),
        "last_success": last_success,
        "last_success_utc": utc_iso(last_success),
        "last_verification": last_verification,
        "last_verification_utc": utc_iso(last_verification),
        "heartbeat_age_seconds": cr.heartbeat_age_seconds(heartbeat, now=now),
        "heartbeat_fresh": heartbeat_fresh(
            heartbeat=heartbeat, now=now, interval_seconds=interval_seconds
        ),
        "population": {
            key: counters.get(key)
            for key in (
                "sealed_decisions",
                "pending_decisions",
                "matured_decisions",
                "matured_unsettled",
                "settled_outcomes",
                "evaluated_decisions",
                "verified_evaluations",
            )
        },
        "next_decision_slot": cm.next_decision_slot(now),
        "next_maturity": min(maturity_times) if maturity_times else None,
        "next_maturity_utc": utc_iso(min(maturity_times)) if maturity_times else None,
        "chain_status": (pre.get("chain") or {}).get("status"),
        "drift_status": (pre.get("drift") or {}).get("status"),
        "operations": dict(operations),
        "scheduler": dict(task_state),
        "errors": [dict(item) for item in errors],
        "storage": dict(disk) if disk else None,
        "disk_free_bytes": (disk or {}).get("free_bytes"),
        "disk_status": (disk or {}).get("status"),
    }


# --------------------------------------------------------------------------- #
# §8 — independent verification (read-only, runs the shipped verifiers)
# --------------------------------------------------------------------------- #


def run_verifier(name: str, *, timeout: int = 600) -> dict[str, Any]:
    path = VERIFIERS[name]
    if not path.is_file():
        return {"name": name, "status": "NOT_RUN", "reason": "verifier not found"}
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{REPO / 'src'}{os.pathsep}{REPO / 'scripts'}"
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, str(path)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=timeout,
    )
    return {
        "name": name,
        "status": "PASS" if proc.returncode == 0 else "FAIL",
        "exit_code": proc.returncode,
        "stdout_tail": proc.stdout[-800:],
        "stderr_tail": proc.stderr[-800:],
    }


def daily_verification(*, report_root: Path, code_commit: str, operation_id: str | None = None) -> dict[str, Any]:
    """One-a-day double verification, recorded to the operational ledger."""
    ops_path = OPS_LEDGER
    entries = read_operations(ops_path)
    started_at = now_seconds()
    cap003 = run_verifier("cap003")
    cap004 = run_verifier("cap004")
    operations = verify_operations_chain(read_operations(ops_path))
    passed = (
        cap003.get("status") == "PASS"
        and cap004.get("status") == "PASS"
        and operations["status"] == "INTACT"
    )
    entry = _record_operation(
        ops_path=ops_path,
        ops_entries=entries,
        campaign_id=cm.CAMPAIGN_ID,
        started_at=started_at,
        ended_at=now_seconds(),
        commit=code_commit,
        action="VERIFY",
        sealed=0,
        settled=0,
        evaluated=0,
        scored=False,
        verification="PASS" if passed else "FAIL",
        exit_code=0 if passed else 1,
        error_type=None if passed else "VERIFICATION_FAILED",
        error=None if passed else "daily verification did not pass",
        operation_id=operation_id,
    )
    payload = {
        "at": started_at,
        "at_utc": utc_iso(started_at),
        "cap003": cap003,
        "cap004": cap004,
        "operations": operations,
        "passed": passed,
        "operation": entry,
    }
    cr.write_json_atomic(Path(report_root) / "DAILY_VERIFICATION.json", payload)
    return payload


# --------------------------------------------------------------------------- #
# §9 — the OS scheduler (Windows Task Scheduler preferred)
# --------------------------------------------------------------------------- #


def scheduler_type() -> str:
    if os.name == "nt":
        return "windows_task_scheduler"
    if sys.platform.startswith("linux") and shutil.which("systemctl"):
        return "systemd_user"
    return "none"


def python_executable() -> str:
    return sys.executable


def task_command() -> str:
    return python_executable()


def task_arguments() -> str:
    return f'"{SCRIPT}" run'


def task_working_directory() -> str:
    return str(REPO)


def current_user_id() -> str:
    domain = os.environ.get("USERDOMAIN")
    user = os.environ.get("USERNAME") or os.environ.get("USER")
    if domain and user:
        return f"{domain}\\{user}"
    return socket.gethostname() + "\\" + (user or "user")


def build_task_xml(
    *,
    start_boundary: str,
    interval_minutes: int,
    user_id: str,
    command: str,
    arguments: str,
    working_dir: str,
    author: str,
) -> str:
    """A language-independent task definition with the required safety settings."""
    date = dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    return (
        '<?xml version="1.0" encoding="UTF-16"?>\n'
        '<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">\n'
        "  <RegistrationInfo>\n"
        f"    <Date>{date}</Date>\n"
        f"    <Author>{author}</Author>\n"
        f"    <Description>{TASK_DESCRIPTION}</Description>\n"
        "  </RegistrationInfo>\n"
        "  <Triggers>\n"
        "    <TimeTrigger>\n"
        f"      <StartBoundary>{start_boundary}</StartBoundary>\n"
        "      <Enabled>true</Enabled>\n"
        "      <Repetition>\n"
        f"        <Interval>PT{interval_minutes}M</Interval>\n"
        "        <Duration>P3650D</Duration>\n"
        "        <StopAtDurationEnd>false</StopAtDurationEnd>\n"
        "      </Repetition>\n"
        "    </TimeTrigger>\n"
        "  </Triggers>\n"
        "  <Principals>\n"
        '    <Principal id="Author">\n'
        f"      <UserId>{user_id}</UserId>\n"
        "      <LogonType>InteractiveToken</LogonType>\n"
        "      <RunLevel>LeastPrivilege</RunLevel>\n"
        "    </Principal>\n"
        "  </Principals>\n"
        "  <Settings>\n"
        "    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>\n"
        "    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>\n"
        "    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>\n"
        "    <AllowHardTerminate>true</AllowHardTerminate>\n"
        "    <StartWhenAvailable>true</StartWhenAvailable>\n"
        "    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>\n"
        "    <AllowStartOnDemand>true</AllowStartOnDemand>\n"
        "    <Enabled>true</Enabled>\n"
        "    <Hidden>false</Hidden>\n"
        "    <WakeToRun>false</WakeToRun>\n"
        "    <ExecutionTimeLimit>PT1H</ExecutionTimeLimit>\n"
        "    <Priority>7</Priority>\n"
        "    <RestartOnFailure>\n"
        "      <Interval>PT5M</Interval>\n"
        "      <Count>3</Count>\n"
        "    </RestartOnFailure>\n"
        "  </Settings>\n"
        '  <Actions Context="Author">\n'
        "    <Exec>\n"
        f"      <Command>{command}</Command>\n"
        f"      <Arguments>{arguments}</Arguments>\n"
        f"      <WorkingDirectory>{working_dir}</WorkingDirectory>\n"
        "    </Exec>\n"
        "  </Actions>\n"
        "</Task>\n"
    )


def _run(args: Sequence[str], *, timeout: int = 60) -> dict[str, Any]:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, check=False, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:  # pragma: no cover - platform dependent
        return {"ok": False, "returncode": None, "stdout": "", "stderr": repr(exc)}
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def _schtasks(args: Sequence[str], *, timeout: int = 60) -> dict[str, Any]:
    return _run(["schtasks", *args], timeout=timeout)


def _powershell(script: str, *, timeout: int = 60) -> dict[str, Any]:
    exe = shutil.which("powershell") or "powershell"
    return _run([exe, "-NoProfile", "-NonInteractive", "-Command", script], timeout=timeout)


def scheduler_status_safe() -> dict[str, Any]:
    """Best-effort scheduler snapshot; never raises, so a cycle is never lost."""
    try:
        return scheduler_status()
    except Exception as exc:  # pragma: no cover - defensive
        return {"installed": None, "enabled": None, "error": repr(exc)}


def scheduler_status(*, task_name: str = TASK_NAME) -> dict[str, Any]:
    """Query the registered task without assuming a language."""
    kind = scheduler_type()
    if kind != "windows_task_scheduler":
        return {"scheduler_type": kind, "installed": False, "enabled": False}
    xml = _schtasks(["/query", "/tn", task_name, "/xml", "ONE"])
    if not xml["ok"]:
        return {
            "scheduler_type": kind,
            "task_name": task_name,
            "installed": False,
            "enabled": False,
            "query_stderr": xml["stderr"].strip(),
        }
    script = (
        f"$t = Get-ScheduledTask -TaskName '{task_name}' -ErrorAction SilentlyContinue; "
        "if ($null -eq $t) { '{}' } else { "
        "$i = Get-ScheduledTaskInfo -TaskName '" + task_name + "'; "
        "$a = $t.Actions | Select-Object -First 1; "
        "[pscustomobject]@{ TaskName=$t.TaskName; State=[string]$t.State; "
        "MultipleInstances=[string]$t.Settings.MultipleInstances; "
        "StartWhenAvailable=[string]$t.Settings.StartWhenAvailable; "
        "Execute=$a.Execute; Arguments=$a.Arguments; WorkingDirectory=$a.WorkingDirectory; "
        "LastRunTime=[string]$i.LastRunTime; LastTaskResult=$i.LastTaskResult; "
        "NextRunTime=[string]$i.NextRunTime; NumberOfMissedRuns=$i.NumberOfMissedRuns } "
        "| ConvertTo-Json -Compress }"
    )
    ps = _powershell(script)
    data: dict[str, Any] = {}
    if ps["ok"] and ps["stdout"].strip() not in ("", "{}"):
        try:
            loaded = json.loads(ps["stdout"].strip())
            if isinstance(loaded, dict):
                data = loaded
        except json.JSONDecodeError:
            data = {}
    state = str(data.get("State", ""))
    return {
        "scheduler_type": kind,
        "task_name": task_name,
        "installed": bool(data),
        "enabled": state not in ("", "Disabled"),
        "state": state or None,
        "multiple_instances": data.get("MultipleInstances"),
        "start_when_available": data.get("StartWhenAvailable"),
        "command": data.get("Execute"),
        "arguments": data.get("Arguments"),
        "working_directory": data.get("WorkingDirectory"),
        "last_run_time": data.get("LastRunTime"),
        "last_task_result": data.get("LastTaskResult"),
        "next_run_time": data.get("NextRunTime"),
        "missed_runs": data.get("NumberOfMissedRuns"),
    }


def install_scheduler(
    *,
    interval_minutes: int = DEFAULT_INTERVAL_SECONDS // 60,
    user_id: str | None = None,
    journal_path: Path | None = None,
    ops_path: Path = OPS_LEDGER,
    operation_id: str | None = None,
    task_name: str = TASK_NAME,
    arguments: str | None = None,
    register_in_ledger: bool = True,
) -> dict[str, Any]:
    """Register (idempotently) the scheduled task that keeps the campaign alive."""
    kind = scheduler_type()
    if kind != "windows_task_scheduler":
        return {"status": "UNSUPPORTED_SCHEDULER", "scheduler_type": kind}
    before = scheduler_status(task_name=task_name)
    start = (dt.datetime.now() + dt.timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%S")
    xml = build_task_xml(
        start_boundary=start,
        interval_minutes=interval_minutes,
        user_id=user_id or current_user_id(),
        command=task_command(),
        arguments=arguments if arguments is not None else task_arguments(),
        working_dir=task_working_directory(),
        author=current_user_id(),
    )
    with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-16") as handle:
        handle.write(xml)
        temp_path = Path(handle.name)
    try:
        created = _schtasks(["/create", "/tn", task_name, "/xml", str(temp_path), "/f"])
    finally:
        temp_path.unlink(missing_ok=True)
    after = scheduler_status(task_name=task_name)
    if not created["ok"] or not after.get("installed"):
        return {
            "status": "INSTALL_FAILED",
            "scheduler_type": kind,
            "returncode": created["returncode"],
            "stderr": created["stderr"].strip(),
            "stdout": created["stdout"].strip(),
        }
    status = "UPDATED" if before.get("installed") else "INSTALLED"
    if register_in_ledger:
        _journal_scheduler_event(
            report_root=journal_path or REPORT_ROOT,
            ops_path=ops_path,
            action="INSTALL",
            status=status,
            interval_minutes=interval_minutes,
            task_state=after,
            operation_id=operation_id,
        )
    return {"status": status, "scheduler_type": kind, "task_name": task_name, "task": after, "xml": xml}


def enable_scheduler(*, enabled: bool, task_name: str = TASK_NAME) -> dict[str, Any]:
    flag = "/enable" if enabled else "/disable"
    proc = _schtasks(["/change", "/tn", task_name, flag])
    return {"status": "OK" if proc["ok"] else "FAILED", "enabled": enabled, "output": proc["stdout"].strip()}


def uninstall_scheduler(*, task_name: str = TASK_NAME) -> dict[str, Any]:
    proc = _schtasks(["/delete", "/tn", task_name, "/f"])
    return {"status": "OK" if proc["ok"] else "FAILED", "output": proc["stdout"].strip()}


def run_task_now(*, task_name: str = TASK_NAME) -> dict[str, Any]:
    proc = _schtasks(["/run", "/tn", task_name])
    return {"status": "OK" if proc["ok"] else "FAILED", "output": proc["stdout"].strip(), "stderr": proc["stderr"].strip()}


def probe_market_data(*, report_root: Path = REPORT_ROOT, now: int | None = None) -> dict[str, Any]:
    """Fetch one real candle through the provider, from this execution context.

    Used to prove the *scheduled* context (not an interactive shell) can reach the
    market-data provider and the filesystem before autonomy is declared.
    """
    moment = now_seconds() if now is None else int(now)
    payload: dict[str, Any] = {
        "at": moment,
        "at_utc": utc_iso(moment),
        "provider": rmc.PROVIDER,
        "source_type": rmc.REAL_SOURCE_TYPE,
        "asset": "BINANCE:BTCUSDT",
        "interval": "4h",
        "python": sys.executable,
        "hostname": hostname(),
        "cwd": str(Path.cwd()),
        "env_keys": sorted(
            key
            for key in os.environ
            if key.startswith(("PYTHON", "CCXT", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"))
        ),
    }
    try:
        connector = rmc.make_connector()
        rows = rmc.fetch_provider_ohlcv(connector, "BINANCE:BTCUSDT", "4h")
        payload["ok"] = True
        payload["n_bars"] = len(rows)
        payload["last_bar_open_time"] = (
            int(rows[-1].timestamp // 1000) if rows else None
        )
        payload["last_bar_open_time_utc"] = (
            utc_iso(int(rows[-1].timestamp // 1000)) if rows else None
        )
        payload["last_bar_close"] = float(rows[-1].close) if rows else None
    except Exception as exc:  # the probe reports a failure instead of hiding it
        payload["ok"] = False
        payload["error"] = repr(exc)
    cr.write_json_atomic(Path(report_root) / PROBE_REPORT_FILENAME, payload)
    return payload


def _journal_scheduler_event(
    *,
    report_root: Path,
    ops_path: Path = OPS_LEDGER,
    action: str,
    status: str,
    interval_minutes: int,
    task_state: Mapping[str, Any],
    operation_id: str | None,
) -> None:
    started_at = now_seconds()
    entries = read_operations(ops_path)
    _record_operation(
        ops_path=ops_path,
        ops_entries=entries,
        campaign_id=cm.CAMPAIGN_ID,
        started_at=started_at,
        ended_at=now_seconds(),
        commit=git_commit(),
        action=action,
        sealed=0,
        settled=0,
        evaluated=0,
        scored=False,
        verification="SKIPPED",
        exit_code=0,
        error_type=None,
        error=None,
        operation_id=operation_id,
    )
    cr.write_json_atomic(
        Path(report_root) / f"SCHEDULER_{action}.json",
        {
            "at": started_at,
            "at_utc": utc_iso(started_at),
            "action": action,
            "status": status,
            "interval_minutes": interval_minutes,
            "task": dict(task_state),
            "scheduler_type": scheduler_type(),
            "task_name": TASK_NAME,
        },
    )


# --------------------------------------------------------------------------- #
# §10 — status
# --------------------------------------------------------------------------- #


def verifier_summary(path: Path) -> str:
    """``PASS 192/192`` / ``FAIL`` / ``NOT_RUN`` read from a verification report."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "NOT_RUN"
    return f"{payload.get('status')} {payload.get('passed')}/{payload.get('total')}"


def status_report(*, now: int) -> dict[str, Any]:
    ledger = dl.DecisionLedger(LEDGER_ROOT)
    if not LEDGER_ROOT.is_dir():
        return {"supervisor_state": "STOPPED", "reason": "ledger root not found"}
    manifest = _load_manifest(LEDGER_ROOT)
    heartbeat = cr.read_heartbeat(LEDGER_ROOT)
    lock = cl.CampaignLock(LEDGER_ROOT, campaign_id=cm.CAMPAIGN_ID)
    counters = cs.campaign_counters(ledger, now=now)
    chain = ledger.verify_chain()
    drift = cm.detect_drift(manifest) if manifest else {"status": "NO_MANIFEST"}
    health = supervisor_health(
        heartbeat=heartbeat,
        now=now,
        interval_seconds=DEFAULT_INTERVAL_SECONDS,
        blocked=chain["status"] != "INTACT" or drift["status"] != "NO_DRIFT",
        stop_requested=lock.stop_requested(),
        matured_unsettled=int(counters.get("matured_unsettled", 0)),
    )
    return {
        "supervisor_state": health,
        "campaign_id": cm.CAMPAIGN_ID,
        "campaign_version": cm.CAMPAIGN_VERSION,
        "ops_version": OPS_VERSION,
        "scheduler": scheduler_status_safe(),
        "heartbeat_age_seconds": cr.heartbeat_age_seconds(heartbeat, now=now),
        "campaign_status": cs.campaign_status_name(
            counters=counters, chain_verified=chain["status"] == "INTACT", drift=drift
        ),
        "population": {
            key: counters.get(key)
            for key in (
                "sealed_decisions",
                "pending_decisions",
                "matured_decisions",
                "matured_unsettled",
                "settled_outcomes",
                "evaluated_decisions",
                "verified_evaluations",
            )
        },
        "directions": {
            "LONG": counters.get("long_count"),
            "SHORT": counters.get("short_count"),
            "NO_TRADE": counters.get("no_trade_count"),
        },
        "next_decision_slot": cm.next_decision_slot(now),
        "next_decision_slot_utc": utc_iso(cm.next_decision_slot(now)),
        "chain_status": chain["status"],
        "drift_status": drift["status"],
        "stop_requested": lock.stop_requested(),
        "operations": verify_operations_chain(read_operations(OPS_LEDGER)),
        "verifiers": {
            "cap003": verifier_summary(
                REPO / "reports" / "agentic-campaign-cap003" / "CAP003_VERIFICATION.json"
            ),
            "cap004": verifier_summary(CAMPAIGN_REPORT_ROOT / "CAP004_VERIFICATION.json"),
            "cap004b": verifier_summary(REPORT_ROOT / "CAP004B_VERIFICATION.json"),
        },
    }


def _render_status(report: Mapping[str, Any]) -> str:
    scheduler = report.get("scheduler") or {}
    population = report.get("population") or {}
    lines = [
        "# CAP-004B supervisor status",
        "",
        f"- supervisor state: **{report.get('supervisor_state')}**",
        f"- campaign: {report.get('campaign_id')} v{report.get('campaign_version')}"
        f" (ops {report.get('ops_version')})",
        f"- campaign status: {report.get('campaign_status')}",
        f"- chain: {report.get('chain_status')}   drift: {report.get('drift_status')}",
        f"- heartbeat age: {report.get('heartbeat_age_seconds')}s",
        f"- next decision slot: {report.get('next_decision_slot_utc')}",
        f"- stop requested: {report.get('stop_requested')}",
        "",
        "## Scheduler",
        "",
        f"- type: {scheduler.get('scheduler_type')}",
        f"- task: {scheduler.get('task_name')}",
        f"- installed: {scheduler.get('installed')}   enabled: {scheduler.get('enabled')}",
        f"- state: {scheduler.get('state')}",
        f"- last run: {scheduler.get('last_run_time')}   result: {scheduler.get('last_task_result')}",
        f"- next run: {scheduler.get('next_run_time')}",
        f"- command: {scheduler.get('command')} {scheduler.get('arguments')}",
        "",
        "## Population",
        "",
        "| population | count |",
        "| --- | --- |",
    ]
    for key, value in population.items():
        lines.append(f"| {key} | {value} |")
    operations = report.get("operations") or {}
    verifiers = report.get("verifiers") or {}
    lines.extend(
        [
            "",
            f"- operations ledger: {operations.get('status')} ({operations.get('events')} events)",
            f"- verifiers: cap003={verifiers.get('cap003')} cap004={verifiers.get('cap004')} "
            f"cap004b={verifiers.get('cap004b')}",
            "",
        ]
    )
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# §11 — CLI
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CAP-004B persistent campaign supervisor")
    parser.add_argument(
        "command",
        choices=(
            "run",
            "status",
            "install",
            "uninstall",
            "start",
            "stop",
            "run-now",
            "verify",
            "probe",
        ),
    )
    parser.add_argument("--interval-seconds", type=int, default=DEFAULT_INTERVAL_SECONDS)
    parser.add_argument("--task-name", default=TASK_NAME)
    parser.add_argument(
        "--probe", action="store_true", help="operate on the market-data probe task"
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    logger = configure_logging()
    now = now_seconds()

    if args.command == "run":
        result = run_supervised_cycle(now=now, interval_seconds=args.interval_seconds)
        logger.info(
            "cycle state=%s action=%s modes=%s sealed=%d settled=%d verify=%s exit=%d",
            result["supervisor_state"],
            result["action"],
            ",".join(result["modes"]),
            result["sealed"],
            result["settled"],
            result["verification"],
            result["exit_code"],
        )
        if args.json:
            print(canonical_json(result))
        return int(result["exit_code"])

    if args.command == "status":
        report = status_report(now=now)
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
        else:
            print(_render_status(report))
        return 0

    if args.command == "probe":
        result = probe_market_data()
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return 0 if result.get("ok") else 1

    if args.command == "install":
        task_name = PROBE_TASK_NAME if args.probe else args.task_name
        arguments = f'"{SCRIPT}" probe' if args.probe else None
        result = install_scheduler(
            interval_minutes=max(1, args.interval_seconds // 60),
            task_name=task_name,
            arguments=arguments,
            register_in_ledger=not args.probe,
        )
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return 0 if result["status"] in ("INSTALLED", "UPDATED") else 1

    if args.command == "uninstall":
        task_name = PROBE_TASK_NAME if args.probe else args.task_name
        result = uninstall_scheduler(task_name=task_name)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result["status"] == "OK" else 1

    if args.command in ("start", "stop"):
        enable = args.command == "start"
        lock = cl.CampaignLock(LEDGER_ROOT, campaign_id=cm.CAMPAIGN_ID)
        if enable:
            lock.clear_stop()
        else:
            lock.request_stop(reason="supervisor stop command")
        result = enable_scheduler(enabled=enable, task_name=args.task_name)
        result["stop_flag"] = not enable
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result["status"] == "OK" else 1

    if args.command == "run-now":
        task_name = PROBE_TASK_NAME if args.probe else args.task_name
        result = run_task_now(task_name=task_name)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result["status"] == "OK" else 1

    if args.command == "verify":
        result = daily_verification(report_root=REPORT_ROOT, code_commit=git_commit())
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False, default=str))
        return 0 if result["passed"] else 1

    return 2  # pragma: no cover - argparse rejects unknown commands first


if __name__ == "__main__":
    raise SystemExit(main())
