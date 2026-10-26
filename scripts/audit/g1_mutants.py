"""Reproducible mutation matrix for G-1 (persistence of the kill switch).

Why this exists
---------------
``tests/unit/autonomous/test_kill_switch_persistence.py`` passing proves the
restore works while it is there. It does not prove the suite would notice if the
restore stopped reading the marker, started failing open, or forgot to arm rule
0. This script removes one property at a time from an exported tree and requires
the suite to fail.

Every mutant is an exact string replacement that must match **exactly once**. If
the code drifts, the script fails loudly instead of silently testing nothing — a
mutant that never applied reports green, which is the worst outcome here.

Usage
-----
    uv run --frozen python scripts/audit/g1_mutants.py             # HEAD
    uv run --frozen python scripts/audit/g1_mutants.py --rev <sha>
    uv run --frozen python scripts/audit/g1_mutants.py --source worktree
    uv run --frozen python scripts/audit/g1_mutants.py --json out.json

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
HOT_STOP_REL = "src/trading_bot/autonomous/hot_stop.py"

TARGET_TESTS: tuple[str, ...] = ("tests/unit/autonomous/test_kill_switch_persistence.py",)

_COPY_IGNORE = shutil.ignore_patterns(
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
)


@dataclass(frozen=True)
class Mutant:
    """One property of persistence, removed by a single exact replacement."""

    mutant_id: str
    description: str
    path: str
    old: str
    new: str
    criterion: str


MUTANTS: tuple[Mutant, ...] = (
    Mutant(
        mutant_id="M1",
        description="the gate does not read the marker at construction (restart boots open)",
        path=HOT_STOP_REL,
        old="        self.restore()\n",
        new="        self._restored = False  # MUTANT: no boot restore\n",
        criterion="ACC-G1-03/04",
    ),
    Mutant(
        mutant_id="M2",
        description="an unreadable control path fails open at boot",
        path=HOT_STOP_REL,
        old=(
            "        except OSError as exc:\n"
            "            self._restored = True\n"
            "            self.engage(\n"
            '                f"control_file_unreadable:{type(exc).__name__}",\n'
            '                actor=f"boot_restore:{self.control_path}",\n'
            "                run_id=run_id,\n"
            "            )\n"
            "            return True\n"
        ),
        new=(
            "        except OSError:\n"
            "            return False  # MUTANT: lstat error treated as absence\n"
        ),
        criterion="ACC-G1-08",
    ),
    Mutant(
        mutant_id="M3",
        description="presence treats every lstat failure as absence",
        path=HOT_STOP_REL,
        old=(
            "        try:\n"
            "            os.lstat(path)\n"
            "        except FileNotFoundError:\n"
            "            return False\n"
            "        return True\n"
        ),
        new=(
            "        try:\n"
            "            os.lstat(path)\n"
            "        except OSError:\n"
            "            return False  # MUTANT\n"
            "        return True\n"
        ),
        criterion="ACC-G1-08",
    ),
    Mutant(
        mutant_id="M4",
        description="engage never writes the marker (the stop dies with the process)",
        path=HOT_STOP_REL,
        old=(
            "        path = self.control_path\n"
            "        assert path is not None  # set in __post_init__\n"
            "        try:\n"
            "            write_control_file(path, self._reason)\n"
            "        except OSError:\n"
            "            return False\n"
            "        return True\n"
        ),
        new="        return True  # MUTANT: nothing written\n",
        criterion="ACC-G1-05",
    ),
    Mutant(
        mutant_id="M5",
        description="a failed atomic replace rewrites the marker in place",
        path=HOT_STOP_REL,
        old=(
            "    except BaseException:\n"
            "        with suppress(OSError):\n"
            "            tmp.unlink()\n"
            "        raise\n"
        ),
        new=(
            "    except BaseException:\n"
            '        target.write_text(payload, encoding="utf-8")  # MUTANT\n'
            "        raise\n"
        ),
        criterion="ACC-G1-09",
    ),
    Mutant(
        mutant_id="M6",
        description="an existing but empty marker is treated as permission to trade",
        path=HOT_STOP_REL,
        old=(
            "        detail, read_error = self._read_marker()\n"
            "        self._restored = True\n"
            "        self.engage(\n"
            '            read_error or detail or f"persisted stop:{HOT_STOP_FILE_NAME}",\n'
        ),
        new=(
            "        detail, read_error = self._read_marker()\n"
            "        if not detail and read_error is None:\n"
            "            return False  # MUTANT\n"
            "        self._restored = True\n"
            "        self.engage(\n"
            '            read_error or detail or f"persisted stop:{HOT_STOP_FILE_NAME}",\n'
        ),
        criterion="ACC-G1-08",
    ),
    Mutant(
        mutant_id="M7",
        description="restore blocks the boundary but leaves rule 0 disarmed",
        path=HOT_STOP_REL,
        old=(
            "            previous, activation_error = self._activate_switch(self._reason)\n"
            "            return self._ack(\n"
            "                run_id=run_id,\n"
            "                previous=previous,\n"
            "                repeated=False,\n"
        ),
        new=(
            "            previous, activation_error = self._state_name(), None  # MUTANT\n"
            "            return self._ack(\n"
            "                run_id=run_id,\n"
            "                previous=previous,\n"
            "                repeated=False,\n"
        ),
        criterion="ACC-G1-03",
    ),
    Mutant(
        mutant_id="M8",
        description="a restored stop is recorded as an ordinary hot engage",
        path=HOT_STOP_REL,
        old=("        detail, read_error = self._read_marker()\n        self._restored = True\n"),
        new="        detail, read_error = self._read_marker()\n",
        criterion="ACC-G1-03",
    ),
)


class AnchorError(RuntimeError):
    pass


@dataclass
class VariantResult:
    variant: str
    description: str
    criterion: str
    exit_code: int
    killed: bool
    duration_s: float
    failing_tests: list[str] = field(default_factory=list)


def _run(cmd: list[str], *, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=900)


def _env_for(src_dir: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(src_dir)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("PYTEST_ADDOPTS", None)
    return env


def _preflight(tree: Path, src_dir: Path) -> None:
    """Prove the interpreter will import the tree this variant is testing."""
    completed = _run(
        [sys.executable, "-c", "import trading_bot; print(trading_bot.__file__)"],
        cwd=tree,
        env=_env_for(src_dir),
    )
    if completed.returncode != 0:
        raise RuntimeError(f"preflight import failed: {completed.stderr[-600:]}")
    imported = Path(completed.stdout.strip()).resolve()
    expected = (src_dir / "trading_bot").resolve()
    if expected not in imported.parents:
        raise RuntimeError(
            "TEST_TARGET != RUNTIME_TARGET: imported "
            f"{imported} instead of something under {expected}"
        )


def _pytest(tree: Path, src_dir: Path) -> tuple[int, list[str], str]:
    completed = _run(
        [
            sys.executable,
            "-m",
            "pytest",
            *TARGET_TESTS,
            "-q",
            "--tb=no",
            "-rf",
            "-p",
            "no:cacheprovider",
        ],
        cwd=tree,
        env=_env_for(src_dir),
    )
    failing = [
        line.split(" - ", 1)[0].strip()
        for line in completed.stdout.splitlines()
        if line.startswith("FAILED ")
    ]
    return completed.returncode, failing, completed.stdout[-2000:]


def _apply(text: str, mutant: Mutant) -> str:
    occurrences = text.count(mutant.old)
    if occurrences != 1:
        raise AnchorError(
            f"{mutant.mutant_id}: anchor matched {occurrences} times in {mutant.path}, "
            "expected exactly 1. The code has drifted; update the mutant, do not "
            "weaken this check."
        )
    mutated = text.replace(mutant.old, mutant.new)
    if mutated == text or mutant.old in mutated:
        raise AnchorError(f"{mutant.mutant_id}: replacement did not remove the anchor")
    return mutated


def _export_rev(rev: str, destination: Path) -> None:
    archive = destination / "tree.tar"
    completed = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "archive", "--format=tar", "-o", str(archive), rev],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"git archive {rev} failed: {completed.stderr[-600:]}")
    with tarfile.open(archive) as tar:
        try:
            tar.extractall(destination / "tree", filter="data")
        except TypeError:  # Python < 3.11.4 has no extraction filters
            tar.extractall(destination / "tree")


def _prepare_tree(source: str, rev: str, destination: Path) -> tuple[Path, str]:
    tree = destination / "tree"
    if source == "worktree":
        shutil.copytree(REPO_ROOT, tree, ignore=_COPY_IGNORE, symlinks=True)
        return tree, "worktree (uncommitted)"
    _export_rev(rev, destination)
    return tree, rev


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rev", default="HEAD", help="revision to export (default: HEAD)")
    parser.add_argument(
        "--source",
        choices=("rev", "worktree"),
        default="rev",
        help="test a committed revision or the current working tree",
    )
    parser.add_argument(
        "--json", dest="json_path", default=None, help="write the full matrix as JSON"
    )
    parser.add_argument(
        "--keep", action="store_true", help="keep the temporary export for inspection"
    )
    args = parser.parse_args(argv)

    started = time.time()
    results: list[VariantResult] = []
    report: dict[str, Any] = {
        "tool": "scripts/audit/g1_mutants.py",
        "criterion": "G-1 ACC-G1-11",
        "source": args.source,
        "rev": args.rev,
        "target_tests": list(TARGET_TESTS),
        "python": sys.version.split()[0],
    }

    tmp = Path(tempfile.mkdtemp(prefix="g1-mutants-"))
    try:
        tree, label = _prepare_tree(args.source, args.rev, tmp)
        report["resolved_source"] = label
        if args.source == "rev":
            resolved = subprocess.run(
                ["git", "-C", str(REPO_ROOT), "rev-parse", f"{args.rev}^{{commit}}"],
                capture_output=True,
                text=True,
                timeout=120,
            )
            report["resolved_rev"] = resolved.stdout.strip()

        _preflight(tree, tree / "src")
        baseline_started = time.time()
        code, failing, tail = _pytest(tree, tree / "src")
        results.append(
            VariantResult(
                variant="baseline",
                description="unmutated tree (control)",
                criterion="ACC-G1-12",
                exit_code=code,
                killed=False,
                duration_s=round(time.time() - baseline_started, 2),
                failing_tests=failing,
            )
        )
        report["baseline"] = results[0].__dict__
        if code != 0:
            report["baseline_tail"] = tail
            print(f"BASELINE FAILED (exit {code}); refusing to score mutants.", file=sys.stderr)
            print(tail, file=sys.stderr)
            _write_json(args.json_path, report, results, started)
            return 1

        originals = {}
        for mutant in MUTANTS:
            originals.setdefault(mutant.path, (tree / mutant.path).read_text(encoding="utf-8"))

        for mutant in MUTANTS:
            variant_dir = tmp / "variants" / mutant.mutant_id
            variant_dir.mkdir(parents=True)
            shutil.copytree(tree / "src", variant_dir / "src", symlinks=True)
            target = variant_dir / mutant.path
            target.write_text(_apply(originals[mutant.path], mutant), encoding="utf-8", newline="")
            _preflight(tree, variant_dir / "src")

            mutant_started = time.time()
            code, failing, tail = _pytest(tree, variant_dir / "src")
            results.append(
                VariantResult(
                    variant=mutant.mutant_id,
                    description=mutant.description,
                    criterion=mutant.criterion,
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
        _write_json(args.json_path, report, results, started)
        return 1
    finally:
        if args.keep:
            print(f"temporary export kept at {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)

    _write_json(args.json_path, report, results, started)

    print(f"{'variant':<10} {'killed':<7} {'exit':<5} {'sec':>6}  description")
    for result in results:
        print(
            f"{result.variant:<10} "
            f"{('n/a' if result.variant == 'baseline' else ('yes' if result.killed else 'NO')):<7} "
            f"{result.exit_code:<5} {result.duration_s:>6}  {result.description}"
        )
        for test in result.failing_tests[:3]:
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
        f"\nbaseline green; {len(MUTANTS)}/{len(MUTANTS)} mutants killed in {time.time() - started:.1f}s"
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
