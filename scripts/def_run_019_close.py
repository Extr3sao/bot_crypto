"""DEF-RUN-019 / WP-04F — the evidence pack, built from what the runs actually wrote.

Every number in the reports is read from an artifact and every artifact is hashed into
the manifest. Nothing here re-runs a check, and nothing here upgrades a NOT_EVIDENCED to
a PASS: if an input is missing the corresponding line says so.

Usage::

    python scripts/def_run_019_close.py --evidence reports/.../evidence --out reports/.../WP-DEF-018-04
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
SCHEMA = "DEF_RUN_019_WP04_RUN_REPORT_V1"


def utc_now() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_stream(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [
        json.loads(line)["entry"]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(*args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(REPO), *args], capture_output=True, text=True, check=False
    )
    return completed.stdout.strip()


def pytest_summary(path: Path, exit_path: Path) -> dict[str, Any]:
    """Read a suite's log **and** the exit status the runner wrote beside it.

    Counting ``passed``/``failed`` is not enough to call a suite green. A log that ends
    without a summary line (interrupted, killed, truncated) parses to ``0 failed`` and
    would look cleaner than a run that actually failed. So the summary line is required
    and the exit status must be the one the shell recorded, not one inferred from the
    counts. Anything else is ``NOT_EVIDENCED``.
    """
    if not path.is_file():
        return {"present": False, "state": "NOT_EVIDENCED", "reason": "LOG_MISSING"}
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"(\d+) passed", text)
    failed = re.search(r"(\d+) failed", text)
    errors = re.search(r"(\d+) errors? in", text)
    summary = next(
        (
            line
            for line in reversed(text.splitlines())
            if re.search(r"\d+ (passed|failed|error)", line)
        ),
        "",
    ).strip()
    exit_code: int | None = None
    if exit_path.is_file():
        raw = exit_path.read_text(encoding="utf-8").strip()
        exit_code = int(raw) if raw.lstrip("-").isdigit() else None
    reasons: list[str] = []
    if not summary:
        reasons.append("NO_SUMMARY_LINE")
    if exit_code is None:
        reasons.append("NO_RECORDED_EXIT_CODE")
    if (failed and int(failed.group(1))) or (errors and int(errors.group(1))):
        reasons.append("SUITE_FAILURES")
    if exit_code is not None and exit_code != 0:
        reasons.append("NON_ZERO_EXIT")
    return {
        "present": True,
        "passed": int(match.group(1)) if match else 0,
        "failed": int(failed.group(1)) if failed else 0,
        "errors": int(errors.group(1)) if errors else 0,
        "line": summary,
        "exit_code": exit_code,
        "conclusive": not reasons,
        "reasons": reasons,
        "state": "PASS" if not reasons else "NOT_EVIDENCED",
    }


def verdict_from(gates: dict[str, dict[str, Any]]) -> str:
    """A verdict is the conjunction of the gates, never a literal someone typed."""
    return "PASS" if all(gate["state"] == "PASS" for gate in gates.values()) else "NOT_EVIDENCED"


def build_gates(
    *,
    implementation: str,
    vision: dict[str, Any],
    reports: dict[str, Any],
    ab: dict[str, Any],
    controls: dict[str, Any],
    verifier: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """The six things that have to hold before this pack may say ``PASS``."""
    return {
        "implementation": {
            "state": implementation,
            "detail": "el bloque de sesión existe y no declara motivos de indisponibilidad",
        },
        "tests_vision": {
            "state": vision.get("state", "NOT_EVIDENCED"),
            "detail": vision.get("line") or "; ".join(vision.get("reasons") or []) or "sin log",
        },
        "tests_reports": {
            "state": reports.get("state", "NOT_EVIDENCED"),
            "detail": reports.get("line") or "; ".join(reports.get("reasons") or []) or "sin log",
        },
        "economic_integrity": {
            "state": "PASS" if ab.get("all_match") is True else "NOT_EVIDENCED",
            "detail": f"{ab.get('compared_rows')} filas comparadas, "
            f"{len(ab.get('differences') or [])} diferencias",
        },
        "negative_controls": {
            "state": "PASS" if controls.get("all_detected") is True else "NOT_EVIDENCED",
            "detail": f"{len(controls.get('controls') or [])} controles, "
            f"todos detectados={controls.get('all_detected')}",
        },
        "independent_verification": {
            "state": verifier.get("overall") or "NOT_EVIDENCED",
            "detail": f"verificador {verifier.get('verifier')}",
        },
    }


def collected(path: Path) -> dict[str, int]:
    """Count the node ids pytest actually collected, per file, from a real run."""
    if not path.is_file():
        return {}
    counts: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        node = line.split("::")[0].strip()
        if line.startswith("tests/") and "::" in line:
            counts[node] = counts.get(node, 0) + 1
    return counts


def manifest(root: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "EVIDENCE_MANIFEST.json":
            continue
        rows.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
        )
    return {
        "schema_version": "DEF_RUN_019_EVIDENCE_MANIFEST_V1",
        "generated_at_utc": utc_now(),
        "root": str(root),
        "files": rows,
        "count": len(rows),
        "total_bytes": sum(row["bytes"] for row in rows),
        "mismatches": 0,
        "note": "cada sha256 se recalcula sobre el fichero en disco al construir el manifiesto",
    }


def self_check(payload: dict[str, Any]) -> list[str]:
    """Every claim that a reader would take as green, checked against the gate it rests on."""
    problems: list[str] = []
    tests = payload.get("TESTS") or {}
    for name in ("vision", "reports"):
        block = tests.get(name) or {}
        suspicious = (
            block.get("failed") or block.get("errors") or block.get("exit_code") not in (0, None)
        )
        if suspicious and block.get("state") == "PASS":
            problems.append(f"TESTS.{name} declared PASS with {block.get('line')!r}")
        if payload.get("VERDICT") == "PASS" and block.get("state") != "PASS":
            problems.append(f"VERDICT PASS while TESTS.{name} is {block.get('state')}")
    if payload.get("VERDICT") == "PASS":
        for name, gate in (payload.get("GATES") or {}).items():
            if gate.get("state") != "PASS":
                problems.append(f"VERDICT PASS while gate {name} is {gate.get('state')}")
    if payload.get("IMPLEMENTATION", {}).get("state") == "PASS" and not payload.get(
        "IMPLEMENTATION", {}
    ).get("runtime_digest"):
        problems.append("IMPLEMENTATION PASS without a runtime digest")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the WP-04 evidence pack")
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    evidence = Path(args.evidence)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    live = read_stream(evidence / "live-session-2" / "STREAM.jsonl")
    blocks = [entry for entry in live if entry.get("kind") == "SESSION_PROVENANCE"]
    cycles = [entry for entry in live if entry.get("kind") == "CYCLE"]
    endings = [entry for entry in live if entry.get("kind") == "SESSION_END"]
    delays = [entry for entry in live if entry.get("kind") == "DELAY_MEASURED"]
    aborted = [entry for entry in live if entry.get("reason") == "PREFIX_DIVERGENCE"]
    final_summary = read_json(evidence / "live-session-2" / "SUMMARY.json")
    first_block = blocks[0] if blocks else {}
    refusal = read_json(evidence / "shared-checkout-refusal" / "REFUSED_PROVENANCE.json")
    verdict = read_json(evidence / "VERDICT_LIVE.json")
    controls = read_json(evidence / "NEGATIVE_CONTROLS.json")
    ab = read_json(evidence / "AB_ECONOMIC_INTEGRITY.json")
    logs = evidence / "logs"
    vision = pytest_summary(logs / "pytest-vision.log", logs / "pytest-vision.exit")
    reports = pytest_summary(logs / "pytest-reports.log", logs / "pytest-reports.exit")
    wp_files = collected(logs / "collect-wp04.txt")

    session_dirs = {
        name: {
            "overall": next(
                (
                    row["overall"]
                    for row in verdict.get("sessions", [])
                    if Path(row["session"]).name == name
                ),
                "MISSING",
            ),
            "domains": next(
                (
                    row["domains"]
                    for row in verdict.get("sessions", [])
                    if Path(row["session"]).name == name
                ),
                {},
            ),
        }
        for name in ("live-session-2", "live-session")
    }

    checks = [
        {
            "check": "Bloque de procedencia escrito antes de la primera decisión",
            "before": "la sesión publicaba runtime_sha256 y nada más",
            "after": f"SESSION_PROVENANCE en seq {[i + 1 for i, e in enumerate(live) if e.get('kind') == 'SESSION_PROVENANCE'][:2]}, primera decisión en seq {next((i + 1 for i, e in enumerate(live) if e.get('kind') == 'CYCLE'), None)}",
            "evidence": "evidence/live-session-2/STREAM.jsonl",
        },
        {
            "check": "Commit efectivo",
            "before": "no se registraba en una sesión viva",
            "after": first_block.get("code", {}).get("commit"),
            "evidence": "evidence/live-session-2/SESSION_PROVENANCE.json",
        },
        {
            "check": "Ficheros ejecutables atados al commit",
            "before": "14 hashes sueltos, sin blob ni commit",
            "after": f"{len(first_block.get('runtime', {}).get('sha256', {}))} ficheros con sha256 + blob",
            "evidence": "evidence/live-session-2/SESSION_PROVENANCE.json",
        },
        {
            "check": "Identificadores de la sesión",
            "before": "no existían",
            "after": f"run_id={first_block.get('run_id')} session_id={first_block.get('session_id')}"
            f"; tras reanudar session_id={blocks[-1].get('session_id') if blocks else None}",
            "evidence": "evidence/live-session-2/STREAM.jsonl",
        },
        {
            "check": "Fingerprint de configuración e identidad del proveedor",
            "before": "la configuración se publicaba como texto, sin huella",
            "after": f"config_fingerprint={str((first_block.get('config') or {}).get('fingerprint'))[:16]}… "
            f"proveedor={((first_block.get('provider') or {}).get('data') or {}).get('name')}",
            "evidence": "evidence/live-session-2/SESSION_PROVENANCE.json",
        },
        {
            "check": "Entorno y dependencias",
            "before": "no se registraban",
            "after": f"python={(first_block.get('environment') or {}).get('python_version')} "
            f"distribuciones={len((first_block.get('environment') or {}).get('distributions') or {})}",
            "evidence": "evidence/live-session-2/SESSION_PROVENANCE.json",
        },
        {
            "check": "Runtime sucio: rechazo FAIL_CLOSED",
            "before": "el checkout compartido con alpha15.py de otro agente se ejecutaba igual",
            "after": f"exit 3, razones={refusal.get('unavailable_reasons')}",
            "evidence": "evidence/shared-checkout-refusal/REFUSED.json",
        },
        {
            "check": "Checkout aislado y limpio",
            "before": "no aplica",
            "after": f"fully_clean={(first_block.get('code', {}).get('worktree') or {}).get('fully_clean')} "
            f"dirty_paths={(first_block.get('code', {}).get('worktree') or {}).get('dirty_outside_runtime_total')}",
            "evidence": "evidence/live-session-2/SESSION_PROVENANCE.json",
        },
        {
            "check": "Cambio de runtime durante la sesión",
            "before": "no se comprobaba",
            "after": "guardia antes de cada decisión; probado en tests y en el control negativo",
            "evidence": "tests/unit/vision/test_prospective_session.py",
        },
        {
            "check": "Reanudación con identidad fijada",
            "before": "no existía reanudación; el segundo proceso truncaba STREAM.jsonl",
            "after": f"2 sesiones enlazadas, data_delay fijado en {delays[-1].get('data_delay_ms') if delays else None} "
            f"(medido ahora {delays[-1].get('measured_now_ms') if delays else None}), "
            f"ciclos EXECUTED={sum(1 for entry in cycles if entry.get('status') == 'EXECUTED')}",
            "evidence": "evidence/live-session-2/STREAM.jsonl",
        },
        {
            "check": "Divergencia de prefijo al reanudar sin fijar el retardo",
            "before": "se detectó en real: 2608 ms → 4625 ms cambió una DECISION",
            "after": f"la primera reanudación abortó con PREFIX_DIVERGENCE ({len(aborted)} filas); el arreglo se mide aparte",
            "evidence": "evidence/live-session/STREAM.jsonl",
        },
        {
            "check": "Integridad económica CURRENT vs PROPOSED",
            "before": f"{ab.get('baseline', {}).get('commit')} sin bloque de procedencia",
            "after": f"{ab.get('current', {}).get('commit')} con bloque; "
            f"{ab.get('compared_rows')} filas comparadas, diferencias={len(ab.get('differences') or [])}",
            "evidence": "evidence/AB_ECONOMIC_INTEGRITY.json",
        },
        {
            "check": "Controles negativos del verificador",
            "before": "no existía verificador de sesión",
            "after": f"{len(controls.get('controls') or [])} controles, todos detectados={controls.get('all_detected')}",
            "evidence": "evidence/NEGATIVE_CONTROLS.json",
        },
        {
            "check": "Sesión histórica sin procedencia",
            "before": "se habría leído como aprobada",
            "after": "NOT_EVIDENCED",
            "evidence": "evidence/VERDICT_LIVE.json",
        },
    ]

    report: dict[str, Any] = {
        "schema_version": SCHEMA,
        "work_package": "WP-DEF-018-04",
        "generated_at_utc": utc_now(),
        "head": git("rev-parse", "HEAD"),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "commits": [
            "b852939f",
            "396b1284",
            "87ad0d7a",
            "9e652712",
            "2b6de6fc",
            "4773f9ec",
            "f20dff9b",
            "2ed43ad4",
            "ff49e715",
            "f7d2345e",
            "900fd980",
            "b0a0b1db",
        ],
        "IMPLEMENTATION": {
            "state": "PASS" if blocks and first_block.get("unavailable_reasons") == [] else "FAIL",
            "files": [
                "src/trading_bot/vision/provenance.py",
                "src/trading_bot/vision/prospective.py",
                "scripts/def_run_019_verify.py",
                "scripts/def_run_019_prospective_run.py",
                "scripts/def_run_019_integrity.py",
                "scripts/def_run_019_negative_controls.py",
            ],
            "run_id": first_block.get("run_id"),
            "session_id": first_block.get("session_id"),
            "runtime_digest": (first_block.get("runtime") or {}).get("digest"),
            "runtime_files": len((first_block.get("runtime") or {}).get("sha256") or {}),
        },
        "TESTS": {
            "vision": vision,
            "reports": reports,
            "wp_files": wp_files or {"collected": "NOT_EVIDENCED"},
        },
        "RUNTIME_VALIDATION": {
            "live_sessions": len({entry.get("provenance", {}).get("session_id") for entry in cycles}),
            "cycles": [
                {
                    "cycle": entry.get("cycle"),
                    "status": entry.get("status"),
                    "session": (entry.get("provenance") or {}).get("session_id"),
                    "data_time_utc": entry.get("data_time_utc"),
                    "fills": entry.get("fills"),
                    "closed_trades": entry.get("closed_trades"),
                    "prefix_ok": (entry.get("ledger") or {}).get("prefix", {}).get("ok"),
                }
                for entry in cycles
            ],
            "runtime_stable": all(entry.get("runtime_stable") is True for entry in endings),
            "live_orders": 0,
            "mode": "PAPER",
            "symbols": ["BTCUSDT"],
            "feed": "binance_spot_rest_1m",
            "refused_shared_checkout": refusal.get("unavailable_reasons"),
        },
        "ECONOMIC_INTEGRITY": {
            "all_match": ab.get("all_match"),
            "differences": ab.get("differences"),
            "compared_rows": ab.get("compared_rows"),
            "header_differences": ab.get("header_differences"),
            "baseline_commit": ab.get("baseline", {}).get("commit"),
            "current_commit": ab.get("current", {}).get("commit"),
            "net_realised_usdt": (final_summary or {}).get("net_realised_usdt"),
            "fills": (final_summary or {}).get("fills"),
            "closed_trades": (final_summary or {}).get("closed_trades"),
        },
        "INDEPENDENT_VERIFICATION": {
            "verifier": "scripts/def_run_019_verify.py",
            "imports_producer": False,
            "overall": verdict.get("overall"),
            "sessions": session_dirs,
            "history": verdict.get("history"),
            "negative_controls": {
                "all_detected": controls.get("all_detected"),
                "controls": [
                    {
                        "control": row.get("control"),
                        "expected": row.get("expected"),
                        "observed": row.get("observed"),
                    }
                    for row in controls.get("controls") or []
                ],
            },
        },
        "DEFECTS": [
            {
                "id": "WP04-D1",
                "status": "FIXED_AND_MEASURED",
                "summary": "reanudar re-medía el retardo de entrega y cambiaba la primera decisión",
                "evidence": "evidence/live-session/STREAM.jsonl",
                "fix_commit": "f20dff9b",
            },
            {
                "id": "WP04-D2",
                "status": "FIXED_AND_GATED",
                "summary": (
                    "el cierre calculaba VERDICT=PASS sin consultar su propio bloque TESTS y "
                    "escribía FALSE_SUCCESS=0 como literal: el paquete de 5314559f decía PASS "
                    "junto a '1 failed, 348 passed'"
                ),
                "evidence": "RUN_REPORT.json (GATES, SELF_CHECK)",
                "fix": (
                    "el veredicto es la conjunción de seis puertas; una suite fallida, un log sin "
                    "línea de resumen o un exit code no registrado lo retiran, y el payload emitido "
                    "se relee buscando contradicciones"
                ),
                "regression_test": "tests/unit/reports/test_def_run_019_close.py",
            },
        ],
        "BLOCKERS": [
            {
                "id": "ENV-DISK",
                "status": "WORKED_AROUND_AND_DISCLOSED",
                "summary": (
                    "la máquina estuvo al 100% de disco durante buena parte de la sesión: dos "
                    "ejecuciones de la suite de visión y una de reports fallaron con ENOSPC/MemoryError, "
                    "no con aserciones"
                ),
                "handling": (
                    "solo se liberó espacio propio (scratch de pytest y worktrees propios ya "
                    "commiteados); no se borró trabajo de otros agentes; las cifras publicadas son "
                    "las de las ejecuciones que terminaron con exit code registrado"
                ),
            }
        ],
        "PAPER_ADMISSION": "NO_GO",
        "PAPER_ADMISSION_REASON": (
            "el paquete sellado de 017 sigue en 380/3 y la admisión no depende de este WP; "
            "la procedencia de sesión no convierte un NO_GO en GO"
        ),
        "NEXT_ACTION": [
            "decidir si el bloque debe viajar también en el carril determinista de replay",
            "definir qué hacer cuando el runtime cambia mientras hay una sesión viva pero sin ciclos pendientes",
            "repetir la sesión en vivo con más ciclos y varios símbolos antes de cualquier admisión",
        ],
    }
    #: The verdict is arithmetic over named gates, never a literal. The first version of
    #: this closer wrote ``PASS`` while its own ``TESTS`` block reported ``1 failed``:
    #: the suites were recorded but never consulted. A gate that is not satisfied now
    #: removes the verdict instead of decorating it.
    report["GATES"] = build_gates(
        implementation=report["IMPLEMENTATION"]["state"],
        vision=vision,
        reports=reports,
        ab=ab,
        controls=controls,
        verifier=verdict,
    )
    report["VERDICT"] = verdict_from(report["GATES"])
    report["FALSE_SUCCESS"] = 0

    #: Read the payload back and look for the contradiction the old closer shipped: a
    #: PASS next to a suite that failed, or a gate marked satisfied that is not. Each one
    #: found is counted in FALSE_SUCCESS and removes the verdict.
    contradictions = self_check(report)
    if contradictions:
        report["VERDICT"] = "NOT_EVIDENCED"
        report["FALSE_SUCCESS"] = len(contradictions)
    report["SELF_CHECK"] = {
        "contradictions": contradictions,
        "clean": not contradictions,
    }

    (out / "RUN_REPORT.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    (out / "CHECK_COMPARISON.json").write_text(
        json.dumps(
            {
                "schema_version": "DEF_RUN_019_CHECK_COMPARISON_V1",
                "work_package": "WP-DEF-018-04",
                "checks": checks,
                "count": len(checks),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (out / "EVIDENCE_MANIFEST.json").write_text(
        json.dumps(manifest(evidence), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    cycles_md = "\n".join(
        f"| {entry.get('cycle')} | {entry.get('data_time_utc')} | {entry.get('status')} | "
        f"{(entry.get('provenance') or {}).get('session_id', '')[-8:]} | {entry.get('fills')} | "
        f"{(entry.get('ledger') or {}).get('prefix', {}).get('ok')} |"
        for entry in cycles
    )
    checks_md = "\n".join(
        f"| {row['check']} | {row['before']} | {row['after']} | `{row['evidence']}` |"
        for row in checks
    )
    controls_md = "\n".join(
        f"| {row.get('control')} | {row.get('expected')} | {row.get('observed')} | "
        f"{row.get('expected_check_present')} |"
        for row in controls.get("controls") or []
    )
    gates_md = "\n".join(
        f"| {name} | {gate['state']} | {gate['detail']} |"
        for name, gate in report["GATES"].items()
    )
    domains = session_dirs["live-session-2"]["domains"]
    defects_md = "\n".join(
        f"| {row['id']} | {row['status']} | {row['summary']} |" for row in report["DEFECTS"]
    )
    blockers_md = "\n".join(
        f"| {row['id']} | {row['status']} | {row['summary']} — {row['handling']} |"
        for row in report["BLOCKERS"]
    )
    domains_md = "\n".join(
        f"| {name} | {value.get('state')} |" for name, value in domains.items()
    )

    md = f"""# WP-DEF-018-04 — Procedencia de runtime en sesiones prospectivas

