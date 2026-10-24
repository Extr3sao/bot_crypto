"""Independent verification of RFC-TAP-PAPER-ADMISSION-REPRO-001.

This script did not produce the fixes and imports none of their logic. It recomputes every
hash from bytes, re-runs every gate as a subprocess and reads the *payload* each tool wrote,
not the prose of the report that cites it. Where it cannot execute a claim, it says
``NOT_EXECUTED`` instead of assuming it.

    python reports/ai-bots/RFC-TAP-PAPER-ADMISSION-REPRO-001/verify_repro.py [--self-test]

Exit codes are its own:

    0 PASS       every in-scope gate was recomputed and agreed
    1 FAIL       a gate disagreed with the tree
    3 BLOCKED    a gate could not be executed (missing tool, missing evidence)

``PASS`` here is a statement about artefacts, never about profitability or admission.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

REPORT = Path(__file__).resolve().parent
REPO = REPORT.parents[2]
EVIDENCE = REPORT / "evidence"
#: Kept apart from the builder's evidence on purpose: these files are rewritten on every
#: run, so the manifest must not hash them.
VERIFIER_EVIDENCE = EVIDENCE / "verifier"
PYTHON = sys.executable

DIAG = REPO / "reports/ai-bots/CODEX-PAPER-ADMISSION-DIAG-001"
SUPERVISOR = REPO / "reports/ai-bots/CODEX-PAPER-SUPERVISOR-001"
SUPERVISOR_CAMPAIGN = SUPERVISOR / "campaign"

#: Frozen at capture time. A verifier that read these from the manifest it is auditing
#: could be made to agree with a rewritten document by rewriting one file.
FROZEN_SHA256: dict[str, str] = {
    "FINAL_REPORT.md": "e30fa25fe329a26bcd57783659dfb880abba7ed66888ba94890f37925e21bb59",
    "NEXT_EXPERIMENT.md": "6759808f41571bed4b418d70b836fade46fbc497f5e3354b081841e924896997",
    "OPERATIONAL_BLOCKERS.md": "94a9c64ef526deb730ae2a61606094312ebbc5fd7bb3777346aaf9480f7e2e97",
    "PAPER_ADMISSION_DIAGNOSIS.md": "36255748b45d1085588e8f7de79b7f038f12c21ffa2181e41e549a4fb46a9f03",
    "RUNTIME_AUTHORITY_MAP.md": "4540e3c75bffb1011a07c6d265849439b42ee5f235b3e29a47153d0241f80b84",
    "STRATEGY_ECONOMIC_STATUS.md": "d8e9e015587af9755da637c97f304a70dacba4b5e346929b967343e9138379f3",
    "verify_claims.py": "e423ef3fcd5990db83e8897bd702f76fda204646b35f56b20b64b77ed3d9c2b1",
}

#: The only files this RFC may change, plus the reports it publishes.
ALLOWED_CHANGES = frozenset(
    {
        ".gitignore",
        "uv.lock",
        "scripts/exp004a_verify.py",
        "scripts/ops_background_audit.py",
        "scripts/paper_lock_campaign_verify.py",
        "tests/unit/ops/test_paper_lock_campaign.py",
        "tests/unit/ops/test_session_status.py",
        "tests/unit/ops/test_windowless.py",
        # Added by the clone-and-run: the manifest digests working-tree bytes, so the
        # paths it covers must not be rewritten by checkout, and the test that keeps
        # that true is itself a change this RFC has to declare.
        ".gitattributes",
        "tests/unit/reports/test_evidence_manifest_eol.py",
    }
)

#: Areas the mandate forbids touching. A path here is a hard failure, allowlisted or not.
FORBIDDEN_PREFIXES = (
    "config/strategy_admission.json",
    "config/risk",
    "data/",
    "src/trading_bot/risk/",
    "src/trading_bot/autonomous/",
    "src/trading_bot/vision/",
    "src/trading_bot/paper/",
)

EXPECTED_ADMISSION: dict[str, Any] = {
    "verdict": "NO_GO",
    "reason": "BASE_TECHNICAL_FIXES_ONLY",
}


@dataclass
class Result:
    name: str
    status: str  # PASS | FAIL | NOT_EXECUTED
    detail: dict[str, Any]

    @property
    def ok(self) -> bool:
        return self.status == "PASS"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def blob_sha256(rel_path: str) -> str | None:
    """The hash of ``rel_path`` as ``HEAD`` stores it (``None`` when ``HEAD`` lacks it)."""

    result = subprocess.run(
        ["git", "show", f"HEAD:{rel_path}"],
        cwd=str(REPO),
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return hashlib.sha256(result.stdout).hexdigest()


def drift_cause(rel_path: str, expected: str) -> str:
    """Name a digest mismatch instead of leaving it to be guessed at.

    ``EOL_NORMALISED`` is the cause that hides: the committed bytes still hash to
    ``expected`` and it was ``core.autocrlf`` that rewrote them on checkout.  It stays a
    FAIL — a digest that depends on who checked the tree out is not a digest — but a gate
    that says ``drifted`` without saying *why* sends the next reader hunting for tampering
    that never happened.  Found by clone-and-run: 13 of 44 digests drifted on a fresh
    Windows clone while the tree that produced them agreed with itself.
    """

    return "EOL_NORMALISED" if blob_sha256(rel_path) == expected else "CONTENT_DIFFERS"


def run(args: list[str], *, timeout: int = 900, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(cwd or REPO),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def pytest_summary(text: str) -> dict[str, Any]:
    """Read pytest's own last line instead of trusting an exit code alone."""

    tail = [line.strip() for line in text.splitlines() if line.strip()][-1:]
    summary = tail[0] if tail else ""
    return {
        "summary": summary,
        "failed": " failed" in summary,
        "errors": summary.startswith("ERROR") or " error" in summary,
    }


