#!/usr/bin/env python
"""Independent verifier for RFC-EXP004A-051-02E — read-only, fail-closed, and not the builder.

This file is written by the verification role. It imports no ``trading_bot`` module and no script the
builder wrote: every digest, ordering and refusal below is recomputed from Git objects, from the files
on disk, and from running the declared command in throwaway directories. The builder's preflight,
capture report and run report are read only as the *claims to be tested*; a disagreement is a failure
of the claim, never a note.

The anchors are constants here, not values read from the declaration. A verifier that learns the
expected window from the artefact it is checking can only confirm that the artefact agrees with
itself; RFC §5-C asks for the opposite, so ``PHASE1_SHA256``, ``GENERATOR_COMMIT`` and the window
opening are stated before anything is read.

Two modes, one contract::

    verify   recompute the five controls RFC §12 names and write the verdict
    seal     verify EVIDENCE_MANIFEST.json against disk and Git, and record it

Exit codes are this file's own and borrow nothing from the extractor or the gate::

    0 PASS     2 FAIL     3 BLOCKED     4 ERROR

``PASS`` here means the builder's claim matched the evidence at this instant. When the claim is
``PENDING_WINDOW`` — no capture exists because the declared window has not opened — PASS is a
statement that the pending state and the refusals around it are true. It is not a capture, not a
certification, and not a promotion, and this verifier has no code path that upgrades it into one.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

VERIFIER_ID = "verifier-d/EXP-004A/WP-051-02E"
BUILDER_ID = "builder/EXP-004A/WP-051-02E"
RUN_ID = "wp051-02e/EXP-004A/2026-10-21"
SCHEMA_VERSION = "1.0"

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "docs" / "agentic" / "exp004a" / "wp051_02e"

DECLARATION = "config/preregistrations/EXP-004A.datasets.phase2.json"
ORIGINAL = "config/preregistrations/EXP-004A.datasets.json"
GENERATOR = "scripts/exp004a_capture.py"
DATASET_DIR = "data/exp004a"
SEALED_02D = "docs/agentic/exp004a/wp051_02d/EVIDENCE_MANIFEST.json"
PREFLIGHT = "WP_051_02E_PREFLIGHT.json"
CAPTURE = "WP_051_02E_CAPTURE_REPORT.json"
RUN_REPORT = "RUN_REPORT.json"
MANIFEST = "EVIDENCE_MANIFEST.json"

#: Anchors, stated before anything is read. A declaration that disagrees is not a new declaration;
#: it is a rewrite of the freeze and a failure, however well it validates against itself.
PHASE1_SHA256 = "8946f871a97b7575b1a9aa2900b3243f88d07a4821d09d6d0a3c113f1e5de211"
PHASE1_BLOB = "43c9deea29a8e4af1c0333bcc0b58131620ec3e7"
GENERATOR_COMMIT = "fc036d967923f09a6092cb0e5de7409afd07ebd7"
GENERATOR_SHA256 = "af1ab7cc23980dadac83ba53d2a5f8c1c5f33f6b5dd4841dd58620b9bb421cb8"
GENERATOR_BLOB = "052832c2252a719c63d0859628ada648c799c6ce"
WINDOW_START = "2026-10-22T00:00:00Z"
WINDOW_END = "2027-01-20T00:00:00Z"
EFFECTIVE = "2026-10-21T16:00:00Z"

CONTROLS = (
    "TECHNICAL_VERIFICATION",
    "PROVENANCE_VERIFICATION",
    "TEMPORAL_VERIFICATION",
    "ARTIFACT_INTEGRITY",
    "POLICY_COMPLIANCE",
)

#: Required before the verifier runs, in the order a reader would check them.
REQUIRED_BEFORE_VERIFICATION = (
    "RFC_EXP004A_051_02E.md",
    "WP_051_02E_BASELINE.json",
    "WP_051_02E_PREFLIGHT.json",
    "WP_051_02E_CAPTURE_REPORT.json",
    "RUN_REPORT.md",
    "RUN_REPORT.json",
    "evidence/TEST_RUNS.json",
)
#: Required by the seal step, because they are produced after this verifier has run.
REQUIRED_AT_SEAL = (
    "WP_051_02E_INDEPENDENT_VERIFICATION.json",
    "WP_051_02E_FINAL_REPORT.md",
    "EVIDENCE_MANIFEST.json",
)

EXIT_PASS = 0
EXIT_FAIL = 2
EXIT_BLOCKED = 3
EXIT_ERROR = 4
STATUS_EXIT = {"PASS": EXIT_PASS, "FAIL": EXIT_FAIL, "BLOCKED": EXIT_BLOCKED}


@dataclass
class Check:
    check_id: str
    control: str
    status: str
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "control": self.control,
            "status": self.status,
            "detail": self.detail,
            "evidence": self.evidence,
        }


def check(check_id: str, control: str, status: str, detail: str, **evidence: Any) -> Check:
    return Check(check_id, control, status, detail, evidence)


# --------------------------------------------------------------------------- #
# primitives — this file's own, not the builder's
# --------------------------------------------------------------------------- #
def git(*args: str) -> tuple[bool, bytes]:
    completed = subprocess.run(
        ["git", "-C", str(REPO), *args], capture_output=True, check=False, timeout=120
    )
    return completed.returncode == 0, completed.stdout if completed.returncode == 0 else b""


def git_text(*args: str) -> str:
    ok, output = git(*args)
    return output.decode("utf-8", "replace").strip() if ok else ""


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def blob_at(commit: str, path: str) -> bytes | None:
    ok, output = git("cat-file", "blob", f"{commit}:{path}")
    return output if ok else None


def git_blob_id(payload: bytes) -> str:
    header = f"blob {len(payload)}\0".encode("ascii")
    return hashlib.sha1(header + payload).hexdigest()  # Git's object id, not a signature


def resolve(ref: str) -> str | None:
    ok, output = git("rev-parse", "--verify", f"{ref}^{{commit}}")
    return output.decode("ascii").strip() if ok else None


def commit_epoch(ref: str) -> int | None:
    text = git_text("log", "-1", "--format=%ct", ref)
    return int(text) if text.isdigit() else None


def last_commit(path: str) -> str | None:
    return git_text("log", "-1", "--format=%H", "--", path) or None


def is_dirty(path: str) -> bool:
    return bool(git_text("status", "--porcelain", "--", path))


def ms(value: str) -> int:
    if not value.endswith("Z"):
        raise ValueError(f"{value!r} is not an explicit UTC instant")
    return int(datetime.fromisoformat(value[:-1] + "+00:00").timestamp() * 1000)


def iso(moment: int) -> str:
    return datetime.fromtimestamp(moment / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def now_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def window_state(start_ms: int, end_ms: int, at_ms: int) -> str:
    if at_ms < start_ms:
        return "BEFORE_WINDOW"
    if at_ms < end_ms:
        return "OPEN"
    return "CLOSED"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the declared command exactly as a capture would, from this checkout."""
    return subprocess.run(
        [sys.executable, GENERATOR, *args],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


def fixture(path: Path, rows: list[dict[str, Any]]) -> Path:
    """Bytes, not text: a text handle writes CRLF here and a verbatim check would then fail for a
    reason that has nothing to do with the extractor."""
    path.write_bytes("".join(json.dumps(row) + "\n" for row in rows).encode("utf-8"))
    return path


def bar(open_utc: str, fetched_utc: str, *, closed: bool = True) -> dict[str, Any]:
    return {
        "ts": ms(open_utc),
        "interval": "1h",
        "closed": closed,
        "fetched_at_ms": ms(fetched_utc),
        "open": 100.0,
        "close": 101.0,
        "high": 102.0,
        "low": 99.0,
        "volume": 10.0,
        "source": "BINANCE_PUBLIC_REST:/api/v3/klines",
    }


def dataset_digests(repo: Path) -> dict[str, str | None]:
    folder = repo / DATASET_DIR
    if not folder.is_dir():
        return {}
    return {path.name: sha256_file(path) for path in sorted(folder.glob("*")) if path.is_file()}


# --------------------------------------------------------------------------- #
# TECHNICAL: the freeze is still the freeze
# --------------------------------------------------------------------------- #
def technical_checks(document: dict[str, Any]) -> list[Check]:
    checks: list[Check] = []

    missing = [
        key
        for key in (
            "declaration_id",
            "experiment_id",
            "phase",
            "schema_version",
            "supersedes",
            "generator",
            "capture_window",
            "effective_from_utc",
            "issued_at_utc",
            "governance_status",
            "entries",
        )
        if document.get(key) in (None, "", [], {})
    ]
    checks.append(
        check(
            "V-TECH-01",
            "TECHNICAL_VERIFICATION",
            "FAIL" if missing else "PASS",
            f"missing fields {missing}" if missing else "every required field is present",
            missing=missing,
        )
    )

    generator = document.get("generator") or {}
    window = document.get("capture_window") or {}
    supersedes = document.get("supersedes") or {}
    anchors = {
        "generator.commit": (generator.get("commit"), GENERATOR_COMMIT),
        "generator.blob_sha256": (generator.get("blob_sha256"), GENERATOR_SHA256),
        "capture_window.start_utc": (window.get("start_utc"), WINDOW_START),
        "capture_window.end_utc": (window.get("end_utc"), WINDOW_END),
        "effective_from_utc": (document.get("effective_from_utc"), EFFECTIVE),
        "supersedes.sha256": (supersedes.get("sha256"), PHASE1_SHA256),
        "supersedes.git_blob": (supersedes.get("git_blob"), PHASE1_BLOB),
        "governance_status": (document.get("governance_status"), "AUTHORIZED_FOR_CAPTURE"),
    }
    drifted = {name: {"found": found, "expected": expected} for name, (found, expected) in anchors.items() if found != expected}
    checks.append(
        check(
            "V-TECH-02",
            "TECHNICAL_VERIFICATION",
            "FAIL" if drifted else "PASS",
            f"{len(drifted)} anchor(s) moved: {sorted(drifted)}"
            if drifted
            else "commit, digest, window and governance status are the anchored ones",
            drift=drifted,
        )
    )

    committed_generator = blob_at(GENERATOR_COMMIT, GENERATOR)
    would_run = git_text("hash-object", "--", GENERATOR)
    committed_blob = git_text("rev-parse", f"{GENERATOR_COMMIT}:{GENERATOR}")
    generator_ok = (
        committed_generator is not None
        and sha256_bytes(committed_generator) == GENERATOR_SHA256
        and committed_blob == GENERATOR_BLOB
        and would_run == GENERATOR_BLOB
        and not is_dirty(GENERATOR)
    )
    checks.append(
        check(
            "V-TECH-03",
            "TECHNICAL_VERIFICATION",
            "PASS" if generator_ok else "FAIL",
            f"generator at {GENERATOR_COMMIT[:12]} is sha256 {sha256_bytes(committed_generator or b'')[:16]}..., "
            f"would-run blob {would_run[:12]}...",
            committed_sha256=sha256_bytes(committed_generator or b""),
            committed_blob=committed_blob,
            would_run_blob=would_run,
            dirty=is_dirty(GENERATOR),
        )
    )

    original_bytes = blob_at(last_commit(ORIGINAL) or "HEAD", ORIGINAL)
    original_digest = sha256_file(REPO / ORIGINAL)
    original_ok = (
        original_digest == PHASE1_SHA256
        and original_bytes is not None
        and git_blob_id(original_bytes) == PHASE1_BLOB
        and not is_dirty(ORIGINAL)
    )
    checks.append(
        check(
            "V-TECH-04",
            "TECHNICAL_VERIFICATION",
            "PASS" if original_ok else "FAIL",
            f"phase 1 sha256 {str(original_digest)[:16]}..., blob {git_blob_id(original_bytes or b'')[:12]}..., "
            f"dirty={is_dirty(ORIGINAL)}",
            sha256=original_digest,
            git_blob=git_blob_id(original_bytes or b""),
            dirty=is_dirty(ORIGINAL),
        )
    )

    sealed_path = REPO / SEALED_02D
    drifted_sealed: list[dict[str, Any]] = []
    sealed_count = 0
    if sealed_path.is_file():
        sealed = read_json(sealed_path)
        for entry in sealed.get("entries") or []:
            sealed_count += 1
            relative = str(entry.get("path"))
            digest = sha256_file(REPO / relative)
            if digest != entry.get("sha256"):
                drifted_sealed.append({"path": relative, "recorded": entry.get("sha256"), "now": digest})
    checks.append(
        check(
            "V-TECH-05",
            "TECHNICAL_VERIFICATION",
            "PASS" if sealed_count and not drifted_sealed else "FAIL",
            f"{sealed_count} sealed 02D artefacts, {len(drifted_sealed)} drifted",
            sealed=sealed_count,
            drifted=drifted_sealed,
        )
    )

    declaration_commit = last_commit(DECLARATION)
    stamp = commit_epoch(declaration_commit) if declaration_commit else None
    declaration_ok = bool(
        declaration_commit
        and stamp is not None
        and stamp * 1000 < ms(WINDOW_START)
        and not is_dirty(DECLARATION)
        and resolve(declaration_commit) is not None
    )
    checks.append(
        check(
            "V-TECH-06",
            "TECHNICAL_VERIFICATION",
            "PASS" if declaration_ok else "FAIL",
            f"declaration committed at {iso(stamp * 1000 if stamp else 0)}, window opens {WINDOW_START}, "
            f"dirty={is_dirty(DECLARATION)}",
            commit=declaration_commit,
            commit_utc=iso(stamp * 1000) if stamp else None,
        )
    )
    return checks


# --------------------------------------------------------------------------- #
# PROVENANCE: every refusal, re-run here
# --------------------------------------------------------------------------- #
def provenance_checks(root: Path) -> list[Check]:
    checks: list[Check] = []
    before = dataset_digests(REPO)

    def attempt(name: str, rows: list[dict[str, Any]] | None, *args: str) -> dict[str, Any]:
        scratch = root / name
        scratch.mkdir(parents=True, exist_ok=True)
        source = fixture(scratch / "BTC.jsonl", rows or [])
        out = scratch / "out"
        completed = run_cli("--slice", "1h:BTC", "--source", str(source), "--out", str(out), *args)
        written = sorted(path.name for path in out.glob("*.jsonl")) if out.is_dir() else []
        return {
            "exit_code": completed.returncode,
            "stdout": completed.stdout.strip()[:600],
            "stderr": completed.stderr.strip()[:600],
            "written": written,
            "out": out,
            "source": source,
        }

    positive = attempt(
        "eligible", [bar("2026-10-22T00:00:00Z", "2026-10-21T17:00:00Z")]
    )
    verbatim = False
    if positive["written"]:
        verbatim = (positive["out"] / positive["written"][0]).read_bytes() == positive[
            "source"
        ].read_bytes()
    checks.append(
        check(
            "V-PROV-01",
            "PROVENANCE_VERIFICATION",
            "PASS" if positive["exit_code"] == 0 and verbatim else "FAIL",
            f"eligible rehearsal exit {positive['exit_code']}, {len(positive['written'])} file(s), "
            f"verbatim={verbatim} (written under a temporary directory, never {DATASET_DIR})",
            exit_code=positive["exit_code"],
            verbatim=verbatim,
        )
    )

    second = run_cli(
        "--slice",
        "1h:BTC",
        "--source",
        str(positive["source"]),
        "--out",
        str(positive["out"]),
    )
    checks.append(
        check(
            "V-PROV-02",
            "PROVENANCE_VERIFICATION",
            "PASS" if second.returncode == 2 else "FAIL",
            f"re-running into an existing dataset returns {second.returncode}; a dataset is written once",
            exit_code=second.returncode,
        )
    )

    pre_effective = attempt(
        "pre-effective", [bar("2026-10-22T00:00:00Z", "2026-10-21T09:00:00Z")]
    )
    checks.append(
        check(
            "V-PROV-03",
            "PROVENANCE_VERIFICATION",
            "PASS"
            if pre_effective["exit_code"] == 5 and not pre_effective["written"]
            else "FAIL",
            f"bar fetched before the declaration took effect: exit {pre_effective['exit_code']}, "
            f"{len(pre_effective['written'])} file(s)",
            exit_code=pre_effective["exit_code"],
            written=pre_effective["written"],
        )
    )

    outside = attempt("outside-window", [bar("2026-10-21T00:00:00Z", "2026-10-21T17:00:00Z")])
    checks.append(
        check(
            "V-PROV-04",
            "PROVENANCE_VERIFICATION",
            "PASS" if outside["exit_code"] == 3 and not outside["written"] else "FAIL",
            f"no bar opens inside the window: exit {outside['exit_code']}, "
            f"{len(outside['written'])} file(s)",
            exit_code=outside["exit_code"],
            written=outside["written"],
        )
    )

    empty = attempt("empty-source", [])
    checks.append(
        check(
            "V-PROV-05",
            "PROVENANCE_VERIFICATION",
            "PASS" if empty["exit_code"] == 4 and not empty["written"] else "FAIL",
            f"empty source: exit {empty['exit_code']}, {len(empty['written'])} file(s)",
            exit_code=empty["exit_code"],
            written=empty["written"],
        )
    )

    tape = run_cli("--slice", "st6:tape", "--dry-run")
    checks.append(
        check(
            "V-PROV-06",
            "PROVENANCE_VERIFICATION",
            "PASS" if tape.returncode == 2 else "FAIL",
            f"st6:tape exit {tape.returncode}; the freeze defines no round-to-window rule",
            exit_code=tape.returncode,
        )
    )

    beyond = run_cli(
        "--slice",
        "1h:BTC",
        "--dry-run",
        "--period-end",
        "2027-06-01T00:00:00Z",
    )
    checks.append(
        check(
            "V-PROV-07",
            "PROVENANCE_VERIFICATION",
            "PASS" if beyond.returncode == 2 else "FAIL",
            f"a period past the declared window returns {beyond.returncode}",
            exit_code=beyond.returncode,
        )
    )

    doctored_path = root / "doctored" / "EXP-004A.datasets.phase2.json"
    doctored_path.parent.mkdir(parents=True, exist_ok=True)
    doctored = read_json(REPO / DECLARATION)
    doctored["generator"]["blob_sha256"] = "0" * 64
    doctored_path.write_text(json.dumps(doctored, indent=2) + "\n", encoding="utf-8")
    doctored_source = fixture(
        root / "doctored" / "BTC.jsonl", [bar("2026-10-22T00:00:00Z", "2026-10-21T17:00:00Z")]
    )
    doctored_run = run_cli(
        "--slice",
        "1h:BTC",
        "--source",
        str(doctored_source),
        "--out",
        str(root / "doctored" / "out"),
        "--declaration",
        str(doctored_path),
    )
    refused_doctored = doctored_run.returncode != 0 and "GENERATOR_BLOB_MISMATCH" in doctored_run.stderr
    checks.append(
        check(
            "V-PROV-08",
            "PROVENANCE_VERIFICATION",
            "PASS" if refused_doctored else "FAIL",
            f"a declaration citing another generator blob is refused with "
            f"{'GENERATOR_BLOB_MISMATCH' if refused_doctored else 'no named defect'} "
            f"(exit {doctored_run.returncode})",
            exit_code=doctored_run.returncode,
            stderr=doctored_run.stderr.strip()[:400],
        )
    )

    after = dataset_digests(REPO)
    checks.append(
        check(
            "V-PROV-09",
            "PROVENANCE_VERIFICATION",
            "PASS" if before == after else "FAIL",
            "the probes wrote nothing into "
            f"{DATASET_DIR}: {len(before)} file(s) before, {len(after)} after, digests "
            f"{'identical' if before == after else 'CHANGED'}",
            before=before,
            after=after,
        )
    )
    return checks


# --------------------------------------------------------------------------- #
# TEMPORAL: the claim is the honest one for this instant
# --------------------------------------------------------------------------- #
def temporal_checks(capture: dict[str, Any], run_report: dict[str, Any]) -> list[Check]:
    checks: list[Check] = []
    start = ms(WINDOW_START)
    end = ms(WINDOW_END)
    state = window_state(start, end, now_ms())

    claimed = str(capture.get("window_state_at_capture") or "")
    checks.append(
        check(
            "V-TEMP-01",
            "TEMPORAL_VERIFICATION",
            "PASS" if claimed == state else "FAIL",
            f"builder claims {claimed or 'nothing'}, this verifier's clock says {state} at {iso(now_ms())}",
            claimed=claimed,
            observed=state,
            instant_utc=iso(now_ms()),
        )
    )

    status = str(capture.get("status") or "")
    published = capture.get("datasets_published") or []
    honest = (
        (state == "BEFORE_WINDOW" and status == "PENDING_WINDOW" and not published)
        or (state == "OPEN" and status in {"CAPTURED", "NO_ELIGIBLE_DATA", "NOT_ELIGIBLE"})
        or (state == "CLOSED" and status in {"FAIL", "BLOCKED"})
    )
    checks.append(
        check(
            "V-TEMP-02",
            "TEMPORAL_VERIFICATION",
            "PASS" if honest else "FAIL",
            f"capture status {status!r} with {len(published)} published dataset(s) against a "
            f"{state} window",
            claimed_status=status,
            published=published,
        )
    )

    temporal = capture.get("temporal") or {}
    no_borrowed_authority = (
        temporal.get("external_timestamp") == "UNAVAILABLE"
        and temporal.get("time_proof") == "TIME_PROOF_WEAK"
    )
    checks.append(
        check(
            "V-TEMP-03",
            "TEMPORAL_VERIFICATION",
            "PASS" if no_borrowed_authority else "FAIL",
            f"external_timestamp={temporal.get('external_timestamp')!r}, "
            f"time_proof={temporal.get('time_proof')!r}",
            external_timestamp=temporal.get("external_timestamp"),
            time_proof=temporal.get("time_proof"),
        )
    )

    ordered = True
    detail = "issued <= effective <= window start, and no capture predates the window"
    try:
        ordered = ms(str((capture.get("capture_window") or {}).get("effective_from_utc"))) <= start
        started = ms(str(capture.get("started_at_utc")))
        if published and started < start:
            ordered = False
            detail = "a dataset was published from a run that began before the window opened"
    except (TypeError, ValueError) as error:
        ordered = False
        detail = f"a captured instant is unreadable: {error}"
    checks.append(
        check(
            "V-TEMP-04",
            "TEMPORAL_VERIFICATION",
            "PASS" if ordered else "FAIL",
            detail,
            effective_from_utc=(capture.get("capture_window") or {}).get("effective_from_utc"),
            capture_started_at_utc=capture.get("started_at_utc"),
        )
    )

    c013 = str((run_report.get("status") or {}).get("C_013") or "")
    checks.append(
        check(
            "V-TEMP-05",
            "TEMPORAL_VERIFICATION",
            "PASS" if c013 == "TIME_PROOF_WEAK" else "FAIL",
            f"the run report says C_013={c013!r}; without an external attestation it must stay weak",
            c_013=c013,
        )
    )
    return checks


# --------------------------------------------------------------------------- #
# INTEGRITY: the artefacts are the ones the report names
# --------------------------------------------------------------------------- #
def artifact_checks(run_dir: Path, capture: dict[str, Any], run_report: dict[str, Any]) -> list[Check]:
    checks: list[Check] = []

    absent = [name for name in REQUIRED_BEFORE_VERIFICATION if not (run_dir / name).is_file()]
    checks.append(
        check(
            "V-ART-01",
            "ARTIFACT_INTEGRITY",
            "FAIL" if absent else "PASS",
            f"{len(REQUIRED_BEFORE_VERIFICATION) - len(absent)} of "
            f"{len(REQUIRED_BEFORE_VERIFICATION)} required artefacts present",
            absent=absent,
        )
    )

    declared = run_report.get("artefacts") or []
    mismatched = []
    for entry in declared:
        relative = str(entry.get("path"))
        digest = sha256_file(REPO / relative)
        if digest != entry.get("sha256"):
            mismatched.append({"path": relative, "claimed": entry.get("sha256"), "now": digest})
    checks.append(
        check(
            "V-ART-02",
            "ARTIFACT_INTEGRITY",
            "PASS" if declared and not mismatched else "FAIL",
            f"{len(declared)} digest(s) declared, {len(mismatched)} do not match the file on disk",
            declared=len(declared),
            mismatched=mismatched,
        )
    )

    folder = REPO / DATASET_DIR
    datasets = sorted(path.name for path in folder.glob("EXP-004A-*.jsonl")) if folder.is_dir() else []
    manifests = (
        sorted(path.name for path in folder.glob("EXP-004A-*.MANIFEST.json"))
        if folder.is_dir()
        else []
    )
    published = capture.get("datasets_published") or []
    consistent = (
        (not published and not datasets and not manifests)
        or (bool(published) and sorted(Path(name).name for name in published) == datasets)
    )
    checks.append(
        check(
            "V-ART-03",
            "ARTIFACT_INTEGRITY",
            "PASS" if consistent else "FAIL",
            f"capture report names {len(published)} dataset(s); {DATASET_DIR} holds "
            f"{len(datasets)} dataset(s) and {len(manifests)} manifest(s)",
            published=published,
            datasets=datasets,
            manifests=manifests,
        )
    )

    ledgers = run_report.get("admission_ledgers") or {}
    ledger_drift = {
        name: {"claimed": digest, "now": sha256_file(REPO / DATASET_DIR / name)}
        for name, digest in ledgers.items()
        if sha256_file(REPO / DATASET_DIR / name) != digest
    }
    checks.append(
        check(
            "V-ART-04",
            "ARTIFACT_INTEGRITY",
            "PASS" if not ledger_drift else "FAIL",
            f"{len(ledgers)} admission ledger digest(s) declared, {len(ledger_drift)} drifted"
            if ledgers
            else "the run report declares no admission ledger digest",
            drift=ledger_drift,
            declared=len(ledgers),
        )
    )

    sealed_path = REPO / SEALED_02D
    dirty_sealed = []
    if sealed_path.is_file():
        for entry in read_json(sealed_path).get("entries") or []:
            if is_dirty(str(entry.get("path"))):
                dirty_sealed.append(str(entry.get("path")))
    checks.append(
        check(
            "V-ART-05",
            "ARTIFACT_INTEGRITY",
            "PASS" if not dirty_sealed else "FAIL",
            f"{len(dirty_sealed)} sealed path(s) modified in the worktree",
            dirty=dirty_sealed,
        )
    )
    return checks


# --------------------------------------------------------------------------- #
# POLICY: no self-certification, no false success, no borrowed authority
# --------------------------------------------------------------------------- #
def policy_checks(run_dir: Path, capture: dict[str, Any], run_report: dict[str, Any]) -> list[Check]:
    checks: list[Check] = []

    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    forbidden = sorted(
        name
        for name in imported
        if name == "trading_bot"
        or name.startswith("exp004a_")
        or name in {"trading_bot.research", "provenance"}
    )
    checks.append(
        check(
            "V-POL-01",
            "POLICY_COMPLIANCE",
            "PASS" if not forbidden else "FAIL",
            "the verifier imports no trading_bot module and no builder script"
            if not forbidden
            else f"forbidden imports: {forbidden}",
            imports=sorted(imported),
        )
    )

    preflight_path = run_dir / PREFLIGHT
    builder_role = read_json(preflight_path).get("role") if preflight_path.is_file() else None
    distinct = builder_role == "builder" and VERIFIER_ID.split("/")[0] != BUILDER_ID.split("/")[0]
    checks.append(
        check(
            "V-POL-02",
            "POLICY_COMPLIANCE",
            "PASS" if distinct else "FAIL",
            f"builder role {builder_role!r} in the preflight; verifier id {VERIFIER_ID}",
            builder_id=BUILDER_ID,
            verifier_id=VERIFIER_ID,
            builder_role=builder_role,
        )
    )

    status = run_report.get("status") or {}
    expected = {
        "C_004": "PASS",
        "C_013": "TIME_PROOF_WEAK",
        "C_016": "UNREACHABLE_UNDER_DECLARED_COST_MODEL",
        "PAPER_VALIDATION": "NOT_PASS",
        "CERTIFICATION": "BLOCKED",
        "PROMOTION": "NO_PROMOTION",
    }
    wrong = {
        key: {"claimed": status.get(key), "allowed": value}
        for key, value in expected.items()
        if status.get(key) != value
    }
    checks.append(
        check(
            "V-POL-03",
            "POLICY_COMPLIANCE",
            "PASS" if not wrong else "FAIL",
            f"{len(expected)} gate states checked, {len(wrong)} wrong: {sorted(wrong)}",
            wrong=wrong,
        )
    )

    wp = str(status.get("WP_051_02E") or "")
    published = capture.get("datasets_published") or []
    allowed_wp = {"PENDING_WINDOW"} if not published else {"PASS"}
    checks.append(
        check(
            "V-POL-04",
            "POLICY_COMPLIANCE",
            "PASS" if wp in allowed_wp else "FAIL",
            f"WP_051_02E={wp!r} with {len(published)} published dataset(s); "
            f"without a prospective capture only {sorted(allowed_wp)} is available",
            wp=wp,
            published=published,
        )
    )

    limitations = run_report.get("limitations") or []
    declared = {str(row.get("id")): row for row in limitations if isinstance(row, dict)}
    observed: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="wp051-02e-limit-") as scratch:
        root = Path(scratch)
        future = now_ms() + 3_600_000
        source = fixture(
            root / "BTC.jsonl",
            [bar("2026-10-22T00:00:00Z", iso(future))],
        )
        completed = run_cli("--slice", "1h:BTC", "--source", str(source), "--out", str(root / "out"))
        observed["future_ingest_exit_code"] = completed.returncode
        observed["future_ingest_published"] = sorted(
            path.name for path in (root / "out").glob("*.jsonl")
        )
        # the probe is a limitation under test, not evidence: it is deleted with the directory
    claim = declared.get("L-01") or {}
    agreed = claim.get("observed_exit_code") == observed["future_ingest_exit_code"]
    checks.append(
        check(
            "V-POL-05",
            "POLICY_COMPLIANCE",
            "PASS" if agreed else "FAIL",
            f"L-01 probe: a bar stamped as fetched in the future returns "
            f"{observed['future_ingest_exit_code']}; the run report declares "
            f"{claim.get('observed_exit_code')!r}",
            observed=observed,
            declared=claim.get("observed_exit_code"),
        )
    )

    executions = [
        read_json(run_dir / name).get("economic_executions")
        for name in (PREFLIGHT, CAPTURE)
        if (run_dir / name).is_file()
    ] + [run_report.get("economic_executions")]
    checks.append(
        check(
            "V-POL-06",
            "POLICY_COMPLIANCE",
            "PASS" if all(value == 0 for value in executions) else "FAIL",
            f"economic executions recorded by builder and verifier: {executions}",
            executions=executions,
        )
    )
    return checks


