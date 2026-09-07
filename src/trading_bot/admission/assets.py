"""ADMISSION-FOUNDATION-01 — Asset admission contract (§16).

Contract only: no full AssetAdmission implementation. Fields defined for a
future AssetRegistry; the two measured candidates are recorded with honest
evidence from PARALLEL-WORK-03 Track D.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class AssetAdmissionRecord:
    """Future AssetRegistry record contract (§16)."""

    asset_id: str
    data_quality: str                 # PASS | FAIL | NOT_MEASURED
    liquidity: str
    spread: str
    slippage: str
    history_depth: str
    correlation: str
    opportunity_overlap: str
    incremental_opportunity: str      # PASS | FAIL | NOT_MEASURED
    strategy_compatibility: str
    admission_state: str              # e.g. ASSET_CANDIDATE | DEFERRED | REJECTED
    evidence: tuple[str, ...] = ()
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


XRP_RECORD = AssetAdmissionRecord(
    asset_id="XRP/USDT:USDT",
    data_quality="PASS",
    liquidity="PASS",
    spread="NOT_MEASURED",
    slippage="PROXY_MEASURED",
    history_depth="PASS (400d+)",
    correlation="PASS (max 0.66-0.71 vs BTC/ETH/SOL, 5m)",
    opportunity_overlap="HIGH (83.8% signal-time overlap)",
    incremental_opportunity="FAIL/current universe (0.0% outside occupied intervals)",
    strategy_compatibility="PASS (all 5 families fire)",
    admission_state="ASSET_CANDIDATE",
    evidence=(
        "feat/research-expansion-v1@fffd469 docs/research-expansion-v1/ASSET_CANDIDATES.md",
        "feat/edge-research-002@e831420 docs/asset-incremental-analysis/ASSET_INCREMENTAL_ANALYSIS.json",
    ),
    notes="liquidity PASS; incremental opportunity FAIL under the current strategy universe",
)

DOGE_RECORD = AssetAdmissionRecord(
    asset_id="DOGE/USDT:USDT",
    data_quality="PASS",
    liquidity="PASS",
    spread="NOT_MEASURED",
    slippage="PROXY_MEASURED",
    history_depth="PASS (400d+)",
    correlation="PASS (max 0.69-0.77 vs BTC/ETH/SOL, 5m)",
    opportunity_overlap="HIGH (80.3% signal-time overlap)",
    incremental_opportunity="FAIL/current universe (0.0% outside occupied intervals)",
    strategy_compatibility="PASS (all 5 families fire)",
    admission_state="ASSET_CANDIDATE",
    evidence=(
        "feat/research-expansion-v1@fffd469 docs/research-expansion-v1/ASSET_CANDIDATES.md",
        "feat/edge-research-002@e831420 docs/asset-incremental-analysis/ASSET_INCREMENTAL_ANALYSIS.json",
    ),
    notes="liquidity PASS; incremental opportunity FAIL under the current strategy universe",
)