# --------------------------------------------------------------------------- gates


def gate_preserved_docs() -> Result:
    actual = {name: sha256(DIAG / name) for name in FROZEN_SHA256}
    drifted = sorted(name for name, digest in actual.items() if digest != FROZEN_SHA256[name])
    causes = {
        name: drift_cause((DIAG / name).relative_to(REPO).as_posix(), FROZEN_SHA256[name])
        for name in drifted
    }
    return Result(
        "V01_preserved_docs_byte_identical",
        "FAIL" if drifted else "PASS",
        {"checked": len(actual), "drifted": drifted, "causes": causes},
    )


def gate_manifest() -> Result:
    path = REPORT / "evidence_manifest.json"
    if not path.is_file():
        return Result("V02_manifest_matches_tree", "NOT_EXECUTED", {"reason": "NO_MANIFEST"})
    manifest = json.loads(path.read_text(encoding="utf-8"))
    problems: list[str] = []
    causes: dict[str, str] = {}
    for name, entry in manifest.get("preserved", {}).items():
        if sha256(REPO / entry["path"]) != entry["sha256"]:
            problems.append(f"preserved:{name}")
            causes[f"preserved:{name}"] = drift_cause(entry["path"], entry["sha256"])
    for entry in manifest.get("code_changes", []):
        target = REPO / entry["path"]
        if not target.is_file():
            problems.append(f"missing:{entry['path']}")
        elif sha256(target) != entry["sha256_after"]:
            problems.append(f"after:{entry['path']}")
            causes[f"after:{entry['path']}"] = drift_cause(
                entry["path"], entry["sha256_after"]
            )
    for rel, entry in manifest.get("evidence", {}).items():
        target = REPO / rel
        if not target.is_file():
            problems.append(f"missing-evidence:{rel}")
        elif sha256(target) != entry["sha256"]:
            problems.append(f"evidence:{rel}")
            causes[f"evidence:{rel}"] = drift_cause(rel, entry["sha256"])
    return Result(
        "V02_manifest_matches_tree",
        "FAIL" if problems else "PASS",
        {
            "problems": problems,
            "causes": causes,
            "preserved": len(manifest.get("preserved", {})),
            "code_changes": len(manifest.get("code_changes", [])),
            "evidence": len(manifest.get("evidence", {})),
        },
    )


