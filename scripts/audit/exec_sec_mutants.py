"""Reproducible mutation matrix for RFC-TAP-EXEC-SEC-002.

Why this exists
---------------
``test_order_authorization.py`` and ``test_exec_sec_process.py`` passing proves
the new contract holds *while the code is there*. It does not prove the tests
would notice if the confirmation check, the classifier or the payload guard
disappeared. This script removes one property at a time from an exported tree
and requires the suite to fail.

Every edit is an exact string replacement that must match **exactly once**. If
the code drifts, the script fails loudly instead of silently testing nothing.

Usage
-----
    uv run --frozen python scripts/audit/exec_sec_mutants.py
    uv run --frozen python scripts/audit/exec_sec_mutants.py --source worktree
    uv run --frozen python scripts/audit/exec_sec_mutants.py --json out.json

Exit status: 0 only when the baseline passes and every mutant is killed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_REL = "src/trading_bot/app.py"
AUTH_REL = "src/trading_bot/execution/order_authorization.py"

TARGET_TESTS: tuple[str, ...] = (
    "tests/unit/test_order_authorization.py",
    "tests/unit/test_exec_sec_process.py",
)

_COPY_IGNORE = shutil.ignore_patterns(
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    ".tmp",
)


class AnchorError(RuntimeError):
    """The mutant's anchor did not match exactly once."""


@dataclass(frozen=True)
class Mutant:
    mutant_id: str
    description: str
    file: str
    edits: tuple[tuple[str, str], ...]
    acceptance: str


_RUN_CONFIRMATION = (
    '    if args.auto_trade and args.mode in {"live", "shadow_live"} and not args.confirm_live:\n'
    "        sys.stderr.write(\n"
    '            "ERROR: --auto-trade en modo live requiere --confirm-live; "\n'
    '            "no se ha ejecutado ninguna accion.\\n"\n'
    "        )\n"
    "        return 2\n"
)

_BOUNDARY_CONFIRMATION = "    if intent.requires_confirmation and not confirm_live:\n"

_BOUNDARY_CLASSIFIER_ERROR = "    if classifier_error:\n"

_BOUNDARY_GATE = (
    "    if not verdict.allowed:\n"
    "        authorization = _authorization_denial(\n"
    "            decision, verdict.reason, intent=intent, confirm_live=confirm_live, gate=verdict\n"
    "        )\n"
)

_SPOT_SELL = (
    "            return OrderDecision(\n"
    "                OrderCategory.UNKNOWN,\n"
    '                "R-SPOT-SELL-NO-VENUE-PROOF",\n'
)

_TPSL = (
    "        return OrderDecision(\n"
    "            OrderCategory.UNKNOWN,\n"
    '            "R-TPSL-NOT-MONOTONIC",\n'
)

_REDUCE_ONLY_REQUIRED = "    if not intent.reduce_only:\n"

_VENUE_CAPABILITY = "    if not capabilities.supports_reduce_only:\n"

_HEDGE = '    if position.position_mode.upper() != "ONE_WAY":\n'

_SIDE = "    if intent.side.upper() != position.closing_side:\n"

_QUANTITY = "    if intent.qty > position.qty + _QTY_EPSILON:\n"

_FLASH_STALE = (
    "    if not position.is_fresh(now):\n"
    "        return OrderDecision(\n"
    '            OrderCategory.UNKNOWN, "R-FLASH-STALE", "position snapshot is older than the window"\n'
    "        )\n"
)

_PAYLOAD_REDUCE_ONLY = '    if payload.get("reduceOnly") is not True:\n'

_FLASH_FIELDS = '        unexpected = set(payload) - {"positionId"}\n'

