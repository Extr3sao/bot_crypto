"""Reproducible negative-control matrix for the kill-switch gate (MT-0004-R1).

Why this exists
---------------
MT-0003 proved that rule 0 works. It did not prove that the suite would notice
if rule 0 disappeared — the mutant was run once by hand and never committed, so
nobody could re-run it and nothing failed when the code drifted.

This script makes that check reproducible. It exports a git revision, runs the
target suites unmutated (they must pass), then removes or weakens one property
of the gate at a time and runs the same suites again. A mutant that survives is
a hole in the tests, and the script exits non-zero.

Every mutant is an exact string replacement that must match **exactly once** in
the exported file. If someone edits `decision.py` and the anchor drifts, the
script fails loudly instead of silently testing nothing — a mutant that never
applied is worse than a failing one, because it reports green.

Usage
-----
    uv run --frozen python scripts/audit/negative_controls.py            # HEAD
    uv run --frozen python scripts/audit/negative_controls.py --rev <sha>
    uv run --frozen python scripts/audit/negative_controls.py --source worktree
    uv run --frozen python scripts/audit/negative_controls.py --json out.json

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
DECISION_REL = "src/trading_bot/autonomous/decision.py"

#: The suites that must be sensitive to the gate. MT-0003's file is included on
#: purpose: a mutant may be killed by either suite, and the report says which.
TARGET_TESTS: tuple[str, ...] = (
    "tests/unit/autonomous/test_decision_kill_switch.py",
    "tests/unit/autonomous/test_kill_switch_negative.py",
)

#: Ignored when copying the working tree; a stale .venv inside the copy would
#: shadow the interpreter and test the wrong tree.
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
    """One property of the gate, removed by a single exact replacement."""

    mutant_id: str
    description: str
    old: str
    new: str
    criterion: str


MUTANTS: tuple[Mutant, ...] = (
    Mutant(
        mutant_id="M1",
        description="rule 0 removed from decide",
        old=(
            "        blocked = self._kill_switch_no_trade()\n"
            "        if blocked is not None:\n"
            "            return blocked\n"
            "        self._reject_advisory_risk_on_an_order(request)\n"
        ),
        new="        self._reject_advisory_risk_on_an_order(request)\n",
        criterion="AC-2",
    ),
    Mutant(
        mutant_id="M2",
        description="rule 0 removed from intend",
        old=(
            "        blocked = self._kill_switch_no_trade()\n"
            "        if blocked is not None:\n"
            "            return blocked\n"
            "        vetoes = [m for m in request.agent_messages if m.review_type is ReviewType.VETO]\n"
        ),
        new="        vetoes = [m for m in request.agent_messages if m.review_type is ReviewType.VETO]\n",
        criterion="AC-2",
    ),
    Mutant(
        mutant_id="M3",
        description="unreadable state fails OPEN instead of closed",
        old=(
            "        except Exception:  # a broken gate must never authorise\n"
            "            return self._no_trade(KILL_SWITCH_STATE_UNREADABLE, KILL_SWITCH_CLASSIFICATION)\n"
        ),
        new="        except Exception:\n            return None\n",
        criterion="AC-2",
    ),
    Mutant(
        mutant_id="M4",
        description="gate never blocks (plumbing kept, condition disabled)",
        old="        if active or state is not KillSwitchState.NORMAL:\n",
        new="        if False:  # mutant M4\n",
        criterion="AC-2",
    ),
    Mutant(
        mutant_id="M5",
        description="derived is_active flag no longer consulted",
        old="        if active or state is not KillSwitchState.NORMAL:\n",
        new="        if state is not KillSwitchState.NORMAL:\n",
        criterion="AC-2",
    ),
    Mutant(
        mutant_id="M6",
        description="unknown TRADING_BOT_KILL_SWITCH value boots NORMAL (fail open)",
        old="target=_ENV_KILL_SWITCH_STATES.get(raw, KillSwitchState.HALTED),",
        new="target=_ENV_KILL_SWITCH_STATES.get(raw, KillSwitchState.NORMAL),",
        criterion="AC-2",
    ),
)


class AnchorError(RuntimeError):
    """A mutant could not be applied exactly once — the gate code has drifted."""


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
    # Exactly one entry: if the caller's PYTHONPATH leaked in, the preflight
    # below would catch it, but keeping it clean makes the message honest.
    env["PYTHONPATH"] = str(src_dir)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("PYTEST_ADDOPTS", None)
    return env


def _preflight(tree: Path, src_dir: Path) -> None:
    """Prove the interpreter will import the tree this variant is testing."""
    env = _env_for(src_dir)
    completed = _run(
        [sys.executable, "-c", "import trading_bot; print(trading_bot.__file__)"],
        cwd=tree,
        env=env,
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
    env = _env_for(src_dir)
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
        env=env,
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
            f"{mutant.mutant_id}: anchor matched {occurrences} times in {DECISION_REL}, "
            "expected exactly 1. The gate code has drifted; update the mutant, do not "
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
        "tool": "scripts/audit/negative_controls.py",
        "criterion": "MT-0004-R1 AC-1/AC-2",
        "source": args.source,
        "rev": args.rev,
        "target_tests": list(TARGET_TESTS),
        "mutated_file": DECISION_REL,
        "python": sys.version.split()[0],
    }

    tmp = Path(tempfile.mkdtemp(prefix="mt0004-mutants-"))
    try:
        tree, label = _prepare_tree(args.source, args.rev, tmp)
        decision_path = tree / DECISION_REL
        original = decision_path.read_text(encoding="utf-8")
        report["resolved_source"] = label
        if args.source == "rev":
            resolved = subprocess.run(
                ["git", "-C", str(REPO_ROOT), "rev-parse", f"{args.rev}^{{commit}}"],
                capture_output=True,
                text=True,
                timeout=120,
            )
            report["resolved_rev"] = resolved.stdout.strip()

        # -- baseline: the unmutated tree must pass ---------------------------
        _preflight(tree, tree / "src")
        baseline_started = time.time()
        code, failing, tail = _pytest(tree, tree / "src")
        results.append(
            VariantResult(
                variant="baseline",
                description="unmutated tree (control)",
                criterion="AC-1",
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

        # -- mutants ----------------------------------------------------------
        for mutant in MUTANTS:
            variant_dir = tmp / "variants" / mutant.mutant_id
            variant_dir.mkdir(parents=True)
            shutil.copytree(tree / "src", variant_dir / "src", symlinks=True)
            target = variant_dir / "src" / "trading_bot" / "autonomous" / "decision.py"
            target.write_text(_apply(original, mutant), encoding="utf-8", newline="")
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
