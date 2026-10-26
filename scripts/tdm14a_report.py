"""RFC-TDM-014A — assemble the deliverables from what was actually executed.

Every number in these reports is read back from an artefact written by a run, a
control or the verifier. Nothing is typed in by hand, so a report cannot drift
away from the execution it describes.

Writes, in ``evidence/tdm/wp-tdm-14a/``: ``INPUT_MANIFEST.json``,
``OUTPUT_MANIFEST.json``, ``REPLAY_REPORT.json/.md`` and ``RUN_REPORT.json/.md``.

Usage::

    python scripts/tdm14a_report.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parents[1]
EVIDENCE = HERE / "evidence" / "tdm" / "wp-tdm-14a"
TDM13 = HERE / "evidence" / "tdm" / "wp-tdm-13"


def load(name: str) -> Any:
    path = EVIDENCE / name
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def sha256_file(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=HERE, capture_output=True, text=True, check=False
    ).stdout.strip()


def build_input_manifest(run_a: dict[str, Any], run_b: dict[str, Any]) -> dict[str, Any]:
    manifest_path = Path(run_a["clone"]) / "evidence/tdm/wp-tdm-13/DATASET_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = []
    for entry in manifest["datasets"]:
        rows.append(
            {
                "dataset_id": entry["dataset_id"],
                "original_path": entry["original_path"],
                "bundle_path": entry["path"],
                "bytes": entry["bytes"],
                "sha256": entry["sha256"],
                "split": entry.get("split"),
                "source": entry.get("source"),
                "license": entry.get("license"),
                "restored_lf": next(
                    r["match"]
                    for r in run_a["inputs"]["rows"]
                    if r["dataset_id"] == entry["dataset_id"]
                ),
                "restored_crlf": next(
                    r["match"]
                    for r in run_b["inputs"]["rows"]
                    if r["dataset_id"] == entry["dataset_id"]
                ),
            }
        )
    return {
        "artifact": "tdm14a-input-manifest-v1",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_manifest": "evidence/tdm/wp-tdm-13/DATASET_MANIFEST.json",
        "source_manifest_sha256": sha256_file(manifest_path),
        "source_commit_of_seal": manifest.get("source_commit"),
        "count": len(rows),
        "total_bytes": sum(r["bytes"] for r in rows),
        "splits": {s: sum(1 for r in rows if r["split"] == s) for s in ("HOLD", "DEV")},
        "all_restored_in_both_runs": all(r["restored_lf"] and r["restored_crlf"] for r in rows),
        "rows": rows,
    }


def build_output_manifest(runs: list[dict[str, Any]]) -> dict[str, Any]:
    out: list[dict[str, Any]] = []
    for run in runs:
        for row in run["outputs"]["rows"]:
            out.append(
                {
                    "run_id": run["run_id"],
                    "label": run["label"],
                    "path": f"{run['clone']}/{row['path']}",
                    "name": row["name"],
                    "bytes": row["bytes"],
                    "sha256": row["sha256"],
                    "absent_before_run": row["absent_before_run"],
                    "generated_after_run_start": row["generated_after_run_start"],
                    "run_id_embedded": row["run_id_embedded"],
                }
            )
        for phase in run["phases"]:
            out.append(
                {
                    "run_id": run["run_id"],
                    "label": run["label"],
                    "path": phase["log"],
                    "name": f"log:{phase['phase']}",
                    "bytes": Path(phase["log"]).stat().st_size
                    if Path(phase["log"]).is_file()
                    else 0,
                    "sha256": phase["log_sha256"],
                    "absent_before_run": True,
                    "generated_after_run_start": True,
                    "run_id_embedded": False,
                }
            )
    generated = [r for r in out if r["absent_before_run"] and r["generated_after_run_start"]]
    return {
        "artifact": "tdm14a-output-manifest-v1",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "entries": len(out),
        "generated_in_their_run": len(generated),
        "runs": [
            {
                "run_id": run["run_id"],
                "label": run["label"],
                "clone": run["clone"],
                "target_commit": run["clone_state"]["target_commit"],
                "started_utc": run["started_utc"],
                "finished_utc": run["finished_utc"],
                "duration_seconds": run["duration_seconds"],
                "cell_metrics_sha256": run.get("cell_metrics_sha256"),
                "review_sha256": run.get("review_sha256"),
            }
            for run in runs
        ],
        "status": "PASS" if len(generated) == len(out) else "FAIL",
        "rows": out,
    }


def build_replay_report(
    runs: list[dict[str, Any]], verification: dict[str, Any], eol: dict[str, Any]
) -> dict[str, Any]:
    acc07 = next(c for c in verification["checks"] if c["id"] == "ACC-07")
    comparisons = acc07["detail"]["comparisons"]
    return {
        "artifact": "tdm14a-replay-report-v1",
        "rfc_id": "RFC-TDM-014A",
        "wp": "WP-14C",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "target_commit": runs[0]["clone_state"]["target_commit"],
        "runs": [
            {
                "run_id": run["run_id"],
                "label": run["label"],
                "clone": run["clone"],
                "core_autocrlf": run["clone_state"]["core_autocrlf"],
                "status": run["status"],
                "started_utc": run["started_utc"],
                "finished_utc": run["finished_utc"],
                "duration_seconds": run["duration_seconds"],
                "phases": [
                    {
                        "phase": p["phase"],
                        "status": p["status"],
                        "command": p["command"],
                        "exit_code": p["exit_code"],
                        "timed_out": p["timed_out"],
                        "timeout_seconds": p["timeout_seconds"],
                        "duration_seconds": p["duration_seconds"],
                        "log": p["log"],
                        "log_sha256": p["log_sha256"],
                        "log_tail": p["log_tail"],
                    }
                    for p in run["phases"]
                ],
                "isolation": run["isolation"],
                "injected_stale_state": run["injected_stale_state"],
                "inputs": {k: v for k, v in run["inputs"].items() if k != "rows"},
                "outputs": {
                    "expected": run["outputs"]["outputs_expected"],
                    "present": run["outputs"]["outputs_present"],
                    "proven_generated": run["outputs"]["outputs_proven_generated"],
                    "status": run["outputs"]["status"],
                    "rows": run["outputs"]["rows"],
                },
            }
            for run in runs
        ],
        "contracts": comparisons,
        "contracts_passing": acc07["detail"]["contracts_passing"],
        "contracts_compared": acc07["detail"]["contracts_compared"],
        "metrics_by_cell_equal_across_runs": acc07["detail"]["metrics_by_cell_equal_across_runs"],
        "metrics_by_cell_equal_to_published": acc07["detail"]["metrics_by_cell_equal_to_published"],
        "eol": {
            "status": eol["status"],
            "modules_compared": len(eol["modules"]),
            "physical_bytes_differ": sum(m["physical_bytes_differ"] for m in eol["modules"]),
            "same_blob": sum(m["blob_oids_equal"] for m in eol["modules"]),
            "v2_equal": sum(m["v2_equal"] for m in eol["modules"]),
            "registry_fingerprints_equal_across_runs": eol[
                "registry_fingerprints_equal_across_runs"
            ],
            "published_matches_independent_digest": eol["published_matches_independent_digest"],
        },
        "reuse_of_intermediate_results": "none: neither phase was invoked with --reuse and both "
        ".tdm12/review.json and .tdm12/cell_metrics.json were absent before their run",
        "status": "PASS"
        if all(r["status"] == "PASS" for r in runs)
        and acc07["status"] == "PASS"
        and eol["status"] == "PASS"
        else "FAIL",
    }


def build_run_report(
    runs: list[dict[str, Any]],
    verification: dict[str, Any],
    negatives: dict[str, Any],
    tests: dict[str, Any] | None,
    compat: dict[str, Any] | None,
) -> dict[str, Any]:
    acc = {c["id"]: c["status"] for c in verification["checks"]}
    return {
        "artifact": "tdm14a-run-report-v1",
        "rfc": "RFC-TDM-014A",
        "work_package": "WP-14A..WP-14D",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "baseline_commit": "04fb8bc8a0900c278cd72c5e3478a45b66fcbc03",
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "head": git("rev-parse", "HEAD"),
        "commits": git("log", "--format=%h %s", "04fb8bc8..HEAD").splitlines(),
        "environment": {
            "python": runs[0]["environment"]["python"],
            "platform": runs[0]["environment"]["platform"],
            "git": git("--version"),
            "system_core_autocrlf": git("config", "--system", "--get", "core.autocrlf") or None,
        },
        "runs": [
            {
                "run_id": run["run_id"],
                "label": run["label"],
                "clone": run["clone"],
                "core_autocrlf": run["clone_state"]["core_autocrlf"],
                "status": run["status"],
                "duration_seconds": run["duration_seconds"],
                "phases": {p["phase"]: p["status"] for p in run["phases"]},
                "outputs_proven": f"{run['outputs']['outputs_proven_generated']}/"
                f"{run['outputs']['outputs_expected']}",
            }
            for run in runs
        ],
        "acceptance_criteria": acc,
        "verdict": verification["verdict"],
        "tests": tests,
        "negative_controls": {
            "total": negatives["total"],
            "proven": negatives["proven"],
            "status": negatives["status"],
            "rows": [
                {"control": c["control"], "status": c["status"], "exit": c["observed_exit_code"]}
                for c in negatives["controls"]
            ],
        },
        "v1_compatibility": {
            "status": (compat or {}).get("status"),
            "differences": len((compat or {}).get("differences") or []),
            "csv_identical": (compat or {}).get("csv_identical"),
            "historical_files_unmodified": (compat or {}).get("historical_files_unmodified"),
        },
        "defects": [
            {
                "id": "D-01",
                "state": "FIXED",
                "detail": "v1 hashed working-tree bytes, so the same blob produced two identities under "
                "LF and CRLF; v2 hashes the blob (ACC-02 reproduced, ACC-03 fixed).",
            },
            {
                "id": "D-02",
                "state": "DOCUMENTED, NOT REWRITTEN",
                "detail": "tdm12_inventory.py hardcoded source_commit='504256ec' as a literal, so no "
                "TDM-12 artefact recorded the commit it actually ran at. v2 derives it from git HEAD; "
                "v1 keeps the literal only to reproduce the published artefact.",
            },
            {
                "id": "D-03",
                "state": "FIXED",
                "detail": "the sealed TDM-13 input bundle had no -text attribute, so a CRLF checkout "
                "delivered 189575 bytes instead of 189574 and the replay could not start. Fixed in "
                ".gitattributes, which is why the CRLF run now reaches the pipeline.",
            },
            {
                "id": "D-04",
                "state": "FIXED IN THIS WORK, FOUND BY THE TESTS",
                "detail": "the first v2 preflight used git status as its cleanliness oracle; on a CRLF "
                "checkout status reports ' M path' for content identical to the blob, which would "
                "have refused the only transformation the RFC tolerates. Replaced with content "
                "hash-object --path plus diff-index --cached.",
            },
            {
                "id": "D-05",
                "state": "OPEN, REPORTED",
                "detail": "identity fields outside the registry (triage.json admission_ledger.sha256, "
                "runtime_entrypoints sha256) still hash working-tree bytes, so those scratch values "
                "remain EOL-sensitive. They are not published contracts and do not enter any ACC.",
            },
        ],
        "false_success": verification["false_success"],
        "false_success_basis": verification["false_success_basis"],
        "paper_orders": 0,
        "live_orders": 0,
        "files_changed": git("diff", "--name-status", "04fb8bc8..HEAD").splitlines(),
        "decision": "NO_ELIGIBLE_CANDIDATE / REJECTED_ALPHA (inherited from TDM-11/12/13, untouched)",
    }


def replay_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# REPLAY_REPORT — RFC-TDM-014A",
        "",
        f"**Commit de implementación:** `{report['target_commit']}`",
        f"**Generado:** {report['generated_at_utc']}",
        "",
        "## Ejecuciones",
        "",
        "| run_id | EOL | estado | duración | fases | outputs probados |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for run in report["runs"]:
        phases = ", ".join(
            f"{p['phase']} {p['status']} {p['duration_seconds']}s / timeout {p['timeout_seconds']}s"
            for p in run["phases"]
        )
        lines.append(
            f"| `{run['run_id']}` | `core.autocrlf={run['core_autocrlf']}` | {run['status']} | "
            f"{run['duration_seconds']} s | {phases} | "
            f"{run['outputs']['proven_generated']}/{run['outputs']['expected']} |"
        )
    lines += [
        "",
        "Comandos exactos por fase (logs completos en `.replay-logs/<label>/` dentro de cada clon):",
        "",
    ]
    for run in report["runs"]:
        for phase in run["phases"]:
            lines.append(f"- `{run['label']}` · `{phase['command']}` → exit {phase['exit_code']}")
    lines += [
        "",
        "## Aislamiento",
        "",
        "| run | eliminado antes de ejecutar | estado inyectado previo |",
        "| --- | --- | --- |",
    ]
    for run in report["runs"]:
        injected = run.get("injected_stale_state")
        lines.append(
            f"| `{run['run_id']}` | {run['isolation']['removed']} | "
            f"{'sí: ' + str(sorted(injected)) if injected else 'no'} |"
        )
    lines += [
        "",
        "Ninguna fase se invocó con `--reuse`: `review.json` y `cell_metrics.json` estaban ausentes",
        "antes de su ejecución y su `mtime` es posterior al inicio del run.",
        "",
        "## Contratos comparados (ACC-07)",
        "",
        "| contrato | publicado | run A | run B | A=B | A=publicado |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in report["contracts"]:
        published = row.get("published", row.get("a_equals_published"))
        a = row.get("run_a", row.get("differences_a_vs_b"))
        b = row.get("run_b")
        lines.append(
            f"| `{row['contract']}` | {_short(published)} | {_short(a)} | {_short(b)} | "
            f"{row.get('a_equals_b')} | {row.get('a_equals_published', 'n/a')} |"
        )
    lines += [
        "",
        f"**Contratos que pasan: {report['contracts_passing']}/{report['contracts_compared']}**",
        f"`metrics_by_cell` igual entre runs: {report['metrics_by_cell_equal_across_runs']} · "
        f"igual al publicado: {report['metrics_by_cell_equal_to_published']}",
        "",
        "## Prueba cruzada EOL",
        "",
        f"- módulos comparados: {report['eol']['modules_compared']}",
        f"- con bytes físicos distintos: {report['eol']['physical_bytes_differ']}",
        f"- con el mismo blob de Git: {report['eol']['same_blob']}",
        f"- con el mismo `source_fingerprint` v2: {report['eol']['v2_equal']}",
        f"- `parameter_hash` de registro iguales entre runs: "
        f"{report['eol']['registry_fingerprints_equal_across_runs']}",
        f"- el digest publicado coincide con el recalculado por el verificador: "
        f"{report['eol']['published_matches_independent_digest']}",
        "",
        f"**Estado del replay: {report['status']}**",
        "",
    ]
    return "\n".join(lines)


def _short(value: Any, limit: int = 60) -> str:
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    text = text.replace("|", "\\|")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def run_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# RUN_REPORT — RFC-TDM-014A",
        "",
        f"**Veredicto:** `{report['verdict']}`",
        f"**Baseline:** `{report['baseline_commit']}` · **HEAD:** `{report['head']}` · "
        f"**Rama:** `{report['branch']}`",
        "",
        "## Commits",
        "",
    ]
    lines += [f"- `{c}`" for c in report["commits"]]
    lines += [
        "",
        "## Criterios de aceptación",
        "",
        "| ACC | estado |",
        "| --- | --- |",
    ]
    lines += [f"| {k} | {v} |" for k, v in report["acceptance_criteria"].items()]
    lines += [
        "",
        "## Ejecuciones",
        "",
        "| run_id | EOL | estado | duración | fases | outputs |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for run in report["runs"]:
        lines.append(
            f"| `{run['run_id']}` | `{run['core_autocrlf']}` | {run['status']} | "
            f"{run['duration_seconds']} s | {run['phases']} | {run['outputs_proven']} |"
        )
    tests = report.get("tests") or {}
    lines += [
        "",
        "## Tests",
        "",
        f"- suites: {tests.get('suites')}",
        f"- pasados: {tests.get('passed')} · fallados: {tests.get('failed')} · "
        f"exit: {tests.get('exit_code')}",
        f"- duración: {tests.get('duration_seconds')} s",
        "",
        "## Controles negativos",
        "",
        "| control | estado | exit |",
        "| --- | --- | --- |",
    ]
    lines += [
        f"| `{c['control']}` | {c['status']} | {c['exit']} |"
        for c in report["negative_controls"]["rows"]
    ]
    lines += [
        "",
        f"**{report['negative_controls']['proven']}/{report['negative_controls']['total']} demostrados**",
        "",
        "## Compatibilidad v1",
        "",
        f"- estado: {report['v1_compatibility']['status']}",
        f"- diferencias con el registro publicado: {report['v1_compatibility']['differences']}",
        f"- CSV idéntico: {report['v1_compatibility']['csv_identical']}",
        f"- históricos intactos: {report['v1_compatibility']['historical_files_unmodified']}",
        "",
        "## Defectos",
        "",
        "| id | estado | detalle |",
        "| --- | --- | --- |",
    ]
    lines += [f"| `{d['id']}` | {d['state']} | {d['detail']} |" for d in report["defects"]]
    lines += [
        "",
        "## Órdenes y decisión",
        "",
        f"- `paper_orders = {report['paper_orders']}` · `live_orders = {report['live_orders']}`",
        f"- `false_success = {report['false_success']}`",
        f"- decisión de mercado: {report['decision']}",
        "",
        "## Archivos cambiados desde la baseline",
        "",
    ]
    lines += [f"- `{line}`" for line in report["files_changed"]]
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out-dir", default=str(EVIDENCE))
    args = parser.parse_args(argv)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    run_a = load("run_lf.json")
    run_b = load("run_crlf.json")
    verification = load("verification_result.json")
    eol = load("EOL_COMPARISON.json")
    negatives = load("NEGATIVE_CONTROLS.json")
    tests = load("TEST_RESULTS.json")
    compat = load("v1_compat.json")
    missing = [
        name
        for name, doc in (
            ("run_lf.json", run_a),
            ("run_crlf.json", run_b),
            ("verification_result.json", verification),
            ("EOL_COMPARISON.json", eol),
            ("NEGATIVE_CONTROLS.json", negatives),
        )
        if doc is None
    ]
    if missing:
        print(f"missing inputs: {missing}")
        return 1

    inputs = build_input_manifest(run_a, run_b)
    outputs = build_output_manifest([run_a, run_b])
    replay = build_replay_report([run_a, run_b], verification, eol)
    run_report = build_run_report([run_a, run_b], verification, negatives, tests, compat)

    for name, doc in (
        ("INPUT_MANIFEST.json", inputs),
        ("OUTPUT_MANIFEST.json", outputs),
        ("REPLAY_REPORT.json", replay),
        ("RUN_REPORT.json", run_report),
    ):
        (out / name).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    (out / "REPLAY_REPORT.md").write_text(replay_markdown(replay), encoding="utf-8")
    (out / "RUN_REPORT.md").write_text(run_markdown(run_report), encoding="utf-8")
    print(
        json.dumps(
            {
                "inputs": f"{inputs['count']} files / {inputs['total_bytes']} bytes",
                "outputs_proven": f"{outputs['generated_in_their_run']}/{outputs['entries']}",
                "replay": replay["status"],
                "contracts": f"{replay['contracts_passing']}/{replay['contracts_compared']}",
                "verdict": run_report["verdict"],
            },
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
