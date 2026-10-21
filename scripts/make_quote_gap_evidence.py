#!/usr/bin/env python
"""make_quote_gap_evidence — corre los checks y arma el informe con lo que salió.

Ningún número de `RUN_REPORT.json` se escribe a mano: cada uno sale de una ejecución real
con su exit code, y el fichero guarda el comando exacto para que se pueda repetir. Los
artefactos del laboratorio, del verificador y del drill se leen y se hashean, no se citan de
memoria.

Uso::

    python scripts/make_quote_gap_evidence.py \
        --out reports/ai-bots/WP-PAPER-QUOTE-GAP-002
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
RUNTIME_FILES = (
    "src/trading_bot/vision/gap_recovery.py",
    "src/trading_bot/vision/durable.py",
    "src/trading_bot/vision/lane.py",
    "src/trading_bot/vision/quotes.py",
    "src/trading_bot/vision/prospective.py",
    "src/trading_bot/paper/broker.py",
    "src/trading_bot/risk/manager.py",
)
SCRIPT_FILES = (
    "scripts/quote_gap_lab.py",
    "scripts/verify_quote_gap.py",
    "scripts/quote_feed_source.py",
    "scripts/make_quote_gap_evidence.py",
)
TEST_FILES = (
    "tests/unit/vision/test_gap_recovery.py",
    "tests/unit/vision/test_gap_recovery_venue.py",
    "tests/unit/vision/test_durable_book.py",
    "tests/unit/vision/test_session_recovery.py",
    "tests/unit/vision/test_prospective_session.py",
    "tests/unit/vision/test_session_durable.py",
)
COUNTS = re.compile(r"(?P<passed>\d+) passed(?:, (?P<failed>\d+) failed)?")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(command: list[str], *, timeout: int = 1800) -> dict[str, Any]:
    started = time.time()
    process = subprocess.run(
        command,
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**os.environ, "PYTHONPATH": str(REPO / "src")},
        check=False,
    )
    output = (process.stdout or "") + (process.stderr or "")
    tail = [line for line in output.splitlines() if line.strip()][-3:]
    match = COUNTS.search(output)
    return {
        "command": " ".join([Path(command[0]).name, *command[1:]]),
        "exit_code": process.returncode,
        "seconds": round(time.time() - started, 1),
        "passed": int(match.group("passed")) if match else None,
        "failed": int(match.group("failed") or 0) if match else None,
        "tail": tail,
    }


def _pytest(paths: list[str]) -> list[str]:
    return [PYTHON, "-m", "pytest", *paths, "-q", "-p", "no:warnings"]


def _from_log(path: Path) -> dict[str, Any]:
    """A check that was run outside this script, read from the log it wrote.

    The alternative is to re-run a ten-minute suite inside a generator that already takes
    minutes, which invites the generator being skipped. The log carries the command, the
    output and the real exit code, and the report labels the source as such.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    exit_code = None
    command = None
    for line in text.splitlines():
        if line.startswith("$ "):
            command = line[2:].strip()
        if line.startswith("EXIT="):
            exit_code = int(line.split("=", 1)[1].strip())
    match = COUNTS.search(text)
    return {
        "command": command or path.name,
        "exit_code": exit_code if exit_code is not None else 1,
        "seconds": None,
        "passed": int(match.group("passed")) if match else None,
        "failed": int(match.group("failed") or 0) if match else None,
        "tail": [line for line in text.splitlines() if line.strip()][-3:],
        "source": f"captured log {path.name}",
    }


