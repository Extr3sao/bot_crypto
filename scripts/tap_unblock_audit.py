"""CODEX / FASE A.5 — qué generadores de informes pueden decir PASS sin mirar el resultado.

The question is not "does this script print PASS". It is whether the PASS it prints is a
*function* of something that ran. Three shapes are distinguishable from the source alone:

``DEMOTED``
    the verdict starts at ``PASS`` and later assignments to the same name can replace it
    with ``FAIL``/``BLOCKED``/``INCONCLUSIVE`` under a stated condition. Reading order
    still matters, so this is reported with the count of demotion sites, not as a
    guarantee.

``LITERAL_FINAL``
    ``PASS`` is assigned and never reassigned: the value is a constant dressed as a
    result.

``CONSTANT_ZERO``
    ``false_success``/``live_orders`` and similar counters are written as ``0`` instead of
    being counted. A reader takes the field as a measurement; it is a typo away from
    being a lie, and usually already is one.

Each finding is also marked ``SEALED`` when the file's current bytes are pinned by an
existing seal/manifest: changing it would invalidate a published artifact, so the finding
is disclosed rather than repaired. That distinction is the difference between "we chose
not to fix it" and "we could not".

Read-only: parses source, hashes files, prints. It never writes to the audited files.

Usage::

    python scripts/tap_unblock_audit.py --json reports/.../GENERATOR_AUDIT.json
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]

#: The six generators that emit a verdict or a report beside their own evidence, plus the
#: one already repaired in WP-DEF-018-04 (kept in the list as the control: it must not
#: come out as ``LITERAL_FINAL`` or ``CONSTANT_ZERO``).
GENERATORS = (
    "scripts/def_run_016_verify.py",
    "scripts/def_run_017_verify.py",
    "scripts/def_run_017_report.py",
    "scripts/def_run_018_gate.py",
    "scripts/def_run_018_verify_b.py",
    "scripts/def_run_018_close.py",
    "scripts/def_run_019_close.py",
)

#: Names whose assignment to the string ``PASS`` is a verdict.
VERDICT_NAMES = frozenset(
    {
        "verdict",
        "result",
        "status",
        "state",
        "overall",
        "technical",
        "technical_status",
        "technical_integrity",
        "economic_status",
        "paper",
        "paper_admission",
        "decision",
        "subject_state",
        "session_state",
    }
)

#: Fields that read as measurements when they are written as literals. ``live_orders`` is
#: deliberately absent: the session refuses any mode but ``PAPER`` before it builds an
#: object, so zero live orders is a structural invariant and not a measurement that could
#: have come out otherwise.
COUNTER_NAMES = frozenset({"false_success", "regressions", "failures"})

#: Manifests that pin a script's bytes. If the current file matches, the script is sealed.
SEALS = (
    "reports/ai-bots/RFC-DEF-RUN-018/EVIDENCE_SEAL.json",
    "reports/ai-bots/RFC-DEF-RUN-018/COMMIT_MANIFEST.json",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sealed_hashes(repo: Path) -> dict[str, set[str]]:
    """Path → the digests some published manifest says those bytes had."""
    out: dict[str, set[str]] = {}
    for name in SEALS:
        path = repo / name
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        rows = payload.get("committed_subject_files") or payload.get("files") or []
        for row in rows:
            target = str(row.get("path") or "").replace("\\", "/")
            digest = row.get("sha256")
            if target and isinstance(digest, str):
                out.setdefault(target, set()).add(digest)
    return out


def _targets(node: ast.stmt) -> list[str]:
    names: list[str] = []
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name):
                names.append(target.id)
    elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        names.append(node.target.id)
    return names


def _is_pass_constant(value: ast.expr | None) -> bool:
    return isinstance(value, ast.Constant) and value.value == "PASS"


def audit_source(path: Path, repo: Path, seals: dict[str, set[str]]) -> dict[str, Any]:
    relative = path.relative_to(repo).as_posix()
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    assignments: dict[str, list[tuple[int, ast.expr | None]]] = {}
    counter_hits: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            for name in _targets(node):
                if name in VERDICT_NAMES:
                    assignments.setdefault(name, []).append((node.lineno, node.value))
        #: ``{"false_success": 0}`` in a payload dict is the shape that misled a reader
        #: once already; catching the ``ast.Dict`` covers it wherever it is written.
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=False):
                if (
                    isinstance(key, ast.Constant)
                    and key.value in COUNTER_NAMES
                    and isinstance(value, ast.Constant)
                ):
                    counter_hits.append(
                        {
                            "kind": "CONSTANT_ZERO",
                            "field": key.value,
                            "line": getattr(node, "lineno", 0),
                            "value": value.value,
                        }
                    )

    findings: list[dict[str, Any]] = []
    for name, sites in sorted(assignments.items()):
        #: ``ast.walk`` yields breadth-first, not in source order: sorting by line is what
        #: makes "the first assignment" mean what a reader means by it.
        sites = sorted(sites, key=lambda item: item[0])
        first_line, first_value = sites[0]
        if not _is_pass_constant(first_value):
            continue
        demotions = [line for line, value in sites[1:] if not _is_pass_constant(value)]
        findings.append(
            {
                "kind": "DEMOTED" if demotions else "LITERAL_FINAL",
                "name": name,
                "line": first_line,
                "assignments": len(sites),
                "demotion_lines": demotions,
            }
        )
    #: Informational, not a finding: a name whose every assignment is one of several
    #: constants chosen by an if/elif chain is decided by branches, and the branches are
    #: where the reader has to look. Reported so "no finding" is not mistaken for
    #: "not examined".
    outcomes: dict[str, list[str]] = {}
    for name, sites in sorted(assignments.items()):
        values = {
            str(value.value)
            for _, value in sites
            if isinstance(value, ast.Constant) and isinstance(value.value, str)
        }
        if len(values) > 1:
            outcomes[name] = sorted(values)
    #: a dict literal repeated in a payload and in its markdown would otherwise be
    #: reported twice; the line is what distinguishes them, so dedupe on (field, line).
    seen: set[tuple[str, int]] = set()
    for hit in counter_hits:
        dedupe_key = (str(hit["field"]), int(hit["line"]))
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        findings.append(hit)

    digest = sha256(path)
    pins = seals.get(relative, set())
    exit_lines = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Return)
        and isinstance(node.value, (ast.IfExp, ast.Compare, ast.Name))
    ]
    return {
        "path": relative,
        "sha256": digest,
        "sealed": digest in pins,
        "seal_pinned_digests": sorted(pins),
        "lines": source.count("\n") + 1,
        "verdict_assignments": {name: len(sites) for name, sites in assignments.items()},
        "multi_outcome": outcomes,
        "conditional_returns": len(exit_lines),
        "findings": findings,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for row in rows:
        for finding in row["findings"]:
            counts[finding["kind"]] = counts.get(finding["kind"], 0) + 1
    return {
        "generators": len(rows),
        "findings_by_kind": counts,
        "sealed_files_with_findings": sorted(
            row["path"] for row in rows if row["sealed"] and row["findings"]
        ),
        "literal_final": sorted(
            row["path"]
            for row in rows
            if any(item["kind"] == "LITERAL_FINAL" for item in row["findings"])
        ),
        "constant_zero": sorted(
            row["path"]
            for row in rows
            if any(item["kind"] == "CONSTANT_ZERO" for item in row["findings"])
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit report generators for literal verdicts")
    parser.add_argument("--repo", default=str(REPO))
    parser.add_argument("--json", default=None)
    parser.add_argument("--md", default=None)
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    seals = sealed_hashes(repo)
    rows: list[dict[str, Any]] = []
    for name in GENERATORS:
        path = repo / name
        if not path.is_file():
            rows.append(
                {
                    "path": name,
                    "missing": True,
                    "sealed": False,
                    "findings": [],
                    "sha256": None,
                }
            )
            continue
        rows.append(audit_source(path, repo, seals))

    payload: dict[str, Any] = {
        "schema_version": "TAP_OPERATIONAL_GENERATOR_AUDIT_V1",
        "generated_at_utc": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repo": str(repo),
        "method": (
            "AST: every assignment of the literal 'PASS' to a verdict name, whether a "
            "later assignment can demote it, and every counter written as a constant. "
            "Sealed = current bytes match a digest in a published manifest."
        ),
        "summary": summarize(rows),
        "generators": rows,
    }
    if args.json:
        target = Path(args.json)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    summary = payload["summary"]
    if args.md:
        lines = [
            "# GENERATOR_AUDIT — ¿el PASS lo decidió algo?",
            "",
            f"Generadores auditados: **{len(rows)}** · "
            f"hallazgos: `{json.dumps(summary['findings_by_kind'], sort_keys=True)}`",
            "",
            "| Generador | Sellado | `PASS` literales | `LITERAL_FINAL` | Constantes |",
            "| --- | --- | --- | --- | --- |",
        ]
        for row in rows:
            if row.get("missing"):
                lines.append(f"| `{row['path']}` | — | FALTA | — | — |")
                continue
            kinds = [item["kind"] for item in row["findings"]]
            consts = [
                f"{item['field']}@{item['line']}"
                for item in row["findings"]
                if item["kind"] == "CONSTANT_ZERO"
            ]
            lines.append(
                f"| `{row['path']}` | {'sí' if row['sealed'] else 'no'} | "
                f"{kinds.count('DEMOTED') + kinds.count('LITERAL_FINAL')} | "
                f"{kinds.count('LITERAL_FINAL')} | {', '.join(consts) or '—'} |"
            )
        lines.extend(
            [
                "",
                "`DEMOTED` significa que una condición posterior puede reemplazar el valor; "
                "no prueba que la condición se evalúe, por eso se publica el número de "
                "sitios de degradación y no una garantía.",
                "",
            ]
        )
        target = Path(args.md)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(json.dumps(payload["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
