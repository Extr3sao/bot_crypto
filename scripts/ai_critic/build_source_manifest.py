"""build_source_manifest — pin the upstream source and promote audit artifacts.

Produces ``SOURCE_MANIFEST.json`` (commit, license, per-file hashes and git blob ids) and
copies the trace/REA files that the RFC names at the report root from the detailed
subdirectories, so a reader does not have to guess which copy is authoritative.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

SOURCE_FILES = (
    "LICENSE",
    "tradingagents/agents/researchers/bull_researcher.py",
    "tradingagents/agents/researchers/bear_researcher.py",
    "tradingagents/agents/managers/research_manager.py",
    "tradingagents/agents/context.py",
    "tradingagents/agents/schemas.py",
    "tradingagents/agents/structured.py",
    "tradingagents/agents/state.py",
    "tradingagents/graph/conditional_logic.py",
    "tradingagents/reporting.py",
    "tradingagents/report_html.py",
    "tradingagents/agents/rating.py",
    "tests/test_debate_opening.py",
    "tests/test_structured_agents.py",
    "tests/test_report_html.py",
)
PIN = "e8f5503e9b86d5c2710b0c76b1f686703968c9df"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=False
    ).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream-root", required=True)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    upstream = Path(args.upstream_root).resolve()
    repo = Path(args.repo_root).resolve()
    out = Path(args.out).resolve()

    head = git(upstream, "rev-parse", "HEAD")
    files = []
    for rel in SOURCE_FILES:
        path = upstream / rel
        files.append(
            {
                "path": rel,
                "sha256": sha256(path) if path.exists() else None,
                "git_blob": git(upstream, "rev-parse", f"HEAD:{rel}") or None,
                "bytes": path.stat().st_size if path.exists() else None,
            }
        )

    manifest = {
        "schema_version": "TAP004_SOURCE_MANIFEST_V1",
        "source_id": "T-TA-CRITIC",
        "project": "TauricResearch/TradingAgents",
        "url": "https://github.com/TauricResearch/TradingAgents.git",
        "commit": head,
        "commit_expected": PIN,
        "commit_matches_pin": head == PIN,
        "license": "Apache-2.0",
        "license_sha256": sha256(upstream / "LICENSE"),
        "acquisition": {
            "command": (
                "git clone --filter=blob:none --no-checkout "
                "https://github.com/TauricResearch/TradingAgents.git ta_lab && "
                f"git -C ta_lab checkout --detach {PIN}"
            ),
            "checkout_bytes": sum(p.stat().st_size for p in upstream.rglob("*") if p.is_file()),
            "no_framework_installed_in_runtime": True,
        },
        "files": files,
        "runtime_entries": {
            "tracker_head": git(repo, "rev-parse", "HEAD"),
            "branch": git(repo, "rev-parse", "--abbrev-ref", "HEAD"),
            "worktree": str(repo),
        },
        "limits": [
            "the upstream checkout is a separate lab, not a runtime dependency",
            "hashes are of the detached checkout, not of a remote artifact cache",
        ],
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    (out / "SOURCE_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    promotions = {
        "upstream/UPSTREAM_PYTHON_TRACE.jsonl": "UPSTREAM_PYTHON_TRACE.jsonl",
        "rea/REA_OPERATION_LOG.jsonl": "REA_OPERATION_LOG.jsonl",
        "rea/REA_TARGET_EVIDENCE.json": "REA_TARGET_EVIDENCE.json",
    }
    promoted = {}
    for source_rel, target_name in promotions.items():
        source = out / source_rel
        target = out / target_name
        shutil.copyfile(source, target)
        promoted[target_name] = {
            "source": source_rel,
            "sha256": sha256(target),
            "bytes": target.stat().st_size,
            "identical_to_source": sha256(source) == sha256(target),
        }
    manifest["promoted_artifacts"] = promoted
    (out / "SOURCE_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"commit": head, "files": len(files), "promoted": list(promoted)}, indent=2))
    return 0 if manifest["commit_matches_pin"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
