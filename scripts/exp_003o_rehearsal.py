"""exp_003o_rehearsal — WP-003O-04: reproduce EXP-003O from a clean checkout.

A worktree is created at a commit with no local changes. The only thing copied in is the
external dataset, and only after each file's digest matches the protocol; the raw minutes are
not tracked in this repository, so pretending a clean checkout already has them would be a
convenient lie. Everything else — both producers, the comparator and the verifier — runs from
the committed files.

The comparison is byte-exact for the two evaluation streams and numeric for the summaries.

Usage
-----
``python scripts/exp_003o_rehearsal.py [--commit HEAD] [--json]``
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

from exp_003o_contract import (  # noqa: E402
    DATASET,
    OUT,
    read_json,
    sha256_file,
    write_json,
)

PYTHON = sys.executable
DATASET_RELATIVE = Path("reports/ai-bots/EXP-003K-CANDIDATE-001/dataset")
STAGES = (
    (
        "rebuild",
        [
            "scripts/exp_003o_rebuilder.py",
            "--out",
            "reports/ai-bots/EXP-003O-INDEPENDENT-SIGNAL-VERIFICATION-001/signals/independent_evaluations.jsonl.gz",
        ],
    ),
    (
        "original",
        [
            "scripts/exp_003o_original.py",
            "--out",
            "reports/ai-bots/EXP-003O-INDEPENDENT-SIGNAL-VERIFICATION-001/signals/original_evaluations.jsonl.gz",
            "--check-published",
        ],
    ),
    ("compare", ["scripts/exp_003o_compare.py"]),
    ("verify", ["scripts/exp_003o_verify.py"]),
)


def _run(command: list[str], cwd: Path) -> tuple[int, str]:
    completed = subprocess.run(command, cwd=str(cwd), capture_output=True, text=True, check=False)
    return completed.returncode, (completed.stdout + completed.stderr)


def _git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(cwd or REPO), capture_output=True, text=True, check=False
    ).stdout.strip()


def rehearse(commit: str) -> dict[str, Any]:
    protocol = read_json(OUT / "design" / "PROTOCOL.json")
    tree = Path(tempfile.mkdtemp(prefix="003o-checkout-")) / "tree"
    evidence: dict[str, Any] = {
        "schema_version": "AI_BOTS_003O_CHECKOUT_REPRODUCTION_V1",
        "run_id": protocol["run_id"],
        "generated_at_utc": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "method": {
            "worktree": "git worktree add --detach <commit>; nothing copied from the dirty tree",
            "dataset": "copied in only after each SHA-256 matched the protocol's frozen digest",
            "stages": [stage for stage, _ in STAGES],
            "comparison": "both evaluation streams compared byte for byte; summaries compared on their verdicts and counts",
        },
    }
    try:
        added = _git("worktree", "add", "--detach", str(tree), commit)
        evidence["worktree_add"] = added
        head = _git("rev-parse", "HEAD", cwd=tree)
        dirty = _git("status", "--porcelain", cwd=tree).splitlines()
        evidence["commit"] = head
        evidence["worktree_status_lines_before"] = len(dirty)
        if dirty:
            evidence["verdict"] = "FAIL"
            evidence["error"] = f"the worktree is not clean: {dirty[:3]}"
            return evidence

        target = tree / DATASET_RELATIVE
        target.mkdir(parents=True, exist_ok=True)
        matched = 0
        for symbol, entry in sorted(protocol["source"]["dataset"]["symbols"].items()):
            source = DATASET / str(entry["file"])
            destination = target / str(entry["file"])
            shutil.copy2(source, destination)
            if sha256_file(destination) != entry["sha256_expected"]:
                evidence["verdict"] = "FAIL"
                evidence["error"] = f"{symbol}: dataset digest mismatch after copy"
                return evidence
            matched += 1
        evidence["dataset_digests_matched"] = matched
        evidence["dataset_digests_expected"] = len(protocol["source"]["dataset"]["symbols"])

        stages: list[dict[str, Any]] = []
        for stage, command in STAGES:
            code, output = _run([PYTHON, *command], tree)
            stages.append(
                {"stage": stage, "exit_code": code, "tail": output.strip().splitlines()[-1:]}
            )
            if code != 0:
                evidence["stages"] = stages
                evidence["verdict"] = "FAIL"
                evidence["error"] = f"{stage} exited {code}"
                return evidence
        evidence["stages"] = stages

        reproduced_out = (
            tree / "reports" / "ai-bots" / "EXP-003O-INDEPENDENT-SIGNAL-VERIFICATION-001"
        )
        comparisons: dict[str, Any] = {}
        for name in ("original_evaluations.jsonl.gz", "independent_evaluations.jsonl.gz"):
            published = OUT / "signals" / name
            fresh = reproduced_out / "signals" / name
            comparisons[name] = {
                "published_sha256": sha256_file(published),
                "reproduced_sha256": sha256_file(fresh) if fresh.exists() else None,
                "bit_identical": fresh.exists() and sha256_file(fresh) == sha256_file(published),
            }
        summary = read_json(reproduced_out / "SIGNAL_PARITY_SUMMARY.json")
        verification = read_json(reproduced_out / "VERIFICATION.json")
        published_summary = read_json(OUT / "SIGNAL_PARITY_SUMMARY.json")
        comparisons["SIGNAL_PARITY_SUMMARY.json"] = {
            "mismatches_published": published_summary["mismatches_unexplained"],
            "mismatches_reproduced": summary["mismatches_unexplained"],
            "verdict_published": published_summary["verdict"],
            "verdict_reproduced": summary["verdict"],
            "identical_counts": (
                published_summary["evaluations_compared"] == summary["evaluations_compared"]
                and published_summary["signals_original"] == summary["signals_original"]
                and published_summary["signals_independent"] == summary["signals_independent"]
            ),
        }
        comparisons["VERIFICATION.json"] = {
            "technical_published": read_json(OUT / "VERIFICATION.json")["technical_signal_parity"],
            "technical_reproduced": verification["technical_signal_parity"],
            "checks_reproduced": f"{verification['checks_passed']}/{verification['checks_total']}",
            "controls_reproduced": verification["negative_controls_effective"],
        }
        evidence["comparisons"] = comparisons
        bits_ok = all(
            item.get("bit_identical", True)
            for key, item in comparisons.items()
            if key.endswith(".jsonl.gz")
        )
        counts_ok = comparisons["SIGNAL_PARITY_SUMMARY.json"]["identical_counts"] and (
            summary["mismatches_unexplained"] == published_summary["mismatches_unexplained"]
        )
        technical_ok = verification["technical_signal_parity"] == "PASS"
        evidence["result"] = {
            "streams_bit_identical": bits_ok,
            "counts_identical": counts_ok,
            "technical_reproduced": verification["technical_signal_parity"],
            "checks": f"{verification['checks_passed']}/{verification['checks_total']}",
            "controls": verification["negative_controls_effective"],
            "false_success": verification["false_success_observed"],
        }
        evidence["verdict"] = "REPRODUCED" if (bits_ok and counts_ok and technical_ok) else "FAIL"
        return evidence
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(tree)], cwd=str(REPO), check=False
        )
        subprocess.run(["git", "worktree", "prune"], cwd=str(REPO), check=False)
        shutil.rmtree(tree.parent, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EXP-003O clean-checkout reproduction")
    parser.add_argument("--commit", default="HEAD")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    evidence = rehearse(args.commit)
    write_json(OUT / "CLEAN_CHECKOUT_REPRODUCTION.json", evidence)
    result = evidence.get("result", {})
    print(
        f"[003o-rehearsal] verdict={evidence.get('verdict')} commit={str(evidence.get('commit'))[:7]} "
        f"bit_identical={result.get('streams_bit_identical')} counts={result.get('counts_identical')} "
        f"technical={result.get('technical_reproduced')}"
    )
    if evidence.get("error"):
        print(f"[003o-rehearsal] error: {evidence['error']}", file=sys.stderr)
    if args.json:
        print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence.get("verdict") == "REPRODUCED" else 3


if __name__ == "__main__":
    raise SystemExit(main())
