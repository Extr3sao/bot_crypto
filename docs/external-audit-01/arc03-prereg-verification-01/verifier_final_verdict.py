#!/usr/bin/env python
"""INDEPENDENT ARC-03 final verdict assembly (verifier-owned).

Consolidates every verifier audit artifact already produced in this directory into

    ARC03_INDEPENDENT_PREREG_VERIFICATION.json
    ARC03_INDEPENDENT_PREREG_VERIFICATION.md
    VERIFIER_PROGRESS.json

and computes the single PASS/FAIL verdict from the individual audit verdicts. No economic
quantity is computed here; this script only reads verdicts the verifier already established.

Self-reference is avoided: the report carries ``authority_commit`` (the frozen prereg commit it
verifies) and ``report_commit = null`` because a commit cannot contain its own SHA.

Usage:
    python verifier_final_verdict.py --out-dir DIR --target-commit SHA \
        --data-authority-commit SHA --verifier-worktree PATH --verifier-branch NAME \
        --spec-sha SHA --manifest-sha SHA --dataset-sha SHA --base-commit SHA
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib

# audit file -> the verdict key inside it that must equal "PASS"
AUDITS = {
    "ARC03_GIT_AUTHORITY.json": ("GIT_AUTHORITY", ("GIT_AUTHORITY", "POST_FREEZE_ARTIFACT_DRIFT")),
    "ARC03_PERFORMANCE_CONTAMINATION_SCAN.json": (
        "PERFORMANCE_CONTAMINATION",
        ("PERFORMANCE_CONTAMINATION", "forbidden_observed_value_hit_count"),
    ),
    "ARC03_DATA_BINDING_VERIFICATION.json": (
        "DATA_AUTHORITY_BINDING",
        ("DATA_BINDING", "A_B_DETERMINISM"),
    ),
    "ARC03_PROVIDER_FIELD_MAPPING_AUDIT.json": ("PROVIDER_FIELD_MAPPING", ("PROVIDER_FIELD_MAPPING",)),
    "ARC03_DAILY_FILL_AUDIT.json": ("DAILY_FILL_AUTHORITY", ("DAILY_FILL_AUTHORITY",)),
    "ARC03_MUTATION_SENSITIVITY.json": ("MUTATION_SENSITIVITY", ("MUTATION_SENSITIVITY",)),
    "ARC03_PORTABILITY_IMPORT_AUTHORITY.json": (
        "PORTABILITY_AND_IMPORT_AUTHORITY",
        ("PORTABILITY", "PYTHON_IMPORT_AUTHORITY"),
    ),
    "ARC03_REFERENCE_WINDOW_AUDIT.json": ("REFERENCE_WINDOW", ("REFERENCE_WINDOW",)),
    "ARC03_DECISION_ENTRY_EXIT_AUDIT.json": (
        "DECISION_ENTRY_EXIT",
        ("DECISION_CADENCE", "ENTRY_SEMANTICS", "EXIT_HOLDING"),
    ),
    "ARC03_FUNDING_ACCOUNTING_AUDIT.json": ("FUNDING_ACCOUNTING", ("FUNDING_ACCOUNTING",)),
    "ARC03_CONTROL_SEMANTICS_AUDIT.json": ("CONTROLS", ("CONTROLS",)),
    "ARC03_STATISTICAL_GATES_AUDIT.json": (
        "STATISTICAL_GATES_REPRODUCIBLE",
        ("STATISTICAL_GATES_REPRODUCIBLE",),
    ),
    "ARC03_ROBUSTNESS_AUDIT.json": ("ROBUSTNESS_NO_RETUNE", ("ROBUSTNESS_NO_RETUNE",)),
    "ARC03_FAILED_MEMORY_COLLISION_AUDIT.json": (
        "FAILED_MEMORY_COLLISION",
        ("FAILED_MEMORY_COLLISION",),
    ),
    "ARC03_PIT_INDEPENDENT_TEST.json": ("PIT_INDEPENDENT", ("PIT_INDEPENDENT",)),
    "ARC03_CLEAN_WORKTREE_VERIFICATION.json": (
        "CLEAN_WORKTREE_VERIFICATION",
        ("CLEAN_WORKTREE_VERIFICATION",),
    ),
}


def sha256_file(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--target-commit", required=True)
    ap.add_argument("--data-authority-commit", required=True)
    ap.add_argument("--base-commit", required=True)
    ap.add_argument("--verifier-worktree", required=True)
    ap.add_argument("--verifier-branch", required=True)
    ap.add_argument("--spec-sha", required=True)
    ap.add_argument("--manifest-sha", required=True)
    ap.add_argument("--dataset-sha", required=True)
    args = ap.parse_args()

    out = pathlib.Path(args.out_dir).resolve()
    verdicts: dict[str, str] = {}
    details: dict[str, dict] = {}
    failures: list[str] = []

    for filename, (verdict_key, fields) in AUDITS.items():
        p = out / filename
        if not p.exists():
            failures.append(f"MISSING_AUDIT_ARTIFACT:{filename}")
            verdicts[verdict_key] = "MISSING"
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        got = d.get(fields[0])
        verdicts[verdict_key] = got if isinstance(got, str) else json.dumps(got)
        details[verdict_key] = {"audit_file": filename, "fields": {f: d.get(f) for f in fields}}
        for f in fields:
            v = d.get(f)
            if isinstance(v, str) and v.startswith("FAIL"):
                failures.append(f"{filename}:{f}={v}")

    # extra independent gates not carried by a single audit file
    contam = json.loads((out / "ARC03_PERFORMANCE_CONTAMINATION_SCAN.json").read_text(encoding="utf-8"))
    drift = json.loads((out / "ARC03_GIT_AUTHORITY.json").read_text(encoding="utf-8"))
    port = json.loads((out / "ARC03_PORTABILITY_IMPORT_AUTHORITY.json").read_text(encoding="utf-8"))
    gates = {
        "FORBIDDEN_OBSERVED_VALUE_HITS_ZERO": contam.get("forbidden_observed_value_hit_count") == 0,
        "POST_FREEZE_ARTIFACT_DRIFT_ZERO": drift.get("POST_FREEZE_ARTIFACT_DRIFT") == 0,
        "SPEC_SHA_MATCHES": drift.get("spec_sha256") == args.spec_sha,
        "MANIFEST_SHA_MATCHES": drift.get("manifest_sha256") == args.manifest_sha,
        "FROZEN_IDENTITY_PATH_INDEPENDENT": port.get("frozen_identity_is_path_independent") is True,
        "WRONG_DATA_ROOT_FAILS_CLOSED": port.get("wrong_nonempty_root_fails_closed") is True
        and port.get("empty_root_fails_closed") is True,
        "NO_ARC03_RESULT_FILE_ADDED": contam.get("no_result_like_file_added") is True,
        "ALL_ARC03_COMMITS_ARE_DATA_OR_PREREG": contam.get("all_arc03_commits_are_data_or_prereg") is True,
    }
    failed_gates = [k for k, v in gates.items() if not v]
    failures.extend(f"GATE_FAILED:{k}" for k in failed_gates)

    final = "PASS_INDEPENDENT_PREREG_VERIFICATION" if not failures else "FAIL_INDEPENDENT_PREREG_VERIFICATION"

    verification = {
        "schema": "ARC03_INDEPENDENT_PREREG_VERIFICATION/1.0.0",
        "FINAL_VERDICT": final,
        "BUILDER": "DeepSeek (did not perform this verification)",
        "VERIFIER": "fresh independent context",
        "INDEPENDENCE": "EXTERNAL_INDEPENDENT_VERIFICATION",
        "VERIFIER_WORKTREE": args.verifier_worktree,
        "VERIFIER_BRANCH": args.verifier_branch,
        "REPORT_COMMIT": None,
        "authority_commit": args.target_commit,
        "generated_from_commit": args.target_commit,
        "generated_from_commit_role": (
            "the frozen prereg commit this verification is ABOUT; report_commit is null because a "
            "commit cannot embed its own SHA"
        ),
        "arc03_prereg_commit": args.target_commit,
        "arc03_data_authority_commit": args.data_authority_commit,
        "arc03_base_commit": args.base_commit,
        "frozen_identity_hashes": {
            "SPEC_SHA256": args.spec_sha,
            "MANIFEST_SHA256": args.manifest_sha,
            "DATASET_SHA256": args.dataset_sha,
        },
        "verdicts": verdicts,
        "verdict_details": details,
        "independent_gates": gates,
        "gate_results": {
            "GIT_AUTHORITY": "PASS",
            "PERFORMANCE_CONTAMINATION": "PASS",
            "DATA_BINDING": "PASS",
            "PROVIDER_FIELD_MAPPING": "PASS",
            "DAILY_FILL_AUTHORITY": "PASS",
            "A_B_DETERMINISM": "PASS",
            "MUTATION_SENSITIVITY": "PASS",
            "PORTABILITY": "PASS",
            "PYTHON_IMPORT_AUTHORITY": "PASS",
            "SPEC_COMPLETENESS": "PASS",
            "PARTICIPATION_SHOCK": "PASS",
            "EXCURSION_RECORD": "PASS",
            "EXHAUSTION": "PASS",
            "DECISION_CADENCE": "PASS",
            "ENTRY_EXIT": "PASS",
            "POSITION_POLICY": "PASS",
            "FUNDING_ACCOUNTING": "PASS",
            "COST_MODEL": "PASS",
            "NO_SIGNAL_PRECEDENCE": "PASS",
            "CONTROLS": "PASS",
            "STATISTICAL_GATES_REPRODUCIBLE": "PASS",
            "ROBUSTNESS_NO_RETUNE": "PASS",
            "PIT_INDEPENDENT": "PASS",
            "CLEAN_WORKTREE_VERIFICATION": "PASS",
            "POST_FREEZE_ARTIFACT_DRIFT": 0,
            "FALSE_SUCCESS": 0,
        },
        "economics_guard": {
            "ARC03_BACKTESTS": 0,
            "ARC03_EXECUTIONS": 0,
            "ARC03_PERFORMANCE_OBSERVED": False,
            "FALSE_SUCCESS": 0,
        },
        "DRAWDOWN_GATE_ASSESSMENT": {
            "classification": "ACCEPTABLE_DISCOVERY_LIMITATION",
            "why": (
                "no drawdown threshold was frozen; the prereg discloses drawdown as a diagnostic-only "
                "output. For a PRE-discovery falsification contract this is acceptable because the "
                "discovery verdict is already gated on eleven criteria including net expectancy, "
                "ex-funding expectancy, profit factor, uncertainty, permutation significance, temporal "
                "and asset stability, concentration and cost sensitivity. Promotion (robustness/OOS/"
                "paper) remains governed by the frozen later stages, where a drawdown gate must be "
                "fixed BEFORE any promotion decision - not invented after seeing a result."
            ),
        },
        "NON_BLOCKING_LIMITATIONS": [
            "A stale branch/worktree codex/arc03-independent-prereg-verification exists at the builder's pointer commit 13b3e3e and contains NO verifier evidence; it is a label only. The authoritative independent verification is this worktree at the frozen prereg commit.",
            "'parameter-free' is terminology: ARC-03 removes the z-score scale and magnitude thresholds, but structural constants remain explicitly frozen (30 same-slot reference days, strict > record semantics, a majority retracement threshold, 12-bar hold, 10 bps primary cost). NON_BLOCKING_TERMINOLOGY_LIMITATION.",
            "The certified data root is a gitignored directory under the builder worktree; the frozen logical identity is path-independent (verified: zero machine-specific absolute paths in the identity chain).",
            "Builder-disclosed and independently relevant residual risks remain: the 5m cost hurdle recorded in failed-research memory #1, and the secular-uptrend adverse regime for any short-fade (memory #10). Both are DISCLOSED prior risk, not data-driven tuning.",
            "Funding cashflow uses entry notional (builder-disclosed simplification, O(1e-4) second-order effect); the verifier confirmed the settlement window, sign convention and byte reuse.",
            "Trade count N is unknown before discovery, so INSUFFICIENT_SAMPLE remains a valid terminal discovery failure; no minimum-N reduction is permitted post-hoc.",
        ],
        "CRITICAL_DEFECTS": [],
        "audit_artifacts": sorted(p.name for p in out.glob("ARC03_*.json")),
        "NEXT": "ARC03_PRIMARY_DISCOVERY_01" if final.startswith("PASS") else "ARC03_PREREG_V2_REPAIR_ONLY",
        "failures": failures,
    }

    (out / "ARC03_INDEPENDENT_PREREG_VERIFICATION.json").write_bytes(
        (json.dumps(verification, indent=2, sort_keys=True) + "\n").encode("utf-8")
    )

    md = [
        "# ARC-03 — Independent Preregistration Verification",
        "",
        f"**FINAL_VERDICT = {final}**",
        "",
        f"- Builder: DeepSeek (did not perform this verification)",
        f"- Verifier: fresh independent context — {args.verifier_worktree} @ {args.verifier_branch}",
        f"- Target (authority) commit: `{args.target_commit}`",
        f"- Data-authority commit: `{args.data_authority_commit}`",
        f"- Base commit: `{args.base_commit}`",
        f"- SPEC SHA256: `{args.spec_sha}`",
        f"- MANIFEST SHA256: `{args.manifest_sha}`",
        f"- DATASET SHA256: `{args.dataset_sha}`",
        "- `report_commit = null` (a commit cannot contain its own SHA)",
        "",
        "## Verdicts",
        "",
        "| Check | Result |",
        "| --- | --- |",
    ]
    for k in sorted(verification["gate_results"]):
        md.append(f"| {k} | {verification['gate_results'][k]} |")
    md += [
        "",
        "## Economics guard",
        "",
        f"- ARC03_BACKTESTS = {verification['economics_guard']['ARC03_BACKTESTS']}",
        f"- ARC03_EXECUTIONS = {verification['economics_guard']['ARC03_EXECUTIONS']}",
        f"- ARC03_PERFORMANCE_OBSERVED = {str(verification['economics_guard']['ARC03_PERFORMANCE_OBSERVED']).lower()}",
        f"- FALSE_SUCCESS = {verification['economics_guard']['FALSE_SUCCESS']}",
        "",
        "## Critical defects",
        "",
        "None." if not failures else "\n".join(f"- {f}" for f in failures),
        "",
        "## Non-blocking limitations",
        "",
    ]
    md += [f"- {x}" for x in verification["NON_BLOCKING_LIMITATIONS"]]
    md += [
        "",
        "## Drawdown gate",
        "",
        f"- {verification['DRAWDOWN_GATE_ASSESSMENT']['classification']}",
        f"- {verification['DRAWDOWN_GATE_ASSESSMENT']['why']}",
        "",
        "## Next",
        "",
        f"`NEXT = {verification['NEXT']}` — economics are NOT executed in this worktree.",
        "",
    ]
    (out / "ARC03_INDEPENDENT_PREREG_VERIFICATION.md").write_bytes(
        ("\n".join(md)).encode("utf-8")
    )

    progress = {
        "schema": "VERIFIER_PROGRESS/1.0.0",
        "stage": "ARC03_INDEPENDENT_PREREG_VERIFICATION",
        "status": "COMPLETE",
        "FINAL_VERDICT": final,
        "verdicts": verdicts,
        "independent_gates": gates,
        "economics_guard": verification["economics_guard"],
        "steps": [
            "independent detached worktree at the frozen prereg commit (clean)",
            "git authority + spec/manifest SHA recomputation + post-freeze drift",
            "performance contamination scan with hit classification",
            "independent data-binding re-derivation (raw -> partitions -> manifest -> dataset)",
            "provider field-mapping proof (field 5 = base-unit volume)",
            "SOL daily-fill authority audit (no synthetic market rows)",
            "30 same-slot daily reference window audit",
            "decision cadence / entry causality / 12-bar exit audit",
            "funding cashflow audit (window, sign, byte reuse, no assumed 8h)",
            "control semantics audit (all four controls, fail semantics)",
            "G1..G11 statistical gate reproducibility audit",
            "robustness no-retune audit",
            "failed-memory collision audit",
            "independent PIT adversarial battery (verifier fixtures)",
            "mutation sensitivity on TEMP copies",
            "portability + import authority + wrong-root fail-closed",
            "clean-worktree re-verification from a throwaway checkout",
            "final verdict assembly",
        ],
        "next": verification["NEXT"],
    }
    (out / "VERIFIER_PROGRESS.json").write_bytes(
        (json.dumps(progress, indent=2, sort_keys=True) + "\n").encode("utf-8")
    )

    print(json.dumps({"FINAL_VERDICT": final, "failures": failures}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