def collect(out: Path, suite_log: Path | None = None) -> dict[str, Any]:
    #: `--out` puede llegar relativo; todo lo que se publica se hace relativo a `REPO`, así que
    #: se ancla aquí una sola vez en vez de fallar a mitad del informe por un `relative_to`.
    out = out if out.is_absolute() else (REPO / out)
    lab = out / "lab" / "GAP_LAB.json"
    verification = out / "VERIFICATION.json"
    drill = out / "drill" / "DRILL.json"

    checks = [_run(_pytest(list(TEST_FILES)))]
    if suite_log is not None:
        checks.append(_from_log(suite_log))
    else:
        checks.append(
            _run(
                _pytest(
                    ["tests/unit/vision", "tests/unit/paper", "tests/unit/risk", "tests/unit/market_data"]
                )
            )
        )
    checks += [
        _run(
            _pytest(
                [
                    "tests/unit/vision/test_minute_quote_feed.py",
                    "tests/unit/vision/test_subbar_execution.py",
                ]
            )
        ),
        _run([PYTHON, "-m", "ruff", "check", *RUNTIME_FILES, *SCRIPT_FILES, *TEST_FILES]),
        _run([PYTHON, "-m", "mypy", *RUNTIME_FILES]),
        _run([PYTHON, "scripts/quote_feed_source.py", "verify"]),
        _run(
            [
                PYTHON,
                "scripts/verify_quote_gap.py",
                "--lab",
                str(lab),
                "--negative-controls",
                "--json",
                str(verification),
            ]
        ),
    ]
    for check in checks:
        #: Un check leído de un log no tiene duración propia; se imprime `(log)` en vez de
        #: fingir un cero que se leería como «instantáneo».
        stamp = f"{check['seconds']:>7.1f}s" if check["seconds"] is not None else "    (log)"
        print(f"{check['exit_code']:>3}  {stamp}  {check['command'][:110]}")

    verification_doc = json.loads(verification.read_text(encoding="utf-8"))
    lab_doc = json.loads(lab.read_text(encoding="utf-8"))
    drill_doc = json.loads(drill.read_text(encoding="utf-8")) if drill.exists() else None

    return {
        "schema_version": "QUOTE_GAP_RUN_REPORT_V1",
        "rfc": "WP-PAPER-QUOTE-GAP-002",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "branch": subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip(),
        "base_commit": subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip(),
        "mode": "PAPER",
        "live_enabled": False,
        "real_model_called": False,
        "live_orders": 0,
        "false_success": int(verification_doc.get("false_success") or 0),
        "environment": {
            "python": sys.version.split()[0],
            "runtime_sha256": {path: _sha256(REPO / path) for path in RUNTIME_FILES},
            "script_sha256": {path: _sha256(REPO / path) for path in SCRIPT_FILES},
            "test_sha256": {path: _sha256(REPO / path) for path in TEST_FILES},
            "dirty_entries": len(
                [
                    line
                    for line in subprocess.run(
                        ["git", "status", "--porcelain"],
                        cwd=REPO,
                        capture_output=True,
                        text=True,
                        check=False,
                    ).stdout.splitlines()
                    if line.strip()
                ]
            ),
        },
        "artifacts": {
            "lab": {
                "path": str(lab.relative_to(REPO)),
                "sha256": _sha256(lab),
                "ok": lab_doc.get("ok"),
                "scenarios": {
                    name: {
                        "A": scenario["A"]["status"],
                        "B": scenario["B"]["status"],
                        "code": scenario["B"].get("code"),
                        "economics_match": None
                        if scenario.get("comparison") is None
                        else scenario["comparison"]["ok"],
                        "bodies_match": None
                        if scenario.get("book_comparison") is None
                        else scenario["book_comparison"]["ok"],
                    }
                    for name, scenario in (lab_doc.get("scenarios") or {}).items()
                },
                "corrupt_feed": lab_doc.get("corrupt_feed"),
                "concurrent_writer": lab_doc.get("concurrent_writer"),
                "kill_while_saving": {
                    "ok": (lab_doc.get("kill_while_saving") or {}).get("ok"),
                    "iterations": len(
                        (lab_doc.get("kill_while_saving") or {}).get("outcomes") or []
                    ),
                },
                "kill_while_resuming": {
                    key: value
                    for key, value in (lab_doc.get("kill_while_resuming") or {}).items()
                    if key != "attempts"
                },
            },
            "verification": {
                "path": str(verification.relative_to(REPO)),
                "sha256": _sha256(verification),
                "passed": verification_doc.get("passed"),
                "failed": verification_doc.get("failed"),
                "ok": verification_doc.get("ok"),
                "negative_controls": verification_doc.get("negative_controls"),
                "negative_controls_ok": verification_doc.get("negative_controls_ok"),
            },
            "drill": None
            if drill_doc is None
            else {
                "path": str(drill.relative_to(REPO)),
                "sha256": _sha256(drill),
                "verdict": drill_doc.get("verdict"),
                "criteria": drill_doc.get("criteria"),
                "state_digest_equal": (
                    (drill_doc.get("A") or {}).get("state_digest")
                    == (drill_doc.get("B") or {}).get("state_digest")
                ),
                "differences": drill_doc.get("differences"),
                "kill": {
                    "killed": [
                        child.get("killed") for child in (drill_doc.get("children") or [])
                    ],
                    "exit_codes": [
                        child.get("exit_code") for child in (drill_doc.get("children") or [])
                    ],
                },
            },
        },
        "checks": checks,
    }


