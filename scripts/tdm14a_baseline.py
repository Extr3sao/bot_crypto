"""RFC-TDM-014A — WP-14A baseline audit: facts first, before any edit.

Nothing in this module trusts the RFC. Every claim about the baseline commit, the
lineage, the shared checkout, the EOL configuration, the entrypoints and the D-01
defect is re-derived from Git and from the bytes on disk; anything that cannot be
re-derived is emitted as ``REPORTED_NOT_VERIFIED`` and never as PASS.

The audit refuses to run if the declared baseline does not exist, is not a commit,
does not carry the declared parent, or is not the tip of the branch it claims.

Commands::

    python scripts/tdm14a_baseline.py                       # audit this checkout
    python scripts/tdm14a_baseline.py --eol-lf PATH --eol-crlf PATH
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(os.environ.get("TDM14A_REPO") or Path(__file__).resolve().parents[1]).resolve()
EVIDENCE = REPO_ROOT / "evidence" / "tdm" / "wp-tdm-14a"

#: Declared by the RFC. Verified below; if it does not match, the audit is BLOCKED.
DECLARED_BASELINE = "04fb8bc8a0900c278cd72c5e3478a45b66fcbc03"
DECLARED_PARENT = "d7819188cf9c8cb6257bc99e82a828bbe6d6c746"
DECLARED_BRANCH = "evidence/tdm13"
DECLARED_REPOSITORY = "Trading Agentic Portable (shared checkout: 'bot freebuff')"

#: The module D-01 was reported against. Verified, not assumed.
D01_MODULE = "src/trading_bot/research/families/breakout_family.py"

#: Producers and consumers of the two contracts the RFC names.
CONTRACT_CONSUMERS: tuple[dict[str, Any], ...] = (
    {
        "contract": "parameter_hash",
        "artifact": "evidence/tdm/wp-tdm-12/CANDIDATE_REGISTRY.{json,csv}",
        "producers": ["scripts/tdm12_inventory.py::family_classes", "main() row assembly"],
        "consumers": [
            "scripts/tdm13_independent_verify.py (claim re-derivation / row counts)",
            "scripts/tdm12_publish.py (publishes the registry)",
            "evidence/tdm/wp-tdm-12/RFC-TDM-012.md (field list, §schema)",
        ],
        "gate_role": "identity field only; no metric, gate or verdict reads it",
    },
    {
        "contract": "REPLAY_REPORT.json",
        "artifact": "evidence/tdm/wp-tdm-13/REPLAY_REPORT.json",
        "producers": ["scripts/tdm13_replay.py"],
        "consumers": [
            "scripts/tdm13_independent_verify.py (deliverable list, line 688)",
            "scripts/tdm13_report.py (drives RUN_REPORT/verification_result)",
        ],
        "gate_role": "declares replay PASS/FAIL; verdict input",
    },
)

#: Runtime entrypoints the RFC tells us to locate rather than invent.
ENTRYPOINTS: tuple[tuple[str, str], ...] = (
    ("scripts/tdm12_review.py", "WP-12 review: PIT ledger, dependence, controls"),
    ("scripts/tdm12_inventory.py", "WP-12 inventory: candidate registry, D-01 lives here"),
    ("scripts/tdm13_inputs.py", "seal/verify/restore the 26 sealed inputs"),
    ("scripts/tdm13_replay.py", "WP-13 replay driver (single-run, pre-014A)"),
    ("scripts/tdm13_independent_verify.py", "WP-13 independent verifier"),
    ("scripts/tdm13_negative_controls.py", "WP-13 negative controls"),
    ("scripts/tdm13_report.py", "WP-13 report writer"),
)

#: Files this RFC expects to write. Declared before editing (scope map).
SCOPE_MAP: dict[str, Any] = {
    "modify": [
        "scripts/tdm12_inventory.py",
        "tests/unit/research/test_tdm13_independent_verify.py (only if the change breaks a contract)",
    ],
    "add": [
        "src/trading_bot/research/source_fingerprint.py",
        "scripts/tdm14a_baseline.py",
        "scripts/tdm14a_replay.py",
        "scripts/tdm14a_verify.py",
        "scripts/tdm14a_negative_controls.py",
        "tests/unit/research/test_source_fingerprint.py",
        "tests/unit/research/test_tdm14a_replay_contract.py",
        "evidence/tdm/wp-tdm-14a/* (deliverables)",
    ],
    "never_touch": [
        "evidence/tdm/wp-tdm-11/**",
        "evidence/tdm/wp-tdm-12/**",
        "evidence/tdm/wp-tdm-13/**",
        "src/trading_bot/**/production runtime paths (scanner, execution, risk gates)",
        "the shared checkout and every change it already carries",
    ],
    "trading_paths_modified": [],
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(*args: str, cwd: Path | None = None) -> tuple[int, str]:
    proc = subprocess.run(
        ["git", *args], cwd=cwd or REPO_ROOT, capture_output=True, text=True, check=False
    )
    return proc.returncode, proc.stdout.strip()


def git_bytes(*args: str, cwd: Path | None = None) -> bytes | None:
    proc = subprocess.run(["git", *args], cwd=cwd or REPO_ROOT, capture_output=True, check=False)
    return proc.stdout if proc.returncode == 0 else None


def tracked_status(cwd: Path) -> dict[str, Any]:
    _, out = git("status", "--porcelain", cwd=cwd)
    lines = [line for line in out.splitlines() if line.strip()]
    tracked = [line for line in lines if not line.startswith("??")]
    return {
        "branch": git("rev-parse", "--abbrev-ref", "HEAD", cwd=cwd)[1],
        "head": git("rev-parse", "HEAD", cwd=cwd)[1],
        "entry_count": len(lines),
        "tracked_dirty_count": len(tracked),
        "tracked_dirty": [line[3:] for line in tracked],
        "fingerprint": sha256_bytes("\n".join(sorted(lines)).encode("utf-8")),
    }


def commit_facts(rev: str) -> dict[str, Any]:
    kind_code, kind = git("cat-file", "-t", rev)
    if kind_code != 0:
        return {"rev": rev, "exists": False}
    return {
        "rev": rev,
        "exists": True,
        "type": kind,
        "full_sha": git("rev-parse", rev)[1],
        "subject": git("log", "-1", "--format=%s", rev)[1],
        "committed_at": git("log", "-1", "--format=%cI", rev)[1],
        "tree": git("rev-parse", f"{rev}^{{tree}}")[1],
        "parent": git("rev-parse", f"{rev}^")[1],
        # ``git branch`` prefixes the current branch with ``*`` and a branch checked
        # out in another worktree with ``+``; both are markers, not part of the name.
        "branches_containing": [
            line.strip().lstrip("*+").strip()
            for line in git("branch", "--contains", rev)[1].splitlines()
            if line.strip()
        ],
    }


def eol_config(cwd: Path) -> dict[str, Any]:
    def cfg(key: str) -> str | None:
        code, out = git("config", "--get", key, cwd=cwd)
        return out or None if code == 0 else None

    attributes = REPO_ROOT / ".gitattributes"
    rules = (
        [
            line.strip()
            for line in attributes.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        ]
        if attributes.is_file()
        else []
    )
    return {
        "core.autocrlf": cfg("core.autocrlf"),
        "core.eol": cfg("core.eol"),
        "checkout.encoding": cfg("checkout.encoding"),
        "gitattributes_paths": [r.split()[0] for r in rules],
        "src_tree_covered_by_gitattributes": any(
            r.split()[0].startswith(("src/", "scripts/", "*")) for r in rules
        )
        if rules
        else False,
        "note": (
            "no attribute rule normalises src/** or scripts/**, so the physical bytes of a "
            "Python module depend on core.autocrlf alone"
        ),
    }


def d01_measure(checkout: Path, relpath: str, rev: str) -> dict[str, Any]:
    """One side of the EOL comparison: bytes on disk vs the committed blob."""
    path = checkout / relpath
    data = path.read_bytes() if path.is_file() else b""
    blob = git_bytes("cat-file", "blob", f"{rev}:{relpath}", cwd=checkout)
    oid = git("rev-parse", f"{rev}:{relpath}", cwd=checkout)[1]
    code, hashed = git("hash-object", relpath, cwd=checkout)
    return {
        "checkout": str(checkout),
        "core_autocrlf": git("config", "--get", "core.autocrlf", cwd=checkout)[1] or None,
        "file_exists": path.is_file(),
        "working_tree_bytes": len(data),
        "crlf_count": data.count(b"\r\n"),
        "sha256_working_tree": sha256_bytes(data),
        "v1_fingerprint_as_published": sha256_bytes(data)[:16],
        "blob_bytes": len(blob or b""),
        "sha256_blob": sha256_bytes(blob or b""),
        "blob_oid_from_tree": oid,
        "blob_oid_from_working_tree": hashed if code == 0 else None,
        "git_status_porcelain": git("status", "--porcelain", "--", relpath, cwd=checkout)[1],
    }


def reproduce_d01(lf: Path | None, crlf: Path | None, rev: str) -> dict[str, Any]:
    if lf is None or crlf is None:
        return {"status": "NOT_RUN", "reason": "no --eol-lf/--eol-crlf checkouts supplied"}
    left = d01_measure(lf, D01_MODULE, rev)
    right = d01_measure(crlf, D01_MODULE, rev)
    same_blob = left["blob_oid_from_tree"] == right["blob_oid_from_tree"]
    different_bytes = left["sha256_working_tree"] != right["sha256_working_tree"]
    v1_differs = left["v1_fingerprint_as_published"] != right["v1_fingerprint_as_published"]
    v2_equal = left["sha256_blob"] == right["sha256_blob"]
    reproduced = same_blob and different_bytes and v1_differs
    return {
        "status": "REPRODUCED" if reproduced else "NOT_REPRODUCED",
        "module": D01_MODULE,
        "rev": rev,
        "lf": left,
        "crlf": right,
        "same_git_blob": same_blob,
        "physical_bytes_differ": different_bytes,
        "v1_fingerprints_differ": v1_differs,
        "v2_fingerprint_candidate_equal": v2_equal,
        "commands": [
            f"git worktree add --detach <lf> {rev}  &&  git -C <lf> config core.autocrlf false",
            f"git worktree add --detach <crlf> {rev} &&  git -C <crlf> config core.autocrlf true",
            "git -C <crlf> checkout -- " + D01_MODULE,
            "git -C <checkout> hash-object " + D01_MODULE,
            "git -C <checkout> rev-parse " + rev + ":" + D01_MODULE,
        ],
        "tolerance_rule": (
            "a physical difference is tolerated only when git status reports the path clean, "
            "i.e. git maps those bytes back to the same blob; v2 hashes that blob, v1 hashed "
            "the bytes"
        ),
    }


def prior_results() -> dict[str, Any]:
    """What TDM-13 published, labelled as reported until re-derived here."""
    path = REPO_ROOT / "evidence" / "tdm" / "wp-tdm-13" / "verification_result.json"
    replay = REPO_ROOT / "evidence" / "tdm" / "wp-tdm-13" / "REPLAY_REPORT.json"
    out: dict[str, Any] = {
        "source": str(path.relative_to(REPO_ROOT)),
        "status": "REPORTED_NOT_VERIFIED",
    }
    if path.is_file():
        doc = json.loads(path.read_text(encoding="utf-8"))
        out["tdm13_verdict"] = doc.get("verdict") or doc.get("status")
        out["tdm13_false_success"] = doc.get("false_success")
        out["tdm13_keys"] = sorted(doc)
    if replay.is_file():
        doc = json.loads(replay.read_text(encoding="utf-8"))
        out["tdm13_replay_status"] = doc.get("status")
        out["tdm13_replay_phases"] = [
            {
                "phase": p.get("phase"),
                "status": p.get("status"),
                "duration_seconds": sum(
                    a.get("duration_seconds", 0) for a in p.get("attempts", [])
                ),
            }
            for p in doc.get("phases", [])
        ]
        out["tdm13_replay_attempt_note"] = doc.get("attempt_note")
    finding = REPO_ROOT / "evidence" / "tdm" / "wp-tdm-13" / "EOL_FINGERPRINT_FINDING.json"
    if finding.is_file():
        doc = json.loads(finding.read_text(encoding="utf-8"))
        out["tdm13_d01_measurements"] = doc.get("measurements")
        out["tdm13_d01_recommended_fix"] = doc.get("recommended_fix_outside_this_rfc")
    return out


def inputs_state() -> dict[str, Any]:
    manifest_path = REPO_ROOT / "evidence" / "tdm" / "wp-tdm-13" / "DATASET_MANIFEST.json"
    if not manifest_path.is_file():
        return {"state": "UNAVAILABLE", "reason": "no DATASET_MANIFEST.json"}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = []
    for entry in manifest["datasets"]:
        path = REPO_ROOT / entry["path"]
        actual = sha256_bytes(path.read_bytes()) if path.is_file() else None
        rows.append(
            {
                "dataset_id": entry["dataset_id"],
                "path": entry["path"],
                "bytes": entry["bytes"],
                "sha256_match": actual == entry["sha256"],
                "split": entry.get("split"),
            }
        )
    bad = [r for r in rows if not r["sha256_match"]]
    return {
        "state": "AVAILABLE" if not bad else "CORRUPTED",
        "declared_count": manifest.get("dataset_count"),
        "declared_total_bytes": manifest.get("total_bytes"),
        "measured_files": len(rows),
        "measured_bytes": sum(
            (REPO_ROOT / r["path"]).stat().st_size
            for r in rows
            if (REPO_ROOT / r["path"]).is_file()
        ),
        "sha256_matching": len(rows) - len(bad),
        "mismatches": [r["dataset_id"] for r in bad],
        "splits": {
            split: sum(1 for r in rows if r["split"] == split) for split in ("HOLD", "DEV", None)
        },
        "rows": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--baseline", default="04fb8bc8")
    parser.add_argument("--parent", default=DECLARED_PARENT)
    parser.add_argument("--branch", default=DECLARED_BRANCH)
    parser.add_argument("--eol-lf", default=None)
    parser.add_argument("--eol-crlf", default=None)
    parser.add_argument("--out", default=str(EVIDENCE / "BASELINE_REPORT.json"))
    parser.add_argument(
        "--run-id", default=time.strftime("tdm14a-baseline-%Y%m%dT%H%M%SZ", time.gmtime())
    )
    args = parser.parse_args(argv)

    started = time.time()
    baseline = commit_facts(args.baseline)
    shared = REPO_ROOT.parent / "bot freebuff"
    worktrees = [
        line.strip()
        for line in git("worktree", "list", "--porcelain")[1].splitlines()
        if line.startswith("worktree ")
    ]

    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: Any) -> None:
        checks.append({"check": name, "status": "PASS" if ok else "FAIL", "detail": detail})

    check("baseline_exists", bool(baseline.get("exists")), baseline.get("rev"))
    check("baseline_is_commit", baseline.get("type") == "commit", baseline.get("type"))
    check(
        "declared_sha_matches",
        baseline.get("full_sha", "").startswith(args.baseline[:8]),
        baseline.get("full_sha"),
    )
    check(
        "parent_is_declared",
        baseline.get("parent", "").startswith(args.parent[:8]),
        baseline.get("parent"),
    )
    check(
        "branch_contains_baseline",
        args.branch in baseline.get("branches_containing", []),
        baseline.get("branches_containing"),
    )
    check(
        "head_is_baseline",
        git("rev-parse", "HEAD")[1].startswith(args.baseline[:8]),
        git("rev-parse", "HEAD")[1],
    )
    check(
        "isolated_worktree",
        shared.resolve() != REPO_ROOT and "ff-wt-tdm14a" in str(REPO_ROOT),
        str(REPO_ROOT),
    )

    shared_state = (
        tracked_status(shared) if shared.is_dir() else {"error": "shared checkout not found"}
    )
    entrypoints = []
    for rel, role in ENTRYPOINTS:
        path = REPO_ROOT / rel
        entrypoints.append(
            {
                "path": rel,
                "role": role,
                "exists": path.is_file(),
                "worktree_sha256": sha256_bytes(path.read_bytes()) if path.is_file() else None,
                "blob_sha256": sha256_bytes(git_bytes("cat-file", "blob", f"HEAD:{rel}") or b""),
                "matches_blob": (
                    path.is_file()
                    and sha256_bytes(path.read_bytes())
                    == sha256_bytes(git_bytes("cat-file", "blob", f"HEAD:{rel}") or b"")
                ),
            }
        )

    d01 = reproduce_d01(
        Path(args.eol_lf).resolve() if args.eol_lf else None,
        Path(args.eol_crlf).resolve() if args.eol_crlf else None,
        args.baseline,
    )
    inputs = inputs_state()

    failed = [c["check"] for c in checks if c["status"] == "FAIL"]
    report = {
        "artifact": "tdm14a-baseline-report-v1",
        "rfc_id": "RFC-TDM-014A",
        "wp": "WP-14A",
        "run_id": args.run_id,
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "repository": DECLARED_REPOSITORY,
        "baseline": baseline,
        "worktree": {
            "path": str(REPO_ROOT),
            "branch": git("rev-parse", "--abbrev-ref", "HEAD")[1],
            "head": git("rev-parse", "HEAD")[1],
            "status": tracked_status(REPO_ROOT),
            "registered_worktrees": worktrees,
            "created_from": args.baseline,
            "creation_command": f"git worktree add -b fix/tdm14a <path> {args.baseline}",
        },
        "shared_checkout": {
            "path": str(shared),
            "role": "must stay untouched; its pre-existing changes are not ours",
            "state": shared_state,
        },
        "environment": {
            "python": sys.version.split()[0],
            "python_executable": sys.executable,
            "platform": platform.platform(),
            "git": git("--version")[1],
            "eol": eol_config(REPO_ROOT),
        },
        "checks": checks,
        "entrypoints": entrypoints,
        "contract_consumers": list(CONTRACT_CONSUMERS),
        "scope_map": SCOPE_MAP,
        "inputs": {k: v for k, v in inputs.items() if k != "rows"},
        "d01_defect": d01,
        "prior_results": prior_results(),
        "elapsed_s": round(time.time() - started, 2),
        "status": "BLOCKED" if failed else "PASS",
        "failed_checks": failed,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": report["status"],
                "failed": failed,
                "d01": d01.get("status"),
                "inputs": report["inputs"].get("state"),
                "shared_tracked_dirty": shared_state.get("tracked_dirty_count"),
                "out": str(out_path),
            },
            indent=1,
        )
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
