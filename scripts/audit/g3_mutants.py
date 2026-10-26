"""Reproducible mutation matrix for G-3 (the hot stop on LIVE paths).

Why this exists
---------------
`tests/unit/test_live_hot_stop_coverage.py` passing proves the boundary works
while it is there. It does not prove the suite would notice if one property
disappeared. This script removes one property at a time from an exported tree
and requires the suite to fail.

Every edit is an exact string replacement that must match **exactly once**. If
the code drifts the script fails loudly instead of silently testing nothing.

The probe subprocess reads ``G3_APP_SRC`` so it loads the mutant package rather
than the original one; without that, the process-boundary tests would keep
testing `tree/src` and every mutant would survive.

Usage
-----
    uv run --frozen python scripts/audit/g3_mutants.py
    uv run --frozen python scripts/audit/g3_mutants.py --source worktree
    uv run --frozen python scripts/audit/g3_mutants.py --rev <sha>
    uv run --frozen python scripts/audit/g3_mutants.py --json out.json

Exit status: 0 only when the baseline passes and every mutant is killed.
"""

from __future__ import annotations

import argparse
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

TARGET_TESTS: tuple[str, ...] = ("tests/unit/test_live_hot_stop_coverage.py",)

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
    expect: str


_POLL_SPOT = (
    "    # Cheap check before anything is built or journalled: a stopped process must\n"
    "    # not leave a trade case behind for an order it will refuse. The\n"
    "    # authoritative check is still the boundary at the sink.\n"
    "    if hot_stop.poll():\n"
    "        return {\n"
    '            "status": "SKIPPED",\n'
    '            "reason": f"kill_switch_engaged_hot:{hot_stop.engaged_reason}",\n'
    "        }\n\n"
)

_POLL_FUTURES = (
    "    # Same reason as the spot path: no trade case for an order that the\n"
    "    # boundary below will refuse.\n"
    "    if hot_stop.poll():\n"
    "        return {\n"
    '            "status": "SKIPPED",\n'
    '            "reason": f"kill_switch_engaged_hot:{hot_stop.engaged_reason}",\n'
    "        }\n\n"
)

MUTANTS: tuple[Mutant, ...] = (
    Mutant(
        mutant_id="M1",
        description="the boot-time kill switch stops being consulted",
        edits=(
            (
                "    try:\n        switch_active = bool(gate.kill_switch.is_active)\n",
                "    try:\n        switch_active = False  # MUTANT\n",
            ),
        ),
        criterion="ACC-G3-06",
        expect="test_env_kill_switch_blocks_entry_without_a_marker",
    ),
    Mutant(
        mutant_id="M2",
        description="spot entry trades while the run directory says stopped",
        edits=(
            (_POLL_SPOT, ""),
            (
                "        with _live_order_boundary(hot_stop, opens_risk=True) as allowed:\n"
                "            if not allowed:\n"
                "                return {\n"
                '                    "status": "SKIPPED",\n'
                '                    "reason": f"kill_switch_engaged_hot:{_live_stop_reason(hot_stop)}",\n'
                "                }\n"
                "            order = connector.create_order(",
                "        if True:  # MUTANT\n            order = connector.create_order(",
            ),
        ),
        criterion="ACC-G3-02",
        expect="test_entry_is_refused_with_a_marker[run-spot]",
    ),
    Mutant(
        mutant_id="M3",
        description="futures entry trades while the run directory says stopped",
        edits=(
            (_POLL_FUTURES, ""),
            (
                "            with _live_order_boundary(hot_stop, opens_risk=True) as allowed:\n"
                "                if not allowed:\n",
                "            with _live_order_boundary(hot_stop, opens_risk=False) as allowed:\n"
                "                if not allowed:\n",
            ),
        ),
        criterion="ACC-G3-02",
        expect="test_entry_is_refused_with_a_marker[run-futures]",
    ),
    Mutant(
        mutant_id="M4",
        description="place-order stops classifying entry as risk",
        edits=(
            (
                '        opens_risk = not (bool(args.reduce_only) or args.trade_side == "CLOSE")\n',
                "        opens_risk = False  # MUTANT\n",
            ),
        ),
        criterion="ACC-G3-02",
        expect="test_entry_is_refused_with_a_marker[place-order-futures]",
    ),
    Mutant(
        mutant_id="M5",
        description="each process invents its own run directory (no inheritance)",
        edits=(
            (
                "    path = Path(run_dir or DEFAULT_LIVE_RUN_DIR).expanduser()\n",
                "    path = Path(run_dir or DEFAULT_LIVE_RUN_DIR).expanduser() / uuid4().hex  # MUTANT\n",
            ),
        ),
        criterion="ACC-G3-04",
        expect="test_restart_over_the_same_run_dir_stays_blocked",
    ),
    Mutant(
        mutant_id="M6",
        description="the boundary drops the lock (engage no longer waits)",
        edits=(
            (
                "    with gate.order_boundary(run_id=run_id) as allowed:\n        yield allowed\n",
                "    gate.poll(run_id=run_id)  # MUTANT: no lock\n    yield not gate.engaged\n",
            ),
        ),
        criterion="ACC-G3-09",
        expect="test_engage_waits_for_the_inflight_dispatch",
    ),
)


@dataclass
class VariantResult:
    variant: str
    description: str
    criterion: str
    expect: str
    exit_code: int
    killed: bool
    duration_s: float
    failing_tests: list[str] = field(default_factory=list)


