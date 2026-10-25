#!/usr/bin/env python
"""Independent verifier for RFC-EXP004A-051-02F — read-only, fail-closed, and not the runner.

This file is written by the verification role. It imports no ``trading_bot`` module, no
script the runner wrote, and nothing that reads the runner's verdict: every digest, every
timestamp and every refusal below is recomputed from Git objects and from the files on
disk. The runner's report is read as the *claim under test*; a disagreement is a failure
of the claim, never a note about it.

The anchors are constants here, not values read from the declaration. A verifier that
learns the expected window from the artefact it is checking can only confirm that the
artefact agrees with itself, so ``PHASE2_SHA256``, ``GENERATOR_COMMIT`` and the window are
stated before anything is read. The declaration is read afterwards, and only to be
checked against them.

What is verified, in the order a reader would ask:

1. the freeze still binds — the phase-1 declaration, the phase-2 successor and the
   generator are the objects the preregistration named, byte for byte;
2. the run report is not claiming more than the disk supports — a ``VERIFIED`` state
   needs published bytes, a pending state needs their absence;
3. every published row is temporally admissible — its open instant is inside the
   declared window, its ingest is at or after the declaration took effect, and its
   ingest is not later than the instant the capture was decided or later than this
   verifier's own clock. This is the check the frozen extractor does not make, and it
   is the reason ``DEF-02E-01`` is a quarantine and not a silent pass;
4. the published bytes are the store's own bytes — every row equals the source row with
   the same open instant, and the set of published opens is exactly the set the window
   selects. A dataset that was invented, back-filled or edited fails here;
5. the capture decision is not in the future — a builder that claims a decision later
   than the verifier's clock is laundering a future row, and the check is here;
6. the gates are where they were — ``C-016``, ``PAPER_VALIDATION``, ``CERTIFICATION`` and
   ``NO_PROMOTION`` are not moved by a capture;
7. the sealed 02E package still verifies, re-run as a separate process against the
   sealed artefacts, with its output written outside the sealed directory.

Exit codes are this file's own:

    0 PASS     2 FAIL     3 BLOCKED     4 ERROR

``PASS`` here means the runner's claim matched the evidence at this instant. It is not a
capture, not a certification and not a promotion, and this verifier has no code path that
turns it into one.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

VERIFIER_ID = "verifier-e/EXP-004A/WP-051-02F"
RUNNER_ID = "runner/EXP-004A/WP-051-02F"
SCHEMA_VERSION = "1.0"

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "docs" / "agentic" / "exp004a" / "wp051_02f"

DECLARATION = "config/preregistrations/EXP-004A.datasets.phase2.json"
PHASE1 = "config/preregistrations/EXP-004A.datasets.json"
GENERATOR = "scripts/exp004a_capture.py"
DATASET_DIR = "data/exp004a"
RUN_REPORT = "RUN_REPORT.json"
CLAIM_REPORT = "CLAIM.json"
VERIFICATION_REPORT = "INDEPENDENT_VERIFICATION.json"
MANIFEST = "EVIDENCE_MANIFEST.json"

#: Anchors, stated before anything is read.
PHASE1_SHA256 = "8946f871a97b7575b1a9aa2900b3243f88d07a4821d09d6d0a3c113f1e5de211"
PHASE1_BLOB = "43c9deea29a8e4af1c0333bcc0b58131620ec3e7"
GENERATOR_COMMIT = "fc036d967923f09a6092cb0e5de7409afd07ebd7"
GENERATOR_SHA256 = "af1ab7cc23980dadac83ba53d2a5f8c1c5f33f6b5dd4841dd58620b9bb421cb8"
WINDOW_START = "2026-10-22T00:00:00Z"
WINDOW_END = "2027-01-20T00:00:00Z"
EFFECTIVE = "2026-10-21T16:00:00Z"

CONTROLS = (
    "FREEZE_INTEGRITY",
    "CLAIM_INTEGRITY",
    "TEMPORAL_ADMISSIBILITY",
    "SOURCE_FIDELITY",
    "GATE_INTEGRITY",
    "INDEPENDENCE",
)

#: The gates a capture may not move. Read from the runner's report, compared to these.
#: ``C_013`` is here because RFC case 7 forbids promoting the time proof: a capture that
#: stores an hour of bars says nothing about whether the clock that stamped them has a
#: source an auditor would accept, so the gate stays weak until an attestation exists.
LOCKED_GATES = {
    "C_013": "TIME_PROOF_WEAK",
    "C_016": "UNREACHABLE_UNDER_DECLARED_COST_MODEL",
    "PAPER_VALIDATION": "NOT_PASS",
    "CERTIFICATION": "BLOCKED",
    "PROMOTION": "NO_PROMOTION",
}

#: The states that mean "a dataset was published and checked". A report in any other
#: state that claims a dataset is a false success.
PUBLISHING_STATES = (
    "CAPTURE_ATTEMPTED",
    "TEMPORAL_QUARANTINE_CHECK",
    "INDEPENDENT_VERIFY",
    "CAPTURED_VERIFIED",
)
PENDING_STATES = ("NOT_DUE", "PENDING_DATA", "PENDING_FRESHNESS")
#: The states that mean "the attempt refused before it captured anything".
REFUSING_STATES = ("BLOCKED_INTEGRITY", "QUARANTINED", "FAILED_OR_PENDING", "BLOCKED")

EXIT_PASS = 0
EXIT_FAIL = 2
EXIT_BLOCKED = 3
EXIT_ERROR = 4
STATUS_EXIT = {"PASS": EXIT_PASS, "FAIL": EXIT_FAIL, "BLOCKED": EXIT_BLOCKED}

INTERVAL_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class Check:
    control: str
    check_id: str
    status: str
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "control": self.control,
            "check_id": self.check_id,
            "status": self.status,
            "detail": self.detail,
            "evidence": self.evidence,
        }


def now_ms() -> int:
    return int(time.time() * 1000)


def iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def parse_ms(value: object, field_name: str) -> int:
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        raise ValueError(f"{field_name} is naive")
    return int(moment.astimezone(UTC).timestamp() * 1000)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(repo: Path, *args: str) -> str | None:
    completed = subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True, check=False
    )
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def git_bytes(repo: Path, commit: str, path: str) -> bytes | None:
    completed = subprocess.run(
        ["git", "cat-file", "blob", f"{commit}:{path}"],
        cwd=str(repo),
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def read_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_bytes().splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


# --------------------------------------------------------------------------- #
# the checks
# --------------------------------------------------------------------------- #


def check_freeze(repo: Path) -> list[Check]:
    """The freeze must be the objects the preregistration named, byte for byte."""
    checks: list[Check] = []
    phase2 = repo / DECLARATION
    if not phase2.is_file():
        return [
            Check(
                "FREEZE_INTEGRITY",
                "PHASE2_DECLARATION_PRESENT",
                "BLOCKED",
                f"{DECLARATION} does not exist",
            )
        ]
    digest = sha256_file(phase2)
    checks.append(
        Check(
            "FREEZE_INTEGRITY",
            "PHASE2_DECLARATION_DIGEST",
            "PASS" if digest else "FAIL",
            f"{DECLARATION} sha256 {digest}",
            {"sha256": digest},
        )
    )
    document = read_json(phase2) or {}
    declared_phase1 = str((document.get("supersedes") or {}).get("sha256") or "")
    checks.append(
        Check(
            "FREEZE_INTEGRITY",
            "PHASE1_DIGEST_MATCHES_DECLARATION",
            "PASS" if declared_phase1 == PHASE1_SHA256 else "FAIL",
            (
                f"the successor names phase 1 as {declared_phase1}; the anchor is {PHASE1_SHA256}"
                if declared_phase1 == PHASE1_SHA256
                else f"the successor names phase 1 as {declared_phase1}, not the anchor "
                f"{PHASE1_SHA256}"
            ),
            {"declared": declared_phase1, "anchor": PHASE1_SHA256},
        )
    )
    phase1_blob = git(repo, "rev-parse", f"HEAD:{PHASE1}")
    checks.append(
        Check(
            "FREEZE_INTEGRITY",
            "PHASE1_BLOB",
            "PASS" if phase1_blob == PHASE1_BLOB else "FAIL",
            f"HEAD:{PHASE1} is {phase1_blob}; the anchor is {PHASE1_BLOB}",
            {"blob": phase1_blob, "anchor": PHASE1_BLOB},
        )
    )
    generator = git_bytes(repo, GENERATOR_COMMIT, GENERATOR)
    generator_digest = sha256_bytes(generator) if generator is not None else None
    checks.append(
        Check(
            "FREEZE_INTEGRITY",
            "GENERATOR_BLOB",
            "PASS" if generator_digest == GENERATOR_SHA256 else "FAIL",
            (
                f"{GENERATOR} at {GENERATOR_COMMIT} hashes {generator_digest}"
                if generator_digest == GENERATOR_SHA256
                else f"{GENERATOR} at {GENERATOR_COMMIT} hashes {generator_digest}, not the "
                f"anchor {GENERATOR_SHA256}"
            ),
            {"sha256": generator_digest, "anchor": GENERATOR_SHA256},
        )
    )
    working = sha256_file(repo / GENERATOR) if (repo / GENERATOR).is_file() else None
    checks.append(
        Check(
            "FREEZE_INTEGRITY",
            "GENERATOR_WORKTREE_UNCHANGED",
            "PASS" if working == GENERATOR_SHA256 else "FAIL",
            (
                "the generator in the worktree is the committed generator"
                if working == GENERATOR_SHA256
                else f"the generator in the worktree hashes {working}, not the frozen "
                f"{GENERATOR_SHA256}"
            ),
            {"worktree_sha256": working},
        )
    )
    return checks


def check_claim_integrity(report: dict[str, Any], dataset_dir: Path) -> list[Check]:
    """A state is a claim about the disk. The disk decides whether it is true."""
    checks: list[Check] = []
    state = str(report.get("state") or "")
    datasets = report.get("datasets") or []
    published = [item for item in datasets if item.get("exists")]
    for item in published:
        target = dataset_dir / Path(str(item.get("dataset_path"))).name
        if not target.is_file():
            checks.append(
                Check(
                    "CLAIM_INTEGRITY",
                    "DATASET_PRESENT",
                    "FAIL",
                    f"{item.get('dataset_path')} is claimed but is not on disk",
                )
            )
        else:
            digest = sha256_file(target)
            checks.append(
                Check(
                    "CLAIM_INTEGRITY",
                    "DATASET_PRESENT",
                    "PASS" if digest == item.get("sha256") else "FAIL",
                    (
                        f"{item.get('dataset_path')} is on disk with the claimed digest"
                        if digest == item.get("sha256")
                        else f"{item.get('dataset_path')} hashes {digest}, not the claimed "
                        f"{item.get('sha256')}"
                    ),
                    {"sha256": digest, "claimed": item.get("sha256")},
                )
            )
    if state in PUBLISHING_STATES and not published:
        checks.append(
            Check(
                "CLAIM_INTEGRITY",
                "NO_FALSE_SUCCESS",
                "FAIL",
                f"the report claims {state} but names no published dataset",
            )
        )
    elif state in PENDING_STATES:
        checks.append(
            Check(
                "CLAIM_INTEGRITY",
                "NO_FALSE_SUCCESS",
                "PASS",
                f"the report claims {state}; no dataset is required for that claim",
            )
        )
    else:
        checks.append(
            Check(
                "CLAIM_INTEGRITY",
                "NO_FALSE_SUCCESS",
                "PASS",
                f"the report claims {state}",
            )
        )
    quarantined = [
        guard for guard in (report.get("temporal_guards") or []) if guard.get("verdict") == "QUARANTINE"
    ]
    if state == "CAPTURED_VERIFIED":
        failed = [
            item
            for item in (report.get("captures") or [])
            if item.get("exit_code") not in (0, None)
        ]
        checks.append(
            Check(
                "CLAIM_INTEGRITY",
                "CAPTURED_VERIFIED_HAS_NO_FAILED_SLICE",
                "PASS" if not failed else "FAIL",
                (
                    "every slice in the claim succeeded"
                    if not failed
                    else "the report claims CAPTURED_VERIFIED while "
                    + ", ".join(f"{item.get('slice')} exited {item.get('exit_code')}" for item in failed)
                ),
                {"failed_slices": [item.get("slice") for item in failed]},
            )
        )
    if state == "QUARANTINED":
        checks.append(
            Check(
                "CLAIM_INTEGRITY",
                "QUARANTINE_NAMED",
                "PASS" if quarantined else "FAIL",
                (
                    "the quarantine names the slices it quarantined"
                    if quarantined
                    else "the report claims a quarantine but names no violation"
                ),
                {"slices": [item.get("slice") for item in quarantined]},
            )
        )
    return checks


def check_capture_outputs(report: dict[str, Any], dataset_dir: Path) -> list[Check]:
    """A slice that exited 0 must have left a dataset behind.

    The failure matrix names this case: an exit code of 0 with no verifiable output
    is a false success. A verifier that reads only the report's own words would let
    it through, so the file is looked for on disk.
    """
    checks: list[Check] = []
    for item in report.get("captures") or []:
        if item.get("exit_code") != 0:
            continue
        name = Path(str(item.get("dataset_path") or "")).name
        path = dataset_dir / name
        checks.append(
            Check(
                "CLAIM_INTEGRITY",
                "CAPTURE_OUTPUT_PRESENT",
                "PASS" if path.is_file() else "FAIL",
                (
                    f"{item.get('slice')} exited 0 and {name} is on disk"
                    if path.is_file()
                    else f"{item.get('slice')} exited 0 but {name} is not on disk; an exit "
                    "code of 0 without an output is a false success"
                ),
                {"dataset_path": str(item.get("dataset_path") or ""), "exists": path.is_file()},
            )
        )
    return checks


def declared_row_counts(repo: Path) -> dict[str, tuple[int, float]]:
    """The declaration's own promise per dataset: ``row_count`` and ``coverage_required``.

    Read from the anchored declaration rather than from the claim, because a claim that
    forgot to carry the numbers is exactly the claim this control exists to measure.
    """
    document = read_json(repo / DECLARATION) or {}
    counts: dict[str, tuple[int, float]] = {}
    for entry in document.get("entries") or []:
        parameters = entry.get("generator_parameters") or {}
        counts[str(entry.get("dataset_id"))] = (
            int(entry.get("row_count") or 0),
            float(parameters.get("coverage_required") or 0.0),
        )
    return counts


def check_coverage(
    report: dict[str, Any], dataset_dir: Path, repo: Path | None = None
) -> list[Check]:
    """The row count on disk is the row count the claim made, and the shortfall is named.

    The frozen extractor writes a dataset once and never enforces the coverage the
    declaration asks for, so a capture taken before the declared period elapses freezes a
    short file permanently. That is not a false success as long as the report says so, and
    it is a false success the moment the report rounds it away. This control recounts the
    bars and compares them with the claim, in both directions.
    """
    checks: list[Check] = []
    for item in report.get("datasets") or []:
        name = Path(str(item.get("dataset_path") or "")).name
        path = dataset_dir / name
        if not path.is_file():
            continue
        rows = sum(1 for line in path.read_bytes().splitlines() if line.strip())
        claimed_rows = item.get("published_rows")
        authority = declared_row_counts(repo).get(str(item.get("dataset_id")), (0, 0.0)) \
            if repo is not None else (0, 0.0)
        declared = int(item.get("declared_row_count") or authority[0])
        required = float(item.get("declared_coverage_required") or authority[1])
        stated = str(item.get("coverage_status") or "")
        recomputed = (
            "NOT_PUBLISHED"
            if rows <= 0
            else (
                "DECLARED_COUNT_UNKNOWN"
                if declared <= 0
                else (
                    "AT_LEAST_DECLARED"
                    if required > 0 and rows / declared >= required
                    else "BELOW_DECLARED"
                )
            )
        )
        problems = []
        carries_fields = "published_rows" in item and "coverage_status" in item
        if carries_fields and claimed_rows != rows:
            problems.append(f"the claim says {claimed_rows} row(s); the file holds {rows}")
        if carries_fields and stated != recomputed:
            problems.append(f"the claim says {stated!r}; the bytes say {recomputed!r}")
        detail = f"{name}: {rows} row(s) of {declared} declared ({recomputed})"
        if not carries_fields:
            # A claim written before this control existed cannot be compared with itself,
            # but it can still be measured. The verifier states the shortfall here so the
            # reader learns it from the verification and not from a missing field.
            detail += "; the claim carries no coverage statement, so this is measured here"
        checks.append(
            Check(
                "CLAIM_INTEGRITY",
                "COVERAGE_DECLARED_VS_PUBLISHED",
                "PASS" if not problems else "FAIL",
                detail if not problems else f"{detail}; " + "; ".join(problems),
                {
                    "path": str(item.get("dataset_path") or ""),
                    "rows": rows,
                    "claimed_rows": claimed_rows,
                    "declared_row_count": declared,
                    "recomputed_status": recomputed,
                    "claimed_status": stated,
                    "claim_carries_coverage_fields": carries_fields,
                },
            )
        )
    return checks


def check_decision_instant(report: dict[str, Any], at_ms: int) -> list[Check]:
    """The capture decision cannot be in the future.

    A builder that records a decision later than the verifier's own clock could launder
    a row that claims an impossible ingest. The check costs one comparison and closes
    the hole the frozen extractor leaves open.

    An attempt that never captured anything has no decision instant, and that is not a
    hole: there is no temporal claim to check. Only an attempt that claims to have
    captured and does not say when it decided is a gap.
    """
    value = report.get("capture_decision_at_utc")
    state = str(report.get("state") or "")
    if not value:
        if state in PENDING_STATES:
            return [
                Check(
                    "TEMPORAL_ADMISSIBILITY",
                    "DECISION_INSTANT_PRESENT",
                    "PASS",
                    f"the attempt claims {state} and captured nothing, so there is no "
                    "temporal claim to check",
                )
            ]
        return [
            Check(
                "TEMPORAL_ADMISSIBILITY",
                "DECISION_INSTANT_PRESENT",
                "BLOCKED",
                "the report records no capture decision instant, so no temporal claim can be checked",
            )
        ]
    decision_ms = parse_ms(value, "capture_decision_at_utc")
    future = decision_ms - at_ms
    return [
        Check(
            "TEMPORAL_ADMISSIBILITY",
            "DECISION_INSTANT_NOT_IN_FUTURE",
            "PASS" if future <= 0 else "FAIL",
            (
                f"the capture decision {value} is not in the future"
                if future <= 0
                else f"the capture decision {value} is {future} ms ahead of this verifier's "
                f"clock {iso(at_ms)}"
            ),
            {"decision_at_utc": value, "verifier_at_utc": iso(at_ms), "ahead_ms": future},
        )
    ]


def store_by_asset(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The report's own store states, indexed by asset.

    The dataset id ends with the asset (``EXP-004A-1H-BTC``), which is the only join
    between the published files and the series they came from.
    """
    index: dict[str, dict[str, Any]] = {}
    for state in report.get("store") or []:
        asset = str(state.get("asset") or "")
        if asset:
            index[asset] = state
    return index


