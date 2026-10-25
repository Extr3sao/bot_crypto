#!/usr/bin/env python
"""Independent verifier for RFC-EXP004A-051-02D — read-only, fail-closed, and not the builder.

This file is written by the verification role. It imports no ``trading_bot`` module and no script the
builder wrote: every digest, order and refusal below is recomputed from Git objects, from the files on
disk, and from running the declared command in a throwaway directory. The builder's preflight report
is read only as the *claims to be tested*; a disagreement is a failure of the claim, never a note.

Two modes, one contract::

    verify   recompute the five controls RFC §12 requires and write the verdict
    seal     verify every entry of EVIDENCE_MANIFEST.json against disk and Git, and record it

Exit codes are the verifier's own and do not touch the extractor's or the gate's::

    0 PASS     2 FAIL     3 BLOCKED     4 ERROR

``PASS`` means the five controls held on this checkout at this instant. It is not an authorisation,
not a 90-day validation, and not a promotion. There is no eligible capture yet, so what is verified
is the *rule* and its binding, not any observed market day.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

VERIFIER_ID = "verifier-c/EXP-004A/WP-051-02D"
BUILDER_ID = "builder/EXP-004A/WP-051-02D"
RUN_ID = "wp051-02d/EXP-004A/2026-10-21"
SCHEMA_VERSION = "1.0"

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "docs" / "agentic" / "exp004a" / "wp051_02d"

DECLARATION = "config/preregistrations/EXP-004A.datasets.phase2.json"
ORIGINAL = "config/preregistrations/EXP-004A.datasets.json"
GENERATOR = "scripts/exp004a_capture.py"
PREREG = "config/preregistrations/EXP-004A.json"
DECISION = "docs/agentic/exp004a/independent/ACCEPTANCE_DECISION.json"
PREFLIGHT = "docs/agentic/exp004a/wp051_02d/WP_051_02D_PREFLIGHT.json"
#: the commit that froze the phase-1 dataset declaration; the original must still be that blob
PHASE_ONE_COMMIT = "47116b2f2c5fd37ed1a60550eefe17d8bd703638"
MANIFEST = "docs/agentic/exp004a/wp051_02d/EVIDENCE_MANIFEST.json"
RUN_REPORT = "docs/agentic/exp004a/wp051_02d/RUN_REPORT.json"

CONTROLS = (
    "TECHNICAL_VERIFICATION",
    "PROVENANCE_VERIFICATION",
    "TEMPORAL_VERIFICATION",
    "ARTIFACT_INTEGRITY",
    "POLICY_COMPLIANCE",
)

EXIT_PASS = 0
EXIT_FAIL = 2
EXIT_BLOCKED = 3
EXIT_ERROR = 4
STATUS_EXIT = {"PASS": EXIT_PASS, "FAIL": EXIT_FAIL, "BLOCKED": EXIT_BLOCKED}

#: Every artefact this package must leave in Git. Deliberately a list here rather than a read of the
#: manifest: the verifier has to know what to expect before it is told.
REQUIRED_ARTEFACTS = (
    "RFC_EXP004A_051_02D.md",
    "WP_051_02D_BASELINE.json",
    "WP_051_02D_PREFLIGHT.json",
    "WP_051_02D_PREFLIGHT.md",
    "WP_051_02D_TEST_REPORT.md",
    "WP_051_02D_CHANGELOG.md",
    "RUN_REPORT.md",
    "RUN_REPORT.json",
    "WP_051_02D_FINAL_REPORT.md",
    "EVIDENCE_MANIFEST.json",
)


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
    return completed.returncode == 0, completed.stdout if completed.returncode == 0 else completed.stderr


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


def blob_id_at(commit: str, path: str) -> str | None:
    ok, output = git("rev-parse", f"{commit}:{path}")
    return output.decode("ascii").strip() if ok else None


def worktree_blob_id(path: str) -> str | None:
    ok, output = git("hash-object", "--", path)
    return output.decode("ascii").strip() if ok else None


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


def ms(iso: str) -> int:
    if not iso.endswith("Z"):
        raise ValueError(f"{iso!r} is not an explicit UTC instant")
    return int(datetime.fromisoformat(iso[:-1] + "+00:00").timestamp() * 1000)


def iso(moment: int) -> str:
    return datetime.fromtimestamp(moment / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the declared command exactly as a capture would, in this checkout."""
    return subprocess.run(
        [sys.executable, GENERATOR, *args],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=180,
    )


