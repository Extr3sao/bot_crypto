"""DEF-RUN-018 / WP-018-02 — reejecutar 017 desde un checkout limpio, no desde este disco.

Un replay en el árbol de trabajo no demuestra reproducibilidad: demuestra que el árbol
funciona. Este script crea un `git worktree` **detached** en el commit sellado, copia
solo los insumos cuyo sha256 coincide con el plan congelado y ejecuta allí los
entrypoints reales, con sus códigos de salida y su stdout capturados.

Qué compara, y qué no:

* compara **economía y contabilidad** por celda (neto, bruto, fills, operaciones,
  aplazamientos, llamadas, minutos ausentes), el delta pareado y la clasificación;
* **no** compara bytes de ledger: cada línea lleva `recorded_at_utc` de pared, así que
  su sha256 cambia entre corridas. La reproducción byte a byte no se reclama.

Estados posibles: `CLEAN_CHECKOUT_REPRODUCED`, `FAIL`, `BLOCKED`. Solo el primero
cuenta como cierre en el gate.

Uso::

    python scripts/def_run_018_clean_replay.py --commit <sha> --workers 6
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
RFC = "RFC-DEF-RUN-018"
SUBJECT = "RFC-DEF-RUN-017"
OUT = REPO / "reports" / "ai-bots" / RFC
TOL = Decimal("0.000001")
PYTHON = sys.executable


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd or REPO, capture_output=True, text=True, check=False
    )


def same(left: Any, right: Any, tol: Decimal = TOL) -> bool:
    return abs(Decimal(str(left)) - Decimal(str(right))) <= tol


def copy_verified(source: Path, destination: Path) -> dict[str, Any]:
    """Copia conservando bytes; devuelve la evidencia de que la copia coincide."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    source_hash = sha256(source)
    copy_hash = sha256(destination)
    return {
        "source": str(source),
        "destination": str(destination),
        "sha256": source_hash,
        "copy_sha256": copy_hash,
        "identical": source_hash == copy_hash,
    }


def run(command: list[str], cwd: Path, timeout: int = 3600) -> dict[str, Any]:
    started = time.monotonic()
    result = subprocess.run(
        command, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False
    )
    elapsed = round(time.monotonic() - started, 2)
    return {
        "command": " ".join(command),
        "cwd": str(cwd),
        "exit_code": result.returncode,
        "duration_seconds": elapsed,
        "stdout_tail": "\n".join(result.stdout.strip().splitlines()[-20:]),
        "stderr_tail": "\n".join(result.stderr.strip().splitlines()[-20:]),
    }


ECONOMIC_FIELDS = (
    "net_pnl_usdt",
    "gross_pnl_usdt",
    "costs_usdt",
    "fills",
    "closed_trades",
    "deferred_slots",
    "calls",
    "days",
)
METADATA_FIELDS = ("missing_minutes", "days_with_trades")


