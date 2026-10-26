"""WP-EDGE-12 — declared paths, anchored on the repository root.

A defect WP-EDGE-04R found and closed was a probe that resolved its declared paths
against the caller's working directory: the same command gave one verdict when it was
typed from the repository root and another when it was not. Every path in this campaign
is therefore resolved here, against the checkout the module was loaded from, and the
reproduction commands this package publishes are functions of that root and nothing
else.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = [
    "DEFAULT_REPORTS",
    "DEFAULT_STATE_ROOT",
    "DEFAULT_STORE_ROOT",
    "REPO_ROOT",
    "iso",
    "now_utc",
    "repo_path",
    "sha256_file",
    "write_json",
]

REPO_ROOT = Path(__file__).resolve().parents[4]

DEFAULT_REPORTS = REPO_ROOT / "reports" / "edge-recovery" / "WP-EDGE-12"
DEFAULT_STATE_ROOT = REPO_ROOT / "data" / "forward" / "edge04"
DEFAULT_STORE_ROOT = REPO_ROOT / "data" / "forward" / "edge03"


def repo_path(value: str | Path) -> Path:
    """Resolve a declared path against the repository root, never against the cwd."""
    candidate = Path(value)
    return candidate if candidate.is_absolute() else REPO_ROOT / candidate


def now_utc() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso(instant_ms: int) -> str:
    return datetime.fromtimestamp(instant_ms / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    return path


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    loaded = json.loads(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()