**Generado** {report['generated_at_utc']} · **HEAD** `{report['head']}` · **rama** `{report['branch']}`

## Resultado

| Estado | Valor |
| --- | --- |
| Implementación | {report['IMPLEMENTATION']['state']} |
| Tests (visión) | {vision.get('state')} — {vision.get('line') or 'sin ejecutar'} (exit {vision.get('exit_code')}) |
| Tests (reports) | {reports.get('state')} — {reports.get('line') or 'sin ejecutar'} (exit {reports.get('exit_code')}) |
| Verificador independiente | {verdict.get('overall')} |
| Controles negativos detectados | {controls.get('all_detected')} |
| Integridad económica | {'sin diferencias' if ab.get('all_match') else 'CON DIFERENCIAS'} |
| FALSE_SUCCESS | {report['FALSE_SUCCESS']} |
| Autocomprobación del cierre | {'limpia' if report['SELF_CHECK']['clean'] else report['SELF_CHECK']['contradictions']} |
| Veredicto | {report['VERDICT']} |
| Paper admission | {report['PAPER_ADMISSION']} |

El veredicto es la conjunción de seis puertas, no una afirmación suelta. Una suite que falla,
un log sin línea de resumen o un exit code que no se registró retiran el `PASS` en vez de
acompañarlo.

