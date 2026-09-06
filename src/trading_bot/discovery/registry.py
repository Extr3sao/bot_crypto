"""Frozen candidate registry + rejected-hypotheses ledger.

After freeze, a candidate is immutable (frozen dataclass + content hash);
any modification attempt is a new object with a different hash and cannot
masquerade as the frozen one. Confirmation must verify the hash before use.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from .criteria import FreezeCriteria
from .dataset import FEE_RATE, SLIPPAGE_BPS
from .runner import DiscoveryRun


def _hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class FrozenCandidate:
    candidate_id: str
    family: str
    symbols: tuple[str, ...]
    regimes: tuple[str, ...]
    direction: str
    costs: dict[str, float]
    discovery_window: tuple[str, str]
    discovery_metrics: dict[str, Any]
    config_sha256: str
    criteria_sha256: str

    @property
    def frozen_sha256(self) -> str:
        return _hash(
            {
                "candidate_id": self.candidate_id,
                "family": self.family,
                "symbols": list(self.symbols),
                "regimes": list(self.regimes),
                "direction": self.direction,
                "costs": self.costs,
                "discovery_window": list(self.discovery_window),
                "discovery_metrics": self.discovery_metrics,
                "config_sha256": self.config_sha256,
                "criteria_sha256": self.criteria_sha256,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "family": self.family,
            "symbols": list(self.symbols),
            "regimes": list(self.regimes),
            "direction": self.direction,
            "costs": self.costs,
            "discovery_window": list(self.discovery_window),
            "discovery_metrics": self.discovery_metrics,
            "config_sha256": self.config_sha256,
            "criteria_sha256": self.criteria_sha256,
            "frozen_sha256": self.frozen_sha256,
            "status": "FROZEN_AWAITING_CONFIRMATION",
        }


@dataclass(frozen=True, slots=True)
class RejectedHypothesis:
    family: str
    symbol: str
    regime: str
    direction: str
    reason: str
    legacy_context_note: str = ""
    trades: int = 0
    net_expectancy_r: float = 0.0
    net_pf: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "symbol": self.symbol,
            "regime": self.regime,
            "direction": self.direction,
            "reason": self.reason,
            "legacy_context_note": self.legacy_context_note,
            "trades": self.trades,
            "net_expectancy_r": round(self.net_expectancy_r, 6),
            "net_pf": round(self.net_pf, 6) if self.net_pf == self.net_pf else None,
        }


@dataclass(frozen=True, slots=True)
class CandidateRegistry:
    candidates: tuple[FrozenCandidate, ...]
    rejected: tuple[RejectedHypothesis, ...]
    criteria: FreezeCriteria
    registry_sha256: str = field(default="")

    def to_dict(self) -> dict[str, Any]:
        body = {
            "schema_version": "candidate-registry-v1",
            "criteria": self.criteria.to_dict(),
            "candidates": [c.to_dict() for c in self.candidates],
            "rejected": [r.to_dict() for r in self.rejected],
        }
        body["registry_sha256"] = _hash(body)
        return body


def registry_from_runs(
    runs: list[DiscoveryRun],
    criteria: FreezeCriteria,
    *,
    legacy_index: Any | None = None,
) -> CandidateRegistry:
    """Classify runs via the pre-registered criteria (single pass, no tuning).

    ``legacy_index`` is used ONLY to annotate rejected hypotheses with known
    legacy failure context (observation). It can never flip a decision: the
    accept/reject logic reads only ``run`` and ``criteria``.
    """
    candidates: list[FrozenCandidate] = []
    rejected: list[RejectedHypothesis] = []
    for run in runs:
        passed, failures = criteria.evaluate(run)
        if passed and run.net_pf != float("inf"):
            candidates.append(
                FrozenCandidate(
                    candidate_id=(
                        f"cand:{run.family}:{run.symbol}:{run.regime}:{run.direction}"
                        f":{_hash({'c': run.config_sha256, 'n': run.trades, 'e': round(run.net_expectancy_r, 6)})[:12]}"
                    ),
                    family=run.family,
                    symbols=(run.symbol,),
                    regimes=(run.regime,),
                    direction=run.direction,
                    costs={"fee_rate": FEE_RATE, "slippage_bps": SLIPPAGE_BPS},
                    discovery_window=run.window,
                    discovery_metrics=run.to_dict(),
                    config_sha256=run.config_sha256,
                    criteria_sha256=_hash(criteria.to_dict()),
                )
            )
        else:
            note = ""
            if legacy_index is not None:
                try:
                    hints = legacy_index.critique_hints(
                        legacy_family=_legacy_family_of(run.family)
                    )
                    if hints.cost_problem:
                        note = "legacy: same mechanism showed net-negative economics with fees (context only)"
                    elif hints.hypothesis_already_tested:
                        note = "legacy: mechanism previously tested on consumed window (context only)"
                except Exception:
                    note = ""
            reason = ";".join(failures) if failures else "non_finite_pf"
            rejected.append(
                RejectedHypothesis(
                    family=run.family,
                    symbol=run.symbol,
                    regime=run.regime,
                    direction=run.direction,
                    reason=reason,
                    legacy_context_note=note,
                    trades=run.trades,
                    net_expectancy_r=run.net_expectancy_r,
                    net_pf=run.net_pf if run.net_pf != float("inf") else 0.0,
                )
            )
    return CandidateRegistry(
        candidates=tuple(candidates),
        rejected=tuple(rejected),
        criteria=criteria,
    )


def _legacy_family_of(family: str) -> str | None:
    mapping = {
        "mean_reversion": "FBS",
        "trend": "TP",
        "ema_crossover": "TP",
        "breakout": "BR",
        "volatility": "LSR",
        "momentum": None,
    }
    return mapping.get(family)