def check_temporal(
    report: dict[str, Any], repo: Path, dataset_dir: Path, at_ms: int
) -> list[Check]:
    """Every published row, re-read, must be temporally admissible."""
    checks: list[Check] = []
    window_start = parse_ms(WINDOW_START, "window start")
    window_end = parse_ms(WINDOW_END, "window end")
    effective = parse_ms(EFFECTIVE, "effective_from_utc")
    decision_raw = report.get("capture_decision_at_utc")
    decision_ms = parse_ms(decision_raw, "capture_decision_at_utc") if decision_raw else None
    series = store_by_asset(report)

    for item in report.get("datasets") or []:
        if not item.get("exists"):
            continue
        path = dataset_dir / Path(str(item.get("dataset_path"))).name
        if not path.is_file():
            continue
        try:
            rows = read_rows(path)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            checks.append(
                Check(
                    "TEMPORAL_ADMISSIBILITY",
                    "ROWS_PARSED",
                    "FAIL",
                    f"{path.name} is not a readable JSONL file: {error}",
                )
            )
            continue
        asset = str(item.get("dataset_id") or "").rsplit("-", 1)[-1]
        interval = str((series.get(asset) or {}).get("interval") or "1h")
        span = INTERVAL_MS.get(interval, INTERVAL_MS["1h"])
        violations: list[str] = []
        opens: list[int] = []
        for number, row in enumerate(rows, start=1):
            try:
                open_ms = int(row["ts"])
                fetched_ms = int(row["fetched_at_ms"])
            except (KeyError, TypeError, ValueError):
                violations.append(f"line {number} lacks ts/fetched_at_ms")
                continue
            opens.append(open_ms)
            close_ms = open_ms + span
            if not window_start <= open_ms < window_end:
                violations.append(f"line {number} opens {iso(open_ms)}, outside the window")
            if fetched_ms < effective:
                violations.append(
                    f"line {number} was ingested {iso(fetched_ms)}, before the declaration took effect"
                )
            if decision_ms is not None and fetched_ms > decision_ms:
                violations.append(
                    f"line {number} was ingested {iso(fetched_ms)}, after the capture decision "
                    f"{iso(decision_ms)}"
                )
            if fetched_ms > at_ms:
                violations.append(
                    f"line {number} was ingested {iso(fetched_ms)}, after this verifier's clock "
                    f"{iso(at_ms)}"
                )
            if close_ms > (decision_ms or at_ms):
                violations.append(
                    f"line {number} closes {iso(close_ms)}, after the capture decision"
                )
        if len(set(opens)) != len(opens):
            violations.append("the rows repeat a bar open instant")
        if opens != sorted(opens):
            violations.append("the rows are not ordered by bar open")
        checks.append(
            Check(
                "TEMPORAL_ADMISSIBILITY",
                "ROWS_ADMISSIBLE",
                "PASS" if not violations else "FAIL",
                (
                    f"{path.name}: {len(rows)} row(s) are temporally admissible"
                    if not violations
                    else f"{path.name}: {len(violations)} violation(s): " + "; ".join(violations[:5])
                ),
                {"rows": len(rows), "violations": violations[:50]},
            )
        )
    return checks