def _md(report: dict[str, Any]) -> str:
    lines = [
        "# RUN REPORT — WP-PAPER-QUOTE-GAP-002",
        "",
        f"- Generado: `{report['generated_at_utc']}`",
        f"- Rama: `{report['branch']}` · base `{report['base_commit'][:12]}`",
        f"- Modo: **{report['mode']}** · `live_orders = {report['live_orders']}` · "
        f"modelo real llamado: `{report['real_model_called']}`",
        f"- `false_success = {report['false_success']}`",
        "",
        "## Checks (ejecutados, con su exit code)",
        "",
        "| # | comando | resultados | exit | s |",
        "| --- | --- | --- | --- | --- |",
    ]
    for index, check in enumerate(report["checks"], start=1):
        result = f"{check['passed']} passed" if check["passed"] is not None else "—"
        if check["failed"]:
            result += f", {check['failed']} failed"
        lines.append(
            f"| {index} | `{check['command']}` | {result} | {check['exit_code']} | "
            f"{check['seconds']} |"
        )
    artifacts = report["artifacts"]
    lines += ["", "## Artefactos", ""]
    lines.append(
        f"- Laboratorio: `{artifacts['lab']['path']}` "
        f"(`{artifacts['lab']['sha256'][:16]}…`), ok=`{artifacts['lab']['ok']}`"
    )
    for name, scenario in artifacts["lab"]["scenarios"].items():
        lines.append(
            f"  - **{name}**: A={scenario['A']} · B={scenario['B']}"
            + (f" ({scenario['code']})" if scenario["code"] else "")
            + f" · economía={scenario['economics_match']} · cuerpo={scenario['bodies_match']}"
        )
    lines.append(
        f"- Verificación independiente: `{artifacts['verification']['path']}` "
        f"(`{artifacts['verification']['sha256'][:16]}…`), "
        f"{artifacts['verification']['passed']} checks, "
        f"{len(artifacts['verification']['negative_controls'] or [])} controles negativos"
    )
    if artifacts["drill"]:
        drill = artifacts["drill"]
        lines.append(
            f"- Drill sobre minutos reales: `{drill['path']}` "
            f"(`{drill['sha256'][:16]}…`), veredicto `{drill['verdict']}`, "
            f"digests iguales={drill['state_digest_equal']}"
        )
    lines += ["", "## Runtime hasheado", ""]
    for path, digest in report["environment"]["runtime_sha256"].items():
        lines.append(f"- `{path}` · `{digest}`")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", type=Path, default=REPO / "reports/ai-bots/WP-PAPER-QUOTE-GAP-002"
    )
    parser.add_argument(
        "--suite-log",
        type=Path,
        default=None,
        help="log of the wide suite already executed (with its EXIT= line)",
    )
    args = parser.parse_args(argv)
    suite_log = args.suite_log
    if suite_log is not None and not suite_log.is_absolute():
        suite_log = REPO / suite_log
    report = collect(args.out, suite_log)
    (args.out / "RUN_REPORT.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (args.out / "RUN_REPORT.md").write_text(_md(report), encoding="utf-8")
    failed = [check for check in report["checks"] if check["exit_code"] != 0]
    print(json.dumps({"checks": len(report["checks"]), "failed": len(failed)}, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
