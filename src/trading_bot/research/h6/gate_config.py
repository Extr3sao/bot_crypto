"""P18 — discovery gates as immutable config, extracted from frozen spec.

No economic CLI overrides allowed.
"""

from __future__ import annotations

from dataclasses import dataclass

SPEC_SHA256 = "f514fecf42b52d2e1c2946cac9dee94b2570d485cb236b9a6c663f46f5bbf148"
MANIFEST_SHA256 = "345334c3107860a5adcc753f5b34976d2b4df9061de34a94507d2bd8f58752dc"
DATASET_SHA256 = "16779b7d2eff0dc9e56015c444c2dbe7b67ef083e6cf1877a024a6de74098d99"


@dataclass(frozen=True, slots=True)
class H6DiscoveryGates:
    min_per_asset_trades: int
    min_pooled_trades: int
    p_sharp_gt_0_min: float
    permutation_p_max: float
    sharpe_ci_excludes_zero: bool
    cost_total_round_trip_bps: int
    cost_sensitivity_bps: tuple[int, ...]
    orthogonality_max_abs_daily_correlation: float
    h5_pnl_correlation: str
    robustness_rules: tuple[str, ...]


def frozen_h6_gates() -> H6DiscoveryGates:
    return H6DiscoveryGates(
        min_per_asset_trades=30,
        min_pooled_trades=100,
        p_sharp_gt_0_min=0.90,
        permutation_p_max=0.05,
        sharpe_ci_excludes_zero=True,
        cost_total_round_trip_bps=10,
        cost_sensitivity_bps=(0, 10, 20, 40),
        orthogonality_max_abs_daily_correlation=0.50,
        h5_pnl_correlation="NOT_EVALUABLE_FROM_PERSISTED_EVIDENCE",
        robustness_rules=("halves", "thirds", "walk_forward"),
    )


class H6FrozenParameterOverride(Exception):
    """Raised if any runtime attempt to override frozen economic params."""