MUTANTS: tuple[Mutant, ...] = (
    Mutant(
        "M1",
        "run --auto-trade no longer requires --confirm-live",
        APP_REL,
        ((_RUN_CONFIRMATION, ""),),
        "T01",
    ),
    Mutant(
        "M2",
        "the sink trusts the CLI and skips the confirmation check",
        APP_REL,
        ((_BOUNDARY_CONFIRMATION, "    if False:\n"),),
        "T11",
    ),
    Mutant(
        "M3",
        "a classifier exception falls through to the gate",
        APP_REL,
        ((_BOUNDARY_CLASSIFIER_ERROR, "    if False:\n"),),
        "REQ-02",
    ),
    Mutant(
        "M4",
        "a rejecting gate is ignored at the sink",
        APP_REL,
        ((_BOUNDARY_GATE, ""),),
        "T02",
    ),
    Mutant(
        "M5",
        "a spot sell is treated as a proven reduction",
        AUTH_REL,
        (
            (
                _SPOT_SELL,
                "            return OrderDecision(\n"
                "                OrderCategory.PROVEN_REDUCTION,\n"
                '                "R-SPOT-SELL-NO-VENUE-PROOF",\n',
            ),
        ),
        "T06",
    ),
    Mutant(
        "M6",
        "a TP/SL change is treated as a proven reduction",
        AUTH_REL,
        (
            (
                _TPSL,
                "        return OrderDecision(\n"
                "            OrderCategory.PROVEN_REDUCTION,\n"
                '            "R-TPSL-NOT-MONOTONIC",\n',
            ),
        ),
        "T09",
    ),
    Mutant(
        "M7",
        "tradeSide=CLOSE is accepted without reduceOnly",
        AUTH_REL,
        ((_REDUCE_ONLY_REQUIRED, "    if False:\n"),),
        "T07",
    ),
    Mutant(
        "M8",
        "a venue without reduceOnly is trusted anyway",
        AUTH_REL,
        ((_VENUE_CAPABILITY, "    if False:\n"),),
        "REQ-03",
    ),
    Mutant(
        "M9",
        "hedge mode ambiguity is ignored",
        AUTH_REL,
        ((_HEDGE, "    if False:\n"),),
        "T08",
    ),
    Mutant(
        "M10",
        "the closing side is not compared to the position",
        AUTH_REL,
        ((_SIDE, "    if False:\n"),),
        "T06",
    ),
    Mutant(
        "M11",
        "a quantity above the position is accepted",
        AUTH_REL,
        ((_QUANTITY, "    if False:\n"),),
        "T06",
    ),
    Mutant(
        "M12",
        "a stale flash-close snapshot is accepted",
        AUTH_REL,
        ((_FLASH_STALE, ""),),
        "T08",
    ),
    Mutant(
        "M13",
        "the final payload may lose reduceOnly",
        AUTH_REL,
        ((_PAYLOAD_REDUCE_ONLY, "    if False:\n"),),
        "T07",
    ),
    Mutant(
        "M14",
        "the flash-close payload may gain a side and size",
        AUTH_REL,
        ((_FLASH_FIELDS, "        unexpected: set[str] = set()\n"),),
        "T07",
    ),
)


@dataclass
class VariantResult:
    variant: str
    killed: bool
    exit_code: int
    seconds: float
    description: str
    acceptance: str
    failed_tests: list[str] = field(default_factory=list)


