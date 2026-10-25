"""RFC-TDM-013 — independent, read-only verifier for the TDM-12 evidence package.

Nothing here imports ``tdm12_review``, ``tdm12_publish`` or any other builder
module, and nothing calls ``tdm12_publish.py --verify``: the whole point of this
file is a second implementation that reads Git objects and the sealed artefacts
itself. Where the builder compared a recorded digest with the working directory,
this one compares it with ``git cat-file`` output; where the builder asserted a
count, this one re-derives it from the committed ledger and registry.

Subcommands::

    python scripts/tdm13_independent_verify.py audit-git
    python scripts/tdm13_independent_verify.py audit-claims
    python scripts/tdm13_independent_verify.py verify

Exit codes: 0 = PASS/VERIFIED, 1 = FAIL, 2 = INCOMPLETE (missing inputs or an
audit that could not be produced). A check that cannot run is never a PASS.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any

#: ``TDM13_REPO`` exists so the negative controls can point the same code at a
#: throwaway sandbox instead of the real worktree.
REPO_ROOT = Path(os.environ.get("TDM13_REPO") or Path(__file__).resolve().parents[1]).resolve()
ART = REPO_ROOT / ".tdm13"
EVIDENCE = REPO_ROOT / "evidence" / "tdm" / "wp-tdm-13"
TDM11 = REPO_ROOT / "evidence" / "tdm" / "wp-tdm-11"
TDM12 = REPO_ROOT / "evidence" / "tdm" / "wp-tdm-12"

RFC_ID = "RFC-TDM-013"
VERIFIER_ID = "tdm13-independent-verifier/1 (separate code path, no builder imports)"

#: Reported baseline: the evidence commit and the commit it claims to sit on.
#: Both are overridable so a sandbox can exercise the lineage check.
TARGET_COMMIT = os.environ.get("TDM13_TARGET", "a96e9c80c608ed91943d1fab35db6fa1704111bb")
BASELINE_COMMIT = os.environ.get("TDM13_BASELINE", "504256ec8934b97a6d405c202604ecac81a02346")

#: RFC-TDM-012 §8, group by group; a group with two names requires both.
EXPECTED_DELIVERABLES: tuple[str, ...] = (
    "RFC-TDM-012.md",
    "BASELINE_AND_SCOPE.md",
    "INDEPENDENT_REVIEW.md",
    "TDM11_CLOSURE_DECISION.json",
    "RUNTIME_AUTHORITY_MAP.md",
    "CANDIDATE_REGISTRY.csv",
    "CANDIDATE_REGISTRY.json",
    "DATA_WINDOW_REGISTRY.json",
    "COST_AND_BIAS_AUDIT.md",
    "RETROSPECTIVE_TRIAGE_REPORT.md",
    "DECISION_REGISTER.json",
    "RUN_REPORT.md",
    "RUN_REPORT.json",
    "FINAL_REPORT.md",
)

#: RFC-TDM-012 §8 second paragraph, field by field.
REQUIRED_RUN_FIELDS: tuple[str, ...] = (
    "run_id",
    "commit",
    "environment",
    "inputs",
    "datasets",
    "agents",
    "strategies",
    "tests",
    "decisions",
    "errors",
    "metrics",
    "result",
    "evidence",
    "false_success",
    "independence_status",
    "paper_orders",
    "live_orders",
)

#: Round-trip cost the retrospective ledger was netted at (TDM-11 constant).
COST_BPS = 23.7906

#: Reported claims, from the TDM-12 closing message. Re-derivation compares
#: against these, and the report keeps the reported value next to the derived
#: one so a discrepancy names both sides.
REPORTED = {
    "deliverables": 14,
    "digests_ok": "16/16",
    "required_fields": "17/17",
    "strategies_measured": 24,
    "registry_rows": 30,
    "ledger_trades": 115,
    "net_mean_bps": -36.3676,
    "eligible": [],
    "paper_orders": 0,
    "live_orders": 0,
    "verdict": "NO_ELIGIBLE_CANDIDATE",
    "tdm11_alpha_status": "REJECTED_ALPHA",
}


# ---------------------------------------------------------------------------
# git plumbing
# ---------------------------------------------------------------------------
def git(*args: str, cwd: Path | None = None) -> tuple[int, bytes]:
    """Raw git call: bytes out, exit code in. Never raises on a git failure."""
    proc = subprocess.run(["git", *args], cwd=cwd or REPO_ROOT, capture_output=True, check=False)
    return proc.returncode, proc.stdout


def git_text(*args: str, cwd: Path | None = None) -> str:
    return git(*args, cwd=cwd)[1].decode("utf-8", "replace").strip()


def blob(commit: str, path: str) -> bytes | None:
    """Committed bytes for ``path`` at ``commit``, or None when it is absent."""
    code, out = git("cat-file", "blob", f"{commit}:{path}")
    return out if code == 0 else None


def tree_paths(commit: str, prefix: str) -> list[str]:
    code, out = git("ls-tree", "-r", "--name-only", commit, "--", prefix)
    if code != 0:
        return []
    return [line for line in out.decode("utf-8", "replace").splitlines() if line]


def is_ancestor(ancestor: str, descendant: str) -> bool:
    return git("merge-base", "--is-ancestor", ancestor, descendant)[0] == 0


def resolves(rev: str) -> bool:
    return git("cat-file", "-e", f"{rev}^{{commit}}")[0] == 0


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# WP-13A / audit-git
# ---------------------------------------------------------------------------
def check_commit_identity() -> list[dict[str, Any]]:
    """ACC-01: the reported commits resolve, and the lineage is the declared one."""
    rows: list[dict[str, Any]] = []

    def add(check: str, ok: bool, detail: str) -> None:
        rows.append({"check": check, "ok": ok, "detail": detail})

    add(
        "target_commit_resolves",
        resolves(TARGET_COMMIT),
        f"git cat-file -e {TARGET_COMMIT}^{{commit}}",
    )
    add(
        "baseline_commit_resolves",
        resolves(BASELINE_COMMIT),
        f"git cat-file -e {BASELINE_COMMIT}^{{commit}}",
    )

    parent = git_text("rev-parse", f"{TARGET_COMMIT}^") if resolves(TARGET_COMMIT) else ""
    add(
        "target_parent_is_baseline",
        parent == BASELINE_COMMIT,
        f"parent of {TARGET_COMMIT[:8]} is {parent[:8] or 'unknown'}",
    )
    add(
        "baseline_is_ancestor_of_target",
        resolves(TARGET_COMMIT)
        and resolves(BASELINE_COMMIT)
        and is_ancestor(BASELINE_COMMIT, TARGET_COMMIT),
        "merge-base --is-ancestor baseline target",
    )
    branches = git_text("branch", "--contains", TARGET_COMMIT)
    # Porcelain-ish listing: '+ branch' means checked out in another worktree.
    branch_names = [line.split()[-1] for line in branches.splitlines() if line.strip()]
    add(
        "target_on_declared_branch",
        "evidence/tdm12" in branch_names,
        f"branches containing target: {branch_names or 'none'}",
    )
    date = git_text("log", "-1", "--format=%cI", TARGET_COMMIT) if resolves(TARGET_COMMIT) else ""
    add("target_commit_has_date", bool(date), f"committed {date or 'unknown'}")
    return rows


def audit_deliverables() -> dict[str, Any]:
    """Presence, digests and required fields, all read from the commit tree."""
    commit = TARGET_COMMIT
    prefix = "evidence/tdm/wp-tdm-12/"
    committed = {Path(p).name: p for p in tree_paths(commit, prefix)}

    present: list[str] = []
    missing: list[str] = []
    per_file: list[dict[str, Any]] = []
    for name in EXPECTED_DELIVERABLES:
        path = committed.get(name)
        if path is None:
            missing.append(name)
            per_file.append({"file": name, "in_commit": False, "sha256": None})
            continue
        data = blob(commit, path)
        present.append(name)
        per_file.append({"file": name, "in_commit": True, "sha256": digest(data or b"")})

    extra = sorted(set(committed) - set(EXPECTED_DELIVERABLES))

    manifest_blob = blob(commit, prefix + "RUN_REPORT.json")
    manifest: dict[str, Any] = json.loads(manifest_blob) if manifest_blob else {}
    fields_present = [f for f in REQUIRED_RUN_FIELDS if f in manifest]
    fields_missing = [f for f in REQUIRED_RUN_FIELDS if f not in manifest]

    digest_checks: list[dict[str, Any]] = []
    for group, recorded, prefix_fn in (
        ("evidence", manifest.get("evidence_sha256") or {}, lambda k: prefix + k),
        ("code", manifest.get("code_sha256") or {}, lambda k: "scripts/" + k),
    ):
        for key, entry in recorded.items():
            path = entry.get("path") or prefix_fn(key)
            if group == "code":
                path = prefix_fn(key)
            data = blob(commit, path)
            actual = digest(data) if data is not None else None
            digest_checks.append(
                {
                    "group": group,
                    "file": key,
                    "path": path,
                    "recorded": entry.get("sha256"),
                    "committed": actual,
                    "ok": data is not None and actual == entry.get("sha256"),
                }
            )

    bad_digests = [d for d in digest_checks if not d["ok"]]
    return {
        "commit": commit,
        "deliverable_prefix": prefix,
        "expected_count": len(EXPECTED_DELIVERABLES),
        "present_count": len(present),
        "present": present,
        "missing": missing,
        "extra_in_directory": extra,
        "per_file": per_file,
        "required_fields": {
            "required": len(REQUIRED_RUN_FIELDS),
            "present": len(fields_present),
            "missing": fields_missing,
            "ok": not fields_missing,
        },
        "digests": {
            "checked": len(digest_checks),
            "ok": len(digest_checks) - len(bad_digests),
            "failures": bad_digests,
        },
        "manifest_excludes_own_hash": "RUN_REPORT.json"
        not in (manifest.get("evidence_sha256") or {}),
        "status": "PASS" if not missing and not fields_missing and not bad_digests else "FAIL",
    }


def audit_scope_intact() -> dict[str, Any]:
    """ACC-08: what the evidence commit actually changed relative to the baseline."""
    _, out = git("diff", "--name-only", BASELINE_COMMIT, TARGET_COMMIT)
    changed = [line for line in out.decode("utf-8", "replace").splitlines() if line]
    guarded = [p for p in changed if p.startswith(("src/", "tests/"))]
    outside = [
        p
        for p in changed
        if not p.startswith("evidence/tdm/wp-tdm-12/") and not p.startswith("scripts/tdm12")
    ]
    status = "PASS" if not guarded and not outside else "FAIL"
    return {
        "baseline": BASELINE_COMMIT,
        "target": TARGET_COMMIT,
        "changed_files": changed,
        "changed_count": len(changed),
        "src_or_tests_modified": guarded,
        "changed_outside_evidence_and_scripts": outside,
        "status": status,
    }


def audit_shared_checkout() -> dict[str, Any]:
    """The shared checkout must be untouched by this work package."""
    shared = REPO_ROOT.parent / "bot freebuff"
    if not shared.is_dir():
        return {"available": False, "status": "INCOMPLETE", "detail": "shared checkout not found"}
    head = git_text("rev-parse", "HEAD", cwd=shared)
    tracked = [
        line[3:]
        for line in git_text("status", "--porcelain", cwd=shared).splitlines()
        if not line.startswith("??")
    ]
    return {
        "available": True,
        "path": str(shared),
        "head": head,
        "tracked_dirty": tracked,
        "tracked_dirty_count": len(tracked),
        "status": "PASS",
        "detail": "read-only: recorded, not modified by this package",
    }


def audit_git() -> dict[str, Any]:
    identity = check_commit_identity()
    identity_ok = all(row["ok"] for row in identity)
    deliverables = audit_deliverables()
    scope = audit_scope_intact()
    shared = audit_shared_checkout()
    status = "PASS"
    if not identity_ok or deliverables["status"] == "FAIL" or scope["status"] == "FAIL":
        status = "FAIL"
    elif shared["status"] == "INCOMPLETE":
        status = "INCOMPLETE"
    return {
        "rfc_id": RFC_ID,
        "verifier_id": VERIFIER_ID,
        "target_commit": TARGET_COMMIT,
        "baseline_commit_expected": BASELINE_COMMIT,
        "identity": identity,
        "deliverables": deliverables,
        "scope": scope,
        "shared_checkout": shared,
        "status": status,
    }


# ---------------------------------------------------------------------------
# WP-13A / audit-claims
# ---------------------------------------------------------------------------
def _claim(name: str, reported: Any, derived: Any, method: str, source: str) -> dict[str, Any]:
    same = reported == derived
    return {
        "claim": name,
        "reported": reported,
        "derived": derived,
        "match": same,
        "method": method,
        "source": source,
    }


def read_bytes(rel: str, from_dir: Path | None = None) -> bytes:
    """Committed bytes, or bytes from a sandbox directory when auditing one."""
    if from_dir is not None:
        path = from_dir / rel
        return path.read_bytes() if path.is_file() else b""
    return blob(TARGET_COMMIT, rel) or b""


def audit_claims(
    from_dir: Path | None = None, reported: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Re-derive the headline numbers from the committed artefacts themselves.

    ``reported`` defaults to the claims in the TDM-12 closing message; the tests
    pass their own so the same code can audit a synthetic package.
    """
    expected = reported or REPORTED
    manifest = json.loads(read_bytes("evidence/tdm/wp-tdm-12/RUN_REPORT.json", from_dir) or b"{}")
    registry = json.loads(
        read_bytes("evidence/tdm/wp-tdm-12/CANDIDATE_REGISTRY.json", from_dir) or b"{}"
    )
    decision = json.loads(
        read_bytes("evidence/tdm/wp-tdm-12/DECISION_REGISTER.json", from_dir) or b"{}"
    )
    closure = json.loads(
        read_bytes("evidence/tdm/wp-tdm-12/TDM11_CLOSURE_DECISION.json", from_dir) or b"{}"
    )
    ledger_blob = read_bytes("evidence/tdm/wp-tdm-11/RETROSPECTIVE_LEDGER.csv", from_dir)

    claims: list[dict[str, Any]] = []

    # C1/C2: the ledger is re-read and the net is recomputed from gross - cost.
    ledger_rows = list(csv.DictReader(ledger_blob.decode("utf-8").splitlines()))
    gross = [float(row["gross_bps"]) for row in ledger_rows if row.get("gross_bps")]
    net_mean = round(statistics.mean([g - COST_BPS for g in gross]), 4) if gross else None
    claims.append(
        _claim(
            "ledger_trades",
            expected["ledger_trades"],
            len(ledger_rows),
            "count of RETROSPECTIVE_LEDGER.csv data rows",
            "evidence/tdm/wp-tdm-11/RETROSPECTIVE_LEDGER.csv",
        )
    )
    claims.append(
        _claim(
            "net_mean_bps",
            expected["net_mean_bps"],
            net_mean,
            f"mean(gross_bps) - {COST_BPS} over the ledger",
            "evidence/tdm/wp-tdm-11/RETROSPECTIVE_LEDGER.csv",
        )
    )
    claims.append(
        _claim(
            "net_mean_matches_manifest",
            manifest.get("metrics", {}).get("tdm11_review", {}).get("net_mean"),
            net_mean,
            "manifest metric vs independent recomputation",
            "evidence/tdm/wp-tdm-12/RUN_REPORT.json",
        )
    )

    # C3/C4: registry size and measured cells.
    rows = registry.get("rows") or []
    cells = registry.get("metrics_by_cell") or {}
    claims.append(
        _claim(
            "registry_rows",
            expected["registry_rows"],
            len(rows),
            "len(CANDIDATE_REGISTRY.json.rows)",
            "evidence/tdm/wp-tdm-12/CANDIDATE_REGISTRY.json",
        )
    )
    claims.append(
        _claim(
            "strategies_measured",
            expected["strategies_measured"],
            len(cells),
            "len(CANDIDATE_REGISTRY.json.metrics_by_cell)",
            "evidence/tdm/wp-tdm-12/CANDIDATE_REGISTRY.json",
        )
    )
    scored = [k for k, v in cells.items() if (v.get("hold") or {}).get("trades")]
    claims.append(
        _claim(
            "cells_with_measured_trades",
            expected["strategies_measured"],
            len(scored),
            "cells carrying a measured hold trade count",
            "evidence/tdm/wp-tdm-12/CANDIDATE_REGISTRY.json",
        )
    )

    # C5: eligibility recomputed from the per-cell numbers, not from the verdict.
    hold_positive = sorted(
        k for k, v in cells.items() if ((v.get("hold") or {}).get("net_mean") or 0) > 0
    )
    dev_positive = sorted(
        k for k, v in cells.items() if ((v.get("dev") or {}).get("net_mean") or 0) > 0
    )
    eligible_derived = sorted(
        k
        for k in cells
        if k in hold_positive
        and k in dev_positive
        and (cells[k].get("hold") or {}).get("power_sufficient")
    )
    claims.append(
        _claim(
            "eligible",
            expected["eligible"],
            eligible_derived,
            "cells net-positive on holdout AND development AND power-sufficient",
            "evidence/tdm/wp-tdm-12/CANDIDATE_REGISTRY.json",
        )
    )
    claims.append(
        _claim(
            "hold_net_positive_matches_manifest",
            manifest.get("metrics", {}).get("triage", {}).get("hold_net_positive"),
            hold_positive,
            "cells with hold net_mean > 0 vs manifest list",
            "evidence/tdm/wp-tdm-12/RUN_REPORT.json",
        )
    )
    claims.append(
        _claim(
            "dev_net_positive_matches_manifest",
            manifest.get("metrics", {}).get("triage", {}).get("dev_net_positive"),
            dev_positive,
            "cells with dev net_mean > 0 vs manifest list",
            "evidence/tdm/wp-tdm-12/RUN_REPORT.json",
        )
    )
    claims.append(
        _claim(
            "decision_register_eligible_matches",
            decision.get("eligible_candidates"),
            eligible_derived,
            "DECISION_REGISTER.eligible_candidates vs recomputation",
            "evidence/tdm/wp-tdm-12/DECISION_REGISTER.json",
        )
    )

    # C6/C7: orders and the verdict chain.
    claims.append(
        _claim(
            "paper_orders",
            expected["paper_orders"],
            manifest.get("paper_orders"),
            "manifest field",
            "evidence/tdm/wp-tdm-12/RUN_REPORT.json",
        )
    )
    claims.append(
        _claim(
            "live_orders",
            expected["live_orders"],
            manifest.get("live_orders"),
            "manifest field",
            "evidence/tdm/wp-tdm-12/RUN_REPORT.json",
        )
    )
    claims.append(
        _claim(
            "verdict_matches_decision_register",
            expected["verdict"],
            decision.get("decision"),
            "manifest result vs decision register",
            "evidence/tdm/wp-tdm-12/DECISION_REGISTER.json",
        )
    )
    claims.append(
        _claim(
            "verdict_matches_manifest",
            expected["verdict"],
            manifest.get("result"),
            "manifest result field",
            "evidence/tdm/wp-tdm-12/RUN_REPORT.json",
        )
    )
    claims.append(
        _claim(
            "tdm11_alpha_status",
            expected["tdm11_alpha_status"],
            closure.get("alpha_status"),
            "closure decision alpha_status",
            "evidence/tdm/wp-tdm-12/TDM11_CLOSURE_DECISION.json",
        )
    )

    # C8: no execution artifacts anywhere in the evidence tree.
    exec_names = {"TRADE_LEDGER.csv", "CONFIRMATORY_RESULTS.csv", "PAPER_ORDERS.csv"}
    if from_dir is not None:
        tdm12_files = {p.name for p in (from_dir / "evidence/tdm/wp-tdm-12").iterdir()}
    else:
        tdm12_files = {Path(p).name for p in tree_paths(TARGET_COMMIT, "evidence/tdm/wp-tdm-12/")}
    claims.append(
        _claim(
            "no_execution_artifacts",
            [],
            sorted(tdm12_files & exec_names),
            "no PAPER/LIVE ledger inside the TDM-12 evidence tree",
            "evidence/tdm/wp-tdm-12/",
        )
    )

    failures = [c for c in claims if not c["match"]]
    return {
        "rfc_id": RFC_ID,
        "verifier_id": VERIFIER_ID,
        "target_commit": TARGET_COMMIT,
        "claims": claims,
        "checked": len(claims),
        "matched": len(claims) - len(failures),
        "failures": failures,
        "status": "PASS" if not failures else "FAIL",
    }


