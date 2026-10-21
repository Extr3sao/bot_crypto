#!/usr/bin/env python
"""WP-051-02E preflight: has the declared window opened, and does the frozen extractor still refuse?

This is the builder side of RFC-EXP004A-051-02E. It answers four questions and writes the answers
with the bytes that produced them:

1. does the phase-2 declaration still bind (the same ``authorize`` the extractor calls), and are the
   phase-1 declaration, the generator and the sealed 02D package still the objects they were;
2. what does the forward store actually hold, and does any of it open inside the declared window;
3. does the declared command still refuse what it must refuse — ``st6:tape``, a window it cannot
   leave, an empty window — *without publishing a byte*;
4. which of ``PENDING_WINDOW``, ``NO_ELIGIBLE_DATA``, ``NOT_ELIGIBLE``, ``CAPTURED``, ``BLOCKED``
   describes the attempt that just happened.

The distinction the first three questions exist to protect is the one this RFC is about: a preflight
that goes green is not a capture. ``READY_FOR_WINDOW`` says the machinery is bound and the window has
not opened yet; it says nothing about market data, profitability or certification, and there is no
code path here that can turn it into ``CAPTURED`` without a dataset on disk produced by the frozen
extractor itself.

Read-only with respect to the freeze: no declaration, no generator, no admission rule and no sealed
artefact is opened for writing. The only writes are the reports named on the command line, plus
whatever the extractor itself writes when — and only when — the window is open and the bytes are
eligible.

Exit codes: ``0`` the attempt happened and its state is one of the non-failure states, ``2`` a hard
control failed or the attestation is violated, ``4`` the preflight could not run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.research.prospective.provenance import (  # noqa: E402
    ORIGINAL_DECLARATION,
    SUCCESSOR_DECLARATION,
    DeclarationError,
    authorize,
    load,
)
from trading_bot.research.prospective.store import (  # noqa: E402
    INTERVAL_MS,
    StoreError,
    index_series,
)

RUN_ID = "wp051-02e/EXP-004A/2026-10-21"
SCHEMA_VERSION = "1.0"
OUT_DIR = "docs/agentic/exp004a/wp051_02e"
GENERATOR = "scripts/exp004a_capture.py"
DATASET_DIR = "data/exp004a"
STORE_ROOT = "data/forward/edge03"
SEALED_MANIFEST = "docs/agentic/exp004a/wp051_02d/EVIDENCE_MANIFEST.json"

EXIT_OK = 0
EXIT_BLOCKED = 2
EXIT_ERROR = 4

#: The states of RFC §6. ``CAPTURED`` is the only one that may be followed by a capture PASS, and it
#: requires a dataset on disk; every other state is a truthful non-PASS.
STATES = (
    "PENDING_WINDOW",
    "NO_ELIGIBLE_DATA",
    "NOT_ELIGIBLE",
    "CAPTURED",
    "BLOCKED",
    "FAIL",
)

#: Every closure artefact this package must leave in Git. Kept here rather than read from the
#: manifest so that a missing file is a failure and not a smaller manifest.
CLOSURE_ARTEFACTS = (
    ("doc", "docs/agentic/exp004a/wp051_02e/RFC_EXP004A_051_02E.md"),
    ("baseline", "docs/agentic/exp004a/wp051_02e/WP_051_02E_BASELINE.json"),
    ("builder", "docs/agentic/exp004a/wp051_02e/WP_051_02E_PREFLIGHT.json"),
    ("builder", "docs/agentic/exp004a/wp051_02e/WP_051_02E_CAPTURE_REPORT.json"),
    ("independent", "docs/agentic/exp004a/wp051_02e/WP_051_02E_INDEPENDENT_VERIFICATION.json"),
    ("doc", "docs/agentic/exp004a/wp051_02e/WP_051_02E_FINAL_REPORT.md"),
    ("doc", "docs/agentic/exp004a/wp051_02e/RUN_REPORT.md"),
    ("report", "docs/agentic/exp004a/wp051_02e/RUN_REPORT.json"),
    ("evidence", "docs/agentic/exp004a/wp051_02e/evidence/TEST_RUNS.json"),
    ("tool", "scripts/exp004a_wp051_02e_preflight.py"),
    ("tool", "scripts/exp004a_wp051_02e_verify.py"),
    ("test", "tests/unit/research/test_exp004a_wp051_02e.py"),
    ("declaration", SUCCESSOR_DECLARATION),
    ("input", ORIGINAL_DECLARATION),
    ("generator", GENERATOR),
    ("input", SEALED_MANIFEST),
)


@dataclass
class Check:
    """One control, the evidence it looked at, and the verdict it earned."""

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


# --------------------------------------------------------------------------- #
# primitives
# --------------------------------------------------------------------------- #
def iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def now_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)


def parse_ms(value: Any, field_name: str) -> int:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{field_name} requires an explicit UTC Z timestamp")
    return int(datetime.fromisoformat(value[:-1] + "+00:00").timestamp() * 1000)


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False, timeout=120
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def run(name: str, function: Any) -> Check:
    started = time.perf_counter()
    try:
        status, detail, evidence = function()
    except Exception as error:  # a crashed control must not read as a pass
        status, detail, evidence = "ERROR", f"{type(error).__name__}: {error}", {}
    return Check(name, status, detail, time.perf_counter() - started, evidence)


def window_state(start_ms: int, end_ms: int, at_ms: int) -> str:
    """Where an instant sits relative to the declared window. No rounding, no grace period."""
    if at_ms < start_ms:
        return "BEFORE_WINDOW"
    if at_ms < end_ms:
        return "OPEN"
    return "CLOSED"


def declared_slices(document: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """The ``<interval>:<asset>`` pairs the declaration itself names, tape excluded by contract.

    ``st6:tape`` is in the declaration and is *not* a bar series, so it is reported separately by
    the ``ST6_TAPE_REFUSED`` control instead of being smuggled into the capture loop.
    """
    pairs: list[tuple[str, dict[str, Any]]] = []
    for entry in document.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        command = str(entry.get("generator_command") or "")
        if "--slice" not in command:
            continue
        spec = command.split("--slice", 1)[1].strip()
        pairs.append((spec, entry))
    return pairs


def store_snapshot(
    repo: Path, entry: dict[str, Any], *, start_ms: int, end_ms: int, effective_ms: int, at_ms: int
) -> dict[str, Any]:
    """What the forward store holds for one declared asset, counted against the declaration.

    ``fetched_after_now`` is the look-ahead counter: a bar the store says was stored in the future
    cannot have been stored at all, and is counted rather than silently believed.
    """
    interval = str(entry.get("timeframe"))
    asset = str(entry.get("asset"))
    path = repo / STORE_ROOT / interval / f"{asset}.jsonl"
    snapshot: dict[str, Any] = {
        "path": path.relative_to(repo).as_posix(),
        "asset": asset,
        "interval": interval,
        "present": path.is_file(),
        "bytes": path.stat().st_size if path.is_file() else 0,
        "sha256_at_read": sha256_file(path),
        "bytes_at_read": path.stat().st_size if path.is_file() else 0,
    }
    if not path.is_file():
        return {**snapshot, "readable": False, "error": "the series file does not exist"}
    try:
        index = index_series(path, asset, interval)
    except StoreError as error:
        return {**snapshot, "readable": False, "error": str(error)}

    opens = [bar.open_ms for bar in index.bars]
    in_window = [bar for bar in index.bars if start_ms <= bar.open_ms < end_ms]
    lag_bound = int((entry.get("generator_parameters") or {}).get("lag_bound_ms") or 0)
    return {
        **snapshot,
        "readable": True,
        "bars": len(index.bars),
        "first_open_utc": iso(min(opens)),
        "last_open_utc": iso(max(opens)),
        "last_fetched_at_utc": iso(max(bar.fetched_at_ms for bar in index.bars)),
        "bars_opening_in_window": len(in_window),
        "first_open_in_window_utc": iso(min(bar.open_ms for bar in in_window)) if in_window else None,
        "bars_fetched_before_effective": sum(
            1 for bar in index.bars if bar.fetched_at_ms < effective_ms
        ),
        "bars_fetched_after_now": sum(1 for bar in index.bars if bar.fetched_at_ms > at_ms),
        "unclosed_bars": sum(1 for bar in index.bars if not bar.closed),
        "duplicate_opens": len(opens) - len(set(opens)),
        "unordered": opens != sorted(opens),
        "negative_lag_bars": sum(1 for bar in index.bars if bar.lag_ms < 0),
        "bars_beyond_lag_bound": sum(
            1 for bar in index.bars if lag_bound and not 0 <= bar.lag_ms <= lag_bound
        ),
        "lag_bound_ms": lag_bound or None,
        "age_of_last_fetch_ms": at_ms - max(bar.fetched_at_ms for bar in index.bars),
    }


def classify(
    *,
    state: str,
    exit_codes: dict[str, int],
    published: list[str],
) -> tuple[str, str]:
    """The attempt's name, given the window state, the exit codes and what reached the disk.

    Ordered from the most specific refusal to the most general failure, and every branch that is not
    ``CAPTURED`` requires the absence of a dataset: a slice that wrote bytes is never allowed to be
    reported as a refusal, and a refusal is never allowed to be reported as a capture.
    """
    if published:
        if state == "OPEN" and all(code == 0 for code in exit_codes.values()):
            return "CAPTURED", f"{len(published)} dataset(s) published inside the open window"
        return "FAIL", f"datasets exist although the attempt did not succeed: {published}"
    codes = set(exit_codes.values())
    if state == "BEFORE_WINDOW" and codes == {3}:
        return (
            "PENDING_WINDOW",
            "no bar opens inside the declared window yet; the extractor refused with exit 3 and "
            "wrote nothing",
        )
    if state == "OPEN" and codes == {3}:
        return "NO_ELIGIBLE_DATA", "the window is open but the store holds no bar inside it"
    if codes == {5}:
        return "NOT_ELIGIBLE", "the bytes exist but no declaration authorised them"
    if codes & {2, 4}:
        return "BLOCKED", f"the extractor refused on a contract or source error: {sorted(codes)}"
    if state == "CLOSED":
        return "FAIL", "the window has closed and no dataset was captured inside it"
    return "FAIL", f"unclassified attempt: state {state}, exit codes {sorted(codes)}"


def attempt(repo: Path, spec: str, entry: dict[str, Any], *, timeout: int = 300) -> dict[str, Any]:
    """Run the declared command exactly as the declaration names it. No extra flags, no override."""
    dataset = Path(str(entry.get("normalized_file")))
    target = repo / dataset
    before = target.exists()
    started = time.perf_counter()
    completed = subprocess.run(
        [sys.executable, GENERATOR, "--slice", spec],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return {
        "slice": spec,
        "dataset_id": str(entry.get("dataset_id")),
        "command": f"python {GENERATOR} --slice {spec}",
        "exit_code": completed.returncode,
        "duration_s": round(time.perf_counter() - started, 3),
        "dataset_path": dataset.as_posix(),
        "dataset_existed_before": before,
        "dataset_published": target.is_file(),
        "stdout": completed.stdout.strip()[:4000],
        "stderr": completed.stderr.strip()[:4000],
    }


# --------------------------------------------------------------------------- #
# report assembly
# --------------------------------------------------------------------------- #
def _manifest(repo: Path) -> dict[str, Any]:
    """Digest every closure artefact; say plainly what is absent instead of shrinking the list."""
    entries: list[dict[str, Any]] = []
    missing: list[str] = []
    for role, relative in CLOSURE_ARTEFACTS:
        path = repo / relative
        if not path.is_file():
            missing.append(relative)
            continue
        body = path.read_bytes()
        blob = git(repo, "rev-parse", f"HEAD:{relative}") or None
        entries.append(
            {
                "role": role,
                "path": relative,
                "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
                "git_blob": blob,
                "in_head": blob is not None,
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": RUN_ID,
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "head_when_generated": git(repo, "rev-parse", "HEAD"),
        "hashing": {
            "sha256": "bytes as read from this checkout",
            "git_blob": "the object id Git stores; null until the commit that carries the file",
            "self_exclusion": (
                "this manifest does not hash itself; the commit that carries it addresses it"
            ),
        },
        "artefacts": len(entries),
        "missing": missing,
        "entries": entries,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument("--declaration", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument(
        "--attempt",
        action="store_true",
        help="also run the declared capture command and write WP_051_02E_CAPTURE_REPORT.json",
    )
    parser.add_argument("--seal", action="store_true", help="write EVIDENCE_MANIFEST.json")
    parser.add_argument(
        "--manifest-only",
        action="store_true",
        help="re-emit the manifest over the artefacts on disk, running no control",
    )
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    out_dir = Path(args.out_dir).resolve() if args.out_dir else repo / OUT_DIR
    declaration_path = (
        Path(args.declaration).resolve() if args.declaration else repo / SUCCESSOR_DECLARATION
    )

    if args.manifest_only:
        out_dir.mkdir(parents=True, exist_ok=True)
        manifest = _manifest(repo)
        (out_dir / "EVIDENCE_MANIFEST.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        print(f"[manifest] {manifest['artefacts']} artefacts, missing {manifest['missing']}")
        return EXIT_OK if not manifest["missing"] else EXIT_BLOCKED

    started_at = datetime.now(UTC)
    at_ms = now_ms()

    try:
        declaration = load(declaration_path)
    except DeclarationError as error:
        print(json.dumps({"ok": False, "defects": [d.as_dict() for d in error.defects]}))
        return EXIT_BLOCKED

    start_ms = parse_ms(declaration.window.get("start_utc"), "capture_window.start_utc")
    end_ms = parse_ms(declaration.window.get("end_utc"), "capture_window.end_utc")
    effective_ms = parse_ms(declaration.document.get("effective_from_utc"), "effective_from_utc")
    state = window_state(start_ms, end_ms, at_ms)

    checks: list[Check] = []

    def authorize_declaration() -> tuple[str, str, dict[str, Any]]:
        try:
            record = authorize(declaration_path, repo=repo)
        except DeclarationError as error:
            return (
                "FAIL",
                f"the declaration does not bind: {', '.join(error.codes)}",
                {"defect_codes": list(error.codes)},
            )
        return (
            "PASS",
            f"{record.declaration_id} binds; generator {record.generator_commit[:12]}...",
            {"provenance": record.as_dict()},
        )

    def phase_one_bytes() -> tuple[str, str, dict[str, Any]]:
        path = repo / ORIGINAL_DECLARATION
        digest = sha256_file(path)
        cited = str(declaration.supersedes.get("sha256") or "")
        blob = git(repo, "rev-parse", f"HEAD:{ORIGINAL_DECLARATION}")
        dirty = git(repo, "status", "--porcelain", "--", ORIGINAL_DECLARATION)
        ok = digest == cited and dirty == ""
        return (
            "PASS" if ok else "FAIL",
            f"phase 1 sha256 {str(digest)[:16]}... blob {blob[:12]}... dirty={bool(dirty)}",
            {"sha256": digest, "cited_sha256": cited, "git_blob": blob, "dirty": bool(dirty)},
        )

    def generator_identity() -> tuple[str, str, dict[str, Any]]:
        commit = declaration.generator_commit
        body = subprocess.run(
            ["git", "-C", str(repo), "cat-file", "blob", f"{commit}:{GENERATOR}"],
            capture_output=True,
            check=False,
            timeout=120,
        )
        committed_sha = hashlib.sha256(body.stdout).hexdigest() if body.returncode == 0 else None
        would_run = git(repo, "hash-object", "--", GENERATOR)
        committed_blob = git(repo, "rev-parse", f"{commit}:{GENERATOR}")
        declared_blob = str(declaration.generator.get("blob_sha256") or "")
        ok = (
            committed_sha == declared_blob
            and would_run == committed_blob
            and git(repo, "status", "--porcelain", "--", GENERATOR) == ""
        )
        return (
            "PASS" if ok else "FAIL",
            f"{GENERATOR} at {commit[:12]} sha256 {str(committed_sha)[:16]}... would-run "
            f"{would_run[:12]}... == committed {committed_blob[:12]}...",
            {
                "commit": commit,
                "committed_sha256": committed_sha,
                "declared_sha256": declared_blob,
                "would_run_blob": would_run,
                "committed_blob": committed_blob,
            },
        )

    def sealed_package() -> tuple[str, str, dict[str, Any]]:
        path = repo / SEALED_MANIFEST
        if not path.is_file():
            return "FAIL", f"{SEALED_MANIFEST} is absent", {}
        sealed = json.loads(path.read_text(encoding="utf-8"))
        drifted = []
        for entry in sealed.get("entries") or []:
            relative = str(entry.get("path"))
            digest = sha256_file(repo / relative)
            if digest != entry.get("sha256"):
                drifted.append({"path": relative, "recorded": entry.get("sha256"), "now": digest})
        return (
            "PASS" if not drifted else "FAIL",
            f"{len(sealed.get('entries') or [])} sealed artefacts, {len(drifted)} drifted",
            {"sealed": len(sealed.get("entries") or []), "drifted": drifted},
        )

    def store_readable() -> tuple[str, str, dict[str, Any]]:
        snapshots = {}
        for spec, entry in declared_slices(declaration.document):
            if str(entry.get("timeframe")) not in INTERVAL_MS:
                continue
            snapshots[spec] = store_snapshot(
                repo,
                entry,
                start_ms=start_ms,
                end_ms=end_ms,
                effective_ms=effective_ms,
                at_ms=at_ms,
            )
        unreadable = {spec: snap["error"] for spec, snap in snapshots.items() if not snap["readable"]}
        inside = sum(snap.get("bars_opening_in_window", 0) for snap in snapshots.values())
        return (
            "FAIL" if unreadable else "PASS",
            f"{len(snapshots)} series readable, {inside} bar(s) open inside the window",
            {"series": snapshots, "unreadable": unreadable},
        )

    def no_lookahead_in_store() -> tuple[str, str, dict[str, Any]]:
        future = {}
        for spec, entry in declared_slices(declaration.document):
            if str(entry.get("timeframe")) not in INTERVAL_MS:
                continue
            snapshot = store_snapshot(
                repo,
                entry,
                start_ms=start_ms,
                end_ms=end_ms,
                effective_ms=effective_ms,
                at_ms=at_ms,
            )
            if snapshot.get("bars_fetched_after_now"):
                future[spec] = snapshot["bars_fetched_after_now"]
        return (
            "PASS" if not future else "FAIL",
            "no stored bar claims an ingest later than this instant"
            if not future
            else f"bars claim an ingest later than now: {future}",
            {"future_ingest": future, "instant_utc": iso(at_ms)},
        )

    def observer_fresh() -> tuple[str, str, dict[str, Any]]:
        ages = {}
        for spec, entry in declared_slices(declaration.document):
            if str(entry.get("timeframe")) not in INTERVAL_MS:
                continue
            snapshot = store_snapshot(
                repo,
                entry,
                start_ms=start_ms,
                end_ms=end_ms,
                effective_ms=effective_ms,
                at_ms=at_ms,
            )
            age = snapshot.get("age_of_last_fetch_ms")
            if age is None:
                ages[spec] = None
                continue
            bound = snapshot.get("lag_bound_ms") or 0
            ages[spec] = {"age_ms": age, "lag_bound_ms": bound, "fresh": 0 <= age <= bound}
        stale = [spec for spec, row in ages.items() if not row or not row.get("fresh")]
        return (
            "PASS" if not stale else "FAIL",
            "every series was written within its own lag bound"
            if not stale
            else f"stale series: {stale}",
            {"age": ages},
        )

    def no_dataset_published() -> tuple[str, str, dict[str, Any]]:
        folder = repo / DATASET_DIR
        datasets = (
            sorted(p.name for p in folder.glob("EXP-004A-*.jsonl")) if folder.is_dir() else []
        )
        manifests = (
            sorted(p.name for p in folder.glob("EXP-004A-*.MANIFEST.json"))
            if folder.is_dir()
            else []
        )
        expected_absent = state != "CLOSED"
        ok = (not datasets and not manifests) if expected_absent else bool(datasets)
        return (
            "PASS" if ok else "FAIL",
            f"{len(datasets)} dataset(s) and {len(manifests)} manifest(s) in {DATASET_DIR}"
            + ("" if ok else "; the capture state and the disk disagree"),
            {"datasets": datasets, "manifests": manifests, "window_state": state},
        )

    def tape_still_refused() -> tuple[str, str, dict[str, Any]]:
        completed = subprocess.run(
            [sys.executable, GENERATOR, "--slice", "st6:tape", "--dry-run"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        return (
            "PASS" if completed.returncode == 2 else "FAIL",
            f"st6:tape exit {completed.returncode}: {completed.stderr.strip()[:160]}",
            {"exit_code": completed.returncode},
        )

    def window_cannot_be_extended() -> tuple[str, str, dict[str, Any]]:
        completed = subprocess.run(
            [
                sys.executable,
                GENERATOR,
                "--slice",
                "1h:BTC",
                "--dry-run",
                "--period-end",
                "2027-06-01T00:00:00Z",
            ],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        return (
            "PASS" if completed.returncode == 2 else "FAIL",
            f"period beyond the window exit {completed.returncode}",
            {"exit_code": completed.returncode, "stderr": completed.stderr.strip()[:300]},
        )

    checks.append(run("DECLARATION_AUTHORIZES", authorize_declaration))
    checks.append(run("PHASE_ONE_BYTES_INTACT", phase_one_bytes))
    checks.append(run("GENERATOR_IDENTITY", generator_identity))
    checks.append(run("SEALED_02D_PACKAGE_INTACT", sealed_package))
    checks.append(run("STORE_READABLE", store_readable))
    checks.append(run("STORE_HAS_NO_FUTURE_INGEST", no_lookahead_in_store))
    checks.append(run("FORWARD_OBSERVER_FRESH", observer_fresh))
    checks.append(run("NO_DATASET_PUBLISHED", no_dataset_published))
    checks.append(run("ST6_TAPE_REFUSED", tape_still_refused))
    checks.append(run("WINDOW_CANNOT_BE_EXTENDED", window_cannot_be_extended))

    store_evidence = next(
        (check.evidence for check in checks if check.name == "STORE_READABLE"), {"series": {}}
    )

    failed = [check for check in checks if check.status != "PASS"]
    if failed:
        status = "BLOCKED"
    elif state == "OPEN":
        status = "WINDOW_OPEN"
    elif state == "CLOSED":
        status = "WINDOW_CLOSED"
    else:
        status = "READY_FOR_WINDOW"

    report = {
        "schema_version": SCHEMA_VERSION,
        "run_id": RUN_ID,
        "role": "builder",
        "rfc": "RFC-EXP004A-051-02E",
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "started_at_utc": started_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "executable": sys.executable,
        },
        "repo": {
            "head": git(repo, "rev-parse", "HEAD"),
            "branch": git(repo, "rev-parse", "--abbrev-ref", "HEAD"),
            "dirty_paths": len(
                [line for line in git(repo, "status", "--porcelain").splitlines() if line.strip()]
            ),
            "note": (
                "the dirty count is reported, not cleaned: other work packages share this checkout "
                "and this script has no business reverting their files"
            ),
        },
        "declaration": {
            "path": declaration_path.relative_to(repo).as_posix()
            if declaration_path.is_relative_to(repo)
            else declaration_path.as_posix(),
            "declaration_id": declaration.declaration_id,
            "schema_version": declaration.schema_version,
            "sha256": sha256_file(declaration_path),
            "commit": git(repo, "log", "-1", "--format=%H", "--", SUCCESSOR_DECLARATION) or None,
            "governance_status": declaration.governance_status,
        },
        "generator": {
            "path": GENERATOR,
            "commit": declaration.generator_commit,
            "declared_sha256": declaration.generator.get("blob_sha256"),
        },
        "capture_window": {
            "start_utc": iso(start_ms),
            "end_utc": iso(end_ms),
            "declared_days": (end_ms - start_ms) / 86_400_000,
            "effective_from_utc": iso(effective_ms),
            "state_at_preflight": state,
            "instant_utc": iso(at_ms),
            "seconds_until_open": max(0, (start_ms - at_ms) // 1000),
        },
        "declared_slices": [spec for spec, _ in declared_slices(declaration.document)],
        "store": store_evidence.get("series", {}),
        "status": status,
        "checks": [check.as_dict() for check in checks],
        "failed_controls": [check.name for check in failed],
        "next_invocation": {
            "when": f"at or after {iso(start_ms)}",
            "commands": [
                f"python {GENERATOR} --slice {spec}"
                for spec, entry in declared_slices(declaration.document)
                if str(entry.get("timeframe")) in INTERVAL_MS
            ],
            "note": (
                "there is no scheduler in this repository that runs these. The commands are the "
                "declared ones and must be executed by an operator, or by a scheduler configured "
                "and verified separately; this report does not pretend either has happened."
            ),
        },
        "not_a_capture": (
            "READY_FOR_WINDOW means the declaration binds, the store is live and the extractor "
            "refuses what it must. It is not a capture, not a PASS of capture, and not a statement "
            "about market data, cost or profitability."
        ),
        "economic_executions": 0,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "WP_051_02E_PREFLIGHT.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    baseline = {
        "schema_version": SCHEMA_VERSION,
        "run_id": RUN_ID,
        "generated_at_utc": report["generated_at_utc"],
        "repo": report["repo"],
        "environment": report["environment"],
        "head": report["repo"]["head"],
        "branch": report["repo"]["branch"],
        "declaration": report["declaration"],
        "generator": report["generator"],
        "capture_window": report["capture_window"],
        "protected_paths_dirty": sorted(
            path
            for path in (
                ORIGINAL_DECLARATION,
                SUCCESSOR_DECLARATION,
                GENERATOR,
                SEALED_MANIFEST,
            )
            if git(repo, "status", "--porcelain", "--", path)
        ),
        "store_at_baseline": report["store"],
        "dataset_directory": sorted(
            path.name for path in (repo / DATASET_DIR).glob("*") if path.is_file()
        )
        if (repo / DATASET_DIR).is_dir()
        else [],
        "note": (
            "the baseline records the checkout it found; nothing here is normalised, cleaned or "
            "committed on its behalf"
        ),
    }
    (out_dir / "WP_051_02E_BASELINE.json").write_text(
        json.dumps(baseline, indent=2) + "\n", encoding="utf-8"
    )

    exit_code = EXIT_OK if not failed else EXIT_BLOCKED

    if args.attempt:
        attempts = []
        for spec, entry in declared_slices(declaration.document):
            if str(entry.get("timeframe")) not in INTERVAL_MS:
                continue
            attempts.append(attempt(repo, spec, entry))
        tape = subprocess.run(
            [sys.executable, GENERATOR, "--slice", "st6:tape", "--dry-run"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        published = [row["dataset_path"] for row in attempts if row["dataset_published"]]
        state_after = window_state(start_ms, end_ms, now_ms())
        capture_state, reason = classify(
            state=state_after,
            exit_codes={row["slice"]: row["exit_code"] for row in attempts},
            published=published,
        )
        if failed and capture_state != "CAPTURED":
            capture_state, reason = (
                "BLOCKED",
                f"preflight controls failed: {[check.name for check in failed]}; {reason}",
            )
        capture = {
            "schema_version": SCHEMA_VERSION,
            "run_id": RUN_ID,
            "role": "builder",
            "started_at_utc": started_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "finished_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "head": report["repo"]["head"],
            "branch": report["repo"]["branch"],
            "declaration": report["declaration"],
            "generator": report["generator"],
            "capture_window": report["capture_window"],
            "window_state_at_capture": state_after,
            "attempts": attempts,
            "tape": {
                "command": f"python {GENERATOR} --slice st6:tape",
                "exit_code": tape.returncode,
                "stderr": tape.stderr.strip()[:400],
                "refused": tape.returncode == 2,
            },
            "accepted": 0,
            "rejected": len(attempts),
            "datasets_published": published,
            "gaps": [],
            "duplicates": 0,
            "source": report["store"],
            "temporal": {
                "market_event_time": "the bar's own ts, as stored",
                "bar_close_time": "ts + interval",
                "provider_time": "not recorded by the store; BINANCE_PUBLIC_REST klines carry no "
                "signed server time in the row",
                "ingested_at_utc": "fetched_at_ms, written by the observer at ingest",
                "capture_started_at_utc": started_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "capture_finished_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "external_timestamp": "UNAVAILABLE",
                "basis": "GIT_ANCESTRY_PLUS_INGEST_CLOCK",
                "time_proof": "TIME_PROOF_WEAK",
            },
            "status": capture_state,
            "reason": reason,
            "not_a_certification": (
                "a CAPTURED status would mean the frozen extractor published a dataset inside the "
                "open window; it says nothing about admission, cost, profitability or promotion"
            ),
            "economic_executions": 0,
        }
        (out_dir / "WP_051_02E_CAPTURE_REPORT.json").write_text(
            json.dumps(capture, indent=2) + "\n", encoding="utf-8"
        )
        print(f"[capture] {capture_state}: {reason}")
        if capture_state not in ("PENDING_WINDOW", "CAPTURED", "NO_ELIGIBLE_DATA", "NOT_ELIGIBLE"):
            exit_code = EXIT_BLOCKED

    if args.seal:
        manifest = _manifest(repo)
        (out_dir / "EVIDENCE_MANIFEST.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        print(f"[manifest] {manifest['artefacts']} artefacts, missing {manifest['missing']}")

    for check in checks:
        print(f"[preflight] {check.status:<5} {check.name:<32} {check.detail}")
    print(f"[preflight] {status} - {len(checks)} controls - {len(failed)} failed")
    return exit_code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
