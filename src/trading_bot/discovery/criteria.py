"""Pre-registered candidate freeze criteria.

Fixed BEFORE looking at discovery results (module committed prior to any
discovery run). The criteria accept discovery metrics only — there is no
parameter through which legacy evidence or locked windows can influence them.
No parameter sweep exists anywhere in the discovery package: each family runs
its committed parameter set; the grid is symbol x regime x direction only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .runner import DiscoveryRun

CRITERIA_SCHEMA_VERSION = "fresh-criteria-v1"


@dataclass(frozen=True, slots=True)
class FreezeCriteria:
    """Pre-registered thresholds. Fail-closed: defaults reject."""

    min_trades: int = 30
    min_net_expectancy_r: float = 0.05
    min_net_pf: float = 1.15
    max_regime_concentration: float = 0.90
    min_stability_halves_positive: bool = True
    require_both_halves_nonempty: bool = True

    def evaluate(self, run: DiscoveryRun) -> tuple[bool, list[str]]:
        failures: list[str] = []
        if run.trades < self.min_trades:
            failures.append(f"trades<{self.min_trades}")
        if run.net_expectancy_r < self.min_net_expectancy_r:
            failures.append("net_exp_r_below_threshold")
        if not (run.net_pf >= self.min_net_pf):
            failures.append("net_pf_below_threshold")
        if run.regime_concentration > self.max_regime_concentration:
            failures.append("regime_concentration_too_high")
        if self.require_both_halves_nonempty and (
            run.stability_halves.get("h1_net_exp_r") is None
            or run.stability_halves.get("h2_net_exp_r") is None
        ):
            failures.append("missing_stability_halves")
        if self.min_stability_halves_positive:
            h1 = run.stability_halves.get("h1_net_exp_r") or 0.0
            h2 = run.stability_halves.get("h2_net_exp_r") or 0.0
            if h1 <= 0 and h2 <= 0:
                failures.append("no_stability_across_halves")
        return (not failures, failures)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": CRITERIA_SCHEMA_VERSION,
            "min_trades": self.min_trades,
            "min_net_expectancy_r": self.min_net_expectancy_r,
            "min_net_pf": self.min_net_pf,
            "max_regime_concentration": self.max_regime_concentration,
            "min_stability_halves_positive": self.min_stability_halves_positive,
            "require_both_halves_nonempty": self.require_both_halves_nonempty,
        }


def preregistered_criteria() -> FreezeCriteria:
    """The single sanctioned criteria instance (no variants allowed)."""
    return FreezeCriteria()