def fixture(path: Path, rows: list[dict[str, Any]]) -> Path:
    """Bytes, not text: a fixture written through a text handle gets CRLF on this host, and then a
    verbatim comparison fails for a reason that has nothing to do with the extractor."""
    path.write_bytes("".join(json.dumps(row) + "\n" for row in rows).encode("utf-8"))
    return path


# --------------------------------------------------------------------------- #
# TECHNICAL: the declaration is the phase-1 contract plus one identifier
# --------------------------------------------------------------------------- #
def technical_checks() -> list[Check]:
    checks: list[Check] = []
    path = REPO / DECLARATION
    if not path.is_file():
        return [check("V-TECH-00", "TECHNICAL_VERIFICATION", "BLOCKED", f"{DECLARATION} absent")]
    try:
        document = read_json(path)
    except json.JSONDecodeError as error:
        return [check("V-TECH-00", "TECHNICAL_VERIFICATION", "FAIL", f"not JSON: {error}")]

    required = (
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
    missing = [key for key in required if document.get(key) in (None, "", [], {})]
    checks.append(
        check(
            "V-TECH-01",
            "TECHNICAL_VERIFICATION",
            "FAIL" if missing else "PASS",
            f"missing fields {missing}" if missing else "every required field is present",
            missing=missing,
        )
    )

    original_path = REPO / ORIGINAL
    original = read_json(original_path)
    entries = document.get("entries") or []
    generator = document.get("generator") or {}
    drift: list[str] = []
    for entry in entries:
        name = str(entry.get("dataset_id"))
        counterpart = next(
            (row for row in original.get("entries", []) if row.get("dataset_id") == name), None
        )
        if counterpart is None:
            drift.append(f"{name}: not declared in phase 1")
            continue
        for key in sorted(set(entry) | set(counterpart)):
            if key == "generator_code_commit":
                continue
            if entry.get(key) != counterpart.get(key):
                drift.append(f"{name}.{key}: {counterpart.get(key)!r} -> {entry.get(key)!r}")
        if entry.get("generator_code_commit") != generator.get("commit"):
            drift.append(f"{name}.generator_code_commit != generator.commit")
    checks.append(
        check(
            "V-TECH-02",
            "TECHNICAL_VERIFICATION",
            "FAIL" if drift else "PASS",
            "; ".join(drift[:4]) if drift else "only generator_code_commit differs from phase 1",
            drift=drift,
        )
    )

    window = document.get("capture_window") or {}
    original_windows = {
        (row.get("period_start_utc"), row.get("period_end_utc")) for row in original["entries"]
    }
    declared = (window.get("start_utc"), window.get("end_utc"))
    checks.append(
        check(
            "V-TECH-03",
            "TECHNICAL_VERIFICATION",
            "PASS" if original_windows == {declared} else "FAIL",
            f"{declared[0]} to {declared[1]}" if original_windows == {declared} else f"{sorted(original_windows)} != {declared}",
            capture_window=list(declared),
        )
    )

    commands = {str(entry.get("generator_command")) for entry in entries}
    expected_commands = {
        str(entry.get("generator_command")) for entry in original["entries"]
    }
    checks.append(
        check(
            "V-TECH-04",
            "TECHNICAL_VERIFICATION",
            "PASS" if commands == expected_commands else "FAIL",
            "every entry still invokes the declared command"
            if commands == expected_commands
            else f"{sorted(commands)} != {sorted(expected_commands)}",
            commands=sorted(commands),
        )
    )

    tape = run_cli("--slice", "st6:tape", "--dry-run")
    checks.append(
        check(
            "V-TECH-05",
            "TECHNICAL_VERIFICATION",
            "PASS" if tape.returncode == 2 else "FAIL",
            f"st6:tape exit {tape.returncode}",
            exit_code=tape.returncode,
        )
    )

    with tempfile.TemporaryDirectory(prefix="wp051-02d-verify-") as scratch:
        root = Path(scratch)
        hour = 3_600_000
        start = ms(str(declared[0]))
        end = ms(str(declared[1]))
        bar = {
            "ts": start,
            "interval": "1h",
            "closed": True,
            "fetched_at_ms": start + hour + 60_000,
            "payload_sha256": "0" * 64,
        }
        inside = fixture(root / "inside.jsonl", [bar])
        result = run_cli("--slice", "1h:BTC", "--source", str(inside), "--out", str(root / "out"))
        written = root / "out" / "EXP-004A-1H-BTC.jsonl"
        verbatim = written.is_file() and written.read_bytes() == inside.read_bytes()
        manifest = {}
        if result.returncode == 0:
            manifest = json.loads(result.stdout)["manifest"]
        checks.append(
            check(
                "V-TECH-06",
                "TECHNICAL_VERIFICATION",
                "PASS" if result.returncode == 0 and verbatim and manifest.get("provenance") else "FAIL",
                f"positive fixture exit {result.returncode}, verbatim={verbatim}, "
                f"provenance={'yes' if manifest.get('provenance') else 'no'}",
                exit_code=result.returncode,
                verbatim=verbatim,
                row_count=manifest.get("row_count"),
            )
        )

        empty = fixture(root / "empty.jsonl", [{**bar, "ts": start - 3 * 24 * hour}])
        refused = run_cli(
            "--slice", "1h:BTC", "--source", str(empty), "--out", str(root / "empty")
        )
        checks.append(
            check(
                "V-TECH-07",
                "TECHNICAL_VERIFICATION",
                "PASS" if refused.returncode == 3 else "FAIL",
                f"empty window exit {refused.returncode}",
                exit_code=refused.returncode,
            )
        )

        early = fixture(
            root / "early.jsonl", [{**bar, "fetched_at_ms": start - 30 * 24 * hour}]
        )
        before = run_cli(
            "--slice", "1h:BTC", "--source", str(early), "--out", str(root / "early")
        )
        checks.append(
            check(
                "V-TECH-08",
                "TECHNICAL_VERIFICATION",
                "PASS" if before.returncode == 5 else "FAIL",
                f"pre-effective fixture exit {before.returncode}",
                exit_code=before.returncode,
            )
        )

    checks.append(
        check(
            "V-TECH-09",
            "TECHNICAL_VERIFICATION",
            "PASS" if bool(declared[0]) and bool(declared[1]) and end > start else "FAIL",
            "the declared window is non-empty",
            start_utc=iso(start),
            end_utc=iso(end),
        )
    )
    return checks


# --------------------------------------------------------------------------- #
# PROVENANCE: DECLARATION -> COMMIT -> GENERATOR
# --------------------------------------------------------------------------- #
def provenance_checks() -> list[Check]:
    checks: list[Check] = []
    document = read_json(REPO / DECLARATION)
    generator = document.get("generator") or {}
    commit = str(generator.get("commit") or "")
    declared_sha = str(generator.get("blob_sha256") or "")

    full = len(commit) == 40 and all(char in "0123456789abcdef" for char in commit)
    resolved = resolve(commit) if full else None
    checks.append(
        check(
            "V-PROV-01",
            "PROVENANCE_VERIFICATION",
            "PASS" if full and resolved == commit else "FAIL",
            f"{commit or '<empty>'} -> {resolved}",
            commit=commit,
            resolved=resolved,
        )
    )

    body = blob_at(commit, str(generator.get("path"))) if resolved else None
    actual = sha256_bytes(body or b"")
    checks.append(
        check(
            "V-PROV-02",
            "PROVENANCE_VERIFICATION",
            "PASS" if body is not None and actual == declared_sha else "FAIL",
            f"blob sha256 {actual[:16]}... vs declared {declared_sha[:16]}...",
            blob_sha256=actual,
            declared_sha256=declared_sha,
        )
    )

    would_run = worktree_blob_id(str(generator.get("path")))
    committed = blob_id_at(commit, str(generator.get("path"))) if resolved else None
    checks.append(
        check(
            "V-PROV-03",
            "PROVENANCE_VERIFICATION",
            "PASS" if would_run == committed and not is_dirty(str(generator.get("path"))) else "FAIL",
            f"would run {would_run} / commit holds {committed}",
            worktree_blob=would_run,
            committed_blob=committed,
        )
    )

    ancestor = bool(commit) and subprocess.run(
        ["git", "-C", str(REPO), "merge-base", "--is-ancestor", commit, "HEAD"],
        capture_output=True,
        check=False,
    ).returncode == 0
    checks.append(
        check(
            "V-PROV-04",
            "PROVENANCE_VERIFICATION",
            "PASS" if ancestor else "FAIL",
            "generator commit is an ancestor of HEAD" if ancestor else "not an ancestor of HEAD",
        )
    )

    freeze = last_commit(ORIGINAL)
    original_blob = blob_at(freeze, ORIGINAL) if freeze else None
    original_sha = sha256_bytes(original_blob or b"")
    cited = str((document.get("supersedes") or {}).get("sha256") or "")
    on_disk = sha256_file(REPO / ORIGINAL)
    checks.append(
        check(
            "V-PROV-05",
            "PROVENANCE_VERIFICATION",
            "PASS" if original_blob is not None and original_sha == cited and on_disk == cited else "FAIL",
            f"phase-1 blob {original_sha[:16]}..., successor cites {cited[:16]}..., disk {str(on_disk)[:16]}...",
            original_blob_sha256=original_sha,
            cited_sha256=cited,
            disk_sha256=on_disk,
            freeze_commit=freeze,
        )
    )

    # The phase-1 commit is a fact of the experiment, not something the successor may name.
    frozen_blob = blob_id_at(PHASE_ONE_COMMIT, ORIGINAL)
    head_blob = blob_id_at("HEAD", ORIGINAL)
    untouched = frozen_blob is not None and frozen_blob == head_blob and not is_dirty(ORIGINAL)
    checks.append(
        check(
            "V-PROV-06",
            "PROVENANCE_VERIFICATION",
            "PASS" if untouched else "FAIL",
            f"phase-1 blob {frozen_blob} / HEAD blob {head_blob} / dirty={is_dirty(ORIGINAL)}",
            phase_one_commit=PHASE_ONE_COMMIT,
            phase_one_blob=frozen_blob,
            head_blob=head_blob,
        )
    )
    return checks


# --------------------------------------------------------------------------- #
# TEMPORAL: when the declaration binds, and whether anything precedes it
# --------------------------------------------------------------------------- #
def temporal_checks() -> list[Check]:
    document = read_json(REPO / DECLARATION)
    window = document.get("capture_window") or {}
    issued = ms(str(document.get("issued_at_utc")))
    effective = ms(str(document.get("effective_from_utc")))
    start = ms(str(window.get("start_utc")))
    checks: list[Check] = []

    checks.append(
        check(
            "V-TEMP-01",
            "TEMPORAL_VERIFICATION",
            "PASS" if issued <= effective <= start else "FAIL",
            f"issued {iso(issued)} <= effective {iso(effective)} <= window {iso(start)}",
            issued_at_utc=iso(issued),
            effective_from_utc=iso(effective),
            window_start_utc=iso(start),
        )
    )

    commit = last_commit(DECLARATION)
    stamp = commit_epoch(commit) if commit else None
    checks.append(
        check(
            "V-TEMP-02",
            "TEMPORAL_VERIFICATION",
            "PASS" if stamp is not None and stamp * 1000 < start else "FAIL",
            f"declaration commit {commit} dated {iso(stamp * 1000) if stamp else 'unknown'}",
            declaration_commit=commit,
            committed_at_utc=iso(stamp * 1000) if stamp else None,
        )
    )

    ancestor = bool(commit) and subprocess.run(
        ["git", "-C", str(REPO), "merge-base", "--is-ancestor", str(commit), "HEAD"],
        capture_output=True,
        check=False,
    ).returncode == 0
    checks.append(
        check(
            "V-TEMP-03",
            "TEMPORAL_VERIFICATION",
            "PASS" if ancestor else "FAIL",
            "declaration commit is an ancestor of HEAD" if ancestor else "not an ancestor of HEAD",
        )
    )

    clean = commit is not None and not is_dirty(DECLARATION)
    checks.append(
        check(
            "V-TEMP-04",
            "TEMPORAL_VERIFICATION",
            "PASS" if clean else "FAIL",
            "the committed declaration is the file on disk" if clean else "declaration is uncommitted or edited",
        )
    )

    declared_files = [str(entry.get("normalized_file")) for entry in document.get("entries", [])]
    present = [name for name in declared_files if (REPO / name).exists()]
    checks.append(
        check(
            "V-TEMP-05",
            "TEMPORAL_VERIFICATION",
            "PASS" if not present else "FAIL",
            "no capture exists, so no retroactive validity is claimed"
            if not present
            else f"datasets already on disk: {present}",
            captures_checked=0,
            datasets_present=present,
        )
    )

    source = (REPO / GENERATOR).read_text(encoding="utf-8")
    try:
        tree = ast.parse(source)
    except SyntaxError as error:  # pragma: no cover - a broken generator is already fatal
        return [*checks, check("V-TEMP-06", "TEMPORAL_VERIFICATION", "FAIL", str(error))]
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        str(node.module).split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    } | {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    gated = "eligibility_defects" in calls and "authorize" in calls
    checks.append(
        check(
            "V-TEMP-06",
            "TEMPORAL_VERIFICATION",
            "PASS" if gated else "FAIL",
            "the extractor calls authorize() and eligibility_defects() before writing"
            if gated
            else f"the extractor does not gate on provenance: calls={sorted(calls)}",
            imports=sorted(imported),
        )
    )
    return checks


# --------------------------------------------------------------------------- #
# ARTIFACTS: the package exists, is committed, and the builder's digests agree
# --------------------------------------------------------------------------- #
def artefact_checks() -> list[Check]:
    checks: list[Check] = []
    # The verifier does not hash itself, the manifest or the final report into this control: all
    # three are produced after it. The seal covers the manifest, which covers the rest.
    required = [
        name
        for name in REQUIRED_ARTEFACTS
        if name not in ("EVIDENCE_MANIFEST.json", "WP_051_02D_FINAL_REPORT.md")
    ]
    missing = [name for name in required if not (OUT_DIR / name).is_file()]
    empty = [name for name in required if (OUT_DIR / name).is_file() and (OUT_DIR / name).stat().st_size == 0]
    uncommitted = [
        name
        for name in required
        if (OUT_DIR / name).is_file()
        and worktree_blob_id(_rel(OUT_DIR / name)) != blob_id_at("HEAD", _rel(OUT_DIR / name))
    ]
    checks.append(
        check(
            "V-ART-01",
            "ARTIFACT_INTEGRITY",
            "PASS" if not (missing or empty) else "FAIL",
            f"{len(required)} artefacts present" if not (missing or empty) else f"missing {missing} empty {empty}",
            missing=missing,
            empty=empty,
        )
    )
    checks.append(
        check(
            "V-ART-02",
            "ARTIFACT_INTEGRITY",
            "PASS" if not uncommitted else "FAIL",
            "every artefact is committed and unmodified" if not uncommitted else f"not in HEAD as on disk: {uncommitted}",
            uncommitted=uncommitted,
            head=git_text("rev-parse", "HEAD"),
        )
    )

    claims: list[str] = []
    if not (REPO / PREFLIGHT).is_file():
        claims.append("preflight report absent")
    else:
        reported = read_json(REPO / PREFLIGHT)
        declared_sha = sha256_file(REPO / DECLARATION)
        if reported.get("declaration", {}).get("sha256") != declared_sha:
            claims.append(
                f"preflight cites declaration {reported.get('declaration', {}).get('sha256')}, "
                f"recomputed {declared_sha}"
            )
        documented = read_json(REPO / DECLARATION)
        generator = documented.get("generator") or {}
        body = blob_at(str(generator.get("commit")), str(generator.get("path")))
        if reported.get("generator", {}).get("blob_sha256") != sha256_bytes(body or b""):
            claims.append("preflight cites another generator blob")
        if reported.get("generator", {}).get("commit") != generator.get("commit"):
            claims.append("preflight cites another generator commit")
    checks.append(
        check(
            "V-ART-03",
            "ARTIFACT_INTEGRITY",
            "PASS" if not claims else "FAIL",
            "the builder's reported declaration and generator digests recompute"
            if not claims
            else "; ".join(claims),
            disagreements=claims,
        )
    )
    return checks


# --------------------------------------------------------------------------- #
# POLICY: nothing outside the declaration moved, and nobody promoted anything
# --------------------------------------------------------------------------- #
def policy_checks() -> list[Check]:
    checks: list[Check] = []
    frozen_blob = blob_id_at(PHASE_ONE_COMMIT, ORIGINAL)
    head_blob = blob_id_at("HEAD", ORIGINAL)
    checks.append(
        check(
            "V-POL-01",
            "POLICY_COMPLIANCE",
            "PASS" if frozen_blob == head_blob and not is_dirty(ORIGINAL) else "FAIL",
            f"original declaration blob {head_blob} is the phase-1 blob"
            if frozen_blob == head_blob
            else f"{head_blob} != {frozen_blob}",
        )
    )

    decision = read_json(REPO / DECISION)
    promotion = decision.get("promotion") or {}
    unchanged = not is_dirty(DECISION) and blob_id_at("HEAD", DECISION) is not None
    verdict = decision.get("verifier_status")
    held = promotion.get("decision") == "NO_PROMOTION" and unchanged and verdict != "PASS"
    checks.append(
        check(
            "V-POL-02",
            "POLICY_COMPLIANCE",
            "PASS" if held else "FAIL",
            f"promotion {promotion.get('decision')}, prior verifier {verdict}, "
            f"decision file unchanged={unchanged}",
            promotion=promotion.get("decision"),
            prior_verifier_status=verdict,
            decision_file_unchanged=unchanged,
        )
    )

    source = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        str(node.module).split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    independent = "trading_bot" not in imported and "exp004a_provenance_preflight" not in imported
    checks.append(
        check(
            "V-POL-03",
            "POLICY_COMPLIANCE",
            "PASS" if independent and VERIFIER_ID != BUILDER_ID else "FAIL",
            "BUILDER != VERIFIER and the verifier imports neither the package nor the preflight"
            if independent
            else f"verifier imports {sorted(imported)}",
            verifier=VERIFIER_ID,
            builder=BUILDER_ID,
            imports=sorted(imported),
        )
    )

    generator = (REPO / GENERATOR).read_text(encoding="utf-8")
    forbidden = [
        token for token in ("requests.", "httpx.", "urllib", "ccxt", "api_key", "api_secret") if token in generator
    ]
    checks.append(
        check(
            "V-POL-04",
            "POLICY_COMPLIANCE",
            "PASS" if not forbidden else "FAIL",
            "the extractor holds no network client or credential" if not forbidden else f"found {forbidden}",
            forbidden=forbidden,
        )
    )

    prereg_unchanged = blob_id_at("HEAD", PREREG) == worktree_blob_id(PREREG)
    experiment = read_json(REPO / DECLARATION).get("experiment_id")
    checks.append(
        check(
            "V-POL-05",
            "POLICY_COMPLIANCE",
            "PASS" if prereg_unchanged and experiment == "EXP-004A" else "FAIL",
            f"preregistration unchanged={prereg_unchanged}, experiment {experiment}",
        )
    )
    return checks


# --------------------------------------------------------------------------- #
# assembly
# --------------------------------------------------------------------------- #
def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def verify() -> dict[str, Any]:
    groups = {
        "TECHNICAL_VERIFICATION": technical_checks(),
        "PROVENANCE_VERIFICATION": provenance_checks(),
        "TEMPORAL_VERIFICATION": temporal_checks(),
        "ARTIFACT_INTEGRITY": artefact_checks(),
        "POLICY_COMPLIANCE": policy_checks(),
    }
    controls = []
    for name in CONTROLS:
        checks = groups[name]
        status = "PASS" if checks and all(item.status == "PASS" for item in checks) else "FAIL"
        controls.append(
            {
                "control": name,
                "status": status,
                "checks": [item.as_dict() for item in checks],
                "failed_checks": [item.check_id for item in checks if item.status != "PASS"],
            }
        )
    status = "PASS" if all(control["status"] == "PASS" for control in controls) else "FAIL"
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": RUN_ID,
        "role": "independent verifier",
        "verifier_id": VERIFIER_ID,
        "builder_id": BUILDER_ID,
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "head_at_verification": git_text("rev-parse", "HEAD"),
        "declaration": {
            "path": DECLARATION,
            "sha256": sha256_file(REPO / DECLARATION),
            "commit": last_commit(DECLARATION),
        },
        "status": status,
        "controls": controls,
        "failed_controls": [item["control"] for item in controls if item["status"] != "PASS"],
        "limits": [
            "No prospective capture exists yet: the window opens 2026-10-22, so this verifies the "
            "binding and the refusals, not any observed market day.",
            "No external timestamp attestation is available; the chronology rests on Git ancestry "
            "plus the bar store's own fetched_at_ms. C-013 stays TIME_PROOF_WEAK.",
            "PASS here is not an authorisation, a 90-day validation or a promotion.",
        ],
        "economic_executions": 0,
    }


