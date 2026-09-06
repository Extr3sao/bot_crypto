"""FRESH-DATA-001 (R1) — prospective discovery on strictly post-legacy data.

The legacy window 2026-05-01..2026-08-18 is permanently ineligible
(CONSUMED_DEVELOPMENT, see ``trading_bot.legacy_evidence``). This package
builds a fresh public dataset with ``start >= 2026-08-19T00:00:00Z``, splits
it chronologically into DISCOVERY / CONFIRMATION / FINAL_HOLDOUT (the latter
two locked), and evaluates the current canonical strategy universe on the
DISCOVERY slice only, with realistic costs and pre-registered freeze
criteria.

Shadow/legacy separation is structural: legacy evidence may annotate context
(repeated hypotheses, known failures) but the criteria functions only accept
discovery metrics — there is no code path from legacy records to scores,
selection or promotion.
"""

from __future__ import annotations

from .criteria import CRITERIA_SCHEMA_VERSION, FreezeCriteria, preregistered_criteria
from .dataset import (
    DataQualityReport,
    DatasetFetcher,
    build_data_manifest,
    fetch_stats_of,
    sha256_candles,
)
from .registry import (
    CandidateRegistry,
    FrozenCandidate,
    RejectedHypothesis,
    registry_from_runs,
)
from .runner import (
    DiscoveryRun,
    DiscoveryRunResult,
    TradeLedger,
    TradeRecord,
    evaluate_combo,
    evaluate_combo_with_ledger,
)
from .split import SplitAccessError, SplitWindows, build_split_manifest, compute_split

__all__ = [
    "CRITERIA_SCHEMA_VERSION",
    "CandidateRegistry",
    "DataQualityReport",
    "DatasetFetcher",
    "DiscoveryRun",
    "DiscoveryRunResult",
    "FreezeCriteria",
    "FrozenCandidate",
    "RejectedHypothesis",
    "SplitAccessError",
    "SplitWindows",
    "TradeLedger",
    "TradeRecord",
    "build_data_manifest",
    "build_split_manifest",
    "compute_split",
    "evaluate_combo",
    "evaluate_combo_with_ledger",
    "fetch_stats_of",
    "preregistered_criteria",
    "registry_from_runs",
    "sha256_candles",
]