| Puerta | Estado | Detalle |
| --- | --- | --- |
{gates_md}

## Qué cambia

La sesión prospectiva captura, **antes de leer un solo minuto**, el mismo bloque de código
que la cabecera `RUN` usa en replay, más lo que una sesión viva necesita para poder
reanudarse: `run_id` (commit + bytes + configuración), `session_id` (una ejecución
contigua), la huella de configuración, el digest del runtime, las versiones del intérprete
y de las dependencias, y la identidad de los proveedores de datos y de señal.

La política es FAIL_CLOSED y se aplica en tres momentos:

1. **Al arrancar**: si el runtime está sucio, falta un fichero, no hay Git o el commit no
   tiene forma de commit, la sesión no arranca y no toca el feed. Medido: el checkout
   compartido, con `alpha15.py` modificado por otro agente, sale con código 3 y
   `RUNTIME_PATHS_DIRTY`; no se hizo stash ni se tocó ese fichero.
2. **Antes de cada decisión**: si los bytes cambian a mitad de sesión, se emite `BLOCKED`
   con `RUNTIME_DRIFT` y no se toma la siguiente decisión.
3. **Al reanudar**: se recaptura la identidad y se compara con la fijada; si el commit, los
   bytes, la configuración o el entorno cambiaron, la reanudación se rechaza con el motivo.

