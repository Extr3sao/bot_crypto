"""P17 — H6_RESULT schema preparation only.

No real H6 result file is generated in this checkpoint.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from trading_bot.research.h6.contracts import DATASET_SHA256, SPEC_SHA256

# contracts.py freezes SPEC + DATASET hashes; the manifest hash is stamped at
# manifest-freeze time and is NOT frozen at this checkpoint (do not invent it).
_MANIFEST_SHA256_PLACEHOLDER = "pending"

ALLOWED_TERMINAL_RESULTS = frozenset(
    {
        "DISCOVERY_PASS",
        "DISCOVERY_FAIL",
        "INSUFFICIENT_SAMPLE",
        "EXECUTION_FAILED",
    }
)


@dataclass(frozen=True, slots=True)
class H6ResultSchema:
    """Future H6_RESULT.json structure."""

    experiment_id: int
    attempt_id: str
    spec_sha256: str
    manifest_sha256: str
    dataset_sha256: str
    N: int
    gross_expectancy: float | None
    net_expectancy: float | None
    PF: float | None
    Sharpe: float | None
    Sharpe_CI: tuple[float, float] | None
    P_Sharpe_gt_0: float | None
    permutation_p: float | None
    halves: tuple[float, float] | None
    thirds: tuple[float, float, float] | None
    walk_forward: tuple[float, float, float] | None
    cost_sensitivity: dict[int, float] | None
    orthogonality: float | None
    result: str | None

    def validate_result_value(self) -> bool:
        if self.result is None:
            return False
        return self.result in ALLOWED_TERMINAL_RESULTS

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "attempt_id": self.attempt_id,
            "spec_sha256": self.spec_sha256,
            "manifest_sha256": self.manifest_sha256,
            "dataset_sha256": self.dataset_sha256,
            "N": self.N,
            "gross_expectancy": self.gross_expectancy,
            "net_expectancy": self.net_expectancy,
            "PF": self.PF,
            "Sharpe": self.Sharpe,
            "Sharpe_CI": self.Sharpe_CI,
            "P_Sharpe_gt_0": self.P_Sharpe_gt_0,
            "permutation_p": self.permutation_p,
            "halves": self.halves,
            "thirds": self.thirds,
            "walk_forward": self.walk_forward,
            "cost_sensitivity": self.cost_sensitivity,
            "orthogonality": self.orthogonality,
            "result": self.result,
        }


def build_schema_placeholder() -> H6ResultSchema:
    return H6ResultSchema(
        experiment_id=1,
        attempt_id="pending",
        spec_sha256=SPEC_SHA256,
        manifest_sha256=_MANIFEST_SHA256_PLACEHOLDER,
        dataset_sha256=DATASET_SHA256,
        N=0,
        gross_expectancy=None,
        net_expectancy=None,
        PF=None,
        Sharpe=None,
        Sharpe_CI=None,
        P_Sharpe_gt_0=None,
        permutation_p=None,
        halves=None,
        thirds=None,
        walk_forward=None,
        cost_sensitivity=None,
        orthogonality=None,
        result=None,
    )
