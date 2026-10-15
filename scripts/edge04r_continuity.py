"""WP-EDGE-04R — attribute every trigger the forward lane lost, from the host's own record.

    python scripts/edge04r_continuity.py                    collect, audit, render
    python scripts/edge04r_continuity.py --collect-only      collect the host evidence
    python scripts/edge04r_continuity.py --offline           re-derive from the stored evidence
    python scripts/edge04r_continuity.py --offline --until <instant>   re-derive at a named instant
    python scripts/edge04r_continuity.py --json              print the audit itself

The stored evidence is what makes the reading re-checkable: ``--offline`` re-derives
every number from ``OS_CONTINUITY_EVIDENCE.json`` and the lane's own log, so a reader
who does not have this host can still reproduce, or contradict, the verdict. Every
figure in the audit is a function of the frozen inputs *and one instant*: with the
instant declared, the file reproduces byte for byte. An offline run with no ``--until``
reads that instant back from the audit it is re-deriving, rather than defaulting to the
clock, so the reading reproduces the record instead of growing by however long the
reader took to reach the command.

Read-only with respect to the host and the lane: it never writes inside the state
root, never touches a slot ledger and never re-registers anything.

Research only: public market data, no credentials, no orders, no capital.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.research.edge03 import autonomous  # noqa: E402
from trading_bot.research.edge03.forward_plan import (  # noqa: E402
    MIN_OBSERVATION_DAYS,
    OBSERVATION_COVERAGE,
)
from trading_bot.research.edge04r import continuity, os_evidence  # noqa: E402

DEFAULT_STATE_ROOT = REPO_ROOT / "data" / "forward" / "edge04"
DEFAULT_REPORTS = REPO_ROOT / "reports" / "edge-recovery" / "WP-EDGE-04R"
EVIDENCE_FILENAME = "OS_CONTINUITY_EVIDENCE.json"
AUDIT_FILENAME = "EDGE04R_CONTINUITY_AUDIT.json"
MARKDOWN_FILENAME = "AVAILABILITY.md"


def _repo_path(value: str | Path) -> Path:
    """Resolve a declared path against the repository root, not against whatever the cwd is.

    The declared reproduction command runs from the repository root and a reader may run it
    from anywhere else, so a relative path taken from the caller's cwd would resolve to a
    different place on each run -- and the snapshot written under one would not be the one
    the next command reads. Anchoring to ``REPO_ROOT`` makes the reading independent of the
    directory it was taken from.
    """
    candidate = Path(value)
    return candidate if candidate.is_absolute() else REPO_ROOT / candidate


def _until_ms(declared: str | None, *, offline: bool, audit_path: Path) -> int:
    """The instant the reading ends at: declared, or read back from the record it re-derives.

    Every figure in this audit is a function of the frozen inputs and this one instant.
    Defaulting to *now* on an offline run puts a number into the re-derivation that no frozen
    input contains: the window grows by however long the reader took to reach the command and
    every count moves with it, so a sound record reads as one that cannot be reproduced. An
    offline run without ``--until`` therefore reads the instant back from the audit it is
    re-deriving; a run that means to take a *new* reading declares a new one.
    """
    if declared:
        return int(datetime.fromisoformat(declared.replace("Z", "+00:00")).timestamp() * 1000)
    if offline and audit_path.is_file():
        recorded = (json.loads(audit_path.read_text(encoding="utf-8")).get("window") or {}).get(
            "to_utc"
        )
        if recorded:
            print(f"window end    read back from the record: {recorded}")
            return int(
                datetime.fromisoformat(str(recorded).replace("Z", "+00:00")).timestamp() * 1000
            )
    return _now_ms()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )


def _snapshot(evidence_dir: Path, *, state_root: Path) -> dict[str, Any]:
    """Copy the raw inputs the reading was taken from, and pin them by digest.

    Without the tick log, the audit is a document about itself: the verifier could check
    that its numbers agree with each other but not that they came from the lane. The copy
    is byte-for-byte (no line-ending translation) and each file carries its sha256 here.
    """
    evidence_dir.mkdir(parents=True, exist_ok=True)
    copies: dict[str, Path] = {}
    runs = state_root / "runs.jsonl"
    if runs.is_file():
        target = evidence_dir / "RUN_LOG_SNAPSHOT.jsonl"
        target.write_bytes(runs.read_bytes())
        copies["RUN_LOG_SNAPSHOT.jsonl"] = target
    slots = state_root / "slots.jsonl"
    if slots.is_file():
        target = evidence_dir / "SLOT_LEDGER_SNAPSHOT.jsonl"
        target.write_bytes(slots.read_bytes())
        copies["SLOT_LEDGER_SNAPSHOT.jsonl"] = target
    manifest = {
        "schema_version": "EDGE04R_SNAPSHOT_V1",
        "generated_at_utc": _iso_now(),
        "source": "the live lane state root, copied without translation",
        "files": {
            name: {
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "sha256_lf": hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
                "copied_from": str(
                    state_root
                    / name.replace("RUN_LOG_SNAPSHOT", "runs").replace(
                        "SLOT_LEDGER_SNAPSHOT", "slots"
                    )
                ),
            }
            for name, path in sorted(copies.items())
        },
        "hypothetical": True,
        "order_sent": False,
    }
    _write_json(evidence_dir / "SNAPSHOT.json", manifest)
    return manifest


def _iso_now() -> str:
    import datetime as dt

    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _measure_lane_bytes(state_root: Path, store_root: Path) -> int:
    total = 0
    for root in (state_root, store_root):
        if root.is_dir():
            total += sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
    return total


def _lane_bytes(
    state_root: Path,
    store_root: Path,
    *,
    live: bool,
    evidence: dict[str, Any],
) -> int:
    """The lane tree's size, pinned to the evidence when the reading is re-derived.

    The byte count is the one figure in this audit that cannot come out of the tick log: it
    is a fact about the tree the lane is writing to *now*, and the lane keeps writing. That
    makes it the one number that would move the committed audit on a re-run, so it is
    recorded in ``OS_CONTINUITY_EVIDENCE.json`` beside the other host readings -- by the
    live pass, at the instant it read it -- and a re-derivation reads it back instead of
    measuring again. Measuring again here is how a reproduction command starts disagreeing
    with the record it reproduces.
    """
    recorded = (evidence.get("lane") or {}).get("bytes")
    if not live and isinstance(recorded, int):
        return recorded
    return _measure_lane_bytes(state_root, store_root)


def _render_markdown(audit: dict[str, Any], evidence: dict[str, Any]) -> str:
    window = audit["window"]
    loss = audit["trigger_loss"]
    availability = audit["availability"]
    causes = loss["causes"]
    counts = availability["windows"]["counts"]
    storage = audit["storage"]
    pressure = storage["pressure"]
    estate = storage["estate"]

    lines = [
        "# WP-EDGE-04R — availability of the forward observer, and why triggers were lost",
        "",
        "Every number below is re-derivable offline from `evidence/"
        + EVIDENCE_FILENAME
        + "` and the lane's own tick log.",
        "",
        "## 1. The window",
        "",
        "| | |",
        "| --- | --- |",
        f"| From | {window['from_utc']} |",
        f"| To | {window['to_utc']} |",
        f"| Length | {window['hours']} h |",
        f"| Schedule interval | {window['interval_seconds']} s |",
        f"| Measured phase | +{window['phase_offset_ms']} ms into the interval |",
        "",
        "## 2. Trigger loss, attributed",
        "",
        "| | count |",
        "| --- | --- |",
        f"| Expected trigger instants | {loss['expected']} |",
        f"| Answered by a tick | {loss['answered_by_a_tick']} |",
        f"| Of those, fired and refused | {loss['refused_after_firing']} |",
        f"| Never answered by any process | {loss['never_answered']} |",
        f"| **Total lost** | **{loss['total_lost']}** |",
        "",
        "| Cause of a trigger that no process answered | instants |",
        "| --- | --- |",
    ]
    for cause in sorted(causes):
        lines.append(f"| `{cause}` | {causes[cause]} |")
    lines += [
        "",
        f"Recorded host states behind those buckets: {counts['boots']} boots, "
        f"{counts['shutdowns']} shutdowns, {counts['session_transitions']} session transitions, "
        f"**{counts['sleep_resume_pairs']} sleep/resume pairs**.",
        "",
        "> A local sleep hypothesis would need a sleep record. There were "
        f"{counts['sleep_resume_pairs']}.",
        "",
        "## 3. Availability",
        "",
        "| | |",
        "| --- | --- |",
        f"| Host down | {availability['host_down_hours']} h |",
        f"| Host up, no interactive session | {availability['session_absent_hours']} h |",
        f"| Schedulable fraction of the window | {availability['schedulable_fraction']} |",
        "",
        "| absence window | reason | seconds | first tick after | recovery latency |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in availability["recovery"][:12]:
        lines.append(
            f"| {row['window_from_utc']} → {row['window_to_utc']} | {row['reason']} | "
            f"{row['seconds']} | {row['first_tick_after_utc']} | {row['recovery_latency_seconds']} s |"
        )
    lines += [
        "",
        "## 4. Per-day reading",
        "",
        "| day | expected | consumed | refused | no session | host down | sleep | silent | coverage of expected |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in audit["daily"]:
        lines.append(
            f"| {row['day']} | {row['expected']} | {row['consumed']} | {row['refused']} | "
            f"{row['no_session']} | {row['host_down']} | {row['sleep']} | {row['silent']} | "
            f"{row['coverage_of_expected']} |"
        )
    lines += [
        "",
        "## 5. Storage",
        "",
        "| | |",
        "| --- | --- |",
        f"| Tick storage readings | {pressure['samples']} |",
        f"| Lowest free space seen | {pressure['minimum_free_gib']} GiB at {pressure['first_utc']} |",
        f"| Hours below the critical floor | {pressure['hours_in_critical']} |",
        f"| Ticks refused by the guard | {pressure['refused_ticks']} |",
        f"| Lane tree | {round(estate['lane_bytes'] / 1024**2, 2)} MiB of a declared "
        f"{round(estate['lane_budget_bytes'] / 1024**2, 0)} MiB budget |",
        f"| Relocation verdict | `{estate['verdict']}` |",
        "",
        "| volume | filesystem | capacity GiB | free GiB | used % |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in estate["volumes"]:
        lines.append(
            f"| {row['drive_letter'] or '(none)'} {row['label']} | {row['file_system']} | "
            f"{row['capacity_gib']} | {row['free_gib']} | {row['used_percent']} |"
        )
    lines += [
        "",
        f"Physical disks: {len(estate['physical_disks'])} — "
        + ", ".join(
            f"{disk['friendly_name']} ({disk['media_type']}, {disk['size_gib']} GiB)"
            for disk in estate["physical_disks"]
        ),
        "",
        "## 6. Checks",
        "",
        "| check | verdict | detail |",
        "| --- | --- | --- |",
    ]
    for check in audit["checks"]:
        lines.append(
            f"| `{check['name']}` | {'PASS' if check['passed'] else 'FAIL'} | {check['detail']} |"
        )
    lines += [
        "",
        f"**Audit verdict: `{audit['verdict']}`.**",
        "",
        "## 7. Re-checking this reading",
        "",
        "```bash",
        "python scripts/edge04r_continuity.py --offline --reports reports/edge-recovery/"
        f"WP-EDGE-04R --until {window['to_utc']}",
        "python scripts/edge04r_verify.py --reports reports/edge-recovery/WP-EDGE-04R --repo .",
        "```",
        "",
        "The instant is declared because it is part of what the record says: the same frozen "
        "inputs plus this instant reproduce `evidence/" + AUDIT_FILENAME + "` byte for byte, "
        "while the same command without it would end the window at whatever time the reader "
        "happened to run it. An offline run with no `--until` reads the instant back from that "
        "same file, so it reproduces the record it re-derives; a new reading declares a new one.",
        "",
        f"Host evidence collected at {evidence.get('host', {}).get('collected_at_utc')} on "
        f"{evidence.get('host', {}).get('name')}; errors in that collection: "
        f"{len(evidence.get('errors') or [])}.",
        "",
        "Research only: hypothetical marks, no orders, no capital, no promotion.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--state-root", default=str(DEFAULT_STATE_ROOT))
    parser.add_argument("--store-root", default=None)
    parser.add_argument(
        "--evidence", default=None, help="use this evidence file instead of the host"
    )
    parser.add_argument("--offline", action="store_true", help="require stored evidence")
    parser.add_argument("--reports", default=str(DEFAULT_REPORTS))
    parser.add_argument("--collect-only", action="store_true")
    parser.add_argument("--json", action="store_true", help="print the audit")
    parser.add_argument(
        "--until",
        default=None,
        help="declare the instant the reading ends at (ISO-8601 UTC), so a re-run reproduces it",
    )
    parser.add_argument(
        "--stored-snapshot",
        action="store_true",
        help="re-derive from the committed run-log snapshot instead of re-copying the live lane",
    )
    args = parser.parse_args(argv)

    state_root = _repo_path(args.state_root)
    store_root = (
        _repo_path(args.store_root)
        if args.store_root
        else REPO_ROOT / "data" / "forward" / "edge03"
    )
    reports = _repo_path(args.reports)
    evidence_path = (
        _repo_path(args.evidence) if args.evidence else reports / "evidence" / EVIDENCE_FILENAME
    )

    errors: list[str] = []
    evidence: dict[str, Any]
    measuring_live = not (args.evidence or args.offline)
    if args.evidence:
        evidence = os_evidence.load(evidence_path)
    elif args.offline:
        if not evidence_path.is_file():
            print(f"no stored evidence at {evidence_path}", file=sys.stderr)
            return 3
        evidence = os_evidence.load(evidence_path)
    else:
        evidence = os_evidence.collect()
        if not evidence.get("supported"):
            _write_json(evidence_path, evidence)
            return 4
        errors = list(evidence.get("errors") or [])
        # The lane tree's size is read here, once, and written down with the instant it was
        # read: it is the only figure in this audit that a re-run would otherwise move.
        evidence["lane"] = {
            "state_root": str(state_root),
            "store_root": str(store_root),
            "bytes": _measure_lane_bytes(state_root, store_root),
            "measured_at_utc": _iso_now(),
            "note": (
                "a live reading of the tree the lane writes to, pinned so a re-derivation "
                "reads it back instead of measuring a tree the lane has kept growing"
            ),
        }
        _write_json(evidence_path, evidence)

    evidence_dir = reports / "evidence"
    # A re-derivation reads the committed snapshot, and only a live pass re-copies it. Reading
    # the live file here instead would contradict the word offline twice over: the audit would
    # be a reading of a lane that kept ticking while the report was written, and the copy of it
    # would overwrite the very snapshot a reader is meant to reproduce -- so the command that
    # is published as the way to check this reading would silently replace its input.
    use_stored_snapshot = args.stored_snapshot or not measuring_live
    if use_stored_snapshot:
        # The stored copy is read in place of the live file, so the reading does not drift
        # with a lane that keeps ticking while the report is being written: the committed
        # snapshot, plus the declared instant, is the whole input.
        snapshot_state = Path(tempfile.mkdtemp(prefix="edge04r-snapshot-"))
        for name, live_name in (
            ("RUN_LOG_SNAPSHOT.jsonl", "runs.jsonl"),
            ("SLOT_LEDGER_SNAPSHOT.jsonl", "slots.jsonl"),
        ):
            stored = evidence_dir / name
            if not stored.is_file():
                print(f"no stored snapshot at {stored}", file=sys.stderr)
                return 3
            (snapshot_state / live_name).write_bytes(stored.read_bytes())
        state_root = snapshot_state

    install_path = state_root / "install.json"
    interval_seconds = autonomous.SCHEDULE_INTERVAL_SECONDS
    if install_path.is_file():
        loaded = json.loads(install_path.read_text(encoding="utf-8"))
        interval_seconds = int(loaded.get("interval_minutes") or interval_seconds // 60) * 60

    audit = continuity.audit(
        runs_path=state_root / "runs.jsonl",
        slots_path=state_root / "slots.jsonl",
        evidence=evidence,
        interval_seconds=interval_seconds,
        until_ms=_until_ms(
            args.until, offline=not measuring_live, audit_path=reports / "evidence" / AUDIT_FILENAME
        ),
        # The lane's byte count is pinned in the evidence when this is a re-derivation and
        # re-measured only by a live pass, so the declared reproduction command reproduces
        # this file rather than a slightly larger one.
        lane_bytes=_lane_bytes(state_root, store_root, live=measuring_live, evidence=evidence),
        lane_budget_bytes=autonomous.LANE_BUDGET_BYTES,
        critical_bytes=autonomous.DISK_CRITICAL_BYTES,
        warning_bytes=autonomous.DISK_WARNING_BYTES,
        coverage_required=OBSERVATION_COVERAGE,
        forward_days_required=MIN_OBSERVATION_DAYS,
        current_drive=str(state_root.drive) or "C:",
    )
    if errors:
        audit["host_evidence_errors"] = errors
    if use_stored_snapshot:
        snapshot = json.loads((evidence_dir / "SNAPSHOT.json").read_text(encoding="utf-8"))
    else:
        snapshot = _snapshot(evidence_dir, state_root=state_root)
    _write_json(evidence_dir / AUDIT_FILENAME, audit)
    audit["snapshot"] = {name: row["sha256"] for name, row in snapshot["files"].items()}
    _write_json(reports / "evidence" / AUDIT_FILENAME, audit)
    (reports / MARKDOWN_FILENAME).write_text(_render_markdown(audit, evidence), encoding="utf-8")
    if args.json:
        print(json.dumps(audit, indent=2, sort_keys=True, default=str))
        return 0
    loss = audit["trigger_loss"]
    print(f"window        {audit['window']['from_utc']} -> {audit['window']['to_utc']}")
    print(f"instants      {loss['expected']} expected, {loss['answered_by_a_tick']} answered")
    print(
        f"lost          {loss['total_lost']} ({loss['refused_after_firing']} refused after firing)"
    )
    print(f"schedulable   {audit['availability']['schedulable_fraction']} of the window")
    print(f"causes        {loss['causes']}")
    print(f"storage       {audit['storage']['estate']['verdict']}")
    print(f"verdict       {audit['verdict']}")
    if args.collect_only:
        print(f"evidence      {evidence_path}")
    return 0 if audit["verdict"] == "AUDIT_PASS" else 5


def _now_ms() -> int:
    import time

    return int(time.time() * 1000)


if __name__ == "__main__":
    raise SystemExit(main())
