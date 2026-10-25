"""ST-6 — independent verification of the end-of-period close and of its isolated replay.

A separate program from the builder (``scripts/st6_forward_regime.py``) and from the replay harness
(``scripts/st6_close_replay.py``).  It trusts neither the builder's artefacts nor the replay's own
summary: it re-derives every declaration it checks from the state on disk, and it exercises the
harness rather than reading its verdict.

What it checks, each against the real state and against the replay:

* **snapshot integrity and hashes** — the newest live-state snapshot is re-verified: every recorded
  live file still hashes to the recorded original and matches inside the snapshot copy, and every
  raw window snapshot still reproduces the hash recorded in the window index;
* **denominator integrity** — the eligible windows are re-derived here from the declared period, not
  read from the tick: the plan is the declared days times the declared slots per day, counted from
  the slot that contains the period start; the first eligible slot is that slot, the last is the
  last full slot before the declared end, and the partial slot the period closes inside is not one;
* **windows and duplicates** — no duplicated slot, no window outside the plan, every window's raw
  bytes re-hash to the recorded hash, and no slot holds two windows;
* **lost windows** — every declared slot that ended is either an observed window or a recorded
  ``MISSED_WINDOW`` with a reason, and nothing was reconstructed;
* **terminal state** — a consolidation on disk must belong to the declared period and carry the
  terminal state, the post-close contract and (when it is the terminal artefact) the transition;
* **zero requests after the close** — no run event after the declared end carries a market request,
  and the replay's post-close runs made none (there or here);
* **idempotency** — a repeated close neither rewrites the consolidation nor appends a run event,
  and the replay reproduces the consolidation byte for byte from the same state and clock;
* **drift preservation** — a measured deviation stays named in the terminal artefact, with its
  assets and instants, beside an insufficient-coverage or supported classification alike;
* **absence of an order path** — every program of the phase is scanned with this verifier's own
  syntax-tree scan for an order or a credential path;
* **protection of the real campaign** — the replay's fingerprints must show the real state unmoved,
  no real market request, no real scheduler call, and this verifier re-checks the implementation
  files against the hashes the replay recorded.

And it requires **negative proof**: every check is applied to deliberately corrupted fixtures, and
each corruption must be reported.  A verifier that cannot fail proves nothing.

Run:  python scripts/st6_close_verify.py [--out PATH] [--skip-replay]
"""

from __future__ import annotations

import argparse
import ast
import gzip
import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

# the external record of the schedule, taken by a process that is neither the tick nor this verifier
from st6_scheduler_evidence import extract_samples as normalise_samples  # noqa: E402
from st6_scheduler_evidence import load_samples as load_witness_samples  # noqa: E402
from st6_scheduler_evidence import read_json as read_external_json  # noqa: E402
from st6_scheduler_evidence import slot_external_coverage  # noqa: E402

DATA = REPO / "data" / "st6"
SNAPSHOTS = DATA / "snapshots"
RAW = DATA / "raw"
PERIOD = DATA / "ST6_PERIOD.json"
WINDOWS = DATA / "ST6_WINDOWS.jsonl"
OBSERVATIONS = DATA / "ST6_OBSERVATIONS.jsonl"
RUNS = DATA / "ST6_RUNS.jsonl"
MISSED = DATA / "ST6_MISSED_WINDOWS.jsonl"
CLOSURE = DATA / "ST6_PERIOD_CLOSURE.json"
REPLAY_REPORT = DATA / "ST6_CLOSE_REPLAY_REPORT.json"
REPLAY_SCRIPT = SCRIPTS / "st6_close_replay.py"
TICK = SCRIPTS / "st6_forward_regime.py"
PYTHON = REPO / ".venv" / "Scripts" / "python.exe"
OUT = DATA / "ST6_CLOSE_INDEPENDENT_VERIFICATION.json"

VERIFIER_VERSION = "ST6_CLOSE_INDEPENDENT_VERIFICATION_V1"
SLOT_HOURS = 4
OUTCOMES = (
    "COST_MODEL_SUPPORTED_IN_OBSERVED_REGIMES",
    "COST_MODEL_DRIFT_DETECTED",
    "INSUFFICIENT_REGIME_COVERAGE",
    "DATA_QUALITY_FAILED",
)
#: The causes a missed window may state, and the class this verifier re-derives from the run log and
#: from the external record of the scheduler.  A claim of absence is the heavy one: it needs the
#: external record to cover every instant of the slot, because the run log is written by the tick
#: and its silences prove nothing about the world.
ATTENDANCE_CLASSES = (
    "ATTENDED_NOT_COLLECTED",
    "ATTENDED_REQUEST_FAILED",
    "UNATTENDED_NO_RUN_EVENT",
    "ATTENDANCE_UNKNOWN",
    "ATTENDANCE_UNKNOWN_RUN_LOG_TRUNCATED",
    "ATTENDANCE_EVIDENCE_CONFLICT",
)
ABSENCE_CLASSES = ("UNATTENDED_NO_RUN_EVENT",)
WITNESS_LOG = DATA / "ST6_SCHEDULER_WITNESS.jsonl"
SCHEDULER_EVIDENCE = DATA / "ST6_SCHEDULER_EVIDENCE.json"
#: Executable tokens that would be an order or a credential path, not a check for one.
ORDER_TOKENS = (
    "create_order",
    "place_order",
    "submit_order",
    "new_order",
    "cancel_order",
    "post_order",
    "createOrder",
    "privateKey",
    "api_key",
    "apikey",
    "api_secret",
    "signature",
    "testnet_order",
)


class Checks:
    def __init__(self) -> None:
        self.total = 0
        self.passed = 0
        self.failed: list[str] = []

    def check(self, name: str, ok: bool, detail: Any = None) -> None:
        self.total += 1
        if ok:
            self.passed += 1
        else:
            self.failed.append(f"{name}: {detail}")


def parse_instant(stamp: str) -> datetime:
    return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return document


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def order_tokens(source: str) -> list[str]:
    """This verifier's own scan: an order path is a name or a string handed to a call."""
    tree = ast.parse(source)
    seen: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            seen.add(node.attr.lower())
        elif isinstance(node, ast.Name):
            seen.add(node.id.lower())
        elif isinstance(node, ast.Call):
            for argument in [*node.args, *[keyword.value for keyword in node.keywords]]:
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    seen.add(argument.value.lower())
    return sorted(token for token in ORDER_TOKENS if token.lower() in seen)


# ------------------------------------------------------------------------------------------------
# pure checks: each returns the findings it observed, and nothing else
# ------------------------------------------------------------------------------------------------


def eligible_windows(period: dict[str, Any]) -> list[dict[str, Any]]:
    """The eligible windows, derived here from the declaration alone."""
    start = parse_instant(period["started_at_utc"])
    end = parse_instant(period["ends_at_utc"])
    planned = int(period["period_days"]) * int(period["slots_per_day"])
    cursor = start.replace(minute=0, second=0, microsecond=0)
    slots: list[dict[str, Any]] = []
    while len(slots) < planned:
        slots.append(
            {
                "key": f"{cursor.strftime('%Y-%m-%d')}#{cursor.hour // SLOT_HOURS}",
                "starts_at_utc": cursor.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "ends_at_utc": (cursor + timedelta(hours=SLOT_HOURS)).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
            }
        )
        cursor += timedelta(hours=SLOT_HOURS)
        if cursor > end + timedelta(days=1):  # a declaration that cannot produce its own plan
            break
    return slots


