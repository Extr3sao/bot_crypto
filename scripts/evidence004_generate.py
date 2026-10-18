"""RFC-TAP-EVIDENCE-004 — canonical numbers and the reports derived from them.

One object (``CANONICAL_RUN.json``) is built from the classified ledger, and every
counted statement in the package is rendered from that same object.  Editorial prose
stays editorial: it is never regenerated.  Only the delimited numeric blocks in the
reports are owned by this generator, and a claim whose source no longer exists stops
the run instead of producing a confident sentence with nothing behind it.

Publication is transactional.  A new projection is written into a directory named by
its own content, read back and re-hashed, and only then does ``CURRENT_MANIFEST.json``
switch to it; the previous projection is recorded before it stops being current and is
never deleted.  A disk that fills up mid-run leaves the published package exactly as
it found it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import evidence004_ledger as ledger

CANONICAL_SCHEMA = ledger.CANONICAL_SCHEMA
DEFAULT_LAYOUT = ledger.DEFAULT_LAYOUT
PACKAGE = DEFAULT_LAYOUT.package
EVIDENCE_DIR = DEFAULT_LAYOUT.evidence
CANONICAL_PATH = DEFAULT_LAYOUT.canonical
DERIVED_ROOT = DEFAULT_LAYOUT.derived
CURRENT_MANIFEST = DEFAULT_LAYOUT.current_manifest
SUPERSESSION_MANIFEST = DEFAULT_LAYOUT.supersession_manifest
CLAIMS_PATH = DEFAULT_LAYOUT.claims
LOCK_PATH = DEFAULT_LAYOUT.lock

BLOCK_BEGIN = "<!-- EVIDENCE004:COUNTS:BEGIN -->"
BLOCK_END = "<!-- EVIDENCE004:COUNTS:END -->"
GENERATED_BY = "scripts/evidence004_generate.py"

# Editorial documents: prose this generator must never rewrite.  They are registered
# so an extra report cannot be slipped in unnoticed, and their counted sentences are
# enforced through the managed block rather than through their bytes.
EDITORIAL_DOCUMENTS = (
    "FINAL_REPORT.md",
    "INFORME_EJECUTIVO.md",
    "REA_FINDINGS_V2.json",
    "REA_TARGET_MATRIX.csv",
    "PATTERN_ADOPTION_MATRIX.md",
    "RECONSTRUCTION_COMPARISON.md",
    "INDEPENDENT_VERIFICATION_REA.json",
    "evidence-004/FINAL_REPORT.md",
)

# Every counted sentence in the package.  ``pointer`` is resolved against the
# canonical object; a claim that cannot be resolved is a defect, not a warning.
COUNTER_CLAIMS: tuple[tuple[str, str], ...] = (
    ("phase_v31.work.operations", "counts.phase_v31.work.operations"),
    ("phase_v31.work.executed_with_evidence_id", "counts.phase_v31.work.executed_with_evidence_id"),
    ("phase_v31.work.executed_with_verified_artifact", "counts.phase_v31.work.executed_with_verified_artifact"),
    ("phase_v31.work.not_executed", "counts.phase_v31.work.not_executed"),
    ("phase_v31.distinct_evidence_ids", "counts.phase_v31.distinct_evidence_ids"),
    ("all_dossiers.work.executed_with_evidence_id", "counts.all_dossiers.work.executed_with_evidence_id"),
    ("all_dossiers.work.not_executed", "counts.all_dossiers.work.not_executed"),
    ("all_dossiers.distinct_evidence_ids", "counts.all_dossiers.distinct_evidence_ids"),
)

PLACEHOLDER = re.compile(r"\{([a-z0-9_]+)\}")
# A bare integer in rendered prose is a claim about a count.  Undeclared ones are the
# mechanism by which "nine operations ran" survived review four times.
BARE_INTEGER = re.compile(r"(?<![\w.\-])(\d+)(?![\w.])")


class GenerationError(RuntimeError):
    """The generator refuses to emit documents that its own object cannot support."""


class WriterConflict(RuntimeError):
    """Another generator holds the lock; two writers must never interleave."""


@contextmanager
def single_writer(lock_path: Path | None = None) -> Iterator[None]:
    target = lock_path or LOCK_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise WriterConflict(
            f"{target} exists: another generator is running, or a crashed run left it behind. "
            "Confirm no writer is active before removing it."
        ) from exc
    try:
        os.write(handle, str(os.getpid()).encode("ascii"))
        os.close(handle)
        yield
    finally:
        target.unlink(missing_ok=True)


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _resolve(payload: Mapping[str, Any], pointer: str) -> Any:
    node: Any = payload
    for part in pointer.split("."):
        if not isinstance(node, Mapping) or part not in node:
            raise GenerationError(f"counter pointer {pointer!r} does not resolve in the canonical object")
        node = node[part]
    if not isinstance(node, int) or isinstance(node, bool):
        raise GenerationError(f"counter pointer {pointer!r} is not an integer")
    return node


def build_canonical(
    events: Sequence[ledger.LedgerEvent] | None = None, layout: ledger.Layout | None = None
) -> dict[str, Any]:
    resolved_layout = layout or DEFAULT_LAYOUT
    resolved = list(events if events is not None else ledger.load_events(resolved_layout.root))
    raw = ledger.build_ledger(resolved, resolved_layout.root)
    canonical: dict[str, Any] = {
        "schema": CANONICAL_SCHEMA,
        "rfc": "RFC-TAP-EVIDENCE-004",
        "date": "2026-10-18",
        "work_package": "WP-TAP-EVIDENCE-004F",
        "evidence_dir": ledger.repo_relative(resolved_layout.evidence, resolved_layout.root),
        "ledger_sha256": raw["ledger_sha256"],
        "hash_domains": raw["hash_domains"],
        "source_files": raw["source_files"],
        "counts": raw["counts"],
        # Spans are published, not filtered out: a verifier that is handed no span can
        # only report that it checked nothing.
        "events": [
            {
                key: value
                for key, value in event.items()
                if key not in {"command", "warnings", "duration_s"}
            }
            for event in raw["events"]
        ],
        "evidence_inventory": ledger.evidence_inventory(resolved),
        "invariants": {
            "exit_code_is_not_completion": True,
            "completed_classes": sorted(ledger.COMPLETED_CLASSES),
            "not_executed_classes": sorted(ledger.NOT_EXECUTED_CLASSES),
            "scopes_are_not_additive": True,
            "text_pins_are_content_not_bytes": True,
        },
        "not_run": [
            "real multimodal model call (no credential, no spending authorisation)",
            "upstream Python/TypeScript backends of T-NF-NOF1, T-QR-SIGNAL, T-FE-FENIX",
            "REA on T-TA-CRITIC and T-FM-DEMO (no inspectable surface / no licence)",
            "compare-source-to-bundle (importer blocked on this host)",
        ],
        "real_model_called": False,
        "orders_placed": 0,
        "risk_config_touched": False,
    }
    canonical["counter_values"] = {
        name: _resolve(canonical, pointer) for name, pointer in COUNTER_CLAIMS
    }
    return canonical


def _render_narrative(
    canonical: Mapping[str, Any], claim: Mapping[str, Any]
) -> tuple[str, dict[str, int]]:
    claim_id = str(claim.get("claim_id", "<unnamed>"))
    template = claim.get("template")
    if not isinstance(template, str) or not template.strip():
        raise GenerationError(
            f"claim {claim_id}: a NARRATIVE claim needs a template, not free text; free text "
            "cannot be checked against a counter"
        )
    counters = claim.get("counters")
    if not isinstance(counters, Mapping) or not counters:
        raise GenerationError(f"claim {claim_id}: a NARRATIVE claim must name the counters it renders")

    placeholders = set(PLACEHOLDER.findall(template))
    unknown = placeholders - set(counters)
    if unknown:
        raise GenerationError(
            f"claim {claim_id}: template uses {sorted(unknown)} but declares no such counter"
        )
    values = {name: _resolve(canonical, str(pointer)) for name, pointer in counters.items()}
    try:
        body = template.format(**{name: values[name] for name in placeholders})
    except (KeyError, IndexError) as exc:
        raise GenerationError(f"claim {claim_id}: template does not format: {exc}") from exc

    if "operations" in counters and "not_executed" not in counters:
        raise GenerationError(
            f"claim {claim_id}: a sentence that reports how many operations were attempted must "
            "also report not_executed. Without it the sentence reads as a count of completed work, "
            "which is the false success this package exists to stop."
        )

    allowed = {str(value) for value in values.values()}
    for literal in claim.get("allowed_literals", []) or []:
        allowed.add(str(literal))
    stray = sorted(set(BARE_INTEGER.findall(body)) - allowed)
    if stray:
        raise GenerationError(
            f"claim {claim_id}: renders the number(s) {', '.join(stray)} that no counter or "
            "declared literal supports"
        )
    unused = [name for name, value in values.items() if str(value) not in body]
    if unused:
        raise GenerationError(f"claim {claim_id}: declares {unused} but never renders it")
    return body, values


def verify_claims(canonical: Mapping[str, Any], claims: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Every declared claim must resolve to a counter or an evidence id already in the ledger."""

    native = {
        evidence_id
        for ids in canonical["evidence_inventory"]["rea_native_ids"].values()
        for evidence_id in ids
    }
    resolved: list[dict[str, Any]] = []
    for claim in claims:
        claim_id = str(claim.get("claim_id", ""))
        kind = str(claim.get("kind", ""))
        if not claim_id or not kind:
            raise GenerationError(f"claim {claim_id or '<unnamed>'}: claim_id and kind are required")
        free_text = claim.get("text")
        # A standalone number in prose is a claim about a count; "nof1" is a name.  The
        # distinction is the token boundary, not the presence of a character.
        if isinstance(free_text, str) and BARE_INTEGER.search(free_text):
            raise GenerationError(
                f"claim {claim_id}: free text may not carry a stand-alone digit. A number in "
                "prose is a claim about a count; state it through a NARRATIVE template so it "
                "renders from the ledger."
            )
        if kind == "COUNTER":
            pointer = str(claim.get("pointer", ""))
            expected = claim.get("expected")
            actual = _resolve(canonical, pointer)
            if expected != actual:
                raise GenerationError(
                    f"claim {claim_id}: states {expected!r} at {pointer} but the ledger says {actual!r}"
                )
            resolved.append({**dict(claim), "resolved_value": actual, "verified": True})
        elif kind == "EVIDENCE_ID":
            evidence_id = str(claim.get("evidence_id", ""))
            if evidence_id not in native:
                raise GenerationError(
                    f"claim {claim_id}: {evidence_id!r} is not an evidence_id present in the raw logs"
                )
            resolved.append({**dict(claim), "resolved_value": evidence_id, "verified": True})
        elif kind == "NARRATIVE":
            body, values = _render_narrative(canonical, claim)
            resolved.append(
                {
                    **dict(claim),
                    "rendered": body,
                    "resolved_values": values,
                    "verified": True,
                }
            )
        else:
            raise GenerationError(f"claim {claim_id}: unknown kind {kind!r}")
    return resolved


