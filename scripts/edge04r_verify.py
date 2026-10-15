"""WP-EDGE-04R — verify the continuity audit from the outside, and try to falsify it.

    python scripts/edge04r_verify.py --reports reports/edge-recovery/WP-EDGE-04R --repo .
    python scripts/edge04r_verify.py --reports ... --self-test     also run the sabotages

This file shares no code with the audit it checks. It re-implements the arithmetic it
needs — the trigger phase, the instants, the matching, the per-instant host state — from
the raw inputs the snapshot carries, and compares its own numbers with the published
ones. A verifier that imported the audit would only be able to say the audit agrees with
itself.

Each check is paid for by the sabotage matrix: for every claim the verifier makes, an
input is mutated to the form that makes the claim false, and the verifier must report
``VERIFY_FAIL`` on the mutated copy and ``VERIFY_PASS`` on the untouched one. A sabotage
that is not detected is reported as its own failure — it is a check that cannot fail.

Research only: public market data, no credentials, no orders, no capital.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

VERIFIER_SCHEMA = "EDGE04R_VERIFICATION_V1"
INTERVAL_MS = 900_000
REQUIRED_DELIVERABLES = (
    "RUN_REPORT.md",
    "RUN_REPORT.json",
    "FINAL_REPORT.md",
    "AVAILABILITY.md",
    "SESSION_INDEPENDENCE.md",
    "INFORME_EJECUTIVO.md",
    "VERIFICATION.json",
)
REQUIRED_EVIDENCE = (
    "OS_CONTINUITY_EVIDENCE.json",
    "EDGE04R_CONTINUITY_AUDIT.json",
    "SESSION_INDEPENDENCE.json",
    "RUN_LOG_SNAPSHOT.jsonl",
    "SLOT_LEDGER_SNAPSHOT.jsonl",
    "SNAPSHOT.json",
    "ECONOMIC_CERTIFICATE_DIAGNOSIS.json",
)
FORBIDDEN_CLAIMS = ("PAPER_READY", "LIVE_READY", "ADOPTED", "PROMOTED")


def _instant(text: str | None) -> int | None:
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp() * 1000)


def _stamp(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha(bytes_: bytes) -> str:
    return hashlib.sha256(bytes_).hexdigest()


def _lf_sha(bytes_: bytes) -> str:
    return hashlib.sha256(bytes_.replace(b"\r\n", b"\n")).hexdigest()


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _rows(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            row = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


# -- the verifier's own arithmetic ------------------------------------------------ #


def _own_windows(evidence: dict[str, Any], *, until_ms: int) -> dict[str, list[tuple[int, int]]]:
    boots = sorted(
        at
        for row in evidence.get("boots") or []
        if (at := _instant(str(row.get("at")))) is not None
    )
    downs = sorted(
        at
        for row in evidence.get("shutdowns") or []
        if (at := _instant(str(row.get("at")))) is not None
    )
    logins = sorted(
        at
        for row in evidence.get("sessions") or []
        if int(row.get("id") or 0) in (21, 22, 25)
        and (at := _instant(str(row.get("at")))) is not None
    )
    logouts = sorted(
        at
        for row in evidence.get("sessions") or []
        if int(row.get("id") or 0) in (23, 24) and (at := _instant(str(row.get("at")))) is not None
    )
    sleeps = sorted(
        at
        for row in evidence.get("power") or []
        if int(row.get("id") or 0) == 42 and (at := _instant(str(row.get("at")))) is not None
    )
    resumes = sorted(
        at
        for row in evidence.get("power") or []
        if int(row.get("id") or 0) == 107 and (at := _instant(str(row.get("at")))) is not None
    )

    host_down: list[tuple[int, int]] = []
    pending: int | None = None
    for at, kind in sorted([(at, "boot") for at in boots] + [(at, "down") for at in downs]):
        if kind == "down":
            pending = at if pending is None else pending
        elif pending is not None:
            host_down.append((pending, at))
            pending = None
    if pending is not None:
        host_down.append((pending, until_ms))

    sleep: list[tuple[int, int]] = []
    open_sleep: int | None = None
    for at, kind in sorted([(at, "s") for at in sleeps] + [(at, "r") for at in resumes]):
        if kind == "s" and open_sleep is None:
            open_sleep = at
        elif kind == "r" and open_sleep is not None:
            sleep.append((open_sleep, at))
            open_sleep = None
    if open_sleep is not None:
        sleep.append((open_sleep, until_ms))

    absent: list[tuple[int, int]] = []
    open_absent: int | None = None
    events = (
        [(at, "logoff") for at in logouts]
        + [(at, "logon") for at in logins]
        + [(at, "boot") for at in boots]
        + [(at, "down") for at in downs]
    )
    for at, kind in sorted(events):
        if kind == "down":
            continue
        if kind in ("logoff", "boot"):
            if open_absent is None:
                open_absent = at
            continue
        if open_absent is not None:
            absent.append((open_absent, at))
            open_absent = None
    if open_absent is not None:
        absent.append((open_absent, until_ms))
    return {"host_down": host_down, "sleep": sleep, "session_absent": absent}


def _own_state(instant: int, windows: dict[str, list[tuple[int, int]]]) -> str:
    for start, end in windows["host_down"]:
        if start <= instant <= end:
            return "HOST_DOWN"
    for start, end in windows["sleep"]:
        if start <= instant <= end:
            return "SLEEP"
    for start, end in windows["session_absent"]:
        if start <= instant <= end:
            return "NO_SESSION"
    return "SILENT_UNATTRIBUTABLE"


def _own_reading(report: Path) -> dict[str, Any]:
    """Re-derive the audit's headline numbers from the snapshot, independently."""
    evidence = _load(report / "evidence" / "OS_CONTINUITY_EVIDENCE.json")
    audit = _load(report / "evidence" / "EDGE04R_CONTINUITY_AUDIT.json")
    ticks = [
        row
        for row in _rows(report / "evidence" / "RUN_LOG_SNAPSHOT.jsonl")
        if str(row.get("mode") or "").upper() == "SCHEDULED"
    ]
    starts = sorted(
        int(row["started_at_ms"]) for row in ticks if isinstance(row.get("started_at_ms"), int)
    )
    until_ms = _instant(audit["window"]["to_utc"]) or starts[-1]
    offsets: dict[int, int] = {}
    for start in starts:
        bucket = (start % INTERVAL_MS) // 1000
        offsets[bucket] = offsets.get(bucket, 0) + 1
    phase = max(sorted(offsets), key=lambda key: offsets[key]) * 1000
    first = starts[0] - (starts[0] - phase) % INTERVAL_MS
    if first < starts[0]:
        first += INTERVAL_MS
    count = (until_ms - first) // INTERVAL_MS + 1
    instants = [first + index * INTERVAL_MS for index in range(int(max(0, count)))]
    tolerance = min(10 * 60 * 1000, INTERVAL_MS // 2 - 1000)
    windows = _own_windows(evidence, until_ms=until_ms)
    consumed = {
        "OBSERVED",
        "NO_NEW_DATA",
        "ALREADY_OBSERVED",
    }
    answers: dict[int, dict[str, Any]] = {}
    for instant in instants:
        best: dict[str, Any] | None = None
        best_distance: int | None = None
        for row in ticks:
            raw_start = row.get("started_at_ms")
            if not isinstance(raw_start, int):
                continue
            distance = abs(raw_start - instant)
            if distance > tolerance:
                continue
            if best_distance is None or distance < best_distance:
                best, best_distance = row, distance
        if best is not None:
            answers[instant] = best
    causes: dict[str, int] = {}
    for instant in instants:
        if instant in answers:
            continue
        cause = _own_state(instant, windows)
        causes[cause] = causes.get(cause, 0) + 1
    refused = sum(1 for row in answers.values() if str(row.get("outcome")) not in consumed)
    days: dict[str, dict[str, int]] = {}
    for instant in instants:
        days.setdefault(_stamp(instant)[:10], {"expected": 0})
        days[_stamp(instant)[:10]]["expected"] += 1
    for instant, row in answers.items():
        key = _stamp(instant)[:10]
        slot = "consumed" if str(row.get("outcome")) in consumed else "refused"
        days.setdefault(key, {"expected": 0, "consumed": 0, "refused": 0})
        days[key][slot] = days[key].get(slot, 0) + 1
    for instant in instants:
        if instant in answers:
            continue
        key = _stamp(instant)[:10]
        cause = _own_state(instant, windows)
        days.setdefault(key, {"expected": 0})
        days[key][cause] = days[key].get(cause, 0) + 1
    # A window that opened before the first tick is only counted from the first tick:
    # the lane did not exist before that, and charging it for the time is not evidence.
    clipped_absent = sum(
        (end - max(start, starts[0])) / 1000
        for start, end in windows["session_absent"]
        if end > starts[0]
    )
    clipped_down = sum(
        (end - max(start, starts[0])) / 1000
        for start, end in windows["host_down"]
        if end > starts[0]
    )
    lifespan = (until_ms - starts[0]) / 1000
    return {
        "ticks": len(ticks),
        "expected": len(instants),
        "answered": len(answers),
        "consumed": len(answers) - refused,
        "refused": refused,
        "causes": causes,
        "phase": phase,
        "window_from": _stamp(starts[0]),
        "window_to": _stamp(until_ms),
        "days": days,
        "sleep_pairs": len(windows["sleep"]),
        "absent_seconds": clipped_absent,
        "down_seconds": clipped_down,
        "schedulable_fraction": round(1 - (clipped_absent + clipped_down) / lifespan, 4),
        "instants": [_stamp(instant) for instant in instants],
        "unanswered_utc": [_stamp(instant) for instant in instants if instant not in answers],
    }


# -- the checks ------------------------------------------------------------------- #


def run_checks(report: Path, *, repo: Path) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    missing = [name for name in REQUIRED_DELIVERABLES if not (report / name).is_file()]
    check(
        "deliverable_set_present",
        not missing,
        f"{len(REQUIRED_DELIVERABLES) - len(missing)}/{len(REQUIRED_DELIVERABLES)} named deliverables"
        + (f"; missing {missing}" if missing else ""),
    )
    missing_evidence = [
        name for name in REQUIRED_EVIDENCE if not (report / "evidence" / name).is_file()
    ]
    check(
        "evidence_set_present",
        not missing_evidence,
        f"{len(REQUIRED_EVIDENCE) - len(missing_evidence)}/{len(REQUIRED_EVIDENCE)} evidence files"
        + (f"; missing {missing_evidence}" if missing_evidence else ""),
    )
    if missing or missing_evidence:
        return {"verdict": "VERIFY_FAIL", "checks": checks, "failures": len(checks)}

    audit = _load(report / "evidence" / "EDGE04R_CONTINUITY_AUDIT.json")
    manifest = _load(report / "evidence" / "SNAPSHOT.json")
    probes = _load(report / "evidence" / "SESSION_INDEPENDENCE.json")
    diagnosis = _load(report / "evidence" / "ECONOMIC_CERTIFICATE_DIAGNOSIS.json")

    # 1. The snapshot is what the audit says it read.
    bad: list[str] = []
    for name, row in (manifest.get("files") or {}).items():
        path = report / "evidence" / name
        if not path.is_file():
            bad.append(f"{name} missing")
            continue
        data = path.read_bytes()
        if _sha(data) != row.get("sha256"):
            bad.append(f"{name} sha256")
        if _lf_sha(data) != row.get("sha256_lf"):
            bad.append(f"{name} sha256_lf")
        if len(data) != row.get("bytes"):
            bad.append(f"{name} bytes")
    check(
        "snapshot_files_match_their_digests",
        not bad,
        f"{len(manifest.get('files') or {})} files; {bad}",
    )

    # 2. The published snapshot hashes are the ones the audit carries.
    published = audit.get("snapshot") or {}
    mismatched = [
        name
        for name, digest in published.items()
        if (manifest.get("files") or {}).get(name, {}).get("sha256") != digest
    ]
    check("the_audit_and_the_manifest_name_the_same_bytes", not mismatched, f"{mismatched}")

    # 3. The audit's own checks all passed.
    failed = [row["name"] for row in audit.get("checks") or [] if not row.get("passed")]
    check(
        "the_audit_own_checks_pass",
        not failed,
        f"{len(audit.get('checks') or [])} checks; failing {failed}",
    )

    # 4. The verifier's independent re-derivation agrees with the published one.
    own = _own_reading(report)
    loss = audit["trigger_loss"]
    published_availability = audit.get("availability") or {}
    # Each figure carries its own tolerance: counts must match exactly, and the two time
    # totals are compared to the second, because both sides round independently. The
    # availability figures matter — without them a sabotage that changes only *how long*
    # the host was unavailable would leave every count unchanged and go unnoticed.
    agreement: dict[str, tuple[Any, Any, float]] = {
        "expected": (loss.get("expected"), own["expected"], 0),
        "answered": (loss.get("answered_by_a_tick"), own["answered"], 0),
        "refused": (loss.get("refused_after_firing"), own["refused"], 0),
        "causes": (dict(loss.get("causes") or {}), own["causes"], 0),
        "window_from": (audit["window"]["from_utc"], own["window_from"], 0),
        "phase": (audit["window"]["phase_offset_ms"], own["phase"], 0),
        "session_absent_seconds": (
            published_availability.get("session_absent_seconds"),
            round(own["absent_seconds"], 3),
            1.0,
        ),
        "host_down_seconds": (
            published_availability.get("host_down_seconds"),
            round(own["down_seconds"], 3),
            1.0,
        ),
        "schedulable_fraction": (
            published_availability.get("schedulable_fraction"),
            own["schedulable_fraction"],
            0.001,
        ),
    }

    def _same(value: tuple[Any, Any, float]) -> bool:
        published, mine, tolerance = value
        if isinstance(published, bool) or isinstance(mine, bool):
            return bool(published == mine)
        if isinstance(published, (int, float)) and isinstance(mine, (int, float)):
            return bool(abs(float(published) - float(mine)) <= tolerance)
        return bool(published == mine)

    disagreed = {key: value[:2] for key, value in agreement.items() if not _same(value)}
    check(
        "independent_re_derivation_agrees",
        not disagreed,
        f"{len(agreement) - len(disagreed)}/{len(agreement)} figures agree; {disagreed}",
    )

    # 5. Every day's columns add up to its own expectation count.
    unreconciled = [
        row["day"]
        for row in audit.get("daily") or []
        if row.get("unaccounted") not in (0, None)
        or (
            row.get("consumed", 0)
            + row.get("refused", 0)
            + row.get("no_session", 0)
            + row.get("host_down", 0)
            + row.get("sleep", 0)
            + row.get("silent", 0)
            != row.get("expected")
        )
    ]
    check("every_day_reconciles", not unreconciled, f"{unreconciled}")

    # 6. The sleep hypothesis is refused on evidence, and the refutation is explicit.
    sleep_claims = int((loss.get("causes") or {}).get("SLEEP", 0))
    check(
        "no_sleep_cause_without_a_sleep_record",
        sleep_claims == 0 or own["sleep_pairs"] > 0,
        f"{sleep_claims} sleep attributions against {own['sleep_pairs']} sleep/resume pairs",
    )

    # 7. The invariants the work package promised not to move.
    invariants = audit.get("invariants") or {}
    ruleset = invariants.get("ruleset") or {}
    frozen = _frozen_digest(repo)
    check(
        "frozen_ruleset_unchanged",
        bool(ruleset.get("agrees")) and ruleset.get("params_hash") == frozen.get("params_hash"),
        f"re-derived {frozen.get('params_hash')} vs published {ruleset.get('params_hash')}",
    )
    check(
        "coverage_floor_and_forward_requirement_intact",
        invariants.get("coverage_required") == 0.9
        and invariants.get("forward_days_required") == 60,
        f"coverage {invariants.get('coverage_required')}, days {invariants.get('forward_days_required')}",
    )
    check(
        "no_order_and_no_promotion_anywhere",
        invariants.get("orders_recorded") == 0
        and invariants.get("non_hypothetical_ticks") == 0
        and set((invariants.get("promotion") or {}).keys()) <= {"NONE"},
        f"orders {invariants.get('orders_recorded')}, non-hypothetical "
        f"{invariants.get('non_hypothetical_ticks')}, promotions {invariants.get('promotion')}",
    )

    # 8. The storage verdict follows from the estate the evidence recorded.
    estate = (audit.get("storage") or {}).get("estate") or {}
    qualifying = [
        row
        for row in estate.get("volumes") or []
        if row.get("usable_for_relocation")
        and row.get("drive_letter") != estate.get("current_drive")
    ]
    expected_verdict = "RELOCATION_AVAILABLE" if qualifying else "NO_VOLUME_WITH_CAPACITY"
    check(
        "storage_verdict_follows_from_the_estate",
        estate.get("verdict") == expected_verdict,
        f"verdict {estate.get('verdict')}, {len(qualifying)} qualifying volume(s)",
    )

    # 9. No mechanism is called viable unless a probe exercised it.
    exercised = {
        str(probe.get("mechanism"))
        for probe in probes.get("probes") or []
        if probe.get("verdict") == "VIABLE"
    }
    mechanisms = (probes.get("classification") or {}).get("mechanisms") or {}
    overstated = [
        name
        for name, row in mechanisms.items()
        if row.get("verdict") == "VIABLE" and name not in exercised
    ]
    check(
        "no_mechanism_is_viable_without_a_probe_that_earned_it",
        not overstated,
        f"viable {sorted(n for n, r in mechanisms.items() if r.get('verdict') == 'VIABLE')}; "
        f"exercised {sorted(exercised)}",
    )

    # 10. The economic certificate is reported as stale by provenance, with both digests.
    stale = bool(diagnosis.get("recorded_digest_matches_head") is False)
    check(
        "the_stale_certificate_is_diagnosed_and_not_silenced",
        stale
        and diagnosis.get("recorded_digest")
        and diagnosis.get("digest_at_head")
        and diagnosis.get("substance_changed") is False,
        f"recorded {str(diagnosis.get('recorded_digest'))[:12]} vs head "
        f"{str(diagnosis.get('digest_at_head'))[:12]}, substance changed "
        f"{diagnosis.get('substance_changed')}",
    )

    # 11. Nothing in the package claims a promotion or a readiness.
    corpus = "\n".join(
        (report / name).read_text(encoding="utf-8", errors="replace")
        for name in REQUIRED_DELIVERABLES
    )
    claimed = [token for token in FORBIDDEN_CLAIMS if token in corpus]
    check(
        "no_deliverable_claims_a_promotion_or_a_readiness",
        not claimed,
        f"forbidden claims found: {claimed}" if claimed else "no readiness or promotion claim",
    )

    failures = [row["name"] for row in checks if not row["passed"]]
    return {
        "schema_version": VERIFIER_SCHEMA,
        "verdict": "VERIFY_PASS" if not failures else "VERIFY_FAIL",
        "checks": checks,
        "failures": failures,
        "re_derivation": {
            key: own[key]
            for key in (
                "expected",
                "answered",
                "consumed",
                "refused",
                "causes",
                "phase",
                "window_from",
                "window_to",
            )
        },
        "hypothetical": True,
        "order_sent": False,
    }


def _frozen_digest(repo: Path) -> dict[str, Any]:
    """Re-hash the frozen ruleset here, without the modules that publish it."""
    try:
        sys.path.insert(0, str(repo / "src"))
        from trading_bot.research.edge01.candidates import FROZEN_PARAMS

        canonical = json.dumps(FROZEN_PARAMS, sort_keys=True, separators=(",", ":"))
        return {"params_hash": hashlib.sha256(canonical.encode("utf-8")).hexdigest()}
    except Exception as exc:  # the check reports the failure rather than passing quietly
        return {"params_hash": None, "error": f"{type(exc).__name__}: {exc}"}


# -- the sabotage matrix ------------------------------------------------------------ #


def _sabotages() -> list[tuple[str, str]]:
    """(name, mutation) pairs. Each one makes a check's claim false on purpose."""
    return [
        ("claim_one_more_trigger", "expected"),
        ("claim_no_trigger_was_lost", "no_loss"),
        ("flip_a_consumed_tick_into_a_refusal", "flip_outcome"),
        ("delete_a_logon_so_an_absence_disappears", "drop_logon"),
        ("invent_a_sleep_that_nobody_recorded", "invent_sleep"),
        ("corrupt_a_snapshot_digest", "corrupt_digest"),
        ("call_a_mechanism_viable_without_a_probe", "overstate_mechanism"),
        ("silence_the_stale_certificate", "hide_stale_certificate"),
        ("break_a_day_so_its_columns_do_not_add_up", "break_day"),
        ("publish_a_readiness_claim", "claim_readiness"),
    ]


def _mutate(report: Path, name: str, target: str) -> None:
    """Apply one mutation to files under ``report`` (used on a throwaway copy only)."""
    audit_path = report / "evidence" / "EDGE04R_CONTINUITY_AUDIT.json"
    probes_path = report / "evidence" / "SESSION_INDEPENDENCE.json"
    diag_path = report / "evidence" / "ECONOMIC_CERTIFICATE_DIAGNOSIS.json"
    manifest_path = report / "evidence" / "SNAPSHOT.json"
    if target == "expected":
        doc = _load(audit_path)
        doc["trigger_loss"]["expected"] += 1
        audit_path.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
    elif target == "no_loss":
        doc = _load(audit_path)
        doc["trigger_loss"]["total_lost"] = 0
        doc["trigger_loss"]["never_answered"] = 0
        doc["trigger_loss"]["causes"] = {}
        audit_path.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
    elif target == "flip_outcome":
        path = report / "evidence" / "RUN_LOG_SNAPSHOT.jsonl"
        rows = _rows(path)
        for row in rows:
            if str(row.get("outcome")) == "OBSERVED":
                row["outcome"] = "DISK_BUDGET_EXCEEDED"
                break
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    elif target == "drop_logon":
        # Every record that says a session came back, not just the first one: deleting one
        # of the two logon events would leave the absence unchanged and the sabotage would
        # be a no-op that looks like a check unable to fail.
        path = report / "evidence" / "OS_CONTINUITY_EVIDENCE.json"
        doc = _load(path)
        doc["sessions"] = [
            row for row in doc.get("sessions") or [] if int(row.get("id") or 0) not in (21, 22, 25)
        ]
        doc["winlogon"] = [
            row for row in doc.get("winlogon") or [] if int(row.get("id") or 0) != 7001
        ]
        path.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
    elif target == "invent_sleep":
        path = report / "evidence" / "OS_CONTINUITY_EVIDENCE.json"
        doc = _load(path)
        doc.setdefault("power", []).append(
            {"at": "2026-10-14T22:00:00Z", "id": 42, "message": "invented"}
        )
        active = _load(report / "evidence" / "EDGE04R_CONTINUITY_AUDIT.json")
        active["trigger_loss"]["causes"]["SLEEP"] = 3
        (report / "evidence" / "EDGE04R_CONTINUITY_AUDIT.json").write_text(
            json.dumps(active, indent=2, sort_keys=True), encoding="utf-8"
        )
        path.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
    elif target == "corrupt_digest":
        doc = _load(manifest_path)
        first = sorted(doc["files"])[0]
        doc["files"][first]["sha256"] = "0" * 64
        manifest_path.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
    elif target == "overstate_mechanism":
        doc = _load(probes_path)
        doc["classification"]["mechanisms"]["WINDOWS_SERVICE"] = {
            "mechanism": "WINDOWS_SERVICE",
            "verdict": "VIABLE",
            "detail": "claimed viable without a probe",
        }
        probes_path.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
    elif target == "hide_stale_certificate":
        doc = _load(diag_path)
        doc["recorded_digest_matches_head"] = True
        diag_path.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
    elif target == "break_day":
        doc = _load(audit_path)
        doc["daily"][0]["consumed"] += 5
        doc["daily"][0]["unaccounted"] = 5
        audit_path.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
    elif target == "claim_readiness":
        (report / "FINAL_REPORT.md").write_text(
            (report / "FINAL_REPORT.md").read_text(encoding="utf-8") + "\nPAPER_READY\n",
            encoding="utf-8",
        )
    else:  # pragma: no cover - a typo in the matrix is a bug, not a passing test
        raise ValueError(f"unknown sabotage target {target!r}")


def self_test(report: Path, *, repo: Path, scratch: Path) -> dict[str, Any]:
    """Apply every sabotage to a copy and require the verifier to notice each one.

    The copy is made outside the package being copied — a scratch directory *inside* it
    would be copied into itself — and the working trees a previous pass may have left
    behind are skipped by name.
    """
    import shutil
    import tempfile

    applied: list[str] = []
    detected: list[str] = []
    undetected: list[str] = []
    ignore = shutil.ignore_patterns("edge04r-self-test-*", "tmp*")
    for name, target in _sabotages():
        with tempfile.TemporaryDirectory(prefix="edge04r-self-test-", dir=scratch) as tmp:
            copy_root = Path(tmp) / "package"
            shutil.copytree(report, copy_root, dirs_exist_ok=True, ignore=ignore)
            _mutate(copy_root, name, target)
            outcome = run_checks(copy_root, repo=repo)
            applied.append(name)
            if outcome["verdict"] == "VERIFY_FAIL":
                detected.append(name)
            else:
                undetected.append(name)
    return {
        "applied": len(applied),
        "detected": len(detected),
        "undetected": len(undetected),
        "sabotages": {name: (name in detected) for name in applied},
        "undetected_names": undetected,
        "verdict": "SELF_TEST_PASS" if not undetected else "SELF_TEST_FAIL",
    }


def _git(repo: Path, *args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", *args], cwd=repo, capture_output=True, text=True, check=False, timeout=60
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return proc.stdout.strip()


def build_economic_diagnosis(*, repo: Path) -> dict[str, Any]:
    """Where the stale certificate came from, with both digests and both commits."""
    rel = "data/recovery/ACTIVE_ECONOMIC_AUDIT.json"
    record_rel = "data/recovery/wp7/COST_BARRIER_CERTIFICATION.json"
    record_path = repo / record_rel
    audit_path = repo / rel
    payload: dict[str, Any] = {
        "schema_version": "EDGE04R_ECONOMIC_CERTIFICATE_DIAGNOSIS_V1",
        "artefact": rel,
        "certificate": record_rel,
        "hypothetical": True,
        "order_sent": False,
    }
    if not record_path.is_file() or not audit_path.is_file():
        payload["verdict"] = "NOT_EXERCISED"
        payload["reason"] = "the certificate or its input is not in this checkout"
        return payload
    record = _load(record_path)
    recorded = (record.get("evidence_digests") or {}).get(rel)
    head_digest = _lf_sha(audit_path.read_bytes())
    cert_commit = _git(repo, "log", "--format=%H", "-1", "--", record_rel)
    regen_commit = _git(repo, "log", "--format=%H", "-1", "--", rel)
    at_cert = subprocess.run(
        ["git", "show", f"{cert_commit}:{rel}"], cwd=repo, capture_output=True, check=False
    ).stdout
    before = json.loads(at_cert.decode("utf-8")) if at_cert else {}
    after = _load(audit_path)
    changed: list[str] = []
    for key in sorted(set(_flatten(before)) | set(_flatten(after))):
        if key.endswith("generated_at_utc"):
            continue
        if _flatten(before).get(key) != _flatten(after).get(key):
            changed.append(key)
    economic_keys = [
        key for key in changed if not key.startswith(("local_observations", "branch", "head"))
    ]
    payload.update(
        {
            "recorded_digest": recorded,
            "digest_at_head": head_digest,
            "recorded_digest_matches_head": recorded == head_digest,
            "digest_at_the_certificate_commit": _lf_sha(at_cert) if at_cert else None,
            "certificate_commit": cert_commit[:12] if cert_commit else None,
            "regenerating_commit": regen_commit[:12] if regen_commit else None,
            "changed_leaf_values": len(changed),
            "economic_leaf_values_changed": economic_keys,
            "substance_changed": bool(economic_keys),
            "verdict": "STALE_BY_PROVENANCE" if recorded != head_digest else "CURRENT",
            "handling": (
                "declared, not silenced: re-issuing the certificate belongs to the work package that "
                "owns it, and editing the recorded digest to match HEAD would replace evidence with "
                "an assertion that no longer has a commit behind it"
            ),
        }
    )
    return payload


def _flatten(document: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(document, dict):
        for key, value in document.items():
            out.update(_flatten(value, f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(document, list):
        out[prefix] = f"list[{len(document)}]"
        for index, value in enumerate(document):
            out.update(_flatten(value, f"{prefix}[{index}]"))
    else:
        out[prefix] = document
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--reports", default=str(REPO_ROOT / "reports" / "edge-recovery" / "WP-EDGE-04R")
    )
    parser.add_argument("--repo", default=str(REPO_ROOT))
    parser.add_argument("--self-test", action="store_true", help="run the sabotage matrix too")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = Path(args.reports)
    repo = Path(args.repo)
    diagnosis = build_economic_diagnosis(repo=repo)
    (report / "evidence" / "ECONOMIC_CERTIFICATE_DIAGNOSIS.json").write_text(
        json.dumps(diagnosis, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    result = run_checks(report, repo=repo)
    if args.self_test:
        import shutil
        import tempfile

        scratch = Path(tempfile.mkdtemp(prefix="edge04r-verify-"))
        try:
            result["self_test"] = self_test(report, repo=repo, scratch=scratch)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
        if result["self_test"]["verdict"] != "SELF_TEST_PASS":
            result["verdict"] = "VERIFY_FAIL"
    result["economic_certificate"] = {
        "verdict": diagnosis.get("verdict"),
        "recorded_digest": diagnosis.get("recorded_digest"),
        "digest_at_head": diagnosis.get("digest_at_head"),
    }
    (report / "VERIFICATION.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["verdict"] == "VERIFY_PASS" else 5
    print(f"verdict      {result['verdict']}")
    for row in result["checks"]:
        print(f"  {'PASS' if row['passed'] else 'FAIL'}  {row['name']}")
    if "self_test" in result:
        test = result["self_test"]
        print(
            f"self-test    {test['verdict']} {test['detected']}/{test['applied']} sabotages detected"
        )
        if test["undetected_names"]:
            print(f"  undetected {test['undetected_names']}")
    print(f"certificate  {diagnosis.get('verdict')}")
    return 0 if result["verdict"] == "VERIFY_PASS" else 5


if __name__ == "__main__":
    raise SystemExit(main())
