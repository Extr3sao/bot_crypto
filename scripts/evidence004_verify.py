"""RFC-TAP-EVIDENCE-004 — independent verifier for the canonical REA ledger.

Deliberately does not import ``evidence004_ledger`` or ``evidence004_generate``: it
re-parses the raw JSONL itself, re-derives every count, re-hashes every artefact and
every pinned document, and only then compares its own numbers against the canonical
object.  A verifier that reused the builder's classifier would agree with it by
construction.

It refuses the two failure modes this package was commissioned to stop:

1. an exit code read as a completed operation, and
2. a historical report still readable as the current result.

``--mutations`` proves the checks bite: each mutation is applied to a throwaway copy
of the package and must make verification fail.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PACKAGE_REL = Path("reports") / "ai-bots" / "RFC-AI-BOTS-002"
EVIDENCE_REL = PACKAGE_REL / "evidence-004"
PHASE_START = "2026-10-18T00:00:00Z"
REA_NATIVE_ID = re.compile(r"^ev_[0-9a-f]{64}$")
WORK_FAMILIES = frozenset({"TARGET_ANALYSIS", "SOURCE_IMPORT", "SOURCE_COMPARE"})
FAMILY = {
    "analyze_javascript_application": "TARGET_ANALYSIS",
    "analyze_web_bundle": "TARGET_ANALYSIS",
    "capture_web_screenshot": "TARGET_ANALYSIS",
    "list_browser_targets": "TARGET_READINESS",
    "doctor": "TARGET_READINESS",
    "import-reference-source": "SOURCE_IMPORT",
    "compare-source-to-bundle": "SOURCE_COMPARE",
}
NOT_EXECUTED = frozenset({"REFUSED_INVALID_INPUT", "BLOCKED_UNSUPPORTED_HOST", "FAILED"})

REPORT_PATTERNS = (
    "RUN_REPORT*.json",
    "RUN_REPORT*.md",
    "FINAL_REPORT*.md",
    "REA_FINDINGS*.json",
    "INFORME_*.md",
    "INDEPENDENT_VERIFICATION*.json",
    "*MATRIX*.md",
    "*MATRIX*.csv",
    "RECONSTRUCTION_*.md",
)

STALE_PATTERNS = (
    "rea_operations_exit_0",
    "all exit 0",
    "todas las operaciones REA",
)
# A count of nine operations is not itself a defect; claiming nine *evidenced* ones is,
# and that is enforced by the counts block and by the derived JSON comparison.
STALE_REGEXES: tuple[re.Pattern[str], ...] = ()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canon(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass
class Verdict:
    checks: list[dict[str, Any]] = field(default_factory=list)

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.checks.append({"name": name, "ok": bool(ok), "detail": detail})
        return bool(ok)

    @property
    def failures(self) -> list[dict[str, Any]]:
        return [check for check in self.checks if not check["ok"]]


# --------------------------------------------------------------------------- raw


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    raw = path.read_bytes()
    if raw and not raw.endswith(b"\n"):
        raise ValueError(f"{path.name}: last line is not newline-terminated (truncated)")
    rows: list[dict[str, Any]] = []
    for index, line in enumerate(raw.decode("utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"{path.name}:{index}: not an object")
        rows.append(payload)
    return rows


def _digests_in(directory: Path) -> dict[str, str]:
    found: dict[str, str] = {}
    for path in sorted(directory.iterdir()) if directory.is_dir() else []:
        if path.is_file() and path.suffix.lower() in {".png", ".json"}:
            found[path.name] = sha256_file(path)
    return found


def _dossier_ids(directory: Path) -> set[str]:
    path = directory / "REA_EVIDENCE.json"
    if not path.is_file():
        return set()
    text = path.read_text(encoding="utf-8")
    return set(re.findall(r'"evidence_id"\s*:\s*"(ev_[0-9a-f]{64})"', text))


def recompute_raw(root: Path) -> tuple[dict[str, dict[str, Any]], list[str], list[str]]:
    """Rebuild the event map straight from the JSONL files under ``root``."""

    package = root / PACKAGE_REL
    rea = package / "rea"
    problems: list[str] = []
    conflicts: list[str] = []
    events: dict[str, dict[str, Any]] = {}
    sources: list[tuple[Path, str]] = []
    consolidated = rea / "REA_COMMAND_LOG.jsonl"
    if consolidated.is_file():
        sources.append((consolidated, ""))
    targets = rea / "targets"
    if targets.is_dir():
        for directory in sorted(targets.iterdir()):
            log = directory / "REA_COMMAND_LOG.jsonl"
            if log.is_file():
                sources.append((log, directory.name))

    for path, fallback in sources:
        file_sha = sha256_file(path)
        try:
            rows = _read_jsonl(path)
        except (ValueError, json.JSONDecodeError) as exc:
            problems.append(f"{path.name}: {exc}")
            continue
        for line, payload in enumerate(rows, start=1):
            target = payload.get("target_id") or fallback
            if not target:
                problems.append(f"{path.name}:{line}: no target")
                continue
            operation = str(payload.get("operation", ""))
            timestamp = str(payload.get("timestamp") or payload.get("ts") or "")
            evidence_id = payload.get("evidence_id")
            evidence_id = evidence_id if isinstance(evidence_id, str) and evidence_id else None
            key = sha256_bytes(
                canon(
                    {
                        "target_id": target,
                        "operation": operation,
                        "timestamp": timestamp,
                        "evidence_id": evidence_id,
                    }
                ).encode("utf-8")
            )
            exit_code = payload.get("exit_code")
            if exit_code is None:
                exit_code = payload.get("exit")
            result = payload.get("result") or payload.get("envelope") or payload.get("error")
            declared = payload.get("evidence_sha256") or payload.get("artifact_sha256")
            target_dir = rea / "targets" / str(target)
            matched = None
            if isinstance(declared, str):
                for name, value in _digests_in(target_dir).items():
                    if value == declared:
                        matched = name
                        break
            corroborated = evidence_id in _dossier_ids(target_dir) if evidence_id else False
            if matched is not None:
                status = "EVIDENCE_ARTIFACT_VERIFIED"
            elif corroborated:
                status = "EVIDENCE_ID_CORROBORATED_IN_DOSSIER"
            elif evidence_id:
                status = "EVIDENCE_ID_DECLARED_ONLY"
            else:
                status = "EVIDENCE_ABSENT"

            family = FAMILY.get(operation, "NON_REA")
            if family == "NON_REA":
                execution = "NON_REA_STEP"
            elif isinstance(result, str) and "NOT_EXECUTED" in result.upper():
                execution = "REFUSED_INVALID_INPUT"
            elif isinstance(result, str) and "BLOCKED_UNSUPPORTED_HOST" in result.upper():
                execution = "BLOCKED_UNSUPPORTED_HOST"
            elif operation == "doctor" and exit_code not in (0, None):
                execution = "DIAGNOSTIC_UNHEALTHY"
            elif exit_code not in (0, None):
                execution = "FAILED"
            elif status == "EVIDENCE_ARTIFACT_VERIFIED":
                execution = "EXECUTED_EVIDENCE_VERIFIED"
            elif evidence_id:
                execution = "EXECUTED_EVIDENCE_DECLARED"
            else:
                execution = "EXECUTED_NO_EVIDENCE"

            span = {"path": f"{PACKAGE_REL.as_posix()}/{path.relative_to(package).as_posix()}", "line": line, "file_sha256": file_sha}
            existing = events.get(key)
            if existing is None:
                events[key] = {
                    "event_key": key,
                    "target_id": target,
                    "operation": operation,
                    "operation_family": family,
                    "timestamp": timestamp,
                    "exit_code": exit_code,
                    "result": result,
                    "execution_class": execution,
                    "evidence": {
                        "evidence_id": evidence_id,
                        "declared_digest": declared,
                        "digest_matched_path": matched,
                        "corroborated_in_dossier": corroborated,
                        "status": status,
                    },
                    "sources": [span],
                }
            else:
                expected = {
                    "target_id": target,
                    "operation": operation,
                    "timestamp": timestamp,
                    "exit_code": exit_code,
                    "result": result,
                    "execution_class": execution,
                }
                for expected_field, expected_value in expected.items():
                    if existing[expected_field] != expected_value:
                        conflicts.append(
                            f"{key[:8]} {expected_field}: {span['path']}:{span['line']}="
                            f"{expected_value!r} vs {existing[expected_field]!r}"
                        )
                if existing["evidence"]["declared_digest"] != declared:
                    conflicts.append(f"{key[:8]} declared_digest differs between copies")
                existing["sources"].append(span)
    return events, problems, conflicts


def _block(events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(events)
    completed = [row for row in rows if row["execution_class"].startswith("EXECUTED_")]
    with_id = [row for row in completed if row["evidence"]["evidence_id"]]
    verified = [row for row in with_id if row["evidence"]["status"] == "EVIDENCE_ARTIFACT_VERIFIED"]
    return {
        "operations": len(rows),
        "executed_with_evidence_id": len(with_id),
        "executed_with_verified_artifact": len(verified),
        "executed_evidence_declared_unverified": len(with_id) - len(verified),
        "not_executed": len([row for row in rows if row["execution_class"] in NOT_EXECUTED]),
    }


def recompute_counts(events: Sequence[dict[str, Any]]) -> dict[str, Any]:
    phase = [row for row in events if row["timestamp"] >= PHASE_START]
    return {
        "phase_v31": {
            "work": _block(row for row in phase if row["operation_family"] in WORK_FAMILIES),
            "readiness": _block(row for row in phase if row["operation_family"] == "TARGET_READINESS"),
            "distinct_evidence_ids": len({row["evidence"]["evidence_id"] for row in phase if row["evidence"]["evidence_id"]}),
        },
        "all_dossiers": {
            "work": _block(row for row in events if row["operation_family"] in WORK_FAMILIES),
            "distinct_evidence_ids": len({row["evidence"]["evidence_id"] for row in events if row["evidence"]["evidence_id"]}),
        },
    }


def render_block(values: Mapping[str, Any]) -> str:
    rows = [
        "<!-- EVIDENCE004:COUNTS:BEGIN -->",
        "",
        "Números canónicos (generado por `scripts/evidence004_generate.py`; no editar a mano).",
        "",
        "| contador | valor |",
        "| --- | --- |",
    ]
    for name in (
        "phase_v31.work.operations",
        "phase_v31.work.executed_with_evidence_id",
        "phase_v31.work.executed_with_verified_artifact",
        "phase_v31.work.not_executed",
        "phase_v31.distinct_evidence_ids",
        "all_dossiers.work.executed_with_evidence_id",
        "all_dossiers.work.not_executed",
        "all_dossiers.distinct_evidence_ids",
    ):
        rows.append(f"| `{name}` | {values[name]} |")
    rows.extend(
        [
            "",
            "Los dos ámbitos no se suman: `phase_v31` cubre el trabajo de esta iteración y",
            "`all_dossiers` cubre todo lo registrado en los cuatro dossiers, con otro denominador.",
            "",
            "<!-- EVIDENCE004:COUNTS:END -->",
        ]
    )
    return "\n".join(rows)


# ---------------------------------------------------------------------- documents


def _resolve(payload: Mapping[str, Any], pointer: str) -> Any:
    node: Any = payload
    for part in pointer.split("."):
        if not isinstance(node, Mapping) or part not in node:
            return None
        node = node[part]
    return node


def _flatten_counters(counts: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "phase_v31.work.operations": counts["phase_v31"]["work"]["operations"],
        "phase_v31.work.executed_with_evidence_id": counts["phase_v31"]["work"]["executed_with_evidence_id"],
        "phase_v31.work.executed_with_verified_artifact": counts["phase_v31"]["work"]["executed_with_verified_artifact"],
        "phase_v31.work.not_executed": counts["phase_v31"]["work"]["not_executed"],
        "phase_v31.distinct_evidence_ids": counts["phase_v31"]["distinct_evidence_ids"],
        "all_dossiers.work.executed_with_evidence_id": counts["all_dossiers"]["work"]["executed_with_evidence_id"],
        "all_dossiers.work.not_executed": counts["all_dossiers"]["work"]["not_executed"],
        "all_dossiers.distinct_evidence_ids": counts["all_dossiers"]["distinct_evidence_ids"],
    }


def discovered_reports(root: Path) -> list[Path]:
    package = root / PACKAGE_REL
    found: set[Path] = set()
    for pattern in REPORT_PATTERNS:
        found.update(path for path in package.rglob(pattern) if path.is_file())
    return sorted(found)


def _evidence_ids_in_json(node: object, found: list[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "evidence_id" and isinstance(value, str) and value:
                found.append(value)
            else:
                _evidence_ids_in_json(value, found)
    elif isinstance(node, list):
        for item in node:
            _evidence_ids_in_json(item, found)


def _stale_matches(text: str) -> list[str]:
    hits = [pattern for pattern in STALE_PATTERNS if pattern in text]
    hits.extend(match.group(0) for pattern in STALE_REGEXES for match in pattern.finditer(text))
    return hits


# ------------------------------------------------------------------------- verify


def verify_package(root: Path) -> Verdict:
    verdict = Verdict()
    package = root / PACKAGE_REL
    evidence = root / EVIDENCE_REL
    canonical_path = evidence / "canonical" / "CANONICAL_RUN.json"
    current_path = evidence / "CURRENT_MANIFEST.json"
    supersession_path = evidence / "SUPERSESSION_MANIFEST.json"

    canonical: dict[str, Any] = {}
    if verdict.check("canonical_exists", canonical_path.is_file(), str(canonical_path)):
        canonical = json.loads(canonical_path.read_text(encoding="utf-8"))
    current: dict[str, Any] = {}
    if verdict.check("current_manifest_exists", current_path.is_file(), str(current_path)):
        current = json.loads(current_path.read_text(encoding="utf-8"))
    supersession: dict[str, Any] = {}
    if verdict.check("supersession_manifest_exists", supersession_path.is_file(), str(supersession_path)):
        supersession = json.loads(supersession_path.read_text(encoding="utf-8"))

    raw, problems, conflicts = recompute_raw(root)
    verdict.check("raw_logs_parse_without_loss", not problems, "; ".join(problems))
    verdict.check(
        "copies_of_one_event_agree",
        not conflicts,
        "; ".join(conflicts[:4]),
    )

    duplicates = [
        key
        for key, event in raw.items()
        if len({span["path"] for span in event["sources"]}) != len(event["sources"])
    ]
    verdict.check(
        "no_event_recorded_twice_in_the_same_file",
        not duplicates,
        f"{len(duplicates)} duplicated record(s)",
    )

    claimed = {event["event_key"]: event for event in canonical.get("events", [])}
    verdict.check(
        "canonical_event_set_equals_raw_checkout",
        set(claimed) == set(raw),
        f"canonical={len(claimed)} raw={len(raw)}",
    )

    mismatched: list[str] = []
    for key in sorted(set(claimed) & set(raw)):
        mine, theirs = raw[key], claimed[key]
        for field_name in ("target_id", "operation", "timestamp", "exit_code", "result", "execution_class"):
            if mine[field_name] != theirs.get(field_name):
                mismatched.append(
                    f"{key[:8]} {field_name}: raw={mine[field_name]!r} "
                    f"canonical={theirs.get(field_name)!r}"
                )
        if mine["evidence"]["status"] != (theirs.get("evidence") or {}).get("status"):
            mismatched.append(f"{key[:8]} evidence status drifted")
        if mine["evidence"]["evidence_id"] != (theirs.get("evidence") or {}).get("evidence_id"):
            mismatched.append(f"{key[:8]} evidence_id drifted")
    verdict.check("every_event_matches_its_raw_bytes", not mismatched, "; ".join(mismatched[:6]))

    span_problems: list[str] = []
    for event in canonical.get("events", []):
        for span in event.get("sources", []):
            path = root / span["path"]
            if not path.is_file():
                span_problems.append(f"{span['path']} missing")
                continue
            if sha256_file(path) != span["file_sha256"]:
                span_problems.append(f"{span['path']} bytes changed")
    verdict.check("stored_spans_point_at_the_bytes_they_hashed", not span_problems, "; ".join(span_problems[:4]))

    mine = recompute_counts(list(raw.values()))
    stated = canonical.get("counts", {})
    drift: list[str] = []
    my_flat = _flatten_counters(mine)
    for name, value in my_flat.items():
        if _resolve(stated, name) != value:
            drift.append(f"{name}: recomputed={value} canonical={_resolve(stated, name)}")
    verdict.check("counts_recomputed_from_raw_logs", not drift, "; ".join(drift[:6]))
    verdict.check(
        "phase_counter_is_seven_plus_two",
        my_flat["phase_v31.work.executed_with_evidence_id"] == 7
        and my_flat["phase_v31.work.not_executed"] == 2,
        f"phase work: {my_flat['phase_v31.work.executed_with_evidence_id']} + "
        f"{my_flat['phase_v31.work.not_executed']}",
    )
    verdict.check(
        "dossier_counter_is_twelve_distinct_ids",
        my_flat["all_dossiers.distinct_evidence_ids"] == 12,
        str(my_flat["all_dossiers.distinct_evidence_ids"]),
    )
    verdict.check(
        "scopes_are_declared_as_separate",
        "not the same" in str(stated.get("conflation_warning", "")),
        "the canonical object must say the two scopes are not one counter",
    )

    claims_path = evidence / "CLAIMS.json"
    claims: list[Mapping[str, Any]] = []
    if verdict.check("claims_file_exists", claims_path.is_file(), str(claims_path)):
        loaded = json.loads(claims_path.read_text(encoding="utf-8"))
        claims = [claim for claim in loaded if isinstance(claim, dict)]
    claim_problems: list[str] = []
    native_ids = {
        event["evidence"]["evidence_id"] for event in raw.values() if event["evidence"]["evidence_id"]
    }
    for claim in claims:
        if claim.get("kind") == "COUNTER":
            pointer = str(claim.get("pointer", ""))
            parts = pointer.split(".")
            node: Any = canonical
            for part in parts:
                node = node.get(part) if isinstance(node, Mapping) else None
            if node != claim.get("expected"):
                claim_problems.append(f"{claim.get('claim_id')}: pointer {pointer} -> {node!r}")
        elif claim.get("kind") == "EVIDENCE_ID":
            if claim.get("evidence_id") not in native_ids:
                claim_problems.append(f"{claim.get('claim_id')}: id not in raw logs")
    verdict.check("claims_resolve_to_evidence_or_counters", not claim_problems, "; ".join(claim_problems[:5]))
    verdict.check("canonical_carries_verified_claims", len(canonical.get("claims", [])) == len(claims), "claim count")
    verdict.check(
        "no_local_key_is_attributed_to_rea",
        not canonical.get("evidence_inventory", {}).get("local_keys_misplaced_in_evidence_id"),
        "the canonical ledger itself must contain no local key in an evidence_id field",
    )

    ledger_sha = str(canonical.get("ledger_sha256", ""))
    derived = evidence / "derived" / ledger_sha[:12]
    verdict.check("derived_dir_is_named_by_ledger_sha", derived.is_dir(), str(derived.name))

    manifest: dict[str, Any] = {}
    manifest_path = derived / "MANIFEST.json"
    if verdict.check("derived_manifest_exists", manifest_path.is_file(), str(manifest_path)):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    hash_problems = [
        record["path"]
        for record in manifest.get("documents", [])
        if not (derived / Path(str(record["path"])).name).is_file()
        or sha256_file(derived / Path(str(record["path"])).name) != record["sha256"]
    ]
    verdict.check("derived_files_match_their_hashes", not hash_problems, ", ".join(hash_problems[:4]))

    counts_block = render_block(my_flat)
    block_targets = [
        package / "RUN_REPORT.md",
        package / "FINAL_REPORT.md",
        package / "INFORME_EJECUTIVO.md",
        derived / "RUN_REPORT.md",
        derived / "INFORME_EJECUTIVO_NUMEROS.md",
    ]
    block_problems = [
        str(path.relative_to(root))
        for path in block_targets
        if not path.is_file() or counts_block not in path.read_text(encoding="utf-8")
    ]
    verdict.check("every_report_carries_the_same_counts_block", not block_problems, ", ".join(block_problems))

    stable_problems: list[str] = []
    for record in current.get("stable_copies", []):
        path = root / record["path"]
        if not path.is_file() or sha256_file(path) != record["sha256"]:
            stable_problems.append(record["path"])
    for name in ("RUN_REPORT.json", "RUN_REPORT.md"):
        if not (derived / name).is_file() or not (package / name).is_file():
            stable_problems.append(f"missing {name}")
        elif sha256_file(derived / name) != sha256_file(package / name):
            stable_problems.append(f"{name} stable copy differs from derived")
    verdict.check("stable_reports_are_byte_identical_to_derived", not stable_problems, ", ".join(stable_problems))

    run_report = json.loads((derived / "RUN_REPORT.json").read_text(encoding="utf-8"))
    verdict.check(
        "derived_json_counts_match_recomputation",
        _flatten_counters(run_report.get("counts", {})) == my_flat,
        "RUN_REPORT.json counters diverge from the raw logs",
    )

    pinned_problems: list[str] = []
    known_defects: dict[str, str] = {}
    superseded_paths: set[str] = set()
    for record in supersession.get("documents", []):
        superseded_paths.add(str(record["path"]))
        path = root / record["path"]
        if not path.is_file():
            pinned_problems.append(f"{record['path']} missing")
        elif sha256_file(path) != record["sha256"]:
            pinned_problems.append(f"{record['path']} bytes changed")
        if record.get("preserved_bytes") is not True:
            pinned_problems.append(f"{record['path']} not marked preserved")
        defect = record.get("known_defect")
        if isinstance(defect, str):
            known_defects[str(record["path"])] = defect
    verdict.check("superseded_documents_are_pinned_not_edited", not pinned_problems, "; ".join(pinned_problems[:5]))

    stale_path = package / "RUN_REPORT_REA_FIRST.json"
    stale_text = stale_path.read_text(encoding="utf-8") if stale_path.is_file() else ""
    verdict.check(
        "historical_report_still_shows_the_defect_it_had",
        '"rea_operations_exit_0": 9' in stale_text,
        "the preserved v3 report must still contain the exit-code count, not a silent rewrite",
    )
    verdict.check(
        "historical_report_is_declared_superseded",
        any(
            str(record["path"]).endswith("RUN_REPORT_REA_FIRST.json")
            for record in supersession.get("documents", [])
        ),
        "a stale report that is not in the supersession manifest is still being served as current",
    )

    registered: set[str] = set()
    for record in current.get("documents", []):
        registered.add(str(record["path"]))
    for record in current.get("stable_copies", []):
        registered.add(str(record["path"]))
    editorial_problems: list[str] = []
    for record in current.get("editorial", []):
        registered.add(str(record["path"]))
        if not (root / str(record["path"])).is_file():
            editorial_problems.append(f"{record['path']} missing")
    verdict.check("editorial_documents_are_registered_and_present", not editorial_problems, "; ".join(editorial_problems))
    for path in discovered_reports(root):
        relative = path.relative_to(root).as_posix()
        if relative not in registered and relative not in superseded_paths:
            verdict.check(
                "no_unregistered_report_is_presented_as_current",
                False,
                f"{relative} is neither current nor declared superseded",
            )
            break
    else:
        verdict.check("no_unregistered_report_is_presented_as_current", True, "")

    stale_hits: list[str] = []
    current_paths = [str(record["path"]) for record in current.get("documents", [])]
    current_paths.extend(str(record["path"]) for record in current.get("stable_copies", []))
    current_paths.extend(str(record["path"]) for record in current.get("editorial", []))
    for relative in current_paths:
        path = root / relative
        if path.is_file() and path.suffix in {".md", ".json"}:
            for hit in _stale_matches(path.read_text(encoding="utf-8")):
                stale_hits.append(f"{relative}: {hit}")
    verdict.check("current_reports_do_not_count_an_exit_code_as_success", not stale_hits, "; ".join(stale_hits))

    local_key_hits: list[str] = []
    for json_relative in [
        str(record["path"])
        for record in current.get("documents", []) + current.get("editorial", [])
    ]:
        path = root / json_relative
        if not path.is_file() or path.suffix != ".json":
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        found: list[str] = []
        _evidence_ids_in_json(payload, found)
        local_key_hits.extend(
            f"{json_relative}: {value}" for value in found if not REA_NATIVE_ID.match(value)
        )
    verdict.check("current_reports_only_use_ids_rea_emitted", not local_key_hits, "; ".join(local_key_hits[:5]))

    superseded_local: list[str] = []
    for record in supersession.get("documents", []):
        path = root / str(record["path"])
        if not path.is_file() or path.suffix != ".json":
            continue
        found = []
        try:
            _evidence_ids_in_json(json.loads(path.read_text(encoding="utf-8")), found)
        except json.JSONDecodeError:
            continue
        bad = [value for value in found if not REA_NATIVE_ID.match(value)]
        if bad and "local key" not in known_defects.get(str(record["path"]), ""):
            superseded_local.append(f"{record['path']}: {bad[0]}")
    verdict.check(
        "superseded_local_keys_are_declared_as_defects",
        not superseded_local,
        "; ".join(superseded_local[:4]),
    )

    providers: list[str] = []
    for invocations in (package / "runs").rglob("MODEL_INVOCATIONS.jsonl"):
        for row in _read_jsonl(invocations):
            value = row.get("provider")
            if isinstance(value, str):
                providers.append(value)
    non_mock = sorted({value for value in providers if "mock" not in value.lower()})
    verdict.check(
        "no_provider_claim_without_a_real_model_call",
        not non_mock or canonical.get("real_model_called") is True,
        f"providers={non_mock} but real_model_called={canonical.get('real_model_called')}: "
        "a run attributed to a real provider needs a receipt in the canonical object",
    )
    verdict.check(
        "mock_runs_are_declared_as_mock",
        bool(providers) and not non_mock and canonical.get("real_model_called") is False,
        f"providers={sorted(set(providers))} real_model_called={canonical.get('real_model_called')}",
    )
    verdict.check(
        "no_orders_no_risk_change",
        canonical.get("orders_placed") == 0 and canonical.get("risk_config_touched") is False,
        "the canonical object must record zero orders and an untouched risk config",
    )

    readme = evidence / "README.md"
    if verdict.check("readme_exists", readme.is_file(), str(readme)):
        text = readme.read_text(encoding="utf-8")
        verdict.check(
            "readme_documents_how_to_reproduce",
            "evidence004_generate.py" in text and "evidence004_verify.py" in text,
            "the README must name both the generator and this verifier",
        )

    return verdict


# ------------------------------------------------------------------------ mutate


def _mutate_text(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise AssertionError(f"mutation target {old!r} not found in {path.name}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _mutate_json(path: Path, mutate: Callable[[dict[str, Any]], None]) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


MUTATIONS: tuple[tuple[str, Callable[[Path], None]], ...] = (
    (
        "evidence_id_rewritten_in_raw_log",
        lambda pkg: _mutate_text(
            pkg / "rea" / "targets" / "T-NF-NOF1" / "REA_COMMAND_LOG.jsonl",
            "ev_4b2bf9c5c313530cc7e1e399d4cde5c175ecdd0018a9f608ee12782522ea9ade",
            "ev_" + "0" * 64,
        ),
    ),
    (
        "result_changed_to_success_in_raw_log",
        lambda pkg: _mutate_text(
            pkg / "rea" / "targets" / "T-NF-NOF1" / "REA_COMMAND_LOG.jsonl",
            "NOT_EXECUTED_INVALID_INPUT",
            "COMPLETED",
        ),
    ),
    (
        "exit_code_flipped_in_raw_log",
        lambda pkg: _mutate_text(
            pkg / "rea" / "targets" / "T-FE-FENIX" / "REA_COMMAND_LOG.jsonl",
            '"exit_code": 0',
            '"exit_code": 1',
        ),
    ),
    (
        "target_id_swapped_in_raw_log",
        lambda pkg: _mutate_text(
            pkg / "rea" / "REA_COMMAND_LOG.jsonl",
            '"target_id": "T-QR-SIGNAL"',
            '"target_id": "T-FE-FENIX"',
        ),
    ),
    (
        "declared_digest_swapped_in_raw_log",
        lambda pkg: _mutate_text(
            pkg / "rea" / "targets" / "T-FE-FENIX" / "REA_COMMAND_LOG.jsonl",
            "977ade7ba3afccd7370f0779f0611ccea168c82e26d383d52565ca9358a70233",
            "0" * 64,
        ),
    ),
    (
        "consolidated_log_diverges_from_dossier_log",
        lambda pkg: _mutate_text(
            pkg / "rea" / "REA_COMMAND_LOG.jsonl",
            '"result": "14 scripts observed, 14 parsed, 0 failures',
            '"result": "15 scripts observed, 14 parsed, 0 failures',
        ),
    ),
    (
        "evidence_artifact_deleted",
        lambda pkg: (pkg / "rea" / "targets" / "T-FE-FENIX" / "rea_screenshot.png").unlink(),
    ),
    (
        "event_duplicated_inside_one_file",
        lambda pkg: _duplicate_first_row(pkg / "rea" / "targets" / "T-QR-SIGNAL" / "REA_COMMAND_LOG.jsonl"),
    ),
    (
        "jsonl_truncated_mid_record",
        lambda pkg: _truncate(pkg / "rea" / "targets" / "T-QR-SIGNAL" / "REA_COMMAND_LOG.jsonl"),
    ),
    (
        "fabricated_run_report_slipped_in",
        lambda pkg: _write_extra_report(pkg / "RUN_REPORT_GUESS.json"),
    ),
    (
        "supersession_entry_removed",
        lambda pkg: _mutate_json(
            pkg / "evidence-004" / "SUPERSESSION_MANIFEST.json",
            lambda payload: payload.__setitem__(
                "documents",
                [d for d in payload["documents"] if not str(d["path"]).endswith("REA_FIRST.json")],
            ),
        ),
    ),
    (
        "counts_block_inflated_to_nine",
        lambda pkg: _mutate_text(
            pkg / "RUN_REPORT.md",
            "| `phase_v31.work.executed_with_evidence_id` | 7 |",
            "| `phase_v31.work.executed_with_evidence_id` | 9 |",
        ),
    ),
    (
        "derived_json_count_inflated",
        lambda pkg: _mutate_json(
            pkg / "evidence-004" / "derived"
            / json.loads((pkg / "evidence-004" / "canonical" / "CANONICAL_RUN.json").read_text(encoding="utf-8"))["ledger_sha256"][:12]
            / "RUN_REPORT.json",
            lambda payload: payload["counts"]["phase_v31"]["work"].__setitem__("not_executed", 0),
        ),
    ),
    (
        "mock_provider_rewritten_as_real",
        lambda pkg: _mutate_text(
            pkg / "runs" / "bot-vis-01" / "MODEL_INVOCATIONS.jsonl",
            '"provider": "mock-script"',
            '"provider": "openai"',
        ),
    ),
)


def _write_extra_report(path: Path) -> None:
    path.write_text('{"counts": {"x": 9}}\n', encoding="utf-8")


def _truncate(path: Path) -> None:
    raw = path.read_bytes()
    path.write_bytes(raw[: len(raw) // 2])


def _duplicate_first_row(path: Path) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise AssertionError(f"{path.name} is empty")
    path.write_text("\n".join([*lines, lines[0]]) + "\n", encoding="utf-8")


def run_mutations(root: Path) -> int:
    """Every mutation must be rejected.  A mutation that passes is a hole.

    The verdict is written to ``MUTATION_REPORT.json`` so the claim "14/14 rejected"
    is an artefact with the failing check named, not a line of console output.
    """

    package = root / PACKAGE_REL
    failures: list[str] = []
    records: list[dict[str, Any]] = []
    for name, apply in MUTATIONS:
        with tempfile.TemporaryDirectory(prefix="evidence004-mut-") as temporary:
            copy = Path(temporary) / "reports"
            shutil.copytree(package.parent, copy / "ai-bots")
            applied = copy / PACKAGE_REL.relative_to("reports")
            try:
                apply(applied)
            except (AssertionError, FileNotFoundError) as exc:
                failures.append(f"{name}: mutation could not be applied ({exc})")
                records.append({"mutation": name, "detected": False, "reason": str(exc)})
                continue
            verdict = verify_package(Path(temporary))
            detected = bool(verdict.failures)
            first = verdict.failures[0]["name"] if detected else None
            records.append(
                {
                    "mutation": name,
                    "detected": detected,
                    "failures": len(verdict.failures),
                    "first_failing_check": first,
                }
            )
            if detected:
                print(f"  rejected {name}: {len(verdict.failures)} failure(s), first={first}")
            else:
                failures.append(f"{name}: NOT DETECTED ({len(verdict.checks)} checks all passed)")

    report = {
        "schema": "evidence004/mutation-report/1",
        "verifier": "scripts/evidence004_verify.py",
        "mutations": len(MUTATIONS),
        "detected": len([record for record in records if record["detected"]]),
        "holes": len(failures),
        "results": records,
    }
    destination = root / EVIDENCE_REL / "MUTATION_REPORT.json"
    destination.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if failures:
        print("\nMUTATION HOLES:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print(f"all {len(MUTATIONS)} mutations rejected")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--mutations", action="store_true", help="prove each check rejects a mutation")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()

    if args.mutations:
        status = run_mutations(root)
        return status

    verdict = verify_package(root)
    canonical_ledger = root / EVIDENCE_REL / "canonical" / "CANONICAL_RUN.json"
    checked_ledger = ""
    if canonical_ledger.is_file():
        checked_ledger = str(json.loads(canonical_ledger.read_text(encoding="utf-8")).get("ledger_sha256", ""))
    payload = {
        "verifier": "scripts/evidence004_verify.py",
        # Deterministic on purpose: re-running on an unchanged tree produces the same
        # bytes, so a stale verification cannot hide behind a fresh timestamp.
        "verified_ledger_sha256": checked_ledger,
        "role": "independent of scripts/evidence004_generate.py and scripts/evidence004_ledger.py",
        "checks": verdict.checks,
        "passed": len(verdict.checks) - len(verdict.failures),
        "failed": len(verdict.failures),
        "failures": verdict.failures,
    }
    destination = root / EVIDENCE_REL / "VERIFICATION.json"
    destination.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        for failure in verdict.failures:
            print(f"FAIL {failure['name']}: {failure['detail']}", file=sys.stderr)
        print(f"{payload['passed']} PASS / {payload['failed']} FAIL")
    return 1 if verdict.failures else 0


if __name__ == "__main__":
    sys.exit(main())
