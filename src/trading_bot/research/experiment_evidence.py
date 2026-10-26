"""Deterministic experiment provenance + evidence integrity (GATE STRAT-HARDEN-002 §7-§10).

The independent verifier found the committed ``EXP-STRAT-DYNAMIC-001`` artifact
was *not* byte-reproducible from its own script and that a stale ``exp.log``
retained a contradicting ``PROMOTE_CANDIDATE`` verdict next to a committed
``DO_NOT_PROMOTE`` result. This module makes that class of contradiction
impossible to miss:

* every run carries a **manifest** with ``run_id``, ``experiment_id``,
  ``commit_sha``, ``dirty_tree``, ``script_sha256``, ``config_sha256``,
  ``dataset_fingerprint``, ``started_at``, ``completed_at``, ``seed``, plus the
  ``result`` and ``decision``;
* results are **immutable per run_id** — a run directory is never overwritten;
* evidence lives under ``reports/<experiment_id>/<run_id>/`` with
  ``RUN_REPORT.json`` / ``RUN_REPORT.md`` / ``stdout.log`` / ``result.json`` /
  ``manifest.json``;
* a top-level ``LATEST.json`` may exist only as an explicitly-marked
  ``POINTER / NON-EVIDENCE`` that names its run;
* a **decision-coherence guard** refuses to emit (or re-validate) a run whose
  ``result.json`` decision disagrees with the decision in ``stdout.log``:
  that is an ``EVIDENCE_CONFLICT`` -> RUN INVALID -> no promotion / no hot-wire.

Canonical JSON is the serialization contract: sorted keys, fixed separators,
ASCII, no insignificant whitespace. ``SEMANTIC_REPRODUCIBILITY`` is the minimum
bar; ``BYTE_REPRODUCIBILITY`` is targeted once the intentionally
non-deterministic fields (:data:`NON_DETERMINISTIC_FIELDS`) are excluded.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections.abc import Iterable
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Final

__all__ = [
    "CANONICAL_JSON_SCHEMA_VERSION",
    "EXPERIMENT_EVIDENCE_VERSION",
    "NON_DETERMINISTIC_FIELDS",
    "RUN_FILES",
    "EvidenceConflictError",
    "EvidenceImmutabilityError",
    "EvidenceIntegrityError",
    "assert_evidence_coherent",
    "build_manifest",
    "canonical_json",
    "deterministic_view",
    "extract_log_decision",
    "extract_result_decision",
    "fingerprint_files",
    "git_commit_sha",
    "git_is_dirty",
    "make_run_id",
    "sha256_bytes",
    "sha256_file",
    "sha256_text",
    "validate_run",
    "write_pointer",
    "write_run",
]

EXPERIMENT_EVIDENCE_VERSION: Final[str] = "experiment-evidence-v1"
CANONICAL_JSON_SCHEMA_VERSION: Final[str] = "canonical-json-v1"

#: Fields that legitimately differ between two runs of the same experiment.
#: Excluding them is what makes a canonical artifact byte-reproducible.
NON_DETERMINISTIC_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "run_id",
        "started_at",
        "completed_at",
        "commit_sha",
        "dirty_tree",
        "duration_ms",
    }
)

RUN_FILES: Final[tuple[str, ...]] = (
    "manifest.json",
    "result.json",
    "stdout.log",
    "RUN_REPORT.json",
    "RUN_REPORT.md",
)

_DECISION_RE: Final[re.Pattern[str]] = re.compile(
    r'"?\b(?:decision|verdict)\b"?\s*[:=]\s*"?([A-Z][A-Z0-9_]*)'
)


class EvidenceIntegrityError(RuntimeError):
    """Base class for every evidence-integrity refusal."""


class EvidenceConflictError(EvidenceIntegrityError):
    """``result.json`` and ``stdout.log`` disagree about the same run."""


class EvidenceImmutabilityError(EvidenceIntegrityError):
    """A previous run's evidence would have been overwritten in place."""