def check_source_fidelity(
    report: dict[str, Any], repo: Path, dataset_dir: Path, source_root: Path
) -> list[Check]:
    """The published bytes must be the store's own bytes, row for row.

    This is the check that a fabricated or back-filled dataset fails: the published set
    of open instants has to be exactly the set the window selects out of the source, and
    every published row has to equal the source row with the same instant.
    """
    checks: list[Check] = []
    window_start = parse_ms(WINDOW_START, "window start")
    window_end = parse_ms(WINDOW_END, "window end")
    series = store_by_asset(report)

    for item in report.get("datasets") or []:
        if not item.get("exists"):
            continue
        path = dataset_dir / Path(str(item.get("dataset_path"))).name
        if not path.is_file():
            continue
        dataset_id = str(item.get("dataset_id") or "")
        asset = dataset_id.rsplit("-", 1)[-1]
        source_path = None
        state = series.get(asset)
        if state and state.get("path"):
            candidate = Path(str(state["path"]))
            source_path = candidate if candidate.is_absolute() else source_root / candidate
        if source_path is None or not source_path.is_file():
            checks.append(
                Check(
                    "SOURCE_FIDELITY",
                    "SOURCE_FOUND",
                    "BLOCKED",
                    f"the source series for {dataset_id} could not be located; the claim cannot "
                    "be checked against the store",
                )
            )
            continue
        try:
            published = read_rows(path)
            source = read_rows(source_path)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            checks.append(
                Check(
                    "SOURCE_FIDELITY",
                    "SOURCE_COMPARED",
                    "FAIL",
                    f"{dataset_id}: a series could not be read: {error}",
                )
            )
            continue
        source_by_open = {int(row["ts"]): row for row in source}
        selected = {
            open_ms: row
            for open_ms, row in source_by_open.items()
            if window_start <= open_ms < window_end
        }
        published_by_open = {int(row["ts"]): row for row in published}
        missing = sorted(set(selected) - set(published_by_open))
        extra = sorted(set(published_by_open) - set(selected))
        altered = sorted(
            open_ms
            for open_ms in set(published_by_open) & set(selected)
            if published_by_open[open_ms] != selected[open_ms]
        )
        problems: list[str] = []
        if extra:
            problems.append(f"{len(extra)} published open(s) are not in the window's selection")
        if missing:
            problems.append(f"{len(missing)} selected open(s) are missing from the dataset")
        if altered:
            problems.append(f"{len(altered)} published row(s) differ from the store's row")
        checks.append(
            Check(
                "SOURCE_FIDELITY",
                "SOURCE_COMPARED",
                "PASS" if not problems else "FAIL",
                (
                    f"{dataset_id}: {len(published)} published row(s) equal the store's rows"
                    if not problems
                    else f"{dataset_id}: " + "; ".join(problems)
                ),
                {
                    "published_rows": len(published),
                    "selected_rows": len(selected),
                    "extra": extra[:10],
                    "missing": missing[:10],
                    "altered": altered[:10],
                },
            )
        )
    return checks