def _verify_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# WP-051-02D independent verification",
        "",
        f"**Verifier**: `{result['verifier_id']}` (not `{result['builder_id']}`)  ",
        f"**HEAD at verification**: `{result['head_at_verification']}`  ",
        f"**Declaration**: `{result['declaration']['path']}` at `{result['declaration']['commit']}`  ",
        f"**Status**: `{result['status']}`",
        "",
        "| Control | Status | Failed checks |",
        "| --- | --- | --- |",
    ]
    for control in result["controls"]:
        failed = ", ".join(control["failed_checks"]) or "-"
        lines.append(f"| `{control['control']}` | `{control['status']}` | {failed} |")
    lines += ["", "## Checks", ""]
    for control in result["controls"]:
        lines.append(f"### {control['control']} — {control['status']}")
        lines.append("")
        lines.append("| Check | Status | Detail |")
        lines.append("| --- | --- | --- |")
        for item in control["checks"]:
            detail = str(item["detail"]).replace("|", "\\|")
            lines.append(f"| `{item['check_id']}` | `{item['status']}` | {detail} |")
        lines.append("")
    lines += ["## Limits", ""] + [f"- {limit}" for limit in result["limits"]] + [""]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# seal: the manifest, against the bytes that are actually here
# --------------------------------------------------------------------------- #
def seal() -> dict[str, Any]:
    path = REPO / MANIFEST
    if not path.is_file():
        return {
            "status": "BLOCKED",
            "reason": f"{MANIFEST} does not exist; nothing to seal",
            "verifier_id": VERIFIER_ID,
        }
    manifest = read_json(path)
    entries = []
    for entry in manifest.get("entries", []):
        rel = str(entry.get("path") or "")
        target = REPO / rel
        digest = sha256_file(target)
        entries.append(
            {
                "path": rel,
                "recorded_sha256": entry.get("sha256"),
                "recomputed_sha256": digest,
                "sha256_matches": digest is not None and digest == entry.get("sha256"),
                "worktree_blob": worktree_blob_id(rel) if target.is_file() else None,
                "head_blob": blob_id_at("HEAD", rel),
            }
        )
    listed = {str(entry.get("path")) for entry in manifest.get("entries", [])}
    required = [
        f"{OUT_DIR_REL}/{name}"
        for name in REQUIRED_ARTEFACTS
        if name not in ("EVIDENCE_MANIFEST.json", "WP_051_02D_FINAL_REPORT.md")
    ]
    unlisted = [name for name in required if name not in listed]
    mismatched = [entry["path"] for entry in entries if not entry["sha256_matches"]]
    status = "PASS" if not (unlisted or mismatched) and entries else "FAIL"
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": RUN_ID,
        "role": "independent verifier (seal)",
        "verifier_id": VERIFIER_ID,
        "sealed_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "head_at_seal": git_text("rev-parse", "HEAD"),
        "manifest": {
            "path": MANIFEST,
            "sha256": sha256_file(path),
            "entries": len(entries),
            "self_excluded": manifest.get("hashing", {}).get("self_exclusion"),
        },
        "status": status,
        "mismatched": mismatched,
        "unlisted_required": unlisted,
        "entries": entries,
        "note": (
            "The seal cannot hash itself, and it does not re-hash the verification report it "
            "accompanies: it hashes every entry the manifest claims. A commit made after the seal "
            "is the durable record of this file."
        ),
        "economic_executions": 0,
    }