# --------------------------------------------------------------------------- #
# verdict
# --------------------------------------------------------------------------- #
def verify(run_dir: Path) -> tuple[list[Check], str]:
    checks: list[Check] = []
    declaration_path = REPO / DECLARATION
    if not declaration_path.is_file():
        return (
            [check("V-TECH-00", "TECHNICAL_VERIFICATION", "BLOCKED", f"{DECLARATION} absent")],
            "BLOCKED",
        )
    document = read_json(declaration_path)
    checks.extend(technical_checks(document))

    with tempfile.TemporaryDirectory(prefix="wp051-02e-verify-") as scratch:
        checks.extend(provenance_checks(Path(scratch)))

    missing = [name for name in (CAPTURE, RUN_REPORT) if not (run_dir / name).is_file()]
    if missing:
        checks.append(
            check(
                "V-TEMP-00",
                "TEMPORAL_VERIFICATION",
                "BLOCKED",
                f"cannot judge a capture claim that is not there: {missing}",
                missing=missing,
            )
        )
        return checks, "BLOCKED"

    capture = read_json(run_dir / CAPTURE)
    run_report = read_json(run_dir / RUN_REPORT)
    checks.extend(temporal_checks(capture, run_report))
    checks.extend(artifact_checks(run_dir, capture, run_report))
    checks.extend(policy_checks(run_dir, capture, run_report))

    if any(item.status == "FAIL" for item in checks):
        status = "FAIL"
    elif any(item.status == "BLOCKED" for item in checks):
        status = "BLOCKED"
    elif any(item.status == "ERROR" for item in checks):
        status = "ERROR"
    else:
        status = "PASS"
    return checks, status


