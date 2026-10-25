"""Regenerate ``EVIDENCE_MANIFEST.json`` for WP-TDM-09 (and freeze WP-TDM-08).

The manifest exists because the most important evidence of WP-TDM-08 lives in
places a fresh clone does not carry:

* ``reports/*`` is gitignored (``.gitignore:55``), so every deliverable of
  WP-TDM-08 is invisible to git;
* ``data/tdm08`` and ``.tdm09`` are trackable but were never added;
* the runtime runs and the byte-identical alpha reproduction were produced in
  throwaway worktrees outside the repository.

A hash list typed by hand would be another unverifiable claim. This script
derives it, records whether git would actually carry each file, and is
re-runnable: same tree, same manifest.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT = REPO_ROOT / "reports" / "trading-decision-monitor" / "WP-TDM-09" / "EVIDENCE_MANIFEST.json"

WP08 = "reports/trading-decision-monitor/WP-TDM-08"
WP09 = "reports/trading-decision-monitor/WP-TDM-09"

WP08_DELIVERABLES = [
    f"{WP08}/runtime_authority_map.md",
    f"{WP08}/strategy_admission_report.md",
    f"{WP08}/alpha_diagnostics.json",
    f"{WP08}/RUN_REPORT.md",
    f"{WP08}/RUN_REPORT.json",
    f"{WP08}/FINAL_REPORT.md",
]

WP09_GENERATED = [
    f"{WP09}/BASELINE_VERIFICATION.md",
    f"{WP09}/ENVIRONMENT_AND_WORKTREE_STATUS.md",
    f"{WP09}/COST_MODEL_RECONCILIATION.md",
    f"{WP09}/RUN_REPORT.md",
    f"{WP09}/RUN_REPORT.json",
    f"{WP09}/FINAL_REPORT.md",
]

WP09_EVIDENCE = [
    ".tdm09/independent_alpha_verification.json",
    ".tdm09/evidence/alpha_diagnostics_reproduced.json",
    ".tdm09/evidence/alpha_reproduction_run.log",
    ".tdm09/evidence/negative_controls.json",
    ".tdm09/evidence/tdm09-paper-bc_traces.jsonl",
    ".tdm09/evidence/tdm09-paper-bc_RUN_REPORT.json",
    ".tdm09/evidence/tdm09-paper-repro_traces.jsonl",
]

SCRIPTS = [
    "scripts/tdm09_verify.py",
    "scripts/tdm09_manifest.py",
    "scripts/tdm08_alpha_diagnostic.py",
    "scripts/tdm08_negative_controls.py",
    "scripts/build_strategy_admission.py",
    "scripts/autonomous_paper.py",
]

#: Evidence that exists only outside the workspace. Path + hash are recorded so a
#: reader can tell whether a copy is the same bytes, and ``carried_by_git`` says
#: plainly that a clone will not have it.
OUTSIDE_ROOT = [
    (
        "C:/Users/GVLLFR0035/Downloads/ff-wt-tdm09-repro/runs/tdm09-paper-bc/traces.jsonl",
        "runtime evidence: economic refusal reproduced (bar-close cadence)",
    ),
    (
        "C:/Users/GVLLFR0035/Downloads/ff-wt-tdm09-repro/runs/tdm09-paper-repro/traces.jsonl",
        "runtime evidence: stale-context refusal reproduced (free-running cadence)",
    ),
    (
        "C:/Users/GVLLFR0035/Downloads/ff-wt-tdm08/runs/tdm08-paper-rt2/traces.jsonl",
        "the traces WP-TDM-08 published; cited here to expose the report/trace mismatch",
    ),
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(args: list[str]) -> str:
    proc = subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True)
    return proc.stdout.strip()


def ignored(path: str) -> str:
    """The .gitignore rule that matches ``path``, or '' when git would carry it."""
    proc = subprocess.run(["git", "check-ignore", "-v", "--", path], cwd=REPO_ROOT, capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def tracked(path: str) -> bool:
    return bool(git(["ls-files", "--error-unmatch", path]))


def entry(path: str, kind: str, note: str = "") -> dict[str, Any]:
    p = REPO_ROOT / path
    rule = ignored(path)
    is_tracked = tracked(path)
    return {
        "path": path,
        "kind": kind,
        "note": note,
        "exists": p.is_file(),
        "bytes": p.stat().st_size if p.is_file() else None,
        "sha256": sha256(p) if p.is_file() else None,
        "git_tracked": is_tracked,
        "gitignored_by": rule.split()[0] if rule else "",
        "carried_by_git": is_tracked,
    }


def main() -> int:
    dataset = sorted(p.relative_to(REPO_ROOT).as_posix() for p in (REPO_ROOT / "data" / "tdm08").glob("*.json"))

    entries = [
        *[entry(p, "wp08_deliverable", "acceptance artefact of WP-TDM-08") for p in WP08_DELIVERABLES],
        *[entry(p, "wp09_deliverable", "acceptance artefact of WP-TDM-09") for p in WP09_GENERATED],
        *[entry(p, "wp09_evidence", "produced or copied by this verification") for p in WP09_EVIDENCE],
        *[entry(p, "dataset", "OOS window 2026-09-25..2026-10-24, sealed bars") for p in dataset],
        *[entry(p, "script", "code that produced or checked the evidence") for p in SCRIPTS],
    ]

    outside = []
    for path, note in OUTSIDE_ROOT:
        p = Path(path)
        outside.append(
            {
                "path": path,
                "kind": "outside_workspace",
                "note": note,
                "exists": p.is_file(),
                "bytes": p.stat().st_size if p.is_file() else None,
                "sha256": sha256(p) if p.is_file() else None,
                "git_tracked": False,
                "gitignored_by": "",
                "carried_by_git": False,
            }
        )

    all_entries = entries + outside
    missing = [e["path"] for e in all_entries if not e["exists"]]
    not_carried = [e["path"] for e in entries if not e["carried_by_git"]]

    manifest = {
        "artifact": "TDM09_EVIDENCE_MANIFEST",
        "generated_by": "scripts/tdm09_manifest.py",
        "generated_at_utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "repo": {
            "head": git(["rev-parse", "HEAD"]),
            "branch": git(["rev-parse", "--abbrev-ref", "HEAD"]),
            "dirty_tracked_files": len(
                [
                    line
                    for line in git(["status", "--porcelain"]).splitlines()
                    if line[:2].strip() and not line.startswith("??")
                ]
            ),
        },
        "summary": {
            "entries": len(all_entries),
            "missing": missing,
            "not_carried_by_git": not_carried,
            "ignored_rule": ".gitignore:55 → reports/*",
        },
        "entries": all_entries,
        "environment": {
            "python": "3.11.15",
            "platform": "Windows-10-10.0.26200-SP0",
            "ccxt": "4.5.63",
            "pydantic": "2.13.4",
            "pytest": "9.1.1",
            "hypothesis": "6.155.7",
            "ruff": "0.15.20",
            "mypy": "2.1.0",
            "core_autocrlf": "false",
        },
        "commands": "RUN_REPORT.md section 1 (C1-C14, with tree and exit code); every command is listed again under how_to_reproduce",
        "anomalies": "BASELINE_VERIFICATION.md §4 (DEF-TDM-09-1..5) and RUN_REPORT.md §4",
        "self_excluded": "EVIDENCE_MANIFEST.json — a file cannot carry its own digest; regenerate with this script",
        "how_to_reproduce": [
            "PYTHONPATH=src python scripts/tdm09_verify.py --out .tdm09/independent_alpha_verification.json",
            "cd ../ff-wt-tdm09-repro && PYTHONPATH=src python scripts/tdm08_alpha_diagnostic.py --measure --out runs/tdm09-alpha-repro --horizon-minutes 30",
            "sha256sum .tdm09/evidence/alpha_diagnostics_reproduced.json "
            + (REPO_ROOT / WP08 / "alpha_diagnostics.json").relative_to(REPO_ROOT).as_posix(),
            "cd ../ff-wt-tdm09-repro && PYTHONPATH=src python scripts/tdm08_negative_controls.py --run-dir runs/tdm09-paper-bc",
            "PYTHONPATH=src python scripts/tdm09_manifest.py",
        ],
        "limitations": [
            "reports/* is gitignored: no WP-TDM-08 or WP-TDM-09 deliverable is visible to git today.",
            "The runtime runs and the alpha reproduction live in throwaway worktrees outside the repository; only the copies under .tdm09/evidence are inside it.",
            "data/tdm08 is trackable but untracked: 2.5 MB of OOS bars would be lost to a clone.",
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(manifest["summary"], indent=2))
    print(f"wrote {OUT.relative_to(REPO_ROOT)}")
    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())