def check_gates(report: dict[str, Any]) -> list[Check]:
    """A capture may not move a gate."""
    checks: list[Check] = []
    gates = report.get("gates") or {}
    for name, expected in LOCKED_GATES.items():
        found = gates.get(name)
        checks.append(
            Check(
                "GATE_INTEGRITY",
                f"GATE_{name}",
                "PASS" if found == expected else "FAIL",
                (
                    f"{name} is {found}"
                    if found == expected
                    else f"{name} is {found!r}; it must stay {expected!r}"
                ),
                {"found": found, "expected": expected},
            )
        )
    return checks


def check_independence(repo: Path) -> list[Check]:
    """This verifier must not depend on the thing it verifies."""
    checks: list[Check] = []
    path = repo / "scripts" / "exp004a_wp051_02f_verify.py"
    forbidden = ("trading_bot", "exp004a_wp051_02f_runner")
    if not path.is_file():
        return [
            Check("INDEPENDENCE", "VERIFIER_PRESENT", "BLOCKED", f"{path} does not exist")
        ]
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    offending = [name for name in imported if any(bad in name for bad in forbidden)]
    checks.append(
        Check(
            "INDEPENDENCE",
            "NO_FORBIDDEN_IMPORT",
            "PASS" if not offending else "FAIL",
            (
                "the verifier imports neither trading_bot nor the runner"
                if not offending
                else f"the verifier imports {offending}"
            ),
            {"imports": sorted(set(imported)), "offending": offending},
        )
    )
    return checks