def _apply(text: str, mutant: Mutant) -> str:
    for old, new in mutant.edits:
        occurrences = text.count(old)
        if occurrences != 1:
            raise AnchorError(
                f"{mutant.mutant_id}: anchor matched {occurrences} times, expected 1:\n{old[:200]}"
            )
        text = text.replace(old, new)
    return text


def _env(src: Path, tree: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(src), str(tree)])
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["G3_APP_SRC"] = str(src)
    env.pop("PYTEST_ADDOPTS", None)
    env.pop("TRADING_BOT_KILL_SWITCH", None)
    return env


def _pytest(tree: Path, src: Path) -> tuple[int, list[str], str]:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            *TARGET_TESTS,
            "-q",
            "--no-header",
            "-p",
            "no:cacheprovider",
        ],
        cwd=tree,
        env=_env(src, tree),
        capture_output=True,
        text=True,
        timeout=1800,
    )
    failing = [
        line.split("::")[-1].split(" ")[0]
        for line in completed.stdout.splitlines()
        if line.startswith("FAILED ")
    ]
    return completed.returncode, failing, (completed.stdout + completed.stderr)[-3000:]


def _export(rev: str | None, destination: Path, source: str) -> Path:
    if source == "worktree":
        shutil.copytree(REPO_ROOT, destination, symlinks=True, ignore=_COPY_IGNORE)
        return destination
    archive = destination.parent / "tree.tar"
    completed = subprocess.run(
        ["git", "archive", "--format=tar", "-o", str(archive), rev or "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"git archive failed: {completed.stderr[-400:]}")
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as tar:
        try:
            tar.extractall(destination, filter="data")
        except TypeError:  # Python < 3.12
            tar.extractall(destination)
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="G-3 mutation matrix.")
    parser.add_argument("--rev", default=None)
    parser.add_argument("--source", choices=["archive", "worktree"], default="worktree")
    parser.add_argument("--json", default=None)
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args(argv)

    started = time.time()
    report: dict[str, Any] = {
        "tool": "g3_mutants",
        "repo_root": str(REPO_ROOT),
        "source": args.source,
        "rev": args.rev,
        "targets": list(TARGET_TESTS),
        "mutants": len(MUTANTS),
    }
    results: list[VariantResult] = []
    tmp = Path(tempfile.mkdtemp(prefix="g3-mutants-"))

    try:
        tree = _export(args.rev, tmp / "tree", args.source)
        base_src = tree / "src"

        code, failing, tail = _pytest(tree, base_src)
        results.append(
            VariantResult(
                variant="baseline",
                description="unmodified tree",
                criterion="ACC-G3-01",
                expect="all green",
                exit_code=code,
                killed=False,
                duration_s=round(time.time() - started, 2),
                failing_tests=failing[:5],
            )
        )
        if code != 0:
            print("BASELINE IS NOT GREEN — nothing below proves anything.", file=sys.stderr)
            print(tail, file=sys.stderr)
            report["baseline_green"] = False
            _write_json(args.json, report, results, started)
            return 1
        report["baseline_green"] = True

        original = (tree / APP_REL).read_text(encoding="utf-8")

        for mutant in MUTANTS:
            variant_src = tmp / "variants" / mutant.mutant_id / "src"
            variant_src.parent.mkdir(parents=True)
            shutil.copytree(tree / "src", variant_src, symlinks=True)
            (variant_src / "trading_bot" / "app.py").write_text(
                _apply(original, mutant), encoding="utf-8", newline=""
            )

            mutant_started = time.time()
            code, failing, tail = _pytest(tree, variant_src)
            results.append(
                VariantResult(
                    variant=mutant.mutant_id,
                    description=mutant.description,
                    criterion=mutant.criterion,
                    expect=mutant.expect,
                    exit_code=code,
                    killed=code != 0,
                    duration_s=round(time.time() - mutant_started, 2),
                    failing_tests=failing[:5],
                )
            )
            if code == 0:
                report.setdefault("survivors", []).append(
                    {"mutant": mutant.mutant_id, "tail": tail}
                )
    except AnchorError as exc:
        print(f"ANCHOR ERROR: {exc}", file=sys.stderr)
        report["anchor_error"] = str(exc)
        _write_json(args.json, report, results, started)
        return 1
    finally:
        if args.keep:
            print(f"temporary export kept at {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)

    _write_json(args.json, report, results, started)

    print(f"{'variant':<10} {'killed':<7} {'exit':<5} {'sec':>7}  description")
    for result in results:
        print(
            f"{result.variant:<10} "
            f"{('n/a' if result.variant == 'baseline' else ('yes' if result.killed else 'NO')):<7} "
            f"{result.exit_code:<5} {result.duration_s:>7}  {result.description}"
        )
        for test in result.failing_tests[:2]:
            print(f"{'':<10} failed: {test}")

    survivors = [r for r in results if r.variant != "baseline" and not r.killed]
    if survivors:
        print(
            "\nSURVIVORS: "
            + ", ".join(r.variant for r in survivors)
            + " — the suite is not sensitive to these properties.",
            file=sys.stderr,
        )
        return 1

    print(
        f"\nbaseline green; {len(MUTANTS)}/{len(MUTANTS)} mutants killed "
        f"in {time.time() - started:.1f}s"
    )
    return 0


def _write_json(
    path: str | None, report: dict[str, Any], results: list[VariantResult], started: float
) -> None:
    report["variants"] = [r.__dict__ for r in results]
    report["total_seconds"] = round(time.time() - started, 2)
    report["all_mutants_killed"] = bool(results) and all(
        r.killed for r in results if r.variant != "baseline"
    )
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"matrix written to {path}")


if __name__ == "__main__":
    raise SystemExit(main())
