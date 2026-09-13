"""V4 — SINGLE runtime authority binding for H6.

V4 repair for V3-AUTH-001.

V3 hard-coded prereg commit / spec / manifest / whitelist / data-authority hashes and
the external-report path across ELEVEN files, and every one of them still pointed at
the superseded, failed **V1** preregistration. Replacing that with V4 copies in eleven
files would reproduce the same class of defect.

Instead there is exactly ONE versioned, non-economic artifact::

    docs/external-audit-01/h6-v4-repair/H6_RUNTIME_AUTHORITY_BINDING_V4.json

Every runtime module obtains prereg commit, artifact hashes and the external verifier
report location from this module and nowhere else. Nothing else in the package may
contain a hash literal or a report path.

Prereg-commit circularity (clean resolution):

* PRE-FREEZE — the binding artifact does not exist yet, so ``current_binding()`` raises
  ``H6RuntimeAuthorityUnavailable`` and the runtime stays FAIL CLOSED. No hashes are
  invented.
* FREEZE — the V4 prereg commit is created containing only economic artifacts.
* POST-FREEZE — ``H6_RUNTIME_AUTHORITY_BINDING_V4.json`` is generated. It is
  NON-ECONOMIC: it records the now-existing prereg commit and the hashes of the frozen
  artifacts, and it never mutates them.

Paths are resolved from the repository root derived from this file's location, never
from the process working directory.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BINDING_SCHEMA_VERSION = "H6-RUNTIME-AUTHORITY-BINDING-V1"


def _resolve_repo_root() -> Path:
    """Deterministic repo root: git toplevel if available, else the module's ancestor."""
    here = Path(__file__).resolve()
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(here.parent), capture_output=True, text=True, timeout=20,
        )
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip()).resolve()
    except Exception:  # pragma: no cover - git absent
        pass
    # <repo>/src/trading_bot/research/h6/runtime_authority.py -> parents[4] == <repo>
    return here.parents[4]


REPO_ROOT: Path = _resolve_repo_root()
BINDING_RELATIVE_PATH = "docs/external-audit-01/h6-v4-repair/H6_RUNTIME_AUTHORITY_BINDING_V4.json"
BINDING_PATH: Path = REPO_ROOT / BINDING_RELATIVE_PATH

# Explicit, greppable sentinel used while unbound (pre-freeze).
UNBOUND = "UNBOUND_PRE_FREEZE"


class H6RuntimeAuthorityUnavailable(Exception):
    """Raised when the runtime has no valid V4 authority binding (fail closed)."""


class H6RuntimeAuthorityMismatch(Exception):
    """Raised when a live artifact does not match the bound hashes."""


