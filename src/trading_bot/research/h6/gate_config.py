"""P18 — discovery gates as immutable config, extracted from frozen spec.

No economic CLI overrides allowed.
"""

from __future__ import annotations

from dataclasses import dataclass

# V4 repair (V3-AUTH-001): these were three more stale V1 literals. They now resolve
# from the single versioned runtime authority binding and are UNBOUND while unbound.
def __getattr__(name: str):
    from trading_bot.research.h6 import runtime_authority as _ra

    if name == "SPEC_SHA256":
        return _ra.spec_sha256_or_unbound()
    if name == "MANIFEST_SHA256":
        return _ra.manifest_sha256_or_unbound()
    if name == "DATASET_SHA256":
        return _ra.dataset_sha256_or_unbound()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
