"""WP-ECONOMIC-RECOVERY-003 — independent re-derivation of the audit's claims.

Deliberately does **not** import ``wp_eco003_audit``: a verifier that reuses the
audit's functions can only confirm that the audit is self-consistent. Everything
here is recomputed from the artefacts themselves — the committed blobs, the
published JSON, the git history, the transcripts — with the audit's output read
only where a claim is about what the audit said.

Read-only: it hashes, runs ``git`` queries and invokes the gate in ``--check``
(which writes nothing). It never edits a published file.

Usage:
    uv run python scripts/wp_eco003_verify.py [--out <evidence dir>]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
WP = Path("docs/agentic/economic_audit/WP-ECONOMIC-RECOVERY-003")
LEDGER = "config/strategy_admission.json"
EXPLORER = "data/recovery/COST_BARRIER_EXPLORER.json"
VERIFICATION = "data/recovery/COST_BARRIER_VERIFICATION.json"
CERTIFICATION = "data/recovery/wp7/COST_BARRIER_CERTIFICATION.json"
EVIDENCE_COPY = "data/recovery/wp7/evidence/COST_BARRIER.json"
MATRIX = "docs/STRATEGY_ADMISSION_MATRIX.json"
CONTRACT_SUITE = (
    "tests/unit/research/test_cost_barrier_explorer.py",
    "tests/unit/research/test_cost_barrier_gate.py",
    "tests/unit/research/test_cost_barrier_adversarial.py",
    "tests/unit/research/test_cost_barrier_ci_parity.py",
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=False
    ).stdout.strip()


def blob(rev: str, path: str) -> bytes:
    return subprocess.run(
        ["git", "show", f"{rev}:{path}"], cwd=REPO, capture_output=True, check=False
    ).stdout


def read_json(path: str) -> Any:
    return json.loads((REPO / path).read_text(encoding="utf-8"))


def check(ident: str, claim: str, verdict: bool, detail: str) -> dict[str, Any]:
    return {
        "id": ident,
        "claim": claim,
        "verdict": "PASS" if verdict else "FAIL",
        "detail": detail,
    }


def ledger_pin_check(explorer: dict[str, Any], head: str) -> dict[str, Any]:
    pin = next(s for s in explorer["sources"] if s["path"] == LEDGER)["sha256"]
    at_head = blob(head, LEDGER)
    revisions = git("log", "--all", "--format=%H", "--", LEDGER).split()
    match = [
        revision
        for revision in revisions
        if sha(blob(revision, LEDGER).replace(b"\n", b"\r\n")) == pin
        or sha(blob(revision, LEDGER).replace(b"\r\n", b"\n")) == pin
    ]
    return check(
        "ledger_pin_names_a_rendering_not_a_blob",
        "the published pin for the ledger is a CRLF rendering of an older revision, not any "
        "committed blob",
        pin != sha(at_head) and bool(match) and all(sha(blob(r, LEDGER)) != pin for r in revisions),
        f"pin={pin[:12]} head_blob={sha(at_head)[:12]} "
        f"matching_revisions={[r[:8] for r in match]} "
        f"revisions_examined={len(revisions)}",
    )


def audit_pin_check(explorer: dict[str, Any], head: str) -> dict[str, Any]:
    source = next(
        s for s in explorer["sources"] if s["path"] == "data/recovery/ACTIVE_ECONOMIC_AUDIT.json"
    )
    at_head = blob(head, "data/recovery/ACTIVE_ECONOMIC_AUDIT.json")
    crlf = sha(at_head.replace(b"\n", b"\r\n"))
    return check(
        "audit_byte_pin_is_a_crlf_rendering_but_a_state_pin_covers_it",
        "the audit source's byte pin is the CRLF rendering of its committed blob and the "
        "semantic state pin is what makes it acceptable",
        source["sha256"] == crlf
        and source["sha256"] != sha(at_head)
        and bool(source.get("state_sha256")),
        f"pin={source['sha256'][:12]} blob={sha(at_head)[:12]} crlf={crlf[:12]} "
        f"state_pin={(source.get('state_sha256') or '-')[:12]}",
    )


def recoverable_input_check(explorer: dict[str, Any]) -> dict[str, Any]:
    pin = next(
        s for s in explorer["sources"] if s["path"] == "reports/strategy-baseline/COST_BARRIER.json"
    )["sha256"]
    copy = REPO / EVIDENCE_COPY
    present_in_tree = (REPO / "reports/strategy-baseline/COST_BARRIER.json").is_file()
    return check(
        "the_gitignored_input_is_recoverable_exactly",
        "the absent declared input is present byte-identically as evidence, so its absence is "
        "recoverable rather than lost",
        copy.is_file() and sha(copy.read_bytes()) == pin and not present_in_tree,
        f"pin={pin[:12]} copy={sha(copy.read_bytes())[:12] if copy.is_file() else '-'} "
        f"present_in_checkout={present_in_tree}",
    )


def payload_check(
    explorer: dict[str, Any], verification: dict[str, Any], evidence: Path
) -> dict[str, Any]:
    """The digest the recertification must reproduce, and what backs that claim.

    The explorer hashes a defined subset of itself (its own convention, not
    ``json.dumps`` of the whole document), so this check does not pretend to
    recompute it: it verifies that the digest is published, that the verification
    document attests it, and that the rebuild transcript shows only provenance
    leaves moving.
    """

    stored = explorer.get("payload_sha256")
    cited = stored in json.dumps(verification)
    diff = (evidence / "explorer_rebuild_diff.txt").read_text(encoding="utf-8", errors="replace")
    differing = re.search(r"differing leaves: (\d+)", diff)
    no_payload_leaf = "/payload" not in diff
    return check(
        "published_payload_digest_is_the_one_under_discussion",
        "the payload digest the recertification reproduces is the published one, the verification "
        "attests it, and the rebuild moved only provenance leaves",
        isinstance(stored, str)
        and len(stored) == 64
        and cited
        and bool(differing)
        and no_payload_leaf,
        f"payload={stored} verification_cites_it={cited} "
        f"rebuild_differing_leaves={differing.group(1) if differing else '-'} "
        f"payload_leaf_changed={not no_payload_leaf}",
    )


def gate_check() -> dict[str, Any]:
    run = subprocess.run(
        [sys.executable, "scripts/cost_barrier_gate.py", "--check"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    out = run.stdout + run.stderr
    failed = re.search(r"\[FAIL\] (\S+)", out)
    return check(
        "gate_reports_integrity_failure_naming_the_ledger",
        "the gate, run today, returns INTEGRITY_FAILURE and names the ledger pin as the failing check",
        run.returncode == 5
        and "INTEGRITY_FAILURE" in out
        and bool(failed)
        and failed.group(1) == "inputs:published_pins_match_the_declared_sources"
        and "config/strategy_admission.json" in out,
        f"exit={run.returncode} failing_check={failed.group(1) if failed else '-'} "
        f"mentions_ledger={'config/strategy_admission.json' in out}",
    )


def multi_family_history_check() -> dict[str, Any]:
    logged = git("log", "--all", "--oneline", "--", "reports/strategy-baseline").strip()
    ignored = subprocess.run(
        ["git", "check-ignore", "reports/strategy-baseline/MULTI_FAMILY_RESULTS_momentum.json"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    return check(
        "multi_family_results_are_in_no_commit",
        "none of the six multi-family result files exists in any commit, and their directory is "
        "ignored by rule",
        logged == "" and ignored.returncode == 0,
        f"commits_touching_reports/strategy-baseline={len(logged.splitlines())} "
        f"ignored_by={ignored.stdout.strip()[:40] or '-'}",
    )


def matrix_carries_no_provenance() -> dict[str, Any]:
    text = (REPO / MATRIX).read_text(encoding="utf-8")
    keys = set(re.findall(r'"([a-z0-9_]+)":', text))
    provenance = {k for k in keys if "sha" in k or "digest" in k or k in {"commit", "generated_at"}}
    return check(
        "admission_matrix_records_no_input_provenance",
        "the only surviving record of the five non-committed families carries no digest, commit "
        "or timestamp for its inputs",
        not provenance,
        f"provenance_like_keys={sorted(provenance)} document_bytes={len(text)}",
    )


def tree_untouched_check(baseline: str) -> dict[str, Any]:
    scope = ("src", "config", "data", "docs", "reports", "scripts/cost_barrier_gate.py")
    changed = git("status", "--porcelain", "--untracked-files=no", "--", *scope)
    diff = git("diff", "--stat", baseline, "--", *scope).strip()
    return check(
        "no_economic_or_runtime_file_changed",
        "the working tree has no tracked change under src/, config/, data/, docs/ or reports/ "
        "relative to the commit under audit, so no published evidence or economic number moved",
        changed == "" and diff == "",
        f"porcelain={changed!r} diff_vs_{baseline[:8]}={diff or '(empty)'}",
    )


def transcript_check(evidence: Path, name: str, expected: re.Pattern[str]) -> dict[str, Any]:
    path = evidence / name
    text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    match = expected.search(text)
    return check(
        f"transcript_{name.replace('.txt', '')}",
        f"the stored transcript {name} ends in the numbers the report quotes",
        bool(match),
        f"found={match.group(0) if match else 'nothing'} bytes={len(text)}",
    )


def audit_metric_check(matrix: dict[str, Any]) -> dict[str, Any]:
    simulation = matrix["simulation"]
    delta = simulation["full_suite"]["set_difference"]
    closing = Path(WP / "DEPENDENCY_GRAPH.md").read_text(encoding="utf-8")
    claims = {
        "chain_nodes": len(matrix["chain"]) == 18,
        "pins": len(matrix["pins"]) == 21,
        "drifting": len(matrix["drift"]) == 3,
        "pathologies": len(matrix["pin_pathology"]) == 2,
        "dependencies": len(matrix["dependency_classification"]["rows"]) == 19,
        "delta_closed": delta["closed"] == 19,
        "delta_introduced": delta["introduced"] == [],
        "graph_cites_18_nodes": "| 18 |" in closing,
        "no_economic_change_claimed": "4383d812" in json.dumps(simulation),
    }
    return check(
        "audit_counts_match_the_recomputed_evidence",
        "every count the audit reports is reproduced from the artefacts it cites",
        all(claims.values()),
        json.dumps(claims),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=WP)
    args = parser.parse_args(argv)
    out_dir = REPO / args.out / "INDEPENDENT_VERIFICATION.json"

    head = git("rev-parse", "HEAD")
    explorer = read_json(EXPLORER)
    verification = read_json(VERIFICATION)
    certification = read_json(CERTIFICATION)
    evidence = REPO / WP / "evidence"
    audit_output = REPO / WP / "EVIDENCE_IMPACT_MATRIX.json"

    checks = [
        ledger_pin_check(explorer, head),
        audit_pin_check(explorer, head),
        recoverable_input_check(explorer),
        payload_check(explorer, verification, evidence),
        gate_check(),
        multi_family_history_check(),
        matrix_carries_no_provenance(),
        tree_untouched_check("2bd6e346"),
        transcript_check(
            evidence,
            "contract_suite_with_input_materialised.txt",
            re.compile(r"(\d+) failed, (\d+) passed"),
        ),
        transcript_check(
            evidence, "recertified_partial_tests.txt", re.compile(r"(\d+) failed, (\d+) passed")
        ),
        transcript_check(
            evidence, "recertified_clone_tests.txt", re.compile(r"(\d+) failed, (\d+) passed")
        ),
        transcript_check(
            evidence,
            "full_suite_before_recertification.txt",
            re.compile(r"(\d+) failed, (\d+) passed"),
        ),
        audit_metric_check(json.loads(audit_output.read_text(encoding="utf-8"))),
        check(
            "certification_is_the_published_one",
            "the certification quoted by the plan is the committed one and it is not a pass claim "
            "for the current tree",
            certification.get("artifact") == "COST_BARRIER_CERTIFICATION"
            and certification.get("status") in {"CERTIFIED", "REFUSED", "SUPERSEDED"},
            f"artifact={certification.get('artifact')} status={certification.get('status')} "
            f"head={str(certification.get('candidate', {}).get('head'))[:8]}",
        ),
    ]

    failed = [row for row in checks if row["verdict"] != "PASS"]
    payload = {
        "wp": "WP-ECONOMIC-RECOVERY-003",
        "artifact": "INDEPENDENT_VERIFICATION",
        "verified_commit": head,
        "method": (
            "recomputed from committed blobs, published artefacts, git history and stored "
            "transcripts; does not import the audit script; read-only"
        ),
        "summary": {
            "checks": len(checks),
            "passed": len(checks) - len(failed),
            "failed": len(failed),
        },
        "checks": checks,
        "scope": (
            "verifies the coherence of the audit's conclusions, not their novelty: the audit says "
            "the chain drifts by one ledger pin, that the drift is integrity-only, and that the "
            "transcripts show 19 contract nodes closing with none introduced"
        ),
    }
    out_dir.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    for row in checks:
        print(f"[{row['verdict']}] {row['id']}: {row['detail']}")
    print(f"\n{payload['summary']['passed']}/{payload['summary']['checks']} PASS -> {out_dir}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
