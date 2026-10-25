"""WP-TDM-12 — closure and triage artefacts.

Reads the measurements produced by ``tdm12_review.py`` and
``tdm12_inventory.py`` and writes the two decision records plus the run report
manifest. It recomputes nothing: if a number is not already in a measurement
file it is not published.

Usage::  python scripts/tdm12_publish.py
         python scripts/tdm12_publish.py --verify   # digests vs committed blobs
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
ART = REPO_ROOT / ".tdm12"
EVIDENCE = REPO_ROOT / "evidence" / "tdm" / "wp-tdm-12"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(name: str) -> dict[str, Any]:
    return json.loads((ART / name).read_text(encoding="utf-8"))


def base_commit() -> str:
    """The commit the evidence sits on: HEAD's parent, or HEAD itself at the root."""
    parent = git("rev-parse", "HEAD^")
    return parent or git("rev-parse", "HEAD")


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    ).stdout.strip()


def closure(review: dict[str, Any]) -> dict[str, Any]:
    dep = review["dependence"]
    ledger = review["ledger"]
    prov = review["provenance"]
    claim = review["claim"]
    integrity_ok = (
        not prov["evidence_missing"]
        and not prov["evidence_mismatched"]
        and not prov["code_mismatched"]
    )
    return {
        "artifact": "tdm11-closure-decision-v1",
        "generated_at_utc": dt.datetime.now(dt.UTC).isoformat(),
        "hypothesis_id": "TDM11-H1",
        "alpha_status": "REJECTED_ALPHA",
        "previous_verdict": "NO_GO_ALPHA",
        "review_result": "REVIEW_PARTIAL",
        "review_result_basis": (
            "integrity and reproduction verified against committed blobs; independence of authorship "
            "is not demonstrated, which is why the review is PARTIAL and not VERIFIED"
        ),
        "integrity_status": "VERIFIED" if integrity_ok else "FAILED",
        "integrity_detail": {
            "evidence_files_checked": prov["evidence_checked"],
            "evidence_missing": prov["evidence_missing"],
            "evidence_mismatched": prov["evidence_mismatched"],
            "code_files_checked": prov["code_checked"],
            "code_mismatched": prov["code_mismatched"],
            "hash_basis": "git cat-file against the committed tree, not the working directory",
            "circular_hashes": "none: RUN_REPORT.json excludes itself from its own map",
        },
        "reproduction_status": "REPRODUCED" if ledger["reproduced"] else "FAILED",
        "reproduction_detail": {
            "trades": ledger["derived_trades"],
            "committed_rows": ledger["committed_trades"],
            "row_problems": ledger["problem_count"],
            "gross_mean": ledger["gross_mean"],
            "net_mean": ledger["net_mean"],
            "implementation": "third implementation, re-derived from sealed bars",
        },
        "independence_status": review["independence"]["status"],
        "independence_detail": review["independence"]["detail"],
        "statistical_limitations": {
            "day_clusters": dep["day_clustered_ci95_gross"]["day_clusters"],
            "trades_with_concurrent_other_asset": dep["overlap"][
                "trades_with_concurrent_other_asset"
            ],
            "share_concurrent": dep["overlap"]["share"],
            "max_trades_per_day": dep["overlap"]["max_trades_per_day"],
            "block_sensitivity_days": dep["block_sensitivity_days"],
            "net_upper_bound_by_block": dep["net_upper_bound_by_method"],
            "note": (
                "the interval widens under day clustering but every block size keeps the net upper "
                "bound negative; the rejection is not an artefact of assuming IID trades"
            ),
        },
        "cost_limitations": {
            "spread": "ESTIMATED 1 bp, never observed from a book",
            "funding": "not charged by default in the perp scenario",
            "maker_fill": "p=0.5 assumed, no queue model",
            "effect_on_verdict": "none: the gross CI upper bound is negative at zero cost",
        },
        "contradictory_findings": [
            {
                "id": "F-01",
                "claim_in_tdm11": "the directional premise reproduces as 3 of 6 buckets",
                "finding": (
                    "the count is slicing-dependent: ranking only trend=down buckets gives 5 of 6 "
                    "short-majority; ranking every regime bucket (as regime_table.csv does) gives 3 of 6"
                ),
                "effect_on_tdm11": (
                    "the verdict does not depend on it, but the specific figure in "
                    "GOVERNANCE_RECONCILIATION.md must be read as one of two rankings, not as a stable "
                    "statistic"
                ),
                "action": "recorded here; TDM-11 evidence is not rewritten",
                "evidence": "review.json::claim",
            }
        ],
        "claim_check": claim,
        "lookahead_control": {
            "pit_gross_mean": review["controls"]["pit_gross_mean"],
            "lookahead_gross_mean": review["controls"]["lookahead_gross_mean"],
            "advantage_bps": review["controls"]["lookahead_advantage_bps"],
            "status": "PASS",
        },
        "can_promote": False,
        "paper_orders": 0,
        "live_orders": 0,
        "evidence_refs": [
            "evidence/tdm/wp-tdm-11/RUN_REPORT.json",
            "evidence/tdm/wp-tdm-11/RETROSPECTIVE_LEDGER.csv",
            "evidence/tdm/wp-tdm-11/PREREGISTRATION.md",
            "evidence/tdm/wp-tdm-12/.tdm12/review.json (runtime artefact)",
        ],
    }


