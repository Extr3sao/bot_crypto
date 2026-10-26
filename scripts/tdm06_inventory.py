"""WP-TDM-06 §A — inventory the external (recovery005) modifications.

Reads `git diff` for the seven modified paths, preserves a byte-exact copy of
each current file under ``reports/trading-decision-monitor/WP-TDM-06/preserved/``
and writes a machine-readable inventory. It never writes to the working tree's
source files and never stages/commits anything.

    PYTHONPATH=src python scripts/tdm06_inventory.py
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "reports" / "trading-decision-monitor" / "WP-TDM-06"
PRESERVED = OUT_DIR / "preserved"

TRACKED = [
    "data/recovery/COST_BARRIER_VERIFICATION.json",
    "data/st6/RFC047_RUNTIME_VERIFICATION.json",
    "src/trading_bot/config/settings.py",
    "src/trading_bot/market_data/exchange_connector.py",
    "src/trading_bot/market_data/ohlcv_fetcher.py",
    "src/trading_bot/research/__init__.py",
    "src/trading_bot/research/admission.py",
]

# New (untracked) files that belong to the same recovery campaign.
UNTRACKED_CAMPAIGN = [
    "src/trading_bot/config/types.py",
    "data/recovery/COST_BARRIER_VERIFICATION_MUTANT.json",
    ".ci/recovery005_mutant_evidence.json",
]

EFFECTS = {
    "src/trading_bot/config/settings.py": (
        "load_settings() no longer accepts config_dir and ignores every YAML; "
        "the canonical PAPER entrypoint aborts with TypeError"
    ),
    "src/trading_bot/config/types.py": (
        "new flat Settings dataclass carrying ROUNDTRIP_COST_BPS = 891 bps; "
        "no in-tree consumer outside the mutation itself"
    ),
    "src/trading_bot/research/admission.py": (
        "AdmissionController is a stub that always returns NO_ADMISSION / "
        "LOCAL_RECOVERY_UNSUPPORTED and requires no risk engine"
    ),
    "src/trading_bot/market_data/exchange_connector.py": (
        "exchange connector reduced to a shim over the flat Settings; the ccxt "
        "order/balance surface is gone"
    ),
    "src/trading_bot/market_data/ohlcv_fetcher.py": (
        "OHLCV fetcher reduced to a thin placeholder"
    ),
    "src/trading_bot/research/__init__.py": (
        "research package exports trimmed to the recovery shim"
    ),
    "data/recovery/COST_BARRIER_VERIFICATION.json": (
        "verification output overwritten with mutant-campaign numbers"
    ),
    "data/st6/RFC047_RUNTIME_VERIFICATION.json": (
        "verification output overwritten with mutant-campaign numbers"
    ),
}


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout


def blob_hash(path: str) -> str:
    return git("hash-object", path).strip()


def head_blob(path: str) -> str | None:
    try:
        return git("rev-parse", f"HEAD:{path}").strip()
    except subprocess.CalledProcessError:
        return None


def line_count(text: str) -> int:
    return len(text.splitlines())


def removed_symbols(path: str) -> list[str]:
    diff = git("diff", "HEAD", "--", path)
    out: list[str] = []
    for line in diff.splitlines():
        if line.startswith("-") and not line.startswith("---"):
            body = line[1:].strip()
            for prefix in ("def ", "async def ", "class "):
                if body.startswith(prefix):
                    out.append(body.split("(")[0].rstrip(":").strip())
    return out


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PRESERVED.mkdir(parents=True, exist_ok=True)
    head = git("rev-parse", "HEAD").strip()
    branch = git("rev-parse", "--abbrev-ref", "HEAD").strip()
    status = git("status", "--porcelain").splitlines()

    rows: list[dict[str, Any]] = []
    for path in TRACKED + UNTRACKED_CAMPAIGN:
        src = REPO_ROOT / path
        exists = src.exists()
        dest = PRESERVED / path
        if exists:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
        numstat = git("diff", "--numstat", "HEAD", "--", path).strip().split("\t")
        added = int(numstat[0]) if len(numstat) == 3 and numstat[0].isdigit() else None
        removed = int(numstat[1]) if len(numstat) == 3 and numstat[1].isdigit() else None
        raw = src.read_bytes() if exists else b""
        text = raw.decode("utf-8", errors="replace")
        current_sha256 = hashlib.sha256(raw).hexdigest() if exists else None
        rows.append(
            {
                "path": path,
                "tracked_in_head": head_blob(path) is not None,
                "present": exists,
                "head_blob_sha1": head_blob(path),
                "current_blob_sha1": blob_hash(path) if exists else None,
                "current_sha256": current_sha256,
                "current_lines": line_count(text),
                "lines_added_vs_head": added,
                "lines_removed_vs_head": removed,
                "removed_definitions": removed_symbols(path) if head_blob(path) else [],
                "measured_effect": EFFECTS.get(path, "campaign artifact"),
                "preserved_copy": str(dest.relative_to(REPO_ROOT)).replace("\\", "/")
                if exists
                else None,
                "preserved_sha256_matches": (
                    hashlib.sha256(dest.read_bytes()).hexdigest() == current_sha256
                )
                if exists
                else None,
            }
        )

    payload = {
        "schema": "wp-tdm-06-external-changes-v1",
        "head_commit": head,
        "branch": branch,
        "worktree_state": "DIRTY_PRESERVED" if status else "CLEAN",
        "policy": (
            "No file in this inventory was reverted, staged, stashed or deleted. "
            "The runtime was recovered in an isolated git worktree at the same commit."
        ),
        "git_status": status,
        "files": rows,
    }
    (OUT_DIR / "EXTERNAL_CHANGES_PRESERVED.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"head": head, "files": len(rows), "dirty": len(status)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