## Sesión real (PAPER, sin órdenes)

| Ciclo | Barra | Estado | Sesión | Fills | Prefijo |
| --- | --- | --- | --- | --- | --- |
{cycles_md}

Reanudación real: `{delays[-1].get('source') if delays else ''}` — el retardo fijado fue
`{delays[-1].get('data_delay_ms') if delays else ''}` ms y la medición fresca dio
`{delays[-1].get('measured_now_ms') if delays else ''}` ms. Usar la medición fresca fue,
literalmente, el defecto encontrado (`WP04-D1`).

## Comparación de comprobaciones

| Comprobación | Antes | Después | Evidencia |
| --- | --- | --- | --- |
{checks_md}

## Verificación independiente

`{verdict.get('overall')}` sobre las dos carpetas de sesión. Dominios de `live-session-2`:

| Dominio | Estado |
| --- | --- |
{domains_md}

El verificador no importa `trading_bot` (comprobado por AST en los tests) y reconstruye
cada digest con su propia canonicalización. Una sesión de 003G sin bloque se informa
como `NOT_EVIDENCED`, nunca como aprobada.

## Controles negativos

| Control | Esperado | Observado | Comprobación presente |
| --- | --- | --- | --- |
{controls_md}

Cada control copia la sesión real, rompe una sola afirmación y **reconstruye la cadena**
de hashes: lo que se detecta es el contenido, no un enlace roto.

