"""WP-EDGE-09A — the estate audit: what exists, what is closed, what is spent.

Three questions, answered with measurements instead of memory:

* **Authoritative inputs.** Which files govern cost, risk and the data contract,
  with their digests, so a later reading can prove they did not move.
* **Data estate.** What corpora this repository holds, how large they are, how
  many files and rows each one carries.
* **Closed work.** Which phases already published a verdict, read from the
  artifact that published it rather than restated from memory.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from .registration import (
    COST_MODEL_V3,
    COST_MODEL_V4,
    FORWARD_CONTRACT,
    REPO_ROOT,
    RFC,
    RISK_CONFIG,
    RUNTIME_CONFIG,
    SCHEMA_VERSION,
    SOURCE_REGISTRY,
    UNIVERSE,
)

#: Directories that make up the estate. ``kind`` says what the directory is for;
#: it is not a quality judgement.
ESTATE_DIRS: tuple[tuple[str, str], ...] = (
    ("data", "market and run data"),
    ("reports/microstructure-forward", "forward microstructure capture"),
    ("reports/microstructure-forward-continuous", "forward microstructure capture"),
    ("reports/microstructure-forward-lab", "forward microstructure capture"),
    ("reports/microstructure-v1", "microstructure phase artifacts"),
    ("reports/microstructure-v2", "microstructure phase artifacts"),
    ("reports/edge-recovery", "edge-recovery work packages"),
    ("reports/execution-economics", "execution cost phase"),
    ("reports/carry", "carry/basis research"),
    ("reports/economic001", "economic checkpoint"),
)

#: Prior phases whose verdict is published inside an artifact. The audit reads
#: the sentence from that artifact; it never restates it from memory.
CLOSED_PHASES: tuple[tuple[str, str, str], ...] = (
    (
        "MICROSTRUCTURE-EDGE-V1/V2",
        "docs/MICROSTRUCTURE_FINAL_REPORT.md",
        "FINAL STATUS:",
    ),
    (
        "MICROSTRUCTURE-V2-ADMISSION",
        "docs/MICROSTRUCTURE_ADMISSION_V2.md",
        "FINAL STATUS:",
    ),
    (
        "MICROSTRUCTURE-FORWARD-COLLECTION-V1",
        "docs/MICROSTRUCTURE_FORWARD_COLLECTION_FINAL.md",
        "FINAL STATUS:",
    ),
    (
        "EXECUTION-COST-MODEL-V4",
        "docs/COST_MODEL_V3.md",
        "VERDICT",
    ),
)

#: The per-WP layout of this package, so a reader can see the shape before the
#: artifacts exist.
WORK_PACKAGES: tuple[tuple[str, str], ...] = (
    ("WP-EDGE-09A", "audit: repository, runtime and the data actually held"),
    ("WP-EDGE-09B", "sources: provider viability, coverage, provenance, point-in-time"),
    ("WP-EDGE-09C", "hypotheses: falsifiable economic statements, registered first"),
    ("WP-EDGE-09D", "gates: cost, liquidity, capacity and frequency"),
    ("WP-EDGE-09E", "experiments: run only where the gates allow, negatives included"),
    ("WP-EDGE-09F", "verification: independent, adversarial, and the closure"),
)


def sha256_file(path: Path) -> str:
    if not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def git(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    return (proc.stdout or "").strip()


def authoritative_inputs() -> dict[str, Any]:
    """The files this package reads and must never write, with their digests."""
    files = {
        "config/risk.yaml": RISK_CONFIG,
        "config/runtime.yaml": RUNTIME_CONFIG,
        "docs/COST_MODEL_V3.json": COST_MODEL_V3,
        "docs/EXECUTION_COST_MODEL_V4.json": COST_MODEL_V4,
        "docs/FORWARD_DATA_CONTRACT.json": FORWARD_CONTRACT,
        "docs/source_registry.md": SOURCE_REGISTRY,
    }
    rows = []
    for label, path in files.items():
        rows.append(
            {
                "path": label,
                "exists": path.is_file(),
                "bytes": path.stat().st_size if path.is_file() else 0,
                "sha256": sha256_file(path),
                "last_commit": git("log", "-1", "--format=%h %s", "--", label) or None,
                "worktree_modified": bool(git("status", "--porcelain", "--", label)),
            }
        )
    return {
        "files": rows,
        "risk_limits_read_not_written": True,
        "runtime_mode": _scalar(RUNTIME_CONFIG, "mode:"),
        "runtime_live_trading_enabled": _scalar(RUNTIME_CONFIG, "live_trading_enabled:"),
        "risk_live_trading_enabled": _scalar(RISK_CONFIG, "live_trading_enabled:"),
    }


def runtime_mode() -> str | None:
    return _scalar(RUNTIME_CONFIG, "mode:")


def _scalar(path: Path, key: str) -> str | None:
    """The value of the first ``key: value`` line, as text, or ``None``."""
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if stripped.startswith(key):
            return stripped.split(":", 1)[1].strip().strip('"')
    return None


def _walk_size(path: Path) -> tuple[int, int]:
    files = 0
    total = 0
    for root, _dirs, names in os.walk(path):
        for name in names:
            try:
                total += os.path.getsize(os.path.join(root, name))
                files += 1
            except OSError:  # pragma: no cover - a file that vanished mid-walk
                continue
    return files, total


def data_estate() -> dict[str, Any]:
    """One row per directory that matters, by size and file count."""
    rows = []
    for relative, kind in ESTATE_DIRS:
        path = REPO_ROOT / relative
        if not path.exists():
            rows.append({"path": relative, "kind": kind, "present": False})
            continue
        files, total = _walk_size(path)
        rows.append(
            {
                "path": relative,
                "kind": kind,
                "present": True,
                "files": files,
                "bytes": total,
                "mib": round(total / 1024 / 1024, 1),
            }
        )
    return {"directories": rows}


def capture_runs() -> list[dict[str, Any]]:
    """Every forward microstructure capture with its manifest, measured."""
    runs: list[dict[str, Any]] = []
    roots = sorted(
        {
            parent
            for parent in REPO_ROOT.glob("reports/microstructure-forward*")
            if (parent / "manifest").is_dir()
        }
    )
    for root in roots:
        for manifest in sorted((root / "manifest").glob("*.json")):
            payload = _load(manifest)
            segments = (
                sum(1 for _ in (root / "segments").rglob("*.jsonl.gz"))
                if (root / "segments").is_dir()
                else 0
            )
            runs.append(
                {
                    "root": str(root.relative_to(REPO_ROOT)).replace("\\", "/"),
                    "run_id": payload.get("run_id") or manifest.stem,
                    "manifest": str(manifest.relative_to(REPO_ROOT)).replace("\\", "/"),
                    "started_at": payload.get("started_at"),
                    "ended_at": payload.get("ended_at"),
                    "duration_seconds": payload.get("duration_seconds"),
                    "markets": payload.get("markets") or payload.get("market"),
                    "continuity": payload.get("continuity"),
                    "status": payload.get("status"),
                    "stopped_on_disk_budget": payload.get("stopped_on_disk_budget"),
                    "bytes_written": payload.get("bytes_written"),
                    "segments_on_disk": segments,
                }
            )
    return runs


def _load(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def closed_phases() -> list[dict[str, Any]]:
    """The verdict sentence of every prior phase, read from its own artifact."""
    rows = []
    for phase, relative, marker in CLOSED_PHASES:
        path = REPO_ROOT / relative
        status = None
        if path.is_file():
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                if marker in line and not line.strip().startswith("#"):
                    status = line.strip()
                    break
        rows.append(
            {
                "phase": phase,
                "artifact": relative,
                "present": path.is_file(),
                "status_line": status,
                "sha256": sha256_file(path)[:16] or None,
            }
        )
    return rows


def build() -> dict[str, Any]:
    forward_root = REPO_ROOT / "reports" / "microstructure-forward-continuous"
    return {
        "schema_version": SCHEMA_VERSION,
        "work_package": "WP-EDGE-09A",
        "title": "estate audit: repository, runtime, data and closed work",
        "head": git("rev-parse", "HEAD"),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "universe": list(UNIVERSE),
        "rfc_present": RFC.is_file(),
        "work_packages": [{"id": wp, "scope": scope} for wp, scope in WORK_PACKAGES],
        "authoritative": authoritative_inputs(),
        "estate": data_estate(),
        "captures": capture_runs(),
        "capture_root_measured": str(forward_root.relative_to(REPO_ROOT)).replace("\\", "/"),
        "closed_phases": closed_phases(),
        "reusable_assets": [
            {
                "asset": "src/trading_bot/research/microstructure/",
                "why": "cost models V2/V3/V4, execution model, PIT types, integrity checks",
            },
            {
                "asset": "src/trading_bot/research/forward/",
                "why": "the capture read side (storage, contract, aggregation) this package reads",
            },
            {
                "asset": "docs/source_registry.md",
                "why": "SRC-01..SRC-18 with their measured claims; extended, never rewritten",
            },
        ],
    }


__all__ = [
    "authoritative_inputs",
    "build",
    "capture_runs",
    "closed_phases",
    "data_estate",
    "git",
    "runtime_mode",
    "sha256_file",
]