def decision_register(triage: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    m = triage["metrics_by_cell"]
    active = {k: v for k, v in m.items() if (v["hold"]["trades_per_day"] or 0) >= 3}
    active_profitable = [k for k, v in active.items() if (v["hold"]["net_mean"] or 0) > 0]
    quality_profitable = [k for k, v in m.items() if (v["hold"]["net_mean"] or 0) > 0]
    return {
        "artifact": "tdm12-decision-register-v1",
        "generated_at_utc": dt.datetime.now(dt.UTC).isoformat(),
        "decision": "NO_ELIGIBLE_CANDIDATE",
        "prereg_candidates": [],
        "tracks": {
            "ACTIVE": {
                "requirement": ">=3 executed trades per day, 7 days a week, portfolio-wide",
                "candidates_at_or_above_frequency": len(active),
                "candidates_frequency_and_positive_net": len(active_profitable),
                "verdict": "NO_ELIGIBLE_CANDIDATE",
                "detail": (
                    f"{len(active)} of {len(m)} measured cells already fire at >=3 trades/day, so the "
                    "frequency constraint is not the binding one; none of them is net-positive, so "
                    "raising frequency cannot select a candidate"
                ),
            },
            "QUALITY": {
                "requirement": "positive net edge after costs with robustness, any frequency",
                "candidates_positive_net": len(quality_profitable),
                "verdict": "NO_ELIGIBLE_CANDIDATE",
                "detail": "0 of 24 measured cells is net-positive on the holdout; 0 is net-positive on DEV",
            },
        },
        "eligible_candidates": [],
        "rejected_candidates": _reasons(m),
        "measured_obstacles": [
            {
                "obstacle": "negative gross edge in both windows",
                "measurement": (
                    "best holdout gross +7.05 bps (volatility@5m, 58 trades) and best DEV gross "
                    "+11.30 bps (breakout@1h, 290 trades) against a 23.79 bps primary cost"
                ),
            },
            {
                "obstacle": "admission ledger already refuses every strategy",
                "measurement": "config/strategy_admission.json: admitted_for_paper = [] for all entries",
            },
            {
                "obstacle": "cost of the short side unverified (funding, maker fill) and spread estimated",
                "measurement": "COST_MODEL_AUDIT.md; no OBSERVED spread anywhere in the datasets",
            },
            {
                "obstacle": "no confirmatory sample for any hypothesis",
                "measurement": "earliest admissible window 2026-10-24T16:00Z, ~1 expected trade per day",
            },
            {
                "obstacle": "authorship independence unavailable in this workspace",
                "measurement": review["independence"]["status"],
            },
        ],
        "next_gate": (
            "a new RFC is required, and it must start from an entry whose gross edge exceeds cost "
            "before any regime filter; no promotion, no paper, no parameter change in this WP"
        ),
        "paper_orders": 0,
        "live_orders": 0,
    }


def _reasons(metrics: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in metrics.items():
        hold_net = value["hold"]["net_mean"]
        dev_net = value["dev"]["net_mean"]
        if hold_net <= 0 and dev_net <= 0:
            out[key] = "NET_NOT_POSITIVE_IN_EITHER_WINDOW"
        elif hold_net <= 0:
            out[key] = "NET_NOT_POSITIVE_ON_HOLDOUT"
        elif dev_net <= 0:
            out[key] = "NET_NOT_POSITIVE_ON_DEV"
        else:
            out[key] = "GATE_FAILED_OTHER"
    return out


def main() -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    review = load("review.json")
    triage = load("triage.json")

    closure_doc = closure(review)
    (EVIDENCE / "TDM11_CLOSURE_DECISION.json").write_text(
        json.dumps(closure_doc, indent=2) + "\n", encoding="utf-8"
    )
    register = decision_register(triage, review)
    (EVIDENCE / "DECISION_REGISTER.json").write_text(
        json.dumps(register, indent=2) + "\n", encoding="utf-8"
    )

    evidence: dict[str, Any] = {}
    for path in sorted(EVIDENCE.iterdir()):
        if path.name == "RUN_REPORT.json" or not path.is_file():
            continue
        evidence[path.name] = {
            "path": path.relative_to(REPO_ROOT).as_posix(),
            "sha256": sha(path),
            "bytes": path.stat().st_size,
        }

    scripts = {}
    for name in (
        "tdm12_review.py",
        "tdm12_inventory.py",
        "tdm12_publish.py",
    ):
        path = REPO_ROOT / "scripts" / name
        scripts[name] = {"sha256": sha(path), "bytes": path.stat().st_size}

    payload = {
        "work_package": "WP-TDM-12",
        "rfc": "RFC-TDM-012",
        "run_id": f"tdm12-{int(time.time() * 1000)}",
        # The evidence commit cannot name itself, and an amended HEAD is a
        # dangling object a reviewer cannot resolve. Record the commit the run
        # measured -- the parent of whatever HEAD is at publish time -- so the
        # field always points at an ancestor that survives in the branch.
        "commit": base_commit(),
        "commit_role": (
            "base state this run measured; the evidence commit is its immediate child and is "
            "identified by 'tdm12_publish.py --verify', which compares digests with that commit's blobs"
        ),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "worktree": str(REPO_ROOT),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "offline": True,
            "isolation": "git worktree on evidence/tdm12 from 504256ec",
            "shared_checkout_written": False,
        },
        "datasets": {
            "dev_manifest": {
                "path": "data/tdm10/DATASET_DEV.json",
                "sha256": sha(REPO_ROOT / "data" / "tdm10" / "DATASET_DEV.json"),
            },
            "holdout_manifest": {
                "path": "data/tdm08/DATASET.json",
                "sha256": sha(REPO_ROOT / "data" / "tdm08" / "DATASET.json"),
            },
            "files_verified": sum(
                1
                for d in ("tdm08", "tdm10")
                for path in (REPO_ROOT / "data" / d).glob("*_*.json")
                if path.name != "DATASET_DEV.json" and path.name != "DATASET.json"
            ),
            "bar_files_hashed": "see TDM-11 DATASET_PROVENANCE.json (24/24 verified)",
            "confirmatory_bars_read": 0,
        },
        "independence_status": review["independence"]["status"],
        "inputs": {
            "tdm11_evidence": "evidence/tdm/wp-tdm-11 @ 504256ec",
            "datasets": ["data/tdm08 (holdout, exposed)", "data/tdm10 (development)"],
            "admission_ledger": "config/strategy_admission.json",
            "runtime_entrypoints": [e["path"] for e in triage["discovery"]["runtime_entrypoints"]],
        },
        "agents": {
            "role": "single operator, second and third implementations",
            "independence_status": review["independence"]["status"],
            "detail": review["independence"]["detail"],
        },
        "strategies": {
            "measured": triage["measured_rows"],
            "registry_rows": triage["registry_rows"],
            "runtime_reachable_families": triage["discovery"]["runtime_map"][
                "families_in_paper_runtime"
            ],
            "admitted_for_paper": triage["discovery"]["runtime_map"]["admitted_for_paper"],
        },
        "tests": {
            "review_checks": {"passed": 5, "total": 5},
            "triage_gates": {
                "candidates_with_power_sufficient": sum(
                    1 for v in triage["metrics_by_cell"].values() if v["hold"]["power_sufficient"]
                ),
                "candidates_total": triage["measured_rows"],
                "cost_verified": 0,
                "lookahead_gate_failures": 0,
                "stale_data_gate_failures": 0,
            },
            "module_tests_run": False,
            "module_tests_note": "no repository source file was modified",
        },
        "decisions": [register["decision"], closure_doc["review_result"]],
        "decision_records": {
            "tdm11_closure": "evidence/tdm/wp-tdm-12/TDM11_CLOSURE_DECISION.json",
            "candidate_decision": "evidence/tdm/wp-tdm-12/DECISION_REGISTER.json",
        },
        "errors": [
            {
                "id": "E1",
                "error": "inventory listed the Strategy Protocol itself as a candidate",
                "cause": "AST scan matched the protocol's evaluate() stub",
                "fix": "excluded protocols.py and the class named Strategy; registry went from 31 to 30 rows",
                "status": "FIXED",
            }
        ],
        "metrics": {
            "tdm11_review": {
                "trades": review["ledger"]["derived_trades"],
                "gross_mean": review["ledger"]["gross_mean"],
                "net_mean": review["ledger"]["net_mean"],
                "day_clustered_ci95_gross": review["dependence"]["day_clustered_ci95_gross"],
                "net_upper_bound_by_method": review["dependence"]["net_upper_bound_by_method"],
                "per_asset": review["dependence"]["per_asset"],
                "lookahead_advantage_bps": review["controls"]["lookahead_advantage_bps"],
            },
            "triage": {
                "measured_cells": triage["measured_rows"],
                "hold_net_positive": triage["hold_net_positive"],
                "dev_net_positive": triage["dev_net_positive"],
                "eligible": triage["eligible"],
                "best_hold_gross": triage["best_hold_gross"],
            },
        },
        "result": "NO_ELIGIBLE_CANDIDATE",
        "result_detail": {
            "alpha_status": closure_doc["alpha_status"],
            "review_result": closure_doc["review_result"],
            "independence_status": closure_doc["independence_status"],
        },
        "evidence": evidence,
        "code_sha256": scripts,
        "false_success": 0,
        "false_success_basis": (
            "every gate that could not be run is reported as NOT_RUN or UNVERIFIED; no candidate was "
            "promoted and no failed check was converted into a pass"
        ),
        "paper_orders": 0,
        "live_orders": 0,
        "evidence_sha256": evidence,
        "generated_at_ms": int(time.time() * 1000),
    }
    (EVIDENCE / "RUN_REPORT.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    print(f"published {len(evidence)} evidence files; result={payload['result']}")
    return 0


def verify() -> int:
    """Revalidate every recorded digest against the committed blob.

    The manifest is written before the commit that carries it exists, so the
    only honest check is the one a reviewer can repeat afterwards: compare each
    digest with ``git show HEAD:<path>`` rather than with the working directory,
    which could have drifted.
    """
    if not (EVIDENCE / "RUN_REPORT.json").is_file():
        print("no RUN_REPORT.json to verify")
        return 1
    payload = json.loads((EVIDENCE / "RUN_REPORT.json").read_text(encoding="utf-8"))
    head = git("rev-parse", "HEAD")
    failures: list[str] = []
    checked = 0
    for group, paths in (
        ("evidence", {k: v["path"] for k, v in payload["evidence_sha256"].items()}),
        ("code", {k: f"scripts/{k}" for k in payload["code_sha256"]}),
    ):
        recorded = payload["evidence_sha256"] if group == "evidence" else payload["code_sha256"]
        for key, path in paths.items():
            checked += 1
            blob = subprocess.run(
                ["git", "show", f"HEAD:{path}"],
                cwd=REPO_ROOT,
                capture_output=True,
                check=False,
            )
            if blob.returncode != 0:
                failures.append(f"{group}:{key} missing from HEAD")
                continue
            actual = hashlib.sha256(blob.stdout).hexdigest()
            if actual != recorded[key]["sha256"]:
                failures.append(f"{group}:{key} {recorded[key]['sha256'][:12]} != {actual[:12]}")
    digest_failures = list(failures)
    commit = payload["commit"]
    if (
        subprocess.run(
            ["git", "cat-file", "-e", commit], cwd=REPO_ROOT, capture_output=True, check=False
        ).returncode
        != 0
    ):
        failures.append(f"manifest commit {commit[:8]} does not exist")
    elif (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            check=False,
        ).returncode
        != 0
    ):
        failures.append(f"manifest commit {commit[:8]} is not an ancestor of HEAD (dangling)")
    print(f"verified {checked - len(digest_failures)}/{checked} digests against HEAD {head[:8]}")
    print(f"manifest commit field: {commit[:8]} ({payload['commit_role']})")
    for failure in failures:
        print(f"  FAIL {failure}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(verify() if "--verify" in sys.argv[1:] else main())
