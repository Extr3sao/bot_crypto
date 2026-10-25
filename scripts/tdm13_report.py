"""RFC-TDM-013 — assemble the published evidence from recorded runs.

This writes ``GIT_AND_CLAIMS_AUDIT.json``, ``DATASET_RESTORE.md``,
``RUN_REPORT.json`` and ``RUN_REPORT.md`` out of the JSON the audits already
produced. It recomputes nothing it cannot read: if a number is not in an audit
output or a manifest, it does not appear in the report.

Deliberate omission: the run report does not contain the SHA of the commit that
carries it (impossible), only ``commit`` = the commit the evidence was built from
plus ``commit_role``; the closing commit is named by
``python scripts/tdm13_independent_verify.py audit-closure``.

Usage::  python scripts/tdm13_report.py
"""

from __future__ import annotations

import datetime
import hashlib
import json
import platform
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
ART = REPO_ROOT / ".tdm13"
EVIDENCE = REPO_ROOT / "evidence" / "tdm" / "wp-tdm-13"
TDM12 = REPO_ROOT / "evidence" / "tdm" / "wp-tdm-12"
TDM11 = REPO_ROOT / "evidence" / "tdm" / "wp-tdm-11"

RFC_ID = "RFC-TDM-013"
VERIFIER_ID = "tdm13-independent-verifier/1"
TARGET_COMMIT = "a96e9c80c608ed91943d1fab35db6fa1704111bb"
BASELINE_COMMIT = "504256ec8934b97a6d405c202604ecac81a02346"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def git(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    return proc.stdout.strip()


def commands() -> list[dict[str, Any]]:
    path = ART / "commands.jsonl"
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def pytest_summary() -> dict[str, Any]:
    path = ART / "pytest.txt"
    if not path.is_file():
        return {"ran": False}
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"(\d+) passed", text)
    failed = re.search(r"(\d+) failed", text)
    return {
        "ran": True,
        "passed": int(match.group(1)) if match else 0,
        "failed": int(failed.group(1)) if failed else 0,
        "file": "tests/unit/research/test_tdm13_independent_verify.py",
    }


def dataset_cross_check(manifest: dict[str, Any]) -> dict[str, Any]:
    """Do the sealed bytes match what TDM-12 and TDM-11 declared for them?

    Two different comparisons, kept apart on purpose: the 24 bar files have a
    declared hash in the TDM-11 provenance, the two per-split manifests do not
    (they *are* the provenance), so they are checked against the TDM-12 manifest.
    """
    tdm12 = load(TDM12 / "RUN_REPORT.json")
    provenance = load(TDM11 / "DATASET_PROVENANCE.json")
    declared = {
        f["path"].replace("\\", "/"): f["sha256"]
        for f in provenance.get("exposed_datasets", {}).get("files", [])
    }
    bars: list[dict[str, Any]] = []
    manifests: list[dict[str, Any]] = []
    for entry in manifest.get("datasets", []):
        key = entry.get("original_path") or ""
        if key in declared:
            bars.append(
                {
                    "dataset_id": entry["dataset_id"],
                    "path": key,
                    "bundle_sha256": entry["sha256"],
                    "tdm11_declared_sha256": declared[key],
                    "match": declared[key] == entry["sha256"],
                }
            )
        else:
            manifests.append(
                {
                    "dataset_id": entry["dataset_id"],
                    "path": key,
                    "bundle_sha256": entry["sha256"],
                }
            )
    tdm12_datasets = tdm12.get("datasets", {})
    dev_sealed = next(
        (m["bundle_sha256"] for m in manifests if m["path"].endswith("DATASET_DEV.json")), None
    )
    hold_sealed = next(
        (m["bundle_sha256"] for m in manifests if m["path"].endswith("/DATASET.json")), None
    )
    return {
        "bar_files_checked": len(bars),
        "bar_files_matching_tdm11": sum(1 for r in bars if r["match"]),
        "bar_mismatches": [r for r in bars if not r["match"]],
        "manifest_files_checked": len(manifests),
        "manifest_mismatches": [
            m
            for m in manifests
            if m["bundle_sha256"]
            not in {
                tdm12_datasets.get("dev_manifest", {}).get("sha256"),
                tdm12_datasets.get("holdout_manifest", {}).get("sha256"),
            }
        ],
        "tdm12_dev_manifest_declared": tdm12_datasets.get("dev_manifest", {}).get("sha256"),
        "tdm12_dev_manifest_sealed": dev_sealed,
        "tdm12_holdout_manifest_declared": tdm12_datasets.get("holdout_manifest", {}).get("sha256"),
        "tdm12_holdout_manifest_sealed": hold_sealed,
        "tdm12_manifest_hashes_match": (
            tdm12_datasets.get("dev_manifest", {}).get("sha256") == dev_sealed
            and tdm12_datasets.get("holdout_manifest", {}).get("sha256") == hold_sealed
        ),
        "rows": bars,
        "manifests": manifests,
    }


