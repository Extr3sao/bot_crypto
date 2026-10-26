"""Reproducible mutation matrix for P0 (live gate enforcement).

Why this exists
---------------
``tests/unit/test_live_gate_enforcement.py`` passing proves the gate is enforced
*while the code is there*. It does not prove the suite would notice if the
enforcement disappeared. This script removes one property at a time from an
exported tree and requires the suite to fail.

Every edit is an exact string replacement that must match **exactly once**. If
the code drifts the script fails loudly instead of silently testing nothing.

The pytest process imports ``trading_bot`` from the variant ``src`` (PYTHONPATH),
and the probe subprocesses read ``P0_APP_SRC``. Without both, the CLI cases
would keep testing the original tree and the structural mutants would survive.

Usage
-----
    uv run --frozen python scripts/audit/p0_live_gate_mutants.py
    uv run --frozen python scripts/audit/p0_live_gate_mutants.py --source worktree
    uv run --frozen python scripts/audit/p0_live_gate_mutants.py --json out.json

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

TARGET_TESTS: tuple[str, ...] = ("tests/unit/test_live_gate_enforcement.py",)

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
    edits: tuple[tuple[str, str], ...]
    criterion: str


_BOUNDARY_GATE_CHECK = (
    "    if not _evaluate_live_gate(settings).allowed:\n"
    "        yield False\n"
    "        return\n"
    "    with gate.order_boundary(run_id=run_id) as allowed:\n"
)

_REDUCTION_EXEMPTION = "    if not opens_risk:\n        yield True\n        return\n"

_RESULT_FAILURES = (
    "    failed = tuple(result.gate_id for result in report.results if not result.passed)\n"
)

_INCOMPLETE_GUARD = (
    "    if report.total_gates != EXPECTED_LIVE_GATE_COUNT:\n"
    "        return LiveGateVerdict(\n"
    "            False, f\"live_gate_incomplete:{report.total_gates}/{EXPECTED_LIVE_GATE_COUNT}\"\n"
    "        )\n"
)

_GATE_ERROR_GUARD = (
    "    except Exception as exc:  # an authority that raises is not permission\n"
    "        return LiveGateVerdict(False, f\"live_gate_error:{type(exc).__name__}\")\n"
)

_RUN_STARTUP_BLOCK = (
    "    # P0 — the live gate is a precondition of the process, not a detail of the\n"
    "    # first order: refuse before the scanner runs, before a client exists, and\n"
    "    # before the loop can report a healthy iteration. The stop keeps priority,\n"
    "    # so an already-stopped process keeps its G-3 behaviour (start and report\n"
    "    # the skip instead of exiting). The boundary checks the gate again at the\n"
    "    # sink; this is the fail-fast copy.\n"
    "    if hot_stop is not None and not _live_stop_is_closed(hot_stop):\n"
    "        try:\n"
    "            startup_settings = load_settings(config_dir=args.config_dir, env_file=env_file)\n"
    "        except Exception as exc:\n"
    "            sys.stderr.write(\n"
    "                \"ERROR: live gate could not read the configuration \"\n"
    "                f\"({type(exc).__name__}); auto-trade refused, no order sent.\\n\"\n"
    "            )\n"
    "            return 2\n"
    "        verdict = _evaluate_live_gate(startup_settings)\n"
    "        if not verdict.allowed:\n"
    "            sys.stderr.write(\n"
    "                f\"ERROR: live trading gate refused auto-trade ({verdict.reason}); no order sent.\\n\"\n"
    "            )\n"
    "            return 2\n"
    "\n"
)

MUTANTS: tuple[Mutant, ...] = (
    Mutant(
        "M1",
        "the entry boundary no longer consults the live gate",
        ((_BOUNDARY_GATE_CHECK, "    with gate.order_boundary(run_id=run_id) as allowed:\n"),),
        "ACC-P0-04",
    ),
    Mutant(
        "M2",
        "the verdict never records a failing check",
        ((_RESULT_FAILURES, "    failed = ()\n"),),
        "ACC-P0-02",
    ),
    Mutant(
        "M3",
        "only critical failures block (GATE-006/008 become advisory)",
        (
            (
                _RESULT_FAILURES,
                "    failed = tuple(result.gate_id for result in report.critical_failures)\n",
            ),
        ),
        "ACC-P0-02",
    ),
    Mutant(
        "M4",
        "run --auto-trade no longer checks the gate before the loop",
        ((_RUN_STARTUP_BLOCK, ""),),
        "ACC-P0-03",
    ),
    Mutant(
        "M5",
        "reduction is dragged into the entry gate",
        ((_REDUCTION_EXEMPTION, ""),),
        "ACC-P0-07",
    ),
    Mutant(
        "M6",
        "a report with fewer than ten checks counts as a pass",
        ((_INCOMPLETE_GUARD, ""),),
        "ACC-P0-05",
    ),
    Mutant(
        "M7",
        "a gate exception is treated as permission",
        ((_GATE_ERROR_GUARD, "    except Exception:  # mutant: an error is permission\n        return LiveGateVerdict(True)\n"),),
        "ACC-P0-05",
    ),
)


@dataclass
class VariantResult:
    variant: str
    killed: bool
    exit_code: int
    seconds: float
    description: str
    criterion: str
    failed_tests: list[str] = field(default_factory=list)


def _run(
    cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None, timeout: int = 1800
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
    env["P0_APP_SRC"] = str(package)
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


def _apply(text: str, mutant: Mutant) -> str:
    mutated = text
    for old, new in mutant.edits:
        count = mutated.count(old)
        if count != 1:
            raise AnchorError(
                f"{mutant.mutant_id}: anchor matched {count} times, expected 1: {old[:80]!r}"
            )
        mutated = mutated.replace(old, new)
    return mutated


def _pytest(tree: Path, src: Path | None, *, maxfail: int | None = None) -> tuple[int, list[str], str]:
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
        line.split(" ")[0]
        for line in completed.stdout.splitlines()
        if line.startswith("FAILED")
    ]
    return completed.returncode, failed, completed.stdout[-1500:]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P0 mutation matrix.")
    parser.add_argument("--rev", default=None)
    parser.add_argument("--source", choices=["archive", "worktree"], default="archive")
    parser.add_argument("--json", default=None)
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args(argv)

    started = time.time()
    tmp = Path(tempfile.mkdtemp(prefix="p0-mutants-"))
    report: dict[str, Any] = {
        "tool": "p0_live_gate_mutants",
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
                criterion="baseline",
                failed_tests=failed,
            ).__dict__
        )
        if code != 0:
            report["tail"] = tail
            print(f"baseline is red (exit {code}); a mutation matrix needs a green baseline")
            for result in report["variants"]:
                print(result)
            if args.json:
                Path(args.json).parent.mkdir(parents=True, exist_ok=True)
                Path(args.json).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            return 1

        for mutant in MUTANTS:
            variant_src = tmp / "variants" / mutant.mutant_id / "src"
            variant_src.parent.mkdir(parents=True)
            shutil.copytree(tree / "src", variant_src, symlinks=True)
            target = variant_src / "trading_bot" / "app.py"
            target.write_text(_apply(target.read_text(encoding="utf-8"), mutant), encoding="utf-8")

            variant_started = time.time()
            code, failed, tail = _pytest(tree, variant_src, maxfail=1)
            seconds = round(time.time() - variant_started, 1)
            result = VariantResult(
                variant=mutant.mutant_id,
                killed=code != 0,
                exit_code=code,
                seconds=seconds,
                description=mutant.description,
                criterion=mutant.criterion,
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