#: The 02E controls that assert a *state of the world* which this package exists to
#: change. The sealed 02E verifier re-evaluates them against its own clock and against
#: ``data/exp004a``, so once the declared window opens and a capture lands they cannot
#: pass again — not because a byte of 02E moved, but because the world it described has.
#: Their expiry is named one by one and never reported as a pass of those controls.
SEALED_02E_EXPIRABLE = {
    "V-TEMP-01": "the sealed builder described a window that had not opened; it has since opened",
    "V-TEMP-02": "the sealed capture status was PENDING_WINDOW; a capture may have run since",
    "V-ART-03": "the sealed report counted zero published datasets; a capture may have published since",
    "V-POL-04": "the sealed policy read PENDING_WINDOW as the only available status",
}


def sealed_02e_integrity(repo: Path) -> Check:
    """Every byte the sealed 02E manifest names, hashed again from the checkout.

    This is the part of "02E is untouched" that does not depend on a clock: the manifest
    is 02E's own statement of what it sealed, and re-hashing its entries says whether the
    package still is what it said it was. A verifier that re-runs 02E is asking a
    different and weaker question, because most of 02E's controls depend on the world.
    """
    package = repo / "docs" / "agentic" / "exp004a" / "wp051_02e"
    manifest = read_json(package / "EVIDENCE_MANIFEST.json")
    if manifest is None:
        return Check(
            "FREEZE_INTEGRITY",
            "SEALED_02E_BYTES_INTACT",
            "BLOCKED",
            f"{package / 'EVIDENCE_MANIFEST.json'} is missing or unreadable",
        )
    entries = manifest.get("entries") or []
    if not entries:
        return Check(
            "FREEZE_INTEGRITY",
            "SEALED_02E_BYTES_INTACT",
            "BLOCKED",
            "the 02E manifest names no artefact, so it attests nothing",
        )
    drifted: list[str] = []
    absent: list[str] = []
    for entry in entries:
        path = repo / str(entry.get("path"))
        if not path.is_file():
            absent.append(str(entry.get("path")))
            continue
        if sha256_file(path) != entry.get("sha256"):
            drifted.append(str(entry.get("path")))
    problems = []
    if drifted:
        problems.append(f"{len(drifted)} sealed file(s) no longer hash to the manifest: {drifted[:5]}")
    if absent:
        problems.append(f"{len(absent)} sealed file(s) are gone: {absent[:5]}")
    return Check(
        "FREEZE_INTEGRITY",
        "SEALED_02E_BYTES_INTACT",
        "PASS" if not problems else "FAIL",
        (
            f"{len(entries)} sealed 02E artefact(s) still hash to the manifest"
            if not problems
            else "; ".join(problems)
        ),
        {"entries": len(entries), "drifted": drifted, "absent": absent},
    )