def render_counts_block(canonical: Mapping[str, Any]) -> str:
    values = canonical["counter_values"]
    lines = [
        BLOCK_BEGIN,
        "",
        f"Números canónicos (generado por `{GENERATED_BY}`; no editar a mano).",
        "",
        "| contador | valor |",
        "| --- | --- |",
    ]
    for name, _pointer in COUNTER_CLAIMS:
        lines.append(f"| `{name}` | {values[name]} |")
    lines.extend(
        [
            "",
            "Los dos ámbitos no se suman: `phase_v31` cubre el trabajo de esta iteración y",
            "`all_dossiers` cubre todo lo registrado en los cuatro dossiers, con otro denominador.",
            "",
            BLOCK_END,
        ]
    )
    return "\n".join(lines)


def render_run_report_md(canonical: Mapping[str, Any]) -> str:
    counts = canonical["counts"]
    phase = counts["phase_v31"]["work"]
    everything = counts["all_dossiers"]
    lines = [
        "# RUN_REPORT — RFC-TAP-EVIDENCE-004 (generado)",
        "",
        f"Generado por `{GENERATED_BY}` a partir de `{canonical['evidence_dir']}/canonical/CANONICAL_RUN.json`.",
        f"`ledger_sha256`: `{canonical['ledger_sha256']}`. No editar a mano: el verificador",
        "independiente recalcula estos números desde los logs crudos y falla si no coinciden.",
        "",
        "## Contadores",
        "",
        render_counts_block(canonical),
        "",
        "## Operaciones de esta iteración",
        "",
        f"**{phase['executed_with_evidence_id']} operaciones REA ejecutadas con `evidence_id`** en esta "
        f"fase, de {phase['operations']} registradas; {phase['not_executed']} no se ejecutaron y la "
        "última columna lo dice. La clase de ejecución va en la celda de evidencia: un exit 0 sin "
        "`evidence_id` nunca cuenta como éxito.",
        "",
        "| # | operación | sujeto | exit | `evidence_id` |",
        "| --- | --- | --- | --- | --- |",
    ]
    phase_events = sorted(
        (event for event in canonical["events"] if event["timestamp"] >= ledger.PHASE_START),
        key=lambda item: (item["timestamp"], item["target_id"]),
    )
    for index, event in enumerate(phase_events, start=1):
        evidence = event["evidence"]
        identifier = evidence["evidence_id"]
        if identifier is None:
            evidence_text = f"— (`{event['execution_class']}`)"
        else:
            mark = "verificado" if evidence["status"] == ledger.EVIDENCE_VERIFIED else "declarado"
            evidence_text = f"`{identifier[:12]}…` ({mark})"
        lines.append(
            "| {index} | `{operation}` | `{target}` | {exit_code} | {evidence} |".format(
                index=index,
                operation=event["operation"],
                target=event["target_id"],
                exit_code="—" if event["exit_code"] is None else event["exit_code"],
                evidence=evidence_text,
            )
        )
    lines.extend(
        [
            "",
            "## Lo que la tabla no dice",
            "",
            f"- El exit code no decide nada: {phase['class_breakdown'].get(ledger.REFUSED_INVALID_INPUT, 0)} "
            "operación(es) devolvieron exit 0 y aun así no se ejecutaron "
            "(`NOT_EXECUTED_INVALID_INPUT`).",
            f"- De las {phase['executed_with_evidence_id']} operaciones con `evidence_id`, "
            f"{phase['executed_with_verified_artifact']} tienen artefacto en disco cuyo sha256 coincide "
            f"con el declarado; las otras {phase['executed_evidence_declared_unverified']} son "
            "evidencia **declarada**, no comprobada byte a byte.",
            f"- Ámbito ampliado: {everything['distinct_evidence_ids']} `evidence_id` distintos en los "
            f"cuatro dossiers, de {everything['work']['operations']} operaciones de trabajo. "
            "Es otro denominador, no una cifra mayor del mismo contador.",
            f"- Discovery separado del trabajo: {counts['phase_v31']['readiness']['operations']} operación(es) "
            "de readiness en esta iteración (`list_browser_targets`), contadas aparte.",
            "- Cero llamadas reales a un modelo, cero órdenes, cero cambios en `config/risk.yaml`.",
            "- `REAL_MODEL_CALLED = false`; ningún patrón externo queda certificado por este informe.",
            "",
        ]
    )
    return "\n".join(lines)