OUT_DIR_REL = "docs/agentic/exp004a/wp051_02d"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", choices=("verify", "seal"), default="verify")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    out_dir = args.out.resolve() if args.out else OUT_DIR

    try:
        if args.mode == "verify":
            result = verify()
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "WP_051_02D_PROVENANCE_VERIFICATION.json").write_text(
                json.dumps(result, indent=2) + "\n", encoding="utf-8"
            )
            (out_dir / "WP_051_02D_PROVENANCE_VERIFICATION.md").write_text(
                _verify_markdown(result), encoding="utf-8"
            )
            for control in result["controls"]:
                failed = ", ".join(control["failed_checks"]) or "-"
                _print(f"[verify] {control['status']:<5} {control['control']:<24} {failed}")
            _print(f"[verify] {result['status']} - {len(result['controls'])} controls")
            return STATUS_EXIT[result["status"]]

        sealed = seal()
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "WP_051_02D_VERIFIER_SEAL.json").write_text(
            json.dumps(sealed, indent=2) + "\n", encoding="utf-8"
        )
        _print(f"[seal] {sealed['status']} - {sealed.get('mismatched')} - {sealed.get('unlisted_required')}")
        return STATUS_EXIT.get(str(sealed["status"]), EXIT_ERROR)
    except Exception as error:  # a verifier that crashes must never look like a pass
        _print(f"[verify] ERROR {type(error).__name__}: {error}")
        return EXIT_ERROR


def _print(text: str) -> None:
    sys.stdout.write(text.encode("ascii", "backslashreplace").decode("ascii") + "\n")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