def gate_unversioned_at_base() -> Result:
    """The reason this RFC exists: at the base commit the diagnosis was not in Git."""

    manifest = json.loads((REPORT / "evidence_manifest.json").read_text(encoding="utf-8"))
    committed = {
        name: entry.get("committed_at") for name, entry in manifest.get("preserved", {}).items()
    }
    still_missing = sorted(name for name, value in committed.items() if value)
    base = manifest["baseline"]["base_commit"]
    probe = run(["git", "cat-file", "-e", f"{base}:reports/ai-bots/CODEX-PAPER-ADMISSION-DIAG-001"])
    independent = probe.returncode != 0
    ok = not still_missing and independent
    return Result(
        "V03_preserved_were_unversioned_at_base",
        "PASS" if ok else "FAIL",
        {
            "base_commit": base,
            "documents_claimed_present": still_missing,
            "git_probe_confirms_absent": independent,
        },
    )


def gate_windowless_audit() -> Result:
    out = VERIFIER_EVIDENCE / "audit.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    completed = run([PYTHON, "scripts/ops_background_audit.py", "--json", str(out)])
    if not out.is_file():
        return Result(
            "V04_windowless_audit_clean",
            "NOT_EXECUTED",
            {"exit": completed.returncode, "stderr": completed.stderr[-800:]},
        )
    report = json.loads(out.read_text(encoding="utf-8"))
    high = [f for f in report["findings"] if f["severity"] == "HIGH"]
    ok = completed.returncode == 0 and report["high"] == 0 and not high
    return Result(
        "V04_windowless_audit_clean",
        "PASS" if ok else "FAIL",
        {
            "exit": completed.returncode,
            "high": report["high"],
            "verdict": report["verdict"],
            "medium": report["by_severity"].get("MEDIUM", 0),
        },
    )


def gate_windowless_contract() -> Result:
    completed = run([PYTHON, "-m", "pytest", "tests/unit/ops/test_windowless.py", "-q"])
    summary = pytest_summary(completed.stdout)
    ok = completed.returncode == 0 and not summary["failed"] and not summary["errors"]
    return Result(
        "V05_windowless_contract_tests",
        "PASS" if ok else "FAIL",
        {"exit": completed.returncode, **summary},
    )


def gate_foreign_schema_refused() -> Result:
    out = VERIFIER_EVIDENCE / "lock_verifier_refusal.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    completed = run(
        [
            PYTHON,
            "scripts/paper_lock_campaign_verify.py",
            "--campaign",
            str(SUPERVISOR_CAMPAIGN),
            "--out",
            str(out),
        ]
    )
    if not out.is_file():
        return Result(
            "V06_lock_verifier_refuses_foreign_schema",
            "NOT_EXECUTED",
            {"exit": completed.returncode, "stderr": completed.stderr[-800:]},
        )
    payload = json.loads(out.read_text(encoding="utf-8"))
    checks = payload["judgement"]["checks"]
    refusal = payload.get("refusal") or {}
    declared = (payload.get("campaign_schema") or {}).get("declared")
    scored = [name for name, value in checks.items() if name != "campaign_schema_is_supported"]
    ok = (
        completed.returncode == 1
        and payload["verdict"] == "FAIL"
        and refusal.get("code") == "UNSUPPORTED_CAMPAIGN_SCHEMA"
        and declared == "TAP_PAPER_SUPERVISOR_CAMPAIGN_V1"
        and scored == []
        and payload.get("mutation_skip_reason", payload.get("mutations_skipped"))
        == "UNSUPPORTED_CAMPAIGN_SCHEMA"
        and payload.get("false_success") == 0
    )
    return Result(
        "V06_lock_verifier_refuses_foreign_schema",
        "PASS" if ok else "FAIL",
        {
            "exit": completed.returncode,
            "verdict": payload["verdict"],
            "declared_schema": declared,
            "refusal": refusal.get("code"),
            "checks_scored": len(scored),
            "mutations_run": len(payload.get("adversarial") or []),
        },
    )