def render_executive_numbers(canonical: Mapping[str, Any]) -> str:
    counts = canonical["counts"]
    phase = counts["phase_v31"]["work"]
    return "\n".join(
        [
            "# Informe ejecutivo — cifras derivadas",
            "",
            f"Derivado de `{canonical['evidence_dir']}/canonical/CANONICAL_RUN.json` (`ledger_sha256` "
            f"`{canonical['ledger_sha256'][:16]}…`).",
            "",
            render_counts_block(canonical),
            "",
            "## Lectura en tres frases",
            "",
            f"1. En esta iteración se registraron {phase['operations']} operaciones REA de trabajo: "
            f"{phase['executed_with_evidence_id']} devolvieron `evidence_id` y "
            f"{phase['not_executed']} no llegaron a ejecutarse.",
            f"2. Sólo {phase['executed_with_verified_artifact']} de esas evidencias tienen artefacto "
            "verificado por hash en este repositorio; el resto está declarado en los dossiers.",
            f"3. Los cuatro dossiers completos suman {counts['all_dossiers']['distinct_evidence_ids']} "
            "`evidence_id` distintos — otro ámbito, no la misma cifra.",
            "",
            "## Lo que no se puede afirmar",
            "",
            "- Ninguna llamada real a un modelo multimodal: `REAL_MODEL_CALLED = false`.",
            "- Ningún patrón externo certificado: `NO_REA_EVIDENCE = NO_EXTERNAL_PATTERN_CERTIFICATION`.",
            "- Ninguna rentabilidad: los runs son mock y no miden edge.",
            "",
        ]
    )


