#!/usr/bin/env python
"""Builder-side preflight for RFC-EXP004A-051-02D: does the successor declaration actually bind?

The verifier decides whether the chain holds; this script decides whether there is a chain to verify,
and it writes down the answer with the exact bytes it looked at. Every check below is one of the
failures RFC §7 names, so a green preflight is a statement about twelve named conditions and about
nothing else — it is not a certification, a promotion or a profitability claim.

``inspect``  read-only; writes the report only when ``--out`` is given.
``seal``     also emits ``EVIDENCE_MANIFEST.json`` over the named artefacts.

Exit codes: ``0`` all controls held, ``2`` a control failed (BLOCKED), ``4`` the script could not run.

No network call, no order, no credential. It reads Git plumbing and hashes files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from trading_bot.research.prospective import provenance  # noqa: E402
from trading_bot.research.prospective.provenance import (  # noqa: E402
    ORIGINAL_DECLARATION,
    SUCCESSOR_DECLARATION,
    DeclarationError,
    authorize,
    load,
    validate,
)

RUN_ID = "wp051-02d/EXP-004A/2026-10-21"
SCHEMA_VERSION = "1.0"
OUT_DIR = "docs/agentic/exp004a/wp051_02d"

EXIT_PASS = 0
EXIT_BLOCKED = 2
EXIT_ERROR = 4

EXPECTED_ORIGINAL_SHA256 = "8946f871a97b7575b1a9aa2900b3243f88d07a4821d09d6d0a3c113f1e5de211"
EXPECTED_GENERATOR = "scripts/exp004a_capture.py"


@dataclass
class Check:
    """One control, its evidence, and the honest verdict."""

    name: str
    status: str
    detail: str
    seconds: float = 0.0
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "control": self.name,
            "status": self.status,
            "detail": self.detail,
            "seconds": round(self.seconds, 4),
            "evidence": self.evidence,
        }


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False, timeout=120
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(name: str, function: Any) -> Check:
    started = time.perf_counter()
    try:
        status, detail, evidence = function()
    except Exception as error:  # a crashed preflight must not read as a pass
        status, detail, evidence = "ERROR", f"{type(error).__name__}: {error}", {}
    return Check(name, status, detail, time.perf_counter() - started, evidence)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument("--declaration", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--seal", action="store_true", help="also write EVIDENCE_MANIFEST.json")
    parser.add_argument(
        "--manifest-only",
        action="store_true",
        help="re-emit the manifest over the artefacts already on disk, re-running no control",
    )
    args = parser.parse_args(argv)

    repo = args.repo.resolve()
    declaration_path = (args.declaration or repo / SUCCESSOR_DECLARATION).resolve()
    out_dir = (args.out.resolve() if args.out else repo / OUT_DIR)
    started_at = datetime.now(UTC)

    if args.manifest_only:
        existing = json.loads((out_dir / "WP_051_02D_PREFLIGHT.json").read_text(encoding="utf-8"))
        manifest = _manifest(repo, out_dir, existing)
        (out_dir / "EVIDENCE_MANIFEST.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        _safe_print(f"[manifest] {len(manifest['entries'])} entries, missing {manifest['missing']}")
        return EXIT_PASS if not manifest["missing"] else EXIT_BLOCKED

    declaration = load(declaration_path)
    defects = validate(declaration, repo=repo)
    defect_codes = {defect.code for defect in defects}

    def declaration_schema() -> tuple[str, str, dict[str, Any]]:
        missing = [field for field in provenance.REQUIRED_FIELDS if declaration.document.get(field) is None]
        if missing:
            return "FAIL", f"missing {missing}", {"missing": missing}
        if declaration.schema_version != provenance.SCHEMA_VERSION:
            return "FAIL", f"schema_version {declaration.schema_version}", {}
        return "PASS", f"{len(declaration.entries)} entries, schema {declaration.schema_version}", {}

    def original_unchanged() -> tuple[str, str, dict[str, Any]]:
        original = repo / ORIGINAL_DECLARATION
        digest = _sha256(original)
        if digest != EXPECTED_ORIGINAL_SHA256:
            return "FAIL", f"{ORIGINAL_DECLARATION} is {digest}", {"sha256": digest}
        if declaration.supersedes.get("sha256") != digest:
            return "FAIL", "the successor cites another digest", {"sha256": digest}
        if _git(repo, "status", "--porcelain", "--", ORIGINAL_DECLARATION):
            return "FAIL", "the original has uncommitted changes", {"sha256": digest}
        return "PASS", f"sha256 {digest[:16]}... unchanged", {"sha256": digest}

    def supersedes_link() -> tuple[str, str, dict[str, Any]]:
        blob = _git(repo, "rev-parse", f"HEAD:{ORIGINAL_DECLARATION}")
        cited = str(declaration.supersedes.get("git_blob") or "")
        if not blob or blob != cited:
            return "FAIL", f"committed blob {blob or 'absent'} != cited {cited}", {}
        return "PASS", f"successor cites blob {blob[:12]}...", {"git_blob": blob}

    def generator_commit() -> tuple[str, str, dict[str, Any]]:
        commit = declaration.generator_commit
        resolved = provenance.resolve_commit(repo, commit)
        if len(commit) != 40 or resolved != commit:
            return "FAIL", f"{commit!r} is not a full resolvable SHA", {"commit": commit}
        return "PASS", f"{commit}", {"commit": commit}

    def generator_bytes() -> tuple[str, str, dict[str, Any]]:
        rel = declaration.generator_path
        would_run = provenance.worktree_blob_id(repo, rel)
        committed = provenance.committed_blob_id(repo, declaration.generator_commit, rel)
        body = provenance.file_bytes_at(repo, declaration.generator_commit, rel)
        digest = provenance.sha256_bytes(body or b"")
        if would_run != committed:
            return "FAIL", f"would run {would_run}, {generator_commit} holds {committed}", {}
        if digest != declaration.generator.get("blob_sha256"):
            return "FAIL", f"declared {declaration.generator.get('blob_sha256')} != {digest}", {}
        return (
            "PASS",
            f"{rel} at {declaration.generator_commit[:8]} is blob {committed[:12]}... / sha256 {digest[:16]}...",
            {"blob_sha256": digest, "git_blob": committed},
        )

    def generator_clean() -> tuple[str, str, dict[str, Any]]:
        if provenance.path_is_dirty(repo, EXPECTED_GENERATOR):
            return "FAIL", f"{EXPECTED_GENERATOR} has uncommitted changes", {}
        return "PASS", "generator path is clean", {}

    def temporal() -> tuple[str, str, dict[str, Any]]:
        issued = declaration.issued_at_ms
        effective = declaration.effective_from_ms
        start = declaration.window_start_ms
        if not issued <= effective <= start:
            return (
                "FAIL",
                f"issued {provenance.to_iso(provenance._from_ms(issued))} / effective "
                f"{provenance.to_iso(provenance._from_ms(effective))} / window "
                f"{provenance.to_iso(provenance._from_ms(start))} is not ordered",
                {},
            )
        return (
            "PASS",
            f"effective {provenance.to_iso(provenance._from_ms(effective))} precedes the window "
            f"{provenance.to_iso(provenance._from_ms(start))}",
            {
                "issued_at_utc": provenance.to_iso(provenance._from_ms(issued)),
                "effective_from_utc": provenance.to_iso(provenance._from_ms(effective)),
                "window_start_utc": provenance.to_iso(provenance._from_ms(start)),
            },
        )

    def declaration_committed() -> tuple[str, str, dict[str, Any]]:
        rel = provenance._relative(repo, declaration_path)
        commit = provenance.last_commit_for_path(repo, rel)
        if not commit:
            return "FAIL", f"{rel} is not committed", {}
        stamp = provenance.commit_epoch(repo, commit)
        if stamp is None:
            return "FAIL", f"commit {commit} has no timestamp", {}
        committed_at = datetime.fromtimestamp(stamp, UTC)
        if stamp * 1000 >= declaration.window_start_ms:
            return "FAIL", f"commit {commit} is dated {committed_at.isoformat()}", {}
        if not provenance.is_ancestor(repo, commit):
            return "FAIL", f"{commit} is not an ancestor of HEAD", {}
        return (
            "PASS",
            f"commit {commit[:12]}... at {committed_at.isoformat()} precedes the window",
            {"commit": commit, "committed_at_utc": committed_at.isoformat()},
        )

    def entries_unchanged() -> tuple[str, str, dict[str, Any]]:
        drift = [defect for defect in defects if defect.code in {"ENTRY_DRIFT", "ENTRY_NOT_IN_ORIGINAL"}]
        if drift:
            return "FAIL", "; ".join(defect.detail for defect in drift[:3]), {}
        return "PASS", "every field except generator_code_commit equals phase 1", {}

    def window_unchanged() -> tuple[str, str, dict[str, Any]]:
        original = json.loads((repo / ORIGINAL_DECLARATION).read_text(encoding="utf-8"))
        pairs = {
            (row.get("period_start_utc"), row.get("period_end_utc")) for row in original["entries"]
        }
        declared = (declaration.window.get("start_utc"), declaration.window.get("end_utc"))
        if pairs != {declared}:
            return "FAIL", f"windows {sorted(pairs)} != declared {declared}", {}
        return "PASS", f"{declared[0]} to {declared[1]}", {"capture_window": list(declared)}

    def datasets_absent() -> tuple[str, str, dict[str, Any]]:
        present = [
            entry.get("normalized_file")
            for entry in declaration.entries
            if isinstance(entry.get("normalized_file"), str)
            and (repo / str(entry["normalized_file"])).exists()
        ]
        if present:
            return "FAIL", f"already on disk before the window: {present}", {"present": present}
        return "PASS", "no declared dataset exists yet", {}

    def slice_contract() -> tuple[str, str, dict[str, Any]]:
        import exp004a_capture as capture

        try:
            capture.resolve_spec("st6:tape", capture.load_declaration())
        except capture.SliceError as error:
            return "PASS", f"st6:tape refused: {error}", {"refusal": str(error)}
        return "FAIL", "st6:tape resolved; a rule was invented", {}

    def overwrite_refusal() -> tuple[str, str, dict[str, Any]]:
        import inspect

        import exp004a_capture as capture

        source = inspect.getsource(capture.write_slice)
        if "already exists" not in source:
            return "FAIL", "write_slice does not refuse an existing target", {}
        return "PASS", "write_slice refuses an existing target", {}

    def write_permissions() -> tuple[str, str, dict[str, Any]]:
        target = repo / "data" / "exp004a"
        probe = target if target.exists() else target.parent
        if not probe.is_dir():
            return "FAIL", f"{probe} is not a directory", {}
        writable = probe.stat().st_mode & 0o200
        return ("PASS" if writable else "FAIL"), f"{probe.relative_to(repo)} writable", {}

    def no_live() -> tuple[str, str, dict[str, Any]]:
        """The extractor must not be able to place an order, even by accident."""
        text = (repo / EXPECTED_GENERATOR).read_text(encoding="utf-8")
        forbidden = [
            token
            for token in ("requests.", "httpx.", "urllib", "ccxt", "api_key", "api_secret")
            if token in text
        ]
        if forbidden:
            return "FAIL", f"generator references {forbidden}", {"forbidden": forbidden}
        return "PASS", "no network client, credential or venue client in the extractor", {}

    checks = [
        _run("DECLARATION_SCHEMA", declaration_schema),
        _run("ORIGINAL_DECLARATION_UNCHANGED", original_unchanged),
        _run("SUPERSEDES_LINK", supersedes_link),
        _run("GENERATOR_COMMIT_FULL_SHA", generator_commit),
        _run("GENERATOR_BYTES_MATCH_COMMIT", generator_bytes),
        _run("GENERATOR_WORKTREE_CLEAN", generator_clean),
        _run("TEMPORAL_ORDER", temporal),
        _run("DECLARATION_COMMITTED_BEFORE_WINDOW", declaration_committed),
        _run("ENTRIES_UNCHANGED_EXCEPT_COMMIT", entries_unchanged),
        _run("CAPTURE_WINDOW_UNCHANGED", window_unchanged),
        _run("DATASETS_ABSENT_BEFORE_WINDOW", datasets_absent),
        _run("ST6_TAPE_STILL_REFUSED", slice_contract),
        _run("OVERWRITE_REFUSED", overwrite_refusal),
        _run("WRITE_PERMISSION", write_permissions),
        _run("NO_LIVE_ORDER_PATH", no_live),
    ]

    # A defect the checks above did not fold into a named control is still a block, never a note.
    unnamed = sorted(defect_codes - {
        "ORIGINAL_DECLARATION_SHA256_MISMATCH",
        "ORIGINAL_DECLARATION_BLOB_MISMATCH",
        "ORIGINAL_DECLARATION_MODIFIED_IN_WORKTREE",
        "ENTRY_DRIFT",
        "ENTRY_NOT_IN_ORIGINAL",
        "GENERATOR_COMMIT_NOT_FULL_SHA",
        "GENERATOR_COMMIT_ZERO",
        "GENERATOR_COMMIT_UNKNOWN",
        "GENERATOR_FILE_DIFFERS_FROM_DECLARED",
        "GENERATOR_WORKTREE_DIRTY",
        "TEMPORAL_ORDER",
        "DECLARATION_NOT_COMMITTED",
        "DECLARATION_COMMITTED_AFTER_WINDOW_START",
        "DECLARATION_WORKTREE_DIRTY",
        "DECLARATION_COMMIT_NOT_ANCESTOR",
        "CAPTURE_BEFORE_EFFECTIVE",
        "CAPTURE_OUTSIDE_DECLARED_WINDOW",
    })
    if unnamed:
        checks.append(Check("UNFOLDED_DEFECTS", "FAIL", f"{unnamed}", 0.0, {"codes": unnamed}))

    try:
        record = authorize(declaration_path, repo=repo)
        record_error = None
    except DeclarationError as error:
        record = None
        record_error = error

    failed = [check for check in checks if check.status != "PASS"]
    status = "PASS" if not failed and record is not None else "BLOCKED"
    report = {
        "schema_version": SCHEMA_VERSION,
        "run_id": RUN_ID,
        "role": "builder",
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "started_at_utc": started_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repo": {
            "head": _git(repo, "rev-parse", "HEAD"),
            "branch": _git(repo, "rev-parse", "--abbrev-ref", "HEAD"),
        },
        "declaration": {
            "path": provenance._relative(repo, declaration_path),
            "declaration_id": declaration.declaration_id,
            "sha256": _sha256(declaration_path),
            "commit": provenance.last_commit_for_path(
                repo, provenance._relative(repo, declaration_path)
            ),
        },
        "generator": {
            "path": declaration.generator_path,
            "commit": declaration.generator_commit,
            "blob_sha256": declaration.generator.get("blob_sha256"),
        },
        "status": status,
        "checks": [check.as_dict() for check in checks],
        "failed_controls": [check.name for check in failed],
        "defects": [defect.as_dict() for defect in defects],
        "provenance_record": record.as_dict() if record else None,
        "authorize_error": record_error.codes if record_error else None,
        "not_a_certification": (
            "PASS here means the twelve provenance controls held on this checkout at this instant. "
            "It does not authorise a run, does not validate 90 days, and does not promote anything."
        ),
        "economic_executions": 0,
    }

    if args.out is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "WP_051_02D_PREFLIGHT.json").write_text(
            json.dumps(report, indent=2, sort_keys=False) + "\n", encoding="utf-8"
        )
        (out_dir / "WP_051_02D_PREFLIGHT.md").write_text(_markdown(report), encoding="utf-8")
        if args.seal:
            manifest = _manifest(repo, out_dir, report)
            (out_dir / "EVIDENCE_MANIFEST.json").write_text(
                json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
            )

    for check in checks:
        _safe_print(f"[preflight] {check.status:<5} {check.name:<38} {check.detail}")
    _safe_print(f"[preflight] {status} - {len(checks)} controls - {len(failed)} failed")
    return EXIT_PASS if status == "PASS" else EXIT_BLOCKED


MANIFEST_ENTRIES = (
    ("declaration", SUCCESSOR_DECLARATION),
    ("rule", "src/trading_bot/research/prospective/provenance.py"),
    ("generator", EXPECTED_GENERATOR),
    ("test", "tests/unit/research/test_exp004a_provenance.py"),
    ("test", "tests/unit/research/test_exp004a_capture.py"),
    ("tool", "scripts/exp004a_provenance_preflight.py"),
    ("tool", "scripts/exp004a_provenance_verify.py"),
    ("input", ORIGINAL_DECLARATION),
    ("input", "docs/RFC-050_EXP004A_TWO_PHASE_FREEZE.md"),
    ("doc", "docs/agentic/exp004a/wp051_02d/RFC_EXP004A_051_02D.md"),
    ("doc", "docs/agentic/exp004a/wp051_02d/WP_051_02D_BASELINE.json"),
    ("output", "docs/agentic/exp004a/wp051_02d/WP_051_02D_PREFLIGHT.json"),
    ("doc", "docs/agentic/exp004a/wp051_02d/WP_051_02D_PREFLIGHT.md"),
    ("doc", "docs/agentic/exp004a/wp051_02d/WP_051_02D_TEST_REPORT.md"),
    ("doc", "docs/agentic/exp004a/wp051_02d/WP_051_02D_CHANGELOG.md"),
    ("doc", "docs/agentic/exp004a/wp051_02d/RUN_REPORT.md"),
    ("doc", "docs/agentic/exp004a/wp051_02d/RUN_REPORT.json"),
    ("independent", "docs/agentic/exp004a/wp051_02d/WP_051_02D_PROVENANCE_VERIFICATION.json"),
    ("independent", "docs/agentic/exp004a/wp051_02d/WP_051_02D_PROVENANCE_VERIFICATION.md"),
)


def _manifest(repo: Path, out_dir: Path, report: dict[str, Any]) -> dict[str, Any]:
    """Digest every closure artefact, and say why the last two cannot be inside it."""
    entries = []
    missing = []
    for role, relative in MANIFEST_ENTRIES:
        path = repo / relative
        if not path.is_file():
            missing.append(relative)
            continue
        body = path.read_bytes()
        blob = _git(repo, "rev-parse", f"HEAD:{relative}") or None
        entries.append(
            {
                "role": role,
                "path": relative,
                "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
                "git_blob": blob,
                "blob_sha256": hashlib.sha256(
                    provenance.file_bytes_at(repo, "HEAD", relative) or b""
                ).hexdigest()
                if blob
                else None,
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": RUN_ID,
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "head_when_generated": _git(repo, "rev-parse", "HEAD"),
        "preflight_status": report["status"],
        "hashing": {
            "sha256": "bytes as read from this checkout",
            "git_blob": "the object id Git stores; stable across checkouts",
            "blob_sha256": "sha256 of the committed blob, not of a CRLF-restored checkout",
            "self_exclusion": (
                "this manifest does not hash itself, and it does not hash the final report: the "
                "report is emitted after the verifier has read the chain, so including it would "
                "either freeze a report that cannot mention the verdict or leave a digest that "
                "the next edit breaks. The commit that carries both files addresses them."
            ),
        },
        "missing": missing,
        "entries": entries,
    }


def _safe_print(text: str) -> None:
    """A Windows console is cp1252; an unprintable arrow must not turn a PASS into a traceback."""
    sys.stdout.write(text.encode("ascii", "backslashreplace").decode("ascii") + "\n")


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# WP-051-02D preflight",
        "",
        f"**Run**: `{report['run_id']}`  ",
        f"**HEAD**: `{report['repo']['head']}`  ",
        f"**Declaration**: `{report['declaration']['path']}` (`{report['declaration']['declaration_id']}`)  ",
        f"**Status**: `{report['status']}`",
        "",
        "| Control | Status | Detail |",
        "| --- | --- | --- |",
    ]
    for check in report["checks"]:
        detail = str(check["detail"]).replace("|", "\\|")
        lines.append(f"| `{check['control']}` | `{check['status']}` | {detail} |")
    lines += [
        "",
        "> PASS here means these controls held on this checkout at this instant. It is not an "
        "authorisation, a 90-day validation or a promotion.",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
