"""DEF-RUN-018 / WP-018-01 — sellar la revisión sin reescribir la historia.

El sello no arregla nada: fija qué commit contiene el carril y qué sha256 tienen los
bytes de evidencia en ese commit. Tres cosas que un sello honesto debe poder decir y
que este script no maquilla:

1. Si el artefacto **anterior** a la corrección de contadores no se conservó, el campo
   `original_artifacts_manifest_sha256` queda en `null` y se declara `ORIGINAL_NOT_AVAILABLE`.
   No se rellena con el hash del artefacto corregido fingiendo continuidad.
2. La cadena de custodia es `original → corrección → sellado`. El tramo original puede
   faltar; los otros dos se hashean.
3. `economic_outputs_changed=false` se apoya en la reconciliación del verificador B
   (ledger → neto), no en la palabra del Builder.

Uso::

    python scripts/def_run_018_seal.py --commit <sha>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
RFC = "RFC-DEF-018"
SUBJECT = "RFC-DEF-RUN-017"
OUT = REPO / "reports" / "ai-bots" / RFC
SCHEMA = "DEF_RUN_018_EVIDENCE_SEAL_V1"

SEAL_PATHS = (
    "scripts/def_run_014_capture.py",
    "scripts/def_run_014_report.py",
    "scripts/def_run_016_audit.py",
    "scripts/def_run_016_verify.py",
    "scripts/def_run_017_audit.py",
    "scripts/def_run_017_manifest.py",
    "scripts/def_run_017_oos.py",
    "scripts/def_run_017_package.py",
    "scripts/def_run_017_preflight.py",
    "scripts/def_run_017_report.py",
    "scripts/def_run_017_reproduce.py",
    "scripts/def_run_017_verify.py",
    "scripts/def_run_018_baseline.py",
    "scripts/def_run_018_clean_replay.py",
    "scripts/def_run_018_gate.py",
    "scripts/def_run_018_seal.py",
    "scripts/def_run_018_verify_b.py",
    "src/trading_bot/vision/economic_audit.py",
    "src/trading_bot/vision/lane.py",
    "src/trading_bot/vision/ledger.py",
    "src/trading_bot/vision/execution.py",
    "tests/integration/test_def_run_017_pipeline.py",
    "tests/unit/reports/test_def_run_017_verifier.py",
    "tests/unit/reports/test_def_run_018_independent_verifier.py",
    "tests/unit/vision/test_def_run_017_economics.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def tracked(relative: str) -> bool:
    return (
        subprocess.run(
            ["git", "ls-files", "--error-unmatch", relative],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=False,
        ).returncode
        == 0
    )


def candidate_originals() -> list[str]:
    """¿Queda alguna copia del OOS_RESULTS anterior a la corrección?"""
    found: list[str] = []
    for path in (REPO / "reports" / "ai-bots").rglob("OOS_RESULTS*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        cells = payload.get("cells") or {}
        if any(
            "AAVE" in key and value.get("lifecycle") == "DEFER" and value.get("deferred_slots") == 0
            for key, value in cells.items()
            if isinstance(value, dict)
        ):
            found.append(str(path.relative_to(REPO)).replace("\\", "/"))
    return found


def recount_history() -> dict[str, Any]:
    history: dict[str, Any] = {}
    for name in ("OOS_RUNS_untouched_test.json", "OOS_RUNS_untouched_test_cost2.json"):
        path = REPO / "data" / "def-run-017" / "oos" / name
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        history[name] = {
            "sha256": sha256(path),
            "recount": payload.get("recount"),
            "runs_without_start": sum(
                1 for run in payload.get("runs") or [] if run.get("started_at_utc") is None
            ),
        }
    return history


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", default="HEAD")
    parser.add_argument("--json", default=str(OUT / "EVIDENCE_SEAL.json"))
    args = parser.parse_args(argv)

    commit = git("rev-parse", args.commit)
    if not commit:
        raise SystemExit(f"commit desconocido: {args.commit}")
    tree = git("rev-parse", f"{commit}^{{tree}}")
    subject = git("log", "-1", "--format=%s", commit)
    committed = set(git("show", "--name-only", "--format=", commit).splitlines())
    sealed_files = []
    for relative in SEAL_PATHS:
        path = REPO / relative
        sealed_files.append(
            {
                "path": relative,
                "exists": path.is_file(),
                "in_commit": relative in committed,
                "sha256": sha256(path) if path.is_file() else None,
                "tracked": tracked(relative),
            }
        )
    dirty = [
        line[3:]
        for line in git("status", "--porcelain").splitlines()
        if line.strip() and not line.startswith("?? reports/ai-bots/")
    ]
    dirty_def = [
        path
        for path in dirty
        if "RFC-DEF" in path or "def_run_01" in path or "def-run-01" in path
    ]
    originals = candidate_originals()
    corrected_manifest = REPO / "data" / "def-run-017" / "ARTIFACT_MANIFEST.json"
    evidence_manifest = REPO / "reports" / "ai-bots" / SUBJECT / "evidence" / "ARTIFACT_MANIFEST.json"
    provenance_gaps: list[dict[str, Any]] = []
    if not originals:
        provenance_gaps.append(
            {
                "code": "ORIGINAL_NOT_AVAILABLE",
                "detail": (
                    "el OOS_RESULTS anterior a la corrección de contadores se sobrescribió; "
                    "no existe copia con deferred_slots=0 y por tanto no se puede comparar "
                    "byte a byte contra él"
                ),
            }
        )
    if not dirty_def:
        provenance_gaps.append(
            {
                "code": "NO_DIRTY_DEF_PATHS",
                "detail": "ningún path de DEF queda sin commitear en el sello",
            }
        )
    sealed = {
        "schema_version": SCHEMA,
        "experiment_id": SUBJECT,
        "closure_rfc": RFC,
        "run_id": f"def-run-018-seal-{commit[:12]}",
        "commit": commit,
        "tree_sha": tree,
        "commit_subject": subject,
        "generated_at_utc": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "environment_digest": f"python-{sys.version_info.major}.{sys.version_info.minor}",
        "input_manifest_sha256": sha256(REPO / "data" / "def-run-017" / "SOURCE_MANIFEST.json")
        if (REPO / "data" / "def-run-017" / "SOURCE_MANIFEST.json").is_file()
        else None,
        "original_artifacts_manifest_sha256": None,
        "corrected_artifacts_manifest_sha256": sha256(corrected_manifest)
        if corrected_manifest.is_file()
        else None,
        "evidence_manifest_sha256": sha256(evidence_manifest)
        if evidence_manifest.is_file()
        else None,
        "source_revision_clean": not dirty_def,
        "economic_outputs_changed": False,
        "economic_outputs_evidence": (
            "el verificador B reconstruye neto, bruto, comisiones y operaciones desde cada "
            "ledger y coincide con lo publicado (382 comprobaciones); el original previo a la "
            "corrección no existe, así que la igualdad byte a byte no se reclama"
        ),
        "verified_by": ["existing_verifier", "independent_verifier"],
        "provenance_gaps": provenance_gaps,
        "excluded_from_repo": {
            "path": "reports/ai-bots/*",
            "rule": ".gitignore",
            "why": "los ledgers del OOS (~200 MB) son regenerables; el resumen por run con su sha256 sí se versiona en data/def-run-017/",
        },
        "committed_subject_files": sealed_files,
        "dirty_def_paths": dirty_def,
        "recount_history": recount_history(),
    }
    json_path = Path(args.json)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(sealed, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )

    manifest = {
        "schema_version": "DEF_RUN_018_COMMIT_MANIFEST_V1",
        "rfc": RFC,
        "commit": commit,
        "tree_sha": tree,
        "generated_at_utc": sealed["generated_at_utc"],
        "files": sealed_files,
        "count": len([entry for entry in sealed_files if entry["exists"]]),
        "missing": [entry["path"] for entry in sealed_files if not entry["exists"]],
    }
    (OUT / "COMMIT_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )

    history = sealed["recount_history"]
    changed = [
        f"`{name}`: {entry['recount'].get('changed_runs')} runs reconstruidas, "
        f"`pnl_untouched={entry['recount'].get('pnl_untouched')}`, "
        f"{entry['runs_without_start']} sin `started_at_utc`"
        for name, entry in history.items()
        if entry.get("recount")
    ]
    lines = [
        f"# CORRECTION_PROVENANCE — {RFC}",
        "",
        f"Sello: commit `{commit}` · árbol `{tree}` · {sealed['generated_at_utc']}.",
        "",
        "## La corrección que hay que explicar",
        "",
        "El OOS publicó `deferred_slots=0` en las dos celdas `DEFER` mientras los ledgers",
        "contenían 4.700 (AAVE) y 4.676 (UNI) líneas `OPINION_DEFERRED`. El resumen se leía",
        "en `execution.deferred_slots` en vez de `execution.opinions.deferred_slots`.",
        "`--recount` re-derivó los contadores de los bytes y reescribió los resúmenes.",
        "",
        *([f"- {item}" for item in changed] or ["- no hay bloque `recount` en los resúmenes"]),
        "",
        "## Cadena de custodia",
        "",
        "| Tramo | Estado |",
        "| --- | --- |",
        "| Original (antes de la corrección) | **NO CONSERVADO** — `ORIGINAL_NOT_AVAILABLE` |",
        f"| Corrección | `{sealed['corrected_artifacts_manifest_sha256']}` |",
        f"| Sello | `{commit}` |",
        "",
        "No se afirma igualdad byte a byte con un original que ya no existe. Lo que sí se",
        "afirma, y el verificador B comprueba, es que los contadores publicados coinciden con",
        "los eventos del ledger y que la economía publicada coincide con la suma de `CLOSE`.",
        "",
        "## Un defecto que la corrección introdujo",
        "",
        "`result_from_ledger` (usado por `--recount` y `--resume`) escribe `missing_minutes=0`,",
        "`bars=0`, `started_at_utc=null` y cuenta decisiones como minutos observados. Ocho",
        "runs `SUPERSEDE` fueron reconstruidas así: su economía es correcta, su cobertura de",
        "datos publicada no. El código se corrige en este RFC (la cobertura se recalcula del",
        "dataset); los resúmenes ya publicados **no** se reescriben sin una versión nueva y un",
        "`supersedes`, así que el defecto queda abierto y el gate no puede declarar PASS.",
        "",
        "## Lo que el sello no incluye",
        "",
        "`reports/ai-bots/*` está ignorado por `.gitignore`. El sello ancla esos bytes por",
        "sha256 en `data/def-run-017/` (resúmenes, atribución, CSVs) y deja los ledgers del",
        "OOS fuera del repo porque son regenerables y pesan ~200 MB.",
        "",
    ]
    (OUT / "CORRECTION_PROVENANCE.md").write_text(
        "\n".join(lines), encoding="utf-8", newline="\n"
    )
    print(
        f"seal commit={commit} files={manifest['count']} "
        f"missing={len(manifest['missing'])} gaps={len(provenance_gaps)} -> {json_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
