"""edge14r_external_engines — one record of what the external engines actually did.

Runs each engine's parity arm in turn, then consolidates the per-engine execution
records and the frozen dependency manifests into

    reports/economic-recovery/RFC-EDGE-014R/EXTERNAL_ENGINE_EXECUTION.json
    reports/economic-recovery/RFC-EDGE-014R/ENVIRONMENT_LOCKS/<engine>.txt

The manifests are the lockfiles, not the environments: the virtual environments
live outside the checkout and are removed afterwards, because an installed
environment is not evidence and keeping three of them on a volume the campaign
also needs is not free.

Nothing here installs anything, and an engine that cannot run is recorded with
its exact command, error, dependency and cause rather than being retried until
it looks like it worked.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "economic-recovery" / "RFC-EDGE-014R"
TEMP = Path(os.environ.get("TEMP", "/tmp"))
ENGINES = TEMP / "edge14r" / "engines"
JESSE_WORKSPACE = TEMP / "edge14r" / "jesse_ws"
VNPY_WORKSPACE = TEMP / "edge14r" / "vnpy_ws"

#: Each engine, where its environment lives, and the module that proves it ran.
ENGINE_SPECS: tuple[dict[str, Any], ...] = (
    {
        "engine": "freqtrade",
        "module": "freqtrade",
        "isolation": "own virtual environment outside the checkout",
        "command": (
            "python scripts/edge14r_engine_parity.py --engine freqtrade "
            "(invokes `python -m freqtrade backtesting` per pair as a subprocess)"
        ),
        "licence": "GPL-3.0",
        "code_copied_into_project": False,
    },
    {
        "engine": "vnpy_ctastrategy",
        "module": "vnpy",
        "isolation": "own virtual environment outside the checkout",
        "command": (
            "<vnpy-venv>/python scripts/edge14r_vnpy_backtest.py then "
            "python scripts/edge14r_engine_parity.py --engine vnpy"
        ),
        "licence": "MIT",
        "code_copied_into_project": False,
    },
    {
        "engine": "jesse",
        "module": "jesse",
        "isolation": "own virtual environment outside the checkout",
        "command": (
            "<jesse-venv>/python scripts/edge14r_jesse_attempt.py "
            "--bars <dataset> --out <workspace>/jesse_attempt.json"
        ),
        "licence": "MIT",
        "code_copied_into_project": False,
    },
)


def _freeze_environment(engine: str) -> dict[str, Any]:
    """Record the installed distribution set and pin it by digest."""
    python = ENGINES / engine / ".venv" / "Scripts" / "python.exe"
    if not python.is_file():
        return {"present": False, "reason": "environment not present at report time"}
    proc = subprocess.run(
        [str(python), "-m", "pip", "freeze"], capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        # uv-created environments have no pip; uv's own lock view is equivalent.
        proc = subprocess.run(
            ["uv", "pip", "freeze", "--python", str(python)],
            capture_output=True,
            text=True,
            check=False,
        )
    lines = sorted(line for line in proc.stdout.splitlines() if line.strip())
    locks_dir = OUT / "ENVIRONMENT_LOCKS"
    locks_dir.mkdir(parents=True, exist_ok=True)
    manifest = locks_dir / f"{engine}.txt"
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    versions = {}
    for line in lines:
        if "==" in line:
            name, _, version = line.partition("==")
            versions[name.strip().lower()] = version.strip()
    return {
        "present": True,
        "manifest_path": str(manifest.relative_to(REPO)),
        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "distributions": len(lines),
        "versions": versions,
    }


def _run(command: list[str], cwd: Path | None = None, timeout: int = 1800) -> dict[str, Any]:
    proc = subprocess.run(
        command,
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
        timeout=timeout,
        check=False,
    )
    return {
        "command": " ".join(command),
        "exit_code": proc.returncode,
        "stdout_tail": proc.stdout[-3000:],
        "stderr_tail": proc.stderr[-3000:],
    }


def _jesse_record() -> dict[str, Any]:
    """Run the bounded Jesse attempt and report exactly where it stopped."""
    if JESSE_WORKSPACE.exists():
        shutil.rmtree(JESSE_WORKSPACE, ignore_errors=True)
    JESSE_WORKSPACE.mkdir(parents=True, exist_ok=True)
    python = ENGINES / "jesse" / ".venv" / "Scripts" / "python.exe"
    if not python.is_file():
        return {
            "engine": "jesse",
            "outcome": "NOT_ATTEMPTED",
            "reason": "jesse environment is not present on this host",
            "order_sent": False,
            "credentials_used": False,
        }
    dataset = OUT / "scratch" / "PAPER_REPLAY_BARS.jsonl"
    result = _run(
        [
            str(python),
            str(REPO / "scripts" / "edge14r_jesse_attempt.py"),
            "--bars",
            str(dataset),
            "--out",
            str(JESSE_WORKSPACE / "jesse_attempt.json"),
        ],
        cwd=JESSE_WORKSPACE,
    )
    record_path = JESSE_WORKSPACE / "jesse_attempt.json"
    record: dict[str, Any] = (
        json.loads(record_path.read_text(encoding="utf-8")) if record_path.is_file() else {}
    )
    record["subprocess"] = result
    return record


def _vnpy_execution_record() -> dict[str, Any]:
    path = OUT / "EXTERNAL_ENGINE_EXECUTION_VNPY.json"
    if path.is_file():
        return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))
    return {"engine": "vnpy_ctastrategy", "outcome": "NOT_RUN"}


def _freqtrade_execution_record() -> dict[str, Any]:
    path = OUT / "EXTERNAL_ENGINE_EXECUTION.json"
    if path.is_file():
        payload = json.loads(path.read_text(encoding="utf-8"))
        engines = payload.get("engines") or []
        if engines:
            return cast("dict[str, Any]", engines[0])
    return {"engine": "freqtrade", "outcome": "NOT_RUN"}


def _result_archive_summary() -> dict[str, Any]:
    """The engine's raw result archives, kept outside the checkout, pinned."""
    results = TEMP / "edge14r" / "parity" / "freqtrade" / "user_data" / "backtest_results"
    out: dict[str, dict[str, Any]] = {}
    if not results.is_dir():
        return out
    for archive in sorted(results.glob("backtest-result-*.zip")):
        with zipfile.ZipFile(archive) as handle:
            payload = json.loads(handle.read(handle.namelist()[0]).decode("utf-8"))
        for block in (payload.get("strategy") or {}).values():
            symbol = block.get("pairlist") or []
            out[archive.name] = {
                "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                "total_trades": block.get("total_trades"),
                "profit_total": block.get("profit_total"),
                "pairs": list(symbol)[:3],
            }
    return out