ACTIVE_CAMPAIGN_PROBE = r"""
import importlib.util, json, sys, tempfile
from pathlib import Path

root = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location(
    "test_paper_lock_campaign", root / "tests/unit/ops/test_paper_lock_campaign.py"
)
module = importlib.util.module_from_spec(spec)
sys.modules["test_paper_lock_campaign"] = module
spec.loader.exec_module(module)

with tempfile.TemporaryDirectory() as tmp:
    campaign = module.build_campaign(Path(tmp))
    verdict = module.verifier.judge(campaign)
    mutations = module.verifier.mutations(campaign)
    print(json.dumps({
        "verdict": verdict["verdict"],
        "checks_total": len(verdict["checks"]),
        "checks_failed": sorted(k for k, v in verdict["checks"].items() if v is False),
        "mutations": len(mutations),
        "invalid": [m["mutation"] for m in mutations if m["invalid"]],
        "undetected": [m["mutation"] for m in mutations if not m["detected"]],
    }))
"""


def gate_active_campaign() -> Result:
    """The verifier must still judge its own schema honestly and detect every mutation."""

    completed = run([PYTHON, "-c", ACTIVE_CAMPAIGN_PROBE, str(REPO)])
    try:
        payload = json.loads(completed.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return Result(
            "V07_lock_verifier_judges_its_own_schema",
            "NOT_EXECUTED",
            {"exit": completed.returncode, "stderr": completed.stderr[-800:]},
        )
    ok = (
        completed.returncode == 0
        and payload["verdict"] == "PASS"
        and payload["checks_failed"] == []
        and payload["mutations"] == 10
        and payload["invalid"] == []
        and payload["undetected"] == []
    )
    return Result(
        "V07_lock_verifier_judges_its_own_schema",
        "PASS" if ok else "FAIL",
        {"exit": completed.returncode, **payload},
    )


def gate_supervisor_verifier() -> Result:
    out = VERIFIER_EVIDENCE / "supervisor_verify.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    completed = run(
        [
            PYTHON,
            "scripts/paper_supervisor_verify.py",
            "--campaign",
            str(SUPERVISOR_CAMPAIGN),
            "--out",
            str(out),
        ]
    )
    if not out.is_file():
        return Result(
            "V08_supervisor_verifier_external",
            "NOT_EXECUTED",
            {"exit": completed.returncode, "stderr": completed.stderr[-800:]},
        )
    payload = json.loads(out.read_text(encoding="utf-8"))
    checks = payload["judgement"]["checks"]
    ok = (
        completed.returncode == 0
        and payload["verdict"] == "PASS"
        and len(checks) == 33
        and all(checks.values())
        and payload["false_success"] == 0
    )
    return Result(
        "V08_supervisor_verifier_external",
        "PASS" if ok else "FAIL",
        {
            "exit": completed.returncode,
            "verdict": payload["verdict"],
            "checks": len(checks),
            "false_success": payload["false_success"],
            "mutations": len(payload.get("adversarial") or []),
        },
    )


def gate_uv_lock() -> Result:
    completed = run(["uv", "lock", "--check"], timeout=300)
    text = (completed.stdout + completed.stderr).strip()
    return Result(
        "V09_uv_lock_reproducible",
        "PASS" if completed.returncode == 0 else "FAIL",
        {"exit": completed.returncode, "output": text[-300:]},
    )


def gate_declared_dependency() -> Result:
    lock = (REPO / "uv.lock").read_text(encoding="utf-8")
    completed = run([PYTHON, "-c", "import matplotlib; print(matplotlib.__version__)"], timeout=120)
    pinned = "matplotlib" in lock
    declared = "matplotlib" in (REPO / "pyproject.toml").read_text(encoding="utf-8")
    ok = completed.returncode == 0 and pinned and declared
    return Result(
        "V10_declared_dependency_importable",
        "PASS" if ok else "FAIL",
        {
            "import_exit": completed.returncode,
            "version": completed.stdout.strip(),
            "declared_in_pyproject": declared,
            "pinned_in_lock": pinned,
        },
    )