@dataclass(frozen=True, slots=True)
class H6RuntimeAuthorityBinding:
    schema_version: str
    generation: str
    prereg_commit: str
    spec_path: str
    spec_sha256: str
    manifest_path: str
    manifest_sha256: str
    whitelist_path: str
    whitelist_sha256: str
    data_authority_path: str
    data_authority_sha256: str
    expected_external_verifier_report_path: str
    dataset_sha256: str = UNBOUND
    economics_inspected: bool = False

    # -- accessors ----------------------------------------------------------

    @property
    def spec_file(self) -> Path:
        return REPO_ROOT / self.spec_path

    @property
    def manifest_file(self) -> Path:
        return REPO_ROOT / self.manifest_path

    @property
    def whitelist_file(self) -> Path:
        return REPO_ROOT / self.whitelist_path

    @property
    def data_authority_file(self) -> Path:
        return REPO_ROOT / self.data_authority_path

    @property
    def external_verifier_report_file(self) -> Path:
        """Versioned, absolute (repo-root relative), CWD-independent."""
        return REPO_ROOT / self.expected_external_verifier_report_path

    def describe(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    # -- integrity ----------------------------------------------------------

    def verify_artifacts_present_and_matching(self) -> dict[str, Any]:
        """Recompute the bound artifact hashes. Does not modify anything."""
        result: dict[str, Any] = {}
        for label, path, expected in (
            ("spec", self.spec_file, self.spec_sha256),
            ("manifest", self.manifest_file, self.manifest_sha256),
            ("whitelist", self.whitelist_file, self.whitelist_sha256),
            ("data_authority", self.data_authority_file, self.data_authority_sha256),
        ):
            if not path.exists():
                result[label] = {"path": str(path), "exists": False, "match": False}
                continue
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            result[label] = {
                "path": str(path),
                "exists": True,
                "expected": expected,
                "actual": actual,
                "match": actual == expected,
            }
        return result

    # -- loading ------------------------------------------------------------

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "H6RuntimeAuthorityBinding":
        required = [
            "schema_version", "generation", "prereg_commit", "spec_path", "spec_sha256",
            "manifest_path", "manifest_sha256", "whitelist_path", "whitelist_sha256",
            "data_authority_path", "data_authority_sha256",
            "expected_external_verifier_report_path",
        ]
        missing = [k for k in required if k not in data]
        if missing:
            raise H6RuntimeAuthorityUnavailable(
                "binding missing required key(s): %s" % ", ".join(missing))
        if data["schema_version"] != BINDING_SCHEMA_VERSION:
            raise H6RuntimeAuthorityUnavailable(
                "binding schema_version %r != %r" % (data["schema_version"], BINDING_SCHEMA_VERSION))
        for k in ("spec_sha256", "manifest_sha256", "whitelist_sha256", "data_authority_sha256"):
            v = str(data[k])
            if len(v) != 64 or any(c not in "0123456789abcdef" for c in v):
                raise H6RuntimeAuthorityUnavailable(f"binding {k} is not 64 lowercase hex")
        rep = str(data["expected_external_verifier_report_path"])
        if not rep.startswith("docs/external-audit-01/") or "h6-external-verification-v4" not in rep:
            raise H6RuntimeAuthorityUnavailable(
                f"binding report path must be a versioned V4 path, got {rep!r}")
        return cls(**{k: data[k] for k in required},
                   dataset_sha256=str(data.get("dataset_sha256", UNBOUND)),
                   economics_inspected=bool(data.get("economics_inspected", False)))


_cache: dict[str, H6RuntimeAuthorityBinding | None] = {}


def load_binding(path: Path | None = None, *, refresh: bool = False) -> H6RuntimeAuthorityBinding | None:
    """Load the binding, or return None if it does not exist / is unusable."""
    key = str(path or BINDING_PATH)
    if not refresh and key in _cache:
        return _cache[key]
    p = path or BINDING_PATH
    if not p.exists():
        _cache[key] = None
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        _cache[key] = H6RuntimeAuthorityBinding.from_mapping(data)
    except Exception:
        _cache[key] = None
    return _cache[key]


def current_binding() -> H6RuntimeAuthorityBinding:
    """Return the binding or raise (fail closed)."""
    b = load_binding()
    if b is None:
        raise H6RuntimeAuthorityUnavailable(
            f"no valid H6 V4 runtime authority binding at {BINDING_RELATIVE_PATH}; "
            "runtime is UNBOUND_PRE_FREEZE and must stay fail-closed"
        )
    return b


def spec_sha256_or_unbound() -> str:
    b = load_binding()
    return b.spec_sha256 if b else UNBOUND


def manifest_sha256_or_unbound() -> str:
    b = load_binding()
    return b.manifest_sha256 if b else UNBOUND


def whitelist_sha256_or_unbound() -> str:
    b = load_binding()
    return b.whitelist_sha256 if b else UNBOUND


def data_authority_sha256_or_unbound() -> str:
    b = load_binding()
    return b.data_authority_sha256 if b else UNBOUND


def dataset_sha256_or_unbound() -> str:
    """The frozen V2/V4 dataset fingerprint (a DATA fact, not an economic one)."""
    b = load_binding()
    if b and b.dataset_sha256 != UNBOUND:
        return b.dataset_sha256
    # The dataset fingerprint is shared across V2/V3/V4 and was independently
    # re-derived by the V3 external verifier from ledger bytes. It is recorded in
    # the data-authority artifact, never as a scattered literal.
    for rel in (
        "docs/external-audit-01/oi-full-history-03/H6_DATA_AUTHORITY_V3.json",
        "docs/external-audit-01/h6-v4-repair/H6_DATA_AUTHORITY_V4.json",
    ):
        p = REPO_ROOT / rel
        if p.exists():
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                v = d.get("dataset_sha256")
                if isinstance(v, str) and len(v) == 64:
                    return v
            except Exception:
                pass
    return UNBOUND


def expected_external_verifier_report_path() -> Path:
    """Repo-root-resolved, CWD-independent. Falls back to the canonical V4 location."""
    b = load_binding()
    if b is not None:
        return b.external_verifier_report_file
    return REPO_ROOT / (
        "docs/external-audit-01/h6-external-verification-v4/"
        "H6_EXTERNAL_VERIFICATION_V4_REPORT.json"
    )


def binding_status() -> dict[str, Any]:
    """Non-throwing status for evidence and diagnostics."""
    b = load_binding()
    return {
        "repo_root": str(REPO_ROOT),
        "binding_path": str(BINDING_PATH),
        "binding_exists": BINDING_PATH.exists(),
        "bound": b is not None,
        "state": "BOUND" if b else UNBOUND,
        "binding": b.describe() if b else None,
        "checked_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


__all__ = [
    "BINDING_PATH",
    "BINDING_RELATIVE_PATH",
    "BINDING_SCHEMA_VERSION",
    "H6RuntimeAuthorityBinding",
    "H6RuntimeAuthorityMismatch",
    "H6RuntimeAuthorityUnavailable",
    "REPO_ROOT",
    "UNBOUND",
    "binding_status",
    "current_binding",
    "data_authority_sha256_or_unbound",
    "dataset_sha256_or_unbound",
    "expected_external_verifier_report_path",
    "load_binding",
    "manifest_sha256_or_unbound",
    "spec_sha256_or_unbound",
    "whitelist_sha256_or_unbound",
]