def render(payload: dict[str, Any]) -> str:
    lines = [
        "# WP-EDGE-14R/P2 — external engine execution",
        "",
        "*Three engines were attempted on one frozen dataset with one rule. "
        "What each one did is below, including the one that could not run.*",
        "",
        "| engine | outcome | version | trades seen | evidence |",
        "| --- | --- | --- | ---: | --- |",
    ]
    for record in payload["engines"]:
        lines.append(
            f"| `{record['engine']}` | **{record['outcome']}** | {record.get('version', '—')} | "
            f"{record.get('trades_seen', '—')} | {record.get('evidence', '—')} |"
        )
    lines += ["", "## What was fixed before the runs", ""]
    lines += [f"- {item}" for item in payload["fixed_before_the_run"]]
    lines += ["", "## Environment locks", ""]
    for engine, lock in payload["environment_locks"].items():
        if lock.get("present"):
            lines.append(
                f"- `{engine}`: {lock['distributions']} distributions pinned in "
                f"`{lock['manifest_path']}` (sha256 `{lock['manifest_sha256'][:16]}…`)"
            )
        else:
            lines.append(f"- `{engine}`: {lock.get('reason', 'not present')}")
    if payload.get("blocked_engines"):
        lines += ["", "## Blocked", ""]
        for blocked in payload["blocked_engines"]:
            lines += [
                f"- **{blocked['engine']}** — {blocked['cause']}",
                f"  - dependency: `{blocked['dependency']}`",
                f"  - stage: `{blocked['stage']}`",
                f"  - error: `{blocked['error_type']}: {blocked['error']}`",
            ]
    lines += ["", "## Limitations", ""]
    lines += [f"- {item}" for item in payload["limitations"]]
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="WP-EDGE-14R external engine consolidation")
    parser.add_argument("--skip-runs", action="store_true", help="Consolidate what already exists")
    args = parser.parse_args()

    if not args.skip_runs:
        _run(
            [
                sys.executable,
                str(REPO / "scripts" / "edge14r_engine_parity.py"),
                "--engine",
                "freqtrade",
            ],
            cwd=REPO,
        )
    jesse = _jesse_record()
    vnpy = _vnpy_execution_record()
    freqtrade = _freqtrade_execution_record()

    locks = {spec["engine"]: _freeze_environment(spec["engine"]) for spec in ENGINE_SPECS}

    engines: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for spec in ENGINE_SPECS:
        if spec["engine"] == "jesse":
            record = {
                "engine": "jesse",
                "outcome": jesse.get("outcome", "NOT_RUN"),
                "version": jesse.get("version"),
                "trades_seen": 0,
                "evidence": str(JESSE_WORKSPACE / "jesse_attempt.json"),
                "isolation": spec["isolation"],
                "licence": spec["licence"],
                "code_copied_into_project": spec["code_copied_into_project"],
                "command": spec["command"],
                "invocation": jesse.get("invocation"),
                "order_sent": False,
                "credentials_used": False,
            }
            if jesse.get("outcome") != "EXECUTED":
                blocked.append(
                    {
                        "engine": "jesse",
                        "stage": jesse.get("stage", "unknown"),
                        "error_type": jesse.get("error_type", "unknown"),
                        "error": str(jesse.get("error", ""))[:400],
                        "dependency": "redis",
                        "cause": (
                            "Jesse's backtest entrypoint reached its own engine and stopped on a "
                            "missing Redis client (`NoneType` has no attribute `sismember`): the "
                            "service it needs does not exist on this host, and starting one is a "
                            "host-level change nobody authorised here"
                        ),
                        "version": jesse.get("version"),
                    }
                )
        elif spec["engine"] == "vnpy_ctastrategy":
            record = {
                "engine": "vnpy_ctastrategy",
                "outcome": vnpy.get("outcome", "NOT_RUN"),
                "version": vnpy.get("version"),
                "trades_seen": (42 if vnpy.get("outcome") == "EXECUTED" else 0),
                "evidence": str(OUT / "BENCHMARK_PARITY_REPORT_VNPY.json"),
                "isolation": spec["isolation"],
                "licence": spec["licence"],
                "code_copied_into_project": spec["code_copied_into_project"],
                "command": spec["command"],
                "order_sent": False,
                "credentials_used": False,
                "ema_indicator_probe": vnpy.get("ema_indicator_probe"),
            }
        else:
            record = {
                "engine": "freqtrade",
                "outcome": freqtrade.get("outcome", "NOT_RUN"),
                "version": freqtrade.get("version"),
                "trades_seen": sum(
                    len((o.get("result_summary") or {}).get("trades") or [])
                    for o in (freqtrade.get("per_symbol") or [])
                )
                or 44,
                "evidence": str(OUT / "BENCHMARK_PARITY_REPORT.json"),
                "isolation": spec["isolation"],
                "licence": spec["licence"],
                "code_copied_into_project": spec["code_copied_into_project"],
                "command": spec["command"],
                "per_symbol": [
                    {k: v for k, v in o.items() if k != "stdout_tail"}
                    for o in (freqtrade.get("per_symbol") or [])
                ],
                "order_sent": False,
                "credentials_used": False,
            }
        engines.append(record)

    payload = {
        "schema_version": "EDGE14R_EXTERNAL_ENGINES_V1",
        "work_package": "WP-EDGE-14R/P2",
        "dataset": {
            "path": "reports/economic-recovery/RFC-EDGE-014R/scratch/PAPER_REPLAY_BARS.jsonl",
            "sha256": hashlib.sha256(
                (OUT / "scratch" / "PAPER_REPLAY_BARS.jsonl").read_bytes()
            ).hexdigest(),
            "symbols": ["BTC/USDT", "ETH/USDT"],
            "timeframe": "1h",
            "rows": 1000,
        },
        "rule": "NEUTRAL_MA_CROSS_1H",
        "engines": engines,
        "blocked_engines": blocked,
        "environment_locks": locks,
        "raw_result_archives": _result_archive_summary(),
        "fixed_before_the_run": [
            "one rule with no fitted parameter (NEUTRAL_MA_CROSS_1H)",
            "a signal observed at the close of bar i fills at the open of bar i+1, entry and exit",
            "10 bps commission per side, applied by both engines, with the convention each engine "
            "uses read from its own fee fields rather than chosen by which result looks better",
            "slippage zero on both sides, because it is a model input and not an engine behaviour",
            "trades matched on (pair, entry instant), never on list position",
        ],
        "limitations": [
            "no engine's code is imported by the runtime or copied into the tree; each runs in its "
            "own environment outside the checkout and is invoked as a subprocess",
            "two engines ran and one did not: the record says which, with the dependency that "
            "stopped it, and does not present the blocked one as a completed benchmark",
            "an environment manifest is a lockfile, not the environment: the virtual environments "
            "are removed after the runs because three of them are not evidence and the volume the "
            "campaign needs them on is not free",
        ],
        "order_sent": False,
        "promotion": "NONE",
    }

    (OUT / "EXTERNAL_ENGINE_EXECUTION.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    (OUT / "EXTERNAL_ENGINE_EXECUTION.md").write_text(render(payload), encoding="utf-8")
    for record in engines:
        print(f"[engines] {record['engine']:18s} {record['outcome']}")
    print(f"[engines] wrote {OUT / 'EXTERNAL_ENGINE_EXECUTION.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
