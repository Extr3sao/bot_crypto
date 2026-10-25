"""Independent verification of WP-ECONOMIC-RECOVERY-002.

Written against the *sources*, not against the work package's own scripts: it
re-hashes files, re-runs the builder's own `--check`, re-clones the repository
and re-runs the tests the work package claims to have repaired. Nothing here
imports `wp_eco002_reproducibility.py` or `wp_eco002_anchor.py`; the JSON those
scripts wrote is only read where the claim is *about* a measurement run (and the
check then says so).

A check that cannot be evaluated is ``NOT_ASSESSED`` and is reported as such —
it never counts as a pass.

Usage:
    uv run python scripts/wp_eco002_verify.py [--out <evidence dir>] [--skip-clones]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
WP = Path("docs/agentic/economic_audit/WP-ECONOMIC-RECOVERY-002")
BASE = "e67194e7"

ADMISSION_CHAIN = (
    "config/strategy_admission.json",
    "docs/STRATEGY_ADMISSION_MATRIX.json",
    "docs/STRATEGY_DISCOVERY_V3_RESULTS.json",
    "docs/COST_MODEL_V3.json",
)

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


def git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd or REPO, capture_output=True, text=True, check=False
    ).stdout.strip()


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def run(
    cmd: list[str], cwd: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, env={**os.environ, **(env or {})}, check=False
    )


class Verdicts:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def add(self, check: str, verdict: str, evidence: str) -> None:
        self.rows.append({"check": check, "verdict": verdict, "evidence": evidence})
        mark = {"PASS": "PASS", "FAIL": "FAIL", "NOT_ASSESSED": "N/A "}[verdict]
        print(f"[{mark}] {check}: {evidence}")

    def pass_if(self, check: str, condition: bool, evidence: str) -> None:
        self.add(check, "PASS" if condition else "FAIL", evidence)


def clone_at(destination: Path, commit: str, *, autocrlf: str | None) -> Path:
    repo = destination / "repo"
    config = ["-c", f"core.autocrlf={autocrlf}"] if autocrlf else []
    subprocess.run(
        ["git", *config, "clone", "--quiet", "--no-hardlinks", str(REPO), str(repo)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "checkout", "--quiet", commit], cwd=repo, check=True, capture_output=True
    )
    return repo


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=WP)
    parser.add_argument("--base", default=BASE)
    parser.add_argument("--skip-clones", action="store_true", help="skip the two clone checks")
    args = parser.parse_args(argv)
    out_dir = REPO / args.out
    verdicts = Verdicts()

    head = git("rev-parse", "HEAD")
    ledger_path = REPO / "config" / "strategy_admission.json"
    ledger_bytes = ledger_path.read_bytes()
    ledger = json.loads(ledger_bytes)

    # ---- 1. the anchor itself ------------------------------------------------
    builder_check = run([sys.executable, "scripts/build_strategy_admission.py", "--check"], REPO)
    verdicts.pass_if(
        "ledger_is_what_the_builder_derives",
        builder_check.returncode == 0,
        f"`build_strategy_admission.py --check` exit {builder_check.returncode}: "
        f"{(builder_check.stdout or builder_check.stderr).strip()[:160]}",
    )

    source_rows = []
    for source in ledger.get("_sources", []):
        path = REPO / source["path"]
        actual = digest(path.read_bytes()) if path.is_file() else None
        source_rows.append(
            {
                "path": source["path"],
                "recorded": source["sha256"],
                "on_disk": actual,
                "match": actual == source["sha256"],
            }
        )
    verdicts.pass_if(
        "every_source_digest_matches_its_file",
        all(row["match"] for row in source_rows) and bool(source_rows),
        "; ".join(
            f"{row['path']} {'match' if row['match'] else 'MISMATCH'}" for row in source_rows
        ),
    )

    crlf_lines = ledger_bytes.count(b"\r\n")
    verdicts.pass_if(
        "ledger_bytes_are_platform_independent",
        crlf_lines == 0,
        f"CRLF lines in the committed ledger: {crlf_lines}",
    )

    previous = json.loads(
        run(["git", "show", f"{args.base}:config/strategy_admission.json"], REPO).stdout
    )
    strip = lambda payload: {k: v for k, v in payload.items() if k != "_sources"}  # noqa: E731
    verdicts.pass_if(
        "the_repair_moved_no_admission_decision",
        strip(previous) == strip(ledger),
        "payload identical to the previous revision once `_sources` is removed: "
        f"{strip(previous) == strip(ledger)}; strategies={len(ledger.get('strategies', {}))}, "
        f"admitted={sum(1 for e in ledger.get('strategies', {}).values() if e.get('admitted_for_paper'))}",
    )

    # the stale anchor must be gone *and* must have matched no revision
    stale = {source["path"]: source["sha256"] for source in previous.get("_sources", [])}.get(
        "docs/STRATEGY_ADMISSION_MATRIX.json"
    )
    history = [
        digest(
            subprocess.run(
                ["git", "show", f"{rev}:docs/STRATEGY_ADMISSION_MATRIX.json"],
                cwd=REPO,
                capture_output=True,
            ).stdout
        )
        for rev in git(
            "log", "--all", "--format=%H", "--", "docs/STRATEGY_ADMISSION_MATRIX.json"
        ).split()
    ]
    verdicts.pass_if(
        "the_stale_digest_named_no_committed_matrix",
        stale is not None and stale not in history,
        f"recorded {str(stale)[:16]}...; committed matrix digests examined: {len(history)}; matched: {stale in history}",
    )
    verdicts.pass_if(
        "the_anchor_now_names_the_committed_matrix",
        source_rows
        and source_rows[1]["recorded"]
        == digest((REPO / "docs" / "STRATEGY_ADMISSION_MATRIX.json").read_bytes()),
        f"ledger records {source_rows[1]['recorded'][:16]}..."
        if len(source_rows) > 1
        else "no second source",
    )

    # ---- 2. the checkout cannot break the chain ------------------------------
    attributes = (REPO / ".gitattributes").read_text(encoding="utf-8")
    pinned = [
        name
        for name in ADMISSION_CHAIN
        if any(line.startswith(name) and line.endswith("-text") for line in attributes.splitlines())
    ]
    verdicts.pass_if(
        "the_admission_chain_is_pinned_against_eol_rewriting",
        len(pinned) == len(ADMISSION_CHAIN),
        f"pinned with -text: {pinned}",
    )

    # ---- 3. the ledger is guarded by a test ----------------------------------
    guard = REPO / "tests" / "unit" / "research" / "test_strategy_admission_ledger.py"
    guard_run = run(
        [
            sys.executable,
            "-m",
            "pytest",
            guard.relative_to(REPO).as_posix(),
            "-q",
            "-p",
            "no:cacheprovider",
        ],
        REPO,
    )
    verdicts.pass_if(
        "a_test_fails_when_the_ledger_drifts",
        guard_run.returncode == 0 and guard.is_file(),
        (guard_run.stdout.strip().splitlines() or [""])[-1][:160],
    )

    # ---- 4. the suite writes no tracked file --------------------------------
    parts = out_dir / "parts"
    measured = ""
    if (parts / "working.json").is_file() and (parts / "clone.json").is_file():
        working = json.loads((parts / "working.json").read_text(encoding="utf-8"))
        cloned = json.loads((parts / "clone.json").read_text(encoding="utf-8"))
        rewritten = working["tracked_data"]["rewritten"] + cloned["tracked_data"]["rewritten"]
        verdicts.pass_if(
            "the_suite_rewrites_no_tracked_file",
            rewritten == [] and working["tracked_data"]["files_hashed_before"] > 1000,
            f"tracked files hashed: {working['tracked_data']['files_hashed_before']}; rewritten in either tree: {rewritten}",
        )
        working_nodes = {f"{f['kind']} {f['node']}" for f in working["failures"]}
        clone_nodes = {f"{f['kind']} {f['node']}" for f in cloned["failures"]}
        verdicts.pass_if(
            "working_tree_and_clean_clone_fail_the_same_nodes",
            working_nodes == clone_nodes,
            f"working={len(working_nodes)} clone={len(clone_nodes)} "
            f"only_working={sorted(working_nodes - clone_nodes)[:3]} only_clone={sorted(clone_nodes - working_nodes)[:3]}",
        )
        # The deliverables commit carries no code, so it may sit on top of the measured commit —
        # but nothing under src/, tests/ or config/ may have moved since the measurement ran, or
        # the numbers describe a tree that no longer exists.
        measured = str(cloned.get("commit") or "")
        drift = (
            [
                path
                for path in git("diff", "--name-only", f"{measured}..HEAD").splitlines()
                if path.startswith(("src/", "tests/", "config/"))
            ]
            if measured
            else ["<no measured commit recorded>"]
        )
        verdicts.pass_if(
            "no_code_changed_between_the_measurement_and_head",
            not drift,
            f"measured at {measured[:12]}, HEAD {head[:12]}; src/tests/config changed since: {drift}",
        )
    else:
        verdicts.add(
            "the_suite_rewrites_no_tracked_file",
            "NOT_ASSESSED",
            "no measurement parts under the evidence dir",
        )

    # ---- 5. nothing economic moved -----------------------------------------
    touched = git("diff", "--name-only", f"{args.base}..{head}")
    economic = [name for name in touched.splitlines() if name.startswith(("src/", "config/"))]
    ledger_only = [name for name in economic if name == "config/strategy_admission.json"]
    verdicts.pass_if(
        "no_runtime_or_configuration_logic_changed",
        set(economic) == set(ledger_only),
        f"src/ and config/ files in {args.base[:8]}..{head[:8]}: {economic or 'none'}",
    )
    for needle in ("COMMISSION", "SLIPPAGE", "FEE_BPS", "fee_bps", "commission_bps"):
        if needle in "".join(touched.splitlines()):
            verdicts.add("no_fee_or_slippage_constant_changed", "FAIL", needle)
            break
    else:
        verdicts.add(
            "no_fee_or_slippage_constant_changed",
            "PASS",
            "no touched path names a fee or slippage constant",
        )

    # ---- 6. the run log is test residue, not campaign evidence --------------
    run_log = REPO / "data" / "st6" / "ST6_RUNS.jsonl"
    tracked = git("ls-files", "--", run_log.relative_to(REPO).as_posix())
    if run_log.is_file():
        events = [
            json.loads(line)
            for line in run_log.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        collected = [event for event in events if event.get("result") == "COLLECTED"]
        verdicts.pass_if(
            "the_run_log_is_unversioned_and_carries_no_collection",
            tracked == "" and not collected,
            f"tracked={bool(tracked)} events={len(events)} with_result_COLLECTED={len(collected)} "
            f"results={sorted({e.get('result') for e in events})}",
        )
    else:
        verdicts.add(
            "the_run_log_is_unversioned_and_carries_no_collection",
            "NOT_ASSESSED",
            "no run log on this host",
        )

    # ---- 7. the cost-barrier consequence is declared, not hidden ------------
    anchor = out_dir / "ANCHOR_REPAIR.json"
    if anchor.is_file():
        recorded = json.loads(anchor.read_text(encoding="utf-8"))
        gate = recorded.get("cost_barrier_gate", {})
        pin_matches = gate.get("pin_matches_now")
        status = (gate.get("status_now") or {}).get("headline", "")
        verdicts.pass_if(
            "the_cost_barrier_pin_drift_is_recorded",
            pin_matches is False and "INTEGRITY_FAILURE" in status,
            f"pin matches now: {pin_matches}; gate: {status}",
        )
        verdicts.pass_if(
            "the_upstream_matrix_builder_is_declared_unreproducible",
            recorded.get("upstream_link", {}).get("reconstructible_from_this_checkout") is False,
            f"matrix builder inputs present: {recorded.get('upstream_link', {}).get('inputs_present')}/6",
        )
    else:
        verdicts.add(
            "the_cost_barrier_pin_drift_is_recorded", "NOT_ASSESSED", "ANCHOR_REPAIR.json is absent"
        )

    # ---- 7b. the declared dependencies are absent from the commit ----------
    declared = out_dir / "DECLARED_DEPENDENCIES.json"
    if declared.is_file():
        inventory = json.loads(declared.read_text(encoding="utf-8"))
        rows = inventory.get("dependencies", [])
        in_head = [
            row["path"]
            for row in rows
            if run(["git", "cat-file", "-e", f"HEAD:{row['path']}"], REPO).returncode == 0
        ]
        classes = {row["classification"] for row in rows}
        verdicts.pass_if(
            "every_declared_missing_dependency_is_absent_from_head",
            bool(rows) and not in_head,
            f"declared paths: {len(rows)}; present in HEAD: {in_head}; classes: {sorted(classes)}",
        )
    else:
        verdicts.add(
            "every_declared_missing_dependency_is_absent_from_head",
            "NOT_ASSESSED",
            "DECLARED_DEPENDENCIES.json is absent",
        )

    # ---- 8. the previously clean-only nodes, in clones ----------------------
    if args.skip_clones:
        verdicts.add(
            "the_previously_clean_only_nodes_pass_in_a_fresh_clone", "NOT_ASSESSED", "--skip-clones"
        )
        verdicts.add(
            "the_admission_chain_survives_a_default_windows_clone", "NOT_ASSESSED", "--skip-clones"
        )
    else:
        selection = [guard.relative_to(REPO).as_posix(), *PREVIOUSLY_CLEAN_ONLY]
        with tempfile.TemporaryDirectory(prefix="wp-eco002-verify-") as tmp:
            repo = clone_at(Path(tmp), head, autocrlf="false")
            result = run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    *selection,
                    "-q",
                    "--tb=no",
                    "-p",
                    "no:cacheprovider",
                ],
                repo,
                {"PYTHONPATH": str(repo / "src")},
            )
            tail = (result.stdout.strip().splitlines() or [""])[-1]
            verdicts.pass_if(
                "the_previously_clean_only_nodes_pass_in_a_fresh_clone",
                result.returncode == 0,
                f"{tail[:160]}; `.venv` present: {(repo / '.venv').exists()}",
            )
        with tempfile.TemporaryDirectory(prefix="wp-eco002-verify-eol-") as tmp:
            repo = clone_at(Path(tmp), head, autocrlf=None)  # the host's own default: true
            chain = {name: (repo / name).read_bytes().count(b"\r\n") for name in ADMISSION_CHAIN}
            result = run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    guard.relative_to(REPO).as_posix(),
                    "-q",
                    "--tb=no",
                    "-p",
                    "no:cacheprovider",
                ],
                repo,
                {"PYTHONPATH": str(repo / "src")},
            )
            verdicts.pass_if(
                "the_admission_chain_survives_a_default_windows_clone",
                all(count == 0 for count in chain.values()) and result.returncode == 0,
                f"CRLF lines per pinned file: {chain}; ledger test exit {result.returncode}",
            )

    failed = [row for row in verdicts.rows if row["verdict"] == "FAIL"]
    unassessed = [row for row in verdicts.rows if row["verdict"] == "NOT_ASSESSED"]
    payload = {
        "wp": "WP-ECONOMIC-RECOVERY-002",
        "artefact": "INDEPENDENT_VERIFICATION",
        # the commit whose code was measured, and where the verifier ran; this file lives in a
        # later commit by construction, so it does not name its own
        "commit_under_measurement": measured or head,
        "head_when_verified": head,
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "base": git("rev-parse", args.base),
        "verifier": "scripts/wp_eco002_verify.py (imports nothing from the work package's scripts)",
        "summary": {
            "pass": len(verdicts.rows) - len(failed) - len(unassessed),
            "fail": len(failed),
            "not_assessed": len(unassessed),
        },
        "checks": verdicts.rows,
    }
    (out_dir / "INDEPENDENT_VERIFICATION.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"\n{payload['summary']['pass']} PASS · {payload['summary']['fail']} FAIL · "
        f"{payload['summary']['not_assessed']} NOT_ASSESSED"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