def seal(run_dir: Path) -> dict[str, Any]:
    """Re-hash every manifest entry and say whether Git already holds the same bytes."""
    path = run_dir / MANIFEST
    if not path.is_file():
        return {"status": "BLOCKED", "detail": f"{MANIFEST} is absent", "entries": []}
    manifest = read_json(path)
    entries = []
    for entry in manifest.get("entries") or []:
        relative = str(entry.get("path"))
        digest = sha256_file(REPO / relative)
        blob = git_text("rev-parse", f"HEAD:{relative}") or None
        entries.append(
            {
                "path": relative,
                "recorded": entry.get("sha256"),
                "now": digest,
                "match": digest == entry.get("sha256"),
                "in_head": blob is not None,
                "head_blob": blob,
            }
        )
    missing = [name for name in REQUIRED_AT_SEAL if not (run_dir / name).is_file()]
    bad = [entry for entry in entries if not entry["match"]]
    uncommitted = [entry["path"] for entry in entries if not entry["in_head"]]
    status = "PASS" if entries and not bad and not missing else "FAIL"
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": RUN_ID,
        "verifier": VERIFIER_ID,
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "head": git_text("rev-parse", "HEAD"),
        "status": status,
        "entries": len(entries),
        "mismatched": bad,
        "missing_reports": missing,
        "not_in_head": uncommitted,
        "detail": (
            "the manifest is verified against the files on disk and against the objects Git stores; "
            "an artefact that is not committed yet is listed, not treated as absent"
        ),
        "entries_by_path": entries,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", choices=("verify", "seal"), default="verify")
    parser.add_argument("--run-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    run_dir = Path(args.run_dir).resolve()
    started = time.perf_counter()

    if args.mode == "seal":
        payload = seal(run_dir)
        target = Path(args.out) if args.out else run_dir / "WP_051_02E_VERIFIER_SEAL.json"
        target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"[seal] {payload['status']} - {payload['entries']} entries - {len(payload['mismatched'])} mismatched")
        return EXIT_PASS if payload["status"] == "PASS" else EXIT_FAIL

    try:
        checks, status = verify(run_dir)
    except Exception as error:  # a crashed verifier must not read as a pass
        print(f"[verify] ERROR {type(error).__name__}: {error}")
        return EXIT_ERROR

    capture_path = run_dir / CAPTURE
    capture_state = read_json(capture_path).get("status") if capture_path.is_file() else None
    payload = {
        "schema_version": SCHEMA_VERSION,
        "run_id": RUN_ID,
        "rfc": "RFC-EXP004A-051-02E",
        "verifier": VERIFIER_ID,
        "builder": BUILDER_ID,
        "independent_of_builder": True,
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "duration_s": round(time.perf_counter() - started, 2),
        "head": git_text("rev-parse", "HEAD"),
        "branch": git_text("rev-parse", "--abbrev-ref", "HEAD"),
        "capture_status_verified": capture_state,
        "status": status,
        "controls": {
            control: {
                "checks": sum(1 for item in checks if item.control == control),
                "failed": [item.check_id for item in checks if item.control == control and item.status != "PASS"],
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
            "generator_git_blob": GENERATOR_BLOB,
            "capture_window": [WINDOW_START, WINDOW_END],
            "effective_from_utc": EFFECTIVE,
        },
        "temporal_proof": "TIME_PROOF_WEAK",
        "external_timestamp": "UNAVAILABLE",
        "not_a_certification": (
            "a PASS here means the builder's claim matched the evidence at this instant. No "
            "prospective capture exists unless the capture report names one, and the certification, "
            "paper validation and promotion gates are untouched by this verdict."
        ),
        "economic_executions": 0,
    }
    target = Path(args.out) if args.out else run_dir / "WP_051_02E_INDEPENDENT_VERIFICATION.json"
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    for item in checks:
        print(f"[verify] {item.status:<5} {item.check_id:<12} {item.detail}")
    print(f"[verify] {status} - {len(checks)} checks")
    return STATUS_EXIT.get(status, EXIT_ERROR)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