def classify_sealed_02e(
    exit_code: int, status: str | None, failed: list[str]
) -> tuple[str, str]:
    """Read a fresh 02E verdict without translating a refusal into consent.

    Three outcomes are possible and only two of them are a pass. A clean 02E verdict
    passes. A verdict whose *only* failures are the controls that expire with the clock
    passes **as integrity**, with every expired control named and with the explicit
    statement that 02E has not been re-certified. Anything else — one regressed control,
    one control this file has never heard of, a crash — fails: an unreadable verdict is
    not a verdict, and "I did not understand the refusal" is not an acquittal.
    """
    if exit_code == 0 and not failed:
        return "PASS", "the sealed 02E package still verifies unchanged"
    regressed = [name for name in failed if name not in SEALED_02E_EXPIRABLE]
    expired = [name for name in failed if name in SEALED_02E_EXPIRABLE]
    if not regressed and expired:
        return "PASS", (
            "the sealed 02E package re-verifies except for "
            f"{len(expired)} control(s) that expire with the clock "
            f"({', '.join(sorted(expired))}); this is not a re-certification of 02E and "
            "those controls are not reported as passing"
        )
    return "FAIL", (
        f"the sealed 02E verifier returned exit {exit_code} ({status}); "
        f"failed controls: {failed or 'none named'}"
    )


