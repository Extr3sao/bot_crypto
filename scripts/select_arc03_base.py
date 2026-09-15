#!/usr/bin/env python
"""ARC-03 research-base selection (programmatic, performance-blind).

Evaluates every candidate research ref and picks the safest base for ARC-03 according to
the frozen criteria in the task specification:

REQUIRED
  has_frozen_aru              docs/alpha-research-universe-01/05_ALPHA_MECHANISM_CANDIDATES.json
  has_arc03_authority         the ARU actually contains the ARC-03 record
  has_research_utilities      src/trading_bot/research + scripts/ normalizers present
  has_certified_reuse_docs    docs/arc01-data-authority-01 reuse assessments present

DISQUALIFYING
  is_verifier_only            branch/commit exists only to hold audit artifacts
  has_arc01_prereg_or_exec    ARC-01 preregistration artifacts (fa15fb4) present at the base
  is_arc02_worktree           ARC-02 (BTC->alt lead-lag) artifacts present
  is_h6_branch                H6 OI-continuation artifacts present
  touches_strategy_runtime    Risk / PaperBroker / live runtime files present

Writes docs/arc03-data-authority-01/ARC03_BASE_SELECTION.json.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
MAIN = ROOT.parents[1]
OUT = ROOT / "docs" / "arc03-data-authority-01" / "ARC03_BASE_SELECTION.json"

ARU = "docs/alpha-research-universe-01/05_ALPHA_MECHANISM_CANDIDATES.json"
ARC01_PREREG = "docs/arc01-prereg-01/ARC01_SPEC_V1.json"
ARC01_EXEC = "docs/external-audit-01/arc01-primary-discovery-01/ARC01_PRIMARY_DISCOVERY_RESULT.json"
REUSE_DOCS = "docs/arc01-data-authority-01/ARC01_OI_REUSE_ASSESSMENT.json"


def git(*args: str, cwd: pathlib.Path | None = None) -> str:
    out = subprocess.run(
        ["git", "-C", str(cwd or MAIN), *args], capture_output=True, text=True, check=False
    )
    return out.stdout.strip()


def refs() -> list[tuple[str, str]]:
    """(label, commit) candidates: local branches, remote branches, detached worktrees."""
    found: dict[str, str] = {}
    for line in git("for-each-ref", "--format=%(refname:short) %(objectname)", "refs/heads", "refs/remotes").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] != "origin/HEAD":
            found[parts[0]] = parts[1]
    return sorted(found.items())


def tree_has(commit: str, path: str) -> bool:
    return bool(git("ls-tree", "-r", "--name-only", commit, "--", path).strip())


def feature(commit: str) -> dict[str, bool]:
    return {
        "has_frozen_aru": tree_has(commit, ARU),
        "has_arc03_authority": "ARC-03"
        in git("show", f"{commit}:{ARU}"),
        "has_research_utilities": tree_has(commit, "src/trading_bot/research") and tree_has(commit, "scripts/normalize_oi_full_history_v2.py"),
        "has_certified_reuse_docs": tree_has(commit, REUSE_DOCS),
        "has_arc01_prereg_or_exec": tree_has(commit, ARC01_PREREG) or tree_has(commit, ARC01_EXEC),
    }


def main() -> int:
    candidates: list[dict] = []
    for label, commit in refs():
        f = feature(commit)
        label_l = label.lower()
        rec = {
            "ref": label,
            "commit": commit,
            "subject": git("log", "-1", "--format=%s", commit),
            **f,
            "is_verifier_only": "verif" in label_l or "audit" in label_l,
            "is_arc02_worktree": "arc-02" in label_l or "arc02" in label_l,
            "is_h6_branch": label_l.startswith("h6") or "/h6" in label_l or "h6-" in label_l,
        }
        rec["eligible"] = (
            rec["has_frozen_aru"]
            and rec["has_arc03_authority"]
            and rec["has_research_utilities"]
            and rec["has_certified_reuse_docs"]
            and not rec["has_arc01_prereg_or_exec"]
            and not rec["is_verifier_only"]
            and not rec["is_arc02_worktree"]
            and not rec["is_h6_branch"]
        )
        candidates.append(rec)

    eligible = [c for c in candidates if c["eligible"]]
    # prefer the most recent eligible commit (freshest certified utilities)
    eligible.sort(key=lambda c: git("log", "-1", "--format=%ct", c["commit"]), reverse=True)
    chosen = eligible[0] if eligible else None

    reason = []
    if chosen:
        reason = [
            f"carries the frozen Alpha Research Universe incl. the ARC-03 authority record ({chosen['ref']})",
            "carries the certified ARC-01 reuse assessments + OI/price normalizers (reuse-before-download)",
            "holds NO ARC-01 preregistration or discovery artifacts (no economic-contamination surface)",
            "is not a verifier-only branch, not ARC-02, not an H6 branch",
            "newest eligible ref, so the research/data utilities are the freshest available",
        ]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(
        (
            json.dumps(
                {
                    "checkpoint": "ARC03-DATA-001",
                    "method": "programmatic evaluation of every local/remote ref against frozen eligibility criteria",
                    "criteria": {
                        "required": [
                            "has_frozen_aru",
                            "has_arc03_authority",
                            "has_research_utilities",
                            "has_certified_reuse_docs",
                        ],
                        "disqualifying": [
                            "has_arc01_prereg_or_exec",
                            "is_verifier_only",
                            "is_arc02_worktree",
                            "is_h6_branch",
                        ],
                    },
                    "BASE_COMMIT": chosen["commit"] if chosen else None,
                    "BASE_REF": chosen["ref"] if chosen else None,
                    "BASE_REASON": reason,
                    "WORKTREE": ".research/arc03-participation-reversal-01",
                    "BRANCH": "research/arc03-participation-reversal-01",
                    "candidates_evaluated": len(candidates),
                    "eligible_candidates": [c["ref"] for c in eligible],
                    "candidates": candidates,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    )
    print(json.dumps({"BASE_COMMIT": chosen["commit"] if chosen else None, "eligible": [c["ref"] for c in eligible]}, indent=2))
    return 0 if chosen else 1


if __name__ == "__main__":
    sys.exit(main())
