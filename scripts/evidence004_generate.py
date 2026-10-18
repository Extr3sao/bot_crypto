"""RFC-TAP-EVIDENCE-004 — canonical numbers and the reports derived from them.

One object (``CANONICAL_RUN.json``) is built from the classified ledger, and every
counted statement in the package is rendered from that same object.  Editorial prose
stays editorial: it is never regenerated.  Only the delimited numeric blocks in the
reports are owned by this generator, and a claim whose source no longer exists stops
the run instead of producing a confident sentence with nothing behind it.

Writes are atomic (temp file + ``os.replace``) and a single-writer lock refuses a
second run, so a half-written report cannot be mistaken for a complete one.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import evidence004_ledger as ledger

CANONICAL_SCHEMA = ledger.CANONICAL_SCHEMA
PACKAGE = ledger.PACKAGE
EVIDENCE_DIR = ledger.EVIDENCE_DIR
CANONICAL_PATH = EVIDENCE_DIR / "canonical" / "CANONICAL_RUN.json"
DERIVED_ROOT = EVIDENCE_DIR / "derived"
CURRENT_MANIFEST = EVIDENCE_DIR / "CURRENT_MANIFEST.json"
SUPERSESSION_MANIFEST = EVIDENCE_DIR / "SUPERSESSION_MANIFEST.json"
CLAIMS_PATH = EVIDENCE_DIR / "CLAIMS.json"
LOCK_PATH = EVIDENCE_DIR / ".writer.lock"

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


class GenerationError(RuntimeError):
    """The generator refuses to emit documents that its own object cannot support."""


class WriterConflict(RuntimeError):
    """Another generator holds the lock; two writers must never interleave."""


@contextmanager
def single_writer(lock_path: Path = LOCK_PATH) -> Iterator[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise WriterConflict(
            f"{lock_path} exists: another generator is running, or a crashed run left it behind. "
            "Confirm no writer is active before removing it."
        ) from exc
    try:
        os.write(handle, str(os.getpid()).encode("ascii"))
        os.close(handle)
        yield
    finally:
        lock_path.unlink(missing_ok=True)


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


def build_canonical(events: Sequence[ledger.LedgerEvent] | None = None) -> dict[str, Any]:
    resolved = list(events if events is not None else ledger.load_events())
    raw = ledger.build_ledger(resolved)
    canonical: dict[str, Any] = {
        "schema": CANONICAL_SCHEMA,
        "rfc": "RFC-TAP-EVIDENCE-004",
        "date": "2026-10-18",
        "evidence_dir": ledger.repo_relative(EVIDENCE_DIR),
        "ledger_sha256": raw["ledger_sha256"],
        "source_files": [{"path": path, "sha256": value} for path, value in raw["source_files"]],
        "counts": raw["counts"],
        "events": [
            {
                key: value
                for key, value in event.items()
                if key not in {"command", "warnings", "sources", "duration_s"}
            }
            for event in raw["events"]
        ],
        "evidence_inventory": ledger.evidence_inventory(resolved),
        "invariants": {
            "exit_code_is_not_completion": True,
            "completed_classes": sorted(ledger.COMPLETED_CLASSES),
            "not_executed_classes": sorted(ledger.NOT_EXECUTED_CLASSES),
            "scopes_are_not_additive": True,
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
        text = str(claim.get("text", ""))
        if not claim_id or not kind or not text:
            raise GenerationError(f"claim {claim_id or '<unnamed>'}: claim_id, kind and text are required")
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
        f"Generado por `{GENERATED_BY}` a partir de `{ledger.repo_relative(CANONICAL_PATH)}`.",
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
        f"fase, de {phase['operations']} de trabajo; {phase['not_executed']} no se ejecutaron y la "
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
            f"Derivado de `{ledger.repo_relative(CANONICAL_PATH)}` (`ledger_sha256` "
            f"`{canonical['ledger_sha256'][:16]}…`).",
            "",
            render_counts_block(canonical),
            "",
            "## Lectura en tres frases",
            "",
            f"1. En esta iteración hubo {phase['operations']} operaciones REA de trabajo: "
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


def render_run_report_json(canonical: Mapping[str, Any]) -> str:
    # The two flat aliases keep the previous consumers working without letting anyone
    # hand-maintain them: both are computed here from the canonical counters, and both
    # verifiers assert they match.  They are not a second source of truth.
    phase_work = canonical["counts"]["phase_v31"]["work"]
    counts = {
        **canonical["counts"],
        "rea_operations_evidenced": phase_work["executed_with_evidence_id"],
        "rea_operations_not_executed": phase_work["not_executed"],
        "legacy_alias_note": (
            "rea_operations_evidenced / rea_operations_not_executed are aliases of "
            "counts.phase_v31.work for readers of the previous schema; they are generated from "
            "the same object and are not a second source of truth."
        ),
    }
    payload = {
        "schema": "evidence004/run-report/1",
        "generated_by": GENERATED_BY,
        "canonical": ledger.repo_relative(CANONICAL_PATH),
        "ledger_sha256": canonical["ledger_sha256"],
        "counts": counts,
        "counter_values": canonical["counter_values"],
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


def _document_registry(derived: Path, hashes: Mapping[str, str]) -> dict[str, Any]:
    return {
        "schema": "evidence004/current-manifest/1",
        "generated_by": GENERATED_BY,
        "canonical": ledger.repo_relative(CANONICAL_PATH),
        "derived_dir": ledger.repo_relative(derived),
        "documents": sorted(
            (
                {"path": ledger.repo_relative(derived / name), "role": "DERIVED", "sha256": value}
                for name, value in hashes.items()
            ),
            key=lambda item: item["path"],
        ),
    }


def generate(events: Sequence[ledger.LedgerEvent] | None = None, dry_run: bool = False) -> dict[str, Any]:
    canonical = build_canonical(events)
    claims: list[Mapping[str, Any]] = []
    if CLAIMS_PATH.is_file():
        loaded = json.loads(CLAIMS_PATH.read_text(encoding="utf-8"))
        if not isinstance(loaded, list):
            raise GenerationError(f"{ledger.repo_relative(CLAIMS_PATH)}: expected a list of claims")
        claims = [claim for claim in loaded if isinstance(claim, dict)]
    canonical["claims"] = verify_claims(canonical, claims)

    canonical_text = json.dumps(canonical, indent=2, ensure_ascii=False) + "\n"
    canonical_sha = ledger.sha256_bytes(canonical_text.encode("utf-8"))
    short = canonical["ledger_sha256"][:12]
    derived = DERIVED_ROOT / short

    rendered = {
        "RUN_REPORT.json": render_run_report_json(canonical),
        "RUN_REPORT.md": render_run_report_md(canonical),
        "INFORME_EJECUTIVO_NUMEROS.md": render_executive_numbers(canonical),
    }
    hashes = {name: ledger.sha256_bytes(text.encode("utf-8")) for name, text in rendered.items()}
    manifest = {
        **_document_registry(derived, hashes),
        "canonical_sha256": canonical_sha,
        "ledger_sha256": canonical["ledger_sha256"],
    }

    if dry_run:
        return {
            "canonical_sha256": canonical_sha,
            "derived_dir": ledger.repo_relative(derived),
            "counts": canonical["counts"],
            "files": sorted([*rendered, "MANIFEST.json"]),
        }

    # A projection of a superseded ledger is itself a stale report that someone could
    # quote as current, so only the projection of the current ledger survives. Git
    # still holds the previous one; nothing evidential is destroyed here.
    if DERIVED_ROOT.is_dir():
        for stale in DERIVED_ROOT.iterdir():
            if stale.is_dir() and stale.name != short:
                shutil.rmtree(stale)

    write_atomic(CANONICAL_PATH, canonical_text)
    for name, text in rendered.items():
        write_atomic(derived / name, text)
    write_atomic(derived / "MANIFEST.json", json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")

    # Stable paths the RFC names explicitly, byte-identical to the derived copies.
    for name in ("RUN_REPORT.json", "RUN_REPORT.md"):
        write_atomic(PACKAGE / name, rendered[name])

    # The managed block is applied before the editorial registry is hashed, so the
    # recorded digest is the digest of the file the reader will actually open.
    block = render_counts_block(canonical)
    for path in (PACKAGE / "FINAL_REPORT.md", PACKAGE / "INFORME_EJECUTIVO.md"):
        if path.is_file():
            apply_block(path, block)

    editorial: list[dict[str, Any]] = []
    for name in EDITORIAL_DOCUMENTS:
        path = PACKAGE / name
        if not path.is_file():
            raise GenerationError(f"editorial document {name} is registered but missing")
        editorial.append(
            {
                "path": ledger.repo_relative(path),
                "role": "CURRENT_EDITORIAL",
                "sha256_at_generation": ledger.sha256_file(path),
            }
        )

    supersession = json.loads(SUPERSESSION_MANIFEST.read_text(encoding="utf-8")) if SUPERSESSION_MANIFEST.is_file() else None
    current = {
        **_document_registry(derived, hashes),
        "canonical_sha256": canonical_sha,
        "ledger_sha256": canonical["ledger_sha256"],
        "stable_copies": [
            {
                "path": ledger.repo_relative(PACKAGE / name),
                "sha256": hashes[name],
                "role": "CURRENT",
            }
            for name in ("RUN_REPORT.json", "RUN_REPORT.md")
        ],
        "editorial": editorial,
        "superseded_manifest": ledger.repo_relative(SUPERSESSION_MANIFEST)
        if supersession is not None
        else None,
    }
    write_atomic(CURRENT_MANIFEST, json.dumps(current, indent=2, ensure_ascii=False) + "\n")

    return {
        "canonical_sha256": canonical_sha,
        "ledger_sha256": canonical["ledger_sha256"],
        "derived_dir": ledger.repo_relative(derived),
        "counts": canonical["counts"],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="compute and print, write nothing")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    args = parser.parse_args(argv)
    try:
        if args.dry_run:
            result = generate(dry_run=True)
        else:
            with single_writer():
                result = generate()
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