# --------------------------------------------------------------------------- #
# Hashing / canonical serialization
# --------------------------------------------------------------------------- #


def _json_default(obj: Any) -> Any:
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, (set, frozenset)):
        return sorted(obj)
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"{type(obj).__name__} is not JSON-serialisable for evidence")


def canonical_json(obj: Any) -> str:
    """Deterministic, whitespace-free JSON: the canonical serialization."""
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=_json_default,
    )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def fingerprint_files(paths: Iterable[Path]) -> str:
    """Order-independent fingerprint of a dataset (relative name + content)."""
    items = sorted((p.name, sha256_file(p)) for p in paths)
    return sha256_text(canonical_json(items))


def git_commit_sha(repo: Path) -> str:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return out.strip() or "UNKNOWN"
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"


def git_is_dirty(repo: Path) -> bool:
    """Fail closed: if the tree state cannot be read, treat it as dirty."""
    try:
        out = subprocess.check_output(
            ["git", "-C", str(repo), "status", "--porcelain"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return True
    return bool(out.strip())


def deterministic_view(obj: dict[str, Any]) -> dict[str, Any]:
    """Drop the intentionally non-deterministic top-level fields."""
    return {k: v for k, v in obj.items() if k not in NON_DETERMINISTIC_FIELDS}


# --------------------------------------------------------------------------- #
# Manifest
# --------------------------------------------------------------------------- #


def make_run_id(
    experiment_id: str, *, now: datetime | None = None, commit_sha: str = "NOCOMMIT"
) -> str:
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    short = (commit_sha or "NOCOMMIT")[:8]
    return f"{experiment_id}-{stamp}-{short}"


def build_manifest(
    *,
    experiment_id: str,
    run_id: str,
    script_path: Path,
    repo: Path,
    config: Any,
    dataset_fingerprint: str,
    seed: int | str,
    started_at: str,
    completed_at: str,
    result: dict[str, Any] | None = None,
    decision: str | None = None,
    artifact_version: str = EXPERIMENT_EVIDENCE_VERSION,
) -> dict[str, Any]:
    """The full provenance record required for every experiment artifact."""
    return {
        "artifact_version": artifact_version,
        "canonical_json_schema_version": CANONICAL_JSON_SCHEMA_VERSION,
        "experiment_id": experiment_id,
        "run_id": run_id,
        "commit_sha": git_commit_sha(repo),
        "dirty_tree": git_is_dirty(repo),
        "script_sha256": sha256_file(script_path),
        "config_sha256": sha256_text(canonical_json(config)),
        "dataset_fingerprint": dataset_fingerprint,
        "started_at": started_at,
        "completed_at": completed_at,
        "seed": seed,
        "result": result,
        "decision": decision,
    }


# --------------------------------------------------------------------------- #
# Decision-coherence guard (§10)
# --------------------------------------------------------------------------- #


def extract_result_decision(result: dict[str, Any]) -> str | None:
    """The run's verdict as a bare string.

    ``verdict`` is preferred; a top-level ``decision`` that is itself a string
    is accepted; a nested ``decision`` object (legacy artifact shape) is not a
    decision and is skipped rather than stringified.
    """
    verdict = result.get("verdict")
    if isinstance(verdict, str) and verdict:
        return verdict
    decision = result.get("decision")
    if isinstance(decision, str) and decision:
        return decision
    return None


def extract_log_decision(stdout_text: str) -> str | None:
    """Read the decision out of a run's stdout.

    Prefers an explicit ``FINAL_DECISION=...`` marker; falls back to the last
    ``"verdict": "..."`` / ``"decision": "..."`` token so a legacy log that
    printed a contradicting verdict is still detected.
    """
    for line in reversed(stdout_text.splitlines()):
        stripped = line.strip()
        if stripped.startswith("FINAL_DECISION="):
            return stripped.split("=", 1)[1].strip()
    matches = _DECISION_RE.findall(stdout_text)
    return matches[-1] if matches else None


def assert_evidence_coherent(result: dict[str, Any], stdout_text: str) -> None:
    """Refuse a run whose result and stdout disagree (§10).

    A log with no decision marker at all is not a contradiction (legacy logs
    exist), but any *disagreement* between a present log decision and the
    result decision is a hard ``EVIDENCE_CONFLICT``.
    """
    result_decision = extract_result_decision(result)
    log_decision = extract_log_decision(stdout_text)
    if log_decision is None:
        return
    if result_decision is None:
        raise EvidenceIntegrityError(
            "EVIDENCE_CONFLICT: stdout carries a decision "
            f"({log_decision}) but result.json carries none — RUN INVALID"
        )
    if result_decision != log_decision:
        raise EvidenceConflictError(
            "EVIDENCE_CONFLICT: result.json says "
            f"{result_decision} but stdout.log says {log_decision} — RUN INVALID"
        )


# --------------------------------------------------------------------------- #
# Immutable run directories
# --------------------------------------------------------------------------- #


def write_run(
    *,
    reports_root: Path,
    experiment_id: str,
    manifest: dict[str, Any],
    result: dict[str, Any],
    stdout_text: str,
    report_markdown: str,
) -> Path:
    """Write one immutable run directory. Never overwrites a prior run."""
    run_id = str(manifest["run_id"])
    run_dir = reports_root / experiment_id / run_id
    if run_dir.exists():
        raise EvidenceImmutabilityError(
            f"run {run_id} already exists at {run_dir}; evidence is immutable per "
            "run_id — pick a new run_id, do not overwrite"
        )
    # Fail closed BEFORE writing anything: a contradictory run is not evidence.
    assert_evidence_coherent(result, stdout_text)

    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(canonical_json(manifest) + "\n", encoding="utf-8")
    (run_dir / "result.json").write_text(canonical_json(result) + "\n", encoding="utf-8")
    (run_dir / "stdout.log").write_text(stdout_text, encoding="utf-8")
    report = {"manifest": manifest, "result": result, "decision": manifest.get("decision")}
    (run_dir / "RUN_REPORT.json").write_text(canonical_json(report) + "\n", encoding="utf-8")
    (run_dir / "RUN_REPORT.md").write_text(report_markdown, encoding="utf-8")
    write_pointer(reports_root=reports_root, experiment_id=experiment_id, run_id=run_id)
    return run_dir


def write_pointer(*, reports_root: Path, experiment_id: str, run_id: str) -> Path:
    """Write/refresh the ``LATEST.json`` pointer, explicitly NON-EVIDENCE."""
    pointer = reports_root / experiment_id / "LATEST.json"
    pointer.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "_marker": "POINTER / NON-EVIDENCE",
        "non_evidence": True,
        "note": "Not evidence. The authoritative artifact lives under <run_id>/.",
        "experiment_id": experiment_id,
        "run_id": run_id,
    }
    pointer.write_text(canonical_json(payload) + "\n", encoding="utf-8")
    return pointer


def validate_run(run_dir: Path) -> dict[str, Any]:
    """Re-validate a persisted run directory. Raises on any contradiction."""
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    stdout_text = (run_dir / "stdout.log").read_text(encoding="utf-8")
    assert_evidence_coherent(result, stdout_text)
    if manifest.get("run_id") != result.get("run_id"):
        raise EvidenceIntegrityError(
            f"EVIDENCE_CONFLICT: manifest run_id {manifest.get('run_id')!r} != "
            f"result run_id {result.get('run_id')!r}"
        )
    missing = [name for name in RUN_FILES if not (run_dir / name).exists()]
    if missing:
        raise EvidenceIntegrityError(f"run {run_dir.name} is missing files: {missing}")
    return {
        "run_id": str(manifest.get("run_id")),
        "experiment_id": str(manifest.get("experiment_id")),
        "decision": extract_result_decision(result),
        "valid": True,
        "files": list(RUN_FILES),
    }
