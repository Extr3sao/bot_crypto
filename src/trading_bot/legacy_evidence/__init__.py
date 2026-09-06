"""LEGACY-HIST-001 — Historical Evidence Layer (read-only / shadow).

Integrates the FRAN V5.7 legacy research package (``his.zip``) as historical
memory for Asset/Strategy Experts and Critics WITHOUT affecting decisions,
scores, paper execution or live trading.

Hard invariants (fail-closed):
- The legacy period 2026-05-01..2026-08-18 is ``CONSUMED_DEVELOPMENT``:
  evidence may inform context and critique, never training, candidate
  promotion, confirmation or execution.
- Strict allowlist ingestion; secrets/``freebuff2api``/executables are never
  read.
- Deterministic SHA-256 provenance for the ZIP and every ingested file.
- Shadow-only at the OpportunityBoard/MetaRanker boundary: provenance can be
  attached alongside a ranking, but no score/routing/acceptance/execution
  path may read it.
"""

from __future__ import annotations

from .builder import LegacyEvidenceBuilder
from .critique import LegacyCritiqueHints, LegacyHypothesisIndex
from .ingest import (
    ALLOWLIST_FILES,
    LEGACY_PERIOD_END_EXCLUSIVE,
    LEGACY_PERIOD_START,
    SOURCE_PATH,
    SOURCE_SYSTEM,
    LegacyEvidenceIngester,
    LegacyIngestError,
    sha256_file,
    sha256_zip,
)
from .shadow import LegacyShadowLink, ShadowEvidenceLinker
from .store import LegacyEvidenceRecord, LegacyEvidenceStore, LegacyPromotionError

__all__ = [
    "ALLOWLIST_FILES",
    "LEGACY_PERIOD_END_EXCLUSIVE",
    "LEGACY_PERIOD_START",
    "SOURCE_PATH",
    "SOURCE_SYSTEM",
    "LegacyCritiqueHints",
    "LegacyEvidenceBuilder",
    "LegacyEvidenceIngester",
    "LegacyEvidenceRecord",
    "LegacyEvidenceStore",
    "LegacyHypothesisIndex",
    "LegacyIngestError",
    "LegacyPromotionError",
    "LegacyShadowLink",
    "ShadowEvidenceLinker",
    "sha256_file",
    "sha256_zip",
]