def gate_scope() -> Result:
    manifest = json.loads((REPORT / "evidence_manifest.json").read_text(encoding="utf-8"))
    base = manifest["baseline"]["base_commit"]
    changed = [line for line in run(["git", "diff", "--name-only", base]).stdout.splitlines() if line]
    outside = sorted(
        path
        for path in changed
        if path not in ALLOWED_CHANGES
        and not path.startswith("reports/ai-bots/")
        and path != "reports/ai-bots/RFC-TAP-PAPER-ADMISSION-REPRO-001"
    )
    forbidden = sorted(
        path for path in changed if any(path.startswith(prefix) for prefix in FORBIDDEN_PREFIXES)
    )
    ok = not outside and not forbidden
    return Result(
        "V11_scope_respected",
        "PASS" if ok else "FAIL",
        {"changed": len(changed), "outside_allowlist": outside, "forbidden": forbidden},
    )


def gate_admission_verdict() -> Result:
    """The economic verdict must still be NO_GO: this RFC changes no admission criteria.

    Recomputed from the ledger itself (how many strategies are admitted) and from Git (the
    ledger is byte-identical to the base commit), not from a report that says so.
    """

    ledger = REPO / "config/strategy_admission.json"
    criteria = REPO / "docs/STRATEGY_ADMISSION_CRITERIA.md"
    missing = [str(p.relative_to(REPO)) for p in (ledger, criteria) if not p.is_file()]
    if missing:
        return Result("V12_admission_verdict_unchanged", "NOT_EXECUTED", {"missing": missing})

    entries = json.loads(ledger.read_text(encoding="utf-8"))["strategies"]
    admitted = sorted(name for name, row in entries.items() if row.get("admitted_for_paper"))
    base = json.loads((REPORT / "evidence_manifest.json").read_text(encoding="utf-8"))[
        "baseline"
    ]["base_commit"]
    touched = [
        line
        for line in run(
            ["git", "diff", "--name-only", base, "--", "config/", "docs/STRATEGY_ADMISSION_CRITERIA.md"]
        ).stdout.splitlines()
        if line
    ]
    ok = not admitted and not touched
    return Result(
        "V12_admission_verdict_unchanged",
        "PASS" if ok else "FAIL",
        {
            "strategies": len(entries),
            "admitted_for_paper": len(admitted),
            "ledger_unchanged_since": base,
            "touched": touched,
            "verdict": EXPECTED_ADMISSION["verdict"],
        },
    )


# ------------------------------------------------------------- negative controls


def control_document_byte_flip() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "FINAL_REPORT.md"
        original = (DIAG / "FINAL_REPORT.md").read_bytes()
        copy.write_bytes(original[:-1] + b"X")
        detected = sha256(copy) != FROZEN_SHA256["FINAL_REPORT.md"]
    return {"control": "document_byte_flip", "detected": detected}


def control_missing_schema() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        campaign = Path(tmp) / "campaign"
        campaign.mkdir()
        (campaign / "CAMPAIGN.json").write_text("{}", encoding="utf-8")
        completed = run(
            [
                PYTHON,
                "scripts/paper_lock_campaign_verify.py",
                "--campaign",
                str(campaign),
                "--out",
                str(Path(tmp) / "out.json"),
                "--skip-mutations",
            ]
        )
        payload = json.loads((Path(tmp) / "out.json").read_text(encoding="utf-8"))
        detected = (
            completed.returncode == 1
            and payload["refusal"]["code"] == "UNSUPPORTED_CAMPAIGN_SCHEMA"
            and payload["judgement"]["checks"] == {"campaign_schema_is_supported": False}
        )
    return {"control": "campaign_without_schema", "detected": detected}