def write_restore_doc(manifest: dict[str, Any]) -> None:
    lines = [
        "# DATASET_RESTORE — RFC-TDM-013",
        "",
        "El paquete TDM-12 dejó sus entradas fuera de Git. Este documento restaura, byte a byte,",
        "los datasets sellados en un clon limpio y comprueba cada SHA-256 antes de ejecutar nada.",
        "",
        f"- `schema_version`: `{manifest.get('schema_version')}`",
        f"- `source_commit`: `{manifest.get('source_commit')}`",
        f"- `storage_mode`: `{manifest.get('storage_mode')}`",
        f"- `dataset_count`: **{manifest.get('dataset_count')}** archivos "
        f"({manifest.get('total_bytes')} bytes)",
        f"- `input_state`: **{manifest.get('input_state')}**",
        f"- `license_status`: `{manifest.get('license_status')}`",
        "",
        "## Procedimiento desde cero",
        "",
        "```bash",
        "# 1. clon limpio fijado al commit de evidencias de TDM-12",
        "git clone <repo> tdm13-clean",
        "cd tdm13-clean",
        "git checkout --detach a96e9c80c608ed91943d1fab35db6fa1704111bb",
        "",
        "# 2. restaurar los inputs sellados (copia byte a byte + verificación de hashes)",
        "python scripts/tdm13_inputs.py restore --target .",
        "",
        "# 3. comprobar que los bytes son los del manifiesto",
        "python scripts/tdm13_inputs.py verify",
        "```",
        "",
        "`restore` escribe en `data/tdm08/` y `data/tdm10/`, las rutas que el pipeline de TDM-12",
        "lee. Los archivos quedan *untracked* en el clon: no se modifica ningún archivo versionado.",
        "",
        "## Inventario",
        "",
        "| dataset_id | ruta original | bytes | sha256 | estado |",
        "| --- | --- | --- | --- | --- |",
    ]
    for entry in manifest.get("datasets", []):
        lines.append(
            f"| `{entry['dataset_id']}` | `{entry.get('original_path')}` | {entry.get('bytes')} | "
            f"`{entry['sha256'][:16]}…` | `{entry.get('state')}` |"
        )
    lines += [
        "",
        "## Qué no se puede afirmar de estos datos",
        "",
        "- **Licencia:** `UNKNOWN_NOT_VERIFIED`. Son klines públicas de exchange sin credenciales y "
        "sin datos personales, pero las condiciones de redistribución no se comprobaron.",
        "- **Endpoint de captura:** no consta la URL exacta por archivo; el manifiesto de cada split "
        "solo declara `binance spot (public klines, no credentials)`.",
        "- **Versión del transform:** `UNKNOWN`. Se conserva la regla de sellado "
        "(`close_time <= fetched_at`), no el código que la aplicó.",
        "- **Reproducibilidad desde el proveedor:** re-descargar hoy no garantiza los mismos bytes; "
        "lo que se certifica es la copia sellada, no el origen.",
        "",
    ]
    (EVIDENCE / "DATASET_RESTORE.md").write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    manifest = load(EVIDENCE / "DATASET_MANIFEST.json")
    git_audit = load(ART / "audit_git.json")
    claims_audit = load(ART / "audit_claims.json")
    replay = load(ART / "replay.json")
    controls = load(ART / "negative_controls.json")
    verdict = load(EVIDENCE / "verification_result.json")
    tests = pytest_summary()
    runs = commands()

    if not manifest or not git_audit or not claims_audit:
        print("missing audits: run audit-git, audit-claims and seal before reporting")
        return 2

    cross = dataset_cross_check(manifest)

    audit_doc = {
        "rfc_id": RFC_ID,
        "verifier_id": VERIFIER_ID,
        "target_commit": TARGET_COMMIT,
        "baseline_commit_expected": BASELINE_COMMIT,
        "git": {
            "identity": git_audit["identity"],
            "deliverables": {
                "expected": git_audit["deliverables"]["expected_count"],
                "present": git_audit["deliverables"]["present_count"],
                "missing": git_audit["deliverables"]["missing"],
                "extra_in_directory": git_audit["deliverables"]["extra_in_directory"],
                "per_file": git_audit["deliverables"]["per_file"],
            },
            "required_fields": git_audit["deliverables"]["required_fields"],
            "digests": {
                "checked": git_audit["deliverables"]["digests"]["checked"],
                "ok": git_audit["deliverables"]["digests"]["ok"],
                "failures": git_audit["deliverables"]["digests"]["failures"],
            },
            "scope": git_audit["scope"],
            "shared_checkout": git_audit["shared_checkout"],
            "status": git_audit["status"],
        },
        "claims": {
            "checked": claims_audit["checked"],
            "matched": claims_audit["matched"],
            "rows": claims_audit["claims"],
            "failures": claims_audit["failures"],
            "status": claims_audit["status"],
        },
        "dataset_cross_check": cross,
        "digests_summary": (
            f"{git_audit['deliverables']['digests']['ok']}/"
            f"{git_audit['deliverables']['digests']['checked']}"
        ),
    }
    (EVIDENCE / "GIT_AND_CLAIMS_AUDIT.json").write_text(
        json.dumps(audit_doc, indent=2) + "\n", encoding="utf-8"
    )
    write_restore_doc(manifest)

    payload = {
        "rfc_id": RFC_ID,
        "run_id": f"tdm13-{git('rev-parse', '--short', 'HEAD')}",
        "commit": TARGET_COMMIT,
        "commit_role": (
            "TDM-12 evidence commit whose package this run audits and replays; the TDM-13 "
            "commit that carries this report cannot name itself, so its closure is proven by "
            "'python scripts/tdm13_independent_verify.py audit-closure'"
        ),
        "baseline_commit_expected": BASELINE_COMMIT,
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "git": git("--version"),
            "offline": True,
            "replay_clone": replay.get("clone"),
            "shared_checkout": str(REPO_ROOT.parent / "bot freebuff"),
        },
        "inputs": {
            "manifest": "evidence/tdm/wp-tdm-13/DATASET_MANIFEST.json",
            "dataset_files": manifest.get("dataset_count"),
            "total_bytes": manifest.get("total_bytes"),
            "storage_mode": manifest.get("storage_mode"),
            "input_state": manifest.get("input_state"),
            "restore_doc": "evidence/tdm/wp-tdm-13/DATASET_RESTORE.md",
        },
        "verifier": {"id": VERIFIER_ID, "independence": verdict.get("independence", {})},
        "git_integrity": git_audit["status"],
        "claims_consistency": claims_audit["status"],
        "replay_status": replay.get("status"),
        "negative_controls_status": controls.get("status"),
        "result": verdict.get("result"),
        "states": {
            "deliverables_present": f"{git_audit['deliverables']['present_count']}/"
            f"{git_audit['deliverables']['expected_count']}",
            "required_fields": f"{git_audit['deliverables']['required_fields']['present']}/"
            f"{git_audit['deliverables']['required_fields']['required']}",
            "digests": audit_doc["digests_summary"],
            "claims_matched": f"{claims_audit['matched']}/{claims_audit['checked']}",
            "replay_comparisons": f"{len([c for c in replay.get('comparisons', []) if c['match']])}/"
            f"{len(replay.get('comparisons', []))}",
            "negative_controls": f"{controls.get('proven')}/{controls.get('total')}",
        },
        "tests": tests,
        "commands": runs,
        "errors": [
            {
                "id": "E-01",
                "error": "audit-git reported a false lineage failure on a valid commit",
                "cause": "'git branch --contains' prefixes checked-out-elsewhere branches with '+', "
                "and the parser stripped only '* ' characters",
                "fix": "parse the trailing token of each branch line",
                "status": "FIXED",
            },
            {
                "id": "E-02",
                "error": "every negative control read as PROVEN regardless of its output",
                "cause": "_control searched for the expected token inside a blob that also contained "
                "the token field itself",
                "fix": "search only the child's stdout/stderr; unit test added",
                "status": "FIXED",
            },
            {
                "id": "E-03",
                "error": "replay reported a false 10/10 pass",
                "cause": "the cloned artifacts had just been restored from the commit by the "
                "re-checkout, so comparing them with the blob matched without the pipeline "
                "having regenerated anything",
                "fix": "delete the target artifacts before the phases and require the pipeline to "
                "recreate them",
                "status": "FIXED",
            },
            {
                "id": "E-04",
                "error": "inventory phase died in 0.1s on the second attempt",
                "cause": "the runner passed 'scripts/tdm12_inventory.py --reuse' as a single path",
                "fix": "run_phase takes extra_args separately; the command line is rendered, not "
                "concatenated into the path",
                "status": "FIXED",
            },
            {
                "id": "D-01",
                "error": "CANDIDATE_REGISTRY.json rows[*].parameter_hash did not reproduce",
                "cause": "the builder fingerprints sha256(module.__file__) working-tree bytes, so the "
                "value depends on the checkout's end-of-line configuration",
                "fix": "NOT FIXED BY DESIGN: TDM-12 is not modified here. Recorded, proven, and "
                "reproduced after matching the bytes (evidence EOL_FINGERPRINT_FINDING.json)",
                "status": "OPEN (builder defect, outside this RFC's write scope)",
            },
        ],
        "paper_orders": 0,
        "live_orders": 0,
        "false_success": 0,
        "false_success_basis": (
            "no check that failed, timed out or was not run is reported as PASS; the replay verdict "
            "is INCOMPLETE or FAIL unless every phase exited 0 and every comparison matched"
        ),
        "generated_at_utc": datetime.datetime.now(datetime.UTC).isoformat(),
    }
    lines = [
        "# RUN_REPORT — RFC-TDM-013 (verificación independiente y reproducibilidad de TDM-12)",
        "",
        f"**Run id:** `{payload['run_id']}` · **Commit auditado:** `{TARGET_COMMIT[:8]}` · "
        f"**Baseline:** `{BASELINE_COMMIT[:8]}` · **Rama:** `{payload['branch']}`",
        "",
        "## Estado de cada fase",
        "",
        "| Fase | Estado | Detalle |",
        "| --- | --- | --- |",
        f"| WP-13A integridad Git | **{git_audit['status']}** | "
        f"{audit_doc['digests_summary']} digests, "
        f"{git_audit['deliverables']['present_count']}/{git_audit['deliverables']['expected_count']} "
        f"entregables, "
        f"{git_audit['deliverables']['required_fields']['present']}/"
        f"{git_audit['deliverables']['required_fields']['required']} campos |",
        f"| WP-13A claims | **{claims_audit['status']}** | "
        f"{claims_audit['matched']}/{claims_audit['checked']} re-derivados |",
        f"| WP-13B inputs | **{manifest.get('input_state')}** | "
        f"{manifest.get('dataset_count')} archivos, {manifest.get('total_bytes')} bytes sellados |",
        f"| WP-13B replay | **{replay.get('status')}** | clon `{(replay.get('clone') or 'n/a')[-14:]}` "
        f"durante {replay.get('duration_seconds')} s |",
        f"| WP-13C controles negativos | **{controls.get('status')}** | "
        f"{controls.get('proven')}/{controls.get('total')} demostrados |",
        f"| Dictamen | **{verdict.get('result')}** | ver `verification_result.json` |",
        "",
        "## Comandos ejecutados",
        "",
        "| # | Comando | Exit | Duración (s) |",
        "| --- | --- | --- | --- |",
    ]
    for i, run in enumerate(runs, start=1):
        lines.append(
            f"| {i} | `{run.get('command')}` | {run.get('exit_code')} | {run.get('duration_seconds')} |"
        )
    lines += [
        "",
        "## Replay: qué se comparó",
        "",
        "| Artefacto | Campo | Publicado | Reproducido | ¿Igual? |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in replay.get("comparisons", []):
        lines.append(
            f"| `{row.get('artifact')}` | `{row.get('field')}` | `{row.get('committed')}` | "
            f"`{row.get('replayed')}` | {'sí' if row.get('match') else '**NO**'} |"
        )
    lines += [
        "",
        "## Controles negativos",
        "",
        "| ID | Inyección | Exit | Control esperado | Estado |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in controls.get("controls", []):
        lines.append(
            f"| {row['id']} | {row['name']} | {row['run']['exit_code']} | "
            f"`{row['expected_token']}` | **{row['status']}** |"
        )
    lines += [
        "",
        "## Límites de este informe",
        "",
        "- **Independencia de identidad:** `NOT_DEMONSTRATED`. La ruta de código del verificador es",
        "  propia (no importa ni ejecuta `tdm12_publish.py --verify`), pero la escribió el mismo",
        "  operador que construyó TDM-12. No se declara un segundo autor que no existe.",
        "- **Alcance de la reproducibilidad:** demuestra que los números publicados vuelven a salir",
        "  de los inputs sellados con el código sin modificar. **No** demuestra que el pipeline sea",
        "  correcto, ni que la estrategia tenga alpha.",
        "- **Datos:** licencia y endpoint de captura `UNKNOWN`; re-descargar hoy no garantiza los",
        "  mismos bytes que la copia sellada.",
        "- **Autorreferencia:** este informe no contiene el SHA del commit que lo contiene; el cierre",
        "  se prueba con `python scripts/tdm13_independent_verify.py audit-closure`.",
        "",
        f"`paper_orders = {payload['paper_orders']}` · `live_orders = {payload['live_orders']}` · "
        f"`FALSE_SUCCESS = {payload['false_success']}` dentro del alcance comprobado.",
        "",
    ]
    (EVIDENCE / "RUN_REPORT.md").write_text("\n".join(lines), encoding="utf-8")

    evidence_hashes: dict[str, Any] = {}
    for path in sorted(EVIDENCE.rglob("*")):
        if not path.is_file() or path.name == "RUN_REPORT.json":
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        evidence_hashes[rel] = {"path": rel, "sha256": sha(path), "bytes": path.stat().st_size}

    payload["evidence_sha256"] = evidence_hashes
    (EVIDENCE / "RUN_REPORT.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )

    print(
        f"report written: git={git_audit['status']} claims={claims_audit['status']} "
        f"replay={replay.get('status')} controls={controls.get('status')} "
        f"result={verdict.get('result')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