def render_claims_md(canonical: Mapping[str, Any]) -> str:
    """The published sentences, each rendered from a counter or an evidence id."""

    lines = ["# Afirmaciones publicadas", "", f"Generado por `{GENERATED_BY}`.", ""]
    for claim in canonical.get("claims", []):
        if claim.get("kind") == "NARRATIVE":
            lines.append(f"- **{claim['claim_id']}** — {claim['rendered']}")
        elif claim.get("kind") == "EVIDENCE_ID":
            lines.append(
                f"- **{claim['claim_id']}** — `{str(claim['evidence_id'])[:16]}…` "
                f"({claim.get('text') or 'evidence id present in the raw logs'})"
            )
        else:
            lines.append(
                f"- **{claim['claim_id']}** — `{claim.get('pointer')}` = "
                f"{claim.get('resolved_value')} ({claim.get('text') or 'counter'})"
            )
    lines.append("")
    return "\n".join(lines)


def render_run_report_json(canonical: Mapping[str, Any]) -> str:
    # The two flat aliases keep the previous consumers working without letting anyone
    # hand-maintain them: both are computed here from the canonical counters, and both
    # verifiers assert they match.  They are not a second source of truth.
    phase_work = canonical["counts"]["phase_v31"]["work"]
    counts = {
        **canonical["counts"],
        "rea_operations_registered": phase_work["operations"],
        "rea_operations_evidenced": phase_work["executed_with_evidence_id"],
        "rea_operations_not_executed": phase_work["not_executed"],
        "legacy_alias_note": (
            "rea_operations_registered / rea_operations_evidenced / rea_operations_not_executed are "
            "aliases of counts.phase_v31.work for readers of the previous schema; they are generated "
            "from the same object and are not a second source of truth. Registered operations are "
            "attempts; only executed_with_evidence_id is work REA completed."
        ),
    }
    payload = {
        "schema": "evidence004/run-report/1",
        "generated_by": GENERATED_BY,
        "canonical": f"{canonical['evidence_dir']}/canonical/CANONICAL_RUN.json",
        "ledger_sha256": canonical["ledger_sha256"],
        "hash_domains": canonical["hash_domains"],
        "counts": counts,
        "counter_values": canonical["counter_values"],
        "claims": canonical.get("claims", []),
        "source_files": canonical["source_files"],
        "operations": canonical["events"],
        "evidence_inventory": canonical["evidence_inventory"],
        "not_run": canonical["not_run"],
        "real_model_called": canonical["real_model_called"],
        "orders_placed": canonical["orders_placed"],
        "risk_config_touched": canonical["risk_config_touched"],
        "count_note": (
            "An exit code of 0 is not a success criterion. compare-source-to-bundle returned exit 0 "
            "with NOT_EXECUTED_INVALID_INPUT and produced no evidence_id, so it is counted as not "
            "executed. phase_v31 and all_dossiers are separate denominators."
        ),
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def apply_block(path: Path, block: str) -> None:
    """Replace the managed numeric block, leaving every editorial sentence untouched."""

    text = path.read_text(encoding="utf-8")
    if BLOCK_BEGIN in text and BLOCK_END in text:
        start = text.index(BLOCK_BEGIN)
        end = text.index(BLOCK_END) + len(BLOCK_END)
        updated = text[:start] + block + text[end:]
    elif BLOCK_BEGIN in text or BLOCK_END in text:
        raise GenerationError(f"{ledger.repo_relative(path)}: unbalanced EVIDENCE004 markers")
    else:
        updated = text.rstrip("\n") + "\n\n" + block + "\n"
    if updated != text:
        write_atomic(path, updated)


def _load_claims(layout: ledger.Layout) -> list[Mapping[str, Any]]:
    if not layout.claims.is_file():
        return []
    loaded = json.loads(layout.claims.read_text(encoding="utf-8"))
    if not isinstance(loaded, list):
        raise GenerationError(f"{ledger.repo_relative(layout.claims)}: expected a list of claims")
    return [claim for claim in loaded if isinstance(claim, dict)]


def _document_registry(layout: ledger.Layout, derived: Path, hashes: Mapping[str, str]) -> dict[str, Any]:
    return {
        "schema": "evidence004/current-manifest/1",
        "generated_by": GENERATED_BY,
        "canonical": ledger.repo_relative(layout.canonical, layout.root),
        "derived_dir": ledger.repo_relative(derived, layout.root),
        "documents": sorted(
            (
                {
                    "path": ledger.repo_relative(derived / name, layout.root),
                    "role": "DERIVED",
                    "sha256": value,
                    "hash_domain": ledger.TEXT_DOMAIN,
                }
                for name, value in hashes.items()
            ),
            key=lambda item: item["path"],
        ),
    }


def _projection_id(canonical_sha256: str, hashes: Mapping[str, str], ledger_sha: str) -> str:
    """Name a projection by what is inside it, so no two different projections collide."""

    identity = ledger.digest(
        {
            "ledger_sha256": ledger_sha,
            "canonical_sha256": canonical_sha256,
            "documents": dict(hashes),
        }
    )
    return f"{ledger_sha[:12]}.{identity[:8]}"


def _self_check(derived: Path, hashes: Mapping[str, str]) -> None:
    for name, expected in hashes.items():
        path = derived / name
        if not path.is_file():
            raise GenerationError(f"candidate projection is missing {name}")
        if ledger.sha256_file(path) != expected:
            raise GenerationError(f"candidate projection {name} does not match what was rendered")


def _read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _record_switch(
    layout: ledger.Layout, current: Mapping[str, Any], projection: str
) -> dict[str, Any]:
    """Record the projection that stops being current, before it stops being current."""

    previous = _read_json(
        layout.superseded_projections,
        {"schema": "evidence004/superseded-projections/1", "projections": []},
    )
    if not isinstance(previous.get("projections"), list):
        raise GenerationError(
            f"{ledger.repo_relative(layout.superseded_projections)}: projections must be a list"
        )
    history: list[dict[str, Any]] = list(previous["projections"])
    current_manifest = _read_json(layout.current_manifest, {})
    previous_dir = current_manifest.get("derived_dir")
    if (
        isinstance(previous_dir, str)
        and Path(previous_dir).name != projection
        and not any(row.get("derived_dir") == previous_dir for row in history)
    ):
        history.append(
            {
                "derived_dir": previous_dir,
                "ledger_sha256": current_manifest.get("ledger_sha256"),
                "canonical_sha256": current_manifest.get("canonical_sha256"),
                "superseded_by": projection,
            }
        )
    payload = {
        "schema": "evidence004/superseded-projections/1",
        "note": (
            "A projection stops being current when CURRENT_MANIFEST.json switches away from it. "
            "It is recorded here first and then kept: no report is ever deleted to make the "
            "current one look unambiguous."
        ),
        "projections": history,
    }
    write_atomic(
        layout.superseded_projections, json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    )
    return payload


def _prune_orphan_projections(layout: ledger.Layout, keep: set[str]) -> list[str]:
    """Remove only directories this package has no record of, after a successful publish."""

    if not layout.derived.is_dir():
        return []
    removed: list[str] = []
    for directory in sorted(layout.derived.iterdir()):
        if not directory.is_dir() or directory.name in keep:
            continue
        shutil.rmtree(directory)
        removed.append(directory.name)
    return removed


def _snapshot(paths: Sequence[Path]) -> dict[Path, bytes | None]:
    return {path: (path.read_bytes() if path.is_file() else None) for path in paths}


def _restore(snapshot: Mapping[Path, bytes | None]) -> list[str]:
    failures: list[str] = []
    for path, payload in snapshot.items():
        try:
            if payload is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)
        except OSError as exc:  # pragma: no cover - a rollback that also fails is reported
            failures.append(f"{ledger.repo_relative(path)}: {exc}")
    return failures