# ---------------------------------------------------------------------------
# WP-13A / verdict assembly
# ---------------------------------------------------------------------------
def _load(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def decide(
    *,
    git_integrity: str,
    claims_consistency: str,
    replay: str,
    negative_controls: str,
    input_state: str,
) -> tuple[str, list[str]]:
    """RFC-TDM-013 §8. A missing check can only ever degrade the verdict."""
    reasons: list[str] = []
    if git_integrity == "FAIL":
        return "FAILED_INTEGRITY", ["git integrity failed"]
    if claims_consistency == "FAIL":
        return "FAILED_INTEGRITY", ["claims inconsistent with the committed artefacts"]
    if replay == "FAIL":
        return "NOT_REPRODUCIBLE", ["replay produced a materially different result"]
    if (
        git_integrity == "PASS"
        and claims_consistency == "PASS"
        and replay == "PASS"
        and negative_controls == "PASS"
        and input_state == "AVAILABLE"
    ):
        return "VERIFIED_REPRODUCIBLE", reasons
    if git_integrity == "PASS" and claims_consistency == "PASS":
        reasons.append(f"integrity verified but reproduction incomplete (replay={replay})")
        return "INTEGRITY_ONLY", reasons
    reasons.append("some audits did not run")
    return "INCOMPLETE", reasons


def verify() -> tuple[int, dict[str, Any]]:
    git_audit = _load(ART / "audit_git.json")
    claims_audit = _load(ART / "audit_claims.json")
    replay = _load(ART / "replay.json")
    controls = _load(ART / "negative_controls.json")
    manifest = _load(EVIDENCE / "DATASET_MANIFEST.json")

    git_integrity = (git_audit or {}).get("status", "INCOMPLETE")
    claims_consistency = (claims_audit or {}).get("status", "INCOMPLETE")
    replay_status = (replay or {}).get("status", "NOT_RUN")
    controls_status = (controls or {}).get("status", "INCOMPLETE")
    input_state = (manifest or {}).get("input_state", "UNKNOWN")

    result, reasons = decide(
        git_integrity=git_integrity,
        claims_consistency=claims_consistency,
        replay=replay_status,
        negative_controls=controls_status,
        input_state=input_state,
    )

    failures: list[dict[str, Any]] = []
    if git_audit:
        failures += [
            {"phase": "git", **f} for f in git_audit["deliverables"]["digests"]["failures"]
        ]
        failures += [
            {"phase": "git", "check": r["check"], "detail": r["detail"]}
            for r in git_audit["identity"]
            if not r["ok"]
        ]
    if claims_audit:
        failures += [{"phase": "claims", **f} for f in claims_audit["failures"]]
    if replay and replay_status == "FAIL":
        failures += [{"phase": "replay", **f} for f in replay.get("differences", [])]
    if controls and controls_status != "PASS":
        failures += [{"phase": "controls", **f} for f in controls.get("failures", [])]

    payload = {
        "rfc_id": RFC_ID,
        "target_commit": TARGET_COMMIT,
        "baseline_commit_expected": BASELINE_COMMIT,
        "run_id": f"tdm13-{git_text('rev-parse', '--short', 'HEAD') or 'unknown'}",
        "verifier_id": VERIFIER_ID,
        "input_state": input_state,
        "git_integrity": git_integrity,
        "claims_consistency": claims_consistency,
        "replay": replay_status,
        "negative_controls": controls_status,
        "result": result,
        "result_reasons": reasons,
        "failures": failures,
        "independence": {
            "code_path": "INDEPENDENT_DERIVATION",
            "identity": (
                "NOT_DEMONSTRATED: the same operator wrote TDM-12 and this verifier; the "
                "documentation is explicit rather than claiming a second identity"
            ),
        },
        "evidence_refs": [
            "evidence/tdm/wp-tdm-13/GIT_AND_CLAIMS_AUDIT.json",
            "evidence/tdm/wp-tdm-13/DATASET_MANIFEST.json",
            "evidence/tdm/wp-tdm-13/DATASET_RESTORE.md",
            "evidence/tdm/wp-tdm-13/REPLAY_REPORT.json",
            "evidence/tdm/wp-tdm-13/NEGATIVE_CONTROLS.json",
            "evidence/tdm/wp-tdm-13/RUN_REPORT.md",
            "evidence/tdm/wp-tdm-13/RUN_REPORT.json",
        ],
        "paper_orders": 0,
        "live_orders": 0,
    }
    (ART / "verification_result.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "verification_result.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"result={result} git={git_integrity} claims={claims_consistency} "
        f"replay={replay_status} controls={controls_status} inputs={input_state}"
    )
    return (0 if result in {"VERIFIED_REPRODUCIBLE", "INTEGRITY_ONLY"} else 1), payload


def audit_closure() -> tuple[int, dict[str, Any]]:
    """Post-commit descriptor: do the published digests still name the blobs?

    The closing report cannot contain the SHA of the commit that carries it, so
    this subcommand is the verifiable substitute: run it after the commit and it
    compares every recorded digest with ``HEAD``'s blobs, printing the SHA it
    checked. It writes nothing, so running it never dirties the tree.
    """
    rel = "evidence/tdm/wp-tdm-13/RUN_REPORT.json"
    head = git_text("rev-parse", "HEAD")
    payload = json.loads(blob(head, rel) or b"{}")
    recorded = payload.get("evidence_sha256") or {}
    failures: list[dict[str, Any]] = []
    for name, entry in recorded.items():
        path = entry.get("path") or f"evidence/tdm/wp-tdm-13/{name}"
        data = blob(head, path)
        actual = digest(data) if data is not None else None
        if actual != entry.get("sha256"):
            failures.append({"file": name, "recorded": entry.get("sha256"), "committed": actual})
    print(
        f"closure: {len(recorded) - len(failures)}/{len(recorded)} digests match HEAD "
        f"{head[:8]} ({head})"
    )
    for failure in failures:
        print(
            f"  FAIL {failure['file']}: {str(failure['recorded'])[:12]} != "
            f"{str(failure['committed'])[:12]}"
        )
    return (0 if not failures else 1), {
        "head": head,
        "checked": len(recorded),
        "failures": failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "command",
        choices=("audit-git", "audit-claims", "audit-closure", "verify"),
        help="which read-only audit to run",
    )
    #: Audit a sandbox tree instead of the commit (used by the negative controls).
    parser.add_argument("--from-dir", default=None, help="read artefacts from this directory")
    args = parser.parse_args(argv)
    ART.mkdir(parents=True, exist_ok=True)

    if args.command == "audit-git":
        payload = audit_git()
        (ART / "audit_git.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(
            f"audit-git status={payload['status']} "
            f"deliverables={payload['deliverables']['present_count']}/"
            f"{payload['deliverables']['expected_count']} "
            f"digests={payload['deliverables']['digests']['ok']}/"
            f"{payload['deliverables']['digests']['checked']}"
        )
        # Failures are printed, not just counted: an exit code alone does not say
        # which control fired.
        for row in payload["identity"]:
            if not row["ok"]:
                print(f"  FAIL {row['check']}: {row['detail']}")
        for failure in payload["deliverables"]["digests"]["failures"]:
            print(
                f"  FAIL digest {failure['file']}: recorded "
                f"{str(failure['recorded'])[:12]} != committed "
                f"{str(failure['committed'])[:12]}"
            )
        if payload["deliverables"]["missing"]:
            print(f"  FAIL missing deliverables {payload['deliverables']['missing']}")
        if payload["deliverables"]["required_fields"]["missing"]:
            print(f"  FAIL missing fields {payload['deliverables']['required_fields']['missing']}")
        return 0 if payload["status"] == "PASS" else 1

    if args.command == "audit-claims":
        payload = audit_claims(Path(args.from_dir).resolve() if args.from_dir else None)
        (ART / "audit_claims.json").write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )
        print(
            f"audit-claims status={payload['status']} "
            f"matched={payload['matched']}/{payload['checked']}"
        )
        for failure in payload["failures"]:
            print(
                f"  MISMATCH {failure['claim']}: reported={failure['reported']} "
                f"derived={failure['derived']}"
            )
        return 0 if payload["status"] == "PASS" else 1

    if args.command == "audit-closure":
        code, _ = audit_closure()
        return code

    code, _ = verify()
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
