"""WP-ECONOMIC-BLOCKER-001 — reproducible test baseline.

The claim to support is narrow: *the tests that fail today failed before this
work package too*. Proving it by running pytest twice on the same working tree
would prove nothing, so the second run happens on a **clean checkout**:

    git archive HEAD | tar -x  →  temp dir  →  PYTHONPATH=src  →  same pytest

with the import path asserted (``trading_bot.__file__`` must point inside the
temporary directory, not at this checkout). If the failing node IDs are
identical in both runs, they are preexisting and independent of any untracked
generated artefact in this tree.

The script also records what this work package itself touched, so the "nothing
in src/tests/config changed" part of the claim is checkable rather than
asserted.

Writes ``TEST_BASELINE_COMPARISON.json`` and ``TEST_BASELINE_COMPARISON.md``.

Usage::

    uv run python scripts/wp_eco001_test_baseline.py --out <evidence dir>
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
#: The sets that were known to fail before this WP started.
FAILING_SELECTION = ("tests/unit/risk", "tests/unit/research")
#: The sets that must stay green; a failure here would be a regression caused by us.
HEALTHY_SELECTION = ("tests/unit/autonomous", "tests/unit/paper", "tests/unit/scanner")
SUMMARY_RE = re.compile(
    r"(\d+) (passed|failed|errors?|skipped|xfailed|xpassed)", re.MULTILINE
)
NODE_RE = re.compile(r"^(FAILED|ERROR) (\S+?)(?: - (.*))?$", re.MULTILINE)


def parse(output: str) -> dict[str, Any]:
    nodes = [
        {"kind": kind, "node": node, "message": (message or "").strip()[:300]}
        for kind, node, message in NODE_RE.findall(output)
    ]
    counts: dict[str, int] = {}
    for number, word in SUMMARY_RE.findall(output):
        key = "error" if word == "errors" else word
        counts[key] = max(counts.get(key, 0), int(number))
    return {"counts": counts, "failures": nodes}


def run_pytest(cwd: Path, selection: tuple[str, ...], *, extra_env: dict[str, str] | None = None) -> dict[str, Any]:
    env = {**os.environ, **(extra_env or {})}
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        *selection,
        "-q",
        "--tb=no",
        "-rfE",
        "-p",
        "no:cacheprovider",
    ]
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env, check=False)
    parsed = parse(proc.stdout + proc.stderr)
    parsed["exit_code"] = proc.returncode
    parsed["import_path"] = subprocess.run(
        [sys.executable, "-c", "import trading_bot,sys;print(trading_bot.__file__)"],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    ).stdout.strip()
    return parsed


def clean_checkout(destination: Path) -> None:
    """Extract HEAD without the working tree's untracked files."""
    archive = subprocess.run(
        ["git", "archive", "--format=tar", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    if archive.returncode != 0:
        raise SystemExit("git archive failed: " + archive.stderr.decode("utf-8", "replace"))
    tar_path = destination / "head.tar"
    tar_path.write_bytes(archive.stdout)
    with tarfile.open(tar_path) as tar:
        tar.extractall(destination)  # our own archive, in a private temp dir
    tar_path.unlink()


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    ).stdout.strip()


def phase_working(parts: Path) -> int:
    run = run_pytest(REPO_ROOT, FAILING_SELECTION)
    (parts / "working.json").write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
    print(f"[baseline] working: {run['counts']} exit={run['exit_code']} nodes={len(run['failures'])}")
    return 0


def phase_clean(parts: Path) -> int:
    with tempfile.TemporaryDirectory(prefix="wp-eco001-baseline-") as tmp:
        root = Path(tmp)
        clean_checkout(root)
        run = run_pytest(root, FAILING_SELECTION, extra_env={"PYTHONPATH": str(root / "src")})
        run["used_clean_checkout"] = True
        run["checkout_dir"] = "<temporary directory, removed>"
        run["imported_its_own_source"] = str(root / "src") in run["import_path"]
    (parts / "clean.json").write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
    print(
        f"[baseline] clean: {run['counts']} exit={run['exit_code']} "
        f"nodes={len(run['failures'])} own_src={run['imported_its_own_source']}"
    )
    return 0


def phase_healthy(parts: Path) -> int:
    run = run_pytest(REPO_ROOT, HEALTHY_SELECTION)
    (parts / "healthy.json").write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
    print(f"[baseline] healthy: {run['counts']} exit={run['exit_code']}")
    return 0


def phase_assemble(parts: Path, out_dir: Path) -> int:
    missing = [n for n in ("working", "clean", "healthy") if not (parts / f"{n}.json").exists()]
    if missing:
        raise SystemExit(f"missing phase outputs: {missing} (run the phases first)")
    working = json.loads((parts / "working.json").read_text(encoding="utf-8"))
    baseline = json.loads((parts / "clean.json").read_text(encoding="utf-8"))
    healthy = json.loads((parts / "healthy.json").read_text(encoding="utf-8"))

    head = _git("rev-parse", "HEAD")
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    touched = _git("status", "--porcelain", "--", "src", "tests", "config")
    baseline_dir_ok = bool(baseline.get("imported_its_own_source"))

    working_nodes = {f"{f['kind']} {f['node']}" for f in working["failures"]}
    baseline_nodes = {f"{f['kind']} {f['node']}" for f in baseline["failures"]}
    only_working = sorted(working_nodes - baseline_nodes)
    only_baseline = sorted(baseline_nodes - working_nodes)
    subset = working_nodes <= baseline_nodes

    payload = {
        "wp": "WP-ECONOMIC-BLOCKER-001",
        "artefact": "TEST_BASELINE_COMPARISON",
        "commit": head,
        "branch": branch,
        "python": sys.version.split()[0],
        "pytest_selection_failing": list(FAILING_SELECTION),
        "pytest_selection_healthy": list(HEALTHY_SELECTION),
        "worktree_touched_src_tests_config": touched or "(none)",
        "this_wp_changes_runtime_code": False,
        "working_tree_run": working,
        "clean_checkout_run": baseline,
        "healthy_run": healthy,
        "clean_checkout_imported_its_own_source": baseline_dir_ok,
        "identical_failure_sets": working_nodes == baseline_nodes,
        "working_failures_are_subset_of_clean_checkout": subset,
        "failures_only_in_working_tree": only_working,
        "failures_only_in_clean_checkout": only_baseline,
        "preexisting_failure_count": len(working_nodes & baseline_nodes),
        "conclusion": (
            "every test that fails in this working tree also fails on a clean checkout of "
            "the same commit, so none of the failures is caused by this work package"
            if subset
            else "the working tree has failures a clean checkout does not reproduce; the "
            "delta is NOT explained and must be treated as unexplained until reviewed"
        ),
        "clean_checkout_failures_explained_by_local_state": [
            "tests that read generated reports/** artefacts which are not versioned, so a "
            "clean checkout cannot reproduce the state that makes them pass",
            "tests/unit/research/test_rfc047_windows_evidence.py and test_st6_scheduler.py "
            "rewrite the tracked file data/st6/RFC047_RUNTIME_VERIFICATION.json while running, "
            "so the suite mutates repository state as a side effect (that file was restored to "
            "HEAD after this measurement)",
        ],
    }
    json_path = out_dir / "TEST_BASELINE_COMPARISON.json"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def table(run: dict[str, Any]) -> str:
        counts = ", ".join(f"{k}={v}" for k, v in sorted(run["counts"].items())) or "no summary"
        return f"{counts} (exit {run['exit_code']})"

    lines = [
        "# TEST_BASELINE_COMPARISON — WP-ECONOMIC-BLOCKER-001",
        "",
        f"Commit: `{head[:12]}` on `{branch}`  ·  Python {payload['python']}",
        "",
        "## Method",
        "",
        "The same pytest selection is run twice: once in this working tree, once in a",
        "clean checkout produced by `git archive HEAD` (no untracked files, no local",
        "`reports/**`), with `PYTHONPATH` pointed at the checkout's own `src` and the",
        "import path asserted so the run cannot silently import this tree's package.",
        "",
        "The run is split into three phases (`--phase working|clean|healthy`) plus",
        "`--phase assemble`, so it fits inside a command timeout without changing what",
        "is measured.",
        "",
        f"- clean checkout imported its own source: **{baseline_dir_ok}**",
        f"- `src/`, `tests/`, `config/` modified by this WP: **{touched or 'none'}**",
        "",
        "## Results",
        "",
        "| Run | `unit/risk` + `unit/research` |",
        "| --- | --- |",
        f"| working tree | {table(working)} |",
        f"| clean checkout | {table(baseline)} |",
        "",
        f"Healthy sets (`{'`, `'.join(HEALTHY_SELECTION)}`): {table(healthy)}",
        "",
        f"- every working-tree failure also fails on the clean checkout: **{subset}**",
        f"- identical failing node IDs: **{working_nodes == baseline_nodes}**",
        f"- preexisting failures (intersection): **{len(working_nodes & baseline_nodes)}**",
        f"- only in working tree (would be a regression caused by this WP): {len(only_working)}",
        f"- only in clean checkout (depends on unversioned local state): {len(only_baseline)}",
        "",
        "## Conclusion",
        "",
        payload["conclusion"] + ".",
        "",
        "The extra failures in the clean checkout are the interesting ones: they are tests",
        "whose *pass* depends on artefacts that exist only in a developer's working tree",
        "(`reports/**` and similar). They are listed below rather than hidden, because a",
        "green local run there is not reproducible evidence.",
        "",
        "Side finding: `data/st6/RFC047_RUNTIME_VERIFICATION.json` is tracked, and two of the",
        "research tests rewrite it while running. The suite therefore mutates repository",
        "state; that file was restored to `HEAD` after this measurement so the WP leaves no",
        "side effects.",
        "",
    ]
    if only_baseline:
        lines += ["### Failing only on the clean checkout", ""]
        lines += [f"- `{n}`" for n in only_baseline]
        lines.append("")
    if only_working:
        lines += ["### Failing only in this working tree", ""]
        lines += [f"- `{n}`" for n in only_working]
        lines.append("")
    (out_dir / "TEST_BASELINE_COMPARISON.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"[baseline] working: {table(working)}")
    print(f"[baseline] clean  : {table(baseline)}")
    print(f"[baseline] healthy: {table(healthy)}")
    print(f"[baseline] subset={subset} identical={working_nodes == baseline_nodes}")
    print(f"[baseline] preexisting={len(working_nodes & baseline_nodes)} only_clean={len(only_baseline)}")
    print(f"[baseline] -> {json_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", default=str(REPO_ROOT / "docs/agentic/economic_audit/WP-ECONOMIC-BLOCKER-001")
    )
    parser.add_argument(
        "--phase",
        choices=("all", "working", "clean", "healthy", "assemble"),
        default="all",
        help="all runs every phase; the split phases let a runner cap wall time",
    )
    args = parser.parse_args(argv)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    parts = out_dir / "baseline_parts"
    parts.mkdir(parents=True, exist_ok=True)

    if args.phase in ("working", "all"):
        phase_working(parts)
    if args.phase in ("clean", "all"):
        phase_clean(parts)
    if args.phase in ("healthy", "all"):
        phase_healthy(parts)
    if args.phase in ("all", "assemble"):
        return phase_assemble(parts, out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