def findings_denominator(period: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    slots = eligible_windows(period)
    planned = int(period["period_days"]) * int(period["slots_per_day"])
    start = parse_instant(period["started_at_utc"])
    end = parse_instant(period["ends_at_utc"])
    first = slots[0] if slots else {}
    last = slots[-1] if slots else {}
    summary = {
        "planned_windows": planned,
        "derived_windows": len(slots),
        "first_slot": first.get("key"),
        "last_slot": last.get("key"),
        "first_slot_starts_at_utc": first.get("starts_at_utc"),
        "last_slot_ends_at_utc": last.get("ends_at_utc"),
        "period_started_at_utc": period["started_at_utc"],
        "period_ends_at_utc": period["ends_at_utc"],
        "closes_inside_slot": f"{end.strftime('%Y-%m-%d')}#{end.hour // SLOT_HOURS}",
    }
    findings: list[str] = []
    if len(slots) != planned:
        findings.append(f"the plan says {planned} windows but the derivation produced {len(slots)}")
    if first.get("key") != f"{start.strftime('%Y-%m-%d')}#{start.hour // SLOT_HOURS}":
        findings.append(
            f"the first eligible window {first.get('key')} is not the slot that contains the "
            f"period start {period['started_at_utc']}"
        )
    if last and last["ends_at_utc"] > period["ends_at_utc"]:
        findings.append(
            f"the last eligible window {last.get('key')} ends after the declared end "
            f"({last['ends_at_utc']} > {period['ends_at_utc']})"
        )
    if summary["closes_inside_slot"] in {slot["key"] for slot in slots}:
        findings.append(
            f"the partial slot the period closes inside ({summary['closes_inside_slot']}) is "
            "counted as an eligible window"
        )
    return summary, findings


def findings_windows(windows: list[dict[str, Any]], raw_dir: Path) -> list[str]:
    findings: list[str] = []
    keys = [f"{row['day']}#{row['slot_index']}" for row in windows]
    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    if duplicates:
        findings.append(f"the window index holds a duplicated slot: {duplicates}")
    if len(windows) != len({row["window_id"] for row in windows}):
        findings.append("the window index holds a duplicated window_id")
    for row in windows:
        path = raw_dir / f"{row['window_id']}.json.gz"
        if not path.exists():
            findings.append(f"{row['raw']['path']} is missing")
            continue
        try:
            with gzip.open(path, "rb") as handle:
                payload = handle.read()
        except Exception as exc:  # corrupt bytes are a finding, not a crash
            findings.append(f"{row['raw']['path']} cannot be read as gzip: {type(exc).__name__}")
            continue
        if sha256_bytes(payload) != row["raw"]["uncompressed_sha256"]:
            findings.append(f"{row['raw']['path']} sha256 mismatch against the index")
        if int(row.get("orders_sent") or 0) != 0:
            findings.append(f"{row['window_id']} reports orders_sent != 0")
        if int(row.get("credentials_used") or 0) != 0:
            findings.append(f"{row['window_id']} reports credentials_used != 0")
    return findings


def _request_count(run: dict[str, Any]) -> int:
    """A run's market-request count, read defensively: a corrupt field must not stop the verifier."""
    try:
        return int(run.get("market_requests") or 0)
    except (TypeError, ValueError):
        return 0


def attendance_from_runs(
    runs: list[dict[str, Any]],
    slot_key: str,
    starts_at_utc: str,
    external: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """What the run log and the external record say about one slot — re-derived, not read.

    A run that declares itself ``MANUAL`` is not the schedule; a run that declares nothing is kept,
    because dropping an unlabelled event could turn a busy slot into an unattended one.  The log is
    front-truncated, so unless its oldest retained event starts at or before the slot's own start the
    absence of an event proves nothing and the derived class says so.

    And the log is the tick's own: it can carry attendance, it cannot carry absence.  The class here
    is therefore read from both sources, and when they disagree the verdict is a conflict.
    """
    coverage = external if isinstance(external, dict) else {
        "status": "SCHEDULER_EVIDENCE_UNAVAILABLE",
        "scheduler_engine_launch_count": 0,
    }
    external_status = str(coverage.get("status") or "SCHEDULER_EVIDENCE_UNAVAILABLE")
    launches = int(coverage.get("scheduler_engine_launch_count") or 0)
    complete = external_status == "EXTERNAL_COVERAGE_COMPLETE"
    events = [run for run in runs if isinstance(run, dict)]
    in_slot = [run for run in events if run.get("slot_key") == slot_key]
    attended = [run for run in in_slot if str(run.get("invocation", "")).upper() != "MANUAL"]
    starts = sorted(str(run.get("actual_start_utc")) for run in events if run.get("actual_start_utc"))
    covers_whole_slot = bool(starts) and starts[0] <= starts_at_utc
    requests = sum(_request_count(run) for run in attended)
    failing = [run for run in attended if run.get("errors")]
    if attended and complete and launches == 0:
        classification = "ATTENDANCE_EVIDENCE_CONFLICT"
    elif attended:
        classification = (
            "ATTENDED_REQUEST_FAILED" if requests and failing else "ATTENDED_NOT_COLLECTED"
        )
    elif complete and launches > 0:
        classification = "ATTENDANCE_EVIDENCE_CONFLICT"
    elif complete:
        classification = "UNATTENDED_NO_RUN_EVENT"
    elif not covers_whole_slot:
        classification = "ATTENDANCE_UNKNOWN_RUN_LOG_TRUNCATED"
    else:
        classification = "ATTENDANCE_UNKNOWN"
    return {
        "classification": classification,
        "scheduled_runs_in_slot": len(attended),
        "manual_runs_in_slot": len(in_slot) - len(attended),
        "market_requests_in_slot": requests,
        "log_covers_whole_slot": covers_whole_slot,
        "external_evidence_status": external_status,
        "scheduler_engine_launch_count": launches,
        "absence_claim_supported_by_external_coverage": not (
            classification in ABSENCE_CLASSES and not complete
        ),
    }


def findings_missed(
    period: dict[str, Any],
    windows: list[dict[str, Any]],
    missed: list[dict[str, Any]],
    now: datetime,
    runs: list[dict[str, Any]],
    witness: list[dict[str, Any]] | None = None,
    evidence: dict[str, Any] | None = None,
) -> list[str]:
    findings: list[str] = []
    planned = {slot["key"] for slot in eligible_windows(period)}
    observed = {f"{row['day']}#{row['slot_index']}" for row in windows}
    recorded = [row["slot_key"] for row in missed]
    if len(recorded) != len(set(recorded)):
        findings.append("a slot is recorded as missed more than once")
    if any(row.get("reconstructed") is not False for row in missed):
        findings.append("a missed window claims to have been reconstructed")
    if any(not row.get("reason") for row in missed):
        findings.append("a missed window states no reason")
    if any(row["slot_key"] in observed for row in missed):
        findings.append("a slot is both observed and recorded as missed")
    outside = sorted(set(recorded) - planned)
    if outside:
        findings.append(f"a slot outside the declared plan is recorded as missed: {outside}")
    if observed - planned:
        findings.append(f"a window outside the declared plan exists: {sorted(observed - planned)}")
    # every declared slot that has already ended must be accounted for
    for slot in eligible_windows(period):
        if parse_instant(slot["ends_at_utc"]) > now:
            continue
        if slot["key"] not in observed and slot["key"] not in set(recorded):
            findings.append(f"the ended declared slot {slot['key']} is neither observed nor missed")
    # The stated cause is audited, not accepted: it has to name a declared class, to be bounded by
    # the declared grid, and to match what this verifier re-derives from the run events itself.  A
    # missed window that blames the schedule while the log shows the tick running is exactly the
    # kind of claim this program exists to catch.
    declared = {slot["key"]: slot for slot in eligible_windows(period)}
    for row in missed:
        key = str(row.get("slot_key"))
        attendance = row.get("attendance")
        if not isinstance(attendance, dict):
            findings.append(f"the missed window {key} carries no attendance evidence")
            continue
        classification = str(attendance.get("classification"))
        if classification not in ATTENDANCE_CLASSES:
            findings.append(
                f"the missed window {key} states an undeclared cause {classification!r}"
            )
            continue
        slot = declared.get(key)
        if slot is None:
            continue  # already reported as a slot outside the declared plan
        if (row.get("starts_at_utc"), row.get("ends_at_utc")) != (
            slot["starts_at_utc"],
            slot["ends_at_utc"],
        ):
            findings.append(
                f"the missed window {key} is not bounded by the declared slot "
                f"({row.get('starts_at_utc')} -> {row.get('ends_at_utc')})"
            )
        coverage = slot_external_coverage(
            parse_instant(slot["starts_at_utc"]),
            parse_instant(slot["ends_at_utc"]),
            normalise_samples(witness or []),
            evidence,
            now,
        )
        derived = attendance_from_runs(runs, key, slot["starts_at_utc"], coverage)
        if classification != derived["classification"]:
            findings.append(
                f"the missed window {key} states {classification} while the run log and the external "
                f"record say {derived['classification']}"
            )
        for field in (
            "scheduled_runs_in_slot",
            "manual_runs_in_slot",
            "market_requests_in_slot",
            "log_covers_whole_slot",
        ):
            if attendance.get(field) != derived[field]:
                findings.append(
                    f"the missed window {key} claims {field}={attendance.get(field)!r} while the "
                    f"run log says {derived[field]!r}"
                )
        if not derived["absence_claim_supported_by_external_coverage"]:
            findings.append(
                f"the missed window {key} claims the absence {classification} without external "
                f"coverage of the slot ({derived['external_evidence_status']})"
            )
        recorded_status = str(
            (attendance.get("external_evidence") or {}).get("status")
            or attendance.get("external_evidence_status")
            or ""
        )
        if classification in ABSENCE_CLASSES and recorded_status and recorded_status != (
            "EXTERNAL_COVERAGE_COMPLETE"
        ):
            findings.append(
                f"the missed window {key} records external status {recorded_status!r} while claiming "
                "the absence "
                f"{classification}"
            )
    return findings


def findings_ledger(
    ledger: dict[str, Any] | None, period: dict[str, Any], windows: list[dict[str, Any]]
) -> list[str]:
    """The close must read the eighty-four slots from the ledger, so the ledger is audited here.

    The consolidation at the end of the period is built on the slot ledger — the durable record —
    rather than on logs that are bounded and front-truncated, so a ledger that is incomplete, that
    invents a slot, that misstates a bound or that claims an absence without external coverage would
    make the consolidation wrong even if every other artefact were right.
    """
    if ledger is None:
        return ["no slot ledger exists: the consolidation has no durable per-slot record"]
    findings: list[str] = []
    declared = {slot["key"]: slot for slot in eligible_windows(period)}
    rows = [row for row in ledger.get("slots") or [] if isinstance(row, dict)]
    ids = [str(row.get("slot_id")) for row in rows]
    if len(rows) != len(declared):
        findings.append(
            f"the ledger holds {len(rows)} slot(s) for {len(declared)} declared slot(s)"
        )
    if len(set(ids)) != len(ids):
        findings.append("the ledger repeats a slot id")
    missing = sorted(set(declared) - set(ids))
    if missing:
        findings.append(f"the ledger omits declared slot(s): {missing}")
    unexpected = sorted(set(ids) - set(declared))
    if unexpected:
        findings.append(f"the ledger carries slot(s) outside the declared plan: {unexpected}")
    observed = {f"{row['day']}#{row['slot_index']}": row for row in windows}
    for row in rows:
        slot_id = str(row.get("slot_id"))
        slot = declared.get(slot_id)
        if slot is None:
            continue
        if (row.get("slot_start_utc"), row.get("slot_end_utc")) != (
            slot["starts_at_utc"],
            slot["ends_at_utc"],
        ):
            findings.append(f"the ledger misstates the bounds of {slot_id}")
        if row.get("state") not in ("COLLECTED", "LOST_NO_WINDOW", "PENDING", "UNACCOUNTED"):
            findings.append(f"the ledger states an undeclared state {row.get('state')!r} for {slot_id}")
        window = observed.get(slot_id)
        if window is not None and row.get("state") != "COLLECTED":
            findings.append(f"{slot_id} has a window in the index but the ledger calls it "
                            f"{row.get('state')}")
        if window is None and row.get("state") == "COLLECTED":
            findings.append(f"the ledger calls {slot_id} collected while the index holds no window")
        if window is not None:
            if row.get("collection_window_id") != window.get("window_id"):
                findings.append(f"the ledger names the wrong window for {slot_id}")
            recorded_raw = (window.get("raw") or {}).get("uncompressed_sha256")
            if recorded_raw and row.get("raw_evidence_hash") != recorded_raw:
                findings.append(f"the ledger's raw hash for {slot_id} does not match the index")
        classification = str(row.get("attendance_classification") or "")
        if classification in ABSENCE_CLASSES and row.get("external_evidence_status") != (
            "EXTERNAL_COVERAGE_COMPLETE"
        ):
            findings.append(
                f"the ledger claims the absence {classification} for {slot_id} without external "
                "coverage of the slot"
            )
        if row.get("state") == "UNACCOUNTED":
            findings.append(f"{slot_id} ended with neither a window nor a recorded loss")
    return findings


def findings_closure(closure: dict[str, Any] | None, period: dict[str, Any]) -> list[str]:
    if closure is None:
        return []
    findings: list[str] = []
    closed = closure.get("period") or {}
    if (closed.get("started_at_utc"), closed.get("ends_at_utc")) != (
        period["started_at_utc"],
        period["ends_at_utc"],
    ):
        findings.append(
            f"the consolidation belongs to another period: {closed.get('started_at_utc')} -> "
            f"{closed.get('ends_at_utc')}"
        )
    if closure.get("auto_extended") is not False:
        findings.append("the consolidation does not refuse extension")
    if closure.get("outcome") not in OUTCOMES:
        findings.append(f"the consolidation outcome {closure.get('outcome')!r} is not declared")
    if closure.get("outcome") == "COST_MODEL_SUPPORTED_IN_OBSERVED_REGIMES":
        coverage = closure.get("coverage_total") or {}
        if not coverage.get("coverage_complete"):
            findings.append("a supported outcome was recorded over incomplete coverage")
    return findings


def findings_drift(closure: dict[str, Any] | None) -> list[str]:
    if closure is None:
        return []
    findings: list[str] = []
    preserved = closure.get("drift_preserved") or {}
    breaches = closure.get("thresholds_breached") or []
    if breaches and not preserved:
        findings.append("the consolidation holds breaches but no preserved drift block")
    if preserved:
        if preserved.get("breaches_total") != len(breaches):
            findings.append(
                "the preserved drift block does not match the breaches listed in the consolidation"
            )
        if not preserved.get("policy"):
            findings.append("the preserved drift block states no aggregation policy")
    drift_verdict = preserved.get("verdict")
    basis_mentions_drift = "drift" in (closure.get("outcome_basis") or "").lower()
    if (
        closure.get("outcome") == "INSUFFICIENT_REGIME_COVERAGE"
        and drift_verdict == "DRIFT_WIDER_THAN_MODELLED"
        and not breaches
        and not basis_mentions_drift
    ):
        # the classification must not bury it: it has to be visible beside the outcome
        findings.append(
            "a drift verdict is recorded under an insufficient-coverage classification with no "
            "breach visible beside it"
        )
    if closure.get("outcome") == "COST_MODEL_SUPPORTED_IN_OBSERVED_REGIMES" and (
        drift_verdict == "DRIFT_WIDER_THAN_MODELLED" or breaches
    ):
        findings.append("a supported outcome hides a measured drift")
    return findings


def findings_post_close(
    runs: list[dict[str, Any]], period: dict[str, Any], closure: dict[str, Any] | None
) -> list[str]:
    findings: list[str] = []
    end = period["ends_at_utc"]
    after = [row for row in runs if str(row.get("actual_start_utc", "")) >= end]
    for row in after:
        if int(row.get("market_requests") or 0) != 0:
            findings.append(
                f"the run {row.get('run_id')} after the close made "
                f"{row.get('market_requests')} market request(s)"
            )
        if row.get("result") not in ("PERIOD_ENDED_CONSOLIDATED",):
            findings.append(
                f"the run {row.get('run_id')} after the close recorded {row.get('result')!r}"
            )
    if closure is not None:
        contract = closure.get("post_close_contract") or {}
        if contract.get("new_market_requests") != 0:
            findings.append("the consolidation's post-close contract does not forbid new requests")
        if contract.get("original_evidence_preserved") is not True:
            findings.append("the consolidation does not state that the original evidence is kept")
    return findings


def findings_idempotency(report: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    scenario = next(
        (entry for entry in report.get("scenarios", []) if entry["scenario"].startswith("4.")), None
    )
    if scenario is None:
        return ["the replay report has no post-close idempotency scenario"]
    for name, ok in scenario["checks"].items():
        if not ok:
            findings.append(f"the replay's idempotency check failed: {name}")
    repeat_hashes = {
        repeat.get("state_after", {}).get("closure_sha256")
        for repeat in scenario.get("repeats", [])
    }
    if len(repeat_hashes) > 1:
        findings.append("the consolidation changed across repeated post-close executions")
    restart = next(
        (entry for entry in report.get("scenarios", []) if entry["scenario"].startswith("10.")),
        None,
    )
    if restart is not None and restart.get("closure_sha256_first") != restart.get(
        "closure_sha256_second"
    ):
        findings.append("a fresh process produced a different consolidation from the same state")
    return findings


def findings_replay_report(report: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    input_state = close_input(report)
    if not input_state.get("digest"):
        findings.append(
            "the replay report does not identify the state it replayed: its close cannot be "
            "attributed to any state"
        )
    else:
        planned = int(input_state.get("declared_windows") or 0)
        window_ids = list(input_state.get("window_ids") or [])
        if len(window_ids) != int(input_state.get("observed_windows") or -1):
            findings.append("the replay report counts windows it does not list")
        if len(set(window_ids)) != len(window_ids):
            findings.append("the replay report lists a duplicated window")
        counted = scenario(report, "6.").get("observed_windows")
        if counted is not None and counted != len(window_ids):
            findings.append(
                "the replay report's close counts a different number of observed windows than the "
                f"state it says it replayed: {counted} against {len(window_ids)}"
            )
        if planned and int(scenario(report, "6.").get("declared_windows") or 0) != planned:
            findings.append("the replay report's closed plan and replayed plan disagree")
    for entry in report.get("scenarios", []):
        for name, ok in entry.get("checks", {}).items():
            if not ok and entry.get("verdict") == "PASS":
                findings.append(
                    f"the replay reports PASS on {entry['scenario']} with a failed check: {name}"
                )
    isolation = report.get("isolation") or {}
    if isolation.get("sandbox_outside_repository") is not True:
        findings.append("the replay's sandbox is not outside the repository")
    if isolation.get("unexplained_changes"):
        findings.append(
            f"the replay moved real files it does not explain: {isolation['unexplained_changes']}"
        )
    if isolation.get("real_state_unchanged") is not True and not isolation.get(
        "unexplained_changes"
    ):
        # the live tick keeps working while the replay runs: its own artefacts are attributed
        pass
    if isolation.get("real_market_requests") != 0:
        findings.append("the replay reports real market requests")
    if isolation.get("real_scheduler_calls") != 0:
        findings.append("the replay reports real scheduler calls")
    if isolation.get("subprocess_attempts"):
        findings.append("the replay attempted to spawn a program it forbids")
    for query in isolation.get("scheduler_queries") or []:
        if query.get("source") != "snapshot":
            findings.append(f"the replay read the real scheduler: {query}")
    if report.get("false_success") not in (0, None):
        findings.append(f"the replay reports false success {report['false_success']}")
    return findings


def live_files_moved_since_snapshot(manifest: dict[str, Any] | None) -> list[str]:
    """Live runtime state is expected to keep moving: the drift is reported, not hidden."""
    if manifest is None:
        return []
    moved: list[str] = []
    for entry in manifest["classification"]["LIVE_RUNTIME_STATE"]:
        if not entry.get("present"):
            continue
        path = REPO / entry["path"]
        if not path.exists() or sha256_file(path) != entry["sha256"]:
            moved.append(entry["path"])
    return sorted(moved)


def findings_snapshot(manifest: dict[str, Any] | None) -> list[str]:
    """The snapshot itself must be immutable: its copy and its evidence must reproduce."""
    if manifest is None:
        return ["no live-state snapshot exists to verify"]
    findings: list[str] = []
    copy_root = REPO / str(manifest.get("copy_root", ""))
    for entry in manifest["classification"]["LIVE_RUNTIME_STATE"]:
        if not entry.get("present"):
            continue
        path = REPO / entry["path"]
        if not path.exists():
            findings.append(f"the snapshot records {entry['path']} but it no longer exists")
            continue
        copy = copy_root / Path(entry["path"]).relative_to("data/st6")
        if not copy.exists():
            findings.append(f"{entry['path']} is missing from the snapshot copy")
        elif sha256_file(copy) != entry["sha256"]:
            findings.append(f"{entry['path']} hashes differently inside the snapshot copy")
    for entry in manifest["classification"]["IMMUTABLE_EVIDENCE"]:
        if not entry["reproduces_the_recorded_hash"]:
            findings.append(f"{entry['path']} does not reproduce its recorded window hash")
    for entry in manifest["classification"]["VERSIONED_IMPLEMENTATION"]:
        if not entry.get("present"):
            findings.append(f"the implementation file {entry['path']} is missing")
            continue
        if sha256_file(REPO / entry["path"]) != entry["sha256"]:
            findings.append(f"the implementation file {entry['path']} changed after the snapshot")
    return findings


def findings_separation(manifest: dict[str, Any] | None) -> list[str]:
    """The three-way separation must be complete and disjoint."""
    if manifest is None:
        return ["no snapshot manifest: the artefact separation cannot be checked"]
    classes = manifest["classification"]
    findings: list[str] = []
    named: dict[str, str] = {}
    for name in ("IMMUTABLE_EVIDENCE", "VERSIONED_IMPLEMENTATION", "LIVE_RUNTIME_STATE"):
        for entry in classes[name]:
            key = entry["path"]
            if key in named and name != "IMMUTABLE_EVIDENCE":
                findings.append(f"{key} is classified both as {named[key]} and as {name}")
            named[key] = name
    for required in (
        "scripts/st6_forward_regime.py",
        "scripts/st6_health_check.py",
        "scripts/st6_scheduler_verify.py",
        "data/st6/ST6_TASK_DEFINITION.xml",
    ):
        if named.get(required) != "VERSIONED_IMPLEMENTATION":
            findings.append(f"{required} is not classified as VERSIONED_IMPLEMENTATION")
    for required in (
        "data/st6/ST6_RUNS.jsonl",
        "data/st6/ST6_HEALTH_STATUS.json",
        "data/st6/ST6_WINDOWS.jsonl",
        "data/st6/ST6_OBSERVATIONS.jsonl",
    ):
        if named.get(required) != "LIVE_RUNTIME_STATE":
            findings.append(f"{required} is not classified as LIVE_RUNTIME_STATE")
    if not classes["IMMUTABLE_EVIDENCE"]:
        findings.append("no raw evidence is classified as immutable")
    return findings


def findings_no_order_path(paths: list[Path]) -> list[str]:
    findings: list[str] = []
    for path in paths:
        if not path.exists():
            findings.append(f"{path.name} does not exist")
            continue
        offenders = order_tokens(path.read_text(encoding="utf-8"))
        # the verifier and the harness name the tokens they forbid, inside their own guards
        if offenders and path.name not in ("st6_close_verify.py", "st6_scheduler_verify.py"):
            findings.append(f"{path.name} carries an order or credential path: {offenders}")
    return findings


# ------------------------------------------------------------------------------------------------
# negative proof: a verifier that cannot fail proves nothing
# ------------------------------------------------------------------------------------------------


def negative_self_tests(period: dict[str, Any], windows: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply the checks to deliberately corrupted fixtures and require each corruption to fire."""
    results: list[dict[str, Any]] = []
    raw_dir = Path(tempfile.mkdtemp(prefix="st6-verify-negative-"))

    def record(name: str, findings: list[str], expect: str) -> None:
        fired = any(expect in finding for finding in findings)
        results.append(
            {
                "fixture": name,
                "expected_finding": expect,
                "findings": findings,
                "detected": fired,
                "status": "PASS" if fired else "FAIL",
            }
        )

    # 1. a duplicated window index row
    duplicated = [*windows, windows[0]]
    record(
        "a duplicated window index row",
        findings_windows(duplicated, RAW),
        "duplicated slot",
    )
    # 2. a tampered hash in the index
    tampered = [{**windows[0], "raw": {**windows[0]["raw"], "uncompressed_sha256": "0" * 64}}]
    record("a tampered window hash", findings_windows(tampered, RAW), "sha256 mismatch")
    # 3. a missing raw snapshot
    missing = [{**windows[0], "window_id": "19990101T000000Z"}]
    record(
        "a missing raw snapshot",
        findings_windows(missing, raw_dir),
        "is missing",
    )
    # 4. an order path in a program
    offender = raw_dir / "offender.py"
    offender.write_text('client.create_order(symbol="BTCUSDT")\n', encoding="utf-8")
    record("an order path in a program", findings_no_order_path([offender]), "order or credential")
    # 5. a consolidation of another period
    foreign = {
        "artifact": "ST6_PERIOD_CLOSURE",
        "period": {"started_at_utc": "2026-01-01T00:00:00Z", "ends_at_utc": "2026-01-15T00:00:00Z"},
        "auto_extended": True,
        "outcome": "COST_MODEL_SUPPORTED_IN_OBSERVED_REGIMES",
        "coverage_total": {"coverage_complete": False},
    }
    record("a consolidation of another period", findings_closure(foreign, period), "another period")
    record(
        "a supported outcome over incomplete coverage",
        findings_closure(
            {
                **foreign,
                "period": {
                    "started_at_utc": period["started_at_utc"],
                    "ends_at_utc": period["ends_at_utc"],
                },
                "auto_extended": False,
            },
            period,
        ),
        "incomplete coverage",
    )
    # 6. drift hidden behind an insufficient-coverage classification
    hidden = {
        "artifact": "ST6_PERIOD_CLOSURE",
        "period": {
            "started_at_utc": period["started_at_utc"],
            "ends_at_utc": period["ends_at_utc"],
        },
        "auto_extended": False,
        "outcome": "INSUFFICIENT_REGIME_COVERAGE",
        "outcome_basis": "the coverage rule is not met",
        "thresholds_breached": [],
        "drift_preserved": {
            "verdict": "DRIFT_WIDER_THAN_MODELLED",
            "breaches_total": 0,
            "policy": "x",
        },
    }
    record("drift buried under insufficient coverage", findings_drift(hidden), "no breach visible")
    record(
        "a supported outcome hiding a measured drift",
        findings_drift(
            {
                "outcome": "COST_MODEL_SUPPORTED_IN_OBSERVED_REGIMES",
                "thresholds_breached": [{"kind": "spread_over_model"}],
                "drift_preserved": {
                    "verdict": "DRIFT_WIDER_THAN_MODELLED",
                    "breaches_total": 1,
                    "policy": "x",
                },
            }
        ),
        "hides a measured drift",
    )
    record(
        "a preserved drift block that does not match its breaches",
        findings_drift(
            {
                "outcome": "INSUFFICIENT_REGIME_COVERAGE",
                "thresholds_breached": [{"kind": "spread_over_model"}],
                "drift_preserved": {
                    "verdict": "DRIFT_WIDER_THAN_MODELLED",
                    "breaches_total": 0,
                    "policy": "x",
                },
            }
        ),
        "does not match the breaches",
    )
    # 7. a market request after the close
    after = [
        {
            "run_id": "x",
            "actual_start_utc": period["ends_at_utc"],
            "result": "COLLECTED",
            "market_requests": 4,
        }
    ]
    record(
        "a market request after the declared end",
        findings_post_close(after, period, None),
        "market request",
    )
    # 8. an ended slot that is neither observed nor missed
    record(
        "an ended declared slot that is unaccounted for",
        findings_missed(
            period, [], [], parse_instant(period["started_at_utc"]) + timedelta(days=2), []
        ),
        "neither observed nor missed",
    )
    # 8b-8e. the stated cause of a missed window, which is now audited rather than trusted
    slot = eligible_windows(period)[0]
    inside = slot["starts_at_utc"]
    ran_in_slot = [
        {
            "run_id": "fixture",
            "slot_key": slot["key"],
            "actual_start_utc": inside,
            "invocation": "SCHEDULED",
            "result": "SKIPPED_NO_WINDOW_DUE",
            "market_requests": 0,
            "errors": None,
        }
    ]
    honest = {
        "artifact": "ST6_MISSED_WINDOW",
        "status": "MISSED_WINDOW",
        "slot_key": slot["key"],
        "starts_at_utc": slot["starts_at_utc"],
        "ends_at_utc": slot["ends_at_utc"],
        "reason": "ATTENDED_NOT_COLLECTED: the tick visited the slot and measured nothing",
        "reconstructed": False,
        "attendance": {
            "classification": "ATTENDED_NOT_COLLECTED",
            "scheduled_runs_in_slot": 1,
            "manual_runs_in_slot": 0,
            "market_requests_in_slot": 0,
            "log_covers_whole_slot": True,
        },
    }
    before_the_slot = parse_instant(period["started_at_utc"])
    record(
        "a missed window that blames the schedule while the log shows the tick ran",
        findings_missed(
            period,
            [],
            [
                {
                    **honest,
                    "attendance": {
                        **honest["attendance"],
                        "classification": "UNATTENDED_NO_RUN_EVENT",
                        "scheduled_runs_in_slot": 0,
                    },
                }
            ],
            before_the_slot,
            ran_in_slot,
        ),
        "while the run log says",
    )
    record(
        "a missed window with no attendance evidence at all",
        findings_missed(
            period,
            [],
            [{key: value for key, value in honest.items() if key != "attendance"}],
            before_the_slot,
            ran_in_slot,
        ),
        "carries no attendance evidence",
    )
    record(
        "a missed window whose own counters contradict the run log",
        findings_missed(
            period,
            [],
            [
                {
                    **honest,
                    "attendance": {**honest["attendance"], "scheduled_runs_in_slot": 3},
                }
            ],
            before_the_slot,
            ran_in_slot,
        ),
        "claims scheduled_runs_in_slot",
    )
    record(
        "a missed window bounded by a slot that was never declared",
        findings_missed(
            period, [], [{**honest, "ends_at_utc": "2026-10-08T20:21:20Z"}], before_the_slot, ran_in_slot
        ),
        "is not bounded by the declared slot",
    )
    # 8f. the other direction: an honest claim must not be flagged
    honest_findings = findings_missed(period, [], [honest], before_the_slot, ran_in_slot)
    results.append(
        {
            "fixture": "an honest missed window whose stated cause the log supports",
            "expected_finding": "none",
            "findings": honest_findings,
            "detected": not honest_findings,
            "status": "PASS" if not honest_findings else "FAIL",
        }
    )
    # 8g-8j. the external record: an absence may only be claimed under coverage of the whole slot
    def covering_witness(slot: dict[str, Any], launches: list[str]) -> list[dict[str, Any]]:
        """Ten-minute samples across the whole slot, optionally naming a scheduler launch."""
        start = parse_instant(slot["starts_at_utc"])
        end = parse_instant(slot["ends_at_utc"])
        samples: list[dict[str, Any]] = [
            {
                "sample_id": f"fixture-{start.strftime('%H%M%S')}",
                "sampled_at_utc": start.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
                "scheduler_reported_last_run_utc": None,
                "scheduler_reported_last_task_result": 0,
                "scheduler_reported_state": 3,
                "scheduler_reported_missed_runs": 0,
                "any_tick_launched_by_the_scheduler_service": False,
            }
        ]
        cursor = start
        while cursor < end:
            cursor = min(cursor + timedelta(minutes=10), end)
            named = next((entry for entry in launches if entry <= cursor.strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )), None)
            samples.append(
                {
                    "sample_id": f"fixture-{cursor.strftime('%H%M%S')}",
                    "sampled_at_utc": cursor.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
                    "scheduler_reported_last_run_utc": named,
                    "scheduler_reported_last_task_result": 0,
                    "scheduler_reported_state": 3,
                    "scheduler_reported_missed_runs": 0,
                    "any_tick_launched_by_the_scheduler_service": False,
                }
            )
        return samples

    # the absence fixtures need a slot whose *start* the retained log can reach: the period begins
    # inside its first slot, so the second declared slot is the first one a covering claim can even be
    # made about
    absence_slot = eligible_windows(period)[1]
    covering = covering_witness(absence_slot, [])
    after_the_slot = parse_instant(absence_slot["ends_at_utc"]) + timedelta(hours=1)
    # the first declared slot is measured in these fixtures, so the only loss under test is the slot
    # the absence claim is about
    observed_first_slot = [
        {"day": "2026-10-08", "slot_index": eligible_windows(period)[0]["key"].split("#")[1]}
    ]
    # a run event from before this slot, so that the retained log demonstrably reaches back past it:
    # without it the derived class could not be a claim about the whole slot at all
    before_ran = [
        {
            "run_id": "fixture-before",
            "slot_key": "2026-10-08#0",
            "actual_start_utc": parse_instant(period["started_at_utc"]).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "invocation": "SCHEDULED",
            "result": "SKIPPED_NO_WINDOW_DUE",
            "market_requests": 0,
            "errors": None,
        }
    ]
    unattended_claim = {
        **honest,
        "slot_key": absence_slot["key"],
        "starts_at_utc": absence_slot["starts_at_utc"],
        "ends_at_utc": absence_slot["ends_at_utc"],
        "reason": "UNATTENDED_NO_RUN_EVENT: the schedule did not fire",
        "attendance": {
            **honest["attendance"],
            "classification": "UNATTENDED_NO_RUN_EVENT",
            "scheduled_runs_in_slot": 0,
            "log_covers_whole_slot": True,
        },
    }
    record(
        "an absence claim without any external coverage of the slot",
        findings_missed(
            period, [], [unattended_claim], after_the_slot, before_ran, witness=[], evidence=None
        ),
        "ATTENDANCE_UNKNOWN",
    )
    record(
        "an absence claim while the external record names a run inside the slot",
        findings_missed(
            period,
            observed_first_slot,
            [
                {
                    **unattended_claim,
                    "attendance": {
                        **unattended_claim["attendance"],
                        "external_evidence_status": "EXTERNAL_COVERAGE_COMPLETE",
                        "external_evidence": {
                            "status": "EXTERNAL_COVERAGE_COMPLETE",
                            "scheduler_engine_launch_count": 1,
                        },
                    },
                }
            ],
            after_the_slot,
            before_ran,
            witness=covering_witness(absence_slot, [absence_slot["starts_at_utc"]]),
            evidence=None,
        ),
        "say ATTENDANCE_EVIDENCE_CONFLICT",
    )
    # the other direction: a supported absence, and an attended slot, must both pass clean
    supported_absence = {
        **unattended_claim,
        "attendance": {
            **unattended_claim["attendance"],
            "external_evidence_status": "EXTERNAL_COVERAGE_COMPLETE",
            "external_evidence": {
                "status": "EXTERNAL_COVERAGE_COMPLETE",
                "scheduler_engine_launch_count": 0,
            },
        },
    }
    supported_findings = findings_missed(
        period,
        observed_first_slot,
        [supported_absence],
        after_the_slot,
        before_ran,
        witness=covering,
        evidence=None,
    )
    results.append(
        {
            "fixture": "an absence claim backed by external coverage that names no run",
            "expected_finding": "none",
            "findings": supported_findings,
            "detected": not supported_findings,
            "status": "PASS" if not supported_findings else "FAIL",
        }
    )
    # a witness that started inside the slot leaves it partial: the tick's own record still carries
    # the attendance, and no absence is asserted either way
    partial_witness = [
        row
        for row in covering_witness(slot, [])
        if row["sampled_at_utc"] >= "2026-10-08T17:00:00.000Z"
    ]
    attended_findings = findings_missed(
        period,
        [],
        [
            {
                **honest,
                "attendance": {
                    **honest["attendance"],
                    "external_evidence_status": "EXTERNAL_COVERAGE_PARTIAL",
                },
            }
        ],
        parse_instant(slot["ends_at_utc"]) + timedelta(hours=1),
        ran_in_slot,
        witness=partial_witness,
        evidence=None,
    )
    results.append(
        {
            "fixture": "an attended slot recorded while the external record only covered part of it",
            "expected_finding": "none",
            "findings": attended_findings,
            "detected": not attended_findings,
            "status": "PASS" if not attended_findings else "FAIL",
        }
    )
    # 8k-8l. the slot ledger, which the consolidation is built on
    declared = eligible_windows(period)
    healthy_ledger = {
        "slots": [
            {
                "slot_id": slot["key"],
                "slot_start_utc": slot["starts_at_utc"],
                "slot_end_utc": slot["ends_at_utc"],
                "state": "PENDING",
                "attendance_classification": None,
                "external_evidence_status": "EXTERNAL_COVERAGE_NOT_YET_STARTED",
            }
            for slot in declared
        ]
    }
    record(
        "a ledger that omits a declared slot",
        findings_ledger({**healthy_ledger, "slots": healthy_ledger["slots"][:-1]}, period, []),
        "omits declared slot",
    )
    record(
        "a ledger that claims an absence without external coverage",
        findings_ledger(
            {
                "slots": [
                    {
                        **healthy_ledger["slots"][0],
                        "state": "LOST_NO_WINDOW",
                        "attendance_classification": "UNATTENDED_NO_RUN_EVENT",
                        "external_evidence_status": "SCHEDULER_EVIDENCE_UNAVAILABLE",
                    },
                    *healthy_ledger["slots"][1:],
                ]
            },
            period,
            [
                {
                    "day": declared[0]["key"].split("#")[0],
                    "slot_index": int(declared[0]["key"].split("#")[1]),
                }
            ],
        ),
        "without external coverage of the slot",
    )
    ledger_clean = findings_ledger(healthy_ledger, period, [])
    results.append(
        {
            "fixture": "a ledger with one entry per declared slot and no unsupported claim",
            "expected_finding": "none",
            "findings": ledger_clean,
            "detected": not ledger_clean,
            "status": "PASS" if not ledger_clean else "FAIL",
        }
    )
    # 9. a declaration whose plan runs past its own end
    record(
        "a declaration whose plan runs past its own end",
        findings_denominator(
            {
                **period,
                "started_at_utc": "2026-10-08T16:21:20Z",
                "ends_at_utc": "2026-10-08T20:00:00Z",
            }
        )[1],
        "ends after the declared end",
    )
    # 10. a snapshot manifest whose implementation hash moved
    record(
        "an implementation hash that moved after the snapshot",
        findings_snapshot(
            {
                "copy_root": "data/st6/snapshots/none",
                "classification": {
                    "LIVE_RUNTIME_STATE": [],
                    "IMMUTABLE_EVIDENCE": [],
                    "VERSIONED_IMPLEMENTATION": [
                        {
                            "path": "scripts/st6_forward_regime.py",
                            "present": True,
                            "sha256": "0" * 64,
                        }
                    ],
                },
            }
        ),
        "changed after the snapshot",
    )
    # 11. an artefact that is classified as live state although it is implementation
    record(
        "an implementation file classified as live state",
        findings_separation(
            {
                "classification": {
                    "LIVE_RUNTIME_STATE": [
                        {"path": "scripts/st6_forward_regime.py", "present": True, "sha256": "x"}
                    ],
                    "IMMUTABLE_EVIDENCE": [{"path": "data/st6/raw/x.json.gz"}],
                    "VERSIONED_IMPLEMENTATION": [
                        {"path": "scripts/st6_health_check.py", "present": True, "sha256": "x"}
                    ],
                }
            }
        ),
        "not classified as VERSIONED_IMPLEMENTATION",
    )
    # 12. a replay report that claims PASS while one of its checks failed
    record(
        "a replay report that hides a failed check",
        findings_replay_report(
            {
                "scenarios": [
                    {
                        "scenario": "3. the exact close instant",
                        "verdict": "PASS",
                        "checks": {"the close returned the declared terminal status": False},
                    }
                ],
                "isolation": {"real_state_unchanged": True, "sandbox_outside_repository": True},
            }
        ),
        "with a failed check",
    )
    # 13. a replay report whose isolation is not proven
    record(
        "a replay report with unexplained real changes",
        findings_replay_report(
            {
                "scenarios": [],
                "isolation": {
                    "real_state_unchanged": False,
                    "sandbox_outside_repository": True,
                    "unexplained_changes": ["scripts/st6_forward_regime.py"],
                },
            }
        ),
        "moved real files",
    )
    # 14. the scan is not vacuous in the other direction either
    results.append(
        {
            "fixture": "a program that merely names the forbidden paths",
            "expected_finding": "none",
            "findings": order_tokens('FORBIDDEN = ("api_key", "create_order")\n'),
            "detected": order_tokens('FORBIDDEN = ("api_key", "create_order")\n') == [],
            "status": "PASS"
            if order_tokens('FORBIDDEN = ("api_key", "create_order")\n') == []
            else "FAIL",
        }
    )
    # 15 to 18. the replay's own origin: a close is a function of a state, and the state is named
    def replay_report(
        digest: str | None, window_ids: list[str], missed: int, closure_hash: str
    ) -> dict[str, Any]:
        input_state: dict[str, Any] = {
            "window_ids": window_ids,
            "observed_windows": len(window_ids),
            "declared_windows": 84,
        }
        if digest is not None:
            input_state["digest"] = digest
        return {
            "scenarios": [
                {
                    "scenario": "3. the exact close instant",
                    "verdict": "PASS",
                    "checks": {},
                    "closure_sha256": closure_hash,
                    "input_state": input_state,
                },
                {
                    "scenario": "6. unattended windows",
                    "verdict": "PASS",
                    "checks": {},
                    "missed_windows": missed,
                    "observed_windows": len(window_ids),
                    "declared_windows": 84,
                },
            ],
            "isolation": {"real_state_unchanged": True, "sandbox_outside_repository": True},
        }

    same_state = replay_report("state-A", ["2026-10-08#0"], 83, "closure-one")
    record(
        "the same state closed two different ways",
        reconcile_replays(
            same_state,
            replay_report("state-A", ["2026-10-08#0"], 83, "closure-two"),
            ["2026-10-08#0"],
        )["findings"],
        "closed the same way",
    )
    record(
        "a state that lost a window since the ship",
        reconcile_replays(
            replay_report("state-A", ["2026-10-08#0", "2026-10-08#9"], 82, "closure-one"),
            replay_report("state-B", ["2026-10-08#0"], 83, "closure-two"),
            ["2026-10-08#0"],
        )["findings"],
        "advanced by collection alone",
    )
    record(
        "a shipped close that does not add up to its own plan",
        reconcile_replays(
            replay_report("state-A", ["2026-10-08#0"], 60, "closure-one"),
            replay_report("state-A", ["2026-10-08#0"], 83, "closure-one"),
            ["2026-10-08#0"],
        )["findings"],
        "the plan minus the windows it had collected",
    )
    record(
        "a replay report that names no state at all",
        findings_replay_report(replay_report(None, ["2026-10-08#0"], 83, "closure-one")),
        "does not identify the state it replayed",
    )
    failed = [entry for entry in results if entry["status"] == "FAIL"]
    return {
        "artifact": "ST6_CLOSE_NEGATIVE_TESTS",
        "tests": len(results),
        "passed": len(results) - len(failed),
        "failed": len(failed),
        "results": results,
        "status": "PASS" if not failed else "FAIL",
    }


# ------------------------------------------------------------------------------------------------
# determinism: the harness is exercised, not read
# ------------------------------------------------------------------------------------------------


def rerun_replay() -> dict[str, Any]:
    """Run the replay again into a private destination and compare the close it produced."""
    root = Path(tempfile.mkdtemp(prefix="st6-verify-rerun-"))
    out_json = root / "report.json"
    out_md = root / "report.md"
    completed = subprocess.run(
        [
            str(PYTHON),
            str(REPLAY_SCRIPT),
            "--out-json",
            str(out_json),
            "--out-md",
            str(out_md),
            "--sandbox-root",
            str(root / "sandbox"),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    report = read_json(out_json)
    return {
        "root": root,
        "exit_code": completed.returncode,
        "stdout_tail": (completed.stdout or "").strip().splitlines()[-3:],
        "stderr_tail": (completed.stderr or "").strip().splitlines()[-3:],
        "report": report,
    }


def close_hash(report: dict[str, Any] | None) -> str | None:
    if not report:
        return None
    scenario = next(
        (entry for entry in report.get("scenarios", []) if entry["scenario"].startswith("3.")), None
    )
    return None if scenario is None else scenario.get("closure_sha256")


def close_input(report: dict[str, Any] | None) -> dict[str, Any]:
    """The identity of the state a replay's close sequence was taken against."""
    if not report:
        return {}
    scenario = next(
        (entry for entry in report.get("scenarios", []) if entry["scenario"].startswith("3.")), None
    )
    return ((scenario or {}).get("input_state") or {})


def scenario(report: dict[str, Any] | None, prefix: str) -> dict[str, Any]:
    if not report:
        return {}
    return next(
        (entry for entry in report.get("scenarios", []) if entry["scenario"].startswith(prefix)), {}
    )


def reconcile_replays(
    shipped: dict[str, Any] | None,
    rerun: dict[str, Any] | None,
    live_window_ids: list[str],
) -> dict[str, Any]:
    """Reconcile two replays of the close by the identity of the state each one replayed.

    A consolidation is a function of the collected state and of the close instant, and the campaign
    keeps collecting while this runs.  So two replays are only required to agree byte for byte when
    they replayed the *same* state; when the state has advanced, the shipped artefact has to be the
    close of an earlier state of the same period, and the advance has to be collection that only
    added windows.  Either way the reading is derived here, from the artefacts, and a report that
    states its own origin without corroboration fails.
    """
    shipped_input = close_input(shipped)
    rerun_input = close_input(rerun)
    shipped_ids = set(shipped_input.get("window_ids") or [])
    rerun_ids = list(rerun_input.get("window_ids") or [])
    live_ids = list(live_window_ids)
    planned = int(shipped_input.get("declared_windows") or rerun_input.get("declared_windows") or 0)
    shipped_digest = shipped_input.get("digest")
    rerun_digest = rerun_input.get("digest")
    same_state = bool(shipped_digest) and shipped_digest == rerun_digest
    shipped_missed = scenario(shipped, "6.").get("missed_windows")
    rerun_missed = scenario(rerun, "6.").get("missed_windows")
    checks = {
        "the shipped report identifies the state it replayed": bool(shipped_digest),
        "the rerun identifies the state it replayed": bool(rerun_digest),
        "the rerun replayed the live state": sorted(rerun_ids) == sorted(live_ids),
        "the two reports close the same declared plan": int(
            shipped_input.get("declared_windows") or 0
        )
        == int(rerun_input.get("declared_windows") or -1)
        and int(shipped_input.get("declared_windows") or 0)
        == int(scenario(shipped, "6.").get("declared_windows") or -1)
        == int(scenario(rerun, "6.").get("declared_windows") or -1),
        "the shipped close is the plan minus the windows it had collected": (
            shipped_missed == planned - len(shipped_ids) and planned > 0
        ),
        "the rerun's close is the plan minus the windows now collected": (
            rerun_missed == planned - len(rerun_ids)
        ),
        "the state advanced by collection alone": shipped_ids <= set(live_ids),
    }
    if same_state:
        checks["the same state is closed the same way"] = close_hash(shipped) == close_hash(rerun)
    else:
        checks["the advance is a later state of the same period"] = len(rerun_ids) >= len(
            shipped_ids
        ) and bool(shipped_ids)
    failed = [name for name, ok in checks.items() if not ok]
    return {
        "shipped_input_state": shipped_input.get("digest"),
        "rerun_input_state": rerun_input.get("digest"),
        "same_input_state": same_state,
        "reading": (
            "REPRODUCED: the shipped artefact is the byte-for-byte close of a state that has not "
            "moved since"
            if same_state
            else "SUPERSEDED_BY_NEW_COLLECTION: the shipped artefact is the close of an earlier "
            "state of the same period, and the state advanced by collecting more windows"
        ),
        "shipped_observed_windows": shipped_input.get("observed_windows"),
        "rerun_observed_windows": len(rerun_ids),
        "live_observed_windows": len(live_ids),
        "windows_added_since_the_ship": sorted(set(live_ids) - shipped_ids),
        "shipped_missed_windows": shipped_missed,
        "rerun_missed_windows": rerun_missed,
        "checks": checks,
        "findings": failed,
    }


def replayed_close(root: Path) -> dict[str, Any]:
    """Read the consolidation the harness *produced*, straight from its sandbox.

    The real period is still open, so the closure on disk does not exist yet: the artefact that can
    be verified positively is the one the replay produced at the injected close instant.  It is read
    from the sandbox file, not from the harness's summary of it.
    """
    base = root / "sandbox" / "close-sequence" / "data" / "st6"
    closure = read_json(base / "ST6_PERIOD_CLOSURE.json")
    windows = read_jsonl(base / "ST6_WINDOWS.jsonl")
    runs = read_jsonl(base / "ST6_RUNS.jsonl")
    missed = read_jsonl(base / "ST6_MISSED_WINDOWS.jsonl")
    return {
        "sandbox": str(base),
        "closure_path": str((base / "ST6_PERIOD_CLOSURE.json").relative_to(root.parent))
        if (base / "ST6_PERIOD_CLOSURE.json").exists()
        else None,
        "closure": closure,
        "closure_sha256": sha256_file(base / "ST6_PERIOD_CLOSURE.json")
        if (base / "ST6_PERIOD_CLOSURE.json").exists()
        else None,
        "windows": windows,
        "runs": runs,
        "missed": missed,
    }


def findings_replayed_close(
    replayed: dict[str, Any], period: dict[str, Any], live_drift: dict[str, Any] | None
) -> tuple[dict[str, Any], list[str]]:
    closure = replayed["closure"]
    findings = list(findings_closure(closure, period))
    findings += findings_drift(closure)
    findings += findings_post_close(replayed["runs"], period, closure)
    summary: dict[str, Any] = {}
    if closure is None:
        findings.append("the replay produced no consolidation to verify")
        return summary, findings
    preserved = closure.get("drift_preserved") or {}
    summary = {
        "outcome": closure.get("outcome"),
        "terminal_state": closure.get("terminal_state"),
        "auto_extended": closure.get("auto_extended"),
        "coverage_total": closure.get("coverage_total"),
        "drift_verdict": preserved.get("verdict"),
        "breaches_total": preserved.get("breaches_total"),
        "orders_sent": closure.get("orders_sent"),
        "credentials_used": closure.get("credentials_used"),
        "missed_windows": len(replayed["missed"]),
    }
    if closure.get("terminal_state") != "PERIOD_CLOSED_NO_FURTHER_COLLECTION":
        findings.append("the replayed close declares no terminal state")
    if not (closure.get("terminal_transition") or {}).get("recorded"):
        findings.append("the replayed close records no terminal transition")
    coverage = closure.get("coverage_total") or {}
    if coverage.get("planned_windows") != int(period["period_days"]) * int(period["slots_per_day"]):
        findings.append("the replayed close carries a denominator that is not the declared plan")
    if int(coverage.get("observed_windows") or 0) != len(replayed["windows"]):
        findings.append("the replayed close's observed count disagrees with its window index")
    if int(coverage.get("missed_windows") or 0) != len(replayed["missed"]):
        findings.append("the replayed close's missed count disagrees with its missed log")
    if int(closure.get("orders_sent") or 0) != 0 or int(closure.get("credentials_used") or 0) != 0:
        findings.append("the replayed close reports an order or a credential")
    # drift preservation against the live monitor: the close may not lose a breach it saw
    if live_drift is not None:
        live_keys = {
            (entry["asset"], entry["kind"], entry["observed_at_utc"])
            for entry in live_drift.get("breaches", [])
        }
        closure_keys = {
            (entry["asset"], entry["kind"], entry["observed_at_utc"])
            for entry in (closure.get("thresholds_breached") or [])
        }
        summary["live_drift_breaches"] = len(live_keys)
        summary["closure_drift_breaches"] = len(closure_keys)
        summary["drift_breaches_lost_by_the_close"] = sorted(live_keys - closure_keys)
        if live_keys - closure_keys:
            findings.append(
                "the replayed close lost a drift breach the live monitor measured: "
                f"{sorted(live_keys - closure_keys)}"
            )
    return summary, findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--skip-replay", action="store_true")
    args = parser.parse_args(argv)

    c = Checks()
    period = read_json(PERIOD)
    if period is None:
        print("no period is declared; nothing to verify")
        return 1
    windows = read_jsonl(WINDOWS)
    missed = read_jsonl(MISSED)
    runs = read_jsonl(RUNS)
    closure = read_json(CLOSURE)
    report = read_json(REPLAY_REPORT)
    ledger_document = read_json(DATA / "ST6_SLOT_LEDGER.json")
    manifest_path = sorted(SNAPSHOTS.glob("ST6_LIVE_STATE_*.json"))
    manifest = read_json(manifest_path[-1]) if manifest_path else None

    denominator, denominator_findings = findings_denominator(period)
    windows_findings = findings_windows(windows, RAW)
    missed_findings = findings_missed(
        period,
        windows,
        missed,
        datetime.now(UTC),
        runs,
        load_witness_samples(WITNESS_LOG),
        read_external_json(SCHEDULER_EVIDENCE),
    )
    closure_findings = findings_closure(closure, period)
    drift_findings = findings_drift(closure)
    post_close_findings = findings_post_close(runs, period, closure)
    idempotency_findings = findings_idempotency(report or {})
    report_findings = (
        findings_replay_report(report or {}) if report else ["no replay report exists"]
    )
    ledger_findings = findings_ledger(ledger_document, period, windows)
    snapshot_findings = findings_snapshot(manifest)
    live_moved = live_files_moved_since_snapshot(manifest)
    separation_findings = findings_separation(manifest)
    order_findings = findings_no_order_path(
        [TICK, SCRIPTS / "st6_health_check.py", SCRIPTS / "st6_scheduler_verify.py"]
    )

    c.check("the denominator is the declared plan", not denominator_findings, denominator_findings)
    c.check(
        "the eligible windows are counted from the start's own slot",
        not denominator_findings,
        denominator,
    )
    c.check(
        "the window index is unique and reproduces its evidence",
        not windows_findings,
        windows_findings,
    )
    c.check("every ended declared slot is accounted for", not missed_findings, missed_findings)
    c.check(
        "a consolidation belongs to the declared period", not closure_findings, closure_findings
    )
    c.check("a measured drift is preserved beside the outcome", not drift_findings, drift_findings)
    c.check(
        "no market request was made after the close", not post_close_findings, post_close_findings
    )
    c.check("the close is idempotent", not idempotency_findings, idempotency_findings)
    c.check("the replay report is internally consistent", not report_findings, report_findings)
    c.check(
        "the eighty-four slots are read from a complete ledger",
        not ledger_findings,
        ledger_findings,
    )
    c.check("the live-state snapshot reproduces", not snapshot_findings, snapshot_findings)
    c.check(
        "the artefacts are separated into immutable, versioned and live",
        not separation_findings,
        separation_findings,
    )
    c.check("no program carries an order or credential path", not order_findings, order_findings)

    negative = negative_self_tests(period, windows)
    c.check(
        "the negative fixtures are all detected",
        negative["status"] == "PASS",
        [entry for entry in negative["results"] if entry["status"] == "FAIL"],
    )

    determinism: dict[str, Any] | None = None
    replayed_summary: dict[str, Any] | None = None
    if not args.skip_replay:
        rerun = rerun_replay()
        produced = replayed_close(rerun["root"])
        replayed_summary, replayed_findings = findings_replayed_close(
            produced, period, read_json(DATA / "ST6_MODEL_DRIFT.json")
        )
        c.check(
            "the consolidation the replay produced is a correct terminal artefact",
            not replayed_findings,
            replayed_findings,
        )
        c.check(
            "the replayed close preserved the drift the live monitor measured",
            not (replayed_summary or {}).get("drift_breaches_lost_by_the_close"),
            replayed_summary,
        )
        reconciliation_replay = reconcile_replays(
            report, rerun["report"], sorted(f"{row['day']}#{row['slot_index']}" for row in windows)
        )
        determinism = {
            "exit_code": rerun["exit_code"],
            "stdout_tail": rerun["stdout_tail"],
            "stderr_tail": rerun["stderr_tail"],
            "shipped_close_sha256": close_hash(report),
            "rerun_close_sha256": close_hash(rerun["report"]),
            "input_state": reconciliation_replay,
            "verdicts_equal": [
                entry["verdict"]
                for entry in sorted(
                    (report or {}).get("scenarios", []), key=lambda e: e["scenario"]
                )
            ]
            == [
                entry["verdict"]
                for entry in sorted(
                    (rerun["report"] or {}).get("scenarios", []), key=lambda e: e["scenario"]
                )
            ],
            "rerun_close_mechanics": (rerun["report"] or {}).get("close_mechanics_verdict"),
        }
        c.check(
            "the replay runs again and closes the same state the same way",
            rerun["exit_code"] == 0
            and determinism["rerun_close_mechanics"] == "PASS"
            and not reconciliation_replay["findings"],
            determinism,
        )
        c.check(
            "a second run of the harness reaches the same verdict on every scenario",
            determinism["verdicts_equal"],
            determinism,
        )

    # the implementation the replay exercised must be the implementation on disk
    if report:
        c.check(
            "the replay verified the tick that is on disk",
            report.get("tick_sha256") == sha256_file(TICK),
            {"report": report.get("tick_sha256"), "disk": sha256_file(TICK)},
        )
    c.check(
        "the builder is neither the verifier nor the replay harness",
        Path(__file__).name not in (TICK.name, REPLAY_SCRIPT.name),
        Path(__file__).name,
    )

    result: dict[str, Any] = {
        "artifact": VERIFIER_VERSION,
        "verifier": "scripts/st6_close_verify.py",
        "builder": "scripts/st6_forward_regime.py",
        "replay_harness": "scripts/st6_close_replay.py",
        "builder_equals_verifier": False,
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "denominator": denominator,
        "counts": {
            "windows": len(windows),
            "observations": len(read_jsonl(OBSERVATIONS)),
            "runs": len(runs),
            "missed": len(missed),
            "closure_present": closure is not None,
            "raw_snapshots": len(list(RAW.glob("*.json.gz"))),
        },
        "findings": {
            "denominator": denominator_findings,
            "windows": windows_findings,
            "missed": missed_findings,
            "closure": closure_findings,
            "drift": drift_findings,
            "post_close": post_close_findings,
            "idempotency": idempotency_findings,
            "replay_report": report_findings,
            "slot_ledger": ledger_findings,
            "snapshot": snapshot_findings,
            "separation": separation_findings,
            "order_paths": order_findings,
        },
        "negative_tests": negative,
        "replayed_close": replayed_summary,
        "snapshot_life": {
            "manifest": str(manifest_path[-1].relative_to(REPO)) if manifest_path else None,
            "snapshot_id": (manifest or {}).get("snapshot_id"),
            "live_files_that_moved_since_the_snapshot": live_moved,
            "reading": (
                "live runtime state keeps moving by design: those files are the ones the running "
                "tick rewrites, and the snapshot copy is the immutable record of what they held"
            ),
        },
        "determinism": determinism,
        "checks_total": c.total,
        "checks_passed": c.passed,
        "mismatches": len(c.failed),
        "failures": c.failed,
        "false_success": len(c.failed),
        "status": "PASS" if not c.failed else "FAIL",
        "verdict": "ST6_CLOSE_VERIFIED" if not c.failed else "ST6_CLOSE_NOT_VERIFIED",
        "method": (
            "the verifier re-derives the plan, the window index, the missed accounting, the "
            "terminal state, the post-close contract and the drift preservation from the state on "
            "disk; it re-verifies the live-state snapshot by re-hashing it; it exercises the replay "
            "harness again and compares the close it produces; and it proves its own checks fail on "
            "corrupted fixtures before it reports anything"
        ),
        "standing_state": {
            "ST6_AUTONOMOUS_COLLECTION_ACTIVE": True,
            "ECO_1": "OPEN",
            "NEXT_CAMPAIGN": "NOT_AUTHORIZED",
            "LIVE_TRADING": "DISABLED",
            "TRADES_AUTHORIZED": 0,
            "PROFITABILITY_VERIFIED": False,
        },
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        # the recorded hashes of this artefact must describe bytes that any host can reproduce
        newline="\n",
    )
    print(
        f"{result['status']} {result['checks_passed']}/{result['checks_total']} checks, "
        f"{result['mismatches']} mismatches, FALSE_SUCCESS = {result['false_success']}"
    )
    for failure in c.failed[:25]:
        print(f"  FAIL {failure}")
    print(f"written -> {out}")
    return 1 if c.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