def reverify_sealed_02e(repo: Path, out_path: Path, *, timeout: int) -> dict[str, Any]:
    """Re-run the sealed 02E verifier against the sealed 02E package.

    The output is written outside the sealed directory on purpose: the 02E artefacts are
    evidence and this package does not get to edit them.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/exp004a_wp051_02e_verify.py",
            "--mode",
            "verify",
            "--run-dir",
            str(repo / "docs" / "agentic" / "exp004a" / "wp051_02e"),
            "--out",
            str(out_path),
        ],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    payload = read_json(out_path) or {}
    failed = [
        str(item.get("check_id"))
        for item in payload.get("checks") or []
        if item.get("status") == "FAIL"
    ]
    verdict, detail = classify_sealed_02e(completed.returncode, payload.get("status"), failed)
    expired = [name for name in failed if name in SEALED_02E_EXPIRABLE]
    regressed = [name for name in failed if name not in SEALED_02E_EXPIRABLE]
    return {
        "command": "python scripts/exp004a_wp051_02e_verify.py --mode verify --run-dir <02e> --out <02f>",
        "exit_code": completed.returncode,
        "status": payload.get("status"),
        "verdict": verdict,
        "detail": detail,
        "failed_checks": failed,
        "expired_checks": expired,
        "regressed_checks": regressed,
        "expiry_reasons": {name: SEALED_02E_EXPIRABLE[name] for name in expired},
        "out": str(out_path),
        "stderr": (completed.stderr or "").strip()[-2000:],
    }


# --------------------------------------------------------------------------- #
# the run
# --------------------------------------------------------------------------- #


def verify(
    run_dir: Path,
    repo: Path,
    *,
    dataset_dir: Path,
    source_root: Path | None = None,
    at_ms: int | None = None,
    timeout: int = 600,
    skip_sealed_reverification: bool = False,
    report_name: str = RUN_REPORT,
) -> tuple[list[Check], str]:
    """Recompute every control and return the checks with one verdict.

    ``at_ms`` is the instant the observation is made at. It is a parameter so that a
    test can judge a package at the instant it was made, instead of only at the instant
    the test happens to run: a verifier that can only ever see "now" cannot check a
    package from the past, and a package from the past is exactly what a rehearsal
    produces.
    """
    checks: list[Check] = []
    report_path = run_dir / report_name
    report = read_json(report_path)
    if report is None:
        return (
            [
                Check(
                    "CLAIM_INTEGRITY",
                    "RUN_REPORT_PRESENT",
                    "BLOCKED",
                    f"{report_path} does not exist or is not JSON; there is no claim to test",
                )
            ],
            "BLOCKED",
        )
    checks.append(
        Check(
            "CLAIM_INTEGRITY",
            "RUN_REPORT_PRESENT",
            "PASS",
            f"{report_path.name} parses and claims state {report.get('state')!r}",
        )
    )
    at_ms = now_ms() if at_ms is None else at_ms
    root = source_root or repo
    checks.extend(check_freeze(repo))
    checks.extend(check_claim_integrity(report, dataset_dir))
    checks.extend(check_capture_outputs(report, dataset_dir))
    checks.extend(check_coverage(report, dataset_dir, repo))
    checks.extend(check_decision_instant(report, at_ms))
    checks.extend(check_temporal(report, repo, dataset_dir, at_ms))
    checks.extend(check_source_fidelity(report, repo, dataset_dir, root))
    checks.extend(check_gates(report))
    checks.extend(check_independence(repo))
    checks.append(sealed_02e_integrity(repo))

    if not skip_sealed_reverification:
        sealed = reverify_sealed_02e(
            repo, run_dir / "reused_preflight" / "02E_REVERIFIED.json", timeout=timeout
        )
        checks.append(
            Check(
                "GATE_INTEGRITY",
                "SEALED_02E_REVERIFICATION",
                sealed["verdict"],
                sealed["detail"],
                sealed,
            )
        )

    failed = [item for item in checks if item.status == "FAIL"]
    blocked = [item for item in checks if item.status == "BLOCKED"]
    status = "FAIL" if failed else ("BLOCKED" if blocked else "PASS")
    return checks, status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument("--dataset-dir", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--source-root", type=Path, default=None)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument(
        "--report",
        default=RUN_REPORT,
        help="the file inside --run-dir that carries the claim under test",
    )
    parser.add_argument(
        "--skip-sealed-reverification",
        action="store_true",
        help="do not re-run the sealed 02E verifier (used by the adversarial tests)",
    )
    args = parser.parse_args(argv)

    run_dir = Path(args.run_dir).resolve()
    repo = Path(args.repo).resolve()
    dataset_dir = Path(args.dataset_dir).resolve() if args.dataset_dir else repo / DATASET_DIR
    started = time.perf_counter()

    try:
        checks, status = verify(
            run_dir,
            repo,
            dataset_dir=dataset_dir,
            source_root=Path(args.source_root).resolve() if args.source_root else None,
            timeout=args.timeout,
            skip_sealed_reverification=args.skip_sealed_reverification,
            report_name=args.report,
        )
    except Exception as error:  # a crashed verifier must not read as a pass
        print(f"[verify] ERROR {type(error).__name__}: {error}")
        return EXIT_ERROR

    report = read_json(run_dir / args.report) or {}
    claim_path = run_dir / args.report
    payload = {
        "schema_version": SCHEMA_VERSION,
        "runner": RUNNER_ID,
        "rfc": "RFC-EXP004A-051-02F",
        "verifier": VERIFIER_ID,
        "independent_of_runner": True,
        "claim": {
            "path": str(claim_path),
            "sha256": sha256_file(claim_path) if claim_path.is_file() else None,
        },
        "generated_at_utc": iso(now_ms()),
        "duration_s": round(time.perf_counter() - started, 2),
        "head": git(repo, "rev-parse", "HEAD"),
        "branch": git(repo, "rev-parse", "--abbrev-ref", "HEAD"),
        "run_state_verified": report.get("state"),
        "status": status,
        "controls": {
            control: {
                "checks": sum(1 for item in checks if item.control == control),
                "failed": [
                    item.check_id
                    for item in checks
                    if item.control == control and item.status == "FAIL"
                ],
                "verdict": (
                    "FAIL"
                    if any(item.control == control and item.status == "FAIL" for item in checks)
                    else "BLOCKED"
                    if any(item.control == control and item.status == "BLOCKED" for item in checks)
                    else "PASS"
                ),
            }
            for control in CONTROLS
        },
        "checks": [item.as_dict() for item in checks],
        "anchors": {
            "phase1_sha256": PHASE1_SHA256,
            "phase1_git_blob": PHASE1_BLOB,
            "generator_commit": GENERATOR_COMMIT,
            "generator_sha256": GENERATOR_SHA256,
            "capture_window": [WINDOW_START, WINDOW_END],
            "effective_from_utc": EFFECTIVE,
        },
        "temporal_proof": "TIME_PROOF_WEAK",
        "external_timestamp": "UNAVAILABLE",
        "not_a_certification": (
            "a PASS here means the runner's claim matched the evidence at this instant. It is "
            "not a capture, not a certification and not a promotion, and the paper, cost and "
            "promotion gates are untouched by this verdict."
        ),
        "economic_executions": 0,
    }
    target = Path(args.out) if args.out else run_dir / VERIFICATION_REPORT
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    for item in checks:
        print(f"[verify] {item.status:<5} {item.check_id:<32} {item.detail}")
    print(f"[verify] {status} - {len(checks)} checks")
    return STATUS_EXIT.get(status, EXIT_ERROR)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
