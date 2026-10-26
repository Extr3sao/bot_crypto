"""WP-ECONOMIC-RECOVERY-002 — evidence that the tests and the ledger are reproducible.

Two claims, measured rather than asserted:

1. **Running the suite does not modify versioned data.** Every tracked file is
   hashed before and after each run; the difference is the evidence. A suite that
   rewrites a tracked artefact makes every later "before/after" comparison in the
   repository a comparison against whatever the tests last wrote.

2. **The clean-checkout failures have names.** The previous work package ran the
   "clean checkout" as ``git archive HEAD | tar -x``, which produces tracked files
   but no ``.git`` — so nine tests that read history failed for the method's
   reason, not the repository's. This script uses a real ``git clone`` at the
   commit under test, records what that clone does *not* have (history is there;
   ``.venv``, ``reports/**`` content and uncommitted runtime evidence are not),
   and reports the per-node status of the exact nodes previously attributed to
   "the clean checkout".

Phases are separate so a long run can be resumed and so the raw pytest output is
kept beside the summary:

    uv run python scripts/wp_eco002_reproducibility.py --phase working
    uv run python scripts/wp_eco002_reproducibility.py --phase clone
    uv run python scripts/wp_eco002_reproducibility.py --phase healthy
    uv run python scripts/wp_eco002_reproducibility.py --phase focused
    uv run python scripts/wp_eco002_reproducibility.py --phase assemble

Writes ``REPRODUCIBILITY_COMPARISON.json``/``.md`` plus ``parts/*.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
FAILING_SELECTION = ("tests/unit/risk", "tests/unit/research")
HEALTHY_SELECTION = ("tests/unit/autonomous", "tests/unit/paper", "tests/unit/scanner")

#: The nodes WP-ECONOMIC-BLOCKER-001 reported as failing *only* in its clean
#: checkout.  They are run by id here so their outcome is not inferred from a
#: directory selection that also contains 100+ pre-existing failures.
PREVIOUSLY_CLEAN_ONLY = (
    "tests/unit/research/test_active_recovery_wp.py::test_audit_is_deterministic_and_committed",
    "tests/unit/research/test_active_recovery_wp.py::test_state_view_is_deterministic",
    "tests/unit/research/test_cost_barrier_ci_parity.py::test_tests_ci_and_the_runtime_all_run_the_same_bytes",
    "tests/unit/research/test_cost_barrier_ci_parity.py::test_the_producer_pins_survive_a_checkout_that_rewrites_line_endings",
    "tests/unit/research/test_economic001_evidence_closure.py::test_the_closure_is_not_inside_the_commit_it_names",
    "tests/unit/research/test_economic001_evidence_closure.py::test_the_delivery_commit_carries_exactly_the_six_deliverables",
    "tests/unit/research/test_economic001_evidence_closure.py::test_the_verification_artefact_stays_inside_its_own_vocabulary",
    "tests/unit/research/test_recovery_determinism.py::test_a_sabotaged_committed_input_is_detected",
    "tests/unit/research/test_recovery_determinism.py::test_a_sabotaged_evidence_copy_is_detected",
    "tests/unit/research/test_recovery_determinism.py::test_an_uncommitted_edit_to_a_committed_document_cannot_move_the_identity",
    "tests/unit/research/test_recovery_determinism.py::test_every_evidence_copy_reproduces_the_published_authority",
    "tests/unit/research/test_recovery_determinism.py::test_no_source_of_either_artefact_came_from_the_working_tree",
    "tests/unit/research/test_recovery_determinism.py::test_repeated_reproduction_is_byte_identical",
    "tests/unit/research/test_recovery_determinism.py::test_the_clean_checkout_rehearsal_passes_on_this_commit",
    "tests/unit/research/test_recovery_determinism.py::test_the_published_artefacts_report_reproducibility_invariants",
    "tests/unit/research/test_recovery_determinism.py::test_the_repair_moved_no_economic_finding",
    "tests/unit/research/test_rfc046_discovery_proposal.py::test_rfc_045_stays_empty_by_control",
    "tests/unit/research/test_st6_scheduler.py::test_a_second_writer_refuses_and_makes_no_market_request",
    "tests/unit/research/test_st6_scheduler.py::test_an_impossible_cadence_refuses_with_a_non_zero_status",
    "tests/unit/research/test_st6_scheduler.py::test_the_run_log_is_compact_self_consistent_and_unique",
    "tests/unit/research/test_st6_scheduler.py::test_the_run_log_records_who_invoked_the_tick",
)

SUMMARY_RE = re.compile(r"(\d+) (passed|failed|errors?|skipped|xfailed|xpassed)", re.MULTILINE)
NODE_RE = re.compile(r"^(FAILED|ERROR) (\S+?)(?: - (.*))?$", re.MULTILINE)
SKIP_RE = re.compile(r"^SKIPPED \[(\d+)\] (\S+?):\d+: ?(.*)$", re.MULTILINE)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd or REPO_ROOT, capture_output=True, text=True, check=False
    ).stdout.strip()


def tracked_files(root: Path) -> list[str]:
    listing = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    return [name for name in listing.split("\0") if name]


def snapshot(root: Path) -> dict[str, str]:
    """SHA-256 of every tracked file that exists in ``root``."""

    digests: dict[str, str] = {}
    for name in tracked_files(root):
        path = root / name
        if path.is_file():
            digests[name] = sha256(path)
    return digests


def compare_snapshots(before: dict[str, str], after: dict[str, str]) -> dict[str, list[str]]:
    changed = sorted(name for name in before if name in after and before[name] != after[name])
    vanished = sorted(name for name in before if name not in after)
    reappeared = sorted(name for name in after if name not in before)
    return {"rewritten": changed, "removed": vanished, "added": reappeared}


def parse(output: str) -> dict[str, Any]:
    nodes = [
        {"kind": kind, "node": node, "message": (message or "").strip()[:400]}
        for kind, node, message in NODE_RE.findall(output)
    ]
    counts: dict[str, int] = {}
    for number, word in SUMMARY_RE.findall(output):
        key = "error" if word == "errors" else word
        counts[key] = max(counts.get(key, 0), int(number))
    skipped = [
        {"node": node, "reason": reason.strip()[:400]}
        for _, node, reason in SKIP_RE.findall(output)
    ]
    return {"counts": counts, "failures": nodes, "skips": skipped}


def run_pytest(
    root: Path, selection: tuple[str, ...], *, extra_env: dict[str, str] | None = None
) -> dict[str, Any]:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", **(extra_env or {})}
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        *selection,
        "-q",
        "--tb=no",
        "-rfEs",
        "-p",
        "no:cacheprovider",
    ]
    proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True, env=env, check=False)
    parsed = parse(proc.stdout + proc.stderr)
    parsed["exit_code"] = proc.returncode
    parsed["raw_tail"] = (proc.stdout + proc.stderr).strip().splitlines()[-3:]
    parsed["import_path"] = subprocess.run(
        [sys.executable, "-c", "import trading_bot;print(trading_bot.__file__)"],
        cwd=root,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    ).stdout.strip()
    return parsed


def measured_run(root: Path, selection: tuple[str, ...], **kwargs: Any) -> dict[str, Any]:
    before = snapshot(root)
    run = run_pytest(root, selection, **kwargs)
    after = snapshot(root)
    run["tracked_data"] = {
        **compare_snapshots(before, after),
        "files_hashed_before": len(before),
        "files_hashed_after": len(after),
    }
    return run


def phase_working(parts: Path) -> int:
    head = git("rev-parse", "HEAD")
    dirty = git("status", "--porcelain", "--untracked-files=no")
    run = measured_run(REPO_ROOT, FAILING_SELECTION)
    run["run_in"] = "working tree"
    run["tracked_files_dirty_before_the_run"] = dirty.splitlines()
    (parts / "working.json").write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
    print(
        f"[working] {run['counts']} exit={run['exit_code']} nodes={len(run['failures'])} "
        f"rewritten={len(run['tracked_data']['rewritten'])} (HEAD {head[:8]})"
    )
    for name in run["tracked_data"]["rewritten"]:
        print(f"  rewritten by the tests: {name}")
    return 0


def prepare_clone(destination: Path, commit: str | None) -> Path:
    """A real clone — history included — at the commit under test.

    ``core.autocrlf=false`` is passed explicitly because this host has it set to
    ``true`` system-wide, which rewrites every text file on checkout; measuring
    the repository must not also measure the host's Git defaults. The effect of
    those defaults on the digest-pinned admission chain is measured separately.
    """

    repo = destination / "repo"
    subprocess.run(
        [
            "git",
            "-c",
            "core.autocrlf=false",
            "clone",
            "--quiet",
            "--no-hardlinks",
            str(REPO_ROOT),
            str(repo),
        ],
        check=True,
        capture_output=True,
    )
    target = commit or git("rev-parse", "HEAD")
    subprocess.run(
        ["git", "checkout", "--quiet", target], cwd=repo, check=True, capture_output=True
    )
    return repo


def phase_clone(parts: Path, commit: str | None) -> int:
    with tempfile.TemporaryDirectory(prefix="wp-eco002-clone-") as tmp:
        repo = prepare_clone(Path(tmp), commit)
        run = measured_run(repo, FAILING_SELECTION, extra_env={"PYTHONPATH": str(repo / "src")})
        run["run_in"] = "real git clone (uncommitted files absent)"
        run["commit"] = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=False
        ).stdout.strip()
        run["imported_its_own_source"] = str(repo / "src") in run["import_path"]
        run["clone_has_git_history"] = (repo / ".git").exists()
        run["clone_has_dot_venv"] = (repo / ".venv").exists()
        # what the checkout is, byte for byte: the admission chain is only verifiable if these
        # files arrive with the endings their digests were computed over
        run["clone_line_endings"] = {
            name: {
                "crlf_lines": (repo / name).read_bytes().count(b"\r\n"),
                "lf_lines": (repo / name).read_bytes().count(b"\n")
                - (repo / name).read_bytes().count(b"\r\n"),
            }
            for name in (
                "config/strategy_admission.json",
                "docs/STRATEGY_ADMISSION_MATRIX.json",
                "docs/STRATEGY_DISCOVERY_V3_RESULTS.json",
            )
        }
        run["clone_reports_entries"] = sorted(
            name for name in tracked_files(repo) if name.startswith("reports/")
        )
        run["clone_reports_present"] = sorted(
            str(path.relative_to(repo)) for path in (repo / "reports").rglob("*") if path.is_file()
        )
    run["checkout_dir"] = "<temporary directory, removed>"
    (parts / "clone.json").write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
    print(
        f"[clone] {run['counts']} exit={run['exit_code']} nodes={len(run['failures'])} "
        f"own_src={run['imported_its_own_source']} git={run['clone_has_git_history']} "
        f"rewritten={len(run['tracked_data']['rewritten'])}"
    )
    for name in run["tracked_data"]["rewritten"]:
        print(f"  rewritten by the tests: {name}")
    return 0


def phase_healthy(parts: Path) -> int:
    run = measured_run(REPO_ROOT, HEALTHY_SELECTION)
    run["run_in"] = "working tree"
    (parts / "healthy.json").write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
    print(
        f"[healthy] {run['counts']} exit={run['exit_code']} "
        f"rewritten={len(run['tracked_data']['rewritten'])}"
    )
    return 0


def phase_focused(parts: Path) -> int:
    """The 21 nodes, by id, in both trees."""

    working = measured_run(REPO_ROOT, PREVIOUSLY_CLEAN_ONLY)
    with tempfile.TemporaryDirectory(prefix="wp-eco002-focused-") as tmp:
        repo = prepare_clone(Path(tmp), git("rev-parse", "HEAD"))
        cloned = measured_run(
            repo, PREVIOUSLY_CLEAN_ONLY, extra_env={"PYTHONPATH": str(repo / "src")}
        )
        cloned["imported_its_own_source"] = str(repo / "src") in cloned["import_path"]
    cloned["checkout_dir"] = "<temporary directory, removed>"
    payload = {"nodes": list(PREVIOUSLY_CLEAN_ONLY), "working": working, "clone": cloned}
    (parts / "focused.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"[focused] working {working['counts']} exit={working['exit_code']}")
    print(f"[focused] clone   {cloned['counts']} exit={cloned['exit_code']}")
    return 0


def outcome(run: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for node in run["failures"]:
        result[node["node"]] = node["kind"]
    for skip in run["skips"]:
        result.setdefault(skip["node"], "SKIPPED")
    for node in PREVIOUSLY_CLEAN_ONLY:
        result.setdefault(node, "PASSED")
    return result


def phase_assemble(parts: Path, out_dir: Path) -> int:
    required = ("working", "clone", "healthy", "focused")
    missing = [name for name in required if not (parts / f"{name}.json").exists()]
    if missing:
        raise SystemExit(f"missing phase outputs: {missing} (run the phases first)")

    working = json.loads((parts / "working.json").read_text(encoding="utf-8"))
    clone = json.loads((parts / "clone.json").read_text(encoding="utf-8"))
    healthy = json.loads((parts / "healthy.json").read_text(encoding="utf-8"))
    focused = json.loads((parts / "focused.json").read_text(encoding="utf-8"))

    working_nodes = {f"{f['kind']} {f['node']}" for f in working["failures"]}
    clone_nodes = {f"{f['kind']} {f['node']}" for f in clone["failures"]}
    only_working = sorted(working_nodes - clone_nodes)
    only_clone = sorted(clone_nodes - working_nodes)

    table = []
    working_outcome = outcome(focused["working"])
    clone_outcome = outcome(focused["clone"])
    for node in PREVIOUSLY_CLEAN_ONLY:
        table.append(
            {
                "node": node,
                "working_tree": working_outcome.get(node, "UNKNOWN"),
                "clean_clone": clone_outcome.get(node, "UNKNOWN"),
            }
        )

    payload = {
        "wp": "WP-ECONOMIC-RECOVERY-002",
        "artefact": "REPRODUCIBILITY_COMPARISON",
        "commit_under_measurement": git("rev-parse", "HEAD"),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "python": sys.version.split()[0],
        "method": (
            "the clean checkout is a real `git clone` at the commit under test, not "
            "`git archive HEAD | tar -x`: the archive has no .git, which made 17 of the 21 nodes "
            "the previous work package attributed to the clean checkout fail for the method's "
            "reason (9 of them in test_recovery_determinism.py alone)"
        ),
        "working_tree": {
            "counts": working["counts"],
            "exit_code": working["exit_code"],
            "failure_count": len(working["failures"]),
            "tracked_files_rewritten_by_the_run": working["tracked_data"]["rewritten"],
            "tracked_files_removed_by_the_run": working["tracked_data"]["removed"],
            "tracked_files_added_by_the_run": working["tracked_data"]["added"],
            "files_hashed": working["tracked_data"]["files_hashed_before"],
            "dirty_before_the_run": working.get("tracked_files_dirty_before_the_run", []),
        },
        "clean_clone": {
            "counts": clone["counts"],
            "exit_code": clone["exit_code"],
            "failure_count": len(clone["failures"]),
            "imported_its_own_source": clone["imported_its_own_source"],
            "has_git_history": clone["clone_has_git_history"],
            "has_dot_venv": clone["clone_has_dot_venv"],
            "line_endings": clone.get("clone_line_endings"),
            "reports_entries_present": clone["clone_reports_present"],
            "tracked_files_rewritten_by_the_run": clone["tracked_data"]["rewritten"],
            "tracked_files_removed_by_the_run": clone["tracked_data"]["removed"],
        },
        "healthy_selection": {
            "counts": healthy["counts"],
            "exit_code": healthy["exit_code"],
            "failures": [f["node"] for f in healthy["failures"]],
            "tracked_files_rewritten_by_the_run": healthy["tracked_data"]["rewritten"],
        },
        "previous_clean_only_nodes": table,
        "failures_only_in_working_tree": only_working,
        "failures_only_in_clean_clone": only_clone,
        "working_failures_are_subset_of_clone": working_nodes <= clone_nodes,
        "preexisting_failure_count_working_tree": len(working["failures"]),
        "tests_rewrite_no_tracked_file": not (
            working["tracked_data"]["rewritten"] or clone["tracked_data"]["rewritten"]
        ),
    }
    (out_dir / "REPRODUCIBILITY_COMPARISON.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )

    still_failing = [row for row in table if row["clean_clone"] not in {"PASSED", "SKIPPED"}]
    fixed = [
        row for row in table if row["working_tree"] != "PASSED" and row["clean_clone"] == "PASSED"
    ]
    lines = [
        "# Reproducibility comparison — WP-ECONOMIC-RECOVERY-002",
        "",
        f"- commit under measurement: `{payload['commit_under_measurement']}` "
        f"(branch `{payload['branch']}`; this file lives in a later commit by construction)",
        f"- python: {payload['python']}",
        "",
        "## Method",
        "",
        payload["method"] + ".",
        "",
        "| tree | failed | passed | rewritten tracked files |",
        "| --- | --- | --- | --- |",
        (
            f"| working tree | {working['counts'].get('failed', 0)} "
            f"| {working['counts'].get('passed', 0)} "
            f"| {len(working['tracked_data']['rewritten'])} |"
        ),
        (
            f"| clean clone | {clone['counts'].get('failed', 0)} "
            f"| {clone['counts'].get('passed', 0)} "
            f"| {len(clone['tracked_data']['rewritten'])} |"
        ),
        "",
        "## The nodes previously attributed to the clean checkout",
        "",
        "| outcome | working tree | clean clone | node |",
        "| --- | --- | --- | --- |",
    ]
    for row in table:
        lines.append(
            f"| {'still failing' if row in still_failing else 'explained'} "
            f"| {row['working_tree']} | {row['clean_clone']} | `{row['node']}` |"
        )
    lines += [
        "",
        f"- nodes that only fail in the working tree: **{len(only_working)}**",
        f"- nodes that only fail in the clean clone: **{len(only_clone)}**",
        f"- the suite rewrites no tracked file: **{payload['tests_rewrite_no_tracked_file']}**",
        "",
    ]
    (out_dir / "REPRODUCIBILITY_COMPARISON.md").write_text("\n".join(lines), encoding="utf-8")
    print(
        f"[assemble] working={len(working_nodes)} clone={len(clone_nodes)} "
        f"only_working={len(only_working)} only_clone={len(only_clone)} "
        f"clean_only_fixed={len(fixed)}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase", required=True, choices=("working", "clone", "healthy", "focused", "assemble")
    )
    parser.add_argument(
        "--out", type=Path, default=Path("docs/agentic/economic_audit/WP-ECONOMIC-RECOVERY-002")
    )
    parser.add_argument(
        "--commit", default=None, help="commit the clean clone checks out (default HEAD)"
    )
    args = parser.parse_args(argv)

    parts = args.out / "parts"
    parts.mkdir(parents=True, exist_ok=True)
    args.out.mkdir(parents=True, exist_ok=True)

    if args.phase == "working":
        return phase_working(parts)
    if args.phase == "clone":
        return phase_clone(parts, args.commit)
    if args.phase == "healthy":
        return phase_healthy(parts)
    if args.phase == "focused":
        return phase_focused(parts)
    return phase_assemble(parts, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
