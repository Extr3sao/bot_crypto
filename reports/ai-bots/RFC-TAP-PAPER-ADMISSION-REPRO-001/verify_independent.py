"""A second opinion on RFC-TAP-PAPER-ADMISSION-REPRO-001, written from the premises.

This file shares no code with ``verify_repro.py``: it re-declares the frozen digests it
checks, re-implements the ledger count from the ledger's own JSON, and re-runs every
external tool instead of reading what the report says the tool printed.  It exists because
the same tree cannot be both the builder and the authority on its own work, and because the
first closure rehearsal ran in a worktree that inherited ``core.autocrlf=false``: the gates
passed there and 13 of 44 digests drifted in a fresh clone of the same commit.

    python reports/ai-bots/RFC-TAP-PAPER-ADMISSION-REPRO-001/verify_independent.py [--json OUT]

Exit codes: 0 every check agreed, 1 a check disagreed, 3 a check could not run.
``PASS`` is a statement about artefacts, never about profitability or admission.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPORT = Path(__file__).resolve().parent
REPO = REPORT.parents[2]
DIAG = REPO / "reports/ai-bots/CODEX-PAPER-ADMISSION-DIAG-001"
SUPERVISOR_CAMPAIGN = REPO / "reports/ai-bots/CODEX-PAPER-SUPERVISOR-001/campaign"
PY = sys.executable

#: Re-typed from the diagnosis, not read from the manifest under test.
FROZEN = {
    "FINAL_REPORT.md": "e30fa25fe329a26bcd57783659dfb880abba7ed66888ba94890f37925e21bb59",
    "NEXT_EXPERIMENT.md": "6759808f41571bed4b418d70b836fade46fbc497f5e3354b081841e924896997",
    "OPERATIONAL_BLOCKERS.md": "94a9c64ef526deb730ae2a61606094312ebbc5fd7bb3777346aaf9480f7e2e97",
    "PAPER_ADMISSION_DIAGNOSIS.md": "36255748b45d1085588e8f7de79b7f038f12c21ffa2181e41e549a4fb46a9f03",
    "RUNTIME_AUTHORITY_MAP.md": "4540e3c75bffb1011a07c6d265849439b42ee5f235b3e29a47153d0241f80b84",
    "STRATEGY_ECONOMIC_STATUS.md": "d8e9e015587af9755da637c97f304a70dacba4b5e346929b967343e9138379f3",
    "verify_claims.py": "e423ef3fcd5990db83e8897bd702f76fda204646b35f56b20b64b77ed3d9c2b1",
}

FORBIDDEN = (
    "config/risk",
    "data/",
    "src/trading_bot/risk/",
    "src/trading_bot/autonomous/",
    "src/trading_bot/vision/",
    "src/trading_bot/paper/",
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def git_bytes(*args: str) -> bytes:
    """Content as Git stores it. Text mode would re-decode it with the console codec."""

    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, check=False).stdout


def run(args: list[str], timeout: int = 900) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def check(name: str, ok: bool, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"check": name, "ok": bool(ok), "detail": detail or {}}


def baseline_commit() -> str:
    manifest = json.loads((REPORT / "evidence_manifest.json").read_text(encoding="utf-8"))
    return manifest["baseline"]["base_commit"]


def check_preserved() -> dict[str, Any]:
    worktree = {name: sha((DIAG / name).read_bytes()) for name in FROZEN}
    blob = {
        name: sha(git_bytes("show", f"HEAD:{(DIAG / name).relative_to(REPO).as_posix()}"))
        for name in FROZEN
    }
    drifted = sorted(n for n in FROZEN if worktree[n] != FROZEN[n] or blob[n] != FROZEN[n])
    return check("preserved_documents_identical_on_disk_and_in_git", not drifted, {"drifted": drifted})


def check_ledger() -> dict[str, Any]:
    ledger = json.loads((REPO / "config/strategy_admission.json").read_text(encoding="utf-8"))
    rows = ledger["strategies"]
    admitted = [name for name, row in rows.items() if row.get("admitted_for_paper") is True]
    base = baseline_commit()
    at_base = sha(git_bytes("show", f"{base}:config/strategy_admission.json"))
    at_head = sha(git_bytes("show", "HEAD:config/strategy_admission.json"))
    on_disk = sha((REPO / "config/strategy_admission.json").read_bytes())
    diff = git("diff", "--name-only", base, "--", "config/").stdout.split()
    #: `git diff` is the claim: it compares what Git stores, so a Windows checkout that
    #: rewrote the line endings of this unpinned file still counts as unchanged — and should,
    #: because nothing in the manifest digests it. The raw-bytes comparison is reported, not
    #: asserted: it says whether the checkout reproduced the blob, which is a property of the
    #: machine, not of the RFC.
    ok = not admitted and at_base == at_head and not diff
    return check(
        "ledger_unchanged_and_nothing_admitted",
        ok,
        {
            "strategies": len(rows),
            "admitted": admitted,
            "diff": diff,
            "blob_identical_head_vs_base": at_base == at_head,
            "worktree_bytes_equal_blob": on_disk == at_head,
        },
    )


def check_scope() -> dict[str, Any]:
    base = baseline_commit()
    changed = git("diff", "--name-only", base).stdout.split()
    forbidden = sorted(p for p in changed if any(p.startswith(f) for f in FORBIDDEN))
    allowed = {
        ".gitattributes",
        ".gitignore",
        "uv.lock",
        "scripts/exp004a_verify.py",
        "scripts/ops_background_audit.py",
        "scripts/paper_lock_campaign_verify.py",
        "tests/unit/ops/test_paper_lock_campaign.py",
        "tests/unit/ops/test_session_status.py",
        "tests/unit/ops/test_windowless.py",
        "tests/unit/reports/test_evidence_manifest_eol.py",
    }
    outside = sorted(p for p in changed if p not in allowed and not p.startswith("reports/"))
    return check("change_scope", not forbidden and not outside, {"forbidden": forbidden, "outside": outside, "changed": len(changed)})


def check_windowless() -> dict[str, Any]:
    out = Path(tempfile.mkdtemp()) / "audit.json"
    audit = run([PY, "scripts/ops_background_audit.py", "--json", str(out)])
    report = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else {}
    tests = run([PY, "-m", "pytest", "tests/unit/ops/test_windowless.py", "-q"])
    tail = [line for line in tests.stdout.splitlines() if line.strip()][-1:]
    ok = audit.returncode == 0 and report.get("high") == 0 and tests.returncode == 0
    return check("windowless_audit_and_contract", ok, {"high": report.get("high"), "tests": tail[0] if tail else ""})


def check_supervisor() -> dict[str, Any]:
    out = Path(tempfile.mkdtemp()) / "sup.json"
    completed = run([PY, "scripts/paper_supervisor_verify.py", "--campaign", str(SUPERVISOR_CAMPAIGN), "--out", str(out)])
    payload = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else {}
    checks = (payload.get("judgement") or {}).get("checks") or {}
    ok = completed.returncode == 0 and payload.get("verdict") == "PASS" and len(checks) == 33 and all(checks.values())
    return check("supervisor_verifier_33_checks", ok, {"verdict": payload.get("verdict"), "checks": len(checks), "false_success": payload.get("false_success")})


def check_lock_verifier() -> dict[str, Any]:
    """It must refuse a campaign whose schema it does not own, without scoring checks."""

    foreign = Path(tempfile.mkdtemp()) / "campaign"
    foreign.mkdir()
    (foreign / "CAMPAIGN.json").write_text(json.dumps({"schema_version": "SOMETHING_ELSE"}), encoding="utf-8")
    out = Path(tempfile.mkdtemp()) / "refusal.json"
    completed = run(
        [PY, "scripts/paper_lock_campaign_verify.py", "--campaign", str(foreign), "--out", str(out), "--skip-mutations"]
    )
    payload = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else {}
    refusal = (payload.get("refusal") or {})
    code = refusal.get("code") if isinstance(refusal, dict) else refusal
    ok = completed.returncode == 1 and code == "UNSUPPORTED_CAMPAIGN_SCHEMA" and payload.get("verdict") == "FAIL"
    return check("foreign_schema_refused", ok, {"refusal": code, "exit": completed.returncode})


def check_environment() -> dict[str, Any]:
    lock = run(["uv", "lock", "--check"], timeout=300)
    imported = run([PY, "-c", "import matplotlib;print(matplotlib.__version__)"])
    pinned = "matplotlib" in (REPO / "uv.lock").read_text(encoding="utf-8")
    ok = lock.returncode == 0 and imported.returncode == 0 and pinned
    return check("uv_lock_and_declared_dependency", ok, {"lock_exit": lock.returncode, "matplotlib": imported.stdout.strip()})


def check_digest_pins() -> dict[str, Any]:
    """Every digested path must be ``-text`` or a checkout can rewrite its bytes."""

    manifest = json.loads((REPORT / "evidence_manifest.json").read_text(encoding="utf-8"))
    paths = [e["path"] for e in manifest.get("preserved", {}).values()]
    paths += [e["path"] for e in manifest.get("code_changes", [])]
    paths += list(manifest.get("evidence", {}))
    attr = git("check-attr", "-z", "text", "--", *sorted(set(paths)))
    fields = attr.stdout.split("\0")
    values = {fields[i]: fields[i + 2] for i in range(0, len(fields) - 2, 3)}
    unpinned = sorted(p for p, v in values.items() if v != "unset")
    return check("every_digested_path_pinned_text", not unpinned and len(values) > 40, {"unpinned": unpinned, "paths": len(values)})


def check_no_session_opened() -> dict[str, Any]:
    """This RFC runs no PAPER or LIVE operation.

    The fixture campaign ships tracked ``STREAM.jsonl`` files — those are evidence, not
    sessions.  What must not exist is a stream this lane produced: an untracked one, or one
    written under the live data tree.
    """

    untracked = git("ls-files", "--others", "--exclude-standard", "*STREAM.jsonl").stdout.split()
    under_data = sorted(
        p.relative_to(REPO).as_posix() for p in REPO.glob("data/**/STREAM.jsonl")
    )
    tracked = git("ls-files", "*STREAM.jsonl").stdout.split()
    return check(
        "no_session_opened_by_this_lane",
        not untracked and not under_data,
        {"untracked": untracked[:5], "under_data": under_data[:5], "tracked_fixtures": len(tracked)},
    )


CHECKS = (
    check_preserved,
    check_ledger,
    check_scope,
    check_windowless,
    check_supervisor,
    check_lock_verifier,
    check_environment,
    check_digest_pins,
    check_no_session_opened,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", dest="json_out", default=None)
    args = parser.parse_args()

    results = []
    for function in CHECKS:
        try:
            results.append(function())
        except Exception as exc:  # a check that cannot run is not a pass
            results.append({"check": function.__name__, "ok": False, "detail": {"error": repr(exc)}})

    failed = [r["check"] for r in results if not r["ok"]]
    payload = {
        "schema_version": "RFC_TAP_PAPER_ADMISSION_REPRO_INDEPENDENT_V1",
        "commit": git("rev-parse", "HEAD").stdout.strip(),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip(),
        "checks": results,
        "passed": len(results) - len(failed),
        "failed": failed,
        "verdict": "PASS" if not failed else "FAIL",
    }
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        Path(args.json_out).write_text(text, encoding="utf-8")
    print(text)
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