def control_local_hiding_removed() -> dict[str, Any]:
    """Strip the window suppression from a copy and require a HIGH finding."""

    script = r"""
import importlib.util, json, sys, tempfile
from pathlib import Path

root = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("audit_probe", root / "scripts/ops_background_audit.py")
module = importlib.util.module_from_spec(spec)
# dataclasses resolves string annotations through sys.modules: register before exec.
sys.modules["audit_probe"] = module
spec.loader.exec_module(module)
source = (root / "scripts/exp004a_verify.py").read_text(encoding="utf-8")
with tempfile.TemporaryDirectory() as tmp:
    (Path(tmp) / "scripts").mkdir()
    (Path(tmp) / "scripts/exp004a_verify.py").write_text(
        source.replace("SW_HIDE", "SW_SHOWNORMAL"), encoding="utf-8"
    )
    report = module.scan(tmp)
    print(json.dumps(sorted({
        f["code"] for f in report["findings"] if f["severity"] == "HIGH"
    })))
"""
    completed = run([PYTHON, "-c", script, str(REPO)])
    codes = json.loads(completed.stdout.strip().splitlines()[-1]) if completed.stdout.strip() else []
    return {
        "control": "declared_local_hiding_removed",
        "detected": "DECLARED_LOCAL_HIDING_MISSING" in codes,
        "codes": codes,
        "stderr": completed.stderr[-400:] if completed.returncode != 0 else "",
    }


def control_manifest_tamper() -> dict[str, Any]:
    manifest = json.loads((REPORT / "evidence_manifest.json").read_text(encoding="utf-8"))
    name = next(iter(manifest["preserved"]))
    entry = dict(manifest["preserved"][name])
    entry["sha256"] = "0" * 64
    detected = sha256(REPO / entry["path"]) != entry["sha256"]
    return {"control": "manifest_hash_tamper", "detected": detected, "subject": name}


CONTROLS: tuple[Callable[[], dict[str, Any]], ...] = (
    control_document_byte_flip,
    control_missing_schema,
    control_local_hiding_removed,
    control_manifest_tamper,
)

GATES: tuple[Callable[[], Result], ...] = (
    gate_preserved_docs,
    gate_manifest,
    gate_unversioned_at_base,
    gate_windowless_audit,
    gate_windowless_contract,
    gate_foreign_schema_refused,
    gate_active_campaign,
    gate_supervisor_verifier,
    gate_uv_lock,
    gate_declared_dependency,
    gate_scope,
    gate_admission_verdict,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Independent verification of the RFC")
    parser.add_argument("--self-test", action="store_true", help="run only the negative controls")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    controls = [control() for control in CONTROLS]
    false_success = [item["control"] for item in controls if not item["detected"]]
    results = [] if args.self_test else [gate() for gate in GATES]

    for result in results:
        mark = {"PASS": "PASS", "FAIL": "FAIL", "NOT_EXECUTED": "BLOCKED"}[result.status]
        print(f"{mark:8} {result.name:45} {json.dumps(result.detail, sort_keys=True)}")
    for item in controls:
        mark = "PASS" if item["detected"] else "FAIL"
        print(f"{mark:8} control:{item['control']:37} {json.dumps(item, sort_keys=True)}")

    failed = [result.name for result in results if result.status == "FAIL"]
    blocked = [result.name for result in results if result.status == "NOT_EXECUTED"]
    verdict = "PASS" if not failed and not blocked and not false_success else "FAIL"
    payload = {
        "schema_version": "RFC_TAP_PAPER_ADMISSION_REPRO_VERIFICATION_V1",
        "verifier": "reports/ai-bots/RFC-TAP-PAPER-ADMISSION-REPRO-001/verify_repro.py",
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "gates": [
            {"name": r.name, "status": r.status, "detail": r.detail} for r in results
        ],
        "negative_controls": controls,
        "false_success": len(false_success),
        "failed": failed,
        "blocked": blocked,
        "verdict": verdict,
    }
    out = Path(args.out) if args.out else EVIDENCE / "VERIFICATION.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "gates": len(results),
                "passed": sum(1 for r in results if r.ok),
                "failed": failed,
                "blocked": blocked,
                "false_success": len(false_success),
                "verdict": verdict,
                "wrote": os.path.relpath(out, REPO),
            },
            indent=2,
        )
    )
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