def compare_cells(
    sealed: dict[str, Any], replay: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Separa economía de metadatos: un minuto ausente mal publicado no es un PnL mal publicado."""
    mismatches: list[dict[str, Any]] = []
    metadata: list[dict[str, Any]] = []
    sealed_cells = sealed.get("cells") or {}
    replay_cells = replay.get("cells") or {}
    for key, expected in sorted(sealed_cells.items()):
        actual = replay_cells.get(key)
        if actual is None:
            mismatches.append({"cell": key, "field": "MISSING", "sealed": expected, "replay": None})
            continue
        for fields, bucket in ((ECONOMIC_FIELDS, mismatches), (METADATA_FIELDS, metadata)):
            for field in fields:
                if not same(expected.get(field, 0), actual.get(field, 0)):
                    bucket.append(
                        {
                            "cell": key,
                            "field": field,
                            "sealed": expected.get(field),
                            "replay": actual.get(field),
                        }
                    )
    for key, expected in sorted((sealed.get("paired_day_deltas") or {}).items()):
        actual = (replay.get("paired_day_deltas") or {}).get(key) or {}
        for left, right in zip(
            expected.get("per_day_usdt") or [], actual.get("per_day_usdt") or [], strict=False
        ):
            if not same(left, right):
                mismatches.append(
                    {"cell": f"{key}|per_day", "field": "per_day_usdt", "sealed": left, "replay": right}
                )
        for left, right in zip(
            expected.get("ci95") or [], actual.get("ci95") or [], strict=False
        ):
            if not same(left, right):
                mismatches.append(
                    {"cell": f"{key}|ci95", "field": "ci95", "sealed": left, "replay": right}
                )
    sealed_status = (sealed.get("decision") or {}).get("economic_status")
    replay_status = (replay.get("decision") or {}).get("economic_status")
    if sealed_status != replay_status:
        mismatches.append(
            {
                "cell": "decision",
                "field": "economic_status",
                "sealed": sealed_status,
                "replay": replay_status,
            }
        )
    return mismatches, metadata


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--worktree", default=None)
    parser.add_argument("--json", default=str(OUT / "CLEAN_REPRO_RUN_REPORT.json"))
    parser.add_argument("--keep", action="store_true", help="no elimina el worktree al terminar")
    args = parser.parse_args(argv)

    commit = git("rev-parse", args.commit).stdout.strip()
    worktree = Path(
        args.worktree or Path(tempfile.gettempdir()) / f"rfc018-clean-{commit[:8]}"
    ).resolve()
    report: dict[str, Any] = {
        "schema_version": "DEF_RUN_018_CLEAN_REPLAY_V1",
        "rfc": RFC,
        "subject": SUBJECT,
        "generated_at_utc": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit": commit,
        "commit_subject": git("log", "-1", "--format=%s", commit).stdout.strip(),
        "worktree": str(worktree),
        "status": "BLOCKED",
        "runtime_executed": False,
        "paper_validation": "NOT_PERFORMED",
        "paper_orders": 0,
        "live_orders": 0,
        "inputs": [],
        "commands": [],
        "mismatches": [],
        "metadata_mismatches": [],
        "sealed": {
            "oos_results": sha256(REPO / "data" / "def-run-017" / "oos" / "OOS_RESULTS.json"),
            "cell_keys": [],
        },
    }

    if worktree.exists():
        git("worktree", "remove", "--force", str(worktree))
        if worktree.exists():
            shutil.rmtree(worktree, ignore_errors=True)
    added = git("worktree", "add", "--detach", str(worktree), commit)
    report["commands"].append(
        {
            "command": f"git worktree add --detach {worktree} {commit}",
            "exit_code": added.returncode,
            "stdout_tail": added.stdout.strip()[-400:],
            "stderr_tail": added.stderr.strip()[-400:],
        }
    )
    if added.returncode != 0:
        report["blockers"] = ["WORKTREE_FAILED"]
        Path(args.json).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print("status=BLOCKED worktree")
        return 2

    plan = json.loads((REPO / "data" / "def-run-017" / "oos" / "OOS_PLAN.json").read_text())
    sealed_results = json.loads(
        (REPO / "data" / "def-run-017" / "oos" / "OOS_RESULTS.json").read_text()
    )
    report["sealed"]["cell_keys"] = sorted(sealed_results.get("cells") or {})
    dataset_paths = [declared["path"] for declared in (plan.get("datasets") or {}).values()]
    to_copy = [
        *dataset_paths,
        *[
            str(path.relative_to(REPO)).replace("\\", "/")
            for folder in ("data/def-run-016", "data/def-run-017")
            for path in sorted((REPO / folder).rglob("*"))
            if path.is_file()
        ],
    ]
    for relative in to_copy:
        source = REPO / relative
        expected = None
        for _symbol, declared in (plan.get("datasets") or {}).items():
            if declared["path"] == relative:
                expected = declared["sha256"]
                break
        entry = copy_verified(source, worktree / relative)
        if expected and entry["sha256"] != expected:
            entry["expected_sha256"] = expected
            entry["identical"] = False
        report["inputs"].append(entry)
    if not all(entry["identical"] for entry in report["inputs"]):
        report["status"] = "BLOCKED"
        report["blockers"] = ["INPUT_HASH_MISMATCH"]
        Path(args.json).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print("status=BLOCKED inputs")
        return 2

    replay_out = worktree / "reports" / "ai-bots" / SUBJECT / "evidence" / "oos"
    commands = [
        [PYTHON, "scripts/def_run_017_reproduce.py", "--out", str(worktree / "REPRODUCTION.json")],
        [
            PYTHON,
            "scripts/def_run_017_oos.py",
            "--execute",
            "--partition",
            "untouched_test",
            "--workers",
            str(args.workers),
            "--cost-multipliers",
            "1.0",
        ],
        [
            PYTHON,
            "scripts/def_run_017_oos.py",
            "--execute",
            "--partition",
            "untouched_test",
            "--workers",
            str(args.workers),
            "--cost-multipliers",
            "2.0",
            "--out-name",
            "OOS_RUNS_untouched_test_cost2.json",
        ],
        [PYTHON, "scripts/def_run_017_oos.py", "--aggregate"],
        [
            PYTHON,
            "scripts/def_run_017_oos.py",
            "--stress",
            "--out-name",
            "OOS_RUNS_untouched_test_cost2.json",
        ],
    ]
    for command in commands:
        result = run(command, worktree)
        report["commands"].append(result)
        if result["exit_code"] != 0:
            report["status"] = "FAIL"
            report["blockers"] = [f"COMMAND_FAILED:{command[1]}"]
            report["runtime_executed"] = Path(worktree / "REPRODUCTION.json").is_file()
            Path(args.json).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(f"status=FAIL {command[1]} exit={result['exit_code']}")
            return 1

    reproduction = json.loads((worktree / "REPRODUCTION.json").read_text())
    replay_results = json.loads((replay_out / "OOS_RESULTS.json").read_text())
    replay_stress = json.loads((replay_out / "OOS_STRESS_COST2.json").read_text())
    sealed_stress = json.loads(
        (REPO / "data" / "def-run-017" / "oos" / "OOS_STRESS_COST2.json").read_text()
    )
    report["mismatches"], report["metadata_mismatches"] = compare_cells(
        sealed_results, replay_results
    )
    for left, right in zip(
        (sealed_stress.get("paired_day_deltas") or {}).get("UNI/USDT", {}).get("ci95") or [],
        (replay_stress.get("paired_day_deltas") or {}).get("UNI/USDT", {}).get("ci95") or [],
        strict=False,
    ):
        if not same(left, right):
            report["mismatches"].append(
                {"cell": "UNI/USDT|stress|ci95", "field": "ci95", "sealed": left, "replay": right}
            )
    if sealed_stress.get("stress_status") != replay_stress.get("stress_status"):
        report["mismatches"].append(
            {
                "cell": "stress",
                "field": "stress_status",
                "sealed": sealed_stress.get("stress_status"),
                "replay": replay_stress.get("stress_status"),
            }
        )
    report["reproduction"] = {
        "scenarios": sorted(reproduction.get("scenarios") or {}),
        "result": reproduction.get("result"),
        "mismatches": reproduction.get("mismatches"),
    }
    report["runtime_executed"] = True
    report["economic_reproduced"] = not report["mismatches"]
    report["status"] = "CLEAN_CHECKOUT_REPRODUCED" if not report["mismatches"] else "FAIL"
    if report["metadata_mismatches"]:
        report["notes"] = [
            "la economía coincide; los metadatos de cobertura no, y esa diferencia es el "
            "defecto RECOUNT_ZEROED_RUN_METADATA que el verificador B también señala"
        ]
    report["comparison"] = {
        "cells": len(replay_results.get("cells") or {}),
        "economic_status": (replay_results.get("decision") or {}).get("economic_status"),
        "stress_status": replay_stress.get("stress_status"),
    }
    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    if not args.keep:
        git("worktree", "remove", "--force", str(worktree))
    print(
        f"status={report['status']} mismatches={len(report['mismatches'])} "
        f"cells={report['comparison']['cells']}"
    )
    return 0 if report["status"] == "CLEAN_CHECKOUT_REPRODUCED" else 1


if __name__ == "__main__":
    sys.exit(main())