def generate(
    events: Sequence[ledger.LedgerEvent] | None = None,
    dry_run: bool = False,
    layout: ledger.Layout | None = None,
) -> dict[str, Any]:
    resolved_layout = layout or DEFAULT_LAYOUT
    canonical = build_canonical(events, resolved_layout)
    canonical["claims"] = verify_claims(canonical, _load_claims(resolved_layout))

    canonical_text = json.dumps(canonical, indent=2, ensure_ascii=False) + "\n"
    canonical_sha = ledger.sha256_bytes(canonical_text.encode("utf-8"))

    rendered = {
        "RUN_REPORT.json": render_run_report_json(canonical),
        "RUN_REPORT.md": render_run_report_md(canonical),
        "INFORME_EJECUTIVO_NUMEROS.md": render_executive_numbers(canonical),
        "CLAIMS.md": render_claims_md(canonical),
    }
    hashes = {name: ledger.sha256_bytes(text.encode("utf-8")) for name, text in rendered.items()}
    projection = _projection_id(canonical_sha, hashes, canonical["ledger_sha256"])
    derived = resolved_layout.derived / projection
    manifest = {
        **_document_registry(resolved_layout, derived, hashes),
        "canonical_sha256": canonical_sha,
        "ledger_sha256": canonical["ledger_sha256"],
    }
    manifest_text = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"

    if dry_run:
        return {
            "canonical_sha256": canonical_sha,
            "projection": projection,
            "derived_dir": ledger.repo_relative(derived, resolved_layout.root),
            "counts": canonical["counts"],
            "files": sorted([*rendered, "MANIFEST.json"]),
        }

    # 1. Candidate projection, complete and self-checked before anything visible moves.
    if not derived.is_dir():
        derived.mkdir(parents=True)
        try:
            for name, text in rendered.items():
                write_atomic(derived / name, text)
            write_atomic(derived / "MANIFEST.json", manifest_text)
            _self_check(derived, hashes)
        except BaseException:
            shutil.rmtree(derived, ignore_errors=True)
            raise
    else:
        _self_check(derived, hashes)

    stable_copies = [resolved_layout.package / "RUN_REPORT.json", resolved_layout.package / "RUN_REPORT.md"]
    editorial = [resolved_layout.package / "FINAL_REPORT.md", resolved_layout.package / "INFORME_EJECUTIVO.md"]
    volatile = [
        resolved_layout.canonical,
        *stable_copies,
        *[path for path in editorial if path.is_file()],
        resolved_layout.superseded_projections,
        resolved_layout.current_manifest,
    ]
    snapshot = _snapshot(volatile)

    # 2. Publish: the current manifest is written last and is the only switch point.
    try:
        write_atomic(resolved_layout.canonical, canonical_text)
        for name, path in zip(("RUN_REPORT.json", "RUN_REPORT.md"), stable_copies, strict=True):
            write_atomic(path, rendered[name])

        block = render_counts_block(canonical)
        for path in editorial:
            if path.is_file():
                apply_block(path, block)

        editorial_records: list[dict[str, Any]] = []
        for name in EDITORIAL_DOCUMENTS:
            path = resolved_layout.package / name
            if not path.is_file():
                raise GenerationError(f"editorial document {name} is registered but missing")
            editorial_records.append(
                {
                    "path": ledger.repo_relative(path, resolved_layout.root),
                    "role": "CURRENT_EDITORIAL",
                    "sha256_at_generation": ledger.sha256_file(path),
                    "hash_domain": ledger.hash_domain_for(path),
                }
            )

        history = _record_switch(resolved_layout, manifest, projection)
        supersession = _read_json(resolved_layout.supersession_manifest, None)
        current = {
            **_document_registry(resolved_layout, derived, hashes),
            "canonical_sha256": canonical_sha,
            "ledger_sha256": canonical["ledger_sha256"],
            "stable_copies": [
                {
                    "path": ledger.repo_relative(path, resolved_layout.root),
                    "sha256": hashes[name],
                    "role": "CURRENT",
                    "hash_domain": ledger.TEXT_DOMAIN,
                }
                for name, path in zip(("RUN_REPORT.json", "RUN_REPORT.md"), stable_copies, strict=True)
            ],
            "editorial": editorial_records,
            "superseded_manifest": ledger.repo_relative(
                resolved_layout.supersession_manifest, resolved_layout.root
            )
            if supersession is not None
            else None,
            "superseded_projections": ledger.repo_relative(
                resolved_layout.superseded_projections, resolved_layout.root
            ),
        }
        write_atomic(resolved_layout.current_manifest, json.dumps(current, indent=2, ensure_ascii=False) + "\n")
    except BaseException:
        _restore(snapshot)
        raise

    keep = {projection} | {
        Path(str(row.get("derived_dir", ""))).name for row in history["projections"]
    }
    removed = _prune_orphan_projections(resolved_layout, keep)

    return {
        "canonical_sha256": canonical_sha,
        "ledger_sha256": canonical["ledger_sha256"],
        "projection": projection,
        "derived_dir": ledger.repo_relative(derived, resolved_layout.root),
        "pruned": removed,
        "counts": canonical["counts"],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="compute and print, write nothing")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    parser.add_argument("--root", default=None, help="repository root (defaults to this checkout)")
    args = parser.parse_args(argv)
    layout = ledger.Layout(Path(args.root).resolve()) if args.root else DEFAULT_LAYOUT
    try:
        if args.dry_run:
            result = generate(dry_run=True, layout=layout)
        else:
            with single_writer(layout.lock):
                result = generate(layout=layout)
    except (ledger.LedgerError, GenerationError, WriterConflict) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"canonical sha256: {result['canonical_sha256']}")
        print(f"derived dir: {result['derived_dir']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
