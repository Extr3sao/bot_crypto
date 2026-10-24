"""Build ``evidence_manifest.json`` for RFC-TAP-PAPER-ADMISSION-REPRO-001.

The manifest is data, not a verdict: it records *what* was preserved, *what* changed and
*which* commit each side of the comparison came from. ``verify_repro.py`` recomputes every
hash from bytes and refuses a manifest that disagrees with the tree, so the two files cannot
drift apart silently.

    python reports/ai-bots/RFC-TAP-PAPER-ADMISSION-REPRO-001/make_manifest.py
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

REPORT = Path(__file__).resolve().parent
REPO = REPORT.parents[2]
EVIDENCE = REPORT / "evidence"

PRESERVED_REPORT = REPO / "reports/ai-bots/CODEX-PAPER-ADMISSION-DIAG-001"
PRESERVED = (
    "FINAL_REPORT.md",
    "NEXT_EXPERIMENT.md",
    "OPERATIONAL_BLOCKERS.md",
    "PAPER_ADMISSION_DIAGNOSIS.md",
    "RUNTIME_AUTHORITY_MAP.md",
    "STRATEGY_ECONOMIC_STATUS.md",
    "verify_claims.py",
)

#: The pre-fix tree this RFC measured. Every "before" below is that commit's bytes.
BASE_COMMIT = "b4c8e3e2"  # merge of main into the supervisor lane, before any fix
LANE_COMMIT = "3b758e22f0c9835646c9eba9db6634757970b126"
MAIN_COMMIT = "0e13160a8d5522961978fe3bd6b904b3a14be1c3"
MERGE_BASE = "1d2192b0aec8cfe1bf2bfcaa308c4787229b3d22"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def blob(commit: str, path: str) -> str | None:
    """The hash of ``path`` as it was committed at ``commit`` (``None`` if absent)."""

    result = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=REPO,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return hashlib.sha256(result.stdout).hexdigest()


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=False
    ).stdout.strip()


def main() -> int:
    changed = [line for line in git("diff", "--name-only", BASE_COMMIT).splitlines() if line]
    untracked = [
        line
        for line in git("ls-files", "--others", "--exclude-standard").splitlines()
        if line
    ]

    manifest = {
        "schema_version": "RFC_TAP_PAPER_ADMISSION_REPRO_MANIFEST_V1",
        "rfc": "RFC-TAP-PAPER-ADMISSION-REPRO-001",
        "generated_at_utc": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "authority": {
            "builder": "RFC-TAP-PAPER-ADMISSION-REPRO-001",
            "verifier": "reports/ai-bots/RFC-TAP-PAPER-ADMISSION-REPRO-001/verify_repro.py",
            "note": (
                "The verifier recomputes every hash and re-runs every gate as a subprocess. "
                "It reads this manifest only as a claim to be tested."
            ),
        },
        "baseline": {
            "main_commit": MAIN_COMMIT,
            "lane_commit": LANE_COMMIT,
            "merge_base": MERGE_BASE,
            "base_commit": git("rev-parse", BASE_COMMIT),
            "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
            "lane_ahead": int(git("rev-list", "--count", f"{MAIN_COMMIT}..{LANE_COMMIT}")),
            "lane_behind": int(git("rev-list", "--count", f"{LANE_COMMIT}..{MAIN_COMMIT}")),
            "environment": {
                "platform": "Windows-10-10.0.26200-SP0",
                "python": "3.11.15",
                "uv": "0.11.26",
                "pytest": "9.1.1",
                "git": "2.51.1.windows.1",
            },
        },
        "preserved": {
            name: {
                "path": (PRESERVED_REPORT / name).relative_to(REPO).as_posix(),
                "sha256": digest(PRESERVED_REPORT / name),
                "bytes": (PRESERVED_REPORT / name).stat().st_size,
                "committed_at": blob(BASE_COMMIT, (PRESERVED_REPORT / name).relative_to(REPO).as_posix()),
            }
            for name in PRESERVED
        },
        "code_changes": [
            {
                "path": path,
                "sha256_before": blob(BASE_COMMIT, path),
                "sha256_after": digest(REPO / path),
            }
            for path in changed
        ],
        #: The verifier rewrites its own outputs on every run; hashing them would make
        #: the manifest disagree with the tree precisely because the check ran.
        "evidence": {
            path.relative_to(REPO).as_posix(): {
                "sha256": digest(path),
                "bytes": path.stat().st_size,
            }
            for path in sorted(EVIDENCE.rglob("*"))
            if path.is_file()
            and path.relative_to(EVIDENCE).parts[0] != "verifier"
            and path.name != "VERIFICATION.json"
        },
        "added_paths": untracked,
    }
    out = REPORT / "evidence_manifest.json"
    out.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "manifest": str(out.relative_to(REPO)),
                "preserved": len(manifest["preserved"]),
                "code_changes": len(manifest["code_changes"]),
                "evidence": len(manifest["evidence"]),
                "added_paths": len(manifest["added_paths"]),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
