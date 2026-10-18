"""RFC-TAP-EVIDENCE-004 — normalise every REA operation log into one classified ledger.

Reporting-only by design: nothing in ``src/`` imports this module, and no raw log is
ever rewritten.  The single rule it exists to enforce is that ``exit_code`` is a
*transport* result, never a completion result: ``compare-source-to-bundle`` exits 0
while reporting ``NOT_EXECUTED_INVALID_INPUT``, so ``execution_class`` is derived from
the reported result and from evidence that can be checked, never from the exit code.

Scopes are deliberately separate counters.  ``phase_v31`` covers the operations of
this iteration; ``all_dossiers`` covers everything the four dossiers recorded.  They
share a subject but not a denominator, so no document may add them together.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LEDGER_SCHEMA = "evidence004/ledger/1"
CANONICAL_SCHEMA = "evidence004/canonical-run/1"

REPO = Path(__file__).resolve().parents[1]
PACKAGE_REL_PARTS = ("reports", "ai-bots", "RFC-AI-BOTS-002")


@dataclass(frozen=True)
class Layout:
    """Every path the package reads or writes, resolved from one repository root.

    Tests and the two independent verifications ask the same questions of a copy, so
    nothing below may reach for a module-level path when a layout can be passed.
    """

    root: Path = REPO

    @property
    def package(self) -> Path:
        return self.root.joinpath(*PACKAGE_REL_PARTS)

    @property
    def rea(self) -> Path:
        return self.package / "rea"

    @property
    def evidence(self) -> Path:
        return self.package / "evidence-004"

    @property
    def canonical(self) -> Path:
        return self.evidence / "canonical" / "CANONICAL_RUN.json"

    @property
    def derived(self) -> Path:
        return self.evidence / "derived"

    @property
    def current_manifest(self) -> Path:
        return self.evidence / "CURRENT_MANIFEST.json"

    @property
    def supersession_manifest(self) -> Path:
        return self.evidence / "SUPERSESSION_MANIFEST.json"

    @property
    def superseded_projections(self) -> Path:
        return self.evidence / "SUPERSEDED_PROJECTIONS.json"

    @property
    def claims(self) -> Path:
        return self.evidence / "CLAIMS.json"

    @property
    def lock(self) -> Path:
        return self.evidence / ".writer.lock"

    @property
    def stale_report(self) -> Path:
        return self.package / "RUN_REPORT_REA_FIRST.json"


DEFAULT_LAYOUT = Layout()
PACKAGE = DEFAULT_LAYOUT.package
REA_DIR = DEFAULT_LAYOUT.rea
EVIDENCE_DIR = DEFAULT_LAYOUT.evidence

# Start of this iteration's working day.  T-NF-PUBLIC was recorded on 2026-10-17 and
# belongs to the previous round; excluding it by timestamp is what makes the two
# scopes recomputable instead of hand-listed.
PHASE_START = "2026-10-18T00:00:00Z"

# An id REA actually emits.  Anything else in an ``evidence_id`` field is a local key
# and must not be attributed to REA (acceptance criterion REA-07).
REA_NATIVE_ID = re.compile(r"^ev_[0-9a-f]{64}$")

EXECUTED_VERIFIED = "EXECUTED_EVIDENCE_VERIFIED"
EXECUTED_DECLARED = "EXECUTED_EVIDENCE_DECLARED"
EXECUTED_NO_EVIDENCE = "EXECUTED_NO_EVIDENCE"
REFUSED_INVALID_INPUT = "REFUSED_INVALID_INPUT"
BLOCKED_UNSUPPORTED_HOST = "BLOCKED_UNSUPPORTED_HOST"
FAILED = "FAILED"
DIAGNOSTIC_UNHEALTHY = "DIAGNOSTIC_UNHEALTHY"
NON_REA_STEP = "NON_REA_STEP"

# The only classes a counter may call "completed".  Everything else is not done,
# whatever its exit code says.
COMPLETED_CLASSES = frozenset({EXECUTED_VERIFIED, EXECUTED_DECLARED, EXECUTED_NO_EVIDENCE})
NOT_EXECUTED_CLASSES = frozenset({REFUSED_INVALID_INPUT, BLOCKED_UNSUPPORTED_HOST, FAILED})

EVIDENCE_VERIFIED = "EVIDENCE_ARTIFACT_VERIFIED"
EVIDENCE_CORROBORATED = "EVIDENCE_ID_CORROBORATED_IN_DOSSIER"
EVIDENCE_DECLARED_ONLY = "EVIDENCE_ID_DECLARED_ONLY"
EVIDENCE_ABSENT = "EVIDENCE_ABSENT"

OPERATION_FAMILY: Mapping[str, str] = {
    "analyze_javascript_application": "TARGET_ANALYSIS",
    "analyze_web_bundle": "TARGET_ANALYSIS",
    "capture_web_screenshot": "TARGET_ANALYSIS",
    "list_browser_targets": "TARGET_READINESS",
    "doctor": "TARGET_READINESS",
    "import-reference-source": "SOURCE_IMPORT",
    "compare-source-to-bundle": "SOURCE_COMPARE",
}


class LedgerError(RuntimeError):
    """A raw log cannot be read without guessing.  Never repaired silently."""


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


# Two hash domains, named, with one authority each.  A pin that does not say which
# domain it lives in is exactly the defect this package exists to close:
#
#   TEXT_CANONICAL_LF  sha256 of the bytes with CRLF folded to LF.  The only identity a
#                      text pin may use: git checks the same commit out as LF or CRLF,
#                      and a raw-byte pin would make one checkout look like an edit.
#   BINARY_RAW         sha256 of the bytes exactly as committed.  Binary artefacts are
#                      never converted, so raw and canonical coincide.
#
# A text file has no byte identity across checkouts, and no document may claim one.
TEXT_SUFFIXES = frozenset({".json", ".jsonl", ".md", ".csv", ".txt", ".py"})
CRLF = b"\r\n"
LF = b"\n"
TEXT_DOMAIN = "TEXT_CANONICAL_LF"
BINARY_DOMAIN = "BINARY_RAW"

HASH_DOMAINS = {
    TEXT_DOMAIN: {
        "normalisation": "CRLF folded to LF before hashing",
        "authority": "every pin on a text document, including superseded reports",
        "not": "byte identity of a checkout: an LF and a CRLF checkout differ here",
    },
    BINARY_DOMAIN: {
        "normalisation": "none: bytes as committed",
        "authority": "artefact provenance for .png and other non-text files",
        "not": "a way to pin a text document",
    },
}


def hash_domain_for(path: Path) -> str:
    return TEXT_DOMAIN if path.suffix.lower() in TEXT_SUFFIXES else BINARY_DOMAIN


def stable_bytes(path: Path) -> bytes:
    """The bytes a pin may point at: canonical LF for text, raw for everything else."""

    raw = path.read_bytes()
    if path.suffix.lower() in TEXT_SUFFIXES:
        return raw.replace(CRLF, LF)
    return raw


def sha256_file(path: Path) -> str:
    return sha256_bytes(stable_bytes(path))


def canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(payload: object) -> str:
    return sha256_bytes(canonical_json(payload).encode("utf-8"))


def repo_relative(path: Path, root: Path | None = None) -> str:
    try:
        return path.resolve().relative_to((root or REPO).resolve()).as_posix()
    except ValueError:
        return path.as_posix()


@dataclass(frozen=True)
class SourceSpan:
    """Where an event was read from, and the content that was read.

    ``content_sha256`` is the canonical-text digest, never the checkout's raw bytes:
    the same event recorded in an LF and a CRLF checkout must produce one identity.
    """

    path: str
    line: int
    content_sha256: str
    hash_domain: str = TEXT_DOMAIN

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "line": self.line,
            "content_sha256": self.content_sha256,
            "hash_domain": self.hash_domain,
        }


@dataclass(frozen=True)
class EvidenceState:
    evidence_id: str | None
    id_kind: str
    declared_digest: str | None
    digest_matched_path: str | None
    corroborated_in_dossier: bool
    status: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "id_kind": self.id_kind,
            "declared_digest": self.declared_digest,
            "digest_matched_path": self.digest_matched_path,
            "corroborated_in_dossier": self.corroborated_in_dossier,
            "status": self.status,
        }


@dataclass(frozen=True)
class LedgerEvent:
    event_key: str
    target_id: str
    operation: str
    operation_family: str
    timestamp: str
    exit_code: int | None
    result: str | None
    execution_class: str
    command: str | None
    evidence: EvidenceState
    duration_s: float | None
    warnings: tuple[str, ...]
    sources: tuple[SourceSpan, ...]

    @property
    def in_phase(self) -> bool:
        return self.timestamp >= PHASE_START

    @property
    def completed(self) -> bool:
        return self.execution_class in COMPLETED_CLASSES

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_key": self.event_key,
            "target_id": self.target_id,
            "operation": self.operation,
            "operation_family": self.operation_family,
            "timestamp": self.timestamp,
            "exit_code": self.exit_code,
            "result": self.result,
            "execution_class": self.execution_class,
            "completed": self.completed,
            "command": self.command,
            "evidence": self.evidence.as_dict(),
            "duration_s": self.duration_s,
            "warnings": list(self.warnings),
            "sources": [span.as_dict() for span in self.sources],
        }


def _as_text(payload: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _as_int(payload: Mapping[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
    return None


def _as_float(payload: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float):
            return float(value)
    return None


def _warnings(payload: Mapping[str, Any]) -> tuple[str, ...]:
    raw = payload.get("warnings")
    if not isinstance(raw, list):
        return ()
    return tuple(str(item) for item in raw)


def _dossier_ids(target_dir: Path) -> set[str]:
    path = target_dir / "REA_EVIDENCE.json"
    if not path.is_file():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:  # pragma: no cover - corrupt input is a hard stop
        raise LedgerError(f"{repo_relative(path)}: {exc}") from exc
    found: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "evidence_id" and isinstance(value, str):
                    found.add(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return found


def _dossier_digests(target_dir: Path) -> dict[str, str]:
    """sha256 of the artefact bytes actually stored in the dossier, by path."""

    digests: dict[str, str] = {}
    for path in sorted(target_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() not in {".png", ".json"}:
            continue
        digests[repo_relative(path)] = sha256_file(path)
    return digests


def _evidence_state(
    payload: Mapping[str, Any],
    target_dir: Path,
    dossier_ids: set[str],
    dossier_digests: Mapping[str, str],
) -> EvidenceState:
    evidence_id = _as_text(payload, "evidence_id")
    if evidence_id is None:
        return EvidenceState(None, "NONE", None, None, False, EVIDENCE_ABSENT)
    id_kind = "REA_NATIVE" if REA_NATIVE_ID.match(evidence_id) else "LOCAL_KEY"
    declared = _as_text(payload, "evidence_sha256", "artifact_sha256")
    matched = None
    if declared is not None:
        for path, value in dossier_digests.items():
            if value == declared:
                matched = path
                break
    corroborated = evidence_id in dossier_ids
    if matched is not None:
        status = EVIDENCE_VERIFIED
    elif corroborated:
        status = EVIDENCE_CORROBORATED
    else:
        status = EVIDENCE_DECLARED_ONLY
    return EvidenceState(evidence_id, id_kind, declared, matched, corroborated, status)


def _classify(
    operation: str,
    family: str,
    exit_code: int | None,
    result: str | None,
    evidence: EvidenceState,
) -> str:
    if family == "NON_REA":
        return NON_REA_STEP
    if result is not None and "NOT_EXECUTED" in result.upper():
        return REFUSED_INVALID_INPUT
    if result is not None and "BLOCKED_UNSUPPORTED_HOST" in result.upper():
        return BLOCKED_UNSUPPORTED_HOST
    if operation == "doctor" and exit_code not in (0, None):
        return DIAGNOSTIC_UNHEALTHY
    if exit_code not in (0, None):
        return FAILED
    if evidence.status == EVIDENCE_VERIFIED:
        return EXECUTED_VERIFIED
    if evidence.evidence_id is not None:
        return EXECUTED_DECLARED
    return EXECUTED_NO_EVIDENCE


def _raw_sources(layout: Layout) -> list[tuple[Path, str]]:
    """Consolidated log first, then every dossier log; target id from the directory."""

    sources: list[tuple[Path, str]] = []
    consolidated = layout.rea / "REA_COMMAND_LOG.jsonl"
    if consolidated.is_file():
        sources.append((consolidated, "T-CONSOLIDATED"))
    targets_dir = layout.rea / "targets"
    if targets_dir.is_dir():
        for directory in sorted(targets_dir.iterdir()):
            log = directory / "REA_COMMAND_LOG.jsonl"
            if directory.is_dir() and log.is_file():
                sources.append((log, directory.name))
    return sources


def _read_source(
    path: Path, fallback_target: str, layout: Layout
) -> list[tuple[Mapping[str, Any], SourceSpan]]:
    canonical = stable_bytes(path)
    file_digest = sha256_bytes(canonical)
    text = canonical.decode("utf-8")
    if text and not text.endswith("\n"):
        # A truncated JSONL loses its last record; refusing is the only honest option.
        raise LedgerError(
            f"{repo_relative(path, layout.root)}: last line is not newline-terminated (truncated?)"
        )
    rows: list[tuple[Mapping[str, Any], SourceSpan]] = []
    for index, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise LedgerError(f"{repo_relative(path, layout.root)}:{index}: {exc}") from exc
        if not isinstance(payload, dict):
            raise LedgerError(
                f"{repo_relative(path, layout.root)}:{index}: event is not an object"
            )
        span = SourceSpan(
            repo_relative(path, layout.root), index, file_digest, hash_domain_for(path)
        )
        rows.append((payload, span))
    return rows


def _target_of(payload: Mapping[str, Any], fallback: str, span: SourceSpan) -> str:
    declared = payload.get("target_id")
    if isinstance(declared, str) and declared:
        return declared
    if fallback != "T-CONSOLIDATED":
        return fallback
    # Consolidated rows always carry a target_id; a missing one is a data defect.
    raise LedgerError(f"{span.path}:{span.line}: event has no target_id")


def load_events(root: Path | None = None) -> list[LedgerEvent]:
    """Read every raw log and merge duplicates into one event per real occurrence."""

    layout = Layout(root) if root is not None else DEFAULT_LAYOUT
    merged: dict[str, dict[str, Any]] = {}
    per_target: dict[str, tuple[set[str], dict[str, str]]] = {}
    targets_dir = layout.rea / "targets"
    known = (
        sorted(directory.name for directory in targets_dir.iterdir() if directory.is_dir())
        if targets_dir.is_dir()
        else []
    )
    for target_id in known:
        directory = targets_dir / target_id
        per_target[target_id] = (_dossier_ids(directory), _dossier_digests(directory))

    for path, fallback in _raw_sources(layout):
        for payload, span in _read_source(path, fallback, layout):
            target_id = _target_of(payload, fallback, span)
            operation = _as_text(payload, "operation")
            if operation is None:
                raise LedgerError(f"{span.path}:{span.line}: event has no operation")
            timestamp = _as_text(payload, "timestamp", "ts")
            if timestamp is None:
                raise LedgerError(f"{span.path}:{span.line}: event has no timestamp")
            dossier_ids, dossier_digests = per_target.get(target_id, (set(), {}))
            evidence = _evidence_state(
                payload, layout.rea / "targets" / target_id, dossier_ids, dossier_digests
            )
            family = OPERATION_FAMILY.get(operation, "NON_REA")
            exit_code = _as_int(payload, "exit_code", "exit")
            result = _as_text(payload, "result", "envelope", "error")
            execution_class = _classify(operation, family, exit_code, result, evidence)
            key = digest(
                {
                    "target_id": target_id,
                    "operation": operation,
                    "timestamp": timestamp,
                    "evidence_id": evidence.evidence_id,
                }
            )
            existing = merged.get(key)
            if existing is None:
                merged[key] = {
                    "event_key": key,
                    "target_id": target_id,
                    "operation": operation,
                    "operation_family": family,
                    "timestamp": timestamp,
                    "exit_code": exit_code,
                    "result": result,
                    "execution_class": execution_class,
                    "command": _as_text(payload, "command"),
                    "evidence": evidence,
                    "duration_s": _as_float(payload, "duration_s"),
                    "warnings": _warnings(payload),
                    "sources": [span],
                }
                continue
            # Same occurrence recorded twice: keep both spans, and fail if the copies
            # disagree about anything that matters.  Silently preferring one would
            # hide exactly the drift this package exists to catch.
            for field in (
                "execution_class",
                "target_id",
                "operation",
                "timestamp",
                "exit_code",
                "result",
            ):
                if (
                    existing[field]
                    != {
                        "target_id": target_id,
                        "operation": operation,
                        "timestamp": timestamp,
                        "exit_code": exit_code,
                        "result": result,
                        "execution_class": execution_class,
                    }[field]
                ):
                    raise LedgerError(
                        f"{span.path}:{span.line}: disagrees with an earlier copy of the same event "
                        f"on {field}"
                    )
            existing["sources"].append(span)

    events: list[LedgerEvent] = []
    for value in merged.values():
        evidence = value["evidence"]
        events.append(
            LedgerEvent(
                event_key=value["event_key"],
                target_id=value["target_id"],
                operation=value["operation"],
                operation_family=value["operation_family"],
                timestamp=value["timestamp"],
                exit_code=value["exit_code"],
                result=value["result"],
                execution_class=value["execution_class"],
                command=value["command"],
                evidence=evidence,
                duration_s=value["duration_s"],
                warnings=value["warnings"],
                sources=tuple(sorted(value["sources"], key=lambda span: (span.path, span.line))),
            )
        )
    events.sort(key=lambda event: (event.timestamp, event.target_id, event.operation))
    return events


def _subset(events: Sequence[LedgerEvent], predicate: Any) -> list[LedgerEvent]:
    return [event for event in events if predicate(event)]


def _block(events: Sequence[LedgerEvent]) -> dict[str, Any]:
    completed = [event for event in events if event.completed]
    with_evidence = [event for event in completed if event.evidence.evidence_id is not None]
    verified = [event for event in with_evidence if event.evidence.status == EVIDENCE_VERIFIED]
    breakdown: dict[str, int] = {}
    for event in events:
        breakdown[event.execution_class] = breakdown.get(event.execution_class, 0) + 1
    return {
        "operations": len(events),
        "executed_with_evidence_id": len(with_evidence),
        "executed_with_verified_artifact": len(verified),
        "executed_evidence_declared_unverified": len(with_evidence) - len(verified),
        "not_executed": len(
            [event for event in events if event.execution_class in NOT_EXECUTED_CLASSES]
        ),
        "failed": len([event for event in events if event.execution_class == FAILED]),
        "not_executed_operations": sorted(
            f"{event.operation} ({event.execution_class})"
            for event in events
            if event.execution_class in NOT_EXECUTED_CLASSES
        ),
        "class_breakdown": dict(sorted(breakdown.items())),
    }


def build_counts(events: Sequence[LedgerEvent]) -> dict[str, Any]:
    """Two scopes, two denominators, never added together."""

    phase = _subset(events, lambda event: event.in_phase)
    work_families = {"TARGET_ANALYSIS", "SOURCE_IMPORT", "SOURCE_COMPARE"}
    phase_work = _subset(phase, lambda event: event.operation_family in work_families)
    with_phase_evidence = [
        event for event in phase_work if event.completed and event.evidence.evidence_id is not None
    ]
    all_ids = {
        event.evidence.evidence_id for event in events if event.evidence.evidence_id is not None
    }
    return {
        "phase_v31": {
            # The 7 + 2 claim lives here and nowhere else: target work plus the two
            # prerequisites it needed, i.e. every REA operation except discovery.
            "definition": (
                f"REA target work and its prerequisites recorded at or after {PHASE_START}: "
                "TARGET_ANALYSIS, SOURCE_IMPORT, SOURCE_COMPARE"
            ),
            "work": _block(phase_work),
            "readiness": _block(
                _subset(phase, lambda event: event.operation_family == "TARGET_READINESS")
            ),
            "non_rea_steps": len(_subset(phase, lambda event: event.operation_family == "NON_REA")),
            "distinct_evidence_ids": len(
                {
                    event.evidence.evidence_id
                    for event in phase
                    if event.evidence.evidence_id is not None
                }
            ),
        },
        "all_dossiers": {
            "definition": "every event recorded in the four target dossiers, any date",
            "work": _block(_subset(events, lambda event: event.operation_family in work_families)),
            "readiness": _block(
                _subset(events, lambda event: event.operation_family == "TARGET_READINESS")
            ),
            "non_rea_steps": len(
                _subset(events, lambda event: event.operation_family == "NON_REA")
            ),
            "distinct_evidence_ids": len(
                {
                    event.evidence.evidence_id
                    for event in events
                    if event.evidence.evidence_id is not None
                }
            ),
        },
        "conflation_warning": (
            "phase_v31 and all_dossiers share a subject but not a denominator: the phase counter "
            f"({len(with_phase_evidence)} work operations with an evidence_id) and the dossier "
            f"counter ({len(all_ids)} distinct evidence_ids) are both true and are not the same "
            "counter."
        ),
    }


def build_ledger(
    events: Sequence[LedgerEvent] | None = None, root: Path | None = None
) -> dict[str, Any]:
    layout = Layout(root) if root is not None else DEFAULT_LAYOUT
    resolved = list(events if events is not None else load_events(layout.root))
    counts = build_counts(resolved)
    payload = {
        "schema": LEDGER_SCHEMA,
        "hash_domains": HASH_DOMAINS,
        "events": [event.as_dict() for event in resolved],
        "counts": counts,
    }
    payload["ledger_sha256"] = digest({"events": payload["events"], "counts": counts})
    pins: dict[str, dict[str, Any]] = {}
    for event in resolved:
        for span in event.sources:
            path = layout.root / span.path
            pins[span.path] = {
                "path": span.path,
                "hash_domain": span.hash_domain,
                "content_sha256": span.content_sha256,
                "content_bytes": len(stable_bytes(path)) if path.is_file() else 0,
            }
    payload["source_files"] = [pins[path] for path in sorted(pins)]
    return payload


def evidence_inventory(events: Sequence[LedgerEvent]) -> dict[str, Any]:
    """Ids by class, so no document can call a local key an REA id."""

    native: dict[str, list[str]] = {}
    local: list[dict[str, str]] = []
    for event in events:
        if event.evidence.evidence_id is None:
            continue
        if event.evidence.id_kind == "REA_NATIVE":
            native.setdefault(event.target_id, []).append(event.evidence.evidence_id)
        else:
            local.append(
                {
                    "target_id": event.target_id,
                    "operation": event.operation,
                    "value": event.evidence.evidence_id,
                }
            )
    return {
        "rea_native_ids": {target: sorted(ids) for target, ids in sorted(native.items())},
        "rea_native_id_count": len({value for ids in native.values() for value in ids}),
        "local_keys_misplaced_in_evidence_id": local,
    }


def iter_events(payload: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    events = payload.get("events")
    if not isinstance(events, list):
        return []
    return [event for event in events if isinstance(event, dict)]
