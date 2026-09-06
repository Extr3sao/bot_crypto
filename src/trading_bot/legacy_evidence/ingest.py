"""Deterministic, allowlisted ingestion of the FRAN V5.7 legacy package.

The ZIP at ``C:\\Users\\GVLLFR0035\\Downloads\\bot freebuff\\his.zip`` is the
source of truth. It is never modified; allowed members are read in memory and
flat-extracted into a working directory so Windows MAX_PATH cannot break the
deep legacy layout.
"""

from __future__ import annotations

import hashlib
import json
import os
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SOURCE_PATH = Path(r"C:\Users\GVLLFR0035\Downloads\bot freebuff\his.zip")
SOURCE_SYSTEM = "FRAN_V5_LEGACY"
SOURCE_VERSION = "V5.7-R26-B / V5.7-R31.9 / V5.8-BCD"
LEGACY_PERIOD_START = datetime(2026, 5, 1, tzinfo=UTC)
LEGACY_PERIOD_END_EXCLUSIVE = datetime(2026, 8, 18, tzinfo=UTC)

#: Strict ingestion allowlist. Anything else inside the ZIP is never read.
ALLOWLIST_FILES: frozenset[str] = frozenset(
    {
        "RESULTADOS_V57_R26_B.json",
        "TRADES_V57_R26_B.csv",
        "OPPORTUNITIES_V57_R26_B.csv",
        "BLOCKED_V57_R26_B.csv",
        "BY_ASSET_V57_R26_B.csv",
        "BY_FAMILY_V57_R26_B.csv",
        "DAILY_COVERAGE_V57_R26_B.csv",
        "FBS_BY_EXIT_REASON_V57_R26_B.csv",
        "RESULTADOS_V57_R31_9_DIAGNOSTIC.json",
        "TP_VOLUME_REGIME_CLASSIFICATION_V57_R31_9.csv",
        "CAMPAIGN_FINAL_BCD.json",
        "research_registry.json",
        # Historical manifests: metadata only (never code, never runtime).
        "E_VOLATILITY_EXPANSION.json",
        "F_LIQUIDITY_SWEEP_REVERSION.json",
        "G_CROSS_SECTIONAL_MOMENTUM.json",
    }
)

#: Manifests are historical metadata only.
METADATA_ONLY_FILES: frozenset[str] = frozenset(
    {
        "E_VOLATILITY_EXPANSION.json",
        "F_LIQUIDITY_SWEEP_REVERSION.json",
        "G_CROSS_SECTIONAL_MOMENTUM.json",
    }
)

# Members that must never be touched even if renamed into the allowlist.
_FORBIDDEN_NAME_PARTS = (
    "freebuff2api",
    ".env",
    ".git",
    ".venv",
    "__pycache__",
    ".bat",
    ".ps1",
    ".pyc",
    "research_daemon",
    "token",
    "credential",
    "secret",
)


class LegacyIngestError(RuntimeError):
    """Raised when the legacy package fails allowlist/provenance checks."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_zip(zip_path: Path) -> str:
    """SHA-256 of the original ZIP (read-only; the file is never touched)."""
    return sha256_file(zip_path)


@dataclass(frozen=True, slots=True)
class IngestedFile:
    name: str
    zip_member: str
    sha256: str
    size_bytes: int
    is_metadata_only: bool


class LegacyEvidenceIngester:
    """Reads only allowlisted members from the legacy ZIP, deterministically.

    Extraction layout is flat (``<workdir>/<member name>``) so the deep
    legacy directories cannot exceed Windows MAX_PATH. If a candidate member
    name would shadow an already-extracted file, ingestion fails closed.
    """

    def __init__(self, zip_path: Path | str = SOURCE_PATH) -> None:
        self._zip_path = Path(zip_path)
        if not self._zip_path.is_file():
            raise LegacyIngestError(f"legacy source not found: {self._zip_path}")

    @property
    def zip_path(self) -> Path:
        return self._zip_path

    def source_sha256(self) -> str:
        return sha256_zip(self._zip_path)

    def _select_members(
        self, archive: zipfile.ZipFile, *, require_all: bool = True
    ) -> dict[str, str]:
        """Map allowlist name -> exact ZIP member, rejecting ambiguity."""
        selected: dict[str, str] = {}
        for info in archive.infolist():
            if info.is_dir():
                continue
            base = os.path.basename(info.filename.replace("\\", "/"))
            if base not in ALLOWLIST_FILES:
                continue
            # Forbidden-part check applies to the member's own name, not its
            # folder path: legit allowlist files live under legacy package
            # directories whose names contain e.g. ``research_daemon``, while
            # the excluded artifacts (daemon executable, .env, tokens, BAT/PS1)
            # are excluded by basename.
            lowered_base = base.lower()
            if any(part in lowered_base for part in _FORBIDDEN_NAME_PARTS):
                raise LegacyIngestError(f"forbidden member matched allowlist: {info.filename}")
            if base in selected:
                raise LegacyIngestError(f"ambiguous allowlist member: {base}")
            selected[base] = info.filename
        missing = ALLOWLIST_FILES - set(selected)
        if missing and require_all:
            raise LegacyIngestError(f"allowlist members missing from ZIP: {sorted(missing)}")
        return selected

    def ingest(
        self, workdir: Path | str, *, require_all: bool = True
    ) -> dict[str, Any]:
        """Extract allowlisted members flat and return deterministic provenance.

        Idempotent: re-running over the same workdir produces byte-identical
        files and the same provenance payload (G14/G15).

        ``require_all=True`` (production default) fails closed when any
        allowlist member is missing from the ZIP. The unit-test fixture uses
        ``require_all=False`` because it bundles only a subset.
        """
        workdir = Path(workdir)
        workdir.mkdir(parents=True, exist_ok=True)
        files: list[IngestedFile] = []
        with zipfile.ZipFile(self._zip_path) as archive:
            selected = self._select_members(archive, require_all=require_all)
            for name in sorted(selected):
                member = selected[name]
                data = archive.read(member)
                target = workdir / name
                if target.exists() and target.read_bytes() != data:
                    raise LegacyIngestError(f"extraction conflict for {name}")
                if not target.exists():
                    target.write_bytes(data)
                files.append(
                    IngestedFile(
                        name=name,
                        zip_member=member,
                        sha256=hashlib.sha256(data).hexdigest(),
                        size_bytes=len(data),
                        is_metadata_only=name in METADATA_ONLY_FILES,
                    )
                )
        return {
            "source_path": str(self._zip_path),
            "source_zip_sha256": self.source_sha256(),
            "source_system": SOURCE_SYSTEM,
            "source_version": SOURCE_VERSION,
            "files": [
                {
                    "name": f.name,
                    "zip_member": f.zip_member,
                    "sha256": f.sha256,
                    "size_bytes": f.size_bytes,
                    "metadata_only": f.is_metadata_only,
                }
                for f in files
            ],
        }

    def load_json(self, workdir: Path | str, name: str) -> dict[str, Any]:
        if name not in ALLOWLIST_FILES:
            raise LegacyIngestError(f"file not in allowlist: {name}")
        path = Path(workdir) / name
        with open(path, encoding="utf-8") as handle:
            data: dict[str, Any] = json.load(handle)
        return data

    def load_csv_rows(self, workdir: Path | str, name: str) -> list[dict[str, str]]:
        if name not in ALLOWLIST_FILES:
            raise LegacyIngestError(f"file not in allowlist: {name}")
        import csv

        path = Path(workdir) / name
        with open(path, encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