def _run(
    cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None, timeout: int = 900
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def _env(tree: Path, src: Path | None = None) -> dict[str, str]:
    env = dict(os.environ)
    package = src or (tree / "src")
    env["PYTHONPATH"] = os.pathsep.join([str(package), str(tree)])
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("PYTEST_ADDOPTS", None)
    env.pop("TRADING_BOT_KILL_SWITCH", None)
    return env


def _export(rev: str | None, destination: Path, source: str) -> Path:
    if source == "worktree":
        shutil.copytree(REPO_ROOT, destination, symlinks=True, ignore=_COPY_IGNORE)
        return destination
    archive = destination.parent / "tree.tar"
    completed = _run(
        ["git", "archive", "--format=tar", "-o", str(archive), rev or "HEAD"], cwd=REPO_ROOT
    )
    if completed.returncode != 0:
        raise RuntimeError(f"git archive failed: {completed.stderr[-400:]}")
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as tar:
        try:
            tar.extractall(destination, filter="data")
        except TypeError:
            tar.extractall(destination)
    return destination


def _apply(path: Path, mutant: Mutant) -> None:
    text = path.read_text(encoding="utf-8")
    mutated = text
    for old, new in mutant.edits:
        count = mutated.count(old)
        if count != 1:
            raise AnchorError(
                f"{mutant.mutant_id}: anchor matched {count} times, expected 1: {old[:80]!r}"
            )
        mutated = mutated.replace(old, new)
    path.write_text(mutated, encoding="utf-8")


def _pytest(
    tree: Path, src: Path | None, *, maxfail: int | None = None
) -> tuple[int, list[str], str]:
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        *TARGET_TESTS,
        "-q",
        "--no-header",
        "-p",
        "no:cacheprovider",
    ]
    if maxfail:
        cmd.append(f"--maxfail={maxfail}")
    completed = _run(cmd, cwd=tree, env=_env(tree, src))
    failed = [
        line.split(" ")[0] for line in completed.stdout.splitlines() if line.startswith("FAILED")
    ]
    return completed.returncode, failed, completed.stdout[-1500:]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RFC-TAP-EXEC-SEC-002 mutation matrix.")
    parser.add_argument("--rev", default=None)
    parser.add_argument("--source", choices=["archive", "worktree"], default="archive")
    parser.add_argument("--json", default=None)
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args(argv)

    started = time.time()
    tmp = Path(tempfile.mkdtemp(prefix="exec-sec-mutants-"))
    report: dict[str, Any] = {
        "tool": "exec_sec_mutants",
        "rfc": "RFC-TAP-EXEC-SEC-002",
        "checkout": str(REPO_ROOT),
        "source": args.source,
        "target_tests": list(TARGET_TESTS),
        "variants": [],
    }
    try:
        tree = _export(args.rev, tmp / "tree", args.source)
        rev = args.rev or _run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT).stdout.strip()
        report["rev"] = rev
        report["app_sha256"] = hashlib.sha256((tree / APP_REL).read_bytes()).hexdigest()
        report["authorization_sha256"] = hashlib.sha256((tree / AUTH_REL).read_bytes()).hexdigest()

        code, failed, tail = _pytest(tree, None)
        baseline_seconds = round(time.time() - started, 1)
        report["baseline_green"] = code == 0
        report["baseline_seconds"] = baseline_seconds
        report["variants"].append(
            VariantResult(
                variant="baseline",
                killed=False,
                exit_code=code,
                seconds=baseline_seconds,
                description="unmutated export",
                acceptance="baseline",
                failed_tests=failed,
            ).__dict__
        )
        if code != 0:
            report["tail"] = tail
            print(f"baseline is red (exit {code}); a mutation matrix needs a green baseline")
            if args.json:
                Path(args.json).parent.mkdir(parents=True, exist_ok=True)
                Path(args.json).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            return 1

        for mutant in MUTANTS:
            variant_src = tmp / "variants" / mutant.mutant_id / "src"
            variant_src.parent.mkdir(parents=True)
            shutil.copytree(tree / "src", variant_src, symlinks=True)
            _apply(variant_src / mutant.file.removeprefix("src/"), mutant)

            variant_started = time.time()
            code, failed, tail = _pytest(tree, variant_src, maxfail=1)
            seconds = round(time.time() - variant_started, 1)
            result = VariantResult(
                variant=mutant.mutant_id,
                killed=code != 0,
                exit_code=code,
                seconds=seconds,
                description=mutant.description,
                acceptance=mutant.acceptance,
                failed_tests=failed[:5],
            )
            report["variants"].append(result.__dict__)
            print(
                f"{result.variant:<10} {'killed' if result.killed else 'SURVIVED':<9} "
                f"{result.seconds:>7}s  {result.description}"
            )
            if not result.killed:
                report.setdefault("tails", {})[mutant.mutant_id] = tail
    finally:
        if args.keep:
            print(f"temporary export kept at {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)

    mutated = [v for v in report["variants"] if v["variant"] != "baseline"]
    killed = [v for v in mutated if v["killed"]]
    report["killed"] = len(killed)
    report["mutants"] = len(mutated)
    report["total_seconds"] = round(time.time() - started, 1)
    text = json.dumps(report, indent=2, default=str)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(text + "\n", encoding="utf-8")
    print(f"\n{len(killed)}/{len(mutated)} mutants killed in {report['total_seconds']}s")
    return 0 if report["baseline_green"] and len(killed) == len(mutated) else 1


if __name__ == "__main__":
    raise SystemExit(main())