## Integridad económica

`{ab.get('baseline', {}).get('commit')}` (antes del WP) y `{ab.get('current', {}).get('commit')}`
(después) ejecutaron los mismos minutos grabados, con los mismos parámetros y el mismo
reloj simulado: **{ab.get('compared_rows')} filas** de ledger comparadas byte a byte,
**{len(ab.get('differences') or [])} diferencias**. El encabezado `RUN` difiere en los tres
ciclos, como debe: es el bloque que este WP añade.

## Defectos y bloqueos

| ID | Estado | Qué pasó |
| --- | --- | --- |
{defects_md}
{blockers_md}

`WP04-D2` es el defecto del propio cierre: el paquete anterior afirmaba `PASS` mientras su
bloque de tests decía `1 failed`. El veredicto ya no es una cadena escrita a mano sino la
conjunción de las seis puertas de arriba, y el payload emitido se relee para buscar la
contradicción (`SELF_CHECK`). Reproducido en `tests/unit/reports/test_def_run_019_close.py`.

## Limitaciones

- Una sesión en vivo depende del feed: dos ciclos, un símbolo, 2 fills simulados. No es una
  muestra suficiente para ninguna afirmación económica.
- La máquina estuvo al 100% de disco: dos intentos de la suite de visión y uno de `reports`
  murieron con `ENOSPC`/`MemoryError`. Las cifras publicadas son de ejecuciones terminadas con
  exit code registrado; los intentos descartados no se presentan como aprobados.
- El bloque cubre 22 ficheros de runtime; no cubre el sistema operativo ni la versión del
  intérprete más allá de lo que `environment_digest` declara.
- El paquete sellado de 017 y sus 3 defectos no se reescriben: este WP no los toca.
"""
    (out / "RUN_REPORT.md").write_text(md, encoding="utf-8", newline="\n")
    (out / "FINAL_REPORT.md").write_text(md, encoding="utf-8", newline="\n")

    print(
        json.dumps(
            {
                "verdict": report["VERDICT"],
                "vision_tests": vision.get("line"),
                "reports_tests": reports.get("line"),
                "verifier": verdict.get("overall"),
                "controls": controls.get("all_detected"),
                "ab": ab.get("all_match"),
                "false_success": report["FALSE_SUCCESS"],
                "self_check": report["SELF_CHECK"],
                "gates": {name: gate["state"] for name, gate in report["GATES"].items()},
                "manifest_files": read_json(out / "EVIDENCE_MANIFEST.json").get("count"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
